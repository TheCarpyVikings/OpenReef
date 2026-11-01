"""Explicit extra feeds remain separate from scheduled feeding obligations.

Run: python3 tests/test_feeding_slots.py (fake HA only).
"""
from datetime import datetime, timedelta, timezone
import unittest

import test_nps as t

nps = t.nps
NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
STAMP = (NOW - timedelta(hours=1)).isoformat()


def product(history):
    return t._product(
        name="Phyto", openedAt=(NOW - timedelta(days=1)).isoformat(),
        remainingMl=1000, doseMl=250, doseTimesPerDay=2,
        doseFirstAt="11:00", doseWindowEnd="21:00", lastDosedAt="", history=history,
    )


class FeedingSlots(unittest.TestCase):
    def test_explicit_extra_does_not_claim_a_timed_or_anytime_slot(self):
        for at in (660, None):
            with self.subTest(slot=at):
                planned = [nps._event(at=at, ml=250, status="planned")]
                extras = nps._match_done(planned, [
                    {"at": 660, "ml": 100, "slot": at, "stamp": STAMP, "extra": True},
                ], 1440)
                self.assertEqual(planned[0]["status"], "planned")
                self.assertIsNone(planned[0]["doneAt"])
                self.assertEqual(len(extras), 1)
                self.assertTrue(extras[0]["unplanned"])
                self.assertEqual(extras[0]["actualMl"], 100)
                self.assertEqual(extras[0]["doneStamp"], STAMP)

    def test_legacy_feed_still_matches_after_an_explicit_extra(self):
        planned = [nps._event(at=660, ml=250, status="planned")]
        extras = nps._match_done(planned, [
            {"at": 659, "ml": 250, "extra": True},
            {"at": 661, "ml": 100},
        ], 60)
        self.assertEqual(len(extras), 1)
        self.assertEqual(planned[0]["status"], "done")
        self.assertEqual(planned[0]["doneAt"], 661)
        self.assertEqual(planned[0]["ml"], 250)
        self.assertEqual(planned[0]["actualMl"], 100)

    def test_each_manual_source_propagates_extra_to_the_timeline(self):
        extra = {"at": STAMP, "ml": 100, "extra": True}
        hatchery = {
            "enabled": True,
            "reservoir": {"remainingMl": 1000, "mixedAt": STAMP},
            "fridgeBottle": {},
            "handFeed": {"defaultDoseMl": 250, "feedsPerDay": 2,
                         "windowStart": "11:00", "windowEnd": "21:00"},
        }
        cultures = {"bottle": {
            "remainingMl": 1000, "filledAt": STAMP, "doseMl": 250,
            "feedsPerDay": 2, "windowStart": "11:00", "windowEnd": "21:00",
            "history": [{**extra, "event": "fed_tank"}],
        }}
        timeline = nps.feed_timeline(
            NOW, products={"phyto": product([{**extra, "kind": "dose", "to": "tank"}])},
            channels={}, hatchery=hatchery, brine_feeds=[extra], cultures=cultures,
        )
        for source in ("shelf:phyto", "brine", "cultures-bottle"):
            with self.subTest(source=source):
                events = [e for e in timeline["events"] if e["source"] == source]
                completed = [e for e in events if e["status"] == "done"]
                self.assertEqual(len(completed), 1)
                self.assertTrue(completed[0]["unplanned"])
                self.assertEqual(completed[0]["actualMl"], 100)
                self.assertEqual(len([e for e in events if not e["unplanned"]]), 2)
                self.assertTrue(all(e["status"] != "done" for e in events if not e["unplanned"]))

    def test_feed_log_keeps_extra_flag_without_changing_legacy_row_shape(self):
        normal = {"at": STAMP, "ml": 250}
        extra = {"at": NOW.isoformat(), "ml": 100, "extra": True}
        log = nps.feed_log(
            NOW, products={"phyto": product([{**r, "kind": "dose", "to": "tank"}
                                             for r in (normal, extra)])}, channels={},
            brine_feeds=[normal, extra],
            cultures={"bottle": {"history": [{**r, "event": "fed_tank"} for r in (normal, extra)]}},
        )
        self.assertEqual(log["counts"]["feeds"], 6)
        for source in ("shelf:phyto", "brine", "cultures-bottle"):
            rows = [r for r in log["rows"] if r["source"] == source]
            self.assertTrue(rows[0]["extra"])
            self.assertNotIn("extra", rows[1])

    def test_undone_extra_is_a_log_tombstone_and_not_a_timeline_feed(self):
        row = {"at": STAMP, "ml": 100, "kind": "dose", "to": "tank",
               "extra": True, "undoneAt": NOW.isoformat()}
        products = {"phyto": product([row])}
        timeline = nps.feed_timeline(NOW, products=products, channels={})
        self.assertFalse(any(e["status"] == "done" for e in timeline["events"]))
        log = nps.feed_log(NOW, products=products, channels={})
        self.assertTrue(log["rows"][0]["extra"])
        self.assertTrue(log["rows"][0]["undone"])
        self.assertEqual(log["counts"]["feeds"], 0)


if __name__ == "__main__":
    unittest.main()
