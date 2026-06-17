"""Automatic Water Change engine — calibration, reservoir, dilution, safety, schedule.

The AWC engine (custom_components/openreef/awc.py) is pure stdlib, so it unit-tests
cleanly with no Home Assistant. We assert the pump-run primitive round-trips, the
dilution identities match the published reef maths (incl. the continuous-mode
efficiency penalty — 1%/day x 30 = ~25.9%, NOT 30%), drift/net-imbalance verdicts
flip at their thresholds, and the flexible schedule resolves litres/% per day/week
and computes the next batch run.

Run standalone:  python3 tests/test_awc.py
"""

from __future__ import annotations

import math
import os
import sys
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
from openreef import awc  # noqa: E402


def _close(a, b, tol=1e-6):
    return abs(a - b) <= tol


# --- Calibration & pump-run primitive ---------------------------------------

def test_runtime_for_volume_basic():
    # 2 L at 100 ml/s = 20 s
    assert _close(awc.runtime_for_volume_s(2.0, 100.0), 20.0)


def test_runtime_zero_rate_is_zero():
    assert awc.runtime_for_volume_s(5.0, 0.0) == 0.0
    assert awc.runtime_for_volume_s(5.0, -10.0) == 0.0


def test_runtime_volume_roundtrip():
    secs = awc.runtime_for_volume_s(1.5, 80.0)
    assert _close(awc.volume_for_runtime_l(secs, 80.0), 1.5)


def test_exchange_factor_lengthens_runtime():
    base = awc.runtime_for_volume_s(1.0, 100.0)
    corrected = awc.runtime_for_volume_s(1.0, 100.0, exchange_factor=1.1)
    assert corrected > base
    # and volume accounting inverts the same factor
    assert _close(awc.volume_for_runtime_l(corrected, 100.0, exchange_factor=1.1), 1.0)


def test_single_point_calibration():
    assert _close(awc.ml_per_s_from_run(500.0, 10.0), 50.0)
    assert awc.ml_per_s_from_run(500.0, 0.0) == 0.0


def test_linear_calibration_slope_and_intercept():
    # volume = 50*s + 20  → slope 50 ml/s, intercept 20 ml (priming offset)
    fit = awc.calibrate_linear([(10, 520), (20, 1020), (30, 1520)])
    assert fit["points"] == 3
    assert _close(fit["mlPerS"], 50.0, tol=1e-6)
    assert _close(fit["interceptMl"], 20.0, tol=1e-6)


def test_linear_calibration_single_point_falls_back():
    fit = awc.calibrate_linear([(10, 500)])
    assert fit["points"] == 1
    assert _close(fit["mlPerS"], 50.0)
    assert fit["interceptMl"] == 0.0


# --- Reservoir accounting ----------------------------------------------------

def test_reservoir_remaining_and_percent():
    assert _close(awc.reservoir_remaining_l(25.0, 5000.0), 20.0)  # 25 L − 5 L
    assert _close(awc.reservoir_percent(25.0, 20.0), 80.0)


def test_reservoir_remaining_clamps_at_zero():
    assert awc.reservoir_remaining_l(10.0, 50000.0) == 0.0


def test_days_of_supply_and_changes_remaining():
    assert _close(awc.days_of_supply(20.0, 2.0), 10.0)
    assert awc.days_of_supply(20.0, 0.0) is None
    assert _close(awc.changes_remaining(20.0, 5.0), 4.0)
    assert awc.changes_remaining(20.0, 0.0) is None


# --- Dilution maths ----------------------------------------------------------

def test_batch_dilution_identity():
    # Three 10% batch changes leave 0.9^3 = 0.729 of the original
    assert _close(awc.batch_fraction_remaining(0.10, 3), 0.729)
    assert _close(awc.batch_removed(0.10, 3), 0.271)


def test_continuous_less_efficient_than_batch():
    # 1%/day for 30 days on equal tank volume = 30% exchanged volume
    removed = awc.continuous_removed(0.30, 1.0)  # V_exchanged/V_tank = 0.30
    assert _close(removed, 1 - math.exp(-0.30), tol=1e-9)
    assert 0.258 < removed < 0.260  # ~25.9%, the honest figure (not 30%)


def test_litres_to_reach_target_continuous():
    # 284 L tank, nitrate 50 → 25 needs −284*ln(0.5) ≈ 196.85 L continuous
    need = awc.litres_to_reach_target_continuous(284.0, 50.0, 25.0)
    assert need is not None and _close(need, 196.85, tol=0.5)


def test_litres_to_reach_target_unreachable_returns_none():
    assert awc.litres_to_reach_target_continuous(284.0, 25.0, 25.0) is None
    assert awc.litres_to_reach_target_continuous(284.0, 25.0, 40.0) is None


def test_steady_state_plateau():
    # 1 ppm/day rising, 10% weekly change ⇒ ~7 ppm/day*... use period-consistent units:
    # production 7 ppm/week, fraction 0.10/week ⇒ plateau 70 ppm
    assert _close(awc.steady_state(7.0, 0.10), 70.0)
    assert awc.steady_state(7.0, 0.0) is None


# --- Safety maths ------------------------------------------------------------

def test_anomaly_verdict_thresholds():
    assert awc.anomaly_verdict(15, 10) == "ok"      # 1.5x
    assert awc.anomaly_verdict(25, 10) == "warn"    # 2.5x
    assert awc.anomaly_verdict(35, 10) == "abort"   # 3.5x
    assert awc.anomaly_verdict(100, 0) == "ok"      # uncalibrated → can't judge


def test_drift_state_flips_at_threshold():
    ok = awc.drift_state(2050, 2000)   # 2.5% over
    assert ok["status"] == "ok" and not ok["recalibrate"]
    bad = awc.drift_state(2400, 2000)  # 20% over
    assert bad["status"] == "warning" and bad["recalibrate"]
    assert bad["driftPct"] == 20.0
    assert awc.drift_state(100, 0)["status"] == "unknown"


def test_net_imbalance_tracks_drift_and_suggests_trim():
    # consistently drain a touch more than we fill ⇒ net negative ⇒ salinity-drop risk
    events = [{"drainedL": 5.0, "filledL": 4.8}] * 12
    state = net = awc.net_imbalance_state(events, threshold_l=2.0)
    assert _close(state["drainedL"], 60.0) and _close(state["filledL"], 57.6)
    assert state["netL"] < 0 and state["status"] == "warning"
    # suggested trim is the litres to ADD to the next fill to rebalance (positive)
    assert state["suggestedTrimL"] > 0
    assert _close(state["suggestedTrimL"], 2.4, tol=1e-6)


def test_net_imbalance_within_threshold_is_ok():
    state = awc.net_imbalance_state([{"drainedL": 5.0, "filledL": 5.0}] * 5, threshold_l=2.0)
    assert state["netL"] == 0.0 and state["status"] == "ok"


# --- Schedule resolution -----------------------------------------------------

def test_resolve_percent_and_litres():
    assert _close(awc.resolve_period_litres({"amountUnit": "percent", "amount": 10}, 200.0), 20.0)
    assert _close(awc.resolve_period_litres({"amountUnit": "litres", "amount": 12}, 200.0), 12.0)


def test_per_change_splits_daily_amount_across_times():
    sched = {"method": "batch_simultaneous", "amountUnit": "litres", "amount": 6,
             "period": "day", "times": ["02:00", "14:00"]}
    assert _close(awc.per_change_litres(sched, 0), 3.0)  # 6 L/day across 2 runs


def test_per_change_splits_weekly_amount_across_slots():
    sched = {"method": "batch_sequential", "amountUnit": "litres", "amount": 14,
             "period": "week", "days": ["Mon", "Wed", "Fri", "Sun"], "times": ["03:00"]}
    # 4 days x 1 time = 4 weekly slots ⇒ 3.5 L per change
    assert awc.runs_per_week(sched) == 4
    assert _close(awc.per_change_litres(sched, 0), 3.5)


def test_daily_equivalent_litres():
    assert _close(awc.daily_equivalent_litres({"amount": 7, "period": "week"}, 0), 1.0)
    assert _close(awc.daily_equivalent_litres({"amount": 2, "period": "day"}, 0), 2.0)


def test_continuous_tick_ml_spreads_over_window():
    # 4.8 L/day across a 24h window, 60s tick: 4800 ml * 60 / 86400 ≈ 3.333 ml
    ml = awc.continuous_tick_ml(4.8, 0, 0, 60)  # start==end ⇒ 24h
    assert _close(ml, 4800.0 * 60.0 / 86400.0, tol=1e-6)


def test_continuous_returns_no_next_run():
    assert awc.next_run({"method": "continuous", "enabled": True}, None, datetime(2026, 6, 17, 1, 0)) is None


def test_next_run_finds_next_time_today():
    sched = {"method": "batch_simultaneous", "enabled": True, "times": ["02:00", "14:00"]}
    now = datetime(2026, 6, 17, 9, 0)
    nxt = awc.next_run(sched, None, now)
    assert nxt == datetime(2026, 6, 17, 14, 0)


def test_next_run_rolls_to_allowed_day():
    # Only Mondays; 2026-06-17 is a Wednesday → next Monday is 2026-06-22
    sched = {"method": "batch_sequential", "enabled": True, "times": ["03:00"], "days": ["Mon"]}
    now = datetime(2026, 6, 17, 9, 0)
    nxt = awc.next_run(sched, None, now)
    assert nxt == datetime(2026, 6, 22, 3, 0)
    assert nxt.weekday() == 0


def test_is_due_after_scheduled_time():
    sched = {"method": "batch_simultaneous", "enabled": True, "times": ["02:00"]}
    # 03:00 now, never run today ⇒ due
    assert awc.is_due(sched, None, datetime(2026, 6, 17, 3, 0))
    # already ran at 02:30 today ⇒ not due again for the 02:00 slot
    assert not awc.is_due(sched, datetime(2026, 6, 17, 2, 30), datetime(2026, 6, 17, 3, 0))
    # before the slot ⇒ not due
    assert not awc.is_due(sched, None, datetime(2026, 6, 17, 1, 0))


def test_within_window_wraps_midnight():
    # quiet hours 23:00–05:00
    start, end = awc.parse_hhmm("23:00"), awc.parse_hhmm("05:00")
    assert awc.within_window(awc.parse_hhmm("01:00"), start, end)
    assert not awc.within_window(awc.parse_hhmm("12:00"), start, end)


# --- Summary (intelligence layer) --------------------------------------------

def test_summary_reservoirs_projection_and_nags():
    now = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)
    cfg = {
        "tankVolumeLitres": 200,
        "reservoirs": {"fresh": {"capacityLitres": 25, "remainingMl": 20000},
                       "waste": {"capacityLitres": 25, "filledMl": 5000}},
        "pumps": {"drain": {"mlPerS": 100, "calibratedAt": (now - timedelta(days=70)).isoformat()},
                  "fill": {"mlPerS": 100}},
        "schedule": {"enabled": True, "method": "continuous", "amountUnit": "litres",
                     "amount": 4, "period": "day"},
        "safety": {"netImbalanceWarnLitres": 2},
        "history": [{"drainedL": 5, "filledL": 4.5}] * 4,  # net −2 L ⇒ at the warn threshold
    }
    s = awc.summary(cfg, now)
    assert s["reservoirs"]["fresh"]["percent"] == 80.0
    assert s["reservoirs"]["waste"]["percent"] == 20.0
    assert _close(s["dailyChangeL"], 4.0)
    assert s["daysOfFreshRemaining"] is not None and _close(s["daysOfFreshRemaining"], 5.0)
    assert s["netImbalance"]["status"] == "warning"          # net −2 L ≥ threshold 2
    assert s["pumps"]["drain"]["recalibrationDue"] is True   # 70d ≥ 60
    assert s["pumps"]["fill"]["calibrationAgeDays"] is None  # never calibrated timestamp
    assert 0 < s["projectedRemovalPct30d"] < 100


# --- State-machine decisions -------------------------------------------------

def test_plan_leg_batch_simultaneous_one_leg():
    leg = awc.plan_leg("batch_simultaneous", 0, 0, 5000, 1000)
    assert leg["pumps"] == ["drain", "fill"] and _close(leg["sliceMl"], 5000)
    # after one full leg → complete
    assert awc.plan_leg("batch_simultaneous", 5000, 5000, 5000, 1000) is None


def test_plan_leg_sequential_drains_then_fills():
    first = awc.plan_leg("batch_sequential", 0, 0, 4000, 1000)
    assert first["pumps"] == ["drain"] and _close(first["sliceMl"], 4000)
    mid = awc.plan_leg("batch_sequential", 4000, 0, 4000, 1000)
    assert mid["pumps"] == ["fill"] and _close(mid["sliceMl"], 4000)
    assert awc.plan_leg("batch_sequential", 4000, 4000, 4000, 1000) is None


def test_plan_leg_continuous_ticks():
    leg = awc.plan_leg("continuous", 0, 0, 5000, 1000)
    assert leg["pumps"] == ["drain", "fill"] and _close(leg["sliceMl"], 1000)
    # last partial tick is clamped to the remainder
    leg2 = awc.plan_leg("continuous", 4500, 4500, 5000, 1000)
    assert _close(leg2["sliceMl"], 500)


def test_plan_leg_resume_to_balance():
    # power loss after draining 3000 but only filling 1000 → resumes the fill side
    leg = awc.plan_leg("batch_sequential", 3000, 1000, 3000, 1000)
    assert leg["pumps"] == ["fill"] and _close(leg["sliceMl"], 2000)


def test_leg_runtime_takes_the_longest_pump():
    cfg = {"pumps": {"drain": {"mlPerS": 100, "exchangeFactor": 1.0},
                     "fill": {"mlPerS": 50, "exchangeFactor": 1.0}}}
    # 1 L: drain 10s, fill 20s → leg runs 20s
    assert _close(awc.leg_runtime_s(1.0, cfg, ["drain", "fill"]), 20.0)
    assert _close(awc.leg_runtime_s(1.0, cfg, ["drain"]), 10.0)


def test_single_change_cap():
    cfg = {"tankVolumeLitres": 200, "safety": {"maxSingleChangePercent": 25}}
    assert not awc.exceeds_single_change_cap(cfg, 50)   # exactly 25%
    assert awc.exceeds_single_change_cap(cfg, 51)       # over
    assert not awc.exceeds_single_change_cap({"tankVolumeLitres": 0}, 9999)  # no tank vol → no cap


def _cfg_ready():
    return {
        "tankVolumeLitres": 200,
        "pumps": {"drain": {"switchEntity": "switch.drain", "mlPerS": 100},
                  "fill": {"switchEntity": "switch.fill", "mlPerS": 100}},
        "guards": {"blockDuringFeed": True, "blockOnReturnPumpIssue": True,
                   "quietHoursEnabled": True, "quietStart": "01:00", "quietEnd": "05:00"},
        "safety": {"maxSingleChangePercent": 25},
        "state": {"fault": ""},
    }


def test_start_guards_clear_when_ready_in_window():
    reasons = awc.start_guard_reasons(_cfg_ready(), {}, awc.parse_hhmm("02:00"))
    assert reasons == []


def test_start_guards_block_outside_quiet_hours_for_auto_only():
    cfg = _cfg_ready()
    at_noon = awc.parse_hhmm("12:00")
    codes = {r["code"] for r in awc.start_guard_reasons(cfg, {}, at_noon, manual=False)}
    assert "quiet_hours" in codes
    # manual bypasses quiet hours + feed mode
    codes_manual = {r["code"] for r in awc.start_guard_reasons(cfg, {"inFeedMode": True}, at_noon, manual=True)}
    assert "quiet_hours" not in codes_manual and "feed_mode" not in codes_manual


def test_start_guards_flag_hardware_and_safety():
    cfg = _cfg_ready()
    live = {"leak": True, "freshEmpty": True, "returnPumpIssue": True}
    reasons = awc.start_guard_reasons(cfg, live, awc.parse_hhmm("02:00"), manual=True)
    by = {r["code"]: r["severity"] for r in reasons}
    assert by.get("leak") == "fault"
    assert by.get("fresh_empty") == "block"
    assert by.get("return_pump") == "block"  # return-pump blocks even manual


def test_start_guards_uncalibrated_and_latched():
    cfg = _cfg_ready()
    cfg["pumps"]["fill"]["mlPerS"] = 0
    cfg["state"]["fault"] = "Leak detected"
    codes = {r["code"] for r in awc.start_guard_reasons(cfg, {}, awc.parse_hhmm("02:00"), manual=True)}
    assert "no_calibration" in codes and "latched" in codes


def test_in_run_safety_leak_and_overfill_latch():
    cfg = _cfg_ready()
    leak = awc.in_run_safety(cfg, {"leak": True}, True, True)
    assert leak["action"] == "fault" and leak["latch"] and leak["masterKill"]
    overfill = awc.in_run_safety(cfg, {"highLevel": True}, False, True)
    assert overfill["action"] == "fault" and overfill["latch"] and not overfill["masterKill"]


def test_in_run_safety_reservoir_limits_pause():
    cfg = _cfg_ready()
    assert awc.in_run_safety(cfg, {"freshEmpty": True}, False, True)["action"] == "pause"
    assert awc.in_run_safety(cfg, {"wasteFull": True}, True, False)["action"] == "pause"
    # fresh-empty doesn't pause a drain-only leg
    assert awc.in_run_safety(cfg, {"freshEmpty": True}, True, False)["action"] == "ok"


# --- tiny standalone runner --------------------------------------------------

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
