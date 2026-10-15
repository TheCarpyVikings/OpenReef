"""Observed phyto readiness and measured animal-culture water care (fake HA)."""
from copy import deepcopy
from datetime import timedelta
from unittest import TestCase, main
from unittest.mock import patch

import test_cultures as t

C, I, NOW = t.cultures, t.integration, t.REAL


class CultureCare(TestCase):
    def test_only_a_recent_dark_observation_recommends_a_split(self):
        for tint in ("", "pale", "green", "dark", "off"):
            for age_h in (1, 23.9, 24, 72):
                with self.subTest(tint=tint, age_h=age_h):
                    at = t._iso(NOW - timedelta(hours=age_h))
                    jar = t._phyto_jar(started_ago_days=9, now=NOW, lastTint=tint, lastLookedAt=at)
                    jar["history"] = [{"event": "tint", "tint": tint, "at": at}]
                    state = C.culture_state(jar, NOW)
                    ready = tint == "dark" and age_h < 24
                    self.assertEqual(state["harvest"]["due"], ready)
                    self.assertEqual(state["splitReady"], ready)
                    self.assertEqual(C.density_advice(tint, state)["action"] == "split_now", ready)
                    if not ready:
                        self.assertIsNone(state["harvest"]["at"])
                        self.assertNotEqual(state["nextChore"]["key"], "harvest")

    def test_measurement_does_not_refresh_stale_colour_and_sign_blocks_dark(self):
        jar = t._phyto_jar(started_ago_days=9, now=NOW, lastTint="dark", lastLookedAt=t._iso(NOW))
        jar["history"] = [{"event": "tint", "tint": "dark", "at": t._iso(NOW - timedelta(days=2))},
                          {"event": "index", "od": 2, "at": t._iso(NOW)}]
        state = C.culture_state(jar, NOW)
        self.assertFalse(state["harvest"]["due"])
        self.assertTrue(state["look"]["due"])
        jar["history"] = [{"event": "tint", "tint": "dark", "at": t._iso(NOW - timedelta(hours=1))}]
        jar["state"].update(lastSign="foam", lastSignAt=t._iso(NOW))
        state = C.culture_state(jar, NOW)
        self.assertFalse(state["harvest"]["due"])
        self.assertEqual(C.density_advice("dark", state)["action"], "hold")

    def test_missing_future_and_undone_colour_cannot_certify_readiness(self):
        for history in ([], [{"event": "tint", "tint": "dark", "at": t._iso(NOW + timedelta(hours=1))}],
                        [{"event": "tint", "tint": "dark", "at": t._iso(NOW), "undoneAt": t._iso(NOW)}]):
            jar = t._phyto_jar(started_ago_days=9, now=NOW, lastTint="dark", lastLookedAt="")
            jar["history"] = history
            state = C.culture_state(jar, NOW)
            self.assertFalse(state["harvest"]["due"])
            self.assertEqual(C.density_advice("dark", state)["action"], "check")

    def test_green_day_nine_is_consistent_in_summary_reminder_and_push(self):
        entry = t._phyto_entry(jars={"p": t._phyto_jar(started_ago_days=9, now=NOW, lastTint="green")})
        cfg = t._config(entry)
        summary = I._cultures_summary_payload(t.FakeHass(), cfg)
        jar = summary["jars"][0]
        self.assertNotIn("harvest", jar["due"])
        self.assertEqual(jar["densityAdvice"], jar["feedAdvice"])
        self.assertEqual(jar["densityAdvice"]["action"], "wait")
        self.assertNotIn("~0 d", jar["densityAdvice"]["reason"])
        self.assertEqual(summary["dueCount"], 0)
        self.assertFalse(I._cultures_task_clock(cfg, "culture_p_harvest", NOW)["due"])
        self.assertEqual(I._cultures_push_plan(summary), [])

    def test_index_estimate_cannot_override_a_green_observation(self):
        entry = t._phyto_entry(jars={"p": t._phyto_jar(started_ago_days=9, now=NOW, lastTint="green")})
        cfg = t._config(entry)
        learned = C.learned_cadences(cfg["nps"]["cultures"]["jars"]["p"], [], NOW)
        learned["index"] = {"readsDark": True, "lastOd": 1, "darkOd": .8}
        with patch.object(C, "learned_cadences", return_value=learned):
            summary = I._cultures_summary_payload(t.FakeHass(), cfg)
        jar = summary["jars"][0]
        self.assertEqual(jar["densityAdvice"]["action"], "check")
        self.assertEqual(jar["densityAdvice"], jar["feedAdvice"])
        self.assertNotIn("harvest", jar["due"])
        self.assertEqual(I._cultures_push_plan(summary), [])

    def test_estimates_never_round_to_zero_days_while_still_green(self):
        state = {"status": "producing", "daysSinceSplit": 7.5, "cycle": {"ofDays": 8}}
        self.assertNotIn("~0 d", C.density_advice("green", state)["reason"])

    def animal_entry(self):
        jar = t._jar(started_ago_days=9, now=NOW, lastTint="clearing", lastSign="foam",
                     lastSignAt=t._iso(NOW - timedelta(hours=1)))
        jar.update(volumeL=4.5, salinityPpt=27)
        return t._entry(jars={"r": jar})

    def test_actual_water_change_volume_drives_recipe_history_and_stock(self):
        entry = self.animal_entry()
        before = deepcopy(t._cultures(entry)["jars"]["r"])
        guide = C.water_care_guide(before, 35, 1000)
        self.assertEqual((guide["mixMl"], guide["rodiMl"], guide["totalMl"]), (771, 229, 1000))
        conn, hass = t.FakeConnection(), t.FakeHass(entries=[entry])
        with patch.object(I, "_mixing_hatchery_debit") as debit:
            t.run(I.websocket_cultures_water_change(hass, conn, {"id": 1, "jar_id": "r", "ml": 1000}))
            self.assertFalse(conn.errors)
            self.assertEqual(debit.call_args.args[2], .771)
        jar = t._cultures(entry)["jars"]["r"]
        self.assertEqual(jar["history"][0]["ml"], 1000)
        self.assertEqual(jar["volumeL"], 4.5)
        for field in ("lastFedAt", "lastHarvestAt", "lastRestartAt", "lastSignAt", "lastTint"):
            self.assertEqual(jar["state"][field], before["state"].get(field, ""))
        self.assertEqual(t._config(entry)["consumables"]["products"]["phyto"]["remainingMl"], 300)

    def test_plain_restart_uses_actual_refill_without_claiming_feed(self):
        entry = self.animal_entry()
        stale = deepcopy(t._config(entry))
        old_feed = t._cultures(entry)["jars"]["r"]["state"]["lastFedAt"]
        conn, hass = t.FakeConnection(), t.FakeHass(entries=[entry])
        with patch.object(I, "_mixing_hatchery_debit") as debit:
            t.run(I.websocket_cultures_restart(hass, conn, {"id": 1, "jar_id": "r", "ml": 3500, "fed": False}))
            self.assertFalse(conn.errors)
            self.assertEqual(debit.call_args.args[2], 2.7)
        jar = t._cultures(entry)["jars"]["r"]
        self.assertEqual(jar["volumeL"], 3.5)
        self.assertEqual(jar["history"][0]["ml"], 3500)
        self.assertTrue(jar["history"][0]["plainWater"])
        self.assertFalse(jar["history"][0]["fed"])
        self.assertEqual(jar["state"]["lastFedAt"], old_feed)
        self.assertEqual(jar["state"]["lastTint"], "")
        self.assertEqual(jar["state"]["lastSign"], "")
        self.assertEqual(t._config(entry)["consumables"]["products"]["phyto"]["remainingMl"], 300)
        self.assertEqual(C.replay_state(jar["history"], jar["species"])["lastTint"], "")
        self.assertEqual(C.clearing_samples(jar["history"] + [{"event": "tint", "tint": "clear", "at": t._iso(NOW + timedelta(hours=3))}]), [])
        self.assertEqual(C.feed_timeline(jar["history"], NOW + timedelta(hours=1))["spans"], [])
        stored = t._config(entry)
        I._nps_preserve_runtime(stored, stale)
        self.assertEqual(stale["nps"]["cultures"]["jars"]["r"]["volumeL"], 3.5)
        current = deepcopy(stored)
        current["nps"]["cultures"]["jars"]["r"]["volumeL"] = 4
        I._nps_preserve_runtime(stored, current)
        self.assertEqual(current["nps"]["cultures"]["jars"]["r"]["volumeL"], 4, "current settings can still change the volume")

    def test_restart_respects_the_minimum_working_volume(self):
        jar = t._cultures(self.animal_entry())["jars"]["r"]
        self.assertFalse(C.water_care_guide(jar, 35, 199, restart=True)["available"])
        self.assertEqual(C.water_care_guide(jar, 35, 200, restart=True)["totalMl"], 200)
        self.assertEqual(C.water_care_guide(jar, 35, 1)["totalMl"], 1)

    def test_plain_restart_can_seed_a_backup_from_a_previously_healthy_crop(self):
        entry = t._entry(jars={"r": t._jar(started_ago_days=20, lastTint="clearing")})
        conn = t.FakeConnection()
        t.run(I.websocket_cultures_restart(t.FakeHass(entries=[entry]), conn,
                                           {"id": 1, "jar_id": "r", "ml": 2500, "fed": False, "split": True}))
        self.assertFalse(conn.errors)
        jars = t._cultures(entry)["jars"]
        self.assertEqual(len(jars), 2)
        backup = next(jar for jid, jar in jars.items() if jid != "r")
        self.assertEqual(backup["state"]["seededFrom"], "r")
        self.assertEqual(jars["r"]["state"]["lastTint"], "")

    def test_invalid_quantities_leave_records_and_stock_unchanged(self):
        for handler in (I.websocket_cultures_water_change, I.websocket_cultures_restart):
            for ml in (0, -1, 4501, 1.5, True, float("nan"), float("inf")):
                with self.subTest(handler=handler.__name__, ml=ml):
                    entry = self.animal_entry()
                    before = deepcopy(entry.options)
                    conn = t.FakeConnection()
                    with patch.object(I, "_mixing_hatchery_debit") as debit:
                        t.run(handler(t.FakeHass(entries=[entry]), conn, {"id": 1, "jar_id": "r", "ml": ml}))
                        self.assertEqual(conn.errors[-1].code, "invalid_volume")
                        debit.assert_not_called()
                    self.assertEqual(entry.options, before)


if __name__ == "__main__":
    main()
