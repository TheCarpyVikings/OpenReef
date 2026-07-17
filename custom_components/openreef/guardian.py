"""Guardian — Lagertha's pure engine (persona, tools, conversation folding).

Like vision.py/awc.py/spawning.py, this module is deliberately **pure,
dependency-free and side-effect-free** (stdlib only — no Home Assistant, no
anthropic/openai SDKs, no network). All orchestration — the WebSocket
commands, the Anthropic tool loop, the OpenAI STT/TTS calls, key storage —
lives in __init__.py per the repo convention, so tests/test_guardian.py runs
in the dependency-free CI.

What it does
------------
The Guardian tab hosts a live talking avatar (Lagertha) whose brain is a
Claude tool loop. This module owns everything about that loop that can be
computed without I/O:

  * ``persona_prompt()``  — the stable system prompt (persona + hard rules).
    It must stay byte-stable across turns of a session so Anthropic prompt
    caching gets a prefix hit; anything volatile (readings, due items) is
    reached through tools instead of being interpolated here.
  * ``build_tools()``     — the Anthropic tool schemas for the READ ring.
    Stage A is read-only by design: no tool in this list can change tank
    state, so a hallucinated call physically cannot dose, drain or switch
    anything. The confirm-to-act ring is Stage B.
  * ``run_tool()``        — answers a tool call from a pre-gathered context
    snapshot (plain dicts assembled by orchestration from config + entity
    states). Formatting is defensive: unknown shapes degrade to
    "unavailable", lists are capped, strings truncated — a corrupt config
    section must never take the conversation down.
  * ``fold_history()``    — validates/trims the panel-supplied transcript.
    The backend is stateless (the panel resends recent turns each call), so
    hostile or bloated payloads are clamped here before they reach the API.

Semantics that are easy to get wrong (and are covered by tests):

  * Personality only on calm states: the persona prompt encodes the standing
    OpenReef law — cheek is allowed for greetings/status chat, but anything
    alert- or safety-adjacent must be delivered straight. The Cheeky/Pro
    toggle maps to ``tone``.
  * Keys are never echoed: ``keys_status()`` reduces stored secrets to
    set/unset + a 4-char hint. Full keys leave the backend only via the
    dedicated admin-only Simli-session command (the Simli browser client
    needs the key by design).
  * History folding keeps the LAST turns, not the first — the most recent
    exchange is what the model needs; the panel owns the full transcript.
"""

from __future__ import annotations

import json
from typing import Any

# Read-ring caps: bound every list/string that can reach the model so a large
# config (years of alert history, 200 ICP rows) cannot blow the context or the
# websocket frame.
MAX_LIST_ITEMS = 12
MAX_TEXT_LEN = 400
MAX_HISTORY_TURNS = 24          # panel resends recent turns; clamp hard
MAX_TURN_CHARS = 4000

TONES = ("cheeky", "pro")
EFFORTS = ("low", "medium", "high")
TTS_FORMATS = ("mp3", "pcm", "none")


# --- keys -------------------------------------------------------------------

def key_hint(key: Any) -> str:
    """Last 4 chars of a stored secret, for "which key is this" UI hints."""
    if not isinstance(key, str) or len(key) < 8:
        return ""
    return key[-4:]


def keys_status(keys: Any) -> dict[str, Any]:
    """Reduce stored secrets to set/unset + hint. NEVER returns key material."""
    keys = keys if isinstance(keys, dict) else {}
    out: dict[str, Any] = {}
    for name in ("anthropic", "openai", "simli"):
        value = keys.get(name)
        is_set = isinstance(value, str) and len(value) >= 8
        out[name] = {"set": is_set, "hint": key_hint(value) if is_set else ""}
    face = keys.get("simliFaceId")
    out["simliFaceId"] = face if isinstance(face, str) else ""
    # Voice-only mode is a supported degradation: Simli missing must not
    # block the feature, only the live face.
    out["ready"] = out["anthropic"]["set"] and out["openai"]["set"]
    out["faceReady"] = out["ready"] and out["simli"]["set"] and bool(out["simliFaceId"])
    return out


def clean_keys(current: Any, updates: Any) -> dict[str, str]:
    """Merge a set-keys request into stored keys.

    Missing field = leave unchanged; empty string = clear. Values are
    stripped and length-capped; only known fields survive (a hostile payload
    cannot smuggle arbitrary data into the config entry).
    """
    current = current if isinstance(current, dict) else {}
    updates = updates if isinstance(updates, dict) else {}
    out: dict[str, str] = {}
    for name in ("anthropic", "openai", "simli", "simliFaceId"):
        if name in updates:
            raw = updates.get(name)
            value = raw.strip()[:256] if isinstance(raw, str) else ""
        else:
            raw = current.get(name)
            value = raw if isinstance(raw, str) else ""
        if value:
            out[name] = value
    return out


# --- persona ----------------------------------------------------------------

def persona_prompt(config: Any) -> str:
    """Stable system prompt. Only slow-changing identity facts (tank name,
    owner, profile, tone) may appear here — live data goes through tools, so
    the prompt stays byte-stable within a session for prompt-cache hits."""
    config = config if isinstance(config, dict) else {}
    tank = config.get("tank") if isinstance(config.get("tank"), dict) else {}
    guardian = config.get("guardian") if isinstance(config.get("guardian"), dict) else {}
    tank_name = tank.get("name") or "the reef tank"
    owner = tank.get("owner") or ""
    profile = tank.get("profile") or ""
    tone = guardian.get("tone") if guardian.get("tone") in TONES else "cheeky"

    lines = [
        "You are Lagertha, shield-maiden and guardian of the reef tank "
        f'"{tank_name}"' + (f", kept by {owner}" if owner else "") + ".",
        "You are the voice of OpenReef, a Home Assistant reef controller. You can "
        "read everything the controller knows through your tools; in this version "
        "you cannot change anything — if asked to dose, feed, or switch equipment, "
        "say that acting needs the keeper's hands for now and offer the reading "
        "or advice instead.",
        "",
        "Rules:",
        "- Answer from tool data, never from guesswork. If a tool reports "
        "something unavailable, say so plainly.",
        "- Replies are spoken aloud: keep them short (2-4 sentences), plain "
        "prose, no markdown, no bullet lists, no emoji.",
        "- Use metric units as reported by the tools.",
        "- You are a seasoned reef keeper: when a value is off, say what it "
        "means and the usual next step, briefly.",
        "- SAFETY VOICE: whenever you are reporting an alert, a parameter out "
        "of range, missing livestock, or anything that could harm the tank, "
        "drop all humour and personality and deliver it straight and clear.",
    ]
    if tone == "cheeky":
        lines.append(
            "- Otherwise you may show your character: dry Viking humour, warm, "
            "a little irreverent about overpriced rival controllers. Never at "
            "the expense of clarity."
        )
    else:
        lines.append("- Keep a professional, warm tone throughout.")
    if profile:
        lines.append(f"- The tank profile is: {profile}.")
    return "\n".join(lines)


# --- tools (READ ring) ------------------------------------------------------

def build_tools() -> list[dict[str, Any]]:
    """Anthropic tool schemas for the Stage A read ring. Descriptions state
    WHEN to call each tool — that measurably improves should-call rate."""
    no_args = {"type": "object", "properties": {}, "additionalProperties": False}
    return [
        {
            "name": "get_tank_status",
            "description": (
                "Current live sensor readings (temperature, pH, salinity, ...) with "
                "their safe ranges, plus tank identity and volume. Call this whenever "
                "the keeper asks how the tank is doing or about any live parameter."
            ),
            "input_schema": no_args,
        },
        {
            "name": "get_recent_readings",
            "description": (
                "Recent manual water-test results (alkalinity, calcium, magnesium and "
                "other chemistry the keeper tests by hand). Call this for questions "
                "about chemistry that has no live sensor."
            ),
            "input_schema": no_args,
        },
        {
            "name": "get_dosing_status",
            "description": (
                "Dosing system state: channels, chemicals, daily volumes and whether "
                "dosing is enabled. Call this for any dosing question."
            ),
            "input_schema": no_args,
        },
        {
            "name": "get_awc_status",
            "description": (
                "Automatic water change configuration and recent activity. Call this "
                "for water-change questions."
            ),
            "input_schema": no_args,
        },
        {
            "name": "get_maintenance_due",
            "description": (
                "Maintenance tasks currently due or overdue. Call this when asked "
                "what needs doing, or before summarising tank health."
            ),
            "input_schema": no_args,
        },
        {
            "name": "get_icp_report",
            "description": (
                "The most recent imported ICP lab test: flagged elements and core "
                "parameters. Call this for trace-element or lab-test questions."
            ),
            "input_schema": no_args,
        },
        {
            "name": "get_vision_summary",
            "description": (
                "Camera vision aggregates: when each fish species was last seen, "
                "zone visits, tank/anemone state and fish count. Call this for "
                "questions about the fish or what the camera has seen."
            ),
            "input_schema": no_args,
        },
        {
            "name": "get_recent_alerts",
            "description": (
                "Recent alert history from the controller. Call this when asked what "
                "has gone wrong lately or before summarising tank health."
            ),
            "input_schema": no_args,
        },
    ]


def _clip(value: Any, limit: int = MAX_TEXT_LEN) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    return value


def _tank_status(snapshot: dict[str, Any]) -> dict[str, Any]:
    tank = snapshot.get("tank") if isinstance(snapshot.get("tank"), dict) else {}
    sensors = snapshot.get("sensors")
    rows = []
    for row in sensors if isinstance(sensors, list) else []:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "label": _clip(row.get("label"), 64),
                "value": row.get("value"),
                "unit": _clip(row.get("unit"), 16),
                "min": row.get("min"),
                "max": row.get("max"),
                "available": bool(row.get("available")),
            }
        )
        if len(rows) >= MAX_LIST_ITEMS:
            break
    return {
        "tank": {
            "name": _clip(tank.get("name"), 64),
            "profile": _clip(tank.get("profile"), 64),
            "volumeLitres": tank.get("volumeLitres"),
        },
        "sensors": rows,
    }


def _recent_readings(snapshot: dict[str, Any]) -> dict[str, Any]:
    readings = snapshot.get("manualReadings")
    if not isinstance(readings, list) or not readings:
        return {"available": False, "note": "No manual test results recorded."}
    rows = []
    for row in readings[-MAX_LIST_ITEMS:]:
        if isinstance(row, dict):
            rows.append({k: _clip(v, 64) for k, v in list(row.items())[:8]})
    return {"available": True, "readings": rows}


def _dosing_status(snapshot: dict[str, Any]) -> dict[str, Any]:
    dosing = snapshot.get("dosing")
    if not isinstance(dosing, dict):
        return {"available": False, "note": "Dosing is not configured."}
    channels = dosing.get("channels")
    rows = []
    channel_items = (
        list(channels.items()) if isinstance(channels, dict)
        else list(enumerate(channels)) if isinstance(channels, list) else []
    )
    for key, ch in channel_items[:MAX_LIST_ITEMS]:
        if not isinstance(ch, dict):
            continue
        rows.append(
            {
                "channel": _clip(str(key), 32),
                "chemical": _clip(ch.get("chemical"), 48),
                "enabled": bool(ch.get("enabled")),
                "dailyMl": ch.get("dailyMl", ch.get("dailyVolumeMl")),
            }
        )
    return {
        "available": True,
        "enabled": bool(dosing.get("enabled")),
        "channels": rows,
    }


def _awc_status(snapshot: dict[str, Any]) -> dict[str, Any]:
    awc = snapshot.get("awc")
    if not isinstance(awc, dict):
        return {"available": False, "note": "Automatic water change is not configured."}
    schedule = awc.get("schedule") if isinstance(awc.get("schedule"), dict) else {}
    return {
        "available": True,
        "enabled": bool(awc.get("enabled")),
        "method": _clip(awc.get("method"), 32),
        "schedule": {k: _clip(v, 64) for k, v in list(schedule.items())[:10]},
        "effectiveTankLitres": snapshot.get("awcTankLitres"),
    }


def _maintenance_due(snapshot: dict[str, Any]) -> dict[str, Any]:
    due = snapshot.get("maintenanceDue")
    if not isinstance(due, list):
        return {"available": False, "note": "Maintenance reminders are not configured."}
    rows = [
        {
            "label": _clip(item.get("label"), 96),
            "severity": _clip(item.get("severity"), 16),
            "message": _clip(item.get("message"), 160),
        }
        for item in due[:MAX_LIST_ITEMS]
        if isinstance(item, dict)
    ]
    return {"available": True, "dueCount": len(rows), "due": rows}


def _icp_report(snapshot: dict[str, Any]) -> dict[str, Any]:
    reports = snapshot.get("icpReports")
    if not isinstance(reports, list) or not reports:
        return {"available": False, "note": "No ICP tests imported."}
    latest = reports[-1] if isinstance(reports[-1], dict) else {}
    values = latest.get("values")
    flagged = []
    ok_count = 0
    value_items = (
        list(values.items()) if isinstance(values, dict)
        else list(enumerate(values)) if isinstance(values, list) else []
    )
    for key, row in value_items:
        if not isinstance(row, dict):
            continue
        status = row.get("status") or row.get("flag")
        if status and str(status).lower() not in ("ok", "good", "normal", "in_range"):
            if len(flagged) < MAX_LIST_ITEMS:
                flagged.append(
                    {
                        "element": _clip(str(row.get("element", row.get("label", key))), 48),
                        "value": row.get("value"),
                        "unit": _clip(row.get("unit"), 16),
                        "status": _clip(str(status), 24),
                    }
                )
        else:
            ok_count += 1
    return {
        "available": True,
        "vendor": _clip(latest.get("vendor"), 48),
        "testedAt": _clip(str(latest.get("testedAt", latest.get("date", ""))), 32),
        "flagged": flagged,
        "inRangeCount": ok_count,
    }


def _vision_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    vision = snapshot.get("visionSummary")
    if not isinstance(vision, dict) or not vision:
        return {"available": False, "note": "Camera vision is not enabled."}
    last_seen = vision.get("lastSeen") if isinstance(vision.get("lastSeen"), dict) else {}
    return {
        "available": True,
        "lastSeen": {
            _clip(str(k), 48): v for k, v in list(last_seen.items())[:MAX_LIST_ITEMS]
        },
        "fishCount": vision.get("fishCount"),
        "tankState": _clip(vision.get("tankState"), 64),
        "anemoneState": _clip(vision.get("anemoneState"), 64),
        "zoneVisits": vision.get("zoneVisits")
        if isinstance(vision.get("zoneVisits"), dict)
        else {},
        "feeding": bool(vision.get("feeding")),
        "asOfEpoch": vision.get("asOf"),
    }


def _recent_alerts(snapshot: dict[str, Any]) -> dict[str, Any]:
    history = snapshot.get("alertHistory")
    if not isinstance(history, list):
        return {"available": False, "note": "No alert history."}
    rows = []
    for item in history[-MAX_LIST_ITEMS:]:
        if isinstance(item, dict):
            rows.append({k: _clip(v, 120) for k, v in list(item.items())[:6]})
    return {"available": True, "alerts": rows}


_TOOL_IMPL = {
    "get_tank_status": _tank_status,
    "get_recent_readings": _recent_readings,
    "get_dosing_status": _dosing_status,
    "get_awc_status": _awc_status,
    "get_maintenance_due": _maintenance_due,
    "get_icp_report": _icp_report,
    "get_vision_summary": _vision_summary,
    "get_recent_alerts": _recent_alerts,
}


def run_tool(name: str, args: Any, snapshot: Any) -> dict[str, Any]:
    """Answer one tool call from the snapshot. Never raises — a formatting
    surprise becomes an "unavailable" result the model can speak to."""
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    impl = _TOOL_IMPL.get(name)
    if impl is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return impl(snapshot)
    except Exception as exc:  # noqa: BLE001 - defensive: arbitrary config shapes
        return {"available": False, "note": f"Tool failed: {type(exc).__name__}"}


def tool_result_json(name: str, args: Any, snapshot: Any) -> str:
    """run_tool serialised for an Anthropic tool_result block."""
    return json.dumps(run_tool(name, args, snapshot), default=str)


# --- conversation folding ---------------------------------------------------

def fold_history(history: Any) -> list[dict[str, str]]:
    """Panel transcript -> clamped Anthropic messages.

    Keeps the LAST MAX_HISTORY_TURNS valid turns, coerces roles to
    user/assistant, truncates oversize turns, and guarantees the list starts
    with a user turn (the API rejects assistant-first). Consecutive same-role
    turns are allowed by the API, so no merging is needed.
    """
    out: list[dict[str, str]] = []
    for item in history if isinstance(history, list) else []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        content = content.strip()
        if not content:
            continue
        out.append({"role": role, "content": content[:MAX_TURN_CHARS]})
    out = out[-MAX_HISTORY_TURNS:]
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def sanitize_guardian_cfg(raw: Any) -> dict[str, Any]:
    """Guardian settings section (NOT the API keys — those live outside the
    exportable settings blob so config export/import can never leak them)."""
    raw = raw if isinstance(raw, dict) else {}
    tone = raw.get("tone")
    effort = raw.get("effort")
    voice = raw.get("voice")
    return {
        "enabled": bool(raw.get("enabled", True)),
        "tone": tone if tone in TONES else "cheeky",
        "effort": effort if effort in EFFORTS else "low",
        "voice": voice.strip()[:32] if isinstance(voice, str) and voice.strip() else "shimmer",
    }
