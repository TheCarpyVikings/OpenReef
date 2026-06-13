"""Alert-evaluation unit tests — does OpenReef correctly flag a tank out of range?

Covers the alerting brain (``_sensor_alert_items``) and the transition detector
(``_sync_alert_state``, which appends history + drives event-triggered captures),
with Home Assistant stubbed (`_ha_stubs`) + faked (`_fake_ha`).

Run standalone:  python3 tests/test_alerts.py
Or with pytest:  pytest tests/
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
import openreef as integration  # noqa: E402

from _fake_ha import FakeHass  # noqa: E402

from datetime import datetime  # noqa: E402

items = integration._sensor_alert_items
sync = integration._sync_alert_state


def _numeric(entity, lo, hi, *, enabled=True, alerts=True, buffer=10, unit="°C"):
    return {
        "entity_id": entity, "label": "Probe", "enabled": enabled, "alertsEnabled": alerts,
        "kind": "numeric", "unit": unit, "min": lo, "max": hi, "warningBuffer": buffer,
    }


def _binary(entity, *, enabled=True):
    return {
        "entity_id": entity, "label": "Leak", "enabled": enabled,
        "alertsEnabled": True, "kind": "binary",
    }


def _cfg(sensors, alerts=None):
    return {"sensors": sensors, "alerts": alerts or {}}


def _sev(result):
    return {item["id"]: item["severity"] for item in result}


# --- threshold evaluation ---------------------------------------------------

def test_in_range_numeric_has_no_alert():
    hass = FakeHass(states={"sensor.temp": "26.0"})
    assert items(hass, _cfg({"temp": _numeric("sensor.temp", 24.5, 27.5)})) == []


def test_over_max_is_critical():
    hass = FakeHass(states={"sensor.temp": "28.0"})
    assert _sev(items(hass, _cfg({"temp": _numeric("sensor.temp", 24.5, 27.5)}))) == {"temp": "critical"}


def test_under_min_is_critical():
    hass = FakeHass(states={"sensor.temp": "23.0"})
    assert _sev(items(hass, _cfg({"temp": _numeric("sensor.temp", 24.5, 27.5)}))) == {"temp": "critical"}


def test_near_threshold_is_warning():
    # range 24.5–27.5, 10% buffer -> warns within 0.3 of an edge but still inside range.
    hass = FakeHass(states={"sensor.temp": "27.3"})
    assert _sev(items(hass, _cfg({"temp": _numeric("sensor.temp", 24.5, 27.5, buffer=10)}))) == {"temp": "warning"}


def test_unmapped_enabled_sensor_warns():
    hass = FakeHass(states={})
    result = items(hass, _cfg({"temp": _numeric("", 24.5, 27.5)}))
    assert _sev(result) == {"temp": "warning"}
    assert "not mapped" in result[0]["title"]


def test_unavailable_sensor_warns():
    hass = FakeHass(states={"sensor.temp": "unavailable"})
    result = items(hass, _cfg({"temp": _numeric("sensor.temp", 24.5, 27.5)}))
    assert _sev(result) == {"temp": "warning"}
    assert "not reporting" in result[0]["title"]


def test_binary_leak_on_is_critical():
    hass = FakeHass(states={"binary_sensor.leak": "on"})
    assert _sev(items(hass, _cfg({"leak": _binary("binary_sensor.leak")}))) == {"leak": "critical"}


def test_binary_leak_off_has_no_alert():
    hass = FakeHass(states={"binary_sensor.leak": "off"})
    assert items(hass, _cfg({"leak": _binary("binary_sensor.leak")})) == []


def test_disabled_sensor_is_skipped():
    hass = FakeHass(states={"sensor.temp": "99"})
    assert items(hass, _cfg({"temp": _numeric("sensor.temp", 24.5, 27.5, enabled=False)})) == []


def test_alerts_disabled_for_sensor_is_skipped():
    hass = FakeHass(states={"sensor.temp": "99"})
    assert items(hass, _cfg({"temp": _numeric("sensor.temp", 24.5, 27.5, alerts=False)})) == []


# --- transition detection (history + capture trigger) -----------------------

def test_ok_to_critical_is_a_transition_and_records_history():
    cfg = _cfg({"temp": _numeric("sensor.temp", 24.5, 27.5)})
    hass = FakeHass(states={"sensor.temp": "30.0"})
    transitions = sync(hass, cfg)
    assert [t["state"] for t in transitions] == ["critical"]
    assert cfg["alerts"]["lastStates"]["temp"] == "critical"
    assert len(cfg["alerts"].get("history", [])) == 1


def test_unchanged_critical_is_not_a_transition():
    cfg = _cfg({"temp": _numeric("sensor.temp", 24.5, 27.5)})
    hass = FakeHass(states={"sensor.temp": "30.0"})
    sync(hass, cfg)                 # ok -> critical
    assert sync(hass, cfg) == []    # critical -> critical: nothing fires again


def test_in_range_from_clean_state_is_not_a_transition():
    cfg = _cfg({"temp": _numeric("sensor.temp", 24.5, 27.5)})
    hass = FakeHass(states={"sensor.temp": "26.0"})
    assert sync(hass, cfg) == []    # resolved with no prior state is not a transition


def test_critical_to_resolved_is_a_transition():
    cfg = _cfg({"temp": _numeric("sensor.temp", 24.5, 27.5)})
    hass = FakeHass(states={"sensor.temp": "30.0"})
    sync(hass, cfg)                 # -> critical
    hass.states.set("sensor.temp", "26.0")
    assert [t["state"] for t in sync(hass, cfg)] == ["resolved"]


# --- tiny standalone runner -------------------------------------------------

# --- lighting-schedule gating of light-dependent (PAR) low alerts -----------

def _par(**over):
    base = {
        "entity_id": "sensor.par", "label": "PAR", "enabled": True, "alertsEnabled": True,
        "kind": "numeric", "unit": "PAR", "min": 50, "max": 350, "warningBuffer": 10,
        "lightGated": True,
    }
    base.update(over)
    return base


def _light_cfg(par, schedule):
    return {"sensors": {"par": par}, "alerts": {}, "lightingSchedule": schedule}


SIMPLE = {"mode": "simple", "onTime": "08:00", "offTime": "20:00", "rampGraceMinutes": 0}
NIGHT = datetime(2026, 1, 15, 2, 0)
DAY = datetime(2026, 1, 15, 14, 0)


def test_low_par_at_night_is_suppressed():
    hass = FakeHass(states={"sensor.par": "0"})
    assert _sev(items(hass, _light_cfg(_par(), SIMPLE), now_local=NIGHT)) == {}


def test_low_par_during_day_alerts():
    hass = FakeHass(states={"sensor.par": "0"})
    assert _sev(items(hass, _light_cfg(_par(), SIMPLE), now_local=DAY)) == {"par": "critical"}


def test_high_par_alerts_even_at_night():
    # Too much light is always wrong — the high side is never gated.
    hass = FakeHass(states={"sensor.par": "400"})
    assert _sev(items(hass, _light_cfg(_par(), SIMPLE), now_local=NIGHT)) == {"par": "critical"}


def test_non_gated_sensor_alerts_at_night():
    hass = FakeHass(states={"sensor.par": "0"})
    assert _sev(items(hass, _light_cfg(_par(lightGated=False), SIMPLE), now_local=NIGHT)) == {"par": "critical"}


def test_schedule_off_means_no_suppression():
    hass = FakeHass(states={"sensor.par": "0"})
    assert _sev(items(hass, _light_cfg(_par(), {"mode": "off"}), now_local=NIGHT)) == {"par": "critical"}


def test_ramp_grace_suppresses_low_par_at_sunrise():
    sched = {"mode": "simple", "onTime": "08:00", "offTime": "20:00", "rampGraceMinutes": 60}
    hass = FakeHass(states={"sensor.par": "20"})
    # 08:30 is inside the dawn ramp grace -> suppressed; 09:30 (ramp done) -> alert
    assert _sev(items(hass, _light_cfg(_par(), sched), now_local=datetime(2026, 1, 15, 8, 30))) == {}
    assert _sev(items(hass, _light_cfg(_par(), sched), now_local=datetime(2026, 1, 15, 9, 30))) == {"par": "critical"}


def test_low_par_warning_band_suppressed_at_night():
    hass = FakeHass(states={"sensor.par": "60"})  # above min, inside warning band
    assert _sev(items(hass, _light_cfg(_par(), SIMPLE), now_local=NIGHT)) == {}
    assert _sev(items(hass, _light_cfg(_par(), SIMPLE), now_local=DAY)) == {"par": "warning"}


def test_equal_time_schedule_never_suppresses_low_par():
    # A degenerate onTime == offTime schedule must NOT silence a real low-PAR alert.
    sched = {"mode": "simple", "onTime": "08:00", "offTime": "08:00", "rampGraceMinutes": 0}
    hass = FakeHass(states={"sensor.par": "0"})
    assert _sev(items(hass, _light_cfg(_par(), sched), now_local=NIGHT)) == {"par": "critical"}
    assert _sev(items(hass, _light_cfg(_par(), sched), now_local=DAY)) == {"par": "critical"}


def test_reef_mode_gates_par():
    sched = {"mode": "reef", "reefPreset": "gbr_central", "offsetHours": 2, "rampGraceMinutes": 30}
    hass = FakeHass(states={"sensor.par": "0"})
    assert _sev(items(hass, _light_cfg(_par(), sched), now_local=datetime(2026, 1, 15, 3, 0))) == {}
    assert _sev(items(hass, _light_cfg(_par(), sched), now_local=datetime(2026, 1, 15, 14, 0))) == {"par": "critical"}


# --- suppression helper + transition carry-forward (no dusk/dawn churn) -------

supp = integration._sensor_low_suppressed


def test_low_suppressed_helper():
    assert supp({"lightingSchedule": SIMPLE}, _par(), NIGHT) is True
    assert supp({"lightingSchedule": SIMPLE}, _par(), DAY) is False
    assert supp({"lightingSchedule": {"mode": "off"}}, _par(), NIGHT) is False
    assert supp({"lightingSchedule": SIMPLE}, _par(lightGated=False), NIGHT) is False


def test_gated_sensor_holds_state_overnight_without_churn():
    # A genuinely-critical daytime PAR must NOT log a "resolved" transition at dusk
    # (and re-alert at dawn). The state is held while the lights are off.
    cfg = {"sensors": {"par": _par()}, "alerts": {"lastStates": {"par": "critical"}}, "lightingSchedule": SIMPLE}
    hass = FakeHass(states={"sensor.par": "0"})
    assert sync(hass, cfg, now_local=NIGHT) == []                       # no transition at night
    assert cfg["alerts"]["lastStates"]["par"] == "critical"            # held, not resolved
    assert sync(hass, cfg, now_local=DAY) == []                        # still critical by day -> no new transition
    assert cfg["alerts"]["lastStates"]["par"] == "critical"


def test_gated_sensor_resolves_during_day_when_recovered():
    cfg = {"sensors": {"par": _par()}, "alerts": {"lastStates": {"par": "critical"}}, "lightingSchedule": SIMPLE}
    hass = FakeHass(states={"sensor.par": "200"})  # back in range (50-350)
    transitions = sync(hass, cfg, now_local=DAY)
    assert any(t["state"] == "resolved" for t in transitions)


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
