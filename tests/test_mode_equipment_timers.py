"""Unit tests for Mode Actions V2 — per-equipment timers, max-off safety caps, and
exit verification.

These exercise the REAL ``_async_apply_mode`` / scheduler / normalisation code with
Home Assistant stubbed (``_ha_stubs``) + faked (``_fake_ha``). ``install_scheduler``
swaps the point-in-time scheduler for a capturing fake so the timer callbacks can be
fired deterministically; ``_FakeServices`` mutates switch state on turn_on/off so the
on-fire re-checks behave like real HA.

Run standalone:  python3 tests/test_mode_equipment_timers.py
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

from _fake_ha import FakeEntry, FakeHass, install_scheduler, run  # noqa: E402

CONF_SETTINGS = integration.CONF_SETTINGS


def _equip(profile, switch, armed=True, **extra):
    base = {"type": profile, "armed": armed, "switch_entity_id": switch}
    base.update(extra)
    return base


def _cfg(equipment, previews, timers=None, interlocks=None, **extra):
    """Build a config for timer-mechanics tests. Exit verification is disabled here so
    a single fire_all() pass exercises only the timer/cap callbacks (a dedicated test
    covers verification)."""
    cfg = {
        "equipment": equipment,
        "modePreviews": previews,
        "alerts": {"modeVerifyEnabled": False},
    }
    if timers is not None:
        cfg["modeEquipmentTimers"] = timers
    if interlocks is not None:
        cfg["interlocks"] = interlocks
    cfg.update(extra)
    return cfg


def _mode(entry):
    return entry.options[CONF_SETTINGS]["mode"]


def _has_call(calls, service, entity):
    return any(c.service == service and entity in c.data.values() for c in calls)


# --- Normalisation ----------------------------------------------------------

def test_normalise_clamps_floors_and_strips():
    cfg = {
        "modePreviews": {"feed": {"wave": "on", "rp": "off", "light": "unchanged"}},
        "modeEquipmentTimers": {
            "feed": {
                # cycle: onSeconds below the floor -> 10; offSeconds above max -> 86400
                "wave": {"enabled": True, "timerMode": "cycle", "onSeconds": 3, "offSeconds": 999999},
                # once with no hold -> degenerate -> disabled
                "rp": {"enabled": True, "timerMode": "once", "holdSeconds": 0},
                # preview "unchanged" -> stripped
                "light": {"enabled": True, "timerMode": "once", "holdSeconds": 30},
                # no preview at all -> stripped
                "ghost": {"enabled": True, "timerMode": "once", "holdSeconds": 30},
            }
        },
    }
    out = integration._normalise_core_config(cfg)
    timers = out["modeEquipmentTimers"]["feed"]
    assert "light" not in timers and "ghost" not in timers
    assert timers["wave"]["onSeconds"] == integration.MODE_EQUIPMENT_CYCLE_MIN_SECONDS
    assert timers["wave"]["offSeconds"] == integration.MODE_EQUIPMENT_TIMER_MAX_SECONDS
    assert timers["wave"]["enabled"] is True
    assert timers["rp"]["enabled"] is False


def test_normalise_running_clears_runtime_state():
    cfg = {
        "mode": {
            "active": "running",
            "equipmentTimers": {"wave": {"phase": "on", "action": "on"}},
            "maxOffTimers": {"rp": {"fireAt": "2026-01-01T00:00:00+00:00"}},
        }
    }
    out = integration._normalise_core_config(cfg)
    assert out["mode"]["equipmentTimers"] == {}
    assert out["mode"]["maxOffTimers"] == {}


def test_normalise_equipment_max_off_clamped():
    cfg = {"equipment": {"rp": _equip("return_pump", "switch.rp", maxOffSeconds=10**9)}}
    out = integration._normalise_core_config(cfg)
    assert out["equipment"]["rp"]["maxOffSeconds"] == integration.EQUIPMENT_MAX_OFF_MAX_SECONDS


# --- Single-shot (hold then revert to pre-mode state) -----------------------

def test_once_timer_drives_then_reverts():
    cfg = _cfg(
        {"wave": _equip("flow_pump", "switch.wave")},
        {"feed": {"wave": "on"}},
        {"feed": {"wave": {"enabled": True, "timerMode": "once", "holdSeconds": 60}}},
    )
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(states={"switch.wave": "off"}, entries=[entry])
    sched = install_scheduler(integration)

    run(integration._async_apply_mode(hass, entry, "feed", None))
    assert _has_call(hass.services.calls, "turn_on", "switch.wave")  # driven immediately
    assert _mode(entry)["equipmentTimers"]["wave"]["phase"] == "hold"
    assert _mode(entry)["returnPlan"]["wave"] == "off"

    n = len(hass.services.calls)
    run(sched.fire_all())  # fire the hold -> revert to pre-mode "off"
    assert _has_call(hass.services.calls[n:], "turn_off", "switch.wave")
    assert _mode(entry)["equipmentTimers"]["wave"]["phase"] == "done"


# --- Repeating cycle --------------------------------------------------------

def test_cycle_toggles_and_rearms():
    cfg = _cfg(
        {"wave": _equip("flow_pump", "switch.wave")},
        {"feed": {"wave": "on"}},
        {"feed": {"wave": {"enabled": True, "timerMode": "cycle", "onSeconds": 30, "offSeconds": 30}}},
    )
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(states={"switch.wave": "off"}, entries=[entry])
    sched = install_scheduler(integration)

    run(integration._async_apply_mode(hass, entry, "feed", None))
    assert _has_call(hass.services.calls, "turn_on", "switch.wave")
    assert _mode(entry)["equipmentTimers"]["wave"]["phase"] == "on"

    n = len(hass.services.calls)
    run(sched.fire_all())  # ON -> OFF, re-arm
    assert _has_call(hass.services.calls[n:], "turn_off", "switch.wave")
    assert _mode(entry)["equipmentTimers"]["wave"]["phase"] == "off"
    assert len(sched.pending()) >= 1  # re-armed for the next phase

    n2 = len(hass.services.calls)
    run(sched.fire_all())  # OFF -> ON again
    assert _has_call(hass.services.calls[n2:], "turn_on", "switch.wave")
    assert _mode(entry)["equipmentTimers"]["wave"]["phase"] == "on"


# --- Start-delay staggering -------------------------------------------------

def test_start_delay_defers_action():
    cfg = _cfg(
        {
            "rp": _equip("return_pump", "switch.rp"),
            "sk": _equip("skimmer", "switch.sk"),
        },
        {"feed": {"rp": "off", "sk": "off"}},
        {"feed": {"sk": {"enabled": True, "timerMode": "once", "startDelaySeconds": 10, "holdSeconds": 60}}},
    )
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(states={"switch.rp": "on", "switch.sk": "on"}, entries=[entry])
    sched = install_scheduler(integration)

    run(integration._async_apply_mode(hass, entry, "feed", None))
    # rp (no timer) fires immediately; sk (10s start delay) is only scheduled
    assert _has_call(hass.services.calls, "turn_off", "switch.rp")
    assert not any("switch.sk" in c.data.values() for c in hass.services.calls)
    assert _mode(entry)["equipmentTimers"]["sk"]["phase"] == "delay"

    run(sched.fire_all())  # the delay elapses -> sk turns off
    assert _has_call(hass.services.calls, "turn_off", "switch.sk")
    assert _mode(entry)["equipmentTimers"]["sk"]["phase"] == "hold"


# --- Safety guard re-applied on a timer fire --------------------------------

def test_safety_guard_blocks_timer_fire():
    cfg = _cfg(
        {
            "rp": _equip("return_pump", "switch.rp"),
            "ato": _equip("ato", "switch.ato"),
        },
        {"feed": {"ato": "on"}},
        {"feed": {"ato": {"enabled": True, "timerMode": "once", "startDelaySeconds": 5, "holdSeconds": 30}}},
        interlocks={"atoBlockWhenReturnPumpOff": True},
    )
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    # Return pump ON at apply time, so the guard passes and the timer is scheduled.
    hass = FakeHass(states={"switch.rp": "on", "switch.ato": "off"}, entries=[entry])
    sched = install_scheduler(integration)

    run(integration._async_apply_mode(hass, entry, "feed", None))
    assert _mode(entry)["equipmentTimers"]["ato"]["phase"] == "delay"

    hass.states.set("switch.rp", "off")  # return pump now off -> ATO turn-on unsafe
    n = len(hass.services.calls)
    run(sched.fire_all())
    assert not _has_call(hass.services.calls[n:], "turn_on", "switch.ato")
    assert _mode(entry)["equipmentTimers"]["ato"]["phase"] == "done"


# --- Mode change cancels timers and reverts ---------------------------------

def test_mode_change_cancels_timers_and_reverts():
    cfg = _cfg(
        {"wave": _equip("flow_pump", "switch.wave")},
        {"feed": {"wave": "on"}},
        {"feed": {"wave": {"enabled": True, "timerMode": "cycle", "onSeconds": 30, "offSeconds": 30}}},
    )
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(states={"switch.wave": "off"}, entries=[entry])
    sched = install_scheduler(integration)

    run(integration._async_apply_mode(hass, entry, "feed", None))
    assert len(sched.pending()) >= 1

    n = len(hass.services.calls)
    run(integration._async_apply_mode(hass, entry, "running", None))
    assert _has_call(hass.services.calls[n:], "turn_off", "switch.wave")  # reverted
    assert _mode(entry)["equipmentTimers"] == {}
    assert len(sched.pending()) == 0  # cycle cancelled


# --- Restart re-arm ---------------------------------------------------------

def test_restart_rearms_from_persisted_state():
    past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    cfg = _cfg(
        {"wave": _equip("flow_pump", "switch.wave")},
        {"feed": {"wave": "on"}},
        {"feed": {"wave": {"enabled": True, "timerMode": "cycle", "onSeconds": 30, "offSeconds": 30}}},
    )
    cfg["mode"] = {
        "active": "feed",
        "startedAt": "",
        "expiresAt": "",
        "autoReturn": False,
        "returnPlan": {"wave": "off"},
        "equipmentTimers": {
            "wave": {
                "timerMode": "cycle",
                "phase": "on",
                "action": "on",
                "nextFireAt": past,
                "onSeconds": 30,
                "offSeconds": 30,
                "holdSeconds": 0,
            }
        },
        "maxOffTimers": {},
    }
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(states={"switch.wave": "on"}, entries=[entry])
    sched = install_scheduler(integration)

    run(
        integration._async_schedule_equipment_timers(
            hass, entry, integration._config_from_entry(entry)
        )
    )
    assert len(sched.pending()) == 1  # re-armed despite a past nextFireAt

    run(sched.fire_all())  # phase "on" -> toggle off
    assert _has_call(hass.services.calls, "turn_off", "switch.wave")
    assert _mode(entry)["equipmentTimers"]["wave"]["phase"] == "off"


# --- "unchanged" preview + enabled timer is a no-op -------------------------

def test_unchanged_preview_timer_is_noop():
    cfg = _cfg(
        {"light": _equip("lighting", "switch.light")},
        {"feed": {"light": "unchanged"}},
        {"feed": {"light": {"enabled": True, "timerMode": "once", "holdSeconds": 30}}},
    )
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(states={"switch.light": "on"}, entries=[entry])
    sched = install_scheduler(integration)

    run(integration._async_apply_mode(hass, entry, "feed", None))
    assert not any("switch.light" in c.data.values() for c in hass.services.calls)
    assert _mode(entry)["equipmentTimers"] == {}
    assert len(sched.pending()) == 0


# --- Exit verification ------------------------------------------------------

def test_verify_flags_stuck_device():
    cfg = {
        "equipment": {"heater": _equip("heater", "switch.heater")},
        "modePreviews": {"feed": {"heater": "off"}},
        "alerts": {
            "modeVerifyEnabled": True,
            "modeStuckNotify": True,
            "modeVerifyDelaySeconds": 5,
        },
    }
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(states={"switch.heater": "on"}, entries=[entry])
    sched = install_scheduler(integration)

    run(integration._async_apply_mode(hass, entry, "feed", None))
    # Simulate a stranded device: the heater bounces back on after we drove it off.
    hass.states.set("switch.heater", "on")

    run(sched.fire_all())  # fire the read-back verification
    assert any(
        c.domain == "persistent_notification"
        and c.service == "create"
        and c.data.get("notification_id") == "openreef_mode_verify"
        for c in hass.services.calls
    )


def test_verify_silent_when_devices_match():
    cfg = {
        "equipment": {"heater": _equip("heater", "switch.heater")},
        "modePreviews": {"feed": {"heater": "off"}},
        "alerts": {"modeVerifyEnabled": True, "modeStuckNotify": True},
    }
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(states={"switch.heater": "on"}, entries=[entry])
    sched = install_scheduler(integration)

    run(integration._async_apply_mode(hass, entry, "feed", None))
    run(sched.fire_all())  # heater actually went off -> no stuck notification
    assert not any(
        c.data.get("notification_id") == "openreef_mode_verify"
        for c in hass.services.calls
        if c.domain == "persistent_notification"
    )


# --- Max-off safety cap -----------------------------------------------------

def test_max_off_cap_force_restores():
    cfg = _cfg(
        {"rp": _equip("return_pump", "switch.rp", maxOffSeconds=600)},
        {"feed": {"rp": "off"}},
    )
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(states={"switch.rp": "on"}, entries=[entry])
    sched = install_scheduler(integration)

    run(integration._async_apply_mode(hass, entry, "feed", None))
    assert _has_call(hass.services.calls, "turn_off", "switch.rp")
    assert "rp" in _mode(entry)["maxOffTimers"]
    assert len(sched.pending()) == 1  # the cap timer

    n = len(hass.services.calls)
    run(sched.fire_all())  # cap elapses -> force back on
    assert _has_call(hass.services.calls[n:], "turn_on", "switch.rp")
    assert _mode(entry)["maxOffTimers"] == {}


def test_max_off_cap_cancelled_on_return():
    cfg = _cfg(
        {"rp": _equip("return_pump", "switch.rp", maxOffSeconds=600)},
        {"feed": {"rp": "off"}},
    )
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(states={"switch.rp": "on"}, entries=[entry])
    sched = install_scheduler(integration)

    run(integration._async_apply_mode(hass, entry, "feed", None))
    assert "rp" in _mode(entry)["maxOffTimers"]

    run(integration._async_apply_mode(hass, entry, "running", None))
    assert _mode(entry)["maxOffTimers"] == {}
    assert len(sched.pending()) == 0


# --- tiny standalone runner -------------------------------------------------

def _main() -> int:
    tests = sorted(
        (name, obj)
        for name, obj in globals().items()
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
