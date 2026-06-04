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
