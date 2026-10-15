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

    def test_large_change_boundary_resolves_sign_and_care_clock_without_a_restart(self):
        for ml in (2249, 2250, 4500):
            with self.subTest(ml=ml):
                entry = self.animal_entry()
                before = deepcopy(t._cultures(entry)["jars"]["r"])
                conn, hass = t.FakeConnection(), t.FakeHass(entries=[entry])
                t.run(I.websocket_cultures_water_change(hass, conn, {"id": 1, "jar_id": "r", "ml": ml}))
                self.assertFalse(conn.errors)
                jar = t._cultures(entry)["jars"]["r"]
                at = C._parse_iso(jar["state"]["lastWaterChangeAt"])
                state = C.culture_state(jar, at)
                large = ml >= 2250
                self.assertEqual(bool(jar["state"]["lastLargeWaterChangeAt"]), large)
                self.assertEqual(bool(jar["state"]["lastSign"]), not large)
                self.assertEqual(state["restart"]["due"], not large)
                self.assertEqual(bool(jar["history"][0].get("clearsSigns")), large)
                for field in ("startedAt", "lastRestartAt", "lastFedAt", "lastHarvestAt", "lastTint"):
                    self.assertEqual(jar["state"][field], before["state"].get(field, ""))
                self.assertEqual(jar["volumeL"], 4.5)
                if large:
                    self.assertEqual(state["restart"]["hoursUntil"], 14 * 24)
                    self.assertEqual(state["daysSinceCare"], 0)
                    self.assertGreaterEqual(state["daysSinceRestart"], 9)
                    self.assertEqual(state["percent"], 0)
                    self.assertTrue(C.culture_state(jar, at + timedelta(days=14))["restart"]["due"])
                    summary = I._cultures_summary_payload(hass, t._config(entry))["jars"][0]
                    self.assertNotIn("foam", summary["risk"]["reason"])
                    self.assertNotIn("two harvests missed", summary["risk"]["reason"])
                    self.assertNotEqual(summary["feedAdvice"]["action"], "harvest_first")

    def test_small_changes_never_accumulate_or_bypass_a_disabled_restart_cadence(self):
        entry = self.animal_entry()
        t._cultures(entry)["jars"]["r"]["cadence"] = {"restartIntervalDays": 0}
        conn, hass = t.FakeConnection(), t.FakeHass(entries=[entry])
        for _ in range(3):
            t.run(I.websocket_cultures_water_change(hass, conn, {"id": 1, "jar_id": "r", "ml": 2000}))
        self.assertFalse(conn.errors)
        summary = I._cultures_summary_payload(hass, t._config(entry))["jars"][0]
        self.assertEqual(summary["state"]["restart"]["reason"], "sign")
        self.assertEqual(summary["lastSign"], "foam")

    def test_large_change_answers_calendar_and_slow_clearing_but_new_signs_return(self):
        jar = t._jar(started_ago_days=20, now=NOW)
        jar["history"] = [t._row("tint", 1, tint="clear"), t._row("feed", 19),
                          t._row("tint", 25, tint="clear"), t._row("feed", 41),
                          t._row("tint", 50, tint="clear"), t._row("feed", 58),
                          t._row("tint", 70, tint="clear"), t._row("feed", 79)]
        # _row uses the pure-engine fixture clock; pin this test to it too.
        jar["state"]["startedAt"] = t._iso(t.NOW - timedelta(days=20))
        jar["state"]["lastRestartAt"] = jar["state"]["startedAt"]
        self.assertEqual(C.culture_state(jar, t.NOW)["restart"]["reason"], "slow")
        jar["state"]["lastLargeWaterChangeAt"] = t._iso(t.NOW)
        state = C.culture_state(jar, t.NOW)
        self.assertFalse(state["clearingSlow"])
        self.assertFalse(state["restart"]["due"])
        later = t.NOW + timedelta(hours=1)
        jar["state"].update(lastSign="milky", lastSignAt=t._iso(later))
        self.assertEqual(C.culture_state(jar, later)["restart"]["reason"], "sign")

    def test_bad_or_old_large_change_stamps_cannot_hide_a_warning(self):
        jar = t._cultures(self.animal_entry())["jars"]["r"]
        for stamp in ("junk", t._iso(NOW + timedelta(hours=1)), t._iso(NOW - timedelta(days=10))):
            with self.subTest(stamp=stamp):
                jar["state"]["lastLargeWaterChangeAt"] = stamp
                self.assertEqual(C.culture_state(jar, NOW)["restart"]["reason"], "sign")

    def test_new_sign_undo_cannot_resurrect_a_sign_resolved_by_water_care(self):
        entry = self.animal_entry()
        jar = t._cultures(entry)["jars"]["r"]
        jar["history"] = [{"event": "sign", "at": jar["state"]["lastSignAt"], "sign": "foam"}]
        conn, hass = t.FakeConnection(), t.FakeHass(entries=[entry])
        t.run(I.websocket_cultures_water_change(hass, conn, {"id": 1, "jar_id": "r", "ml": 2250}))
        t.run(I.websocket_cultures_log(hass, conn, {"id": 2, "jar_id": "r", "sign": "smell"}))
        jar = t._cultures(entry)["jars"]["r"]
        summary = I._cultures_summary_payload(hass, t._config(entry))["jars"][0]
        self.assertEqual(summary["state"]["restart"]["reason"], "sign")
        t.run(I.websocket_cultures_undo(hass, conn, {"id": 3, "jar_id": "r", "at": jar["state"]["lastSignAt"]}))
        self.assertFalse(conn.errors)
        jar = t._cultures(entry)["jars"]["r"]
        self.assertEqual(jar["state"]["lastSign"], "")
        self.assertEqual(C.replay_state(jar["history"], jar["species"])["lastSign"], "")

    def test_summary_reminders_stale_save_and_heat_remain_consistent(self):
        entry = self.animal_entry()
        stale = deepcopy(t._config(entry))
        conn, hass = t.FakeConnection(), t.FakeHass(entries=[entry])
        before = I._cultures_summary_payload(hass, t._config(entry))
        self.assertEqual(before["jars"][0]["largeWaterChange"], {"pct": 50, "minMl": 2250})
        self.assertIn("2250 ml", before["jars"][0]["feedAdvice"]["reason"])
        self.assertIn("restart or large water change", I._cultures_push_plan(before)[0]["title"])
        t.run(I.websocket_cultures_water_change(hass, conn, {"id": 1, "jar_id": "r", "ml": 2250}))
        stored = t._config(entry)
        I._nps_preserve_runtime(stored, stale)
        self.assertEqual(stale["nps"]["cultures"]["jars"]["r"], stored["nps"]["cultures"]["jars"]["r"])
        jar = stored["nps"]["cultures"]["jars"]["r"]
        at = C._parse_iso(jar["state"]["lastWaterChangeAt"])
        self.assertFalse(I._cultures_task_clock(stored, "culture_r_restart", at)["due"])
        risk = C.risk_line(jar, C.culture_state(jar, at), C.temperature_advice(34, "rotifer_L"), at)
        self.assertEqual(risk["level"], "act")
        self.assertIn("34", risk["reason"])
        self.assertNotIn("foam", risk["reason"])

    def test_threshold_rounds_up_to_whole_ml_and_other_species_keep_their_care(self):
        self.assertEqual(C.large_water_change_guide({"species": "rotifer_L", "volumeL": 4.501})["minMl"], 2251)
        for species in ("tigriopus", "nanno"):
            self.assertEqual(C.large_water_change_guide({"species": species, "volumeL": 4.5}), {})

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
