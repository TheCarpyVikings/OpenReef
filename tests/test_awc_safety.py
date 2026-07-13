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
    return run(integration._async_awc_start(hass, entry, litres, method, manual, None))


def _fire_leg(hass, entry):
    run(integration._async_awc_leg_complete(hass, entry, None))


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
    """Fire one simultaneous monitor tick. ``age_done`` lists roles ('drain'/'fill'/
    'fill2') whose stop time should be pushed into the past to simulate that pump
    finishing. Timing is edited in the entry's STORED options — the handler fetches
    fresh config inside the lock, so a mutated local copy would be invisible to it."""
    st = _state(entry)
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    for role in age_done:
        st.setdefault("endsAt", {})[role] = past
    run(integration._async_awc_exchange_tick(hass, entry, None))


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
        "endsAt": {"drain": "2026-01-01T00:00:00+00:00", "fill": "2026-01-01T00:00:00+00:00"},
        "exchangeBaselineNetMl": 750,
    })
    hass = _hass(entry)
    _start(hass, entry, 2.0, method="batch_sequential")
    saved = _state(entry)
    assert saved["status"] == "draining"
    assert not saved["endsAt"].get("drain")
    assert not saved["endsAt"].get("fill")
    assert saved["exchangeBaselineNetMl"] == 0


def test_leg_timer_is_armed_via_scheduler():
    sched = install_scheduler(integration)
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    _start(hass, entry, 1.0)
    # Exactly the AWC leg timer should be pending (mode is 'running', nothing else arms).
    pending = sched.pending()
    assert len(pending) >= 1
    # Before the leg's scheduled end the fired timer is a SAFETY CHECKPOINT (R9): it
    # must NOT complete the leg, and it must re-arm itself so monitoring continues.
    run(sched.fire_all())
    assert _state(entry)["status"] == "draining"
    assert sched.pending()
    # Once the scheduled end has passed, the fired timer completes the leg.
    _state(entry)["legEndsAt"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    run(sched.fire_all())
    assert _state(entry)["status"] == "filling"
    _state(entry)["legEndsAt"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
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
    resumed = run(integration._async_awc_try_resume(hass, entry, None))
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
    resumed = run(integration._async_awc_try_resume(hass, entry, None))
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
        "movedMl": {"drain": 2000, "fill": 0},
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
        "movedMl": {"drain": 2000, "fill": 0},
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
    assert _close(st["movedMl"]["fill"], 800.0, 20.0)  # ~8 s x 100 ml/s credited
    # the reservoir model was debited for the credited volume too
    assert _close(_awc(entry)["reservoirs"]["fresh"]["remainingMl"], 25000 - st["movedMl"]["fill"], 1.0)
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
        "movedMl": {"drain": 2000, "fill": 0},
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

    async def both():
        # Each start fetches its own config INSIDE the lock (the R1 refactor), so the
        # loser sees the winner's saved 'draining' status — this used to pass only
        # because both shared one config dict, masking the stale-snapshot race.
        return await asyncio.gather(
            integration._async_awc_start(hass, entry, 2.0, "batch_sequential", True, None),
            integration._async_awc_start(hass, entry, 2.0, "batch_sequential", True, None),
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
    assert run(integration._async_awc_try_resume(hass, entry, None))
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
    # tick within the slot's freshness window (a 10 h-stale slot now expires, T7)
    run(integration._async_awc_schedule_tick(hass, entry, _now(3, 0)))
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


def _interval_entry(**sched_over):
    base = {"enabled": True, "method": "batch_sequential", "mode": "interval",
            "everyMinutes": 60, "windowStart": "00:00", "windowEnd": "00:00",
            "amount": 0.96, "amountUnit": "litres", "period": "day"}
    base.update(sched_over)
    return _entry("batch_sequential", awc_over={"schedule": base})


def test_interval_schedule_starts_micro_change():
    # Hourly 40 ml micro-changes: a tick just past a slot starts ONE change at the
    # per-slot volume (Stage A cadence headline).
    entry = _interval_entry()
    _state(entry)["lastRun"] = _now(1, 30).isoformat()  # served through 01:30
    hass = _hass(entry)
    run(integration._async_awc_schedule_tick(hass, entry, _now(2, 1)))
    st = _state(entry)
    assert st["status"] == "draining"
    assert _close(st["targetLitres"], 0.04, 1e-6)


def test_interval_missed_slots_coalesce_into_one_change():
    # HA down 02:00→04:55: slots 02/03/04 unserved and fresh → ONE 3× catch-up
    # change, never three back-to-back micro-changes.
    entry = _interval_entry()
    _state(entry)["lastRun"] = _now(1, 30).isoformat()
    hass = _hass(entry)
    run(integration._async_awc_schedule_tick(hass, entry, _now(4, 55)))
    st = _state(entry)
    assert st["status"] == "draining"
    assert _close(st["targetLitres"], 0.12, 1e-6)  # 3 × 40 ml, one change


def test_interval_coalesce_clamped_to_single_change_cap():
    # A big catch-up is clamped to the single-change salinity guardrail, not blocked.
    entry = _entry("batch_sequential", awc_over={
        "schedule": {"enabled": True, "method": "batch_sequential", "mode": "interval",
                     "everyMinutes": 60, "windowStart": "00:00", "windowEnd": "00:00",
                     "amount": 96, "amountUnit": "litres", "period": "day"},
        "safety": {"highLevelEntity": "binary_sensor.high", "leakEntity": "binary_sensor.leak",
                   "maxSingleChangePercent": 3},
    })
    _state(entry)["lastRun"] = _now(1, 30).isoformat()
    hass = _hass(entry)
    run(integration._async_awc_schedule_tick(hass, entry, _now(4, 55)))
    st = _state(entry)
    assert st["status"] == "draining"
    assert _close(st["targetLitres"], 6.0, 1e-6)  # 3 × 4 L clamped to 3% of 200 L


def test_editing_interval_cadence_rearms_schedule():
    # everyMinutes/window edits move slots — they must re-arm like a times edit (R24).
    entry = _interval_entry()
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    config["automaticWaterChange"]["schedule"]["everyMinutes"] = 120
    run(integration._async_save_config(hass, entry, config))
    assert _state(entry)["scheduleArmedAt"]


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


# --- Wave 7: reconciliation & slot semantics ----------------------------------

def test_abort_consumes_schedule_slot_no_restart_loop():
    # A user Stop must consume the slot (R7): the next minutely tick used to see an
    # idle state with an unserved slot and restart the change 60 s later — all day.
    entry = _sched_entry("batch_sequential")
    hass = _hass(entry)
    run(integration._async_awc_schedule_tick(hass, entry, _now(2, 30)))
    assert _state(entry)["status"] == "draining"
    conn = FakeConnection()
    run(integration.websocket_awc_abort(hass, conn, {"id": 1}))
    assert _state(entry)["status"] == "idle"
    assert _state(entry)["lastRun"]
    run(integration._async_awc_schedule_tick(hass, entry, _now(2, 31)))
    assert _state(entry)["status"] == "idle"  # not restarted


def test_enabling_schedule_does_not_fire_passed_slot():
    # Enabling a schedule whose slot already passed today must wait for the slot's
    # next occurrence, not start a change on the spot (R24).
    entry = _sched_entry("batch_sequential", enabled=False)
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    config["automaticWaterChange"]["schedule"]["enabled"] = True
    run(integration._async_save_config(hass, entry, config))
    assert _state(entry)["scheduleArmedAt"]
    run(integration._async_awc_schedule_tick(hass, entry, _now(3, 0)))
    assert _state(entry)["status"] == "idle"


def test_enabling_master_awc_does_not_fire_passed_slot():
    # The MASTER AWC toggle re-enables the tick just like a schedule enable — it must
    # re-arm the slot semantics too (vacation pattern: disable AWC, re-enable in the
    # morning; the overnight slot must not fire on the spot).
    entry = _sched_entry("batch_sequential")
    _awc(entry)["enabled"] = False
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    config["automaticWaterChange"]["enabled"] = True
    run(integration._async_save_config(hass, entry, config))
    assert _state(entry)["scheduleArmedAt"]
    run(integration._async_awc_schedule_tick(hass, entry, _now(3, 0)))
    assert _state(entry)["status"] == "idle"


def test_race_duplicate_resume_single_relaunch():
    # Two resumes racing (the minutely auto-resume + a manual click, or a double
    # click): exactly one relaunches; the loser must NOT stop-and-restart the leg
    # the winner just began.
    import asyncio

    entry = _entry("batch_sequential")
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    hass.states.set("binary_sensor.fresh_empty", "on")
    _fire_leg(hass, entry)  # drain credited; fill leg blocked → paused
    assert _state(entry)["status"] == "paused"
    hass.states.set("binary_sensor.fresh_empty", "off")

    async def both():
        return await asyncio.gather(
            integration._async_awc_try_resume(hass, entry, None),
            integration._async_awc_try_resume(hass, entry, None),
        )

    r1, r2 = run(both())
    assert sorted([r1, r2]) == [False, True]  # exactly one resumed
    assert _state(entry)["status"] == "filling"
    ons = [c for c in _switch_calls(hass, "switch.awc_fill") if c.service == "turn_on"]
    assert len(ons) == 1


def test_state_saves_do_not_rearm_schedule():
    # Ordinary state saves (leg transitions, activity) leave the schedule armed-stamp
    # alone — only slot-defining edits re-arm (R24).
    entry = _sched_entry("batch_sequential")
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    run(integration._async_save_config(hass, entry, config))
    assert not _state(entry)["scheduleArmedAt"]
    run(integration._async_awc_schedule_tick(hass, entry, _now(2, 30)))
    assert _state(entry)["status"] == "draining"  # the pending slot still fires


def test_blocked_scheduled_start_logged_once_per_slot():
    # A due schedule blocked by an unavailable leak sensor is surfaced ONCE per slot
    # (activity + notification), not every minute (T7).
    entry = _sched_entry("batch_sequential")
    hass = _hass(entry, states={"binary_sensor.leak": "unavailable"})
    run(integration._async_awc_schedule_tick(hass, entry, _now(2, 30)))
    assert _state(entry)["status"] == "idle"
    run(integration._async_awc_schedule_tick(hass, entry, _now(2, 31)))
    notes = [c for c in hass.services.calls
             if c.domain == "persistent_notification"
             and c.data.get("notification_id") == "openreef_awc_blocked"]
    assert len(notes) == 1
    acts = [a for a in integration._config_from_entry(entry).get("activity", [])
            if "blocked" in a.get("message", "")]
    assert len(acts) == 1
    # the sensor recovers within the slot's freshness window → the change starts
    hass.states.set("binary_sensor.leak", "off")
    run(integration._async_awc_schedule_tick(hass, entry, _now(2, 40)))
    assert _state(entry)["status"] == "draining"


def test_stale_blocked_slot_expires_instead_of_firing():
    # Blocked all morning: once the slot is > 4 h stale the tick consumes it (T7) —
    # the blocker clearing at 06:30 must NOT fire a surprise water change.
    entry = _sched_entry("batch_sequential")
    hass = _hass(entry, states={"binary_sensor.leak": "unavailable"})
    run(integration._async_awc_schedule_tick(hass, entry, _now(2, 30)))  # blocked, logged
    hass.states.set("binary_sensor.leak", "off")
    run(integration._async_awc_schedule_tick(hass, entry, _now(6, 30)))  # 4.5 h stale
    st = _state(entry)
    assert st["status"] == "idle"
    assert st["lastRun"]  # slot consumed
    acts = [a for a in integration._config_from_entry(entry).get("activity", [])
            if "expired" in a.get("message", "")]
    assert len(acts) == 1
    run(integration._async_awc_schedule_tick(hass, entry, _now(6, 31)))
    assert _state(entry)["status"] == "idle"


def test_config_export_strips_runtime_records():
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    config["activity"] = [{"timestamp": "t", "message": "m", "type": "info"}]
    run(integration._async_save_config(hass, entry, config))
    conn = FakeConnection()
    run(integration.websocket_config_export(hass, conn, {"id": 1}))
    payload = conn.results[0].payload
    assert payload["kind"] == "openreef-config"
    assert payload["schema"] == integration.CORE_SCHEMA_VERSION
    assert "activity" not in payload["config"]
    assert "automaticWaterChange" in payload["config"]


def test_config_import_roundtrip_sanitizes_state():
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_config_export(hass, conn, {"id": 1}))
    payload = conn.results[0].payload
    # tamper the backup the way a real restore differs: a setting change, a stale
    # running state, demo mode left on, a channel claiming firmware sync
    payload["config"]["automaticWaterChange"]["schedule"]["enabled"] = True
    payload["config"]["automaticWaterChange"]["state"] = {
        "status": "exchanging", "drainedMl": 500}
    payload["config"]["automaticWaterChange"]["simulation"] = {"enabled": True}
    payload["config"].setdefault("dosing", {}).setdefault("channels", {})["kalk"] = {
        "name": "Kalk", "chemical": "kalk", "sync": {"state": "synced"}}
    conn2 = FakeConnection()
    run(integration.websocket_config_import(hass, conn2, {"id": 2, "payload": payload}))
    assert not conn2.errors, conn2.error_codes
    cfg = integration._config_from_entry(entry)
    awc = integration._awc_cfg(cfg)
    assert awc["schedule"]["enabled"] is True     # the SETTING imported
    assert awc["state"]["status"] == "idle"       # the STATE did not
    assert awc["simulation"]["enabled"] is False  # demo mode never restores silently
    kalk = cfg["dosing"]["channels"]["kalk"]
    assert kalk["sync"]["state"] == "unsynced"    # re-syncs against real firmware


def test_config_import_rejections():
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_config_import(hass, conn, {"id": 1, "payload": {"kind": "nope"}}))
    assert "invalid_payload" in conn.error_codes
    conn2 = FakeConnection()
    run(integration.websocket_config_import(hass, conn2, {"id": 2, "payload": {
        "kind": "openreef-config", "schema": integration.CORE_SCHEMA_VERSION + 1,
        "config": {}}}))
    assert "newer_schema" in conn2.error_codes
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    conn3 = FakeConnection()
    run(integration.websocket_config_import(hass, conn3, {"id": 3, "payload": {
        "kind": "openreef-config", "schema": 1, "config": {}}}))
    assert "busy" in conn3.error_codes


def test_calibration_run_times_out_and_blocks_scheduler():
    sched = install_scheduler(integration)
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_awc_calibration_run(
        hass, conn, {"id": 1, "role": "fill", "seconds": 30}))
    assert not conn.errors, conn.error_codes
    assert hass.states.get("switch.awc_fill").state == "on"
    # a second run and any change start are blocked while it's in flight
    conn2 = FakeConnection()
    run(integration.websocket_awc_calibration_run(
        hass, conn2, {"id": 2, "role": "drain", "seconds": 30}))
    assert "busy" in conn2.error_codes
    started, reasons = _start(hass, entry, 2.0, method="batch_sequential")
    assert not started and any(r["code"] == "busy" for r in reasons)
    # the stop timer fires → pump off, odometer bumped, sandbox free again
    run(sched.fire_all())
    assert hass.states.get("switch.awc_fill").state == "off"
    assert _close(_awc(entry)["pumps"]["fill"]["runSeconds"], 30.0, 0.5)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    install_scheduler(integration)


def test_sim_mode_runs_change_with_zero_real_actuation():
    # Demo mode: a full change completes with NO switch service calls; virtual pump
    # states are recorded; dead-reckoned reservoirs/history still move (the demo).
    entry = _entry("batch_sequential", awc_over={"simulation": {"enabled": True}})
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    assert not [c for c in hass.services.calls if c.domain == "switch"]
    sim_pumps = hass.data[integration.DOMAIN][integration.AWC_RUNTIME]["simPumps"]
    assert sim_pumps.get("drain") is True
    _drive(hass, entry)
    assert _state(entry)["status"] == "idle"
    assert not [c for c in hass.services.calls if c.domain == "switch"]
    assert _close(_awc(entry)["history"][0]["filledL"], 2.0, 1e-6)
    sim_pumps = hass.data[integration.DOMAIN][integration.AWC_RUNTIME]["simPumps"]
    assert sim_pumps.get("drain") is False and sim_pumps.get("fill") is False


def test_sim_mode_needs_no_pump_entities():
    # The demo works on a box with zero hardware configured.
    entry = _entry("batch_sequential", awc_over={
        "simulation": {"enabled": True},
        "pumps": {"drain": {"switchEntity": "", "mlPerS": 100},
                  "fill": {"switchEntity": "", "mlPerS": 100}}})
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    _drive(hass, entry)
    assert _state(entry)["status"] == "idle"


def test_sim_hazard_injection_blocks_and_faults():
    # An injected leak blocks a start, and injected mid-run it latches a fault via
    # the checkpoint — the real two-tier policy, virtually, zero real actuation.
    entry = _entry("batch_sequential", awc_over={
        "simulation": {"enabled": True, "hazards": {"leak": True}}})
    hass = _hass(entry)
    started, reasons = _start(hass, entry, 2.0, method="batch_sequential")
    assert not started and any("leak" in r["code"] for r in reasons)
    conn = FakeConnection()
    run(integration.websocket_awc_sim_set(hass, conn, {"id": 1, "hazard": "leak", "value": False}))
    assert not conn.errors
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    conn2 = FakeConnection()
    run(integration.websocket_awc_sim_set(hass, conn2, {"id": 2, "hazard": "leak", "value": True}))
    run(integration._async_awc_timer_fired(hass, entry, None))  # mid-leg checkpoint
    st = _state(entry)
    assert st["status"] == "fault" and "leak" in st["fault"].lower()
    assert not [c for c in hass.services.calls if c.domain == "switch"]


def test_sim_toggle_guards():
    # Entering sim is refused while a real change runs; leaving sim mid-virtual-run
    # aborts the sandbox change cleanly.
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    conn = FakeConnection()
    run(integration.websocket_awc_sim_set(hass, conn, {"id": 1, "enabled": True}))
    assert "busy" in conn.error_codes
    conn2 = FakeConnection()
    run(integration.websocket_awc_abort(hass, conn2, {"id": 2}))
    conn3 = FakeConnection()
    run(integration.websocket_awc_sim_set(hass, conn3, {"id": 3, "enabled": True}))
    assert not conn3.errors
    assert _start(hass, entry, 0.5, method="batch_sequential")[0]
    conn4 = FakeConnection()
    run(integration.websocket_awc_sim_set(hass, conn4, {"id": 4, "enabled": False}))
    assert not conn4.errors
    assert _state(entry)["status"] == "idle"
    assert integration._awc_sim_enabled(integration._config_from_entry(entry)) is False


def _notes(hass, notification_id):
    return [c for c in hass.services.calls if c.domain == "persistent_notification"
            and c.data.get("notification_id") == notification_id]


def test_reservoir_low_advisory_notifies_once_per_cooldown():
    entry = _entry("batch_sequential")
    _awc(entry)["reservoirs"]["fresh"]["remainingMl"] = 2000.0  # 8% of 25 L
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry)
    run(integration._async_awc_schedule_tick(hass, entry, _now(3, 0)))
    assert len(_notes(hass, "openreef_awc_reservoir_low_fresh")) == 1
    run(integration._async_awc_schedule_tick(hass, entry, _now(3, 1)))
    assert len(_notes(hass, "openreef_awc_reservoir_low_fresh")) == 1  # cooldown holds


def test_reservoir_low_advisory_respects_gate():
    entry = _entry("batch_sequential", awc_over={"notifications": {"reservoirLow": False}})
    _awc(entry)["reservoirs"]["fresh"]["remainingMl"] = 2000.0
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry)
    run(integration._async_awc_schedule_tick(hass, entry, _now(3, 0)))
    assert not _notes(hass, "openreef_awc_reservoir_low_fresh")


def test_paused_fault_gate_silences_pause_notification():
    entry = _entry("batch_sequential", awc_over={"notifications": {"pausedFault": False}})
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    hass.states.set("binary_sensor.fresh_empty", "on")
    _fire_leg(hass, entry)
    assert _state(entry)["status"] == "paused"  # behaviour unchanged
    assert not _notes(hass, "openreef_awc_paused")  # notification silenced


def test_net_drift_and_recalibration_advisories():
    entry = _entry("batch_sequential")
    awc = _awc(entry)
    awc["ledger"] = {"cumulativeDrainedL": 30.0, "cumulativeFilledL": 20.0, "resetAt": ""}
    awc["pumps"]["drain"]["calibratedAt"] = (
        datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry)
    run(integration._async_awc_schedule_tick(hass, entry, _now(3, 0)))
    assert len(_notes(hass, "openreef_awc_net_drift")) == 1
    assert len(_notes(hass, "openreef_awc_recal_drain")) == 1
    assert not _notes(hass, "openreef_awc_recal_fill")  # never calibrated → no age → no nag


def test_fresh_debits_accumulate_dispensed_since_full():
    # Every fill-side debit also bumps the drift odometer (Stage A wiring).
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    _drive(hass, entry)
    assert _close(_awc(entry)["reservoirs"]["fresh"]["dispensedSinceFullMl"], 2000.0, 1.0)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    _drive(hass, entry)
    assert _close(_awc(entry)["reservoirs"]["fresh"]["dispensedSinceFullMl"], 4000.0, 1.0)


def test_drift_graded_once_when_empty_float_trips():
    # Model says 20 L dispensed when the 25 L reservoir runs empty → −20% drift →
    # warning + ONE notification per fill cycle; reset-to-full zeroes and re-arms.
    entry = _entry("batch_sequential")
    _awc(entry)["reservoirs"]["fresh"]["dispensedSinceFullMl"] = 20000.0
    _awc(entry)["reservoirs"]["fresh"]["fullConfirmedAt"] = "2026-07-01T00:00:00+00:00"
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry, states={"binary_sensor.fresh_empty": "on"})
    run(integration._async_awc_schedule_tick(hass, entry, _now(3, 0)))
    fresh = _awc(entry)["reservoirs"]["fresh"]
    assert fresh["driftStatus"] == "warning" and fresh["driftCheckedAt"]
    assert _close(fresh["driftPct"], -20.0, 0.1)
    def _drift_notes():
        return [c for c in hass.services.calls if c.domain == "persistent_notification"
                and c.data.get("notification_id") == "openreef_awc_drift_fresh"]
    assert len(_drift_notes()) == 1
    run(integration._async_awc_schedule_tick(hass, entry, _now(3, 1)))  # latched
    assert len(_drift_notes()) == 1
    conn = FakeConnection()
    run(integration.websocket_awc_reset_reservoir(hass, conn, {"id": 1, "reservoir": "fresh"}))
    fresh = _awc(entry)["reservoirs"]["fresh"]
    assert fresh["dispensedSinceFullMl"] == 0 and fresh["driftCheckedAt"] == ""
    assert _close(fresh["remainingMl"], 25000.0)
    assert len(_drift_notes()) == 1  # already graded this cycle — reset doesn't re-notify


def test_drift_within_tolerance_stays_quiet():
    entry = _entry("batch_sequential")
    _awc(entry)["reservoirs"]["fresh"]["dispensedSinceFullMl"] = 24500.0  # −2%
    _awc(entry)["reservoirs"]["fresh"]["fullConfirmedAt"] = "2026-07-01T00:00:00+00:00"
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry, states={"binary_sensor.fresh_empty": "on"})
    run(integration._async_awc_schedule_tick(hass, entry, _now(3, 0)))
    fresh = _awc(entry)["reservoirs"]["fresh"]
    assert fresh["driftStatus"] == "ok" and fresh["driftCheckedAt"]
    assert not [c for c in hass.services.calls if c.domain == "persistent_notification"
                and c.data.get("notification_id") == "openreef_awc_drift_fresh"]


def test_reset_to_full_grades_drift_when_float_tripped():
    # Refill-from-empty without the tick having run: the reset itself grades first.
    entry = _entry("batch_sequential")
    _awc(entry)["reservoirs"]["fresh"]["dispensedSinceFullMl"] = 20000.0
    _awc(entry)["reservoirs"]["fresh"]["fullConfirmedAt"] = "2026-07-01T00:00:00+00:00"
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry, states={"binary_sensor.fresh_empty": "on"})
    conn = FakeConnection()
    run(integration.websocket_awc_reset_reservoir(hass, conn, {"id": 1, "reservoir": "fresh"}))
    fresh = _awc(entry)["reservoirs"]["fresh"]
    assert fresh["driftStatus"] == "warning"  # graded before zeroing
    assert fresh["dispensedSinceFullMl"] == 0 and fresh["driftCheckedAt"] == ""
    assert fresh["fullConfirmedAt"]  # the reset itself is the next cycle's anchor
    notes = [c for c in hass.services.calls if c.domain == "persistent_notification"
             and c.data.get("notification_id") == "openreef_awc_drift_fresh"]
    assert len(notes) == 1


def test_drift_not_graded_without_confirmed_full_anchor():
    # Fresh install / never marked full: the odometer started from an unknown level —
    # grading would be a guess, and false recalibrate alarms are forbidden.
    entry = _entry("batch_sequential")
    _awc(entry)["reservoirs"]["fresh"]["dispensedSinceFullMl"] = 12000.0
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry, states={"binary_sensor.fresh_empty": "on"})
    run(integration._async_awc_schedule_tick(hass, entry, _now(3, 0)))
    fresh = _awc(entry)["reservoirs"]["fresh"]
    assert fresh["driftCheckedAt"] == "" and fresh["driftStatus"] == ""
    assert not _notes(hass, "openreef_awc_drift_fresh")


def test_drift_skipped_after_unmarked_bucket_topup():
    # dispensed way past capacity = someone refilled without 'mark full' — no honest
    # reference this cycle; skip rather than accuse the pump.
    entry = _entry("batch_sequential")
    _awc(entry)["reservoirs"]["fresh"]["dispensedSinceFullMl"] = 40000.0  # 1.6× capacity
    _awc(entry)["reservoirs"]["fresh"]["fullConfirmedAt"] = "2026-07-01T00:00:00+00:00"
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry, states={"binary_sensor.fresh_empty": "on"})
    run(integration._async_awc_schedule_tick(hass, entry, _now(3, 0)))
    assert _awc(entry)["reservoirs"]["fresh"]["driftCheckedAt"] == ""
    assert not _notes(hass, "openreef_awc_drift_fresh")


def test_micro_change_skips_ato_and_dosing_suspend():
    # A change at/under ato.microChangeThresholdMl runs without holding the ATO or
    # dosing, and finalizes with NO stabilization hold-off (Stage A micro-changes).
    entry = _entry("batch_sequential", awc_over={
        "ato": {"suspendDuringChange": True, "stabilizationHoldoffMinutes": 15,
                "microChangeThresholdMl": 100}})
    hass = _hass(entry)
    assert _start(hass, entry, 0.05, method="batch_sequential")[0]  # 50 ml ≤ 100 ml
    assert _state(entry)["microChange"] is True
    assert integration._awc_ato_suspended(entry.options[CONF_SETTINGS]) is False
    assert integration._dosing_awc_suspended(integration._config_from_entry(entry)) is False
    _drive(hass, entry)
    st = _state(entry)
    assert st["status"] == "idle"
    assert st["atoSuspendedUntil"] == ""  # no hold-off for a micro-change
    assert st["microChange"] is False


def test_normal_change_still_suspends_ato_with_threshold_set():
    # Above the threshold everything behaves exactly as before.
    entry = _entry("batch_sequential", awc_over={
        "ato": {"suspendDuringChange": True, "stabilizationHoldoffMinutes": 15,
                "microChangeThresholdMl": 100}})
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]  # 2 L > 100 ml
    assert _state(entry)["microChange"] is False
    assert integration._awc_ato_suspended(entry.options[CONF_SETTINGS]) is True
    assert integration._dosing_awc_suspended(integration._config_from_entry(entry)) is True
    _drive(hass, entry)
    assert _state(entry)["atoSuspendedUntil"]  # hold-off armed as usual


def test_micro_change_preserves_prior_holdoff():
    # A normal change's stabilization hold-off must survive a micro-change that
    # starts and finishes inside it — the micro path used to clear the stamp and
    # release the dosing hold early (review F6).
    entry = _entry("batch_sequential", awc_over={
        "ato": {"suspendDuringChange": True, "stabilizationHoldoffMinutes": 60,
                "microChangeThresholdMl": 100}})
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]  # normal change
    _drive(hass, entry)
    holdoff_before = _state(entry)["atoSuspendedUntil"]
    assert holdoff_before  # hold-off armed
    assert _start(hass, entry, 0.05, method="batch_sequential")[0]  # micro inside it
    # during the micro run the previous hold-off still holds ATO + dosing
    assert integration._awc_ato_suspended(entry.options[CONF_SETTINGS]) is True
    assert integration._dosing_awc_suspended(integration._config_from_entry(entry)) is True
    _drive(hass, entry)
    assert _state(entry)["atoSuspendedUntil"] == holdoff_before  # untouched
    assert integration._awc_ato_suspended(entry.options[CONF_SETTINGS]) is True


def test_micro_change_fault_kills_ato_equipment():
    # A latched hazard mid-micro-change must physically stop the ATO — the micro
    # start skipped the kill by design, and the predicate only blocks future
    # turn-ons (review F5).
    equipment = {"ato1": {"type": "ato", "armed": True, "switch_entity_id": "switch.my_ato"}}
    entry = _entry("batch_sequential", equipment=equipment, awc_over={
        "ato": {"suspendDuringChange": True, "stabilizationHoldoffMinutes": 15,
                "microChangeThresholdMl": 100}})
    hass = _hass(entry, states={"switch.my_ato": "on"})
    assert _start(hass, entry, 0.05, method="batch_sequential")[0]
    assert not _has_call(hass.services.calls, "turn_off", "switch.my_ato")  # micro: no kill
    hass.states.set("binary_sensor.leak", "on")
    st = _state(entry)
    now = datetime.now(timezone.utc)
    st["legStartedAt"] = now.isoformat()
    st["legEndsAt"] = (now + timedelta(seconds=10)).isoformat()
    run(integration._async_awc_timer_fired(hass, entry, None))  # checkpoint → fault
    assert _state(entry)["status"] == "fault"
    assert _has_call(hass.services.calls, "turn_off", "switch.my_ato")


def test_sim_sandbox_restores_real_accounting_on_exit():
    # Demo runs drive the real state machine — but exiting the demo must restore the
    # real reservoir/ledger/history/wear models and the schedule state verbatim
    # (review F7/F12/F13).
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_awc_sim_set(hass, conn, {"id": 1, "enabled": True}))
    assert not conn.errors, conn.error_codes
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    # a virtual change must not hold the real ATO/doser even while "running"
    assert integration._awc_ato_suspended(entry.options[CONF_SETTINGS]) is False
    assert integration._dosing_awc_suspended(integration._config_from_entry(entry)) is False
    _drive(hass, entry)
    awc = _awc(entry)
    assert awc["history"] and _close(awc["reservoirs"]["fresh"]["remainingMl"], 23000.0, 5)
    conn2 = FakeConnection()
    run(integration.websocket_awc_sim_set(hass, conn2, {"id": 2, "enabled": False}))
    assert not conn2.errors, conn2.error_codes
    awc = _awc(entry)
    assert awc["history"] == []                                # virtual litres gone
    assert _close(awc["reservoirs"]["fresh"]["remainingMl"], 25000.0, 1e-6)
    assert awc["reservoirs"]["fresh"]["dispensedSinceFullMl"] == 0
    assert awc["pumps"]["fill"]["startCount"] == 0             # wear restored
    assert _state(entry)["lastRun"] == ""                      # schedule state restored
    assert awc["simulation"]["snapshot"] is None


def test_sim_toggle_refused_during_calibration_run():
    # Flipping the sandbox under a timed calibration run would strand a REAL pump on
    # (review F9 — the critical one).
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_awc_calibration_run(
        hass, conn, {"id": 1, "role": "fill", "seconds": 30}))
    assert not conn.errors, conn.error_codes
    conn2 = FakeConnection()
    run(integration.websocket_awc_sim_set(hass, conn2, {"id": 2, "enabled": True}))
    assert "busy" in conn2.error_codes
    conn3 = FakeConnection()
    run(integration.websocket_config_import(hass, conn3, {"id": 3, "payload": {
        "kind": "openreef-config", "schema": 1, "config": {}}}))
    assert "busy" in conn3.error_codes  # imports can swap the pump entity mid-run
    hass.data[integration.DOMAIN].pop(integration.AWC_CALRUN_UNSUB, None)  # cleanup


def test_orphaned_calibration_run_recovered_at_startup():
    # HA restarted mid-run: the in-memory stop timer died — the persisted stamp lets
    # startup stop the pump (review F10).
    entry = _entry("batch_sequential")
    awc = _awc(entry)
    awc["state"].update({"calRunRole": "fill",
                         "calRunEndsAt": "2026-07-12T00:00:30+00:00"})
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry, states={"switch.awc_fill": "on"})
    run(integration._async_awc_recover_orphaned_calrun(hass, entry))
    assert _has_call(hass.services.calls, "turn_off", "switch.awc_fill")
    st = _state(entry)
    assert st["calRunRole"] == "" and st["calRunEndsAt"] == ""


def test_blocked_slot_notes_once_per_blocker_per_day():
    # Interval mode mints a new slot every everyMinutes — a persistent blocker must
    # note ONCE per day per reason, not once per slot (review F3).
    entry = _interval_entry()
    hass = _hass(entry, states={"binary_sensor.leak": "unavailable"})
    _state(entry)["lastRun"] = _now(1, 30).isoformat()
    run(integration._async_awc_schedule_tick(hass, entry, _now(2, 1)))
    run(integration._async_awc_schedule_tick(hass, entry, _now(3, 1)))  # NEW slot, same blocker
    assert len(_notes(hass, "openreef_awc_blocked")) == 1


def test_interval_coalesce_awkward_cap_still_starts():
    # An exact-cap clamp used to re-trip the cap guard after 3-decimal rounding
    # (cap 15.8375 → target 15.838) and deadlock the schedule (review F2).
    entry = _entry("batch_sequential", awc_over={
        "tankVolumeLitres": 63.35,
        "schedule": {"enabled": True, "method": "batch_sequential", "mode": "interval",
                     "everyMinutes": 60, "windowStart": "00:00", "windowEnd": "00:00",
                     "amount": 240, "amountUnit": "litres", "period": "day"},
        "safety": {"highLevelEntity": "binary_sensor.high", "leakEntity": "binary_sensor.leak",
                   "maxSingleChangePercent": 25},
        "reservoirs": {
            "fresh": {"capacityLitres": 25, "remainingMl": 25000, "emptyEntity": "binary_sensor.fresh_empty"},
            "waste": {"capacityLitres": 25, "filledMl": 0, "fullEntity": "binary_sensor.waste_full"},
        },
    })
    _state(entry)["lastRun"] = _now(1, 30).isoformat()
    hass = _hass(entry)
    run(integration._async_awc_schedule_tick(hass, entry, _now(4, 55)))
    st = _state(entry)
    assert st["status"] == "draining", st  # started — no cap deadlock
    assert st["targetLitres"] <= 63.35 * 0.25 + 1e-6
    assert _close(st["targetLitres"], 15.837, 1e-6)


def test_ato_restore_timer_skips_latched_fault():
    # The hold-off expiry firing while a FAULT is latched must not clear the
    # suspension / release the dosing hold out from under it (R12).
    sched = install_scheduler(integration)
    entry = _entry("batch_sequential")
    awc = _awc(entry)
    awc["state"].update({
        "status": "fault", "fault": "test fault",
        "atoSuspendedUntil": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
    })
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    run(integration._async_arm_awc_ato_restore(hass, entry, config))
    assert sched.pending()
    run(sched.fire_all())
    assert _state(entry)["atoSuspendedUntil"]  # untouched — the fault is still latched
    install_scheduler(integration)


def test_ato_restore_timer_clears_expired_holdoff_when_idle():
    # The same expiry with an idle state DOES clear the suspension and release the
    # dosing hold — the R27 restart re-arm depends on this handler behaviour.
    sched = install_scheduler(integration)
    entry = _entry("batch_sequential")
    awc = _awc(entry)
    awc["state"].update({
        "status": "idle",
        "atoSuspendedUntil": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
    })
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    run(integration._async_arm_awc_ato_restore(hass, entry, config))
    run(sched.fire_all())
    assert _state(entry)["atoSuspendedUntil"] == ""
    install_scheduler(integration)


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
    assert _state(entry)["endsAt"]["drain"] and _state(entry)["endsAt"]["fill"]


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
    assert st["status"] == "exchanging"                     # fill still running
    assert _close(st["movedMl"]["drain"], 1000.0, 1.0)      # drain capped at target
    assert st["movedMl"]["drain"] <= 1000.0 + 1e-6          # never exceeds target
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
    st = _state(entry)
    now = datetime.now(timezone.utc)
    st.setdefault("endsAt", {})["drain"] = now.isoformat()
    st["endsAt"]["fill"] = (now + timedelta(seconds=20)).isoformat()
    run(integration._async_awc_exchange_tick(hass, entry, None))
    s2 = _state(entry)
    assert s2["status"] == "exchanging"           # 1.0 L gap < 1.5 L cap ⇒ no abort
    assert _close(s2["movedMl"]["drain"], 2000, 5) and _close(s2["movedMl"]["fill"], 1000, 40)


def test_simultaneous_resume_to_balance_only_restarts_unfinished_side():
    # crash after drain done (2 L) but fill only 0.5 L: resume must NOT re-run drain,
    # and the 1.5 L pre-existing gap must NOT false-abort (re-baselined imbalance cap).
    entry = _entry("batch_simultaneous")  # default cap 0.5 L — would abort without baseline
    awc = _awc(entry)
    awc["state"].update({
        "status": "exchanging", "method": "batch_simultaneous", "targetLitres": 2.0,
        "movedMl": {"drain": 2000, "fill": 500},
    })
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    run(integration._async_awc_resume_on_startup(hass, entry, config))
    st = _state(entry)
    assert st["status"] == "exchanging"
    assert _close(st["exchangeBaselineNetMl"], 1500, 1)  # SIGNED: drained ahead ⇒ positive
    # fill restarts, drain does NOT (already complete)
    assert _has_call(hass.services.calls, "turn_on", "switch.awc_fill")
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_drain")
    # a real intermediate tick (fill half-done) must NOT abort despite the big gap
    now = datetime.now(timezone.utc)
    _state(entry).setdefault("endsAt", {})["fill"] = (now + timedelta(seconds=7.5)).isoformat()
    run(integration._async_awc_exchange_tick(hass, entry, None))
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
        "movedMl": {"drain": 0, "fill": 0},
    })
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    run(integration._async_awc_resume_on_startup(hass, entry, config))
    st = _state(entry)
    assert st["status"] == "fault" and "calibrat" in st["fault"].lower()
    assert not _awc(entry)["history"]  # never recorded a (zero-volume) completion


# --- Wave 6: sequential/simultaneous parity ------------------------------------

def test_abort_mid_leg_credits_elapsed_volume():
    # Stop at ~40% of the drain leg: the elapsed volume must land in history, the
    # ledger and the waste reservoir — not vanish (R6).
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    st = _state(entry)
    now = datetime.now(timezone.utc)
    st["legStartedAt"] = (now - timedelta(seconds=8)).isoformat()
    st["legEndsAt"] = (now + timedelta(seconds=12)).isoformat()
    conn = FakeConnection()
    run(integration.websocket_awc_abort(hass, conn, {"id": 1}))
    assert not conn.errors
    assert _state(entry)["status"] == "idle"
    h = _awc(entry)["history"][0]
    # generous tolerance (±1.5 s of flow): the credit dead-reckons from REAL utcnow,
    # so a slow CI box eats into the margin one-directionally
    assert _close(h["drainedL"], 0.8, 0.15) and h["partial"]
    assert _close(_awc(entry)["reservoirs"]["waste"]["filledMl"], 800.0, 150.0)
    assert _close(_awc(entry)["ledger"]["cumulativeDrainedL"], 0.8, 0.15)


def test_sequential_checkpoint_trips_leak_mid_leg():
    # A leak 10 s into a 20 s drain leg aborts at the mid-leg CHECKPOINT (R9) — with
    # the elapsed volume credited (R6) — instead of waiting out the leg timer.
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    st = _state(entry)
    now = datetime.now(timezone.utc)
    st["legStartedAt"] = (now - timedelta(seconds=10)).isoformat()
    st["legEndsAt"] = (now + timedelta(seconds=10)).isoformat()
    hass.states.set("binary_sensor.leak", "on")
    run(integration._async_awc_timer_fired(hass, entry, None))
    st = _state(entry)
    assert st["status"] == "fault" and "leak" in st["fault"].lower()
    assert _has_call(hass.services.calls, "turn_off", "switch.awc_drain")
    # ±1.5 s of flow: elapsed is measured against REAL utcnow (CI-drift headroom)
    assert _close(_awc(entry)["history"][0]["drainedL"], 1.0, 0.15)  # 10 s × 100 ml/s


def test_sequential_checkpoint_ok_rearms_without_completing():
    # A healthy checkpoint mid-leg must neither credit the slice nor advance the leg —
    # it just re-arms the monitor (R9).
    sched = install_scheduler(integration)
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    # Fire the armed checkpoint THROUGH the scheduler: fire_all cancels every record
    # it fires, so a pending record afterwards can only be the checkpoint's re-arm.
    assert run(sched.fire_all()) >= 1
    st = _state(entry)
    assert st["status"] == "draining" and st["movedMl"].get("drain", 0) == 0
    assert sched.pending()
    install_scheduler(integration)


def test_exchange_tick_survives_unreachable_pump_stop():
    # R11: a raising turn_off (ESP unreachable) must not abandon the tick — the
    # accounting still persists and the monitor timer still re-arms.
    sched = install_scheduler(integration)
    entry = _entry("batch_simultaneous", awc_over={"safety": {
        "highLevelEntity": "binary_sensor.high", "leakEntity": "binary_sensor.leak",
        "maxSingleChangePercent": 25, "maxInstantaneousImbalanceLitres": 3.0}})
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_simultaneous")[0]
    hass.services.fail_on.add(("switch", "turn_off", "switch.awc_drain"))
    _fire_exchange(hass, entry, age_done=("drain",))
    st = _state(entry)
    assert st["status"] == "exchanging"
    assert _close(st["movedMl"]["drain"], 2000, 5)  # accounting persisted despite the failure
    assert sched.pending()                    # monitor re-armed
    hass.services.fail_on.clear()
    install_scheduler(integration)


def test_timer_fired_rearms_monitor_after_handler_crash():
    # R11: if the handler dies mid-flight (here: the save), the finally-arm must keep
    # the monitor alive — a dead timer while pumps run is the 'keep filling forever'
    # hazard.
    sched = install_scheduler(integration)
    entry = _entry("batch_simultaneous")
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_simultaneous")[0]
    real_save = integration._async_save_config

    async def _boom(*args, **kwargs):
        raise RuntimeError("save died")

    integration._async_save_config = _boom
    try:
        raised = False
        try:
            run(sched.fire_all())  # fires the armed monitor tick → handler crashes
        except RuntimeError:
            raised = True
    finally:
        integration._async_save_config = real_save
    assert raised
    assert sched.pending()  # the finally-arm re-armed the monitor
    assert _state(entry)["status"] == "exchanging"
    install_scheduler(integration)


def test_sequential_resume_uncalibrated_faults_not_replays():
    # Resume lands on a fill leg whose pump lost its calibration: begin-leg must fault
    # (R8), never energise a pump on a zero-length timer.
    entry = _entry("batch_sequential", awc_over={"pumps": {
        "drain": {"switchEntity": "switch.awc_drain", "mlPerS": 100},
        "fill": {"switchEntity": "switch.awc_fill", "mlPerS": 0},
    }})
    awc = _awc(entry)
    awc["state"].update({
        "status": "filling", "method": "batch_sequential", "targetLitres": 2.0,
        "movedMl": {"drain": 2000, "fill": 0}, "legStartedAt": "", "legEndsAt": "",
    })
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    run(integration._async_awc_resume_on_startup(hass, entry, config))
    st = _state(entry)
    assert st["status"] == "fault" and "calibrat" in st["fault"].lower()
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_fill")


def test_sequential_resume_sliver_completes_without_fault():
    # Resume with 30 ml left on the fill leg while spin-up is 50 ml: the sliver's
    # runtime rounds to ≤ 0 on a CALIBRATED pump — run a floor tick and finish,
    # never latch a 'not calibrated' fault (R13 parity for the sequential path).
    entry = _entry("batch_sequential", awc_over={"pumps": {
        "drain": {"switchEntity": "switch.awc_drain", "mlPerS": 100},
        "fill": {"switchEntity": "switch.awc_fill", "mlPerS": 100, "spinUpMl": 50},
    }})
    awc = _awc(entry)
    awc["state"].update({
        "status": "filling", "method": "batch_sequential", "targetLitres": 2.0,
        "movedMl": {"drain": 2000, "fill": 1970}, "legStartedAt": "", "legEndsAt": "",
    })
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    run(integration._async_awc_resume_on_startup(hass, entry, config))
    st = _state(entry)
    assert st["status"] == "filling", st.get("fault")
    _fire_leg(hass, entry)  # the floor tick's completion credits the sliver → finalize
    assert _state(entry)["status"] == "idle"
    assert _close(_awc(entry)["history"][0]["filledL"], 2.0, 1e-3)


def test_acknowledge_records_partial_progress_history():
    # A begin-failure fault latches with progress still on the books; acknowledging
    # must record it in history/ledger before zeroing — the reservoir models already
    # hold the debit, and the two books must not diverge.
    entry = _entry("batch_sequential")
    awc = _awc(entry)
    awc["state"].update({
        "status": "fault", "fault": "AWC pump start failed: boom",
        "method": "batch_sequential", "targetLitres": 2.0,
        "movedMl": {"drain": 1500, "fill": 0},
    })
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_awc_acknowledge(hass, conn, {"id": 1}))
    assert not conn.errors, conn.error_codes
    assert _state(entry)["status"] == "idle"
    assert not any(_state(entry)["movedMl"].values())  # zeroed (normalised per-pump keys)
    h = _awc(entry)["history"][0]
    assert _close(h["drainedL"], 1.5, 1e-6) and h["partial"]
    assert "acknowledged" in h["notes"].lower()
    assert _close(_awc(entry)["ledger"]["cumulativeDrainedL"], 1.5, 1e-6)


def test_simultaneous_resume_near_end_completes_without_fault():
    # Crash with 30 ml left on the fill side while its spin-up correction is 50 ml:
    # the sliver's fitted runtime is ≤ 0 — that side is DONE, not 'uncalibrated' (R13).
    entry = _entry("batch_simultaneous", awc_over={"pumps": {
        "drain": {"switchEntity": "switch.awc_drain", "mlPerS": 100},
        "fill": {"switchEntity": "switch.awc_fill", "mlPerS": 100, "spinUpMl": 50},
    }})
    awc = _awc(entry)
    awc["state"].update({
        "status": "exchanging", "method": "batch_simultaneous", "targetLitres": 2.0,
        "movedMl": {"drain": 2000, "fill": 1970},
    })
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    run(integration._async_awc_resume_on_startup(hass, entry, config))
    st = _state(entry)
    assert st["status"] != "fault", st.get("fault")
    _fire_exchange(hass, entry, age_done=("drain", "fill"))
    assert _state(entry)["status"] == "idle"


def test_simultaneous_relaunch_dead_reckons_run_on():
    # HA died mid-exchange; by the time it's back both persisted stop times have
    # passed — the ESP kept pumping toward them, so the run-on must be credited before
    # replanning (R10): resume finalizes instead of re-running already-moved volume.
    entry = _entry("batch_simultaneous")
    awc = _awc(entry)
    now = datetime.now(timezone.utc)
    awc["state"].update({
        "status": "exchanging", "method": "batch_simultaneous", "targetLitres": 2.0,
        "movedMl": {"drain": 1500, "fill": 500},
        "endsAt": {"drain": (now - timedelta(seconds=60)).isoformat(),
                   "fill": (now - timedelta(seconds=45)).isoformat()},
    })
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    run(integration._async_awc_resume_on_startup(hass, entry, config))
    st = _state(entry)
    assert st["status"] == "idle"
    assert _close(_awc(entry)["history"][0]["filledL"], 2.0, 1e-3)
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_fill")
    # the run-on was mirrored into the reservoir models (fill delta 1.5 L, drain 0.5 L)
    assert _close(_awc(entry)["reservoirs"]["fresh"]["remainingMl"], 23500.0, 1.0)
    assert _close(_awc(entry)["reservoirs"]["waste"]["filledMl"], 500.0, 1.0)


def test_exchange_tick_rate_zeroed_mid_run_pauses_without_credit():
    # A raw settings write zeroes a pump's rate mid-run: dead-reckoning a zero rate
    # reads 'full target moved' — pre-fix that phantom credit tripped the imbalance
    # abort (or with the cap disabled, phantom-completed the change). The tick must
    # PAUSE instead (R26), crediting only the HEALTHY side's real elapsed progress;
    # the minutely auto-resume must keep it paused (not escalate to a latched fault);
    # and recalibrating WHILE PAUSED via the WS — the instructed recovery — must work.
    entry = _entry("batch_simultaneous")
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_simultaneous")[0]
    _awc(entry)["pumps"]["fill"]["mlPerS"] = 0
    run(integration._async_awc_exchange_tick(hass, entry, None))
    st = _state(entry)
    assert st["status"] == "paused" and "calibrat" in st["pausedReason"].lower()
    assert st["movedMl"].get("fill", 0) == 0     # the zero-rate side got NO phantom credit
    assert st["movedMl"].get("drain", 0) <= 200  # healthy side: honest elapsed only (~0-2 s)
    run(integration._async_awc_schedule_tick(hass, entry, datetime.now()))
    st = _state(entry)
    assert st["status"] == "paused" and "calibrat" in st["pausedReason"].lower()
    # recalibrate while paused (allowed: pumps off, no live dead-reckoning) → resume
    conn = FakeConnection()
    run(integration.websocket_awc_calibrate(
        hass, conn, {"id": 9, "role": "fill", "volume_ml": 500, "seconds": 5}))
    assert not conn.errors, conn.error_codes
    assert run(integration._async_awc_try_resume(hass, entry, None))
    assert _state(entry)["status"] == "exchanging"


def test_leg_anomaly_warn_tier_surfaces_once():
    # A leg at 2.2× its expected runtime (warn ≥ 2×, abort ≥ 3×) surfaces the warn
    # tier once per change: activity + notification, non-blocking (T8).
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    st = _state(entry)
    now = datetime.now(timezone.utc)
    st["legStartedAt"] = (now - timedelta(seconds=44)).isoformat()
    st["legEndsAt"] = (now - timedelta(seconds=1)).isoformat()
    _fire_leg(hass, entry)
    st = _state(entry)
    assert st["status"] == "filling"          # warn is non-blocking
    assert st["anomalyWarned"] is True
    notes = [c for c in hass.services.calls
             if c.domain == "persistent_notification"
             and c.data.get("notification_id") == "openreef_awc_anomaly"]
    assert len(notes) == 1
    # a second slow leg in the SAME change does not re-notify
    st["legStartedAt"] = (now - timedelta(seconds=44)).isoformat()
    st["legEndsAt"] = (now - timedelta(seconds=1)).isoformat()
    _fire_leg(hass, entry)
    notes = [c for c in hass.services.calls
             if c.domain == "persistent_notification"
             and c.data.get("notification_id") == "openreef_awc_anomaly"]
    assert len(notes) == 1


# --- Two-config races (R1: every entry point fetches config INSIDE the lock) --
# The fake services yield to the event loop on every call, so asyncio.gather here
# produces real interleavings — with the old pre-lock snapshots these tests fail.

def _switch_calls(hass, entity):
    return [c for c in hass.services.calls
            if c.domain == "switch" and entity in c.data.values()]


def test_race_abort_vs_leg_timer_never_resurrects_pumps():
    # An abort racing the leg timer must end idle with every pump OFF as the LAST
    # word — the stale-snapshot bug let the timer re-launch the next leg from a
    # pre-abort 'draining' status (a pump running with the panel showing idle).
    import asyncio

    for order in ("abort_first", "timer_first"):
        entry = _entry("batch_sequential")
        hass = _hass(entry)
        assert _start(hass, entry, 2.0, method="batch_sequential")[0]
        # Age the leg to its end so the timer takes the leg-COMPLETION path (which
        # advances to the fill leg), not the R9 mid-leg checkpoint — completion vs
        # abort is the race that used to resurrect pumps.
        _state(entry)["legEndsAt"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        conn = FakeConnection()

        async def race():
            abort = integration.websocket_awc_abort(hass, conn, {"id": 1})
            timer = integration._async_awc_timer_fired(hass, entry, None)
            pair = (abort, timer) if order == "abort_first" else (timer, abort)
            await asyncio.gather(*pair)

        run(race())
        assert _state(entry)["status"] == "idle", order
        for pump in ("switch.awc_drain", "switch.awc_fill"):
            calls = _switch_calls(hass, pump)
            services = [c.service for c in calls]
            assert not calls or services[-1] == "turn_off", (order, pump, services)
            assert hass.states.get(pump).state == "off", (order, pump)


def test_race_run_now_vs_scheduler_tick_single_start():
    # A due scheduler tick racing a manual run-now: exactly one change starts —
    # the loser must see the winner's saved status under the lock, not a stale
    # idle snapshot that double-runs the prefight and doubles the drain volume.
    import asyncio

    for order in ("manual_first", "tick_first"):
        entry = _entry("batch_sequential", awc_over={"schedule": {
            "enabled": True, "method": "batch_sequential", "times": ["00:00"],
            "amount": 2, "amountUnit": "litres", "period": "day",
        }})
        hass = _hass(entry)
        conn = FakeConnection()
        now_local = datetime(2026, 7, 12, 3, 0)  # past the 00:00 slot, never run ⇒ due

        async def race():
            manual = integration.websocket_awc_run_now(hass, conn, {"id": 1, "litres": 2})
            tick = integration._async_awc_schedule_tick(hass, entry, now_local)
            pair = (manual, tick) if order == "manual_first" else (tick, manual)
            await asyncio.gather(*pair)

        run(race())
        assert _state(entry)["status"] == "draining", order
        ons = [c for c in _switch_calls(hass, "switch.awc_drain") if c.service == "turn_on"]
        assert len(ons) == 1, (order, [c.service for c in _switch_calls(hass, "switch.awc_drain")])


def test_ws_calibrate_busy_during_run():
    # Recalibrating mid-run would re-scale the live dead-reckoning — rejected.
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    conn = FakeConnection()
    run(integration.websocket_awc_calibrate(
        hass, conn, {"id": 1, "role": "drain", "volume_ml": 500, "seconds": 10}))
    assert "busy" in conn.error_codes
    assert _close(_awc(entry)["pumps"]["drain"]["mlPerS"], 100.0, 1e-6)  # unchanged


def test_ws_calibrate_rejects_implausible_intercept():
    # Least-squares over convex data: the fitted line predicts NEGATIVE volume at the
    # 5 s run — that's measurement noise, not a pump; reject instead of storing it.
    entry = _entry()
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_awc_calibrate(hass, conn, {"id": 1, "role": "drain",
        "points": [[5, 10], [10, 100], [60, 3000]]}))
    assert "implausible_calibration" in conn.error_codes
    assert _close(_awc(entry)["pumps"]["drain"]["mlPerS"], 100.0, 1e-6)  # unchanged


# --- Stage B: N-source (fill2/fresh2), state migration, salt ledger ------------

def test_legacy_state_blob_migrates_and_resumes():
    # A pre-Stage-B persisted blob (drainedMl/filledMl/exchangeBaselineGapMl scalars)
    # must migrate to movedMl/endsAt/exchangeBaselineNetMl — with the SIGN recovered
    # from whichever side was ahead — and then resume-to-balance to completion.
    entry = _entry("batch_simultaneous")
    awc = _awc(entry)
    st = awc["state"]
    for key in ("movedMl", "endsAt", "activeSourceRole", "exchangeBaselineNetMl"):
        st.pop(key, None)  # make it a genuinely OLD-shape blob
    st.update({
        "status": "exchanging", "method": "batch_simultaneous", "targetLitres": 2.0,
        "drainedMl": 2000, "filledMl": 500, "exchangeBaselineGapMl": 1500,
        "drainEndsAt": "", "fillEndsAt": "",
    })
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(entry.options[CONF_SETTINGS])
    st = _state(entry)
    assert st["movedMl"] == {"drain": 2000.0, "fill": 500.0}
    assert st["endsAt"] == {"drain": "", "fill": ""}
    assert st["exchangeBaselineNetMl"] == 1500.0  # SIGNED: drained ahead ⇒ positive
    for legacy in ("drainedMl", "filledMl", "drainEndsAt", "fillEndsAt", "exchangeBaselineGapMl"):
        assert legacy not in st, legacy
    hass = _hass(entry)
    config = integration._config_from_entry(entry)
    run(integration._async_awc_resume_on_startup(hass, entry, config))
    assert _state(entry)["status"] == "exchanging"
    assert _has_call(hass.services.calls, "turn_on", "switch.awc_fill")
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_drain")
    _fire_exchange(hass, entry, age_done=("drain", "fill"))
    assert _state(entry)["status"] == "idle"
    assert _close(_awc(entry)["history"][0]["filledL"], 2.0, 1e-3)


def _two_source_entry(fresh2_over=None, policy=None):
    """drain + fill (fresh) + fill2 (fresh2), alternate policy anchored on 'fill'."""
    return _entry("batch_sequential", awc_over={
        "pumps": {
            "drain": {"switchEntity": "switch.awc_drain", "mlPerS": 100},
            "fill": {"switchEntity": "switch.awc_fill", "mlPerS": 100},
            "fill2": {"switchEntity": "switch.awc_fill2", "mlPerS": 100,
                      "reservoirId": "fresh2"},
        },
        "reservoirs": {
            "fresh": {"capacityLitres": 25, "remainingMl": 25000,
                      "emptyEntity": "binary_sensor.fresh_empty"},
            "fresh2": {"capacityLitres": 25, "remainingMl": 25000,
                       "emptyEntity": "binary_sensor.fresh2_empty", **(fresh2_over or {})},
            "waste": {"capacityLitres": 25, "filledMl": 0,
                      "fullEntity": "binary_sensor.waste_full"},
        },
        "sourcePolicy": policy or {"mode": "alternate", "order": ["fill", "fill2"],
                                   "lastSourceUsed": "fill"},
    })


_TWO_SOURCE_STATES = {"switch.awc_fill2": "off", "binary_sensor.fresh2_empty": "off"}


def test_fill2_end_to_end_alternate_draws_from_second_source():
    # Alternate policy, last change came from 'fill' → this one draws WHOLLY from
    # fill2: its pump runs, its reservoir is debited, history/ledger say so, and the
    # rotation anchor advances. Source 1 is untouched throughout.
    entry = _two_source_entry()
    hass = _hass(entry, _TWO_SOURCE_STATES)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    assert _state(entry)["activeSourceRole"] == "fill2"
    _drive(hass, entry)
    awc = _awc(entry)
    assert awc["state"]["status"] == "idle"
    assert _has_call(hass.services.calls, "turn_on", "switch.awc_fill2")
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_fill")
    assert _close(awc["reservoirs"]["fresh2"]["remainingMl"], 23000.0, 1.0)  # debited 2 L
    assert _close(awc["reservoirs"]["fresh"]["remainingMl"], 25000.0, 1e-6)  # untouched
    assert awc["history"][0]["source"] == "fill2"
    assert _close(awc["ledger"]["perSource"]["fill2"], 2.0, 1e-6)
    assert awc["sourcePolicy"]["lastSourceUsed"] == "fill2"


def test_alternate_skips_insufficient_source_with_warning():
    # fresh2's recorded volume can't cover the change → the rotation falls through to
    # 'fill' and a source-skip warning lands in the activity feed.
    entry = _two_source_entry(fresh2_over={"remainingMl": 100})
    hass = _hass(entry, _TWO_SOURCE_STATES)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    assert _state(entry)["activeSourceRole"] == "fill"
    _drive(hass, entry)
    awc = _awc(entry)
    assert awc["state"]["status"] == "idle"
    assert _has_call(hass.services.calls, "turn_on", "switch.awc_fill")
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_fill2")
    assert awc["history"][0]["source"] == "fill"
    acts = [a for a in integration._config_from_entry(entry).get("activity", [])
            if "skipped" in a.get("message", "")]
    assert len(acts) == 1


def test_fill2_run_pauses_on_its_own_empty_float():
    # The ACTIVE source's float is the one that matters: source 1's float being wet
    # (on) must not block a fill2 change, and fresh2's float tripping mid-run pauses.
    entry = _two_source_entry()
    hass = _hass(entry, {**_TWO_SOURCE_STATES, "binary_sensor.fresh_empty": "on"})
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]  # fresh's float irrelevant
    assert _state(entry)["activeSourceRole"] == "fill2"
    hass.states.set("binary_sensor.fresh2_empty", "on")  # the ACTIVE source runs dry
    _fire_leg(hass, entry)  # drain credited → fill2 leg blocked by fresh2's float
    st = _state(entry)
    assert st["status"] == "paused"
    assert "empty" in st["pausedReason"].lower()
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_fill2")


def test_salt_ledger_accumulates_net_grams():
    # fresh saltPpt 36 vs tank target 35 (salinity band midpoint): a full 2 L change
    # adds 2 L × 36 − 2 L × 35 ≈ +2 g of salt to the net-salt ledger.
    entry = _entry("batch_sequential", awc_over={"reservoirs": {
        "fresh": {"capacityLitres": 25, "remainingMl": 25000,
                  "emptyEntity": "binary_sensor.fresh_empty", "saltPpt": 36},
        "waste": {"capacityLitres": 25, "filledMl": 0,
                  "fullEntity": "binary_sensor.waste_full"},
    }})
    cfg = entry.options[CONF_SETTINGS]
    cfg["sensors"]["salinity"]["min"] = 34
    cfg["sensors"]["salinity"]["max"] = 36
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(cfg)
    assert integration._awc_tank_ppt(integration._config_from_entry(entry)) == 35.0
    hass = _hass(entry)
    assert _start(hass, entry, 2.0, method="batch_sequential")[0]
    _drive(hass, entry)
    assert _state(entry)["status"] == "idle"
    assert _close(_awc(entry)["ledger"]["netSaltGrams"], 2.0, 0.1)


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
