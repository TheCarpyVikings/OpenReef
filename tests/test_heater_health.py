"""Passive heater monitoring: simulated thermal cycles and fake-HA lifecycle."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _ha_stubs import install
install()
from _fake_ha import FakeHass, FakeEntry, FakeState, FakeConnection
from custom_components.openreef import heater_health as h, heater_monitor as m
from custom_components import openreef as integration

START = datetime(2026, 10, 1, 8, tzinfo=timezone.utc).timestamp()


def reading(at, watts=2, water=25, room=20, **kwargs):
    return {"at": at, "watts": watts, "waterC": water, "roomC": room,
            "minC": 24.5, "maxC": 27.5, "action": None, **kwargs}


def cycle(state, at, watts=202, minutes=10, room=20, mode="heater", end=25.3):
    h.observe(state, reading(at, water=25, room=room), mode)
    h.observe(state, reading(at + 60, water=25, room=room), mode)
    for minute in range(minutes):
        h.observe(state, reading(at + 120 + minute * 60, watts,
                  25 + (end - 25) * minute / minutes, room), mode)
    return h.observe(state, reading(at + 120 + minutes * 60, water=end, room=room), mode)


def learned():
    state = h.new_state(START)
    for day in range(9):
        for run in range(3):
            cycle(state, START + day * 86400 + run * 1800)
    assert h.ready(state)
    return state


class LearningTests(unittest.TestCase):
    def test_baseline_is_automatic_but_requires_independent_cycles_and_days(self):
        state = h.new_state(START)
        for run in range(20):
            cycle(state, START + run * 1800)
        self.assertFalse(h.ready(state))
        state = learned()
        result = h.summary(state, state["observedAt"])
        self.assertEqual(result["status"], "monitoring")
        self.assertEqual(result["powerPercent"], 100)

    def test_colder_room_does_not_count_as_heater_deterioration(self):
        state = learned()
        for n in range(3):
            result = cycle(state, START + 10 * 86400 + n * 2400, minutes=20, room=14)
        self.assertIsNone(result["issue"])
        self.assertEqual(result["powerPercent"], 100)

    def test_slower_heating_under_comparable_conditions_requires_three_cycles(self):
        state = learned()
        refs = deepcopy(state["reference"])
        for n in range(3):
            result = cycle(state, START + 10 * 86400 + n * 2400, minutes=20)
            if n < 2:
                self.assertIsNone(result["issue"])
        self.assertEqual(result["issue"]["code"], "response")
        self.assertEqual(state["reference"], refs)

    def test_reduced_power_is_detected_without_relearning_the_fault(self):
        state = learned()
        refs = deepcopy(state["reference"])
        for n in range(3):
            result = cycle(state, START + 10 * 86400 + n * 1800, watts=160)
        self.assertEqual(result["issue"]["code"], "power_changed")
        self.assertEqual(result["powerPercent"], 79)
        self.assertEqual(state["reference"], refs)

    def test_thermostat_change_prompts_instead_of_silently_resetting(self):
        state = learned()
        refs = deepcopy(state["reference"])
        for n in range(3):
            result = cycle(state, START + 10 * 86400 + n * 1800, end=25.9)
        self.assertEqual(result["issue"]["code"], "settings_changed")
        self.assertEqual(state["reference"], refs)

    def test_shared_plug_does_not_guess_that_largest_load_is_heating(self):
        state = h.new_state(START)
        for minute in range(12):
            result = h.observe(state, reading(START + minute * 60, 450, 25.5 - minute * .01), "shared_chiller")
        self.assertEqual(result["current"], "uncertain")
        self.assertEqual(result["issue"]["code"], "identify")
        self.assertFalse(state["reference"])
        h.identify(state, state["loads"][0]["id"], "cooling")
        result = h.observe(state, reading(START + 780, 450), "shared_chiller")
        self.assertEqual(result["current"], "cooling")

    def test_shared_heater_learns_without_waiting_for_fan_season(self):
        state = h.new_state(START)
        for watts, role in ((2, "idle"), (202, "heating")):
            h.observe(state, reading(START, watts), "shared_fan")
            load = next(x for x in state["loads"] if x["watts"] == watts)
            h.identify(state, load["id"], role)
        for day in range(9):
            for n in range(3):
                cycle(state, START + day * 86400 + n * 1800, mode="shared_fan")
        result = h.summary(state, state["observedAt"])
        self.assertTrue(result["baselineReady"])
        self.assertFalse(result["coolingObserved"])

    def test_controller_state_identifies_load_without_user_prompt(self):
        state = h.new_state(START)
        for minute in range(12):
            result = h.observe(state, reading(START + minute * 60, 202, action="heating"), "shared_fan")
        self.assertEqual(result["current"], "heating")
        self.assertEqual(state["loads"][0]["source"], "controller")
        self.assertIsNone(result["issue"])

    def test_equal_power_outputs_require_telemetry_not_an_arbitrary_label(self):
        state = h.new_state(START)
        h.observe(state, reading(START, 200, action="heating"), "shared_chiller")
        result = h.observe(state, reading(START + 60, 200, action="cooling"), "shared_chiller")
        self.assertEqual(result["current"], "cooling")
        self.assertTrue(state["loads"][0]["ambiguous"])
        result = h.observe(state, reading(START + 120, 200), "shared_chiller")
        self.assertEqual(result["current"], "uncertain")
        self.assertEqual(result["issue"]["code"], "overlap")
        with self.assertRaises(ValueError):
            h.identify(state, state["loads"][0]["id"], "heating")

    def test_no_power_with_explicit_controller_demand_is_an_issue(self):
        state = h.new_state(START)
        for minute in range(17):
            result = h.observe(state, reading(START + minute * 60, action="heating"), "shared_fan")
        self.assertEqual(result["issue"]["code"], "no_heat")

    def test_missing_readings_do_not_look_like_zero_or_bridge_a_cycle(self):
        state = h.new_state(START)
        h.observe(state, reading(START), "heater")
        h.observe(state, reading(START + 60, 202), "heater")
        for n in range(20):
            result = h.observe(state, reading(START + 120 + n * 60, watts=None, error="Power unavailable"), "heater")
        self.assertEqual(result["issue"]["code"], "readings")
        self.assertIsNone(result["powerPercent"])
        h.observe(state, reading(START + 1500, 202), "heater")
        h.observe(state, reading(START + 1560, 2, water=25.3), "heater")
        self.assertFalse(state["reference"])
        self.assertLess(sum(x["seconds"] for x in state["hours"]), 300)

    def test_no_heat_timer_does_not_count_unobserved_time(self):
        state = h.new_state(START)
        h.observe(state, reading(START, action="heating"), "heater")
        h.observe(state, reading(START + 60, error="Power unavailable"), "heater")
        result = h.observe(state, reading(START + 1800, action="heating"), "heater")
        self.assertIsNone(result["issue"])

    def test_continuous_heating_above_learned_cutoff_does_not_wait_for_cycle_end(self):
        state = learned()
        now = START + 10 * 86400
        for minute in range(8):
            result = h.observe(state, reading(now + minute * 60, 202, water=26), "heater")
        self.assertEqual(result["issue"]["code"], "overrun")
        self.assertNotEqual(result["issue"]["severity"], "critical")

    def test_critical_temperature_overrides_learning_and_missing_room(self):
        state = h.new_state(START)
        result = h.observe(state, reading(START, 202, water=29, room=None, error="Room unavailable", paused=True), "heater")
        self.assertEqual(result["status"], "critical")
        self.assertEqual(result["issue"]["code"], "temperature")

    def test_out_of_range_cycles_never_become_a_healthy_reference(self):
        state = h.new_state(START)
        for minute in range(13):
            watts = 2 if minute in (0, 12) else 202
            h.observe(state, reading(START + minute * 60, watts, 25 + minute * .025, maxC=25.1), "heater")
        self.assertFalse(state["reference"])

    def test_heater_unused_for_days_has_no_current_performance_claim(self):
        state = learned()
        now = START + 20 * 86400
        result = h.observe(state, reading(now), "heater")
        self.assertEqual(result["status"], "waiting")
        self.assertIsNone(result["powerPercent"])

    def test_identification_prompt_does_not_repeat_each_time_the_fan_starts(self):
        state = h.new_state(START)
        h.observe(state, reading(START, 202, action="heating"), "shared_fan")
        for minute in range(1, 14):
            h.observe(state, reading(START + minute * 60, 12), "shared_fan")
        result = h.observe(state, reading(START + 840, 202), "shared_fan")
        self.assertEqual(result["issue"]["code"], "identify")

    def test_maintenance_and_temperature_jumps_never_train(self):
        state = h.new_state(START)
        h.observe(state, reading(START, 202), "heater")
        result = h.observe(state, reading(START + 60, 202, water=24, paused=True), "heater")
        self.assertFalse(state["reference"])
        self.assertIsNone(state["segment"])
        state = h.new_state(START)
        h.observe(state, reading(START), "heater")
        result = h.observe(state, reading(START + 60, water=25.8), "heater")
        self.assertIn("settle", result["reason"])

    def test_energy_estimates_separate_heater_and_cooling_and_ignore_gaps(self):
        state = h.new_state(START)
        h.observe(state, reading(START, 2, action="idle"), "shared_fan")
        h.observe(state, reading(START + 60, 202, action="heating"), "shared_fan")
        for minute in range(2, 12):
            h.observe(state, reading(START + minute * 60, 202, action="heating"), "shared_fan")
        h.observe(state, reading(START + 720, 12, action="cooling"), "shared_fan")
        for minute in range(13, 23):
            result = h.observe(state, reading(START + minute * 60, 12, action="cooling"), "shared_fan")
        self.assertAlmostEqual(result["heatingWhEstimate"], 200 * 11 / 60, places=1)
        self.assertAlmostEqual(result["coolingWhEstimate"], 10 * 10 / 60, places=1)
        before = result["heatingWhEstimate"]
        result = h.observe(state, reading(START + 10 * 3600, 202), "shared_fan")
        self.assertEqual(before, result["heatingWhEstimate"])

    def test_explicit_reset_keeps_old_reference_and_cooling_identity(self):
        state = learned()
        state["loads"].append({"id": "p8", "watts": 12, "role": "cooling", "source": "confirmed", "seconds": 600, "visits": 3, "first": START})
        fresh = h.restart(state, START + 20 * 86400)
        self.assertFalse(fresh["reference"])
        self.assertEqual(fresh["previous"]["reference"], state["reference"])
        self.assertTrue(any(x["role"] == "cooling" for x in fresh["loads"]))
        self.assertFalse(any(x["role"] == "heating" for x in fresh["loads"]))


class Store:
    def __init__(self, data=None):
        self.data = deepcopy(data)
        self.saves = []
    async def async_load(self):
        return deepcopy(self.data)
    async def async_save(self, data):
        self.data = deepcopy(data)
        self.saves.append(self.data)
    def async_delay_save(self, callback, delay):
        self.data = callback()


def fixture():
    now = datetime.now(timezone.utc)
    config = integration._normalise_core_config({
        "sensors": {"temp": {"entity_id": "sensor.tank", "enabled": True},
                    "room_temp": {"entity_id": "sensor.room", "enabled": True}},
        "equipment": {"inkbird": {"label": "Inkbird", "power_entity_id": "sensor.power",
                     "heaterMonitor": {"mode": "shared_fan"}}}})
    entry = FakeEntry(options={integration.CONF_SETTINGS: config})
    hass = FakeHass(entries=[entry], states={
        "sensor.tank": FakeState("25", {"unit_of_measurement": "°C"}, now),
        "sensor.room": FakeState("20", {"unit_of_measurement": "°C"}, now),
        "sensor.power": FakeState("202", {"unit_of_measurement": "W"}, now)})
    notes = []
    async def notify(*args):
        notes.append(args)
    monitor = m.Monitor(hass, entry, Store(), lambda: entry.options[integration.CONF_SETTINGS], notify)
    monitor.states["inkbird"] = h.new_state(now.timestamp(), m.bindings(config, config["equipment"]["inkbird"]))
    return hass, entry, monitor, notes


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_units_unavailable_and_freshness_are_checked(self):
        hass, entry, monitor, _ = fixture()
        config = entry.options[integration.CONF_SETTINGS]
        item = config["equipment"]["inkbird"]
        now = datetime.now(timezone.utc)
        hass.states.set("sensor.tank", FakeState("77", {"unit_of_measurement": "°F"}, now))
        hass.states.set("sensor.power", FakeState("0.202", {"unit_of_measurement": "kW"}, now))
        result = m.sample(hass, config, item, now.timestamp())
        self.assertEqual(result["waterC"], 25)
        self.assertEqual(result["watts"], 202)
        self.assertIsNone(result["error"])
        self.assertIn("power monitor", m.sample(hass, config, item, now.timestamp() + 1800)["error"])
        hass.states.set("sensor.power", FakeState("NaN", {"unit_of_measurement": "W"}, now))
        self.assertIsNone(m.sample(hass, config, item, now.timestamp())["watts"])

    async def test_notifications_dedupe_and_survive_restart(self):
        hass, entry, monitor, notes = fixture()
        now = datetime.now(timezone.utc).timestamp()
        for minute in range(13):
            await monitor.tick(now + minute * 60)
        self.assertEqual(len(notes), 1)
        again = m.Monitor(hass, entry, monitor.store, monitor.config_getter, monitor.notify)
        await again.load()
        await again.tick(now + 13 * 60)
        self.assertEqual(len(notes), 1)
        self.assertFalse([call for call in hass.services.calls if call.domain in ("switch", "climate")])

    async def test_identification_and_acknowledgement_are_durable(self):
        hass, entry, monitor, notes = fixture()
        await monitor.tick()
        load = monitor.states["inkbird"]["loads"][0]
        await monitor.respond("inkbird", "identify", load["id"], "heating")
        self.assertEqual(monitor.store.data["inkbird"]["loads"][0]["role"], "heating")
        before = deepcopy(monitor.states["inkbird"]["reference"])
        await monitor.respond("inkbird", "acknowledge")
        self.assertEqual(monitor.states["inkbird"]["reference"], before)
        with self.assertRaises(ValueError):
            await monitor.respond("missing", "replaced")
        with self.assertRaises(ValueError):
            await monitor.respond("inkbird", "identify", "nope", "heating")

    async def test_restore_never_bridges_a_partial_cycle(self):
        hass, entry, monitor, _ = fixture()
        await monitor.tick()
        self.assertIsNotNone(monitor.states["inkbird"]["last"])
        await monitor.stop()
        restored = m.Monitor(hass, entry, monitor.store, monitor.config_getter, monitor.notify)
        await restored.load()
        self.assertIsNone(restored.states["inkbird"]["last"])
        self.assertIsNone(restored.states["inkbird"]["segment"])

    async def test_missing_readings_can_escalate_to_temperature_alert(self):
        hass, entry, monitor, notes = fixture()
        now = datetime.now(timezone.utc).timestamp()
        hass.states.set("sensor.room", FakeState("unavailable"))
        for minute in range(17):
            await monitor.tick(now + minute * 60)
        self.assertEqual(len(notes), 1)
        hass.states.set("sensor.tank", FakeState("29", {"unit_of_measurement": "°C"}, datetime.now(timezone.utc)))
        await monitor.tick(now + 17 * 60)
        self.assertEqual(len(notes), 2)
        self.assertEqual(monitor.states["inkbird"]["issue"]["severity"], "critical")

    async def test_repeated_temperature_excursions_do_not_spam_notifications(self):
        hass, entry, monitor, notes = fixture()
        now = datetime.now(timezone.utc)
        for minute, water in enumerate((29, 25, 29, 25, 29)):
            hass.states.set("sensor.tank", FakeState(str(water), {"unit_of_measurement": "°C"}, now))
            await monitor.tick(now.timestamp() + minute * 60)
        self.assertEqual(len(notes), 1)
        self.assertEqual(monitor.states["inkbird"]["issue"]["severity"], "critical")

    async def test_settings_normalise_and_do_not_arm_equipment(self):
        cfg = integration._normalise_core_config({"equipment": {"x": {
            "heaterMonitor": {"mode": "shared_fan", "climateEntity": "climate.tank"}}}})
        self.assertFalse(cfg["equipment"]["x"]["armed"])
        self.assertEqual(cfg["equipment"]["x"]["heaterMonitor"]["mode"], "shared_fan")
        self.assertEqual(integration._normalise_core_config(cfg), cfg)
        self.assertEqual(h.normalise_settings({"mode": "garbage", "climateEntity": "switch.any"}), {"mode": "off", "climateEntity": ""})

    async def test_duplicate_power_mappings_require_correction(self):
        hass, entry, monitor, _ = fixture()
        cfg = entry.options[integration.CONF_SETTINGS]
        cfg["equipment"]["second"] = deepcopy(cfg["equipment"]["inkbird"])
        result = m.sample(hass, cfg, cfg["equipment"]["inkbird"], datetime.now(timezone.utc).timestamp())
        self.assertIn("more than one", result["error"])

    async def test_awc_and_maintenance_pause_learning(self):
        hass, entry, monitor, _ = fixture()
        cfg = entry.options[integration.CONF_SETTINGS]
        cfg["automaticWaterChange"]["state"]["status"] = "draining"
        self.assertTrue(m.sample(hass, cfg, cfg["equipment"]["inkbird"], datetime.now(timezone.utc).timestamp())["paused"])

    async def test_lifecycle_resubscribes_on_binding_change_and_flushes_on_stop(self):
        hass, entry, monitor, _ = fixture()
        listeners = []
        old_event, old_time = m.async_track_state_change_event, m.async_track_time_interval
        def subscribe(*args):
            item = {"args": args, "cancelled": False}
            listeners.append(item)
            return lambda: item.update(cancelled=True)
        m.async_track_state_change_event = m.async_track_time_interval = subscribe
        try:
            await monitor.configure()
            await monitor.configure()
            self.assertEqual(len(listeners), 2)
            state = monitor.states["inkbird"]
            state["reference"] = learned()["reference"]
            entry.options[integration.CONF_SETTINGS]["equipment"]["inkbird"]["power_entity_id"] = "sensor.new_power"
            await monitor.configure()
            self.assertTrue(all(x["cancelled"] for x in listeners[:2]))
            self.assertFalse(monitor.states["inkbird"]["reference"])
            self.assertTrue(monitor.states["inkbird"]["previous"]["reference"])
            await monitor.stop()
            self.assertTrue(all(x["cancelled"] for x in listeners))
            self.assertTrue(monitor.store.saves)
        finally:
            m.async_track_state_change_event, m.async_track_time_interval = old_event, old_time

    async def test_websocket_returns_snapshot_and_rejects_invalid_action(self):
        hass, entry, monitor, _ = fixture()
        hass.data[integration.DOMAIN] = {m.KEY: monitor}
        conn = FakeConnection()
        integration.websocket_heater_health(hass, conn, {"id": 1})
        self.assertIn("inkbird", conn.results[-1].payload["equipment"])
        await integration.websocket_heater_health_respond(hass, conn,
            {"id": 2, "equipmentId": "inkbird", "action": "toggle_heater"})
        self.assertEqual(conn.errors[-1].code, "invalid_response")
        self.assertFalse([call for call in hass.services.calls if call.domain in ("switch", "climate")])


if __name__ == "__main__":
    unittest.main()
