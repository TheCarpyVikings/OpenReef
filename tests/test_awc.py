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


def test_runtime_applies_spin_up_offset():
    # slope 1.46 ml/s, spin-up -2.6 mL (startup deficit): a 40 mL dose must run LONGER
    # so V = slope*t + intercept lands on 40. t = (40 - (-2.6))/1.46 = 29.18 s (vs 27.4 without).
    t = awc.runtime_for_volume_s(0.040, 1.46, 1.0, -2.6)
    assert _close(t, (40.0 + 2.6) / 1.46, tol=1e-6)
    # delivered volume at that runtime = 1.46*t - 2.6 ≈ 40 mL
    assert _close(1.46 * t - 2.6, 40.0, tol=1e-3)
    # a positive spin-up (startup surge) shortens the run instead
    t2 = awc.runtime_for_volume_s(0.040, 1.46, 1.0, 2.6)
    assert _close(t2, (40.0 - 2.6) / 1.46, tol=1e-6)
    # default spin-up 0.0 is unchanged from the pure-rate primitive
    assert _close(awc.runtime_for_volume_s(0.040, 1.46), 40.0 / 1.46, tol=1e-6)


def test_runtime_spin_up_clamps_tiny_dose_to_zero():
    # a dose smaller than a positive spin-up surge can't be delivered ⇒ 0 s (caller skips it)
    assert awc.runtime_for_volume_s(0.001, 1.46, 1.0, 5.0) == 0.0


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


# --- Simultaneous exchange (independent per-pump timing) ---------------------

def test_exchange_side_progress_dead_reckons_from_remaining():
    # 2 L target at 100 ml/s ⇒ 20 s full runtime. With 5 s remaining, 15 s done ⇒ 1.5 L.
    vol, done = awc.exchange_side_progress(5.0, 100.0, 1.0, 2000.0)
    assert _close(vol, 1500.0, 1e-6) and not done


def test_exchange_side_progress_done_caps_at_target():
    vol, done = awc.exchange_side_progress(0.0, 100.0, 1.0, 2000.0)
    assert vol == 2000.0 and done
    # negative remaining (overdue) also caps at target, never above
    vol2, done2 = awc.exchange_side_progress(-5.0, 100.0, 1.0, 2000.0)
    assert vol2 == 2000.0 and done2


def test_exchange_imbalance_cap():
    assert not awc.exchange_imbalance_exceeds(1000, 950, 0.1)  # 50 ml < 100 ml cap
    assert awc.exchange_imbalance_exceeds(1000, 800, 0.1)      # 200 ml > 100 ml cap
    assert not awc.exchange_imbalance_exceeds(1000, 0, 0)      # cap 0 ⇒ disabled
    # baseline (resume-to-balance): a pre-existing gap being CORRECTED never trips
    assert not awc.exchange_imbalance_exceeds(1500, 0, 0.1, baseline_ml=1500)   # new divergence 0
    assert not awc.exchange_imbalance_exceeds(1000, 0, 0.1, baseline_ml=1500)   # gap shrank
    assert awc.exchange_imbalance_exceeds(1700, 0, 0.1, baseline_ml=1500)       # new 200 ml > cap


def test_simultaneous_max_excursion():
    # 100/50 pair, 2 L: drain 20 s, fill 40 s ⇒ peak gap = 2·(1−20/40) = 1.0 L
    assert _close(awc.simultaneous_max_excursion_l({"pumps": {"drain": {"mlPerS": 100}, "fill": {"mlPerS": 50}}}, 2.0), 1.0)
    # matched pumps ⇒ no excursion
    assert _close(awc.simultaneous_max_excursion_l({"pumps": {"drain": {"mlPerS": 100}, "fill": {"mlPerS": 100}}}, 2.0), 0.0)


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


def test_runs_per_week_multiplies_days_by_times():
    # Mon/Wed x 06:00/18:00 fires 2 days x 2 times = 4 runs/week — NOT max(2,2)=2.
    # The old max() split a weekly amount across 2 slots but ran 4x ⇒ ~2x over-change.
    sched = {"method": "batch_sequential", "amountUnit": "litres", "amount": 14,
             "period": "week", "days": ["Mon", "Wed"], "times": ["06:00", "18:00"]}
    assert awc.runs_per_week(sched) == 4
    # weekly 14 L across 4 real runs ⇒ 3.5 L each (delivering 14 L/week, not 28 L)
    assert _close(awc.per_change_litres(sched, 0), 3.5)
    # daily period: 2 days x 3 times = 6 runs/week
    daily = {"method": "batch_sequential", "days": ["Mon", "Tue"], "times": ["06:00", "12:00", "18:00"]}
    assert awc.runs_per_week(daily) == 6


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


def test_interval_slot_generation():
    sched = {"mode": "interval", "everyMinutes": 60, "windowStart": "01:00", "windowEnd": "05:00"}
    assert awc.slot_minutes_for_day(sched) == [60, 120, 180, 240]
    # wrapped window: post-midnight slots land as early-morning minutes of the day
    wrapped = {"mode": "interval", "everyMinutes": 30, "windowStart": "23:00", "windowEnd": "01:00"}
    assert awc.slot_minutes_for_day(wrapped) == [0, 30, 1380, 1410]
    # equal bounds = the full day
    full = {"mode": "interval", "everyMinutes": 60, "windowStart": "00:00", "windowEnd": "00:00"}
    assert len(awc.slot_minutes_for_day(full)) == 24
    # a sillily small interval is floored to 15 min
    tiny = {"mode": "interval", "everyMinutes": 1, "windowStart": "00:00", "windowEnd": "01:00"}
    assert len(awc.slot_minutes_for_day(tiny)) == 4


def test_interval_equivalence_with_24_times():
    # The old '24 explicit times' stopgap and hourly interval mode are the same
    # schedule — slots, due decision, per-change volume and weekly run count.
    times24 = {"enabled": True, "method": "batch_simultaneous", "amount": 0.96,
               "amountUnit": "litres", "period": "day",
               "times": [f"{h:02d}:00" for h in range(24)]}
    interval = {"enabled": True, "method": "batch_simultaneous", "amount": 0.96,
                "amountUnit": "litres", "period": "day", "mode": "interval",
                "everyMinutes": 60, "windowStart": "00:00", "windowEnd": "00:00"}
    now = datetime(2026, 6, 17, 7, 30)
    assert awc.slot_minutes_for_day(times24) == awc.slot_minutes_for_day(interval)
    assert awc.due_slot(times24, None, now) == awc.due_slot(interval, None, now)
    assert abs(awc.per_change_litres(times24, 52) - awc.per_change_litres(interval, 52)) < 1e-9
    assert abs(awc.per_change_litres(interval, 52) - 0.04) < 1e-9  # the 40 ml micro-change
    assert awc.runs_per_week(interval) == 24 * 7


def test_interval_due_slots_and_next_run():
    sched = {"enabled": True, "method": "batch_simultaneous", "mode": "interval",
             "everyMinutes": 60, "windowStart": "01:00", "windowEnd": "05:00"}
    now = datetime(2026, 6, 17, 3, 30)
    # nothing ran: 01:00/02:00/03:00 have passed and are unserved (ascending)
    assert [s.hour for s in awc.due_slots(sched, None, now)] == [1, 2, 3]
    # served through 02:10 → only 03:00 outstanding
    served = datetime(2026, 6, 17, 2, 10)
    assert [s.hour for s in awc.due_slots(sched, served, now)] == [3]
    assert awc.due_slot(sched, served, now).hour == 3
    # next slot after 03:30 is 04:00; after the window closes, tomorrow's 01:00
    assert awc.next_run(sched, None, now) == datetime(2026, 6, 17, 4, 0)
    assert awc.next_run(sched, None, datetime(2026, 6, 17, 12, 0)) == datetime(2026, 6, 18, 1, 0)


def test_schedule_text_lines():
    interval = {"enabled": True, "method": "batch_simultaneous", "amount": 0.96,
                "amountUnit": "litres", "period": "day", "mode": "interval",
                "everyMinutes": 60, "windowStart": "00:00", "windowEnd": "00:00"}
    text = awc.schedule_text(interval, 52)
    assert "40 ml" in text and "every hour" in text and "0.96 L/day" in text and "∥" in text
    times = {"enabled": True, "method": "batch_sequential", "amount": 4,
             "amountUnit": "litres", "period": "day", "times": ["02:00"], "days": ["Mon"]}
    text2 = awc.schedule_text(times, 52)
    assert "4 L at 02:00 on Mon" in text2 and "drain then fill" in text2
    assert awc.schedule_text({"enabled": False}, 52).startswith("Schedule off")


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
        "reservoirs": {"fresh": {"capacityLitres": 25, "remainingMl": 25000},
                       "waste": {"capacityLitres": 25, "filledMl": 0}},
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


def test_start_guards_block_paused_change():
    cfg = _cfg_ready()
    cfg["state"]["status"] = "paused"
    codes = {r["code"] for r in awc.start_guard_reasons(cfg, {}, awc.parse_hhmm("02:00"), manual=True)}
    assert "paused" in codes


def test_reservoir_preflight_blocks_insufficient_capacity():
    cfg = _cfg_ready()
    cfg["reservoirs"]["fresh"]["remainingMl"] = 1000
    cfg["reservoirs"]["waste"]["filledMl"] = 24500
    codes = {r["code"] for r in awc.reservoir_preflight_reasons(cfg, 2.0)}
    assert "fresh_insufficient" in codes
    assert "waste_insufficient" in codes


def test_reservoir_preflight_allows_known_capacity():
    assert awc.reservoir_preflight_reasons(_cfg_ready(), 2.0) == []


def test_in_run_safety_leak_and_overfill_latch():
    cfg = _cfg_ready()
    leak = awc.in_run_safety(cfg, {"leak": True}, True, True)
    assert leak["action"] == "fault" and leak["latch"] and leak["masterKill"]
    overfill = awc.in_run_safety(cfg, {"highLevel": True}, False, True)
    assert overfill["action"] == "fault" and overfill["latch"] and not overfill["masterKill"]


def test_flood_sensor_unavailable_fails_closed():
    # A CONFIGURED leak / high-level sensor gone unavailable blocks start (never latches)...
    cfg = _cfg_ready()
    codes = {r["code"]: r["severity"]
             for r in awc.start_guard_reasons(cfg, {"leakUnknown": True}, awc.parse_hhmm("02:00"), manual=True)}
    assert codes.get("leak_unavailable") == "block"
    codes2 = {r["code"]: r["severity"]
              for r in awc.start_guard_reasons(cfg, {"highLevelUnknown": True}, awc.parse_hhmm("02:00"))}
    assert codes2.get("high_level_unavailable") == "block"
    # ...and pauses an in-flight change (auto-resume when the sensor recovers)
    v = awc.in_run_safety(cfg, {"leakUnknown": True}, True, True)
    assert v["action"] == "pause" and not v["latch"]
    v2 = awc.in_run_safety(cfg, {"highLevelUnknown": True}, True, True)
    assert v2["action"] == "pause" and not v2["latch"]
    # a real leak still outranks the unknown (fault + master kill)
    v3 = awc.in_run_safety(cfg, {"leak": True, "highLevelUnknown": True}, True, True)
    assert v3["action"] == "fault" and v3["masterKill"]


def test_in_run_safety_reservoir_limits_pause():
    cfg = _cfg_ready()
    assert awc.in_run_safety(cfg, {"freshEmpty": True}, False, True)["action"] == "pause"
    assert awc.in_run_safety(cfg, {"wasteFull": True}, True, False)["action"] == "pause"
    # fresh-empty doesn't pause a drain-only leg
    assert awc.in_run_safety(cfg, {"freshEmpty": True}, True, False)["action"] == "ok"


# --- Hardening Wave 4: engine math fixes + the named coverage gaps ------------

def test_calibrate_linear_ill_conditioned_falls_back_to_through_origin():
    # Two ~30 s runs: least squares would fit slope 40 ml/s / intercept -690 ml
    # (2.3x wrong); the conditioning guard must fall back to the honest ~17 ml/s.
    fit = awc.calibrate_linear([(30.0, 510.0), (30.5, 530.0)])
    assert 16.5 < fit["mlPerS"] < 17.5, fit
    assert fit["interceptMl"] == 0.0
    # A properly spread set still least-squares (intercept recovered).
    fit = awc.calibrate_linear([(10.0, 105.0), (30.0, 305.0), (60.0, 605.0)])
    assert _close(fit["mlPerS"], 10.0, 1e-6)
    assert _close(fit["interceptMl"], 5.0, 1e-6)


def test_spin_up_round_trips_runtime_and_volume():
    # t = (V - spinUp)/rate; the inverse (with the offset re-applied) returns V.
    seconds = awc.runtime_for_volume_s(0.04, 10.0, 1.0, spin_up_ml=5.0)  # 40 ml dose
    assert _close(seconds, 3.5)
    litres = awc.volume_for_runtime_l(seconds, 10.0, 1.0, spin_up_ml=5.0)
    assert _close(litres, 0.04)
    # Remaining-time tails pass spin_up 0 (no further start occurs).
    assert _close(awc.volume_for_runtime_l(seconds, 10.0, 1.0), 0.035)


def test_runtime_respects_exchange_factor():
    # factor 1.25: a longer/loaded line needs 25% more runtime for the same volume.
    base = awc.runtime_for_volume_s(1.0, 100.0)
    loaded = awc.runtime_for_volume_s(1.0, 100.0, exchange_factor=1.25)
    assert _close(loaded, base * 1.25)
    assert _close(awc.volume_for_runtime_l(loaded, 100.0, 1.25), 1.0)


def test_net_imbalance_threshold_zero_means_disabled():
    verdict = awc.net_imbalance_from_totals(100.0, 90.0, threshold_l=0)
    assert verdict["status"] == "ok"          # previously: "warn always"
    assert verdict["netL"] == -10.0
    assert awc.net_imbalance_from_totals(100.0, 90.0, threshold_l=2.0)["status"] == "warning"


def test_summary_prefers_ledger_over_capped_history():
    now = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)
    cfg = {
        "tankVolumeLitres": 200,
        "reservoirs": {"fresh": {"capacityLitres": 25, "remainingMl": 20000},
                       "waste": {"capacityLitres": 25, "filledMl": 0}},
        "pumps": {"drain": {"mlPerS": 100}, "fill": {"mlPerS": 100}},
        "schedule": {"enabled": False},
        "safety": {"netImbalanceWarnLitres": 2.0},
        # Capped history holds a sliver; the persistent ledger holds the truth.
        "history": [{"drainedL": 1.0, "filledL": 1.0}],
        "ledger": {"cumulativeDrainedL": 120.0, "cumulativeFilledL": 110.0},
    }
    summary = awc.summary(cfg, now)
    net = summary["netImbalance"]
    assert net["drainedL"] == 120.0 and net["filledL"] == 110.0
    assert net["status"] == "warning" and net["suggestedTrimL"] == 10.0


def test_daily_equivalent_honours_day_restrictions():
    # "4 L per day, Mondays only" averages 4/7 L/day — not 4 (was up to 7x off).
    sched = {"enabled": True, "method": "batch_sequential", "amountUnit": "litres",
             "amount": 4, "period": "day", "days": ["Mon"], "times": ["02:00"]}
    assert _close(awc.daily_equivalent_litres(sched, 200), 4.0 / 7.0)
    # Unrestricted daily and weekly schedules are unchanged.
    sched["days"] = []
    assert _close(awc.daily_equivalent_litres(sched, 200), 4.0)
    weekly = {**sched, "period": "week", "amount": 14}
    assert _close(awc.daily_equivalent_litres(weekly, 200), 2.0)
    # Continuous keeps the plain period read (no run-slots to restrict).
    cont = {"enabled": True, "method": "continuous", "amountUnit": "litres",
            "amount": 4, "period": "day"}
    assert _close(awc.daily_equivalent_litres(cont, 200), 4.0)


def test_next_run_is_dst_safe_with_zoneinfo():
    try:
        from zoneinfo import ZoneInfo
    except ImportError:  # pragma: no cover
        return
    tz = ZoneInfo("Europe/London")
    # BST began 2026-03-29 01:00 UTC; a 02:00 slot after the changeover must
    # still read 02:00 wall-clock (the timedelta+replace form kept the old offset).
    now = datetime(2026, 3, 28, 12, 0, tzinfo=tz)
    sched = {"enabled": True, "method": "batch_sequential", "times": ["02:00"]}
    first = awc.next_run(sched, None, now)
    assert (first.hour, first.minute) == (2, 0)   # 02:00 on the 29th = first BST instant
    assert first.utcoffset() != now.utcoffset()   # crossed the change; wall clock held
    after = awc.next_run(sched, first, first + timedelta(minutes=1))
    assert (after.hour, after.minute) == (2, 0)
    assert after.date() == datetime(2026, 3, 30).date()  # the post-DST day, still 02:00


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
