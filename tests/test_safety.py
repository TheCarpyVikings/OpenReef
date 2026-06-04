"""Safety unit tests — the two promises that make OpenReef a controller you can trust:

  1. Control stays LOCKED until a device is explicitly armed (no accidental switching).
  2. An ATO must not run when return flow isn't confirmed (the return-pump interlock).

These exercise the REAL ``websocket_toggle_equipment`` handler and the interlock
helpers, with Home Assistant stubbed (`_ha_stubs`) + faked (`_fake_ha`). The WS
decorators in the stub are pass-through, so the handler is a plain coroutine here.

Run standalone:  python3 tests/test_safety.py
Or with pytest:  pytest tests/
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
import openreef as integration  # noqa: E402

from _fake_ha import FakeConnection, FakeEntry, FakeHass, run  # noqa: E402

CONF_SETTINGS = integration.CONF_SETTINGS
_block_reason = integration._equipment_safety_block_reason
_return_pump_issues = integration._return_pump_dependency_issues


def _equip(profile, armed, switch):
    return {"type": profile, "armed": armed, "switch_entity_id": switch}


def _config(equipment=None, interlocks=None):
    return {"equipment": equipment or {}, "interlocks": interlocks or {}}


# --- ATO / return-pump interlock (pure logic) ------------------------------

def test_ato_blocked_when_return_pump_off():
    config = _config(
        {"rp": _equip("return_pump", True, "switch.rp")},
        {"atoBlockWhenReturnPumpOff": True},
    )
    hass = FakeHass(states={"switch.rp": "off"})
    reason = _block_reason(hass, config, "ato", _equip("ato", True, "switch.ato"), "on")
    assert reason, "ATO turn-on must be blocked while the return pump is off"
    assert "return flow" in reason.lower()


def test_ato_allowed_when_return_pump_on():
    config = _config(
        {"rp": _equip("return_pump", True, "switch.rp")},
        {"atoBlockWhenReturnPumpOff": True},
    )
    hass = FakeHass(states={"switch.rp": "on"})
    assert _block_reason(hass, config, "ato", _equip("ato", True, "switch.ato"), "on") == ""


def test_ato_allowed_when_interlock_disabled():
    config = _config(
        {"rp": _equip("return_pump", True, "switch.rp")},
        {"atoBlockWhenReturnPumpOff": False},
    )
    hass = FakeHass(states={"switch.rp": "off"})
    assert _block_reason(hass, config, "ato", _equip("ato", True, "switch.ato"), "on") == ""


def test_ato_off_is_never_blocked():
    config = _config(
        {"rp": _equip("return_pump", True, "switch.rp")},
        {"atoBlockWhenReturnPumpOff": True},
    )
    hass = FakeHass(states={"switch.rp": "off"})
    assert _block_reason(hass, config, "ato", _equip("ato", True, "switch.ato"), "off") == ""


def test_non_ato_equipment_is_not_blocked_by_this_interlock():
    config = _config(
        {"rp": _equip("return_pump", True, "switch.rp")},
        {"atoBlockWhenReturnPumpOff": True},
    )
    hass = FakeHass(states={"switch.rp": "off"})
    assert _block_reason(hass, config, "heater", _equip("heater", True, "switch.heater"), "on") == ""


def test_return_pump_issues_flag_off_unavailable_and_skip_unarmed():
    config = _config(
        {
            "rp1": _equip("return_pump", True, "switch.rp1"),
            "rp2": _equip("return_pump", True, "switch.rp2"),
            "rp3": _equip("return_pump", True, "switch.rp3"),
            "rp4": _equip("return_pump", False, "switch.rp4"),  # unarmed -> ignored
        },
    )
    hass = FakeHass(states={"switch.rp1": "on", "switch.rp2": "off", "switch.rp3": "unavailable"})
    issues = _return_pump_issues(hass, config)
    assert len(issues) == 2  # rp2 (off) + rp3 (unavailable); rp1 on is fine; rp4 unarmed skipped


# --- websocket_toggle_equipment: the "locked until armed" gate --------------

def _entry(equipment, interlocks=None):
    return FakeEntry(options={CONF_SETTINGS: {"equipment": equipment, "interlocks": interlocks or {}}})


def _toggle(hass, equipment_id):
    conn = FakeConnection()
    run(integration.websocket_toggle_equipment(hass, conn, {"id": 1, "equipment_id": equipment_id}))
    return conn


def test_toggle_rejects_unarmed_equipment():
    entry = _entry({"light": _equip("lighting", False, "switch.light")})
    hass = FakeHass(states={"switch.light": "off"}, entries=[entry])
    conn = _toggle(hass, "light")
    assert conn.error_codes == ["not_armed"]
    assert hass.services.calls == []  # nothing was switched


def test_toggle_rejects_unmapped_equipment():
    entry = _entry({"light": _equip("lighting", True, "switch.light")})
    hass = FakeHass(states={"switch.light": "off"}, entries=[entry])
    conn = _toggle(hass, "ghost")
    assert conn.error_codes == ["not_mapped"]
    assert hass.services.calls == []


def test_toggle_rejects_when_not_configured():
    hass = FakeHass(entries=[])
    conn = _toggle(hass, "light")
    assert conn.error_codes == ["not_configured"]
    assert hass.services.calls == []


def test_toggle_rejects_missing_entity():
    entry = _entry({"light": _equip("lighting", True, "switch.light")})
    hass = FakeHass(states={}, entries=[entry])  # armed but the switch has no state
    conn = _toggle(hass, "light")
    assert conn.error_codes == ["missing_entity"]
    assert hass.services.calls == []


def test_toggle_rejects_safety_blocked_ato():
    entry = _entry(
        {
            "rp": _equip("return_pump", True, "switch.rp"),
            "ato": _equip("ato", True, "switch.ato"),
        },
        {"atoBlockWhenReturnPumpOff": True},
    )
    # ATO is off -> toggling armed ATO to ON, but the return pump is off -> must be blocked.
    hass = FakeHass(states={"switch.rp": "off", "switch.ato": "off"}, entries=[entry])
    conn = _toggle(hass, "ato")
    assert conn.error_codes == ["safety_blocked"]
    assert hass.services.calls == []  # the ATO was NOT energised


def test_toggle_happy_path_switches_armed_available_equipment():
    entry = _entry({"light": _equip("lighting", True, "switch.light")})
    hass = FakeHass(states={"switch.light": "off"}, entries=[entry])
    conn = _toggle(hass, "light")
    assert conn.errors == [], f"unexpected errors: {conn.error_codes}"
    assert len(hass.services.calls) == 1
    call = hass.services.calls[0]
    assert (call.domain, call.service) == ("switch", "turn_on")  # was off -> turned on
    assert "switch.light" in call.data.values()  # ATTR_ENTITY_ID is stubbed, assert on the value
    assert conn.results, "a success result should be sent"


# --- _async_apply_mode: a mode only ever switches ARMED equipment -----------

def test_apply_mode_only_switches_armed_equipment():
    cfg = {
        "equipment": {
            "heater": _equip("heater", True, "switch.heater"),
            "skimmer": _equip("skimmer", False, "switch.skimmer"),  # disarmed
        },
        "modePreviews": {"feed": {"heater": "off", "skimmer": "off"}},
    }
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(states={"switch.heater": "on", "switch.skimmer": "on"}, entries=[entry])
    result = run(integration._async_apply_mode(hass, entry, "feed", None))
    # the armed heater was switched off...
    assert any(c.service == "turn_off" and "switch.heater" in c.data.values() for c in hass.services.calls)
    # ...and the disarmed skimmer was never touched.
    assert not any("switch.skimmer" in c.data.values() for c in hass.services.calls)
    assert any(s.get("equipment_id") == "skimmer" for s in result.get("skipped_locked", []))


def test_apply_mode_skips_unavailable_switch():
    cfg = {
        "equipment": {"heater": _equip("heater", True, "switch.heater")},
        "modePreviews": {"feed": {"heater": "off"}},
    }
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(states={"switch.heater": "unavailable"}, entries=[entry])
    result = run(integration._async_apply_mode(hass, entry, "feed", None))
    # an unavailable switch is never driven (alert-notification housekeeping calls are fine)
    assert not any(call.domain == "switch" for call in hass.services.calls)
    assert any(s.get("equipment_id") == "heater" for s in result.get("skipped_missing", []))


# --- ATO duty-cycle window math (anchor 00:00, hourly interval, 120s on) -----

def _ato_cfg():
    return {
        "interlocks": {
            "atoDutyCycleAnchorTime": "00:00",
            "atoDutyCycleIntervalMinutes": 60,
            "atoDutyCycleOnSeconds": 120,
        }
    }


def test_ato_window_active_at_window_start():
    now = datetime(2026, 1, 1, 0, 0, 30, tzinfo=timezone.utc)  # 30s into the on-period
    active, _key, _off = integration._ato_duty_cycle_window(_ato_cfg(), now)
    assert active is True


def test_ato_window_inactive_after_on_period():
    now = datetime(2026, 1, 1, 0, 5, 0, tzinfo=timezone.utc)  # 5 min in -> past the 120s on
    active, _key, _off = integration._ato_duty_cycle_window(_ato_cfg(), now)
    assert active is False


def test_ato_window_active_again_next_interval():
    now = datetime(2026, 1, 1, 1, 0, 30, tzinfo=timezone.utc)  # 30s into the 2nd hourly window
    active, _key, _off = integration._ato_duty_cycle_window(_ato_cfg(), now)
    assert active is True


# --- _async_set_ato_duty_cycle_state: the async ATO setter ------------------

def _ato_state_entry(*, mode="running", ato_state_armed=True, with_return_pump=False, block=False):
    equipment = {"ato": _equip("ato", ato_state_armed, "switch.ato")}
    if with_return_pump:
        equipment["rp"] = _equip("return_pump", True, "switch.rp")
    cfg = {
        "mode": {"active": mode},
        "equipment": equipment,
        "interlocks": {"atoBlockWhenReturnPumpOff": block},
    }
    return FakeEntry(options={CONF_SETTINGS: cfg})


def _set_ato(hass, entry, target):
    run(integration._async_set_ato_duty_cycle_state(hass, entry, target, "window-1", "started"))


def test_ato_setter_is_noop_outside_running_mode():
    entry = _ato_state_entry(mode="feed")
    hass = FakeHass(states={"switch.ato": "off"}, entries=[entry])
    _set_ato(hass, entry, "on")
    assert not any(c.domain == "switch" for c in hass.services.calls)  # ATO only cycles in Running


def test_ato_setter_on_is_blocked_when_return_pump_off():
    entry = _ato_state_entry(mode="running", with_return_pump=True, block=True)
    hass = FakeHass(states={"switch.ato": "off", "switch.rp": "off"}, entries=[entry])
    _set_ato(hass, entry, "on")
    assert not any(c.domain == "switch" for c in hass.services.calls)  # not energised while pump off


def test_ato_setter_on_fires_when_clear():
    entry = _ato_state_entry(mode="running", block=False)
    hass = FakeHass(states={"switch.ato": "off"}, entries=[entry])
    _set_ato(hass, entry, "on")
    assert any(c.service == "turn_on" and "switch.ato" in c.data.values() for c in hass.services.calls)


def test_ato_setter_off_turns_ato_off():
    entry = _ato_state_entry(mode="running")
    hass = FakeHass(states={"switch.ato": "on"}, entries=[entry])
    _set_ato(hass, entry, "off")
    assert any(c.service == "turn_off" and "switch.ato" in c.data.values() for c in hass.services.calls)


def test_ato_setter_skips_when_already_in_target_state():
    entry = _ato_state_entry(mode="running")
    hass = FakeHass(states={"switch.ato": "on"}, entries=[entry])
    _set_ato(hass, entry, "on")  # already on
    assert not any(c.domain == "switch" for c in hass.services.calls)


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
