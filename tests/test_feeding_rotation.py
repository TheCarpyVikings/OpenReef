"""Calendar rotation and notification contracts, using fake Home Assistant.

Run: python3 tests/test_feeding_rotation.py
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import test_nps as t
from _fake_ha import FakeConnection, FakeEntry, FakeHass, run

integration = t.integration
feeding = integration.feeding_engine
CONF_SETTINGS = integration.CONF_SETTINGS
LONDON = ZoneInfo("Europe/London")


def rotation(**changes):
    return {"enabled": True, "startDate": "2026-10-01", "startPhase": "marine",
            "marineFoodIds": ["manual:marine"], "platinumFoodIds": ["manual:platinum"],
            "notify": False, **changes}


def catalog():
    return [{"id": fid, "enabled": True, "tankFeed": True, "loggable": True,
             "sources": [{"id": fid, "tankFeed": True, "loggable": True, "available": False}]}
            for fid in ("manual:marine", "manual:platinum")]


class CalendarRotation(unittest.TestCase):
    def state(self, day, **changes):
        return feeding.rotation_summary(datetime.fromisoformat(day).replace(tzinfo=LONDON),
                                        rotation(**changes), catalog())

    def test_marine_platinum_boundaries_and_repeated_cycle(self):
        cases = [(0, "marine", 1, 1, 1, 28), (27, "marine", 28, 4, 28, 1),
                 (28, "platinum", 29, 5, 1, 14), (41, "platinum", 42, 6, 14, 1),
                 (42, "marine", 1, 1, 1, 28), (70, "platinum", 29, 5, 1, 14),
                 (420, "marine", 1, 1, 1, 28)]
        for delta, phase, cycle_day, week, phase_day, remaining in cases:
            with self.subTest(delta=delta):
                now = datetime(2026, 10, 1, tzinfo=LONDON) + timedelta(days=delta)
                state = feeding.rotation_summary(now, rotation(), catalog())
                self.assertEqual((state["phase"], state["cycleDay"], state["cycleWeek"],
                                  state["phaseDay"], state["daysUntilSwitch"]),
                                 (phase, cycle_day, week, phase_day, remaining))
                self.assertEqual(state["suggestedFoodIds"], ["manual:" + phase])
                self.assertEqual(state["nextSwitchDate"], (now.date() + timedelta(days=remaining)).isoformat())

    def test_start_in_platinum_and_resume_mid_phase_across_year(self):
        for day, phase, cycle_day, phase_day in (
            ("2026-12-20", "platinum", 29, 1), ("2027-01-02", "platinum", 42, 14),
            ("2027-01-03", "marine", 1, 1), ("2027-01-30", "marine", 28, 28),
            ("2027-01-31", "platinum", 29, 1),
        ):
            state = self.state(day, startDate="2026-12-20", startPhase="platinum")
            self.assertEqual((state["phase"], state["cycleDay"], state["phaseDay"]), (phase, cycle_day, phase_day))
        state = self.state("2026-10-10")
        self.assertEqual((state["phaseDay"], state["phaseStartDate"]), (10, "2026-10-01"))

    def test_local_midnight_dst_and_leap_day_use_calendar_days(self):
        cfg = rotation(startDate="2026-03-01")
        before = datetime(2026, 3, 28, 23, 59, tzinfo=timezone.utc).astimezone(LONDON)
        after = datetime(2026, 3, 29, 0, 0, tzinfo=timezone.utc).astimezone(LONDON)
        self.assertEqual(feeding.rotation_summary(before, cfg, catalog())["phase"], "marine")
        self.assertEqual(feeding.rotation_summary(after, cfg, catalog())["phase"], "platinum")
        summer = datetime(2026, 6, 28, 23, 1, tzinfo=timezone.utc).astimezone(LONDON)
        self.assertEqual(feeding.rotation_summary(summer, rotation(startDate="2026-06-01"), catalog())["phase"], "platinum")
        first_one = datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc).astimezone(LONDON)
        second_one = datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc).astimezone(LONDON)
        self.assertEqual(feeding.rotation_summary(first_one, rotation(), catalog()),
                         feeding.rotation_summary(second_one, rotation(), catalog()))
        self.assertEqual(self.state("2028-02-29", startDate="2028-02-01")["phase"], "platinum")

    def test_disabled_future_and_missing_foods_never_invent_feeds(self):
        future = self.state("2026-09-30")
        self.assertEqual((future["status"], future["phase"], future["nextPhase"], future["daysUntilSwitch"]),
                         ("upcoming", None, "marine", 1))
        self.assertEqual(future["suggestedFoodIds"], [])
        self.assertEqual(self.state("2026-10-01", enabled=False)["status"], "disabled")
        cfg = rotation(marineFoodIds=["manual:marine", "deleted"])
        original = deepcopy(cfg)
        state = feeding.rotation_summary(datetime(2026, 10, 1, tzinfo=LONDON), cfg, catalog())
        self.assertEqual(state["status"], "needs_foods")
        self.assertEqual(state["invalidFoodIds"], ["deleted"])
        self.assertEqual(state["suggestedFoodIds"], ["manual:marine"])
        self.assertEqual(cfg, original)
        self.assertEqual(self.state("2026-10-01")["status"], "active", "empty stock must not stop a calendar")

    def test_validation_and_junk_normalisation(self):
        for fields in ({"startDate": "2026-02-30"}, {"startDate": "2026-1-01"},
                       {"startDate": "2026-10-01T12:00:00Z"}, {"startPhase": "other"},
                       {"marineFoodIds": []}, {"platinumFoodIds": ["manual:marine"]},
                       {"marineFoodIds": ["unknown"]}, {"marineFoodIds": "manual:marine"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                feeding.validate_rotation(rotation(**fields), catalog())
        off = feeding.validate_rotation(rotation(enabled=False, startDate="bad", marineFoodIds=["deleted"]), [])
        self.assertFalse(off["enabled"])
        self.assertEqual(off["marineFoodIds"], ["deleted"])
        self.assertEqual(off["startDate"], "")
        self.assertFalse(feeding.normalise_rotation(None)["enabled"])
        self.assertFalse(feeding.normalise_rotation({"enabled": "true", "startDate": "2026-10-01"})["enabled"])
        self.assertFalse(feeding.normalise_rotation({"enabled": True, "startDate": "invalid"})["enabled"])


class RotationAPI(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
        owner = self

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return owner.now.astimezone(tz) if tz else owner.now.replace(tzinfo=None)

        self.addCleanup(patch.stopall)
        patch.object(integration, "datetime", Clock).start()
        patch.object(integration.dt_util, "as_local", lambda stamp: stamp.astimezone(LONDON)).start()
        patch.object(integration.dt_util, "now", lambda: self.now.astimezone(LONDON)).start()
        patch.object(integration.dt_util, "utcnow", lambda: self.now).start()
        cfg = integration._normalise_core_config({
            "watchdog": {"enabled": False}, "tank": {"volumeLitres": 52},
            "feeding": {"foods": {
                "marine": {"name": "Vitalis Marine flake", "unit": "pinch", "portion": 1},
                "platinum": {"name": "Vitalis Platinum pellets", "unit": "pinch", "portion": 2},
            }},
            "consumables": {"products": {"f2": t._product(name="Guillard's f/2", category="other")}},
        })
        self.entry = FakeEntry(options={CONF_SETTINGS: cfg})
        self.hass = FakeHass(entries=[self.entry])
        self.hass.config.time_zone = "Europe/London"
        self.next_id = 0

    def saved(self):
        return self.entry.options[CONF_SETTINGS]

    def call(self, api_name, error=None, **msg):
        connection = FakeConnection()
        self.next_id += 1
        run(getattr(integration, "websocket_" + api_name)(self.hass, connection, {"id": self.next_id, **msg}))
        if error:
            self.assertIn(error, connection.error_codes)
        else:
            self.assertEqual(connection.errors, [], [(e.code, e.message) for e in connection.errors])
            self.assertTrue(connection.results)
        return connection.results[-1].payload if connection.results else None

    def save_rotation(self, error=None, **fields):
        return self.call("feeding_rotation_save", error=error, **{
            "enabled": True, "start_date": "2026-10-01", "start_phase": "marine",
            "marine_food_ids": ["manual:marine"], "platinum_food_ids": ["manual:platinum"], **fields})

    def notifications(self):
        return [c for c in self.hass.services.calls if c.domain == "persistent_notification"
                and c.service == "create" and c.data.get("notification_id") == "openreef_feeding_rotation"]

    def tick(self, days=0):
        self.now += timedelta(days=days)
        return run(integration._async_feeding_rotation_tick(self.hass, self.entry, self.now))

    def test_setup_defaults_and_summary_are_guidance_only(self):
        self.call("feeding_log", food_id="manual:marine", source_id="manual:marine", amount=1, extra=True)
        before = deepcopy(self.saved())
        result = self.save_rotation()
        self.assertEqual(result["rotation"]["phase"], "marine")
        self.assertFalse(self.saved()["feeding"]["rotation"]["notify"])
        self.assertEqual(self.saved()["feeding"]["rows"], before["feeding"]["rows"])
        self.assertEqual(self.saved()["feeding"]["foods"], before["feeding"]["foods"])
        for key in ("consumables", "dosing", "nps"):
            self.assertEqual(self.saved()[key], before[key], key)
        self.assertFalse(self.notifications())
        state = self.call("feeding_summary", days=30)
        self.assertEqual(state["rotation"]["suggestedFoodIds"], ["manual:marine"])
        self.assertEqual(state["rotation"]["cycleDay"], 1)
        self.assertEqual(state["totals"][0]["amount"], 1)

    def test_invalid_food_dates_overlap_and_culture_supply_reject_without_changes(self):
        for fields in ({"start_date": "2026-02-30"}, {"marine_food_ids": []},
                       {"platinum_food_ids": ["manual:marine"]}, {"marine_food_ids": ["deleted"]},
                       {"marine_food_ids": ["product:f2"]}):
            with self.subTest(fields=fields):
                before = deepcopy(self.saved())
                self.save_rotation(error="invalid_rotation", **fields)
                self.assertEqual(self.saved(), before)
        self.saved()["feeding"]["preferences"]["manual:marine"] = {"tankFeed": False}
        self.save_rotation(error="invalid_rotation")

    def test_rotation_and_marker_survive_stale_settings_and_other_feeding_saves(self):
        stale = deepcopy(self.saved())
        self.save_rotation(notify=True)
        self.assertTrue(self.tick(28))
        expected = deepcopy(self.saved()["feeding"]["rotation"])
        self.call("save_config", config=deepcopy(stale))
        self.assertEqual(self.saved()["feeding"]["rotation"], expected)
        run(integration._async_save_config(self.hass, self.entry, deepcopy(stale)))
        self.assertEqual(self.saved()["feeding"]["rotation"], expected)
        integration._persist_entry_config(self.hass, self.entry, deepcopy(stale))
        self.assertEqual(self.saved()["feeding"]["rotation"], expected)
        self.call("feeding_food_save", food_id="manual:marine", name="Marine flake", unit="pinch", portion=3)
        self.assertEqual(self.saved()["feeding"]["rotation"], expected)
        self.assertFalse(self.tick())

    def test_switch_notification_once_restart_and_next_cycles(self):
        self.save_rotation(notify=True)
        self.assertFalse(self.tick())
        self.assertFalse(self.tick(27))
        self.assertTrue(self.tick(1))
        self.assertFalse(self.tick())
        self.hass = FakeHass(entries=[self.entry])  # restart: no in-memory dedup remains
        self.assertFalse(self.tick())
        self.assertTrue(self.tick(14))
        self.assertTrue(self.tick(28))
        self.assertEqual(len(self.notifications()), 2)
        self.assertTrue(all(c.domain == "persistent_notification" for c in self.hass.services.calls))
        self.assertFalse(self.saved()["feeding"]["rows"])

    def test_future_start_initial_setup_date_adjust_and_notify_enable_are_quiet(self):
        self.save_rotation(notify=True, start_date="2026-10-02", start_phase="platinum")
        self.assertFalse(self.tick())
        self.assertFalse(self.tick(1), "initial start is not a switch reminder")
        self.assertTrue(self.tick(14))
        self.save_rotation(notify=True, start_date="2026-10-16", start_phase="marine")
        self.assertFalse(self.tick(), "adjusted date seeds the current phase silently")
        self.save_rotation(notify=False, start_date="2026-10-16")
        self.tick(28)
        count = len(self.notifications())
        self.save_rotation(notify=True, start_date="2026-10-16")
        self.assertFalse(self.tick(), "enabling alerts today must not replay today's switch")
        self.assertEqual(len(self.notifications()), count)

    def test_no_backlog_unconfigured_marker_or_missing_food_notifications(self):
        self.save_rotation(notify=True)
        self.assertFalse(self.tick(29), "the missed switch yesterday is not replayed")
        self.assertEqual(self.saved()["feeding"]["rotation"]["observedPhaseStartDate"], "2026-10-29")
        self.assertFalse(self.tick(56), "several missed phases do not create a backlog")
        self.saved()["feeding"]["rotation"]["observedPhaseStartDate"] = ""
        self.assertFalse(self.tick(), "unknown state establishes a quiet baseline")
        self.save_rotation(notify=True, start_date=self.now.date().isoformat())
        self.saved()["feeding"]["foods"].pop("platinum")
        self.assertFalse(self.tick(28))
        self.assertEqual(self.call("feeding_summary")["rotation"]["status"], "needs_foods")
        self.assertFalse(self.notifications())
        self.save_rotation(enabled=False, start_date="broken", platinum_food_ids=["deleted"])
        self.assertFalse(self.saved()["feeding"]["rotation"]["enabled"])

    def test_local_switch_day_and_clock_rewind_do_not_duplicate(self):
        self.now = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)
        self.save_rotation(notify=True, start_date="2026-06-01")
        self.now = datetime(2026, 6, 28, 23, 1, tzinfo=timezone.utc)  # June29 in HA
        self.assertTrue(self.tick())
        self.now -= timedelta(days=1)
        self.assertFalse(self.tick())
        self.now += timedelta(days=1)
        self.assertFalse(self.tick())
        self.assertEqual(len(self.notifications()), 1)

    def test_latest_settings_and_simultaneous_disable_survive_notification_await(self):
        self.save_rotation(notify=True)
        original_call = self.hass.services.async_call

        async def update_during_call(domain, service, data, **kwargs):
            await original_call(domain, service, data, **kwargs)
            latest = deepcopy(self.saved())
            latest["tank"]["name"] = "Changed while notifying"
            self.entry.options = {**self.entry.options, CONF_SETTINGS: latest}

        self.hass.services.async_call = update_during_call
        self.assertTrue(self.tick(28))
        self.assertEqual(self.saved()["tank"]["name"], "Changed while notifying")
        self.assertEqual(self.saved()["feeding"]["rotation"]["observedPhaseStartDate"], "2026-10-29")

        async def disable_during_call(domain, service, data, **kwargs):
            await original_call(domain, service, data, **kwargs)
            self.saved()["feeding"]["rotation"].update(enabled=False, startDate="2026-11-01",
                                                       observedPhaseStartDate="2026-11-01")

        self.hass.services.async_call = disable_during_call
        self.assertTrue(self.tick(14))
        self.assertFalse(self.saved()["feeding"]["rotation"]["enabled"])
        self.assertEqual(self.saved()["feeding"]["rotation"]["observedPhaseStartDate"], "2026-11-01")

    def test_notification_failure_retries_and_concurrent_ticks_do_not_duplicate(self):
        self.save_rotation(notify=True)
        original_call = self.hass.services.async_call

        async def fail(*args, **kwargs):
            raise RuntimeError("notification service unavailable")

        self.hass.services.async_call = fail
        self.assertFalse(self.tick(28))
        self.assertEqual(self.saved()["feeding"]["rotation"]["observedPhaseStartDate"], "2026-10-01")
        self.hass.services.async_call = original_call

        async def together():
            return await asyncio.gather(*[integration._async_feeding_rotation_tick(self.hass, self.entry, self.now)
                                         for _ in range(3)])

        self.assertEqual(run(together()), [True, False, False])
        self.assertEqual(len(self.notifications()), 1)

    def test_watcher_arms_without_dosing_hardware_and_disarms_when_notifications_off(self):
        self.assertFalse(integration._dosing_channels(self.saved()))
        records = []

        def track(hass, callback, interval):
            record = {"callback": callback, "interval": interval, "cancelled": False}
            records.append(record)
            return lambda: record.update(cancelled=True)

        with patch.object(integration, "async_track_time_interval", track):
            self.save_rotation(notify=True)
            self.assertTrue(records)
            current = records[-1]
            self.assertEqual(current["interval"], timedelta(seconds=integration.DOSING_TICK_SECONDS))
            self.now += timedelta(days=28)
            with patch.object(integration, "_async_dosing_tick", side_effect=AssertionError("no hardware tick")):
                run(current["callback"](self.now))
            self.assertEqual(len(self.notifications()), 1)
            self.save_rotation(notify=False)
            self.assertTrue(current["cancelled"])
            self.assertNotIn(integration.DOSING_TICK_UNSUB, self.hass.data[integration.DOMAIN])


if __name__ == "__main__":
    unittest.main()
