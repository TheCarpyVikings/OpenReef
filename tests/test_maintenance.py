"""Maintenance Tasks — the record_task_completion service handler.

The due/overdue logic + UI are frontend; the one backend runtime path is the HA
service that logs a completion (so a physical button/automation can mark a task
done). Tested through the real handler with HA stubbed (`_ha_stubs`) + faked
(`_fake_ha`). (Config seeding/normalisation is covered in test_config_migration.)

Run standalone:  python3 tests/test_maintenance.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
import openreef as integration  # noqa: E402

from _fake_ha import FakeEntry, FakeHass, run  # noqa: E402

CONF_SETTINGS = integration.CONF_SETTINGS
record = integration._handle_record_task_completion


def _entry():
    cfg = {
        "maintenance": {
            "seeded": True,
            "tasks": {"water_change": {"label": "Water change", "cadenceDays": 7, "enabled": True}},
            "completions": {},
        }
    }
    return FakeEntry(options={CONF_SETTINGS: cfg})


def _call(data):
    return SimpleNamespace(data=data)


def _saved(entry):
    return entry.options[CONF_SETTINGS]["maintenance"]


def test_record_completion_appends_with_notes():
    entry = _entry()
    hass = FakeHass(entries=[entry])
    run(record(hass, _call({"task_id": "water_change", "notes": "60L WC, corals happy"})))
    completions = _saved(entry)["completions"]["water_change"]
    assert len(completions) == 1
    assert completions[0]["notes"] == "60L WC, corals happy"
    assert completions[0]["timestamp"]  # stamped


def test_record_completion_logs_activity():
    entry = _entry()
    hass = FakeHass(entries=[entry])
    run(record(hass, _call({"task_id": "water_change"})))
    activity = entry.options[CONF_SETTINGS].get("activity", [])
    assert any("Water change" in item.get("message", "") for item in activity)


def test_record_completion_unknown_task_raises():
    entry = _entry()
    hass = FakeHass(entries=[entry])
    raised = False
    try:
        run(record(hass, _call({"task_id": "does_not_exist"})))
    except Exception:  # noqa: BLE001 - ServiceValidationError (stubbed as Exception)
        raised = True
    assert raised, "an unknown task_id must be rejected"
    assert _saved(entry)["completions"] == {}  # nothing logged


def test_record_completion_not_configured_raises():
    raised = False
    try:
        run(record(FakeHass(entries=[]), _call({"task_id": "water_change"})))
    except Exception:  # noqa: BLE001 - HomeAssistantError (stubbed)
        raised = True
    assert raised


def test_record_completion_stores_volume():
    entry = _entry()
    hass = FakeHass(entries=[entry])
    run(record(hass, _call({"task_id": "water_change", "volume": 20, "volume_unit": "L"})))
    completion = _saved(entry)["completions"]["water_change"][0]
    assert completion["volume"] == 20.0
    assert completion["volumeUnit"] == "L"


# --- V2: backend due evaluator (mirrors the panel's _maintenanceDueState) ----

NOW = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)  # a Thursday
due = integration._maintenance_due_items


def _cfg(tasks, completions=None, reminders=None, enabled=True):
    return {
        "maintenance": {
            "seeded": True,
            "enabled": enabled,
            "tasks": tasks,
            "completions": completions or {},
            "reminders": reminders
            if reminders is not None
            else {"enabled": True, "time": "09:00", "notifyTarget": "", "persistent": True},
        }
    }


def _interval(**over):
    base = {"label": "X", "cadenceDays": 7, "criticalAfterDays": 14, "enabled": True,
            "scheduleMode": "interval", "notify": True}
    base.update(over)
    return base


def _ago(days):
    return (NOW - timedelta(days=days)).isoformat()


def test_due_interval_due_and_overdue():
    assert due(_cfg({"t": _interval()}, {"t": [{"timestamp": _ago(10)}]}), NOW)[0]["severity"] == "warning"
    assert due(_cfg({"t": _interval()}, {"t": [{"timestamp": _ago(20)}]}), NOW)[0]["severity"] == "critical"
    # inside cadence -> not due
    assert due(_cfg({"t": _interval()}, {"t": [{"timestamp": _ago(3)}]}), NOW) == []


def test_due_snooze_suppresses():
    task = _interval(snoozedUntil=(NOW + timedelta(days=2)).isoformat())
    assert due(_cfg({"t": task}, {"t": [{"timestamp": _ago(20)}]}), NOW) == []


def test_due_skip_does_not_count_as_done():
    # A skipped entry yesterday must NOT satisfy the cadence; the real done was 10d ago.
    comps = {"t": [{"timestamp": _ago(1), "skipped": True}, {"timestamp": _ago(10)}]}
    assert due(_cfg({"t": _interval()}, comps), NOW)[0]["severity"] == "warning"


def test_due_fixed_day():
    # Every Saturday (Mon=0..Sun=6 -> Sat=5). Last Saturday before Thu 2026-06-04 is 2026-05-30.
    fixed = _interval(scheduleMode="fixed", scheduleDays=[5], scheduleMonthDays=[])
    # done the Friday before -> due for last Saturday
    before = {"t": [{"timestamp": datetime(2026, 5, 29, 9, 0, tzinfo=timezone.utc).isoformat()}]}
    assert due(_cfg({"t": fixed}, before), NOW)[0]["severity"] == "warning"
    # done on the Saturday -> ok (not due)
    on = {"t": [{"timestamp": datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc).isoformat()}]}
    assert due(_cfg({"t": fixed}, on), NOW) == []
    # missed two Saturdays -> overdue
    old = {"t": [{"timestamp": datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc).isoformat()}]}
    assert due(_cfg({"t": fixed}, old), NOW)[0]["severity"] == "critical"


def test_due_disabled_task_excluded():
    assert due(_cfg({"t": _interval(enabled=False)}, {"t": [{"timestamp": _ago(99)}]}), NOW) == []


# --- V2: the daily reminder tick (persistent notification + phone push) ------

fire = integration._async_fire_maintenance_reminder


def test_reminder_fires_persistent_and_push():
    cfg = _cfg(
        {"wc": _interval(label="Water change")},
        {"wc": [{"timestamp": _ago(20)}]},
        reminders={"enabled": True, "time": "09:00", "notifyTarget": "mobile_app_pixel", "persistent": True},
    )
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(entries=[entry])
    run(fire(hass, entry, NOW))
    calls = [(c.domain, c.service) for c in hass.services.calls]
    assert ("persistent_notification", "create") in calls
    assert ("notify", "mobile_app_pixel") in calls


def test_reminder_silent_when_disabled():
    cfg = _cfg(
        {"wc": _interval(label="Water change")},
        {"wc": [{"timestamp": _ago(20)}]},
        reminders={"enabled": False, "time": "09:00", "notifyTarget": "mobile_app_pixel", "persistent": True},
    )
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(entries=[entry])
    run(fire(hass, entry, NOW))
    assert not any(c.domain == "notify" for c in hass.services.calls)
    assert not any(c.domain == "persistent_notification" and c.service == "create" for c in hass.services.calls)


def test_reminder_no_push_without_target():
    cfg = _cfg(
        {"wc": _interval(label="Water change")},
        {"wc": [{"timestamp": _ago(20)}]},
        reminders={"enabled": True, "time": "09:00", "notifyTarget": "", "persistent": True},
    )
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(entries=[entry])
    run(fire(hass, entry, NOW))
    # persistent notification still created, but no phone push when no target set
    assert any(c.domain == "persistent_notification" and c.service == "create" for c in hass.services.calls)
    assert not any(c.domain == "notify" for c in hass.services.calls)


# --- tiny standalone runner -------------------------------------------------

def _main() -> int:
    tests = sorted(
        (name, obj) for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    )
    passed = 0
    failed = []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{passed}/{len(tests)} passed", "" if not failed else f"— FAILED: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
