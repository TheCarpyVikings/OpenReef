"""Seed corrections restore linked records atomically; no real HA or equipment."""
from copy import deepcopy
from datetime import datetime, timedelta
import unittest

import test_cultures as t
from _fake_ha import FakeConnection, FakeHass, run

I, C, NOW = t.integration, t.cultures, t.REAL


def fixture(source="sibling", legacy=False, tracked=True):
    started, crashed = (NOW - timedelta(days=33)).isoformat(), (NOW - timedelta(hours=2)).isoformat()
    donor = t._phyto_jar(started_ago_days=7, now=NOW, workingL=4.85, lastTint="dark")
    donor.update(name="Nanno Main", volumeL=5)
    target = t._phyto_jar(started_ago_days=33, now=NOW, workingL=3.5, crashedAt=crashed)
    target["name"] = "Nanno Backup"
    target["history"] = [
        {"event": "crashed", "at": crashed, "tint": "pale"},
        {"event": "seeded", "at": started, "ml": 3500, "workingMl": 3500, "tint": "pale"},
    ]
    products = t._phyto_products()
    products["f2"]["remainingMl"] = 232
    if source == "bottle":
        products["home_phyto_c2"] = {"name": "Backup phyto", "category": "phyto", "bottleMl": 1000,
                                    "remainingMl": 600, "openedAt": (NOW - timedelta(days=1)).isoformat(), "history": []}
    entry = t._phyto_entry(jars={"c1": donor, "c2": target}, products=products)
    cfg = t._config(entry)
    cfg["mixingStation"] = {"enabled": tracked, "salt": {"targetPpt": 35},
        "vessels": {"mix": {"volumeLitres": 35, "estimatedLitres": 10.3, "contents": "salt"}},
        "batch": {"state": "storing", "litres": 10.3, "loggedPpt": 35,
                  "startedAt": (NOW - timedelta(days=1)).isoformat(), "testedAt": (NOW - timedelta(hours=4)).isoformat()}}
    entry.options = {**entry.options, t.CONF_SETTINGS: cfg}
    before = t._config(entry)
    hass, conn = FakeHass(entries=[entry]), FakeConnection()
    extra = {"from_jar_id": "c1"} if source == "sibling" else {"from_bottle": True} if source == "bottle" else {"arrival_tint": "green"}
    run(I.websocket_cultures_seed(hass, conn, {"id": 1, "jar_id": "c2", "starter_ml": 250, "working_l": 1.25, **extra}))
    assert not conn.errors, conn.errors
    cfg = t._config(entry)
    row = cfg["nps"]["cultures"]["jars"]["c2"]["history"][0]
    stamp = row["at"]
    if legacy:
        row.pop("seedUndo")
    entry.options = {**entry.options, t.CONF_SETTINGS: cfg}
    return entry, hass, conn, before, stamp


class SeedUndo(unittest.TestCase):
    def test_linked_seed_restores_both_cultures_stock_and_water_once(self):
        for clicked in ("c1", "c2"):
            with self.subTest(clicked=clicked):
                entry, hass, conn, before, stamp = fixture()
                seeded = t._config(entry)
                self.assertEqual(seeded["nps"]["cultures"]["jars"]["c1"]["state"]["workingL"], 4.6)
                self.assertEqual(seeded["mixingStation"]["vessels"]["mix"]["estimatedLitres"], 9.3)
                self.assertEqual(seeded["consumables"]["products"]["f2"]["remainingMl"], 230.5)
                run(I.websocket_cultures_undo(hass, conn, {"id": 2, "jar_id": clicked, "at": stamp}))
                self.assertFalse(conn.errors)
                cfg = t._config(entry)
                jars = cfg["nps"]["cultures"]["jars"]
                self.assertEqual(I._cultures_seed_state(jars["c2"]), I._cultures_seed_state(before["nps"]["cultures"]["jars"]["c2"]))
                self.assertEqual(jars["c1"]["state"]["workingL"], 4.85)
                self.assertEqual(cfg["mixingStation"]["vessels"]["mix"]["estimatedLitres"], 10.3)
                self.assertEqual(cfg["consumables"]["products"]["f2"]["remainingMl"], 232)
                self.assertTrue(all(jars[j]["history"][0]["undoneAt"] for j in ("c1", "c2")))
                self.assertTrue(cfg["consumables"]["products"]["f2"]["history"][-1]["undoneAt"])
                self.assertFalse([c for c in hass.services.calls if c.domain == "switch"])
                run(I.websocket_cultures_undo(hass, conn, {"id": 3, "jar_id": clicked, "at": stamp}))
                self.assertEqual(conn.errors[-1].code, "nothing_to_undo")
                self.assertEqual(t._config(entry), cfg)

    def test_legacy_225_seed_uses_actual_donor_stock_and_water_records(self):
        entry, hass, conn, before, stamp = fixture(legacy=True)
        run(I.websocket_cultures_undo(hass, conn, {"id": 2, "jar_id": "c2", "at": stamp}))
        self.assertFalse(conn.errors)
        cfg = t._config(entry)
        jar = cfg["nps"]["cultures"]["jars"]["c2"]
        self.assertEqual(C.culture_state(jar, NOW)["status"], "crashed")
        self.assertEqual(jar["state"]["startedAt"], before["nps"]["cultures"]["jars"]["c2"]["state"]["startedAt"])
        self.assertEqual(jar["state"]["crashedAt"], before["nps"]["cultures"]["jars"]["c2"]["state"]["crashedAt"])
        self.assertEqual(cfg["nps"]["cultures"]["jars"]["c1"]["state"]["workingL"], 4.85)
        self.assertEqual(cfg["mixingStation"]["vessels"]["mix"]["estimatedLitres"], 10.3)
        self.assertEqual(cfg["consumables"]["products"]["f2"]["remainingMl"], 232)

    def test_supplier_and_fridge_seed_return_only_the_stock_they_used(self):
        for source in ("starter", "bottle"):
            with self.subTest(source=source):
                entry, hass, conn, before, stamp = fixture(source)
                run(I.websocket_cultures_undo(hass, conn, {"id": 2, "jar_id": "c2", "at": stamp}))
                self.assertFalse(conn.errors)
                cfg = t._config(entry)
                self.assertEqual(cfg["consumables"]["products"]["f2"]["remainingMl"], 232)
                self.assertEqual(cfg["nps"]["cultures"]["jars"]["c1"]["state"], before["nps"]["cultures"]["jars"]["c1"]["state"])
                if source == "bottle":
                    self.assertEqual(cfg["consumables"]["products"]["home_phyto_c2"]["remainingMl"], 600)

    def test_conflicts_refuse_before_any_ledger_changes(self):
        for conflict in ("target", "donor", "water", "batch", "stock_load", "stock_topup", "stock_corrected", "missing_stock", "missing_donor", "expired", "future", "receipt"):
            with self.subTest(conflict=conflict):
                entry, _hass, _conn, _before, stamp = fixture()
                cfg = t._config(entry)
                jars = cfg["nps"]["cultures"]["jars"]
                at = datetime.fromisoformat(stamp)
                later = (at + timedelta(minutes=1)).isoformat()
                if conflict in ("target", "donor"):
                    jars["c2" if conflict == "target" else "c1"]["history"].insert(0, {"event": "tint", "at": later, "tint": "green"})
                elif conflict == "water":
                    cfg["mixingStation"]["vessels"]["mix"]["estimatedLitres"] -= 0.5
                elif conflict == "batch":
                    cfg["mixingStation"]["batch"]["testedAt"] = later
                elif conflict == "stock_load":
                    cfg["consumables"]["products"]["f2"]["openedAt"] = later
                elif conflict == "stock_topup":
                    cfg["consumables"]["products"]["f2"]["history"].append({"kind": "refill", "at": later, "ml": 1})
                elif conflict == "stock_corrected":
                    cfg["consumables"]["products"]["f2"]["remainingMl"] = 232
                elif conflict == "missing_stock":
                    cfg["consumables"]["products"]["f2"]["history"] = []
                elif conflict == "missing_donor":
                    jars["c1"]["history"] = []
                elif conflict == "receipt":
                    jars["c2"]["history"][0]["seedUndo"]["mixBefore"] = {}
                I._nps_cultures_cfg(cfg)
                previous = deepcopy(cfg)
                error = I._cultures_undo_apply(cfg, "c2", stamp, at + timedelta(hours=25 if conflict == "expired" else -1 if conflict == "future" else 2))
                self.assertIsNotNone(error)
                self.assertEqual(cfg, previous)

    def test_later_independent_stock_usage_is_preserved_and_link_changes_do_not_redirect_credit(self):
        entry, _, _, _, stamp = fixture()
        cfg = t._config(entry)
        jar = cfg["nps"]["cultures"]["jars"]["c2"]
        jar["nutrient"]["productId"] = "replacement"
        f2 = cfg["consumables"]["products"]["f2"]
        I._consumable_debit(f2, 2, "dose", at=datetime.fromisoformat(stamp)+timedelta(seconds=10), to="jar", jar_id="c1")
        self.assertIsNone(I._cultures_undo_apply(cfg, "c2", stamp, datetime.fromisoformat(stamp)+timedelta(minutes=1)))
        self.assertEqual(f2["remainingMl"], 230)

    def test_untracked_water_is_not_invented_and_background_light_is_retained(self):
        entry, _, _, _, stamp = fixture(tracked=False)
        cfg = t._config(entry)
        jar = cfg["nps"]["cultures"]["jars"]["c2"]
        at = datetime.fromisoformat(stamp)
        I._cultures_history(jar, "light", at+timedelta(minutes=1), lightH=4)
        jar["state"]["lightMinutesToday"] = 240
        self.assertIsNone(I._cultures_undo_apply(cfg, "c2", stamp, at+timedelta(minutes=2)))
        self.assertEqual(cfg["mixingStation"]["vessels"]["mix"]["estimatedLitres"], 10.3)
        restored = cfg["nps"]["cultures"]["jars"]["c2"]
        self.assertEqual(restored["state"]["lightMinutesToday"], 240)
        self.assertFalse(restored["history"][0].get("undoneAt"))

    def test_ready_storing_transition_keeps_the_same_batch_undoable(self):
        entry, _, _, _, stamp = fixture()
        cfg = t._config(entry)
        cfg["mixingStation"]["batch"]["state"] = "ready"
        self.assertIsNone(I._cultures_undo_apply(cfg, "c2", stamp, datetime.fromisoformat(stamp)+timedelta(minutes=1)))
        self.assertEqual(cfg["mixingStation"]["vessels"]["mix"]["estimatedLitres"], 10.3)
        self.assertEqual(cfg["mixingStation"]["batch"]["state"], "ready")

    def test_legacy_missing_receipts_are_explained_without_guessing(self):
        for missing in ("water", "old_cycle"):
            with self.subTest(missing=missing):
                entry, _, _, _, stamp = fixture(legacy=True)
                cfg = t._config(entry)
                if missing == "water":
                    cfg["activity"] = []
                else:
                    cfg["nps"]["cultures"]["jars"]["c2"]["history"] = cfg["nps"]["cultures"]["jars"]["c2"]["history"][:2]
                before = deepcopy(cfg)
                error = I._cultures_undo_apply(cfg, "c2", stamp, datetime.fromisoformat(stamp)+timedelta(minutes=1))
                self.assertEqual(error[0], "seed_undo_conflict")
                self.assertEqual(cfg, before)

    def test_summary_exposes_one_linked_undo_from_either_row_without_leaking_receipt(self):
        entry, hass, _, _, stamp = fixture()
        cfg = t._config(entry)
        summary = I._cultures_summary_payload(hass, cfg)
        for jar in summary["jars"]:
            row = next(r for r in jar["history"] if r["at"] == stamp)
            self.assertTrue(row["undoable"], row.get("undoReason"))
            self.assertEqual(row["undoJarId"], "c2")
            self.assertEqual(row["undoKind"], "seed")
            self.assertNotIn("seedUndo", row)
        self.assertIn("seedUndo", t._config(entry)["nps"]["cultures"]["jars"]["c2"]["history"][0])

    def test_stale_settings_save_cannot_resurrect_the_seed_or_redebit_stock(self):
        entry, hass, conn, _, stamp = fixture()
        stale = t._config(entry)
        run(I.websocket_cultures_undo(hass, conn, {"id": 2, "jar_id": "c2", "at": stamp}))
        stored = t._config(entry)
        I._nps_preserve_runtime(stored, stale)
        I._mixing_preserve_runtime(stored, stale)
        for jid in ("c1", "c2"):
            self.assertEqual(stale["nps"]["cultures"]["jars"][jid]["state"], stored["nps"]["cultures"]["jars"][jid]["state"])
            self.assertTrue(stale["nps"]["cultures"]["jars"][jid]["history"][0]["undoneAt"])
        self.assertEqual(stale["consumables"]["products"]["f2"]["remainingMl"], 232)
        self.assertEqual(stale["mixingStation"]["vessels"]["mix"]["estimatedLitres"], 10.3)


if __name__ == "__main__":
    unittest.main()
