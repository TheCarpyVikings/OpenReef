"""The coral diary (0.7.192): livestock.py pure maths, the coral_* WS
handlers against the fake HA, the stale-save guard and the digest's two
lines.

Covers: the group table and cadence resolution (own > arrival > group),
the colony score's losses and caps in Reef Health's grammar, the confidence
clock (a colony nobody looks at cannot grade A), trend, the check-in and
feed clocks, the summary's counts and due lists, the mouth in the keeper's
foods, every WS action's ledger side-effects (first look = baseline, undo
tombstones, a feed's optional shelf debit, a status change dropping the
rockwork slot), _livestock_preserve_runtime carrying the server-written
ledgers through a whole-config save, and the digest nags.

The score fixtures here are the SAME numbers tests/test_panel_corals.mjs
pins on the panel's mirror — change one, change both.

Run standalone:  python3 tests/test_livestock.py
Or with pytest:  pytest tests/
"""

from __future__ import annotations

import copy
import os
import sys
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
import openreef as integration  # noqa: E402
from openreef import livestock as L  # noqa: E402

from _fake_ha import FakeConnection, FakeEntry, FakeHass, run  # noqa: E402

CONF_SETTINGS = integration.CONF_SETTINGS
NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
REAL = datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _coral(species="torch", added_days_ago=100, now=None, **fields):
    base = now or NOW
    c = {"name": "Golden torch", "species": species, "colour": "gold", "status": "active",
         "addedAt": (base - timedelta(days=added_days_ago)).date().isoformat()}
    c.update(fields)
    return c


def _look(days_ago, now=None, **fields):
    base = now or NOW
    row = {"at": _iso(base - timedelta(days=days_ago)), "extension": 3, "tissue": "intact", "colour": 4,
           "fluor": "same", "feeding": "", "pests": "none", "neighbours": []}
    row.update(fields)
    return row


# --- groups and cadences ------------------------------------------------------

def test_groups_cover_every_art_species_and_nps_wins():
    for species in integration.CORAL_SPECIES:
        assert species in L.SPECIES_GROUP, species
        assert L.SPECIES_GROUP[species] in L.GROUPS
    assert L.group_id({"species": "torch"}) == "euphyllia"
    assert L.group_id({"species": "acan"}) == "lps_feeder"
    assert L.group_id({"species": "zoa"}) == "soft"
    # An NPS animal is NPS whatever it is drawn as.
    assert L.group_id({"species": "zoa", "npsId": "tubastraea"}) == "nps"


def test_check_cadence_own_beats_arrival_beats_group():
    settings = L.settings_view({})
    assert L.check_cadence(_coral("zoa"), settings, NOW) == {"days": 14, "reason": "group"}
    assert L.check_cadence(_coral("torch"), settings, NOW) == {"days": 7, "reason": "group"}
    assert L.check_cadence(_coral("zoa", added_days_ago=5), settings, NOW) == {"days": 3, "reason": "arrival"}
    assert L.check_cadence(_coral("zoa", added_days_ago=5, checkCadenceDays=10), settings, NOW) == {"days": 10, "reason": "own"}
    # The arrival window is the keeper's: 0 days switches it off.
    assert L.check_cadence(_coral("zoa", added_days_ago=5), L.settings_view({"arrivalDays": 0}), NOW)["reason"] == "group"


def test_feed_cadence_null_is_group_zero_is_off():
    assert L.feed_cadence(_coral("acan")) == {"days": 3, "reason": "group"}
    assert L.feed_cadence(_coral("acan", feedCadenceDays=0)) == {"days": 0, "reason": "own"}
    assert L.feed_cadence(_coral("acan", feedCadenceDays=None)) == {"days": 3, "reason": "group"}
    assert L.feed_cadence(_coral("zoa"))["days"] == 0


# --- the score ------------------------------------------------------------------

def test_score_perfect_look_is_100():
    out = L.score_checkin(_look(0), {}, "euphyllia")
    assert out == {"score": 100, "losses": [], "caps": []}


def test_score_losses_and_caps_name_their_signal():
    """The panel mirror pins these exact numbers (test_panel_corals.mjs)."""
    out = L.score_checkin(_look(0, extension=1, tissue="receding", colour=2, pests="suspected"), {}, "euphyllia")
    assert [l["points"] for l in out["losses"]] == [10, 20, 15, 12]
    assert out["score"] == 40                       # 100 - 57 = 43, capped at 40 by active recession
    assert [c["limit"] for c in out["caps"]] == [40, 50]
    # Retracted, a fish nipping and a shading neighbour, fluorescence fading.
    out = L.score_checkin(_look(0, extension=0, fluor="fading", neighbours=["nipped", "shaded", "stung"]), {}, "sps")
    assert out["score"] == 100 - 25 - 8 - 8 - 8 and not out["caps"]   # at most two neighbours count
    # Confirmed pests cap at 60 even on a colony that otherwise looks fine.
    out = L.score_checkin(_look(0, pests="confirmed"), {}, "soft")
    assert out["score"] == 60 and out["caps"][0]["limit"] == 60
    # RTN caps at 10.
    assert L.score_checkin(_look(0, tissue="rtn"), {}, "sps")["score"] == 10


def test_score_colour_is_judged_against_the_colonys_own_baseline():
    # Chart 4 against a baseline of 6: two steps paler.
    assert L.score_checkin(_look(0, colour=4), {"colour": 6}, "sps")["score"] == 85
    # Chart 4 against a baseline of 5: one step.
    assert L.score_checkin(_look(0, colour=4), {"colour": 5}, "sps")["score"] == 94
    # Chart 5 against the default baseline (4): darker than usual is fine.
    assert L.score_checkin(_look(0, colour=5), {}, "sps")["score"] == 100
    # Chart 2 is bleaching territory whatever the baseline said.
    assert L.score_checkin(_look(0, colour=2), {"colour": 2}, "sps")["score"] == 50


def test_ignored_food_only_counts_for_animals_that_are_fed():
    assert L.score_checkin(_look(0, feeding="ignored"), {}, "soft")["score"] == 100
    assert L.score_checkin(_look(0, feeding="ignored"), {}, "lps_feeder")["score"] == 92
    assert L.score_checkin(_look(0, feeding="ignored"), {}, "nps")["score"] == 92


# --- the colony state -----------------------------------------------------------

def test_state_unchecked_colony_has_no_score_and_is_due():
    st = L.coral_state(_coral(), [], [], NOW)
    assert st["score"] is None and st["grade"] == "—" and st["word"] == "unchecked"
    assert st["checkDue"] and st["checkOverdue"] and st["checkins"] == 0
    assert st["insights"][0]["label"] == "No check-in yet"


def test_state_confidence_clock_caps_a_forgotten_colony_at_70():
    """A perfect look 20 days ago on a weekly cadence: stale, capped, and
    reading 'watch' — a colony nobody looks at cannot grade A."""
    st = L.coral_state(_coral(), [_look(20)], [], NOW)
    assert st["stale"] and st["score"] == 70 and st["grade"] == "C" and st["word"] == "watch"
    assert st["checkDue"] and st["checkOverdue"]
    assert any(c["limit"] == 70 for c in st["caps"])
    assert st["trend"] is None                 # no trend claimed off a stale look
    # Inside twice the cadence it is merely due, not stale.
    st = L.coral_state(_coral(), [_look(9)], [], NOW)
    assert not st["stale"] and st["score"] == 100 and st["checkDue"] and not st["checkOverdue"]


def test_state_trend_and_words():
    rows = [_look(1), _look(8, extension=1, tissue="receding", colour=2, pests="suspected")]
    st = L.coral_state(_coral(), rows, [], NOW)
    assert st["score"] == 100 and st["trend"] == {"delta": 60, "word": "up"}
    assert st["word"] == "fine" and st["nextCheckAt"] == _iso(NOW + timedelta(days=6))
    st = L.coral_state(_coral(), list(reversed(rows)), [], NOW)   # newest first is sorted by stamp anyway
    assert st["score"] == 100, "rows are sorted by their stamps, not their order"
    needs = L.coral_state(_coral(), [_look(1, tissue="receding")], [], NOW)
    assert needs["word"] == "needs" and needs["score"] == 40
    watch = L.coral_state(_coral(), [_look(1, extension=1, colour=3, fluor="fading")], [], NOW)
    assert watch["score"] == 76 and watch["word"] == "fine"
    bleached = L.coral_state(_coral(), [_look(1, extension=1, colour=2)], [], NOW)
    assert bleached["score"] == 50 and bleached["word"] == "needs"       # the bleaching cap
    watch = L.coral_state(_coral(), [_look(1, extension=0, fluor="fading")], [], NOW)
    assert watch["score"] == 67 and watch["word"] == "watch"
    steady = L.coral_state(_coral(), [_look(1, extension=1), _look(8, colour=3)], [], NOW)
    assert steady["trend"] == {"delta": -4, "word": "down"}
    steady = L.coral_state(_coral(), [_look(1, colour=3), _look(8, colour=3)], [], NOW)
    assert steady["trend"] == {"delta": 0, "word": "steady"}


def test_state_tombstoned_rows_do_not_count():
    rows = [_look(1, tissue="rtn", undoneAt=_iso(NOW)), _look(8)]
    st = L.coral_state(_coral(), rows, [], NOW)
    assert st["score"] == 100 and st["checkins"] == 1 and st["checkDue"]


def test_state_feed_clock_anchors_on_the_last_feed_then_arrival():
    acan = _coral("acan", added_days_ago=40)
    st = L.coral_state(acan, [_look(1)], [], NOW)
    assert st["feedDays"] == 3 and st["feedDue"]
    assert st["nextFeedAt"].startswith((NOW - timedelta(days=37)).date().isoformat())   # anchored on arrival day
    st = L.coral_state(acan, [_look(1)], [{"at": _iso(NOW - timedelta(days=1))}], NOW)
    assert not st["feedDue"] and st["nextFeedAt"] == _iso(NOW + timedelta(days=2))
    st = L.coral_state(acan, [_look(1)], [{"at": _iso(NOW - timedelta(days=4))}], NOW)
    assert st["feedDue"]
    # Off, and never for an NPS animal (the feed plan owns those), never for a lost coral.
    assert L.coral_state(_coral("acan", feedCadenceDays=0), [], [], NOW)["feedDays"] == 0
    assert L.coral_state(_coral("suncoral", npsId="tubastraea"), [], [], NOW)["feedDue"] is False
    assert L.coral_state(_coral("acan", status="lost"), [], [], NOW)["feedDue"] is False


def test_summary_counts_and_due_lists():
    live = {
        "corals": {
            "a": _coral("torch", name="A"),
            "b": _coral("acan", name="B"),
            "c": _coral("zoa", name="C", status="lost"),
            "d": _coral("scoly", name="D", status="fragged"),
        },
        "checkins": {"a": [_look(1)], "b": [_look(20)]},
        "feeds": {},
    }
    s = L.summary(live, NOW)
    assert s["counts"] == {"active": 2, "fine": 1, "watch": 1, "needs": 0, "unchecked": 0, "lost": 1, "gone": 1}
    assert [d["id"] for d in s["dueChecks"]] == ["b"] and s["dueChecks"][0]["overdue"]
    assert [d["id"] for d in s["dueFeeds"]] == ["a", "b"]
    assert s["corals"]["c"]["status"] == "lost"


def test_mouth_and_shelf_use_the_nps_matchers_rule():
    assert "Mysis-sized meaty food fits" in L.mouth(_coral("scoly"))["note"]
    assert L.mouth(_coral("zoa"))["note"] == ""
    assert "Rotifers" in L.mouth(_coral("suncoral", npsId="tubastraea"))["note"]
    shelf = {
        "roids": {"name": "Reef Roids", "category": "zooPrepared", "particleUmMin": 150, "particleUmMax": 250},
        "mysis": {"name": "Frozen mysis", "category": "zooPrepared", "particleUmMin": 3000, "particleUmMax": 8000},
        "pellet": {"name": "LPS pellets", "category": "zooPrepared"},
        "phyto": {"name": "Phyto", "category": "phyto"},
    }
    foods = L.foods_on_shelf(_coral("scoly"), shelf)
    assert [(f["id"], f["fits"]) for f in foods] == [("mysis", True), ("pellet", True), ("roids", False)]
    assert [f["id"] for f in L.foods_on_shelf(_coral("clam"), shelf)] == ["phyto"]
    assert L.foods_on_shelf(_coral("zoa"), shelf) == []


# --- the WS handlers ---------------------------------------------------------------

def _rig(corals=None, **extra):
    cfg = integration._normalise_core_config({
        "livestock": {"corals": corals or {"torchy": _coral(now=REAL), "acan": _coral("acan", name="Acan garden", now=REAL)}},
        "diagram": {"layout": {"coral:torchy": "lps_1"}},
        **extra,
    })
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(entries=[entry])
    return hass, entry, FakeConnection()


def test_ws_checkin_scores_the_row_and_the_first_look_is_the_baseline():
    hass, entry, conn = _rig()
    run(integration.websocket_coral_checkin(hass, conn, {
        "id": 1, "coralId": "torchy", "extension": 2, "colour": 5, "tissue": "intact", "note": "opening well"}))
    assert not conn.errors, conn.errors
    saved = entry.options[CONF_SETTINGS]["livestock"]
    row = saved["checkins"]["torchy"][0]
    assert row["score"] == 100 and row["colour"] == 5 and row["note"] == "opening well"
    assert saved["corals"]["torchy"]["baseline"] == {"colour": 5, "extension": 2, "notes": ""}
    payload = conn.results[-1].payload
    assert payload["summary"]["corals"]["torchy"]["score"] == 100
    assert any("Checked in on Golden torch — 100/100, fine" in a["message"] for a in entry.options[CONF_SETTINGS]["activity"])
    # The second look is judged against that baseline: chart 3 is two steps paler.
    run(integration.websocket_coral_checkin(hass, conn, {"id": 2, "coralId": "torchy", "extension": 2, "colour": 3}))
    saved = entry.options[CONF_SETTINGS]["livestock"]
    assert saved["checkins"]["torchy"][0]["score"] == 85
    assert saved["corals"]["torchy"]["baseline"]["colour"] == 5, "the baseline is set once"


def test_ws_checkin_refuses_unknown_lost_and_stale_stamps():
    hass, entry, conn = _rig()
    run(integration.websocket_coral_checkin(hass, conn, {"id": 1, "coralId": "nope"}))
    assert conn.errors[-1].code == "unknown_coral"
    run(integration.websocket_coral_status(hass, conn, {"id": 2, "coralId": "acan", "status": "lost", "note": "RTN"}))
    run(integration.websocket_coral_checkin(hass, conn, {"id": 3, "coralId": "acan"}))
    assert conn.errors[-1].code == "not_active"
    run(integration.websocket_coral_checkin(hass, conn, {"id": 4, "coralId": "torchy",
                                                         "at": _iso(REAL - timedelta(hours=30))}))
    assert conn.errors[-1].code == "bad_stamp"
    run(integration.websocket_coral_checkin(hass, conn, {"id": 5, "coralId": "torchy",
                                                         "at": _iso(REAL - timedelta(hours=3))}))
    assert conn.results[-1].payload["success"]
    assert entry.options[CONF_SETTINGS]["livestock"]["checkins"]["torchy"][0]["at"] == _iso(REAL - timedelta(hours=3))


def test_ws_checkin_undo_tombstones_within_a_day():
    hass, entry, conn = _rig()
    run(integration.websocket_coral_checkin(hass, conn, {"id": 1, "coralId": "torchy", "tissue": "rtn"}))
    stamp = entry.options[CONF_SETTINGS]["livestock"]["checkins"]["torchy"][0]["at"]
    assert conn.results[-1].payload["summary"]["corals"]["torchy"]["word"] == "needs"
    run(integration.websocket_coral_checkin_undo(hass, conn, {"id": 2, "coralId": "torchy", "at": stamp}))
    row = entry.options[CONF_SETTINGS]["livestock"]["checkins"]["torchy"][0]
    assert row["undoneAt"] and row["tissue"] == "rtn", "a tombstone, not a deletion"
    assert conn.results[-1].payload["summary"]["corals"]["torchy"]["word"] == "unchecked"
    run(integration.websocket_coral_checkin_undo(hass, conn, {"id": 3, "coralId": "torchy", "at": stamp}))
    assert conn.errors[-1].code == "nothing_to_undo"
    run(integration.websocket_coral_checkin_undo(hass, conn, {"id": 4, "coralId": "torchy", "at": "2020-01-01T00:00:00+00:00"}))
    assert conn.errors[-1].code == "nothing_to_undo"


def test_ws_feed_logs_every_coral_and_debits_the_shelf_only_with_an_amount():
    hass, entry, conn = _rig(consumables={"products": {
        "mysis": {"name": "Frozen mysis", "category": "zooPrepared", "bottleMl": 100, "remainingMl": 100}}})
    run(integration.websocket_coral_feed(hass, conn, {"id": 1, "coralIds": ["torchy", "acan"], "productId": "mysis",
                                                      "response": "took"}))
    assert not conn.errors, conn.errors
    saved = entry.options[CONF_SETTINGS]
    assert saved["livestock"]["feeds"]["torchy"][0]["food"] == "Frozen mysis"
    assert saved["livestock"]["feeds"]["acan"][0]["response"] == "took"
    assert saved["livestock"]["feeds"]["acan"][0]["ml"] is None
    assert saved["consumables"]["products"]["mysis"]["remainingMl"] == 100, "a pinch is not a millilitre"
    assert conn.results[-1].payload["summary"]["corals"]["acan"]["feedDue"] is False
    run(integration.websocket_coral_feed(hass, conn, {"id": 2, "coralIds": ["acan"], "productId": "mysis", "ml": 2}))
    saved = entry.options[CONF_SETTINGS]
    assert saved["consumables"]["products"]["mysis"]["remainingMl"] == 98
    assert saved["consumables"]["products"]["mysis"]["history"][0]["to"] == "tank"
    assert saved["livestock"]["feeds"]["acan"][0]["ml"] == 2
    assert "Target-fed Acan garden — Frozen mysis, 2 ml" in saved["activity"][0]["message"]
    run(integration.websocket_coral_feed(hass, conn, {"id": 3, "coralIds": ["torchy"], "productId": "ghost"}))
    assert conn.errors[-1].code == "unknown_product"
    run(integration.websocket_coral_feed(hass, conn, {"id": 4, "coralIds": []}))
    assert conn.errors[-1].code == "no_corals"
    stamp = saved["livestock"]["feeds"]["acan"][0]["at"]
    run(integration.websocket_coral_feed_undo(hass, conn, {"id": 5, "coralId": "acan", "at": stamp}))
    assert entry.options[CONF_SETTINGS]["livestock"]["feeds"]["acan"][0]["undoneAt"]


def test_ws_status_keeps_the_record_and_drops_the_rockwork_slot():
    hass, entry, conn = _rig()
    run(integration.websocket_coral_checkin(hass, conn, {"id": 1, "coralId": "torchy"}))
    run(integration.websocket_coral_status(hass, conn, {"id": 2, "coralId": "torchy", "status": "lost",
                                                        "note": "RTN after the alk crash"}))
    saved = entry.options[CONF_SETTINGS]
    coral = saved["livestock"]["corals"]["torchy"]
    assert coral["status"] == "lost" and coral["statusNote"] == "RTN after the alk crash" and coral["statusAt"]
    assert "coral:torchy" not in saved["diagram"]["layout"]
    assert saved["livestock"]["checkins"]["torchy"], "the ledger stays — losing the record is losing the lesson"
    assert saved["activity"][0]["message"].startswith("Golden torch marked lost — RTN")
    assert conn.results[-1].payload["summary"]["counts"]["lost"] == 1
    # And back again.
    run(integration.websocket_coral_status(hass, conn, {"id": 3, "coralId": "torchy", "status": "active"}))
    assert entry.options[CONF_SETTINGS]["livestock"]["corals"]["torchy"]["status"] == "active"


def test_ws_summary_carries_foods_mouths_and_groups():
    hass, entry, conn = _rig(consumables={"products": {
        "mysis": {"name": "Frozen mysis", "category": "zooPrepared", "particleUmMin": 4000, "particleUmMax": 8000}}})
    run(integration.websocket_livestock_summary(hass, conn, {"id": 1}))
    payload = conn.results[-1].payload
    assert payload["foods"]["acan"][0]["id"] == "mysis" and payload["foods"]["acan"][0]["fits"]
    assert payload["foods"]["torchy"][0]["fits"] is False   # 4000–8000 µm is over a torch's window
    assert payload["mouths"]["acan"]["note"]
    assert payload["groups"]["lps_feeder"]["feedDays"] == 3 and payload["maxCorals"] == 60


def test_preserve_runtime_keeps_ledgers_photos_and_a_newer_status():
    hass, entry, conn = _rig()
    stale = copy.deepcopy(entry.options[CONF_SETTINGS])           # the wall's snapshot
    run(integration.websocket_coral_checkin(hass, conn, {"id": 1, "coralId": "torchy", "colour": 5}))
    run(integration.websocket_coral_feed(hass, conn, {"id": 2, "coralIds": ["acan"], "food": "mysis"}))
    run(integration.websocket_coral_status(hass, conn, {"id": 3, "coralId": "acan", "status": "lost"}))
    stored = entry.options[CONF_SETTINGS]
    stored["livestock"]["corals"]["torchy"]["photos"] = [{"url": "/openreef_captures/corals/torchy_x.jpg", "at": _iso(REAL), "note": ""}]
    stale["livestock"]["corals"]["torchy"]["name"] = "Renamed torch"   # the client's edit
    integration._livestock_preserve_runtime(stored, stale)
    live = stale["livestock"]
    assert live["checkins"]["torchy"][0]["colour"] == 5
    assert live["feeds"]["acan"][0]["food"] == "mysis"
    assert live["corals"]["torchy"]["photos"][0]["url"].endswith("torchy_x.jpg")
    assert live["corals"]["torchy"]["baseline"]["colour"] == 5, "the first look's baseline survives"
    assert live["corals"]["torchy"]["name"] == "Renamed torch", "the client's edit stands"
    assert live["corals"]["acan"]["status"] == "lost", "a status stamped after the snapshot wins"
    # A client that carries a NEWER status keeps it.
    stale2 = copy.deepcopy(stored)
    stale2["livestock"]["corals"]["acan"]["status"] = "active"
    stale2["livestock"]["corals"]["acan"]["statusAt"] = _iso(REAL + timedelta(minutes=5))
    integration._livestock_preserve_runtime(stored, stale2)
    assert stale2["livestock"]["corals"]["acan"]["status"] == "active"
    # The whole-config save runs the guard end to end.
    stale3 = copy.deepcopy(stale)
    del stale3["livestock"]["checkins"]
    run(integration.websocket_save_config(hass, conn, {"id": 9, "config": stale3}))
    assert entry.options[CONF_SETTINGS]["livestock"]["checkins"]["torchy"][0]["colour"] == 5


def test_digest_nags_one_line_each_and_off_with_the_switches():
    cfg = integration._normalise_core_config({"livestock": {
        "corals": {"a": _coral("torch", name="A"), "b": _coral("acan", name="B"), "c": _coral("zoa", name="C")},
        "checkins": {"c": [_look(1)]},
    }})
    nags = integration._maintenance_coral_nags(cfg, NOW)
    assert [n["id"] for n in nags] == ["coral_check", "coral_feed"]
    assert nags[0]["detail"] == "2 due — A, B" and nags[0]["severity"] == "critical"
    assert nags[1]["detail"] == "2 due — A, B"        # a torch feeds weekly, an acan every three days
    cfg["livestock"]["settings"]["remind"] = False
    assert [n["id"] for n in integration._maintenance_coral_nags(cfg, NOW)] == ["coral_feed"]
    cfg["livestock"]["settings"]["feedRemind"] = False
    assert integration._maintenance_coral_nags(cfg, NOW) == []
    assert integration._maintenance_coral_nags(integration._normalise_core_config({}), NOW) == []


def test_digest_push_carries_the_coral_lines():
    hass, entry, conn = _rig(maintenance={"enabled": True, "reminders": {"enabled": True, "notifyTarget": "mobile_app_phone"}})
    run(integration._async_fire_maintenance_reminder(hass, entry, REAL))
    pushes = [c for c in hass.services.calls if c.domain == "notify"]
    assert pushes, "the digest pushed"
    data = pushes[-1].data
    assert "coral check-ins" in data["title"] and "target feeds" in data["title"]
    assert "Coral check-ins: 2 due — Golden torch, Acan garden" in data["message"]
    assert any("Coral check-ins: 2 due" in row["message"] for row in entry.options[CONF_SETTINGS]["activity"])


# Keep this LAST: a test defined below the runner is a test that never runs.
if __name__ == "__main__":
    failures = 0
    names = [name for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    for name in names:
        try:
            globals()[name]()
            print(f"  ok  {name}")
        except Exception as err:  # noqa: BLE001 - report every failure kind
            failures += 1
            print(f"FAIL  {name}: {type(err).__name__}: {err}")
    print(f"\n{len(names) - failures}/{len(names)} passed")
    raise SystemExit(1 if failures else 0)
