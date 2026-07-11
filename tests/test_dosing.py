"""Dosing engine — pure maths: schedule compilation, guard mirror, missed-dose
trajectory, respread, reservoir/integrity/tube ledgers, ramp, dry-run.

Everything here calls ``openreef.dosing`` directly with plain dicts — no HA fakes
needed beyond the import stubs (importing the package pulls in ``__init__.py``).

Run standalone:  python3 tests/test_dosing.py
Or with pytest:  pytest tests/
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
from openreef import dosing  # noqa: E402

NOW = datetime(2026, 1, 1, 12, 0, 0)
NOW_UTC = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _channel(chemical="kalk", **over):
    ch = {
        "enabled": True,
        "chemical": chemical,
        "schedule": {
            "enabled": True,
            "mlPerDay": 300,
            "mode": "continuous",
            "dosesPerDay": 8,
            "windowStart": "00:00",
            "windowEnd": "00:00",
            "night": {"enabled": False, "percent": 50, "useLightingSchedule": False,
                      "windowStart": "22:00", "windowEnd": "08:00"},
        },
        "guards": {
            "phEntity": "sensor.ph",
            "phPauseAbove": 8.45,
            "phResumeBelow": 8.30,
            "phMissingAcknowledged": False,
            "suspendDuringAwc": True,
            "quietHoursEnabled": False,
            "quietStart": "01:00",
            "quietEnd": "05:00",
            "maxPerDoseMl": 10,
            "maxDailyMl": 0,
            "minDoseIntervalMinutes": 1,
            "evaporationLimitMlPerDay": 0,
        },
        "reservoir": {"volumeMl": 5000, "remainingMl": 5000, "lowThresholdMl": 500,
                      "refilledAt": "", "primedAt": ""},
        "calibration": {"stepsPerMl": 11851, "measuredMl": 27, "calibratedAt": NOW_UTC.isoformat(),
                        "syncedToDevice": True, "history": []},
        "wear": {"runSeconds": 0, "doseCount": 0, "tubeInstalledAt": "", "tubeLifeHours": 1000},
        "ramp": {"enabled": False, "startPercent": 60, "stepPercent": 10, "maxDkhPerDay": 1.0,
                 "startedAt": "", "checkpoints": []},
        "sync": {"state": "synced", "lastSyncedAt": "", "lastError": "", "pendingWrites": {}},
        "state": {},
        "driver": {"type": "openreef_esphome_stepper", "version": 1,
                   "entities": {"reservoirLowSensor": "binary_sensor.low"}},
        "dailyLog": [],
        "events": [],
    }
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(ch.get(key), dict):
            ch[key].update(value)
        else:
            ch[key] = value
    return ch


def _live(**over):
    live = {
        "deviceOnline": True,
        "enabledSwitch": True,
        "reservoirLow": False,
        "phValue": 8.10,
        "phUnavailable": False,
        "dosedTodayMl": 0.0,
        "dosedSensorTrusted": True,
        "awcActive": False,
        "now": NOW_UTC,
    }
    live.update(over)
    return live


def _codes(reasons):
    return [r["code"] for r in reasons]


# --------------------------------------------------------------------------- #
# Schedule compilation
# --------------------------------------------------------------------------- #
def test_compile_kalk_default_operating_point():
    # The brief's default: 300 ml/day continuous, 24 h window, no night weighting.
    ch = _channel()
    out = dosing.compile_schedule(ch, None, NOW)
    plan = out["plan"]
    assert plan["perDoseMl"] == 2.08, plan
    assert plan["dayIntervalMin"] == 10
    assert abs(plan["realisedMlPerDay"] - 300) / 300 < 0.10
    assert "300" in plan["summaryText"]
    assert out["writes"]["doseVolumeNumber"] == 2.08
    assert out["writes"]["maxDailyNumber"] == 375.0  # auto: 1.25x rounded to 5
    assert out["writes"]["phStopNumber"] == 8.45
    assert out["writes"]["phResumeNumber"] == 8.30
    assert not out["warnings"]


def test_compile_night_weighting_tightens_night_interval():
    ch = _channel(schedule={"night": {"enabled": True, "percent": 65, "useLightingSchedule": False,
                                      "windowStart": "22:00", "windowEnd": "08:00"}})
    plan = dosing.compile_schedule(ch, None, NOW)["plan"]
    assert plan["nightIntervalMin"] < plan["dayIntervalMin"]
    assert plan["nightMl"] == 195.0 and plan["dayMl"] == 105.0
    assert "overnight" in plan["summaryText"]


def test_compile_night_inherits_lighting_window():
    ch = _channel(schedule={"night": {"enabled": True, "percent": 50, "useLightingSchedule": True,
                                      "windowStart": "22:00", "windowEnd": "08:00"}})
    plan = dosing.compile_schedule(ch, (1200, 480), NOW)["plan"]  # lights off 20:00–08:00
    assert plan["nightStart"] == 1200 and plan["nightEnd"] == 480


def test_compile_doses_mode_spreads_evenly():
    ch = _channel(chemical="alk", schedule={"mlPerDay": 40, "mode": "doses", "dosesPerDay": 8,
                                            "windowStart": "08:00", "windowEnd": "20:00"})
    plan = dosing.compile_schedule(ch, None, NOW)["plan"]
    assert plan["perDoseMl"] == 5.0
    assert plan["dayIntervalMin"] == 90  # 720 min window / 8
    assert "8 doses of 5 ml" in plan["summaryText"]


def test_compile_warns_cap_below_daily():
    ch = _channel(guards={"maxDailyMl": 100})
    warnings = dosing.compile_schedule(ch, None, NOW)["warnings"]
    assert "cap_below_daily" in [w["code"] for w in warnings]


def test_compile_warns_kalk_exceeds_evaporation():
    ch = _channel(guards={"evaporationLimitMlPerDay": 200})
    warnings = dosing.compile_schedule(ch, None, NOW)["warnings"]
    assert "kalk_exceeds_evaporation" in [w["code"] for w in warnings]


def test_compile_no_volume_warns_and_writes_the_zero():
    # R2: a zeroed schedule is a safety edit — the zero must reach the firmware
    # (and be drift-checked) or the pump keeps dosing its stale volume.
    ch = _channel(schedule={"mlPerDay": 0})
    out = dosing.compile_schedule(ch, None, NOW)
    assert "no_volume" in [w["code"] for w in out["warnings"]]
    assert out["writes"] == {"doseVolumeNumber": 0.0}


def test_compile_night_outside_window_deactivates_weighting():
    ch = _channel(schedule={"windowStart": "09:00", "windowEnd": "17:00",
                            "night": {"enabled": True, "percent": 65, "useLightingSchedule": False,
                                      "windowStart": "22:00", "windowEnd": "06:00"}})
    out = dosing.compile_schedule(ch, None, NOW)
    assert "night_outside_window" in [w["code"] for w in out["warnings"]]
    assert out["plan"]["nightPercent"] == 0.0


def test_compile_respects_max_per_dose_guard():
    ch = _channel(schedule={"mlPerDay": 2000}, guards={"maxPerDoseMl": 5})
    plan = dosing.compile_schedule(ch, None, NOW)["plan"]
    assert plan["perDoseMl"] <= 5.0


def test_compile_stale_respread_is_ignored_and_flagged():
    # R17: base values no longer match the (edited) schedule — the catch-up
    # override must not apply, and the plan flags it for the tick to clear.
    ch = _channel(state={"respread": {
        "date": NOW.date().isoformat(), "dayIntervalMin": 5, "nightIntervalMin": 5,
        "basePerDoseMl": 9.99, "baseDayIntervalMin": 99, "baseNightIntervalMin": 99,
    }})
    out = dosing.compile_schedule(ch, None, NOW)
    assert out["plan"]["dayIntervalMin"] == 10, "stale override must be ignored"
    assert out["plan"]["respreadStale"] is True


def test_compile_same_day_respread_overrides_interval():
    ch = _channel(state={"respread": {"date": NOW.date().isoformat(),
                                      "dayIntervalMin": 7, "nightIntervalMin": 7}})
    plan = dosing.compile_schedule(ch, None, NOW)["plan"]
    assert plan["dayIntervalMin"] == 7
    stale = _channel(state={"respread": {"date": "2025-12-31", "dayIntervalMin": 7, "nightIntervalMin": 7}})
    assert dosing.compile_schedule(stale, None, NOW)["plan"]["dayIntervalMin"] == 10


# --------------------------------------------------------------------------- #
# Guard mirror
# --------------------------------------------------------------------------- #
def test_guards_all_clear_when_healthy():
    ch = _channel()
    assert dosing.guard_reasons(ch, _live(), 720) == []


def test_guard_disabled_and_firmware_disabled():
    assert "disabled" in _codes(dosing.guard_reasons(_channel(enabled=False), _live(), 720))
    assert "firmware_disabled" in _codes(dosing.guard_reasons(_channel(), _live(enabledSwitch=False), 720))


def test_guard_not_calibrated_blocks():
    ch = _channel(calibration={"stepsPerMl": 0})
    assert "not_calibrated" in _codes(dosing.guard_reasons(ch, _live(), 720))


def test_guard_ph_blocked_with_hysteresis_latch():
    ch = _channel()
    assert "ph_blocked" in _codes(dosing.guard_reasons(ch, _live(phValue=8.50), 720))
    # Latched high: still blocked between resume (8.30) and pause (8.45)...
    latched = _channel(state={"phLatchedHigh": True})
    assert "ph_blocked" in _codes(dosing.guard_reasons(latched, _live(phValue=8.38), 720))
    # ...but a fresh (unlatched) channel at the same pH doses fine.
    assert "ph_blocked" not in _codes(dosing.guard_reasons(_channel(), _live(phValue=8.38), 720))
    # And below resume, even a latched channel clears.
    assert "ph_blocked" not in _codes(dosing.guard_reasons(latched, _live(phValue=8.25), 720))


def test_guard_ph_unavailable_fails_safe():
    ch = _channel()
    assert "ph_unavailable" in _codes(dosing.guard_reasons(ch, _live(phValue=None, phUnavailable=True), 720))


def test_guard_ph_resume_zero_falls_back_and_releases_latch():
    # A configured resume of 0 must not latch the mirror forever (review finding):
    # the fallback pins resume to pause − 0.1, matching the firmware write path.
    ch = _channel(guards={"phResumeBelow": 0.0}, state={"phLatchedHigh": True})
    assert "ph_blocked" not in _codes(dosing.guard_reasons(ch, _live(phValue=8.20), 720))
    assert "ph_blocked" in _codes(dosing.guard_reasons(ch, _live(phValue=8.40), 720))


def test_guard_daily_cap_mirrors_the_auto_cap():
    # maxDailyMl 0 = auto: the mirror must show the cap the firmware enforces
    # (300 x 1.25 → 375), not silently show nothing (review finding).
    ch = _channel(guards={"maxDailyMl": 0})
    assert "daily_cap_reached" in _codes(dosing.guard_reasons(ch, _live(dosedTodayMl=375), 720))
    assert "daily_cap_reached" not in _codes(dosing.guard_reasons(ch, _live(dosedTodayMl=300), 720))


def test_guard_kalk_without_ph_requires_acknowledgment():
    ch = _channel(guards={"phEntity": ""})
    assert "ph_unacknowledged" in _codes(dosing.guard_reasons(ch, _live(phValue=None), 720))
    acked = _channel(guards={"phEntity": "", "phMissingAcknowledged": True})
    assert "ph_unacknowledged" not in _codes(dosing.guard_reasons(acked, _live(phValue=None), 720))
    # Non-kalk channels never demand the acknowledgment.
    alk = _channel(chemical="alk", guards={"phEntity": ""})
    assert "ph_unacknowledged" not in _codes(dosing.guard_reasons(alk, _live(phValue=None), 720))


def test_guard_awc_active_and_optout():
    ch = _channel()
    assert "awc_active" in _codes(dosing.guard_reasons(ch, _live(awcActive=True), 720))
    optout = _channel(guards={"suspendDuringAwc": False})
    assert "awc_active" not in _codes(dosing.guard_reasons(optout, _live(awcActive=True), 720))


def test_guard_quiet_hours_scheduled_only():
    ch = _channel(guards={"quietHoursEnabled": True, "quietStart": "01:00", "quietEnd": "05:00"})
    assert "quiet_hours" in _codes(dosing.guard_reasons(ch, _live(), 120))
    assert "quiet_hours" not in _codes(dosing.guard_reasons(ch, _live(), 120, manual=True))
    assert "quiet_hours" not in _codes(dosing.guard_reasons(ch, _live(), 720))


def test_guard_daily_cap_and_reservoir_low_and_offline():
    capped = _channel(guards={"maxDailyMl": 300})
    assert "daily_cap_reached" in _codes(dosing.guard_reasons(capped, _live(dosedTodayMl=300), 720))
    assert "reservoir_low" in _codes(dosing.guard_reasons(_channel(), _live(reservoirLow=True), 720))
    assert "device_offline" in _codes(dosing.guard_reasons(_channel(), _live(deviceOnline=False), 720))


def test_guard_ledger_empty_without_float_is_warning_not_block():
    ch = _channel(reservoir={"remainingMl": 0},
                  driver={"type": "openreef_esphome_stepper", "version": 1, "entities": {}})
    reasons = dosing.guard_reasons(ch, _live(reservoirLow=None), 720)
    ledger = [r for r in reasons if r["code"] == "reservoir_ledger_empty"]
    assert ledger and ledger[0]["severity"] == "warn"
    assert not [r for r in reasons if r["severity"] == "block"]


# --------------------------------------------------------------------------- #
# Missed-dose trajectory + respread
# --------------------------------------------------------------------------- #
def test_expected_dosed_tracks_the_day():
    plan = dosing.compile_schedule(_channel(), None, NOW)["plan"]
    at_noon = dosing.expected_dosed_ml(plan, 720)
    at_end = dosing.expected_dosed_ml(plan, 1440)
    assert 0 < at_noon < at_end
    assert abs(at_end - plan["realisedMlPerDay"]) < plan["perDoseMl"] + 0.01
    assert abs(at_noon - at_end / 2) < 2 * plan["perDoseMl"]


def test_missed_state_thresholds():
    assert dosing.missed_state(100, 99, 2)["status"] == "ok"
    assert dosing.missed_state(100, 95, 2)["status"] == "behind"
    missed = dosing.missed_state(100, 50, 2)
    assert missed["status"] == "missed" and missed["missedMl"] == 50.0


def test_respread_kalk_always_skips():
    ch = _channel()
    plan = dosing.compile_schedule(ch, None, NOW)["plan"]
    assert dosing.respread_plan(ch, plan, 50, 720, 100)["recommendation"] == "skip"


def test_respread_2part_tightens_interval_under_caps():
    ch = _channel(chemical="alk", schedule={"mlPerDay": 40, "mode": "doses", "dosesPerDay": 8,
                                            "windowStart": "08:00", "windowEnd": "20:00"})
    plan = dosing.compile_schedule(ch, None, NOW)["plan"]
    # Noon = 4 h into the 08:00–20:00 window; only 5 ml delivered, 8 ml missed.
    out = dosing.respread_plan(ch, plan, 8, 720, 5)
    assert out["recommendation"] == "respread"
    assert out["dayIntervalMin"] < plan["dayIntervalMin"]
    assert "doseIntervalNumber" in out["writes"]


def test_respread_refuses_to_break_the_daily_cap():
    ch = _channel(chemical="alk", schedule={"mlPerDay": 40, "mode": "doses", "dosesPerDay": 8,
                                            "windowStart": "08:00", "windowEnd": "20:00"})
    plan = dosing.compile_schedule(ch, None, NOW)["plan"]
    plan = {**plan, "maxDailyMl": 45.0}
    out = dosing.respread_plan(ch, plan, 30, 720, 20)
    assert out["recommendation"] == "skip"
    assert "cap" in out["reason"]


# --------------------------------------------------------------------------- #
# Ledgers: reservoir, calibration, wear, integrity, ramp
# --------------------------------------------------------------------------- #
def test_reservoir_days_until_empty_and_low():
    res = {"volumeMl": 5000, "remainingMl": 900, "lowThresholdMl": 1000,
           "refilledAt": "", "primedAt": ""}
    out = dosing.reservoir_state(res, 300, NOW)
    assert out["daysUntilEmpty"] == 3.0
    assert out["low"] is True


def test_reservoir_refill_without_reprime_flag():
    res = {"volumeMl": 5000, "remainingMl": 5000, "lowThresholdMl": 500,
           "refilledAt": NOW_UTC.isoformat(), "primedAt": ""}
    assert dosing.reservoir_state(res, 300, NOW)["refillWithoutReprime"] is True
    res["primedAt"] = (NOW_UTC + timedelta(minutes=5)).isoformat()
    assert dosing.reservoir_state(res, 300, NOW)["refillWithoutReprime"] is False


def test_calibration_from_measured():
    out = dosing.calibration_from_measured(27.0)
    assert out["stepsPerMl"] == 11851.9 and out["mlPerRev"] == 0.27
    assert dosing.calibration_from_measured(0) is None
    assert dosing.calibration_from_measured(2000) is None


def test_tube_wear_increment_is_speed_aware():
    # 2.08 ml at 11851 steps/ml, 400 steps/s ≈ 61.6 s of run time.
    seconds = dosing.tube_wear_increment(2.08, 11851, 400)
    assert abs(seconds - 61.6) < 0.1
    assert dosing.tube_wear_increment(2.08, 11851, 800) < seconds
    assert dosing.tube_wear_increment(2.08, 0, 400) == 0.0


def test_integrity_states():
    assert dosing.integrity(_channel(calibration={"stepsPerMl": 0}), NOW)["status"] == "untrusted"
    old = _channel(calibration={"stepsPerMl": 11851, "calibratedAt": (NOW_UTC - timedelta(days=90)).isoformat()})
    out = dosing.integrity(old, NOW_UTC)
    assert out["status"] == "attention" and any("90 days" in r for r in out["reasons"])
    drifted = _channel(calibration={
        "stepsPerMl": 13000, "calibratedAt": NOW_UTC.isoformat(),
        "history": [{"stepsPerMl": 13000}, {"stepsPerMl": 11500}],
    })
    assert dosing.integrity(drifted, NOW_UTC)["status"] == "attention"
    assert dosing.integrity(_channel(), NOW_UTC)["status"] == "ok"


def test_tube_state_replace_due_at_life():
    wear = {"runSeconds": 1000 * 3600, "doseCount": 5, "tubeInstalledAt": "", "tubeLifeHours": 1000}
    out = dosing.tube_state(wear, NOW)
    assert out["runHours"] == 1000.0 and out["tubeReplaceDue"] is True
    wear["runSeconds"] = 901 * 3600
    out = dosing.tube_state(wear, NOW)
    assert out["tubeReplaceDue"] is False and out["tubeReplaceSoon"] is True


def test_ramp_target_steps_up_with_checkpoints():
    assert dosing.ramp_target({"enabled": False}, 300) is None
    ramp = {"enabled": True, "startPercent": 60, "stepPercent": 10, "maxDkhPerDay": 1.0,
            "checkpoints": [{"at": "", "testedValue": 8.1}]}
    out = dosing.ramp_target(ramp, 300)
    assert out["percent"] == 70.0 and out["targetMlPerDay"] == 210.0
    ramp["checkpoints"] = [{}] * 5
    assert dosing.ramp_target(ramp, 300)["complete"] is True


# --------------------------------------------------------------------------- #
# Rollover, dry-run, ETA, summary
# --------------------------------------------------------------------------- #
def test_detect_rollover_is_value_based():
    assert dosing.detect_rollover(120.5, 2.1) is True
    assert dosing.detect_rollover(120.5, 122.6) is False
    assert dosing.detect_rollover(0, 2.1) is False  # first sample, not a reset


def test_dry_run_preview_matches_plan():
    plan = dosing.compile_schedule(_channel(), None, NOW)["plan"]
    out = dosing.dry_run_preview(plan)
    assert out["count"] == plan["dosesDay"] + plan["dosesNight"]
    assert abs(out["totalMl"] - plan["realisedMlPerDay"]) < 0.01
    assert out["doses"][0]["ml"] == plan["perDoseMl"]
    assert len(out["doses"]) <= 300 and out["truncated"] is False


def test_next_dose_eta():
    plan = dosing.compile_schedule(_channel(), None, NOW)["plan"]
    eta = dosing.next_dose_eta(plan, 720)
    assert eta is not None and 0 <= eta["inMinutes"] <= plan["dayIntervalMin"]


def test_compile_doses_mode_tiny_window_never_overshoots():
    # ceil-derived interval: an 8-minute window with 3 doses must fire exactly 3
    # doses in the simulation, not 4 (review finding).
    ch = _channel(chemical="alk", schedule={"mlPerDay": 9, "mode": "doses", "dosesPerDay": 3,
                                            "windowStart": "08:00", "windowEnd": "08:08"})
    out = dosing.compile_schedule(ch, None, NOW)
    preview = dosing.dry_run_preview(out["plan"])
    assert preview["count"] <= 3


def test_summary_missed_states_are_trust_aware():
    # Sensor unbound/offline → "unknown", never a giant false "missed" (review finding).
    ch = _channel()
    out = dosing.summary({"kalk": ch}, {"kalk": _live(dosedSensorTrusted=False)}, NOW)
    assert out["kalk"]["missed"]["status"] == "unknown"
    assert out["kalk"]["missed"]["missedMl"] == 0.0
    # Schedule paused → "idle".
    paused = _channel(schedule={"enabled": False})
    out = dosing.summary({"kalk": paused}, {"kalk": _live()}, NOW)
    assert out["kalk"]["missed"]["status"] == "idle"
    # Live shortfall is display-only and never escalates past "behind" —
    # the orchestrator's debounced/baselined state owns "missed".
    out = dosing.summary({"kalk": _channel()}, {"kalk": _live(dosedTodayMl=0.0)}, NOW)
    assert out["kalk"]["missed"]["status"] == "behind"
    latched = _channel(state={"missedMl": 20.0, "missedSince": NOW_UTC.isoformat()})
    out = dosing.summary({"kalk": latched}, {"kalk": _live(dosedTodayMl=0.0)}, NOW)
    assert out["kalk"]["missed"] == {"missedMl": 20.0, "status": "missed", "pendingDecision": True}


def test_summary_integrates_everything():
    channels = {"kalk": _channel()}
    out = dosing.summary(channels, {"kalk": _live(dosedTodayMl=150)}, NOW)
    entry = out["kalk"]
    assert entry["chemicalLabel"] == "Kalkwasser"
    assert entry["plan"]["perDoseMl"] == 2.08
    assert entry["guards"] == []
    assert entry["dosedTodayMl"] == 150
    assert entry["reservoir"]["daysUntilEmpty"] is not None
    assert entry["integrity"]["status"] == "ok"
    assert entry["tube"]["tubeLifeHours"] == 1000
    assert entry["nextDose"] is not None
    assert entry["sync"]["state"] == "synced"


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
