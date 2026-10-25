"""Independent arithmetic and ledger checks from the hatchery/cultures audit.

Run: python3 tests/test_cultures_integrity.py (fake HA only).
"""
from copy import deepcopy
from datetime import timedelta
import math
import unittest

import test_cultures as t
from test_nps import _drip_channel
from _fake_ha import FakeConnection, FakeHass, run

C, I, NOW = t.cultures, t.integration, t.REAL


def stamp(days=0):
    return (NOW - timedelta(days=days)).isoformat()


def phyto_config(**kwargs):
    return t._config(t._phyto_entry(jars={"c1": t._phyto_jar(started_ago_days=12, now=NOW, lastTint="dark", workingL=3.5)}, **kwargs))


class CultureIntegrity(unittest.TestCase):
    def test_150_ml_tank_draw_without_topup_leaves_485_l_and_preserves_stock(self):
        parent = t._phyto_jar(started_ago_days=19, now=NOW, lastTint="dark", workingL=5,
                             lastHarvestAt=stamp(7), cyclesSinceFresh=2)
        parent["volumeL"] = 5
        products = {**t._phyto_products(), "home_phyto_c1": {
            "name": "Home phyto", "category": "phyto", "bottleMl": 2500, "remainingMl": 1300,
            "openedAt": stamp(1), "shelfLifeDaysOpened": 21, "history": []}}
        cfg = t._config(t._phyto_entry(jars={"c1": parent}, products=products))
        before_products = deepcopy(cfg["consumables"]["products"])
        before_station = deepcopy(cfg["mixingStation"])
        error = I._cultures_phyto_split_apply(FakeHass(), cfg, "c1", ml=150,
                                            dests=[{"to": "tank", "ml": 150}],
                                            fresh_ml=0, nutrient=False, tint="dark", now=NOW)
        self.assertIsNone(error)
        jar = cfg["nps"]["cultures"]["jars"]["c1"]
        self.assertEqual(jar["state"]["workingL"], 4.85)
        self.assertEqual(jar["state"]["lastTint"], "dark")
        self.assertEqual(jar["state"]["lastHarvestAt"], stamp(7))
        self.assertEqual(jar["state"]["cyclesSinceFresh"], 2)
        row = jar["history"][0]
        self.assertTrue(row["draw"])
        self.assertEqual((row["ml"], row["tankMl"], row["freshMl"], row["nutrientMl"]), (150, 150, 0, 0))
        self.assertEqual(row["dests"], [{"to": "tank", "ml": 150}])
        for pid in before_products:
            self.assertEqual(cfg["consumables"]["products"][pid]["remainingMl"], before_products[pid]["remainingMl"])
        self.assertEqual(cfg["mixingStation"], before_station)

    def test_shallow_index_and_secchi_fits_use_unrounded_slopes(self):
        for index in (True, False):
            rows = [{"event": "seeded", "at": stamp(30)}]
            points = []
            for i in range(4):
                day = i if index else i * 9
                value = 2 + i * .001 if index else 60 - i * .1
                points.append((day, math.log(value)))
                rows.append({"event": "index" if index else "tint", "at": stamp(30-day),
                             "od" if index else "secchiCm": value,
                             "tint": "green" if i < 2 else "dark"})
            result = C.index_fit(rows, 1) if index else C.secchi_fit(rows, 60)
            self.assertTrue(result["fit"]["available"])
            self.assertTrue(math.isfinite(result["daysToDark"]))
            mx = sum(x for x, _ in points) / 4
            my = sum(y for _, y in points) / 4
            slope = sum((x-mx)*(y-my) for x, y in points) / sum((x-mx)**2 for x, _ in points)
            band = result["darkOd"] if index else result["bands"]["dark"]
            expected = math.log(band / 1) / slope if index else math.log(60 / band) / -slope
            self.assertAlmostEqual(result["daysToDark"], expected, delta=.051)

    def test_draws_keep_recovery_peak_and_measurement_cycle_anchors(self):
        rows = [{"event": "seeded", "at": stamp(10)},
                {"event": "tint", "at": stamp(4), "tint": "dark"},
                {"event": "harvest", "at": stamp(1), "ml": 100, "draw": True},
                {"event": "tint", "at": stamp(), "tint": "dark", "secchiCm": 2},
                {"event": "index", "at": stamp(), "od": 1}]
        self.assertEqual(C.darkening_samples(rows), [6])
        self.assertEqual(C._dark_run_days(rows, NOW-timedelta(days=10), NOW), 4)
        self.assertEqual(C.secchi_samples(rows)[0]["days"], 10)
        self.assertEqual(C.index_samples(rows)[0]["days"], 10)
        self.assertEqual(C.darkening_by_depth(rows)["byDepth"], {})

    def test_future_observation_cannot_clear_a_health_warning(self):
        jar = t._phyto_jar(started_ago_days=12, now=NOW, lastTint="dark", lastSignAt=stamp(1), lastSign="foam")
        jar["history"] = [{"event": "tint", "at": stamp(-1), "tint": "dark"}]
        self.assertTrue(C.culture_state(jar, NOW)["harvestBlocked"])

    def test_daily_draw_does_not_exceed_learned_recovery(self):
        for pct in (10, 30, 50, 60, 90):
            for days in (1, 2, 4, 8, 12, 30):
                expected = 100 * (1 - (1-pct/100)**(1/days))
                self.assertLessEqual(C.daily_draw_pct(pct, days), expected + 1e-9)
        self.assertEqual(C.daily_draw_pct(60, 8), 10.8)
        jar = t._phyto_jar(started_ago_days=30, now=NOW)
        jar["history"] = [{"event": event, "at": stamp(days), "tint": tint}
                          for event, days, tint in (("seeded", 30, "pale"), ("tint", 18, "dark"),
                                                   ("harvest", 17, "pale"), ("tint", 5, "dark"))]
        learned = C.learned_cadences(jar, [], NOW)
        self.assertFalse(learned["dailyOffer"]["available"])
        self.assertIsNone(learned["suggest"]["mode"])

    def test_flat_ph_does_not_certify_harvest_readiness(self):
        result = C.ph_trend([{"event": "light", "at": stamp(d), "phMax": 8} for d in (2, 1, 0)])
        self.assertEqual(result["trend"], "flat")
        self.assertNotIn("ready to split", result["line"])

    def test_seed_rejects_more_starter_than_final_volume(self):
        jar = t._phyto_jar()
        for starter, working in ((2000, 1), (5000, None)):
            self.assertFalse(C.seed_guide(jar, starter_ml=starter, working_l=working)["available"])
        guide = C.seed_guide(jar, starter_ml=250, working_l=3.5)
        self.assertEqual(guide["starterMl"] + guide["freshMl"], guide["workingMl"])
        self.assertEqual(guide["nutrientMl"], round(3.25*1.5, 1))
        self.assertFalse(C.split_guide(jar, ml=4000, fresh_ml=0)["available"])

    def test_three_way_refill_handles_stronger_phyto_and_refuses_excess(self):
        guide = C.refill_guide(.5, 100, 27, 20, 250, 35)
        self.assertNotEqual(guide.get("available"), False)
        self.assertEqual(guide["phytoMl"] + guide["mixMl"] + guide["rodiMl"], 500)
        self.assertAlmostEqual(guide["phytoMl"]*35 + guide["mixMl"]*20, 500*27, delta=10)
        self.assertFalse(C.refill_guide(.5, 100, 27, 35, 600, 35)["available"])

    def test_expired_refill_sources_and_insufficient_defaults_are_not_offered(self):
        for remaining, age in ((900, 2), (2, 0)):
            cfg = phyto_config(products={"home_phyto_c1": {"name": "Home phyto", "category": "phyto", "bottleMl": 1000,
                                                      "remainingMl": remaining, "shelfLifeDaysOpened": 1, "openedAt": stamp(age)}})
            cs = cfg["nps"]["cultures"]
            cs["jars"]["r"] = t._jar(started_ago_days=10, now=NOW, lastTint="clearing")
            cfg["nps"]["cultures"] = I._nps_cultures_cfg(cfg)
            cs = cfg["nps"]["cultures"]
            jar = cs["jars"]["r"]
            found = I._cultures_phyto_source(cfg, cs, jar, "r", "bottle:home_phyto_c1", 100, 675, NOW, "clearing")
            self.assertIsInstance(found, tuple)
            payload = I._cultures_animal_phyto_payload(cfg, cs, "r", jar, C.culture_state(jar, NOW), 35, NOW)
            self.assertEqual(next(s for s in payload["phytoSources"] if s["kind"] == "bottle")["ready"], age == 0)
            self.assertNotEqual((payload["phytoRefill"] or {}).get("sourceId"), "bottle:home_phyto_c1")

    def test_restart_and_seed_refuse_unavailable_linked_feed_atomically(self):
        for action in ("restart", "seed"):
            jar = t._jar(started_ago_days=10, now=NOW, lastTint="clearing")
            if action == "seed":
                jar["state"] = {}
            entry = t._entry(jars={"r": jar}, products={"phyto": {"category": "phyto", "remainingMl": 0}})
            if action == "restart":
                cfg = t._config(entry)
                before = deepcopy(cfg)
                self.assertEqual(I._cultures_restart_apply(FakeHass(), cfg, "r")[0], "feed_unavailable")
                self.assertEqual(cfg, before)
            else:
                before = deepcopy(entry.options)
                conn = FakeConnection()
                run(I.websocket_cultures_seed(FakeHass(entries=[entry]), conn, {"id": 1, "jar_id": "r"}))
                self.assertEqual(conn.errors[-1].code, "feed_unavailable")
                self.assertEqual(entry.options, before)

    def test_topups_preserve_old_and_unknown_ages(self):
        for when in (stamp(2), "", "invalid", stamp(-1)):
            bottle = {"remainingMl": 100, "bottleMl": 1000, "openedAt": when}
            I._cultures_home_bottle_fill(bottle, 100, NOW, {}, "Phyto")
            expected = stamp(2) if when == stamp(2) else ""
            self.assertEqual(bottle["openedAt"], expected)
            channel = _drip_channel(reservoir={"volumeMl": 1000, "remainingMl": 100, "mixedAt": when})
            I._cultures_drip_load(FakeHass(), "drip", channel, 100, "Phyto", NOW)
            self.assertEqual(channel["reservoir"]["mixedAt"], expected)

    def test_zero_drip_share_uses_only_unallocated_split(self):
        channel = _drip_channel(reservoir={"productId": "home_phyto_c1", "productIsBottle": False,
                                           "volumeMl": 1000, "remainingMl": 0})
        cfg = phyto_config(channels={"drip": channel})
        self.assertIsNone(I._cultures_phyto_split_apply(FakeHass(), cfg, "c1", ml=500,
                                                      dests=[{"to": "tank", "ml": 400}, {"to": "drip", "ml": 0}], now=NOW))
        self.assertEqual(cfg["dosing"]["channels"]["drip"]["reservoir"]["remainingMl"], 100)
        row = cfg["nps"]["cultures"]["jars"]["c1"]["history"][0]
        self.assertEqual(sum(d["ml"] for d in row["dests"]), 500)

    def test_bottle_overflow_is_recorded_as_waste(self):
        cfg = phyto_config()
        self.assertIsNone(I._cultures_phyto_split_apply(FakeHass(), cfg, "c1", ml=2100, now=NOW))
        row = cfg["nps"]["cultures"]["jars"]["c1"]["history"][0]
        self.assertEqual({s["to"]: s["ml"] for s in row["dests"]}, {"bottle": 1000, "waste": 1100})
        self.assertEqual(sum(d["ml"] for d in row["dests"]), row["ml"])

    def test_default_backup_share_is_validated_before_parent_split(self):
        cfg = phyto_config()
        before = deepcopy(cfg)
        error = I._cultures_phyto_split_apply(FakeHass(), cfg, "c1", ml=100,
                                            dests=[{"to": "vessel", "ml": 0}], now=NOW)
        self.assertEqual(error[0], "invalid_volume")
        self.assertEqual(cfg, before)

    def test_tracked_nutrient_must_cover_parent_and_backup_together(self):
        cfg = phyto_config()
        jar = cfg["nps"]["cultures"]["jars"]["c1"]
        pid, nutrient = I._cultures_nutrient_product(cfg, jar)
        nutrient["remainingMl"] = .8
        before = deepcopy(cfg)
        error = I._cultures_phyto_split_apply(FakeHass(), cfg, "c1", ml=500,
                                            dests=[{"to": "vessel", "ml": 250}], now=NOW)
        self.assertEqual(error[0], "nutrient_unavailable")
        self.assertEqual(cfg, before)

    def test_disabled_drip_schedule_does_not_inflate_demand(self):
        channel = _drip_channel(reservoir={"productId": "home_phyto_c1", "productIsBottle": False})
        channel["schedule"]["enabled"] = False
        cfg = phyto_config(channels={"drip": channel})
        summary = I._cultures_summary_payload(FakeHass(), cfg)
        self.assertNotIn("the drip", summary["jars"][0]["sizing"]["line"])

    def test_seed_from_sibling_conserves_donor_and_starter_volumes(self):
        parent = t._phyto_jar(started_ago_days=12, now=NOW, lastTint="dark", workingL=3.5)
        target = t._phyto_jar()
        target["state"] = {}
        entry = t._phyto_entry(jars={"c1": parent, "c2": target})
        conn = FakeConnection()
        run(I.websocket_cultures_seed(FakeHass(entries=[entry]), conn,
                                     {"id": 1, "jar_id": "c2", "from_jar_id": "c1", "starter_ml": 250, "working_l": 1.25}))
        self.assertFalse(conn.errors)
        jars = t._cultures(entry)["jars"]
        self.assertEqual(jars["c1"]["state"]["workingL"], 3.25)
        self.assertEqual(jars["c2"]["state"]["workingL"], 1.25)
        self.assertEqual(jars["c1"]["history"][0]["ml"], 250)
        self.assertTrue(jars["c1"]["history"][0]["draw"])
        self.assertEqual(jars["c2"]["history"][0]["freshMl"], 1000)
        self.assertEqual(jars["c1"]["state"]["lastTint"], "dark")

    def test_rejected_new_backup_does_not_insert_a_jar(self):
        cfg = phyto_config()
        _, nutrient = I._cultures_nutrient_product(cfg, cfg["nps"]["cultures"]["jars"]["c1"])
        nutrient["remainingMl"] = 0
        before = deepcopy(cfg)
        error, _ = I._cultures_split_apply(FakeHass(), cfg, "c1", "", NOW)
        self.assertEqual(error[0], "nutrient_unavailable")
        self.assertEqual(cfg, before)

    def test_undo_credits_original_bottle_after_feed_setting_changes(self):
        cfg = t._config(t._entry(jars={"r": t._jar(started_ago_days=10, now=NOW, lastTint="clearing")}))
        original = cfg["consumables"]["products"]["phyto"]["remainingMl"]
        self.assertIsNone(I._cultures_log_apply(FakeHass(), cfg, "r", fed=True))
        jar = cfg["nps"]["cultures"]["jars"]["r"]
        at = jar["history"][0]["at"]
        jar["feed"]["productId"] = "different"
        self.assertIsNone(I._cultures_undo_apply(cfg, "r", at, NOW+timedelta(minutes=1)))
        self.assertEqual(cfg["consumables"]["products"]["phyto"]["remainingMl"], original)

    def test_green_source_is_not_an_automatic_dark_culture_dose(self):
        cfg = phyto_config()
        cs = cfg["nps"]["cultures"]
        cs["jars"]["c1"]["state"]["lastTint"] = "green"
        jar = t._jar(started_ago_days=10, now=NOW, lastTint="clearing")
        auto = I._cultures_phyto_source(cfg, cs, jar, "r", "vessel:c1", None, 675, NOW, "clearing")
        self.assertEqual(auto[0], "vessel_not_ready")
        manual = I._cultures_phyto_source(cfg, cs, jar, "r", "vessel:c1", 100, 675, NOW, "clearing")
        self.assertIsInstance(manual, dict)


if __name__ == "__main__":
    unittest.main()
