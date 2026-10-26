"""Intentional unload must stop owned actuators before cancelling stop timers."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

from test_save_guards import integration, FakeEntry, FakeHass, run, CONF_SETTINGS


def config():
    return integration._normalise_core_config({
        "automaticWaterChange": {"pumps": {
            "drain": {"switchEntity": "switch.drain"},
            "fill": {"switchEntity": "switch.fill"},
        }},
        "dosing": {"channels": {
            "generic": {"driver": {"type": "ha_switch_timed", "entities": {
                "powerSwitch": "switch.food"}}},
            "firmware": {"driver": {"type": "reefnode_stepper", "entities": {
                "enabledSwitch": "switch.enabled", "haSuspendSwitch": "switch.suspend"}}},
        }},
        "mixingStation": {"switches": {
            "rodiBooster": {"switchEntity": "switch.booster"},
            "mixPumpA": {"switchEntity": "switch.mix_a"},
            "mixPumpB": {"switchEntity": "switch.mix_b"},
            "heater": {"switchEntity": "switch.heater"},
        }},
    })


def make(cfg=None):
    entry = FakeEntry(options={CONF_SETTINGS: cfg or config()})
    hass = FakeHass(entries=[entry], states={
        f"switch.{name}": "off" if name == "suspend" else "on"
        for name in ("drain", "fill", "food", "enabled", "suspend", "booster",
                     "mix_a", "mix_b", "heater", "unrelated", "ato")
    })
    return hass, entry


def calls(hass):
    return {(call.data[integration.ATTR_ENTITY_ID], call.service)
            for call in hass.services.calls if call.domain == "switch"}


def test_stops_all_owned_pumps_and_service_scripts_without_crediting_volume():
    cfg = config()
    cfg["automaticWaterChange"]["state"].update(status="draining", phaseStartedAt="2026-10-25T12:00:00+00:00")
    cfg["dosing"]["channels"]["generic"]["state"].update(
        haRunStartedAt="2026-10-25T12:00:00+00:00", haRunTargetMl=100)
    before = deepcopy(cfg)
    hass, entry = make(cfg)
    assert run(integration._async_shutdown_dosing_and_awc(hass, entry))
    assert calls(hass) == {("switch.drain", "turn_off"), ("switch.fill", "turn_off"),
                           ("switch.food", "turn_off"), ("switch.enabled", "turn_off"),
                           ("switch.suspend", "turn_on")}
    assert all(call.kwargs["blocking"] for call in hass.services.calls)
    assert entry.options[CONF_SETTINGS] == before
    assert hass.data[integration.DOMAIN]["unloading"]
    assert hass.states.get("switch.unrelated").state == "on"


def test_failure_keeps_callbacks_and_attempts_every_other_stop():
    hass, entry = make()
    cancelled = []
    stop = lambda: cancelled.append(True)
    hass.data[integration.DOMAIN] = {integration.NPS_DRAIN_UNSUB: stop}
    hass.services.fail_on.add(("switch", "turn_off", "switch.drain"))
    assert not run(integration.async_unload_entry(hass, entry))
    assert hass.states.get("switch.food").state == "off"
    assert hass.states.get("switch.fill").state == "off"
    assert hass.states.get("switch.suspend").state == "on"
    assert hass.data[integration.DOMAIN][integration.NPS_DRAIN_UNSUB] is stop
    assert not cancelled
    assert "switch.drain" in hass.data[integration.DOMAIN]["shutdownFailures"]


def test_successful_unload_cancels_callbacks_only_after_outputs_confirm_stop():
    hass, entry = make()
    cancelled = []

    def cancel_stop():
        assert hass.states.get("switch.drain").state == "off"
        assert hass.states.get("switch.food").state == "off"
        assert hass.states.get("switch.enabled").state == "off"
        assert hass.states.get("switch.suspend").state == "on"
        cancelled.append(True)

    hass.data[integration.DOMAIN] = {integration.NPS_DRAIN_UNSUB: cancel_stop}
    assert run(integration.async_unload_entry(hass, entry))
    assert cancelled == [True]


def test_hung_output_is_bounded_and_does_not_block_other_stops():
    async def scenario():
        hass, entry = make()
        original = hass.services.async_call

        async def slow_call(domain, service, data=None, **kwargs):
            if data.get(integration.ATTR_ENTITY_ID) == "switch.drain":
                await asyncio.Event().wait()
            await original(domain, service, data, **kwargs)

        hass.services.async_call = slow_call
        old_timeout = integration._AUTOMATION_SHUTDOWN_TIMEOUT_S
        integration._AUTOMATION_SHUTDOWN_TIMEOUT_S = 0.02
        try:
            assert not await integration._async_shutdown_dosing_and_awc(hass, entry)
        finally:
            integration._AUTOMATION_SHUTDOWN_TIMEOUT_S = old_timeout
        assert hass.states.get("switch.fill").state == "off"
        assert hass.states.get("switch.suspend").state == "on"
    run(scenario())


def test_waits_for_inflight_on_then_stops_and_blocks_later_starts():
    async def scenario():
        hass, entry = make()
        held, release = asyncio.Event(), asyncio.Event()

        async def earlier_run():
            async with integration._awc_lock(hass):
                held.set()
                await release.wait()
                # Represents the physical dispatch that passed its guard before unload.
                await hass.services.async_call("switch", "turn_on", {
                    integration.ATTR_ENTITY_ID: "switch.drain"}, blocking=True)

        earlier = asyncio.create_task(earlier_run())
        await held.wait()
        shutdown = asyncio.create_task(integration._async_shutdown_dosing_and_awc(hass, entry))
        await asyncio.sleep(0)
        assert hass.data[integration.DOMAIN]["unloading"]
        assert not shutdown.done()
        release.set()
        await earlier
        assert await shutdown
        assert hass.states.get("switch.drain").state == "off"
        for action in (
            integration._async_awc_set_pump(hass, config(), "drain", True, None),
            integration._async_mixing_set_switch(hass, config(), "rodiBooster", True, None),
        ):
            try:
                await action
                raise AssertionError("new run accepted during unload")
            except RuntimeError as err:
                assert "unloading" in str(err)
    run(scenario())


def test_lock_timeout_keeps_fallback_timer_and_still_stops_outputs():
    async def scenario():
        hass, entry = make()
        held, release = asyncio.Event(), asyncio.Event()

        async def owner():
            async with integration._dosing_lock(hass):
                held.set()
                await release.wait()

        task = asyncio.create_task(owner())
        await held.wait()
        stop = lambda: None
        hass.data[integration.DOMAIN][integration.NPS_DRAIN_UNSUB] = stop
        old_timeout = integration._AUTOMATION_SHUTDOWN_TIMEOUT_S
        integration._AUTOMATION_SHUTDOWN_TIMEOUT_S = 0.02
        try:
            assert not await integration.async_unload_entry(hass, entry)
        finally:
            integration._AUTOMATION_SHUTDOWN_TIMEOUT_S = old_timeout
            release.set()
            await task
        assert hass.states.get("switch.food").state == "off"
        assert hass.data[integration.DOMAIN][integration.NPS_DRAIN_UNSUB] is stop
        assert "actuator ownership" in hass.data[integration.DOMAIN]["shutdownFailures"]
    run(scenario())


def test_failed_unload_never_runs_setup_again():
    hass, entry = make()
    hass.services.fail_on.add(("switch", "turn_off", "switch.drain"))
    setups = []
    old_setup = integration.async_setup_entry

    async def setup(*args):
        setups.append(True)

    integration.async_setup_entry = setup
    try:
        run(integration.async_reload_entry(hass, entry))
    finally:
        integration.async_setup_entry = old_setup
    assert not setups
    assert hass.data[integration.DOMAIN]["unloading"]


def test_simulated_water_systems_never_touch_real_outputs():
    cfg = config()
    cfg["automaticWaterChange"]["simulation"]["enabled"] = True
    cfg["mixingStation"]["simulate"] = True
    cfg["mixingStation"]["batch"]["state"] = "salting"
    cfg["mixingStation"]["rodi"]["draw"]["active"] = True
    cfg["dosing"]["channels"] = {}
    hass, entry = make(cfg)
    assert run(integration._async_shutdown_dosing_and_awc(hass, entry))
    assert not hass.services.calls


def test_ato_task_is_cancelled_and_only_owned_duty_output_is_stopped():
    cfg = config()
    cfg["interlocks"]["atoDutyCycleEnabled"] = True
    cfg["equipment"]["ato_test"] = {
        "armed": True, "type": "ato", "switch_entity_id": "switch.ato"}
    hass, entry = make(cfg)
    cancelled = []
    hass.data[integration.DOMAIN] = {"ato_duty_cycle_task": SimpleNamespace(
        done=lambda: False, cancel=lambda: cancelled.append(True))}
    assert run(integration._async_shutdown_dosing_and_awc(hass, entry))
    assert cancelled == [True]
    assert ("switch.ato", "turn_off") in calls(hass)
    cfg["interlocks"]["atoDutyCycleEnabled"] = False
    hass, entry = make(cfg)
    assert run(integration._async_shutdown_dosing_and_awc(hass, entry))
    assert ("switch.ato", "turn_off") not in calls(hass)


def test_active_mixing_outputs_stop_without_crediting_interrupted_draw():
    cfg = config()
    mix = cfg["mixingStation"]
    mix["batch"]["circulateUntil"] = "2026-10-25T12:10:00+00:00"
    mix["rodi"]["draw"].update(active=True, litres=10, destination="mix",
                                startedAt="2026-10-25T12:00:00+00:00",
                                endsAt="2026-10-25T13:00:00+00:00")
    before_vessels = deepcopy(mix["vessels"])
    hass, entry = make(cfg)
    assert run(integration._async_shutdown_dosing_and_awc(hass, entry))
    assert {("switch.booster", "turn_off"), ("switch.mix_a", "turn_off"),
            ("switch.mix_b", "turn_off")} <= calls(hass)
    assert ("switch.heater", "turn_off") not in calls(hass)
    saved = entry.options[CONF_SETTINGS]["mixingStation"]
    assert saved["rodi"]["draw"]["active"] is False
    assert saved["rodi"]["draw"]["startedAt"] == mix["rodi"]["draw"]["startedAt"]
    assert saved["rodi"]["draw"]["litres"] == 10
    assert saved["rodi"]["draw"]["endsAt"] == ""
    assert saved["vessels"] == before_vessels
    assert saved["rodi"]["litresProcessed"] == 0
    assert "actual volume is unknown" in entry.options[CONF_SETTINGS]["activity"][0]["message"]


def test_calibration_retains_start_and_freezes_only_after_confirmed_stop():
    for fail in (False, True):
        cfg = config()
        cal = cfg["mixingStation"]["rodi"]["calibration"]
        cal.update(active=True, startedAt="2026-10-25T12:00:00+00:00", stoppedAt="")
        hass, entry = make(cfg)
        if fail:
            hass.services.fail_on.add(("switch", "turn_off", "switch.booster"))
        assert run(integration._async_shutdown_dosing_and_awc(hass, entry)) is not fail
        saved = entry.options[CONF_SETTINGS]["mixingStation"]["rodi"]["calibration"]
        assert saved["active"]
        assert saved["startedAt"] == cal["startedAt"]
        assert bool(saved["stoppedAt"]) is not fail


if __name__ == "__main__":
    tests = [value for name, value in globals().copy().items() if name.startswith("test_")]
    for test in tests:
        test()
    print(f"{len(tests)}/{len(tests)} automation shutdown tests passed")
