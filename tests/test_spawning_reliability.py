"""Spawning recovery and scheduler regressions; no live HA or hardware required."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import test_spawning as f
from _fake_ha import FakeConnection, FakeIntervalScheduler

i = f.integration
NOON = datetime(2026, 6, 17, 13, tzinfo=timezone.utc)


class SpawningReliabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = NOON
        self.utc_patch = patch.object(i.dt_util, "utcnow", side_effect=lambda: self.clock)
        self.now_patch = patch.object(i.dt_util, "now", side_effect=lambda: self.clock)
        self.utc_patch.start()
        self.now_patch.start()
        self.addCleanup(self.utc_patch.stop)
        self.addCleanup(self.now_patch.stop)

    async def tick(self, hass, entry, minutes=0):
        self.clock = NOON + timedelta(minutes=minutes)
        await i._async_spawning_tick(hass, entry, self.clock)

    def runtime(self, hass):
        return hass.data[i.DOMAIN][i.SPAWNING_RUNTIME]

    def status(self, hass):
        conn = FakeConnection()
        i.websocket_spawning_execution_status(hass, conn, {"id": 1})
        return conn.results[0].payload["runtime"]

    async def test_unfulfilled_commands_retry_and_alert_for_both_light_directions(self):
        for at, initial, service in ((NOON, "off", "turn_on"), (NOON.replace(hour=23), "on", "turn_off")):
            entry = f._exec_entry()
            hass = f._exec_hass(entry, {"switch.tank_light": initial})
            hass.services.responses[("switch", service)] = None
            for minute in range(3):
                self.clock = at + timedelta(minutes=minute)
                await i._async_spawning_tick(hass, entry, self.clock)
            self.assertEqual(len(f._switch_calls(hass, service)), 3)
            self.assertFalse(self.runtime(hass)["overrides"])
            self.assertEqual(self.status(hass)["health"], "fault")
            notes = [c for c in hass.services.calls if c.domain == "persistent_notification"]
            self.assertEqual(len(notes), 1)
            self.assertIn("unconfirmed", notes[0].data["title"])

    async def test_delayed_state_confirmation_clears_fault_without_manual_hold(self):
        entry = f._exec_entry()
        hass = f._exec_hass(entry)
        hass.services.responses[("switch", "turn_on")] = None
        await self.tick(hass, entry)
        self.assertIn("light", self.runtime(hass)["mismatches"])
        hass.states.set("switch.tank_light", "on")
        await self.tick(hass, entry, 1)
        self.assertEqual(len(f._switch_calls(hass, "turn_on")), 1)
        self.assertEqual(self.status(hass)["health"], "ok")
        self.assertFalse(self.runtime(hass)["mismatches"])

    async def test_device_reboot_and_unattributed_changes_recover(self):
        for expose_unavailable in (True, False):
            entry = f._exec_entry()
            hass = f._exec_hass(entry)
            await self.tick(hass, entry)
            if expose_unavailable:
                hass.states.set("switch.tank_light", "unavailable")
                await self.tick(hass, entry, 1)
            hass.states.set("switch.tank_light", "off")
            await self.tick(hass, entry, 2)
            self.assertEqual(hass.states.get("switch.tank_light").state, "on")
            self.assertFalse(self.runtime(hass)["overrides"])

    async def test_direct_ha_manual_override_and_resume_change_the_actual_plug(self):
        entry = f._exec_entry()
        hass = f._exec_hass(entry)
        await self.tick(hass, entry)
        hass.states.set("switch.tank_light", "off")
        hass.states.get("switch.tank_light").context = SimpleNamespace(user_id="tester", parent_id=None)
        await self.tick(hass, entry, 1)
        self.assertEqual(hass.states.get("switch.tank_light").state, "off")
        self.assertEqual(self.status(hass)["health"], "override")
        i.websocket_spawning_execution_resume(hass, FakeConnection(), {"id": 1})
        await self.tick(hass, entry, 2)
        self.assertEqual(hass.states.get("switch.tank_light").state, "on")
        self.assertFalse(self.runtime(hass)["overrides"])

    async def test_unrelated_saves_preserve_deadline_and_allow_ticks(self):
        scheduler = FakeIntervalScheduler()
        entry = f._exec_entry()
        hass = f._exec_hass(entry)
        with patch.object(i, "async_track_time_interval", scheduler.track):
            await i._async_save_config(hass, entry, i._config_from_entry(entry))
            timer = next(r for r in scheduler.pending() if "spawning" in r["callback"].__qualname__)
            for seconds in (30, 60, 90, 120):
                self.clock = NOON + timedelta(seconds=seconds)
                await i._async_save_config(hass, entry, i._config_from_entry(entry))
                self.assertFalse(timer["cancelled"])
                if seconds % 60 == 0:
                    await timer["callback"](self.clock)
            self.assertEqual(hass.tasks.count("openreef_spawning_reconcile"), 1)
        self.assertEqual(hass.states.get("switch.tank_light").state, "on")
        self.assertEqual(self.runtime(hass)["lastCompletedAt"], self.clock.isoformat())

    async def test_startup_waits_for_ha_started_and_unregisters_listener(self):
        entry = f._exec_entry()
        hass = f._exec_hass(entry)
        hass.is_running = False
        await i._async_schedule_spawning_tick(hass, entry)
        await i._async_schedule_spawning_tick(hass, entry)
        self.assertEqual(len(hass.bus.listeners), 1)
        self.assertNotIn("openreef_spawning_reconcile", hass.tasks)
        hass.bus.listeners[0].callback(None)
        self.assertIn("openreef_spawning_reconcile", hass.tasks)
        # Reload while HA is still starting must not leave another armed callback.
        i._clear_spawning_tick(hass)
        await i._async_schedule_spawning_tick(hass, entry)
        i._clear_spawning_tick(hass)
        self.assertTrue(hass.bus.listeners[-1].cancelled)

    async def test_queued_startup_work_cannot_actuate_after_unload(self):
        entry = f._exec_entry()
        hass = f._exec_hass(entry)
        queued = []
        hass.async_create_task = lambda coro, name=None: queued.append(coro)
        await i._async_schedule_spawning_tick(hass, entry)
        i._clear_spawning_tick(hass)
        hass.data[i.DOMAIN].pop(i.SPAWNING_RUNTIME, None)
        for coro in queued:
            await coro
        self.assertFalse(hass.services.calls)

    async def test_activity_save_preserves_unrelated_concurrent_settings(self):
        entry = f._exec_entry()
        hass = f._exec_hass(entry)
        original = hass.services.async_call

        async def concurrent_edit(domain, service, data=None, **kwargs):
            if domain == "switch":
                cfg = i._config_from_entry(entry)
                cfg["alerts"]["modeNotifyTarget"] = "mobile_app_beta_tester"
                i._persist_entry_config(hass, entry, cfg)
            return await original(domain, service, data, **kwargs)

        hass.services.async_call = concurrent_edit
        await self.tick(hass, entry)
        saved = i._config_from_entry(entry)
        self.assertEqual(saved["alerts"]["modeNotifyTarget"], "mobile_app_beta_tester")
        self.assertTrue(any("daylight plug" in row["message"] for row in saved["activity"]))

    async def test_light_error_uses_configured_phone_notification_route(self):
        entry = f._exec_entry(extra={"alerts": {"modeNotifyTarget": "mobile_app_beta_tester"}})
        hass = f._exec_hass(entry)
        hass.services.fail_on.add(("switch", "turn_on"))
        with self.assertLogs(i._LOGGER, level="WARNING"):
            await self.tick(hass, entry)
        pushes = [call for call in hass.services.calls if call.domain == "notify"]
        self.assertEqual(len(pushes), 1)
        self.assertEqual(pushes[0].service, "mobile_app_beta_tester")
        self.assertIn("unconfirmed", pushes[0].data["title"])

    async def test_program_edit_requests_sync_without_postponing_interval(self):
        scheduler = FakeIntervalScheduler()
        entry = f._exec_entry()
        hass = f._exec_hass(entry)
        with patch.object(i, "async_track_time_interval", scheduler.track):
            await i._async_schedule_spawning_tick(hass, entry)
            timer = scheduler.pending()[0]
            cfg = i._config_from_entry(entry)
            cfg["spawningProgram"]["offsetMonths"] = 6
            await i._async_save_config(hass, entry, cfg)
            self.assertFalse(timer["cancelled"])
            self.assertEqual(hass.tasks.count("openreef_spawning_reconcile"), 2)

    async def test_pending_tick_cannot_undo_disarm_or_command_the_next_channel(self):
        entry = f._exec_entry(moonEntity="switch.moon")
        hass = f._exec_hass(entry, {"switch.moon": "on"})
        entered, release = asyncio.Event(), asyncio.Event()
        original = hass.services.async_call

        async def delayed(domain, service, data=None, **kwargs):
            if data and "switch.tank_light" in data.values():
                entered.set()
                await release.wait()
            return await original(domain, service, data, **kwargs)

        hass.services.async_call = delayed
        task = asyncio.create_task(self.tick(hass, entry))
        await entered.wait()
        cfg = i._config_from_entry(entry)
        cfg["spawningProgram"]["execution"]["armed"] = False
        cfg["spawningProgram"]["offsetMonths"] = 6
        await i._async_save_config(hass, entry, cfg)
        release.set()
        await task
        saved = i._config_from_entry(entry)["spawningProgram"]
        self.assertFalse(saved["execution"]["armed"])
        self.assertEqual(saved["offsetMonths"], 6)
        self.assertFalse(f._switch_calls(hass, "turn_off", "switch.moon"))
        self.assertEqual(self.status(hass)["health"], "disarmed")

    async def test_slow_tick_does_not_overlap_and_timeout_is_alerted(self):
        entry = f._exec_entry()
        hass = f._exec_hass(entry)
        entered = asyncio.Event()
        calls = []
        original = hass.services.async_call

        async def blocked(domain, service, data=None, **kwargs):
            if domain == "switch":
                calls.append(service)
                entered.set()
                await asyncio.Event().wait()
            return await original(domain, service, data, **kwargs)

        hass.services.async_call = blocked
        with patch.object(i, "SPAWNING_COMMAND_TIMEOUT_SECONDS", 0.02), self.assertLogs(i._LOGGER, level="WARNING"):
            task = asyncio.create_task(self.tick(hass, entry))
            await entered.wait()
            await self.tick(hass, entry)
            await task
        self.assertEqual(calls, ["turn_on"])
        self.assertEqual(self.status(hass)["health"], "fault")
        self.assertIn("light", self.runtime(hass)["issues"])
        self.assertFalse(self.runtime(hass)["lock"].locked())
        hass.services.async_call = original
        await self.tick(hass, entry, 1)
        self.assertEqual(self.status(hass)["health"], "ok")

    async def test_health_cannot_claim_ok_before_first_tick_or_after_missed_heartbeat(self):
        entry = f._exec_entry()
        hass = f._exec_hass(entry, {"switch.tank_light": "on"})
        self.assertEqual(self.status(hass)["health"], "starting")
        await self.tick(hass, entry)
        self.assertEqual(self.status(hass)["health"], "ok")
        self.clock += timedelta(minutes=4)
        self.assertEqual(self.status(hass)["health"], "stalled")

    async def test_changed_binding_does_not_inherit_an_override(self):
        entry = f._exec_entry()
        hass = f._exec_hass(entry, {"switch.replacement": "off"})
        await self.tick(hass, entry)
        self.runtime(hass)["overrides"]["light"] = {"since": self.clock.isoformat(), "desiredAtOverride": True}
        entry.options[f.CONF_SETTINGS]["spawningProgram"]["execution"]["lightEntity"] = "switch.replacement"
        await self.tick(hass, entry, 1)
        self.assertEqual(hass.states.get("switch.replacement").state, "on")
        self.assertFalse(self.runtime(hass)["overrides"])

    async def test_conflicting_outputs_are_rejected_on_save_and_block_old_configs(self):
        entry = f._exec_entry(moonEntity="switch.tank_light")
        hass = f._exec_hass(entry)
        conn = FakeConnection()
        await i.websocket_save_config(hass, conn, {"id": 1, "config": i._config_from_entry(entry)})
        self.assertEqual(conn.error_codes, ["spawning_output_conflict"])
        await self.tick(hass, entry)
        self.assertFalse(f._switch_calls(hass, "turn_on"))
        self.assertIn("program", self.runtime(hass)["issues"])

    async def test_heartbeat_warning_is_sent_while_an_old_tick_is_busy(self):
        entry = f._exec_entry()
        hass = f._exec_hass(entry)
        scheduler = FakeIntervalScheduler()
        with patch.object(i, "async_track_time_interval", scheduler.track):
            await i._async_schedule_spawning_tick(hass, entry)
        await self.tick(hass, entry)
        lock = self.runtime(hass)["lock"]
        async with lock:
            self.clock += timedelta(minutes=4)
            await scheduler.pending()[0]["callback"](self.clock)
        notes = [c for c in hass.services.calls if c.domain == "persistent_notification"]
        self.assertTrue(any("checks have stopped" in c.data["title"] for c in notes))
        self.assertEqual(hass.states.get(i.SPAWNING_STATUS_ENTITY).state, "stalled")


class SpawningCalendarTests(unittest.TestCase):
    def test_final_evening_and_following_early_hours_are_kept_until_sunrise(self):
        cfg = f._sp_cfg()
        pred = f.spawning.predict_spawn_window(f.REEF_PRESETS["gbr_central"], 2026, 0)
        evening = datetime.fromisoformat(pred["windowEnd"]).replace(hour=23, tzinfo=timezone.utc)
        self.assertTrue(f.spawning.execution_desired_state(cfg, evening)["inSpawnWindow"])
        morning = evening.replace(hour=1) + timedelta(days=1)
        state = f.spawning.execution_desired_state(cfg, morning)
        self.assertTrue(state["inSpawnWindow"])
        sunrise = morning.replace(hour=0) + timedelta(minutes=state["sunriseMinute"])
        self.assertTrue(f.spawning.execution_desired_state(cfg, sunrise - timedelta(minutes=1))["inSpawnWindow"])
        self.assertFalse(f.spawning.execution_desired_state(cfg, sunrise)["inSpawnWindow"])

    def test_previous_december_window_survives_new_year(self):
        cfg = {**f._sp_cfg(), "offsetMonths": 1}
        when = datetime(2027, 1, 6, 1, tzinfo=timezone.utc)
        state = f.spawning.execution_desired_state(cfg, when)
        self.assertEqual(state["spawnWindow"], {"start": "2027-01-05", "end": "2027-01-08"})
        self.assertTrue(state["inSpawnWindow"])

    def test_local_full_moon_date_and_window_match_across_timezones(self):
        for zone in ("Pacific/Kiritimati", "Pacific/Honolulu", "Europe/London"):
            tz = ZoneInfo(zone)
            pred = f.spawning.predict_spawn_window(f.REEF_PRESETS["gbr_central"], 2026, 0,
                                                 datetime(2026, 9, 1, tzinfo=tz))
            local_full = datetime.fromisoformat(pred["fullMoonUtc"]).astimezone(tz).date()
            self.assertEqual(pred["fullMoonLocalDate"], local_full.isoformat())
            self.assertEqual(pred["windowStart"], (local_full + timedelta(days=12)).isoformat())

    def test_shifted_solar_noon_uses_the_actual_final_nights_sunrise(self):
        cfg = {**f._sp_cfg(), "solarNoonHour": 0}
        when = datetime(2026, 12, 9, 12, tzinfo=timezone.utc)
        state = f.spawning.execution_desired_state(cfg, when)
        self.assertTrue(state["inSpawnWindow"])
        sunrise = when.replace(hour=0) + timedelta(minutes=state["sunriseMinute"])
        self.assertFalse(f.spawning.execution_desired_state(cfg, sunrise)["inSpawnWindow"])

    def test_apex_templates_use_signed_rt_offsets_and_keep_hysteresis(self):
        for unit, tol in (("C", "0.2"), ("F", "0.4")):
            snippets = f.spawning.generate_program("gbr_central", 2026, temp_unit=unit)["codeSnippets"]
            for key in ("temperature_heater", "temperature_chiller"):
                code = snippets[key]["code"]
                self.assertIn("Fallback OFF", code)
                self.assertNotIn("Set OFF", code)
                self.assertIn("RT+-" + tol, code)
                self.assertIn("RT+" + tol, code)

    def test_export_local_dates_and_double_moon_warning(self):
        tz = ZoneInfo("Pacific/Kiritimati")
        today = datetime(2027, 1, 1, tzinfo=tz)
        prog = f.spawning.generate_program("gbr_central", 2027, today=today)
        expected = f.spawning.lunar_events(today.astimezone(timezone.utc),
                                          datetime(2028, 1, 1, tzinfo=tz).astimezone(timezone.utc))["new_moons"]
        self.assertEqual(prog["newMoonDates"], [d.astimezone(tz).date().isoformat() for d in expected])
        self.assertEqual(prog["params"]["timeZone"], "Pacific/Kiritimati")
        self.assertTrue(prog["lunarWarnings"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
