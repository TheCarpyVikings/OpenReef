"""Correct a harvest recorded against the other physical hatchery."""
from copy import deepcopy
from datetime import datetime, timezone
import unittest

import test_nps as fixtures
from _fake_ha import FakeConnection, FakeHass, run

integration, nps = fixtures.integration, fixtures.nps
SETTINGS = fixtures.CONF_SETTINGS
NOW = datetime(2026, 11, 4, 23, 30, tzinfo=timezone.utc)
OLD = "2026-11-02T09:53:47+00:00"
TARGET = "2026-11-02T22:54:08+00:00"
REPLACEMENT = "2026-11-04T09:42:00+00:00"
HARVEST = "2026-11-04T21:41:59+00:00"


def fixture():
    entry = fixtures._v2_entry(vessels={
        "v1": {"name": "Hatchery 1", "volumeL": .4, "eggType": "premium", "hatchHours": 36,
               "state": {"hatchStartedAt": REPLACEMENT, "eggType": "premium", "hatchHours": 36}},
        "v2": {"name": "Hatchery 2", "volumeL": .7, "eggType": "standard", "hatchHours": 30,
               "state": {"hatchStartedAt": TARGET, "eggType": "standard", "hatchHours": 30}},
    })
    config = entry.options[SETTINGS]
    hatchery = integration._nps_hatchery_v2(config)
    hatchery["history"] = [{"vesselId": "v1", "startedAt": OLD, "harvestedAt": HARVEST,
                           "eggType": "premium", "plannedHours": 36, "actualHours": 59.8},
                          {"vesselId": "v2", "startedAt": "2026-10-31T00:00:00+00:00",
                           "harvestedAt": TARGET, "eggType": "standard", "plannedHours": 30,
                           "actualHours": 70.9}]
    hatchery["reservoir"].update({"remainingMl": 0, "mixedAt": HARVEST})
    tasks = [integration._nps_hatch_task_ids(v) for v in ("v1", "v2")]
    config["maintenance"] = {"tasks": {t: {"snoozedUntil": "2026-12-01T00:00:00+00:00"}
                                      for pair in tasks for t in pair}, "completions": {}}
    for task, stamp in ((tasks[0][0], OLD), (tasks[0][0], REPLACEMENT),
                        (tasks[1][0], TARGET), (tasks[0][1], HARVEST)):
        integration._nps_hatch_log_completion(config["maintenance"], task,
            datetime.fromisoformat(stamp), "original note")
    return entry, config


def request(config, source="v1", target="v2"):
    hatch = config["nps"]["hatchery"]
    return {"id": 1, "source_vessel_id": source, "target_vessel_id": target,
            "harvested_at": hatch["history"][0]["harvestedAt"],
            "harvest_started_at": hatch["history"][0]["startedAt"],
            "source_started_at": hatch["vessels"][source]["state"]["hatchStartedAt"],
            "target_started_at": hatch["vessels"][target]["state"]["hatchStartedAt"]}


class HatcheryCorrection(unittest.TestCase):
    def test_restores_original_and_moves_replacement_without_stock_changes(self):
        _, config = fixture()
        before = deepcopy(config)
        self.assertIsNone(integration._nps_hatch_correct_vessel_apply(config, request(config), NOW))
        hatch = config["nps"]["hatchery"]
        self.assertEqual(hatch["vessels"]["v1"]["state"]["hatchStartedAt"], OLD)
        self.assertEqual(hatch["vessels"]["v2"]["state"]["hatchStartedAt"], REPLACEMENT)
        self.assertEqual(hatch["vessels"]["v2"]["state"]["hatchHours"], 36)
        self.assertEqual(hatch["vessels"]["v2"]["state"]["eggType"], "premium")
        row = hatch["history"][0]
        self.assertEqual((row["vesselId"], row["startedAt"], row["plannedHours"], row["eggType"]),
                         ("v2", TARGET, 30, "standard"))
        self.assertEqual(row["actualHours"], 46.8)
        self.assertEqual(row["harvestedAt"], HARVEST)
        self.assertEqual(hatch["history"][1:], before["nps"]["hatchery"]["history"][1:])
        for key in ("reservoir", "fridgeBottle", "handFeeds", "enrichment"):
            self.assertEqual(hatch[key], before["nps"]["hatchery"][key])
        for vid in ("v1", "v2"):
            self.assertEqual({k: v for k, v in hatch["vessels"][vid].items() if k != "state"},
                {k: v for k, v in before["nps"]["hatchery"]["vessels"][vid].items() if k != "state"})
        for key in ("dosing", "automaticWaterChange", "mixing", "consumables"):
            self.assertEqual(config.get(key), before.get(key))
        self.assertEqual(nps.hatch_state(OLD, 36, NOW)["hoursLeft"], 0)
        self.assertEqual(nps.hatch_state(REPLACEMENT, 36, NOW)["hoursLeft"], 22.2)

    def test_reminders_follow_physical_batches_without_duplicate_old_starts(self):
        _, config = fixture()
        integration._nps_hatch_correct_vessel_apply(config, request(config), NOW)
        m = config["maintenance"]
        s1, h1 = integration._nps_hatch_task_ids("v1")
        s2, h2 = integration._nps_hatch_task_ids("v2")
        self.assertEqual([r["timestamp"] for r in m["completions"][s1]], [OLD])
        self.assertEqual([r["timestamp"] for r in m["completions"][s2]], [REPLACEMENT, TARGET])
        self.assertEqual(m["completions"][h1], [])
        self.assertEqual(m["completions"][h2][0]["timestamp"], HARVEST)
        self.assertIsNone(m["tasks"][h1]["snoozedUntil"])
        self.assertEqual(m["tasks"][h2]["snoozedUntil"], "2026-11-05T21:42:00+00:00")

    def test_stale_or_repeated_request_cannot_overwrite_newer_records(self):
        for field in ("harvested_at", "harvest_started_at", "source_started_at", "target_started_at"):
            _, config = fixture()
            msg = request(config)
            msg[field] = "stale"
            before = deepcopy(config)
            self.assertEqual(integration._nps_hatch_correct_vessel_apply(config, msg, NOW)[0], "hatch_changed")
            self.assertEqual(config, before)
        _, config = fixture()
        msg = request(config)
        integration._nps_hatch_correct_vessel_apply(config, msg, NOW)
        before = deepcopy(config)
        self.assertEqual(integration._nps_hatch_correct_vessel_apply(config, msg, NOW)[0], "hatch_changed")
        self.assertEqual(config, before)

    def test_invalid_dates_idle_target_and_enrichment_leave_records_intact(self):
        for case in ("idle", "future", "enrichment", "enriched", "same"):
            _, config = fixture()
            hatch = config["nps"]["hatchery"]
            if case == "idle": hatch["vessels"]["v2"]["state"]["hatchStartedAt"] = ""
            if case == "future": hatch["vessels"]["v1"]["state"]["hatchStartedAt"] = "2026-12-01T00:00:00+00:00"
            if case == "enrichment": hatch["enrichment"]["state"]["startedAt"] = HARVEST
            if case == "enriched": hatch["history"][0]["enriched"] = True
            msg = request(config)
            if case == "same": msg["target_vessel_id"] = "v1"
            before = deepcopy(config)
            self.assertIsNotNone(integration._nps_hatch_correct_vessel_apply(config, msg, NOW))
            self.assertEqual(config, before)

    def test_correction_is_reversible(self):
        _, config = fixture()
        before = deepcopy(config["nps"]["hatchery"])
        integration._nps_hatch_correct_vessel_apply(config, request(config), NOW)
        self.assertIsNone(integration._nps_hatch_correct_vessel_apply(config, request(config, "v2", "v1"), NOW))
        self.assertEqual(config["nps"]["hatchery"], before)

    def test_websocket_persists_and_summary_exposes_exact_starts(self):
        entry, config = fixture()
        hass, conn = FakeHass(entries=[entry]), FakeConnection()
        run(integration.websocket_nps_hatch_correct_vessel(hass, conn, request(config)))
        self.assertFalse(conn.errors, conn.errors)
        saved = entry.options[SETTINGS]["nps"]["hatchery"]
        self.assertEqual(saved["vessels"]["v1"]["state"]["hatchStartedAt"], OLD)
        self.assertEqual(saved["vessels"]["v2"]["state"]["hatchStartedAt"], REPLACEMENT)
        run(integration.websocket_nps_summary(hass, conn, {"id": 2}))
        vessels = conn.results[-1].payload["hatchery"]["vessels"]
        self.assertEqual([v["startedAt"] for v in vessels], [OLD, REPLACEMENT])


if __name__ == "__main__":
    unittest.main()
