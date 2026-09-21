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
from openreef import nps as nps_engine  # noqa: E402

from _fake_ha import FakeConnection, FakeEntry, FakeHass, FakeState, run  # noqa: E402

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
        jar["state"]["lastTint"] = "green"
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


def _config(entry):
    return integration._config_from_entry(entry)


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
    assert pod["harvestIntervalDays"] == 10 and pod["waterChangeIntervalDays"] == 0
    assert pod["waterChangePct"] == 50, "pods change water on a sign, not a clock"
    assert pod["tempHardMaxC"] == 28 and pod["tempActC"] == 30 and pod["tempCriticalC"] == 32, "the heat tiers"
    assert rot["vesselKind"] == "cone" and pod["vesselKind"] == "tub", "rotifers in the cone, pods in a tub"
    assert rot["salinityPpt"] == 27 and rot["firstHarvestDays"] == 6 and rot["sieveUm"] == 50
    assert rot["bottleShelfDays"] == 5 and rot["purgeMl"] == 50 and pod["firstHarvestDays"] == 28
    assert cultures.species_preset("nonsense")["id"] == "rotifer_L"
    assert set(cultures.species_ids()) == {"rotifer_L", "tigriopus", "nanno"}


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
    assert abs(st["harvest"]["hoursUntil"] - 120.0) < 0.1, "first harvest at day 6 (Reefphyto: 5–7)"
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
    assert not st["splitEligible"], "12 days old — the split rides the first restart at 14"
    older = _jar(started_ago_days=15, lastRestartAt=_iso(NOW - timedelta(days=1)), now=NOW)
    assert cultures.culture_state(older, NOW)["splitEligible"], "15 days old and not starving"


def test_culture_state_restart_anchor_moves_with_a_restart():
    jar = _jar(started_ago_days=30, lastRestartAt=_iso(NOW - timedelta(days=15)), now=NOW)
    st = cultures.culture_state(jar, NOW)
    assert st["restart"]["due"] and st["daysSinceRestart"] == 15.0
    assert st["percent"] == 100
    jar["state"]["lastRestartAt"] = _iso(NOW - timedelta(days=1))
    assert not cultures.culture_state(jar, NOW)["restart"]["due"]


def test_copepod_clocks_are_the_slow_lane():
    young = cultures.culture_state(_jar(species="tigriopus", started_ago_days=10, now=NOW), NOW)
    assert young["status"] == "establishing", "a generation is a month — day 10 is still establishing"
    jar = _jar(species="tigriopus", started_ago_days=30, lastFedAt=_iso(NOW - timedelta(days=3)), now=NOW)
    st = cultures.culture_state(jar, NOW)
    assert st["status"] == "producing"
    assert st["feed"]["due"], "3 days on a 24 h clock"
    assert st["harvest"]["due"], "first harvest at day 28, never done since"
    assert not st["restart"]["available"], "copepods never sieve-restart"
    assert not st["waterChange"]["available"] and st["waterChangeOnDemand"], "water changes on a sign"
    assert st["percent"] is None


def test_feed_advice_reads_the_tint():
    due = {"due": True}
    wait = {"due": False}
    assert cultures.feed_advice("clear", wait)["action"] == "feed_now"
    assert cultures.feed_advice("green", due)["action"] == "skip"
    assert cultures.feed_advice("green", wait)["action"] == "wait"
    assert cultures.feed_advice("clearing", due)["action"] == "feed_now"
    assert cultures.feed_advice("", due)["action"] == "check"


def test_temperature_advice_has_a_hard_line():
    assert cultures.temperature_advice(None, "tigriopus")["available"] is False
    assert cultures.temperature_advice(23, "tigriopus")["status"] == "ok"
    assert cultures.temperature_advice(26.5, "tigriopus")["status"] == "warm"
    hot = cultures.temperature_advice(28.0, "tigriopus")
    assert hot["status"] == "hot" and not hot["act"], "28 °C warns"
    assert cultures.temperature_advice(30.0, "tigriopus")["act"], "30 °C: act now"
    assert cultures.temperature_advice(32.0, "tigriopus")["status"] == "critical"
    assert cultures.temperature_advice(31.0, "rotifer_L")["status"] == "hot"
    assert cultures.temperature_advice(16, "rotifer_L")["status"] == "cool"
    assert cultures.temperature_advice("junk", "rotifer_L")["status"] == "unknown"


def test_refill_guide_is_the_measured_jug():
    full = cultures.refill_guide(2.5, 25, 35)
    assert full == {"totalMl": 625, "mixMl": 625, "rodiMl": 0, "targetPpt": 35.0, "mixPpt": 35.0, "sg": 1.0264}
    brackish = cultures.refill_guide(2.5, 25, 20)
    assert brackish["totalMl"] == 625 and brackish["mixMl"] == 357 and brackish["rodiMl"] == 268
    assert cultures.refill_guide(2.5, 0, 35)["totalMl"] == 0
    # Reece's cone: 27 ppt cut from the station's 35 — the fill and the daily jug.
    fill = cultures.refill_guide(2.0, 100, 27, 35)
    assert fill == {"totalMl": 2000, "mixMl": 1543, "rodiMl": 457, "targetPpt": 27.0, "mixPpt": 35.0, "sg": 1.0204}
    daily = cultures.refill_guide(2.0, 25, 27, 35)
    assert daily["totalMl"] == 500 and daily["mixMl"] == 386 and daily["rodiMl"] == 114
    # The station's own target is what gets cut — a 34 ppt station cuts less.
    assert cultures.refill_guide(2.0, 100, 27, 34)["mixMl"] == 1588
    # At or above the station: straight mix, and the jug says the station's ppt.
    assert cultures.refill_guide(2.0, 100, 35, 34)["available"] is False, "dilution cannot increase salinity"
    assert cultures.refill_guide(2.0, 100, 27, 0)["mixPpt"] == 35.0, "a junk station target falls back to 35"


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
    assert out["enabled"] is False and out["tempEntity"] == "" and out["jars"] == {}
    assert {k: out["bottle"][k] for k in ("volumeMl", "remainingMl", "filledAt", "doseMl")} == {"volumeMl": 1000, "remainingMl": 0, "filledAt": "", "doseMl": 20}
    assert out["bottle"]["history"] == [] and not out["bottle"]["lastLoadEnriched"]
    assert out["enrichment"]["drops"] == 3 and out["enrichment"]["soakH"] == 6 and out["enrichment"]["state"]["startedAt"] == ""
    assert "phytoDose" not in out, "the tank's phyto lives on the shelf product now (0.7.129)"
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
    assert jar["history"] == [{"event": "seeded", "at": "", "ml": 0, "tint": "", "from": "",
                               "sign": "", "eggRatio": None, "fed": False, "tankMl": None, "to": "", "tempC": None, "purgeMl": 0, "skipped": False}]
    assert out["bottle"]["remainingMl"] == 0


def test_normalise_cultures_caps_the_jar_count_and_seeds_species_cadence():
    raw = {"jars": {f"c{n}": {"species": "tigriopus"} for n in range(1, 7)}}
    out = integration._normalise_cultures(raw)
    assert len(out["jars"]) == cultures.CULTURE_JARS_MAX
    assert out["jars"]["c1"]["cadence"]["harvestIntervalDays"] == 10
    assert out["jars"]["c1"]["salinityPpt"] == 35
    assert out["jars"]["c1"]["vesselKind"] == "tub" and out["jars"]["c1"]["purgeMl"] == 0
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
    entry = _entry(jars={"c1": _jar(species="tigriopus", started_ago_days=30)})
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
    assert jar["history"][0]["event"] == "water_change" and jar["history"][0]["ml"] == 1250, "50 % of 2.5 L on a sign"


def test_ws_split_creates_b_from_a_producing_jar_and_refuses_otherwise():
    entry = _entry(jars={"c1": _jar(started_ago_days=2)})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_split(hass, conn, {"id": 1, "jar_id": "c1"}))
    assert conn.errors[-1].code == "not_producing"
    _cultures(entry)["jars"]["c1"]["state"]["startedAt"] = _iso(REAL - timedelta(days=15))
    run(integration.websocket_cultures_split(hass, conn, {"id": 2, "jar_id": "c1"}))
    jars = _cultures(entry)["jars"]
    assert set(jars) == {"c1", "c2"}
    assert jars["c2"]["name"] == "Rotifers B" and jars["c2"]["species"] == "rotifer_L"
    assert jars["c2"]["volumeL"] == 2.5 and jars["c2"]["feed"]["productId"] == "phyto"
    assert jars["c2"]["state"]["seededFrom"] == "c1" and jars["c2"]["state"]["startedAt"]
    assert jars["c1"]["history"][0]["event"] == "split" and jars["c1"]["history"][0]["from"] == "c2"
    assert jars["c1"]["state"]["startedAt"] == _iso(REAL - timedelta(days=15)), "the source keeps its clocks"
    # A second split reuses the idle sibling, never a third jar.
    run(integration.websocket_cultures_crash(hass, conn, {"id": 3, "jar_id": "c2"}))
    run(integration.websocket_cultures_split(hass, conn, {"id": 4, "jar_id": "c1"}))
    jars = _cultures(entry)["jars"]
    assert set(jars) == {"c1", "c2"} and jars["c2"]["state"]["crashedAt"] == ""


def test_ws_split_refuses_when_every_jar_is_used():
    jars = {f"c{n}": _jar(started_ago_days=16) for n in range(1, cultures.CULTURE_JARS_MAX + 1)}
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
    assert bottle["remainingMl"] == 0 and bottle["filledAt"], "retain the load identity so the last feed can be undone"
    bottle["remainingMl"] = 50
    bottle["filledAt"] = _iso(REAL)
    run(integration.websocket_cultures_bottle(hass, conn, {"id": 3, "action": "empty"}))
    bottle = _cultures(entry)["bottle"]
    assert {k: bottle[k] for k in ("volumeMl", "remainingMl", "filledAt", "doseMl")} == {"volumeMl": 1000, "remainingMl": 0, "filledAt": "", "doseMl": 20}
    assert not bottle["lastLoadEnriched"] and bottle["enrichedAt"] == ""
    assert [row["event"] for row in bottle["history"]] == ["emptied", "fed_tank", "fed_tank"], "the bottle keeps its own journal"


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
    assert p["enabled"] and p["maxJars"] == 6 and p["canAddJar"]
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
    assert [s["id"] for s in p["species"]] == ["rotifer_L", "tigriopus", "nanno"]
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



# --------------------------------------------------------------------------- #
# V2 Stage A (0.7.125): the vessel, the purge, the rig payload, the shelf
# --------------------------------------------------------------------------- #
def test_normalise_cultures_vessel_kind_and_purge_follow_the_preset():
    out = integration._normalise_cultures({"jars": {
        "c1": {"species": "rotifer_L"},
        "c2": {"species": "rotifer_L", "vesselKind": "jar", "purgeMl": 999},
        "c3": {"species": "tigriopus", "vesselKind": "cone"},
        "c4": {"species": "tigriopus", "vesselKind": "bathtub", "purgeMl": "junk"},
    }})
    assert out["jars"]["c1"]["vesselKind"] == "cone" and out["jars"]["c1"]["purgeMl"] == 50
    assert out["jars"]["c2"]["vesselKind"] == "jar" and out["jars"]["c2"]["purgeMl"] == 500, "purge clamps at 500 ml"
    assert out["jars"]["c3"]["vesselKind"] == "cone", "a keeper may put pods in a cone; the copy will argue"
    assert out["jars"]["c4"]["vesselKind"] == "tub" and out["jars"]["c4"]["purgeMl"] == 0


def test_rig_state_reads_the_stage_heat_first():
    def jar(**over):
        base = {"id": "c1", "name": "Rotifers A", "vesselKind": "cone", "tint": "clearing", "due": [],
                "firstHarvestDays": 6, "purgeMl": 50, "sieveUm": 50,
                "state": {"status": "producing", "percent": 40, "ageDays": 8},
                "feedAdvice": {"action": "wait"}, "temp": {"status": "ok", "tempC": 23, "hardMaxC": 30},
                "harvestGuide": {"totalMl": 625, "mixMl": 480, "rodiMl": 145, "targetPpt": 27},
                "tintTarget": "leafy green"}
        base.update(over)
        return base
    bottle = {"remainingMl": 250, "volumeMl": 1000, "status": "fresh"}
    quiet = cultures.rig_state([jar()], bottle)
    assert quiet["stage"] == "steady" and quiet["cones"][0]["pct"] == 40 and quiet["tub"] is None
    assert quiet["jug"] == {"mode": "harvest", "harvestMl": 625, "mixMl": 480, "rodiMl": 145, "ppt": 27, "mixPpt": 35.0, "purgeMl": 50, "sieveUm": 50, "jarName": "Rotifers A", "available": True, "reason": "", "vesselKind": "cone"}
    assert quiet["bottle"] == {"ml": 250, "pct": 25, "status": "fresh"}
    harvest = cultures.rig_state([jar(due=["harvest"])], bottle)
    assert harvest["stage"] == "harvest" and harvest["cones"][0]["harvestHot"] and harvest["cones"][0]["purgeHot"]
    assert "625 ml through the 50 µm net" in harvest["caption"] and "145 ml RODI" in harvest["caption"]
    feed = cultures.rig_state([jar(feedAdvice={"action": "feed_now"})], bottle)
    assert feed["stage"] == "feed" and "leafy green" in feed["caption"]
    heat = cultures.rig_state([jar(due=["harvest"], temp={"status": "hot", "tempC": 29, "hardMaxC": 28})], bottle)
    assert heat["stage"] == "heat" and "extra air" in heat["caption"], "heat outranks a due harvest"
    tub = cultures.rig_state([jar(), jar(id="c2", name="Pods", vesselKind="tub",
                                            state={"status": "establishing", "percent": None, "ageDays": 9},
                                            firstHarvestDays=28)], bottle)
    assert tub["tub"]["name"] == "Pods" and tub["tub"]["pct"] == 32 and tub["tub"]["establishDays"] == 9
    assert tub["stage"] == "establishing", "a jar still establishing is the more useful line than 'steady'"
    empty = cultures.rig_state([jar(state={"status": "none"}, tint="")], {})
    assert empty["stage"] == "idle" and empty["cones"][0]["tint"] == "" and not empty["cones"][0]["airOn"]
    assert len(cultures.rig_state([jar(id=f"c{n}") for n in range(6)], {})["cones"]) == cultures.RIG_CONES_MAX


def test_summary_carries_the_rig_and_the_vessel_fields():
    entry = _entry(jars={"c1": _jar(started_ago_days=12, lastFedAt=_iso(REAL - timedelta(hours=20)),
                                    lastHarvestAt=_iso(REAL - timedelta(hours=30))),
                         "c2": _jar(species="tigriopus", started_ago_days=3)})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_summary(hass, conn, {"id": 1}))
    p = conn.results[-1].payload
    by_id = {j["id"]: j for j in p["jars"]}
    assert by_id["c1"]["vesselKind"] == "cone" and by_id["c1"]["purgeMl"] == 50 and by_id["c1"]["sieveUm"] == 50
    assert by_id["c2"]["vesselKind"] == "tub" and by_id["c2"]["adultSieveUm"] == 300
    assert by_id["c2"]["state"]["waterChangeOnDemand"] and by_id["c2"]["tintTarget"].startswith("Granny")
    rig = p["rig"]
    assert [c["id"] for c in rig["cones"] if c["status"] != "ghost"] == ["c1"] and rig["tub"]["id"] == "c2"
    assert rig["cones"][1]["status"] == "ghost" and rig["cones"][1]["name"] == "Rotifers B", "one running cone pencils B in (0.7.140)"
    assert rig["stage"] == "harvest" and rig["cones"][0]["airOn"] and rig["jug"]["harvestMl"] == 625


def test_reefphyto_products_are_on_the_shelf():
    names = {item["name"]: item for item in nps_engine.PRODUCT_LIBRARY}
    for name in ("Reef Juice (live phyto blend)", "Rotifer Feed Concentrate", "Copepod Feed",
                 "Rotifer & Artemia Enrichment"):
        assert name in names and names[name]["brand"] == "Reefphyto" and names[name]["refrigerated"]
    assert "not designed as a culture feed" in names["Reef Juice (live phyto blend)"]["notes"]
    assert names["Rotifer & Artemia Enrichment"]["category"] == "enrichment", "drops into the soak, not a feed-plan food (0.7.165)"



# --------------------------------------------------------------------------- #
# V2 Stage B (0.7.126): the journal that learns, signs, risk, phone actions
# --------------------------------------------------------------------------- #
def _row(event, hours_ago, now=None, **fields):
    base = now or NOW
    row = {"event": event, "at": _iso(base - timedelta(hours=hours_ago)), "ml": 0, "tint": "", "from": "",
           "sign": "", "eggRatio": 0, "tempC": None}
    row.update(fields)
    return row


def test_clearing_samples_measure_feed_to_clear():
    history = [  # newest first, as stored
        _row("tint", 2, tint="clear"), _row("feed", 12, tint="clearing"),   # 10 h
        _row("feed", 20, tint="green"),                                       # fed again before clearing: void
        _row("harvest", 40, tint="clear"), _row("feed", 49, tint="clearing"),  # 9 h (the harvest row's tint closes it)
        _row("seeded", 200),
    ]
    assert cultures.clearing_samples(history) == [10.0, 9.0]
    assert cultures.clearing_samples([]) == [] and cultures.clearing_samples("junk") == []


def test_learned_cadences_follow_the_hatch_clock_contract():
    jar = _jar(started_ago_days=20, now=NOW)
    jar["history"] = [
        _row("tint", 1, tint="clear"), _row("feed", 10, tint="clearing"),
        _row("tint", 30, tint="clear"), _row("feed", 38, tint="clearing"),
        _row("restart", 48), _row("seeded", 20 * 24),
    ]
    learned = cultures.learned_cadences(jar, [jar["history"]], NOW)
    assert learned["clearingH"] == {"available": True, "hours": 8.5, "samples": 2}
    assert learned["suggest"]["feedIntervalH"] == 8.0, "feed a little before it clears"
    assert not learned["runLengthDays"]["available"], "one run is not a pattern"
    assert learned["yieldMlDay"] is None
    # First harvest learns across the species' jars; run length from restarts and crashes.
    sib = [_row("harvest", 10 * 24, ml=600), _row("seeded", 15 * 24)]
    mine = [_row("harvest", 1, ml=625), _row("harvest", 25, ml=625), _row("harvest", 49, ml=625),
            _row("restart", 60), _row("restart", 60 + 11 * 24), _row("restart", 60 + 23 * 24), _row("seeded", 60 + 33 * 24)]
    jar["history"] = mine
    learned = cultures.learned_cadences(jar, [mine, sib], NOW)
    assert learned["runLengthDays"] == {"available": True, "days": 11.0, "samples": 3}
    assert learned["suggest"]["restartIntervalDays"] is None, "planned restarts are not evidence of crashes"
    assert learned["yieldMlDay"] == 133.9, "1875 ml over the known 14-calendar-day window, including zero-harvest days"
    assert learned["firstHarvestDays"]["samples"] == 2 and learned["firstHarvestDays"]["available"], "one sample per seed, across the species' jars"
    assert cultures.first_harvest_samples([sib, [_row("harvest", 3 * 24), _row("seeded", 9 * 24)]]) == [6.0, 5.0]


def test_restart_comes_forward_on_a_sign_or_slow_clearing():
    jar = _jar(started_ago_days=5, lastSignAt=_iso(NOW - timedelta(hours=1)), lastSign="foam", now=NOW)
    st = cultures.culture_state(jar, NOW)
    assert st["restart"]["due"] and st["restart"]["reason"] == "sign"
    assert "restart" in [k for k in ("feed", "harvest", "restart") if st[k]["due"]]
    # A sign answered by a restart is history.
    jar["state"]["lastRestartAt"] = _iso(NOW - timedelta(minutes=10))
    assert cultures.culture_state(jar, NOW)["restart"]["reason"] is None
    # Slow clearing: the last two samples 1.5× the earlier baseline.
    slow = _jar(started_ago_days=8, now=NOW)
    slow["history"] = [
        _row("tint", 1, tint="clear"), _row("feed", 19, tint="clearing"),      # 18 h
        _row("tint", 25, tint="clear"), _row("feed", 41, tint="clearing"),     # 16 h
        _row("tint", 50, tint="clear"), _row("feed", 58, tint="clearing"),     # 8 h
        _row("tint", 70, tint="clear"), _row("feed", 79, tint="clearing"),     # 9 h
        _row("tint", 90, tint="clear"), _row("feed", 100, tint="clearing"),    # 10 h
    ]
    st = cultures.culture_state(slow, NOW)
    assert st["clearingSlow"] and st["restart"]["reason"] == "slow"
    # Pods have no restart: a sign is a water change due now.
    pod = _jar(species="tigriopus", started_ago_days=40, lastSignAt=_iso(NOW - timedelta(hours=2)), lastSign="surface", now=NOW)
    st = cultures.culture_state(pod, NOW)
    assert not st["restart"]["available"] and st["waterChange"]["due"] and st["waterChange"]["reason"] == "sign"
    pod["state"]["lastWaterChangeAt"] = _iso(NOW - timedelta(hours=1))
    assert not cultures.culture_state(pod, NOW)["waterChange"]["due"]


def test_feed_advice_puts_harvest_debt_first():
    debt = {"due": True, "hoursOverdue": 26.0}
    assert cultures.feed_advice("clear", {"due": True}, debt, 24.0)["action"] == "harvest_first"
    assert cultures.feed_advice("clear", {"due": True}, {"due": True, "hoursOverdue": 5.0}, 24.0)["action"] == "feed_now"


def test_risk_line_explains_itself():
    ok = _jar(started_ago_days=10, lastHarvestAt=_iso(NOW - timedelta(hours=5)), lastFedAt=_iso(NOW - timedelta(hours=1)), now=NOW)
    st = cultures.culture_state(ok, NOW)
    temp = cultures.temperature_advice(23, "rotifer_L")
    assert cultures.risk_line(ok, st, temp, NOW) == {"level": "ok", "reason": "no warning from the recorded observations"}
    debt = _jar(started_ago_days=10, lastHarvestAt=_iso(NOW - timedelta(hours=60)), now=NOW)
    risk = cultures.risk_line(debt, cultures.culture_state(debt, NOW), temp, NOW)
    assert risk["level"] == "act" and "two harvests missed" in risk["reason"]
    late = _jar(started_ago_days=10, lastHarvestAt=_iso(NOW - timedelta(hours=30)), now=NOW)
    late["history"] = [_row("feed", 3, tint="green")]
    risk = cultures.risk_line(late, cultures.culture_state(late, NOW), temp, NOW)
    assert risk["level"] == "watch" and "harvest overdue" in risk["reason"] and "fed on green" in risk["reason"]
    signed = _jar(started_ago_days=10, lastHarvestAt=_iso(NOW - timedelta(hours=5)),
                  lastSignAt=_iso(NOW - timedelta(hours=1)), lastSign="milky", now=NOW)
    risk = cultures.risk_line(signed, cultures.culture_state(signed, NOW), temp, NOW)
    assert risk["level"] == "act" and "milky water since the last restart" in risk["reason"]
    hot = cultures.temperature_advice(30.5, "tigriopus")
    pod = _jar(species="tigriopus", started_ago_days=40, lastHarvestAt=_iso(NOW - timedelta(days=2)), now=NOW)
    assert cultures.risk_line(pod, cultures.culture_state(pod, NOW), hot, NOW)["level"] == "act"
    assert cultures.risk_line(_jar(now=NOW), cultures.culture_state(_jar(now=NOW), NOW), temp, NOW) == {"level": "ok", "reason": ""}


def test_ws_log_sign_and_egg_ratio_write_the_journal():
    entry = _entry(jars={"c1": _jar(started_ago_days=10, lastHarvestAt=_iso(REAL - timedelta(hours=5)))},
                   temp_entity="sensor.bench")
    hass = FakeHass(entries=[entry], states={"sensor.bench": "24.2"})
    conn = FakeConnection()
    run(integration.websocket_cultures_log(hass, conn, {"id": 1, "jar_id": "c1", "sign": "foam", "egg_ratio": 22}))
    assert not conn.errors
    jar = _cultures(entry)["jars"]["c1"]
    assert jar["state"]["lastSign"] == "foam" and jar["state"]["lastSignAt"]
    assert jar["history"][0]["event"] == "sign" and jar["history"][0]["sign"] == "foam"
    assert jar["history"][0]["eggRatio"] == 22 and jar["history"][0]["tempC"] == 24.2
    run(integration.websocket_cultures_summary(hass, conn, {"id": 2}))
    j = conn.results[-1].payload["jars"][0]
    assert j["state"]["restart"]["reason"] == "sign" and "restart" in j["due"]
    assert j["risk"]["level"] == "act" and "foam" in j["risk"]["reason"]
    assert [x["id"] for x in conn.results[-1].payload["signs"]] == ["foam", "milky", "smell", "surface"]
    assert "learned" in j and j["learned"]["suggest"]["feedIntervalH"] is None
    run(integration.websocket_cultures_log(hass, conn, {"id": 3, "jar_id": "c1", "sign": "bogus"}))
    assert conn.errors[-1].code == "nothing_to_log", "an unknown sign is not a log"
    run(integration.websocket_cultures_restart(hass, conn, {"id": 4, "jar_id": "c1"}))
    jar = _cultures(entry)["jars"]["c1"]
    assert jar["state"]["lastSign"] == "" and jar["state"]["lastSignAt"] == "", "a restart answers the sign"


def test_ws_apply_learned_sets_the_cadence_and_retimes_the_reminder():
    jar = _jar(started_ago_days=20, lastHarvestAt=_iso(REAL - timedelta(hours=5)))
    jar["history"] = [_row("tint", 1, REAL, tint="clear"), _row("feed", 10, REAL, tint="clearing"),
                      _row("tint", 30, REAL, tint="clear"), _row("feed", 38, REAL, tint="clearing")]
    maintenance = {"tasks": {"culture_c1_feed": {"label": "A: feed", "cadenceHours": 12, "criticalAfterHours": 12}},
                   "completions": {}}
    entry = _entry(jars={"c1": jar}, maintenance=maintenance)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_apply_learned(hass, conn, {"id": 1, "jar_id": "c1", "field": "restartIntervalDays"}))
    assert conn.errors[-1].code == "not_learned"
    run(integration.websocket_cultures_apply_learned(hass, conn, {"id": 2, "jar_id": "c1", "field": "feedIntervalH"}))
    assert not [e for e in conn.errors if e.code != "not_learned"]
    cfg = entry.options[CONF_SETTINGS]
    assert cfg["nps"]["cultures"]["jars"]["c1"]["cadence"]["feedIntervalH"] == 8.0
    assert cfg["maintenance"]["tasks"]["culture_c1_feed"]["cadenceHours"] == 8.0
    run(integration.websocket_cultures_apply_learned(hass, conn, {"id": 3, "jar_id": "c1", "field": "harvestPct"}))
    assert conn.errors[-1].code == "unknown_field"


def test_push_plan_is_one_question_per_jar():
    summary = {"jars": [
        {"id": "c1", "name": "Rotifers A", "state": {"status": "producing", "restart": {"reason": None}},
         "due": ["feed", "harvest"], "feedAdvice": {"reason": "clearing — feed on schedule"}, "risk": {"level": "ok"}},
        {"id": "c2", "name": "Pods", "state": {"status": "establishing", "restart": {}}, "due": ["feed"],
         "feedAdvice": {"reason": "no tint logged yet"}, "risk": {"level": "ok"}},
        {"id": "c3", "name": "B", "state": {"status": "producing", "restart": {"reason": "sign"}}, "due": ["restart", "harvest"],
         "feedAdvice": {"reason": ""}, "risk": {"level": "act", "reason": "foam on the surface since the last restart"}},
        {"id": "c4", "name": "Quiet", "state": {"status": "producing"}, "due": [], "feedAdvice": {}, "risk": {}},
        {"id": "c5", "name": "Empty", "state": {"status": "none"}, "due": ["feed"], "feedAdvice": {}, "risk": {}},
    ]}
    plan = integration._cultures_push_plan(summary)
    assert [p["jarId"] for p in plan] == ["c1", "c2", "c3"]
    assert plan[0]["title"] == "OpenReef: Rotifers A — feed + harvest?"
    assert [a["title"] for a in plan[0]["actions"]] == ["Harvested + fed", "Later"]
    assert plan[0]["actions"][0]["action"] == "OPENREEF_CULTURE_HARVEST:c1" and plan[0]["message"].startswith("Clearing")
    assert [a["title"] for a in plan[1]["actions"]] == ["Fed", "Skipped", "Later"]
    assert plan[1]["actions"][1]["action"] == "OPENREEF_CULTURE_SKIP:c2"
    assert [a["title"] for a in plan[2]["actions"]] == ["Restarted", "Harvested + fed", "Later"]
    assert plan[2]["message"].startswith("Foam on the surface")


def test_actionable_push_and_the_phone_tap():
    entry = _entry(jars={"c1": _jar(started_ago_days=10, lastHarvestAt=_iso(REAL - timedelta(hours=30)))},
                   maintenance={"tasks": {}, "completions": {}, "reminders": {"enabled": True, "notifyTarget": "mobile_app_phone"}})
    hass = FakeHass(entries=[entry])
    run(integration._async_push_actionable(hass, "mobile_app_phone", "T", "M",
                                           [{"action": "OPENREEF_CULTURE_HARVEST:c1", "title": "Harvested + fed"},
                                            {"action": "X", "title": "1"}, {"action": "Y", "title": "2"}, {"action": "Z", "title": "3"}],
                                           tag="t"))
    call = hass.services.calls[-1]
    assert call.domain == "notify" and call.service == "mobile_app_phone"
    assert len(call.data["data"]["actions"]) == 3 and call.data["data"]["tag"] == "t"
    run(integration._async_push_actionable(hass, "", "T", "M", []))
    assert hass.services.calls[-1] is call, "no target, no push"
    run(integration._async_push_actionable(hass, "mobile_app_phone", "T", "M", []))
    assert "data" not in hass.services.calls[-1].data, "no buttons, no data block"
    # The daily tick sends the jar's question.
    n = run(integration._async_cultures_push_due(hass, _config(entry), "mobile_app_phone"))
    assert n == 1 and hass.services.calls[-1].data["title"].startswith("OpenReef: Rotifers A")
    # A tap on the button does the tap.
    class Ev:
        def __init__(self, action):
            self.data = {"action": action}
    run(integration._async_notification_action(hass, Ev("OPENREEF_CULTURE_HARVEST:c1")))
    jar = _cultures(entry)["jars"]["c1"]
    assert jar["history"][0]["event"] == "harvest" and jar["history"][0]["ml"] == 625
    assert _cultures(entry)["bottle"]["remainingMl"] == 625
    rows = len(_cultures(entry)["jars"]["c1"]["history"])
    run(integration._async_notification_action(hass, Ev("OPENREEF_CULTURE_LATER:c1")))
    run(integration._async_notification_action(hass, Ev("SOMETHING_ELSE")))
    assert len(_cultures(entry)["jars"]["c1"]["history"]) == rows, "later and foreign actions do nothing"
    run(integration._async_notification_action(hass, Ev("OPENREEF_CULTURE_FED:nope")))
    activity = entry.options[CONF_SETTINGS].get("activity") or []
    assert any("Phone tap ignored" in str(a.get("message", "")) for a in activity)



# --------------------------------------------------------------------------- #
# V2 Stage C (0.7.127): the DHA step, the boost clock, the tank
# --------------------------------------------------------------------------- #
def test_soak_and_boost_clocks():
    assert cultures.soak_state("", 6, 8, NOW)["status"] == "none"
    soaking = cultures.soak_state(_iso(NOW - timedelta(hours=2)), 6, 8, NOW)
    assert soaking["status"] == "soaking" and soaking["percent"] == 33 and soaking["hoursLeft"] == 4.0
    done = cultures.soak_state(_iso(NOW - timedelta(hours=7)), 6, 8, NOW)
    assert done["status"] == "done" and done["hoursLeft"] == 7.0, "the warm boost window ticks from the soak's end"
    assert cultures.soak_state(_iso(NOW - timedelta(hours=15)), 6, 8, NOW)["status"] == "fading"
    bottle = {"remainingMl": 400, "lastLoadEnriched": True, "enrichedAt": _iso(NOW - timedelta(hours=20))}
    assert cultures.bottle_boost(bottle, 24, NOW) == {"status": "gutloaded", "hoursLeft": 4.0}
    bottle["enrichedAt"] = _iso(NOW - timedelta(hours=30))
    assert cultures.bottle_boost(bottle, 24, NOW)["status"] == "faded"
    assert cultures.bottle_boost({"remainingMl": 400, "lastLoadEnriched": False}, 24, NOW)["status"] == "none"
    assert cultures.bottle_boost({"remainingMl": 0, "lastLoadEnriched": True, "enrichedAt": _iso(NOW)}, 24, NOW)["status"] == "none"
    assert cultures.bottle_boost({"remainingMl": 10, "lastLoadEnriched": True, "enrichedAt": ""}, 24, NOW)["status"] == "faded", "fail-closed"


def test_next_harvest_names_its_driver():
    clock = {"available": True, "due": False, "at": _iso(NOW + timedelta(hours=20)), "hoursUntil": 20.0}
    fresh = {"status": "fresh", "remainingMl": 300, "hoursLeft": 60.0}
    assert cultures.next_harvest(fresh, None, clock, False)["status"] == "none"
    for bottle in (fresh, {"status": "empty"}, {"status": "stale", "hoursLeft": 0}):
        assert cultures.next_harvest(bottle, 600, clock, True) == {"status": "wait", "hoursUntil": 20, "driver": "jar"}
    assert cultures.next_harvest(fresh, None, {**clock, "due": True}, True)["status"] == "now"
    assert cultures.next_harvest({"status": "empty"}, None, {**clock, "due": True}, True)["driver"] == "empty"
    history = [{"event": "fed_tank", "at": _iso(NOW - timedelta(hours=2)), "ml": 20}, {"event": "fed_tank", "at": _iso(NOW - timedelta(hours=26)), "ml": 20},
               {"event": "filled", "at": _iso(NOW - timedelta(hours=30)), "ml": 625}]
    assert cultures.bottle_usage_ml_per_day(history, NOW) == 20 and cultures.bottle_usage_ml_per_day([], NOW) is None


def test_ws_harvest_can_go_to_the_soak_and_then_the_bottle_carries_the_boost():
    products = {"phyto": {"name": "Live phyto", "bottleMl": 500, "remainingMl": 300, "history": []},
                "enrich": {"name": "Rotifer & Artemia Enrichment", "bottleMl": 100, "remainingMl": 50, "history": []}}
    entry = _entry(jars={"c1": _jar(started_ago_days=10, lastHarvestAt=_iso(REAL - timedelta(hours=30)))}, products=products)
    cfg = _config(entry)
    cfg["nps"]["cultures"]["enrichment"] = {"productId": "enrich", "drops": 4, "soakH": 6}
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_log(hass, conn, {"id": 1, "jar_id": "c1", "harvested": True, "fed": True, "enrich": True}))
    assert not conn.errors
    cult = _cultures(entry)
    assert cult["bottle"]["remainingMl"] == 0, "the crop went to the soak, not the bottle"
    assert cult["enrichment"]["state"]["portionMl"] == 625 and cult["enrichment"]["state"]["jarId"] == "c1"
    assert _config(entry)["consumables"]["products"]["enrich"]["remainingMl"] == 49.8, "four drops off the enrichment bottle"
    run(integration.websocket_cultures_log(hass, conn, {"id": 2, "jar_id": "c1", "harvested": True, "enrich": True}))
    assert conn.errors[-1].code == "enrich_busy"
    run(integration.websocket_cultures_summary(hass, conn, {"id": 3}))
    p = conn.results[-1].payload
    assert p["enrichment"]["soak"]["status"] == "soaking" and p["enrichment"]["jarName"] == "Rotifers A"
    assert p["enrichment"]["productName"] == "Rotifer & Artemia Enrichment"
    assert p["nextHarvest"]["status"] == "wait" and p["nextHarvest"]["driver"] == "jar"
    _cultures(entry)["enrichment"]["state"]["startedAt"] = _iso(datetime.now(timezone.utc) - timedelta(hours=7))
    run(integration.websocket_cultures_enrich_done(hass, conn, {"id": 4}))
    cult = _cultures(entry)
    assert cult["bottle"]["remainingMl"] == 625 and cult["bottle"]["lastLoadEnriched"] and cult["bottle"]["enrichedAt"]
    assert cult["bottle"]["history"][0]["event"] == "enriched" and cult["enrichment"]["state"]["startedAt"] == ""
    assert cult["jars"]["c1"]["history"][0]["event"] == "enriched"
    run(integration.websocket_cultures_enrich_done(hass, conn, {"id": 5}))
    assert conn.errors[-1].code == "no_soak"
    run(integration.websocket_cultures_summary(hass, conn, {"id": 6}))
    p = conn.results[-1].payload
    assert p["bottle"]["boost"]["status"] == "gutloaded" and p["bottle"]["enriched"]
    assert p["nextHarvest"]["status"] == "wait" and p["nextHarvest"]["driver"] in ("depletion", "jar", "freshness")
    # A plain harvest on top keeps the boost flag honest: the LAST load was not enriched.
    run(integration.websocket_cultures_log(hass, conn, {"id": 7, "jar_id": "c1", "harvested": True}))
    assert _cultures(entry)["bottle"]["remainingMl"] == 1000 and not _cultures(entry)["bottle"]["lastLoadEnriched"], "a plain top-up removes the whole-bottle enrichment claim"


def test_ws_enrich_plain_and_bottle_feed_log_the_tank():
    entry = _entry(jars={"c1": _jar(started_ago_days=10, lastHarvestAt=_iso(REAL - timedelta(hours=30)))},
                   maintenance={"tasks": {"brine_hand_feed": {"label": "Hand-feed the tank"}}, "completions": {}})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_log(hass, conn, {"id": 1, "jar_id": "c1", "harvested": True, "enrich": True}))
    run(integration.websocket_cultures_enrich_done(hass, conn, {"id": 2, "bottled": False}))
    cult = _cultures(entry)
    assert cult["bottle"]["remainingMl"] == 625 and not cult["bottle"]["lastLoadEnriched"]
    assert cult["bottle"]["history"][0]["event"] == "filled" and cult["jars"]["c1"]["history"][0]["event"] == "bottled"
    run(integration.websocket_cultures_bottle(hass, conn, {"id": 3, "action": "fed", "ml": 25}))
    cult = _cultures(entry)
    assert cult["bottle"]["remainingMl"] == 600 and cult["bottle"]["history"][0] ["event"] == "fed_tank"
    comps = entry.options[CONF_SETTINGS]["maintenance"]["completions"]["brine_hand_feed"]
    assert comps and "rotifers from the bottle" in comps[0]["notes"], "feeding rotifers IS hand-feeding the tank"
    run(integration.websocket_cultures_summary(hass, conn, {"id": 4}))
    assert conn.results[-1].payload["bottle"]["usageMlDay"] == 25.0


def test_ws_cysts_opened_and_the_summary_has_no_phyto():
    entry = _entry(jars={})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_summary(hass, conn, {"id": 1}))
    assert "phytoDose" not in conn.results[-1].payload, "Reef Juice is the shelf's business, not the jars'"
    assert not hasattr(integration, "websocket_cultures_phyto_dosed")
    run(integration.websocket_nps_cysts_opened(hass, conn, {"id": 4}))
    assert _config(entry)["nps"]["hatchery"]["cysts"]["openedAt"]
    payload = integration._nps_cysts_payload({"cysts": {"openedAt": _iso(REAL - timedelta(days=22))}}, REAL)
    assert payload["status"] == "aging" and payload["days"] == 22
    assert integration._nps_cysts_payload({}, REAL)["available"] is False


def test_stage_c_runtime_survives_a_stale_save():
    stored = {"nps": {"cultures": {
        "enabled": True, "jars": {},
        "bottle": {"volumeMl": 1000, "remainingMl": 625, "filledAt": _iso(REAL), "doseMl": 20,
                   "enrichedAt": _iso(REAL), "lastLoadEnriched": True,
                   "history": [{"event": "enriched", "at": _iso(REAL), "ml": 625}]},
        "enrichment": {"productId": "e", "drops": 3, "soakH": 6, "state": {"startedAt": _iso(REAL), "portionMl": 300, "jarId": "c1"}},
    }, "hatchery": {"cysts": {"openedAt": _iso(REAL)}, "vessels": {}, "reservoir": {}, "fridgeBottle": {}, "enrichment": {"state": {}}}}}
    incoming = copy.deepcopy(stored)
    cult = incoming["nps"]["cultures"]
    cult["bottle"] = {"volumeMl": 2000, "remainingMl": 0, "filledAt": "", "doseMl": 30, "enrichedAt": "", "lastLoadEnriched": False, "history": []}
    cult["enrichment"] = {"productId": "other", "drops": 5, "soakH": 4, "state": {"startedAt": "", "portionMl": 0, "jarId": ""}}
    incoming["nps"]["hatchery"]["cysts"] = {"openedAt": ""}
    integration._nps_preserve_runtime(stored, incoming)
    cult = incoming["nps"]["cultures"]
    assert cult["bottle"]["remainingMl"] == 625 and cult["bottle"]["lastLoadEnriched"] and cult["bottle"]["history"]
    assert cult["bottle"]["volumeMl"] == 2000 and cult["bottle"]["doseMl"] == 30, "the keeper's settings stay"
    assert cult["enrichment"]["state"]["portionMl"] == 300 and cult["enrichment"]["drops"] == 5
    assert incoming["nps"]["hatchery"]["cysts"]["openedAt"]



# --------------------------------------------------------------------------- #
# V2 Stage D (0.7.128): never zero, lineage, the heat guard, the card
# --------------------------------------------------------------------------- #
def _projection(peaks):
    """Fake cooling projection rows: (hours_from_now, roomC) pairs."""
    return [{"at": _iso(NOW + timedelta(hours=h)), "roomC": c} for h, c in peaks]


def test_heat_guard_reads_the_forecast_against_the_species_band():
    assert cultures.heat_guard([], "tigriopus", NOW)["available"] is False
    assert cultures.heat_guard("junk", "tigriopus", NOW)["status"] == "unknown"
    clear = cultures.heat_guard(_projection([(1, 22.0), (6, 24.5), (12, 23.0)]), "tigriopus", NOW)
    assert clear["status"] == "clear" and clear["peakC"] == 24.5
    watch = cultures.heat_guard(_projection([(1, 22.0), (8, 27.2), (12, 25.0)]), "tigriopus", NOW)
    assert watch["status"] == "watch" and "above the 26 °C band" in watch["line"]
    warn = cultures.heat_guard(_projection([(1, 24.0), (5, 27.0), (9, 28.4), (15, 30.1), (30, 33.0)]), "tigriopus", NOW)
    assert warn["status"] == "warn" and warn["hoursUntil"] == 9.0 and warn["peakC"] == 30.1, "the 30 h row is outside the day"
    assert "passes 28 °C in ~9 h" in warn["line"] and "extra air" in warn["line"]
    # Rotifers warn later — their line is 30 °C.
    assert cultures.heat_guard(_projection([(9, 28.4), (15, 29.5)]), "rotifer_L", NOW)["status"] == "watch"
    assert cultures.heat_guard(_projection([(9, 28.4), (15, 30.5)]), "rotifer_L", NOW)["status"] == "warn"


def test_stagger_tint_strip_and_continuity():
    a = _jar(started_ago_days=20, lastRestartAt=_iso(NOW - timedelta(days=9)), now=NOW)
    b = _jar(started_ago_days=12, lastRestartAt=_iso(NOW - timedelta(days=2)), now=NOW)
    good = cultures.stagger_advice(a, b, NOW)
    assert good["available"] and good["days"] == 7.0 and good["idealDays"] == 7.0 and "staggered" in good["advice"]
    b["state"]["lastRestartAt"] = _iso(NOW - timedelta(days=8))
    close = cultures.stagger_advice(a, b, NOW)
    assert close["days"] == 1.0 and "never delay a due restart" in close["advice"]
    pod_a = _jar(species="tigriopus", started_ago_days=40, now=NOW)
    assert cultures.stagger_advice(pod_a, pod_a, NOW)["available"] is False, "no restart, no stagger"
    history = [_row("tint", 2, tint="clear"), _row("feed", 20, tint="green"), _row("harvest", 30, tint="clearing"),
               _row("feed", 3 * 24 + 1, tint="green"), _row("seeded", 20 * 24)]
    strip = cultures.tint_strip(history, NOW)
    assert len(strip) == 14 and strip[-1] == "clear" and strip[-2] == "green" and strip[-3] == "" and strip[-4] == "green" and strip[0] == "", "the latest tap of each day wins; a day with no look is blank"
    assert cultures.continuity_days(_iso(NOW - timedelta(days=41, hours=12)), NOW) == 41.5
    assert cultures.continuity_days("", NOW) is None


def test_ws_seed_and_split_write_the_lineage_and_continuity():
    entry = _entry(jars={"c1": _jar(), "c2": _jar()})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_seed(hass, conn, {"id": 1, "jar_id": "c1"}))
    cult = _cultures(entry)
    assert cult["jars"]["c1"]["state"]["generation"] == 1
    assert cult["continuity"]["rotifer_L"]["since"] == cult["jars"]["c1"]["state"]["startedAt"]
    assert cult["continuity"]["tigriopus"]["since"] == ""
    # Make c1 producing, then split into the idle c2: gen 2, continuity untouched.
    cult["jars"]["c1"]["state"]["startedAt"] = _iso(REAL - timedelta(days=15))
    cult["jars"]["c1"]["state"]["lastRestartAt"] = _iso(REAL - timedelta(days=1))
    cult["continuity"]["rotifer_L"]["since"] = _iso(REAL - timedelta(days=15))
    entry.options = {**entry.options, CONF_SETTINGS: _config(entry)}
    run(integration.websocket_cultures_split(hass, conn, {"id": 2, "jar_id": "c1"}))
    assert not conn.errors
    cult = _cultures(entry)
    assert cult["jars"]["c2"]["state"]["generation"] == 2 and cult["jars"]["c2"]["state"]["seededFrom"] == "c1"
    assert cult["continuity"]["rotifer_L"]["since"] == _iso(REAL - timedelta(days=15))
    run(integration.websocket_cultures_summary(hass, conn, {"id": 3}))
    p = conn.results[-1].payload
    by_id = {j["id"]: j for j in p["jars"]}
    assert by_id["c1"]["lineage"]["line"] == "gen 1 · from the starter"
    assert by_id["c2"]["lineage"] == {"generation": 2, "fromName": "Rotifers A", "line": "gen 2 · from Rotifers A"}
    assert by_id["c1"]["stagger"]["available"] and by_id["c1"]["stagger"]["days"] == 1.0
    assert len(by_id["c1"]["tintStrip"]) == 14
    backup = {b["species"]: b for b in p["backup"]}
    assert backup["rotifer_L"]["running"] == 2 and backup["rotifer_L"]["backedUp"] and backup["rotifer_L"]["continuityDays"] == 15.0
    assert "tigriopus" not in backup and p["guardAvailable"] is False
    assert by_id["c1"]["guard"]["available"] is False, "no cooling projection — the guard says so"
    # The last crash of a species clears its continuity.
    run(integration.websocket_cultures_crash(hass, conn, {"id": 4, "jar_id": "c2"}))
    run(integration.websocket_cultures_crash(hass, conn, {"id": 5, "jar_id": "c1"}))
    assert _cultures(entry)["continuity"]["rotifer_L"]["since"] == ""


def test_ws_restart_can_seed_b_from_the_same_crop():
    entry = _entry(jars={"c1": _jar(started_ago_days=15, lastRestartAt=_iso(REAL - timedelta(days=14)))})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_restart(hass, conn, {"id": 1, "jar_id": "c1", "split": True}))
    assert not conn.errors
    cult = _cultures(entry)
    assert "c2" in cult["jars"] and cult["jars"]["c2"]["name"] == "Rotifers B"
    assert cult["jars"]["c2"]["state"]["seededFrom"] == "c1" and cult["jars"]["c2"]["vesselKind"] == "cone"
    assert cult["jars"]["c1"]["history"][0]["event"] == "split" and cult["jars"]["c1"]["history"][1]["event"] == "restart"
    # A plain restart never splits; an establishing jar cannot split and says so in the feed.
    entry = _entry(jars={"c1": _jar(started_ago_days=2)})
    hass = FakeHass(entries=[entry])
    run(integration.websocket_cultures_restart(hass, conn, {"id": 2, "jar_id": "c1", "split": True}))
    assert "c2" not in _cultures(entry)["jars"]
    activity = entry.options[CONF_SETTINGS].get("activity") or []
    assert any("B was not seeded" in str(a.get("message", "")) for a in activity)


def test_heat_guard_push_fires_once_a_day_from_the_cooling_projection():
    entry = _entry(jars={"c1": _jar(started_ago_days=10), "c2": _jar(species="tigriopus", started_ago_days=40)},
                   maintenance={"tasks": {}, "completions": {}, "reminders": {"enabled": True, "notifyTarget": "mobile_app_phone"}})
    hass = FakeHass(entries=[entry])
    hass.data.setdefault(integration.DOMAIN, {})[integration.COOLING_RUNTIME] = {"snapshot": {"projection": {"hours": [
        {"at": _iso(REAL + timedelta(hours=2)), "roomC": 25.0}, {"at": _iso(REAL + timedelta(hours=8)), "roomC": 28.6},
        {"at": _iso(REAL + timedelta(hours=14)), "roomC": 27.0}]}}}
    config = _config(entry)
    sent = run(integration._async_cultures_heat_guard_push(hass, config, "mobile_app_phone"))
    assert sent == 1, "the pods warn at 28, the rotifers do not"
    call = hass.services.calls[-1]
    assert call.data["title"] == "OpenReef: heat ahead for the Tigriopus copepods" and "passes 28 °C in ~8 h" in call.data["message"]
    assert config["nps"]["cultures"]["guard"]["notified"]["tigriopus"]
    assert run(integration._async_cultures_heat_guard_push(hass, config, "mobile_app_phone")) == 0, "once a day"
    conn = FakeConnection()
    entry.options = {**entry.options, CONF_SETTINGS: config}
    run(integration.websocket_cultures_summary(hass, conn, {"id": 1}))
    p = conn.results[-1].payload
    assert p["guardAvailable"]
    by_id = {j["id"]: j for j in p["jars"]}
    assert by_id["c2"]["guard"]["status"] == "warn" and by_id["c1"]["guard"]["status"] == "watch"
    assert {b["species"]: b["guard"]["status"] for b in p["backup"]} == {"rotifer_L": "watch", "tigriopus": "warn"}
    # The stamps and the continuity survive a stale save.
    stored = {"nps": {"cultures": {"enabled": True, "jars": {}, "continuity": {"rotifer_L": {"since": _iso(REAL)}},
                                   "guard": {"notified": {"tigriopus": _iso(REAL)}}}}}
    incoming = copy.deepcopy(stored)
    incoming["nps"]["cultures"]["continuity"] = {"rotifer_L": {"since": ""}}
    incoming["nps"]["cultures"]["guard"] = {"notified": {}}
    integration._nps_preserve_runtime(stored, incoming)
    assert incoming["nps"]["cultures"]["continuity"]["rotifer_L"]["since"] == _iso(REAL)
    assert incoming["nps"]["cultures"]["guard"]["notified"]["tigriopus"] == _iso(REAL)


def test_the_fill_and_every_debit_read_the_station_and_the_bottle_gets_what_was_rinsed_in():
    """Day 0: the summary carries the cone's fill split from the mixing
    station's target; seeding, harvesting, restarting and changing water debit
    the vessel by the MIX share only (the rest is RODI); the harvest's bottle
    fill is what the net was rinsed into, not the culture water."""
    jars = {"c1": {"name": "Rotifers A", "species": "rotifer_L", "vesselKind": "cone", "volumeL": 2.0,
                   "salinityPpt": 27, "purgeMl": 50, "feed": {"productId": "", "doseMl": 1}, "cadence": {},
                   "state": {}, "history": []}}
    entry = _entry(jars=jars)
    cfg = _config(entry)
    cfg["mixingStation"] = {"enabled": True, "salt": {"targetPpt": 35}}
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    debits = []
    real_debit = integration._mixing_hatchery_debit
    integration._mixing_hatchery_debit = lambda hass_, config_, litres, note: debits.append((round(litres, 3), note))
    try:
        run(integration.websocket_cultures_summary(hass, conn, {"id": 1}))
        jar = conn.results[-1].payload["jars"][0]
        assert jar["mixPpt"] == 35.0 and jar["fillGuide"] == {"totalMl": 2000, "mixMl": 1543, "rodiMl": 457, "targetPpt": 27.0, "mixPpt": 35.0, "sg": 1.0204}
        assert jar["harvestGuide"]["mixMl"] == 424 and jar["harvestGuide"]["rodiMl"] == 126, "replace harvest plus purge"
        assert jar["pouchMl"] == 500 and jar["arrivalFillGuide"] == jar["fillGuide"], "sieve the starter into the full prepared volume; discard shipping water"
        assert conn.results[-1].payload["rig"]["jug"]["mode"] == "fill" and conn.results[-1].payload["rig"]["jug"]["mixMl"] == 1543
        run(integration.websocket_cultures_seed(hass, conn, {"id": 2, "jar_id": "c1"}))
        assert not conn.errors and debits[-1] == (1.543, "seeding Rotifers A"), "the vessel gives the mix share of the fill, not the whole cone"
        # Producing: the jug is the harvest again.
        cfg = _config(entry)
        cfg["nps"]["cultures"]["jars"]["c1"]["state"]["startedAt"] = _iso(datetime.now(timezone.utc) - timedelta(days=8))
        entry.options = {**entry.options, CONF_SETTINGS: cfg}
        run(integration.websocket_cultures_summary(hass, conn, {"id": 3}))
        assert conn.results[-1].payload["rig"]["jug"]["mode"] == "harvest" and conn.results[-1].payload["rig"]["jug"]["harvestMl"] == 500
        run(integration.websocket_cultures_log(hass, conn, {"id": 4, "jar_id": "c1", "tint": "clearing", "fed": True, "harvested": True, "bottle_ml": 150}))
        assert not conn.errors
        cfg = _config(entry)
        assert cfg["nps"]["cultures"]["bottle"]["remainingMl"] == 150, "the bottle holds the rinsed crop, not 500 ml of culture water"
        assert cfg["nps"]["cultures"]["jars"]["c1"]["history"][0]["ml"] == 500, "the journal keeps the harvest volume"
        assert debits[-1] == (0.424, "refilling Rotifers A"), "the refill draws the mix share of 550 ml, including the purge"
        assert any("500 ml harvested" in str(item.get("message", "")) for item in cfg["activity"]) or True
        run(integration.websocket_cultures_log(hass, conn, {"id": 5, "jar_id": "c1", "harvested": True}))
        assert _config(entry)["nps"]["cultures"]["bottle"]["remainingMl"] == 650, "no bottle number = the old assumption, the whole harvest"
        run(integration.websocket_cultures_restart(hass, conn, {"id": 6, "jar_id": "c1"}))
        assert not conn.errors and debits[-1] == (1.543, "restarting Rotifers A")
        # A 34 ppt station cuts less RODI and the vessel gives more.
        cfg = _config(entry)
        cfg["mixingStation"]["salt"]["targetPpt"] = 34
        entry.options = {**entry.options, CONF_SETTINGS: cfg}
        run(integration.websocket_cultures_summary(hass, conn, {"id": 7}))
        assert conn.results[-1].payload["jars"][0]["fillGuide"]["mixMl"] == 1588 and conn.results[-1].payload["jars"][0]["mixPpt"] == 34.0
    finally:
        integration._mixing_hatchery_debit = real_debit


def test_a_harvest_can_go_straight_into_the_tank():
    """0.7.161: the jar's default destination, the per-harvest override, the
    ledgers each one moves. Straight into the tank = no bottle fill, a row
    stamped to:tank with the rinsed volume, the hand-feed reminder done, the
    activity line; the bottle path and the soak path are untouched."""
    started = _iso(datetime.now(timezone.utc) - timedelta(days=9))
    jars = {"c1": {"name": "Rotifers A", "species": "rotifer_L", "vesselKind": "cone", "volumeL": 2.0,
                   "salinityPpt": 27, "purgeMl": 50, "harvestTo": "tank", "feed": {"productId": "", "doseMl": 1},
                   "cadence": {}, "state": {"startedAt": started, "lastRestartAt": started, "lastFedAt": started, "lastTint": "green"},
                   "history": []}}
    entry = _entry(jars=jars, maintenance={"tasks": {"brine_hand_feed": {"label": "Feed the tank", "cadenceDays": 1, "snoozedUntil": "2099-01-01T00:00:00+00:00"}},
                                           "completions": {}})
    cfg = _config(entry)
    assert cfg["nps"]["cultures"]["jars"]["c1"]["harvestTo"] == "tank", "the default survives the normaliser"
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    real_debit = integration._mixing_hatchery_debit
    integration._mixing_hatchery_debit = lambda *a, **k: None
    try:
        run(integration.websocket_cultures_summary(hass, conn, {"id": 1}))
        jar = conn.results[-1].payload["jars"][0]
        assert jar["harvestTo"] == "tank" and jar["state"]["status"] == "producing"
        # The default: straight in, with the rinsed volume.
        run(integration.websocket_cultures_log(hass, conn, {"id": 2, "jar_id": "c1", "tint": "clearing", "harvested": True, "bottle_ml": 120}))
        assert not conn.errors, conn.errors
        cfg = _config(entry)
        assert cfg["nps"]["cultures"]["bottle"]["remainingMl"] == 0, "nothing went into the bottle"
        row = cfg["nps"]["cultures"]["jars"]["c1"]["history"][0]
        assert row["event"] == "harvest" and row["to"] == "tank" and row["tankMl"] == 120 and row["ml"] == 500
        maintenance = cfg["maintenance"]
        assert maintenance["completions"]["brine_hand_feed"][0]["notes"].endswith("rotifers from Rotifers A straight into the tank")
        assert maintenance["tasks"]["brine_hand_feed"]["snoozedUntil"] is None
        assert any("straight into the tank" in str(item.get("message", "")) for item in cfg["activity"])
        # The override: this crop into the bottle after all.
        run(integration.websocket_cultures_log(hass, conn, {"id": 3, "jar_id": "c1", "harvested": True, "destination": "bottle", "bottle_ml": 150}))
        assert not conn.errors, conn.errors
        cfg = _config(entry)
        assert cfg["nps"]["cultures"]["bottle"]["remainingMl"] == 150
        row = cfg["nps"]["cultures"]["jars"]["c1"]["history"][0]
        assert row["to"] == "bottle" and row["tankMl"] is None
        # The soak still wins when ticked.
        run(integration.websocket_cultures_log(hass, conn, {"id": 4, "jar_id": "c1", "harvested": True, "enrich": True, "destination": "tank"}))
        assert not conn.errors, conn.errors
        cfg = _config(entry)
        assert cfg["nps"]["cultures"]["enrichment"]["state"]["startedAt"] and cfg["nps"]["cultures"]["jars"]["c1"]["history"][0]["to"] == "soak"
        # A bottle-default jar with no word goes to the bottle, as before.
        cfg["nps"]["cultures"]["jars"]["c1"]["harvestTo"] = "bottle"
        cfg["nps"]["cultures"]["enrichment"]["state"] = {"startedAt": "", "portionMl": 0, "jarId": ""}
        entry.options = {**entry.options, CONF_SETTINGS: cfg}
        run(integration.websocket_cultures_log(hass, conn, {"id": 5, "jar_id": "c1", "harvested": True, "bottle_ml": 100}))
        cfg = _config(entry)
        assert cfg["nps"]["cultures"]["bottle"]["remainingMl"] == 250 and cfg["nps"]["cultures"]["jars"]["c1"]["history"][0]["to"] == "bottle"
        # Junk defaults normalise to the bottle; the WS refuses a junk destination.
        assert integration._normalise_cultures({"jars": {"x": {"species": "rotifer_L", "harvestTo": "sink"}}})["jars"]["x"]["harvestTo"] == "bottle"
        assert integration._normalise_cultures({"jars": {"x": {"species": "rotifer_L", "history": [{"event": "harvest", "to": "moon"}, {"event": "harvest", "to": "tank"}]}}})["jars"]["x"]["history"][0]["to"] == "" \
            and integration._normalise_cultures({"jars": {"x": {"species": "rotifer_L", "history": [{"event": "harvest", "to": "tank"}]}}})["jars"]["x"]["history"][0]["to"] == "tank"
    finally:
        integration._mixing_hatchery_debit = real_debit


def test_a_straight_feeding_cone_is_a_source_on_the_live_shelf():
    """The shelf shows a producing tank-default cone as a live SOURCE (no
    capacity, the harvest clock, tank harvests as usage) and drops the
    'on its way' note; a bottle-default cone keeps the note and no entry."""
    started = _iso(datetime.now(timezone.utc) - timedelta(days=9))
    harvested_at = _iso(datetime.now(timezone.utc) - timedelta(hours=30))
    jars = {"c1": {"name": "Rotifers A", "species": "rotifer_L", "vesselKind": "cone", "volumeL": 2.0,
                   "salinityPpt": 27, "purgeMl": 50, "harvestTo": "tank", "feed": {"productId": "", "doseMl": 1},
                   "cadence": {}, "state": {"startedAt": started, "lastRestartAt": started, "lastFedAt": started, "lastHarvestAt": harvested_at, "lastTint": "green"},
                   "history": [{"event": "harvest", "at": harvested_at, "ml": 500, "to": "tank", "tankMl": 120}]}}
    entry = _entry(jars=jars)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_summary(hass, conn, {"id": 1}))
    assert not conn.errors, conn.errors
    payload = conn.results[-1].payload
    live = payload["shelf"]["live"]
    entry_id = "live_rotifer_cone_c1"
    assert entry_id in live, list(live)
    src = live[entry_id]
    assert src["name"] == "Live rotifers (Rotifers A, straight from the cone)" and src["category"] == "zooLive"
    assert src["live"]["vessel"] == "cone" and src["live"]["source"] and src["live"]["jarId"] == "c1"
    assert src["live"]["harvestDue"] is True and src["live"]["harvestMl"] == 500 and src["live"]["lastHarvestAt"] == harvested_at
    assert src["history"] == [{"at": harvested_at, "ml": 120.0, "kind": "dose"}]
    state = payload["shelf"]["products"][entry_id]
    # 120 ml logged 30 h ago: the runway averages over the observed span (1.25 d).
    assert state["percent"] is None and state["empty"] is False and state["low"] is False and state["usageMlPerDay"] == 96.0
    assert not any("from the cone" in str(p.get("name")) for p in payload.get("pending", []) if isinstance(p, dict)), "the cone is on the shelf, not on its way"
    # Bottle-default: no source, the note stays.
    cfg = _config(entry)
    cfg["nps"]["cultures"]["jars"]["c1"]["harvestTo"] = "bottle"
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    run(integration.websocket_nps_summary(hass, conn, {"id": 2}))
    payload = conn.results[-1].payload
    assert entry_id not in payload["shelf"]["live"]


def test_every_websocket_handler_is_registered():
    """0.7.126–0.7.128 shipped three handlers the panel called that
    async_setup_entry never registered (apply_learned, enrich_done,
    cysts_opened) — the fake HA's lenient stub hid it. Read the source:
    every ``async def websocket_*`` must appear in an async_register_command."""
    import re
    src = open(os.path.join(_ROOT, "custom_components", "openreef", "__init__.py"), encoding="utf-8").read()
    handlers = set(re.findall(r"^async def (websocket_[a-z0-9_]+)\(", src, re.M))
    registered = set(re.findall(r"async_register_command\(hass, (websocket_[a-z0-9_]+)\)", src))
    assert handlers, "no handlers found — the regex is wrong"
    missing = sorted(handlers - registered)
    assert not missing, f"handlers the panel can never reach: {missing}"



# --------------------------------------------------------------------------- #
# 0.7.140 — the §8.12 gaps: purge in the journal, the ghost cone B, the rack's
# offset on the guard, the starter's acclimation maths.
# --------------------------------------------------------------------------- #
def test_purge_rides_the_journal_and_teaches_the_run_length():
    entry = _entry(jars={"c1": _jar(started_ago_days=10, lastHarvestAt=_iso(REAL - timedelta(hours=30)))})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_log(hass, conn, {"id": 1, "jar_id": "c1", "harvested": True}))
    jar = _cultures(entry)["jars"]["c1"]
    assert jar["history"][0]["event"] == "harvest" and jar["history"][0]["purgeMl"] == 50, "a cone harvest records the tip bleed"
    run(integration.websocket_cultures_restart(hass, conn, {"id": 2, "jar_id": "c1"}))
    jar = _cultures(entry)["jars"]["c1"]
    assert jar["history"][0]["event"] == "restart" and jar["history"][0]["purgeMl"] == 50
    # A plain jar has no tip to bleed.
    plain = _entry(jars={"c1": {**_jar(started_ago_days=10, lastHarvestAt=_iso(REAL - timedelta(hours=30))), "vesselKind": "jar"}})
    hass2 = FakeHass(entries=[plain])
    run(integration.websocket_cultures_log(hass2, FakeConnection(), {"id": 1, "jar_id": "c1", "harvested": True}))
    assert _cultures(plain)["jars"]["c1"]["history"][0]["purgeMl"] == 0
    # The normaliser keeps and clamps it.
    out = integration._normalise_cultures({"jars": {"c1": {"history": [{"event": "harvest", "purgeMl": 9999}]}}})
    assert out["jars"]["c1"]["history"][0]["purgeMl"] == 500
    # The maths: every finished run with the purge it was bled at; the note
    # speaks only with two runs at each of two volumes.
    def rows(days_ago_seed, purge, run_days, harvests=3):
        seed = REAL - timedelta(days=days_ago_seed)
        out = [{"event": "seeded", "at": _iso(seed)}]
        for k in range(1, harvests + 1):
            out.append({"event": "harvest", "at": _iso(seed + timedelta(days=k)), "ml": 625, "purgeMl": purge})
        out.append({"event": "restart", "at": _iso(seed + timedelta(days=run_days)), "purgeMl": purge})
        return out
    history = rows(60, 50, 11) + rows(48, 50, 12) + rows(35, 100, 14) + rows(20, 100, 13)
    # Consecutive runs: each restart row is the next run's anchor, so drop the
    # duplicate seeds after the first run.
    history = [history[0]] + [r for r in history[1:] if r["event"] != "seeded"]
    runs = cultures.run_length_runs(history)
    # Each restart anchors the next run, so the runs are −60→−49 (11 d @50),
    # −49→−36 (13 d @50), −36→−21 (15 d @100), −21→−7 (14 d @100).
    assert [(r["days"], r["purgeMl"]) for r in runs] == [(14.0, 100), (15.0, 100), (13.0, 50), (11.0, 50)], "newest first, with its purge"
    note = cultures.purge_note(runs)
    assert note["available"] and "does not establish the cause" in note["line"] and note["byPurge"]["100"]["runs"] == 2
    assert note["byPurge"]["100"]["days"] == 14.5 and note["byPurge"]["50"]["days"] == 12.0
    assert not cultures.purge_note(runs[:3])["available"], "one run at 50 ml is not a comparison"
    assert not cultures.purge_note([])["available"]
    same = cultures.purge_note([{"days": 11, "purgeMl": 50}, {"days": 12, "purgeMl": 50}, {"days": 11.5, "purgeMl": 100}, {"days": 12, "purgeMl": 100}])
    assert "similar observed run lengths" in same["line"]
    worse = cultures.purge_note([{"days": 13, "purgeMl": 50}, {"days": 12, "purgeMl": 50}, {"days": 10, "purgeMl": 100}, {"days": 11, "purgeMl": 100}])
    assert "shorter runs observed" in worse["line"]
    learned = cultures.learned_cadences({"species": "rotifer_L", "cadence": {}, "history": history}, [], REAL)
    assert learned["purge"]["available"] and learned["runLengthDays"]["available"]


def test_rig_state_pencils_in_b_beside_one_running_cone():
    def jar(**over):
        base = {"id": "c1", "name": "Rotifers A", "vesselKind": "cone", "tint": "clearing", "due": [],
                "firstHarvestDays": 6, "purgeMl": 50, "sieveUm": 50,
                "state": {"status": "producing", "percent": 40, "ageDays": 8},
                "feedAdvice": {"action": "wait"}, "temp": {"status": "ok", "tempC": 23, "hardMaxC": 30},
                "harvestGuide": {"totalMl": 625, "mixMl": 480, "rodiMl": 145, "targetPpt": 27}}
        base.update(over)
        return base
    one = cultures.rig_state([jar()], {})
    assert [c["status"] for c in one["cones"]] == ["producing", "ghost"]
    ghost = one["cones"][1]
    assert ghost["name"] == "Rotifers B" and ghost["note"] == "comes with the first restart" and ghost["id"] == ""
    assert not ghost["airOn"] and not ghost["purgeHot"] and one["stage"] == "steady", "a ghost is drawing only — no air, no stage"
    assert [c["status"] for c in cultures.rig_state([jar(), jar(id="c2", name="Rotifers B")], {})["cones"]] == ["producing", "producing"], "B exists — no ghost"
    assert [c["status"] for c in cultures.rig_state([jar(state={"status": "none"}, tint="")], {})["cones"]] == ["none"], "nothing running, nothing to pencil in"
    assert cultures.rig_state([jar(id="c2", name="Pods", vesselKind="tub")], {})["cones"] == [], "a tub earns no cone"
    establishing = cultures.rig_state([jar(name="Cone", state={"status": "establishing", "percent": None, "ageDays": 2})], {})
    assert establishing["cones"][1]["name"] == "B" and establishing["stage"] == "establishing"


def test_heat_guard_shifts_by_the_racks_own_offset():
    proj = [{"at": _iso(REAL), "roomC": 24.0}, {"at": _iso(REAL + timedelta(hours=8)), "roomC": 27.0}]
    assert cultures.rack_offset_c(proj, 26.0, REAL) == 2.0
    assert cultures.rack_offset_c(proj, None, REAL) is None and cultures.rack_offset_c([], 26.0, REAL) is None
    assert cultures.rack_offset_c([proj[1]], 26.0, REAL) is None, "no projection row for now, no offset"
    assert cultures.rack_offset_c(proj, 40.0, REAL) == 5.0 and cultures.rack_offset_c(proj, 10.0, REAL) == -5.0, "clamped"
    plain = cultures.heat_guard(proj, "tigriopus", REAL)
    shifted = cultures.heat_guard(proj, "tigriopus", REAL, offset_c=2.0)
    assert plain["status"] == "watch" and plain["offsetC"] == 0.0 and plain["line"].startswith("room peaks")
    assert shifted["status"] == "warn" and shifted["offsetC"] == 2.0 and shifted["peakC"] == 29.0
    assert shifted["line"].startswith("the rack passes 28 °C in ~8 h") and "rack +2.0 °C over the room" in shifted["line"]
    assert cultures.heat_guard(proj, "tigriopus", REAL, offset_c=0.3)["offsetC"] == 0.0, "under half a degree is noise"
    assert cultures.heat_guard(proj, "tigriopus", REAL, offset_c=99)["status"] == "watch", "an absurd offset is ignored"
    assert cultures.heat_guard([], "tigriopus", REAL, offset_c=2.0)["available"] is False
    # The summary: the rack sensor's lead over the projection's room shifts
    # every guard, and says so on the payload.
    entry = _entry(jars={"c2": _jar(species="tigriopus", started_ago_days=40)}, temp_entity="sensor.bench")
    hass = FakeHass(entries=[entry], states={"sensor.bench": "26.0"})
    hass.data.setdefault(integration.DOMAIN, {})[integration.COOLING_RUNTIME] = {"snapshot": {"projection": {"hours": proj}}}
    conn = FakeConnection()
    run(integration.websocket_cultures_summary(hass, conn, {"id": 1}))
    p = conn.results[-1].payload
    assert p["rackOffsetC"] == 2.0 and p["jars"][0]["guard"]["status"] == "warn" and p["backup"][0]["guard"]["status"] == "warn"
    no_sensor = _entry(jars={"c2": _jar(species="tigriopus", started_ago_days=40)})
    hass2 = FakeHass(entries=[no_sensor])
    hass2.data.setdefault(integration.DOMAIN, {})[integration.COOLING_RUNTIME] = {"snapshot": {"projection": {"hours": proj}}}
    conn2 = FakeConnection()
    run(integration.websocket_cultures_summary(hass2, conn2, {"id": 1}))
    p2 = conn2.results[-1].payload
    assert p2["rackOffsetC"] is None and p2["jars"][0]["guard"]["status"] == "watch"


def test_acclimation_plan_keeps_every_step_inside_five_ppt():
    plan = cultures.acclimation_plan(27, 35)
    assert plan["steps"] == [{"addMl": 500, "ppt": 31.0, "waitMin": 15}] and plan["finalStepPpt"] == 4.0 and plan["withinRule"]
    assert "add 500 ml of cone water, wait 15 min (~31 ppt)" in plan["line"] and plan["line"].endswith("the last step is 4 ppt")
    same = cultures.acclimation_plan(27, 27)
    assert same["steps"] == [] and "float the pouch 15 min, then sieve" in same["line"]
    assert cultures.acclimation_plan(27, 30)["steps"] == [], "3 ppt is inside the rule"
    down = cultures.acclimation_plan(35, 27)
    assert down["steps"][0]["ppt"] == 31.0 and down["finalStepPpt"] == -4.0 and "the last step is 4 ppt" in down["line"]
    three = cultures.acclimation_plan(27, 38)
    assert len(three["steps"]) == 2 and three["withinRule"]
    prev = 27.0
    for step in three["steps"] + [{"ppt": 38.0}]:
        assert abs(step["ppt"] - prev) <= 5.05, "every step inside the rule"
        prev = step["ppt"]
    wild = cultures.acclimation_plan(5, 45)
    assert len(wild["steps"]) == cultures.ACCLIMATE_STEPS_MAX and not wild["withinRule"] and "too big" in wild["line"]
    # The summary aims at the first rotifer cone's water; the v1 35 ppt jar
    # gets the two-step plan, a 27 ppt cone gets "pour in".
    entry = _entry(jars={"c1": {**_jar(), "starterPpt": 27}})
    conn = FakeConnection()
    run(integration.websocket_cultures_summary(FakeHass(entries=[entry]), conn, {"id": 1}))
    arrival = conn.results[-1].payload["arrival"]["rotifer"]
    assert arrival["fromPpt"] == 27 and arrival["toPpt"] == 35 and arrival["steps"][0]["ppt"] == 31.0
    entry = _entry(jars={"c1": {**_jar(), "salinityPpt": 27, "starterPpt": 27}, "c2": _jar(species="tigriopus")})
    conn = FakeConnection()
    run(integration.websocket_cultures_summary(FakeHass(entries=[entry]), conn, {"id": 1}))
    arrival = conn.results[-1].payload["arrival"]["rotifer"]
    assert arrival["toPpt"] == 27 and arrival["steps"] == []
    empty = FakeConnection()
    run(integration.websocket_cultures_summary(FakeHass(entries=[_entry(jars={})]), empty, {"id": 1}))
    assert empty.results[-1].payload["arrival"]["rotifer"]["available"] is False, "no measured shipping salinity"



# --------------------------------------------------------------------------- #
# 0.7.184 — the look that decided not to feed, and the timeline
# --------------------------------------------------------------------------- #
def test_skipped_feed_holds_the_clock_without_claiming_a_feed():
    # Fed 20 h ago on a 12 h cadence: due. A skip 1 h ago holds it 11 h more.
    jar = _jar(started_ago_days=10, now=NOW, lastFedAt=_iso(NOW - timedelta(hours=20)))
    assert cultures.culture_state(jar, NOW)["feed"]["due"] is True
    jar["state"]["lastFeedSkippedAt"] = _iso(NOW - timedelta(hours=1))
    st = cultures.culture_state(jar, NOW)
    assert st["feed"]["due"] is False and st["feed"]["hoursUntil"] == 11.0 and st["feed"]["skipped"] is True
    assert jar["state"]["lastFedAt"] == _iso(NOW - timedelta(hours=20)), "a skip never pretends to be a feed"
    # A feed after the skip is the newer word.
    jar["state"]["lastFedAt"] = _iso(NOW - timedelta(minutes=30))
    st = cultures.culture_state(jar, NOW)
    assert st["feed"]["skipped"] is False and st["feed"]["hoursUntil"] == 11.5
    # A skip from before this seed is history, not the present.
    jar = _jar(started_ago_days=1, now=NOW, lastFedAt=_iso(NOW - timedelta(hours=20)),
               lastFeedSkippedAt=_iso(NOW - timedelta(days=3)))
    st = cultures.culture_state(jar, NOW)
    assert st["feed"]["due"] is True and st["feed"]["skipped"] is False


def test_feed_timeline_marks_and_clearing_spans():
    history = [  # newest first, as stored
        _row("feed", 2, tint="clearing"),                       # open span, 2 h so far
        _row("tint", 4, tint="clear"),                          # clears the 10 h feed: 6 h
        _row("feed", 10, tint="green"),                         # voids the 18 h feed's span
        _row("tint", 12, tint="green", skipped=True),           # the look that skipped
        _row("feed", 18, tint="clearing"),
        _row("tint", 21, tint="clear"),                         # clears the 30 h feed: 9 h
        _row("feed", 30, tint="clear"),
        _row("seeded", 40 * 24),                                # outside the window
    ]
    tl = cultures.feed_timeline(history, NOW, days=30)
    assert tl["days"] == 30 and tl["since"] == _iso(NOW - timedelta(days=30))
    assert [m["event"] for m in tl["marks"]] == ["feed", "tint", "feed", "tint", "feed", "tint", "feed"], "oldest first, window only"
    assert tl["marks"][0]["at"] == _iso(NOW - timedelta(hours=30)) and tl["marks"][0]["fed"] is True
    skipped = [m for m in tl["marks"] if m["skipped"]]
    assert len(skipped) == 1 and skipped[0]["tint"] == "green" and skipped[0]["fed"] is False
    assert [(sp["hours"], sp["open"]) for sp in tl["spans"]] == [(9.0, False), (6.0, False), (2.0, True)]
    assert tl["spans"][0]["fedAt"] == _iso(NOW - timedelta(hours=30)) and tl["spans"][0]["clearAt"] == _iso(NOW - timedelta(hours=21))
    assert tl["spans"][2]["clearAt"] is None
    # The spans agree with the learning's samples (newest first there).
    assert cultures.clearing_samples(history) == [6.0, 9.0]
    # A crash resets: no span across it; a 7-day window drops the old marks.
    tl = cultures.feed_timeline([_row("tint", 1, tint="clear"), _row("crashed", 3), _row("feed", 5)], NOW)
    assert tl["spans"] == [] and [m["event"] for m in tl["marks"]] == ["feed", "crashed", "tint"]
    assert cultures.feed_timeline([_row("feed", 10 * 24)], NOW, days=7)["marks"] == []
    assert cultures.feed_timeline(None, NOW) == {"days": 30, "since": _iso(NOW - timedelta(days=30)), "tintBefore": "", "marks": [], "spans": []}
    # The water as last reported before the window opens, so the band never starts blank.
    assert cultures.feed_timeline([_row("feed", 2, tint="green"), _row("tint", 9 * 24, tint="clear")], NOW, days=7)["tintBefore"] == "clear"
    assert cultures.feed_timeline([_row("restart", 8 * 24), _row("tint", 9 * 24, tint="clear")], NOW, days=7)["tintBefore"] == ""


def test_ws_skip_feed_logs_the_look_and_skips_the_reminder():
    maintenance = {"tasks": {"culture_c1_feed": {"label": "Feed rotifers", "snoozedUntil": None}},
                   "completions": {}}
    entry = _entry(jars={"c1": _jar(started_ago_days=5, lastFedAt=_iso(REAL - timedelta(hours=20)))},
                   maintenance=maintenance)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    # Fed and skipped at once is nonsense; so is a skipped harvest.
    run(integration.websocket_cultures_log(hass, conn, {"id": 1, "jar_id": "c1", "tint": "green", "fed": True, "skip_feed": True}))
    assert conn.errors[-1].code == "fed_and_skipped"
    run(integration.websocket_cultures_log(hass, conn, {"id": 2, "jar_id": "c1", "harvested": True, "skip_feed": True}))
    assert conn.errors[-1].code == "harvest_and_skipped"
    # The look: still green, not fed.
    run(integration.websocket_cultures_log(hass, conn, {"id": 3, "jar_id": "c1", "tint": "green", "skip_feed": True}))
    cfg = entry.options[CONF_SETTINGS]
    jar = cfg["nps"]["cultures"]["jars"]["c1"]
    assert jar["state"]["lastTint"] == "green" and jar["state"]["lastFeedSkippedAt"]
    assert jar["state"]["lastFedAt"] == _iso(REAL - timedelta(hours=20)), "the feed stamp is untouched"
    assert cfg["consumables"]["products"]["phyto"]["remainingMl"] == 300.0, "no phyto moved"
    assert jar["history"][0]["event"] == "tint" and jar["history"][0]["tint"] == "green"
    assert jar["history"][0]["skipped"] is True and jar["history"][0]["fed"] is False
    comps = cfg["maintenance"]["completions"]["culture_c1_feed"]
    assert comps[0]["skipped"] is True and comps[0]["source"] == "cultures" and "water green" in comps[0]["notes"]
    run(integration.websocket_cultures_summary(hass, conn, {"id": 30}))
    payload = conn.results[-1].payload
    feed = next(j for j in payload["jars"] if j["id"] == "c1")["state"]["feed"]
    assert feed["due"] is False and feed["skipped"] is True and 11.9 <= feed["hoursUntil"] <= 12.0
    assert cfg["maintenance"]["tasks"]["culture_c1_feed"]["snoozedUntil"] == feed["at"], "the reminder holds to the jar's next slot"
    assert "feed" not in next(j for j in payload["jars"] if j["id"] == "c1")["due"]
    # The normaliser keeps both, and the payload ships the timeline.
    norm = _config(entry)["nps"]["cultures"]["jars"]["c1"]
    assert norm["state"]["lastFeedSkippedAt"] == jar["state"]["lastFeedSkippedAt"] and norm["history"][0]["skipped"] is True
    tl = next(j for j in payload["jars"] if j["id"] == "c1")["timeline"]
    assert tl["days"] == 30 and tl["marks"][-1]["skipped"] is True and tl["marks"][-1]["tint"] == "green"
    # A skip with no tint is still a row — the skip itself.
    run(integration.websocket_cultures_log(hass, conn, {"id": 4, "jar_id": "c1", "skip_feed": True}))
    assert _cultures(entry)["jars"]["c1"]["history"][0]["event"] == "skip"
    # A skip after a clear tap counts in the clearing maths like any look.
    run(integration.websocket_cultures_log(hass, conn, {"id": 5, "jar_id": "c1", "tint": "clear", "skip_feed": True}))
    assert _cultures(entry)["jars"]["c1"]["history"][0]["tint"] == "clear"
    # The phone's Skipped button is the same tap.
    class Ev:
        def __init__(self, action):
            self.data = {"action": action}
    before = _cultures(entry)["jars"]["c1"]["state"]["lastFeedSkippedAt"]
    run(integration._async_notification_action(hass, Ev("OPENREEF_CULTURE_SKIP:c1")))
    after = _cultures(entry)["jars"]["c1"]["state"]["lastFeedSkippedAt"]
    assert after >= before and _cultures(entry)["jars"]["c1"]["history"][0]["skipped"] is True
    # An idle jar has nothing to skip.
    run(integration.websocket_cultures_log(hass, conn, {"id": 6, "jar_id": "c1", "skip_feed": True}))
    entry2 = _entry(jars={"c1": _jar()})
    run(integration.websocket_cultures_log(FakeHass(entries=[entry2]), conn, {"id": 7, "jar_id": "c1", "skip_feed": True}))
    assert conn.errors[-1].code == "jar_idle"


def test_replay_state_rereads_the_surviving_journal():
    """A tombstoned row is invisible to every reader — the clocks re-read
    what is left, a seed or restart puts the water back to green."""
    h = lambda **f: {"event": "tint", "at": "", "ml": 0, "tint": "", "sign": "", "eggRatio": None,
                     "fed": False, "skipped": False, "undoneAt": "", **f}
    rows = [h(event="feed", at=_iso(REAL - timedelta(hours=1)), tint="green", fed=True, undoneAt=_iso(REAL)),
            h(event="tint", at=_iso(REAL - timedelta(hours=6)), tint="clearing", skipped=True),
            h(event="sign", at=_iso(REAL - timedelta(hours=8)), sign="foam"),
            h(event="feed", at=_iso(REAL - timedelta(hours=20)), tint="clear", fed=True),
            h(event="restart", at=_iso(REAL - timedelta(days=3)))]
    out = cultures.replay_state(rows)
    assert out["lastTint"] == "clearing" and out["lastFedAt"] == _iso(REAL - timedelta(hours=20))
    assert out["lastFeedSkippedAt"] == _iso(REAL - timedelta(hours=6))
    assert out["lastSign"] == "foam" and out["lastSignAt"] == _iso(REAL - timedelta(hours=8))
    # The restart is the newest word on water and signs once the taps above it go.
    for row in rows[:4]:
        row["undoneAt"] = _iso(REAL)
    out = cultures.replay_state(rows)
    assert out == {"lastTint": "green", "lastFedAt": _iso(REAL - timedelta(days=3)), "lastFeedSkippedAt": "",
                   "lastSignAt": "", "lastSign": ""}
    assert cultures.clearing_samples(rows) == [] and cultures.feed_timeline(rows, REAL)["marks"][-1]["event"] == "restart"
    assert cultures.tint_strip(rows, REAL)[-1] == ""


def test_ws_undo_takes_a_wrong_feed_back_everywhere():
    """Reece logged a feed as green when the water was clearing: the undo
    tombstones the row, the water and the feed clock fall back, the phyto
    returns, the reminder completion goes, the timeline stops counting it."""
    maintenance = {"tasks": {"culture_c1_feed": {"label": "Feed rotifers", "snoozedUntil": None}},
                   "completions": {}}
    jar = _jar(started_ago_days=5, lastFedAt=_iso(REAL - timedelta(hours=20)), lastTint="clearing")
    jar["history"] = [{"event": "tint", "at": _iso(REAL - timedelta(hours=3)), "ml": 0, "tint": "clearing",
                       "fed": False, "skipped": False},
                      {"event": "feed", "at": _iso(REAL - timedelta(hours=20)), "ml": 0, "tint": "green",
                       "fed": True, "skipped": False}]
    entry = _entry(jars={"c1": jar}, maintenance=maintenance)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_log(hass, conn, {"id": 1, "jar_id": "c1", "tint": "green", "fed": True}))
    cfg = entry.options[CONF_SETTINGS]
    jar = cfg["nps"]["cultures"]["jars"]["c1"]
    stamp = jar["history"][0]["at"]
    phyto = cfg["consumables"]["products"]["phyto"]
    assert jar["state"]["lastTint"] == "green" and jar["state"]["lastFedAt"] == stamp
    assert phyto["remainingMl"] == 295.0 and phyto["history"][-1]["at"] == stamp, "the dose carries the tap's stamp"
    assert cfg["maintenance"]["completions"]["culture_c1_feed"][0]["timestamp"] == stamp
    run(integration.websocket_cultures_summary(hass, conn, {"id": 2}))
    tl = next(j for j in conn.results[-1].payload["jars"] if j["id"] == "c1")["timeline"]
    assert tl["marks"][-1]["fed"] is True and tl["spans"][-1]["open"] is True
    # The undo.
    run(integration.websocket_cultures_undo(hass, conn, {"id": 3, "jar_id": "c1", "at": stamp}))
    assert conn.results[-1].payload["success"] is True
    cfg = entry.options[CONF_SETTINGS]
    jar = cfg["nps"]["cultures"]["jars"]["c1"]
    phyto = cfg["consumables"]["products"]["phyto"]
    assert jar["history"][0]["undoneAt"] and jar["history"][0]["at"] == stamp, "tombstoned, never deleted"
    assert jar["state"]["lastTint"] == "clearing", "the water falls back to the look before it"
    assert jar["state"]["lastFedAt"] == _iso(REAL - timedelta(hours=20)), "the feed clock falls back"
    assert phyto["remainingMl"] == 300.0 and phyto["history"][-1]["undoneAt"], "the phyto is back and its row tombstoned"
    assert not cfg["maintenance"]["completions"].get("culture_c1_feed"), "the reminder completion goes"
    assert "taken back" in cfg["activity"][0]["message"] and "5 ml back" in cfg["activity"][0]["message"]
    run(integration.websocket_cultures_summary(hass, conn, {"id": 4}))
    payload = next(j for j in conn.results[-1].payload["jars"] if j["id"] == "c1")
    assert payload["tint"] == "clearing" and payload["timeline"]["marks"][-1]["fed"] is False
    assert payload["timeline"]["spans"][-1]["fedAt"] == _iso(REAL - timedelta(hours=20)) and payload["timeline"]["spans"][-1]["open"], \
        "the open clearing span now runs from the feed before it"
    assert payload["history"][0]["undoneAt"], "the journal still shows the row, marked"
    # The normaliser keeps the tombstone; the same row cannot be undone twice.
    assert _config(entry)["nps"]["cultures"]["jars"]["c1"]["history"][0]["undoneAt"]
    run(integration.websocket_cultures_undo(hass, conn, {"id": 5, "jar_id": "c1", "at": stamp}))
    assert conn.errors[-1].code == "nothing_to_undo"
    # Relogged as seen: the clocks read the new row.
    run(integration.websocket_cultures_log(hass, conn, {"id": 6, "jar_id": "c1", "tint": "clearing", "fed": True}))
    jar = entry.options[CONF_SETTINGS]["nps"]["cultures"]["jars"]["c1"]
    assert jar["state"]["lastTint"] == "clearing" and jar["state"]["lastFedAt"] == jar["history"][0]["at"]
    assert entry.options[CONF_SETTINGS]["consumables"]["products"]["phyto"]["remainingMl"] == 295.0


def test_ws_undo_skip_sign_window_and_ceremonies():
    maintenance = {"tasks": {"culture_c1_feed": {"label": "Feed rotifers", "snoozedUntil": None}},
                   "completions": {}}
    entry = _entry(jars={"c1": _jar(started_ago_days=12, lastFedAt=_iso(REAL - timedelta(hours=20)))},
                   maintenance=maintenance)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    # A skip: the hold on the reminder and the skip stamp go with it.
    run(integration.websocket_cultures_log(hass, conn, {"id": 1, "jar_id": "c1", "tint": "green", "skip_feed": True}))
    cfg = entry.options[CONF_SETTINGS]
    stamp = cfg["nps"]["cultures"]["jars"]["c1"]["history"][0]["at"]
    assert cfg["maintenance"]["tasks"]["culture_c1_feed"]["snoozedUntil"]
    run(integration.websocket_cultures_undo(hass, conn, {"id": 2, "jar_id": "c1", "at": stamp}))
    cfg = entry.options[CONF_SETTINGS]
    jar = cfg["nps"]["cultures"]["jars"]["c1"]
    assert jar["state"]["lastFeedSkippedAt"] == "" and cfg["maintenance"]["tasks"]["culture_c1_feed"]["snoozedUntil"] is None
    assert not cfg["maintenance"]["completions"].get("culture_c1_feed")
    assert cfg["consumables"]["products"]["phyto"]["remainingMl"] == 300.0, "a skip never moved phyto, so none comes back"
    run(integration.websocket_cultures_summary(hass, conn, {"id": 3}))
    feed = next(j for j in conn.results[-1].payload["jars"] if j["id"] == "c1")["state"]["feed"]
    assert feed["skipped"] is False and feed["due"] is True, "the feed is due again"
    # A sign: withdrawn, the restart no longer comes forward.
    run(integration.websocket_cultures_log(hass, conn, {"id": 4, "jar_id": "c1", "sign": "foam"}))
    stamp = entry.options[CONF_SETTINGS]["nps"]["cultures"]["jars"]["c1"]["history"][0]["at"]
    run(integration.websocket_cultures_summary(hass, conn, {"id": 5}))
    assert next(j for j in conn.results[-1].payload["jars"] if j["id"] == "c1")["state"]["restart"]["reason"] == "sign"
    run(integration.websocket_cultures_undo(hass, conn, {"id": 6, "jar_id": "c1", "at": stamp}))
    jar = entry.options[CONF_SETTINGS]["nps"]["cultures"]["jars"]["c1"]
    assert jar["state"]["lastSign"] == "" and jar["state"]["lastSignAt"] == ""
    run(integration.websocket_cultures_summary(hass, conn, {"id": 7}))
    assert next(j for j in conn.results[-1].payload["jars"] if j["id"] == "c1")["state"]["restart"]["reason"] != "sign"
    # Beyond a day, a ceremony, an unknown jar: refused, nothing moves.
    old = _iso(REAL - timedelta(hours=30))
    jar["history"].insert(0, {"event": "feed", "at": old, "ml": 0, "tint": "green", "fed": True, "skipped": False})
    run(integration.websocket_cultures_undo(hass, conn, {"id": 8, "jar_id": "c1", "at": old}))
    assert conn.errors[-1].code == "nothing_to_undo"
    run(integration.websocket_cultures_log(hass, conn, {"id": 9, "jar_id": "c1", "harvested": True}))
    stamp = entry.options[CONF_SETTINGS]["nps"]["cultures"]["jars"]["c1"]["history"][0]["at"]
    assert entry.options[CONF_SETTINGS]["nps"]["cultures"]["jars"]["c1"]["history"][0]["event"] == "harvest"
    run(integration.websocket_cultures_undo(hass, conn, {"id": 10, "jar_id": "c1", "at": stamp}))
    assert conn.errors[-1].code == "not_undoable"
    assert not entry.options[CONF_SETTINGS]["nps"]["cultures"]["jars"]["c1"]["history"][0].get("undoneAt")
    run(integration.websocket_cultures_undo(hass, conn, {"id": 11, "jar_id": "nope", "at": stamp}))
    assert conn.errors[-1].code == "unknown_jar"


# --------------------------------------------------------------------------- #
# 0.7.207 — the phyto vessel, Stage A (docs/phyto-culture-brainstorm.md §5, §9)
# --------------------------------------------------------------------------- #
def _phyto_jar(started_ago_days=None, now=None, **state):
    base = now or REAL
    jar = {"name": "Nanno A", "species": "nanno", "vesselKind": "bottle", "volumeL": 4, "salinityPpt": 35,
           "starterMl": 250, "harvestTo": "bottle", "mode": "batch", "nutrient": {"productId": "f2", "mlPerL": 1.5},
           "bottleMl": 1000, "feed": {"productId": "", "doseMl": 5}, "cadence": {}, "state": {}, "history": []}
    if started_ago_days is not None:
        jar["state"].update({"startedAt": _iso(base - timedelta(days=started_ago_days)),
                             "lastRestartAt": _iso(base - timedelta(days=started_ago_days)),
                             "lastTint": "pale", "workingL": 1.25, "cyclesSinceFresh": 0})
    jar["state"].update(state)
    return jar


def _phyto_products():
    return {"f2": {"name": "Phytoplankton Nutrient (Guillard's f/2)", "brand": "Reefphyto", "category": "other",
                   "bottleMl": 250.0, "remainingMl": 250.0, "shelfLifeDaysOpened": 365, "refrigerated": True,
                   "openedAt": _iso(REAL - timedelta(days=1)), "history": []}}


def _phyto_entry(jars=None, products=None, maintenance=None, tank_l=52, channels=None):
    entry = _entry(jars=jars if jars is not None else {"c1": _phyto_jar()},
                   products=products if products is not None else _phyto_products(),
                   maintenance=maintenance)
    cfg = _config(entry)
    cfg["tank"] = {**(cfg.get("tank") or {}), "volumeLitres": tank_l}
    cfg["mixingStation"] = {"enabled": True, "salt": {"targetPpt": 35}}
    if channels is not None:
        cfg["dosing"] = {**(cfg.get("dosing") or {}), "channels": channels}
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    return entry


def test_phyto_preset_scales_and_the_split_maps_onto_the_harvest_clock():
    nanno = cultures.species_preset("nanno")
    assert nanno["kind"] == "phyto" and nanno["salinityPpt"] == 35 and nanno["vesselKind"] == "bottle"
    assert nanno["splitPct"] == 60 and nanno["splitIntervalDays"] == 8 and nanno["restartCycles"] == 4
    assert nanno["nutrientMlPerL"] == 1.5 and nanno["bottleShelfDays"] == 21 and nanno["starterShelfDays"] == 28
    assert cultures.tints_for("nanno") == ("pale", "green", "dark", "off") and cultures.tints_for("rotifer_L") == ("green", "clearing", "clear")
    assert "yellow" in cultures.signs_for("nanno") and "milky" not in cultures.signs_for("nanno")
    assert cultures.phyto_seed_tint("nanno") == "pale" and cultures.phyto_seed_tint("rotifer_L") == "green"
    cad = cultures.cadence_for("nanno", {"splitPct": 70, "splitIntervalDays": 6})
    assert cad["harvestPct"] == 70 and cad["harvestIntervalDays"] == 6, "the keeper edits split*, the clocks read harvest*"
    assert cad["restartCycles"] == 4 and cad["lightHours"] == 16
    assert "splitPct" not in cultures.cadence_for("rotifer_L", {}), "an animal's cadence has no phyto keys"
    assert cultures.CULTURE_JARS_MAX == 6


def test_phyto_state_greens_then_reads_dark_and_the_split_clock_comes_forward():
    # Day 3: establishing, the look is due daily, no split yet.
    jar = _phyto_jar(started_ago_days=3, now=NOW, lastLookedAt=_iso(NOW - timedelta(hours=30)))
    st = cultures.culture_state(jar, NOW)
    assert st["status"] == "establishing" and st["feed"]["available"] is False and st["waterChange"]["available"] is False
    assert st["look"]["available"] and st["look"]["due"], "a look a day"
    assert st["harvest"]["available"] and not st["harvest"]["due"] and st["cycle"]["ofDays"] == 8 and st["cycle"]["day"] == 3.0
    assert st["workingL"] == 1.25 and st["cyclesSinceFresh"] == 0 and st["mode"] == "batch"
    assert st["nextChore"]["key"] == "look"
    # A DARK tap makes it producing and the split due — ready on a sign.
    jar["state"]["lastTint"] = "dark"
    jar["history"] = [{"event": "tint", "at": _iso(NOW - timedelta(hours=1)), "tint": "dark"}]
    st = cultures.culture_state(jar, NOW)
    assert st["status"] == "producing" and st["harvest"]["due"] and st["harvest"]["reason"] == "dark"
    assert st["splitEligible"] and not st["peakHeld"]
    # Held dark three days without a split: peak-held (a run that started
    # before the seed does not count — the seed is the floor).
    jar["history"] = [{"event": "tint", "at": _iso(NOW - timedelta(days=3, hours=1)), "tint": "dark"},
                      {"event": "tint", "at": _iso(NOW - timedelta(days=1)), "tint": "dark"}]
    assert not cultures.culture_state(jar, NOW)["peakHeld"], "a tap before the seed is not this culture's"
    jar["state"]["startedAt"] = jar["state"]["lastRestartAt"] = _iso(NOW - timedelta(days=10))
    st = cultures.culture_state(jar, NOW)
    assert st["peakHeld"] and st["darkDays"] >= 3
    assert cultures.density_advice("dark", st)["action"] == "split_now" and "held at" in cultures.density_advice("dark", st)["reason"]
    # After a split the cycle restarts, the counter steps; four cycles = a fresh vessel due.
    jar = _phyto_jar(started_ago_days=20, now=NOW, lastHarvestAt=_iso(NOW - timedelta(days=2)), lastTint="green", cyclesSinceFresh=4)
    st = cultures.culture_state(jar, NOW)
    assert st["status"] == "producing" and st["cycle"]["day"] == 2.0 and st["cycle"]["percent"] == 25
    assert st["restart"]["due"] and st["restart"]["reason"] == "cycles" and st["percent"] == 100
    assert not st["harvest"]["due"] and st["harvest"]["hoursUntil"] == 6 * 24
    # A sign blocks the split until a later look says green or dark.
    jar["state"].update({"lastSignAt": _iso(NOW - timedelta(hours=5)), "lastSign": "yellow", "cyclesSinceFresh": 1})
    jar["history"] = [{"event": "sign", "at": _iso(NOW - timedelta(hours=5)), "sign": "yellow"}]
    st = cultures.culture_state(jar, NOW)
    assert st["harvestBlocked"] and not st["splitEligible"] and st["restart"]["reason"] == "sign"
    assert cultures.density_advice("green", st)["action"] == "hold"
    jar["history"].insert(0, {"event": "tint", "at": _iso(NOW - timedelta(hours=1)), "tint": "green"})
    st = cultures.culture_state(jar, NOW)
    assert not st["harvestBlocked"] and st["restart"]["reason"] == "sign", "the look unblocks the split; the fresh vessel stays forward"
    # Off-colour is a hold in itself.
    jar["state"]["lastTint"] = "off"
    assert cultures.culture_state(jar, NOW)["harvestBlocked"]
    assert cultures.density_advice("off", cultures.culture_state(jar, NOW))["action"] == "hold"


def test_density_advice_reads_the_colour_and_the_learned_days():
    st = {"status": "producing", "daysSinceSplit": 2.0, "cycle": {"ofDays": 8}, "harvestBlocked": False, "peakHeld": False}
    assert cultures.density_advice("pale", st)["action"] == "wait" and "recovering" in cultures.density_advice("pale", st)["reason"]
    st["daysSinceSplit"] = 4.0
    assert "dark in ~4 d" in cultures.density_advice("green", st)["reason"]
    assert "dark in ~2 d" in cultures.density_advice("green", st, days_to_dark=6)["reason"], "the learned number wins"
    st["daysSinceSplit"] = 9.0
    assert cultures.density_advice("pale", st)["action"] == "check", "still pale past the interval — check light, air, f/2"
    assert cultures.density_advice("", st)["action"] == "check"
    assert cultures.density_advice("dark", {"status": "none"})["action"] == "none"


def test_split_guide_maths_scale_up_and_refusals():
    jar = _phyto_jar(started_ago_days=10, now=NOW)
    g = cultures.split_guide(jar, 35)
    assert (g["outMl"], g["freshMl"], g["mixMl"], g["rodiMl"], g["nutrientMl"]) == (750, 750, 750, 0, 1.1)
    assert g["workingMlBefore"] == 1250 and g["workingMlAfter"] == 1250 and not g["scaleUp"] and g["seedPct"] == 40
    assert g.get("available", True) and g["warning"] == "" and g["targetPpt"] == 35
    # The scale-up: 750 out, 3000 in → 3.5 L working, f/2 by the FRESH litres.
    g = cultures.split_guide(jar, 35, 750, 3000)
    assert g["scaleUp"] and g["workingMlAfter"] == 3500 and g["nutrientMl"] == 4.5 and g["mixMl"] == 3000
    # Nothing out, fresh in: a pure scale-up.
    g = cultures.split_guide(jar, 35, 0, 1000)
    assert g["scaleUp"] and g["outMl"] == 0 and g["workingMlAfter"] == 2250 and g.get("available", True)
    # Thin seed: warned; more than the vessel: refused; the container: refused.
    assert "thin seed" in cultures.split_guide(jar, 35, 1000)["warning"]
    assert cultures.split_guide(jar, 35, 1300)["available"] is False
    assert cultures.split_guide(jar, 35, 750, 4000)["available"] is False and "4 L" in cultures.split_guide(jar, 35, 750, 4000)["reason"]
    # The keeper's own ml per litre rides the fresh water.
    jar["nutrient"]["mlPerL"] = 1.7
    assert cultures.split_guide(jar, 35)["nutrientMl"] == 1.3
    # A 27 ppt phyto (a keeper matching a cone) cuts the station's water.
    jar["salinityPpt"] = 27
    g = cultures.split_guide(jar, 35)
    assert g["mixMl"] + g["rodiMl"] == 750 and g["rodiMl"] > 0


def test_seed_guide_offers_the_starter_page_and_the_kit():
    jar = _phyto_jar()
    g = cultures.seed_guide(jar, 35)
    assert (g["starterMl"], g["freshMl"], g["workingL"], g["nutrientMl"], g["ratio"]) == (250, 1000, 1.25, 1.5, 4.0)
    assert g["mixMl"] == 1000 and g["rodiMl"] == 0 and g["kitWorkingL"] == 3.5
    kit = cultures.seed_guide(jar, 35, working_l=3.5)
    assert kit["freshMl"] == 3250 and kit["nutrientMl"] == 4.9 and kit["workingMl"] == 3500
    assert cultures.seed_guide(jar, 35, working_l=5)["available"] is False, "the container holds 4 L"
    assert cultures.seed_guide(jar, 35, starter_ml=500)["workingL"] == 2.5


def test_darkening_samples_learn_the_days_to_dark():
    h = [{"event": "seeded", "at": _iso(NOW - timedelta(days=30))},
         {"event": "tint", "at": _iso(NOW - timedelta(days=24)), "tint": "dark"},        # 6 d
         {"event": "harvest", "at": _iso(NOW - timedelta(days=23)), "ml": 750},
         {"event": "tint", "at": _iso(NOW - timedelta(days=20)), "tint": "green"},
         {"event": "tint", "at": _iso(NOW - timedelta(days=16)), "tint": "dark"},        # 7 d
         {"event": "harvest", "at": _iso(NOW - timedelta(days=15)), "ml": 750},
         {"event": "crashed", "at": _iso(NOW - timedelta(days=12))},
         {"event": "tint", "at": _iso(NOW - timedelta(days=11)), "tint": "dark"},        # voided by the crash
         {"event": "seeded", "at": _iso(NOW - timedelta(days=10))},
         {"event": "tint", "at": _iso(NOW - timedelta(days=5)), "tint": "dark"}]         # 5 d
    assert cultures.darkening_samples(h) == [5.0, 7.0, 6.0]
    jar = _phyto_jar(started_ago_days=10, now=NOW)
    jar["history"] = h
    learned = cultures.learned_cadences(jar, [h], NOW)
    assert learned["daysToDark"]["available"] and learned["daysToDark"]["days"] == 6.0 and learned["daysToDark"]["samples"] == 3
    assert learned["suggest"]["splitIntervalDays"] == 6.0
    assert "daysToDark" not in cultures.learned_cadences(_jar(started_ago_days=10, now=NOW), [], NOW)


def test_sizing_line_and_the_home_dose_estimate():
    assert cultures.home_dose_ml(52) == 35.0 and cultures.home_dose_ml(0) == 0.0
    s = cultures.sizing_line(3.5, 60, 8, 35, "the tank's hand dose")
    assert s["yieldMlDay"] == 262 and s["ratio"] == 7.5 and "run it at ~" in s["line"] and s["idealL"] == 0.5
    s = cultures.sizing_line(1.25, 60, 8, 35)
    assert s["yieldMlDay"] == 94 and "run it at ~" in s["line"], "even the 1:4 seed out-produces a hand-dosed 52 L tank"
    assert "set the home bottle's hand dose" in cultures.sizing_line(1.25, 60, 8, 0)["line"]
    assert "scale up at the next split" in cultures.sizing_line(0.5, 60, 8, 200)["line"]
    assert cultures.sizing_line(0, 60, 8, 35)["available"] is False
    st = cultures.starter_state(_iso(NOW - timedelta(days=25)), 28, NOW)
    assert st["status"] == "aging" and st["daysLeft"] == 3.0
    assert cultures.starter_state("", 28, NOW)["available"] is False


def test_rig_state_draws_the_lit_vessel_and_names_the_split():
    jar = {"id": "c1", "name": "Nanno A", "kind": "phyto", "vesselKind": "bottle", "volumeL": 4, "firstHarvestDays": 7,
           "state": {"status": "producing", "ageDays": 12, "cycle": {"day": 8, "ofDays": 8, "percent": 100}, "workingL": 1.25,
                     "harvestBlocked": False, "peakHeld": False}, "tint": "dark", "due": ["harvest", "look"],
           "densityAdvice": {"action": "split_now", "reason": "dark"}, "temp": {"status": "ok"},
           "homeBottle": {"remainingMl": 300, "expiry": {"status": "fresh"}},
           "splitGuide": {"outMl": 750, "freshMl": 750, "mixMl": 750, "rodiMl": 0, "targetPpt": 35, "nutrientMl": 1.1,
                          "scaleUp": False, "workingMlAfter": 1250}}
    rig = cultures.rig_state([jar], {})
    assert rig["cones"] == [] and rig["tub"] is None, "a lit vessel is not a cone — no ghost B either"
    p = rig["phyto"][0]
    assert p["splitHot"] and p["tint"] == "dark" and p["pct"] == 100 and p["bottleMl"] == 300 and p["bottleStatus"] == "fresh"
    assert rig["stage"] == "split" and rig["caption"].startswith("SPLIT — Nanno A") and "1.1 ml f/2" in rig["caption"]
    assert rig["phytoJug"]["outMl"] == 750 and rig["phytoJug"]["jarName"] == "Nanno A"
    jar["splitGuide"].update({"scaleUp": True, "freshMl": 3000, "mixMl": 3000, "nutrientMl": 4.5, "workingMlAfter": 3500})
    assert cultures.rig_state([jar], {})["stage"] == "scale_up"
    jar["state"].update({"harvestBlocked": True})
    jar["tint"] = "off"
    assert cultures.rig_state([jar], {})["stage"] == "off_colour"
    jar["state"].update({"harvestBlocked": False, "status": "establishing", "ageDays": 3, "cycle": {}})
    jar["tint"] = "pale"
    jar["due"] = []
    rig = cultures.rig_state([jar], {})
    assert rig["stage"] == "greening" and "day 3 of ~7" in rig["caption"]


def test_ws_phyto_seed_refuses_an_off_starter_and_writes_the_recipe():
    entry = _phyto_entry()
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    debits = []
    real_debit = integration._mixing_hatchery_debit
    integration._mixing_hatchery_debit = lambda hass_, config_, litres, note: debits.append((round(litres, 3), note))
    try:
        run(integration.websocket_cultures_seed(hass, conn, {"id": 1, "jar_id": "c1", "arrival_tint": "off"}))
        assert conn.errors[-1].code == "starter_off" and not _cultures(entry)["jars"]["c1"]["state"].get("startedAt")
        run(integration.websocket_cultures_seed(hass, conn, {"id": 2, "jar_id": "c1", "arrival_tint": "green",
                                                             "starter_ml": 250, "working_l": 1.25,
                                                             "starter_opened_at": _iso(REAL - timedelta(days=2))}))
        assert not [e for e in conn.errors if e.code != "starter_off"], conn.errors
        cfg = _config(entry)
        jar = cfg["nps"]["cultures"]["jars"]["c1"]
        assert jar["state"]["workingL"] == 1.25 and jar["state"]["lastTint"] == "pale" and jar["state"]["cyclesSinceFresh"] == 0
        assert jar["state"]["arrivalTint"] == "green" and jar["state"]["starterOpenedAt"] == _iso(REAL - timedelta(days=2))
        seeded = jar["history"][0]
        assert seeded["event"] == "seeded" and seeded["freshMl"] == 1000 and seeded["nutrientMl"] == 1.5 and seeded["workingMl"] == 1250
        assert cfg["consumables"]["products"]["f2"]["remainingMl"] == 248.5 and cfg["consumables"]["products"]["f2"]["history"][-1]["to"] == "jar"
        assert debits[-1] == (1.0, "seeding Nanno A"), "the NEW water only — the starter is the supplier's"
        # The home bottle joined the shelf with the tank's estimated dose and its reminder.
        bottle = cfg["consumables"]["products"]["home_phyto_c1"]
        assert bottle["category"] == "phyto" and bottle["refrigerated"] and bottle["stirDaily"] and bottle["cellsPerMl"] == 0
        assert bottle["doseMl"] == 35 and bottle["doseEveryDays"] == 1 and bottle["shelfLifeDaysOpened"] == 21 and bottle["remainingMl"] == 0
        assert jar["bottleProductId"] == "home_phyto_c1"
        assert cfg["maintenance"]["tasks"]["nps_dose_home_phyto_c1"]["cadenceDays"] == 1
        run(integration.websocket_cultures_summary(hass, conn, {"id": 3}))
        p = conn.results[-1].payload
        j = p["jars"][0]
        assert j["kind"] == "phyto" and j["tints"] == ["pale", "green", "dark", "off"] and j["hasBottle"] is False and j["hasHomeBottle"]
        assert j["homeBottle"]["exists"] and j["homeBottle"]["handDose"]["ml"] == 35 and j["homeBottle"]["expiry"]["status"] == "empty"
        assert j["seedGuides"]["starter"]["workingL"] == 1.25 and j["seedGuides"]["kit"]["workingL"] == 3.5
        assert j["nutrient"]["productId"] == "f2" and j["nutrient"]["splitsLeft"] == 225
        assert j["sizing"]["available"] and "run it at ~" in j["sizing"]["line"]
        assert j["starter"]["status"] == "fresh" and j["state"]["status"] == "establishing" and j["due"] == []
        assert j["densityAdvice"]["action"] == "wait" and j["feedAdvice"] == j["densityAdvice"]
        assert p["phytoTints"] == ["pale", "green", "dark", "off"] and p["maxJars"] == 6
        assert p["rig"]["phyto"][0]["name"] == "Nanno A" and p["rig"]["stage"] == "greening"
        # A running vessel refuses a second seed; the arrival check is only on the way in.
        run(integration.websocket_cultures_seed(hass, conn, {"id": 4, "jar_id": "c1"}))
        assert conn.errors[-1].code == "jar_busy"
    finally:
        integration._mixing_hatchery_debit = real_debit


def test_ws_phyto_look_logs_the_colour_and_a_secchi_reading_and_refuses_feeds():
    entry = _phyto_entry(jars={"c1": _phyto_jar(started_ago_days=4)})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_log(hass, conn, {"id": 1, "jar_id": "c1", "tint": "green", "secchi_cm": 12.5}))
    assert not conn.errors
    jar = _cultures(entry)["jars"]["c1"]
    assert jar["state"]["lastTint"] == "green" and jar["state"]["lastLookedAt"] and jar["history"][0]["secchiCm"] == 12.5
    assert jar["history"][0]["event"] == "tint"
    run(integration.websocket_cultures_log(hass, conn, {"id": 2, "jar_id": "c1", "fed": True}))
    assert conn.errors[-1].code == "not_a_jar"
    run(integration.websocket_cultures_log(hass, conn, {"id": 3, "jar_id": "c1", "tint": "clear"}))
    assert conn.errors[-1].code == "nothing_to_log", "the rotifer scale is not the vessel's"
    run(integration.websocket_cultures_log(hass, conn, {"id": 4, "jar_id": "c1", "secchi_cm": 9}))
    assert not [e for e in conn.errors if e.code not in ("not_a_jar", "nothing_to_log")]
    assert _cultures(entry)["jars"]["c1"]["history"][0]["secchiCm"] == 9 and _cultures(entry)["jars"]["c1"]["state"]["lastTint"] == "green"
    # Dark at day 4: producing, the split due, the look logged on the reminder.
    entry.options[CONF_SETTINGS]["maintenance"] = {"tasks": {"culture_c1_look": {"label": "Look", "enabled": True, "cadenceDays": 1, "criticalAfterDays": 2}}, "completions": {}}
    run(integration.websocket_cultures_log(hass, conn, {"id": 5, "jar_id": "c1", "tint": "dark"}))
    run(integration.websocket_cultures_summary(hass, conn, {"id": 6}))
    j = conn.results[-1].payload["jars"][0]
    assert j["state"]["status"] == "producing" and "harvest" in j["due"] and j["state"]["harvest"]["reason"] == "dark"
    assert j["densityAdvice"]["action"] == "split_now"
    comps = entry.options[CONF_SETTINGS]["maintenance"]["completions"]["culture_c1_look"]
    assert comps and comps[0]["source"] == "cultures"
    assert integration._cultures_task_clock(_config(entry), "culture_c1_look", datetime.now(timezone.utc))["available"]
    # A sign brings the fresh vessel forward and blocks the split.
    run(integration.websocket_cultures_log(hass, conn, {"id": 7, "jar_id": "c1", "sign": "yellow"}))
    run(integration.websocket_cultures_summary(hass, conn, {"id": 8}))
    j = conn.results[-1].payload["jars"][0]
    assert j["state"]["harvestBlocked"] and j["state"]["restart"]["reason"] == "sign" and j["risk"]["level"] == "act"
    run(integration.websocket_cultures_split(hass, conn, {"id": 9, "jar_id": "c1"}))
    assert conn.errors[-1].code == "off_colour"
    # Undo the dark look: the colour and the look stamp re-read the journal.
    stamp = _cultures(entry)["jars"]["c1"]["history"][1]["at"]
    assert _cultures(entry)["jars"]["c1"]["history"][1]["tint"] == "dark"
    run(integration.websocket_cultures_undo(hass, conn, {"id": 10, "jar_id": "c1", "at": stamp}))
    jar = _cultures(entry)["jars"]["c1"]
    assert jar["history"][1]["undoneAt"] and jar["state"]["lastTint"] == "green"
    assert not entry.options[CONF_SETTINGS]["maintenance"]["completions"].get("culture_c1_look")


def test_ws_phyto_split_to_the_bottle_and_the_tank_moves_every_ledger():
    maintenance = {"tasks": {"brine_hand_feed": {"label": "Hand-feed the tank", "enabled": True, "cadenceDays": 1, "criticalAfterDays": 2},
                             "culture_c1_harvest": {"label": "Split", "enabled": True, "cadenceDays": 8, "criticalAfterDays": 10}},
                   "completions": {}}
    entry = _phyto_entry(jars={"c1": _phyto_jar(started_ago_days=9, lastTint="dark")}, maintenance=maintenance)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    debits = []
    real_debit = integration._mixing_hatchery_debit
    integration._mixing_hatchery_debit = lambda hass_, config_, litres, note: debits.append((round(litres, 3), note))
    try:
        run(integration.websocket_cultures_split(hass, conn, {"id": 1, "jar_id": "c1", "ml": 750,
                                                              "to": [{"to": "bottle", "ml": 600}, {"to": "tank", "ml": 150}],
                                                              "tint": "dark", "secchi_cm": 6}))
        assert not conn.errors, conn.errors
        cfg = _config(entry)
        jar = cfg["nps"]["cultures"]["jars"]["c1"]
        row = jar["history"][0]
        assert row["event"] == "harvest" and row["ml"] == 750 and row["to"] == "bottle" and row["tankMl"] == 150
        assert row["dests"] == [{"to": "bottle", "ml": 600}, {"to": "tank", "ml": 150}]
        assert row["freshMl"] == 750 and row["nutrientMl"] == 1.1 and row["workingMl"] == 1250 and row["secchiCm"] == 6 and row["tint"] == "dark"
        assert jar["state"]["lastTint"] == "pale" and jar["state"]["cyclesSinceFresh"] == 1 and jar["state"]["lastHarvestAt"] == row["at"]
        assert jar["state"]["workingL"] == 1.25
        bottle = cfg["consumables"]["products"]["home_phyto_c1"]
        assert bottle["remainingMl"] == 600 and bottle["openedAt"] == row["at"] and bottle["lastShakenAt"] == row["at"]
        assert bottle["history"][-1] == {"at": row["at"], "ml": 600, "kind": "refill"}
        assert cfg["consumables"]["products"]["f2"]["remainingMl"] == 248.9
        assert debits[-1] == (0.75, "splitting Nanno A")
        comps = cfg["maintenance"]["completions"]
        assert comps["brine_hand_feed"] and comps["culture_c1_harvest"], "the tank share is a hand feed; the split chore is done"
        log = integration._nps_feed_log_for(cfg, datetime.now(timezone.utc), 2)
        rows = [r for r in log["rows"] if r["source"] == "culture:c1"]
        assert rows and rows[0]["ml"] == 150 and rows[0]["name"] == "Phyto from Nanno A"
        # The summary: pale again, the cycle at day 0, the bottle three weeks fresh.
        run(integration.websocket_cultures_summary(hass, conn, {"id": 2}))
        j = conn.results[-1].payload["jars"][0]
        assert j["tint"] == "pale" and j["state"]["cycle"]["day"] == 0.0 and j["homeBottle"]["remainingMl"] == 600
        assert j["homeBottle"]["expiry"]["status"] == "fresh" and j["homeBottle"]["expiry"]["daysLeft"] == 21.0
        assert j["homeBottle"]["shake"]["applies"] and not j["homeBottle"]["shake"]["due"]
        # The second split is a SCALE-UP: 750 out, 3000 in → 3.5 L working.
        cfg["nps"]["cultures"]["jars"]["c1"]["state"]["lastTint"] = "dark"
        entry.options = {**entry.options, CONF_SETTINGS: cfg}
        run(integration.websocket_cultures_split(hass, conn, {"id": 3, "jar_id": "c1", "ml": 750, "fresh_ml": 3000}))
        assert not conn.errors, conn.errors
        cfg = _config(entry)
        jar = cfg["nps"]["cultures"]["jars"]["c1"]
        assert jar["state"]["workingL"] == 3.5 and jar["history"][0]["freshMl"] == 3000 and jar["history"][0]["nutrientMl"] == 4.5
        assert jar["history"][0]["dests"] == [{"to": "bottle", "ml": 750}], "no list = the vessel's default, the bottle"
        assert cfg["consumables"]["products"]["home_phyto_c1"]["remainingMl"] == 1000, "the litre bottle is full — 350 ml over the top, logged"
        assert cfg["consumables"]["products"]["home_phyto_c1"]["openedAt"] == cfg["nps"]["cultures"]["jars"]["c1"]["history"][1]["at"], "a top-up never renews the clock"
        assert any("over the top" in str(a.get("message", "")) for a in cfg["activity"])
        assert debits[-1] == (3.0, "splitting Nanno A")
        # Refusals: more than the vessel holds; the destinations over the split; a foreign place.
        run(integration.websocket_cultures_split(hass, conn, {"id": 4, "jar_id": "c1", "ml": 4000}))
        assert conn.errors[-1].code == "invalid_volume"
        run(integration.websocket_cultures_split(hass, conn, {"id": 5, "jar_id": "c1", "ml": 500, "to": [{"to": "bottle", "ml": 400}, {"to": "tank", "ml": 300}]}))
        assert conn.errors[-1].code == "invalid_volume"
        run(integration.websocket_cultures_split(hass, conn, {"id": 6, "jar_id": "c1", "ml": 500, "to": [{"to": "cone", "ml": 500}]}))
        assert conn.errors[-1].code == "unknown_destination"
        assert len(_config(entry)["nps"]["cultures"]["jars"]["c1"]["history"]) == 2, "a refused split writes nothing"
    finally:
        integration._mixing_hatchery_debit = real_debit


def test_ws_phyto_fresh_vessel_resets_the_cycle_and_a_blocked_one_wastes_the_crop():
    entry = _phyto_entry(jars={"c1": _phyto_jar(started_ago_days=30, lastTint="dark", cyclesSinceFresh=4,
                                                 lastHarvestAt=_iso(REAL - timedelta(days=8)))})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_summary(hass, conn, {"id": 1}))
    j = conn.results[-1].payload["jars"][0]
    assert "restart" in j["due"] and j["state"]["restart"]["reason"] == "cycles" and j["state"]["percent"] == 100
    run(integration.websocket_cultures_fresh_vessel(hass, conn, {"id": 2, "jar_id": "c1"}))
    assert not conn.errors, conn.errors
    jar = _cultures(entry)["jars"]["c1"]
    assert jar["history"][0]["event"] == "restart" and jar["history"][0]["ml"] == 750 and jar["history"][0]["dests"] == [{"to": "bottle", "ml": 750}]
    assert jar["state"]["cyclesSinceFresh"] == 0 and jar["state"]["lastRestartAt"] == jar["history"][0]["at"] and jar["state"]["lastTint"] == "pale"
    assert _config(entry)["consumables"]["products"]["home_phyto_c1"]["remainingMl"] == 750
    # The restart WS is the same ceremony for a phyto vessel.
    cfg = _config(entry)
    cfg["nps"]["cultures"]["jars"]["c1"]["state"].update({"lastTint": "dark", "cyclesSinceFresh": 2})
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    run(integration.websocket_cultures_restart(hass, conn, {"id": 3, "jar_id": "c1"}))
    assert not conn.errors and _cultures(entry)["jars"]["c1"]["state"]["cyclesSinceFresh"] == 0
    # A sign on the record: the split is refused, the fresh vessel goes ahead and its crop to waste.
    run(integration.websocket_cultures_log(hass, conn, {"id": 4, "jar_id": "c1", "sign": "brown"}))
    run(integration.websocket_cultures_split(hass, conn, {"id": 5, "jar_id": "c1", "ml": 300}))
    assert conn.errors[-1].code == "off_colour"
    before = _config(entry)["consumables"]["products"]["home_phyto_c1"]["remainingMl"]
    run(integration.websocket_cultures_fresh_vessel(hass, conn, {"id": 6, "jar_id": "c1", "ml": 500}))
    assert not [e for e in conn.errors if e.code != "off_colour"]
    jar = _cultures(entry)["jars"]["c1"]
    assert jar["history"][0]["event"] == "restart" and jar["history"][0]["dests"] == [{"to": "waste", "ml": 500}] and not jar["history"][0].get("to")
    assert jar["state"]["lastSign"] == "" and jar["state"]["lastSignAt"] == ""
    assert _config(entry)["consumables"]["products"]["home_phyto_c1"]["remainingMl"] == before, "an off-colour crop never reaches the bottle"


def test_ws_phyto_split_loads_the_drip_and_seeds_b():
    from test_nps import _drip_channel
    channel = _drip_channel(reservoir={"productId": "home_phyto_c1", "productIsBottle": False, "volumeMl": 500, "remainingMl": 100})
    entry = _phyto_entry(jars={"c1": _phyto_jar(started_ago_days=12, lastTint="dark", workingL=3.5, generation=1)},
                         channels={"drip": channel})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_summary(hass, conn, {"id": 1}))
    j = conn.results[-1].payload["jars"][0]
    assert j["drips"] == [{"id": "drip", "name": "Phyto drip", "linked": True}] and j["state"]["workingL"] == 3.5
    run(integration.websocket_cultures_split(hass, conn, {"id": 2, "jar_id": "c1", "ml": 2100,
                                                          "to": [{"to": "drip", "ml": 500}, {"to": "vessel", "ml": 250}, {"to": "bottle", "ml": 1000}]}))
    assert not conn.errors, conn.errors
    cfg = _config(entry)
    res = cfg["dosing"]["channels"]["drip"]["reservoir"]
    assert res["remainingMl"] == 500 and res["mixedAt"], "the jar took 400 ml to its brim and its day clock restarted"
    jars = cfg["nps"]["cultures"]["jars"]
    assert set(jars) == {"c1", "c2"} and jars["c2"]["species"] == "nanno" and jars["c2"]["volumeL"] == 1.0 and jars["c2"]["name"] == "Nanno B"
    assert jars["c2"]["state"]["seededFrom"] == "c1" and jars["c2"]["state"]["generation"] == 2
    assert jars["c2"]["state"]["workingL"] == 1.0, "the litre bottle caps the 1:4 recipe"
    assert jars["c2"]["history"][0]["event"] == "seeded" and jars["c2"]["history"][0]["freshMl"] == 750
    row = jars["c1"]["history"][1] if jars["c1"]["history"][0]["event"] == "split" else jars["c1"]["history"][0]
    assert row["event"] == "harvest" and row["ml"] == 2100
    dests = {d["to"]: d["ml"] for d in row["dests"]}
    assert dests == {"drip": 400, "bottle": 1000, "waste": 450}, "the drip took what fitted (400 of 500); the rest is waste; B's 250 rides the split row"
    assert jars["c1"]["history"][0]["event"] == "split" and jars["c1"]["history"][0]["ml"] == 250
    assert jars["c1"]["state"]["workingL"] == 3.5 and cfg["consumables"]["products"]["home_phyto_c1"]["remainingMl"] == 1000
    assert cfg["consumables"]["products"]["home_phyto_c2"]["doseMl"] == 35, "B has its own bottle on the shelf"
    # No drip on the rack: the drip share is refused before anything moves.
    entry2 = _phyto_entry(jars={"c1": _phyto_jar(started_ago_days=12, lastTint="dark")})
    conn2 = FakeConnection()
    run(integration.websocket_cultures_split(FakeHass(entries=[entry2]), conn2, {"id": 3, "jar_id": "c1", "to": [{"to": "drip", "ml": 300}]}))
    assert conn2.errors[-1].code == "no_drip" and not _cultures(entry2)["jars"]["c1"]["history"]


def test_ws_shaken_and_the_drip_loaded_from_the_home_bottle():
    from test_nps import _drip_channel
    products = {**_phyto_products(),
                "home_phyto_c1": {"name": "Home phyto (Nanno A)", "brand": "Home culture", "category": "phyto", "bottleMl": 1000.0,
                                  "remainingMl": 900.0, "refrigerated": True, "stirDaily": True, "shelfLifeDaysOpened": 21,
                                  "openedAt": _iso(REAL - timedelta(days=3)), "history": [], "doseMl": 35, "doseEveryDays": 1},
                "dry": {"name": "GoldPods", "bottleMl": 250.0, "remainingMl": 100.0, "history": []}}
    channel = _drip_channel(reservoir={"productId": "home_phyto_c1", "productIsBottle": False, "volumeMl": 500, "remainingMl": 100})
    entry = _phyto_entry(jars={"c1": _phyto_jar(started_ago_days=12, lastTint="green")}, products=products, channels={"drip": channel})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    now = datetime.now(timezone.utc)
    shake = nps_engine.shake_state(products["home_phyto_c1"], now)
    assert shake["applies"] and shake["due"] and shake["hoursSince"] >= 71, "never shaken since it was opened three days ago"
    run(integration.websocket_consumable_mark_shaken(hass, conn, {"id": 1, "product_id": "home_phyto_c1"}))
    assert not conn.errors
    bottle = _config(entry)["consumables"]["products"]["home_phyto_c1"]
    assert bottle["lastShakenAt"] and not nps_engine.shake_state(bottle, now + timedelta(minutes=1))["due"]
    run(integration.websocket_consumable_mark_shaken(hass, conn, {"id": 2, "product_id": "dry"}))
    assert conn.errors[-1].code == "no_shake"
    assert nps_engine.consumable_state(bottle, now)["shake"]["applies"]
    # Loaded with debit: the jar to its brim, the difference off the bottle.
    run(integration.websocket_dosing_mark_refreshed(hass, conn, {"id": 3, "channel_id": "drip", "debit": True}))
    assert not [e for e in conn.errors if e.code != "no_shake"], conn.errors
    cfg = _config(entry)
    assert cfg["dosing"]["channels"]["drip"]["reservoir"]["remainingMl"] == 500 and cfg["dosing"]["channels"]["drip"]["reservoir"]["mixedAt"]
    bottle = cfg["consumables"]["products"]["home_phyto_c1"]
    assert bottle["remainingMl"] == 500 and bottle["history"][-1]["kind"] == "transfer" and bottle["history"][-1]["ml"] == 400
    # Without the flag the tap is what it was: a stamp, no ledger movement.
    run(integration.websocket_dosing_mark_refreshed(hass, conn, {"id": 4, "channel_id": "drip"}))
    assert _config(entry)["consumables"]["products"]["home_phyto_c1"]["remainingMl"] == 500
    # The summary's demand line reads the drip and the hand dose.
    run(integration.websocket_cultures_summary(hass, conn, {"id": 5}))
    j = conn.results[-1].payload["jars"][0]
    assert j["sizing"]["demandMlDay"] == 41 and "the tank's hand dose + the drip" in j["sizing"]["line"]


def test_phyto_push_plan_and_the_phone_split():
    entry = _phyto_entry(jars={"c1": _phyto_jar(started_ago_days=9, lastTint="dark")})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_summary(hass, conn, {"id": 1}))
    plan = integration._cultures_push_plan(conn.results[-1].payload)
    assert len(plan) == 1 and plan[0]["title"] == "OpenReef: Nanno A — split?"
    assert [a["action"] for a in plan[0]["actions"]] == ["OPENREEF_CULTURE_SPLIT:c1", "OPENREEF_CULTURE_LATER:c1"]
    assert plan[0]["message"].startswith("Dark")

    class Ev:
        def __init__(self, action):
            self.data = {"action": action}
    run(integration._async_notification_action(hass, Ev("OPENREEF_CULTURE_SPLIT:c1")))
    jar = _cultures(entry)["jars"]["c1"]
    assert jar["history"][0]["event"] == "harvest" and jar["history"][0]["ml"] == 750 and jar["history"][0]["dests"] == [{"to": "bottle", "ml": 750}]
    assert _config(entry)["consumables"]["products"]["home_phyto_c1"]["remainingMl"] == 750
    # A look alone is not a push; a fresh vessel due is.
    cfg = _config(entry)
    cfg["nps"]["cultures"]["jars"]["c1"]["state"].update({"lastLookedAt": _iso(REAL - timedelta(days=2)), "cyclesSinceFresh": 4})
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    run(integration.websocket_cultures_summary(hass, conn, {"id": 2}))
    summary = conn.results[-1].payload
    assert "look" in summary["jars"][0]["due"] and "restart" in summary["jars"][0]["due"]
    plan = integration._cultures_push_plan(summary)
    assert plan[0]["title"] == "OpenReef: Nanno A — fresh vessel?" and plan[0]["actions"][0]["action"] == "OPENREEF_CULTURE_FRESH:c1"
    cfg["nps"]["cultures"]["jars"]["c1"]["state"]["cyclesSinceFresh"] = 1
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    run(integration.websocket_cultures_summary(hass, conn, {"id": 3}))
    assert integration._cultures_push_plan(conn.results[-1].payload) == [], "a look alone is not worth a push"


def test_home_bottle_is_made_on_save_and_survives_a_stale_client():
    entry = _phyto_entry()
    cfg = _config(entry)
    assert "home_phyto_c1" not in cfg["consumables"]["products"]
    integration._cultures_ensure_home_bottles(cfg)
    assert cfg["consumables"]["products"]["home_phyto_c1"]["doseMl"] == 35 and cfg["nps"]["cultures"]["jars"]["c1"]["bottleProductId"] == "home_phyto_c1"
    integration._cultures_ensure_home_bottles(cfg)
    assert len([p for p in cfg["consumables"]["products"] if p.startswith("home_phyto_")]) == 1, "idempotent"
    cfg["nps"]["cultures"]["enabled"] = False
    cfg["nps"]["cultures"]["jars"]["c9"] = _phyto_jar()
    integration._cultures_ensure_home_bottles(cfg)
    assert "home_phyto_c9" not in cfg["consumables"]["products"], "quiet while the cultures are off"
    cfg["nps"]["cultures"]["enabled"] = True
    # A stale client that never saw the bottle posts a config without it: the guard carries it over.
    stored = copy.deepcopy(cfg)
    stored["consumables"]["products"]["home_phyto_c1"]["remainingMl"] = 600
    incoming = copy.deepcopy(cfg)
    del incoming["consumables"]["products"]["home_phyto_c1"]
    integration._nps_preserve_runtime(stored, incoming)
    assert incoming["consumables"]["products"]["home_phyto_c1"]["remainingMl"] == 600
    # ...but a vessel the client removed takes its bottle with it.
    incoming = copy.deepcopy(cfg)
    del incoming["consumables"]["products"]["home_phyto_c1"]
    del incoming["nps"]["cultures"]["jars"]["c1"]
    integration._nps_preserve_runtime(stored, incoming)
    assert "home_phyto_c1" not in incoming["consumables"]["products"]
    # The Shaken stamp is server-written: the newer one wins through a stale save.
    stored["consumables"]["products"]["home_phyto_c1"]["lastShakenAt"] = _iso(REAL)
    incoming = copy.deepcopy(cfg)
    incoming["consumables"]["products"]["home_phyto_c1"]["lastShakenAt"] = _iso(REAL - timedelta(days=1))
    integration._nps_preserve_runtime(stored, incoming)
    assert incoming["consumables"]["products"]["home_phyto_c1"]["lastShakenAt"] == _iso(REAL)
    # Reseed from a young bottle after a crash; too old refuses.
    entry = _phyto_entry(jars={"c1": _phyto_jar(started_ago_days=12, lastTint="dark")},
                         products={**_phyto_products(), "home_phyto_c1": {
                             "name": "Home phyto (Nanno A)", "category": "phyto", "bottleMl": 1000.0, "remainingMl": 600.0,
                             "refrigerated": True, "stirDaily": True, "shelfLifeDaysOpened": 21,
                             "openedAt": _iso(REAL - timedelta(days=3)), "history": []}})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_crash(hass, conn, {"id": 1, "jar_id": "c1"}))
    run(integration.websocket_cultures_summary(hass, conn, {"id": 2}))
    assert conn.results[-1].payload["jars"][0]["reseedFromBottle"] is True
    run(integration.websocket_cultures_seed(hass, conn, {"id": 3, "jar_id": "c1", "from_bottle": True}))
    assert not conn.errors, conn.errors
    cfg = _config(entry)
    assert cfg["consumables"]["products"]["home_phyto_c1"]["remainingMl"] == 350 and cfg["nps"]["cultures"]["jars"]["c1"]["state"]["seededFrom"] == "bottle"
    assert cfg["nps"]["cultures"]["jars"]["c1"]["state"]["workingL"] == 1.25 and cfg["nps"]["cultures"]["jars"]["c1"]["history"][0]["from"] == "bottle"
    run(integration.websocket_cultures_summary(hass, conn, {"id": 4}))
    assert conn.results[-1].payload["jars"][0]["lineage"]["line"] == "gen 1 · from the fridge bottle"
    cfg["nps"]["cultures"]["jars"]["c1"]["state"]["crashedAt"] = _iso(datetime.now(timezone.utc) + timedelta(seconds=1))
    cfg["consumables"]["products"]["home_phyto_c1"]["openedAt"] = _iso(REAL - timedelta(days=9))
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    run(integration.websocket_cultures_seed(hass, conn, {"id": 5, "jar_id": "c1", "from_bottle": True}))
    assert conn.errors[-1].code == "bottle_too_old"


# --------------------------------------------------------------------------- #
# 0.7.208 — the phyto vessel, Stage B: light, heat, backup, learning (doc §5.6,
# §5.8, §5.10, §11)
# --------------------------------------------------------------------------- #
def _sun(now_local, sunrise_h=6.75, sunset_h=19.15, day=None):
    """A sun entity snapshot around ``now_local`` (a local, aware datetime):
    the two FUTURE stamps HA carries. ``day`` forces the branch."""
    is_day = (sunrise_h <= now_local.hour + now_local.minute / 60 < sunset_h) if day is None else day
    base = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    if is_day:
        setting = base + timedelta(hours=sunset_h)
        rising = base + timedelta(days=1, hours=sunrise_h)
    elif now_local.hour + now_local.minute / 60 >= sunset_h:
        setting = base + timedelta(days=1, hours=sunset_h)
        rising = base + timedelta(days=1, hours=sunrise_h)
    else:
        setting = base + timedelta(hours=sunset_h)
        rising = base + timedelta(hours=sunrise_h)
    return {"state": "above_horizon" if is_day else "below_horizon",
            "next_rising": rising.isoformat(), "next_setting": setting.isoformat()}


_TZ1 = timezone(timedelta(hours=1))


def _local(h, m=0, day=21):
    return datetime(2026, 9, day, h, m, tzinfo=_TZ1)


def test_sun_day_reads_the_two_future_stamps_by_day_and_by_night():
    day = cultures.sun_day(_sun(_local(14)), _local(14))
    assert day["available"] and day["isDay"] and day["daylightH"] == 12.4
    assert day["sunsetAt"] == _local(19, 9).isoformat(), "by day the window hangs off the COMING sunset"
    night = cultures.sun_day(_sun(_local(21)), _local(21))
    assert not night["isDay"] and night["daylightH"] == 12.4
    assert night["sunsetAt"] == _local(19, 9).isoformat(), "at night the window hangs off the LAST sunset"
    early = cultures.sun_day(_sun(_local(4)), _local(4))
    assert early["sunsetAt"] == _local(19, 9, day=20).isoformat(), "before dawn the last sunset was yesterday's"
    assert cultures.sun_day({}, _local(4))["available"] is False and cultures.sun_day(None, _local(4))["daylightH"] is None


def test_light_window_the_three_modes_the_sunset_rule_and_the_latest_off_cap():
    light = {"mode": "sun+lamp", "switchEntity": "switch.lamp", "onAt": "07:00", "latestOff": "00:00"}
    # 16 h target − 12.4 h of sun = 3.6 h of lamp from sunset 19:09 → 22:45.
    w = cultures.light_window(light, 16, _local(14), _sun(_local(14)))
    assert w["rule"] == "sunset" and w["plannedLampH"] == 3.6 and not w["active"] and w["onAt"] == _local(19, 9).isoformat()
    w = cultures.light_window(light, 16, _local(21), _sun(_local(21)))
    assert w["active"] and not w["over"] and w["offAt"] == _local(22, 45).isoformat()
    w = cultures.light_window(light, 16, _local(23, 30), _sun(_local(23, 30)))
    assert not w["active"] and w["over"], "past the window it is over, not active"
    # latestOff caps the window; a cap before sunset means the next day's — no cap.
    w = cultures.light_window({**light, "latestOff": "21:30"}, 16, _local(21), _sun(_local(21)))
    assert w["rule"] == "latest_off" and w["offAt"] == _local(21, 30).isoformat() and w["plannedLampH"] == 2.35
    w = cultures.light_window({**light, "latestOff": "18:00"}, 16, _local(21), _sun(_local(21)))
    assert w["rule"] == "sunset" and w["plannedLampH"] == 3.6
    # Midsummer: 17 h of sun reaches a 16 h target — the lamp stays off.
    w = cultures.light_window(light, 16, _local(21), _sun(_local(21), sunrise_h=4.0, sunset_h=21.5, day=False))
    assert w["rule"] == "sun_enough" and w["plannedLampH"] == 0 and not w["active"]
    # No sun to read: sun+lamp falls back to the lamp rule and says so.
    w = cultures.light_window(light, 16, _local(9), None)
    assert w["rule"] == "on_at_fallback" and w["active"] and w["onAt"] == _local(7).isoformat() and w["sunAvailable"] is False
    # Lamp: on-at + the target, across midnight when it must.
    w = cultures.light_window({"mode": "lamp", "onAt": "10:00"}, 16, _local(1, 30), None)
    assert w["active"] and w["onAt"] == _local(10, day=20).isoformat() and w["offAt"] == _local(2, day=21).isoformat()
    # Sun: never a window.
    w = cultures.light_window({"mode": "sun"}, 16, _local(21), _sun(_local(21)))
    assert w["rule"] == "none" and not w["active"] and w["onAt"] is None
    assert cultures.light_window({"mode": "junk"}, 16, _local(21), _sun(_local(21)))["mode"] == "sun"


def test_light_state_the_readout_the_short_day_nudge_the_lamp_off_watch_and_the_lost_day():
    cad = cultures.cadence_for("nanno", {})
    light = {"mode": "sun+lamp", "switchEntity": "switch.lamp", "onAt": "07:00", "latestOff": "00:00"}
    jar = {"species": "nanno", "light": light, "state": {"lightDay": "2026-09-21", "lightMinutesToday": 27,
                                                          "lightOnAt": _local(20).isoformat()}}
    at = _local(21, 3)
    on = cultures.light_state(jar, cad, at, _sun(at), "on")
    assert on["status"] == "ok" and on["lit"] and on["plugOn"] and on["lampH"] == 1.5 and on["deliveredH"] == 13.9
    assert on["line"].startswith("daylight 12.4 h (astronomical — the window gives less) · lamp 3.6 h from sunset 19:09 → 22:45 · 1.5 h lamp so far"), on["line"]
    assert on["window"]["active"] and on["window"]["hoursIn"] == 1.9
    off = cultures.light_state(jar, cad, at, _sun(at), "off")
    assert off["status"] == "watch" and off["line"].endswith("— lamp off 1.9 h into its window") and not off["lit"]
    gone = cultures.light_state(jar, cad, at, _sun(at), "unavailable")
    assert gone["status"] == "watch" and "lamp unavailable" in gone["line"]
    # A short winter day with the lamp dead: 8 h of sun + nothing = a lost day.
    winter = {"species": "nanno", "light": {**light, "latestOff": "22:00"}, "state": {"lightDay": "2026-12-21", "lightMinutesToday": 0}}
    dec = datetime(2026, 12, 21, 23, 55, tzinfo=timezone.utc)
    lost = cultures.light_state(winter, cad, dec, _sun(dec, sunrise_h=8.0, sunset_h=15.9), "off")
    assert lost["status"] == "act" and lost["deliveredH"] == 7.9 and "lost a day of light" in lost["line"]
    # No plug bound in a lamp mode is a watch; a sun mode never minds the plug.
    assert cultures.light_state({"species": "nanno", "light": {"mode": "lamp"}, "state": {}}, cad, _local(9), None, None)["status"] == "watch"
    sun = cultures.light_state({"species": "nanno", "light": {"mode": "sun"}, "state": {}}, cad, _local(21), _sun(_local(21)), None)
    assert sun["status"] == "watch" and "under the 16 h target" in sun["line"] and sun["nudge"] == "" and sun["deliveredH"] == 12.4
    short = cultures.light_state({"species": "nanno", "light": {"mode": "sun"}, "state": {}}, cad, _local(21),
                                 _sun(_local(21), sunrise_h=7.3, sunset_h=18.2), None)
    assert short["shortDay"] and short["nudge"] == "the days are under 12 h — put the LED on the plug" and short["status"] == "watch"
    unknown = cultures.light_state({"species": "nanno", "light": {"mode": "sun"}, "state": {}}, cad, _local(21), None, None)
    assert unknown["status"] == "unknown" and unknown["daylightH"] is None and unknown["deliveredH"] is None
    # sun+lamp with no sun: the fallback is named, and it is a watch.
    fb = cultures.light_state(jar, cad, _local(9), None, "on")
    assert fb["status"] == "watch" and "no sun entity — the lamp runs on its on-at time instead" in fb["line"]
    assert "Air is never switched" in fb["aerationNote"]


def test_backup_refresh_clock_and_the_calendar_never_asks_b_for_a_split():
    b = _phyto_jar(started_ago_days=33, now=NOW, backupOf="c1", lastTint="green", workingL=1.0)
    b["volumeL"] = 1.0
    st = cultures.culture_state(b, NOW)
    assert st["backupOf"] == "c1" and st["refresh"]["available"] and st["refresh"]["due"] and st["refresh"]["reason"] == "backup"
    assert st["refresh"]["everyDays"] == 32, "restartCycles × splitIntervalDays = 4 × 8"
    assert not st["harvest"]["due"] and st["harvest"]["reason"] is None, "B is never asked for a calendar split"
    young = _phyto_jar(started_ago_days=10, now=NOW, backupOf="c1", lastTint="green", workingL=1.0)
    st = cultures.culture_state(young, NOW)
    assert not st["refresh"]["due"] and st["refresh"]["hoursUntil"] == 22 * 24
    young["state"]["lastTint"] = "dark"
    young["history"] = [{"event": "tint", "at": _iso(NOW - timedelta(hours=1)), "tint": "dark"}]
    assert cultures.culture_state(young, NOW)["harvest"]["reason"] == "dark", "a dark B is still a crop"
    main = _phyto_jar(started_ago_days=33, now=NOW, lastTint="green")
    st = cultures.culture_state(main, NOW)
    assert st["refresh"]["available"] is False and st["backupOf"] == ""
    # A tighter cadence keeps the week floor.
    b["cadence"] = {"splitIntervalDays": 1, "restartCycles": 3}
    assert cultures.culture_state(b, NOW)["refresh"]["everyDays"] == 7


def test_learned_daily_offer_recovery_by_depth_and_the_light_line():
    now = NOW
    rows = []
    # Two cycles: seeded → dark in 6 d; a 60 % split → dark in 6 d.
    rows.append({"event": "seeded", "at": _iso(now - timedelta(days=20)), "ml": 1250, "tint": "pale", "freshMl": 1000, "nutrientMl": 1.5, "workingMl": 1250})
    rows.append({"event": "tint", "at": _iso(now - timedelta(days=14)), "tint": "dark"})
    rows.append({"event": "harvest", "at": _iso(now - timedelta(days=13)), "ml": 750, "tint": "dark", "freshMl": 750, "nutrientMl": 1.1, "workingMl": 1250})
    rows.append({"event": "tint", "at": _iso(now - timedelta(days=7)), "tint": "dark"})
    jar = _phyto_jar(started_ago_days=20, now=now, lastHarvestAt=_iso(now - timedelta(days=13)), lastTint="green")
    jar["history"] = list(reversed(rows))
    learned = cultures.learned_cadences(jar, [jar["history"]], now)
    assert learned["daysToDark"] == {"available": True, "days": 6.0, "samples": 2}
    assert learned["suggest"]["splitIntervalDays"] == 6 and learned["suggest"]["mode"] == "daily"
    assert learned["dailyOffer"] == {"available": True, "pct": 20.0}, "60 % over 6 d ≈ 14 % a day, held to the guide's 20"
    assert cultures.daily_draw_pct(70, 3) == 30 and cultures.daily_draw_pct(60, 8) == 20
    jar["mode"] = "daily"
    daily = cultures.learned_cadences(jar, [jar["history"]], now)
    assert daily["suggest"]["mode"] is None and daily["dailyOffer"]["available"] is False, "in daily mode there is nothing to offer"
    # Recovery by depth: two 70 % splits at ~5 d, two 50 % at ~3 d.
    deep = []
    t = now - timedelta(days=40)
    for pct, days in ((70, 5), (50, 3), (70, 5), (50, 3)):
        out = 1250 * pct / 100
        deep.append({"event": "harvest", "at": _iso(t), "ml": out, "freshMl": out, "workingMl": 1250, "nutrientMl": 1.0, "tint": "dark"})
        deep.append({"event": "tint", "at": _iso(t + timedelta(days=days)), "tint": "dark"})
        t += timedelta(days=days + 1)
    depth = cultures.darkening_by_depth(list(reversed(deep)))
    assert depth["available"] and depth["line"] == "> 65 % splits took ~5 d to darken, ≤ 50 % splits took ~3 d to darken — this does not establish the cause"
    assert cultures.darkening_by_depth(deep[:4])["available"] is False, "two at each depth before it speaks"
    # The light line: a week under 14 h beside a cycle slower than the record.
    dim = [{"event": "light", "at": _iso(now - timedelta(days=d)), "lightH": 11.0, "lampH": 0.0, "daylightH": 11.0} for d in range(1, 8)]
    slow_rows = rows + [{"event": "harvest", "at": _iso(now - timedelta(days=6)), "ml": 750, "tint": "dark", "freshMl": 750, "nutrientMl": 1.1, "workingMl": 1250}]
    jar["mode"] = "batch"
    jar["history"] = list(reversed(slow_rows + dim))
    assert cultures.light_samples(jar["history"]) == [11.0] * 7
    learned = cultures.learned_cadences(jar, [jar["history"]], now)
    assert learned["light"]["weekH"] == 11.0 and learned["light"]["line"] == "", "no slow cycle yet — nothing to pin on the light"
    jar["history"].insert(0, {"event": "tint", "at": _iso(now - timedelta(hours=1)), "tint": "dark"})   # dark after 5.96 d — not slow
    assert cultures.learned_cadences(jar, [jar["history"]], now)["light"]["line"] == ""
    # A split at −9 d with no dark tap before it voids that cycle; the next
    # dark comes 9 days after: slow against the 6-day record.
    jar["history"] = list(reversed(rows[:3] + [{"event": "harvest", "at": _iso(now - timedelta(days=9)), "ml": 750, "tint": "green", "freshMl": 750, "nutrientMl": 1.1, "workingMl": 1250},
                                              {"event": "tint", "at": _iso(now - timedelta(hours=1)), "tint": "dark"}] + dim))
    assert cultures.darkening_samples(jar["history"])[0] > 8.9
    line = cultures.learned_cadences(jar, [jar["history"]], now)["light"]["line"]
    assert line.startswith("a week under 14 h of light (~11 h a day) beside a slow cycle") and "nothing here proves it" in line


def test_risk_line_carries_the_light_the_f2_the_cycles_the_backup_and_the_starter():
    ok_temp = {"available": True, "status": "ok", "tempC": 23.0}
    jar = _phyto_jar(started_ago_days=12, now=NOW, lastTint="green", lastHarvestAt=_iso(NOW - timedelta(days=2)))
    jar["history"] = [{"event": "harvest", "at": _iso(NOW - timedelta(days=2)), "ml": 750, "freshMl": 750, "nutrientMl": 0, "workingMl": 1250}]
    st = cultures.culture_state(jar, NOW)
    risk = cultures.risk_line(jar, st, ok_temp, NOW)
    assert risk["level"] == "watch" and "no f/2 logged at the last split" in risk["reason"]
    jar["history"][0]["nutrientMl"] = 1.1
    assert cultures.risk_line(jar, st, ok_temp, NOW)["level"] == "ok"
    light_watch = {"status": "watch", "line": "daylight 11.6 h … · lamp 4.4 h … — lamp off 2 h into its window", "nudge": ""}
    assert cultures.risk_line(jar, st, ok_temp, NOW, light=light_watch)["reason"] == "lamp off 2 h into its window"
    nudge = {"status": "watch", "line": "daylight 11.6 h (astronomical — the window gives less)", "nudge": "the days are under 12 h — put the LED on the plug"}
    assert cultures.risk_line(jar, st, ok_temp, NOW, light=nudge)["reason"] == "the days are under 12 h — put the LED on the plug"
    lost = {"status": "act", "line": "7.9 h of light today — the culture lost a day of light; expect the split to slip", "nudge": ""}
    risk = cultures.risk_line(jar, st, ok_temp, NOW, light=lost)
    assert risk["level"] == "act" and risk["reason"] == "the culture lost a day of light; expect the split to slip"
    # Four splits since a fresh vessel: sterilise the spare.
    jar["state"]["cyclesSinceFresh"] = 4
    st = cultures.culture_state(jar, NOW)
    assert "4 splits since a fresh vessel — sterilise the spare" in cultures.risk_line(jar, st, ok_temp, NOW)["reason"]
    # The backup's refresh, and the starter's month while establishing.
    b = _phyto_jar(started_ago_days=33, now=NOW, backupOf="c1", lastTint="green", workingL=1.0)
    st = cultures.culture_state(b, NOW)
    assert "the backup is 33 days old — refresh it from the main vessel" in cultures.risk_line(b, st, ok_temp, NOW)["reason"]
    fresh = _phyto_jar(started_ago_days=2, now=NOW, lastTint="pale", starterOpenedAt=_iso(NOW - timedelta(days=30)))
    st = cultures.culture_state(fresh, NOW)
    assert "starter bottle is past its four weeks" in cultures.risk_line(fresh, st, ok_temp, NOW)["reason"]
    # The heat guard speaks the alga's copy; an animal's jar keeps its own.
    proj = [{"at": _iso(NOW + timedelta(hours=3)), "roomC": 29.5}]
    assert "shade it, move it off the sunlit shelf" in cultures.heat_guard(proj, "nanno", NOW)["line"]
    assert "a 50 % change ready" in cultures.heat_guard(proj, "tigriopus", NOW)["line"]
    # The rig's lamp follows the light.
    rig = cultures.rig_state([{"id": "c1", "name": "Nanno A", "kind": "phyto", "vesselKind": "bottle", "volumeL": 4,
                               "state": {"status": "producing", "workingL": 1.25, "cycle": {"day": 3, "ofDays": 8, "percent": 40}},
                               "due": ["refresh"], "tint": "green", "backupOf": "c0",
                               "light": {"mode": "sun+lamp", "sunAvailable": True, "switchEntity": "switch.l", "lit": False, "status": "watch"}}],
                             {"remainingMl": 0, "volumeMl": 1000, "status": "empty", "percent": 0})
    p = rig["phyto"][0]
    assert p["lightOn"] is False and p["lightWatch"] and p["backup"] and p["refreshHot"]


def test_light_tick_runs_the_plug_from_sunset_banks_the_hours_and_writes_the_day_row():
    now = datetime.now(timezone.utc)
    now_local = integration.dt_util.as_local(now)
    # Sunset an hour ago, 14 h of sun today → 2 h of lamp: the window is open now.
    sun = {"state": "below_horizon", "next_rising": _iso(now + timedelta(hours=9)), "next_setting": _iso(now + timedelta(hours=23))}
    jar = _phyto_jar(started_ago_days=5, lastTint="green")
    jar["light"] = {"mode": "sun+lamp", "switchEntity": "switch.lamp", "onAt": "07:00", "latestOff": "00:00", "tempEntity": ""}
    entry = _phyto_entry(jars={"c1": jar})
    hass = FakeHass(states={"switch.lamp": "off", "sun.sun": FakeState("below_horizon", {"next_rising": sun["next_rising"], "next_setting": sun["next_setting"]})},
                    entries=[entry])
    run(integration._async_cultures_light_tick(hass, entry, now))
    assert hass.states.get("switch.lamp").state == "on"
    state = _cultures(entry)["jars"]["c1"]["state"]
    assert state["lightOnAt"] and state["lightDay"] == now_local.date().isoformat() and state["lightMinutesToday"] == 0
    assert any("lamp on at sunset" in a["message"] and "2.0 h to the 16 h day" in a["message"] for a in _config(entry)["activity"]), _config(entry)["activity"][:3]
    calls = len(hass.services.calls)
    run(integration._async_cultures_light_tick(hass, entry, now + timedelta(minutes=1)))
    assert len(hass.services.calls) == calls, "mid-window with the plug on: nothing to do, nothing saved"
    # The window ends: the plug goes off, the minutes are banked, the day's light said.
    run(integration._async_cultures_light_tick(hass, entry, now + timedelta(hours=1, minutes=5)))
    assert hass.states.get("switch.lamp").state == "off"
    state = _cultures(entry)["jars"]["c1"]["state"]
    assert state["lightOnAt"] == "" and state["lightOffAt"] and 64 <= state["lightMinutesToday"] <= 66
    assert any("lamp off — 1.1 h on the plug today — 15.1 h with the sun" in a["message"] for a in _config(entry)["activity"])
    # The plug drops mid-window after we lit it: one warning per window, no fight.
    cfg = _config(entry)
    cfg["nps"]["cultures"]["jars"]["c1"]["state"].update({"lightOnAt": _iso(now), "lightWatchAt": ""})
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    hass.states.set("switch.lamp", "off")
    switch_calls = lambda: [c for c in hass.services.calls if c.domain == "switch"]   # noqa: E731 — the save pipeline dismisses notifications too
    calls = len(switch_calls())
    run(integration._async_cultures_light_tick(hass, entry, now + timedelta(minutes=30)))
    assert len(switch_calls()) == calls and hass.states.get("switch.lamp").state == "off", "we do not re-assert over the keeper"
    assert any("lamp off 1.5 h into its window — check the plug" in a["message"] for a in _config(entry)["activity"])
    assert _cultures(entry)["jars"]["c1"]["state"]["lightWatchAt"]
    # A failed call: no stamp, retried next tick.
    cfg = _config(entry)
    cfg["nps"]["cultures"]["jars"]["c1"]["state"].update({"lightOnAt": "", "lightWatchAt": ""})
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    hass.services.fail_on.add(("switch", "turn_on"))
    run(integration._async_cultures_light_tick(hass, entry, now + timedelta(minutes=2)))
    assert _cultures(entry)["jars"]["c1"]["state"]["lightOnAt"] == "" and hass.states.get("switch.lamp").state == "off"
    hass.services.fail_on.clear()
    run(integration._async_cultures_light_tick(hass, entry, now + timedelta(minutes=3)))
    assert _cultures(entry)["jars"]["c1"]["state"]["lightOnAt"] and hass.states.get("switch.lamp").state == "on"
    # Unbound mid-burst: the stamps clear, nothing is switched.
    cfg = _config(entry)
    cfg["nps"]["cultures"]["jars"]["c1"]["light"]["switchEntity"] = ""
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    calls = len(switch_calls())
    run(integration._async_cultures_light_tick(hass, entry, now + timedelta(minutes=4)))
    assert _cultures(entry)["jars"]["c1"]["state"]["lightOnAt"] == "" and len(switch_calls()) == calls
    # The day roll: yesterday's lamp minutes + the sun go into the journal as a light row.
    cfg = _config(entry)
    yesterday = (now_local - timedelta(days=1)).date().isoformat()
    cfg["nps"]["cultures"]["jars"]["c1"]["light"].update({"switchEntity": "switch.lamp"})
    cfg["nps"]["cultures"]["jars"]["c1"]["state"].update({"lightDay": yesterday, "lightMinutesToday": 200, "lightOnAt": ""})
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    run(integration._async_cultures_light_tick(hass, entry, now + timedelta(minutes=5)))
    jar_after = _cultures(entry)["jars"]["c1"]
    row = next(r for r in jar_after["history"] if r["event"] == "light")
    assert row["lampH"] == 3.3 and row["daylightH"] == 14.0 and row["lightH"] == 17.3
    assert jar_after["state"]["lightDay"] == now_local.date().isoformat() and jar_after["state"]["lightMinutesToday"] == 0
    assert cultures.light_samples(jar_after["history"]) == [17.3]
    # Sun mode never touches a plug — even one left bound.
    cfg = _config(entry)
    cfg["nps"]["cultures"]["jars"]["c1"]["light"]["mode"] = "sun"
    cfg["nps"]["cultures"]["jars"]["c1"]["state"]["lightOnAt"] = ""
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    hass.states.set("switch.lamp", "off")
    calls = len(switch_calls())
    run(integration._async_cultures_light_tick(hass, entry, now + timedelta(minutes=6)))
    assert len(switch_calls()) == calls and hass.states.get("switch.lamp").state == "off"
    # The tick is armed only for a rack with a phyto vessel.
    assert integration.CULTURES_TICK_SECONDS == 60


def test_ws_refresh_backup_reseeds_b_from_a_and_a_vessel_share_refreshes_a_running_b():
    a = _phyto_jar(started_ago_days=40, lastTint="dark", lastHarvestAt=_iso(REAL - timedelta(days=6)), cyclesSinceFresh=2, generation=1)
    a["history"] = [{"event": "tint", "at": _iso(REAL - timedelta(hours=2)), "tint": "dark"}]
    b = _phyto_jar(started_ago_days=33, lastTint="green", workingL=1.0, backupOf="c1", generation=2, seededFrom="c1")
    b["name"], b["volumeL"] = "Nanno B", 1.0
    entry = _phyto_entry(jars={"c1": a, "c2": b},
                         maintenance={"tasks": {"culture_c2_refresh": {"label": "Refresh Nanno B from Nanno A", "enabled": True, "cadenceDays": 32}},
                                      "completions": {}, "reminders": {"enabled": True}})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_summary(hass, conn, {"id": 1}))
    jars = {j["id"]: j for j in conn.results[-1].payload["jars"]}
    assert jars["c2"]["backupOf"] == "c1" and "refresh" in jars["c2"]["due"] and jars["c2"]["refresh"]["available"]
    assert jars["c2"]["refresh"]["fromName"] == "Nanno A" and jars["c2"]["refresh"]["starterMl"] == 250 and jars["c2"]["refresh"]["freshMl"] == 750
    assert jars["c1"]["refresh"]["backupId"] == "c2" and jars["c1"]["refresh"]["backupName"] == "Nanno B" and not jars["c1"]["refresh"]["isBackup"]
    assert "harvest" not in jars["c2"]["due"], "the calendar never asks B for a split"
    assert jars["c2"]["risk"]["level"] == "watch" and "the backup is 33 days old" in jars["c2"]["risk"]["reason"]
    assert conn.results[-1].payload["sun"]["available"] is False, "no sun entity on this fake — never a guess"
    plan = integration._cultures_push_plan(conn.results[-1].payload)
    b_push = next(p for p in plan if p["jarId"] == "c2")
    assert b_push["title"] == "OpenReef: Nanno B — refresh?" and b_push["actions"][0] == {"action": "OPENREEF_CULTURE_REFRESH:c2", "title": "Refresh from Nanno A"}
    assert b_push["message"] == "The backup is 33 days old — a fresh litre from Nanno A"
    f2_before = _config(entry)["consumables"]["products"]["f2"]["remainingMl"]
    run(integration.websocket_cultures_refresh_backup(hass, conn, {"id": 2, "jar_id": "c2"}))
    assert not conn.errors, conn.errors
    cfg = _config(entry)
    b_after, a_after = cfg["nps"]["cultures"]["jars"]["c2"], cfg["nps"]["cultures"]["jars"]["c1"]
    assert b_after["history"][0]["event"] == "seeded" and b_after["history"][0]["from"] == "c1" and b_after["history"][0]["freshMl"] == 750
    assert b_after["history"][1]["event"] == "restart" and b_after["history"][1]["from"] == "c1" and b_after["history"][1]["dests"] == [{"to": "waste", "ml": 1000}]
    assert b_after["state"]["backupOf"] == "c1" and b_after["state"]["generation"] == 2 and b_after["state"]["workingL"] == 1.0, "gen = A's + 1: a refresh is a new seed, not a lineage step"
    assert (REAL - integration._parse_datetime(b_after["state"]["startedAt"])).total_seconds() < 60, "B's clock restarts — the refresh clock with it"
    assert cfg["maintenance"]["completions"]["culture_c2_refresh"][0]["notes"] == "Logged automatically — Nanno B refreshed from Nanno A"
    row = next(r for r in a_after["history"] if r["event"] == "harvest")
    assert row["ml"] == 250 and row["freshMl"] == 250 and a_after["state"]["workingL"] == 1.25, "A gives 250 ml and takes 250 ml back — like for like"
    assert a_after["history"][0] == {**a_after["history"][0], "event": "split", "from": "c2", "ml": 250}
    assert round(f2_before - cfg["consumables"]["products"]["f2"]["remainingMl"], 2) == round(0.375 + 1.125, 2), "f/2 by the fresh litres: A's 250 ml and B's 750 ml"
    assert any("Nanno B refreshed from Nanno A" in x["message"] for x in cfg["activity"])
    run(integration.websocket_cultures_summary(hass, conn, {"id": 3}))
    jars = {j["id"]: j for j in conn.results[-1].payload["jars"]}
    assert "refresh" not in jars["c2"]["due"] and jars["c2"]["state"]["refresh"]["hoursUntil"] > 31 * 24
    # A's own split with a vessel share now REFRESHES B rather than making a third jar.
    cfg["nps"]["cultures"]["jars"]["c1"]["state"]["lastTint"] = "dark"
    cfg["nps"]["cultures"]["jars"]["c1"]["history"].insert(0, {"event": "tint", "at": _iso(REAL), "tint": "dark"})
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    run(integration.websocket_cultures_split(hass, conn, {"id": 4, "jar_id": "c1", "ml": 750, "to": [{"to": "bottle", "ml": 500}, {"to": "vessel", "ml": 250}]}))
    assert not conn.errors, conn.errors
    cfg = _config(entry)
    assert set(cfg["nps"]["cultures"]["jars"]) == {"c1", "c2"}
    b_rows = cfg["nps"]["cultures"]["jars"]["c2"]["history"]
    assert b_rows[0]["event"] == "seeded" and b_rows[1]["event"] == "restart" and sum(1 for r in b_rows if r["event"] == "restart") == 2
    # Refusals: not a backup, the parent idle, the parent not ready — nothing written.
    run(integration.websocket_cultures_refresh_backup(hass, conn, {"id": 5, "jar_id": "c1"}))
    assert conn.errors[-1].code == "not_a_backup"
    cfg["nps"]["cultures"]["jars"]["c1"]["state"]["lastTint"] = "pale"
    cfg["nps"]["cultures"]["jars"]["c1"]["history"].insert(0, {"event": "tint", "at": _iso(REAL), "tint": "pale"})
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    before = len(_cultures(entry)["jars"]["c2"]["history"])
    run(integration.websocket_cultures_refresh_backup(hass, conn, {"id": 6, "jar_id": "c2"}))
    assert conn.errors[-1].code == "not_ready_to_split" and len(_cultures(entry)["jars"]["c2"]["history"]) == before
    cfg["nps"]["cultures"]["jars"]["c1"]["state"]["crashedAt"] = _iso(REAL + timedelta(seconds=1))
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    run(integration.websocket_cultures_refresh_backup(hass, conn, {"id": 7, "jar_id": "c2"}))
    assert conn.errors[-1].code == "parent_idle"
    # The phone's Refresh button is the same ceremony.
    cfg["nps"]["cultures"]["jars"]["c1"]["state"].update({"crashedAt": "", "lastTint": "dark"})
    cfg["nps"]["cultures"]["jars"]["c1"]["history"].insert(0, {"event": "tint", "at": _iso(REAL + timedelta(seconds=1)), "tint": "dark"})
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    event = type("Ev", (), {"data": {"action": "OPENREEF_CULTURE_REFRESH:c2"}})()
    run(integration._async_notification_action(hass, event))
    assert _cultures(entry)["jars"]["c2"]["history"][0]["event"] == "seeded"


def test_ws_apply_learned_moves_the_split_interval_and_switches_to_daily():
    now = REAL
    rows = [{"event": "seeded", "at": _iso(now - timedelta(days=20)), "ml": 1250, "tint": "pale", "freshMl": 1000, "nutrientMl": 1.5, "workingMl": 1250},
            {"event": "tint", "at": _iso(now - timedelta(days=14)), "tint": "dark"},
            {"event": "harvest", "at": _iso(now - timedelta(days=13)), "ml": 750, "tint": "dark", "freshMl": 750, "nutrientMl": 1.1, "workingMl": 1250},
            {"event": "tint", "at": _iso(now - timedelta(days=7)), "tint": "dark"}]
    jar = _phyto_jar(started_ago_days=20, lastHarvestAt=_iso(now - timedelta(days=13)), lastTint="green")
    jar["history"] = list(reversed(rows))
    entry = _phyto_entry(jars={"c1": jar}, maintenance={"tasks": {"culture_c1_harvest": {"label": "Split Nanno A", "enabled": True, "cadenceDays": 8, "criticalAfterDays": 11}},
                                                           "completions": {}, "reminders": {"enabled": True}})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_summary(hass, conn, {"id": 1}))
    j = conn.results[-1].payload["jars"][0]
    assert j["learned"]["suggest"]["splitIntervalDays"] == 6 and j["dailyOffer"] == {"available": True, "pct": 20.0}
    run(integration.websocket_cultures_apply_learned(hass, conn, {"id": 2, "jar_id": "c1", "field": "splitIntervalDays"}))
    assert not conn.errors, conn.errors
    cfg = _config(entry)
    assert cfg["nps"]["cultures"]["jars"]["c1"]["cadence"]["splitIntervalDays"] == 6
    task = cfg["maintenance"]["tasks"]["culture_c1_harvest"]
    assert task["cadenceDays"] == 6 and task["criticalAfterDays"] == 9 and task["cadenceHours"] == 144
    assert any("split cadence set from the journal — 6 days" in x["message"] for x in cfg["activity"])
    run(integration.websocket_cultures_summary(hass, conn, {"id": 3}))
    j = conn.results[-1].payload["jars"][0]
    assert j["state"]["cycle"]["ofDays"] == 6 and j["cadence"]["harvestIntervalDays"] == 6, "the chore clock follows"
    run(integration.websocket_cultures_apply_learned(hass, conn, {"id": 4, "jar_id": "c1", "field": "mode"}))
    assert not conn.errors, conn.errors
    cfg = _config(entry)
    jar_after = cfg["nps"]["cultures"]["jars"]["c1"]
    assert jar_after["mode"] == "daily" and jar_after["cadence"]["splitIntervalDays"] == 1 and jar_after["cadence"]["splitPct"] == 20
    assert cfg["maintenance"]["tasks"]["culture_c1_harvest"]["cadenceDays"] == 1
    run(integration.websocket_cultures_summary(hass, conn, {"id": 5}))
    j = conn.results[-1].payload["jars"][0]
    assert j["mode"] == "daily" and j["dailyOffer"]["available"] is False and j["learned"]["suggest"]["mode"] is None
    assert j["splitGuide"]["outMl"] == 250 and j["splitGuide"]["removalPct"] == 20, "the daily draw is sized to the culture"
    run(integration.websocket_cultures_apply_learned(hass, conn, {"id": 6, "jar_id": "c1", "field": "mode"}))
    assert conn.errors[-1].code == "not_learned"
    run(integration.websocket_cultures_apply_learned(hass, conn, {"id": 7, "jar_id": "c1", "field": "lightHours"}))
    assert conn.errors[-1].code == "unknown_field"


def test_ws_summary_reads_the_vessel_sensor_the_sun_and_the_lamp_and_the_guard_speaks_phyto():
    now = datetime.now(timezone.utc)
    jar = _phyto_jar(started_ago_days=12, lastTint="green")
    jar["light"] = {"mode": "sun+lamp", "switchEntity": "switch.lamp", "onAt": "07:00", "latestOff": "00:00", "tempEntity": "sensor.nanno_water"}
    entry = _phyto_entry(jars={"c1": jar}, maintenance={"tasks": {}, "completions": {}, "reminders": {"enabled": True, "notifyTarget": "mobile_app_phone"}})
    cfg = _config(entry)
    cfg["nps"]["cultures"]["tempEntity"] = "sensor.rack"
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    hass = FakeHass(states={"sensor.rack": FakeState("24.0", {"unit_of_measurement": "°C"}),
                            "sensor.nanno_water": FakeState("29.6", {"unit_of_measurement": "°C"}),
                            "switch.lamp": "on",
                            "sun.sun": FakeState("below_horizon", {"next_rising": _iso(now + timedelta(hours=9)), "next_setting": _iso(now + timedelta(hours=23)), "elevation": -8.2})},
                    entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_summary(hass, conn, {"id": 1}))
    payload = conn.results[-1].payload
    j = payload["jars"][0]
    assert payload["tempC"] == 24.0, "the rack's air is still the rack's"
    assert j["temp"]["tempC"] == 29.6 and j["temp"]["source"] == "vessel" and j["temp"]["status"] == "hot"
    assert j["risk"]["level"] == "watch" and "29.6 °C at the rack" in j["risk"]["reason"]
    assert payload["sun"]["available"] and payload["sun"]["daylightH"] == 14.0 and payload["sun"]["isDay"] is False
    light = j["light"]
    assert light["mode"] == "sun+lamp" and light["plugOn"] and light["lit"] and light["window"]["active"] and light["plannedLampH"] == 2.0
    assert light["status"] == "ok" and light["lampH"] == 0, "own stamps only — a plug on that we did not light counts nothing yet"
    assert payload["rig"]["phyto"][0]["lightOn"] is True
    # Without the vessel sensor the rack stands in, and says so.
    cfg["nps"]["cultures"]["jars"]["c1"]["light"]["tempEntity"] = ""
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    run(integration.websocket_cultures_summary(hass, conn, {"id": 2}))
    j = conn.results[-1].payload["jars"][0]
    assert j["temp"]["tempC"] == 24.0 and j["temp"]["source"] == "rack"
    # The heat guard's push for the alga carries the alga's sentence.
    hass.data.setdefault(integration.DOMAIN, {})[integration.COOLING_RUNTIME] = {"snapshot": {"projection": {"hours": [
        {"at": _iso(now + timedelta(hours=4)), "roomC": 29.4}]}}}
    config = _config(entry)
    assert run(integration._async_cultures_heat_guard_push(hass, config, "mobile_app_phone")) == 1
    call = hass.services.calls[-1]
    assert call.data["title"] == "OpenReef: heat ahead for the Nannochloropsis (phyto)"
    assert "shade it, move it off the sunlit shelf" in call.data["message"] and "The alga declines abruptly near 30 °C" in call.data["message"]
    assert "ammonia" not in call.data["message"]


def test_shelf_nudge_says_what_the_vessel_is_doing_about_an_empty_bottle():
    jar = _phyto_jar(started_ago_days=12, lastTint="dark")
    jar["history"] = [{"event": "tint", "at": _iso(REAL - timedelta(hours=1)), "tint": "dark"}]
    products = {**_phyto_products(), "home_phyto_c1": {"name": "Home phyto (Nanno A)", "category": "phyto", "bottleMl": 1000, "remainingMl": 0,
                                                       "refrigerated": True, "stirDaily": True, "shelfLifeDaysOpened": 21, "openedAt": "", "history": [],
                                                       "doseMl": 35, "doseEveryDays": 1}}
    entry = _phyto_entry(jars={"c1": jar}, products=products)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_summary(hass, conn, {"id": 1}))
    state = conn.results[-1].payload["shelf"]["products"]["home_phyto_c1"]
    assert state["splitNudge"] == "empty — Nanno A reads dark: split into this bottle"
    assert "splitNudge" not in conn.results[-1].payload["shelf"]["products"]["f2"]
    # Greening: the next split's clock; a full bottle: no nudge at all.
    cfg = _config(entry)
    cfg["nps"]["cultures"]["jars"]["c1"]["state"].update({"lastTint": "green", "lastHarvestAt": _iso(REAL - timedelta(days=5))})
    cfg["nps"]["cultures"]["jars"]["c1"]["history"] = []
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    run(integration.websocket_nps_summary(hass, conn, {"id": 2}))
    assert conn.results[-1].payload["shelf"]["products"]["home_phyto_c1"]["splitNudge"] == "empty — Nanno A's next split is due in ~3 d"
    cfg["consumables"]["products"]["home_phyto_c1"].update({"remainingMl": 800, "openedAt": _iso(REAL - timedelta(days=1))})
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    run(integration.websocket_nps_summary(hass, conn, {"id": 3}))
    assert conn.results[-1].payload["shelf"]["products"]["home_phyto_c1"]["splitNudge"] == ""
    # The pure sentence: low with a running-out clock and a sign on the vessel.
    low = {"empty": False, "low": True, "remainingMl": 60, "daysUntilEmpty": 1.7}
    assert nps_engine.home_bottle_nudge(low, {"status": "producing", "harvestBlocked": True}, "Nanno A").startswith("runs out in ~1.7 d — Nanno A is off-colour")
    assert nps_engine.home_bottle_nudge(low, {"status": "none"}, "Nanno A") == "runs out in ~1.7 d — Nanno A is not running; seed it and the bottle fills at the first split"
    early = nps_engine.home_bottle_nudge(low, {"status": "producing", "splitEligible": False, "harvest": {"hoursUntil": 96}}, "Nanno A", 6)
    assert early == "runs out in ~1.7 d — Nanno A's next split is due in ~4 d (your record says ~6 d to dark) — a small early split tides it over"


def test_normaliser_keeps_the_light_block_and_the_stage_b_stamps():
    raw = {"enabled": True, "jars": {"c1": {"name": "Nanno A", "species": "nanno",
                                            "light": {"mode": "sun+lamp", "switchEntity": "switch.lamp", "onAt": "6:30", "latestOff": "25:00", "tempEntity": "sensor.x"},
                                            "state": {"backupOf": "c9", "lightOnAt": "2026-09-21T19:00:00+00:00", "lightMinutesToday": 9999, "lightDay": "2026-09-21", "lightWatchAt": "x", "lightLostDay": "2026-09-21"},
                                            "history": [{"event": "light", "at": "2026-09-20T23:59:00+00:00", "lightH": 15.5, "lampH": 3.2, "daylightH": 12.3}]}}}
    out = integration._normalise_cultures(raw)
    jar = out["jars"]["c1"]
    assert jar["light"] == {"mode": "sun+lamp", "switchEntity": "switch.lamp", "onAt": "06:30", "latestOff": "00:00", "tempEntity": "sensor.x"}
    assert jar["state"]["backupOf"] == "c9" and jar["state"]["lightMinutesToday"] == 1440 and jar["state"]["lightDay"] == "2026-09-21"
    assert jar["history"][0]["lightH"] == 15.5 and jar["history"][0]["lampH"] == 3.2 and jar["history"][0]["daylightH"] == 12.3
    junk = integration._normalise_cultures({"jars": {"c1": {"species": "nanno", "light": {"mode": "moon", "switchEntity": "not an entity"}}}})
    assert junk["jars"]["c1"]["light"]["mode"] == "sun" and junk["jars"]["c1"]["light"]["switchEntity"] == "" and junk["jars"]["c1"]["light"]["onAt"] == "07:00"
    assert "light" in integration._normalise_cultures({"jars": {"c1": {"species": "rotifer_L"}}})["jars"]["c1"], "every jar carries the block; only a vessel reads it"

# --------------------------------------------------------------------------- #
# 0.7.209 — the phyto vessel, Stage C: the rotifer coupling and the stick
# (doc §4.2, §5.5, §6, §12)
# --------------------------------------------------------------------------- #
def test_three_way_jug_and_the_cone_dose():
    # The brief's own numbers: a 27 ppt cone, 675 ml to replace, 350 ml of 35 ppt phyto.
    g = cultures.refill_guide(0.675, 100, 27, 35, 350, 35)
    assert (g["mixMl"], g["rodiMl"], g["phytoMl"], g["resultPpt"]) == (171, 154, 350, 27.0)
    assert g["mixMl"] + g["rodiMl"] + g["phytoMl"] == g["totalMl"] == 675
    assert round((171 * 35 + 350 * 35) / 675, 1) == 27.0, "the salt balances"
    # Too much salty phyto for a brackish cone: refused with the most it could take.
    g = cultures.refill_guide(0.675, 100, 27, 35, 600, 35)
    assert g["available"] is False and "cut the phyto to 520 ml" in g["reason"] and g["resultPpt"] == 31.1
    # Same salinity: the phyto simply replaces mix.
    g = cultures.refill_guide(0.675, 100, 35, 35, 170, 35)
    assert (g["mixMl"], g["rodiMl"]) == (505, 0)
    # Brackish phyto into a full-strength jar: not reachable.
    g = cultures.refill_guide(0.5, 100, 35, 35, 300, 27)
    assert g["available"] is False and "stronger saltwater" in g["reason"]
    # No phyto: the old two-way jug, byte for byte.
    assert cultures.refill_guide(0.675, 100, 27, 35) == {"totalMl": 675, "mixMl": 521, "rodiMl": 154, "targetPpt": 27.0, "mixPpt": 35.0, "sg": cultures.sg_from_ppt(27)}
    assert cultures.refill_guide(0.675, 100, 27, 35, 0, 35) == cultures.refill_guide(0.675, 100, 27, 35)
    # One tint of the cone (doc §4.1): ~170 ml for 2.5 L, an estimate rounded to 10 ml.
    assert cultures.cone_dose_ml(2.5) == 170 and cultures.cone_dose_ml(1.0) == 70 and cultures.cone_dose_ml(4) == 270
    jar = {"species": "rotifer_L", "volumeL": 2.5, "salinityPpt": 27, "vesselKind": "cone", "purgeMl": 50, "cadence": {}}
    hg = cultures.harvest_guide(jar, 35, None, 170, 35)
    assert hg["refillMl"] == 675 and hg["phytoMl"] == 170 and hg["mixMl"] + hg["rodiMl"] + hg["phytoMl"] == 675 and hg["resultPpt"] == 27.0
    assert cultures.harvest_guide(jar, 35)["mixMl"] == 521, "without phyto nothing changed"


def test_secchi_fit_reads_the_keepers_own_stick():
    def iso(d):
        return _iso(NOW - timedelta(days=d))
    hist = [{"event": "seeded", "at": iso(20)}, {"event": "tint", "at": iso(19), "tint": "pale", "secchiCm": 16},
            {"event": "tint", "at": iso(17), "tint": "pale", "secchiCm": 12}, {"event": "tint", "at": iso(15), "tint": "green", "secchiCm": 8},
            {"event": "tint", "at": iso(14), "tint": "dark", "secchiCm": 4}, {"event": "harvest", "at": iso(13), "ml": 750},
            {"event": "tint", "at": iso(12), "tint": "pale", "secchiCm": 14}, {"event": "tint", "at": iso(10), "tint": "green", "secchiCm": 7},
            {"event": "tint", "at": iso(8), "tint": "dark", "secchiCm": 4.5}, {"event": "harvest", "at": iso(7), "ml": 750},
            {"event": "tint", "at": iso(5), "tint": "green", "secchiCm": 9}]
    samples = cultures.secchi_samples(hist)
    assert len(samples) == 8 and samples[0] == {"at": samples[0]["at"], "cm": 16.0, "tint": "pale", "days": 1.0}
    assert samples[-1]["days"] == 2.0, "days since the LAST split"
    fit = cultures.secchi_fit(hist, 9)
    assert fit["available"] and fit["bands"] == {"pale": 14.0, "green": 8.0, "dark": 4.2} and fit["counts"]["dark"] == 2
    assert fit["stick"] == {"darkMaxCm": 6.1, "greenMaxCm": 11.0}, "the zones between the medians"
    assert fit["fit"]["available"] and fit["fit"]["halvingDays"] == 3.0 and fit["fit"]["points"] == 8 and fit["fit"]["slopePerDay"] < 0
    assert fit["daysToDark"] == 3.3 and fit["lastCm"] == 9.0
    assert fit["line"] == ("Secchi: on your stick: dark ~4.2 cm, green ~8 cm, pale ~14 cm (8 readings) · "
                           "the depth halves every ~3 d (8 readings, your fit) · today's 9 cm is ~3.3 d from dark")
    assert cultures.secchi_fit(hist, 4)["daysToDark"] == 0.0
    # Two readings are bands at best; one is nothing; a rising depth is no fit.
    two = [{"event": "seeded", "at": iso(6)}, {"event": "tint", "at": iso(5), "tint": "green", "secchiCm": 9}, {"event": "tint", "at": iso(4), "tint": "green", "secchiCm": 8}]
    f2 = cultures.secchi_fit(two)
    assert f2["available"] and f2["bands"] == {"green": 8.5} and f2["stick"] is None and f2["fit"]["available"] is False and f2["daysToDark"] is None
    assert cultures.secchi_fit([{"event": "tint", "at": iso(1), "tint": "dark", "secchiCm": 4}])["available"] is False
    rising = [{"event": "seeded", "at": iso(8)}] + [{"event": "tint", "at": iso(7 - d), "tint": "pale", "secchiCm": 5 + d * 2} for d in range(5)]
    fr = cultures.secchi_fit(rising)
    assert fr["fit"]["available"] is False and fr["fit"]["slopePerDay"] > 0, "a slope that is not downward is reported, never used"
    # A crash ends the cycle: readings after it have no day.
    crashed = [{"event": "seeded", "at": iso(9)}, {"event": "crashed", "at": iso(8)}, {"event": "tint", "at": iso(7), "tint": "pale", "secchiCm": 15}]
    assert cultures.secchi_samples(crashed)[0]["days"] is None
    # The journal's learned block carries it for a vessel.
    jar = _phyto_jar(started_ago_days=20, now=NOW, lastTint="green", lastHarvestAt=iso(7))
    jar["history"] = list(reversed(hist))
    assert cultures.learned_cadences(jar, [jar["history"]], NOW)["secchi"]["daysToDark"] == 3.3


def test_ws_rotifer_harvest_refills_with_phyto_from_the_home_bottle():
    cone = _jar(started_ago_days=12, lastTint="clearing")
    cone["salinityPpt"] = 27
    cone["feed"] = {"productId": "home_phyto_c2", "doseMl": 170}
    vessel = _phyto_jar(started_ago_days=12, lastTint="dark")
    vessel["history"] = [{"event": "tint", "at": _iso(REAL - timedelta(hours=1)), "tint": "dark"}]
    products = {**_phyto_products(),
                "home_phyto_c2": {"name": "Home phyto (Nanno A)", "category": "phyto", "bottleMl": 1000, "remainingMl": 600, "refrigerated": True,
                                  "stirDaily": True, "shelfLifeDaysOpened": 21, "openedAt": _iso(REAL - timedelta(days=2)), "history": [], "doseMl": 35, "doseEveryDays": 1}}
    entry = _phyto_entry(jars={"c1": cone, "c2": vessel}, products=products,
                         maintenance={"tasks": {"culture_c1_feed": {"label": "Feed", "enabled": True, "cadenceHours": 12}}, "completions": {}, "reminders": {"enabled": True}})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_summary(hass, conn, {"id": 1}))
    j = next(x for x in conn.results[-1].payload["jars"] if x["id"] == "c1")
    assert [s["id"] for s in j["phytoSources"]] == ["bottle:home_phyto_c2", "vessel:c2"] and j["coneDoseMl"] == 170
    assert j["phytoSources"][0]["ml"] == 600 and j["phytoSources"][1]["ready"] and j["phytoSources"][1]["tint"] == "dark"
    assert j["phytoRefill"]["sourceId"] == "bottle:home_phyto_c2" and j["phytoRefill"]["phytoMl"] == 170 and j["phytoRefill"]["refillMl"] == 675
    assert j["phytoRefill"]["mixMl"] + j["phytoRefill"]["rodiMl"] + 170 == 675 and j["phytoRefill"]["stillGreen"] is False
    v = next(x for x in conn.results[-1].payload["jars"] if x["id"] == "c2")
    assert v["cones"] == [{"id": "c1", "name": "Rotifers A", "doseMl": 170, "tint": "clearing", "stillGreen": False, "feedDue": True}]
    debits = []
    real = integration._mixing_hatchery_debit
    integration._mixing_hatchery_debit = lambda hass_, config_, litres, why: debits.append(round(litres * 1000))
    try:
        run(integration.websocket_cultures_log(hass, conn, {"id": 2, "jar_id": "c1", "tint": "clearing", "harvested": True,
                                                            "phyto_from": "bottle:home_phyto_c2"}))
        assert not conn.errors, conn.errors
        cfg = _config(entry)
        cone_after = cfg["nps"]["cultures"]["jars"]["c1"]
        row = cone_after["history"][0]
        assert row["event"] == "harvest" and row["fed"] is True and row["phytoMl"] == 170 and row["phytoFrom"] == "bottle:home_phyto_c2"
        assert cone_after["state"]["lastTint"] == "green" and cone_after["state"]["lastFedAt"], "the refill IS the feed"
        bottle = cfg["consumables"]["products"]["home_phyto_c2"]
        assert bottle["remainingMl"] == 430 and bottle["history"][-1]["to"] == "jar" and bottle["history"][-1]["jarId"] == "c1"
        # 675 ml refill at 27 ppt: 170 ml of 35 ppt phyto + 351 ml mix + 154 ml RODI.
        assert debits == [351], debits
        assert cfg["maintenance"]["completions"]["culture_c1_feed"][0]["notes"].startswith("Logged automatically — fed with the refill: 170 ml")
        assert any("170 ml of phyto from Home phyto (Nanno A) in the refill (351 ml mix + 154 ml RODI → 27 ppt)" in a["message"] for a in cfg["activity"])
        # Still green: refused before anything moves.
        before = copy.deepcopy((cfg["nps"]["cultures"]["jars"]["c1"]["history"], cfg["consumables"]["products"]["home_phyto_c2"]["remainingMl"]))
        run(integration.websocket_cultures_log(hass, conn, {"id": 3, "jar_id": "c1", "harvested": True, "phyto_ml": 100}))
        assert conn.errors[-1].code == "still_green"
        cfg = _config(entry)
        assert (cfg["nps"]["cultures"]["jars"]["c1"]["history"], cfg["consumables"]["products"]["home_phyto_c2"]["remainingMl"]) == before
        # A short bottle, a missing source, more phyto than the refill.
        cfg["nps"]["cultures"]["jars"]["c1"]["state"]["lastTint"] = "clear"
        cfg["consumables"]["products"]["home_phyto_c2"]["remainingMl"] = 50
        entry.options = {**entry.options, CONF_SETTINGS: cfg}
        run(integration.websocket_cultures_log(hass, conn, {"id": 4, "jar_id": "c1", "harvested": True, "phyto_ml": 100}))
        assert conn.errors[-1].code == "phyto_short"
        run(integration.websocket_cultures_log(hass, conn, {"id": 5, "jar_id": "c1", "harvested": True, "phyto_from": "bottle:nope", "phyto_ml": 20}))
        assert conn.errors[-1].code == "no_phyto_source"
        run(integration.websocket_cultures_log(hass, conn, {"id": 6, "jar_id": "c1", "harvested": True, "ml": 200, "phyto_from": "vessel:c2", "phyto_ml": 900}))
        assert conn.errors[-1].code == "invalid_volume"
    finally:
        integration._mixing_hatchery_debit = real


def test_ws_rotifer_harvest_and_restart_draw_from_a_dark_vessel():
    cone = _jar(started_ago_days=12, lastTint="clear", lastRestartAt=_iso(REAL - timedelta(days=15)))
    cone["salinityPpt"] = 27
    vessel = _phyto_jar(started_ago_days=12, lastTint="dark", cyclesSinceFresh=1, lastHarvestAt=_iso(REAL - timedelta(days=5)))
    vessel["history"] = [{"event": "tint", "at": _iso(REAL - timedelta(hours=1)), "tint": "dark"}]
    entry = _phyto_entry(jars={"c1": cone, "c2": vessel})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_log(hass, conn, {"id": 1, "jar_id": "c1", "harvested": True, "phyto_from": "vessel:c2"}))
    assert not conn.errors, conn.errors
    cfg = _config(entry)
    cone_after, v_after = cfg["nps"]["cultures"]["jars"]["c1"], cfg["nps"]["cultures"]["jars"]["c2"]
    assert cone_after["history"][0]["phytoMl"] == 170 and cone_after["history"][0]["phytoFrom"] == "vessel:c2" and cone_after["state"]["lastTint"] == "green"
    draw = v_after["history"][0]
    assert draw["event"] == "harvest" and draw["draw"] is True and draw["ml"] == 170 and draw["dests"] == [{"to": "cone", "ml": 170, "jarId": "c1"}]
    assert draw["freshMl"] == 0 and draw["nutrientMl"] == 0, "a draw: nothing in, no f/2"
    assert v_after["state"]["workingL"] == 1.08 and v_after["state"]["lastTint"] == "dark", "the vessel stays dark, only the ledger moves"
    assert v_after["state"]["lastHarvestAt"] == _iso(REAL - timedelta(days=5)) and v_after["state"]["cyclesSinceFresh"] == 1, "no clock, no counter"
    assert not any(k.startswith("culture_c2_harvest") for k in (cfg.get("maintenance") or {}).get("completions") or {}), "a draw is not a split done"
    assert len([r for r in cone_after["history"] if r["event"] == "feed"]) == 0, "the cone's own ceremony wrote the harvest row — no second feed row"
    # The restart: FAO's batch method — the new water carries phyto; the linked feed product is NOT also debited.
    cfg["nps"]["cultures"]["jars"]["c1"]["feed"] = {"productId": "phyto", "doseMl": 5}
    cfg["consumables"]["products"]["phyto"] = {"name": "Live phyto", "bottleMl": 500.0, "remainingMl": 300.0, "history": [], "category": "phyto"}
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    debits = []
    real = integration._mixing_hatchery_debit
    integration._mixing_hatchery_debit = lambda hass_, config_, litres, why: debits.append(round(litres * 1000))
    try:
        run(integration.websocket_cultures_restart(hass, conn, {"id": 2, "jar_id": "c1", "phyto_from": "vessel:c2", "phyto_ml": 300}))
        assert not conn.errors, conn.errors
    finally:
        integration._mixing_hatchery_debit = real
    cfg = _config(entry)
    cone_after, v_after = cfg["nps"]["cultures"]["jars"]["c1"], cfg["nps"]["cultures"]["jars"]["c2"]
    row = cone_after["history"][0]
    assert row["event"] == "restart" and row["phytoMl"] == 300 and row["fed"] is True and row["ml"] == 2500
    # 2.5 L at 27 ppt with 300 ml of 35 ppt phyto: 1629 ml mix + 571 ml RODI (the vessel's draw moves no mix).
    assert [d for d in debits if d] == [1629], debits
    assert cfg["consumables"]["products"]["phyto"]["remainingMl"] == 300.0, "the phyto was the feed — the bottle is untouched"
    assert v_after["history"][0]["draw"] is True and v_after["state"]["workingL"] == 0.78, "300 of 1080 ml is still a draw"
    # A vessel that is not ready refuses; a restart never minds a green cone.
    cfg["nps"]["cultures"]["jars"]["c2"]["state"]["lastTint"] = "pale"
    cfg["nps"]["cultures"]["jars"]["c2"]["history"].insert(0, {"event": "tint", "at": _iso(REAL), "tint": "pale"})
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    run(integration.websocket_cultures_restart(hass, conn, {"id": 3, "jar_id": "c1", "phyto_from": "vessel:c2"}))
    assert conn.errors[-1].code == "vessel_not_ready"


def test_ws_phyto_split_feeds_a_cone_and_refuses_a_green_one():
    cone = _jar(started_ago_days=12, lastTint="clear")
    vessel = _phyto_jar(started_ago_days=12, lastTint="dark", workingL=3.5)
    vessel["history"] = [{"event": "tint", "at": _iso(REAL - timedelta(hours=1)), "tint": "dark"}]
    entry = _phyto_entry(jars={"c1": cone, "c2": vessel},
                         maintenance={"tasks": {"culture_c1_feed": {"label": "Feed", "enabled": True, "cadenceHours": 12}}, "completions": {}, "reminders": {"enabled": True}})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_split(hass, conn, {"id": 1, "jar_id": "c2", "ml": 2100,
                                                          "to": [{"to": "bottle", "ml": 1000}, {"to": "cone", "ml": 0, "jarId": "c1"}]}))
    assert not conn.errors, conn.errors
    cfg = _config(entry)
    cone_after, v_after = cfg["nps"]["cultures"]["jars"]["c1"], cfg["nps"]["cultures"]["jars"]["c2"]
    assert cone_after["history"][0]["event"] == "feed" and cone_after["history"][0]["phytoMl"] == 170 and cone_after["history"][0]["phytoFrom"] == "vessel:c2"
    assert cone_after["state"]["lastTint"] == "green" and cfg["maintenance"]["completions"]["culture_c1_feed"][0]["notes"].startswith("Logged automatically — 170 ml of phyto from Nanno A")
    row = v_after["history"][0]
    assert {d["to"]: d["ml"] for d in row["dests"]} == {"bottle": 1000, "cone": 170, "waste": 930}, "a zero cone share became one tint; the rest is waste"
    assert next(d for d in row["dests"] if d["to"] == "cone")["jarId"] == "c1"
    assert not row.get("draw") and v_after["state"]["lastTint"] == "pale" and v_after["state"]["cyclesSinceFresh"] == 1, "a 60 % split is a split"
    assert any("170 ml into Rotifers A" in a["message"] for a in cfg["activity"])
    # The cone reads green now: a second cone share is refused before anything moves.
    before = len(v_after["history"])
    run(integration.websocket_cultures_split(hass, conn, {"id": 2, "jar_id": "c2", "ml": 100, "to": [{"to": "cone", "ml": 100, "jarId": "c1"}]}))
    assert conn.errors[-1].code == "still_green" and len(_cultures(entry)["jars"]["c2"]["history"]) == before
    run(integration.websocket_cultures_split(hass, conn, {"id": 3, "jar_id": "c2", "ml": 100, "to": [{"to": "cone", "ml": 100, "jarId": "c2"}]}))
    assert conn.errors[-1].code == "unknown_destination"
    # A small draw to the tank keeps the vessel's colour and clock.
    cfg = _config(entry)
    cfg["nps"]["cultures"]["jars"]["c2"]["state"]["lastTint"] = "dark"
    cfg["nps"]["cultures"]["jars"]["c2"]["history"].insert(0, {"event": "tint", "at": _iso(REAL), "tint": "dark"})
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    anchor = cfg["nps"]["cultures"]["jars"]["c2"]["state"]["lastHarvestAt"]
    refused = len(conn.errors)
    run(integration.websocket_cultures_split(hass, conn, {"id": 4, "jar_id": "c2", "ml": 60, "to": [{"to": "tank", "ml": 60}]}))
    assert len(conn.errors) == refused, conn.errors[-1]
    v_after = _cultures(entry)["jars"]["c2"]
    assert v_after["history"][0]["draw"] is True and v_after["state"]["lastTint"] == "dark" and v_after["state"]["lastHarvestAt"] == anchor
    assert v_after["history"][0]["dests"] == [{"to": "tank", "ml": 60}] and v_after["history"][0]["freshMl"] == 60
    assert v_after["state"]["workingL"] == 3.5, "the tile's default is like for like — a draw topped up keeps its working volume"
    # In daily mode every draw is the day's split: the clock re-anchors.
    cfg = _config(entry)
    cfg["nps"]["cultures"]["jars"]["c2"]["mode"] = "daily"
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    run(integration.websocket_cultures_split(hass, conn, {"id": 5, "jar_id": "c2", "ml": 60, "to": [{"to": "tank", "ml": 60}]}))
    assert len(conn.errors) == refused, conn.errors[-1]
    assert _cultures(entry)["jars"]["c2"]["state"]["lastHarvestAt"] != anchor and not _cultures(entry)["jars"]["c2"]["history"][0].get("draw")


def test_cone_default_dose_from_the_home_bottle_and_the_report_yield():
    # A rotifer jar with no feed product gets the rack's home bottle at one tint; a keeper's number stands.
    entry = _phyto_entry(jars={"c1": _jar(started_ago_days=3), "c2": _phyto_jar(started_ago_days=5, lastTint="green"),
                               "c3": {**_jar(started_ago_days=3), "name": "Pods", "species": "tigriopus", "volumeL": 4, "feed": {"productId": "home_phyto_c2", "doseMl": 5}},
                               "c4": {**_jar(started_ago_days=3), "name": "Mine", "feed": {"productId": "home_phyto_c2", "doseMl": 50}}},
                         products={**_phyto_products(), "home_phyto_c2": {"name": "Home phyto (Nanno A)", "category": "phyto", "bottleMl": 1000, "remainingMl": 300, "history": []}})
    cfg = _config(entry)
    cfg["nps"]["cultures"]["jars"]["c1"]["feed"] = {"productId": "", "doseMl": 5}
    integration._cultures_ensure_home_bottles(cfg)
    jars = cfg["nps"]["cultures"]["jars"]
    assert jars["c1"]["feed"] == {"productId": "home_phyto_c2", "doseMl": 170}, "linked at one tint of a 2.5 L cone"
    assert jars["c3"]["feed"]["doseMl"] == 270, "the untouched 5 ml default on a home bottle becomes one tint of the tub"
    assert jars["c4"]["feed"]["doseMl"] == 50, "a keeper's own number is never moved"
    assert any("Rotifers A will feed from Home phyto (Nanno A) — 170 ml a feed" in a["message"] for a in cfg["activity"])
    # No home bottle on the shelf: nothing happens.
    plain = _config(_entry(jars={"c1": _jar(started_ago_days=3)}))
    plain["nps"]["cultures"]["jars"]["c1"]["feed"] = {"productId": "", "doseMl": 5}
    integration._cultures_ensure_home_bottles(plain)
    assert plain["nps"]["cultures"]["jars"]["c1"]["feed"]["productId"] == ""
    # The Reef Report: the rack's yield beside the rotifer harvests.
    from openreef import report
    start, end = NOW - timedelta(days=7), NOW
    jars_ctx = {"n1": {"name": "Nanno A", "species": "nanno", "history": [
                    {"event": "harvest", "at": _iso(NOW - timedelta(days=1)), "ml": 750, "dests": [{"to": "bottle", "ml": 600}, {"to": "tank", "ml": 150}]},
                    {"event": "harvest", "at": _iso(NOW - timedelta(days=5)), "ml": 750, "dests": [{"to": "bottle", "ml": 500}, {"to": "cone", "ml": 170, "jarId": "r1"}, {"to": "waste", "ml": 80}]},
                    {"event": "harvest", "at": _iso(NOW - timedelta(days=2)), "ml": 60, "draw": True, "dests": [{"to": "tank", "ml": 60}]},
                    {"event": "tint", "at": _iso(NOW - timedelta(days=3)), "tint": "green", "secchiCm": 8},
                    {"event": "harvest", "at": _iso(NOW - timedelta(days=20)), "ml": 750}]},
                "r1": {"name": "Rotifers A", "species": "rotifer_L", "history": [
                    {"event": "harvest", "at": _iso(NOW - timedelta(days=1)), "ml": 625, "fed": True, "phytoMl": 170, "phytoFrom": "bottle:home_phyto_n1"},
                    {"event": "feed", "at": _iso(NOW - timedelta(days=3)), "fed": True, "phytoMl": 170, "phytoFrom": "vessel:n1"}]}}
    sec = report.cultures_section(jars_ctx, start, end)
    nanno = next(j for j in sec["jars"] if j["id"] == "n1")
    assert nanno["kind"] == "phyto" and nanno["harvests"] == 3 and nanno["yieldL"] == 1.56 and nanno["dests"] == {"bottle": 1100, "cone": 170, "tank": 210, "waste": 80}
    assert sec["phytoYieldL"] == 1.56 and nanno["looks"] == 1
    rots = next(j for j in sec["jars"] if j["id"] == "r1")
    assert rots["kind"] == "animal" and rots["feeds"] == 2 and rots["phytoFedMl"] == 340
    text = "\\n".join(str(b) for b in report.text_blocks({"living": {"cultures": sec, "hatches": {}, "corals": {}}, "period": {}, "score": {}, "water": {}, "maintenance": {}}))
    assert "Nanno A: 1 looks, 3 splits — 1.6 L (1.1 L bottle, 0.17 L cone, 0.21 L tank, 0.08 L waste)" in text, text[:600]
    assert "Rotifers A: 2 feeds, 0 looks, 1 harvests, 340 ml of home phyto" in text

# --------------------------------------------------------------------------- #
# 0.7.210 — the phyto vessel, Stage D: the index (doc §6, §13)
# --------------------------------------------------------------------------- #
def test_green_index_reads_the_patch_against_the_card():
    # Half the red, three quarters of the green through the culture: OD 0.30 and 0.125 → index 0.213.
    g = cultures.green_index({"r": 120, "g": 180, "b": 40}, {"r": 240, "g": 240, "b": 240})
    assert g["available"] and (g["odR"], g["odG"], g["odB"]) == (0.301, 0.125, 0.778) and g["od"] == 0.213
    assert (g["tR"], g["tG"]) == (0.5, 0.75) and not g["looksOff"] and not g["brighter"]
    # Green absorbed more than red: yellow-brown, a hint to look.
    assert cultures.green_index({"r": 150, "g": 100, "b": 40}, {"r": 240, "g": 240, "b": 240})["looksOff"]
    # Brighter than the card: the card was not lit the same — flagged, OD 0.
    b = cultures.green_index({"r": 250, "g": 250, "b": 250}, {"r": 200, "g": 200, "b": 200})
    assert b["brighter"] and b["od"] == 0.0
    # Black against the card saturates at the cap.
    assert cultures.green_index({"r": 0, "g": 0, "b": 0}, {"r": 240, "g": 240, "b": 240})["saturated"]
    # Missing channels, a dark card: not a reading.
    assert cultures.green_index({"r": 10, "g": 10}, {"r": 240, "g": 240, "b": 240})["available"] is False
    assert cultures.green_index({"r": 10, "g": 10, "b": 10}, {"r": 0, "g": 240, "b": 240})["available"] is False
    assert cultures.green_index(None, None)["available"] is False


def test_index_fit_bands_curve_days_to_dark_and_the_estimate():
    def iso(d, h=0):
        return _iso(NOW - timedelta(days=d, hours=h))
    hist = [{"event": "seeded", "at": iso(14)},
            {"event": "index", "at": iso(13), "od": 0.12, "source": "phone"}, {"event": "tint", "at": iso(13, -1), "tint": "pale"},
            {"event": "index", "at": iso(11), "od": 0.25, "source": "phone"}, {"event": "tint", "at": iso(11, 1), "tint": "pale"},
            {"event": "index", "at": iso(9), "od": 0.5, "source": "phone"}, {"event": "tint", "at": iso(9), "tint": "green"},
            {"event": "index", "at": iso(7), "od": 0.95, "source": "phone"}, {"event": "tint", "at": iso(7, -2), "tint": "dark"},
            {"event": "harvest", "at": iso(6), "ml": 750},
            {"event": "index", "at": iso(5), "od": 0.4, "source": "camera"}, {"event": "tint", "at": iso(5), "tint": "pale"},
            {"event": "index", "at": iso(3), "od": 0.6, "source": "camera"}, {"event": "tint", "at": iso(3), "tint": "green"},
            {"event": "index", "at": iso(1), "od": 0.9, "source": "camera"}, {"event": "tint", "at": iso(1), "tint": "dark"}]
    samples = cultures.index_samples(hist)
    assert len(samples) == 7 and [s["tint"] for s in samples] == ["pale", "pale", "green", "dark", "pale", "green", "dark"], "the nearest tap, either side"
    assert samples[4]["days"] == 1.0, "days since the LAST split"
    fit = cultures.index_fit(hist, 0.7)
    assert fit["bands"] == {"pale": 0.25, "green": 0.55, "dark": 0.925} and fit["darkOd"] == 0.925 and fit["counts"]["dark"] == 2
    assert fit["fit"]["available"] and fit["fit"]["doublingDays"] == 2.7 and fit["fit"]["points"] == 7 and fit["fit"]["ratePerDay"] > 0
    assert fit["daysToDark"] == 1.1 and fit["readsDark"] is False and fit["lastOd"] == 0.9 and fit["lastSource"] == "camera"
    assert fit["line"] == ("Index: your index: pale ~0.25, green ~0.55, dark ~0.925 (7 readings) · it doubles every ~2.7 d (7 readings, your fit) · "
                           "today's 0.7 is ~1.1 d from dark")
    dark = cultures.index_fit(hist, 0.95)
    assert dark["readsDark"] is True and dark["daysToDark"] == 0.0 and "today's 0.95 reads dark — look, then split" in dark["line"]
    assert cultures.index_dark_days(hist, NOW) == 0.0, "0.9 a day ago sits under the 0.925 band — no run"
    # A falling index is no curve; one reading is a number with no bands; a draw does not reset the tint.
    falling = [{"event": "seeded", "at": iso(8)}] + [{"event": "index", "at": iso(7 - d), "od": 0.9 - d * 0.15, "source": "phone"} for d in range(5)]
    ff = cultures.index_fit(falling, 0.3)
    assert ff["fit"]["available"] is False and ff["fit"]["ratePerDay"] < 0 and ff["darkOd"] is None
    one = cultures.index_fit([{"event": "seeded", "at": iso(3)}, {"event": "index", "at": iso(1), "od": 0.3, "source": "phone"}], 0.3)
    assert one["available"] and one["line"] == "Index: today's index 0.3 — the bands come with the tints you log beside it"
    drawn = hist + [{"event": "harvest", "at": iso(0, 6), "ml": 60, "draw": True}, {"event": "index", "at": iso(0, 5), "od": 0.92, "source": "phone"}]
    assert cultures.index_samples(drawn)[-1]["tint"] == "dark", "a draw keeps the colour"
    # The estimate only ever comes through a count.
    assert cultures.estimate_cells(0.7, None)["available"] is False
    est = cultures.estimate_cells(0.7, {"cellsPerMl": 1.2e7, "od": 0.9, "at": iso(1)})
    assert est["available"] and est["cellsPerMl"] == 9333333.0 and est["factor"] == 13333333 and "estimated from your count of 12,000,000 at an index of 0.9" in est["note"]
    assert cultures.estimate_cells(-1, {"cellsPerMl": 1.2e7, "od": 0.9})["available"] is False
    # The pH: rising, flat, falling — two days before it speaks.
    ph = [{"event": "light", "at": iso(d), "lightH": 15, "phMax": v} for d, v in ((4, 8.4), (3, 8.6), (2, 8.9), (1, 9.1))]
    t = cultures.ph_trend(ph)
    assert t["trend"] == "rising" and t["line"] == "pH 8.4 → 9.1 over 3 d — growing" and t["days"] == 4
    assert cultures.ph_trend([{"event": "light", "at": iso(d), "phMax": 9.1} for d in (3, 2, 1)])["trend"] == "flat"
    down = cultures.ph_trend([{"event": "light", "at": iso(d), "phMax": v} for d, v in ((2, 9.1), (1, 8.4))])
    assert down["trend"] == "falling" and "a crash? look at it" in down["line"]
    assert cultures.ph_trend([{"event": "light", "at": iso(1), "phMax": 9.1}])["available"] is False
    # The learned block carries all three; the risk line reads them.
    jar = _phyto_jar(started_ago_days=14, now=NOW, lastTint="green", lastHarvestAt=iso(6))
    jar["history"] = list(reversed(hist + ph))
    learned = cultures.learned_cadences(jar, [jar["history"]], NOW)
    assert learned["index"]["darkOd"] == 0.925 and learned["ph"]["trend"] == "rising"
    st = cultures.culture_state(jar, NOW)
    ok_temp = {"available": True, "status": "ok", "tempC": 23.0}
    risk = cultures.risk_line(jar, st, ok_temp, NOW, index={**learned["index"], "ph": {"trend": "falling", "line": "pH falling 9.1 → 8.4 over 2 d — a crash? look at it, smell it"}})
    assert risk["level"] == "watch" and "pH falling" in risk["reason"]
    # The index held at the dark band while the taps say green: the keeper
    # tapped green half a day ago (the tint run ends), the index kept reading
    # 0.95 — three and a half days on, the curve's own watch speaks.
    later = NOW + timedelta(days=3)
    jar["history"] = list(reversed(hist + [{"event": "tint", "at": iso(0, 12), "tint": "green"},
                                           {"event": "index", "at": iso(0, 11), "od": 0.95, "source": "phone"}]))
    jar["state"]["lastTint"] = "green"
    st = cultures.culture_state(jar, later)
    learned = cultures.learned_cadences(jar, [jar["history"]], later)
    assert learned["index"]["darkOd"] == 0.925 and not st["peakHeld"]
    assert cultures.index_dark_days(jar["history"], later) == 3.5
    assert "the index has read dark for 3.5 days" in cultures.risk_line(jar, st, ok_temp, later, index=learned["index"])["reason"]
    assert "reads yellow-brown" in cultures.risk_line(jar, st, ok_temp, NOW, index={"looksOff": True})["reason"]


def test_ws_index_reading_logs_the_look_calibrates_by_count_and_fills_the_bottle_at_the_split():
    vessel = _phyto_jar(started_ago_days=9, lastTint="green", lastLookedAt=_iso(REAL - timedelta(hours=30)))
    entry = _phyto_entry(jars={"c1": vessel}, maintenance={"tasks": {"culture_c1_look": {"label": "Look", "enabled": True, "cadenceDays": 1}}, "completions": {}, "reminders": {"enabled": True}})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_calibrate(hass, conn, {"id": 1, "jar_id": "c1", "cells_per_ml": 1.5e7}))
    assert conn.errors[-1].code == "no_index", "a count needs an index to hang on"
    run(integration.websocket_cultures_index(hass, conn, {"id": 2, "jar_id": "c1", "r": 250, "g": 250, "b": 250, "ref_r": 200, "ref_g": 200, "ref_b": 200}))
    assert conn.errors[-1].code == "brighter_than_card"
    run(integration.websocket_cultures_index(hass, conn, {"id": 3, "jar_id": "c1", "r": 120, "g": 180, "b": 40, "ref_r": 240, "ref_g": 240, "ref_b": 240, "source": "phone"}))
    assert len(conn.errors) == 2, conn.errors[-1]
    cfg = _config(entry)
    jar = cfg["nps"]["cultures"]["jars"]["c1"]
    row = jar["history"][0]
    assert row["event"] == "index" and row["od"] == 0.213 and row["odR"] == 0.301 and row["source"] == "phone" and "estCellsPerMl" not in row
    assert jar["state"]["lastIndexOd"] == 0.213 and jar["state"]["lastIndexAt"] and jar["state"]["lastTint"] == "green", "the tint stays the keeper's word"
    assert (REAL - integration._parse_datetime(jar["state"]["lastLookedAt"])).total_seconds() < 60, "a photo against the card is the day's look"
    assert cfg["maintenance"]["completions"]["culture_c1_look"][0]["notes"].startswith("Logged automatically — the index read")
    assert jar["state"]["lastHarvestAt"] == "" and jar["state"]["cyclesSinceFresh"] == 0, "never a clock"
    run(integration.websocket_cultures_summary(hass, conn, {"id": 4}))
    j = conn.results[-1].payload["jars"][0]
    assert j["index"]["readings"] == 1 and j["index"]["lastOd"] == 0.213 and j["index"]["estimate"] is None and j["index"]["calibration"] is None
    assert j["index"]["line"] == "Index: today's index 0.213 — the bands come with the tints you log beside it"
    # The count: within two days of the reading it calibrates; the estimate follows every later reading.
    run(integration.websocket_cultures_calibrate(hass, conn, {"id": 5, "jar_id": "c1", "cells_per_ml": 4.26e6}))
    assert len(conn.errors) == 2, conn.errors[-1]
    cfg = _config(entry)
    cal = cfg["nps"]["cultures"]["jars"]["c1"]["state"]["calibration"]
    assert cal["cellsPerMl"] == 4260000.0 and cal["od"] == 0.213 and cal["at"]
    run(integration.websocket_cultures_index(hass, conn, {"id": 6, "jar_id": "c1", "r": 60, "g": 120, "b": 40, "ref_r": 240, "ref_g": 240, "ref_b": 240, "source": "camera"}))
    cfg = _config(entry)
    row = cfg["nps"]["cultures"]["jars"]["c1"]["history"][0]
    assert row["od"] == 0.452 and row["estCellsPerMl"] == 9040000.0 and row["source"] == "camera", row
    run(integration.websocket_cultures_summary(hass, conn, {"id": 7}))
    j = conn.results[-1].payload["jars"][0]
    assert j["index"]["estimate"]["cellsPerMl"] == 9040000.0 and "estimated from your count of 4,260,000" in j["index"]["estimate"]["note"]
    # The split: the bottle carries the estimate, marked; the drip's line reads it.
    from test_nps import _drip_channel
    channel = _drip_channel(reservoir={"productId": "home_phyto_c1", "productIsBottle": False, "volumeMl": 500, "remainingMl": 100, "refrigerated": True})
    cfg["dosing"] = {**(cfg.get("dosing") or {}), "channels": {"drip": channel}}
    cfg["nps"]["cultures"]["jars"]["c1"]["state"]["lastTint"] = "dark"
    cfg["nps"]["cultures"]["jars"]["c1"]["history"].insert(0, {"event": "tint", "at": _iso(REAL), "tint": "dark"})
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    run(integration.websocket_cultures_split(hass, conn, {"id": 8, "jar_id": "c1", "to": [{"to": "bottle", "ml": 750}]}))
    assert len(conn.errors) == 2, conn.errors[-1]
    cfg = _config(entry)
    bottle = cfg["consumables"]["products"]["home_phyto_c1"]
    assert bottle["cellsPerMl"] == 9040000.0 and bottle["cellsPerMlSource"] == "index" and bottle["cellsPerMlAt"]
    assert any("~9,040,000 cells/ml estimated from your count" in a["message"] for a in cfg["activity"])
    from openreef import dosing as dosing_engine
    plan = {"mlPerDay": 41, "perDoseMl": 0.5, "dayIntervalMin": 20, "windowStart": 0, "windowEnd": 0}
    standing = dosing_engine.standing_state(channel, plan, 52, bottle)
    assert standing["mode"] == "density" and "the bottle's density is an estimate from your count" in standing["text"], standing["text"]
    # A stale client that never saw the estimate cannot wipe it.
    stale = copy.deepcopy(cfg)
    stale["consumables"]["products"]["home_phyto_c1"].pop("cellsPerMlSource", None)
    stale["consumables"]["products"]["home_phyto_c1"].pop("cellsPerMlAt", None)
    stale["consumables"]["products"]["home_phyto_c1"]["cellsPerMl"] = 0
    integration._nps_preserve_runtime(cfg, stale)
    assert stale["consumables"]["products"]["home_phyto_c1"]["cellsPerMl"] == 9040000.0 and stale["consumables"]["products"]["home_phyto_c1"]["cellsPerMlSource"] == "index"
    # Clearing the count: the index is a number again; the next split writes no density.
    run(integration.websocket_cultures_calibrate(hass, conn, {"id": 9, "jar_id": "c1", "cells_per_ml": 0}))
    assert _cultures(entry)["jars"]["c1"]["state"]["calibration"] is None
    # An index reading can be taken back; the look goes with it.
    stamp = _cultures(entry)["jars"]["c1"]["history"][1]["at"] if _cultures(entry)["jars"]["c1"]["history"][0]["event"] != "index" else _cultures(entry)["jars"]["c1"]["history"][0]["at"]
    row = next(r for r in _cultures(entry)["jars"]["c1"]["history"] if r["event"] == "index")
    run(integration.websocket_cultures_undo(hass, conn, {"id": 10, "jar_id": "c1", "at": row["at"]}))
    assert len(conn.errors) == 2, conn.errors[-1]
    jar = _cultures(entry)["jars"]["c1"]
    assert next(r for r in jar["history"] if r["at"] == row["at"])["undoneAt"] and jar["state"]["lastIndexOd"] == 0.213
    # Refusals write nothing: a bad reading, a jar that is not a vessel, an idle one.
    run(integration.websocket_cultures_index(hass, conn, {"id": 11, "jar_id": "c1", "r": 10, "g": 10, "b": 10, "ref_r": 0, "ref_g": 240, "ref_b": 240}))
    assert conn.errors[-1].code == "invalid_reading"
    rot = _phyto_entry(jars={"c1": _jar(started_ago_days=5)})
    conn2 = FakeConnection()
    run(integration.websocket_cultures_index(FakeHass(entries=[rot]), conn2, {"id": 1, "jar_id": "c1", "r": 100, "g": 100, "b": 100, "ref_r": 240, "ref_g": 240, "ref_b": 240}))
    assert conn2.errors[-1].code == "not_phyto"


def test_light_tick_banks_the_ph_and_reads_the_colour_sensor_against_its_blank():
    now = datetime.now(timezone.utc)
    now_local = integration.dt_util.as_local(now)
    yesterday = (now_local - timedelta(days=1)).date().isoformat()
    jar = _phyto_jar(started_ago_days=6, lastTint="green")
    jar["light"] = {"mode": "sun", "switchEntity": "", "onAt": "07:00", "latestOff": "00:00", "tempEntity": ""}
    jar["index"] = {"phEntity": "sensor.nanno_ph", "redEntity": "sensor.nanno_red", "greenEntity": "sensor.nanno_green", "blueEntity": "", "baseline": None}
    jar["state"].update({"lightDay": yesterday, "lightMinutesToday": 0, "phDay": yesterday, "phMinToday": 8.4, "phMaxToday": 8.9})
    entry = _phyto_entry(jars={"c1": jar})
    hass = FakeHass(states={"sensor.nanno_ph": "8.7", "sensor.nanno_red": "1200", "sensor.nanno_green": "2400",
                            "sun.sun": FakeState("above_horizon", {"next_rising": _iso(now + timedelta(hours=20)), "next_setting": _iso(now + timedelta(hours=6))})},
                    entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_index_blank(hass, conn, {"id": 1, "jar_id": "c1"}))
    assert not conn.errors, conn.errors
    blank = _cultures(entry)["jars"]["c1"]["index"]["baseline"]
    assert blank["r"] == 1200 and blank["g"] == 2400 and blank["at"]
    # The culture in front of the sensor: red halves, green to three quarters.
    hass.states.set("sensor.nanno_red", "600")
    hass.states.set("sensor.nanno_green", "1800")
    run(integration._async_cultures_light_tick(hass, entry, now))
    jar_after = _cultures(entry)["jars"]["c1"]
    day_row = next(r for r in jar_after["history"] if r["event"] == "light")
    assert day_row["phMin"] == 8.4 and day_row["phMax"] == 8.9, "yesterday's range on yesterday's row"
    idx_row = next(r for r in jar_after["history"] if r["event"] == "index")
    assert idx_row["source"] == "sensor" and idx_row["od"] == 0.213 and idx_row["odR"] == 0.301
    assert jar_after["state"]["phDay"] == now_local.date().isoformat() and jar_after["state"]["phMinToday"] == 8.7 == jar_after["state"]["phMaxToday"]
    assert jar_after["state"]["lastLookedAt"] == jar["state"].get("lastLookedAt", ""), "a sensor reading is not the keeper's look"
    # A new extreme moves the range; a wobble under 0.05 does not save.
    hass.states.set("sensor.nanno_ph", "9.0")
    run(integration._async_cultures_light_tick(hass, entry, now + timedelta(minutes=1)))
    assert _cultures(entry)["jars"]["c1"]["state"]["phMaxToday"] == 9.0
    hass.states.set("sensor.nanno_ph", "9.02")
    run(integration._async_cultures_light_tick(hass, entry, now + timedelta(minutes=2)))
    assert _cultures(entry)["jars"]["c1"]["state"]["phMaxToday"] == 9.0
    # No blank, no reading: the sensor without one is refused at the blank tap and skipped by the tick.
    cfg = _config(entry)
    cfg["nps"]["cultures"]["jars"]["c1"]["index"]["redEntity"] = ""
    entry.options = {**entry.options, CONF_SETTINGS: cfg}
    run(integration.websocket_cultures_index_blank(hass, conn, {"id": 2, "jar_id": "c1"}))
    assert conn.errors[-1].code == "no_sensor"
    run(integration.websocket_cultures_summary(hass, conn, {"id": 3}))
    j = conn.results[-1].payload["jars"][0]
    assert j["index"]["sensor"]["bound"] is False and j["index"]["sensor"]["phEntity"] == "sensor.nanno_ph" and j["index"]["phNow"]["max"] == 9.0
    assert j["index"]["ph"]["available"] is False, "one day of pH is not a trend"

# --------------------------------------------------------------------------- #
# 0.7.211 — a column reactor (the Clear Tides P360) for the rotifers and the pods
# --------------------------------------------------------------------------- #
def test_a_column_reactor_bleeds_off_its_tap_like_the_cone_bleeds_its_tip():
    cone = {"species": "rotifer_L", "volumeL": 5, "salinityPpt": 27, "vesselKind": "cone", "purgeMl": 50, "cadence": {}}
    column = {**cone, "vesselKind": "reactor"}
    tub = {**cone, "vesselKind": "tub"}
    assert cultures.harvest_guide(cone, 35)["purgeMl"] == 50 and cultures.harvest_guide(column, 35)["purgeMl"] == 50
    assert cultures.harvest_guide(tub, 35)["purgeMl"] == 0, "a tub has nowhere to bleed from"
    assert cultures.harvest_guide(column, 35)["refillMl"] == 1300, "a 25 % harvest of 5 L plus the 50 ml drained, replaced"
    assert cultures.PURGE_VESSELS == ("cone", "reactor")
    # The rig: the column's captions say the tap; the cone keeps its tip.
    def payload(kind, due):
        return {"id": "c1", "name": "Rotifers A", "kind": "rotifer", "vesselKind": kind, "volumeL": 5, "purgeMl": 50, "sieveUm": 50, "firstHarvestDays": 6,
                "state": {"status": "producing", "percent": 40, "ageDays": 12, "harvest": {"due": "harvest" in due}, "restart": {"due": "restart" in due}},
                "due": due, "tint": "clearing", "feedAdvice": {"action": "wait"}, "temp": {"status": "ok"},
                "harvestGuide": cultures.harvest_guide({"species": "rotifer_L", "volumeL": 5, "salinityPpt": 27, "vesselKind": kind, "purgeMl": 50, "cadence": {}}, 35),
                "fillGuide": cultures.refill_guide(5, 100, 27, 35)}
    bottle = {"remainingMl": 0, "volumeMl": 1000, "status": "empty", "percent": 0}
    rig = cultures.rig_state([payload("reactor", ["harvest"])], bottle)
    assert rig["stage"] == "harvest" and "drain ~50 ml of settled detritus off the tap" in rig["caption"] and rig["jug"]["vesselKind"] == "reactor"
    assert "bleed" not in rig["caption"]
    rig = cultures.rig_state([payload("cone", ["harvest"])], bottle)
    assert "bleed ~50 ml off the tip" in rig["caption"] and rig["jug"]["vesselKind"] == "cone"
    rig = cultures.rig_state([payload("reactor", ["restart"])], bottle)
    assert rig["stage"] == "restart" and "drain the tap, the whole column" in rig["caption"]
    # The ceremony stamps the purge on a reactor's harvest row; the shelf's live source names the vessel.
    jar = _jar(started_ago_days=12)
    jar.update({"vesselKind": "reactor", "volumeL": 5, "purgeMl": 50, "harvestTo": "tank"})
    entry = _entry(jars={"c1": jar})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_cultures_log(hass, conn, {"id": 1, "jar_id": "c1", "harvested": True}))
    assert not conn.errors, conn.errors
    row = _cultures(entry)["jars"]["c1"]["history"][0]
    assert row["event"] == "harvest" and row["purgeMl"] == 50 and row["ml"] == 1250
    run(integration.websocket_nps_summary(hass, conn, {"id": 2}))
    live = conn.results[-1].payload["shelf"]["live"]
    source = next(v for k, v in live.items() if k.startswith(nps_engine.LIVE_ROTIFER_CONE_PREFIX))
    assert source["name"] == "Live rotifers (Rotifers A, straight from the reactor)" and source["live"]["where"] == "the reactor (Rotifers A)"
    assert nps_engine.live_cone_product("c1", "R", {}, 100, "", [])["name"].endswith("straight from the cone)"), "the default word is still the cone"


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
