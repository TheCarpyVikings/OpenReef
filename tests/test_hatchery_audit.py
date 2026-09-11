"""Hatchery audit regressions. Run: python3 tests/test_hatchery_audit.py."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

import test_nps as fixtures
from _fake_ha import FakeConnection, FakeHass, FakeState, run

integration, nps = fixtures.integration, fixtures.nps
SETTINGS = fixtures.CONF_SETTINGS
NOW = fixtures.NOW


def stamp(hours_ago, now=NOW):
    return (now - timedelta(hours=hours_ago)).isoformat()


def config_with_load(age=2, ml=300, now=NOW, **extra):
    entry = fixtures._v2_entry(reservoir={
        "volumeMl": 750, "remainingMl": ml, "mixedAt": stamp(age, now), **extra})
    config = entry.options[SETTINGS]
    integration._nps_hatchery_v2(config)
    return config


class HatcheryAudit(unittest.TestCase):
    def test_cold_expiry_is_fixed_and_expired_batches_stay_expired(self):
        loaded = stamp(60)
        for elapsed in (48, 48.001, 60, 61.2345, 100):
            now = datetime.fromisoformat(loaded) + timedelta(hours=elapsed)
            self.assertAlmostEqual(nps.brine_window_hours(loaded, now, 24, 48, loaded), 48)
            self.assertTrue(integration._nps_batch_is_stale(
                loaded, {"refrigeratedAt": loaded}, now))
        self.assertEqual(nps.brine_window_hours(stamp(30), NOW, 24, 48, NOW.isoformat()), 24)

    def test_cold_fraction_matches_independent_budget_at_different_entry_times(self):
        for warm in (0, 5, 12, 23, 24, 30):
            loaded = stamp(80)
            cold = (datetime.fromisoformat(loaded) + timedelta(hours=warm)).isoformat()
            expected = warm + (1 - warm / 24) * 48 if warm < 24 else 24
            self.assertAlmostEqual(nps.brine_window_hours(loaded, NOW, 24, 48, cold), expected)

    def test_top_up_keeps_existing_age_and_cold_credit(self):
        config = config_with_load(age=23, fridgeSavedH=3)
        hatchery = config["nps"]["hatchery"]
        loaded = hatchery["reservoir"]["mixedAt"]
        self.assertIsNone(integration._nps_container_load(config, hatchery, NOW, enriched=False))
        self.assertEqual(hatchery["reservoir"]["mixedAt"], loaded)
        self.assertEqual(hatchery["reservoir"]["fridgeSavedH"], 3)
        self.assertEqual(hatchery["reservoir"]["remainingMl"], 750)
        self.assertEqual(integration._nps_plain_shelf_hours(config, NOW), 24)

    def test_enrichment_cannot_finish_without_food_or_before_duration(self):
        config = config_with_load()
        hatchery = config["nps"]["hatchery"]
        hatchery["enrichment"]["state"].update({
            "startedAt": stamp(1), "batchLoadedAt": stamp(2), "enrichHours": 12})
        self.assertEqual(integration._nps_enrich_loaded_apply(config, NOW)[0], "no_first_dose")
        config["nps"]["hatchery"]["enrichment"]["state"]["firstDoseAt"] = stamp(1)
        self.assertEqual(integration._nps_enrich_loaded_apply(config, NOW)[0], "soak_incomplete")
        self.assertFalse(config["nps"]["hatchery"]["reservoir"]["lastLoadEnriched"])

    def test_late_soak_acknowledgement_uses_scheduled_end(self):
        config = config_with_load(age=30)
        config["nps"]["hatchery"]["enrichment"]["state"].update({
            "startedAt": stamp(28), "batchLoadedAt": stamp(30),
            "firstDoseAt": stamp(28), "enrichHours": 12})
        self.assertIsNone(integration._nps_enrich_loaded_apply(config, NOW))
        res = config["nps"]["hatchery"]["reservoir"]
        self.assertEqual(res["enrichedAt"], stamp(16))
        self.assertTrue(integration._nps_batch_is_stale(res["mixedAt"], res, NOW))

    def test_soaking_batch_is_joined_not_replaced_and_cannot_complete_after_emptying(self):
        # 0.7.169: a harvest JOINS a running soak while enough of it remains —
        # the older portion keeps its load stamp — but an enriched load never
        # lands on a soak, under the floor the harvest waits, and once the
        # container is emptied the soak has no batch: the load says cancel,
        # Soak done says the batch changed.
        config = config_with_load()
        hatchery = config["nps"]["hatchery"]
        hatchery["enrichment"]["state"].update({
            "startedAt": stamp(1), "firstDoseAt": stamp(1), "batchLoadedAt": stamp(2)})
        loaded = hatchery["reservoir"]["mixedAt"]
        self.assertIsNone(integration._nps_container_load(config, hatchery, NOW, enriched=False))
        self.assertEqual(hatchery["reservoir"]["remainingMl"], 750)
        self.assertEqual(hatchery["reservoir"]["mixedAt"], loaded)
        self.assertEqual(integration._nps_container_load(config, hatchery, NOW, enriched=True)[0], "soaking")
        hatchery["enrichment"]["state"]["firstDoseAt"] = stamp(10)
        code, message = integration._nps_container_load(config, hatchery, NOW, enriched=False)
        self.assertEqual(code, "soaking")
        self.assertIn("~2 h left", message)
        hatchery["reservoir"]["remainingMl"] = 0
        code, message = integration._nps_container_load(config, hatchery, NOW, enriched=False)
        self.assertEqual(code, "soaking")
        self.assertIn("cancel the soak", message)
        self.assertEqual(integration._nps_enrich_loaded_apply(config, NOW)[0], "batch_changed")

    def test_planner_only_counts_volume_that_can_be_used_before_each_expiry(self):
        config = config_with_load(age=23, ml=1000, volumeMl=1500)
        hatchery = config["nps"]["hatchery"]
        hatchery["handFeed"] = {"defaultDoseMl": 100, "feedsPerDay": 24}
        hatchery["fridgeBottle"].update({
            "remainingMl": 100, "mixedAt": stamp(1), "refrigeratedAt": stamp(1)})
        loaded, shelf, usable, rate = integration._nps_brine_supply_for_planning(config, NOW)
        self.assertAlmostEqual(usable, 200)  # 100 ml before warm expiry, then 100 ml cold
        suggestion = nps.next_hatch_suggestion(NOW, 24, loaded, shelf, usable, rate, None)
        self.assertEqual(suggestion["readyBy"], (NOW + timedelta(hours=2)).isoformat())
        hatchery["fridgeBottle"]["mixedAt"] = stamp(60)
        hatchery["fridgeBottle"]["refrigeratedAt"] = stamp(60)
        self.assertEqual(integration._nps_brine_supply_for_planning(config, NOW)[2], 100)

    def test_future_load_volume_and_earlier_gap_are_reported(self):
        result = nps.next_hatch_suggestion(
            NOW, 24, NOW.isoformat(), 24, 100, 2400,
            [{"startedAt": stamp(20), "hatchHours": 24}],
            chain_shelf_hours=24, load_volume_ml=200)
        self.assertEqual(result["supplyGapHours"], 4)  # stock ends at +1, load arrives +5
        self.assertEqual(result["chainShelfHours"], 2)
        self.assertEqual(result["readyBy"], (NOW + timedelta(hours=7)).isoformat())
        self.assertEqual(result["lateHours"], 18)

    def test_fastest_completion_wins_even_if_that_cone_frees_later(self):
        now = datetime.now(timezone.utc)
        entry = fixtures._v2_entry(vessels={
            "v1": {"name": "Standard", "hatchHours": 36, "state": {
                "hatchStartedAt": stamp(25.7, now), "hatchHours": 36}},
            "v2": {"name": "Premium", "hatchHours": 24, "state": {
                "hatchStartedAt": stamp(10.3, now), "hatchHours": 24}}})
        conn = FakeConnection()
        run(integration.websocket_nps_summary(FakeHass(entries=[entry]), conn, {"id": 1}))
        hatchery = conn.results[-1].payload["hatchery"]
        self.assertEqual(hatchery["nextStartVessel"], "v2")
        self.assertEqual(hatchery["nextHatch"]["hatchHours"], 24)
        self.assertEqual(hatchery["nextHatch"]["lateHours"], 0)
        self.assertEqual(hatchery["nextHatch"]["hoursUntil"], 13.7)

    def test_temperature_units_and_cool_room_preset(self):
        entry = fixtures._v2_entry()
        entry.options[SETTINGS]["nps"]["hatchery"]["tempEntity"] = "sensor.water"
        hass = FakeHass(entries=[entry], states={"sensor.water": FakeState("77", {"unit_of_measurement": "°F"})})
        conn = FakeConnection()
        run(integration.websocket_nps_summary(hass, conn, {"id": 1}))
        self.assertEqual(conn.results[-1].payload["hatchery"]["temp"]["tempC"], 25)
        entry.options[SETTINGS]["nps"]["hatchery"]["eggType"] = "cool_room"
        run(integration.websocket_nps_summary(hass, conn, {"id": 2}))
        self.assertFalse(conn.results[-1].payload["hatchery"]["temp"]["available"])
        for temp in (None, float("nan"), float("inf"), -1, 40):
            self.assertFalse(nps.expected_hatch_hours(24, temp)["available"])
        self.assertTrue(nps.expected_hatch_hours(24, 35)["warm"])

    def test_learning_is_scoped_to_each_vessel(self):
        history = [{"vesselId": "v2", "eggType": "standard", "actualHours": 45},
                   {"vesselId": "v1", "eggType": "standard", "actualHours": 24},
                   {"vesselId": "v1", "eggType": "standard", "actualHours": 26}]
        self.assertEqual(nps.learned_hatch_hours(history, "standard", "v1")["hours"], 25)
        self.assertFalse(nps.learned_hatch_hours(history, "standard", "v2")["available"])

    def test_hand_feeds_cannot_log_more_than_the_stock(self):
        now = datetime.now(timezone.utc)
        for handler, extra in ((integration.websocket_nps_hand_feed, {}),
                               (integration.websocket_nps_fridge_bottle, {"action": "feed"})):
            entry = fixtures._v2_entry(reservoir={"volumeMl": 500, "remainingMl": 10, "mixedAt": stamp(1, now)})
            entry.options[SETTINGS]["nps"]["hatchery"]["fridgeBottle"] = {
                "remainingMl": 10, "mixedAt": stamp(1, now), "refrigeratedAt": stamp(1, now)}
            conn, hass = FakeConnection(), FakeHass(entries=[entry])
            run(handler(hass, conn, {"id": 1, "ml": 250, **extra}))
            self.assertEqual(entry.options[SETTINGS]["nps"]["hatchery"]["handFeeds"][0]["ml"], 10)
            run(handler(hass, conn, {"id": 2, "ml": 250, **extra}))
            self.assertTrue(conn.errors)

    def test_fridge_merge_uses_remaining_life_and_return_never_loses_overflow(self):
        now = datetime.now(timezone.utc)
        entry = fixtures._v2_entry(reservoir={"volumeMl": 500, "remainingMl": 200, "mixedAt": stamp(23, now)})
        entry.options[SETTINGS]["nps"]["hatchery"]["fridgeBottle"] = {
            "remainingMl": 200, "mixedAt": stamp(30, now), "refrigeratedAt": stamp(30, now)}
        hass, conn = FakeHass(entries=[entry]), FakeConnection()
        run(integration.websocket_nps_fridge_bottle(hass, conn, {"id": 1, "action": "fill"}))
        self.assertFalse(conn.errors)
        bottle = entry.options[SETTINGS]["nps"]["hatchery"]["fridgeBottle"]
        self.assertEqual(bottle["mixedAt"], stamp(23, now))  # newer warm load expires first
        res = entry.options[SETTINGS]["nps"]["hatchery"]["reservoir"]
        res.update({"remainingMl": 200, "mixedAt": stamp(1, now)})
        before = deepcopy(entry.options[SETTINGS])
        run(integration.websocket_nps_fridge_bottle(hass, conn, {"id": 2, "action": "return"}))
        self.assertEqual(conn.errors[-1].code, "container_full")
        self.assertEqual(entry.options[SETTINGS], before)

    def test_linked_pump_uses_batch_clock_and_blocks_a_running_soak(self):
        config = config_with_load(age=26, fridgeSavedH=10)
        channel = {"chemical": "livefood", "enabled": True,
                   "schedule": {"enabled": True, "mlPerDay": 100},
                   "calibration": {"stepsPerMl": 100},
                   "reservoir": {"volumeMl": 750, "remainingMl": 300,
                                 "mixedAt": stamp(26), "shelfLifeDays": 1}}
        config["dosing"] = {"channels": {"brine": channel}}
        config["nps"].setdefault("feedExchange", {})["channelId"] = "brine"
        fresh = integration._dosing_food_freshness(channel, NOW, config)
        self.assertEqual(fresh["hoursLeft"], 8)
        self.assertTrue(integration._dosing_desired_switches(channel, NOW, config)["enabledSwitch"])
        config["nps"]["hatchery"]["enrichment"]["state"]["startedAt"] = stamp(1)
        fresh = integration._dosing_food_freshness(channel, NOW, config)
        self.assertEqual(fresh["status"], "soaking")
        self.assertFalse(integration._dosing_desired_switches(channel, NOW, config)["enabledSwitch"])
        reasons = fixtures.dosing.guard_reasons(channel, {"foodFreshness": fresh}, 720, now=NOW)
        self.assertTrue(any(r["code"] == "food_soaking" and r["severity"] == "block" for r in reasons))
        # Unlinked pumps still use their own shelf settings.
        config["nps"]["feedExchange"]["channelId"] = ""
        self.assertEqual(integration._dosing_food_freshness(channel, NOW, config)["status"], "stale")

    def test_empty_stock_and_expiry_boundaries_never_grant_runway(self):
        result = nps.next_hatch_suggestion(NOW, 24, stamp(1), 24, 0, None, None)
        self.assertEqual(result["readyBy"], NOW.isoformat())
        config = config_with_load(age=24)
        error = integration._nps_container_load(config, config["nps"]["hatchery"], NOW, enriched=False)
        self.assertEqual(error[0], "stale_brine")

    def test_discard_clears_soak_and_boost_stamps(self):
        entry = fixtures._enrich_entry()
        hass, conn = FakeHass(entries=[entry]), FakeConnection()
        run(integration.websocket_nps_hatch_enrich(hass, conn, {"id": 1}))
        run(integration.websocket_nps_reservoir_discard(hass, conn, {"id": 2}))
        hatchery = entry.options[SETTINGS]["nps"]["hatchery"]
        self.assertEqual(hatchery["reservoir"]["remainingMl"], 0)
        self.assertFalse(hatchery["enrichment"]["state"]["startedAt"])
        self.assertFalse(hatchery["reservoir"]["enrichedAt"])
        run(integration.websocket_nps_enrich_loaded(hass, conn, {"id": 3}))
        self.assertEqual(conn.errors[-1].code, "no_enrichment")

    def test_cyst_defaults_and_cycle_count_make_no_yield_speed_assumption(self):
        self.assertEqual(nps.egg_type_hours("premium"), 24)
        self.assertEqual(nps.egg_type_hours("decapsulated"), 24)
        self.assertEqual(nps.vessels_needed(24, 24), 1)
        self.assertEqual(nps.vessels_needed(36, 24), 2)


if __name__ == "__main__":
    unittest.main()
