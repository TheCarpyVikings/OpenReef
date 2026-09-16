"""Reef Report, Stage A (0.7.197): the two ledgers and their guards.

The score log is panel-stamped (report_score_stamp) and the event ledger is
mirrored at the activity choke point; both are server-owned and must ride
through a stale whole-config save untouched.

Run standalone:  python3 tests/test_reports.py
"""

from __future__ import annotations

import os
import sys
from copy import deepcopy as _deepcopy
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
import openreef as integration  # noqa: E402
from openreef import dosing, nps  # noqa: E402

from _fake_ha import FakeConnection, FakeEntry, FakeHass, run  # noqa: E402

CONF_SETTINGS = integration.CONF_SETTINGS

NOW = datetime(2026, 9, 16, 9, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.isoformat()


def test_normalise_reports_coerces_garbage_and_keeps_one_score_per_day():
    cfg = integration._normalise_core_config({"reports": {
        "weekStart": "6", "scoreLog": [
            {"date": "2026-09-15", "at": _iso(NOW - timedelta(days=1)), "total": 71.6, "parts": {"chemistry": 80, "life": "x"}},
            {"date": "2026-09-15", "at": _iso(NOW - timedelta(days=1, hours=5)), "total": 40},
            {"date": "nope", "total": 50}, "junk", {"date": "2026-09-16", "total": 999},
        ],
        "events": [{"at": _iso(NOW), "message": "x" * 300, "type": "control"}, {"at": "bad"}, 7],
    }})
    reports = cfg["reports"]
    assert reports["weekStart"] == 6
    assert [r["date"] for r in reports["scoreLog"]] == ["2026-09-16", "2026-09-15"]
    day = reports["scoreLog"][1]
    assert day["total"] == 72 and day["parts"] == {"chemistry": 80}, "the newest stamp of the day wins, parts coerced"
    assert reports["scoreLog"][0]["total"] == 100, "clamped"
    assert len(reports["events"]) == 1 and len(reports["events"][0]["message"]) == 200
    empty = integration._normalise_core_config({"reports": "garbage"})["reports"]
    assert empty == {"weekStart": 0, "scoreLog": [], "events": []}


def test_activity_choke_point_mirrors_events_but_not_plain_info():
    cfg = integration._normalise_core_config({})
    integration._append_activity(cfg, "Heartbeat OK", "info")
    integration._append_activity(cfg, "Return pump switched off", "control")
    integration._append_activity(cfg, "Alk drifting", "warning")
    integration._append_activity(cfg, "Feed mode applied", "info", kind="mode")
    events = cfg["reports"]["events"]
    assert [e["message"] for e in events] == ["Feed mode applied", "Alk drifting", "Return pump switched off"]
    assert events[0]["kind"] == "mode" and "kind" not in events[1]
    assert len(cfg["activity"]) == 4, "the activity feed is untouched"
    for i in range(integration.REPORT_EVENTS_MAX + 20):
        integration._append_activity(cfg, f"tick {i}", "control")
    assert len(cfg["reports"]["events"]) == integration.REPORT_EVENTS_MAX


def test_report_ledgers_survive_a_stale_save():
    stored = {"reports": {"weekStart": 0,
                          "scoreLog": [{"date": "2026-09-16", "at": _iso(NOW), "total": 78, "parts": {}}],
                          "events": [{"at": _iso(NOW), "message": "AWC finished", "type": "control"}]}}
    incoming = {"reports": {"weekStart": 3, "scoreLog": [], "events": []}}
    integration._reports_preserve_runtime(stored, incoming)
    assert incoming["reports"]["weekStart"] == 3, "the keeper's setting is the client's"
    assert incoming["reports"]["scoreLog"][0]["total"] == 78 and incoming["reports"]["events"][0]["message"] == "AWC finished"
    old_client = {"tank": {}}
    integration._reports_preserve_runtime(stored, old_client)
    assert old_client["reports"]["scoreLog"][0]["total"] == 78, "a client without the block still carries the ledgers"


def test_ws_score_stamp_keeps_the_latest_per_day_and_refuses_junk():
    entry = FakeEntry(options={CONF_SETTINGS: {}})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_report_score_stamp(hass, conn, {"id": 1, "date": "2026-09-16", "total": 71.4, "parts": {"chemistry": 88.2, "life": 100}}))
    run(integration.websocket_report_score_stamp(hass, conn, {"id": 2, "date": "2026-09-16", "total": 75, "parts": {"chemistry": 90}}))
    run(integration.websocket_report_score_stamp(hass, conn, {"id": 3, "date": "2026-09-15", "total": 60}))
    assert not conn.errors
    log = entry.options[CONF_SETTINGS]["reports"]["scoreLog"]
    assert [(r["date"], r["total"]) for r in log] == [("2026-09-16", 75), ("2026-09-15", 60)]
    assert log[0]["parts"] == {"chemistry": 90}
    assert conn.results[-1].payload["scoreLog"][0]["total"] == 60 or conn.results[-1].payload["scoreLog"][0]["date"] == "2026-09-16"
    run(integration.websocket_report_score_stamp(hass, conn, {"id": 4, "date": "16/09/2026", "total": 50}))
    run(integration.websocket_report_score_stamp(hass, conn, {"id": 5, "date": "2026-09-16", "total": 140}))
    assert [e.code for e in conn.errors] == ["invalid_date", "invalid_total"]


def test_ws_report_events_reads_a_window():
    entry = FakeEntry(options={CONF_SETTINGS: {"reports": {"events": [
        {"at": _iso(datetime.now(timezone.utc) - timedelta(days=2)), "message": "recent", "type": "control"},
        {"at": _iso(datetime.now(timezone.utc) - timedelta(days=20)), "message": "old", "type": "warning"},
    ]}}})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_report_events(hass, conn, {"id": 1}))
    assert [e["message"] for e in conn.results[-1].payload["events"]] == ["recent"]
    run(integration.websocket_report_events(hass, conn, {"id": 2, "days": 30}))
    assert [e["message"] for e in conn.results[-1].payload["events"]] == ["recent", "old"]


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok  {name}")
            except Exception as err:  # noqa: BLE001
                failures += 1
                print(f"FAIL  {name}: {type(err).__name__}: {err}")
    print(f"{len([n for n in globals() if n.startswith('test_')]) - failures} passed, {failures} failed")
    raise SystemExit(1 if failures else 0)
