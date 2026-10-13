"""Stock/readiness agreement across feeding plans, cards and logging actions.

Run: python3 tests/test_feeding_availability.py (fake HA only).
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

import test_nps as t
import test_cultures as c
from _fake_ha import FakeConnection, FakeHass, run

nps, integration = t.nps, t.integration
NOW = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)


def stamp(hours=1, now=NOW):
    return (now - timedelta(hours=hours)).isoformat()


def hatchery(now=NOW, ml=100):
    return {"enabled": True, "reservoir": {"remainingMl": ml, "volumeMl": 750, "mixedAt": stamp(now=now)},
            "fridgeBottle": {}, "handFeed": {"defaultDoseMl": 30, "feedsPerDay": 2}}


def pending(**kw):
    return [e for e in t._tl(NOW, **kw)["events"] if e["status"] in ("due", "late", "planned", "missed")]


class FeedingAvailability(unittest.TestCase):
    def test_food_coverage_and_pump_suggestions_do_not_count_empty_or_expired_bottles(self):
        product = {"name": "Phyto", "category": "phyto", "particleUmMin": 1, "particleUmMax": 10,
                   "remainingMl": 100, "shelfLifeDaysOpened": 1, "openedAt": stamp()}
        channels = {"food": {"chemical": "food", "enabled": True, "reservoir": {"productId": "p"}}}
        for change in ({"remainingMl": 0}, {"openedAt": stamp(25)}, {"openedAt": ""}):
            plan = nps.compile_feed_plan(["dendronephthya"], {"p": {**product, **change}}, channels, now=NOW)
            self.assertEqual(plan["counts"]["covered"], 0)
            self.assertEqual(plan["suggestions"], [])
        self.assertEqual(nps.compile_feed_plan(["dendronephthya"], {"p": product}, {}, now=NOW)["counts"]["covered"], 1)

    def test_rotifer_plan_requires_fresh_stock_and_reserves_only_remaining_volume(self):
        bottle = {"remainingMl": 50, "filledAt": stamp(), "doseMl": 30, "feedsPerDay": 3}
        self.assertEqual(len(pending(cultures={"bottle": bottle})), 1)
        for changes in ({"remainingMl": 20}, {"remainingMl": 0}, {"filledAt": stamp(121)},
                        {"filledAt": ""}, {"filledAt": stamp(-1)}):
            with self.subTest(changes=changes):
                self.assertEqual(pending(cultures={"bottle": {**bottle, **changes}}), [])

    def test_brine_plan_requires_usable_stock_and_names_the_actual_source(self):
        h = hatchery()
        for changes in ({"remainingMl": 20}, {"mixedAt": stamp(25)}, {"mixedAt": ""},
                        {"mixedAt": stamp(-1)}):
            with self.subTest(changes=changes):
                self.assertEqual(pending(hatchery={**h, "reservoir": {**h["reservoir"], **changes}}), [])
        h["enrichment"] = {"state": {"startedAt": stamp(), "batchLoadedAt": stamp()}}
        self.assertEqual(pending(hatchery=h), [])
        h["fridgeBottle"] = {"remainingMl": 50, "mixedAt": stamp(30), "refrigeratedAt": stamp(30)}
        events = pending(hatchery=h)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["feedVessels"], ["bottle"])
        self.assertIn("fridge bottle", events[0]["note"])

    def test_completed_feeds_survive_empty_stock_disabling_and_enabling_a_pump(self):
        h = hatchery(ml=0)
        feed = {"at": stamp(), "ml": 30, "from": "container"}
        for enabled, fx in ((True, False), (False, False), (True, True)):
            events = t._tl(NOW, hatchery={**h, "enabled": enabled}, brine_feeds=[feed], fx_enabled=fx)["events"]
            self.assertEqual([(e["status"], e["actualMl"]) for e in events], [("done", 30)])
        bottle = {"remainingMl": 0, "history": [{"event": "fed_tank", "at": stamp(), "ml": 40}]}
        events = t._tl(NOW, cultures={"enabled": False, "bottle": bottle})["events"]
        self.assertEqual(events[0]["status"], "done")

    def test_completed_slot_is_not_reserved_again(self):
        h = hatchery(ml=30)
        events = t._tl(NOW, hatchery=h, brine_feeds=[{"at": stamp(), "ml": 30}])["events"]
        self.assertEqual(sorted(e["status"] for e in events), ["done", "due"])

    def test_phyto_direct_feed_waits_for_observed_density_and_health(self):
        for tint in ("pale", "green", "brown", "dark"):
            jar = c._phyto_jar(started_ago_days=10, now=NOW, lastTint=tint)
            jar["harvestTo"] = "tank"
            self.assertEqual(bool(pending(cultures={"jars": {"p": jar}})), tint == "dark")
        jar["state"].update(lastSign="foam", lastSignAt=stamp())
        self.assertEqual(pending(cultures={"jars": {"p": jar}}), [])

    def test_unhealthy_rotifers_are_not_recommended_as_tank_food(self):
        jar = c._jar(started_ago_days=10, now=NOW, lastTint="clearing", lastSign="smell", lastSignAt=stamp())
        jar["harvestTo"] = "tank"
        self.assertEqual(pending(cultures={"jars": {"r": jar}}), [])
        cfg = c._config(c._entry(jars={"r": jar}))
        products, sources = integration._nps_live_shelf(cfg, NOW)
        self.assertFalse(any(p.get("live", {}).get("vessel") == "cone" for p in products.values()))
        self.assertFalse(any("harvest into the bottle" in p["note"] for p in sources))

    def test_brine_handlers_reject_stale_unknown_and_soaking_before_mutating(self):
        now = datetime.now(timezone.utc)
        for vessel, age, soaking in (("container", 25, False), ("bottle", 49, False),
                                     ("container", -1, False), ("container", None, False),
                                     ("container", 1, True)):
            with self.subTest(vessel=vessel, age=age, soaking=soaking):
                entry = t._v2_entry()
                cfg = integration._config_from_entry(entry)
                h = integration._nps_hatchery_v2(cfg)
                target = h["reservoir" if vessel == "container" else "fridgeBottle"]
                target.update(remainingMl=100, mixedAt=stamp(age, now) if age is not None else "")
                if vessel == "bottle":
                    target["refrigeratedAt"] = target["mixedAt"]
                if soaking:
                    h["enrichment"]["state"].update(startedAt=stamp(1, now), batchLoadedAt=target["mixedAt"])
                entry.options[t.CONF_SETTINGS] = cfg
                before = deepcopy(entry.options)
                conn = FakeConnection()
                handler = integration.websocket_nps_hand_feed if vessel == "container" else integration.websocket_nps_fridge_bottle
                run(handler(FakeHass(entries=[entry]), conn, {"id": 1, **({"action": "feed"} if vessel == "bottle" else {})}))
                self.assertTrue(conn.errors)
                self.assertEqual(entry.options, before)

    def test_linked_culture_feed_cannot_consume_missing_empty_insufficient_or_expired_food(self):
        now = datetime.now(timezone.utc)
        for product in (None, {"remainingMl": 0}, {"remainingMl": 2},
                        {"remainingMl": 100, "shelfLifeDaysOpened": 1, "openedAt": stamp(25, now)}):
            with self.subTest(product=product):
                jar = c._jar(started_ago_days=10, now=now, lastTint="clearing")
                entry = c._entry(jars={"r": jar}, products={} if product is None else {"phyto": product})
                cfg = c._config(entry)
                before = deepcopy(cfg)
                error = integration._cultures_log_apply(FakeHass(), cfg, "r", fed=True)
                self.assertIsNotNone(error)
                self.assertEqual(cfg, before)
                conn = FakeConnection()
                run(integration.websocket_cultures_summary(FakeHass(entries=[entry]), conn, {"id": 1}))
                summary = conn.results[-1].payload["jars"][0]
                self.assertTrue(summary["feed"]["pauseReason"])
                self.assertNotEqual(summary["feedAdvice"]["action"], "feed_now")

    def test_enrichment_cannot_start_or_log_a_dose_from_unavailable_linked_food(self):
        now = datetime.now(timezone.utc)
        for product in (None, {"remainingMl": 0}, {"remainingMl": 0.01},
                        {"remainingMl": 20, "shelfLifeDaysOpened": 1, "openedAt": stamp(25, now)}):
            for phase in ("start", "first", "second", "rotifers"):
                with self.subTest(product=product, phase=phase):
                    entry = t._v2_entry(reservoir={"volumeMl": 750, "remainingMl": 300, "mixedAt": stamp(10, now)})
                    cfg = integration._config_from_entry(entry)
                    cfg["consumables"]["products"] = {} if product is None else {"enrich": product}
                    h = integration._nps_hatchery_v2(cfg)
                    h["enrichment"].update(productId="enrich", doseMl=1)
                    if phase in ("first", "second"):
                        h["enrichment"]["state"].update(startedAt=stamp(1, now), batchLoadedAt=h["reservoir"]["mixedAt"])
                        if phase == "second":
                            h["enrichment"]["state"]["firstDoseAt"] = stamp(1, now)
                    if phase == "rotifers":
                        cfg["nps"]["cultures"] = c._config(c._entry(jars={"r": c._jar(started_ago_days=10, now=now)}))["nps"]["cultures"]
                        cfg["nps"]["cultures"]["enrichment"]["productId"] = "enrich"
                    entry.options[t.CONF_SETTINGS] = cfg
                    before = deepcopy(cfg)
                    if phase == "start":
                        conn = FakeConnection()
                        run(integration.websocket_nps_hatch_enrich(FakeHass(entries=[entry]), conn, {"id": 1}))
                        self.assertTrue(conn.errors)
                        self.assertEqual(entry.options[t.CONF_SETTINGS], before)
                    else:
                        if phase == "rotifers":
                            error = integration._cultures_log_apply(FakeHass(), cfg, "r", harvested=True, enrich=True)
                        else:
                            handler = integration._nps_enrich_dose_apply if phase == "first" else integration._nps_enrich_second_dose_apply
                            error = handler(cfg, now)
                        self.assertEqual(error[0], "food_unavailable")
                        self.assertEqual(cfg, before)


if __name__ == "__main__":
    unittest.main()
