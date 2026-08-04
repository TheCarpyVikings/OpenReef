"""Beta feedback — redaction, consent, sync folding and the websocket handlers.

The module is deliberately detachable (see custom_components/openreef/beta.py),
so this suite is detachable too: delete it along with the feature.

What we pin down — the things that would be genuinely bad to get wrong:
  * redaction catches credentials, including a Home Assistant long-lived access
    token, before anything leaves the tester's machine;
  * the two consent toggles are honoured at the point the payload is built, so
    "off" means the field is empty rather than merely unrendered;
  * an "unsafe" report cannot be filed as low severity;
  * merge_sync notifies exactly once per item that closes, and unread is sticky
    until the tester actually reads it;
  * the bearer token never appears in anything the panel can see;
  * a portal that is down queues the submission instead of losing it;
  * leaving the beta drops the token immediately.

Run standalone:  python3 tests/test_beta.py
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
from openreef import beta  # noqa: E402

from _fake_ha import FakeConnection, FakeEntry, FakeHass, run  # noqa: E402


# --- helpers ----------------------------------------------------------------


def _enrolled_state(**overrides):
    state = beta._blank()
    state.update(
        {
            "enabled": True,
            "token": "secret-token-value",
            "installId": "abc123",
            "testerName": "Tester One",
        }
    )
    state.update(overrides)
    return state


def _hass_with(state=None):
    entry = FakeEntry(options={beta.OPT_KEY: state} if state is not None else {})
    hass = FakeHass(entries=[entry])
    return hass, entry


class _Poster:
    """Stand-in for beta._post. Records calls, replays scripted responses."""

    def __init__(self, *responses):
        self.calls = []
        self._responses = list(responses)

    async def __call__(self, hass, endpoint, path, payload, token):
        self.calls.append({"path": path, "payload": payload, "token": token})
        if self._responses:
            return self._responses.pop(0)
        return True, {}, ""


# --- redaction --------------------------------------------------------------


def test_redact_strips_credentials():
    ha_token = "eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJhYmNkZWZnaGlqIn0.c2lnbmF0dXJlLWhlcmU"
    blob = "\n".join(
        [
            "normal line about the return pump",
            f"Authorization: Bearer {ha_token}",
            "api_key=sk-ant-api03-abcdefghijklmnopqrstuvwxyz012345",
            "password: hunter2000000000",
            "token = ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        ]
    )
    cleaned = beta.redact(blob)
    assert "eyJhbGciOiJIUzI1NiJ9" not in cleaned, cleaned
    assert "sk-ant-api03" not in cleaned, cleaned
    assert "hunter2000000000" not in cleaned, cleaned
    assert "ghp_abcdefghij" not in cleaned, cleaned
    # Innocent content survives — over-redaction that eats the whole report
    # would be its own kind of failure.
    assert "return pump" in cleaned


def test_redact_tolerates_non_strings():
    assert beta.redact(None) == ""
    assert beta.redact(42) == ""


# --- payload assembly -------------------------------------------------------


def test_consent_off_empties_attachments():
    state = _enrolled_state(shareSupport=False, shareLogs=False)
    payload = beta.build_submission(
        state,
        {"kind": "bug", "body": "it broke"},
        support_summary="OpenReef support summary\nVersion: 0.6.9",
        log_tail="some log lines",
        ha_version="2026.7.1",
        openreef_version="0.6.9",
    )
    assert payload["supportSummary"] == ""
    assert payload["logTail"] == ""
    assert payload["body"] == "it broke"


def test_consent_on_includes_and_redacts_attachments():
    state = _enrolled_state()
    payload = beta.build_submission(
        state,
        {"kind": "bug", "body": "broke"},
        support_summary="Version: 0.6.9\napi_key=sk-live-abcdefghijklmnopqrst",
        log_tail="log",
        ha_version="2026.7.1",
        openreef_version="0.6.9",
    )
    assert "Version: 0.6.9" in payload["supportSummary"]
    assert "sk-live-abcdefghij" not in payload["supportSummary"]
    assert payload["logTail"] == "log"


def test_body_is_redacted_too():
    payload = beta.build_submission(
        _enrolled_state(),
        {"kind": "bug", "body": "my token is ghp_abcdefghijklmnopqrstuvwxyz01"},
        support_summary="",
        log_tail="",
        ha_version="",
        openreef_version="",
    )
    assert "ghp_abcdefghij" not in payload["body"]


def test_unsafe_is_always_a_blocker():
    payload = beta.build_submission(
        _enrolled_state(),
        {"kind": "unsafe", "severity": "low", "body": "heater stayed on"},
        support_summary="",
        log_tail="",
        ha_version="",
        openreef_version="",
    )
    assert payload["severity"] == "blocker"


def test_unknown_kind_and_severity_fall_back():
    payload = beta.build_submission(
        _enrolled_state(),
        {"kind": "nonsense", "severity": "catastrophic", "body": "x"},
        support_summary="",
        log_tail="",
        ha_version="",
        openreef_version="",
    )
    assert payload["kind"] == "bug"
    assert payload["severity"] == "normal"


# --- state ------------------------------------------------------------------


def test_state_survives_a_corrupt_blob():
    entry = FakeEntry(options={beta.OPT_KEY: {"enabled": "yes", "items": "not-a-list"}})
    state = beta._state(entry)
    assert state["enabled"] is False
    assert state["items"] == []


def test_state_of_missing_entry_is_blank():
    assert beta._state(None)["enabled"] is False


def test_public_state_never_leaks_the_token():
    state = _enrolled_state()
    public = beta.public_state(state)
    assert "secret-token-value" not in str(public)
    assert public["enrolled"] is True
    assert public["testerName"] == "Tester One"


# --- sync folding -----------------------------------------------------------


def test_merge_sync_flags_newly_closed_once():
    state = _enrolled_state(
        items=[{"ref": "OR-0001", "kind": "bug", "status": "new", "body": "b", "unread": False}]
    )
    payload = {"items": [{"ref": "OR-0001", "kind": "bug", "status": "actioned", "reply": "fixed"}]}

    state, closed = beta.merge_sync(state, payload)
    assert [item["ref"] for item in closed] == ["OR-0001"]
    assert state["items"][0]["unread"] is True
    assert state["items"][0]["reply"] == "fixed"

    # Same response again: already closed, so no second notification.
    state, closed_again = beta.merge_sync(state, payload)
    assert closed_again == []


def test_unread_is_sticky_until_read():
    state = _enrolled_state(
        items=[{"ref": "OR-0002", "kind": "bug", "status": "actioned", "body": "b", "unread": True}]
    )
    # A plain status refresh must not silently clear the dot.
    state, _ = beta.merge_sync(
        state, {"items": [{"ref": "OR-0002", "kind": "bug", "status": "actioned"}]}
    )
    assert state["items"][0]["unread"] is True


def test_merge_sync_preserves_the_local_body():
    """The portal only returns an excerpt; the install's own copy wins."""
    state = _enrolled_state(
        items=[{"ref": "OR-0003", "kind": "bug", "status": "new", "body": "the full text", "unread": False}]
    )
    state, _ = beta.merge_sync(
        state, {"items": [{"ref": "OR-0003", "kind": "bug", "status": "triaged", "bodyExcerpt": "the ful"}]}
    )
    assert state["items"][0]["body"] == "the full text"


def test_merge_sync_ignores_junk_rows():
    state, closed = beta.merge_sync(_enrolled_state(), {"items": ["nope", {}, {"ref": ""}]})
    assert state["items"] == []
    assert closed == []


def test_announcements_stay_read_once_read():
    state = _enrolled_state(
        announcements=[{"id": "a1", "title": "t", "body": "b", "publishedAt": "2026-01-01", "unread": False}]
    )
    state, _ = beta.merge_sync(
        state, {"announcements": [{"id": "a1", "title": "t", "body": "b", "publishedAt": "2026-01-01"}]}
    )
    assert state["announcements"][0]["unread"] is False


# --- websocket handlers -----------------------------------------------------


def test_status_reports_not_enrolled_by_default():
    hass, _entry = _hass_with()
    connection = FakeConnection()
    run(beta.websocket_beta_status(hass, connection, {"id": 1, "type": "openreef/beta_status"}))
    assert connection.results[0].payload["enrolled"] is False


def test_submit_requires_enrolment():
    hass, _entry = _hass_with()
    connection = FakeConnection()
    run(beta.websocket_beta_submit(hass, connection, {"id": 1, "kind": "bug", "body": "hi"}))
    assert connection.error_codes == ["not_enrolled"]


def test_submit_sends_and_records_the_ref():
    hass, entry = _hass_with(_enrolled_state())
    connection = FakeConnection()
    poster = _Poster((True, {"ref": "OR-0042"}, ""))
    original, beta._post = beta._post, poster
    try:
        run(
            beta.websocket_beta_submit(
                hass, connection, {"id": 1, "kind": "bug", "body": "the ATO ran twice", "tab": "awc"}
            )
        )
    finally:
        beta._post = original

    payload = connection.results[0].payload
    assert payload["sent"] is True and payload["ref"] == "OR-0042"
    assert poster.calls[0]["path"] == "/api/feedback"
    assert poster.calls[0]["payload"]["panelTab"] == "awc"
    assert beta._state(entry)["items"][0]["ref"] == "OR-0042"


def test_submit_queues_when_the_portal_is_down():
    hass, entry = _hass_with(_enrolled_state())
    connection = FakeConnection()
    poster = _Poster((False, {}, "network_error"))
    original, beta._post = beta._post, poster
    try:
        run(beta.websocket_beta_submit(hass, connection, {"id": 1, "kind": "bug", "body": "lost?"}))
    finally:
        beta._post = original

    assert connection.results[0].payload["queued"] is True
    queue = beta._state(entry)["queue"]
    assert len(queue) == 1 and queue[0]["body"] == "lost?"


def test_queue_flushes_on_the_next_sync():
    hass, entry = _hass_with(
        _enrolled_state(queue=[{"installId": "abc123", "kind": "bug", "body": "queued one"}])
    )
    poster = _Poster((True, {"ref": "OR-0007"}, ""), (True, {"items": []}, ""))
    original, beta._post = beta._post, poster
    try:
        run(beta._async_sync(hass, entry))
    finally:
        beta._post = original

    assert [call["path"] for call in poster.calls] == ["/api/feedback", "/api/sync"]
    assert beta._state(entry)["queue"] == []


def test_a_revoked_token_drops_the_queue_instead_of_retrying_forever():
    hass, entry = _hass_with(_enrolled_state(queue=[{"kind": "bug", "body": "orphan"}]))
    poster = _Poster((False, {}, "revoked"), (False, {}, "revoked"))
    original, beta._post = beta._post, poster
    try:
        run(beta._async_sync(hass, entry))
    finally:
        beta._post = original
    assert beta._state(entry)["queue"] == []


def test_sync_notifies_on_a_closed_item():
    hass, entry = _hass_with(
        _enrolled_state(items=[{"ref": "OR-0009", "kind": "bug", "status": "new", "body": "b"}])
    )
    poster = _Poster(
        (True, {"items": [{"ref": "OR-0009", "kind": "bug", "status": "actioned", "reply": "done"}]}, "")
    )
    original, beta._post = beta._post, poster
    try:
        run(beta._async_sync(hass, entry))
    finally:
        beta._post = original

    notifications = [
        call for call in hass.services.calls if call.domain == "persistent_notification"
    ]
    assert len(notifications) == 1
    assert "OR-0009" in notifications[0].data["title"]


def test_leaving_the_beta_drops_the_token_immediately():
    hass, entry = _hass_with(_enrolled_state())
    connection = FakeConnection()
    run(beta.websocket_beta_settings(hass, connection, {"id": 1, "enabled": False}))
    state = beta._state(entry)
    assert state["enabled"] is False
    assert state["token"] == ""
    assert connection.results[0].payload["enrolled"] is False


def test_consent_toggles_persist():
    hass, entry = _hass_with(_enrolled_state())
    connection = FakeConnection()
    run(beta.websocket_beta_settings(hass, connection, {"id": 1, "shareLogs": False}))
    assert beta._state(entry)["shareLogs"] is False
    assert beta._state(entry)["shareSupport"] is True


def test_mark_read_clears_one_or_all():
    hass, entry = _hass_with(
        _enrolled_state(
            items=[
                {"ref": "OR-1", "kind": "bug", "status": "actioned", "body": "a", "unread": True},
                {"ref": "OR-2", "kind": "bug", "status": "actioned", "body": "b", "unread": True},
            ]
        )
    )
    connection = FakeConnection()
    run(beta.websocket_beta_mark_read(hass, connection, {"id": 1, "ref": "OR-1"}))
    items = {item["ref"]: item["unread"] for item in beta._state(entry)["items"]}
    assert items == {"OR-1": False, "OR-2": True}

    run(beta.websocket_beta_mark_read(hass, connection, {"id": 2}))
    assert all(not item["unread"] for item in beta._state(entry)["items"])


def test_enrol_stores_the_token_and_starts_quiet_on_failure():
    hass, entry = _hass_with()
    connection = FakeConnection()
    poster = _Poster((False, {}, "invalid_code"))
    original, beta._post = beta._post, poster
    try:
        run(beta.websocket_beta_enrol(hass, connection, {"id": 1, "code": "reef-bad1"}))
    finally:
        beta._post = original
    assert connection.error_codes == ["enrol_failed"]
    assert beta._state(entry)["enabled"] is False

    connection = FakeConnection()
    poster = _Poster((True, {"token": "tok", "testerName": "Ada"}, ""))
    original, beta._post = beta._post, poster
    try:
        run(beta.websocket_beta_enrol(hass, connection, {"id": 2, "code": "reef-good"}))
    finally:
        beta._post = original

    # Codes are normalised to uppercase so a tester's phone keyboard can't
    # invalidate a perfectly good invite.
    assert poster.calls[0]["payload"]["code"] == "REEF-GOOD"
    state = beta._state(entry)
    assert state["token"] == "tok" and state["testerName"] == "Ada" and state["enabled"] is True


def test_sync_is_a_noop_when_not_enrolled():
    hass, entry = _hass_with()
    poster = _Poster()
    original, beta._post = beta._post, poster
    try:
        run(beta._async_sync(hass, entry))
    finally:
        beta._post = original
    assert poster.calls == []


def test_stop_is_safe_to_call_twice():
    hass, _entry = _hass_with()
    beta.async_stop(hass)
    beta.async_stop(hass)  # must not raise


def test_start_does_nothing_without_a_token():
    hass, entry = _hass_with(_enrolled_state(token=""))
    run(beta.async_start(hass, entry))
    assert beta.UNSUB_KEY not in hass.data.get(beta.DOMAIN, {})


# --- runner -----------------------------------------------------------------

if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  ok  {name}")
        except AssertionError as err:
            failures += 1
            print(f"FAIL  {name}: {err}")
        except Exception as err:  # noqa: BLE001
            failures += 1
            print(f"ERROR {name}: {type(err).__name__}: {err}")
    print("beta:", "all passed" if not failures else f"{failures} failure(s)")
    sys.exit(1 if failures else 0)
