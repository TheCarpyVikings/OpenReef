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
    busy.options[CONF_SETTINGS]["sensors"] = {"ph": {"entity_id": "sensor.ph", "enabled": True}}
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


def _busy_report():
    """The compile test's context, compiled — the fixture the score and the
    recommendations read."""
    ctx = {
        "period": WEEK, "now": NOW, "tankL": 52.0,
        "tasks": {"water": {"label": "Water change", "cadenceDays": 7, "enabled": True},
                  "sock": {"label": "Filter sock", "cadenceDays": 7, "enabled": True}},
        "completions": {"water": [{"timestamp": _at(-7), "volume": 10, "volumeUnit": "L"}, {"timestamp": _at(0), "volume": 10, "volumeUnit": "L"}],
                        "sock": [{"timestamp": _at(-10)}, {"timestamp": _at(1)}]},
        "manualReadings": {"alkalinity": [{"timestamp": _at(-20), "value": 8.6}, {"timestamp": _at(-6), "value": 8.7}, {"timestamp": _at(1), "value": 8.3}],
                           "nitrate": [{"timestamp": _at(-10), "value": 5}, {"timestamp": _at(3), "value": 22}]},
        "paramMeta": {"alkalinity": {"label": "Alkalinity", "unit": "dKH", "min": 7.5, "max": 9.5}, "nitrate": {"label": "Nitrate", "unit": "ppm", "min": 2, "max": 15}},
        "feedLog": {"rows": [{"date": (START + timedelta(days=d)).date().isoformat(), "how": "hand"} for d in range(7)]},
        "hatchHistory": [{"vesselId": "v1", "startedAt": _at(0), "harvestedAt": _at(1, 10), "plannedHours": 24, "actualHours": 29}],
        "cultureJars": {"j1": {"name": "Rotifers", "history": [{"at": _at(0), "fed": True}, {"at": _at(4), "sign": "foam"}]}},
        "corals": {"c1": {"name": "Acro"}, "c2": {"name": "Zoa"}}, "checkins": {"c1": [{"at": _at(1)}]},
        "coralStates": {"c1": {"score": 62, "grade": "C", "scoreBefore": 80}, "c2": {"score": 90, "grade": "A"}},
        "events": [{"at": _at(3), "message": "Heater interlock", "type": "warning"}],
        "scoreLog": [{"date": (START + timedelta(days=2)).date().isoformat(), "total": 75, "parts": {}}],
    }
    return report.compile_period(ctx)


def test_week_score_has_five_explainable_parts_and_neutral_gaps():
    out = _busy_report()
    ws = out["score"]
    parts = {p["id"]: p for p in ws["parts"]}
    # Chemistry: alkalinity steady (100 — 8.3–8.7 sits inside the 0.5 dKH tolerance),
    # nitrate swinging + out of range (35, and the cap at 50 does not lift it) -> 67.5
    assert parts["chemistry"]["score"] == 68 and "Nitrate swinging and out of range" in parts["chemistry"]["why"]
    assert parts["chemistry"]["raise"].startswith("Test Calcium, Magnesium")
    # Care: sock late (1 of 1 timed -> on time 50 %), 2 of 8 tested (25), water changed (100) -> 58
    assert parts["care"]["score"] == 58 and "50 % of chores on time" in parts["care"]["why"]
    # Nutrition: 7 feeds (100), hatch 5 h late (70), a culture sign (70) -> 80
    assert parts["nutrition"]["score"] == 80 and "5 h past the clock" in parts["nutrition"]["why"]
    # Livestock: A + C = 80 avg, one drop -> 70
    assert parts["livestock"]["score"] == 70 and "1 dropped" in parts["livestock"]["why"]
    assert parts["reliability"]["score"] == 85
    total = round((68 * 30 + 58 * 25 + 80 * 15 + 70 * 15 + 85 * 15) / 100)
    assert ws["total"] == total, (ws["total"], total)
    assert ws["condition"] == round((68 * 30 + 70 * 15) / 45) and ws["consistency"] == round((58 * 25 + 80 * 15 + 85 * 15) / 55)
    assert ws["neutral"] == []
    empty = report.compile_period({"period": WEEK, "now": NOW})["score"]
    assert empty["total"] == 100 and empty["condition"] is None, "only reliability has data on an empty week: a quiet log"
    assert set(empty["neutral"]) == {"Chemistry stability", "Care consistency", "Nutrition", "Livestock wellbeing"}
    assert all(p["available"] is False and p["score"] is None for p in empty["parts"] if p["id"] != "reliability")


def test_recommendations_are_evidence_backed_capped_and_snoozable():
    out = _busy_report()
    recs = out["recommendations"]
    ids = [r["id"] for r in recs["items"]]
    assert len(ids) == 3 and not recs["calm"]
    # Priority order: out of range (12), swinging (15), a coral dropping (18); the culture sign (20) waits its turn.
    assert ids == ["range_nitrate", "steady_nitrate", "coral_c1"], ids
    rec = recs["items"][0]
    assert rec["evidence"] == "Latest 22.0 ppm from your test on 10 Sep; the range is 2–15 ppm." and rec["actions"] == [{"action": "tab", "id": "manual", "label": "Log a test"}]
    assert "effort" in rec and "effect" in rec and "priority" not in rec
    # The full rule set fires beyond the cap; snoozing lifts the next ones in.
    later = (NOW + timedelta(days=20)).isoformat()
    again = report.recommend(out, {"range_nitrate": later, "steady_nitrate": later, "coral_c1": later}, NOW)
    assert [r["id"] for r in again["items"]] == ["culture_j1", "hatch_late", "test_calcium"] and again["snoozed"] == ["coral_c1", "range_nitrate", "steady_nitrate"]
    assert again["items"][2]["evidence"] == "Never logged." and again["items"][0]["evidence"] == "1 sign logged: foam."
    expired = report.recommend(out, {"range_nitrate": (NOW - timedelta(days=1)).isoformat()}, NOW)
    assert expired["items"][0]["id"] == "range_nitrate" and expired["snoozed"] == []
    quiet = {"period": {"days": 7}, "headline": {"score": {"gaps": 0, "stamps": 7}}, "did": {"maintenance": {"done": 3, "timed": 3, "waterChangedL": 10, "tasks": []}},
             "water": {"parameters": [{"id": "alkalinity", "label": "Alkalinity", "band": "steady", "inRange": True, "latestIsFromPeriod": True}]}, "living": {}}
    calm = report.recommend(quiet, None, NOW)
    assert calm["calm"] and [r["id"] for r in calm["items"]] == ["keep_rhythm"]
    bare = report.compile_period({"period": WEEK, "now": NOW})["recommendations"]
    assert [r["id"] for r in bare["items"]] == ["test_alkalinity", "test_calcium", "test_magnesium"], "an empty config is asked to test, alkalinity first"


def test_ws_rec_snooze_stores_and_lifts():
    entry = FakeEntry(options={CONF_SETTINGS: {}})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_report_rec_snooze(hass, conn, {"id": 1, "rec_id": "test_alkalinity"}))
    assert not conn.errors and "test_alkalinity" in conn.results[-1].payload["snoozedRecs"]
    until = integration._parse_datetime(entry.options[CONF_SETTINGS]["reports"]["snoozedRecs"]["test_alkalinity"])
    assert 29 <= (until - datetime.now(timezone.utc)).days <= 30
    run(integration.websocket_report_rec_snooze(hass, conn, {"id": 2, "rec_id": "test_alkalinity", "days": 0}))
    assert entry.options[CONF_SETTINGS]["reports"]["snoozedRecs"] == {}
    run(integration.websocket_report_rec_snooze(hass, conn, {"id": 3, "rec_id": "  "}))
    assert conn.errors[-1].code == "invalid_rec"
    stale = integration._normalise_core_config({"reports": {"snoozedRecs": {"old": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), "live": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), "junk": 5}}})
    assert list(stale["reports"]["snoozedRecs"]) == ["live"]
    stored = {"reports": {"snoozedRecs": {"a": "2099-01-01T00:00:00+00:00"}, "scoreLog": [], "events": []}}
    incoming = {"reports": {"weekStart": 0, "snoozedRecs": {}, "scoreLog": [], "events": []}}
    integration._reports_preserve_runtime(stored, incoming)
    assert incoming["reports"]["snoozedRecs"] == {"a": "2099-01-01T00:00:00+00:00"}, "snoozes ride the guard"


def test_period_bounds_anchor_reads_any_past_period():
    anchored = report.period_bounds(NOW, 0, "week", anchor=datetime(2026, 8, 20).date())
    assert (anchored["start"].date().isoformat(), anchored["end"].date().isoformat(), anchored["partial"]) == ("2026-08-17", "2026-08-24", False)
    this_week = report.period_bounds(NOW, 0, "week", anchor=NOW.date())
    assert this_week["start"].date().isoformat() == "2026-09-14" and this_week["partial"]
    month = report.period_bounds(NOW, 0, "month", anchor=datetime(2026, 7, 9).date())
    assert (month["start"].date().isoformat(), month["end"].date().isoformat()) == ("2026-07-01", "2026-08-01")


def test_snapshot_is_compact_and_push_text_carries_the_headline():
    out = _busy_report()
    snap = report.snapshot(out)
    assert snap["id"] == "week:2026-09-07" and snap["kind"] == "week" and snap["label"] == "7–13 September 2026"
    assert snap["weekScore"]["total"] == out["score"]["total"] and snap["did"]["done"] == 2
    assert [w["id"] for w in snap["water"]][:2] == ["alkalinity", "calcium"] and snap["recommendations"][0]["id"] == "range_nitrate"
    import json
    assert len(json.dumps(snap)) < 2500, len(json.dumps(snap))
    title, message = report.push_text(out)
    assert title == "OpenReef Weekly Reef Report · 7–13 September 2026"
    lines = message.split("\n")
    assert lines[0].startswith(f"Week Score {out['score']['total']} (condition") and "Reef Health avg 75" in lines[0]
    assert lines[1] == out["headline"]["verdict"] and lines[2] == "2 chores (50 % on time) · 10 L water changed · 2 tests"
    assert lines[3] == "Top: Bring nitrate back into range" and lines[-1] == "Open OpenReef → Home → Reef Report."


def test_store_snapshot_replaces_caps_and_rides_the_guard():
    cfg = integration._normalise_core_config({})
    out = _busy_report()
    integration._report_store_snapshot(cfg, out)
    integration._report_store_snapshot(cfg, out)
    assert len(cfg["reports"]["items"]) == 1, "the same period stored twice is one row"
    for weeks_back in range(1, 40):
        older = dict(out, period={**out["period"], "start": (START - timedelta(days=7 * weeks_back)).isoformat(), "kind": "week"})
        integration._report_store_snapshot(cfg, older)
    for months_back in range(1, 20):
        older = dict(out, period={**out["period"], "start": (START - timedelta(days=31 * months_back)).isoformat(), "kind": "month"})
        integration._report_store_snapshot(cfg, older)
    kinds = [r["kind"] for r in cfg["reports"]["items"]]
    assert kinds.count("week") == integration.REPORT_ITEMS_WEEKLY_MAX and kinds.count("month") == integration.REPORT_ITEMS_MONTHLY_MAX
    assert cfg["reports"]["items"][0]["id"] == "week:2026-09-07", "newest first"
    stored = {"reports": {"items": [{"id": "week:2026-09-07", "kind": "week", "start": "2026-09-07"}], "scoreLog": [], "events": [], "snoozedRecs": {}}}
    incoming = {"reports": {"weekStart": 0, "items": [], "scoreLog": [], "events": [], "snoozedRecs": {}, "schedule": {"enabled": False, "time": "08:00", "push": True}}}
    integration._reports_preserve_runtime(stored, incoming)
    assert incoming["reports"]["items"][0]["id"] == "week:2026-09-07" and incoming["reports"]["schedule"]["enabled"] is False, "snapshots are the server's, the schedule is the keeper's"


def test_due_kinds_catch_up_and_the_tick_stores_and_pushes():
    cfg = integration._normalise_core_config({})
    assert integration._report_due_kinds(cfg, NOW) == ["week", "month"], "a fresh install owes both"
    cfg["reports"]["items"] = [{"id": "week:2026-09-07", "kind": "week", "start": "2026-09-07"}]
    assert integration._report_due_kinds(cfg, NOW) == ["month"]
    entry = FakeEntry(options={CONF_SETTINGS: {
        "reports": {"items": [{"id": "month:2026-08-01", "kind": "month", "start": "2026-08-01"}]},
        "maintenance": {"enabled": True, "tasks": {}, "completions": {}, "reminders": {"enabled": True, "time": "09:00", "notifyTarget": "mobile_app_pixel", "persistent": True}},
    }})
    hass = FakeHass(entries=[entry])
    made = run(integration._async_report_tick(hass, entry, datetime.now(timezone.utc)))
    assert made == ["week"]
    items = entry.options[CONF_SETTINGS]["reports"]["items"]
    assert [i["kind"] for i in items] == ["week", "month"] and items[0]["generatedAt"]
    pushes = [c for c in hass.services.calls if c.domain == "notify"]
    assert len(pushes) == 1 and pushes[0].service == "mobile_app_pixel" and "Reef Report" in pushes[0].data["title"]
    assert entry.options[CONF_SETTINGS]["activity"][0]["message"].startswith("Weekly Reef Report ready")
    assert entry.options[CONF_SETTINGS]["reports"]["events"][0]["kind"] == "report"
    assert run(integration._async_report_tick(hass, entry, datetime.now(timezone.utc))) == [], "stored: nothing owed"
    # Push off: the digest carries one line instead, the day it was written.
    entry.options[CONF_SETTINGS]["reports"]["schedule"]["push"] = False
    line = integration._report_digest_line(entry.options[CONF_SETTINGS], datetime.now(timezone.utc))
    assert line.startswith("the weekly Reef Report is ready")
    assert integration._report_digest_line(entry.options[CONF_SETTINGS], datetime.now(timezone.utc) + timedelta(days=1)) == ""
    entry.options[CONF_SETTINGS]["reports"]["schedule"]["enabled"] = False
    del entry.options[CONF_SETTINGS]["reports"]["items"][:]
    assert run(integration._async_report_tick(hass, entry, datetime.now(timezone.utc))) == [], "the schedule off writes nothing"


def test_ws_list_generate_and_anchor():
    entry = FakeEntry(options={CONF_SETTINGS: {"reports": {"weekStart": 0, "schedule": {"enabled": True, "time": "07:00", "push": True}}}})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_report_list(hass, conn, {"id": 1}))
    assert conn.results[-1].payload["items"] == [] and conn.results[-1].payload["schedule"]["time"] == "07:00"
    run(integration.websocket_report_generate(hass, conn, {"id": 2}))
    assert not conn.errors and conn.results[-1].payload["stored"]["kind"] == "week"
    assert not [c for c in hass.services.calls if c.domain == "notify"], "storing by hand never pushes"
    run(integration.websocket_report_list(hass, conn, {"id": 3}))
    assert len(conn.results[-1].payload["items"]) == 1
    run(integration.websocket_report_compile(hass, conn, {"id": 4}))
    assert conn.results[-1].payload["stored"]["kind"] == "week", "the compile says when its period is stored"
    run(integration.websocket_report_compile(hass, conn, {"id": 5, "anchor": "2026-06-10"}))
    assert conn.results[-1].payload["period"]["start"].startswith("2026-06-08") and conn.results[-1].payload["stored"] is None
    run(integration.websocket_report_compile(hass, conn, {"id": 6, "anchor": "yesterday"}))
    assert conn.errors[-1].code == "invalid_anchor"


def test_water_names_its_source_and_a_probe_the_kit_contradicts_is_checked_not_chased():
    """Reece's tank, 2026-09-17: "Bring salinity back into range — latest
    25.312 ppt" from a probe nobody had enabled. The engine now names where a
    figure came from, and a sensor far outside its band (or one the kit
    contradicts) asks for the probe to be checked, not the tank."""
    meta = {"salinity": {"label": "Salinity", "unit": "ppt", "min": 32, "max": 36}}
    manual = {"salinity": [{"timestamp": _at(1, 9), "value": 34.6}]}
    sensors = {"salinity": [{"t": _at(1, 11), "v": 25.312}, {"t": _at(5, 9), "v": 25.31}]}
    water = report.water_section(manual, sensors, meta, START, END)
    by_id = lambda w: next(p for p in w["parameters"] if p["id"] == "salinity")  # noqa: E731
    sal = by_id(water)
    assert sal["latest"] == 25.31 and sal["latestSource"] == "sensor" and sal["inRange"] is False
    assert sal["latestTest"]["value"] == 34.6 and sal["latestSensor"]["value"] == 25.31
    assert sal["farOut"] is True, "more than a band-width outside 32–36"
    assert sal["disagree"]["delta"] == -9.288 and sal["disagree"]["test"] == 34.6 and sal["disagree"]["sensor"] == 25.312
    recs = report.recommend({"water": water, "did": {}, "living": {}, "happened": {}, "headline": {}, "period": {"days": 7}}, {}, NOW)
    ids = [r["id"] for r in recs["items"]]
    assert "check_salinity" in ids and "range_salinity" not in ids, ids
    check = next(r for r in recs["items"] if r["id"] == "check_salinity")
    assert check["evidence"] == ("The sensor read 25.31 ppt on 12 Sep, far outside 32–36 ppt; your test on 8 Sep said 34.6 ppt. "
                                 "A probe or a unit problem is likelier than the tank."), check["evidence"]
    assert check["actions"][0]["id"] == "settings"
    # The keeper's own test out of range is the tank's to fix — and says it was a test.
    water2 = report.water_section({"salinity": [{"timestamp": _at(2), "value": 30.5}]}, {}, meta, START, END)
    recs2 = report.recommend({"water": water2, "did": {}, "living": {}, "happened": {}, "headline": {}, "period": {"days": 7}}, {}, NOW)
    rng = next(r for r in recs2["items"] if r["id"] == "range_salinity")
    assert rng["evidence"] == "Latest 30.5 ppt from your test on 9 Sep; the range is 32–36 ppt."
    assert by_id(water2)["latestSource"] == "test" and by_id(water2)["disagree"] is None
    # A probe within twice the tolerance of the kit is not a disagreement.
    water3 = report.water_section(manual, {"salinity": [{"t": _at(1, 12), "v": 35.2}]}, meta, START, END)
    assert by_id(water3)["disagree"] is None and by_id(water3)["farOut"] is False
    snap = report.snapshot(report.compile_period({"period": WEEK, "now": NOW, "manualReadings": manual, "sensorReadings": sensors, "paramMeta": meta}))
    assert next(w for w in snap["water"] if w["id"] == "salinity")["source"] == "sensor"


def test_report_reads_only_enabled_sensors_and_the_keepers_band():
    cfg = integration._normalise_core_config({"sensors": {
        "salinity": {"entity_id": "sensor.old_probe", "enabled": False, "min": 1.024, "max": 1.027},
        "alkalinity": {"entity_id": "sensor.trident_alk", "enabled": True, "min": 7.8, "max": 8.6, "label": "Alk (Trident)"},
    }})
    meta = integration._report_param_meta(cfg)
    assert meta["salinity"] == {"label": "Salinity", "unit": "ppt", "min": 31.82, "max": 35.8, "sensor": False, "entity": ""}, meta["salinity"]
    assert meta["alkalinity"]["min"] == 7.8 and meta["alkalinity"]["label"] == "Alk (Trident)" and meta["alkalinity"]["entity"] == "sensor.trident_alk"
    assert meta["calcium"]["min"] == 380 and meta["calcium"]["sensor"] is False, "defaults behind an unmapped one"
    readings = {"salinity": [{"t": _at(1), "v": 25.312}], "alkalinity": [{"t": _at(1), "v": 8.2}, {"t": _at(2), "v": "junk"}, {"t": _at(3), "value": 8.1}],
                "calcium": [{"t": _at(1), "v": 420}]}
    clean = integration._report_clean_readings(cfg, readings)
    assert set(clean) == {"alkalinity"}, "a disabled probe and an unmapped one feed nothing"
    assert [r["v"] for r in clean["alkalinity"]] == [8.2, 8.1]
    cfg["sensors"]["salinity"]["enabled"] = True
    assert [r["v"] for r in integration._report_clean_readings(cfg, {"salinity": [{"t": _at(1), "v": 1.0264}]})["salinity"]] == [35.0], "an SG probe reads in ppt"
    ctx = integration._report_context(cfg, NOW, NOW, WEEK, readings)
    assert set(ctx["sensorReadings"]) == {"alkalinity", "salinity"} and ctx["paramMeta"]["salinity"]["unit"] == "ppt"

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
