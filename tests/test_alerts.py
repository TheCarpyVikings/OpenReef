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
