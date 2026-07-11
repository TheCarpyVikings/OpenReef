"""Automatic Water Change — state machine, two-tier safety, ATO suspend, resume.

These exercise the REAL orchestration in ``__init__.py`` (start → leg → finalize,
abort/latch, pause/auto-resume, calibration, reservoir reset, ATO suspend, resume-to-
balance on restart) with Home Assistant stubbed (``_ha_stubs``) + faked (``_fake_ha``).
Legs are advanced by calling ``_async_awc_leg_complete`` directly (what the leg timer
would call), which keeps the flow deterministic; one test asserts the leg timer is
actually armed via the scheduler.

Run standalone:  python3 tests/test_awc_safety.py
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
import openreef as integration  # noqa: E402

from _fake_ha import FakeConnection, FakeEntry, FakeHass, install_scheduler, run  # noqa: E402

CONF_SETTINGS = integration.CONF_SETTINGS

_SENSORS = {
    "switch.awc_drain": "off",
    "switch.awc_fill": "off",
    "binary_sensor.leak": "off",
    "binary_sensor.high": "off",
    "binary_sensor.fresh_empty": "off",
    "binary_sensor.waste_full": "off",
}


def _awc_block(method="batch_sequential", **over):
    awc = {
        "enabled": True,
        "tankVolumeLitres": 200,
        "pumps": {
            "drain": {"switchEntity": "switch.awc_drain", "mlPerS": 100},
            "fill": {"switchEntity": "switch.awc_fill", "mlPerS": 100},
        },
        "reservoirs": {
            "fresh": {"capacityLitres": 25, "remainingMl": 25000, "emptyEntity": "binary_sensor.fresh_empty"},
            "waste": {"capacityLitres": 25, "filledMl": 0, "fullEntity": "binary_sensor.waste_full"},
        },
        "safety": {
            "highLevelEntity": "binary_sensor.high",
            "leakEntity": "binary_sensor.leak",
            "maxSingleChangePercent": 25,
        },
        "guards": {"quietHoursEnabled": False, "blockDuringFeed": True, "blockOnReturnPumpIssue": True},
        "ato": {"suspendDuringChange": True, "stabilizationHoldoffMinutes": 15},
        "schedule": {"method": method},
    }
    awc.update(over)
    return awc


def _entry(method="batch_sequential", equipment=None, awc_over=None):
    cfg = {"automaticWaterChange": _awc_block(method, **(awc_over or {}))}
    if equipment is not None:
        cfg["equipment"] = equipment
    return FakeEntry(options={CONF_SETTINGS: integration._normalise_core_config(cfg)})


def _hass(entry, states=None):
    s = dict(_SENSORS)
    s.update(states or {})
    return FakeHass(states=s, entries=[entry])


def _awc(entry):
    return entry.options[CONF_SETTINGS]["automaticWaterChange"]


def _state(entry):
    return _awc(entry)["state"]


def _has_call(calls, service, entity):
    return any(c.service == service and entity in c.data.values() for c in calls)


def _start(hass, entry, litres=2.0, method=None, manual=True):
    config = integration._config_from_entry(entry)
    return run(integration._async_awc_start(hass, entry, config, litres, method, manual, None))


def _fire_leg(hass, entry):
    config = integration._config_from_entry(entry)
    run(integration._async_awc_leg_complete(hass, entry, config, None))


def _drive(hass, entry, max_legs=12):
    for _ in range(max_legs):
        if _state(entry)["status"] not in integration._AWC_RUNNING_STATES:
            return
        _fire_leg(hass, entry)


def _close(a, b, tol=1.0):
    return abs(a - b) <= tol


# --- Happy paths -------------------------------------------------------------

def test_continuous_method_is_blocked():
    # continuous/trickle is projection-only; only sequential + simultaneous run live.
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    started, reasons = _start(hass, entry, 2.0, method="continuous")
    assert not started
    assert any(r["code"] == "unsupported_method" for r in reasons)
    assert _state(entry)["status"] == "idle"
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_drain")


def _fire_exchange(hass, entry, age_done=()):
    """Fire one simultaneous monitor tick. ``age_done`` lists roles ('drain'/'fill')
    whose stop time should be pushed into the past to simulate that pump finishing."""
    config = integration._config_from_entry(entry)
    st = config["automaticWaterChange"]["state"]
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    if "drain" in age_done:
        st["drainEndsAt"] = past
    if "fill" in age_done:
        st["fillEndsAt"] = past
    run(integration._async_awc_exchange_tick(hass, entry, config, None))


def test_sequential_drains_then_fills():
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    _start(hass, entry, 2.0, method="batch_sequential")
    assert _state(entry)["status"] == "draining"

    _fire_leg(hass, entry)  # drain done → fill leg
    assert _state(entry)["status"] == "filling"
    assert _has_call(hass.services.calls, "turn_on", "switch.awc_fill")

    _fire_leg(hass, entry)  # fill done → finalize
    awc = _awc(entry)
    assert awc["state"]["status"] == "idle"
    assert _close(awc["history"][0]["drainedL"], 2.0, 1e-6)
    assert _close(awc["history"][0]["filledL"], 2.0, 1e-6)


def test_new_run_clears_stale_simultaneous_timing_fields():
    entry = _entry("batch_sequential")
    st = _state(entry)
    st.update({
        "drainEndsAt": "2026-01-01T00:00:00+00:00",
        "fillEndsAt": "2026-01-01T00:00:00+00:00",
        "exchangeBaselineGapMl": 750,
    })
    hass = _hass(entry)
    _start(hass, entry, 2.0, method="batch_sequential")
    saved = _state(entry)
    assert saved["status"] == "draining"
    assert saved["drainEndsAt"] == ""
    assert saved["fillEndsAt"] == ""
    assert saved["exchangeBaselineGapMl"] == 0


def test_leg_timer_is_armed_via_scheduler():
    sched = install_scheduler(integration)
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    _start(hass, entry, 1.0)
    # Exactly the AWC leg timer should be pending (mode is 'running', nothing else arms).
    pending = sched.pending()
    assert len(pending) >= 1
    run(sched.fire_all())
    assert _state(entry)["status"] == "filling"
    run(sched.fire_all())
    assert _state(entry)["status"] == "idle"
    # restore real scheduler for subsequent tests
    install_scheduler(integration)


# --- Two-tier safety: faults latch -------------------------------------------

def test_leak_mid_change_latches_and_master_kills():
    equipment = {"rp": {"type": "return_pump", "armed": True, "switch_entity_id": "switch.rp"}}
    entry = _entry("batch_sequential", equipment=equipment)
    hass = _hass(entry, {"switch.rp": "on"})
    _start(hass, entry, 2.0, method="batch_sequential")
    # leak appears during the drain leg
    hass.states.set("binary_sensor.leak", "on")
    _fire_leg(hass, entry)  # drain done → safety check before fill → leak fault
    st = _state(entry)
    assert st["status"] == "fault" and "Leak" in st["fault"]
    assert _has_call(hass.services.calls, "turn_off", "switch.awc_drain")
    assert _has_call(hass.services.calls, "turn_off", "switch.awc_fill")
    assert _has_call(hass.services.calls, "turn_off", "switch.rp")  # master kill
    # latched fault keeps the ATO suspended
    assert integration._awc_ato_suspended(entry.options[CONF_SETTINGS]) is True
    # a partial change was recorded
    assert _awc(entry)["history"][0]["partial"] is True


def test_high_level_overfill_latches_without_master_kill():
    equipment = {"rp": {"type": "return_pump", "armed": True, "switch_entity_id": "switch.rp"}}
    entry = _entry("batch_sequential", equipment=equipment)
    hass = _hass(entry, {"switch.rp": "on"})
    _start(hass, entry, 2.0, method="batch_sequential")
    hass.states.set("binary_sensor.high", "on")
    _fire_leg(hass, entry)
    st = _state(entry)
    assert st["status"] == "fault" and "high-level" in st["fault"].lower()
    # high-level is NOT a master kill — the return pump is left running
    assert not _has_call(hass.services.calls, "turn_off", "switch.rp")


# --- Two-tier safety: benign limits pause + auto-resume ----------------------

def test_fresh_empty_pauses_then_resumes():
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    _start(hass, entry, 2.0, method="batch_sequential")
    hass.states.set("binary_sensor.fresh_empty", "on")
    _fire_leg(hass, entry)  # drain done → fill leg blocked by empty fresh reservoir
    assert _state(entry)["status"] == "paused"
    assert "Fresh" in _state(entry)["pausedReason"]

    # refill the reservoir and resume
    hass.states.set("binary_sensor.fresh_empty", "off")
    config = integration._config_from_entry(entry)
    resumed = run(integration._async_awc_try_resume(hass, entry, config, None))
    assert resumed is True
    assert _state(entry)["status"] == "filling"
    _drive(hass, entry)
    assert _state(entry)["status"] == "idle"
    assert _close(_awc(entry)["history"][0]["filledL"], 2.0, 1e-6)


def test_resume_blocked_stays_paused():
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    _start(hass, entry, 2.0, method="batch_sequential")
    hass.states.set("binary_sensor.fresh_empty", "on")
    _fire_leg(hass, entry)
    assert _state(entry)["status"] == "paused"
    # still empty → resume should fail and remain paused
    config = integration._config_from_entry(entry)
    resumed = run(integration._async_awc_try_resume(hass, entry, config, None))
    assert resumed is False
    assert _state(entry)["status"] == "paused"


# --- Start guards ------------------------------------------------------------

def test_start_blocked_when_uncalibrated():
    entry = _entry(awc_over={"pumps": {
        "drain": {"switchEntity": "switch.awc_drain", "mlPerS": 0},
        "fill": {"switchEntity": "switch.awc_fill", "mlPerS": 0},
    }})
    hass = _hass(entry)
    started, reasons = _start(hass, entry, 2.0)
    assert not started
    assert any(r["code"] == "no_calibration" for r in reasons)
    assert _state(entry)["status"] == "idle"


def test_start_blocked_by_leak():
    entry = _entry()
    hass = _hass(entry, {"binary_sensor.leak": "on"})
    started, reasons = _start(hass, entry, 2.0)
    assert not started
    assert any(r["code"] == "leak" and r["severity"] == "fault" for r in reasons)


def test_start_blocked_by_single_change_cap():
    entry = _entry()  # tank 200 L, cap 25% = 50 L
    hass = _hass(entry)
    started, reasons = _start(hass, entry, 60.0)
    assert not started
    assert any(r["code"] == "max_single_change" for r in reasons)


def test_start_blocked_when_paused():
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    _start(hass, entry, 2.0, method="batch_sequential")
    hass.states.set("binary_sensor.fresh_empty", "on")
    _fire_leg(hass, entry)
    assert _state(entry)["status"] == "paused"

    started, reasons = _start(hass, entry, 2.0, method="batch_sequential")
    assert not started
    assert any(r["code"] == "paused" for r in reasons)


def test_start_blocked_by_dead_reckoned_reservoir_capacity():
    entry = _entry(awc_over={"reservoirs": {
        "fresh": {"capacityLitres": 25, "remainingMl": 1000, "emptyEntity": "binary_sensor.fresh_empty"},
        "waste": {"capacityLitres": 25, "filledMl": 24500, "fullEntity": "binary_sensor.waste_full"},
    }})
    hass = _hass(entry)
    started, reasons = _start(hass, entry, 2.0)
    assert not started
    codes = {r["code"] for r in reasons}
    assert "fresh_insufficient" in codes
    assert "waste_insufficient" in codes


def test_pump_start_failure_latches_fault_and_stops_pumps():
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    original_call = hass.services.async_call

    async def fail_drain_start(domain, service, data=None, **kwargs):
        if domain == "switch" and service == "turn_on" and "switch.awc_drain" in (data or {}).values():
            raise RuntimeError("simulated switch failure")
        await original_call(domain, service, data, **kwargs)

    hass.services.async_call = fail_drain_start
    started, reasons = _start(hass, entry, 2.0, method="batch_sequential")
    assert not started
    assert any(r["code"] == "pump_start_failed" for r in reasons)
    assert _state(entry)["status"] == "fault"
    assert _has_call(hass.services.calls, "turn_off", "switch.awc_drain")
    assert _has_call(hass.services.calls, "turn_off", "switch.awc_fill")


# --- ATO coordination --------------------------------------------------------

def test_ato_suspended_during_change_and_blocks_turn_on():
    equipment = {"ato": {"type": "ato", "armed": True, "switch_entity_id": "switch.ato"}}
    entry = _entry("batch_sequential", equipment=equipment)
    hass = _hass(entry, {"switch.ato": "on"})
    _start(hass, entry, 2.0)
    # ATO physically turned off at start...
    assert _has_call(hass.services.calls, "turn_off", "switch.ato")
    config = entry.options[CONF_SETTINGS]
    assert integration._awc_ato_suspended(config) is True
    # ...and the safety gate blocks any attempt to turn the ATO back on
    mapped = config["equipment"]["ato"]
    reason = integration._equipment_safety_block_reason(hass, config, "ato", mapped, "on")
    assert "water change" in reason.lower()

    _drive(hass, entry)  # finalize → hold-off window
    # still suspended during the post-change stabilization hold-off
    assert integration._awc_ato_suspended(entry.options[CONF_SETTINGS]) is True


# --- Resume-to-balance on restart -------------------------------------------

def test_resume_to_balance_on_startup():
    # Simulate a crash at a leg boundary: drained 2 L, fill leg NOT yet begun (no stamps).
    entry = _entry("batch_sequential")
    awc = _awc(entry)
    awc["state"].update({
        "status": "filling", "method": "batch_sequential", "targetLitres": 2.0,
        "drainedMl": 2000, "filledMl": 0,
        "legStartedAt": "", "legEndsAt": "",
    })
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    run(integration._async_awc_resume_on_startup(hass, entry, config))
    # the fill leg is re-begun (resume-to-balance), pumps re-energised
    assert _state(entry)["status"] == "filling"
    assert _has_call(hass.services.calls, "turn_on", "switch.awc_fill")
    _drive(hass, entry)
    assert _state(entry)["status"] == "idle"
    assert _close(_awc(entry)["history"][0]["filledL"], 2.0, 1e-6)


def test_sequential_restart_mid_leg_credits_elapsed_no_replay():
    # Crash 8 s into a 20 s fill leg (100 ml/s): the elapsed 0.8 L must be CREDITED, and
    # the resumed leg must move only the remaining 1.2 L — not replay the whole 2 L
    # (the old behaviour: 0.8 L already in the tank + 2 L replay = 0.8 L overfill).
    entry = _entry("batch_sequential")
    awc = _awc(entry)
    now = datetime.now(timezone.utc)
    awc["state"].update({
        "status": "filling", "method": "batch_sequential", "targetLitres": 2.0,
        "drainedMl": 2000, "filledMl": 0,
        "legStartedAt": (now - timedelta(seconds=8)).isoformat(),
        "legEndsAt": (now + timedelta(seconds=12)).isoformat(),
    })
    awc["reservoirs"]["fresh"]["remainingMl"] = 25000
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    run(integration._async_awc_resume_on_startup(hass, entry, config))
    st = _state(entry)
    assert st["status"] == "filling"
    assert _close(st["filledMl"], 800.0, 20.0)  # ~8 s x 100 ml/s credited
    # the reservoir model was debited for the credited volume too
    assert _close(_awc(entry)["reservoirs"]["fresh"]["remainingMl"], 25000 - st["filledMl"], 1.0)
    _drive(hass, entry)
    assert _state(entry)["status"] == "idle"
    # total accounted fill is the 2 L target — nothing replayed
    assert _close(_awc(entry)["history"][0]["filledL"], 2.0, 0.05)


def test_sequential_restart_after_leg_elapsed_finalizes_no_replay():
    # Crash discovered AFTER the fill leg's whole window elapsed: full credit ⇒ the change
    # finalizes instead of re-pumping another 2 L into the tank.
    entry = _entry("batch_sequential")
    awc = _awc(entry)
    awc["state"].update({
        "status": "filling", "method": "batch_sequential", "targetLitres": 2.0,
        "drainedMl": 2000, "filledMl": 0,
        "legStartedAt": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
        "legEndsAt": (datetime.now(timezone.utc) - timedelta(minutes=4)).isoformat(),
    })
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    run(integration._async_awc_resume_on_startup(hass, entry, config))
    assert _state(entry)["status"] == "idle"
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_fill")
    assert _close(_awc(entry)["history"][0]["filledL"], 2.0, 1e-6)


# --- WebSocket handlers ------------------------------------------------------

def test_ws_run_now_blocked_returns_reasons():
    entry = _entry(awc_over={"pumps": {
        "drain": {"switchEntity": "", "mlPerS": 0},
        "fill": {"switchEntity": "", "mlPerS": 0},
    }})
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_awc_run_now(hass, conn, {"id": 1, "litres": 2}))
    assert not conn.errors, conn.error_codes
    payload = conn.results[0].payload
    assert payload["started"] is False
    assert any(r["code"] == "no_pump_entity" for r in payload["reasons"])


def test_ws_run_now_starts_then_abort():
    entry = _entry()
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_awc_run_now(hass, conn, {"id": 1, "litres": 2}))
    assert conn.results[0].payload["started"] is True
    assert _state(entry)["status"] == "draining"

    conn2 = FakeConnection()
    run(integration.websocket_awc_abort(hass, conn2, {"id": 2}))
    assert not conn2.errors
    assert _state(entry)["status"] == "idle"
    assert _has_call(hass.services.calls, "turn_off", "switch.awc_drain")


def test_ws_calibrate_single_and_multi_point():
    entry = _entry(awc_over={"pumps": {
        "drain": {"switchEntity": "switch.awc_drain", "mlPerS": 0},
        "fill": {"switchEntity": "switch.awc_fill", "mlPerS": 0},
    }})
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_awc_calibrate(hass, conn, {"id": 1, "role": "drain", "volume_ml": 500, "seconds": 10}))
    assert not conn.errors, conn.error_codes
    assert _close(_awc(entry)["pumps"]["drain"]["mlPerS"], 50.0, 1e-6)
    assert _awc(entry)["pumps"]["drain"]["calibratedAt"]

    # single-point ⇒ no priming offset (can't infer it from one point)
    assert _awc(entry)["pumps"]["drain"]["spinUpMl"] == 0.0

    conn2 = FakeConnection()
    run(integration.websocket_awc_calibrate(hass, conn2, {"id": 2, "role": "fill",
        "points": [[10, 520], [20, 1020], [30, 1520]]}))
    assert not conn2.errors, conn2.error_codes
    fill = _awc(entry)["pumps"]["fill"]
    assert _close(fill["mlPerS"], 50.0, 1e-6)
    assert _close(fill["interceptMl"], 20.0, 1e-6)
    # intercept 20 mL splits: bounded spin-up (cap = 3 s × 50 ml/s = 150 mL ⇒ all of it) + 0 prime
    assert _close(fill["spinUpMl"], 20.0, 1e-6)
    assert _close(fill["primeMl"], 0.0, 1e-6)

    # a slow pump with an over-large intercept clamps the per-dose spin-up and parks the rest in prime
    conn3 = FakeConnection()
    run(integration.websocket_awc_calibrate(hass, conn3, {"id": 3, "role": "drain",
        "points": [[10, 6], [60, 79]]}))  # slope ~1.46 ml/s, intercept ~ -8.6 mL
    assert not conn3.errors, conn3.error_codes
    drain = _awc(entry)["pumps"]["drain"]
    cap = max(5.0, 3.0 * drain["mlPerS"])  # AWC_SPINUP_MIN_CAP_ML / AWC_SPINUP_MAX_SECONDS
    assert abs(drain["spinUpMl"]) <= cap + 1e-6
    # spin-up + prime reconstruct the raw intercept
    assert _close(drain["spinUpMl"] + drain["primeMl"], drain["interceptMl"], 1e-3)


def test_ledger_outlives_history_cap_and_resets():
    # The persistent ledger must accumulate past AWC_HISTORY_MAX (100) — at hourly
    # micro-changes the capped history is only ~4 days and would silently blind the
    # net-imbalance number.
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    awc = integration._awc_cfg(config)
    now = datetime.now(timezone.utc)
    for _ in range(120):  # > the 100-event cap; drain 1.0 / fill 0.99 each (net −1.2 L)
        integration._awc_record_history(awc, now, 1.0, 0.99, "batch_sequential", False, "")
    assert len(awc["history"]) == 100
    assert _close(awc["ledger"]["cumulativeDrainedL"], 120.0, 1e-6)
    assert _close(awc["ledger"]["cumulativeFilledL"], 118.8, 1e-6)
    # summary reads the ledger, not the (truncated) history
    import openreef.awc as awc_engine
    s = awc_engine.summary(awc, now)
    assert _close(s["netImbalance"]["netL"], -1.2, 1e-6)
    assert _close(s["netImbalance"]["drainedL"], 120.0, 1e-6)

    # reset zeroes it and stamps resetAt
    conn = FakeConnection()
    run(integration.websocket_awc_reset_ledger(hass, conn, {"id": 1}))
    assert not conn.errors, conn.error_codes
    ledger = _awc(entry)["ledger"]
    assert ledger["cumulativeDrainedL"] == 0.0 and ledger["cumulativeFilledL"] == 0.0
    assert ledger["resetAt"]

    # tubing-replaced stamps the install date (the yearly tubing nag was dead
    # code end-to-end: nothing ever set tubingInstalledAt — hardening T6)
    run(integration.websocket_awc_tubing_replaced(hass, conn, {"id": 2, "role": "drain"}))
    assert not conn.errors, conn.error_codes
    assert _awc(entry)["pumps"]["drain"]["tubingInstalledAt"]
    run(integration.websocket_awc_tubing_replaced(hass, conn, {"id": 3, "role": "bogus"}))
    assert "invalid_role" in conn.error_codes


def test_ledger_seeds_from_history_on_upgrade():
    # A pre-ledger config (history only) seeds the ledger from the summed history so the
    # displayed net-imbalance is continuous across the migration.
    entry = _entry(awc_over={"history": [
        {"completedAt": "2026-07-01T00:00:00+00:00", "drainedL": 5.0, "filledL": 4.8,
         "method": "batch_sequential", "partial": False, "notes": ""},
    ] * 3})
    ledger = _awc(entry)["ledger"]
    assert _close(ledger["cumulativeDrainedL"], 15.0, 1e-6)
    assert _close(ledger["cumulativeFilledL"], 14.4, 1e-6)


def test_pump_odometers_accumulate():
    # A full 2 L sequential change at 100 ml/s: each pump gains 1 start and ~20 s runtime.
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    _drive(hass, entry)
    assert _state(entry)["status"] == "idle"
    pumps = _awc(entry)["pumps"]
    assert pumps["drain"]["startCount"] == 1
    assert pumps["fill"]["startCount"] == 1
    assert _close(pumps["drain"]["runSeconds"], 20.0, 0.5)
    assert _close(pumps["fill"]["runSeconds"], 20.0, 0.5)


def test_concurrent_starts_only_one_wins():
    # Two overlapping starts (e.g. scheduler tick + manual run-now) must serialise on the
    # AWC state lock: exactly one begins, the other reports "busy" — never a double-start
    # that would run both prefights against the same idle state.
    import asyncio

    entry = _entry("batch_sequential")
    hass = _hass(entry)
    config = integration._config_from_entry(entry)

    async def both():
        return await asyncio.gather(
            integration._async_awc_start(hass, entry, config, 2.0, "batch_sequential", True, None),
            integration._async_awc_start(hass, entry, config, 2.0, "batch_sequential", True, None),
        )

    r1, r2 = run(both())
    results = [r1, r2]
    assert sum(1 for started, _ in results if started) == 1
    blocked = next(reasons for started, reasons in results if not started)
    assert {r["code"] for r in blocked} & {"busy", "paused"} == {"busy"}
    # exactly one drain turn_on was issued
    ons = [c for c in hass.services.calls if c.service == "turn_on" and "switch.awc_drain" in c.data.values()]
    assert len(ons) == 1


def test_leak_sensor_unavailable_pauses_not_faults():
    # Fail-closed: the configured leak sensor going unavailable mid-change pauses (pumps
    # off, no latch) and the change auto-resumes once the sensor reports again.
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]

    hass.states.set("binary_sensor.leak", "unavailable")
    _fire_leg(hass, entry)
    assert _state(entry)["status"] == "paused"
    assert "unavailable" in _state(entry)["pausedReason"].lower()
    assert _has_call(hass.services.calls, "turn_off", "switch.awc_drain")

    # sensor recovers → resume completes the change
    hass.states.set("binary_sensor.leak", "off")
    config = integration._config_from_entry(entry)
    assert run(integration._async_awc_try_resume(hass, entry, config, None))
    _drive(hass, entry)
    assert _state(entry)["status"] == "idle"


def test_start_blocked_when_leak_sensor_unavailable():
    entry = _entry("batch_sequential")
    hass = _hass(entry, states={"binary_sensor.leak": "unavailable"})
    started, reasons = _start(hass, entry, 2.0, method="batch_sequential")
    assert not started
    assert "leak_unavailable" in {r["code"] for r in reasons}


def test_abort_best_effort_stops_all_pumps_and_latches():
    # A failed turn_off on ONE pump must not strand the other or skip the fault latch/save.
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    config = integration._config_from_entry(entry)

    real_call = hass.services.async_call

    async def flaky(domain, service, data=None, **kwargs):
        if service == "turn_off" and "switch.awc_drain" in (data or {}).values():
            raise RuntimeError("switch unavailable")
        return await real_call(domain, service, data, **kwargs)

    hass.services.async_call = flaky
    run(integration._async_awc_abort(hass, entry, config, "test fault", True, False, None))

    # the fill pump was still commanded off despite the drain turn_off raising
    assert _has_call(hass.services.calls, "turn_off", "switch.awc_fill")
    # and the state transition completed: fault latched (not left mid-abort)
    assert _state(entry)["status"] == "fault"
    assert _state(entry)["fault"] == "test fault"


def test_ws_acknowledge_clears_fault():
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    _start(hass, entry, 2.0, method="batch_sequential")
    hass.states.set("binary_sensor.leak", "on")
    _fire_leg(hass, entry)
    assert _state(entry)["status"] == "fault"

    conn = FakeConnection()
    run(integration.websocket_awc_acknowledge(hass, conn, {"id": 1}))
    assert conn.error_codes == ["hazard_active"]
    assert _state(entry)["status"] == "fault"

    hass.states.set("binary_sensor.leak", "off")
    conn = FakeConnection()
    run(integration.websocket_awc_acknowledge(hass, conn, {"id": 2}))
    assert not conn.errors, conn.error_codes
    st = _state(entry)
    assert st["status"] == "idle" and st["fault"] == ""
    assert integration._awc_ato_suspended(entry.options[CONF_SETTINGS]) is False


def test_ws_summary_returns_metrics():
    entry = _entry()
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_awc_summary(hass, conn, {"id": 1}))
    assert not conn.errors, conn.error_codes
    payload = conn.results[0].payload
    assert "summary" in payload and "reservoirs" in payload["summary"]
    assert "live" in payload and "state" in payload
    assert payload["summary"]["reservoirs"]["fresh"]["percent"] == 100.0


def test_ws_reset_reservoir():
    entry = _entry(awc_over={"reservoirs": {
        "fresh": {"capacityLitres": 25, "remainingMl": 1000, "emptyEntity": ""},
        "waste": {"capacityLitres": 25, "filledMl": 20000, "fullEntity": ""},
    }})
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_awc_reset_reservoir(hass, conn, {"id": 1, "reservoir": "fresh"}))
    assert _close(_awc(entry)["reservoirs"]["fresh"]["remainingMl"], 25000)
    conn2 = FakeConnection()
    run(integration.websocket_awc_reset_reservoir(hass, conn2, {"id": 2, "reservoir": "waste"}))
    assert _awc(entry)["reservoirs"]["waste"]["filledMl"] == 0


# --- Phase 3: scheduler tick (batch + continuous + auto-resume) --------------

def _sched_entry(method, **sched):
    base = {"enabled": True, "method": method, "amountUnit": "litres",
            "amount": 4, "period": "day", "times": ["02:00"], "days": []}
    base.update(sched)
    return _entry(method, awc_over={"schedule": base})


def _now(h, m, day=17):
    return datetime(2026, 6, day, h, m, tzinfo=timezone.utc)  # 2026-06-17 is a Wednesday


def test_scheduler_starts_due_sequential_change():
    entry = _sched_entry("batch_sequential")
    hass = _hass(entry)
    run(integration._async_awc_schedule_tick(hass, entry, _now(2, 30)))
    st = _state(entry)
    assert st["status"] == "draining"
    assert _close(st["targetLitres"], 4.0, 1e-6)


def test_scheduler_skips_before_due_time():
    entry = _sched_entry("batch_sequential")
    hass = _hass(entry)
    run(integration._async_awc_schedule_tick(hass, entry, _now(1, 0)))
    assert _state(entry)["status"] == "idle"
    # nextRun is surfaced for the panel
    assert _state(entry)["nextRun"]


def test_scheduler_legacy_continuous_is_migrated_to_sequential():
    entry = _sched_entry("continuous", windowStart="00:00", windowEnd="00:00", amount=4.8)
    hass = _hass(entry)
    run(integration._async_awc_schedule_tick(hass, entry, _now(12, 0)))
    assert _awc(entry)["schedule"]["method"] == "batch_sequential"
    assert _state(entry)["status"] == "draining"
    assert _close(_state(entry)["targetLitres"], 4.8, 1e-6)


def test_scheduler_runs_simultaneous():
    entry = _sched_entry("batch_simultaneous")
    hass = _hass(entry)
    run(integration._async_awc_schedule_tick(hass, entry, _now(2, 30)))
    assert _awc(entry)["schedule"]["method"] == "batch_simultaneous"
    assert _state(entry)["status"] == "exchanging"


def test_scheduler_does_nothing_when_schedule_disabled():
    entry = _sched_entry("batch_sequential", enabled=False)
    hass = _hass(entry)
    run(integration._async_awc_schedule_tick(hass, entry, _now(2, 30)))
    assert _state(entry)["status"] == "idle"


def test_scheduler_auto_resumes_paused_change():
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    _start(hass, entry, 2.0, method="batch_sequential")
    hass.states.set("binary_sensor.fresh_empty", "on")
    _fire_leg(hass, entry)
    assert _state(entry)["status"] == "paused"
    # reservoir refilled; the periodic tick recovers it
    hass.states.set("binary_sensor.fresh_empty", "off")
    run(integration._async_awc_schedule_tick(hass, entry, _now(3, 0)))
    assert _state(entry)["status"] == "filling"


# --- Simultaneous (independent per-pump timers + imbalance abort) ------------

def test_simultaneous_starts_both_pumps():
    entry = _entry("batch_simultaneous")
    hass = _hass(entry)
    started, reasons = _start(hass, entry, 2.0, method="batch_simultaneous")
    assert started and not reasons
    assert _state(entry)["status"] == "exchanging"
    assert _has_call(hass.services.calls, "turn_on", "switch.awc_drain")
    assert _has_call(hass.services.calls, "turn_on", "switch.awc_fill")
    # each pump got its own stop time
    assert _state(entry)["drainEndsAt"] and _state(entry)["fillEndsAt"]


def test_simultaneous_completes_balanced():
    entry = _entry("batch_simultaneous")
    hass = _hass(entry)
    _start(hass, entry, 2.0, method="batch_simultaneous")
    _fire_exchange(hass, entry, age_done=("drain", "fill"))  # both pumps reached their stop
    awc = _awc(entry)
    assert awc["state"]["status"] == "idle"
    assert _has_call(hass.services.calls, "turn_off", "switch.awc_drain")
    assert _has_call(hass.services.calls, "turn_off", "switch.awc_fill")
    assert len(awc["history"]) == 1 and not awc["history"][0]["partial"]
    assert _close(awc["history"][0]["drainedL"], 2.0, 1e-3)
    assert _close(awc["history"][0]["filledL"], 2.0, 1e-3)


def test_simultaneous_fast_pump_does_not_overpump():
    # drain 100 ml/s (fast), fill 50 ml/s (slow): for 1 L, drain ends at 10s, fill at 20s.
    entry = _entry("batch_simultaneous", awc_over={"pumps": {
        "drain": {"switchEntity": "switch.awc_drain", "mlPerS": 100},
        "fill": {"switchEntity": "switch.awc_fill", "mlPerS": 50},
        # generous imbalance cap so this test isolates the over-pump check
    }, "safety": {"highLevelEntity": "binary_sensor.high", "leakEntity": "binary_sensor.leak",
                  "maxSingleChangePercent": 25, "maxInstantaneousImbalanceLitres": 5}})
    hass = _hass(entry)
    _start(hass, entry, 1.0, method="batch_simultaneous")
    # drain finishes first; its own timer stops it at exactly target — no over-pump
    _fire_exchange(hass, entry, age_done=("drain",))
    st = _state(entry)
    assert st["status"] == "exchanging"               # fill still running
    assert _close(st["drainedMl"], 1000.0, 1.0)        # drain capped at target
    assert st["drainedMl"] <= 1000.0 + 1e-6            # never exceeds target
    assert _has_call(hass.services.calls, "turn_off", "switch.awc_drain")
    # then fill finishes → finalize, balanced
    _fire_exchange(hass, entry, age_done=("drain", "fill"))
    assert _state(entry)["status"] == "idle"
    assert _close(_awc(entry)["history"][0]["filledL"], 1.0, 1e-3)


def test_simultaneous_start_blocked_when_pumps_too_mismatched():
    # Very mismatched pumps (100/10) ⇒ predicted ~0.9 L sump swing for a 1 L change
    # exceeds the 0.1 L cap ⇒ blocked at START (never starts → never a mid-run abort).
    entry = _entry("batch_simultaneous", awc_over={"pumps": {
        "drain": {"switchEntity": "switch.awc_drain", "mlPerS": 100},
        "fill": {"switchEntity": "switch.awc_fill", "mlPerS": 10},
    }, "safety": {"highLevelEntity": "binary_sensor.high", "leakEntity": "binary_sensor.leak",
                  "maxSingleChangePercent": 25, "maxInstantaneousImbalanceLitres": 0.1}})
    hass = _hass(entry)
    started, reasons = _start(hass, entry, 1.0, method="batch_simultaneous")
    assert not started
    assert any(r["code"] == "imbalance_too_large" for r in reasons)
    assert _state(entry)["status"] == "idle"
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_drain")


def test_simultaneous_intermediate_tick_no_false_abort():
    # Regression: a healthy rate-mismatched pair (100/50) must NOT false-abort on a real
    # mid-run tick. 2 L peak swing = 1.0 L, so a 1.5 L cap allows the start; the gap grows
    # to 1.0 L mid-run and must stay 'exchanging'.
    entry = _entry("batch_simultaneous", awc_over={"pumps": {
        "drain": {"switchEntity": "switch.awc_drain", "mlPerS": 100},
        "fill": {"switchEntity": "switch.awc_fill", "mlPerS": 50},
    }, "safety": {"highLevelEntity": "binary_sensor.high", "leakEntity": "binary_sensor.leak",
                  "maxSingleChangePercent": 25, "maxInstantaneousImbalanceLitres": 1.5}})
    hass = _hass(entry)
    started, reasons = _start(hass, entry, 2.0, method="batch_simultaneous")
    assert started, reasons
    # Simulate a consistent t=20 s: drain just finished, fill has 20 s of its 40 s left.
    config = integration._config_from_entry(entry)
    st = config["automaticWaterChange"]["state"]
    now = datetime.now(timezone.utc)
    st["drainEndsAt"] = now.isoformat()
    st["fillEndsAt"] = (now + timedelta(seconds=20)).isoformat()
    run(integration._async_awc_exchange_tick(hass, entry, config, None))
    s2 = _state(entry)
    assert s2["status"] == "exchanging"           # 1.0 L gap < 1.5 L cap ⇒ no abort
    assert _close(s2["drainedMl"], 2000, 5) and _close(s2["filledMl"], 1000, 40)


def test_simultaneous_resume_to_balance_only_restarts_unfinished_side():
    # crash after drain done (2 L) but fill only 0.5 L: resume must NOT re-run drain,
    # and the 1.5 L pre-existing gap must NOT false-abort (re-baselined imbalance cap).
    entry = _entry("batch_simultaneous")  # default cap 0.5 L — would abort without baseline
    awc = _awc(entry)
    awc["state"].update({
        "status": "exchanging", "method": "batch_simultaneous", "targetLitres": 2.0,
        "drainedMl": 2000, "filledMl": 500,
    })
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    run(integration._async_awc_resume_on_startup(hass, entry, config))
    st = _state(entry)
    assert st["status"] == "exchanging"
    assert _close(st["exchangeBaselineGapMl"], 1500, 1)
    # fill restarts, drain does NOT (already complete)
    assert _has_call(hass.services.calls, "turn_on", "switch.awc_fill")
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_drain")
    # a real intermediate tick (fill half-done) must NOT abort despite the big gap
    config = integration._config_from_entry(entry)
    now = datetime.now(timezone.utc)
    config["automaticWaterChange"]["state"]["fillEndsAt"] = (now + timedelta(seconds=7.5)).isoformat()
    run(integration._async_awc_exchange_tick(hass, entry, config, None))
    assert _state(entry)["status"] == "exchanging"
    _fire_exchange(hass, entry, age_done=("drain", "fill"))
    assert _state(entry)["status"] == "idle"
    assert _close(_awc(entry)["history"][0]["filledL"], 2.0, 1e-3)


def test_simultaneous_resume_uncalibrated_faults_not_completes():
    # both pumps uncalibrated on resume must FAULT, never finalize as a phantom complete.
    entry = _entry("batch_simultaneous", awc_over={"pumps": {
        "drain": {"switchEntity": "switch.awc_drain", "mlPerS": 0},
        "fill": {"switchEntity": "switch.awc_fill", "mlPerS": 0},
    }})
    awc = _awc(entry)
    awc["state"].update({
        "status": "exchanging", "method": "batch_simultaneous", "targetLitres": 2.0,
        "drainedMl": 0, "filledMl": 0,
    })
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    run(integration._async_awc_resume_on_startup(hass, entry, config))
    st = _state(entry)
    assert st["status"] == "fault" and "calibrat" in st["fault"].lower()
    assert not _awc(entry)["history"]  # never recorded a (zero-volume) completion


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
