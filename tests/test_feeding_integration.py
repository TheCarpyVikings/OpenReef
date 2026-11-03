"""Real feeding handlers with fake HA: inventory, archive and user corrections.

Run: python3 tests/test_feeding_integration.py
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

import test_nps as t
from _fake_ha import FakeConnection, FakeEntry, FakeHass, run

integration = t.integration
CONF_SETTINGS = integration.CONF_SETTINGS


class FeedingIntegration(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.slot = self.now.strftime("%H:%M")
        self.feed_at = self.now.isoformat()
        loaded = (self.now - timedelta(hours=2)).isoformat()
        self.cfg = integration._normalise_core_config({
            "tank": {"volumeLitres": 500},
            "nps": {"enabled": True, "hatchery": {
                "enabled": True,
                "reservoir": {"remainingMl": 2000, "volumeMl": 5000, "mixedAt": loaded},
                "fridgeBottle": {"remainingMl": 500, "volumeMl": 500, "mixedAt": loaded,
                                 "filledAt": loaded, "refrigeratedAt": loaded},
                "handFeed": {"defaultDoseMl": 250, "feedsPerDay": 1,
                             "windowStart": self.slot, "windowEnd": self.slot},
            }, "cultures": {"enabled": True, "bottle": {
                "remainingMl": 500, "volumeMl": 1000, "filledAt": loaded,
                "doseMl": 100, "feedsPerDay": 1, "windowStart": self.slot, "windowEnd": self.slot,
            }}},
            "consumables": {"products": {"phyto": t._product(
                openedAt=(self.now - timedelta(days=1)).isoformat(),
                remainingMl=1000, bottleMl=2000, doseMl=100,
                doseTimesPerDay=1, doseFirstAt=self.slot, doseWindowEnd=self.slot,
                lastDosedAt="", history=[],
            )}},
        })
        self.entry = FakeEntry(options={CONF_SETTINGS: self.cfg})
        self.hass = FakeHass(entries=[self.entry])
        self.next_id = 0

    def saved(self):
        return self.entry.options[CONF_SETTINGS]

    def call(self, api_name, *, error=None, **msg):
        self.next_id += 1
        connection = FakeConnection()
        run(getattr(integration, "websocket_" + api_name)(self.hass, connection, {"id": self.next_id, **msg}))
        if error is None:
            self.assertEqual(connection.errors, [], [(e.code, e.message) for e in connection.errors])
            self.assertTrue(connection.results, api_name + " should reply")
        else:
            self.assertTrue(connection.errors, api_name + " should reject")
            if error is not True:
                self.assertIn(error, connection.error_codes)
        return connection.results[-1].payload if connection.results else None

    def summary(self, days=1):
        return self.call("feeding_summary", days=days)

    def create_food(self, name="Vitalis flake", unit="pinch", portion=1, live=False):
        self.call("feeding_food_save", name=name, unit=unit, portion=portion, live=live)
        foods = self.saved()["feeding"]["foods"]
        key = next(fid for fid, food in foods.items() if food["name"] == name)
        return "manual:" + key

    def log(self, food, source=None, amount=1, **fields):
        return self.call("feeding_log", food_id=food, source_id=source or food, amount=amount, **fields)

    def total(self, result, food):
        return next(item for item in result["totals"] if item["foodId"] == food)

    def active(self, result, food):
        return [row for row in result["rows"] if row["foodId"] == food and not row["undone"]]

    def catalog_food(self, food):
        return next(item for item in self.summary()["foods"] if item["id"] == food)

    def add_shelf_product(self, product_id, **fields):
        product = deepcopy(self.saved()["consumables"]["products"]["phyto"])
        product.update({"name": product_id, "category": "other", "history": [], **fields})
        self.saved()["consumables"]["products"][product_id] = product
        return product

    def test_manual_food_two_same_time_feeds_keep_distinct_uuids_and_portions(self):
        food = self.create_food()
        at = (self.now - timedelta(days=2)).replace(second=0, microsecond=0).isoformat()
        self.log(food, amount=1, at=at)
        self.log(food, amount=2, at=at)
        result = self.summary(7)
        rows = self.active(result, food)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({row["id"] for row in rows}), 2)
        self.assertTrue(all(row["id"].startswith("manual:") for row in rows))
        self.assertEqual(self.total(result, food)["amount"], 3)
        self.assertEqual(self.total(result, food)["unit"], "pinch")
        self.assertFalse(self.active(self.summary(), food))

    def test_partial_brine_completes_slot_and_undo_reopens_it(self):
        self.log("brine", "brine:container", 100, at=self.feed_at, slot=self.slot)
        result = self.summary()
        self.assertEqual(self.total(result, "brine")["amount"], 100)
        self.assertFalse([p for p in result["planned"] if p["foodId"] == "brine"])
        row = self.active(result, "brine")[0]
        timeline_row = next(r for r in result["timelineRows"] if r["id"] == row["id"])
        self.assertTrue(timeline_row["editable"] and timeline_row["undoable"])
        self.assertEqual(timeline_row["at"], self.feed_at)
        self.assertEqual(row["plannedAmount"], 250)
        self.assertEqual(self.saved()["nps"]["hatchery"]["reservoir"]["remainingMl"], 1900)
        self.call("feeding_undo", entry_id=row["id"])
        after = self.summary()
        self.assertFalse(self.active(after, "brine"))
        self.assertFalse([r for r in after["timelineRows"] if r["foodId"] == "brine"])
        self.assertEqual(len([p for p in after["planned"] if p["foodId"] == "brine"]), 1)
        self.assertEqual(self.saved()["nps"]["hatchery"]["reservoir"]["remainingMl"], 2000)

    def test_explicit_extra_preserves_plan_and_shelf_cadence(self):
        for food, source in (("brine", "brine:container"), ("product:phyto", "shelf:phyto"),
                             ("rotifers", "cultures-bottle")):
            self.log(food, source, 50, at=self.feed_at, extra=True)
        result = self.summary()
        for food in ("brine", "product:phyto", "rotifers"):
            self.assertEqual(self.total(result, food)["amount"], 50)
            self.assertEqual(len([p for p in result["planned"] if p["foodId"] == food]), 1)
            self.assertTrue(self.active(result, food)[0]["extra"])
        self.assertEqual(self.saved()["consumables"]["products"]["phyto"]["lastDosedAt"], "")

    def test_each_source_debits_only_its_inventory(self):
        self.log("brine", "brine:container", 100, extra=True)
        self.log("brine", "brine:bottle", 50, extra=True)
        self.log("rotifers", "cultures-bottle", 40, extra=True)
        self.log("product:phyto", "shelf:phyto", 10, extra=True)
        saved = self.saved()
        self.assertEqual(saved["nps"]["hatchery"]["reservoir"]["remainingMl"], 1900)
        self.assertEqual(saved["nps"]["hatchery"]["fridgeBottle"]["remainingMl"], 450)
        self.assertEqual(saved["nps"]["cultures"]["bottle"]["remainingMl"], 460)
        self.assertEqual(saved["consumables"]["products"]["phyto"]["remainingMl"], 990)
        self.assertEqual(self.total(self.summary(), "brine")["amount"], 150)
        self.assertFalse([call for call in self.hass.services.calls
                          if call.domain != "persistent_notification"], "logging must not operate a pump")

    def test_undo_reloaded_source_does_not_credit_new_batch(self):
        self.log("brine", "brine:container", 100, at=self.feed_at, extra=True)
        row = self.active(self.summary(), "brine")[0]
        vessel = self.saved()["nps"]["hatchery"]["reservoir"]
        vessel.update(mixedAt=datetime.now(timezone.utc).isoformat(), remainingMl=1700)
        self.call("feeding_undo", entry_id=row["id"])
        self.assertEqual(self.saved()["nps"]["hatchery"]["reservoir"]["remainingMl"], 1700)
        self.assertFalse(self.active(self.summary(), "brine"))

    def test_manual_edit_keeps_id_and_changes_actual_day_without_duplicate(self):
        food = self.create_food()
        self.log(food, amount=1, at=self.feed_at)
        original = self.active(self.summary(), food)[0]
        yesterday = (self.now - timedelta(days=1)).isoformat()
        self.call("feeding_edit", entry_id=original["id"], amount=3, at=yesterday)
        self.assertFalse(self.active(self.summary(), food))
        week = self.summary(7)
        rows = self.active(week, food)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], original["id"])
        self.assertEqual(rows[0]["at"], yesterday)
        self.assertEqual(self.total(week, food)["amount"], 3)

    def test_stock_edit_amount_and_time_never_reimports_previous_feed(self):
        self.log("brine", "brine:container", 100, at=self.feed_at, extra=True)
        row = self.active(self.summary(), "brine")[0]
        changed_at = self.now.replace(second=0, microsecond=0).isoformat()
        self.call("feeding_edit", entry_id=row["id"], amount=75, at=changed_at)
        for _ in range(2):
            result = self.summary()
            self.assertEqual(len(self.active(result, "brine")), 1)
            self.assertEqual(self.total(result, "brine")["amount"], 75)
        self.assertEqual(self.saved()["nps"]["hatchery"]["reservoir"]["remainingMl"], 1925)
        changed = self.active(result, "brine")[0]
        self.call("feeding_undo", entry_id=changed["id"])
        self.assertEqual(self.saved()["nps"]["hatchery"]["reservoir"]["remainingMl"], 2000)

    def test_stale_whole_config_preserves_archive_foods_and_undo(self):
        stale = deepcopy(self.saved())
        food = self.create_food()
        self.log(food, amount=2)
        row = self.active(self.summary(), food)[0]
        self.call("feeding_undo", entry_id=row["id"])
        expected = deepcopy(self.saved()["feeding"])
        integration._nps_preserve_runtime(self.saved(), stale)
        self.assertEqual(stale["feeding"], expected)
        run(integration._async_save_config(self.hass, self.entry, stale))
        self.assertFalse(self.active(self.summary(), food))
        self.assertIn(food[7:], self.saved()["feeding"]["foods"])

    def test_archive_retains_shelf_rows_after_legacy_fifty_row_eviction(self):
        history = [{"at": (self.now - timedelta(hours=3, minutes=i)).isoformat(),
                    "ml": 1, "kind": "dose", "to": "tank"} for i in range(50)]
        history.sort(key=lambda r: r["at"])
        first_stamp = history[0]["at"]
        self.saved()["consumables"]["products"]["phyto"]["history"] = history
        for _ in range(5):
            self.call("consumable_log_dose", product_id="phyto", ml=1)
        self.assertEqual(len(self.saved()["consumables"]["products"]["phyto"]["history"]), 50)
        result = self.summary(7)
        self.assertEqual(self.total(result, "product:phyto")["feeds"], 55)
        self.assertEqual(self.total(result, "product:phyto")["amount"], 55)
        self.assertTrue(any(r["at"] == first_stamp for r in result["rows"]))

    def test_summary_display_cap_does_not_limit_actual_totals(self):
        self.saved()["feeding"]["rows"] = [{
            "id": "imported-" + str(i), "at": (self.now - timedelta(seconds=i + 1)).isoformat(),
            "source": "brine", "sourceId": "brine:container", "foodId": "brine",
            "name": "Live brine", "unit": "ml", "amount": 10, "ml": 10,
            "live": True, "liveKnown": True, "how": "hand",
        } for i in range(400)]
        result = self.summary(7)
        self.assertEqual(len(result["rows"]), 300)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["counts"]["feeds"], 400)
        self.assertEqual(result["rowCount"], 400)
        self.assertEqual(self.total(result, "brine")["amount"], 4000)

    def test_live_liquid_percent_uses_configured_tank_volume(self):
        food = self.create_food("Live feed", "ml", 100, True)
        self.log(food, amount=5000)
        result = self.summary()
        self.assertEqual(result["tankLitres"], 500)
        self.assertEqual(result["liveVolumePct"], 1)
        self.assertEqual(self.total(result, food)["tankVolumePct"], 1)
        self.saved()["tank"]["volumeLitres"] = 52
        result = self.summary()
        self.assertEqual(result["liveVolumePct"], 9.615)
        self.assertEqual(self.total(result, food)["tankVolumePct"], 9.615)

    def test_summary_is_read_only_and_does_not_call_services(self):
        before = deepcopy(self.saved())
        self.summary(30)
        self.assertEqual(self.saved(), before)
        self.assertEqual(self.hass.services.calls, [])

    def test_invalid_amounts_units_future_and_naive_times_are_rejected(self):
        for unit in ("bucket", "", "millilitres"):
            self.call("feeding_food_save", name="Bad", unit=unit, portion=1, error="invalid_food")
        food = self.create_food()
        before = deepcopy(self.saved())
        for amount in (float("nan"), float("inf"), -1, 0, True):
            self.call("feeding_log", food_id=food, source_id=food, amount=amount, error="invalid_feed")
        for at in ((self.now + timedelta(days=1)).isoformat(), self.now.replace(tzinfo=None).isoformat(), "bad"):
            self.call("feeding_log", food_id=food, source_id=food, amount=1, at=at, error="bad_stamp")
        self.call("feeding_log", food_id="brine", source_id="shelf:phyto", amount=1, error="invalid_feed")
        self.assertEqual(self.saved(), before)

    def test_backdated_shelf_extra_marks_the_inserted_row_not_latest_row(self):
        self.log("product:phyto", "shelf:phyto", 100, at=self.feed_at, slot=self.slot)
        early = (self.now - timedelta(minutes=10)).isoformat()
        self.log("product:phyto", "shelf:phyto", 25, at=early, extra=True)
        history = self.saved()["consumables"]["products"]["phyto"]["history"]
        planned = next(r for r in history if r["at"] == self.feed_at)
        extra = next(r for r in history if r["at"] == early)
        self.assertFalse(planned.get("extra", False))
        self.assertTrue(extra.get("extra"))
        self.assertFalse([p for p in self.summary()["planned"] if p["foodId"] == "product:phyto"])

    def test_feeds_before_current_stock_batch_are_rejected_without_debit(self):
        self.saved()["consumables"]["products"]["phyto"]["openedAt"] = (
            self.now - timedelta(hours=2)).isoformat()
        before = deepcopy(self.saved())
        at = (self.now - timedelta(hours=3)).isoformat()
        for food, source in (("brine", "brine:container"), ("brine", "brine:bottle"),
                             ("rotifers", "cultures-bottle"), ("product:phyto", "shelf:phyto")):
            self.call("feeding_log", food_id=food, source_id=source, amount=25,
                      at=at, extra=True, error="batch_mismatch")
        self.assertEqual(self.saved(), before)

    def test_native_same_time_taps_remain_distinct_including_both_brine_sources(self):
        for source in ("brine:container", "brine:container", "brine:bottle"):
            self.log("brine", source, 25, at=self.feed_at, extra=True)
        result = self.summary()
        rows = self.active(result, "brine")
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({r["id"] for r in rows}), 3)
        self.assertEqual(self.total(result, "brine")["amount"], 75)
        self.assertEqual(self.saved()["nps"]["hatchery"]["reservoir"]["remainingMl"], 1950)
        self.assertEqual(self.saved()["nps"]["hatchery"]["fridgeBottle"]["remainingMl"], 475)

    def test_native_time_edit_cannot_collide_with_other_brine_source(self):
        earlier = (self.now - timedelta(minutes=1)).isoformat()
        self.log("brine", "brine:container", 100, at=self.feed_at, extra=True)
        self.log("brine", "brine:bottle", 25, at=earlier, extra=True)
        bottle_row = next(r for r in self.active(self.summary(7), "brine")
                          if r["sourceId"] == "brine:bottle")
        self.call("feeding_edit", entry_id=bottle_row["id"], amount=25, at=self.feed_at)
        result = self.summary(7)
        rows = self.active(result, "brine")
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({r["id"] for r in rows}), 2)
        self.assertEqual(self.total(result, "brine")["amount"], 125)

    def test_catalog_rename_does_not_rewrite_archived_native_food_label(self):
        self.call("consumable_log_dose", product_id="phyto", ml=25)
        before = self.active(self.summary(), "product:phyto")[0]
        self.saved()["consumables"]["products"]["phyto"]["name"] = "Renamed future bottle"
        after = self.active(self.summary(), "product:phyto")[0]
        self.assertEqual(after["id"], before["id"])
        self.assertEqual(after["name"], before["name"])
        self.assertEqual(after["amount"], 25)

    def test_live_classification_does_not_freeze_running_drip_amount(self):
        channel = t._drip_channel(reservoir={"productId": "phyto"},
                                  driver={"entities": {"dosedTodaySensor": "sensor.drip_today"}})
        self.saved()["dosing"]["channels"] = {"drip": channel}
        self.hass.states.set("sensor.drip_today", "100")
        self.call("feeding_food_save", food_id="product:phyto", name="Phyto",
                  unit="ml", portion=100, live=True)
        first = self.summary()
        self.assertEqual(self.total(first, "product:phyto")["amount"], 100)
        self.hass.states.set("sensor.drip_today", "200")
        second = self.summary()
        self.assertEqual(self.total(second, "product:phyto")["amount"], 200)
        self.assertEqual(second["liveLiquidMl"], 200)
        self.assertEqual(len(self.active(second, "product:phyto")), 1)
        daily = [row for row in second["timelineRows"] if row["foodId"] == "product:phyto"]
        self.assertEqual(len(daily), 1)
        self.assertTrue(daily[0]["drip"])
        self.assertEqual(daily[0]["amount"], 200)
        self.assertFalse(daily[0]["editable"] or daily[0]["undoable"])
        context = second["timelineContext"]
        self.assertEqual(context["date"], second["date"])
        self.assertTrue(any(event["source"] == "channel:drip" for event in context["events"]))
        self.assertTrue(all(event["how"] in ("pump", "system") for event in context["events"]))

    def test_anytime_plan_can_complete_with_smaller_amount_and_undo(self):
        hand = self.saved()["nps"]["hatchery"]["handFeed"]
        hand.update(windowStart="", windowEnd="", feedsPerDay=1)
        plans = [p for p in self.summary()["planned"] if p["foodId"] == "brine"]
        self.assertEqual(len(plans), 1)
        self.assertIsNone(plans[0]["at"])
        self.log("brine", "brine:container", 100, slot="anytime")
        result = self.summary()
        self.assertFalse([p for p in result["planned"] if p["foodId"] == "brine"])
        row = self.active(result, "brine")[0]
        self.assertFalse(row["extra"])
        self.assertEqual(row["plannedAmount"], 250)
        self.call("feeding_undo", entry_id=row["id"])
        reopened = [p for p in self.summary()["planned"] if p["foodId"] == "brine"]
        self.assertEqual(len(reopened), 1)
        self.assertIsNone(reopened[0]["at"])
        self.assertEqual(self.saved()["nps"]["hatchery"]["reservoir"]["remainingMl"], 2000)

    def test_stale_background_saves_preserve_new_foods_and_native_preferences(self):
        stale_async = deepcopy(self.saved())
        stale_sync = deepcopy(self.saved())
        food = self.create_food()
        self.call("feeding_food_save", food_id="product:phyto", name="Phyto",
                  unit="ml", portion=300, live=True)
        expected_foods = deepcopy(self.saved()["feeding"]["foods"])
        expected_preferences = deepcopy(self.saved()["feeding"]["preferences"])
        run(integration._async_save_config(self.hass, self.entry, stale_async))
        self.assertEqual(self.saved()["feeding"]["foods"], expected_foods)
        self.assertEqual(self.saved()["feeding"]["preferences"], expected_preferences)
        integration._persist_entry_config(self.hass, self.entry, stale_sync)
        self.assertEqual(self.saved()["feeding"]["foods"], expected_foods)
        self.assertEqual(self.saved()["feeding"]["preferences"], expected_preferences)
        self.assertIn(food[7:], self.saved()["feeding"]["foods"])

    def busy_shelf(self):
        history = [{"at": (self.now - timedelta(minutes=i)).isoformat(),
                    "ml": 1, "kind": "dose", "to": "tank"}
                   for i in range(50, 0, -1)]
        product = self.saved()["consumables"]["products"]["phyto"]
        product.update(history=history, lastDosedAt=history[-1]["at"], remainingMl=1000)
        return (self.now - timedelta(hours=2)).isoformat()

    def test_backdated_feed_older_than_fifty_rows_remains_editable_and_undoable(self):
        at = self.busy_shelf()
        self.log("product:phyto", "shelf:phyto", 25, at=at, extra=True)
        result = self.summary(7)
        self.assertEqual(self.total(result, "product:phyto")["feeds"], 51)
        self.assertEqual(self.total(result, "product:phyto")["amount"], 75)
        row = next(r for r in self.active(result, "product:phyto") if r["at"] == at)
        self.assertTrue(row["editable"])
        self.assertTrue(row["undoable"])
        product = self.saved()["consumables"]["products"]["phyto"]
        self.assertEqual(len(product["history"]), 50)
        native = next(r for r in product["history"] if r["at"] == at)
        self.assertTrue(native["extra"])
        self.assertTrue(native["recordedAt"])
        self.assertEqual(product["remainingMl"], 975)

        self.call("feeding_edit", entry_id=row["id"], amount=15)
        edited = self.summary(7)
        self.assertEqual(self.total(edited, "product:phyto")["feeds"], 51)
        self.assertEqual(self.total(edited, "product:phyto")["amount"], 65)
        self.assertEqual(len([r for r in self.active(edited, "product:phyto") if r["at"] == at]), 1)
        self.assertEqual(self.saved()["consumables"]["products"]["phyto"]["remainingMl"], 985)

        self.call("feeding_undo", entry_id=row["id"])
        undone = self.summary(7)
        self.assertEqual(self.total(undone, "product:phyto")["feeds"], 50)
        self.assertEqual(self.total(undone, "product:phyto")["amount"], 50)
        self.assertEqual(len([r for r in undone["rows"] if r["at"] == at and r["undone"]]), 1)
        self.assertEqual(self.saved()["consumables"]["products"]["phyto"]["remainingMl"], 1000)

    def test_stale_settings_save_preserves_backdated_shelf_writes_by_recorded_at(self):
        at = self.busy_shelf()
        stale = deepcopy(self.saved())
        latest_old_at = max(r["at"] for r in stale["consumables"]["products"]["phyto"]["history"])
        self.log("product:phyto", "shelf:phyto", 25, at=at, extra=True)
        native = next(r for r in self.saved()["consumables"]["products"]["phyto"]["history"] if r["at"] == at)
        self.assertLess(native["at"], latest_old_at)
        self.assertGreater(native["recordedAt"], latest_old_at)
        self.call("save_config", config=stale)
        product = self.saved()["consumables"]["products"]["phyto"]
        self.assertEqual(product["remainingMl"], 975)
        self.assertEqual(len([r for r in product["history"] if r["at"] == at]), 1)
        result = self.summary(7)
        self.assertEqual(self.total(result, "product:phyto")["amount"], 75)
        row = next(r for r in self.active(result, "product:phyto") if r["at"] == at)

        stale_before_edit = deepcopy(self.saved())
        self.call("feeding_edit", entry_id=row["id"], amount=10)
        self.call("save_config", config=stale_before_edit)
        product = self.saved()["consumables"]["products"]["phyto"]
        self.assertEqual(product["remainingMl"], 990)
        native = next(r for r in product["history"] if r["at"] == at)
        self.assertEqual(native["ml"], 10)
        final = self.summary(7)
        self.assertEqual(self.total(final, "product:phyto")["feeds"], 51)
        self.assertEqual(self.total(final, "product:phyto")["amount"], 60)

    def test_small_remaining_stock_allows_smaller_actual_portion(self):
        product = self.saved()["consumables"]["products"]["phyto"]
        product.update(remainingMl=1, doseMl=2)
        food = next(f for f in self.summary()["foods"] if f["id"] == "product:phyto")
        self.assertEqual(food["portion"], 2)
        self.assertTrue(next(s for s in food["sources"] if s["id"] == "shelf:phyto")["available"])
        self.call("feeding_log", food_id="product:phyto", source_id="shelf:phyto",
                  amount=2, extra=True, error="food_unavailable")
        self.assertEqual(self.saved()["consumables"]["products"]["phyto"]["remainingMl"], 1)
        self.log("product:phyto", "shelf:phyto", 1, extra=True)
        self.assertEqual(self.saved()["consumables"]["products"]["phyto"]["remainingMl"], 0)
        self.assertEqual(self.total(self.summary(), "product:phyto")["amount"], 1)

    def test_nutrients_and_enrichment_cannot_be_enabled_or_logged_as_tank_food(self):
        cases = {
            "named_f2": {"name": "Guillard’s F / 2 fertiliser"},
            "linked_nutrient": {},
            "enrichment_category": {"category": "enrichment"},
            "hatchery_soak": {},
            "culture_soak": {},
        }
        for pid, fields in cases.items():
            self.add_shelf_product(pid, **fields)
        self.saved()["nps"]["cultures"]["jars"] = {
            "algae": {"species": "nanno", "nutrient": {"productId": "linked_nutrient"}},
        }
        self.saved()["nps"]["hatchery"]["enrichment"]["productId"] = "hatchery_soak"
        self.saved()["nps"]["cultures"]["enrichment"]["productId"] = "culture_soak"

        for pid in cases:
            with self.subTest(product=pid):
                fid = "product:" + pid
                # A stale stored preference must not defeat a newly linked
                # nutrient or enrichment restriction.
                self.saved()["feeding"]["preferences"][fid] = {"tankFeed": True}
                food = self.catalog_food(fid)
                self.assertFalse(food["tankFeed"])
                self.assertTrue(food["tankFeedLocked"])
                self.assertTrue(food["tankFeedReason"])
                source = next(s for s in food["sources"] if s["id"] == "shelf:" + pid)
                self.assertFalse(source["loggable"])
                self.assertFalse(source["available"])
                before = deepcopy(self.saved())
                self.call("feeding_food_save", food_id=fid, name=food["name"],
                          unit="ml", portion=1, tank_feed=True, error="not_tank_food")
                self.call("feeding_log", food_id=fid, source_id=source["id"],
                          amount=1, extra=True, error="not_tank_food")
                self.assertEqual(self.saved(), before)

    def test_culture_feed_presets_and_linked_supply_require_explicit_dual_use(self):
        for pid, name in (("rotifer_food", "Rotifer Feed Concentrate"),
                          ("pod_food", "Copepod Feed")):
            preset = next(p for p in t.nps.PRODUCT_LIBRARY if p["name"] == name)
            self.add_shelf_product(pid, name=name, brand=preset["brand"])
        self.add_shelf_product("custom_jar_food")
        self.saved()["nps"]["cultures"]["jars"] = {
            "animals": {"species": "rotifer_L", "feed": {"productId": "custom_jar_food"}},
        }
        for pid in ("rotifer_food", "pod_food", "custom_jar_food"):
            with self.subTest(product=pid):
                fid, source_id = "product:" + pid, "shelf:" + pid
                food = self.catalog_food(fid)
                self.assertFalse(food["tankFeed"])
                self.assertFalse(food["tankFeedLocked"])
                self.assertTrue(food["tankFeedReason"])
                self.assertFalse(food["sources"][0]["available"])
                before = deepcopy(self.saved())
                self.call("feeding_log", food_id=fid, source_id=source_id,
                          amount=5, extra=True, error="not_tank_food")
                self.assertEqual(self.saved(), before)
                self.call("feeding_food_save", food_id=fid, name=food["name"],
                          unit="ml", portion=5, tank_feed=True)
                enabled = self.catalog_food(fid)
                self.assertTrue(enabled["tankFeed"])
                self.assertTrue(enabled["sources"][0]["available"])
                self.assertTrue(self.saved()["feeding"]["preferences"][fid]["tankFeed"])
                self.log(fid, source_id, 5, extra=True)
                self.assertEqual(self.total(self.summary(), fid)["amount"], 5)
                self.assertEqual(self.saved()["consumables"]["products"][pid]["remainingMl"], 995)

    def test_home_phyto_bottle_remains_tank_food_when_also_used_for_cultures(self):
        self.add_shelf_product("my_home_bottle", category="phyto")
        self.saved()["nps"]["cultures"]["jars"] = {
            "algae": {"species": "nanno", "bottleProductId": "my_home_bottle"},
            "animals": {"species": "rotifer_L", "feed": {"productId": "my_home_bottle"}},
        }
        food = self.catalog_food("phyto:nanno")
        source = next(s for s in food["sources"] if s["id"] == "shelf:my_home_bottle")
        self.assertTrue(food["tankFeed"])
        self.assertFalse(food["tankFeedLocked"])
        self.assertTrue(source["available"])
        self.log(food["id"], source["id"], 20, extra=True)
        self.assertEqual(self.total(self.summary(), food["id"])["amount"], 20)
        self.assertEqual(self.saved()["consumables"]["products"]["my_home_bottle"]["remainingMl"], 980)

    def test_excluding_supply_keeps_actual_tank_history_and_undo_but_not_culture_uses(self):
        self.add_shelf_product("shared_supply")
        fid = "product:shared_supply"
        self.log(fid, "shelf:shared_supply", 25, extra=True)
        recorded = self.active(self.summary(), fid)[0]
        product = self.saved()["consumables"]["products"]["shared_supply"]
        product["history"].extend([
            {"at": (self.now - timedelta(minutes=2)).isoformat(), "ml": 3,
             "kind": "dose", "to": "jar", "jarId": "algae"},
            {"at": (self.now - timedelta(minutes=1)).isoformat(), "ml": 7,
             "kind": "dose", "to": "soak"},
        ])
        product["remainingMl"] -= 10
        self.saved()["nps"]["cultures"]["jars"] = {
            "algae": {"species": "nanno", "nutrient": {"productId": "shared_supply"}},
        }
        result = self.summary()
        self.assertFalse(next(f for f in result["foods"] if f["id"] == fid)["tankFeed"])
        rows = self.active(result, fid)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], recorded["id"])
        self.assertTrue(rows[0]["undoable"])
        self.assertEqual(self.total(result, fid)["amount"], 25)
        self.call("feeding_undo", entry_id=recorded["id"])
        self.assertFalse(self.active(self.summary(), fid))
        product = self.saved()["consumables"]["products"]["shared_supply"]
        self.assertEqual(product["remainingMl"], 990)
        self.assertEqual(len([r for r in product["history"] if r.get("to") in ("jar", "soak")]), 2)

    def test_manual_food_tank_use_opt_out_and_back_in_retains_prior_history(self):
        fid = self.create_food()
        self.log(fid, amount=1)
        first = self.active(self.summary(), fid)[0]
        self.call("feeding_food_save", food_id=fid, name="Vitalis flake", unit="pinch",
                  portion=1, tank_feed=False)
        food = self.catalog_food(fid)
        self.assertFalse(food["tankFeed"])
        self.assertFalse(food["tankFeedLocked"])
        self.assertFalse(food["sources"][0]["loggable"])
        before = deepcopy(self.saved())
        self.call("feeding_log", food_id=fid, source_id=fid, amount=1, error="not_tank_food")
        self.assertEqual(self.saved(), before)
        self.assertEqual(self.total(self.summary(), fid)["amount"], 1)
        self.assertTrue(self.active(self.summary(), fid)[0]["undoable"])
        self.call("feeding_food_save", food_id=fid, name="Vitalis flake", unit="pinch",
                  portion=1, tank_feed=True)
        self.assertTrue(self.catalog_food(fid)["sources"][0]["available"])
        self.log(fid, amount=2)
        self.assertEqual(self.total(self.summary(), fid)["amount"], 3)
        self.call("feeding_undo", entry_id=first["id"])
        self.assertEqual(self.total(self.summary(), fid)["amount"], 2)

    def test_tank_use_preferences_survive_normalisation_and_stale_settings_saves(self):
        self.add_shelf_product("custom_jar_food")
        self.saved()["nps"]["cultures"]["jars"] = {
            "animals": {"species": "rotifer_L", "feed": {"productId": "custom_jar_food"}},
        }
        manual = self.create_food()
        stale_settings = deepcopy(self.saved())
        stale_background = deepcopy(self.saved())
        self.call("feeding_food_save", food_id="product:custom_jar_food", name="Custom jar food",
                  unit="ml", portion=5, tank_feed=True)
        self.call("feeding_food_save", food_id=manual, name="Vitalis flake", unit="pinch",
                  portion=1, tank_feed=False)
        expected = deepcopy(self.saved()["feeding"]["preferences"])
        self.call("save_config", config=stale_settings)
        run(integration._async_save_config(self.hass, self.entry, stale_background))
        self.assertEqual(self.saved()["feeding"]["preferences"], expected)
        self.assertTrue(self.catalog_food("product:custom_jar_food")["tankFeed"])
        self.assertFalse(self.catalog_food(manual)["tankFeed"])

    def test_preset_use_migrates_and_survives_stale_settings_without_metadata(self):
        expected = {}
        for index, name in enumerate(("Phytoplankton Nutrient (Guillard's f/2)",
                                      "Rotifer Feed Concentrate", "Copepod Feed")):
            preset = next(p for p in t.nps.PRODUCT_LIBRARY if p["name"] == name)
            for variant in ("omitted", "renamed"):
                pid = f"old_preset_{index}_{variant}"
                product = self.add_shelf_product(pid, name=name, brand=preset["brand"])
                self.assertNotIn("feedingUse", product)
                expected[pid] = preset["feedingUse"]

        stale = deepcopy(self.saved())
        normalised = integration._normalise_core_config(deepcopy(self.saved()))
        for pid, role in expected.items():
            self.assertEqual(normalised["consumables"]["products"][pid]["feedingUse"], role)
            if pid.endswith("renamed"):
                stale["consumables"]["products"][pid].update(name="My renamed supply", brand="My label")

        # The stored and incoming snapshots both predate feedingUse. Keeping
        # a known role must also work during the first save after upgrading.
        self.call("save_config", config=stale)
        for pid, role in expected.items():
            with self.subTest(product=pid):
                product = self.saved()["consumables"]["products"][pid]
                self.assertEqual(product["feedingUse"], role)
                if pid.endswith("renamed"):
                    self.assertEqual(product["name"], "My renamed supply")
                    self.assertEqual(product["brand"], "My label")
                food = self.catalog_food("product:" + pid)
                self.assertFalse(food["tankFeed"])
                self.assertEqual(food["tankFeedLocked"], role == "culture_nutrient")
                self.assertFalse(food["sources"][0]["available"])

        # Repeating the old Settings save cannot remove the now-persisted role.
        self.call("save_config", config=stale)
        for pid, role in expected.items():
            self.assertEqual(self.saved()["consumables"]["products"][pid]["feedingUse"], role)
            self.assertFalse(self.catalog_food("product:" + pid)["tankFeed"])

    def test_portion_and_tank_use_edits_without_live_preserve_classification_and_history(self):
        manual = self.create_food("My live culture", "ml", 10, True)
        native = "product:phyto"
        self.assertFalse(self.catalog_food(native)["liveKnown"])
        self.log(manual, amount=10)
        self.log(native, "shelf:phyto", 7, extra=True)
        before = {r["id"]: deepcopy(r) for r in self.saved()["feeding"]["rows"]
                  if r["foodId"] in (manual, native)}
        self.assertEqual(len(before), 2)
        manual_row = next(r for r in before.values() if r["foodId"] == manual)
        native_row = next(r for r in before.values() if r["foodId"] == native)
        self.assertTrue(manual_row["live"])
        self.assertTrue(manual_row["liveKnown"])
        self.assertFalse(native_row["liveKnown"])

        for fid in (manual, native):
            for tank_feed, portion in ((False, 20), (True, 30)):
                with self.subTest(food=fid, tank_feed=tank_feed):
                    food = self.catalog_food(fid)
                    self.call("feeding_food_save", food_id=fid, name=food["name"],
                              unit="ml", portion=portion, tank_feed=tank_feed)
                    after = {r["id"]: r for r in self.saved()["feeding"]["rows"]
                             if r["foodId"] in (manual, native)}
                    # Exact retained rows also verify updatedAt is untouched;
                    # changing availability or a usual portion is not a
                    # retrospective correction of live-food classification.
                    self.assertEqual(after, before)
                    updated = self.catalog_food(fid)
                    self.assertEqual(updated["tankFeed"], tank_feed)
                    self.assertEqual(updated["portion"], portion)
                    self.assertTrue(self.saved()["feeding"]["foods"][manual[7:]]["live"])
                    self.assertTrue(self.catalog_food(manual)["live"])
                    self.assertFalse(self.catalog_food(native)["liveKnown"])
        self.assertNotIn("live", self.saved()["feeding"]["preferences"][native])


if __name__ == "__main__":
    unittest.main()
