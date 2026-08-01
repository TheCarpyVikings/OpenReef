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


# --- V2.1: automatic water changes logged from AWC --------------------------
# AWC runs write a completion tagged source="awc" so the chore, the reminders and
# the water-change chart all count the water the controller actually moved. Manual
# entries carry NO source — that absence is what the panel renders differently.

log_awc = integration._maintenance_log_awc_change
AWC_SOURCE = integration.const.MAINTENANCE_SOURCE_AWC


def _awc_cfg_for_log(log_enabled=True, tasks=None, completions=None):
    return {
        "maintenance": {
            "seeded": True,
            "enabled": True,
            "logAwcChanges": log_enabled,
            "tasks": tasks if tasks is not None else {"water_change": _interval(label="Water change")},
            "completions": completions or {},
        }
    }


def test_awc_change_logs_tagged_completion():
    cfg = _awc_cfg_for_log()
    log_awc(cfg, NOW, 12.5, False, "")
    entry = cfg["maintenance"]["completions"]["water_change"][0]
    assert entry["volume"] == 12.5
    assert entry["volumeUnit"] == "L"
    assert entry["source"] == AWC_SOURCE
    assert entry["timestamp"] == NOW.isoformat()


def test_awc_same_day_runs_merge_into_one_entry():
    cfg = _awc_cfg_for_log()
    log_awc(cfg, NOW, 1.0, False, "")
    log_awc(cfg, NOW + timedelta(hours=3), 2.5, False, "")
    entries = cfg["maintenance"]["completions"]["water_change"]
    assert len(entries) == 1, "a continuous schedule must not spam one row per slice"
    assert entries[0]["volume"] == 3.5
    assert entries[0]["timestamp"] == (NOW + timedelta(hours=3)).isoformat()


def test_awc_next_day_starts_a_new_entry():
    cfg = _awc_cfg_for_log()
    log_awc(cfg, NOW, 1.0, False, "")
    log_awc(cfg, NOW + timedelta(days=1), 2.0, False, "")
    entries = cfg["maintenance"]["completions"]["water_change"]
    assert len(entries) == 2
    assert [e["volume"] for e in entries] == [2.0, 1.0]  # newest first


def test_awc_never_merges_into_a_manual_entry():
    cfg = _awc_cfg_for_log(completions={"water_change": [
        {"id": "manual", "timestamp": NOW.isoformat(), "volume": 20.0, "volumeUnit": "L", "notes": ""},
    ]})
    log_awc(cfg, NOW + timedelta(hours=1), 5.0, False, "")
    entries = cfg["maintenance"]["completions"]["water_change"]
    assert len(entries) == 2
    assert entries[1]["volume"] == 20.0 and "source" not in entries[1]  # hand-logged untouched
    assert entries[0]["source"] == AWC_SOURCE


def test_awc_partial_change_is_logged_with_reason():
    cfg = _awc_cfg_for_log()
    log_awc(cfg, NOW, 3.0, True, "leak sensor")
    entry = cfg["maintenance"]["completions"]["water_change"][0]
    assert entry["volume"] == 3.0          # the water moved, so it counts
    assert "leak sensor" in entry["notes"]


def test_awc_logging_can_be_turned_off():
    cfg = _awc_cfg_for_log(log_enabled=False)
    log_awc(cfg, NOW, 12.5, False, "")
    assert cfg["maintenance"]["completions"] == {}


def test_awc_zero_volume_and_missing_task_are_noops():
    cfg = _awc_cfg_for_log()
    log_awc(cfg, NOW, 0.0, False, "")
    assert cfg["maintenance"]["completions"] == {}
    no_task = _awc_cfg_for_log(tasks={})
    log_awc(no_task, NOW, 5.0, False, "")
    assert no_task["maintenance"]["completions"] == {}


def test_awc_falls_back_to_another_volume_logging_task():
    cfg = _awc_cfg_for_log(tasks={"my_wc": {**_interval(label="Big change"), "logsVolume": True}})
    log_awc(cfg, NOW, 8.0, False, "")
    assert cfg["maintenance"]["completions"]["my_wc"][0]["volume"] == 8.0


def test_awc_entries_respect_the_per_task_cap():
    cap = integration.const.MAINTENANCE_COMPLETIONS_MAX
    cfg = _awc_cfg_for_log()
    for day in range(cap + 5):
        log_awc(cfg, NOW + timedelta(days=day), 1.0, False, "")
    assert len(cfg["maintenance"]["completions"]["water_change"]) == cap


def test_awc_history_hook_logs_a_completion():
    """The single hook: anything recorded in AWC history is logged for maintenance."""
    cfg = _awc_cfg_for_log()
    awc = {}
    integration._awc_record_history(awc, NOW, 10.0, 9.8, "batch_sequential", False, "", config=cfg)
    entry = cfg["maintenance"]["completions"]["water_change"][0]
    assert entry["volume"] == 9.8       # the FILL volume is the water changed
    assert entry["source"] == AWC_SOURCE
    assert awc["history"][0]["filledL"] == 9.8  # AWC's own history still recorded


def test_awc_history_hook_without_config_stays_awc_only():
    awc = {}
    integration._awc_record_history(awc, NOW, 10.0, 9.8, "batch_sequential", False, "")
    assert awc["history"][0]["filledL"] == 9.8  # no config passed -> nothing to log against


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
