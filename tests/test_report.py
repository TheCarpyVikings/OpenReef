"""Reef Report, Stage B (0.7.198): the pure compile, the backend next-due
mirror, and the compile WS on a fake HA.

Run standalone:  python3 tests/test_report.py
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
from openreef import report  # noqa: E402

from _fake_ha import FakeConnection, FakeEntry, FakeHass, run  # noqa: E402

CONF_SETTINGS = integration.CONF_SETTINGS
# A Wednesday, 09:00 UTC. The previous Mon–Sun week is 7–13 September.
NOW = datetime(2026, 9, 16, 9, 0, tzinfo=timezone.utc)
WEEK = report.period_bounds(NOW, 0, "week", "previous")
START, END = WEEK["start"], WEEK["end"]


def _iso(dt):
    return dt.isoformat()


def _at(day_offset, hour=9):
    """A stamp inside the previous week: day 0 = its Monday."""
    return _iso(START + timedelta(days=day_offset, hours=hour))


def test_period_bounds_week_and_month():
    assert (START.date().isoformat(), END.date().isoformat()) == ("2026-09-07", "2026-09-14")
    assert WEEK["label"] == "7–13 September 2026" and WEEK["days"] == 7 and not WEEK["partial"]
    current = report.period_bounds(NOW, 0, "week", "current")
    assert current["start"].date().isoformat() == "2026-09-14" and current["partial"]
    sunday_weeks = report.period_bounds(NOW, 6, "week", "previous")
    assert sunday_weeks["start"].date().isoformat() == "2026-09-06", "a Sunday-start week ends on Saturday"
    month = report.period_bounds(NOW, 0, "month", "previous")
    assert (month["start"].date().isoformat(), month["end"].date().isoformat(), month["label"]) == ("2026-08-01", "2026-09-01", "August 2026")
    assert report.period_bounds(NOW, 0, "month", "current")["end"].date().isoformat() == "2026-10-01"
    assert report.period_bounds(NOW, 99, "week")["weekStart"] == 6 and report.period_bounds(NOW, "x", "week")["weekStart"] == 0


def test_maintenance_section_counts_on_time_and_water():
    tasks = {"water": {"label": "Water change", "cadenceDays": 7, "enabled": True, "logsVolume": True},
             "sock": {"label": "Filter sock", "cadenceDays": 7, "enabled": True},
             "brine": {"label": "Feed brine", "cadenceHours": 8, "enabled": True},
             "old": {"label": "Old chore", "cadenceDays": 7, "enabled": False}}
    completions = {
        "water": [{"timestamp": _at(-7), "volume": 10, "volumeUnit": "L"},                 # the week before: the anchor
                  {"timestamp": _at(0), "volume": 20, "volumeUnit": "pct", "source": "awc"},  # on time (7 d)
                  {"timestamp": _at(3), "volume": 5, "volumeUnit": "L"}],                    # on time (early)
        "sock": [{"timestamp": _at(-9)}, {"timestamp": _at(1)}],                             # 10 d on a 7 d cadence: late
        "brine": [{"timestamp": _at(2, 8)}, {"timestamp": _at(2, 15)}, {"timestamp": _at(2, 23)}, {"timestamp": _at(3, 20), "skipped": True}],
        "old": [{"timestamp": _at(4)}],
    }
    out = report.maintenance_section(tasks, completions, START, END, tank_l=52.0)
    assert out["done"] == 7 and out["skipped"] == 1
    # timed: water 2 (both on time), sock 1 (late), brine 2 (7 h and 8 h gaps: on time) -> 4/5
    assert out["timed"] == 5 and out["onSchedule"] == 80.0
    assert out["waterChangedL"] == 15.4 and out["autoL"] == 10.4 and out["handL"] == 5.0
    assert out["bySource"] == {"hand": 6, "awc": 1}
    by = {t["id"]: t for t in out["tasks"]}
    assert by["sock"]["late"] == 1 and by["old"]["tracked"] is False and by["brine"]["skipped"] == 1
    assert "old" in by, "history outlives the toggle"


def test_water_section_bands_consumption_and_honest_gaps():
    manual = {
        "alkalinity": [{"timestamp": _at(-20), "value": 8.6}, {"timestamp": _at(-13), "value": 8.2},
                       {"timestamp": _at(-6), "value": 8.7}, {"timestamp": _at(1), "value": 8.3}, {"timestamp": _at(5), "value": 8.0}],
        "calcium": [{"timestamp": _at(2), "value": 430}],
        "nitrate": [{"timestamp": _at(-10), "value": 5}, {"timestamp": _at(3), "value": 22}],
        "salinity": [{"timestamp": _at(-40), "value": 35}],
    }
    sensors = {"ph": [{"t": _at(0, h), "v": 8.1 + 0.01 * (h % 3)} for h in range(0, 168, 6)]}
    meta = {"alkalinity": {"label": "Alkalinity", "unit": "dKH", "min": 7.5, "max": 9.5},
            "nitrate": {"label": "Nitrate", "unit": "ppm", "min": 2, "max": 15}}
    out = report.water_section(manual, sensors, meta, START, END)
    by = {p["id"]: p for p in out["parameters"]}
    alk = by["alkalinity"]
    assert alk["tests"] == 2 and alk["band"] == "drifting" and alk["latest"] == 8.0 and alk["inRange"] is True
    assert alk["consumption"]["pairs"] == 3 and 0.05 < alk["consumption"]["perDay"] < 0.11, alk["consumption"]
    assert by["calcium"]["band"] == "single" and by["calcium"]["consumption"]["perDay"] is None
    assert by["nitrate"]["band"] == "swinging" and by["nitrate"]["inRange"] is False and by["nitrate"]["change"] == 17.0
    assert by["salinity"]["band"] == "untested" and by["salinity"]["latest"] == 35.0 and by["salinity"]["daysSince"] > 40
    assert by["ph"]["band"] == "steady" and by["ph"]["sensorSamples"] == 28 and by["ph"]["tests"] == 0
    assert set(out["untested"]) == {"Magnesium", "Phosphate", "Salinity", "Temperature"}
    assert "pH" in out["tested"]


def test_living_sections_count_what_the_journals_say():
    hatch = report.hatches_section(
        [{"vesselId": "v1", "startedAt": _at(0), "harvestedAt": _at(1, 10), "plannedHours": 24, "actualHours": 25},
         {"vesselId": "v2", "startedAt": _at(2), "harvestedAt": _at(3, 12), "plannedHours": 24, "actualHours": 27, "enriched": True},
         {"vesselId": "v1", "startedAt": _at(6, 22), "harvestedAt": _at(8), "plannedHours": 24, "actualHours": 26}],
        {"v1": {"name": "Hatchery 1"}, "v2": {"name": "Hatchery 2"}}, START, END)
    assert hatch["started"] == 3 and hatch["harvested"] == 2 and hatch["avgActualHours"] == 26.0 and hatch["avgLateHours"] == 2.0
    assert hatch["enriched"] == 1 and hatch["byVessel"][0] == {"id": "v1", "name": "Hatchery 1", "harvests": 1}
    jars = {"j1": {"name": "Rotifers", "history": [
        {"at": _at(0), "fed": True, "tint": "green"}, {"at": _at(1), "tint": "clearing"},
        {"at": _at(2), "harvested": True, "ml": 300}, {"at": _at(3), "fed": True, "undoneAt": _at(3, 10)},
        {"at": _at(4), "sign": "foam"}, {"at": _at(5), "event": "restart"}, {"at": _at(-1), "fed": True}]}}
    cult = report.cultures_section(jars, START, END)
    assert cult["feeds"] == 1 and cult["looks"] == 2 and cult["harvests"] == 1 and cult["signs"] == 1 and cult["restarts"] == 1
    assert cult["jars"][0]["harvestMl"] == 300 and cult["jars"][0]["signList"] == ["foam"]
    corals = report.corals_section(
        {"c1": {"name": "Acro"}, "c2": {"name": "Zoa"}},
        {"c1": [{"at": _at(1)}, {"at": _at(4), "undoneAt": _at(4, 1)}, {"at": _at(-3)}], "c2": [{"at": _at(2)}]},
        {"c1": [{"at": _at(2)}]},
        {"c1": {"score": 62, "grade": "C", "scoreBefore": 80}, "c2": {"score": 90, "grade": "A", "scoreBefore": 88}},
        START, END)
    assert corals["checkins"] == 2 and corals["feeds"] == 1 and corals["grades"] == {"C": 1, "A": 1}
    assert corals["moved"] == [{"id": "c1", "name": "Acro", "from": 80, "to": 62}]


def test_score_events_and_next_sections():
    log = [{"date": (START + timedelta(days=d)).date().isoformat(), "total": t, "parts": {"chemistry": t + 5}}
           for d, t in ((-3, 70), (-2, 72), (0, 78), (1, 80), (4, 82))]
    score = report.score_section(log, START, END)
    assert score["latest"] == 82 and score["average"] == 80.0 and score["previousAverage"] == 71.0 and score["delta"] == 9.0
    assert score["stamps"] == 3 and score["gaps"] == 4 and score["parts"] == {"chemistry": 85.0}
    events = report.events_section([{"at": _at(1), "message": "Alk drifting", "type": "warning"},
                                    {"at": _at(2), "message": "Return pump off", "type": "control"},
                                    {"at": _at(9), "message": "next week", "type": "warning"}], START, END)
    assert events["count"] == 2 and events["byType"] == {"warning": 1, "control": 1} and events["rows"][0]["message"] == "Return pump off"
    nxt = report.next_section([{"id": "a", "label": "Kalk", "dueAt": _iso(END - timedelta(hours=2)), "status": "warning"},
                               {"id": "b", "label": "Water change", "dueAt": _iso(END + timedelta(days=2, hours=10)), "status": "ok"},
                               {"id": "c", "label": "Far", "dueAt": _iso(END + timedelta(days=9)), "status": "ok"}], END)
    assert nxt["count"] == 2 and [d["label"] for d in nxt["days"]] == ["Already due", "Wednesday"]


def test_compile_period_reads_everything_and_writes_the_notes():
    ctx = {
        "period": WEEK, "now": NOW, "tankL": 52.0,
        "tasks": {"water": {"label": "Water change", "cadenceDays": 7, "enabled": True}},
        "completions": {"water": [{"timestamp": _at(-7), "volume": 10, "volumeUnit": "L"}, {"timestamp": _at(0), "volume": 10, "volumeUnit": "L"}]},
        "manualReadings": {"alkalinity": [{"timestamp": _at(1), "value": 8.3}]},
        "paramMeta": {"alkalinity": {"label": "Alkalinity", "unit": "dKH", "min": 7.5, "max": 9.5}},
        "awcHistory": [{"completedAt": _at(2), "drainedL": 2.5, "filledL": 2.5, "partial": False}, {"completedAt": _at(9), "drainedL": 2.5, "filledL": 2.5}],
        "feedLog": {"rows": [{"date": (START + timedelta(days=1)).date().isoformat(), "how": "hand"},
                             {"date": (START + timedelta(days=1)).date().isoformat(), "how": "pump", "undone": True},
                             {"date": END.date().isoformat(), "how": "hand"}], "counts": {"feeds": 99}},
        "events": [{"at": _at(3), "message": "Heater interlock", "type": "warning"}],
        "scoreLog": [{"date": (START + timedelta(days=2)).date().isoformat(), "total": 75, "parts": {}}],
        "upcoming": [{"id": "water", "label": "Water change", "dueAt": _iso(END + timedelta(days=1)), "status": "ok"}],
    }
    out = report.compile_period(ctx)
    assert out["period"]["label"] == "7–13 September 2026" and out["did"]["maintenance"]["done"] == 1
    assert out["did"]["awc"]["runs"] == 1 and out["did"]["awc"]["drainedL"] == 2.5
    assert out["did"]["feeds"] == {"count": 1, "hand": 1, "pump": 0, "undone": 1, "available": True}, "counted inside the window, not the log's span"
    assert out["did"]["tests"] == {"count": 1, "parameters": ["Alkalinity"]}
    assert out["headline"]["score"]["latest"] == 75 and out["headline"]["score"]["gaps"] == 6
    assert out["next"]["count"] == 1 and out["next"]["days"][0]["label"] == "Tuesday", "the plan starts the day after a Monday-ending week"
    assert out["happened"]["count"] == 1
    assert any(n.startswith("Not tested this period:") for n in out["notes"])
    assert any("stamped on 1 of 7 days" in n for n in out["notes"])
    assert out["headline"]["verdict"] == "1 chore ticked off, 100 % on time, 7 parameters untested, 1 warning on the log."
    empty = report.compile_period({"period": WEEK, "now": NOW})
    assert empty["headline"]["verdict"] == "Nothing ticked off, no water tests logged."
    assert "No Reef Health stamps this period" in " ".join(empty["notes"]) and "Feeding log not available" in " ".join(empty["notes"])


def test_backend_next_due_mirrors_the_panel_clock():
    base = {"maintenance": {"enabled": True, "tasks": {}, "completions": {}}}
    interval = {"label": "X", "cadenceDays": 7, "criticalAfterDays": 14, "scheduleMode": "interval", "enabled": True}
    cfg = integration._normalise_core_config({**base, "maintenance": {"enabled": True, "tasks": {"t": interval},
                                                                      "completions": {"t": [{"timestamp": _iso(NOW - timedelta(days=3))}]}}})
    at, state = integration._maintenance_next_due_at(cfg, "t", cfg["maintenance"]["tasks"]["t"], NOW)
    assert at == NOW + timedelta(days=4) and state == "ok"
    cfg["maintenance"]["completions"]["t"] = [{"timestamp": _iso(NOW - timedelta(days=9))}]
    assert integration._maintenance_next_due_at(cfg, "t", cfg["maintenance"]["tasks"]["t"], NOW) == (NOW, "warning")
    cfg["maintenance"]["tasks"]["t"]["snoozedUntil"] = _iso(NOW + timedelta(days=2))
    at, state = integration._maintenance_next_due_at(cfg, "t", cfg["maintenance"]["tasks"]["t"], NOW)
    assert at == NOW + timedelta(days=2) and state == "ok", "a snooze wins over an overdue cadence"
    hourly = {"label": "H", "cadenceHours": 8, "criticalAfterHours": 16, "scheduleMode": "interval", "enabled": True}
    cfg2 = integration._normalise_core_config({"maintenance": {"enabled": True, "tasks": {"h": hourly}, "completions": {"h": [{"timestamp": _iso(NOW - timedelta(hours=2))}]}}})
    assert integration._maintenance_next_due_at(cfg2, "h", cfg2["maintenance"]["tasks"]["h"], NOW)[0] == NOW + timedelta(hours=6)
    fixed = {"label": "F", "scheduleMode": "fixed", "scheduleDays": [5], "enabled": True, "cadenceDays": 7, "criticalAfterDays": 14}   # Saturdays
    cfg3 = integration._normalise_core_config({"maintenance": {"enabled": True, "tasks": {"f": fixed},
                                                               "completions": {"f": [{"timestamp": _iso(NOW - timedelta(days=4))}]}}})
    at, _state = integration._maintenance_next_due_at(cfg3, "f", cfg3["maintenance"]["tasks"]["f"], NOW)
    assert at.date().isoformat() == "2026-09-19", at
    upcoming = integration._maintenance_upcoming(cfg3, NOW, 7)
    assert [u["id"] for u in upcoming] == ["f"] and upcoming[0]["source"] is None


def test_ws_compile_runs_on_an_empty_and_a_busy_config():
    entry = FakeEntry(options={CONF_SETTINGS: {}})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_report_compile(hass, conn, {"id": 1}))
    assert not conn.errors, conn.errors
    empty = conn.results[-1].payload
    assert empty["period"]["kind"] == "week" and not empty["period"]["partial"] and empty["readingsSource"] == "tests"
    assert empty["did"]["maintenance"]["done"] == 0 and empty["water"]["untested"]
    now = datetime.now(timezone.utc)
    week = report.period_bounds(now, 0, "week", "previous")
    inside = week["start"] + timedelta(days=1, hours=9)
    busy = FakeEntry(options={CONF_SETTINGS: {
        "maintenance": {"enabled": True, "tasks": {"water": {"label": "Water change", "cadenceDays": 7, "criticalAfterDays": 14, "enabled": True, "scheduleMode": "interval", "logsVolume": True}},
                        "completions": {"water": [{"id": "a", "timestamp": inside.isoformat(), "volume": 12, "volumeUnit": "L"}]}},
        "manualReadings": {"alkalinity": [{"id": "r", "timestamp": inside.isoformat(), "value": 8.4, "unit": "dKH"}]},
        "reports": {"weekStart": 0, "scoreLog": [{"date": inside.date().isoformat(), "at": inside.isoformat(), "total": 81, "parts": {"chemistry": 90}}],
                    "events": [{"at": inside.isoformat(), "message": "Skimmer off", "type": "control"}]},
    }})
    hass = FakeHass(entries=[busy])
    conn = FakeConnection()
    run(integration.websocket_report_compile(hass, conn, {"id": 2, "readings": {"ph": [{"t": inside.isoformat(), "v": 8.1}]}}))
    assert not conn.errors, conn.errors
    out = conn.results[-1].payload
    assert out["readingsSource"] == "panel"
    assert out["did"]["maintenance"]["done"] == 1 and out["did"]["maintenance"]["waterChangedL"] == 12.0
    assert out["did"]["tests"]["parameters"] == ["Alkalinity"] and out["headline"]["score"]["latest"] == 81
    assert out["happened"]["rows"][0]["message"] == "Skimmer off"
    assert next(p for p in out["water"]["parameters"] if p["id"] == "ph")["sensorSamples"] == 1
    assert out["next"]["count"] >= 1, "the water change falls due inside the plan window"
    run(integration.websocket_report_compile(hass, conn, {"id": 3, "period": "month", "which": "current"}))
    assert conn.results[-1].payload["period"]["kind"] == "month" and conn.results[-1].payload["period"]["partial"]


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
