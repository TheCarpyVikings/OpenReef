"""Live cultures (v1): the rotifer / copepod jar engine, its normaliser, the
cultures_* WS handlers against the fake HA, the maintenance bridge and the
stale-save guard.

Covers: cultures.py pure maths (species presets, chore clocks anchored on
seed/restart, establishing vs producing, crash, tint-driven feed advice, the
heatwave line, the measured jug, the fail-closed bottle clock), the
normaliser (junk tolerance, caps, unknown species, the jar cap), every WS
action's ledger side-effects, and _nps_preserve_runtime carrying the
server-written state through a whole-config save.

Run standalone:  python3 tests/test_cultures.py
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
from openreef import cultures  # noqa: E402

from _fake_ha import FakeConnection, FakeEntry, FakeHass, run  # noqa: E402

CONF_SETTINGS = integration.CONF_SETTINGS
NOW = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
# The WS handlers stamp the wall clock, so their fixtures must be relative
# to the real "now" — the pure-maths tests pin NOW for exact hours.
REAL = datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _jar(species="rotifer_L", started_ago_days=None, now=None, **state):
    base = now or REAL
    jar = {"name": "Rotifers A", "species": species, "volumeL": 2.5, "salinityPpt": 35,
           "feed": {"productId": "phyto", "doseMl": 5}, "cadence": {}, "state": {}, "history": []}
    if started_ago_days is not None:
        jar["state"]["startedAt"] = _iso(base - timedelta(days=started_ago_days))
        jar["state"]["lastRestartAt"] = jar["state"]["startedAt"]
        jar["state"]["lastFedAt"] = jar["state"]["startedAt"]
    jar["state"].update(state)
    return jar


def _entry(jars=None, bottle=None, products=None, temp_entity="", maintenance=None):
    cfg = {
        "nps": {"enabled": True, "cultures": {
            "enabled": True, "tempEntity": temp_entity,
            "jars": jars if jars is not None else {"c1": _jar()},
            "bottle": bottle or {"volumeMl": 1000, "remainingMl": 0, "filledAt": "", "doseMl": 20},
        }},
        "consumables": {"products": products if products is not None else {
            "phyto": {"name": "Live phyto", "bottleMl": 500.0, "remainingMl": 300.0, "history": []},
        }},
    }
    if maintenance is not None:
        cfg["maintenance"] = maintenance
    return FakeEntry(options={CONF_SETTINGS: cfg})


def _cultures(entry):
    return entry.options[CONF_SETTINGS]["nps"]["cultures"]


# --------------------------------------------------------------------------- #
# cultures.py — pure maths
# --------------------------------------------------------------------------- #
def test_species_presets_carry_the_research_numbers():
    rot = cultures.species_preset("rotifer_L")
    pod = cultures.species_preset("tigriopus")
    assert rot["harvestIntervalDays"] == 1 and rot["restartIntervalDays"] == 14
    assert rot["waterChangeIntervalDays"] == 0, "the rotifer harvest IS the water change"
    assert pod["harvestIntervalDays"] == 7 and pod["waterChangeIntervalDays"] > 0
    assert pod["tempHardMaxC"] == 28, "the heatwave line"
    assert cultures.species_preset("nonsense")["id"] == "rotifer_L"
    assert set(cultures.species_ids()) == {"rotifer_L", "tigriopus"}


def test_cadence_overrides_merge_and_clamp():
    cad = cultures.cadence_for("rotifer_L", {"harvestPct": 40, "restartIntervalDays": 0,
                                             "feedIntervalH": 0, "harvestIntervalDays": "junk"})
    assert cad["harvestPct"] == 40
    assert cad["restartIntervalDays"] == 0, "a keeper may switch the restart off"
    assert cad["feedIntervalH"] == 12, "feed can never be 'never'"
    assert cad["harvestIntervalDays"] == 1


def test_culture_state_none_and_crashed():
    assert cultures.culture_state(_jar(now=NOW), NOW)["status"] == "none"
    crashed = _jar(started_ago_days=20, crashedAt=_iso(NOW - timedelta(days=1)), now=NOW)
    st = cultures.culture_state(crashed, NOW)
    assert st["status"] == "crashed" and st["ageDays"] == 19.0
    assert st["nextChore"] is None
    # A crash BEFORE the current seed stamp is history, not the present.
    reseeded = _jar(started_ago_days=1, crashedAt=_iso(NOW - timedelta(days=5)), now=NOW)
    assert cultures.culture_state(reseeded, NOW)["status"] == "establishing"


def test_culture_state_establishing_holds_the_harvest_back():
    st = cultures.culture_state(_jar(started_ago_days=1, now=NOW), NOW)
    assert st["status"] == "establishing"
    assert st["harvest"]["available"] and not st["harvest"]["due"]
    assert abs(st["harvest"]["hoursUntil"] - 48.0) < 0.1, "first harvest at day 3"
    assert st["feed"]["due"], "seeded 24 h ago on a 12 h feed clock"
    assert st["percent"] == 7, "1 of 14 days into the restart cycle"
    assert not st["splitEligible"]


def test_culture_state_producing_clocks_and_next_chore():
    jar = _jar(started_ago_days=12, lastFedAt=_iso(NOW - timedelta(hours=2)), now=NOW,
               lastHarvestAt=_iso(NOW - timedelta(hours=26)))
    st = cultures.culture_state(jar, NOW)
    assert st["status"] == "producing"
    assert st["harvest"]["due"] and st["harvest"]["hoursOverdue"] == 2.0
    assert not st["feed"]["due"] and st["feed"]["hoursUntil"] == 10.0
    assert st["restart"]["available"] and not st["restart"]["due"]
    assert abs(st["restart"]["hoursUntil"] - 48.0) < 0.1
    assert not st["waterChange"]["available"], "rotifers have no separate water change"
    assert st["nextChore"]["key"] == "harvest" and st["nextChore"]["due"]
    assert st["splitEligible"], "12 days old and not starving"


def test_culture_state_restart_anchor_moves_with_a_restart():
    jar = _jar(started_ago_days=30, lastRestartAt=_iso(NOW - timedelta(days=15)), now=NOW)
    st = cultures.culture_state(jar, NOW)
    assert st["restart"]["due"] and st["daysSinceRestart"] == 15.0
    assert st["percent"] == 100
    jar["state"]["lastRestartAt"] = _iso(NOW - timedelta(days=1))
    assert not cultures.culture_state(jar, NOW)["restart"]["due"]


def test_copepod_clocks_are_the_slow_lane():
    jar = _jar(species="tigriopus", started_ago_days=10, lastFedAt=_iso(NOW - timedelta(days=3)), now=NOW)
    st = cultures.culture_state(jar, NOW)
    assert st["status"] == "producing"
    assert st["feed"]["due"], "3 days on a 60 h clock"
    assert st["harvest"]["due"], "first harvest at day 7, never done since"
    assert not st["restart"]["available"], "copepods never sieve-restart"
    assert st["waterChange"]["available"] and not st["waterChange"]["due"]
    assert st["percent"] is None


def test_feed_advice_reads_the_tint():
    due = {"due": True}
    wait = {"due": False}
    assert cultures.feed_advice("clear", wait)["action"] == "feed_now"
    assert cultures.feed_advice("green", due)["action"] == "skip"
    assert cultures.feed_advice("green", wait)["action"] == "wait"
    assert cultures.feed_advice("clearing", due)["action"] == "feed_now"
    assert cultures.feed_advice("", due)["action"] == "feed_now"


def test_temperature_advice_has_a_hard_line():
    assert cultures.temperature_advice(None, "tigriopus")["available"] is False
    assert cultures.temperature_advice(23, "tigriopus")["status"] == "ok"
    assert cultures.temperature_advice(26.5, "tigriopus")["status"] == "warm"
    assert cultures.temperature_advice(28.0, "tigriopus")["status"] == "hot"
    assert cultures.temperature_advice(16, "rotifer_L")["status"] == "cool"
    assert cultures.temperature_advice("junk", "rotifer_L")["status"] == "unknown"


def test_refill_guide_is_the_measured_jug():
    full = cultures.refill_guide(2.5, 25, 35)
    assert full == {"totalMl": 625, "mixMl": 625, "rodiMl": 0, "targetPpt": 35.0}
    brackish = cultures.refill_guide(2.5, 25, 20)
    assert brackish["totalMl"] == 625 and brackish["mixMl"] == 357 and brackish["rodiMl"] == 268
    assert cultures.refill_guide(2.5, 0, 35)["totalMl"] == 0


def test_bottle_state_fails_closed():
    assert cultures.bottle_state({"remainingMl": 0}, 3, NOW)["status"] == "empty"
    assert cultures.bottle_state({"remainingMl": 300, "filledAt": ""}, 3, NOW)["status"] == "stale"
    fresh = cultures.bottle_state({"remainingMl": 300, "filledAt": _iso(NOW - timedelta(hours=6))}, 3, NOW)
    assert fresh["status"] == "fresh" and fresh["hoursLeft"] == 66.0
    aging = cultures.bottle_state({"remainingMl": 300, "filledAt": _iso(NOW - timedelta(hours=60))}, 3, NOW)
    assert aging["status"] == "aging"
    stale = cultures.bottle_state({"remainingMl": 300, "filledAt": _iso(NOW - timedelta(days=4))}, 3, NOW)
    assert stale["status"] == "stale" and stale["hoursLeft"] == 0.0


def test_stagger_days_between_siblings():
    a = _jar(started_ago_days=20, lastRestartAt=_iso(NOW - timedelta(days=9)), now=NOW)
    b = _jar(started_ago_days=2, now=NOW)
    assert cultures.stagger_days(a, b, NOW) == 7.0
    assert cultures.stagger_days(a, _jar(now=NOW), NOW) is None


# --------------------------------------------------------------------------- #
# _normalise_cultures
# --------------------------------------------------------------------------- #
def test_normalise_cultures_defaults_and_junk():
    out = integration._normalise_cultures(None)
    assert out == {"enabled": False, "tempEntity": "", "jars": {},
                   "bottle": {"volumeMl": 1000, "remainingMl": 0, "filledAt": "", "doseMl": 20}}
    out = integration._normalise_cultures({"enabled": 1, "jars": {
        "c1": {"name": "x" * 80, "species": "unicorn", "volumeL": 999, "cadence": {"harvestPct": 200},
               "state": {"lastTint": "purple", "startedAt": None}, "history": ["junk", {"event": "seeded"}]},
        "bad": "not a jar",
    }, "bottle": {"remainingMl": -5}})
    jar = out["jars"]["c1"]
    assert out["enabled"] is True and "bad" not in out["jars"]
    assert jar["species"] == "rotifer_L" and jar["volumeL"] == 50 and len(jar["name"]) == 40
    assert jar["cadence"]["harvestPct"] == 60 and jar["cadence"]["restartIntervalDays"] == 14
    assert jar["state"]["lastTint"] == "" and jar["state"]["startedAt"] == ""
    assert jar["history"] == [{"event": "seeded", "at": "", "ml": 0, "tint": "", "from": ""}]
    assert out["bottle"]["remainingMl"] == 0


def test_normalise_cultures_caps_the_jar_count_and_seeds_species_cadence():
    raw = {"jars": {f"c{n}": {"species": "tigriopus"} for n in range(1, 7)}}
    out = integration._normalise_cultures(raw)
    assert len(out["jars"]) == cultures.CULTURE_JARS_MAX
    assert out["jars"]["c1"]["cadence"]["harvestIntervalDays"] == 7
    assert out["jars"]["c1"]["salinityPpt"] == 35
    assert out["jars"]["c1"]["name"] == "Culture 1"


def test_core_normaliser_carries_cultures():
    cfg = integration._normalise_core_config({"nps": {"enabled": True}})
    assert cfg["nps"]["cultures"]["jars"] == {}
    assert cfg["nps"]["cultures"]["enabled"] is False


# --------------------------------------------------------------------------- #
# WS handlers
# --------------------------------------------------------------------------- #
def test_ws_seed_stamps_clocks_and_refuses_a_running_jar():
    entry = _entry()
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_seed(hass, conn, {"id": 1, "jar_id": "c1"}))
    state = _cultures(entry)["jars"]["c1"]["state"]
    assert state["startedAt"] and state["lastRestartAt"] == state["startedAt"]
    assert state["lastTint"] == "green" and state["seededFrom"] == ""
    assert _cultures(entry)["jars"]["c1"]["history"][0]["event"] == "seeded"
    run(integration.websocket_cultures_seed(hass, conn, {"id": 2, "jar_id": "c1"}))
    assert conn.errors[-1].code == "jar_busy"
    run(integration.websocket_cultures_seed(hass, conn, {"id": 3, "jar_id": "nope"}))
    assert conn.errors[-1].code == "unknown_jar"


def test_ws_log_tint_feed_debits_the_bottle_and_marks_the_reminder():
    maintenance = {"tasks": {"culture_c1_feed": {"label": "Feed rotifers", "snoozedUntil": _iso(REAL)}},
                   "completions": {}}
    entry = _entry(jars={"c1": _jar(started_ago_days=5)}, maintenance=maintenance)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_log(hass, conn, {"id": 1, "jar_id": "c1", "tint": "clear", "fed": True}))
    cfg = entry.options[CONF_SETTINGS]
    jar = cfg["nps"]["cultures"]["jars"]["c1"]
    assert jar["state"]["lastTint"] == "clear" and jar["state"]["lastFedAt"]
    assert cfg["consumables"]["products"]["phyto"]["remainingMl"] == 295.0
    comps = cfg["maintenance"]["completions"]["culture_c1_feed"]
    assert comps and comps[0]["source"] == "cultures"
    assert cfg["maintenance"]["tasks"]["culture_c1_feed"]["snoozedUntil"] is None
    assert jar["history"][0]["event"] == "feed" and jar["history"][0]["tint"] == "clear"
    run(integration.websocket_cultures_log(hass, conn, {"id": 2, "jar_id": "c1"}))
    assert conn.errors[-1].code == "nothing_to_log"


def test_ws_log_harvest_fills_the_bottle_oldest_wins_and_refuses_establishing():
    entry = _entry(jars={"c1": _jar(started_ago_days=1)})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_log(hass, conn, {"id": 1, "jar_id": "c1", "harvested": True}))
    assert conn.errors[-1].code == "establishing"
    _cultures(entry)["jars"]["c1"]["state"]["startedAt"] = _iso(REAL - timedelta(days=10))
    run(integration.websocket_cultures_log(hass, conn, {"id": 2, "jar_id": "c1", "harvested": True}))
    bottle = _cultures(entry)["bottle"]
    assert bottle["remainingMl"] == 625.0, "25% of 2.5 L by default"
    first_fill = bottle["filledAt"]
    assert first_fill
    jar = _cultures(entry)["jars"]["c1"]
    assert jar["state"]["lastHarvestAt"] and jar["history"][0]["ml"] == 625.0
    run(integration.websocket_cultures_log(hass, conn, {"id": 3, "jar_id": "c1", "harvested": True, "ml": 300}))
    bottle = _cultures(entry)["bottle"]
    assert bottle["remainingMl"] == 925.0
    assert bottle["filledAt"] == first_fill, "a top-up never resets the bottle clock"
    run(integration.websocket_cultures_log(hass, conn, {"id": 4, "jar_id": "c1", "harvested": True, "ml": 300}))
    assert _cultures(entry)["bottle"]["remainingMl"] == 1000.0, "clamped at the bottle"
    activity = entry.options[CONF_SETTINGS].get("activity") or []
    assert any("bottle full" in str(a.get("message", "")) for a in activity)


def test_ws_copepod_harvest_never_touches_the_rotifer_bottle():
    entry = _entry(jars={"c1": _jar(species="tigriopus", started_ago_days=10)})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_log(hass, conn, {"id": 1, "jar_id": "c1", "harvested": True}))
    assert not conn.errors
    assert _cultures(entry)["bottle"]["remainingMl"] == 0


def test_ws_restart_rewinds_the_fortnight_not_the_age():
    entry = _entry(jars={"c1": _jar(started_ago_days=20, lastRestartAt=_iso(REAL - timedelta(days=15)))})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_restart(hass, conn, {"id": 1, "jar_id": "c1"}))
    jar = _cultures(entry)["jars"]["c1"]
    assert jar["state"]["startedAt"] == _iso(REAL - timedelta(days=20))
    assert jar["state"]["lastRestartAt"] != _iso(REAL - timedelta(days=15))
    assert jar["state"]["lastTint"] == "green"
    assert jar["history"][0]["event"] == "restart" and jar["history"][0]["ml"] == 2500
    assert entry.options[CONF_SETTINGS]["consumables"]["products"]["phyto"]["remainingMl"] == 295.0


def test_ws_water_change_is_copepod_only():
    entry = _entry(jars={"c1": _jar(started_ago_days=10), "c2": _jar(species="tigriopus", started_ago_days=10)})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_water_change(hass, conn, {"id": 1, "jar_id": "c1"}))
    assert conn.errors[-1].code == "no_water_change"
    run(integration.websocket_cultures_water_change(hass, conn, {"id": 2, "jar_id": "c2"}))
    jar = _cultures(entry)["jars"]["c2"]
    assert jar["state"]["lastWaterChangeAt"]
    assert jar["history"][0]["event"] == "water_change" and jar["history"][0]["ml"] == 875


def test_ws_split_creates_b_from_a_producing_jar_and_refuses_otherwise():
    entry = _entry(jars={"c1": _jar(started_ago_days=2)})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_split(hass, conn, {"id": 1, "jar_id": "c1"}))
    assert conn.errors[-1].code == "not_producing"
    _cultures(entry)["jars"]["c1"]["state"]["startedAt"] = _iso(REAL - timedelta(days=12))
    run(integration.websocket_cultures_split(hass, conn, {"id": 2, "jar_id": "c1"}))
    jars = _cultures(entry)["jars"]
    assert set(jars) == {"c1", "c2"}
    assert jars["c2"]["name"] == "Rotifers B" and jars["c2"]["species"] == "rotifer_L"
    assert jars["c2"]["volumeL"] == 2.5 and jars["c2"]["feed"]["productId"] == "phyto"
    assert jars["c2"]["state"]["seededFrom"] == "c1" and jars["c2"]["state"]["startedAt"]
    assert jars["c1"]["history"][0]["event"] == "split" and jars["c1"]["history"][0]["from"] == "c2"
    assert jars["c1"]["state"]["startedAt"] == _iso(REAL - timedelta(days=12)), "the source keeps its clocks"
    # A second split reuses the idle sibling, never a third jar.
    run(integration.websocket_cultures_crash(hass, conn, {"id": 3, "jar_id": "c2"}))
    run(integration.websocket_cultures_split(hass, conn, {"id": 4, "jar_id": "c1"}))
    jars = _cultures(entry)["jars"]
    assert set(jars) == {"c1", "c2"} and jars["c2"]["state"]["crashedAt"] == ""


def test_ws_split_refuses_when_every_jar_is_used():
    jars = {f"c{n}": _jar(started_ago_days=12) for n in range(1, 5)}
    entry = _entry(jars=jars)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_split(hass, conn, {"id": 1, "jar_id": "c1"}))
    assert conn.errors[-1].code == "jars_full"


def test_ws_crash_then_reseed_from_a_sibling():
    entry = _entry(jars={"c1": _jar(started_ago_days=12), "c2": _jar(started_ago_days=5)})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_crash(hass, conn, {"id": 1, "jar_id": "c2"}))
    jar = _cultures(entry)["jars"]["c2"]
    assert jar["state"]["crashedAt"] and jar["history"][0]["event"] == "crashed"
    run(integration.websocket_cultures_crash(hass, conn, {"id": 2, "jar_id": "c2"}))
    assert conn.errors[-1].code == "jar_idle"
    run(integration.websocket_cultures_summary(hass, conn, {"id": 3}))
    payload = conn.results[-1].payload
    by_id = {j["id"]: j for j in payload["jars"]}
    assert by_id["c2"]["state"]["status"] == "crashed" and by_id["c2"]["reseedFrom"] == ["c1"]
    assert payload["idleJars"] == ["c2"]
    run(integration.websocket_cultures_seed(hass, conn, {"id": 4, "jar_id": "c2", "from_jar_id": "c1"}))
    jar = _cultures(entry)["jars"]["c2"]
    assert jar["state"]["crashedAt"] == "" and jar["state"]["seededFrom"] == "c1"


def test_ws_bottle_fed_and_empty():
    entry = _entry(bottle={"volumeMl": 1000, "remainingMl": 100, "filledAt": _iso(REAL), "doseMl": 20})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_bottle(hass, conn, {"id": 1, "action": "fed"}))
    assert _cultures(entry)["bottle"]["remainingMl"] == 80.0
    run(integration.websocket_cultures_bottle(hass, conn, {"id": 2, "action": "fed", "ml": 80}))
    bottle = _cultures(entry)["bottle"]
    assert bottle["remainingMl"] == 0 and bottle["filledAt"] == "", "empty clears the clock"
    bottle["remainingMl"] = 50
    bottle["filledAt"] = _iso(REAL)
    run(integration.websocket_cultures_bottle(hass, conn, {"id": 3, "action": "empty"}))
    assert _cultures(entry)["bottle"] == {"volumeMl": 1000, "remainingMl": 0, "filledAt": "", "doseMl": 20}


def test_ws_summary_computes_everything_backend_side():
    entry = _entry(
        jars={"c1": _jar(started_ago_days=12, lastFedAt=_iso(REAL - timedelta(hours=20)),
                         lastHarvestAt=_iso(REAL - timedelta(hours=30)), lastTint="clear"),
              "c2": _jar(species="tigriopus", started_ago_days=3)},
        bottle={"volumeMl": 1000, "remainingMl": 400, "filledAt": _iso(REAL - timedelta(hours=10)), "doseMl": 20},
        temp_entity="sensor.bench")
    hass = FakeHass(entries=[entry], states={"sensor.bench": "28.4"})
    conn = FakeConnection()
    run(integration.websocket_cultures_summary(hass, conn, {"id": 1}))
    p = conn.results[-1].payload
    assert p["enabled"] and p["maxJars"] == 4 and p["canAddJar"]
    assert p["tempC"] == 28.4
    by_id = {j["id"]: j for j in p["jars"]}
    rot, pod = by_id["c1"], by_id["c2"]
    assert rot["state"]["status"] == "producing"
    assert set(rot["due"]) == {"feed", "harvest"} and p["dueCount"] >= 2
    assert rot["feedAdvice"]["action"] == "feed_now"
    assert rot["temp"]["status"] == "warm" and pod["temp"]["status"] == "hot", "28.4 °C: rotifers warm, Tigriopus over the line"
    assert rot["harvestGuide"]["totalMl"] == 625 and rot["hasBottle"]
    assert not pod["hasBottle"] and pod["state"]["status"] == "establishing"
    assert rot["feed"]["productName"] == "Live phyto"
    assert p["bottle"]["status"] == "fresh" and p["bottle"]["remainingMl"] == 400
    assert [s["id"] for s in p["species"]] == ["rotifer_L", "tigriopus"]
    assert p["tints"] == ["green", "clearing", "clear"]


def test_ws_summary_falls_back_to_the_hatchery_sensor():
    entry = _entry()
    entry.options[CONF_SETTINGS]["nps"]["hatchery"] = {"tempEntity": "sensor.hatch"}
    hass = FakeHass(entries=[entry], states={"sensor.hatch": "22.0"})
    conn = FakeConnection()
    run(integration.websocket_cultures_summary(hass, conn, {"id": 1}))
    assert conn.results[-1].payload["tempC"] == 22.0


def test_ws_actions_refuse_an_idle_jar():
    entry = _entry()
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    for handler in (integration.websocket_cultures_log, integration.websocket_cultures_restart,
                    integration.websocket_cultures_water_change):
        run(handler(hass, conn, {"id": 1, "jar_id": "c1", "fed": True}))
        assert conn.errors[-1].code == "jar_idle"


# --------------------------------------------------------------------------- #
# Stale-save guard
# --------------------------------------------------------------------------- #
def test_cultures_runtime_survives_a_stale_save():
    stored = {"nps": {"cultures": {
        "enabled": True, "tempEntity": "",
        "jars": {"c1": {"name": "Rotifers A", "species": "rotifer_L", "volumeL": 2.5,
                        "state": {"startedAt": _iso(REAL), "lastTint": "clear"},
                        "history": [{"event": "seeded", "at": _iso(REAL)}]},
                 "c9": {"name": "Gone", "species": "rotifer_L", "state": {"startedAt": _iso(REAL)}}},
        "bottle": {"volumeMl": 1000, "remainingMl": 400, "filledAt": _iso(REAL), "doseMl": 20},
    }}}
    incoming = copy.deepcopy(stored)
    cult = incoming["nps"]["cultures"]
    cult["jars"]["c1"]["state"] = {"startedAt": ""}          # stale
    cult["jars"]["c1"]["history"] = []
    cult["jars"]["c1"]["name"] = "Left jar"                    # the client's edit
    cult["jars"]["c1"]["volumeL"] = 4.0
    del cult["jars"]["c9"]                                      # the client removed it
    cult["jars"]["c2"] = {"name": "New", "species": "tigriopus", "state": {}}
    cult["bottle"] = {"volumeMl": 2000, "remainingMl": 0, "filledAt": "", "doseMl": 30}
    integration._nps_preserve_runtime(stored, incoming)
    cult = incoming["nps"]["cultures"]
    assert cult["jars"]["c1"]["state"]["startedAt"] == _iso(REAL)
    assert cult["jars"]["c1"]["state"]["lastTint"] == "clear"
    assert cult["jars"]["c1"]["history"]
    assert cult["jars"]["c1"]["name"] == "Left jar" and cult["jars"]["c1"]["volumeL"] == 4.0
    assert "c9" not in cult["jars"] and cult["jars"]["c2"]["state"] == {}
    assert cult["bottle"]["remainingMl"] == 400 and cult["bottle"]["filledAt"] == _iso(REAL)
    assert cult["bottle"]["volumeMl"] == 2000 and cult["bottle"]["doseMl"] == 30
    # A client that predates the block entirely gets the stored one whole.
    older = {"nps": {"enabled": True}}
    integration._nps_preserve_runtime(stored, older)
    assert older["nps"]["cultures"]["bottle"]["remainingMl"] == 400


def test_cultures_runtime_survives_the_real_save_handler():
    entry = _entry(jars={"c1": _jar(started_ago_days=5)},
                   bottle={"volumeMl": 1000, "remainingMl": 300, "filledAt": _iso(REAL), "doseMl": 20})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    stale = copy.deepcopy(entry.options[CONF_SETTINGS])
    stale["nps"]["cultures"]["jars"]["c1"]["state"] = {}
    stale["nps"]["cultures"]["bottle"]["remainingMl"] = 0
    stale["nps"]["cultures"]["jars"]["c1"]["name"] = "Renamed"
    run(integration.websocket_save_config(hass, conn, {"id": 1, "config": stale}))
    cult = _cultures(entry)
    assert cult["jars"]["c1"]["state"]["startedAt"] == _iso(REAL - timedelta(days=5))
    assert cult["bottle"]["remainingMl"] == 300
    assert cult["jars"]["c1"]["name"] == "Renamed"


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
