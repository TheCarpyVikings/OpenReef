"""Cross-controller binding and stale-settings safety regressions."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from test_save_guards import integration, FakeEntry, FakeHass, FakeConnection, run, CONF_SETTINGS


def config():
    return integration._normalise_core_config({
        "automaticWaterChange": {
            "pumps": {"drain": {"switchEntity": "switch.drain", "mlPerS": 20},
                      "fill": {"switchEntity": "switch.fill", "mlPerS": 20}},
        },
        "dosing": {"enabled": True, "channels": {
            "food": {"name": "Food", "enabled": False,
                     "driver": {"type": "ha_switch_timed", "entities": {"powerSwitch": "switch.food"}}},
        }},
    })


def test_shared_pump_and_wrong_domain_are_rejected():
    cfg = config()
    cfg["dosing"]["channels"]["food"]["driver"]["entities"]["powerSwitch"] = "switch.drain"
    errors = integration._automation_binding_errors(cfg)
    assert "awc.drain" in errors and "dosing.food.powerSwitch" in errors
    cfg["dosing"]["channels"]["food"]["driver"]["entities"]["powerSwitch"] = "sensor.flow"
    assert "requires a switch" in integration._automation_binding_errors(cfg)["dosing.food.powerSwitch"]


def test_shared_readonly_sensor_is_allowed_but_distinct_numbers_are_not():
    cfg = config()
    entities = cfg["dosing"]["channels"]["food"]["driver"]["entities"]
    entities.update(dosedTodaySensor="sensor.shared", reservoirRemainingSensor="sensor.shared")
    assert not integration._automation_binding_errors(cfg)
    entities.update(manualDoseMlNumber="number.volume", doseMlNumber="number.volume")
    assert integration._automation_binding_errors(cfg)


def test_awc_cannot_be_rebound_or_recalibrated_during_a_run():
    old = config()
    old["automaticWaterChange"]["state"]["status"] = "draining"
    hass = FakeHass()
    for key, value in (("switchEntity", "switch.other"), ("mlPerS", 1)):
        new = deepcopy(old)
        new["automaticWaterChange"]["pumps"]["drain"][key] = value
        assert integration._automation_settings_error(hass, old, new)
    new = deepcopy(old)
    new["automaticWaterChange"]["enabled"] = False
    assert not integration._automation_settings_error(hass, old, new)


def test_dosing_channel_removal_needs_disabled_and_confirmed_off():
    old = config()
    new = deepcopy(old)
    new["dosing"]["channels"] = {}
    hass = FakeHass(states={"switch.food": "off"})
    old["dosing"]["channels"]["food"]["enabled"] = True
    assert integration._automation_settings_error(hass, old, new)
    old["dosing"]["channels"]["food"]["enabled"] = False
    hass.states.set("switch.food", "unavailable")
    assert integration._automation_settings_error(hass, old, new)
    hass.states.set("switch.food", "off")
    assert not integration._automation_settings_error(hass, old, new)


def test_stale_save_and_alias_preserve_dose_stop_and_counters():
    for handler, key in ((integration.websocket_save_config, "config"),
                         (integration.websocket_update_config_alias, "settings")):
        stored = config()
        old = stored["dosing"]["channels"]["food"]
        old["state"].update(haRunStartedAt="2026-10-25T10:00:00+00:00",
                            haRunEndsAt="2026-10-25T10:00:30+00:00", haRunTargetMl=100,
                            lastSensorMl=150, haDosedTodayMl=150)
        old["reservoir"]["remainingMl"] = 250
        entry = FakeEntry(options={CONF_SETTINGS: stored})
        hass = FakeHass(entries=[entry], states={"switch.food": "on"})
        incoming = deepcopy(stored)
        incoming["dosing"]["channels"]["food"]["state"] = {}
        incoming["dosing"]["channels"]["food"]["reservoir"]["remainingMl"] = 1000
        connection = FakeConnection()
        run(handler(hass, connection, {"id": 1, key: incoming}))
        assert not connection.errors
        saved = entry.options[CONF_SETTINGS]["dosing"]["channels"]["food"]
        assert saved["state"]["haRunTargetMl"] == 100
        assert saved["state"]["lastSensorMl"] == 150
        assert saved["state"]["haRunEndsAt"] == old["state"]["haRunEndsAt"]
        assert saved["reservoir"]["remainingMl"] == 250


def test_save_refuses_collision_before_storing_it():
    stored = config()
    entry = FakeEntry(options={CONF_SETTINGS: stored})
    hass = FakeHass(entries=[entry])
    incoming = deepcopy(stored)
    incoming["automaticWaterChange"]["pumps"]["fill"]["switchEntity"] = "switch.drain"
    connection = FakeConnection()
    run(integration.websocket_save_config(hass, connection, {"id": 1, "config": incoming}))
    assert connection.errors
    assert entry.options[CONF_SETTINGS]["automaticWaterChange"]["pumps"]["fill"]["switchEntity"] == "switch.fill"
    assert not hass.services.calls


def test_existing_collision_still_allows_disabling():
    old = config()
    old["dosing"]["channels"]["food"]["enabled"] = True
    old["dosing"]["channels"]["food"]["driver"]["entities"]["powerSwitch"] = "switch.drain"
    new = deepcopy(old)
    new["dosing"]["channels"]["food"]["enabled"] = False
    assert not integration._automation_settings_error(FakeHass(), old, new)


def test_service_run_cannot_be_removed_while_master_enable_is_off():
    old = config()
    old["dosing"]["channels"]["food"]["state"]["serviceRunUntil"] = (
        datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
    new = deepcopy(old)
    new["dosing"]["channels"] = {}
    hass = FakeHass(states={"switch.food": "off"})
    assert "safety window" in integration._automation_settings_error(hass, old, new)


def test_generic_switch_cannot_enable_matched_drain():
    old = config()
    new = deepcopy(old)
    new["nps"]["feedExchange"].update(enabled=True, channelId="food")
    assert "completed-dose counter" in integration._automation_settings_error(FakeHass(), old, new)


def test_notification_await_cannot_overwrite_new_run_or_cancel_its_monitor():
    for notifications_changed in (False, True):
        stored = config()
        entry = FakeEntry(options={CONF_SETTINGS: stored})
        hass = FakeHass(entries=[entry])
        scheduled = []
        old_notify = integration._async_sync_alert_notifications
        old_schedule = integration._async_schedule_awc

        async def interleaved_notification(_hass, snapshot):
            latest = deepcopy(entry.options[CONF_SETTINGS])
            latest["automaticWaterChange"]["state"].update(status="draining", targetLitres=2)
            latest["dosing"]["channels"]["food"]["enabled"] = False
            entry.options = {**entry.options, CONF_SETTINGS: latest}
            snapshot["alertEscalation"]["outputsActive"] = True
            return notifications_changed

        async def capture_schedule(_hass, _entry, cfg=None):
            scheduled.append(cfg["automaticWaterChange"]["state"]["status"])

        integration._async_sync_alert_notifications = interleaved_notification
        integration._async_schedule_awc = capture_schedule
        try:
            returned = run(integration._async_save_config(hass, entry, stored))
        finally:
            integration._async_sync_alert_notifications = old_notify
            integration._async_schedule_awc = old_schedule
        assert entry.options[CONF_SETTINGS]["automaticWaterChange"]["state"]["status"] == "draining"
        assert returned["automaticWaterChange"]["state"]["status"] == "draining"
        assert scheduled == ["draining"]


def test_unrelated_save_cannot_restore_settled_matched_drain_debt():
    stored = config()
    stored["nps"]["feedExchange"]["state"].update(owedMl=0, totalDrainedL=1)
    entry = FakeEntry(options={CONF_SETTINGS: stored})
    stale = deepcopy(stored)
    stale["nps"]["feedExchange"]["state"].update(owedMl=1000, totalDrainedL=0)
    hass = FakeHass(entries=[entry])
    run(integration._async_save_config(hass, entry, stale))
    state = entry.options[CONF_SETTINGS]["nps"]["feedExchange"]["state"]
    assert state["owedMl"] == 0 and state["totalDrainedL"] == 1


def test_import_never_arms_old_pump_schedules_or_replays_pending_drain():
    cfg = config()
    cfg["automaticWaterChange"]["enabled"] = True
    cfg["dosing"]["channels"]["food"]["enabled"] = True
    cfg["dosing"]["channels"]["food"]["state"]["haRunStartedAt"] = "old run"
    cfg["nps"]["feedExchange"]["enabled"] = True
    cfg["nps"]["feedExchange"]["state"]["owedMl"] = 1000
    integration._sanitize_imported_config(cfg, config())
    assert cfg["automaticWaterChange"]["enabled"] is False
    assert cfg["dosing"]["enabled"] is False
    assert cfg["dosing"]["channels"]["food"]["enabled"] is False
    assert cfg["dosing"]["channels"]["food"]["state"]["haRunStartedAt"] == ""
    assert cfg["nps"]["feedExchange"]["enabled"] is False
    assert cfg["nps"]["feedExchange"]["state"] == {}


def test_direct_bookkeeping_save_preserves_live_controllers():
    stored = config()
    stored["automaticWaterChange"]["state"].update(status="fault", fault="Check levels")
    stored["dosing"]["channels"]["food"]["enabled"] = False
    entry = FakeEntry(options={CONF_SETTINGS: stored})
    stale = deepcopy(stored)
    stale["automaticWaterChange"]["state"].update(status="idle", fault="")
    stale["dosing"]["channels"]["food"]["enabled"] = True
    hass = FakeHass(entries=[entry])
    integration._persist_entry_config(hass, entry, stale)
    saved = entry.options[CONF_SETTINGS]
    assert saved["automaticWaterChange"]["state"]["status"] == "fault"
    assert saved["dosing"]["channels"]["food"]["enabled"] is False


def test_read_and_validation_notifications_cannot_restore_old_controller_or_stock():
    for handler in (integration.websocket_get_config, integration.websocket_validate_config,
                    integration.websocket_validate_mappings_alias):
        stored = config()
        entry = FakeEntry(options={CONF_SETTINGS: stored})
        hass = FakeHass(entries=[entry])
        old_notify = integration._async_sync_alert_notifications

        async def interleaved_notification(_hass, snapshot):
            latest = deepcopy(entry.options[CONF_SETTINGS])
            latest["automaticWaterChange"]["state"].update(status="draining", targetLitres=2)
            latest["automaticWaterChange"]["reservoirs"]["fresh"]["remainingMl"] = 3
            latest["dosing"]["channels"]["food"]["reservoir"]["remainingMl"] = 20
            entry.options = {**entry.options, CONF_SETTINGS: latest}
            snapshot["alertEscalation"]["outputsActive"] = True
            return True

        integration._async_sync_alert_notifications = interleaved_notification
        try:
            run(handler(hass, FakeConnection(), {"id": 1}))
        finally:
            integration._async_sync_alert_notifications = old_notify
        saved = entry.options[CONF_SETTINGS]
        assert saved["automaticWaterChange"]["state"]["status"] == "draining"
        assert saved["automaticWaterChange"]["reservoirs"]["fresh"]["remainingMl"] == 3
        assert saved["dosing"]["channels"]["food"]["reservoir"]["remainingMl"] == 20
        assert saved["alertEscalation"]["outputsActive"] is True


def test_ato_scheduler_does_not_block_pump_save_on_network_io():
    async def scenario():
        cfg = config()
        cfg["mode"]["active"] = "running"
        cfg["interlocks"]["atoDutyCycleEnabled"] = True
        cfg["equipment"]["ato"] = {"type": "ato", "armed": True, "switch_entity_id": "switch.ato"}
        entry = FakeEntry(options={CONF_SETTINGS: cfg})
        hass = FakeHass(entries=[entry])
        tasks = []
        entered = asyncio.Event()
        release = asyncio.Event()
        old_setter = integration._async_set_ato_duty_cycle_state

        async def slow_ato(*args):
            entered.set()
            await release.wait()

        def create_task(coro, *args, **kwargs):
            task = asyncio.create_task(coro)
            tasks.append(task)
            return task

        hass.async_create_task = create_task
        integration._async_set_ato_duty_cycle_state = slow_ato
        try:
            async with integration._awc_lock(hass):
                await asyncio.wait_for(integration._async_schedule_ato_duty_cycle(hass, entry, cfg), 0.2)
                await asyncio.wait_for(entered.wait(), 0.2)
                await integration._async_schedule_ato_duty_cycle(hass, entry, cfg)
                assert len(tasks) == 1, "one pending duty task, no save-triggered task storm"
        finally:
            release.set()
            await asyncio.gather(*tasks)
            integration._async_set_ato_duty_cycle_state = old_setter
    run(scenario())


def test_ato_on_waits_for_awc_and_rechecks_new_hold():
    async def scenario():
        cfg = config()
        cfg["mode"]["active"] = "running"
        cfg["equipment"]["ato"] = {"type": "ato", "armed": True, "switch_entity_id": "switch.ato"}
        entry = FakeEntry(options={CONF_SETTINGS: cfg})
        hass = FakeHass(entries=[entry], states={"switch.ato": "off"})
        async with integration._awc_lock(hass):
            pending = asyncio.create_task(integration._async_set_ato_duty_cycle_state(
                hass, entry, "on", "window", "started"))
            await asyncio.sleep(0)
            assert not pending.done()
            entry.options[CONF_SETTINGS]["automaticWaterChange"]["state"]["status"] = "draining"
        await asyncio.wait_for(pending, 1)
        assert not any(c.service == "turn_on" for c in hass.services.calls)
    run(scenario())


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in globals().copy().items() if name.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"PASS {name}")
    print(f"{len(tests)} passed")
