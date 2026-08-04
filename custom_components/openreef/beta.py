"""OpenReef beta feedback — a deliberately detachable module.

WHY THIS FILE IS SHAPED LIKE THIS
---------------------------------
Beta feedback is scaffolding. It exists to survive the beta and then be torn
out, so every design choice here optimises for *removal*, not for elegance:

  * All state lives in its own config-entry options key (``OPT_KEY``), never in
    ``CONF_SETTINGS``. That means no ``CORE_SCHEMA_VERSION`` bump, no entry in
    ``_normalise_core_config``, and no migration to write when it goes. Deleting
    the feature leaves one orphan dict in the options blob that nothing reads.
  * Nothing in the integration imports *from* this module except the four
    tagged lines in ``__init__.py``. There are no shared helpers, no shared
    constants (the handful it needs are duplicated below on purpose), and no
    reach-ins to core config. The dependency arrow only ever points inward.
  * Every failure path is a no-op. A dead portal, a revoked token, a corrupt
    queue — none of it may ever raise into the panel, the setup path, or the
    unload path. Feedback plumbing must not be able to take a reef controller
    down.

TO REMOVE AFTER BETA
--------------------
    git rm custom_components/openreef/beta.py
    git rm custom_components/openreef/frontend/openreef-beta.js
    git rm tests/test_beta.py tests/test_panel_beta.mjs
    grep -rn "BETA-FEEDBACK" custom_components/    # delete every line it finds

That is the whole procedure. See docs/beta-feedback.md for the checklist.

TRANSPORT
---------
Testers are self-hosted Home Assistant installs behind NAT, so nothing can
reach *in*. The integration pushes feedback out over HTTPS and polls for
replies on a slow timer. See docs/beta-feedback.md for the wire contract.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Duplicated rather than imported from .const so removing this file never
# leaves a dangling constant behind. Two string literals is a cheap price for
# a clean `git rm`.
DOMAIN = "openreef"
OPT_KEY = "beta_feedback"
#: Core's config blob lives under this options key. We only ever READ it, and
#: only through total, defensive accessors — see activation_snapshot. Reading
#: core's *data* keeps the dependency arrow pointing inward; importing core's
#: *code* would not, and would make this file harder to delete.
SETTINGS_KEY = "settings"

#: Where a tester's install talks to. Overridable per-install so the portal can
#: move (or be pointed at localhost during development) without a release.
DEFAULT_ENDPOINT = "https://beta.openreef.co.uk"

#: hass.data keys — namespaced so a stale timer can never collide with core.
UNSUB_KEY = "beta_feedback_unsub"
SYNC_LOCK_KEY = "beta_feedback_syncing"

SYNC_INTERVAL = timedelta(minutes=30)
HTTP_TIMEOUT = 20

#: Caps. These bound what we send, what we store, and what a hostile or broken
#: portal can push back into a tester's config entry.
BODY_MAX = 4000
INTENT_MAX = 500
SUPPORT_MAX = 24000
LOG_TAIL_LINES = 80
LOG_TAIL_MAX = 8000
QUEUE_MAX = 20
ITEMS_MAX = 50
ANNOUNCEMENTS_MAX = 10

KINDS = ("bug", "feature", "idea", "question", "praise", "unsafe")
SEVERITIES = ("low", "normal", "high", "blocker")
STATUSES = ("new", "triaged", "planned", "in_progress", "actioned", "wontfix", "duplicate")

#: Statuses that mean Reece has finished with the item — these are what earn a
#: tester-facing notification.
CLOSED_STATUSES = ("actioned", "wontfix", "duplicate")


# --- redaction --------------------------------------------------------------
# The support summary is machine-generated from the tester's own config, so it
# should never contain a secret. "Should never" is not a security model: a
# tester can type an entity name containing an API key, or paste a token into
# the body. Everything outbound goes through here first.

_SECRET_PATTERNS = (
    # Vendor-prefixed keys (Anthropic, OpenAI, Simli, GitHub, Slack, generic).
    re.compile(r"\b(?:sk|pk|gh[pousr]|xox[baprs])[-_][A-Za-z0-9_\-]{16,}", re.I),
    # Bearer tokens and anything self-describing as a secret.
    re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(
        r"\b(?:api[_-]?key|token|secret|password|passwd|pwd)\b\s*[:=]\s*\S+",
        re.I,
    ),
    # JWTs — three base64url segments. HA long-lived access tokens are JWTs,
    # and they are the single most damaging thing a tester could paste.
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
)


def redact(text: Any) -> str:
    """Strip anything that looks like a credential.

    Deliberately over-eager: a mangled log line costs a follow-up question, a
    leaked long-lived access token costs a tester their Home Assistant.
    """
    if not isinstance(text, str):
        return ""
    out = text
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("[redacted]", out)
    return out


def _clip(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else ""
    text = text.strip()
    return text[:limit]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- state ------------------------------------------------------------------
# One dict, one options key, no schema. `_state` is total: it never raises and
# always returns something usable, so a corrupted blob degrades to "not
# enrolled" instead of breaking the panel.


def _blank() -> dict[str, Any]:
    return {
        "enabled": False,
        "endpoint": DEFAULT_ENDPOINT,
        "token": "",
        "installId": "",
        "testerName": "",
        "shareSupport": True,
        "shareLogs": True,
        "items": [],
        "announcements": [],
        "queue": [],
        "lastSyncAt": "",
        "lastError": "",
    }


def _state(entry: ConfigEntry | None) -> dict[str, Any]:
    """Current beta state for an entry, always a fresh usable dict."""
    base = _blank()
    if entry is None:
        return base
    stored = entry.options.get(OPT_KEY)
    if not isinstance(stored, dict):
        return base
    for key, default in base.items():
        value = stored.get(key, default)
        if isinstance(default, list) and not isinstance(value, list):
            value = default
        elif isinstance(default, bool) and not isinstance(value, bool):
            value = default
        elif isinstance(default, str) and not isinstance(value, str):
            value = default
        base[key] = value
    return base


def _save(hass: HomeAssistant, entry: ConfigEntry, state: dict[str, Any]) -> None:
    """Persist beta state, trimming the unbounded lists on the way out."""
    state["items"] = list(state.get("items") or [])[:ITEMS_MAX]
    state["announcements"] = list(state.get("announcements") or [])[:ANNOUNCEMENTS_MAX]
    state["queue"] = list(state.get("queue") or [])[:QUEUE_MAX]
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, OPT_KEY: state}
    )


def _entry(hass: HomeAssistant) -> ConfigEntry | None:
    """First OpenReef entry, or None. Mirrors core's `_first_entry` without
    importing it — see the module docstring on the dependency arrow."""
    try:
        entries = hass.config_entries.async_entries(DOMAIN)
    except Exception:  # noqa: BLE001 - a broken registry must not break the panel
        return None
    return entries[0] if entries else None


# --- environment ------------------------------------------------------------


def _ha_version() -> str:
    """Home Assistant's version, or "" under the dependency-free test stubs."""
    try:
        from homeassistant.const import __version__ as version  # noqa: PLC0415

        return version if isinstance(version, str) else ""
    except Exception:  # noqa: BLE001
        return ""


def _openreef_version() -> str:
    try:
        from .const import INTEGRATION_VERSION  # noqa: PLC0415

        return INTEGRATION_VERSION if isinstance(INTEGRATION_VERSION, str) else ""
    except Exception:  # noqa: BLE001
        return ""


def _read_log_tail(path: str) -> str:
    """Blocking read of the OpenReef-relevant tail of home-assistant.log.

    Runs in an executor. Filtered to lines mentioning openreef so a tester
    never ships their whole log (which would carry every other integration's
    business, and quite possibly their credentials).
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError:
        return ""
    hits = [line.rstrip() for line in lines if "openreef" in line.lower()]
    return "\n".join(hits[-LOG_TAIL_LINES:])[-LOG_TAIL_MAX:]


async def _async_log_tail(hass: HomeAssistant) -> str:
    try:
        path = hass.config.path("home-assistant.log")
        raw = await hass.async_add_executor_job(_read_log_tail, path)
    except Exception:  # noqa: BLE001 - never let diagnostics collection raise
        return ""
    return redact(raw)


# --- transport --------------------------------------------------------------
# `_http` is the seam tests monkeypatch; the aiohttp import is lazy so the
# dependency-free CI never loads it (same arrangement guardian uses).


def _http(hass: HomeAssistant):
    """Shared aiohttp session behind a seam tests replace."""
    from homeassistant.helpers.aiohttp_client import (  # noqa: PLC0415
        async_get_clientsession,
    )

    return async_get_clientsession(hass)


async def _post(
    hass: HomeAssistant, endpoint: str, path: str, payload: dict[str, Any], token: str
) -> tuple[bool, dict[str, Any], str]:
    """POST JSON to the portal. Returns (ok, data, error) and never raises."""
    import aiohttp  # noqa: PLC0415 - lazy so the dependency-free CI never loads it

    url = f"{endpoint.rstrip('/')}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        session = _http(hass)
        async with session.post(
            url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT),
        ) as response:
            try:
                data = await response.json()
            except Exception:  # noqa: BLE001 - HTML error page, empty body, etc.
                data = {}
            if response.status >= 400:
                error = str(data.get("error") or f"http_{response.status}")
                return False, data if isinstance(data, dict) else {}, error
            return True, data if isinstance(data, dict) else {}, ""
    except Exception as err:  # noqa: BLE001 - offline is the expected case
        return False, {}, str(err) or "network_error"


# --- payload assembly -------------------------------------------------------


def build_submission(
    state: dict[str, Any],
    msg: dict[str, Any],
    *,
    support_summary: str,
    log_tail: str,
    ha_version: str,
    openreef_version: str,
) -> dict[str, Any]:
    """Assemble one outbound feedback payload.

    Pure: no hass, no I/O, no clock beyond the caller's. Split out from the
    handler so the redaction and consent rules are directly testable — the
    two things here that would be genuinely bad to get wrong.
    """
    kind = msg.get("kind")
    kind = kind if kind in KINDS else "bug"
    severity = msg.get("severity")
    severity = severity if severity in SEVERITIES else "normal"
    # "Something unsafe happened" is never a low-priority item, whatever the
    # dropdown said. The portal pages on blocker.
    if kind == "unsafe":
        severity = "blocker"

    return {
        "installId": state.get("installId") or "",
        "kind": kind,
        "severity": severity,
        "body": redact(_clip(msg.get("body"), BODY_MAX)),
        "intent": redact(_clip(msg.get("intent"), INTENT_MAX)),
        "panelTab": _clip(msg.get("tab"), 64),
        "userAgent": _clip(msg.get("userAgent"), 512),
        "openreefVersion": openreef_version,
        "haVersion": ha_version,
        # Consent is enforced here, at the point of assembly, rather than at
        # the call site — so there is exactly one place to audit.
        "supportSummary": (
            redact(_clip(support_summary, SUPPORT_MAX))
            if state.get("shareSupport")
            else ""
        ),
        "logTail": log_tail if state.get("shareLogs") else "",
        "clientAt": _now(),
    }


def activation_snapshot(settings: Any) -> dict[str, Any]:
    """Whether this install actually *works*, read from core's persisted config.

    The problem this solves: feedback volume only ever measures testers who are
    already succeeding. Someone who installed OpenReef, couldn't map their
    probes and quietly gave up looks identical to someone who is perfectly
    happy — both send nothing. This rides along on the 30-minute sync, so a
    tester who never types a word still tells us whether they got there.

    Every read is defensive and every failure degrades to "unknown" rather than
    raising: this is diagnostics about diagnostics, and it must never be the
    reason a sync fails.

    Note `trustStatus` is only recomputed when the panel is opened, so it can
    be stale — `trustCheckedAt` travels with it so the portal can say so
    instead of quietly implying the reading is fresh.
    """
    blank = {
        "setupComplete": False,
        "trustStatus": "unknown",
        "trustCheckedAt": "",
        "sensorsEnabled": 0,
        "sensorsMapped": 0,
        "equipmentMapped": 0,
        "equipmentArmed": 0,
    }
    if not isinstance(settings, dict):
        return blank

    try:
        display = settings.get("display")
        blank["setupComplete"] = bool(
            display.get("setupComplete") if isinstance(display, dict) else False
        )

        trust = settings.get("trustCheck")
        if isinstance(trust, dict):
            status = trust.get("lastStatus")
            blank["trustStatus"] = (
                status if status in ("ok", "warning", "critical", "unknown") else "unknown"
            )
            blank["trustCheckedAt"] = _clip(trust.get("lastRun"), 40)

        sensors = settings.get("sensors")
        for sensor in (sensors.values() if isinstance(sensors, dict) else []):
            if not isinstance(sensor, dict) or not sensor.get("enabled"):
                continue
            blank["sensorsEnabled"] += 1
            if sensor.get("entity_id"):
                blank["sensorsMapped"] += 1

        equipment = settings.get("equipment")
        for item in (equipment.values() if isinstance(equipment, dict) else []):
            if not isinstance(item, dict):
                continue
            if item.get("switch_entity_id"):
                blank["equipmentMapped"] += 1
            if item.get("armed"):
                blank["equipmentArmed"] += 1
    except Exception:  # noqa: BLE001 - a weird config must not break the sync
        _LOGGER.debug("beta: activation snapshot failed", exc_info=True)

    return blank


def merge_sync(state: dict[str, Any], data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fold a portal sync response into local state.

    Returns (new_state, newly_closed) where `newly_closed` is the items that
    just reached a closed status and so deserve a notification. Pure, because
    "did this item just get answered?" is the logic a tester actually feels,
    and it should be pinned by tests rather than by observation.
    """
    state = dict(state)
    known = {
        item.get("ref"): item
        for item in state.get("items") or []
        if isinstance(item, dict) and item.get("ref")
    }
    newly_closed: list[dict[str, Any]] = []

    incoming = data.get("items")
    for row in incoming if isinstance(incoming, list) else []:
        if not isinstance(row, dict):
            continue
        ref = _clip(row.get("ref"), 32)
        if not ref:
            continue
        status = row.get("status")
        status = status if status in STATUSES else "new"
        previous = known.get(ref) or {}
        was_closed = previous.get("status") in CLOSED_STATUSES
        item = {
            "ref": ref,
            "kind": row.get("kind") if row.get("kind") in KINDS else "bug",
            "status": status,
            "body": _clip(previous.get("body") or row.get("bodyExcerpt"), 400),
            "reply": _clip(row.get("reply"), 2000),
            "createdAt": _clip(previous.get("createdAt") or row.get("createdAt"), 40),
            "repliedAt": _clip(row.get("repliedAt"), 40),
            # Sticky: an item stays unread until the tester actually opens it,
            # so a status change while the panel is closed is never missed.
            "unread": bool(previous.get("unread")) or (status in CLOSED_STATUSES and not was_closed),
        }
        known[ref] = item
        if status in CLOSED_STATUSES and not was_closed:
            newly_closed.append(item)

    state["items"] = sorted(
        known.values(), key=lambda item: item.get("createdAt") or "", reverse=True
    )[:ITEMS_MAX]

    notes = data.get("announcements")
    if isinstance(notes, list):
        seen = {
            note.get("id")
            for note in state.get("announcements") or []
            if isinstance(note, dict)
        }
        merged = [
            {
                "id": _clip(note.get("id"), 64),
                "title": _clip(note.get("title"), 200),
                "body": _clip(note.get("body"), 2000),
                "publishedAt": _clip(note.get("publishedAt"), 40),
                "unread": note.get("id") not in seen,
            }
            for note in notes
            if isinstance(note, dict) and note.get("id")
        ]
        by_id = {note["id"]: note for note in merged}
        for note in state.get("announcements") or []:
            if isinstance(note, dict) and note.get("id") in by_id and not note.get("unread"):
                by_id[note["id"]]["unread"] = False
        state["announcements"] = sorted(
            by_id.values(), key=lambda note: note.get("publishedAt") or "", reverse=True
        )[:ANNOUNCEMENTS_MAX]

    state["lastSyncAt"] = _now()
    state["lastError"] = ""
    return state, newly_closed


def public_state(state: dict[str, Any]) -> dict[str, Any]:
    """The panel's view. Never carries the bearer token."""
    items = [item for item in state.get("items") or [] if isinstance(item, dict)]
    notes = [note for note in state.get("announcements") or [] if isinstance(note, dict)]
    return {
        "enabled": bool(state.get("enabled")),
        "enrolled": bool(state.get("token")),
        "endpoint": state.get("endpoint") or DEFAULT_ENDPOINT,
        "testerName": state.get("testerName") or "",
        "shareSupport": bool(state.get("shareSupport")),
        "shareLogs": bool(state.get("shareLogs")),
        "items": items,
        "announcements": notes,
        "queued": len(state.get("queue") or []),
        "lastSyncAt": state.get("lastSyncAt") or "",
        "lastError": state.get("lastError") or "",
        "unread": sum(1 for item in items if item.get("unread"))
        + sum(1 for note in notes if note.get("unread")),
        "version": _openreef_version(),
    }


# --- notification -----------------------------------------------------------


async def _async_notify(hass: HomeAssistant, items: list[dict[str, Any]]) -> None:
    """Tell the tester their feedback got answered.

    Persistent notification only. Deliberately NOT the mobile push channel:
    that one is reserved for "your heater is stuck on", and diluting it with
    product chatter is how people learn to swipe reef alerts away.
    """
    if not items:
        return
    if len(items) == 1:
        item = items[0]
        verb = "actioned" if item.get("status") == "actioned" else "closed"
        title = f"Reece {verb} your feedback ({item.get('ref')})"
        message = item.get("reply") or "Open the OpenReef panel to read the update."
    else:
        title = f"Reece replied to {len(items)} pieces of your feedback"
        message = ", ".join(str(item.get("ref")) for item in items)
    try:
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "notification_id": "openreef_beta_feedback",
                "title": title,
                "message": message,
            },
            blocking=False,
        )
    except Exception:  # noqa: BLE001 - a failed toast is not worth an error
        _LOGGER.debug("beta: persistent notification failed", exc_info=True)


# --- sync -------------------------------------------------------------------


async def _async_sync(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Flush the offline queue, then pull status changes. Never raises."""
    state = _state(entry)
    if not state.get("enabled") or not state.get("token"):
        return state
    if hass.data.setdefault(DOMAIN, {}).get(SYNC_LOCK_KEY):
        return state
    hass.data[DOMAIN][SYNC_LOCK_KEY] = True
    try:
        endpoint = state.get("endpoint") or DEFAULT_ENDPOINT
        token = state.get("token") or ""

        # Flush first: a tester who wrote feedback offline should see it land
        # before we tell them anything about what Reece has been doing.
        remaining: list[dict[str, Any]] = []
        for queued in list(state.get("queue") or []):
            ok, _data, error = await _post(hass, endpoint, "/api/feedback", queued, token)
            if not ok:
                # Auth failures are permanent — retrying a revoked token
                # forever just burns a request every 30 minutes.
                if error in ("invalid_token", "revoked"):
                    continue
                remaining.append(queued)
        state["queue"] = remaining

        ok, data, error = await _post(
            hass,
            endpoint,
            "/api/sync",
            {
                "installId": state.get("installId") or "",
                "since": state.get("lastSyncAt") or "",
                # Rides along on a request that already happens. A tester who
                # never sends feedback still reports whether they got set up.
                "activation": activation_snapshot(entry.options.get(SETTINGS_KEY)),
                "openreefVersion": _openreef_version(),
                "haVersion": _ha_version(),
            },
            token,
        )
        if not ok:
            state["lastError"] = error
            _save(hass, entry, state)
            return state

        state, newly_closed = merge_sync(state, data)
        _save(hass, entry, state)
        await _async_notify(hass, newly_closed)
        return state
    except Exception:  # noqa: BLE001 - a background timer must never surface
        _LOGGER.debug("beta: sync failed", exc_info=True)
        return _state(entry)
    finally:
        hass.data.setdefault(DOMAIN, {})[SYNC_LOCK_KEY] = False


# --- lifecycle --------------------------------------------------------------


async def async_start(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Start the slow poll. Called from async_setup_entry; safe to call twice."""
    async_stop(hass)
    state = _state(entry)
    if not state.get("enabled") or not state.get("token"):
        return

    from homeassistant.helpers.event import async_track_time_interval  # noqa: PLC0415

    async def _tick(_now: Any) -> None:
        await _async_sync(hass, entry)

    hass.data.setdefault(DOMAIN, {})[UNSUB_KEY] = async_track_time_interval(
        hass, _tick, SYNC_INTERVAL
    )


def async_stop(hass: HomeAssistant) -> None:
    """Cancel the poll. Called from async_unload_entry; safe to call twice."""
    unsub = hass.data.setdefault(DOMAIN, {}).pop(UNSUB_KEY, None)
    if unsub is not None:
        try:
            unsub()
        except Exception:  # noqa: BLE001 - teardown must never raise
            _LOGGER.debug("beta: unsubscribe failed", exc_info=True)


# --- websocket API ----------------------------------------------------------


@websocket_api.websocket_command({vol.Required("type"): "openreef/beta_status"})
@websocket_api.async_response
async def websocket_beta_status(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Current beta state for the panel."""
    connection.send_result(msg["id"], public_state(_state(_entry(hass))))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/beta_enrol",
        vol.Required("code"): str,
        vol.Optional("endpoint"): str,
        vol.Optional("accept"): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_beta_enrol(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Redeem an invite code and switch beta feedback on."""
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return

    state = _state(entry)
    endpoint = _clip(msg.get("endpoint"), 200) or state.get("endpoint") or DEFAULT_ENDPOINT
    # The install id is ours, generated once and reused, so Reece can tell
    # "same tester, new report" from "two testers" without us sending anything
    # that identifies the machine.
    install_id = state.get("installId") or uuid.uuid4().hex

    ok, data, error = await _post(
        hass,
        endpoint,
        "/api/enrol",
        {
            "code": _clip(msg.get("code"), 64).upper(),
            "installId": install_id,
            "openreefVersion": _openreef_version(),
            "haVersion": _ha_version(),
            # The panel only sends accept=True after the tester ticks the box
            # next to the agreement/privacy links. The portal refuses to enrol
            # without it and stamps which version was accepted.
            "agreementAccepted": bool(msg.get("accept")),
        },
        "",
    )
    if not ok:
        connection.send_error(msg["id"], "enrol_failed", error)
        return

    state.update(
        {
            "enabled": True,
            "endpoint": endpoint,
            "installId": install_id,
            "token": _clip(data.get("token"), 200),
            "testerName": _clip(data.get("testerName"), 120),
            "lastError": "",
        }
    )
    _save(hass, entry, state)
    await async_start(hass, entry)
    connection.send_result(msg["id"], public_state(_state(entry)))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/beta_settings",
        vol.Optional("enabled"): bool,
        vol.Optional("shareSupport"): bool,
        vol.Optional("shareLogs"): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_beta_settings(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Toggle participation and the two consent switches.

    Turning `enabled` off is a full local opt-out: the poll stops and the token
    is dropped, so the install goes quiet immediately rather than "quiet until
    someone notices". Re-enrolling needs the code again, which is the honest
    behaviour — leaving a live token on a disabled install would be a lie.
    """
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return

    state = _state(entry)
    for key in ("enabled", "shareSupport", "shareLogs"):
        if key in msg:
            state[key] = bool(msg[key])
    if not state["enabled"]:
        state["token"] = ""
        state["queue"] = []
    _save(hass, entry, state)

    if state["enabled"]:
        await async_start(hass, entry)
    else:
        async_stop(hass)
    connection.send_result(msg["id"], public_state(_state(entry)))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/beta_submit",
        vol.Required("kind"): str,
        vol.Required("body"): str,
        vol.Optional("severity"): str,
        vol.Optional("intent"): str,
        vol.Optional("tab"): str,
        vol.Optional("userAgent"): str,
        vol.Optional("support"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_beta_submit(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Send one piece of feedback, queueing it locally if the portal is away."""
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return

    state = _state(entry)
    if not state.get("enabled") or not state.get("token"):
        connection.send_error(msg["id"], "not_enrolled", "Enter your invite code first")
        return
    if not _clip(msg.get("body"), BODY_MAX):
        connection.send_error(msg["id"], "empty", "Say something first")
        return

    payload = build_submission(
        state,
        msg,
        support_summary=msg.get("support") or "",
        log_tail=await _async_log_tail(hass) if state.get("shareLogs") else "",
        ha_version=_ha_version(),
        openreef_version=_openreef_version(),
    )

    ok, data, error = await _post(
        hass,
        state.get("endpoint") or DEFAULT_ENDPOINT,
        "/api/feedback",
        payload,
        state.get("token") or "",
    )
    if ok:
        ref = _clip(data.get("ref"), 32)
        state["items"] = [
            {
                "ref": ref,
                "kind": payload["kind"],
                "status": "new",
                "body": payload["body"][:400],
                "reply": "",
                "createdAt": _now(),
                "repliedAt": "",
                "unread": False,
            },
            *(state.get("items") or []),
        ]
        state["lastError"] = ""
        _save(hass, entry, state)
        connection.send_result(msg["id"], {"sent": True, "ref": ref, "state": public_state(_state(entry))})
        return

    # Offline, or the portal is down. Keep it — losing a tester's bug report
    # because Reece's box was rebooting is the one failure they'd never forgive.
    state["queue"] = [*(state.get("queue") or []), payload][-QUEUE_MAX:]
    state["lastError"] = error
    _save(hass, entry, state)
    connection.send_result(
        msg["id"], {"sent": False, "queued": True, "error": error, "state": public_state(_state(entry))}
    )


@websocket_api.websocket_command({vol.Required("type"): "openreef/beta_sync"})
@websocket_api.async_response
async def websocket_beta_sync(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Sync on demand — the panel calls this when the tester opens the modal."""
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    connection.send_result(msg["id"], public_state(await _async_sync(hass, entry)))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/beta_mark_read",
        vol.Optional("ref"): str,
    }
)
@websocket_api.async_response
async def websocket_beta_mark_read(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Clear the unread dot — for one item, or all of them when ref is absent."""
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return

    state = _state(entry)
    ref = _clip(msg.get("ref"), 32)
    for item in state.get("items") or []:
        if isinstance(item, dict) and (not ref or item.get("ref") == ref):
            item["unread"] = False
    for note in state.get("announcements") or []:
        if isinstance(note, dict) and not ref:
            note["unread"] = False
    _save(hass, entry, state)
    connection.send_result(msg["id"], public_state(_state(entry)))


def async_register_ws(hass: HomeAssistant) -> None:
    """Register every beta websocket command. One call site in async_setup."""
    for handler in (
        websocket_beta_status,
        websocket_beta_enrol,
        websocket_beta_settings,
        websocket_beta_submit,
        websocket_beta_sync,
        websocket_beta_mark_read,
    ):
        websocket_api.async_register_command(hass, handler)
