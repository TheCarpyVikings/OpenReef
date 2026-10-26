"""Failure-injection regressions for the dosing safety audit (no hardware)."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from test_dosing_sync import integration, _entry, _hass, _channel, _saved_channel, _calls, CONF_SETTINGS
from _fake_ha import run, install_scheduler


def _fixture(**over):
    channel = _channel(chemical="food", guards={"phEntity": ""}, **over)
    channel["driver"]["entities"]["minGapNumber"] = "number.kalk_min_gap"
    entry = _entry(channels={"food": channel})
    hass = _hass(entry, {"number.kalk_min_gap": "0"})
    scheduler = install_scheduler(integration)
    return entry, hass, scheduler


class NpsSafetyAudit(unittest.TestCase):
    def test_sync_cannot_enable_until_readback_verifies(self):
        entry, hass, scheduler = _fixture()
        run(integration._async_dosing_sync_pass(hass, entry))
        self.assertEqual(hass.states.get("switch.kalk_enabled").state, "off")
        run(scheduler.fire_all())
        self.assertEqual(hass.states.get("switch.kalk_enabled").state, "on")

    def test_missing_or_offline_calibration_never_enables(self):
        for missing in (True, False):
            with self.subTest(missing=missing):
                entry, hass, _ = _fixture()
                if missing:
                    entry.options[CONF_SETTINGS]["dosing"]["channels"]["food"]["driver"]["entities"]["stepsPerMlNumber"] = ""
                else:
                    hass.states.set("number.kalk_steps_per_ml", "unavailable")
                hass.states.set("switch.kalk_enabled", "on")
                run(integration._async_dosing_sync_pass(hass, entry))
                self.assertEqual(hass.states.get("switch.kalk_enabled").state, "off")
                self.assertFalse(any(c.data.get(integration.ATTR_ENTITY_ID) == "switch.kalk_enabled"
                                     for c in _calls(hass, "switch", "turn_on")))

    def test_rejected_numeric_write_stays_off(self):
        entry, hass, scheduler = _fixture()
        hass.services._states = None
        run(integration._async_dosing_sync_pass(hass, entry))
        run(scheduler.fire_all())
        run(scheduler.fire_all())
        self.assertEqual(_saved_channel(entry, "food")["sync"]["state"], "failed")
        self.assertFalse(any(c.data.get(integration.ATTR_ENTITY_ID) == "switch.kalk_enabled"
                             for c in _calls(hass, "switch", "turn_on")))

    def test_master_disable_revokes_enable(self):
        entry, hass, _ = _fixture()
        entry.options[CONF_SETTINGS]["dosing"]["enabled"] = False
        hass.states.set("switch.kalk_enabled", "on")
        run(integration._async_dosing_sync_pass(hass, entry))
        self.assertEqual(hass.states.get("switch.kalk_enabled").state, "off")

    def test_manual_volume_must_exist_and_read_back(self):
        for case in ("missing", "rejected", "nan"):
            with self.subTest(case=case):
                entry, hass, _ = _fixture()
                channel = _saved_channel(entry, "food")
                if case == "missing":
                    channel["driver"]["entities"]["manualDoseMlNumber"] = ""
                elif case == "rejected":
                    hass.services._states = None
                else:
                    hass.states.set("number.kalk_manual_dose", "nan")
                    hass.services._states = None
                self.assertFalse(run(integration._async_dosing_fire_bounded_dose(hass, channel, 2)))
                self.assertFalse(_calls(hass, "button", "press"))

    def test_stale_runtime_cannot_undo_user_disable_or_rebind(self):
        entry, hass, _ = _fixture()
        stale = integration._config_from_entry(entry)
        current = entry.options[CONF_SETTINGS]["dosing"]["channels"]["food"]
        current["enabled"] = False
        current["schedule"]["mlPerDay"] = 0
        current["driver"]["entities"]["enabledSwitch"] = "switch.replacement_enabled"
        current["state"]["suspendedUntil"] = "2099-01-01T00:00:00+00:00"
        run(integration._async_dosing_save(hass, entry, stale))
        saved = _saved_channel(entry, "food")
        self.assertFalse(saved["enabled"])
        self.assertEqual(saved["schedule"]["mlPerDay"], 0)
        self.assertEqual(saved["driver"]["entities"]["enabledSwitch"], "switch.replacement_enabled")
        self.assertEqual(saved["state"]["suspendedUntil"], "2099-01-01T00:00:00+00:00")

    def test_observed_dose_and_drain_credit_survive_restart_once(self):
        entry, hass, _ = _fixture(state={"lastSensorMl": 10, "lastSensorAt": "2026-01-01T12:00:00+00:00"})
        cfg = entry.options[CONF_SETTINGS]
        cfg["nps"]["feedExchange"].update(enabled=True, channelId="food")
        cfg["nps"]["feedExchange"]["state"]["owedMl"] = 0
        hass.states.set("sensor.kalk_dosed_today", "20")
        # Reproduce the old hourly-flush gap: no transition was otherwise due.
        rt = hass.data.setdefault(integration.DOMAIN, {}).setdefault(integration.DOSING_RUNTIME, {})
        rt["lastFlushAt"] = datetime.now(timezone.utc).isoformat()
        run(integration._async_dosing_tick(hass, entry))
        self.assertEqual(entry.options[CONF_SETTINGS]["nps"]["feedExchange"]["state"]["owedMl"], 10)
        hass.data[integration.DOMAIN].pop(integration.DOSING_RUNTIME, None)
        run(integration._async_dosing_tick(hass, entry))
        self.assertEqual(entry.options[CONF_SETTINGS]["nps"]["feedExchange"]["state"]["owedMl"], 10)
        self.assertEqual(_saved_channel(entry, "food")["reservoir"]["remainingMl"], 4990)

    def test_midnight_reset_never_invents_matched_drain(self):
        entry, hass, _ = _fixture(state={"lastSensorMl": 10, "lastSensorAt": "2026-01-01T23:59:00+00:00"})
        cfg = entry.options[CONF_SETTINGS]
        cfg["nps"]["feedExchange"].update(enabled=True, channelId="food")
        hass.states.set("sensor.kalk_dosed_today", "1")
        old = integration.dt_util
        class Clock:
            now = staticmethod(lambda: datetime(2026, 1, 2, 0, 1))
            utcnow = staticmethod(lambda: datetime(2026, 1, 2, 0, 1, tzinfo=timezone.utc))
        integration.dt_util = Clock()
        try:
            run(integration._async_dosing_tick(hass, entry))
        finally:
            integration.dt_util = old
        self.assertEqual(entry.options[CONF_SETTINGS]["nps"]["feedExchange"]["state"]["owedMl"], 1)
        self.assertEqual(_saved_channel(entry, "food")["dailyLog"][0]["deliveredMl"], 10)

    def test_standing_phyto_expiry_is_fail_closed(self):
        entry, _, _ = _fixture(reservoir={"shelfLifeDays": 1, "mixedAt": "2020-01-01T00:00:00+00:00"},
                              schedule={"standing": {"enabled": True}})
        channel = _saved_channel(entry, "food")
        self.assertFalse(integration._dosing_desired_switches(channel, config=entry.options[CONF_SETTINGS])["enabledSwitch"])

    def test_panic_hold_uses_explicit_guard_clock(self):
        entry, _, _ = _fixture(state={"suspendedUntil": "2099-01-01T00:00:00+00:00"})
        reasons = integration.dosing_engine.guard_reasons(_saved_channel(entry, "food"), {}, 720,
                                                         now=datetime.now(timezone.utc))
        self.assertTrue(any(r["code"] == "suspended" for r in reasons))

    def test_unacknowledged_sync_does_not_spin_on_its_own_saves(self):
        entry, hass, _ = _fixture()
        # Accept switches, reject numeric writes as a real device can.
        original = hass.services.async_call
        async def reject_numbers(domain, service, data=None, **kwargs):
            if domain == "number":
                states = hass.services._states
                hass.services._states = None
                try:
                    return await original(domain, service, data, **kwargs)
                finally:
                    hass.services._states = states
            return await original(domain, service, data, **kwargs)
        hass.services.async_call = reject_numbers
        run(integration._async_dosing_sync_pass(hass, entry))
        writes = len(_calls(hass, "number", "set_value"))
        run(integration._async_dosing_sync_pass(hass, entry))
        self.assertEqual(len(_calls(hass, "number", "set_value")), writes)

    def test_delayed_manual_number_feedback_is_accepted(self):
        import asyncio
        entry, hass, _ = _fixture()
        original = hass.services.async_call
        async def delayed(domain, service, data=None, **kwargs):
            if domain == "number":
                async def publish():
                    await asyncio.sleep(0.02)
                    hass.states.set(data[integration.ATTR_ENTITY_ID], str(data["value"]))
                asyncio.create_task(publish())
                return
            return await original(domain, service, data, **kwargs)
        hass.services.async_call = delayed
        self.assertTrue(run(integration._async_dosing_fire_bounded_dose(
            hass, _saved_channel(entry, "food"), 2)))
        self.assertEqual(len(_calls(hass, "button", "press")), 1)

    def test_unknown_button_state_allows_its_first_press(self):
        entry, hass, _ = _fixture()
        hass.states.set("button.kalk_prime", "unknown")
        self.assertTrue(run(integration._async_dosing_press(hass, _saved_channel(entry, "food"), "primeButton")))

    def test_enabled_channel_cannot_be_deleted(self):
        from _fake_ha import FakeConnection
        entry, hass, _ = _fixture()
        conn = FakeConnection()
        run(integration.websocket_dosing_delete_channel(hass, conn, {"id": 1, "channel_id": "food"}))
        self.assertIn("automation_safety", conn.error_codes)
        self.assertIn("food", entry.options[CONF_SETTINGS]["dosing"]["channels"])

    def test_awc_suspension_requires_observed_acknowledgment(self):
        entry, hass, _ = _fixture()
        hass.services._states = None
        self.assertFalse(run(integration._async_dosing_awc_suspend(hass, entry.options[CONF_SETTINGS], True, None)))

    def test_generic_ha_pump_has_recovery_trace_before_on(self):
        from test_nps import _ha_entry, _ha_channel
        from _fake_ha import FakeHass
        entry = _ha_entry(_ha_channel())
        hass = FakeHass(states={"switch.pump": "off"}, entries=[entry])
        install_scheduler(integration)
        original = hass.services.async_call
        async def inspect(domain, service, data=None, **kwargs):
            if domain == "switch" and service == "turn_on":
                state = entry.options[CONF_SETTINGS]["dosing"]["channels"]["phyto_pump"]["state"]
                self.assertTrue(state["haRunEndsAt"])
            return await original(domain, service, data, **kwargs)
        hass.services.async_call = inspect
        cfg = integration._config_from_entry(entry)
        ch = cfg["dosing"]["channels"]["phyto_pump"]
        self.assertTrue(run(integration._async_dosing_ha_run(hass, entry, cfg, "phyto_pump", ch, 5)))

    def test_generic_ha_executor_honours_awc_and_panic(self):
        from test_nps import _ha_entry, _ha_channel
        from _fake_ha import FakeHass
        for mode in ("awc", "panic"):
            entry = _ha_entry(_ha_channel())
            cfg = integration._config_from_entry(entry)
            if mode == "awc":
                cfg["automaticWaterChange"]["state"]["status"] = "draining"
            else:
                cfg["dosing"]["channels"]["phyto_pump"]["state"]["suspendedUntil"] = "2099-01-01T00:00:00+00:00"
            entry.options[CONF_SETTINGS] = cfg
            hass = FakeHass(states={"switch.pump": "off"}, entries=[entry])
            install_scheduler(integration)
            run(integration._async_dosing_ha_executor(hass, entry, cfg,
                datetime.now(timezone.utc), datetime.now(), None))
            self.assertFalse(_calls(hass, "switch", "turn_on"), mode)


    def test_prime_trace_precedes_motor_and_blocks_remapping(self):
        from _fake_ha import FakeConnection
        entry, hass, _ = _fixture(enabled=False)
        original = hass.services.async_call
        async def inspect(domain, service, data=None, **kwargs):
            if domain == "button":
                stamp = _saved_channel(entry, "food")["state"]["serviceRunUntil"]
                self.assertGreater(datetime.fromisoformat(stamp), datetime.now(timezone.utc))
            return await original(domain, service, data, **kwargs)
        hass.services.async_call = inspect
        conn = FakeConnection()
        run(integration.websocket_dosing_prime(hass, conn, {"id": 1, "channel_id": "food"}))
        self.assertFalse(conn.errors)
        run(integration.websocket_dosing_delete_channel(hass, conn, {"id": 2, "channel_id": "food"}))
        self.assertIn("automation_safety", conn.error_codes)

    def test_generic_completed_run_settles_once_and_never_owes_drain(self):
        from test_nps import _ha_entry, _ha_channel
        from _fake_ha import FakeHass
        import asyncio
        entry = _ha_entry(_ha_channel())
        cfg = integration._config_from_entry(entry)
        cfg["nps"]["feedExchange"].update(enabled=True, channelId="phyto_pump")
        entry.options[CONF_SETTINGS] = cfg
        hass = FakeHass(states={"switch.pump": "off"}, entries=[entry])
        install_scheduler(integration)
        async def scenario():
            ch = cfg["dosing"]["channels"]["phyto_pump"]
            self.assertTrue(await integration._async_dosing_ha_run(hass, entry, cfg, "phyto_pump", ch, 5))
            await asyncio.gather(*[integration._async_dosing_ha_finish(hass, entry, cfg, "phyto_pump", ch) for _ in range(2)])
        run(scenario())
        saved = entry.options[CONF_SETTINGS]
        self.assertEqual(saved["dosing"]["channels"]["phyto_pump"]["state"]["haDosedTodayMl"], 5)
        self.assertEqual(saved["nps"]["feedExchange"]["state"]["owedMl"], 0)

    def test_generic_unconfirmed_start_does_not_claim_delivery(self):
        from test_nps import _ha_entry, _ha_channel
        from _fake_ha import FakeHass
        entry = _ha_entry(_ha_channel())
        hass = FakeHass(states={"switch.pump": "off"}, entries=[entry])
        scheduler = install_scheduler(integration)
        hass.services._states = None
        cfg = integration._config_from_entry(entry)
        ch = cfg["dosing"]["channels"]["phyto_pump"]
        self.assertFalse(run(integration._async_dosing_ha_run(hass, entry, cfg, "phyto_pump", ch, 5)))
        run(scheduler.fire_all())
        saved = entry.options[CONF_SETTINGS]["dosing"]["channels"]["phyto_pump"]
        self.assertFalse(saved["enabled"])
        self.assertEqual(saved["state"]["haDosedTodayMl"], 0)
        self.assertEqual(saved["reservoir"]["remainingMl"], 500)


    def test_unrelated_stale_save_cannot_reenable_or_replay_observed_water(self):
        entry, hass, _ = _fixture(state={"lastSensorMl": 10, "lastSensorAt": "2026-01-01T12:00:00+00:00"})
        stale = integration._config_from_entry(entry)
        current = entry.options[CONF_SETTINGS]["dosing"]["channels"]["food"]
        current["enabled"] = False
        current["schedule"]["mlPerDay"] = 0
        current["driver"]["entities"]["enabledSwitch"] = "switch.new_enable"
        current["state"]["lastSensorMl"] = 20
        current["state"]["haRunEndsAt"] = "2099-01-01T00:00:00+00:00"
        current["state"]["serviceRunUntil"] = "2099-01-01T00:00:00+00:00"
        # Represents a culture/light/report task holding a pre-disable snapshot.
        stale.setdefault("activity", []).append({"message": "Unrelated work"})
        run(integration._async_save_config(hass, entry, stale))
        saved = _saved_channel(entry, "food")
        self.assertFalse(saved["enabled"])
        self.assertEqual(saved["schedule"]["mlPerDay"], 0)
        self.assertEqual(saved["driver"]["entities"]["enabledSwitch"], "switch.new_enable")
        self.assertEqual(saved["state"]["lastSensorMl"], 20)
        self.assertEqual(saved["state"]["haRunEndsAt"], "2099-01-01T00:00:00+00:00")
        self.assertEqual(saved["state"]["serviceRunUntil"], "2099-01-01T00:00:00+00:00")

    def test_unrelated_save_keeps_channel_membership_and_stock(self):
        entry, hass, _ = _fixture()
        stale = integration._config_from_entry(entry)
        # Stock writers must own the lock and fetch current state too.
        stale["dosing"]["channels"]["food"]["reservoir"]["remainingMl"] = 123
        stale["dosing"]["channels"]["rogue"] = deepcopy(stale["dosing"]["channels"]["food"])
        run(integration._async_save_config(hass, entry, stale))
        self.assertEqual(set(entry.options[CONF_SETTINGS]["dosing"]["channels"]), {"food"})
        self.assertEqual(_saved_channel(entry, "food")["reservoir"]["remainingMl"], 5000)
        old = integration._config_from_entry(entry)
        entry.options[CONF_SETTINGS]["dosing"]["channels"].pop("food")
        run(integration._async_save_config(hass, entry, old))
        self.assertEqual(entry.options[CONF_SETTINGS]["dosing"]["channels"], {})

    def test_owned_dosing_save_can_change_controls_with_nested_lock(self):
        entry, hass, _ = _fixture()
        async def edit():
            async with integration._dosing_lock(hass):
                async with integration._dosing_lock(hass):
                    cfg = integration._config_from_entry(entry)
                    cfg["dosing"]["channels"]["food"]["enabled"] = False
                    await integration._async_save_config(hass, entry, cfg)
        run(edit())
        self.assertFalse(_saved_channel(entry, "food")["enabled"])
        self.assertFalse(integration._dosing_lock(hass).locked())


    def test_unrelated_save_cannot_remove_expiry_guard_or_overwrite_stock(self):
        entry, hass, _ = _fixture(reservoir={"shelfLifeDays": 0, "productId": ""})
        stale = integration._config_from_entry(entry)
        current = entry.options[CONF_SETTINGS]["dosing"]["channels"]["food"]["reservoir"]
        current.update(shelfLifeDays=1, refrigerated=True, productId="new_bottle", productIsBottle=True)
        stale_res = stale["dosing"]["channels"]["food"]["reservoir"]
        stale_res.update(remainingMl=400, mixedAt="2026-10-25T12:00:00+00:00")
        run(integration._async_save_config(hass, entry, stale))
        saved = _saved_channel(entry, "food")["reservoir"]
        self.assertEqual(saved["shelfLifeDays"], 1)
        self.assertTrue(saved["refrigerated"])
        self.assertEqual(saved["productId"], "new_bottle")
        self.assertTrue(saved["productIsBottle"])
        self.assertEqual(saved["remainingMl"], 5000)
        async def stock_load():
            async with integration._awc_lock(hass), integration._dosing_lock(hass):
                latest = integration._config_from_entry(entry)
                latest["dosing"]["channels"]["food"]["reservoir"].update(
                    remainingMl=400, mixedAt="2026-10-25T12:00:00+00:00")
                await integration._async_save_config(hass, entry, latest)
        run(stock_load())
        saved = _saved_channel(entry, "food")["reservoir"]
        self.assertEqual(saved["remainingMl"], 400)
        self.assertEqual(saved["shelfLifeDays"], 1)


    def test_awc_release_rechecks_newer_panic_lockout(self):
        entry, hass, _ = _fixture()
        stale = integration._config_from_entry(entry)
        entry.options[CONF_SETTINGS]["dosing"]["channels"]["food"]["state"]["suspendedUntil"] = "2099-01-01T00:00:00+00:00"
        hass.states.set("switch.kalk_ha_suspend", "on")
        self.assertTrue(run(integration._async_dosing_awc_suspend(hass, stale, False, None)))
        self.assertEqual(hass.states.get("switch.kalk_ha_suspend").state, "on")

    def test_generic_start_rechecks_awc_after_waiting_for_water_lock(self):
        from test_nps import _ha_entry, _ha_channel
        from _fake_ha import FakeHass
        entry = _ha_entry(_ha_channel())
        stale = integration._config_from_entry(entry)
        latest = integration._config_from_entry(entry)
        latest["automaticWaterChange"]["state"]["status"] = "draining"
        entry.options[CONF_SETTINGS] = latest
        hass = FakeHass(states={"switch.pump": "off"}, entries=[entry])
        install_scheduler(integration)
        self.assertFalse(run(integration._async_dosing_ha_run(hass, entry, stale,
            "phyto_pump", stale["dosing"]["channels"]["phyto_pump"], 5)))
        self.assertFalse(_calls(hass, "switch", "turn_on"))

    def test_watcher_flush_cannot_replay_newer_atomic_dose_or_run(self):
        entry, hass, _ = _fixture(state={"lastSensorMl": 10, "lastSensorAt": "2026-01-01T12:00:00+00:00"})
        baseline = integration._config_from_entry(entry)
        watcher = deepcopy(baseline)
        watcher["dosing"]["channels"]["food"]["state"]["missedMl"] = 3
        latest = entry.options[CONF_SETTINGS]["dosing"]["channels"]["food"]
        latest["state"].update(lastSensorMl=20, lastSensorAt="2026-01-01T12:01:00+00:00",
                               haRunEndsAt="2099-01-01T00:00:00+00:00")
        latest["reservoir"]["remainingMl"] = 4990
        latest["wear"].update(runSeconds=100, doseCount=2)
        latest["sync"]["state"] = "failed"
        run(integration._async_dosing_save(hass, entry, watcher, watcher_base=baseline))
        saved = _saved_channel(entry, "food")
        self.assertEqual(saved["state"]["lastSensorMl"], 20)
        self.assertEqual(saved["state"]["haRunEndsAt"], "2099-01-01T00:00:00+00:00")
        self.assertEqual(saved["reservoir"]["remainingMl"], 4990)
        self.assertEqual(saved["wear"]["doseCount"], 2)
        self.assertEqual(saved["sync"]["state"], "failed")
        self.assertEqual(saved["state"]["missedMl"], 3)

    def test_tick_cannot_release_panic_or_awc_started_during_await(self):
        for hold in ("panic", "awc"):
            with self.subTest(hold=hold):
                entry, hass, _ = _fixture(state={"lastSensorMl": 10, "lastSensorAt": "2026-01-01T12:00:00+00:00"})
                hass.states.set("sensor.kalk_dosed_today", "20")
                original = integration._async_dosing_account_observation
                async def interrupt(*args, **kwargs):
                    await original(*args, **kwargs)
                    saved = entry.options[CONF_SETTINGS]
                    if hold == "panic":
                        saved["dosing"]["channels"]["food"]["state"]["suspendedUntil"] = "2099-01-01T00:00:00+00:00"
                    else:
                        saved["automaticWaterChange"]["state"]["status"] = "fault"
                    hass.states.set("switch.kalk_ha_suspend", "on")
                integration._async_dosing_account_observation = interrupt
                try:
                    run(integration._async_dosing_tick(hass, entry))
                finally:
                    integration._async_dosing_account_observation = original
                self.assertEqual(hass.states.get("switch.kalk_ha_suspend").state, "on")

    def test_older_sample_cannot_replay_newer_baseline_as_rollover(self):
        entry, hass, _ = _fixture(state={"lastSensorMl": 20, "lastSensorAt": "2026-01-01T12:02:00+00:00"})
        cfg = integration._config_from_entry(entry)
        run(integration._async_dosing_account_observation(hass, entry, cfg, "food",
            cfg["dosing"]["channels"]["food"], 10, 10,
            datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc)))
        self.assertEqual(_saved_channel(entry, "food")["state"]["lastSensorMl"], 20)
        self.assertEqual(_saved_channel(entry, "food")["reservoir"]["remainingMl"], 5000)

    def test_generic_start_rechecks_user_edits_after_lock_wait(self):
        from test_nps import _ha_entry, _ha_channel
        from _fake_ha import FakeHass
        for change in ("disable", "schedule", "panic"):
            with self.subTest(change=change):
                entry = _ha_entry(_ha_channel())
                stale = integration._config_from_entry(entry)
                current = entry.options[CONF_SETTINGS]["dosing"]["channels"]["phyto_pump"]
                if change == "disable":
                    current["enabled"] = False
                elif change == "schedule":
                    current["schedule"]["mlPerDay"] = 0
                else:
                    current["state"]["suspendedUntil"] = "2099-01-01T00:00:00+00:00"
                hass = FakeHass(states={"switch.pump": "off"}, entries=[entry])
                install_scheduler(integration)
                self.assertFalse(run(integration._async_dosing_ha_run(hass, entry, stale,
                    "phyto_pump", stale["dosing"]["channels"]["phyto_pump"], 5)))
                self.assertFalse(_calls(hass, "switch", "turn_on"))

    def test_unloading_blocks_firmware_enable_and_manual_button(self):
        entry, hass, _ = _fixture()
        hass.data.setdefault(integration.DOMAIN, {})["unloading"] = True
        run(integration._async_dosing_sync_pass(hass, entry))
        self.assertFalse(run(integration._async_dosing_press(hass, _saved_channel(entry, "food"), "primeButton")))
        self.assertFalse(_calls(hass, "switch", "turn_on"))
        self.assertFalse(_calls(hass, "button", "press"))

    def test_panic_intent_survives_failed_hardware_stop(self):
        from _fake_ha import FakeConnection
        entry, hass, _ = _fixture()
        original = hass.services.async_call
        async def reject_switches(domain, service, data=None, **kwargs):
            if domain == "switch":
                stamp = _saved_channel(entry, "food")["state"]["suspendedUntil"]
                self.assertGreater(datetime.fromisoformat(stamp), datetime.now(timezone.utc))
                raise RuntimeError("device unreachable")
            return await original(domain, service, data, **kwargs)
        hass.services.async_call = reject_switches
        conn = FakeConnection()
        run(integration.websocket_dosing_suspend(hass, conn, {"id": 1, "channel_id": "food"}))
        self.assertIn("stop_unconfirmed", conn.error_codes)
        saved = _saved_channel(entry, "food")
        self.assertFalse(integration._dosing_desired_switches(saved, config=entry.options[CONF_SETTINGS])["enabledSwitch"])
        self.assertTrue(saved["state"]["suspendedUntil"])

    def test_generic_panic_stops_immediately_and_never_guesses_partial_volume(self):
        from test_nps import _ha_entry, _ha_channel
        from _fake_ha import FakeHass, FakeConnection
        entry = _ha_entry(_ha_channel())
        hass = FakeHass(states={"switch.pump": "off"}, entries=[entry])
        install_scheduler(integration)
        cfg = integration._config_from_entry(entry)
        channel = cfg["dosing"]["channels"]["phyto_pump"]
        run(integration._async_dosing_ha_run(hass, entry, cfg, "phyto_pump", channel, 5))
        self.assertEqual(hass.states.get("switch.pump").state, "on")
        conn = FakeConnection()
        run(integration.websocket_dosing_suspend(hass, conn, {"id": 1, "channel_id": "phyto_pump"}))
        self.assertFalse(conn.errors)
        self.assertEqual(hass.states.get("switch.pump").state, "off")
        saved = _saved_channel(entry, "phyto_pump")
        self.assertEqual(saved["state"]["haRunEndsAt"], "")
        self.assertEqual(saved["state"]["haDosedTodayMl"], 0)
        self.assertEqual(saved["reservoir"]["remainingMl"], 500)


if __name__ == "__main__":
    unittest.main()
