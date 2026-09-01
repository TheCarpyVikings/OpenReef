"""Automated NPS system — Stage A: the consumables (bottle) engine, its
normaliser, the WS ledger commands, and the food-chemical dosing hooks.

Covers: nps.py pure maths (runway forecast honesty, fail-closed expiry, low
grading), _normalise_nps_config (schema ownership, caps, junk tolerance), the
consumable_* WS handlers against the fake HA, the dosing_reset_reservoir →
bottle "transfer" debit bridge, and the food chemical joining the livefood
freshness guard.

Run standalone:  python3 tests/test_nps.py
Or with pytest:  pytest tests/
"""

from __future__ import annotations

import os
import sys
from copy import deepcopy as _deepcopy
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
import openreef as integration  # noqa: E402
from openreef import dosing, nps  # noqa: E402

from _fake_ha import FakeConnection, FakeEntry, FakeHass, run  # noqa: E402

CONF_SETTINGS = integration.CONF_SETTINGS
NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _product(**over):
    product = {
        "name": "Phyto", "brand": "AlgaeBarn", "category": "phyto",
        "bottleMl": 1000.0, "remainingMl": 500.0, "lowThresholdMl": 0.0,
        "openedAt": _iso(NOW - timedelta(days=2)), "shelfLifeDaysOpened": 28.0,
        "refrigerated": True, "stirDaily": True,
        "particleUmMin": 1.0, "particleUmMax": 10.0,
        "notes": "", "createdAt": _iso(NOW - timedelta(days=2)),
        "history": [],
    }
    product.update(over)
    return product


# --------------------------------------------------------------------------- #
# nps.py — pure maths
# --------------------------------------------------------------------------- #
def test_runway_none_without_history():
    state = nps.consumable_state(_product(), NOW)
    assert state["usageMlPerDay"] is None
    assert state["daysUntilEmpty"] is None      # no guess, ever


def test_runway_averages_over_observed_span():
    history = [
        {"at": _iso(NOW - timedelta(days=2)), "ml": 10, "kind": "dose"},
        {"at": _iso(NOW - timedelta(days=1)), "ml": 10, "kind": "pump"},
        {"at": _iso(NOW - timedelta(days=1)), "ml": 400, "kind": "refill"},  # supply, not demand
        {"at": _iso(NOW - timedelta(days=40)), "ml": 999, "kind": "dose"},   # outside window
    ]
    state = nps.consumable_state(_product(history=history), NOW)
    # 20 ml over an observed 2-day span = 10 ml/day; 500 remaining → 50 days.
    assert state["usageMlPerDay"] == 10.0
    assert state["daysUntilEmpty"] == 50.0


def test_transfer_counts_as_demand():
    history = [{"at": _iso(NOW - timedelta(hours=12)), "ml": 250, "kind": "transfer"}]
    assert nps.usage_ml_per_day(_product(history=history), NOW) == 250.0


def test_low_auto_threshold_is_ten_percent():
    assert nps.consumable_state(_product(remainingMl=99), NOW)["low"] is True
    assert nps.consumable_state(_product(remainingMl=101), NOW)["low"] is False
    # explicit threshold wins over the auto 10%
    state = nps.consumable_state(_product(remainingMl=180, lowThresholdMl=200), NOW)
    assert state["low"] is True


def test_expiry_fail_closed_and_shelf_stable():
    assert nps.expiry_state(_product(shelfLifeDaysOpened=0), NOW)["status"] == "fresh"
    assert nps.expiry_state(_product(openedAt=""), NOW)["status"] == "expired"  # unknown age
    assert nps.expiry_state(_product(openedAt=_iso(NOW - timedelta(days=27))), NOW)["status"] == "aging"
    assert nps.expiry_state(_product(openedAt=_iso(NOW - timedelta(days=29))), NOW)["status"] == "expired"


def test_shelf_summary_counts():
    products = {
        "ok": _product(),
        "low": _product(remainingMl=50),
        "old": _product(openedAt=_iso(NOW - timedelta(days=40))),
        "junk": "not-a-dict",
    }
    shelf = nps.shelf_summary(products, NOW)
    assert shelf["count"] == 3
    assert shelf["lowCount"] == 1
    assert shelf["expiredCount"] == 1


# --------------------------------------------------------------------------- #
# Normaliser — schema ownership
# --------------------------------------------------------------------------- #
def test_normalise_defaults():
    config = integration._normalise_core_config({})
    assert config["nps"]["enabled"] is False
    assert config["nps"]["feedExchange"]["enabled"] is False
    assert config["consumables"] == {"products": {}}


def test_normalise_product_clamps():
    config = integration._normalise_core_config({
        "consumables": {"products": {
            "phyto": {
                "name": "Phyto", "category": "not-a-category",
                "bottleMl": 1000, "remainingMl": 5000,          # over-full → clamped
                "history": [
                    {"at": "x", "ml": 5, "kind": "dose"},
                    {"at": "x", "ml": 5, "kind": "nonsense"},   # kind coerced to dose
                    "junk",
                ],
            },
            "junk": "not-a-dict",
        }},
    })
    products = config["consumables"]["products"]
    assert set(products) == {"phyto"}
    phyto = products["phyto"]
    assert phyto["category"] == "other"
    assert phyto["remainingMl"] == 1000
    assert [h["kind"] for h in phyto["history"]] == ["dose", "dose"]


def test_normalise_product_cap():
    raw = {str(i): {"name": f"P{i}"} for i in range(80)}
    config = integration._normalise_core_config({"consumables": {"products": raw}})
    assert len(config["consumables"]["products"]) == integration.CONSUMABLES_MAX_PRODUCTS


def test_food_chemical_and_bridge_fields_survive():
    config = integration._normalise_core_config({
        "dosing": {"channels": {
            "phyto_pump": {
                "name": "Phyto", "chemical": "food",
                "reservoir": {"volumeMl": 500, "productId": "phyto", "productIsBottle": True},
            },
        }},
    })
    channel = config["dosing"]["channels"]["phyto_pump"]
    assert channel["chemical"] == "food"                       # not coerced to "other"
    assert channel["reservoir"]["productId"] == "phyto"
    assert channel["reservoir"]["productIsBottle"] is True
    assert channel["reservoir"]["shelfLifeDays"] == 0          # shelf-stable by default


def test_channel_cap_is_32():
    raw = {f"ch{i}": {"name": f"C{i}", "chemical": "food"} for i in range(40)}
    config = integration._normalise_core_config({"dosing": {"channels": raw}})
    assert len(config["dosing"]["channels"]) == 32


# --------------------------------------------------------------------------- #
# Freshness guard — food joins livefood (opt-in via shelfLifeDays)
# --------------------------------------------------------------------------- #
def test_food_freshness_guard_opt_in():
    base = {
        "enabled": True, "chemical": "food",
        "schedule": {"enabled": True, "mlPerDay": 10, "mode": "doses", "dosesPerDay": 4},
        "guards": {}, "state": {},
        "driver": {"type": "openreef_esphome_stepper", "entities": {"reservoirLowSensor": "b.low"}},
    }
    stale = dict(base, reservoir={"volumeMl": 500, "remainingMl": 400,
                                  "shelfLifeDays": 2, "mixedAt": ""})
    codes = [r["code"] for r in dosing.guard_reasons(stale, {}, 720, False, NOW)]
    assert "stale_food" in codes                                # fail-closed once opted in

    shelf_stable = dict(base, reservoir={"volumeMl": 500, "remainingMl": 400,
                                         "shelfLifeDays": 0, "mixedAt": ""})
    codes = [r["code"] for r in dosing.guard_reasons(shelf_stable, {}, 720, False, NOW)]
    assert "stale_food" not in codes                            # 0 = never expires


# --------------------------------------------------------------------------- #
# WS handlers — ledger operations against the fake HA
# --------------------------------------------------------------------------- #
def _entry(products=None, channels=None):
    cfg = {
        "nps": {"enabled": True},
        "consumables": {"products": products or {}},
    }
    if channels:
        cfg["dosing"] = {"channels": channels}
    return FakeEntry(options={CONF_SETTINGS: cfg})


def _saved_products(entry):
    return entry.options[CONF_SETTINGS]["consumables"]["products"]


def test_ws_log_dose_decrements_and_logs():
    entry = _entry({"phyto": _product()})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_consumable_log_dose(
        hass, conn, {"id": 1, "product_id": "phyto", "ml": 25}))
    assert not conn.errors
    saved = _saved_products(entry)["phyto"]
    assert saved["remainingMl"] == 475.0
    assert saved["history"][-1]["kind"] == "dose"
    assert saved["history"][-1]["ml"] == 25


def test_ws_log_dose_unknown_product_errors():
    entry = _entry({})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_consumable_log_dose(
        hass, conn, {"id": 1, "product_id": "ghost", "ml": 5}))
    assert conn.error_codes == ["unknown_product"]


def test_ws_refill_new_bottle_restarts_expiry_clock():
    stale_open = _iso(NOW - timedelta(days=40))
    entry = _entry({"phyto": _product(remainingMl=10, openedAt=stale_open)})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_consumable_refill(
        hass, conn, {"id": 1, "product_id": "phyto"}))
    saved = _saved_products(entry)["phyto"]
    assert saved["remainingMl"] == 1000.0
    assert saved["openedAt"] != stale_open                      # clock restarted
    assert saved["history"][-1]["kind"] == "refill"


def test_ws_refill_top_up_keeps_opened_clock_and_clamps():
    opened = _iso(NOW - timedelta(days=3))
    entry = _entry({"phyto": _product(remainingMl=900, openedAt=opened)})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_consumable_refill(
        hass, conn, {"id": 1, "product_id": "phyto", "ml": 500}))
    saved = _saved_products(entry)["phyto"]
    assert saved["remainingMl"] == 1000.0                       # clamped to the bottle
    assert saved["openedAt"] == opened                          # same bottle, same clock


def test_ws_delete_removes_product():
    entry = _entry({"phyto": _product()})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_consumable_delete(
        hass, conn, {"id": 1, "product_id": "phyto"}))
    assert _saved_products(entry) == {}


def test_ws_nps_summary_shape():
    entry = _entry({"phyto": _product(remainingMl=50)})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_summary(hass, conn, {"id": 1}))
    assert not conn.errors
    payload = conn.results[-1].payload
    assert payload["enabled"] is True
    assert payload["shelf"]["lowCount"] == 1
    assert payload["library"]                                    # seeded presets present
    assert "phyto" in payload["categories"]


def test_reset_reservoir_debits_linked_bottle_as_transfer():
    channels = {
        "phyto_pump": {
            "name": "Phyto pump", "chemical": "food", "enabled": True,
            "reservoir": {"volumeMl": 400, "remainingMl": 100,
                          "productId": "phyto", "productIsBottle": False},
        },
    }
    entry = _entry({"phyto": _product(remainingMl=800)}, channels=channels)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_dosing_reset_reservoir(
        hass, conn, {"id": 1, "channel_id": "phyto_pump"}))
    assert not conn.errors
    saved = _saved_products(entry)["phyto"]
    # 400 ml reservoir refilled from 100 ml remaining = 300 ml poured from the bottle.
    assert saved["remainingMl"] == 500.0
    assert saved["history"][-1]["kind"] == "transfer"
    assert saved["history"][-1]["ml"] == 300


def test_reset_reservoir_bottle_is_reservoir_not_double_debited():
    channels = {
        "phyto_pump": {
            "name": "Phyto pump", "chemical": "food", "enabled": True,
            "reservoir": {"volumeMl": 400, "remainingMl": 100,
                          "productId": "phyto", "productIsBottle": True},
        },
    }
    entry = _entry({"phyto": _product(remainingMl=800)}, channels=channels)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_dosing_reset_reservoir(
        hass, conn, {"id": 1, "channel_id": "phyto_pump"}))
    # Doses debit the bottle live in that mode — a refill must not also debit it.
    assert _saved_products(entry)["phyto"]["remainingMl"] == 800.0


# --------------------------------------------------------------------------- #
# Stage B — feed-exchange engine maths
# --------------------------------------------------------------------------- #
def test_feed_exchange_owed_includes_chaser():
    # 30 ml brine + 200 ml line-flush chaser: BOTH entered the tank, both owed.
    assert nps.feed_exchange_owed(0, 30, 200, 2000) == (230.0, 0.0)


def test_feed_exchange_owed_cap_reports_dropped():
    owed, dropped = nps.feed_exchange_owed(1900, 30, 200, 2000)
    assert owed == 2000.0
    assert dropped == 130.0


def test_feed_exchange_batch_rules():
    assert nps.feed_exchange_batch(100, 150, 2000) == 0.0        # below the minimum
    assert nps.feed_exchange_batch(500, 150, 2000) == 500.0      # drain it all
    assert nps.feed_exchange_batch(5000, 150, 2000) == 2000.0    # per-run cap
    assert nps.feed_exchange_batch(500, 150, 2000, waste_headroom_ml=300) == 300.0
    assert nps.feed_exchange_batch(500, 150, 2000, waste_headroom_ml=100) == 0.0


def test_hatch_prime_state():
    assert nps.hatch_prime_state(_iso(NOW - timedelta(hours=6)), NOW)["status"] == "prime"
    fading = nps.hatch_prime_state(_iso(NOW - timedelta(hours=30)), NOW)
    assert fading["status"] == "fading"
    assert fading["primeLeftHours"] == 0.0
    assert fading["enriched"] is False and fading["window"] == "yolk"
    assert nps.hatch_prime_state("", NOW)["status"] == "unknown"


def test_an_enriched_batch_is_gut_loaded_not_depleted():
    """Reece, 0.7.89: the yolk clock condemned the batch the app had just told
    him to gut-load. Loaded 22 h ago, soak finished 2 h ago -> fed, not fading."""
    loaded = _iso(NOW - timedelta(hours=22))
    soaked = _iso(NOW - timedelta(hours=2))
    st = nps.hatch_prime_state(loaded, NOW, soaked)
    assert st["status"] == "gutloaded"          # NOT "fading"
    assert st["enriched"] is True and st["window"] == "boost"
    assert st["ageHours"] == 22.0               # the load age is still reported
    assert st["primeLeftHours"] == 10.0         # 12 h room hold, 2 h spent
    assert st["windowHours"] == nps.ENRICH_SHELF_H_ROOM


def test_the_boost_has_its_own_ending_and_the_fridge_extends_it():
    loaded = _iso(NOW - timedelta(hours=40))
    soaked = _iso(NOW - timedelta(hours=20))
    warm = nps.hatch_prime_state(loaded, NOW, soaked)
    assert warm["status"] == "boost_fading"     # 20 h > 12 h room hold
    assert warm["primeLeftHours"] == 0.0
    assert warm["soakAgeHours"] == 20.0
    cold = nps.hatch_prime_state(loaded, NOW, soaked, refrigerated=True)
    assert cold["status"] == "gutloaded"        # <10 C holds the HUFAs
    assert cold["primeLeftHours"] == 28.0
    # No soak stamp = never enriched: the yolk clock still rules.
    assert nps.hatch_prime_state(loaded, NOW, "")["status"] == "fading"


def test_instar_two_delay_follows_the_temperature():
    warm = nps.instar_two_delay_hours(28.0)
    assert warm["available"] is True and warm["hours"] == nps.INSTAR_II_HOURS
    cool = nps.instar_two_delay_hours(26.4)      # Reece's bench
    assert cool["hours"] > warm["hours"]
    assert nps.instar_two_delay_hours(2.0)["hours"] <= nps.INSTAR_II_DELAY_MAX_H
    assert nps.instar_two_delay_hours(None)["available"] is False


def test_normalise_feed_exchange():
    config = integration._normalise_core_config({})
    fx = config["nps"]["feedExchange"]
    assert fx["enabled"] is False
    assert fx["minDrainMl"] == 150
    assert fx["maxOwedMl"] == 2000
    assert fx["state"]["owedMl"] == 0
    clamped = integration._normalise_core_config({
        "nps": {"feedExchange": {"minDrainMl": 5, "maxOwedMl": 999999,
                                 "state": {"owedMl": -50}}},
    })["nps"]["feedExchange"]
    assert clamped["minDrainMl"] == 10
    assert clamped["maxOwedMl"] == 20000
    assert clamped["state"]["owedMl"] == 0


# --------------------------------------------------------------------------- #
# Stage B — orchestration against the fake HA
# --------------------------------------------------------------------------- #
def _fx_entry(owed=500.0, fx_over=None, awc_over=None):
    awc = {
        "enabled": True,
        "pumps": {
            "drain": {"switchEntity": "switch.drain", "mlPerS": 10.0,
                      "exchangeFactor": 1.0, "spinUpMl": 0.0},
            "fill": {"switchEntity": "switch.fill", "mlPerS": 10.0},
        },
        "reservoirs": {"fresh": {"capacityLitres": 25},
                       "waste": {"capacityLitres": 25, "filledMl": 0}},
        "safety": {"floodMissingAcknowledged": True},
        "state": {"status": "idle"},
    }
    for key, value in (awc_over or {}).items():
        if isinstance(value, dict) and isinstance(awc.get(key), dict):
            awc[key].update(value)
        else:
            awc[key] = value
    fx = {"enabled": True, "channelId": "brine", "minDrainMl": 150,
          "maxOwedMl": 2000, "state": {"owedMl": owed}}
    fx.update(fx_over or {})
    cfg = {
        "nps": {"enabled": True, "feedExchange": fx},
        "automaticWaterChange": awc,
        "consumables": {"products": {}},
    }
    return FakeEntry(options={CONF_SETTINGS: cfg})


def _fx_state(entry):
    return entry.options[CONF_SETTINGS]["nps"]["feedExchange"]["state"]


def test_accrue_banks_dose_plus_chaser_and_credits_fill_ledger():
    entry = _fx_entry(owed=0.0)
    hass = FakeHass(entries=[entry])
    run(integration._async_nps_feed_exchange_accrue(hass, entry, "brine", 30.0, 200.0))
    assert _fx_state(entry)["owedMl"] == 230.0
    ledger = entry.options[CONF_SETTINGS]["automaticWaterChange"]["ledger"]
    assert abs(ledger["cumulativeFilledL"] - 0.03) < 1e-9   # the dose; chaser credits separately


def test_accrue_ignores_disabled_and_other_channels():
    entry = _fx_entry(owed=0.0)
    hass = FakeHass(entries=[entry])
    run(integration._async_nps_feed_exchange_accrue(hass, entry, "kalk_pump", 30.0, 0.0))
    assert _fx_state(entry)["owedMl"] == 0.0
    entry2 = _fx_entry(owed=0.0, fx_over={"enabled": False})
    hass2 = FakeHass(entries=[entry2])
    run(integration._async_nps_feed_exchange_accrue(hass2, entry2, "brine", 30.0, 0.0))
    assert _fx_state(entry2)["owedMl"] == 0.0


def test_accrue_cap_records_dropped():
    entry = _fx_entry(owed=1900.0)
    hass = FakeHass(entries=[entry])
    run(integration._async_nps_feed_exchange_accrue(hass, entry, "brine", 30.0, 200.0))
    state = _fx_state(entry)
    assert state["owedMl"] == 2000.0
    assert state["droppedMl"] == 130.0


def test_matched_drain_full_cycle():
    from _fake_ha import install_scheduler
    entry = _fx_entry(owed=500.0)
    hass = FakeHass(states={"switch.drain": "off", "switch.fill": "off"}, entries=[entry])
    scheduler = install_scheduler(integration)
    now_local = datetime(2026, 8, 13, 14, 0, 0)

    async def scenario():
        started = await integration._async_nps_matched_drain_maybe(hass, entry, now_local)
        assert started is True
        assert hass.states.get("switch.drain").state == "on"
        state = _fx_state(entry)
        assert state["drainTargetMl"] == 500.0
        assert state["drainStartedAt"]
        # Fire the stop timer: books settle, pump stops.
        assert await scheduler.fire_all() == 1
        assert hass.states.get("switch.drain").state == "off"
        state = _fx_state(entry)
        assert state["owedMl"] == 0.0
        assert state["lastDrainMl"] == 500.0
        assert state["drainStartedAt"] == ""
        awc = entry.options[CONF_SETTINGS]["automaticWaterChange"]
        assert awc["reservoirs"]["waste"]["filledMl"] == 500.0
        assert abs(awc["ledger"]["cumulativeDrainedL"] - 0.5) < 1e-9

    run(scenario())


def test_matched_drain_blocked_by_leak_records_reason():
    entry = _fx_entry(owed=500.0, awc_over={"safety": {"leakEntity": "binary_sensor.leak"}})
    hass = FakeHass(states={"switch.drain": "off", "binary_sensor.leak": "on"}, entries=[entry])
    started = run(integration._async_nps_matched_drain_maybe(
        hass, entry, datetime(2026, 8, 13, 14, 0, 0)))
    assert started is False
    assert hass.states.get("switch.drain").state == "off"
    assert _fx_state(entry)["lastBlockedReason"] == "leak"


def test_matched_drain_waits_below_minimum_and_when_busy():
    entry = _fx_entry(owed=100.0)   # below the 150 ml minimum
    hass = FakeHass(states={"switch.drain": "off"}, entries=[entry])
    assert run(integration._async_nps_matched_drain_maybe(
        hass, entry, datetime(2026, 8, 13, 14, 0, 0))) is False
    busy = _fx_entry(owed=500.0, awc_over={"state": {"status": "draining"}})
    hass2 = FakeHass(states={"switch.drain": "off"}, entries=[busy])
    assert run(integration._async_nps_matched_drain_maybe(
        hass2, busy, datetime(2026, 8, 13, 14, 0, 0))) is False
    assert hass2.states.get("switch.drain").state == "off"


def test_orphaned_drain_recovery_credits_elapsed_partial():
    entry = _fx_entry(owed=500.0)
    started_at = datetime.now(timezone.utc) - timedelta(seconds=30)
    _fx_state(entry).update({
        "drainStartedAt": started_at.isoformat(),
        "drainEndsAt": (started_at + timedelta(seconds=50)).isoformat(),
        "drainTargetMl": 500.0,
    })
    hass = FakeHass(states={"switch.drain": "on"}, entries=[entry])
    run(integration._async_nps_recover_orphaned_drain(hass, entry))
    assert hass.states.get("switch.drain").state == "off"
    state = _fx_state(entry)
    # ~30 s at 10 ml/s ≈ 300 ml credited; the rest stays owed.
    assert abs(state["lastDrainMl"] - 300.0) < 5.0
    assert abs(state["owedMl"] - 200.0) < 5.0
    assert state["drainStartedAt"] == ""
    waste = entry.options[CONF_SETTINGS]["automaticWaterChange"]["reservoirs"]["waste"]
    assert abs(waste["filledMl"] - 300.0) < 5.0


def test_awc_start_blocked_while_matched_drain_runs():
    from _fake_ha import install_scheduler
    entry = _fx_entry(owed=500.0)
    hass = FakeHass(states={"switch.drain": "off", "switch.fill": "off"}, entries=[entry])
    scheduler = install_scheduler(integration)

    async def scenario():
        assert await integration._async_nps_matched_drain_maybe(
            hass, entry, datetime(2026, 8, 13, 14, 0, 0)) is True
        started, reasons = await integration._async_awc_start(
            hass, entry, 2.0, "batch_sequential", True, None)
        assert started is False
        assert any(r["code"] == "busy" for r in reasons)
        await scheduler.fire_all()   # let the drain finish cleanly

    run(scenario())


# --------------------------------------------------------------------------- #
# Stage C — feed truce (UV/ozone/skimmer pause after food doses)
# --------------------------------------------------------------------------- #
def _truce_entry(enabled=True, equipment=None, truce_state=None):
    cfg = {
        "nps": {
            "enabled": True,
            "truce": {"enabled": enabled, "uvOffMinutes": 120,
                      "ozoneOffMinutes": 120, "skimmerOffMinutes": 45,
                      "state": truce_state or {}},
        },
        "equipment": equipment or {
            "uv1": {"armed": True, "type": "uv", "switch_entity_id": "switch.uv"},
            "skim1": {"armed": True, "type": "skimmer", "switch_entity_id": "switch.skimmer"},
            "uv_unarmed": {"armed": False, "type": "uv", "switch_entity_id": "switch.uv2"},
        },
    }
    return FakeEntry(options={CONF_SETTINGS: cfg})


def _truce_state(entry):
    return entry.options[CONF_SETTINGS]["nps"]["truce"]["state"]


def test_truce_engage_pauses_armed_on_equipment_only():
    entry = _truce_entry()
    hass = FakeHass(states={"switch.uv": "on", "switch.uv2": "on", "switch.skimmer": "off"},
                    entries=[entry])
    run(integration._async_nps_truce_engage(hass, entry))
    assert hass.states.get("switch.uv").state == "off"
    assert hass.states.get("switch.uv2").state == "on"        # unarmed: untouched
    state = _truce_state(entry)
    assert state["uv"]["turnedOff"] == ["switch.uv"]
    assert state["uv"]["restoreAt"]
    # The skimmer was already off (keeper's choice) — never claimed.
    assert state.get("skimmer", {}).get("turnedOff", []) == []


def test_truce_engage_noop_when_disabled():
    entry = _truce_entry(enabled=False)
    hass = FakeHass(states={"switch.uv": "on"}, entries=[entry])
    run(integration._async_nps_truce_engage(hass, entry))
    assert hass.states.get("switch.uv").state == "on"


def test_truce_tick_restores_when_due_and_only_claimed_entities():
    past = _iso(datetime.now(timezone.utc) - timedelta(minutes=1))
    entry = _truce_entry(truce_state={
        "uv": {"restoreAt": past, "turnedOff": ["switch.uv"]},
    })
    hass = FakeHass(states={"switch.uv": "off", "switch.skimmer": "off"}, entries=[entry])
    run(integration._async_nps_truce_tick(hass, entry))
    assert hass.states.get("switch.uv").state == "on"
    assert hass.states.get("switch.skimmer").state == "off"   # never claimed, never touched
    state = _truce_state(entry)
    assert state["uv"]["turnedOff"] == []
    assert state["uv"]["restoreAt"] == ""


def test_truce_tick_waits_until_due_but_restores_if_disabled():
    future = _iso(datetime.now(timezone.utc) + timedelta(minutes=30))
    entry = _truce_entry(truce_state={
        "uv": {"restoreAt": future, "turnedOff": ["switch.uv"]},
    })
    hass = FakeHass(states={"switch.uv": "off"}, entries=[entry])
    run(integration._async_nps_truce_tick(hass, entry))
    assert hass.states.get("switch.uv").state == "off"        # window still open
    disabled = _truce_entry(enabled=False, truce_state={
        "uv": {"restoreAt": future, "turnedOff": ["switch.uv"]},
    })
    hass2 = FakeHass(states={"switch.uv": "off"}, entries=[disabled])
    run(integration._async_nps_truce_tick(hass2, disabled))
    assert hass2.states.get("switch.uv").state == "on"        # disabled mid-hold ⇒ restore now


def test_truce_repeat_dose_extends_window():
    entry = _truce_entry(truce_state={
        "uv": {"restoreAt": _iso(datetime.now(timezone.utc) + timedelta(minutes=5)),
               "turnedOff": ["switch.uv"]},
    })
    hass = FakeHass(states={"switch.uv": "off"}, entries=[entry])
    run(integration._async_nps_truce_engage(hass, entry))
    # switch.uv is off so nothing new is claimed, but a fresh ON dose elsewhere
    # in the profile would extend; simulate the extend path with the uv back on:
    hass.states.set("switch.uv", "on")
    before = _truce_state(entry)["uv"]["restoreAt"]
    run(integration._async_nps_truce_engage(hass, entry))
    after = _truce_state(entry)["uv"]["restoreAt"]
    assert after > before                                      # pushed out to now+120 min


def test_uv_profile_alias_normalises():
    assert integration._normalise_equipment_profile("uv sterilizer") == "uv"
    assert integration._normalise_equipment_profile("Ozone") == "ozone"


# --------------------------------------------------------------------------- #
# Stage C — ha_switch_timed generic pump driver
# --------------------------------------------------------------------------- #
def _ha_channel(**over):
    ch = {
        "name": "Phyto pump", "chemical": "food", "enabled": True,
        "driver": {"type": "ha_switch_timed", "entities": {"powerSwitch": "switch.pump"}},
        "schedule": {"enabled": True, "mlPerDay": 20, "mode": "doses", "dosesPerDay": 4,
                     "windowStart": "00:00", "windowEnd": "00:00",
                     "night": {"enabled": False}},
        "guards": {},
        "calibration": {"mlPerS": 1.0, "spinUpMl": 0.0},
        "reservoir": {"volumeMl": 1000, "remainingMl": 500, "shelfLifeDays": 0},
        "state": {}, "wear": {},
    }
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(ch.get(key), dict):
            ch[key].update(value)
        else:
            ch[key] = value
    return ch


def _ha_entry(channel=None, products=None):
    cfg = {
        "nps": {"enabled": True},
        "consumables": {"products": products or {}},
        "dosing": {"enabled": True, "channels": {"phyto_pump": channel or _ha_channel()}},
    }
    return FakeEntry(options={CONF_SETTINGS: cfg})


def _saved_channel(entry):
    return entry.options[CONF_SETTINGS]["dosing"]["channels"]["phyto_pump"]


def test_ha_timed_guard_calibration_is_flow_based():
    ch = _ha_channel()
    codes = [r["code"] for r in dosing.guard_reasons(ch, {}, 720, False, NOW)]
    assert "not_calibrated" not in codes
    ch_uncal = _ha_channel(calibration={"mlPerS": 0})
    codes = [r["code"] for r in dosing.guard_reasons(ch_uncal, {}, 720, False, NOW)]
    assert "not_calibrated" in codes


def test_ha_executor_full_dose_cycle():
    from _fake_ha import install_scheduler
    entry = _ha_entry()
    hass = FakeHass(states={"switch.pump": "off"}, entries=[entry])
    scheduler = install_scheduler(integration)
    now_utc = datetime.now(timezone.utc)
    now_local = datetime(2026, 8, 13, 12, 0, 0)

    async def scenario():
        config = integration._config_from_entry(entry)
        changed = await integration._async_dosing_ha_executor(
            hass, entry, config, now_utc, now_local, None)
        assert changed is True
        assert hass.states.get("switch.pump").state == "on"
        # 20 ml/day over 4 doses = 5 ml per dose at 1 ml/s = 5 s run
        channel = config["dosing"]["channels"]["phyto_pump"]
        assert channel["state"]["haRunTargetMl"] == 5.0
        # stop timer settles the books
        assert await scheduler.fire_all() == 1
        assert hass.states.get("switch.pump").state == "off"
        saved = _saved_channel(entry)
        assert saved["state"]["haDosedTodayMl"] == 5.0
        assert saved["state"]["lastDoseAt"]
        assert saved["reservoir"]["remainingMl"] == 495.0
        assert saved["wear"]["doseCount"] == 1

    run(scenario())


def test_ha_executor_paces_by_interval_and_daily_plan():
    from _fake_ha import install_scheduler
    entry = _ha_entry(_ha_channel(state={
        "haDoseDate": datetime(2026, 8, 13).strftime("%Y-%m-%d"),
        "haDosedTodayMl": 0.0,
        "lastDoseAt": _iso(datetime.now(timezone.utc) - timedelta(minutes=2)),
    }))
    hass = FakeHass(states={"switch.pump": "off"}, entries=[entry])
    install_scheduler(integration)

    async def scenario():
        config = integration._config_from_entry(entry)
        # last dose 2 min ago, interval is 1440/4 = 360 min — must wait
        await integration._async_dosing_ha_executor(
            hass, entry, config, datetime.now(timezone.utc),
            datetime(2026, 8, 13, 12, 0, 0), None)
        assert hass.states.get("switch.pump").state == "off"
        # daily plan met — never a catch-up bolus
        config["dosing"]["channels"]["phyto_pump"]["state"].update(
            {"haDosedTodayMl": 20.0, "lastDoseAt": ""})
        await integration._async_dosing_ha_executor(
            hass, entry, config, datetime.now(timezone.utc),
            datetime(2026, 8, 13, 12, 0, 0), None)
        assert hass.states.get("switch.pump").state == "off"

    run(scenario())


def test_ha_executor_refuses_kalk_and_stale_food():
    from _fake_ha import install_scheduler
    kalk = _ha_channel(chemical="kalk")
    entry = _ha_entry(kalk)
    hass = FakeHass(states={"switch.pump": "off"}, entries=[entry])
    install_scheduler(integration)

    async def scenario():
        config = integration._config_from_entry(entry)
        await integration._async_dosing_ha_executor(
            hass, entry, config, datetime.now(timezone.utc),
            datetime(2026, 8, 13, 12, 0, 0), None)
        assert hass.states.get("switch.pump").state == "off"   # kalk refused outright

    run(scenario())
    # stale food (shelf life set, no mixedAt) — the guard chain is enforcement
    stale = _ha_channel(reservoir={"volumeMl": 1000, "remainingMl": 500,
                                   "shelfLifeDays": 1, "mixedAt": ""})
    entry2 = _ha_entry(stale)
    hass2 = FakeHass(states={"switch.pump": "off"}, entries=[entry2])

    async def scenario2():
        config = integration._config_from_entry(entry2)
        await integration._async_dosing_ha_executor(
            hass2, entry2, config, datetime.now(timezone.utc),
            datetime(2026, 8, 13, 12, 0, 0), None)
        assert hass2.states.get("switch.pump").state == "off"

    run(scenario2())


def test_ha_recover_orphan_credits_honest_overrun():
    entry = _ha_entry(_ha_channel(state={
        "haRunStartedAt": _iso(datetime.now(timezone.utc) - timedelta(seconds=60)),
        "haRunEndsAt": _iso(datetime.now(timezone.utc) - timedelta(seconds=55)),
        "haRunTargetMl": 5.0,
        "haDoseDate": datetime.now().strftime("%Y-%m-%d"),
        "haDosedTodayMl": 0.0,
    }))
    hass = FakeHass(states={"switch.pump": "on"}, entries=[entry])
    run(integration._async_dosing_ha_recover(hass, entry))
    assert hass.states.get("switch.pump").state == "off"
    saved = _saved_channel(entry)
    # pump really ran ~60 s at 1 ml/s → ~60 ml credited, NOT the 5 ml target
    assert abs(saved["state"]["haDosedTodayMl"] - 60.0) < 3.0
    assert saved["state"]["haRunEndsAt"] == ""
    assert any(e.get("kind") == "warn" for e in saved.get("events", []))


def test_ha_dose_decrements_linked_bottle():
    from _fake_ha import install_scheduler
    channel = _ha_channel(reservoir={"volumeMl": 1000, "remainingMl": 500,
                                     "shelfLifeDays": 0, "productId": "phyto",
                                     "productIsBottle": True})
    entry = _ha_entry(channel, products={"phyto": _product(remainingMl=400)})
    hass = FakeHass(states={"switch.pump": "off"}, entries=[entry])
    scheduler = install_scheduler(integration)

    async def scenario():
        config = integration._config_from_entry(entry)
        assert await integration._async_dosing_ha_executor(
            hass, entry, config, datetime.now(timezone.utc),
            datetime(2026, 8, 13, 12, 0, 0), None)
        await scheduler.fire_all()
        products = entry.options[CONF_SETTINGS]["consumables"]["products"]
        assert products["phyto"]["remainingMl"] == 395.0       # bottle IS the reservoir
        assert products["phyto"]["history"][-1]["kind"] == "pump"

    run(scenario())


# --------------------------------------------------------------------------- #
# Stage D — species plans + nutrient budget
# --------------------------------------------------------------------------- #
def test_species_plan_gap_detection():
    # Dendronephthya with nothing on the shelf → a phyto gap.
    plan = nps.compile_feed_plan(["dendronephthya"], {}, {})
    assert len(plan["gaps"]) == 1
    assert "phyto" in plan["gaps"][0]
    # A phyto product in the particle window closes the gap.
    plan = nps.compile_feed_plan(
        ["dendronephthya"],
        {"phyto": _product(particleUmMin=1, particleUmMax=10)}, {})
    assert plan["gaps"] == []


def test_species_plan_pump_suggestion_and_night():
    products = {"brine": _product(name="Baby brine", category="zooLive",
                                  particleUmMin=400, particleUmMax=500)}
    channels = {"brine_pump": {
        "name": "Brine pump", "chemical": "livefood",
        "reservoir": {"productId": "brine"},
    }}
    plan = nps.compile_feed_plan(["chili"], products, channels)
    assert len(plan["suggestions"]) == 1
    sug = plan["suggestions"][0]
    assert sug["channelId"] == "brine_pump"
    assert sug["night"] is True                      # chili is strictly nocturnal
    assert sug["dosesPerDay"] == 1


def test_species_plan_particle_mismatch_warns():
    products = {"mysis": _product(name="Mysis blend", category="zooPrepared",
                                  particleUmMin=1000, particleUmMax=3000)}
    channels = {"p1": {"name": "Blend pump", "chemical": "food",
                       "reservoir": {"productId": "mysis"}}}
    plan = nps.compile_feed_plan(["gorgonian_easy"], products, channels)
    assert any("particle" in w for w in plan["warnings"])
    # Difficulty-5 honesty banner
    plan5 = nps.compile_feed_plan(["dendronephthya"],
                                  {"phyto": _product(particleUmMin=1, particleUmMax=10)}, {})
    assert any("expert" in w.lower() for w in plan5["warnings"])


def test_nutrient_budget_math_and_verdicts():
    assert nps.nutrient_budget({}, NOW, 100, 2.0) == {"available": False}
    history = [{"at": _iso(NOW - timedelta(days=1)), "ml": 10, "kind": "dose"}]
    phyto = _product(history=history)                 # 10 ml/day phyto
    budget = nps.nutrient_budget({"phyto": phyto}, NOW, 100, 2.0)
    assert budget["available"] is True
    assert budget["feedingMlPerDay"] == 10.0
    # 10 ml × 0.4 mgN/ml × 4.43 / 100 L = 0.177 ppm NO3/day; ÷ 2% daily = 8.86
    assert abs(budget["no3PpmPerDay"] - 0.18) < 0.01
    assert abs(budget["steadyNo3"] - 8.9) < 0.2
    assert budget["verdict"] == "balanced"
    assert nps.nutrient_budget({"phyto": phyto}, NOW, 100, 20.0)["verdict"] == "clean"
    assert nps.nutrient_budget({"phyto": phyto}, NOW, 100, 0.1)["verdict"] == "heavy"
    assert nps.nutrient_budget({"phyto": phyto}, NOW, 100, 0.0)["verdict"] == "no_export"


def test_normalise_species_whitelist():
    config = integration._normalise_core_config({
        "nps": {"species": ["chili", "made_up", "chili", "dendronephthya"]},
    })
    assert config["nps"]["species"] == ["chili", "dendronephthya"]


# --------------------------------------------------------------------------- #
# Hatchery (v1) — the incubation clock
# --------------------------------------------------------------------------- #
def test_hatch_state_lifecycle():
    assert nps.hatch_state("", 24, NOW)["status"] == "none"
    mid = nps.hatch_state(_iso(NOW - timedelta(hours=15)), 24, NOW)
    assert mid["status"] == "incubating"
    assert mid["hoursLeft"] == 9.0
    assert mid["percent"] == 62
    assert nps.hatch_state(_iso(NOW - timedelta(hours=25)), 24, NOW)["status"] == "ready"
    # Past the grace window the yolk clock nags.
    assert nps.hatch_state(_iso(NOW - timedelta(hours=40)), 24, NOW)["status"] == "overdue"


def test_next_hatch_suggestion_freshness_timed():
    # Loaded 4 h ago, 48 h shelf, no reservoir data, 24 h eggs: the new batch
    # must be ready by loaded+48 -> start 48-4-25 = 19 h from now.
    s = nps.next_hatch_suggestion(NOW, 24, _iso(NOW - timedelta(hours=4)), 48, None, None, "")
    assert s["status"] == "wait" and s["driver"] == "freshness"
    assert s["hoursUntil"] == 19.0
    assert not s["overlap"]


def test_next_hatch_suggestion_depletion_wins():
    # 100 ml left at 60 ml/day = dry in 40 h, sooner than the 46 h of freshness
    # left -> depletion drives the clock: start at 40 - 25 = 15 h.
    s = nps.next_hatch_suggestion(NOW, 24, _iso(NOW - timedelta(hours=2)), 48, 100, 60, "")
    assert s["status"] == "wait" and s["driver"] == "depletion"
    assert s["hoursUntil"] == 15.0


def test_next_hatch_suggestion_overlap_says_start_now():
    # 36 h eggs but brine only keeps 24 h: batches must overlap, waiting is
    # never the answer.
    s = nps.next_hatch_suggestion(NOW, 36, _iso(NOW - timedelta(hours=2)), 24, None, None, "")
    assert s["status"] == "start_now"
    assert s["overlap"] is True


def test_next_hatch_suggestion_overdue_and_no_brine():
    stale = nps.next_hatch_suggestion(NOW, 24, _iso(NOW - timedelta(hours=30)), 24, None, None, "")
    assert stale["status"] == "overdue"
    dry = nps.next_hatch_suggestion(NOW, 24, _iso(NOW - timedelta(hours=1)), 48, 0, 40, "")
    assert dry["status"] == "overdue" and dry["driver"] == "depletion"
    assert nps.next_hatch_suggestion(NOW, 24, "", 24, None, None, "")["status"] == "no_brine"


def test_next_hatch_suggestion_chained_while_incubating():
    # 6 h into a 36 h hatch with 48 h shelf: the next start keeps the chain
    # unbroken at started + shelf -> 42 h from now.
    s = nps.next_hatch_suggestion(NOW, 36, "", 48, None, None, _iso(NOW - timedelta(hours=6)))
    assert s["status"] == "chained" and s["driver"] == "freshness"
    assert s["hoursUntil"] == 42.0


def test_next_hatch_multi_vessel_chains_on_latest():
    # Two batches running (18 h and 6 h in): every load resets the container's
    # clock, so the chain anchors on the LATEST start.
    starts = [_iso(NOW - timedelta(hours=18)), _iso(NOW - timedelta(hours=6))]
    s = nps.next_hatch_suggestion(NOW, 24, "", 48, None, None, starts)
    assert s["status"] == "chained" and s["busyCount"] == 2
    assert s["hoursUntil"] == 42.0    # latest start + 48 h shelf


def test_next_hatch_respects_each_batches_stamped_clock():
    # Reece's live catch (0.7.62): a 36 h batch was 9.2 h in when the default
    # clock was dropped to 24 h. The chain must anchor on the BATCH's stamped
    # clock — it loads at +26.8 h — not the new default, which would have
    # called for a start 12 h early.
    batch = [{"startedAt": _iso(NOW - timedelta(hours=9.2)), "hatchHours": 36}]
    s = nps.next_hatch_suggestion(NOW, 24, "", 24, None, None, batch)
    assert s["status"] == "chained"
    assert s["hoursUntil"] == 26.8
    assert s["busyCount"] == 1


def test_hatchery_v2_pure_helpers():
    assert nps.vessels_needed(36, 24) == 2      # the documented 2-vessel stagger
    assert nps.vessels_needed(24, 48) == 1
    history = [
        {"eggType": "standard", "actualHours": 20.0},
        {"eggType": "standard", "actualHours": 21.0},
        {"eggType": "decapsulated", "actualHours": 14.0},
        {"eggType": "standard", "actualHours": 19.0},
    ]
    learned = nps.learned_hatch_hours(history, "standard")
    assert learned["available"] and learned["hours"] == 20.0 and learned["samples"] == 3
    assert not nps.learned_hatch_hours(history, "decapsulated")["available"]  # 1 sample
    temp = nps.expected_hatch_hours(24, 21)     # 7 °C below optimum
    assert temp["available"] and temp["factor"] == 1.56
    assert temp["expectedHours"] == 37.4
    assert nps.expected_hatch_hours(24, 32)["warm"] is True
    guide = nps.cyst_dose_guide(1.0)
    assert guide["grams"] == 2.0 and guide["nauplii"] == 450000


def _v2_entry(reservoir=None, vessels=None):
    entry = _entry({})
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"] = {
        "hatchHours": 24, "eggType": "standard",
        "vessels": vessels or {
            "v1": {"name": "Hatchery 1", "volumeL": 1.0, "state": {}},
            "v2": {"name": "Hatchery 2", "volumeL": 0.7, "state": {}},
        },
        "reservoir": reservoir or {},
    }
    return entry


def test_ws_hatch_start_picks_idle_vessel_and_refuses_when_all_busy():
    entry = _v2_entry()
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_start(hass, conn, {"id": 1}))
    run(integration.websocket_nps_hatch_start(hass, conn, {"id": 2}))
    vessels = entry.options[CONF_SETTINGS]["nps"]["hatchery"]["vessels"]
    assert vessels["v1"]["state"]["hatchStartedAt"] and vessels["v2"]["state"]["hatchStartedAt"]
    run(integration.websocket_nps_hatch_start(hass, conn, {"id": 3}))
    assert conn.errors and conn.errors[-1].code == "all_busy"


def test_ws_harvest_hard_gate_and_volume_move():
    # Stale leftovers HARD-block the load (Reece, locked); discard unlocks it,
    # and the load then tops the container to full (loadVolumeMl 0).
    stale_mix = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    entry = _v2_entry(reservoir={"volumeMl": 500, "remainingMl": 200, "mixedAt": stale_mix})
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"]["vessels"]["v1"]["state"] = {
        "hatchStartedAt": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
        "eggType": "standard", "hatchHours": 24,
    }
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_cancel(hass, conn, {"id": 1, "harvested": True}))
    assert conn.errors and conn.errors[-1].code == "stale_brine"
    vessels = entry.options[CONF_SETTINGS]["nps"]["hatchery"]["vessels"]
    assert vessels["v1"]["state"]["hatchStartedAt"], "a blocked load must not clear the batch"
    run(integration.websocket_nps_reservoir_discard(hass, conn, {"id": 2}))
    reservoir = entry.options[CONF_SETTINGS]["nps"]["hatchery"]["reservoir"]
    assert reservoir["remainingMl"] == 0 and not reservoir["mixedAt"]
    run(integration.websocket_nps_hatch_cancel(hass, conn, {"id": 3, "harvested": True}))
    saved = entry.options[CONF_SETTINGS]["nps"]["hatchery"]
    assert saved["reservoir"]["remainingMl"] == 500     # top-to-full
    assert saved["reservoir"]["mixedAt"]
    assert not saved["vessels"]["v1"]["state"]["hatchStartedAt"]
    assert saved["history"] and saved["history"][0]["vesselId"] == "v1"


def test_ws_harvest_fixed_load_volume_clamps():
    entry = _v2_entry(reservoir={"volumeMl": 1000, "remainingMl": 800,
                                 "loadVolumeMl": 400,
                                 "mixedAt": datetime.now(timezone.utc).isoformat()})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_cancel(hass, conn, {"id": 1, "harvested": True}))
    assert not conn.errors
    reservoir = entry.options[CONF_SETTINGS]["nps"]["hatchery"]["reservoir"]
    assert reservoir["remainingMl"] == 1000    # 800 + 400 clamped at the brim


def test_ws_hand_feed_debits_the_container():
    entry = _v2_entry(reservoir={"volumeMl": 500, "remainingMl": 300,
                                 "mixedAt": datetime.now(timezone.utc).isoformat()})
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"]["handFeed"] = {"defaultDoseMl": 30, "feedsPerDay": 2}
    cfg["maintenance"] = {"seeded": True, "enabled": True, "tasks": {
        "brine_hand_feed": {"label": "Feed live brine", "enabled": True,
                            "cadenceDays": 1, "cadenceHours": 12}}, "completions": {}}
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hand_feed(hass, conn, {"id": 1}))
    saved = entry.options[CONF_SETTINGS]
    assert saved["nps"]["hatchery"]["reservoir"]["remainingMl"] == 270   # default dose
    logged = saved["maintenance"]["completions"].get("brine_hand_feed") or []
    assert logged and logged[0]["source"] == "hatchery"
    run(integration.websocket_nps_hand_feed(hass, conn, {"id": 2, "ml": 50}))
    assert entry.options[CONF_SETTINGS]["nps"]["hatchery"]["reservoir"]["remainingMl"] == 220


def test_ws_hatch_clock_moves_the_batch_the_push_and_the_reminders():
    """Reece's live catch (0.7.79): "Set clock to 34 h" changed the number and
    nothing else. Everything downstream of the clock has to move with it —
    the countdown already running, the ready push, and the hour cadence of the
    hatchery reminders."""
    now = datetime.now(timezone.utc)
    entry = _v2_entry()
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"]["vessels"]["v1"]["state"] = {
        "hatchStartedAt": (now - timedelta(hours=0.7)).isoformat(),
        "eggType": "standard", "hatchHours": 24,
    }
    # v2 is already ripe on its own clock — no arithmetic un-hatches nauplii.
    cfg["nps"]["hatchery"]["vessels"]["v2"]["state"] = {
        "hatchStartedAt": (now - timedelta(hours=26)).isoformat(),
        "eggType": "standard", "hatchHours": 24,
        "readyNotifiedAt": now.isoformat(),
    }
    cfg["maintenance"] = {"seeded": True, "enabled": True, "completions": {}, "tasks": {
        "brine_hatch_start": {"label": "Start brine shrimp hatch", "enabled": True,
                              "cadenceDays": 1, "cadenceHours": 24,
                              "criticalAfterDays": 2, "criticalAfterHours": 48},
        "brine_hatch_harvest": {"label": "Harvest, rinse & load brine", "enabled": True,
                                "cadenceDays": 1, "cadenceHours": 24,
                                "criticalAfterDays": 2, "criticalAfterHours": 36,
                                "snoozedUntil": (now + timedelta(hours=23.3)).isoformat()},
    }}
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_clock(hass, conn, {"id": 1, "hours": 33.8}))
    assert not conn.errors
    hatchery = entry.options[CONF_SETTINGS]["nps"]["hatchery"]
    assert hatchery["hatchHours"] == 34                     # rounded into the grid
    v1_state = hatchery["vessels"]["v1"]["state"]
    assert v1_state["hatchHours"] == 34, "the running countdown is the visible half"
    assert not v1_state["readyNotifiedAt"], "a longer clock must re-arm the ready push"
    v2_state = hatchery["vessels"]["v2"]["state"]
    assert v2_state["hatchHours"] == 24 and v2_state["readyNotifiedAt"], \
        "a hatched batch keeps its own result"
    tasks = entry.options[CONF_SETTINGS]["maintenance"]["tasks"]
    assert tasks["brine_hatch_start"]["cadenceHours"] == 34
    assert tasks["brine_hatch_start"]["criticalAfterHours"] == 58
    assert tasks["brine_hatch_harvest"]["cadenceHours"] == 34
    assert tasks["brine_hatch_harvest"]["criticalAfterHours"] == 46
    assert tasks["brine_hatch_harvest"]["cadenceDays"] == 1     # round(34/24) == 1
    # v2 is ripe NOW, so the harvest reminder must not sit snoozed on a stamp
    # that belonged to the old clock.
    assert tasks["brine_hatch_harvest"]["snoozedUntil"] is None
    payload = conn.results[-1].payload
    assert payload["hours"] == 34 and payload["previous"] == 24
    assert [b["name"] for b in payload["restamped"]] == ["Hatchery 1"]
    assert payload["restamped"][0]["hoursLeft"] == 33.3
    assert payload["kept"] == ["Hatchery 2"]


def test_ws_hatch_clock_re_anchors_the_harvest_snooze_and_clamps():
    now = datetime.now(timezone.utc)
    started = now - timedelta(hours=2)
    entry = _v2_entry(vessels={"v1": {"name": "Hatchery 1", "volumeL": 0.7, "state": {
        "hatchStartedAt": started.isoformat(), "eggType": "standard", "hatchHours": 24}}})
    cfg = entry.options[CONF_SETTINGS]
    cfg["maintenance"] = {"seeded": True, "enabled": True, "completions": {}, "tasks": {
        "brine_hatch_harvest": {"label": "Harvest", "enabled": True, "cadenceDays": 1,
                                "cadenceHours": 24, "snoozedUntil": None}}}
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    # Out of range on purpose: the clock is an 8-48 h grid.
    run(integration.websocket_nps_hatch_clock(hass, conn, {"id": 1, "hours": 96}))
    saved = entry.options[CONF_SETTINGS]
    assert saved["nps"]["hatchery"]["hatchHours"] == 48
    snoozed = datetime.fromisoformat(
        saved["maintenance"]["tasks"]["brine_hatch_harvest"]["snoozedUntil"])
    assert abs((snoozed - (started + timedelta(hours=48))).total_seconds()) < 5, \
        "the harvest reminder lands when this batch actually ripens"
    # A start chore the keeper never added must not be conjured into existence.
    assert "brine_hatch_start" not in saved["maintenance"]["tasks"]


def test_ws_hatch_clock_can_leave_running_batches_alone():
    now = datetime.now(timezone.utc)
    entry = _v2_entry(vessels={"v1": {"name": "Hatchery 1", "volumeL": 0.7, "state": {
        "hatchStartedAt": (now - timedelta(hours=3)).isoformat(),
        "eggType": "standard", "hatchHours": 24}}})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_clock(
        hass, conn, {"id": 1, "hours": 36, "restamp": False}))
    hatchery = entry.options[CONF_SETTINGS]["nps"]["hatchery"]
    assert hatchery["hatchHours"] == 36
    assert hatchery["vessels"]["v1"]["state"]["hatchHours"] == 24
    assert conn.results[-1].payload["kept"] == ["Hatchery 1"]


def test_ws_hatch_clock_aligns_a_stranded_batch_with_no_hours():
    """Reece's state on 2026-08-25: the clock already said 34 h, so the
    learned chip had retired itself — and the batch started before the change
    was stamped 24 h with NO route back. Aligning takes no hours at all."""
    now = datetime.now(timezone.utc)
    started = now - timedelta(hours=1.8)
    entry = _v2_entry(vessels={"v1": {"name": "Hatchery 1", "volumeL": 0.7, "state": {
        "hatchStartedAt": started.isoformat(), "eggType": "standard",
        "hatchHours": 24, "readyNotifiedAt": ""}}})
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"]["hatchHours"] = 34
    cfg["maintenance"] = {"seeded": True, "enabled": True, "completions": {}, "tasks": {
        "brine_hatch_harvest": {"label": "Harvest", "enabled": True,
                                "cadenceDays": 1, "cadenceHours": 24}}}
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_clock(hass, conn, {"id": 1}))
    assert not conn.errors
    saved = entry.options[CONF_SETTINGS]
    assert saved["nps"]["hatchery"]["hatchHours"] == 34, "no hours given — the clock must not move"
    assert saved["nps"]["hatchery"]["vessels"]["v1"]["state"]["hatchHours"] == 34
    assert saved["maintenance"]["tasks"]["brine_hatch_harvest"]["cadenceHours"] == 34
    payload = conn.results[-1].payload
    assert payload["restamped"][0]["hoursLeft"] == 32.2


def test_ws_hatch_clock_vessel_id_overrides_the_egg_type_rule():
    now = datetime.now(timezone.utc)
    entry = _v2_entry(vessels={
        "v1": {"name": "Hatchery 1", "volumeL": 0.7, "state": {
            "hatchStartedAt": (now - timedelta(hours=2)).isoformat(),
            "eggType": "decapsulated", "hatchHours": 18}},
        "v2": {"name": "Hatchery 2", "volumeL": 0.7, "state": {
            "hatchStartedAt": (now - timedelta(hours=2)).isoformat(),
            "eggType": "standard", "hatchHours": 24}},
    })
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    # Sweeping change: the decapsulated batch is a different animal, left alone.
    run(integration.websocket_nps_hatch_clock(hass, conn, {"id": 1, "hours": 34}))
    vessels = entry.options[CONF_SETTINGS]["nps"]["hatchery"]["vessels"]
    assert vessels["v1"]["state"]["hatchHours"] == 18, "an 18 h decap batch is not a 34 h one"
    assert vessels["v2"]["state"]["hatchHours"] == 34
    assert conn.results[-1].payload["kept"] == ["Hatchery 1"]
    # Naming it is an explicit override — move THAT batch.
    run(integration.websocket_nps_hatch_clock(hass, conn, {"id": 2, "vessel_id": "v1"}))
    vessels = entry.options[CONF_SETTINGS]["nps"]["hatchery"]["vessels"]
    assert vessels["v1"]["state"]["hatchHours"] == 34
    run(integration.websocket_nps_hatch_clock(hass, conn, {"id": 3, "vessel_id": "nope"}))
    assert conn.errors[-1].code == "unknown_vessel"


def test_save_config_carries_the_running_batch_onto_a_new_clock():
    """The settings field is a route to the clock too — Reece changed it there
    and the running countdown stayed behind (0.7.80)."""
    now = datetime.now(timezone.utc)
    entry = _v2_entry(vessels={"v1": {"name": "Hatchery 1", "volumeL": 0.7, "state": {
        "hatchStartedAt": (now - timedelta(hours=3)).isoformat(),
        "eggType": "standard", "hatchHours": 24, "readyNotifiedAt": ""}}})
    incoming = _deepcopy(entry.options[CONF_SETTINGS])
    incoming["nps"]["hatchery"]["hatchHours"] = 36
    incoming["maintenance"] = {"seeded": True, "enabled": True, "completions": {}, "tasks": {
        "brine_hatch_harvest": {"label": "Harvest", "enabled": True,
                                "cadenceDays": 1, "cadenceHours": 24}}}
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_save_config(hass, conn, {"id": 1, "config": incoming}))
    saved = entry.options[CONF_SETTINGS]
    assert saved["nps"]["hatchery"]["vessels"]["v1"]["state"]["hatchHours"] == 36
    assert saved["maintenance"]["tasks"]["brine_hatch_harvest"]["cadenceHours"] == 36
    # A save that does NOT touch the clock leaves the batch entirely alone.
    again = _deepcopy(saved)
    again["nps"]["hatchery"]["vessels"]["v1"]["state"]["hatchHours"] = 36
    again["tank"] = {"volumeLitres": 60}
    run(integration.websocket_save_config(hass, conn, {"id": 2, "config": again}))
    assert entry.options[CONF_SETTINGS]["nps"]["hatchery"]["vessels"]["v1"]["state"]["hatchHours"] == 36


def test_save_config_never_un_hatches_a_ripe_batch():
    now = datetime.now(timezone.utc)
    entry = _v2_entry(vessels={"v1": {"name": "Hatchery 1", "volumeL": 0.7, "state": {
        "hatchStartedAt": (now - timedelta(hours=26)).isoformat(),
        "eggType": "standard", "hatchHours": 24,
        "readyNotifiedAt": now.isoformat()}}})
    incoming = _deepcopy(entry.options[CONF_SETTINGS])
    incoming["nps"]["hatchery"]["hatchHours"] = 40
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_save_config(hass, conn, {"id": 1, "config": incoming}))
    state = entry.options[CONF_SETTINGS]["nps"]["hatchery"]["vessels"]["v1"]["state"]
    assert state["hatchHours"] == 24, "those nauplii have hatched"
    assert state["readyNotifiedAt"], "and the keeper was already told"


def test_hatch_ready_push_fires_exactly_once():
    entry = _v2_entry()
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"]["vessels"]["v1"]["state"] = {
        "hatchStartedAt": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
        "eggType": "standard", "hatchHours": 24, "readyNotifiedAt": "",
    }
    hass = FakeHass(entries=[entry])
    run(integration._async_nps_hatch_ready_push(hass, entry))
    pushes = [c for c in hass.services.calls
              if c.domain == "persistent_notification" and c.service == "create"
              and "hatch_ready" in (c.data or {}).get("notification_id", "")]
    assert len(pushes) == 1, "the ready push should fire for the ripe batch"
    assert entry.options[CONF_SETTINGS]["nps"]["hatchery"]["vessels"]["v1"]["state"]["readyNotifiedAt"]
    run(integration._async_nps_hatch_ready_push(hass, entry))
    pushes = [c for c in hass.services.calls
              if c.domain == "persistent_notification" and c.service == "create"
              and "hatch_ready" in (c.data or {}).get("notification_id", "")]
    assert len(pushes) == 1, "a batch must notify exactly once"


def test_enrich_state_lifecycle():
    assert nps.enrich_state("", 12, False, "", NOW)["status"] == "none"
    mid = nps.enrich_state(_iso(NOW - timedelta(hours=7)), 12, False, "", NOW)
    assert mid["status"] == "enriching" and mid["hoursLeft"] == 5.0
    assert mid["secondDoseDue"] is False
    # Split-dose protocol: the T+10 top-up comes due mid-soak, once.
    due = nps.enrich_state(_iso(NOW - timedelta(hours=10.5)), 12, True, "", NOW)
    assert due["secondDoseDue"] is True
    dosed = nps.enrich_state(_iso(NOW - timedelta(hours=10.5)), 12, True,
                             _iso(NOW - timedelta(minutes=5)), NOW)
    assert dosed["secondDoseDue"] is False
    assert nps.enrich_state(_iso(NOW - timedelta(hours=13)), 12, False, "", NOW)["status"] == "done"
    assert nps.enrich_state(_iso(NOW - timedelta(hours=19)), 12, False, "", NOW)["status"] == "overdue"


def _enrich_entry(dose_delay_h=0, remaining=300, mixed_hours_ago=10):
    # Container semantics: the brine being enriched is ALREADY loaded — give
    # the reservoir a batch of the requested age (wall clock; handlers do).
    mixed_at = ((datetime.now(timezone.utc) - timedelta(hours=mixed_hours_ago)).isoformat()
                if mixed_hours_ago is not None else "")
    entry = _v2_entry(reservoir={"volumeMl": 500, "remainingMl": remaining,
                                 "mixedAt": mixed_at})
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"]["enrichment"] = {
        "hours": 12, "doseMl": 2, "productId": "selcon", "splitDose": True,
        "doseDelayH": dose_delay_h,
    }
    cfg["consumables"] = {"products": {"selcon": _product(
        name="Selcon", category="other", bottleMl=60, remainingMl=50)}}
    return entry


def test_enrich_state_dose_delay_anchors_on_first_dose():
    # Reece's catch: instar I can't eat. Holding phase — no dose yet, +8 h
    # delay: percent 0, no clock, the dose comes due only past the molt.
    early = nps.enrich_state(_iso(NOW - timedelta(hours=3)), 12, False, "", NOW, "", 8)
    assert early["status"] == "enriching" and early["percent"] == 0.0
    assert early["firstDoseDue"] is False and early["hoursLeft"] is None
    due = nps.enrich_state(_iso(NOW - timedelta(hours=9)), 12, False, "", NOW, "", 8)
    assert due["firstDoseDue"] is True
    # Container semantics: the molt clock runs on the BATCH's load stamp —
    # engaging 1 h ago on a 9 h-old batch is due immediately.
    batch_due = nps.enrich_state(_iso(NOW - timedelta(hours=1)), 12, False, "", NOW,
                                 "", 8, _iso(NOW - timedelta(hours=9)))
    assert batch_due["firstDoseDue"] is True
    batch_young = nps.enrich_state(_iso(NOW - timedelta(hours=1)), 12, False, "", NOW,
                                   "", 8, _iso(NOW - timedelta(hours=3)))
    assert batch_young["firstDoseDue"] is False
    # Dosed: the soak counts from the DOSE — 5 h fed of 12 leaves 7.
    fed = nps.enrich_state(_iso(NOW - timedelta(hours=13)), 12, False, "", NOW,
                           _iso(NOW - timedelta(hours=5)), 8)
    assert fed["status"] == "enriching" and fed["hoursLeft"] == 7.0
    assert fed["firstDoseDue"] is False
    # Done anchors on the dose too, not the load.
    done = nps.enrich_state(_iso(NOW - timedelta(hours=21)), 12, False, "", NOW,
                            _iso(NOW - timedelta(hours=13)), 8)
    assert done["status"] == "done"
    # And the split top-up counts 10 h from the first dose.
    topup = nps.enrich_state(_iso(NOW - timedelta(hours=19)), 12, True, "", NOW,
                             _iso(NOW - timedelta(hours=10.5)), 8)
    assert topup["secondDoseDue"] is True


def test_ws_enrich_dose_delay_flow():
    # A YOUNG batch (3 h old, delay 8): engage holds — no debit, no dose —
    # and the top-up refuses to jump the queue. The dose logs later.
    entry = _enrich_entry(dose_delay_h=8, mixed_hours_ago=3)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_enrich(hass, conn, {"id": 1}))
    saved = entry.options[CONF_SETTINGS]
    assert saved["consumables"]["products"]["selcon"]["remainingMl"] == 50, \
        "no debit before the batch can eat"
    state = saved["nps"]["hatchery"]["enrichment"]["state"]
    assert not state["firstDoseAt"] and state["doseDelayH"] == 8
    assert state["batchLoadedAt"], "the soak must remember the batch's load stamp"
    run(integration.websocket_nps_enrich_second_dose(hass, conn, {"id": 2}))
    assert conn.errors and conn.errors[-1].code == "no_first_dose"
    run(integration.websocket_nps_enrich_dose(hass, conn, {"id": 3}))
    saved = entry.options[CONF_SETTINGS]
    assert saved["consumables"]["products"]["selcon"]["remainingMl"] == 48
    assert saved["nps"]["hatchery"]["enrichment"]["state"]["firstDoseAt"]
    run(integration.websocket_nps_enrich_dose(hass, conn, {"id": 4}))
    assert conn.errors[-1].code == "already_dosed"


def test_ws_enrich_old_batch_doses_immediately():
    # Reece's evening scenario: brine loaded at 8am, enriched at night — the
    # batch is past the molt, so the dose (and debit) happen at engage even
    # with a delay configured.
    entry = _enrich_entry(dose_delay_h=8, mixed_hours_ago=10)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_enrich(hass, conn, {"id": 1}))
    saved = entry.options[CONF_SETTINGS]
    assert saved["consumables"]["products"]["selcon"]["remainingMl"] == 48
    assert saved["nps"]["hatchery"]["enrichment"]["state"]["firstDoseAt"]
    assert not conn.errors


def test_enrich_push_reminds_the_first_dose_once():
    entry = _enrich_entry(dose_delay_h=8)
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"] = integration._normalise_hatchery(cfg["nps"]["hatchery"], True)
    cfg["nps"]["hatchery"]["enrichment"]["state"].update({
        # Engaged only 1 h ago — but the BATCH is 9 h old: the dose is due.
        "startedAt": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "batchLoadedAt": (datetime.now(timezone.utc) - timedelta(hours=9)).isoformat(),
        "enrichHours": 12, "doseDelayH": 8,
    })
    hass = FakeHass(entries=[entry])
    def _notes(nid):
        return [c for c in hass.services.calls
                if c.domain == "persistent_notification" and c.service == "create"
                and (c.data or {}).get("notification_id") == nid]
    run(integration._async_nps_hatch_ready_push(hass, entry))
    assert len(_notes("openreef_enrich_dose")) == 1, "the dose push should fire past the molt"
    assert not _notes("openreef_enrich_done"), "no done push before any food went in"
    run(integration._async_nps_hatch_ready_push(hass, entry))
    assert len(_notes("openreef_enrich_dose")) == 1, "the dose push must fire exactly once"


def test_ws_enrich_is_a_container_action():
    # Reece's mesh flow: "Enrich" soaks the LOADED brine and must NEVER touch
    # a running hatch. Soak done stamps the boost clock — nothing moves.
    entry = _enrich_entry()
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_start(hass, conn, {"id": 1}))
    run(integration.websocket_nps_hatch_enrich(hass, conn, {"id": 2}))
    saved = entry.options[CONF_SETTINGS]["nps"]["hatchery"]
    assert saved["vessels"]["v1"]["state"]["hatchStartedAt"], \
        "the running hatch must be untouched"
    assert saved["enrichment"]["state"]["startedAt"], "the soak clock must start"
    assert saved["enrichment"]["state"]["batchLoadedAt"]
    products = entry.options[CONF_SETTINGS]["consumables"]["products"]
    assert products["selcon"]["remainingMl"] == 48                   # dose at engage (delay 0)
    run(integration.websocket_nps_hatch_enrich(hass, conn, {"id": 3}))
    assert conn.errors and conn.errors[-1].code == "enrich_busy"
    run(integration.websocket_nps_enrich_loaded(hass, conn, {"id": 4}))
    saved = entry.options[CONF_SETTINGS]["nps"]["hatchery"]
    assert saved["reservoir"]["remainingMl"] == 300, "soak done moves NO volume"
    assert saved["reservoir"]["lastLoadEnriched"] is True
    assert saved["reservoir"]["enrichedAt"], "the boost decays from soak end"
    assert not saved["enrichment"]["state"]["startedAt"], "the soak must clear"
    assert not saved["history"], "a container soak inserts no journal row of its own"
    assert saved["vessels"]["v1"]["state"]["hatchStartedAt"], \
        "the hatch survives the whole soak lifecycle"


def test_ws_soak_done_badges_the_harvested_batch():
    # Reece's catch (0.7.112): every enriched batch after 0.7.70 lost its
    # journal badge — soak done stamped the container but never the row.
    # The row the HARVEST wrote is the one that earns "enriched N h", keyed
    # by the shared load stamp; no second row appears.
    entry = _enrich_entry(remaining=0, mixed_hours_ago=None)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_start(hass, conn, {"id": 1}))
    run(integration.websocket_nps_hatch_cancel(hass, conn, {"id": 2, "harvested": True}))
    saved = entry.options[CONF_SETTINGS]["nps"]["hatchery"]
    assert len(saved["history"]) == 1 and not saved["history"][0].get("enriched")
    assert saved["history"][0]["vesselId"] == "v1"
    run(integration.websocket_nps_hatch_enrich(hass, conn, {"id": 3}))
    run(integration.websocket_nps_enrich_loaded(hass, conn, {"id": 4}))
    saved = entry.options[CONF_SETTINGS]["nps"]["hatchery"]
    assert len(saved["history"]) == 1, "soak done badges the harvest row, never adds one"
    row = saved["history"][0]
    assert row["enriched"] is True and row["enrichedHours"] == 0.0
    assert row["vesselId"] == "v1", "the badge stays on the cone that hatched it"
    log = entry.options[CONF_SETTINGS]["activity"]
    assert any("Hatchery 1 batch is gut-loaded" in str(item.get("message", "")) for item in log), \
        "the log names the hatchery whose batch soaked"
    # A second harvest into the same container (top-up) then a second soak
    # badges the NEW row and leaves the first badge alone.
    run(integration.websocket_nps_hatch_start(hass, conn, {"id": 5}))
    run(integration.websocket_nps_hatch_cancel(hass, conn, {"id": 6, "harvested": True}))
    run(integration.websocket_nps_hatch_enrich(hass, conn, {"id": 7}))
    run(integration.websocket_nps_enrich_loaded(hass, conn, {"id": 8}))
    saved = entry.options[CONF_SETTINGS]["nps"]["hatchery"]
    assert len(saved["history"]) == 2
    assert saved["history"][0]["enriched"] is True and saved["history"][1]["enriched"] is True


def test_ws_enrich_needs_loaded_brine():
    entry = _enrich_entry(remaining=0, mixed_hours_ago=None)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_enrich(hass, conn, {"id": 1}))
    assert conn.errors and conn.errors[-1].code == "no_brine"


def test_ws_enrich_second_dose_debits_once():
    entry = _enrich_entry()   # old batch → first dose at engage
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_enrich(hass, conn, {"id": 1}))
    run(integration.websocket_nps_enrich_second_dose(hass, conn, {"id": 2}))
    products = entry.options[CONF_SETTINGS]["consumables"]["products"]
    assert products["selcon"]["remainingMl"] == 46                   # 50 - 2 - 2
    assert entry.options[CONF_SETTINGS]["nps"]["hatchery"]["enrichment"]["state"]["secondDoseAt"]
    run(integration.websocket_nps_enrich_second_dose(hass, conn, {"id": 3}))
    assert conn.errors and conn.errors[-1].code == "already_dosed"


def test_enriched_load_caps_the_shelf_clock():
    # The HUFA boost is transient: enriched load = 12 h shelf warm, 48 h fridged.
    entry = _v2_entry(reservoir={"volumeMl": 500, "remainingMl": 300,
                                 "mixedAt": datetime.now(timezone.utc).isoformat(),
                                 "lastLoadEnriched": True})
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"] = integration._normalise_hatchery(cfg["nps"]["hatchery"], True)
    _loaded, shelf_h, _rem, _rate = integration._nps_brine_supply(cfg)
    assert shelf_h == 12.0
    cfg["nps"]["hatchery"]["reservoir"]["refrigerated"] = True
    _loaded, shelf_h, _rem, _rate = integration._nps_brine_supply(cfg)
    assert shelf_h == 48.0
    # Container soak (0.7.70): the boost decays from SOAK END, so an evening
    # enrich of a morning batch keeps an honest clock — loaded 6 h ago,
    # soaked done 1 h ago, room temp: shelf = min(24, 5 + 12) = 17 h.
    cfg["nps"]["hatchery"]["reservoir"].update({
        "refrigerated": False,
        "mixedAt": (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat(),
        "enrichedAt": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    })
    _loaded, shelf_h, _rem, _rate = integration._nps_brine_supply(cfg)
    assert abs(shelf_h - 17.0) < 0.1


def test_enrich_push_fires_done_and_topup_once():
    entry = _enrich_entry()
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"] = integration._normalise_hatchery(cfg["nps"]["hatchery"], True)
    cfg["nps"]["hatchery"]["enrichment"]["state"].update({
        "startedAt": (datetime.now(timezone.utc) - timedelta(hours=10.5)).isoformat(),
        "enrichHours": 12,
    })
    hass = FakeHass(entries=[entry])
    def _topups():
        return [c for c in hass.services.calls
                if c.domain == "persistent_notification" and c.service == "create"
                and (c.data or {}).get("notification_id") == "openreef_enrich_topup"]
    run(integration._async_nps_hatch_ready_push(hass, entry))
    assert len(_topups()) == 1, "the split-dose top-up should notify at T+10"
    run(integration._async_nps_hatch_ready_push(hass, entry))
    assert len(_topups()) == 1, "the top-up must notify exactly once"
    # Roll the soak past done: the finish push fires once too.
    cfg = integration._config_from_entry(entry)
    cfg["nps"]["hatchery"]["enrichment"]["state"]["startedAt"] = (
        datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
    integration._persist_entry_config(hass, entry, cfg)
    def _dones():
        return [c for c in hass.services.calls
                if c.domain == "persistent_notification" and c.service == "create"
                and (c.data or {}).get("notification_id") == "openreef_enrich_done"]
    run(integration._async_nps_hatch_ready_push(hass, entry))
    assert len(_dones()) == 1, "the enrichment-done push should fire"
    run(integration._async_nps_hatch_ready_push(hass, entry))
    assert len(_dones()) == 1, "the done push must fire exactly once"


def test_hatchery_standalone_gate():
    # 0.7.71: hatchery.enabled inherits nps.enabled for existing configs, and
    # an explicit choice wins in both directions (breeders: NPS off, rig on).
    on = integration._normalise_core_config({"nps": {"enabled": True}})
    assert on["nps"]["hatchery"]["enabled"] is True
    off = integration._normalise_core_config({"nps": {"enabled": False}})
    assert off["nps"]["hatchery"]["enabled"] is False
    standalone = integration._normalise_core_config(
        {"nps": {"enabled": False, "hatchery": {"enabled": True}}})
    assert standalone["nps"]["hatchery"]["enabled"] is True
    opted_out = integration._normalise_core_config(
        {"nps": {"enabled": True, "hatchery": {"enabled": False}}})
    assert opted_out["nps"]["hatchery"]["enabled"] is False


def test_hatch_ready_push_fires_for_standalone_hatcheries():
    entry = _v2_entry()
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["enabled"] = False
    cfg["nps"]["hatchery"]["enabled"] = True
    cfg["nps"]["hatchery"]["vessels"]["v1"]["state"] = {
        "hatchStartedAt": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
        "eggType": "standard", "hatchHours": 24, "readyNotifiedAt": "",
    }
    hass = FakeHass(entries=[entry])
    run(integration._async_nps_hatch_ready_push(hass, entry))
    pushes = [c for c in hass.services.calls
              if c.domain == "persistent_notification" and c.service == "create"]
    assert pushes, "a breeder with NPS off must still get the harvest push"


def test_egg_type_hours_and_normaliser():
    assert nps.egg_type_hours("decapsulated") == 16
    assert nps.egg_type_hours("nonsense") == 24        # unknown → standard
    config = integration._normalise_core_config({
        "nps": {"hatchery": {"eggType": "made_up", "hatchHours": 200}},
    })
    hatchery = config["nps"]["hatchery"]
    assert hatchery["eggType"] == "standard"
    assert hatchery["hatchHours"] == 48                # clamped
    # v2: the single clock migrated into vessel v1.
    assert hatchery["vessels"]["v1"]["state"]["hatchStartedAt"] == ""


def test_ws_hatch_start_and_cancel():
    entry = _entry({})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_start(hass, conn, {"id": 1}))
    vessels = entry.options[CONF_SETTINGS]["nps"]["hatchery"]["vessels"]
    assert vessels["v1"]["state"]["hatchStartedAt"], "hatch start did not stamp the clock"
    # Per-batch stamps: the batch carries its own egg type + hours (v2).
    assert vessels["v1"]["state"]["eggType"] == "standard"
    assert vessels["v1"]["state"]["hatchHours"] == 24
    run(integration.websocket_nps_hatch_cancel(hass, conn, {"id": 2}))
    assert entry.options[CONF_SETTINGS]["nps"]["hatchery"]["vessels"]["v1"]["state"]["hatchStartedAt"] == ""
    assert not conn.errors


def _hatch_reminder_entry(hatch_hours=36, harvest_snooze=None, started=""):
    entry = _entry({})
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"] = {"hatchHours": hatch_hours,
                              "state": {"hatchStartedAt": started}}
    cfg["maintenance"] = {
        "seeded": True,
        "enabled": True,
        "tasks": {
            "brine_hatch_start": {
                "label": "Start brine shrimp hatch", "enabled": True,
                "cadenceDays": 2, "criticalAfterDays": 4,
                "cadenceHours": hatch_hours, "criticalAfterHours": hatch_hours + 24,
                "snoozedUntil": _iso(NOW + timedelta(hours=5)),
            },
            "brine_hatch_harvest": {
                "label": "Harvest, rinse & load brine", "enabled": True,
                "cadenceDays": 2, "criticalAfterDays": 4,
                "cadenceHours": hatch_hours, "criticalAfterHours": hatch_hours + 12,
                "snoozedUntil": harvest_snooze,
            },
        },
        "completions": {},
    }
    return entry


def test_ws_hatch_start_syncs_the_reminders():
    # Starting a hatch IS the "start" chore — it gets logged done (hatchery-
    # sourced, snooze cleared) — and the harvest reminder is pointed at the
    # moment this hatch ripens: snoozed until now + hatchHours.
    entry = _hatch_reminder_entry(hatch_hours=36)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    before = datetime.now(timezone.utc)
    run(integration.websocket_nps_hatch_start(hass, conn, {"id": 1}))
    saved = entry.options[CONF_SETTINGS]["maintenance"]
    logged = saved["completions"]["brine_hatch_start"]
    assert logged and logged[0]["source"] == "hatchery"
    assert not saved["tasks"]["brine_hatch_start"].get("snoozedUntil")
    assert saved["tasks"]["brine_hatch_harvest"]["cadenceHours"] == 36  # survives the save
    snooze = datetime.fromisoformat(saved["tasks"]["brine_hatch_harvest"]["snoozedUntil"])
    hours_out = (snooze - before).total_seconds() / 3600.0
    assert 35.9 < hours_out < 36.2, f"harvest reminder should land ~36 h out, got {hours_out}"
    assert not conn.errors


def test_ws_hatch_cancel_harvested_logs_the_chore():
    # "Hatched & loaded" chains a harvested cancel: the harvest chore is done.
    entry = _hatch_reminder_entry(harvest_snooze=_iso(NOW + timedelta(hours=30)),
                                  started=_iso(NOW - timedelta(hours=6)))
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_cancel(hass, conn, {"id": 1, "harvested": True}))
    saved = entry.options[CONF_SETTINGS]["maintenance"]
    logged = saved["completions"].get("brine_hatch_harvest") or []
    assert logged and logged[0]["source"] == "hatchery"
    assert not saved["tasks"]["brine_hatch_harvest"].get("snoozedUntil")


def test_ws_hatch_plain_cancel_only_drops_the_stale_snooze():
    # Abandoning a batch logs NOTHING (nothing was harvested) but drops a
    # harvest snooze that now points at a hatch that will never come ripe.
    future = datetime.now(timezone.utc) + timedelta(hours=30)
    entry = _hatch_reminder_entry(harvest_snooze=future.isoformat(),
                                  started=_iso(NOW - timedelta(hours=6)))
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_cancel(hass, conn, {"id": 1}))
    saved = entry.options[CONF_SETTINGS]["maintenance"]
    assert not (saved["completions"].get("brine_hatch_harvest") or [])
    assert not saved["tasks"]["brine_hatch_harvest"].get("snoozedUntil")


def test_ws_summary_carries_hatchery():
    entry = _entry({})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_summary(hass, conn, {"id": 1}))
    hatchery = conn.results[-1].payload["hatchery"]
    assert hatchery["state"]["status"] == "none"
    assert len(hatchery["eggTypes"]) == 4
    assert hatchery["nextHatch"]["status"] == "no_brine"


def test_ws_summary_hand_dose_brine_clocks():
    # No linked channel: the hatchery's own "Hatched & loaded" stamp drives
    # the prime/freshness clocks AND the next-hatch advice.
    entry = _entry({})
    cfg = entry.options[CONF_SETTINGS]
    loaded = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
    cfg["nps"]["hatchery"] = {"hatchHours": 24,
                              "state": {"hatchStartedAt": "", "loadedAt": loaded}}
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_summary(hass, conn, {"id": 1}))
    payload = conn.results[-1].payload
    fx = payload["feedExchange"]
    assert fx["channelId"] == ""
    assert fx["prime"]["status"] == "prime"
    assert fx["freshness"]["status"] == "fresh"
    next_hatch = payload["hatchery"]["nextHatch"]
    # 24 h hatch + 24 h shelf = structural overlap: the honest advice is now.
    assert next_hatch["status"] == "start_now"
    assert next_hatch["overlap"] is True


def test_ws_summary_never_calls_an_enriched_batch_stale():
    """The whole of Reece's 0.7.89 report in one assert set: load, wait out the
    molt, soak 12 h, and the card used to answer "past prime, hatch fresh" —
    about the batch it had just had him gut-load. Now the boost clock rules,
    and the container's shelf runs to the end of that boost too."""
    now = datetime.now(timezone.utc)
    entry = _entry({})
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"] = {
        "hatchHours": 34,
        "reservoir": {"volumeMl": 750, "remainingMl": 500,
                      "mixedAt": (now - timedelta(hours=26)).isoformat(),
                      "refrigerated": False, "lastLoadEnriched": True,
                      "enrichedAt": (now - timedelta(hours=4)).isoformat()},
    }
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_summary(hass, conn, {"id": 1}))
    payload = conn.results[-1].payload
    prime = payload["feedExchange"]["prime"]
    assert prime["status"] == "gutloaded"        # 26 h old, and NOT fading
    assert prime["primeLeftHours"] == 8.0        # 12 h room hold, 4 h spent
    container = payload["hatchery"]["reservoir"]
    # Soak ended 22 h after the load, so the window is 22 + 12 — the old min()
    # against the 24 h yolk shelf declared it stale two hours ago.
    assert container["shelfHours"] == 34.0
    assert payload["feedExchange"]["freshness"]["status"] != "stale"
    # And the molt advice is on the payload for the card to argue with.
    assert "instar" in payload["hatchery"]


def test_ws_hatch_loaded_stamps_the_hand_dose_clock():
    # Harvested without a pump: loadedAt is stamped, and the overlap case
    # (24 h hatch vs 24 h shelf) re-anchors the start reminder to DUE NOW —
    # a stale snooze must not suppress it. Started relative to REAL now: the
    # handler computes actualHours against the wall clock.
    entry = _hatch_reminder_entry(
        hatch_hours=24,
        started=(datetime.now(timezone.utc) - timedelta(hours=25)).isoformat())
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    before = datetime.now(timezone.utc)
    run(integration.websocket_nps_hatch_cancel(hass, conn, {"id": 1, "harvested": True}))
    saved = entry.options[CONF_SETTINGS]
    # v2: the load stamp lives on the container ledger (reservoir.mixedAt).
    loaded = saved["nps"]["hatchery"]["reservoir"]["mixedAt"]
    assert loaded and datetime.fromisoformat(loaded) >= before - timedelta(seconds=5)
    assert not saved["maintenance"]["tasks"]["brine_hatch_start"].get("snoozedUntil")
    # The harvested batch's story landed in the history (learned-clock feed).
    history = saved["nps"]["hatchery"]["history"]
    assert history and history[0]["plannedHours"] == 24
    assert 24.9 < history[0]["actualHours"] < 25.2


def test_ws_hatch_loaded_snoozes_start_to_the_smart_time():
    # An 8 h hatch against the 24 h shelf: the next start lands at
    # 24 - (8 + 1) = 15 h out, and the start reminder snoozes right to it.
    entry = _hatch_reminder_entry(hatch_hours=8,
                                  started=_iso(NOW - timedelta(hours=9)))
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    before = datetime.now(timezone.utc)
    run(integration.websocket_nps_hatch_cancel(hass, conn, {"id": 1, "harvested": True}))
    saved = entry.options[CONF_SETTINGS]
    snooze = saved["maintenance"]["tasks"]["brine_hatch_start"]["snoozedUntil"]
    hours_out = (datetime.fromisoformat(snooze) - before).total_seconds() / 3600.0
    assert 14.9 < hours_out < 15.2, f"start reminder should snooze ~15 h, got {hours_out}"


def test_capture_trigger_registered_for_feed_exchange():
    config = integration._normalise_core_config({})
    assert config["capture"]["triggers"]["npsFeedExchange"] is False
    assert integration.CAPTURE_TRIGGER_FIELD["nps_feed_exchange"] == "npsFeedExchange"


def test_ws_summary_carries_stage_d_blocks():
    entry = _entry({"phyto": _product()})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_summary(hass, conn, {"id": 1}))
    payload = conn.results[-1].payload
    assert payload["speciesLibrary"]
    assert "gaps" in payload["speciesPlan"]
    assert payload["budget"] == {"available": False}   # no usage logged yet


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok  {name}")
            except AssertionError as err:
                failures += 1
                print(f"FAIL  {name}: {err}")
    raise SystemExit(1 if failures else 0)
