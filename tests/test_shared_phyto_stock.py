"""Several phyto vessels can harvest into one stock entry (fake HA only)."""
from copy import deepcopy
from datetime import timedelta
from unittest import TestCase, main

import test_cultures as t

I, C, N, NOW = t.integration, t.cultures, t.nps_engine, t.REAL


def stamp(hours=0):
    return t._iso(NOW - timedelta(hours=hours))


def entry_with_bottles():
    jars = {key: t._phyto_jar(started_ago_days=8, now=NOW, lastTint="dark", workingL=3.5,
                              lastLookedAt=stamp(1)) for key in ("main", "backup")}
    for key, jar in jars.items():
        jar["name"] = "Nanno " + key.title()
        jar["history"] = [{"at": stamp(1), "event": "tint", "tint": "dark"}]
    entry = t._phyto_entry(jars=jars)
    cfg = t._config(entry)
    I._cultures_ensure_home_bottles(cfg)
    products = cfg["consumables"]["products"]
    products["home_phyto_main"].update(bottleMl=2500, remainingMl=600, doseMl=100,
        openedAt=stamp(48), lastDosedAt=stamp(1), lastShakenAt=stamp(1),
        history=[{"kind": "dose", "at": stamp(1), "ml": 100, "to": "tank"}])
    products["home_phyto_backup"].update(remainingMl=1000, openedAt=stamp(2),
        history=[{"kind": "dose", "at": stamp(3), "ml": 35, "to": "tank"}])
    entry.options[t.CONF_SETTINGS] = cfg
    return entry


class SharedPhytoStock(TestCase):
    def merge(self, entry, **fields):
        hass, conn = t.FakeHass(entries=[entry]), t.FakeConnection()
        t.run(I.websocket_cultures_share_bottle(hass, conn, {
            "id": 1, "jar_id": "backup", "target_jar_id": "main", **fields}))
        return hass, conn

    def test_merge_combines_stock_and_preserves_target_plan_and_oldest_age(self):
        entry = entry_with_bottles()
        before = t._config(entry)
        hass, conn = self.merge(entry)
        self.assertFalse(conn.errors)
        cfg = t._config(entry)
        products = cfg["consumables"]["products"]
        self.assertNotIn("home_phyto_backup", products)
        shared = products["home_phyto_main"]
        self.assertEqual((shared["remainingMl"], shared["bottleMl"], shared["doseMl"]), (1600, 2500, 100))
        self.assertEqual(shared["openedAt"], stamp(48))
        self.assertEqual(shared["lastDosedAt"], stamp(1))
        for key, jar in cfg["nps"]["cultures"]["jars"].items():
            self.assertEqual(jar["bottleProductId"], "home_phyto_main")
            self.assertEqual(jar["state"], before["nps"]["cultures"]["jars"][key]["state"])
        self.assertNotIn("nps_dose_home_phyto_backup", cfg["maintenance"]["tasks"])
        self.assertEqual(cfg["mixingStation"], before["mixingStation"])
        self.assertEqual(products["f2"], before["consumables"]["products"]["f2"])
        self.assertFalse([call for call in hass.services.calls if call.domain in ("switch", "number", "button")])
        self.merge(entry)
        self.assertEqual(t._config(entry)["consumables"]["products"]["home_phyto_main"]["remainingMl"], 1600)

    def test_both_splits_fill_the_same_capacity_and_one_dose_debits_it(self):
        entry = entry_with_bottles()
        hass, conn = self.merge(entry)
        for key in ("main", "backup"):
            t.run(I.websocket_cultures_split(hass, conn, {"id": 2, "jar_id": key, "ml": 200,
                "fresh_ml": 200, "to": [{"to": "bottle", "ml": 200}], "nutrient": False}))
        self.assertFalse(conn.errors)
        cfg = t._config(entry)
        self.assertEqual(cfg["consumables"]["products"]["home_phyto_main"]["remainingMl"], 2000)
        summary = I._cultures_summary_payload(hass, cfg)
        for jar in summary["jars"]:
            self.assertEqual(jar["homeBottle"]["remainingMl"], 2000)
            self.assertEqual(jar["homeBottle"]["bottleMl"], 2500)
            self.assertEqual(jar["splitGuide"]["bottleFreeMl"], 500)
        events = N.feed_timeline(NOW + timedelta(hours=25), products=cfg["consumables"]["products"],
                                 channels={}, cultures=cfg["nps"]["cultures"], tank_l=52)["events"]
        planned = [row for row in events if row["source"].startswith("shelf:home_phyto_")
                   and row["status"] in ("due", "late", "missed", "planned")]
        self.assertEqual([(row["source"], row["ml"]) for row in planned], [("shelf:home_phyto_main", 100)])
        t.run(I.websocket_consumable_log_dose(hass, conn, {"id": 3, "product_id": "home_phyto_main"}))
        self.assertFalse(conn.errors)
        self.assertEqual(t._config(entry)["consumables"]["products"]["home_phyto_main"]["remainingMl"], 1900)

    def test_old_feeds_keep_their_identity_in_the_archive(self):
        entry = entry_with_bottles()
        hass, conn = self.merge(entry)
        self.assertFalse(conn.errors)
        cfg = t._config(entry)
        rows = I._feeding_capture(cfg, cfg, NOW)["rows"]
        feeds = [r for r in rows if r.get("source", "").startswith("shelf:home_phyto_")]
        self.assertEqual(len(feeds), 2, feeds)
        self.assertEqual(sum(r["ml"] for r in feeds), 135)
        old = next(r for r in feeds if r["source"] == "shelf:home_phyto_backup")
        native, inventory, _, _ = I._feeding_native_row(cfg, old)
        self.assertEqual(native["ml"], 35)
        self.assertIs(inventory, cfg["consumables"]["products"]["home_phyto_main"])
        t.run(I.websocket_feeding_undo(hass, conn, {"id": 2, "entry_id": old["id"]}))
        self.assertFalse(conn.errors)
        cfg = t._config(entry)
        self.assertEqual(cfg["consumables"]["products"]["home_phyto_main"]["remainingMl"], 1635)
        self.assertEqual(len(I._feeding_capture(cfg, cfg, NOW)["rows"]), len(rows))

    def test_merge_relinks_cone_and_pump_stock_without_changing_pump_volume(self):
        entry = entry_with_bottles()
        cfg = entry.options[t.CONF_SETTINGS]
        cfg["nps"]["cultures"]["jars"]["rot"] = t._jar(started_ago_days=20)
        cfg["nps"]["cultures"]["jars"]["rot"]["feed"]["productId"] = "home_phyto_backup"
        cfg["dosing"] = {"channels": {"phyto": {"reservoir": {
            "productId": "home_phyto_backup", "productIsBottle": False, "volumeMl": 500, "remainingMl": 123}}}}
        stale = deepcopy(cfg)
        _, conn = self.merge(entry)
        self.assertFalse(conn.errors)
        cfg = t._config(entry)
        reservoir = cfg["dosing"]["channels"]["phyto"]["reservoir"]
        self.assertEqual(reservoir["productId"], "home_phyto_main")
        self.assertEqual(reservoir["remainingMl"], 123)
        self.assertEqual(cfg["nps"]["cultures"]["jars"]["rot"]["feed"]["productId"], "home_phyto_main")
        I._nps_preserve_runtime(cfg, stale)
        self.assertEqual(stale["dosing"]["channels"]["phyto"]["reservoir"]["productId"], "home_phyto_main")

    def test_simultaneous_old_doses_remain_distinct_and_undo_credits_correct_amount(self):
        entry = entry_with_bottles()
        products = entry.options[t.CONF_SETTINGS]["consumables"]["products"]
        products["home_phyto_backup"]["history"][0]["at"] = stamp(1)
        hass, conn = self.merge(entry)
        cfg = t._config(entry)
        feeds = [row for row in I._feeding_capture(cfg, cfg, NOW)["rows"]
                 if row.get("source", "").startswith("shelf:home_phyto_")]
        self.assertEqual(len(feeds), 2)
        backup = next(row for row in feeds if row["source"] == "shelf:home_phyto_backup")
        t.run(I.websocket_feeding_undo(hass, conn, {"id": 2, "entry_id": backup["id"]}))
        self.assertFalse(conn.errors)
        cfg = t._config(entry)
        shared = cfg["consumables"]["products"]["home_phyto_main"]
        self.assertEqual(shared["remainingMl"], 1635)
        self.assertFalse(next(row for row in shared["history"] if row.get("ml") == 100).get("undoneAt"))

    def test_a_third_vessel_can_join_the_same_stock_without_recounting_earlier_merges(self):
        entry = entry_with_bottles()
        self.merge(entry)
        cfg = t._config(entry)
        third = deepcopy(cfg["nps"]["cultures"]["jars"]["main"])
        third.update(name="Nanno Third", bottleProductId="home_phyto_third", bottleMl=5000)
        cfg["nps"]["cultures"]["jars"]["third"] = third
        I._cultures_ensure_home_bottles(cfg)
        cfg["consumables"]["products"]["home_phyto_third"].update(remainingMl=400, openedAt=stamp(24))
        entry.options[t.CONF_SETTINGS] = cfg
        _, conn = self.merge(entry, jar_id="main", target_jar_id="third")
        self.assertFalse(conn.errors)
        cfg = t._config(entry)
        for jar in cfg["nps"]["cultures"]["jars"].values():
            self.assertEqual(jar["bottleProductId"], "home_phyto_third")
        self.assertEqual(I._cultures_resolve_bottle(cfg, "home_phyto_backup"), "home_phyto_third")
        self.assertEqual(cfg["consumables"]["products"]["home_phyto_third"]["remainingMl"], 2000)
        stale = deepcopy(cfg)
        stale["nps"]["cultures"]["bottleMerges"] = {}
        I._nps_preserve_runtime(cfg, stale)
        I._cultures_ensure_home_bottles(stale)
        self.assertEqual(stale["consumables"]["products"]["home_phyto_third"]["remainingMl"], 2000)
        self.assertNotIn("home_phyto_backup", stale["consumables"]["products"])
        self.assertNotIn("home_phyto_main", stale["consumables"]["products"])

    def test_merge_preserves_unknown_or_older_stock_age_through_stale_save(self):
        for opened in ("", stamp(120)):
            with self.subTest(opened=opened):
                entry = entry_with_bottles()
                products = entry.options[t.CONF_SETTINGS]["consumables"]["products"]
                products["home_phyto_backup"]["openedAt"] = opened
                products["home_phyto_main"].update(cellsPerMl=1234, cellsPerMlSource="index", cellsPerMlAt=stamp(1))
                stale = deepcopy(t._config(entry))
                _, conn = self.merge(entry)
                self.assertFalse(conn.errors)
                cfg = t._config(entry)
                I._nps_preserve_runtime(cfg, stale)
                for snapshot in (cfg, stale):
                    shared = snapshot["consumables"]["products"]["home_phyto_main"]
                    self.assertEqual(shared["openedAt"], opened)
                    self.assertEqual(shared["cellsPerMl"], 0)
                    self.assertNotIn("cellsPerMlSource", shared)

    def test_stale_settings_cannot_recreate_the_old_bottle_or_lose_stock(self):
        entry = entry_with_bottles()
        stale = deepcopy(t._config(entry))
        self.merge(entry)
        stored = t._config(entry)
        I._nps_preserve_runtime(stored, stale)
        I._cultures_ensure_home_bottles(stale)
        cfg = I._normalise_core_config(stale)
        self.assertNotIn("home_phyto_backup", cfg["consumables"]["products"])
        self.assertEqual(cfg["consumables"]["products"]["home_phyto_main"]["remainingMl"], 1600)
        self.assertEqual(cfg["nps"]["cultures"]["jars"]["backup"]["bottleProductId"], "home_phyto_main")

    def test_invalid_merge_is_refused_without_changes(self):
        for kind in ("capacity", "salinity", "species", "unknown"):
            with self.subTest(kind=kind):
                entry = entry_with_bottles()
                cfg = entry.options[t.CONF_SETTINGS]
                if kind == "capacity":
                    cfg["consumables"]["products"]["home_phyto_main"]["bottleMl"] = 1500
                elif kind == "salinity":
                    cfg["nps"]["cultures"]["jars"]["main"]["salinityPpt"] = 27
                elif kind == "species":
                    cfg["nps"]["cultures"]["jars"]["main"]["species"] = "rotifer_L"
                before = deepcopy(entry.options)
                _, conn = self.merge(entry, **({"target_jar_id": "absent"} if kind == "unknown" else {}))
                self.assertTrue(conn.errors)
                self.assertEqual(entry.options, before)

    def test_shared_low_stock_advice_can_use_either_ready_culture(self):
        entry = entry_with_bottles()
        self.merge(entry)
        cfg = t._config(entry)
        cfg["consumables"]["products"]["home_phyto_main"]["remainingMl"] = 0
        jars = cfg["nps"]["cultures"]["jars"]
        jars["main"]["state"]["lastTint"] = "pale"
        shelf = N.shelf_summary(cfg["consumables"]["products"], NOW, 52)
        I._cultures_shelf_nudges(cfg, shelf["products"], NOW)
        shared = shelf["products"]["home_phyto_main"]
        self.assertIn("Nanno Backup reads dark", shared["splitNudge"])
        self.assertEqual(set(shared["cultureNames"]), {"Nanno Main", "Nanno Backup"})


if __name__ == "__main__":
    main()
