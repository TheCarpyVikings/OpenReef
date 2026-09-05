"""Maintenance Tasks — the record_task_completion service handler.

The due/overdue logic + UI are frontend; the one backend runtime path is the HA
service that logs a completion (so a physical button/automation can mark a task
done). Tested through the real handler with HA stubbed (`_ha_stubs`) + faked
(`_fake_ha`). (Config seeding/normalisation is covered in test_config_migration.)

Run standalone:  python3 tests/test_maintenance.py
"""

from __future__ import annotations

import copy
import json
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


# --- V2.2: stale-panel save must not drop completions -----------------------
# The panel posts the WHOLE config. Anything logged since its snapshot (an AWC run, a
# completion from an automation) has to survive that save — while a deliberate delete
# of an entry the panel COULD see still sticks. The completionsSyncedAt stamp is the
# anchor that tells those two apart.

merge = integration._merge_recent_completions


def _stored(entries, synced=None):
    block = {"maintenance": {"tasks": {"water_change": _interval()}, "completions": {"water_change": entries}}}
    if synced is not None:
        block["maintenance"]["completionsSyncedAt"] = synced
    return block


def _payload(entries, synced):
    return {"maintenance": {
        "tasks": {"water_change": _interval()},
        "completions": {"water_change": entries},
        "completionsSyncedAt": synced,
    }}


def _awc_entry(entry_id, when, volume=2.0):
    return {"id": entry_id, "timestamp": when.isoformat(), "volume": volume,
            "volumeUnit": "L", "notes": "", "source": AWC_SOURCE}


def _manual_entry(entry_id, when, volume=10.0):
    return {"id": entry_id, "timestamp": when.isoformat(), "volume": volume,
            "volumeUnit": "L", "notes": ""}


SNAPSHOT = NOW                       # when the stale panel was last handed the truth
BEFORE = NOW - timedelta(hours=6)    # entry it saw
AFTER = NOW + timedelta(hours=2)     # entry logged after its snapshot


def test_merge_restores_awc_entry_logged_after_the_snapshot():
    stored = _stored([_awc_entry("awc-new", AFTER), _manual_entry("old", BEFORE)])
    payload = _payload([_manual_entry("old", BEFORE)], SNAPSHOT.isoformat())
    merge(stored, payload)
    entries = payload["maintenance"]["completions"]["water_change"]
    assert [e["id"] for e in entries] == ["awc-new", "old"]  # restored, newest first


def test_merge_restores_service_logged_entry_too():
    """record_task_completion writes manual entries from automations — same risk."""
    stored = _stored([_manual_entry("from-automation", AFTER)])
    payload = _payload([], SNAPSHOT.isoformat())
    merge(stored, payload)
    assert [e["id"] for e in payload["maintenance"]["completions"]["water_change"]] == ["from-automation"]


def test_merge_respects_a_deliberate_delete():
    stored = _stored([_awc_entry("awc-seen", BEFORE), _manual_entry("kept", BEFORE)])
    payload = _payload([_manual_entry("kept", BEFORE)], SNAPSHOT.isoformat())
    merge(stored, payload)
    ids = [e["id"] for e in payload["maintenance"]["completions"]["water_change"]]
    assert ids == ["kept"], "an entry the panel could see must stay deleted"


def test_merge_takes_the_grown_same_day_awc_entry():
    """Same-day AWC runs merge in place; the backend owns that entry's volume."""
    stored = _stored([_awc_entry("awc-1", AFTER, volume=6.0)])
    payload = _payload([_awc_entry("awc-1", BEFORE, volume=2.0)], SNAPSHOT.isoformat())
    merge(stored, payload)
    entry = payload["maintenance"]["completions"]["water_change"][0]
    assert entry["volume"] == 6.0 and entry["timestamp"] == AFTER.isoformat()


def test_merge_leaves_manual_entries_the_client_still_has_alone():
    stored = _stored([_manual_entry("m1", BEFORE, volume=10.0)])
    payload = _payload([{**_manual_entry("m1", BEFORE, volume=10.0), "notes": "edited"}], SNAPSHOT.isoformat())
    merge(stored, payload)
    assert payload["maintenance"]["completions"]["water_change"][0]["notes"] == "edited"


def test_merge_without_a_stamp_restores_nothing():
    """Old client / import: fail in the direction that can't resurrect deletes."""
    stored = _stored([_awc_entry("awc-new", AFTER)])
    payload = _payload([], "")
    merge(stored, payload)
    assert payload["maintenance"]["completions"]["water_change"] == []


def test_merge_handles_missing_blocks_without_raising():
    merge(None, {})
    merge({"maintenance": {}}, {"maintenance": {}})
    payload = {"maintenance": {"completionsSyncedAt": SNAPSHOT.isoformat()}}
    merge(_stored([_awc_entry("awc-new", AFTER)]), payload)
    assert payload["maintenance"]["completions"]["water_change"][0]["id"] == "awc-new"


def test_stale_panel_save_keeps_the_awc_entry_end_to_end():
    """The whole point, through the real save handler: AWC logs a change while the
    panel sits on unsaved edits (so it won't refresh), then the panel saves."""
    from _fake_ha import FakeConnection

    entry = _entry()
    hass = FakeHass(entries=[entry])
    run(record(hass, _call({"task_id": "water_change", "volume": 5, "volume_unit": "L"})))
    stale = copy.deepcopy(entry.options[CONF_SETTINGS])   # what the panel is holding

    awc_now = datetime.now(timezone.utc) + timedelta(seconds=1)
    live = entry.options[CONF_SETTINGS]
    integration._maintenance_log_awc_change(live, awc_now, 3.5, False, "")
    run(integration._async_save_config(hass, entry, live))
    assert len(_saved(entry)["completions"]["water_change"]) == 2

    stale["maintenance"]["tasks"]["water_change"]["cadenceDays"] = 10  # the pending edit
    run(integration.websocket_save_config(hass, FakeConnection(), {"id": 1, "config": stale}))
    entries = _saved(entry)["completions"]["water_change"]
    assert len(entries) == 2, "the automatic change must survive a stale panel save"
    assert entries[0]["source"] == AWC_SOURCE
    assert _saved(entry)["tasks"]["water_change"]["cadenceDays"] == 10  # edit still applied


def test_save_stamps_the_completion_history():
    entry = _entry()
    hass = FakeHass(entries=[entry])
    run(record(hass, _call({"task_id": "water_change"})))
    assert _saved(entry)["completionsSyncedAt"], "every save must re-stamp the snapshot"


# --- hour-grained cadence (hatch chores) -------------------------------------
# cadenceHours > 0 puts an interval task on an hour clock; the normaliser owns
# the clamps and drops junk back to day-based.

def test_normalise_hour_cadence_fields():
    config = integration._normalise_core_config({
        "maintenance": {
            "seeded": True,
            "tasks": {
                "brine_hatch_harvest": {"label": "Harvest", "cadenceDays": 2,
                                        "cadenceHours": 36, "criticalAfterHours": 48},
                "hour_junk": {"label": "Junk", "cadenceDays": 1, "cadenceHours": "nope"},
                "hour_clamped": {"label": "Clamped", "cadenceDays": 1, "cadenceHours": 9000,
                                 "criticalAfterHours": 2},
                "day_based": {"label": "Days", "cadenceDays": 7},
            },
            "completions": {},
        }
    })
    tasks = config["maintenance"]["tasks"]
    assert tasks["brine_hatch_harvest"]["cadenceHours"] == 36
    assert tasks["brine_hatch_harvest"]["criticalAfterHours"] == 48
    assert "cadenceHours" not in tasks["hour_junk"], "junk hours must fall back to day-based"
    assert tasks["hour_clamped"]["cadenceHours"] == 336          # two-week ceiling
    assert tasks["hour_clamped"]["criticalAfterHours"] == 336    # critical >= cadence
    assert "cadenceHours" not in tasks["day_based"]


def test_normalise_keeps_hatchery_completion_source():
    config = integration._normalise_core_config({
        "maintenance": {
            "seeded": True,
            "tasks": {"brine_hatch_start": {"label": "Start", "cadenceDays": 1}},
            "completions": {"brine_hatch_start": [
                {"timestamp": "2026-08-13T08:00:00+00:00", "source": "hatchery"},
                {"timestamp": "2026-08-12T08:00:00+00:00", "source": "made_up"},
            ]},
        }
    })
    entries = config["maintenance"]["completions"]["brine_hatch_start"]
    assert entries[0]["source"] == "hatchery"
    assert "source" not in entries[1], "unknown sources must be stripped"


# --- the shared due contract (lockstep with the panel) -----------------------
# _maintenance_task_state here and _maintenanceDueState in the panel are separate
# implementations of ONE schedule: this one fires the reminders with the panel
# closed, the panel's drives the pills, Attention list and Reef Health dent. Both
# read this fixture — tests/test_panel_maintenance.mjs runs the same cases — so
# drifting either implementation fails a suite instead of silently disagreeing.

with open(os.path.join(_HERE, "fixtures", "maintenance_due_cases.json"), encoding="utf-8") as handle:
    DUE_CASES = json.load(handle)


def test_due_contract_matches_the_shared_fixture():
    now = datetime.fromisoformat(DUE_CASES["now"])
    mismatches = []
    for case in DUE_CASES["cases"]:
        task = {
            "label": "Subject", "enabled": True, "cadenceDays": 7,
            "criticalAfterDays": 14, "scheduleMode": "interval", "notify": True,
            **case["task"],
        }
        cfg = _cfg({"subject": task}, {"subject": case.get("completions", [])},
                   enabled=case.get("maintenanceEnabled", True))
        items = due(cfg, now)
        actual = items[0]["severity"] if items else "none"
        if actual != case["expect"]:
            mismatches.append(f"{case['name']}: backend says {actual}, contract says {case['expect']}")
    assert not mismatches, "backend drifted from the shared due contract:\n  " + "\n  ".join(mismatches)


# --- tiny standalone runner -------------------------------------------------


# --- V3 slice (2026-09-05): the shelf's bottles ride the daily digest; the
# task's notes ride the notification ---------------------------------------

def _bottle(name, bottle=250.0, remaining=20.0, **over):
    base = {"name": name, "category": "phyto", "bottleMl": bottle, "remainingMl": remaining,
            "history": [{"at": (NOW - timedelta(days=d)).isoformat(), "ml": 5.0, "kind": "dose"} for d in (1, 2, 3)]}
    base.update(over)
    return base


def _shelf_cfg(products, tasks=None, completions=None, target="mobile_app_pixel"):
    cfg = _cfg(tasks if tasks is not None else {"wc": _interval(label="Water change")},
               completions or {},
               reminders={"enabled": True, "time": "09:00", "notifyTarget": target, "persistent": True})
    cfg["consumables"] = {"products": products}
    return cfg


def test_shelf_nags_read_the_shelfs_own_flags():
    cfg = _shelf_cfg({
        "rj": _bottle("Reef Juice", remaining=20.0),                      # 8% < the 10% auto threshold
        "sel": _bottle("Selcon", remaining=200.0),                        # fine
        "emp": _bottle("Oyster-Feast", remaining=0.0),                    # empty
        "old": _bottle("Amino", remaining=200.0, shelfLifeDaysOpened=90,
                       openedAt=(NOW - timedelta(days=400)).isoformat()),  # expired
        "nosize": {"name": "Loose", "bottleMl": 0, "remainingMl": 0},     # no size: never low
    })
    nags = {n["id"]: n for n in integration._maintenance_shelf_nags(cfg, NOW)}
    assert set(nags) == {"shelf:rj", "shelf:emp", "shelf:old"}, set(nags)
    assert nags["shelf:rj"]["severity"] == "warning" and nags["shelf:rj"]["label"] == "Reef Juice"
    assert nags["shelf:rj"]["detail"].startswith("8% left, ≈"), nags["shelf:rj"]["detail"]
    assert nags["shelf:emp"] == {"id": "shelf:emp", "label": "Oyster-Feast", "detail": "empty", "severity": "critical"}
    assert nags["shelf:old"]["detail"] == "expired" and nags["shelf:old"]["severity"] == "critical"
    assert integration._maintenance_shelf_nags(_cfg({"wc": _interval()}), NOW) == []


def test_reminder_digest_names_the_low_bottles():
    cfg = _shelf_cfg({"rj": _bottle("Reef Juice", remaining=20.0), "emp": _bottle("Oyster-Feast", remaining=0.0)},
                     completions={"wc": [{"timestamp": _ago(20)}]})
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(entries=[entry])
    run(fire(hass, entry, NOW))
    push = next(c for c in hass.services.calls if c.domain == "notify")
    assert push.data["title"] == "OpenReef: 1 reef task due (1 overdue), 2 bottles to check", push.data["title"]
    assert push.data["message"].startswith("Water change · Bottles: ") and "Oyster-Feast (empty)" in push.data["message"]
    assert "Reef Juice (8% left, ≈" in push.data["message"], push.data["message"]
    # The activity feed gets one line per kind, only when the set grows.
    saved = entry.options[CONF_SETTINGS]
    messages = [item["message"] for item in saved.get("activity", [])]
    assert any(m == "Maintenance due: Water change" for m in messages), messages
    assert any(m.startswith("Bottles to check: Reef Juice (8% left") and "Oyster-Feast (empty)" in m for m in messages), messages
    # A second tick the same day: pushes again (the intended nag), logs nothing new.
    before = len(hass.services.calls)
    run(fire(hass, entry, NOW))
    assert sum(1 for c in hass.services.calls[before:] if c.domain == "notify") == 1
    assert len([m for m in (item["message"] for item in entry.options[CONF_SETTINGS].get("activity", [])) if m.startswith("Bottles")]) == 1


def test_reminder_pushes_the_bottles_even_with_no_task_due():
    cfg = _shelf_cfg({"rj": _bottle("Reef Juice", remaining=20.0)}, completions={"wc": [{"timestamp": _ago(1)}]})
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(entries=[entry])
    run(fire(hass, entry, NOW))
    push = next(c for c in hass.services.calls if c.domain == "notify")
    assert push.data["title"] == "OpenReef: 1 bottle to check" and push.data["message"].startswith("Bottles: Reef Juice (8% left")
    # Nothing due and nothing low: silent, as before.
    quiet = _shelf_cfg({"sel": _bottle("Selcon", remaining=200.0)}, completions={"wc": [{"timestamp": _ago(1)}]})
    entry2 = FakeEntry(options={CONF_SETTINGS: quiet})
    hass2 = FakeHass(entries=[entry2])
    run(fire(hass2, entry2, NOW))
    assert not any(c.domain == "notify" for c in hass2.services.calls)


def test_due_items_carry_the_notes_and_the_notification_shows_them():
    cfg = _cfg({"sock": _interval(label="Filter sock", notes="Rinse in tank water, never tap.")},
               {"sock": [{"timestamp": _ago(10)}]})
    item = due(cfg, NOW)[0]
    assert item["notes"] == "Rinse in tank water, never tap." and item["message"] == "Filter sock is due for maintenance."
    assert due(_cfg({"t": _interval()}, {"t": [{"timestamp": _ago(10)}]}), NOW)[0]["notes"] == ""
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(entries=[entry])
    run(fire(hass, entry, NOW))
    # The in-HA notification path reads the wall clock (so "due" or "overdue"
    # by the day it runs); the how-line rides under it either way.
    created = next(c for c in hass.services.calls if c.domain == "persistent_notification" and c.service == "create")
    assert created.data["message"].startswith("Filter sock is ") and created.data["message"].endswith("\nRinse in tank water, never tap."), created.data["message"]
    assert created.data["title"].startswith("OpenReef: Filter sock ")


# --- V3 (2026-09-05): the new-water record, the checklist, quiet hours, events

def test_new_water_record_survives_the_normaliser_and_the_service():
    cfg = _cfg({"wc": _interval(label="Water change", logsVolume=True)},
               {"wc": [{"timestamp": _ago(1), "volume": 10, "volumeUnit": "L",
                        "newWater": {"ppt": 35.14, "tempC": 25.26, "brand": "  NYOS Pure  "}},
                       {"timestamp": _ago(2), "newWater": {"ppt": 0, "tempC": 99, "brand": ""}},
                       {"timestamp": _ago(3), "newWater": "35"}]})
    rows = integration._normalise_core_config(cfg)["maintenance"]["completions"]["wc"]
    assert rows[0]["newWater"] == {"ppt": 35.1, "tempC": 25.3, "brand": "NYOS Pure"}
    assert "newWater" not in rows[1] and "newWater" not in rows[2]
    # The service takes the figures by hand and fires the done event.
    entry = _entry()
    hass = FakeHass(entries=[entry])
    run(record(hass, _call({"task_id": "water_change", "volume": 12, "volume_unit": "L",
                            "new_water_ppt": 35.0, "new_water_temp_c": 25.5})))
    row = _saved(entry)["completions"]["water_change"][0]
    assert row["newWater"] == {"ppt": 35.0, "tempC": 25.5}
    done = [e for e in hass.bus.events if e.event_type == integration.const.MAINTENANCE_DONE_EVENT]
    assert len(done) == 1 and done[0].data["source"] == "service" and done[0].data["volume"] == 12.0
    assert done[0].data["label"] == "Water change" and done[0].data["newWater"] == {"ppt": 35.0, "tempC": 25.5}


def test_task_checklist_is_kept_and_capped():
    cfg = _cfg({"wc": _interval(steps=["  Return pump off ", "", 7, "Siphon" * 40] + [f"step {i}" for i in range(20)])})
    steps = integration._normalise_core_config(cfg)["maintenance"]["tasks"]["wc"]["steps"]
    assert steps[0] == "Return pump off" and steps[1] == ("Siphon" * 40)[:120]
    assert len(steps) == 12 and "" not in steps
    assert integration._normalise_core_config(_cfg({"wc": _interval()}))["maintenance"]["tasks"]["wc"]["steps"] == []


def _local_hm(now, offset_min):
    local = integration.dt_util.as_local(now)
    t = (local.hour * 60 + local.minute + offset_min) % 1440
    return f"{t // 60:02d}:{t % 60:02d}"


def test_quiet_hours_window_wraps_midnight_and_holds_the_heartbeat():
    now = datetime.now(timezone.utc)
    active = {"quietHours": {"enabled": True, "start": _local_hm(now, -60), "end": _local_hm(now, 60)}}
    assert integration._quiet_hours_active(active, now) is True
    later = {"quietHours": {"enabled": True, "start": _local_hm(now, 60), "end": _local_hm(now, 120)}}
    assert integration._quiet_hours_active(later, now) is False
    complement = {"quietHours": {"enabled": True, "start": _local_hm(now, 60), "end": _local_hm(now, -60)}}
    assert integration._quiet_hours_active(complement, now) is False, "a wrapping window that excludes now"
    assert integration._quiet_hours_active({"quietHours": {"enabled": False, "start": "00:00", "end": "23:59"}}, now) is False
    assert integration._quiet_hours_active({"quietHours": {"enabled": True, "start": "22:00", "end": "22:00"}}, now) is False
    # 22:00 → 07:00 holds 03:00 local and frees 12:00 local.
    local = integration.dt_util.as_local(now)
    night = {"quietHours": {"enabled": True, "start": "22:00", "end": "07:00"}}
    assert integration._quiet_hours_active(night, local.replace(hour=3, minute=0)) is True
    assert integration._quiet_hours_active(night, local.replace(hour=12, minute=0)) is False
    # The normaliser: defaults off, 22:00 → 07:00, junk times fall back.
    quiet = integration._normalise_core_config({})["quietHours"]
    assert quiet == {"enabled": False, "start": "22:00", "end": "07:00"}
    quiet = integration._normalise_core_config({"quietHours": {"enabled": 1, "start": "23:30", "end": "junk"}})["quietHours"]
    assert quiet == {"enabled": True, "start": "23:30", "end": "07:00"}
    # The heartbeat push is held, the activity line says so, the check still runs.
    cfg = {"watchdog": {"enabled": True, "heartbeatEnabled": True, "heartbeatEveryHours": 24,
                        "missedAfterHours": 30, "notifyTarget": "mobile_app_pixel", "lastHeartbeat": ""},
           **active}
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(entries=[entry])
    out = run(integration._async_run_watchdog(hass, entry, force=True))
    assert not any(c.domain == "notify" for c in hass.services.calls)
    assert any(item["message"] == "OpenReef heartbeat OK (push held — quiet hours)" for item in out["activity"])
    cfg2 = {**cfg, **later}
    entry2 = FakeEntry(options={CONF_SETTINGS: cfg2})
    hass2 = FakeHass(entries=[entry2])
    run(integration._async_run_watchdog(hass2, entry2, force=True))
    assert any(c.domain == "notify" and c.service == "mobile_app_pixel" for c in hass2.services.calls)


def test_due_and_low_events_fire_once_on_the_daily_tick():
    cfg = _shelf_cfg({"rj": _bottle("Reef Juice", remaining=20.0)}, completions={"wc": [{"timestamp": _ago(20)}]})
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(entries=[entry])
    run(fire(hass, entry, NOW))
    due = [e for e in hass.bus.events if e.event_type == integration.const.MAINTENANCE_DUE_EVENT]
    low = [e for e in hass.bus.events if e.event_type == integration.const.CONSUMABLE_LOW_EVENT]
    assert len(due) == 1 and due[0].data["task_id"] == "wc" and due[0].data["severity"] == "critical"
    assert due[0].data["label"] == "Water change" and due[0].data["entry_id"] == entry.entry_id
    assert len(low) == 1 and low[0].data["product_id"] == "rj" and low[0].data["label"] == "Reef Juice"
    assert low[0].data["severity"] == "warning" and low[0].data["detail"].startswith("8% left")
    # The next tick: the same set, so no events — the day they first appear is the hook.
    before = len(hass.bus.events)
    run(fire(hass, entry, NOW + timedelta(days=1)))
    assert len(hass.bus.events) == before

def test_reminder_push_carries_done_buttons_and_the_tap_logs_the_task():
    # 0.7.140 (doc §8.11 #9): the digest offers Done for the first two tasks,
    # overdue first; the tap logs the task through the service's own core.
    cfg = _cfg(
        {"wc": _interval(label="Water change"), "glass": _interval(label="Clean the glass", cadenceDays=3, criticalAfterDays=30),
         "pump": _interval(label="Pump service", cadenceDays=2, criticalAfterDays=30)},
        {"wc": [{"timestamp": _ago(20)}], "glass": [{"timestamp": _ago(5)}], "pump": [{"timestamp": _ago(3)}]},
        reminders={"enabled": True, "time": "09:00", "notifyTarget": "mobile_app_pixel", "persistent": True},
    )
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(entries=[entry])
    run(fire(hass, entry, NOW))
    push = [c for c in hass.services.calls if c.domain == "notify"][-1]
    actions = push.data["data"]["actions"]
    assert actions[0] == {"action": "OPENREEF_TASK_DONE:wc", "title": "Done: Water change"}, "the overdue task leads"
    assert actions[1]["action"].startswith("OPENREEF_TASK_DONE:") and actions[1]["action"] != actions[0]["action"]
    assert actions[2]["action"] == "OPENREEF_LATER" and len(actions) == 3
    assert push.data["data"]["tag"] == "openreef_maintenance_digest"

    class Ev:
        def __init__(self, action):
            self.data = {"action": action}

    run(integration._async_notification_action(hass, Ev("OPENREEF_TASK_DONE:wc")))
    entries = entry.options[CONF_SETTINGS]["maintenance"]["completions"]["wc"]
    assert "source" not in entries[0], "a phone tap is the keeper's own completion, not an automatic one"
    assert entries[0]["notes"] == "Marked done from the phone" and entries[0]["timestamp"]
    done = [e for e in hass.bus.events if e.event_type == integration.MAINTENANCE_DONE_EVENT]
    assert len(done) == 1 and done[0].data["source"] == "phone" and done[0].data["task_id"] == "wc"
    activity = entry.options[CONF_SETTINGS].get("activity") or []
    assert any("Maintenance done: Water change (from the phone)" in str(a.get("message", "")) for a in activity)
    run(integration._async_notification_action(hass, Ev("OPENREEF_TASK_DONE:nope")))
    activity = entry.options[CONF_SETTINGS].get("activity") or []
    assert any("Phone tap ignored" in str(a.get("message", "")) for a in activity)
    assert len(entry.options[CONF_SETTINGS]["maintenance"]["completions"]["wc"]) == 2, "the fixture's entry plus the tap, nothing from the bad tap"
    # The service still refuses an unknown task the way it always did.
    try:
        run(record(hass, _call({"task_id": "nope"})))
        raise AssertionError("an unknown task must be refused")
    except integration.ServiceValidationError:
        pass



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
