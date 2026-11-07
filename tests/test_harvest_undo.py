"""Harvest recovery preserves later work and the actual load time."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

import test_nps as fixtures
from _fake_ha import FakeConnection, FakeHass, run

integration = fixtures.integration
NOW = datetime(2026, 11, 7, 7, 50, tzinfo=timezone.utc)
OLD = (NOW - timedelta(hours=21.7)).isoformat()
START = (NOW - timedelta(hours=36)).isoformat()


class FrozenTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


def fixture(*, linked=False, litres=10):
    entry = fixtures._v2_entry(vessels={
        "v1": {"name": "Hatchery 1", "eggType": "premium", "hatchHours": 36,
               "state": {"hatchStartedAt": START, "eggType": "premium", "hatchHours": 36}},
        "v2": {"name": "Hatchery 2", "state": {"hatchStartedAt": ""}},
    })
    fixtures._mixing_station_for_hatchery(entry, litres=litres)
    config = integration._config_from_entry(entry)
    hatch = config["nps"]["hatchery"]
    hatch["reservoir"].update({"volumeMl": 750, "remainingMl": 250, "mixedAt": OLD,
                                "fridgeSavedH": 1, "loadVolumeMl": 0})
    if linked:
        config["nps"]["feedExchange"]["channelId"] = "brine"
        config["dosing"]["channels"]["brine"] = {"chemical": "livefood", "reservoir": {
            "volumeMl": 750, "remainingMl": 250, "mixedAt": OLD}}
    start, harvest = integration._nps_hatch_task_ids("v1")
    config["maintenance"]["tasks"].update({start: {"label": "Start"}, harvest: {"label": "Harvest"}})
    config = integration._normalise_core_config(config)
    return entry, config


def harvest(config):
    error = integration._nps_hatch_cancel_apply(FakeHass(), config, "v1", True, NOW)
    assert error is None, error


def request(config, action="undo"):
    row = config["nps"]["hatchery"]["history"][0]
    return {"id": 1, "action": action, "vessel_id": row["vesselId"],
            "harvested_at": row["harvestedAt"], "started_at": row["startedAt"],
            "mixed_at": integration._nps_canonical_reservoir(config)["mixedAt"]}


class HarvestUndo(unittest.TestCase):
    def test_undo_restores_previous_stock_batch_history_and_water_once(self):
        for linked in (False, True):
            with self.subTest(linked=linked):
                _, config = fixture(linked=linked)
                before = deepcopy(config)
                harvest(config)
                self.assertEqual(integration._nps_canonical_reservoir(config)["mixedAt"], OLD)
                self.assertEqual(config["mixingStation"]["vessels"]["mix"]["estimatedLitres"], 9.5)
                # HA serialisation and normalisation must not lose the checkpoint.
                config = integration._normalise_core_config(config)
                self.assertTrue(integration._nps_harvest_repair_status(config, NOW)["canUndo"])
                msg = request(config)
                self.assertIsNone(integration._nps_harvest_repair_apply(config, msg, NOW))
                hatch, original = config["nps"]["hatchery"], before["nps"]["hatchery"]
                for key in ("vessels", "reservoir", "history", "fridgeBottle", "enrichment", "handFeeds"):
                    self.assertEqual(hatch[key], original[key], key)
                self.assertEqual(integration._nps_canonical_reservoir(config), integration._nps_canonical_reservoir(before))
                self.assertEqual(config["mixingStation"], before["mixingStation"])
                _, task = integration._nps_hatch_task_ids("v1")
                self.assertFalse(config["maintenance"]["completions"][task])
                restored = deepcopy(config)
                self.assertIsNotNone(integration._nps_harvest_repair_apply(config, msg, NOW))
                self.assertEqual(config, restored)

    def test_undo_refuses_later_feeding_restart_transfer_enrichment_or_water_use(self):
        for change in ("feed", "restart", "bottle", "enrich", "water", "channel", "journal", "reminder"):
            with self.subTest(change=change):
                _, config = fixture()
                harvest(config)
                msg = request(config)
                hatch = config["nps"]["hatchery"]
                if change == "feed": hatch["reservoir"]["remainingMl"] -= 50
                if change == "restart": hatch["vessels"]["v1"]["state"]["hatchStartedAt"] = NOW.isoformat()
                if change == "bottle": hatch["fridgeBottle"]["remainingMl"] = 50
                if change == "enrich": hatch["enrichment"]["state"]["startedAt"] = NOW.isoformat()
                if change == "water": config["mixingStation"]["vessels"]["mix"]["estimatedLitres"] -= 1
                if change == "channel": config["nps"]["feedExchange"]["channelId"] = "other"
                if change == "journal": hatch["history"][0]["vesselId"] = "v2"
                if change == "reminder":
                    start, _ = integration._nps_hatch_task_ids("v1")
                    config["maintenance"]["tasks"][start]["snoozedUntil"] = NOW.isoformat()
                before = deepcopy(config)
                self.assertIsNotNone(integration._nps_harvest_repair_apply(config, msg, NOW))
                self.assertEqual(config, before)

    def test_undo_does_not_resurrect_exhausted_mixing_batch(self):
        _, config = fixture(litres=.5)
        harvest(config)
        self.assertEqual(config["mixingStation"]["batch"]["state"], "idle")
        self.assertFalse(integration._nps_harvest_repair_status(config, NOW)["canUndo"])
        self.assertTrue(integration._nps_harvest_repair_status(config, NOW)["canCorrectEmpty"])

    def test_existing_harvest_correction_keeps_feeds_and_replacement_start_uses_harvest_time(self):
        for linked in (False, True):
            with self.subTest(linked=linked):
                _, config = fixture(linked=linked)
                harvest(config)
                hatch = config["nps"]["hatchery"]
                hatch["harvestUndo"] = {}  # A harvest saved by an older version.
                hatch["vessels"]["v1"]["state"]["hatchStartedAt"] = NOW.isoformat()
                integration._nps_canonical_reservoir(config)["remainingMl"] = 500
                hatch["handFeeds"] = [{"at": NOW.isoformat(), "ml": 250, "from": "container"}]
                before = deepcopy(config)
                msg = request(config, "emptied")
                later = NOW + timedelta(hours=2)
                self.assertIsNone(integration._nps_harvest_repair_apply(config, msg, later))
                self.assertEqual(integration._nps_canonical_reservoir(config)["mixedAt"], NOW.isoformat())
                self.assertEqual(integration._nps_canonical_reservoir(config)["remainingMl"], 500)
                self.assertEqual(hatch["reservoir"]["fridgeSavedH"], 0)
                prime = fixtures.nps.hatch_prime_state(integration._nps_canonical_reservoir(config)["mixedAt"], later,
                                                       fridge_saved_h=hatch["reservoir"]["fridgeSavedH"])
                self.assertEqual(prime["primeLeftHours"], 22)
                for key in ("history", "vessels", "handFeeds", "fridgeBottle", "enrichment"):
                    self.assertEqual(hatch[key], before["nps"]["hatchery"][key])
                self.assertEqual(config["mixingStation"], before["mixingStation"])
                corrected = deepcopy(config)
                self.assertIsNotNone(integration._nps_harvest_repair_apply(config, msg, later))
                self.assertEqual(config, corrected)

    def test_correction_rejects_stale_requests_new_loads_empty_enriched_chilled_or_future(self):
        for case in ("stale", "vessel", "mixed", "load", "empty", "enriched", "soak", "chilled", "future"):
            with self.subTest(case=case):
                _, config = fixture()
                harvest(config)
                hatch = config["nps"]["hatchery"]
                msg = request(config, "emptied")
                if case == "stale": msg["harvested_at"] = OLD
                if case == "vessel": msg["vessel_id"] = "v2"
                if case == "mixed": msg["mixed_at"] = START
                if case == "load": hatch["reservoir"]["mixedAt"] = NOW.isoformat()
                if case == "empty": hatch["reservoir"]["remainingMl"] = 0
                if case == "enriched": hatch["history"][0]["enriched"] = True
                if case == "soak": hatch["enrichment"]["state"]["startedAt"] = NOW.isoformat()
                if case == "chilled": hatch["fridgeBottle"]["refrigeratedAt"] = NOW.isoformat()
                if case == "future":
                    hatch["history"][0]["harvestedAt"] = (NOW + timedelta(hours=1)).isoformat()
                    msg = request(config, "emptied")
                before = deepcopy(config)
                self.assertIsNotNone(integration._nps_harvest_repair_apply(config, msg, NOW))
                self.assertEqual(config, before)

    def test_checkpoint_survives_stale_settings_and_cannot_be_injected_by_them(self):
        _, config = fixture()
        incoming = deepcopy(config)
        harvest(config)
        integration._nps_preserve_runtime(config, incoming)
        self.assertEqual(incoming["nps"]["hatchery"]["harvestUndo"], config["nps"]["hatchery"]["harvestUndo"])
        saved = deepcopy(incoming)
        config["nps"]["hatchery"]["harvestUndo"] = {}
        integration._nps_preserve_runtime(config, saved)
        self.assertFalse(saved["nps"]["hatchery"]["harvestUndo"])

    def test_malformed_checkpoints_are_ignored(self):
        _, config = fixture()
        harvest(config)
        undo = config["nps"]["hatchery"]["harvestUndo"]
        for key in ("state", "reservoir", "container", "history"):
            damaged = deepcopy(undo)
            damaged["before"][key] = "invalid"
            self.assertFalse(integration._normalise_harvest_undo(damaged))
        damaged = deepcopy(undo)
        damaged["before"]["container"]["extra"] = "x" * 64000
        self.assertFalse(integration._normalise_harvest_undo(damaged))

    def test_correction_retimes_idle_start_without_another_completion(self):
        _, config = fixture()
        harvest(config)
        start, _ = integration._nps_hatch_task_ids("v1")
        completions = deepcopy(config["maintenance"]["completions"])
        config["maintenance"]["tasks"][start]["snoozedUntil"] = (NOW + timedelta(days=1)).isoformat()
        self.assertIsNone(integration._nps_harvest_repair_apply(config, request(config, "emptied"), NOW))
        self.assertEqual(config["maintenance"]["completions"], completions)
        self.assertNotEqual(config["maintenance"]["tasks"][start]["snoozedUntil"], (NOW + timedelta(days=1)).isoformat())

    @patch.object(integration, "datetime", FrozenTime)
    def test_websocket_persistence_summary_and_no_actuation(self):
        entry, config = fixture()
        entry.options[fixtures.CONF_SETTINGS] = config
        hass, conn = FakeHass(entries=[entry]), FakeConnection()
        run(integration.websocket_nps_hatch_cancel(hass, conn, {"id": 1, "vessel_id": "v1", "harvested": True}))
        self.assertFalse(conn.errors, conn.errors)
        saved = integration._config_from_entry(entry)
        run(integration.websocket_nps_summary(hass, conn, {"id": 2}))
        self.assertTrue(conn.results[-1].payload["hatchery"]["harvestRepair"]["canUndo"])
        run(integration.websocket_nps_harvest_repair(hass, conn, request(saved)))
        self.assertFalse(conn.errors, conn.errors)
        self.assertEqual(entry.options[fixtures.CONF_SETTINGS]["nps"]["hatchery"]["vessels"]["v1"]["state"]["hatchStartedAt"], START)
        self.assertFalse([call for call in hass.services.calls if call.domain != "persistent_notification"])


if __name__ == "__main__":
    unittest.main()
