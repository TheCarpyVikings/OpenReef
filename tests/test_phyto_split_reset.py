"""Refilled phyto splits reset the cycle, including legacy sub-30% splits."""
from copy import deepcopy
from datetime import timedelta
from unittest import TestCase, main
from unittest.mock import patch

import test_cultures as t

C, I, NOW = t.cultures, t.integration, t.REAL


def stamp(days=0):
    return t._iso(NOW - timedelta(days=days))


def dark_jar():
    jar = t._phyto_jar(started_ago_days=7, now=NOW, lastTint="dark", workingL=3.5,
                       lastLookedAt=stamp(.01), cyclesSinceFresh=1, lastHarvestAt=stamp(7))
    jar["history"] = [{"event": "tint", "at": stamp(.01), "tint": "dark"},
                      {"event": "tint", "at": stamp(5.5), "tint": "dark"}]
    return jar


def legacy_jar():
    jar = dark_jar()
    jar["history"].insert(0, {"event": "harvest", "at": stamp(), "ml": 1000,
                               "freshMl": 1000, "nutrientMl": 1.5, "workingMl": 3500,
                               "draw": True, "tint": "dark",
                               "dests": [{"to": "bottle", "ml": 1000}]})
    jar["state"]["lastLookedAt"] = stamp()
    return jar


class PhytoSplitReset(TestCase):
    def test_refilled_splits_below_thirty_percent_reset_summary_and_reminder(self):
        for ml, nutrient in ((60, True), (1000, True), (1000, False), (1050, True)):
            with self.subTest(ml=ml, nutrient=nutrient):
                entry = t._phyto_entry(jars={"p": dark_jar()})
                cfg = t._config(entry)
                self.assertEqual(C.culture_state(cfg["nps"]["cultures"]["jars"]["p"], NOW)["darkDays"], 5.5)
                conn, hass = t.FakeConnection(), t.FakeHass(entries=[entry])
                with patch.object(I, "_mixing_hatchery_debit") as debit:
                    t.run(I.websocket_cultures_split(hass, conn, {
                        "id": 1, "jar_id": "p", "ml": ml, "fresh_ml": ml,
                        "to": [{"to": "bottle", "ml": ml}], "tint": "dark", "nutrient": nutrient,
                    }))
                    self.assertFalse(conn.errors)
                    self.assertEqual(debit.call_args.args[2], ml / 1000)
                cfg = t._config(entry)
                jar = cfg["nps"]["cultures"]["jars"]["p"]
                self.assertFalse(jar["history"][0].get("draw"))
                self.assertEqual(jar["state"]["lastHarvestAt"], jar["history"][0]["at"])
                self.assertEqual(jar["state"]["cyclesSinceFresh"], 2)
                self.assertEqual(jar["state"]["workingL"], 3.5)
                self.assertEqual(jar["state"]["lastTint"], "pale")
                self.assertEqual(cfg["consumables"]["products"]["home_phyto_p"]["remainingMl"], min(ml, 1000))
                summary = I._cultures_summary_payload(hass, cfg)
                tile = summary["jars"][0]
                self.assertEqual(tile["state"]["cycle"]["day"], 0)
                self.assertEqual(tile["state"]["darkDays"], 0)
                self.assertFalse(tile["state"]["peakHeld"])
                self.assertNotIn("harvest", tile["due"])
                self.assertNotEqual(tile["densityAdvice"]["action"], "split_now")
                self.assertNotIn("without a split", tile["risk"]["reason"])
                self.assertFalse(I._cultures_task_clock(cfg, "culture_p_harvest", NOW)["due"])

    def test_legacy_refilled_draw_repairs_once_without_replaying_stock(self):
        raw = {"jars": {"p": legacy_jar()}}
        before = deepcopy(raw)
        repaired = I._normalise_cultures(raw)
        self.assertEqual(raw, before, "normalisation must not mutate its input")
        jar = repaired["jars"]["p"]
        self.assertFalse(jar["history"][0].get("draw"))
        self.assertEqual(jar["state"]["lastHarvestAt"], stamp())
        self.assertEqual(jar["state"]["cyclesSinceFresh"], 2)
        self.assertEqual(jar["state"]["lastTint"], "pale")
        self.assertEqual(jar["history"][0]["tint"], "dark", "retain the observed harvest colour")
        self.assertEqual(I._normalise_cultures(repaired), repaired, "repeat reads cannot count the split twice")
        cfg = t._config(t._phyto_entry(jars={"p": legacy_jar()}))
        stock, station = deepcopy(cfg["consumables"]), deepcopy(cfg["mixingStation"])
        tile = I._cultures_summary_payload(t.FakeHass(), cfg)["jars"][0]
        self.assertEqual(tile["state"]["cycle"]["day"], 0)
        self.assertEqual(tile["state"]["darkDays"], 0)
        self.assertNotIn("harvest", tile["due"])
        self.assertEqual(cfg["consumables"], stock)
        self.assertEqual(cfg["mixingStation"], station)

    def test_legacy_repair_counts_multiple_refills_but_keeps_a_later_split(self):
        jar = legacy_jar()
        jar["history"][0]["at"] = stamp(2)
        jar["history"].insert(0, {**jar["history"][0], "at": stamp(1)})
        jar["history"].insert(0, {"event": "harvest", "at": stamp(), "ml": 2100,
                                 "freshMl": 2100, "tint": "dark"})
        jar["state"].update(lastHarvestAt=stamp(), lastTint="pale", cyclesSinceFresh=2)
        repaired = I._normalise_cultures({"jars": {"p": jar}})
        state = repaired["jars"]["p"]["state"]
        self.assertEqual(state["lastHarvestAt"], stamp())
        self.assertEqual(state["lastTint"], "pale")
        self.assertEqual(state["cyclesSinceFresh"], 4)
        self.assertEqual(I._normalise_cultures(repaired), repaired)
        stale = {"nps": {"cultures": {"jars": {"p": jar}}}}
        I._nps_preserve_runtime({"nps": {"cultures": repaired}}, stale)
        self.assertEqual(I._normalise_cultures(stale["nps"]["cultures"]), repaired)

    def test_legacy_repair_preserves_later_observations_and_fresh_vessel(self):
        for event in ("tint", "restart", "seeded"):
            with self.subTest(event=event):
                jar = legacy_jar()
                old_at = stamp(1)
                jar["history"][0]["at"] = old_at
                jar["history"].insert(0, {"event": event, "at": stamp(), "tint": "green"})
                jar["state"].update(lastTint="green", lastLookedAt=stamp())
                if event in ("restart", "seeded"):
                    jar["state"].update(lastRestartAt=stamp(), cyclesSinceFresh=0)
                    if event == "seeded":
                        jar["state"]["startedAt"] = stamp()
                repaired = I._normalise_cultures({"jars": {"p": jar}})["jars"]["p"]
                self.assertEqual(repaired["state"]["lastTint"], "green")
                self.assertEqual(repaired["state"]["cyclesSinceFresh"], 2 if event == "tint" else 0)

    def test_legacy_repair_ignores_no_refill_undone_invalid_and_future_rows(self):
        for changes in ({"freshMl": 0}, {"undoneAt": stamp()}, {"at": "bad"}, {"at": stamp(-1)}):
            with self.subTest(changes=changes):
                jar = legacy_jar()
                jar["history"][0].update(changes)
                repaired = I._normalise_cultures({"jars": {"p": jar}})["jars"]["p"]
                self.assertTrue(repaired["history"][0]["draw"])
                for field in ("lastHarvestAt", "cyclesSinceFresh", "lastTint"):
                    self.assertEqual(repaired["state"][field], jar["state"][field])

    def test_undoing_a_later_look_cannot_restore_pre_split_dark_colour(self):
        jar = dark_jar()
        jar["history"].insert(0, {"event": "harvest", "at": stamp(), "ml": 1000,
                                 "freshMl": 1000, "tint": "dark"})
        jar["state"].update(lastHarvestAt=stamp(), lastTint="pale")
        entry = t._phyto_entry(jars={"p": jar})
        conn, hass = t.FakeConnection(), t.FakeHass(entries=[entry])
        t.run(I.websocket_cultures_log(hass, conn, {"id": 1, "jar_id": "p", "tint": "green"}))
        at = t._cultures(entry)["jars"]["p"]["state"]["lastLookedAt"]
        t.run(I.websocket_cultures_undo(hass, conn, {"id": 2, "jar_id": "p", "at": at}))
        self.assertFalse(conn.errors)
        self.assertEqual(t._cultures(entry)["jars"]["p"]["state"]["lastTint"], "pale")


if __name__ == "__main__":
    main()
