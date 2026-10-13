"""Pump and hand-feeding must agree on whether a brine batch is usable."""

import unittest

from test_hatchery_audit import NOW, config_with_load, integration, nps, stamp


class HatcheryPumpClockAudit(unittest.TestCase):
    def test_pump_and_manual_feed_reject_unverifiable_batch_clocks(self):
        for mixed_at, extra in (
                (stamp(-1), {}),
                (NOW.replace(tzinfo=None).isoformat(), {}),
                ("invalid", {}),
                (stamp(2), {"lastLoadEnriched": True, "enrichedAt": stamp(-1)}),
                (stamp(2), {"lastLoadEnriched": True, "enrichedAt": stamp(3)})):
            with self.subTest(mixed_at=mixed_at, extra=extra):
                config = config_with_load(**extra)
                channel = {
                    "chemical": "livefood", "enabled": True,
                    "schedule": {"enabled": True, "mlPerDay": 100},
                    "calibration": {"stepsPerMl": 100},
                    "reservoir": {"volumeMl": 750, "remainingMl": 300,
                                  "mixedAt": mixed_at, "shelfLifeDays": 1}}
                config["dosing"] = {"channels": {"brine": channel}}
                config["nps"].setdefault("feedExchange", {})["channelId"] = "brine"
                self.assertEqual(integration._dosing_food_freshness(channel, NOW, config)["status"], "stale")
                self.assertFalse(integration._dosing_desired_switches(channel, NOW, config)["enabledSwitch"])
                hatchery = integration._nps_feed_hatchery(config)
                self.assertFalse(nps.brine_feed_sources(hatchery, NOW)["container"]["available"])

    def test_valid_custom_shelf_and_cold_credit_remain_usable(self):
        config = config_with_load(age=30, fridgeSavedH=8)
        channel = {
            "chemical": "livefood", "enabled": True,
            "schedule": {"enabled": True, "mlPerDay": 100},
            "calibration": {"stepsPerMl": 100},
            "reservoir": {"volumeMl": 750, "remainingMl": 300,
                          "mixedAt": stamp(30), "shelfLifeDays": 2}}
        config["dosing"] = {"channels": {"brine": channel}}
        config["nps"].setdefault("feedExchange", {})["channelId"] = "brine"
        self.assertEqual(integration._dosing_food_freshness(channel, NOW, config)["hoursLeft"], 26)
        self.assertTrue(integration._dosing_desired_switches(channel, NOW, config)["enabledSwitch"])


if __name__ == "__main__":
    unittest.main()
