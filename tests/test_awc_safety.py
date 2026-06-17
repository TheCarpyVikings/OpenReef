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


def _awc_block(method="batch_simultaneous", **over):
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


def _entry(method="batch_simultaneous", equipment=None, awc_over=None):
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

def test_batch_simultaneous_completes():
    entry = _entry("batch_simultaneous")
    hass = _hass(entry)
    started, reasons = _start(hass, entry, 2.0)
    assert started and not reasons
    assert _state(entry)["status"] == "exchanging"
    assert _has_call(hass.services.calls, "turn_on", "switch.awc_drain")
    assert _has_call(hass.services.calls, "turn_on", "switch.awc_fill")

    _fire_leg(hass, entry)
    awc = _awc(entry)
    assert awc["state"]["status"] == "idle"
    assert _has_call(hass.services.calls, "turn_off", "switch.awc_drain")
    assert _has_call(hass.services.calls, "turn_off", "switch.awc_fill")
    assert len(awc["history"]) == 1 and not awc["history"][0]["partial"]
    assert _close(awc["history"][0]["filledL"], 2.0, 1e-6)
    assert _close(awc["todayLitres"], 2.0, 1e-6)
    # dead-reckoned reservoirs: fresh 25L−2L=23L, waste 0+2L=2L
    assert _close(awc["reservoirs"]["fresh"]["remainingMl"], 23000)
    assert _close(awc["reservoirs"]["waste"]["filledMl"], 2000)


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


def test_leg_timer_is_armed_via_scheduler():
    sched = install_scheduler(integration)
    entry = _entry("batch_simultaneous")
    hass = _hass(entry)
    _start(hass, entry, 1.0)
    # Exactly the AWC leg timer should be pending (mode is 'running', nothing else arms).
    pending = sched.pending()
    assert len(pending) >= 1
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


# --- ATO coordination --------------------------------------------------------

def test_ato_suspended_during_change_and_blocks_turn_on():
    equipment = {"ato": {"type": "ato", "armed": True, "switch_entity_id": "switch.ato"}}
    entry = _entry("batch_simultaneous", equipment=equipment)
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

    _fire_leg(hass, entry)  # finalize → hold-off window
    # still suspended during the post-change stabilization hold-off
    assert integration._awc_ato_suspended(entry.options[CONF_SETTINGS]) is True


# --- Resume-to-balance on restart -------------------------------------------

def test_resume_to_balance_on_startup():
    # Simulate a crash after draining 2 L but before filling (sequential).
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
    # the fill leg is re-begun (resume-to-balance), pumps re-energised
    assert _state(entry)["status"] == "filling"
    assert _has_call(hass.services.calls, "turn_on", "switch.awc_fill")
    _drive(hass, entry)
    assert _state(entry)["status"] == "idle"
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
    assert _state(entry)["status"] == "exchanging"

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

    conn2 = FakeConnection()
    run(integration.websocket_awc_calibrate(hass, conn2, {"id": 2, "role": "fill",
        "points": [[10, 520], [20, 1020], [30, 1520]]}))
    assert not conn2.errors, conn2.error_codes
    assert _close(_awc(entry)["pumps"]["fill"]["mlPerS"], 50.0, 1e-6)
    assert _close(_awc(entry)["pumps"]["fill"]["interceptMl"], 20.0, 1e-6)


def test_ws_acknowledge_clears_fault():
    entry = _entry("batch_sequential")
    hass = _hass(entry)
    _start(hass, entry, 2.0, method="batch_sequential")
    hass.states.set("binary_sensor.leak", "on")
    _fire_leg(hass, entry)
    assert _state(entry)["status"] == "fault"

    conn = FakeConnection()
    run(integration.websocket_awc_acknowledge(hass, conn, {"id": 1}))
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


def test_scheduler_starts_due_batch_change():
    entry = _sched_entry("batch_simultaneous")
    hass = _hass(entry)
    run(integration._async_awc_schedule_tick(hass, entry, _now(2, 30)))
    st = _state(entry)
    assert st["status"] == "exchanging"
    assert _close(st["targetLitres"], 4.0, 1e-6)


def test_scheduler_skips_before_due_time():
    entry = _sched_entry("batch_simultaneous")
    hass = _hass(entry)
    run(integration._async_awc_schedule_tick(hass, entry, _now(1, 0)))
    assert _state(entry)["status"] == "idle"
    # nextRun is surfaced for the panel
    assert _state(entry)["nextRun"]


def test_scheduler_continuous_trickles_in_window():
    entry = _sched_entry("continuous", windowStart="00:00", windowEnd="00:00", amount=4.8)
    hass = _hass(entry)
    run(integration._async_awc_schedule_tick(hass, entry, _now(12, 0)))
    # a small continuous micro-exchange has begun
    assert _state(entry)["status"] == "exchanging"
    assert 0 < _state(entry)["targetLitres"] < 0.1


def test_scheduler_continuous_skips_outside_window():
    entry = _sched_entry("continuous", windowStart="01:00", windowEnd="05:00", amount=4.8)
    hass = _hass(entry)
    run(integration._async_awc_schedule_tick(hass, entry, _now(12, 0)))
    assert _state(entry)["status"] == "idle"


def test_scheduler_does_nothing_when_schedule_disabled():
    entry = _sched_entry("batch_simultaneous", enabled=False)
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
