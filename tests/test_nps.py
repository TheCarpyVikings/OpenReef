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
        # The linked channel has to exist (0.7.132): a link to a channel that
        # is gone is no link, and the normaliser says so.
        "dosing": {"channels": {"brine": {"name": "Live brine", "chemical": "livefood", "enabled": True}}},
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
    assert s["status"] == "chained" and s["driver"] == "chain"
    assert s["hoursUntil"] == 42.0 and s["chainVessel"] is None


def test_next_hatch_chain_counts_the_brine_on_hand():
    # Reece's live case (0.7.118): Hatchery 1 is 25.9 h into a 38 h batch,
    # the container is empty, and a feeding bottle in the fridge has 46 h
    # left. The old chain ignored the bottle: that load lands at +12.1 h and
    # (plain 24 h shelf) fades at +37.1 h, a 38 h batch needs 39 h of runway
    # -> "start now". With no feed rate the bottle outlives that load, so
    # the honest deadline is the bottle's fade at +46 h: start in ~7 h.
    batch = [{"startedAt": _iso(NOW - timedelta(hours=25.9)), "hatchHours": 38, "id": "v1"}]
    bottle_loaded = _iso(NOW - timedelta(hours=2))
    s = nps.next_hatch_suggestion(NOW, 38, bottle_loaded, 48, None, None, batch,
                                  chain_shelf_hours=24)
    assert s["status"] == "chained" and s["driver"] == "freshness"
    assert abs(s["hoursUntil"] - 7.0) < 0.05 and s["chainVessel"] == "v1"
    # At 500 ml fed out at 500 ml/day the bottle is GONE at +24 h, before the
    # incoming load fades: the incoming harvest is the deadline -> start now.
    s = nps.next_hatch_suggestion(NOW, 38, bottle_loaded, 48, 500, 500, batch,
                                  chain_shelf_hours=24)
    assert s["status"] == "start_now" and s["driver"] == "chain"
    assert s["chainVessel"] == "v1"
    # A bottle big enough to feed past the incoming load's fade pushes the
    # deadline to ITS depletion.
    s = nps.next_hatch_suggestion(NOW, 38, bottle_loaded, 48, 900, 500, batch,
                                  chain_shelf_hours=24)
    assert s["driver"] == "depletion" and abs(s["hoursUntil"] - (43.2 - 39.0)) < 0.05
    # Nothing on hand: the chain alone, as before.
    s = nps.next_hatch_suggestion(NOW, 38, "", 24, None, None, batch, chain_shelf_hours=24)
    assert s["status"] == "start_now" and s["driver"] == "chain"


def test_ws_summary_next_hatch_sees_the_bottle_and_names_the_vessel():
    now = datetime.now(timezone.utc)
    entry = _v2_entry(reservoir={"volumeMl": 750, "remainingMl": 0, "loadVolumeMl": 0})
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"]["hatchHours"] = 38
    cfg["nps"]["hatchery"]["vessels"]["v1"]["state"] = {
        "hatchStartedAt": (now - timedelta(hours=25.9)).isoformat(), "hatchHours": 38}
    cfg["nps"]["hatchery"]["fridgeBottle"] = {
        "remainingMl": 500, "mixedAt": (now - timedelta(hours=2)).isoformat(),
        "refrigeratedAt": (now - timedelta(hours=2)).isoformat(), "lastLoadEnriched": True,
        "enrichedAt": (now - timedelta(hours=2)).isoformat()}
    cfg["nps"]["hatchery"]["handFeed"] = {"defaultDoseMl": 30, "feedsPerDay": 2}
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_summary(hass, conn, {"id": 1}))
    hatchery = conn.results[-1].payload["hatchery"]
    nxt = hatchery["nextHatch"]
    assert nxt["chainVessel"] == "v1"
    # 60 ml/day out of 500 ml: the bottle outlives the incoming load (its
    # boost window, 2 h soak offset + 48 h cold = 50 h) -> chained on the bottle.
    assert nxt["status"] == "chained" and nxt["driver"] == "freshness"
    assert hatchery["reservoir"]["freshness"] is None
    assert hatchery["fridgeBottle"]["remainingMl"] == 500


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
    # The same batch in the feeding bottle, fridged the moment it was loaded
    # (0.7.116): the bottle's own clock reads the full 48 h.
    cfg["nps"]["hatchery"]["fridgeBottle"] = {
        "remainingMl": 300, "mixedAt": cfg["nps"]["hatchery"]["reservoir"]["mixedAt"],
        "refrigeratedAt": cfg["nps"]["hatchery"]["reservoir"]["mixedAt"],
        "lastLoadEnriched": True}
    bottle = integration._nps_fridge_bottle_state(cfg, datetime.now(timezone.utc))
    assert abs(bottle["shelfHours"] - 48.0) < 0.05
    # Container soak (0.7.70): the boost decays from SOAK END, so an evening
    # enrich of a morning batch keeps an honest clock — loaded 6 h ago,
    # soaked done 1 h ago, room temp: shelf = min(24, 5 + 12) = 17 h.
    cfg["nps"]["hatchery"]["reservoir"].update({
        "fridgeSavedH": 0,
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




# ------------------------------------------------- the mixing station pays
# for hatch water (doc §30)

def _mixing_station_for_hatchery(entry, *, coupled=True, guard="warn", litres=40.0):
    cfg = entry.options[CONF_SETTINGS]
    cfg["mixingStation"] = {
        "enabled": True, "layout": "dual",
        "vessels": {"rodi": {"volumeLitres": 50, "estimatedLitres": 40},
                    "mix": {"volumeLitres": 50, "estimatedLitres": litres, "contents": "salt"}},
        "salt": {"brand": "nyos_pure", "targetPpt": 35.0, "mixHours": 0, "customGPerL": 0},
        "storage": {"circulateEveryH": 6, "circulateForMin": 10, "retestAfterDays": 7},
        "batch": {"state": "storing", "type": "salt", "litres": litres, "usedLitres": 0,
                  "stageAt": _iso(NOW), "testedAt": _iso(NOW)},
        "integrations": {"awcGuard": guard, "hatcheryFromVessel": coupled},
    }


def _mix_litres(entry):
    return entry.options[CONF_SETTINGS]["mixingStation"]["vessels"]["mix"]["estimatedLitres"]


def test_hatchery_from_vessel_defaults_on():
    cfg = integration._normalise_core_config({"mixingStation": {"enabled": True}})
    assert cfg["mixingStation"]["integrations"]["hatcheryFromVessel"] is True
    cfg = integration._normalise_core_config(
        {"mixingStation": {"integrations": {"hatcheryFromVessel": False}}})
    assert cfg["mixingStation"]["integrations"]["hatcheryFromVessel"] is False


def test_ws_hatch_start_draws_the_cone_from_the_mix_vessel():
    # Reece (0.7.113): a 0.5 L hatchery set up in settings takes 0.5 L of
    # saltwater out of the mixing station's vessel the moment a hatch starts.
    entry = _v2_entry(vessels={
        "v1": {"name": "Hatchery 1", "volumeL": 0.5, "state": {}},
        "v2": {"name": "Hatchery 2", "volumeL": 0.7, "state": {}},
    })
    _mixing_station_for_hatchery(entry)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_start(hass, conn, {"id": 1}))
    assert _mix_litres(entry) == 39.5, "the 0.5 L cone must leave the vessel ledger"
    run(integration.websocket_nps_hatch_start(hass, conn, {"id": 2}))
    assert _mix_litres(entry) == 38.8, "the second cone draws its own 0.7 L"
    log = entry.options[CONF_SETTINGS]["activity"]
    assert any("0.5 L drawn by the hatch in Hatchery 1" in str(i.get("message", "")) for i in log)


def test_ws_harvest_backflush_draws_the_container_fill_from_the_mix_vessel():
    # The harvest backflushes the nauplii home on fresh 35 ppt — a 750 ml
    # container filled from empty is 0.75 L out of the vessel. A top-up onto
    # a half-full container draws only what the container actually gained.
    entry = _v2_entry(vessels={"v1": {"name": "Hatchery 1", "volumeL": 0.5, "state": {}}},
                      reservoir={"volumeMl": 750, "remainingMl": 0, "loadVolumeMl": 0})
    _mixing_station_for_hatchery(entry)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_start(hass, conn, {"id": 1}))
    assert _mix_litres(entry) == 39.5
    run(integration.websocket_nps_hatch_cancel(hass, conn, {"id": 2, "harvested": True}))
    assert entry.options[CONF_SETTINGS]["nps"]["hatchery"]["reservoir"]["remainingMl"] == 750
    assert _mix_litres(entry) == 38.75, "the 750 ml backflush must leave the vessel"
    log = entry.options[CONF_SETTINGS]["activity"]
    assert any("0.75 L drawn by the brine backflush" in str(i.get("message", "")) for i in log)
    # Second batch: the container still holds 750 ml (top-to-full) — the
    # backflush gains it nothing, so nothing is drawn beyond the cone.
    run(integration.websocket_nps_hatch_start(hass, conn, {"id": 3}))
    run(integration.websocket_nps_hatch_cancel(hass, conn, {"id": 4, "harvested": True}))
    assert _mix_litres(entry) == 38.25, "a full container gains nothing, draws nothing"
    # A cancelled (not harvested) hatch never backflushes — no container draw.
    run(integration.websocket_nps_hatch_start(hass, conn, {"id": 5}))
    run(integration.websocket_nps_hatch_cancel(hass, conn, {"id": 6, "harvested": False}))
    assert _mix_litres(entry) == 37.75


def test_ws_hatchery_draw_respects_the_toggle_and_the_guard():
    entry = _v2_entry(vessels={"v1": {"name": "Hatchery 1", "volumeL": 0.5, "state": {}}},
                      reservoir={"volumeMl": 750, "remainingMl": 0, "loadVolumeMl": 0})
    _mixing_station_for_hatchery(entry, coupled=False)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_start(hass, conn, {"id": 1}))
    run(integration.websocket_nps_hatch_cancel(hass, conn, {"id": 2, "harvested": True}))
    assert _mix_litres(entry) == 40.0, "unticked: the keeper's hatch water comes from elsewhere"
    entry2 = _v2_entry(vessels={"v1": {"name": "Hatchery 1", "volumeL": 0.5, "state": {}}})
    _mixing_station_for_hatchery(entry2, guard="off")
    hass2 = FakeHass(entries=[entry2])
    run(integration.websocket_nps_hatch_start(hass2, FakeConnection(), {"id": 1}))
    assert _mix_litres(entry2) == 40.0, "guard Off: the ledger is never touched from outside"


# ------------------------------------------------- the per-batch fridge and
# the hatchery audit (doc §12, 0.7.115)

def test_brine_window_is_a_two_rate_clock():
    loaded = _iso(NOW - timedelta(hours=12))
    # Never fridged: the room window, full stop.
    assert nps.brine_window_hours(loaded, NOW, 24, 48) == 24.0
    # Fridged at load: the full fridge window.
    assert nps.brine_window_hours(loaded, NOW, 24, 48, loaded) == 48.0
    # Fridged after 12 warm hours of a 24 h window: half the life is left and
    # it is spent at the slow rate — 12 + 24 = 36 h from load, not 48.
    assert nps.brine_window_hours(loaded, NOW, 24, 48, loaded) == 48.0
    late = nps.brine_window_hours(loaded, NOW, 24, 48, _iso(NOW))
    assert late == 36.0
    # Fridged once it is already spent: nothing comes back.
    spent = _iso(NOW - timedelta(hours=30))
    assert nps.brine_window_hours(spent, NOW, 24, 48, _iso(NOW)) == 30.0
    # Banked credit from an earlier spell extends the room window.
    assert nps.brine_window_hours(loaded, NOW, 24, 48, None, 5.0) == 29.0
    # Exit: 20 h at 4 °C on a 24/48 clock spends 10 warm-equivalent hours and
    # banks the other 10.
    cold_h, saved_h = nps.fridge_saved_on_exit(_iso(NOW - timedelta(hours=20)), NOW, 24, 48)
    assert cold_h == 20.0 and saved_h == 10.0
    # A fridge no better than the room banks nothing.
    assert nps.fridge_saved_on_exit(_iso(NOW - timedelta(hours=20)), NOW, 24, 24)[1] == 0.0


def test_prime_yolk_window_is_fridge_aware_per_batch():
    # The old fixed 24 h called a cold unfed batch "fading" while the container
    # beside it read fresh for 48 h. Loaded 30 h ago, fridged after 6 h warm:
    # 6 + (18/24) * 48 = 42 h window -> still prime with 12 h left.
    loaded = _iso(NOW - timedelta(hours=30))
    st = nps.hatch_prime_state(loaded, NOW, fridged_at_iso=_iso(NOW - timedelta(hours=24)))
    assert st["status"] == "prime" and st["refrigerated"] is True
    assert st["windowHours"] == 42.0 and st["primeLeftHours"] == 12.0
    # Same batch never fridged: fading, as before.
    assert nps.hatch_prime_state(loaded, NOW)["status"] == "fading"
    # The boost window rides the same clock from the soak end.
    soaked = _iso(NOW - timedelta(hours=20))
    st = nps.hatch_prime_state(loaded, NOW, soaked, fridged_at_iso=_iso(NOW - timedelta(hours=14)))
    # 6 h warm of a 12 h hold = half left, spent at 48 h rate: 6 + 24 = 30 h hold.
    assert st["status"] == "gutloaded" and st["windowHours"] == 30.0
    assert st["primeLeftHours"] == 10.0


def test_legacy_fridge_stamps_migrate_to_the_feeding_bottle():
    loaded = _iso(NOW - timedelta(hours=3))
    # Pre-0.7.115 global toggle: the current load moves to the bottle, cold
    # since its window began. The container comes back empty and warm.
    cfg = integration._normalise_hatchery({"reservoir": {
        "volumeMl": 500, "remainingMl": 300, "mixedAt": loaded, "refrigerated": True}}, True)
    assert "refrigerated" not in cfg["reservoir"] and "refrigeratedAt" not in cfg["reservoir"]
    assert cfg["reservoir"]["remainingMl"] == 0 and cfg["reservoir"]["mixedAt"] == ""
    bottle = cfg["fridgeBottle"]
    assert bottle["remainingMl"] == 300 and bottle["mixedAt"] == loaded
    assert bottle["refrigeratedAt"] == loaded
    # 0.7.115's container stamp: the same move, stamp and credit ride along,
    # the enriched anchors carry.
    soaked = _iso(NOW - timedelta(hours=1))
    cold = _iso(NOW - timedelta(minutes=30))
    cfg = integration._normalise_hatchery({"reservoir": {
        "volumeMl": 500, "remainingMl": 300, "mixedAt": loaded, "refrigeratedAt": cold,
        "fridgeSavedH": 2.5, "lastLoadEnriched": True, "enrichedAt": soaked}}, True)
    bottle = cfg["fridgeBottle"]
    assert bottle["refrigeratedAt"] == cold and bottle["fridgeSavedH"] == 2.5
    assert bottle["lastLoadEnriched"] is True and bottle["enrichedAt"] == soaked
    assert cfg["reservoir"]["lastLoadEnriched"] is False and cfg["reservoir"]["fridgeSavedH"] == 0
    # A stamp on an EMPTY container is just dropped.
    cfg = integration._normalise_hatchery({"reservoir": {
        "volumeMl": 500, "remainingMl": 0, "refrigeratedAt": cold}}, True)
    assert cfg["fridgeBottle"]["remainingMl"] == 0 and cfg["fridgeBottle"]["mixedAt"] == ""
    # A stored bottle survives the normaliser untouched.
    cfg = integration._normalise_hatchery({"fridgeBottle": {
        "remainingMl": 400, "mixedAt": loaded, "refrigeratedAt": cold}}, True)
    assert cfg["fridgeBottle"]["remainingMl"] == 400
    assert cfg["fridgeBottle"]["refrigeratedAt"] == cold


def _bottle(entry):
    return entry.options[CONF_SETTINGS]["nps"]["hatchery"]["fridgeBottle"]


def test_ws_fridge_fill_drains_the_container_into_the_bottle():
    now = datetime.now(timezone.utc)
    loaded = (now - timedelta(hours=6)).isoformat()
    entry = _v2_entry(reservoir={"volumeMl": 750, "remainingMl": 500, "mixedAt": loaded})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_fridge_bottle(hass, conn, {"id": 1, "action": "fill"}))
    res = entry.options[CONF_SETTINGS]["nps"]["hatchery"]["reservoir"]
    bottle = _bottle(entry)
    assert res["remainingMl"] == 0 and res["mixedAt"] == "", \
        "the container is drained — free for the next hatch"
    assert bottle["remainingMl"] == 500 and bottle["mixedAt"] == loaded
    assert bottle["refrigeratedAt"], "the stamp says WHEN it went cold"
    # Nothing left to fill from.
    run(integration.websocket_nps_fridge_bottle(hass, conn, {"id": 2, "action": "fill"}))
    assert conn.errors and conn.errors[-1].code == "no_brine"
    # The summary: the bottle wears its OWN clock — 6 h warm of 24 then cold
    # = 6 + (18/24) * 48 = 42 h from load, 36 h of it still to come.
    run(integration.websocket_nps_summary(hass, conn, {"id": 3}))
    hatchery = conn.results[-1].payload["hatchery"]
    bottle_sum = hatchery["fridgeBottle"]
    assert bottle_sum["remainingMl"] == 500 and abs(bottle_sum["shelfHours"] - 42.0) < 0.1
    assert bottle_sum["freshness"]["status"] == "fresh"
    assert abs(bottle_sum["freshness"]["hoursLeft"] - 36.0) < 0.1
    assert "refrigerated" not in hatchery["reservoir"], "the container is never the cold thing"
    assert hatchery["reservoir"]["freshness"] is None, "the container is empty"
    # Next-hatch planning counts the bottle as supply: its clock, its volume.
    assert abs(hatchery["nextHatch"]["shelfHours"] - 42.0) < 0.1
    log = entry.options[CONF_SETTINGS]["activity"]
    assert any("drained into the feeding bottle" in str(i.get("message", "")) for i in log)


def test_ws_fridge_fill_refusals_and_the_enriched_bottle():
    now = datetime.now(timezone.utc)
    # Stale brine: the fridge won't bring it back.
    entry = _v2_entry(reservoir={"volumeMl": 750, "remainingMl": 500,
                                 "mixedAt": (now - timedelta(hours=30)).isoformat()})
    conn = FakeConnection()
    run(integration.websocket_nps_fridge_bottle(FakeHass(entries=[entry]), conn,
                                                {"id": 1, "action": "fill"}))
    assert conn.errors and conn.errors[-1].code == "stale_brine"
    # Mid-soak: the soak needs to stay warm.
    entry = _enrich_entry(mixed_hours_ago=10)
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_enrich(hass, conn, {"id": 1}))
    run(integration.websocket_nps_fridge_bottle(hass, conn, {"id": 2, "action": "fill"}))
    assert conn.errors and conn.errors[-1].code == "soaking"
    # Soak done, then fill: the gut-loaded batch goes cold on the BOOST clock.
    run(integration.websocket_nps_enrich_loaded(hass, conn, {"id": 3}))
    run(integration.websocket_nps_fridge_bottle(hass, conn, {"id": 4, "action": "fill"}))
    bottle = _bottle(entry)
    assert bottle["lastLoadEnriched"] is True and bottle["enrichedAt"] and bottle["refrigeratedAt"]
    run(integration.websocket_nps_summary(hass, conn, {"id": 5}))
    bottle_sum = conn.results[-1].payload["hatchery"]["fridgeBottle"]
    assert bottle_sum["lastLoadEnriched"] is True
    assert bottle_sum["shelfHours"] > 48, "soak offset + the 48 h cold boost hold"
    assert bottle_sum["shelfHours"] <= 72
    # A stale bottle refuses a refill until it is emptied.
    entry = _v2_entry(reservoir={"volumeMl": 750, "remainingMl": 500, "mixedAt": now.isoformat()})
    entry.options[CONF_SETTINGS]["nps"]["hatchery"]["fridgeBottle"] = {
        "remainingMl": 200, "mixedAt": (now - timedelta(hours=60)).isoformat(),
        "refrigeratedAt": (now - timedelta(hours=59)).isoformat()}
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_fridge_bottle(hass, conn, {"id": 1, "action": "fill"}))
    assert conn.errors and conn.errors[-1].code == "bottle_stale"
    run(integration.websocket_nps_summary(hass, conn, {"id": 2}))
    assert conn.results[-1].payload["hatchery"]["fridgeBottle"]["freshness"]["status"] == "stale"
    run(integration.websocket_nps_fridge_bottle(hass, conn, {"id": 3, "action": "empty"}))
    assert _bottle(entry)["remainingMl"] == 0 and _bottle(entry)["mixedAt"] == ""
    run(integration.websocket_nps_fridge_bottle(hass, conn, {"id": 4, "action": "fill"}))
    assert _bottle(entry)["remainingMl"] == 500


def test_ws_fridge_feed_return_and_empty():
    now = datetime.now(timezone.utc)
    loaded = (now - timedelta(hours=26)).isoformat()
    entry = _v2_entry(reservoir={"volumeMl": 750, "remainingMl": 0, "loadVolumeMl": 0})
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"]["fridgeBottle"] = {
        "remainingMl": 400, "mixedAt": loaded,
        "refrigeratedAt": (now - timedelta(hours=20)).isoformat()}
    cfg["nps"]["hatchery"]["handFeed"] = {"defaultDoseMl": 30, "feedsPerDay": 2}
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    # Feed by hand from the bottle: the default dose, then an explicit one.
    run(integration.websocket_nps_fridge_bottle(hass, conn, {"id": 1, "action": "feed"}))
    assert _bottle(entry)["remainingMl"] == 370
    run(integration.websocket_nps_fridge_bottle(hass, conn, {"id": 2, "action": "feed", "ml": 70}))
    assert _bottle(entry)["remainingMl"] == 300
    log = entry.options[CONF_SETTINGS]["activity"]
    assert any("Hand-fed 70 ml of live brine from the fridge bottle" in str(i.get("message", ""))
               for i in log)
    # Pour back: 20 h cold on a 24/48 clock banks 10 h; the container takes
    # the batch, its load stamp and the credit.
    run(integration.websocket_nps_fridge_bottle(hass, conn, {"id": 3, "action": "return"}))
    res = entry.options[CONF_SETTINGS]["nps"]["hatchery"]["reservoir"]
    assert res["remainingMl"] == 300 and res["mixedAt"] == loaded
    assert abs(res["fridgeSavedH"] - 10.0) < 0.05
    assert _bottle(entry)["remainingMl"] == 0 and _bottle(entry)["refrigeratedAt"] == ""
    # 26 h old with 10 h banked: the room clock reads a 34 h window.
    _l, shelf_h, _r, _rt = integration._nps_brine_supply(
        integration._config_from_entry(entry), now)
    assert abs(shelf_h - 34.0) < 0.1
    log = entry.options[CONF_SETTINGS]["activity"]
    assert any("poured back" in str(i.get("message", "")) and "banked" in str(i.get("message", ""))
               for i in log)
    # Empty bottle: feed / return / empty all say so.
    for action in ("feed", "return", "empty"):
        run(integration.websocket_nps_fridge_bottle(hass, conn, {"id": 9, "action": action}))
        assert conn.errors[-1].code == "bottle_empty"


def test_ws_fridge_fill_on_top_and_return_keep_the_older_clock():
    now = datetime.now(timezone.utc)
    older = (now - timedelta(hours=20)).isoformat()
    entry = _v2_entry(reservoir={"volumeMl": 750, "remainingMl": 300, "loadVolumeMl": 0,
                                 "mixedAt": now.isoformat()})
    entry.options[CONF_SETTINGS]["nps"]["hatchery"]["fridgeBottle"] = {
        "remainingMl": 200, "mixedAt": older,
        "refrigeratedAt": (now - timedelta(hours=19)).isoformat()}
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_fridge_bottle(hass, conn, {"id": 1, "action": "fill"}))
    bottle = _bottle(entry)
    assert bottle["remainingMl"] == 500 and bottle["mixedAt"] == older, \
        "topping up: the older batch's clock rules the mix"
    log = entry.options[CONF_SETTINGS]["activity"]
    assert any("older batch's clock rules" in str(i.get("message", "")) for i in log)
    # A fresh harvest fills the drained container; pouring the bottle back
    # clamps at the brim and the older batch's clock rules again.
    run(integration.websocket_nps_hatch_start(hass, conn, {"id": 2}))
    run(integration.websocket_nps_hatch_cancel(hass, conn, {"id": 3, "harvested": True}))
    res = entry.options[CONF_SETTINGS]["nps"]["hatchery"]["reservoir"]
    assert res["remainingMl"] == 750
    run(integration.websocket_nps_fridge_bottle(hass, conn, {"id": 4, "action": "return"}))
    res = entry.options[CONF_SETTINGS]["nps"]["hatchery"]["reservoir"]
    assert res["remainingMl"] == 750, "clamped at the brim"
    assert res["mixedAt"] == older
    assert _bottle(entry)["remainingMl"] == 0


def test_planning_supply_counts_the_feeding_bottle():
    now = datetime.now(timezone.utc)
    entry = _v2_entry(reservoir={"volumeMl": 750, "remainingMl": 200,
                                 "mixedAt": (now - timedelta(hours=20)).isoformat()})
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"]["handFeed"] = {"defaultDoseMl": 30, "feedsPerDay": 2}
    bottle_loaded = (now - timedelta(hours=8)).isoformat()
    cfg["nps"]["hatchery"]["fridgeBottle"] = {
        "remainingMl": 300, "mixedAt": bottle_loaded,
        "refrigeratedAt": (now - timedelta(hours=6)).isoformat()}
    config = integration._config_from_entry(entry)
    c_loaded, c_shelf, c_rem, c_rate = integration._nps_brine_supply(config, now)
    p_loaded, p_shelf, p_rem, p_rate = integration._nps_brine_supply_for_planning(config, now)
    assert c_shelf == 24.0 and c_rem == 200, "the container's own clock is unchanged"
    assert p_loaded == bottle_loaded, "the bottle dies later: it anchors the planning clock"
    assert abs(p_shelf - (2 + 22 / 24 * 48)) < 0.1
    assert p_rem == 500 and p_rate == c_rate, "the volume is both"
    # An older bottle than the container: the container anchors, the volume is still both.
    cfg["nps"]["hatchery"]["fridgeBottle"] = {
        "remainingMl": 300, "mixedAt": (now - timedelta(hours=45)).isoformat(),
        "refrigeratedAt": (now - timedelta(hours=44)).isoformat()}
    config = integration._config_from_entry(entry)
    p_loaded, p_shelf, p_rem, _ = integration._nps_brine_supply_for_planning(config, now)
    assert p_loaded == c_loaded and p_shelf == 24.0 and p_rem == 500


def test_vessel_ledger_keeps_two_decimals_across_a_save():
    # 0.7.113's sub-litre hatchery draws were rounded away by the next save:
    # a 0.75 L backflush left 38.75 L on the log and 38.8 L in the ledger.
    cfg = integration._normalise_core_config({"mixingStation": {
        "enabled": True,
        "vessels": {"mix": {"volumeLitres": 50, "estimatedLitres": 38.75},
                    "rodi": {"volumeLitres": 50, "estimatedLitres": 12.25}}}})
    assert cfg["mixingStation"]["vessels"]["mix"]["estimatedLitres"] == 38.75
    assert cfg["mixingStation"]["vessels"]["rodi"]["estimatedLitres"] == 12.25


def test_summary_temperature_stretch_uses_the_rated_hours():
    # Reece's live case: 26.1 °C, a 38 h clock. Stretching the clock itself
    # said "expect ~43.7 h" — about batches that actually ran 36.
    entry = _v2_entry()
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"]["hatchHours"] = 38
    cfg["nps"]["hatchery"]["tempEntity"] = "sensor.hatch_temp"
    hass = FakeHass(states={"sensor.hatch_temp": "26.1"}, entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_summary(hass, conn, {"id": 1}))
    temp = conn.results[-1].payload["hatchery"]["temp"]
    assert temp["available"] is True and temp["ratedHours"] == 24.0
    assert temp["expectedHours"] == nps.expected_hatch_hours(24, 26.1)["expectedHours"]
    assert temp["expectedHours"] < 38, "the stretch is on the rated 24 h, never on the clock"


def test_next_hatch_chain_plans_on_the_plain_shelf():
    # An enriched container holds for 34 h, but the batch that loads NEXT is
    # unfed at load: the chain must plan on 24 h, not 34.
    started = _iso(NOW - timedelta(hours=2))
    plain = nps.next_hatch_suggestion(NOW, 24, None, 34, None, None, [started],
                                      chain_shelf_hours=24)
    boosted = nps.next_hatch_suggestion(NOW, 24, None, 34, None, None, [started])
    assert plain["status"] == "chained" and boosted["status"] == "chained"
    assert plain["hoursUntil"] < boosted["hoursUntil"]
    assert abs(boosted["hoursUntil"] - plain["hoursUntil"] - 10.0) < 0.1
    # Wired: the summary hands the chain the plain shelf and the payload says so.
    now = datetime.now(timezone.utc)
    entry = _v2_entry(reservoir={"volumeMl": 750, "remainingMl": 500,
                                 "mixedAt": (now - timedelta(hours=26)).isoformat(),
                                 "lastLoadEnriched": True,
                                 "enrichedAt": (now - timedelta(hours=4)).isoformat()})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_start(hass, conn, {"id": 1}))
    run(integration.websocket_nps_summary(hass, conn, {"id": 2}))
    hatchery = conn.results[-1].payload["hatchery"]
    assert hatchery["reservoir"]["shelfHours"] == 34.0
    assert hatchery["reservoir"]["plainShelfHours"] == 24.0
    assert hatchery["vesselsNeeded"] == nps.vessels_needed(24, 24), \
        "vessels-needed is structural: the plain shelf, never the boost"


# --------------------------------------------------------------------------- #
# 0.7.129 — the hand-dose plan (Reef Juice moved off the cultures onto the shelf)
# --------------------------------------------------------------------------- #
def _reef_juice(**over):
    product = _product(name="Reef Juice", brand="Reefphyto", bottleMl=250.0, remainingMl=200.0,
                       doseGuide={"light": 27, "medium": 18, "heavy": 9}, doseStocking="medium",
                       doseMl=0.0, doseEveryDays=1.0, doseNote="At dusk, skimmer off.", lastDosedAt="")
    product.update(over)
    return product


def test_hand_dose_guide_reads_the_stocking_band_off_the_tank_volume():
    rj = _reef_juice()
    assert nps.hand_dose_guide(rj, 52) == {"available": True, "ml": 2.9, "stocking": "medium", "perLitres": 18.0}
    assert nps.hand_dose_guide({**rj, "doseStocking": "heavy"}, 90)["ml"] == 10.0
    assert nps.hand_dose_guide({**rj, "doseStocking": "junk"}, 90)["stocking"] == "medium"
    assert nps.hand_dose_guide(rj, 0)["available"] is False and nps.hand_dose_guide(rj, 0)["ml"] is None
    assert nps.hand_dose_guide(_product(), 100)["available"] is False, "a bottle without a guide is not guided"


def test_hand_dose_state_size_cadence_and_clock():
    never = nps.hand_dose_state(_reef_juice(), NOW, 52)
    assert never["planned"] and never["ml"] == 2.9 and never["everyDays"] == 1.0
    assert never["clock"]["due"] and never["clock"]["hoursOverdue"] == 0.0, "planned but never dosed = due now"
    fresh = nps.hand_dose_state(_reef_juice(lastDosedAt=_iso(NOW - timedelta(hours=6))), NOW, 52)
    assert not fresh["clock"]["due"] and fresh["clock"]["hoursUntil"] == 18.0
    late = nps.hand_dose_state(_reef_juice(lastDosedAt=_iso(NOW - timedelta(hours=30))), NOW, 52)
    assert late["clock"]["due"] and late["clock"]["hoursOverdue"] == 6.0
    explicit = nps.hand_dose_state(_reef_juice(doseMl=5), NOW, 52)
    assert explicit["ml"] == 5.0, "the keeper's size beats the guide"
    off = nps.hand_dose_state(_reef_juice(doseEveryDays=0), NOW, 52)
    assert off["planned"] is False and off["clock"]["available"] is False, "no size, no cadence = no plan"
    plain = nps.hand_dose_state(_product(doseMl=3, doseEveryDays=2, lastDosedAt=_iso(NOW - timedelta(days=1))), NOW, None)
    assert plain["planned"] and plain["ml"] == 3.0 and plain["clock"]["hoursUntil"] == 24.0
    state = nps.consumable_state(_reef_juice(), NOW, 52)
    assert state["handDose"]["ml"] == 2.9
    shelf = nps.shelf_summary({"rj": _reef_juice(), "p": _product()}, NOW, 52)
    assert shelf["doseDueCount"] == 1 and shelf["products"]["p"]["handDose"]["planned"] is False


def test_normalise_hand_dose_plan_and_the_reef_juice_migration():
    config = integration._normalise_core_config({
        "consumables": {"products": {
            "rj": {"name": "Reef Juice", "bottleMl": 250, "doseMl": "junk", "doseEveryDays": 999,
                   "doseStocking": "purple", "doseGuide": {"light": 27, "medium": -1, "heavy": "x", "extra": 4},
                   "doseNote": "n" * 300, "lastDosedAt": _iso(NOW)},
            "plain": {"name": "Pods"},
        }},
    })
    rj = config["consumables"]["products"]["rj"]
    assert rj["doseMl"] == 0 and rj["doseEveryDays"] == 60 and rj["doseStocking"] == "medium"
    assert rj["doseGuide"] == {"light": 27} and len(rj["doseNote"]) == 200 and rj["lastDosedAt"] == _iso(NOW)
    plain = config["consumables"]["products"]["plain"]
    assert plain["doseGuide"] == {} and plain["doseEveryDays"] == 0 and plain["lastDosedAt"] == ""
    # A 0.7.128 config: the cultures block carried the plan and the panel had
    # seeded culture_phyto_dose. Both land on the shelf, once.
    legacy = integration._normalise_core_config({
        "nps": {"cultures": {"phytoDose": {"productId": "rj", "cadenceDays": 2, "stocking": "heavy",
                                            "doseMl": 0, "lastDosedAt": _iso(NOW - timedelta(days=1))}}},
        "consumables": {"products": {"rj": {"name": "Reef Juice", "bottleMl": 250}}},
        "maintenance": {"tasks": {"culture_phyto_dose": {"label": "Dose phyto", "cadenceDays": 2, "criticalAfterDays": 4}},
                        "completions": {"culture_phyto_dose": [{"id": "x", "timestamp": _iso(NOW - timedelta(days=1)), "notes": ""}]}},
    })
    rj = legacy["consumables"]["products"]["rj"]
    assert rj["doseEveryDays"] == 2 and rj["doseStocking"] == "heavy" and rj["lastDosedAt"] == _iso(NOW - timedelta(days=1))
    assert rj["doseGuide"] == {"light": 27, "medium": 18, "heavy": 9} and rj["doseNote"]
    assert "phytoDose" not in legacy["nps"]["cultures"]
    assert "culture_phyto_dose" not in legacy["maintenance"]["tasks"] and legacy["maintenance"]["tasks"]["nps_dose_rj"]["cadenceDays"] == 2
    assert legacy["maintenance"]["completions"]["nps_dose_rj"] and "culture_phyto_dose" not in legacy["maintenance"]["completions"]
    # Migrated once: a stale client re-sending the legacy block cannot undo an edit.
    again = integration._normalise_core_config({
        "nps": {"cultures": {"phytoDose": {"productId": "rj", "cadenceDays": 2, "stocking": "heavy"}}},
        "consumables": {"products": {"rj": {**rj, "doseEveryDays": 3, "doseStocking": "light"}}},
    })
    assert again["consumables"]["products"]["rj"]["doseEveryDays"] == 3 and again["consumables"]["products"]["rj"]["doseStocking"] == "light"


def test_ws_log_dose_without_ml_uses_the_plan_and_keeps_the_reminder():
    entry = _entry({"rj": _reef_juice()})
    cfg = entry.options[CONF_SETTINGS]
    cfg["tank"] = {"volumeLitres": 52}
    cfg["maintenance"] = {"tasks": {"nps_dose_rj": {"label": "Dose Reef Juice by hand", "cadenceDays": 1, "snoozedUntil": "2099-01-01T00:00:00+00:00"}},
                          "completions": {}}
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_summary(hass, conn, {"id": 1}))
    plan = conn.results[-1].payload["shelf"]["products"]["rj"]["handDose"]
    assert plan["ml"] == 2.9 and plan["clock"]["due"] and conn.results[-1].payload["shelf"]["doseDueCount"] == 1
    run(integration.websocket_consumable_log_dose(hass, conn, {"id": 2, "product_id": "rj"}))
    assert not conn.errors
    saved = _saved_products(entry)["rj"]
    assert saved["remainingMl"] == 197.1 and saved["history"][-1] == {"at": saved["history"][-1]["at"], "ml": 2.9, "kind": "dose"}
    assert saved["lastDosedAt"]
    maintenance = entry.options[CONF_SETTINGS]["maintenance"]
    assert maintenance["completions"]["nps_dose_rj"][0]["source"] == "shelf"
    assert maintenance["tasks"]["nps_dose_rj"]["snoozedUntil"] is None, "the tap clears the snooze, like the panel"
    assert any(item.get("message") == "Reef Juice dosed by hand — 2.9 ml" for item in entry.options[CONF_SETTINGS]["activity"])
    run(integration.websocket_nps_summary(hass, conn, {"id": 3}))
    plan = conn.results[-1].payload["shelf"]["products"]["rj"]["handDose"]
    assert not plan["clock"]["due"] and abs(plan["clock"]["hoursUntil"] - 24.0) < 0.2
    # An explicit ml still stamps the plan; a plan-less bottle without ml is refused.
    run(integration.websocket_consumable_log_dose(hass, conn, {"id": 4, "product_id": "rj", "ml": 1}))
    assert _saved_products(entry)["rj"]["remainingMl"] == 196.1
    entry2 = _entry({"p": _product()})
    hass2 = FakeHass(entries=[entry2])
    conn2 = FakeConnection()
    run(integration.websocket_consumable_log_dose(hass2, conn2, {"id": 5, "product_id": "p"}))
    assert conn2.error_codes == ["no_dose_size"]


def test_hand_dose_stamp_survives_a_stale_save_and_leaves_with_the_bottle():
    stored = {"consumables": {"products": {"rj": _reef_juice(remainingMl=197.1, lastDosedAt=_iso(NOW),
                                                             history=[{"at": _iso(NOW), "ml": 2.9, "kind": "dose"}])}}}
    incoming = _deepcopy(stored)
    incoming["consumables"]["products"]["rj"].update({"remainingMl": 200.0, "lastDosedAt": "", "history": [], "doseEveryDays": 3})
    integration._nps_preserve_runtime(stored, incoming)
    rj = incoming["consumables"]["products"]["rj"]
    assert rj["lastDosedAt"] == _iso(NOW) and rj["remainingMl"] == 197.1 and rj["doseEveryDays"] == 3
    entry = _entry({"rj": _reef_juice()})
    entry.options[CONF_SETTINGS]["maintenance"] = {"tasks": {"nps_dose_rj": {"label": "x", "cadenceDays": 1}, "other": {"label": "y", "cadenceDays": 7}},
                                                   "completions": {"nps_dose_rj": [{"id": "a", "timestamp": _iso(NOW)}]}}
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_consumable_delete(hass, conn, {"id": 1, "product_id": "rj"}))
    assert not conn.errors
    maintenance = entry.options[CONF_SETTINGS]["maintenance"]
    assert "nps_dose_rj" not in maintenance["tasks"] and "nps_dose_rj" not in maintenance["completions"] and "other" in maintenance["tasks"]


def test_the_reef_juice_preset_carries_its_plan():
    rj = next(item for item in nps.PRODUCT_LIBRARY if item["name"].startswith("Reef Juice"))
    assert rj["doseGuide"] == {"light": 27, "medium": 18, "heavy": 9} and rj["doseEveryDays"] == 1 and rj["doseNote"]
    assert all("doseGuide" not in item for item in nps.PRODUCT_LIBRARY if not item["name"].startswith("Reef Juice"))



# --- Feed timeline v2 (doc §13): the slot model, the skip, the late log, the strip.

def _tl(now_local, **kw):
    kw.setdefault("products", {})
    kw.setdefault("channels", {})
    return nps.feed_timeline(now_local, **kw)


def _by_id(timeline, prefix):
    return [e for e in timeline["events"] if e["id"].startswith(prefix)]


def test_hand_dose_slots_derive_from_the_cadence():
    hourly = nps.hand_dose_slots(_product(doseEveryHours=6, doseFirstAt="08:00"))
    assert hourly["unit"] == "hours" and hourly["perDay"] == 4 and hourly["slots"] == [2 * 60, 8 * 60, 14 * 60, 20 * 60]
    assert hourly["text"] == "every 6 h from 08:00 · 4 a day"
    odd = nps.hand_dose_slots(_product(doseEveryHours=5, doseFirstAt="08:00"))
    assert odd["perDay"] == 4 and odd["slots"] == [8 * 60, 13 * 60, 18 * 60, 23 * 60], "restarts at the anchor each day — no drift"
    chips = nps.hand_dose_slots(_product(doseEveryHours=12))
    assert chips["perDay"] == 2 and chips["slots"] == [] and chips["firstAt"] == "", "no anchor = any-time chips"
    daily = nps.hand_dose_slots(_product(doseEveryDays=2, doseFirstAt="20:30"))
    assert daily["unit"] == "days" and daily["perDay"] == 1 and daily["slots"] == [20 * 60 + 30] and daily["text"] == "every 2 days at 20:30"
    none = nps.hand_dose_slots(_product())
    assert none["unit"] == "" and none["perDay"] == 0
    both = nps.hand_dose_slots(_product(doseEveryDays=3, doseEveryHours=8))
    assert both["unit"] == "hours", "hours outrank days when both are set"


def test_hand_dose_clock_snaps_to_the_anchored_slot_and_stays_in_lockstep():
    tz = timezone.utc
    # Every day at 08:00, dosed yesterday 20:00 -> due today 08:00, not 20:00.
    dosed = datetime(2026, 8, 12, 20, 0, tzinfo=tz)
    state = nps.hand_dose_state(_product(doseMl=3, doseEveryDays=1, doseFirstAt="08:00", lastDosedAt=_iso(dosed)), NOW, None, tz)
    assert state["clock"]["at"] == _iso(datetime(2026, 8, 13, 8, 0, tzinfo=tz)) and state["clock"]["due"]
    assert state["cadenceText"] == "every day at 08:00" and state["slots"] == ["08:00"]
    # Dosed early today (07:00) -> tomorrow 08:00, the day cadence gates the day.
    early = nps.hand_dose_state(_product(doseMl=3, doseEveryDays=1, doseFirstAt="08:00",
                                         lastDosedAt=_iso(datetime(2026, 8, 13, 7, 0, tzinfo=tz))), NOW, None, tz)
    assert early["clock"]["at"] == _iso(datetime(2026, 8, 14, 8, 0, tzinfo=tz)) and early["clock"]["hoursUntil"] == 20.0
    # Every 6 h from 08:00, dosed 08:10 -> next 14:00 (snapped, not 14:10).
    hourly = nps.hand_dose_state(_product(doseMl=1, doseEveryHours=6, doseFirstAt="08:00",
                                          lastDosedAt=_iso(datetime(2026, 8, 13, 8, 10, tzinfo=tz))), NOW, None, tz)
    assert hourly["clock"]["at"] == _iso(datetime(2026, 8, 13, 14, 0, tzinfo=tz)) and hourly["clock"]["hoursUntil"] == 2.0
    assert hourly["everyHours"] == 6.0 and hourly["everyDays"] == 0.0 and hourly["slotsPerDay"] == 4
    # A dose between slots owns the nearer one: 10:59 -> 14:00, 11:01 -> 20:00.
    mid = nps.hand_dose_state(_product(doseMl=1, doseEveryHours=6, doseFirstAt="08:00",
                                       lastDosedAt=_iso(datetime(2026, 8, 13, 10, 59, tzinfo=tz))), NOW, None, tz)
    assert mid["clock"]["at"] == _iso(datetime(2026, 8, 13, 14, 0, tzinfo=tz))
    # No anchor = plain arithmetic (the 0.7.129 contract holds).
    plain = nps.hand_dose_state(_product(doseMl=1, doseEveryHours=6, lastDosedAt=_iso(NOW - timedelta(hours=2))), NOW, None, tz)
    assert plain["clock"]["hoursUntil"] == 4.0
    # Late in the day past the last slot -> wraps to tomorrow's first.
    late = nps.hand_dose_state(_product(doseMl=1, doseEveryHours=6, doseFirstAt="08:00",
                                        lastDosedAt=_iso(datetime(2026, 8, 13, 20, 5, tzinfo=tz))), NOW, None, tz)
    assert late["clock"]["at"] == _iso(datetime(2026, 8, 14, 2, 0, tzinfo=tz))
    # A skip holds the cadence: never dosed but skipped at NOW -> next slot, not "due now".
    skipped = nps.hand_dose_state(_product(doseMl=3, doseEveryDays=1, doseFirstAt="08:00", doseSkippedAt=_iso(NOW)), NOW, None, tz)
    assert not skipped["clock"]["due"] and skipped["clock"]["at"] == _iso(datetime(2026, 8, 14, 8, 0, tzinfo=tz))
    assert skipped["lastAt"] == "" and skipped["skippedAt"] == _iso(NOW), "the real last dose stays untouched"


def test_normalise_hours_cadence_anchor_and_skip_stamp():
    config = integration._normalise_core_config({"consumables": {"products": {
        "p": {"name": "Phyto", "doseEveryHours": 99, "doseFirstAt": "25:99", "doseSkippedAt": "x" * 80},
        "q": {"name": "Pods", "doseEveryHours": 6, "doseFirstAt": "8:5"},
    }}})
    p = config["consumables"]["products"]["p"]
    assert p["doseEveryHours"] == 24 and p["doseFirstAt"] == "" and len(p["doseSkippedAt"]) == 40
    q = config["consumables"]["products"]["q"]
    assert q["doseEveryHours"] == 6 and q["doseFirstAt"] == "08:05"
    # The skip stamp is server-written: a stale save must not clobber a newer one.
    stored = {"consumables": {"products": {"p": _product(doseSkippedAt=_iso(NOW))}}}
    incoming = _deepcopy(stored)
    incoming["consumables"]["products"]["p"]["doseSkippedAt"] = ""
    integration._nps_preserve_runtime(stored, incoming)
    assert incoming["consumables"]["products"]["p"]["doseSkippedAt"] == _iso(NOW)


def test_ws_skip_dose_holds_the_cadence_and_snoozes_the_reminder():
    entry = _entry({"rj": _reef_juice(doseFirstAt="20:00")})
    cfg = entry.options[CONF_SETTINGS]
    cfg["tank"] = {"volumeLitres": 52}
    cfg["maintenance"] = {"tasks": {"nps_dose_rj": {"label": "Dose Reef Juice by hand", "cadenceDays": 1}}, "completions": {}}
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_consumable_skip_dose(hass, conn, {"id": 1, "product_id": "rj"}))
    assert not conn.errors
    saved = _saved_products(entry)["rj"]
    assert saved["doseSkippedAt"] and saved["lastDosedAt"] == "" and saved["remainingMl"] == 200.0 and saved["history"] == []
    maintenance = entry.options[CONF_SETTINGS]["maintenance"]
    comp = maintenance["completions"]["nps_dose_rj"][0]
    assert comp["skipped"] is True and comp["source"] == "shelf"
    assert maintenance["tasks"]["nps_dose_rj"]["snoozedUntil"], "the reminder sleeps until the engine's next slot"
    run(integration.websocket_nps_summary(hass, conn, {"id": 2}))
    plan = conn.results[-1].payload["shelf"]["products"]["rj"]["handDose"]
    assert not plan["clock"]["due"] and plan["clock"]["at"] == maintenance["tasks"]["nps_dose_rj"]["snoozedUntil"], "one clock, two readers"
    # No cadence = nothing to skip.
    entry2 = _entry({"p": _product(doseMl=2)})
    conn2 = FakeConnection()
    run(integration.websocket_consumable_skip_dose(FakeHass(entries=[entry2]), conn2, {"id": 3, "product_id": "p"}))
    assert conn2.error_codes == ["no_plan"]


def test_ws_log_dose_late_stamps_when_it_happened():
    entry = _entry({"rj": _reef_juice(doseMl=3)})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    earlier = datetime.now(timezone.utc) - timedelta(hours=3)
    run(integration.websocket_consumable_log_dose(hass, conn, {"id": 1, "product_id": "rj", "at": _iso(earlier)}))
    assert not conn.errors
    saved = _saved_products(entry)["rj"]
    assert saved["history"][-1]["at"] == _iso(earlier) and saved["lastDosedAt"] == _iso(earlier) and saved["remainingMl"] == 197.0
    # A later real dose keeps lastDosedAt at the newest stamp even if a back-dated one follows.
    run(integration.websocket_consumable_log_dose(hass, conn, {"id": 2, "product_id": "rj"}))
    newest = _saved_products(entry)["rj"]["lastDosedAt"]
    run(integration.websocket_consumable_log_dose(hass, conn, {"id": 3, "product_id": "rj", "at": _iso(earlier - timedelta(hours=1))}))
    saved = _saved_products(entry)["rj"]
    assert saved["lastDosedAt"] == newest and [h["at"] for h in saved["history"]] == sorted(h["at"] for h in saved["history"]), "history stays in time order"
    # Future or ancient stamps are refused.
    for bad in (_iso(datetime.now(timezone.utc) + timedelta(minutes=5)), _iso(datetime.now(timezone.utc) - timedelta(days=2)), "junk"):
        c = FakeConnection()
        run(integration.websocket_consumable_log_dose(hass, c, {"id": 9, "product_id": "rj", "at": bad}))
        assert c.error_codes == ["bad_stamp"], bad


def test_feed_timeline_pumps_hand_slots_and_the_ladder():
    tz = timezone.utc
    now = datetime(2026, 8, 13, 14, 20, tzinfo=tz)  # 14:20
    channels = {
        "phyto": {"name": "Phyto pump", "chemical": "food", "enabled": True,
                  "reservoir": {"productId": "phyto"},
                  "schedule": {"enabled": True, "mlPerDay": 4, "mode": "doses", "dosesPerDay": 4,
                               "windowStart": "08:00", "windowEnd": "20:00"},
                  "state": {"lastDoseAt": _iso(datetime(2026, 8, 13, 12, 31, tzinfo=tz))}},
        "cont": {"name": "Drip", "chemical": "livefood", "enabled": True,
                 "schedule": {"enabled": True, "mlPerDay": 50, "mode": "continuous",
                              "windowStart": "22:00", "windowEnd": "06:00"}},
        "alk": {"name": "Alk", "chemical": "alk", "schedule": {"enabled": True, "mlPerDay": 20, "mode": "doses", "dosesPerDay": 4}},
    }
    products = {
        "phyto": _product(name="Phyto"),
        # Every 6 h from 08:00: 08:00 done (logged 08:12), 14:00 due (20 min ago), 20:00 planned, 02:00 missed (successor due).
        "pods": _product(name="Pods", doseMl=2, doseEveryHours=6, doseFirstAt="08:00",
                         history=[{"at": _iso(datetime(2026, 8, 13, 8, 12, tzinfo=tz)), "ml": 2, "kind": "dose"},
                                  {"at": _iso(datetime(2026, 8, 12, 8, 0, tzinfo=tz)), "ml": 2, "kind": "dose"}],
                         lastDosedAt=_iso(datetime(2026, 8, 13, 8, 12, tzinfo=tz))),
        # Every day at 09:00, never dosed -> late (days cadence never goes red).
        "rj": _reef_juice(doseMl=3, doseFirstAt="09:00"),
        # Every 2 days at 20:00, dosed yesterday -> ghost today.
        "ghost": _product(name="Amino", doseMl=1, doseEveryDays=2, doseFirstAt="20:00",
                          lastDosedAt=_iso(datetime(2026, 8, 12, 20, 0, tzinfo=tz))),
        # Every 12 h, no anchor -> two any-time chips; one extra logged without a plan match counts as the first.
        "chips": _product(name="Zoo", doseMl=5, doseEveryHours=12,
                          history=[{"at": _iso(datetime(2026, 8, 13, 10, 0, tzinfo=tz)), "ml": 5, "kind": "dose"}]),
        # No plan at all, but a dose logged today -> an extra done dot.
        "loose": _product(name="Loose", history=[{"at": _iso(datetime(2026, 8, 13, 11, 0, tzinfo=tz)), "ml": 4, "kind": "dose"}]),
    }
    tl = _tl(now, products=products, channels=channels,
             awc={"enabled": True, "schedule": {"enabled": True, "mode": "times", "times": ["02:00", "22:00"]}},
             lighting={"configured": True, "onTime": "09:00", "offTime": "21:00"})
    assert tl["nowMin"] == 14 * 60 + 20 and tl["night"] == {"onMin": 540, "offMin": 1260}
    pump = _by_id(tl, "channel:phyto:")
    assert [e["at"] for e in pump] == [570, 750, 930, 1110] and all(e["ml"] == 1.0 for e in pump)
    assert [e["status"] for e in pump] == ["expected", "done", "planned", "planned"], "past ticks are expected; the run stamp's nearest is done"
    assert pump[1]["doneAt"] == 12 * 60 + 31
    band = _by_id(tl, "channel:cont:")
    assert len(band) == 1 and band[0]["kind"] == "band" and band[0]["band"] == [1320, 360]
    assert not _by_id(tl, "channel:alk"), "only food pumps ride the strip"
    pods = _by_id(tl, "shelf:pods:")
    assert [(e["at"], e["status"]) for e in pods] == [(120, "missed"), (480, "done"), (840, "due"), (1200, "planned")]
    assert pods[1]["doneAt"] == 8 * 60 + 12 and pods[1]["actualMl"] == 2.0
    rj = _by_id(tl, "shelf:rj:")
    assert [(e["at"], e["status"]) for e in rj] == [(540, "late")] and rj[0]["how"] == "hand"
    ghost = _by_id(tl, "shelf:ghost:")
    assert ghost[0]["status"] == "ghost" and ghost[0]["at"] == 1200 and ghost[0]["nextDate"] == "2026-08-14"
    chips = _by_id(tl, "shelf:chips:")
    assert [e["at"] for e in chips] == [None, None] and sorted(e["status"] for e in chips) == ["done", "due"]
    loose = _by_id(tl, "shelf:loose:")
    assert loose[0]["status"] == "done" and loose[0]["unplanned"] and loose[0]["at"] == 660
    awc = _by_id(tl, "awc:")
    assert [(e["at"], e["how"], e["status"]) for e in awc] == [(120, "system", "expected"), (1320, "system", "planned")]
    # Sorted: timed first by minute, bands and chips after.
    ats = [e["at"] for e in tl["events"] if e["kind"] == "dose" and e["at"] is not None]
    assert ats == sorted(ats)
    assert tl["events"][-1]["kind"] == "band"
    # Next: the due/late ones first (0 min), then the soonest planned.
    assert tl["next"][0]["minutesUntil"] == 0 and len(tl["next"]) == 3
    assert tl["counts"]["pump"] == 4 and tl["counts"]["missed"] == 1 and tl["counts"]["late"] == 1 and tl["counts"]["extra"] == 1
    assert tl["text"].startswith("12 feeds today — 4 pumped (Phyto pump), 8 by hand ("), tl["text"]
    assert "1 missed" in tl["text"] and "Set a first-dose time" in tl["text"], tl["text"]


def test_feed_timeline_skip_carried_overdue_and_the_zero_states():
    tz = timezone.utc
    now = datetime(2026, 8, 13, 14, 20, tzinfo=tz)
    # Skipped today: every slot left open reads skipped; the logged one stays done.
    skipped = _product(name="Skip", doseMl=1, doseEveryHours=8, doseFirstAt="06:00",
                       doseSkippedAt=_iso(datetime(2026, 8, 13, 14, 0, tzinfo=tz)),
                       history=[{"at": _iso(datetime(2026, 8, 13, 6, 5, tzinfo=tz)), "ml": 1, "kind": "dose"}])
    # Overdue since Tuesday (every day at 20:00, last dosed Monday) -> due now, not planned for 20:00.
    carried = _product(name="Carried", doseMl=1, doseEveryDays=1, doseFirstAt="20:00",
                       lastDosedAt=_iso(datetime(2026, 8, 10, 20, 0, tzinfo=tz)))
    tl = _tl(now, products={"s": skipped, "c": carried})
    assert [e["status"] for e in _by_id(tl, "shelf:s:")] == ["done", "skipped", "skipped"]
    c = _by_id(tl, "shelf:c:")
    assert c[0]["status"] == "due" and c[0]["at"] == 1200 and c[0]["note"].startswith("overdue since")
    # Nothing at all.
    empty = _tl(now)
    assert empty["events"] == [] and empty["next"] == [] and empty["text"].startswith("Nothing scheduled")
    # A days-cadence slot past its time is late, never missed, right up to midnight.
    late_day = _tl(datetime(2026, 8, 13, 23, 59, tzinfo=tz),
                   products={"rj": _reef_juice(doseMl=3, doseFirstAt="09:00")})
    assert _by_id(late_day, "shelf:rj:")[0]["status"] == "late"
    # Local-day bucketing: a dose logged 23:30 UTC yesterday is TODAY in UTC+2.
    east = timezone(timedelta(hours=2))
    stamped = _product(name="East", doseMl=1, doseEveryDays=1,
                       history=[{"at": _iso(datetime(2026, 8, 12, 23, 30, tzinfo=timezone.utc)), "ml": 1, "kind": "dose"}],
                       lastDosedAt=_iso(datetime(2026, 8, 12, 23, 30, tzinfo=timezone.utc)))
    tl_east = _tl(datetime(2026, 8, 13, 10, 0, tzinfo=east), products={"e": stamped})
    e = _by_id(tl_east, "shelf:e:")
    assert e[0]["status"] == "done" and e[0]["doneAt"] == 90, e


def test_feed_timeline_cultures_and_hand_brine():
    tz = timezone.utc
    now = datetime(2026, 8, 13, 14, 20, tzinfo=tz)
    cultures = {"enabled": True, "jars": {
        "pods": {"name": "Pod tub", "species": "copepod_tisbe",
                 "state": {"startedAt": _iso(now - timedelta(days=40)), "lastHarvestAt": _iso(now - timedelta(days=11))},
                 "cadence": {"harvestIntervalDays": 10},
                 "history": [{"event": "harvest", "at": _iso(datetime(2026, 8, 13, 9, 0, tzinfo=tz)), "ml": 300}]},
        "rots": {"name": "Cone", "species": "rotifer_L",
                 "state": {"startedAt": _iso(now - timedelta(days=20)), "lastHarvestAt": _iso(now - timedelta(days=2))},
                 "cadence": {"harvestIntervalDays": 1},
                 "history": [{"event": "harvest", "at": _iso(datetime(2026, 8, 13, 9, 0, tzinfo=tz)), "ml": 500}]},
    }, "bottle": {"history": [{"event": "fed_tank", "at": _iso(datetime(2026, 8, 13, 12, 0, tzinfo=tz)), "ml": 40}]}}
    hatchery = {"enabled": True, "reservoir": {"remainingMl": 400}, "fridgeBottle": {"remainingMl": 0},
                "handFeed": {"defaultDoseMl": 30, "feedsPerDay": 2}}
    feeds = [{"at": _iso(datetime(2026, 8, 13, 8, 0, tzinfo=tz)), "ml": 30}]
    tl = _tl(now, cultures=cultures, hatchery=hatchery, brine_feeds=feeds,
             culture_bottle_species={"rotifer_L"})
    pods = _by_id(tl, "culture:pods:")
    assert len(pods) == 1 and pods[0]["status"] == "done" and pods[0]["doneAt"] == 540 and pods[0]["actualMl"] == 300.0
    assert not _by_id(tl, "culture:rots"), "a rotifer harvest fills the bottle — the bottle feeds the tank"
    bottle = _by_id(tl, "cultures-bottle:")
    assert bottle[0]["status"] == "done" and bottle[0]["at"] == 720 and bottle[0]["ml"] == 40.0
    brine = _by_id(tl, "brine:")
    assert sorted(e["status"] for e in brine) == ["done", "due"] and [e["ml"] for e in brine] == [30.0, 30.0]
    assert tl["counts"]["hand"] == 4 and tl["counts"]["done"] == 3
    # With the exchange pump doing the brine, no hand chips.
    auto = _tl(now, hatchery=hatchery, brine_feeds=feeds, fx_enabled=True)
    assert not _by_id(auto, "brine:")
    # Empty container, no chips either — nothing to feed.
    dry = _tl(now, hatchery={**hatchery, "reservoir": {"remainingMl": 0}})
    assert not _by_id(dry, "brine:")


def test_ws_summary_carries_the_timeline():
    tz_now = datetime.now(timezone.utc)
    entry = _entry({"rj": _reef_juice(doseMl=3, doseFirstAt="23:59")},
                   channels={"phyto": {"name": "Phyto pump", "chemical": "food", "enabled": True,
                                       "schedule": {"enabled": True, "mlPerDay": 4, "mode": "doses", "dosesPerDay": 2,
                                                    "windowStart": "00:00", "windowEnd": "00:00"}}})
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"] = {"enabled": True, "reservoir": {"volumeMl": 1000, "remainingMl": 400, "mixedAt": _iso(tz_now)},
                              "handFeed": {"defaultDoseMl": 30, "feedsPerDay": 2},
                              "handFeeds": [{"at": _iso(tz_now), "ml": 25, "from": "container"}]}
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_summary(hass, conn, {"id": 1}))
    assert not conn.errors
    tl = conn.results[-1].payload["timeline"]
    assert set(tl) == {"date", "nowMin", "night", "events", "next", "counts", "text"}
    ids = [e["id"] for e in tl["events"]]
    assert "channel:phyto:0" in ids and "shelf:rj:0" in ids and "brine:0" in ids, ids
    brine = [e for e in tl["events"] if e["source"] == "brine"]
    assert any(e["status"] == "done" and e["actualMl"] == 25.0 for e in brine), "the hatchery's own feed log is the done mark"
    assert all(s in nps.TIMELINE_STATUSES for s in (e["status"] for e in tl["events"]))



def test_hand_feed_log_is_written_by_both_fed_buttons_and_survives_a_stale_save():
    """0.7.131: the strip's brine done-marks no longer depend on the keeper
    having synced the hatchery reminders — every Fed tap is stamped."""
    entry = _v2_entry(reservoir={"volumeMl": 500, "remainingMl": 300,
                                 "mixedAt": datetime.now(timezone.utc).isoformat()})
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"]["handFeed"] = {"defaultDoseMl": 30, "feedsPerDay": 2}
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hand_feed(hass, conn, {"id": 1}))
    assert not conn.errors
    feeds = entry.options[CONF_SETTINGS]["nps"]["hatchery"]["handFeeds"]
    assert len(feeds) == 1 and feeds[0]["ml"] == 30 and feeds[0]["from"] == "container" and feeds[0]["at"], feeds
    assert "brine_hand_feed" not in (entry.options[CONF_SETTINGS].get("maintenance") or {}).get("completions", {}), "no reminder, no completion — the log stands alone"
    # The strip reads it.
    run(integration.websocket_nps_summary(hass, conn, {"id": 2}))
    brine = [e for e in conn.results[-1].payload["timeline"]["events"] if e["source"] == "brine"]
    assert any(e["status"] == "done" and e["actualMl"] == 30.0 for e in brine), brine
    # The fridge bottle's Fed writes the same log, tagged.
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"]["fridgeBottle"] = {"volumeMl": 250, "remainingMl": 200, "mixedAt": datetime.now(timezone.utc).isoformat(),
                                             "filledAt": datetime.now(timezone.utc).isoformat()}
    run(integration.websocket_nps_fridge_bottle(hass, conn, {"id": 3, "action": "feed", "ml": 20}))
    assert not conn.errors, conn.errors
    feeds = entry.options[CONF_SETTINGS]["nps"]["hatchery"]["handFeeds"]
    assert feeds[0]["from"] == "bottle" and feeds[0]["ml"] == 20 and len(feeds) == 2, feeds
    # A stale panel save (no log) must not lose either; a union keeps both, newest first.
    stored = {"nps": {"hatchery": {"handFeeds": list(feeds)}}}
    incoming = {"nps": {"hatchery": {"handFeeds": [{"at": "2020-01-01T00:00:00+00:00", "ml": 5, "from": "container"}]}}}
    integration._nps_preserve_runtime(stored, incoming)
    merged = incoming["nps"]["hatchery"]["handFeeds"]
    assert [f["ml"] for f in merged] == [20, 30, 5], merged
    # The normaliser caps and cleans it.
    config = integration._normalise_core_config({"nps": {"enabled": True, "hatchery": {"handFeeds": [{"at": "x", "ml": 1}, {"ml": 2}, {"at": "y", "ml": -3, "from": "junk"}]}}})
    assert config["nps"]["hatchery"]["handFeeds"] == [{"at": "x", "ml": 1, "from": "container"}, {"at": "y", "ml": 0, "from": "container"}]


def test_ws_undo_dose_takes_back_a_mis_tap_within_the_window():
    now = datetime.now(timezone.utc)
    entry = _entry({"rj": _reef_juice(doseMl=3, doseFirstAt="20:00")})
    cfg = entry.options[CONF_SETTINGS]
    cfg["maintenance"] = {"tasks": {"nps_dose_rj": {"label": "Dose Reef Juice by hand", "cadenceDays": 1}}, "completions": {}}
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    # Nothing logged yet: nothing to undo.
    run(integration.websocket_consumable_undo_dose(hass, conn, {"id": 0, "product_id": "rj"}))
    assert conn.error_codes == ["nothing_to_undo"]
    conn = FakeConnection()
    earlier = _iso(now - timedelta(hours=5))
    run(integration.websocket_consumable_log_dose(hass, conn, {"id": 1, "product_id": "rj", "at": earlier}))
    run(integration.websocket_consumable_log_dose(hass, conn, {"id": 2, "product_id": "rj"}))
    assert not conn.errors
    saved = _saved_products(entry)["rj"]
    assert saved["remainingMl"] == 194.0 and len(saved["history"]) == 2 and saved["lastDosedAt"] != earlier
    assert len(entry.options[CONF_SETTINGS]["maintenance"]["completions"]["nps_dose_rj"]) == 2
    # The plan advertises the undo.
    run(integration.websocket_nps_summary(hass, conn, {"id": 3}))
    undo = conn.results[-1].payload["shelf"]["products"]["rj"]["handDose"]["undo"]
    assert undo["available"] and undo["ml"] == 3.0 and undo["at"] == saved["lastDosedAt"] and 9 <= undo["minutesLeft"] <= 10, undo
    # Undo: the ml goes back, the row goes, the clock falls back to the earlier dose, the completion goes.
    run(integration.websocket_consumable_undo_dose(hass, conn, {"id": 4, "product_id": "rj"}))
    assert not conn.errors, conn.errors
    saved = _saved_products(entry)["rj"]
    assert saved["remainingMl"] == 197.0 and len(saved["history"]) == 1 and saved["history"][0]["at"] == earlier
    assert saved["lastDosedAt"] == earlier
    comps = entry.options[CONF_SETTINGS]["maintenance"]["completions"]["nps_dose_rj"]
    assert len(comps) == 1 and comps[0]["timestamp"] == earlier
    assert any(item.get("message") == "Reef Juice hand dose undone — 3 ml back in the bottle" for item in entry.options[CONF_SETTINGS]["activity"])
    # The earlier dose is outside the window: nothing more to undo.
    conn = FakeConnection()
    run(integration.websocket_consumable_undo_dose(hass, conn, {"id": 5, "product_id": "rj"}))
    assert conn.error_codes == ["nothing_to_undo"]
    # A pump debit is never undoable, and the ml never overfills the bottle.
    pumped = _product(bottleMl=100, remainingMl=99, history=[{"at": _iso(now), "ml": 5, "kind": "pump"}])
    assert not nps.hand_dose_undo(pumped, now)["available"]
    entry2 = _entry({"p": _product(bottleMl=100, remainingMl=99, doseMl=5, history=[{"at": _iso(now), "ml": 5, "kind": "dose"}], lastDosedAt=_iso(now))})
    conn2 = FakeConnection()
    run(integration.websocket_consumable_undo_dose(FakeHass(entries=[entry2]), conn2, {"id": 6, "product_id": "p"}))
    assert not conn2.errors and _saved_products(entry2)["p"]["remainingMl"] == 100.0 and _saved_products(entry2)["p"]["lastDosedAt"] == ""



def test_normalise_drops_a_feed_exchange_link_to_a_channel_that_is_gone():
    """Reece's live catch (0.7.132): a stale channelId left the settings select
    on its placeholder while the panel believed a pump was bound — and never
    seeded the hand-feed reminder."""
    stale = integration._normalise_core_config({
        "nps": {"enabled": True, "feedExchange": {"enabled": True, "channelId": "ghost_pump"}},
        "dosing": {"channels": {}}})
    fx = stale["nps"]["feedExchange"]
    assert fx["channelId"] == "" and fx["enabled"] is False, fx
    live = integration._normalise_core_config({
        "nps": {"enabled": True, "feedExchange": {"enabled": True, "channelId": "brine"}},
        "dosing": {"channels": {"brine": {"name": "Live brine", "chemical": "livefood"}}}})
    assert live["nps"]["feedExchange"] == {**live["nps"]["feedExchange"], "channelId": "brine", "enabled": True}
    # No dosing block at all (a hand-feeder's config) — same answer: no link.
    bare = integration._normalise_core_config({"nps": {"enabled": True, "feedExchange": {"channelId": "brine"}}})
    assert bare["nps"]["feedExchange"]["channelId"] == ""



def test_feed_timeline_keeps_soak_and_jar_bottles_off_the_strip():
    """Selcon into the soak and phyto into a jar are logged as bottle doses,
    but they are not tank feeds (Reece's strip showed a Selcon dot)."""
    tz = timezone.utc
    now = datetime(2026, 8, 13, 14, 20, tzinfo=tz)
    row = [{"at": _iso(datetime(2026, 8, 13, 1, 19, tzinfo=tz)), "ml": 0.5, "kind": "dose"}]
    products = {"selcon": _product(name="Selcon", history=row),
                "jarphyto": _product(name="Jar phyto", history=row, doseMl=2, doseEveryDays=1, doseFirstAt="09:00")}
    loud = _tl(now, products=products)
    assert _by_id(loud, "shelf:selcon:") and _by_id(loud, "shelf:jarphyto:")[0]["status"] == "done", "without the link they are just doses"
    quiet = _tl(now, products=products, quiet_product_ids={"selcon", "jarphyto"})
    assert not _by_id(quiet, "shelf:selcon:"), "the soak bottle stays off the strip"
    jar = _by_id(quiet, "shelf:jarphyto:")
    assert [e["id"] for e in jar] == ["shelf:jarphyto:0"] and jar[0]["status"] == "late", "a keeper-set tank cadence still lands its slot; the jar dose is not its done mark"
    # The summary wires the links up.
    entry = _entry({"selcon": _product(name="Selcon", history=[{"at": _iso(datetime.now(timezone.utc)), "ml": 0.5, "kind": "dose"}])})
    cfg = entry.options[CONF_SETTINGS]
    cfg["nps"]["hatchery"] = {"enabled": True, "enrichment": {"productId": "selcon"}}
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_summary(hass, conn, {"id": 1}))
    assert not any(e["productId"] == "selcon" for e in conn.results[-1].payload["timeline"]["events"])



def test_spread_slots_and_the_times_a_day_unit():
    assert nps.spread_slots(3, "11:00", "21:00") == [11 * 60, 16 * 60, 21 * 60], "3 feeds 11–21 = 11:00, 16:00, 21:00"
    assert nps.spread_slots(2, "08:00", "20:00") == [8 * 60, 20 * 60]
    assert nps.spread_slots(1, "11:00", "21:00") == [11 * 60], "one feed = the window start"
    assert nps.spread_slots(3, "08:00") == [0, 8 * 60, 16 * 60], "no end = spread across 24 h from the start"
    assert nps.spread_slots(3, "22:00", "04:00") == [60, 4 * 60, 22 * 60], "a window across midnight"
    assert nps.spread_slots(3, "", "21:00") == [] and nps.spread_slots(0, "11:00", "21:00") == []
    cad = nps.hand_dose_slots(_product(doseTimesPerDay=3, doseFirstAt="11:00", doseWindowEnd="21:00"))
    assert cad["unit"] == "perDay" and cad["perDay"] == 3 and cad["slots"] == [660, 960, 1260] and cad["text"] == "3 a day, 11:00–21:00"
    assert nps.hand_dose_slots(_product(doseTimesPerDay=2, doseFirstAt="09:00"))["text"] == "2 a day from 09:00"
    assert nps.hand_dose_slots(_product(doseTimesPerDay=1))["text"] == "once a day" and nps.hand_dose_slots(_product(doseTimesPerDay=2))["slots"] == []
    assert nps.hand_dose_slots(_product(doseTimesPerDay=3, doseEveryHours=6, doseEveryDays=1))["unit"] == "perDay", "times a day outranks the rest"
    # The clock walks the uneven window: dosed 11:10 -> 16:00; dosed 21:05 -> tomorrow 11:00; dosed 13:31 (nearer 16:00) -> 21:00.
    tz = timezone.utc
    plan = lambda h, m: nps.hand_dose_state(_product(doseMl=250, doseTimesPerDay=3, doseFirstAt="11:00", doseWindowEnd="21:00",
                                                     lastDosedAt=_iso(datetime(2026, 8, 13, h, m, tzinfo=tz))), NOW, None, tz)
    assert plan(11, 10)["clock"]["at"] == _iso(datetime(2026, 8, 13, 16, 0, tzinfo=tz))
    assert plan(21, 5)["clock"]["at"] == _iso(datetime(2026, 8, 14, 11, 0, tzinfo=tz))
    assert plan(13, 31)["clock"]["at"] == _iso(datetime(2026, 8, 13, 21, 0, tzinfo=tz))
    state = plan(11, 10)
    assert state["timesPerDay"] == 3 and state["windowEnd"] == "21:00" and state["everyDays"] == 0.0 and state["cadenceText"] == "3 a day, 11:00–21:00"
    # No anchor: plain arithmetic at 24/n.
    chips = nps.hand_dose_state(_product(doseMl=1, doseTimesPerDay=4, lastDosedAt=_iso(NOW - timedelta(hours=2))), NOW, None, tz)
    assert chips["clock"]["hoursUntil"] == 4.0
    # The normaliser.
    config = integration._normalise_core_config({"consumables": {"products": {"p": {"name": "P", "doseTimesPerDay": 99.7, "doseWindowEnd": "21:00", "doseFirstAt": "11:00"}}},
                                                 "nps": {"enabled": True, "hatchery": {"handFeed": {"feedsPerDay": 3, "windowStart": "11:00", "windowEnd": "9pm"}},
                                                         "cultures": {"bottle": {"feedsPerDay": 2, "windowStart": "10:00", "windowEnd": "18:00"}}}})
    p = config["consumables"]["products"]["p"]
    assert p["doseTimesPerDay"] == 24 and p["doseWindowEnd"] == "21:00"
    hand = config["nps"]["hatchery"]["handFeed"]
    assert hand["windowStart"] == "11:00" and hand["windowEnd"] == "", "junk end = spread across the day"
    bottle = config["nps"]["cultures"]["bottle"]
    assert bottle["feedsPerDay"] == 2 and bottle["windowStart"] == "10:00" and bottle["windowEnd"] == "18:00"


def test_feed_timeline_windows_for_the_shelf_the_brine_and_the_bottle():
    tz = timezone.utc
    now = datetime(2026, 8, 13, 16, 40, tzinfo=tz)   # 16:40
    # Shelf: 3 a day 11–21, 11:00 logged at 11:08; 16:00 is 40 min past -> late (its successor 21:00 isn't due); 21:00 planned.
    products = {"rj": _product(name="Reef Juice", doseMl=3, doseTimesPerDay=3, doseFirstAt="11:00", doseWindowEnd="21:00",
                               history=[{"at": _iso(datetime(2026, 8, 13, 11, 8, tzinfo=tz)), "ml": 3, "kind": "dose"}],
                               lastDosedAt=_iso(datetime(2026, 8, 13, 11, 8, tzinfo=tz)))}
    # Brine: 3 feeds 11–21 with one fed 11:02; the bottle: 2 a day 10–18, nothing fed yet, plus an unplanned pour at 07:00.
    hatchery = {"enabled": True, "reservoir": {"remainingMl": 400}, "fridgeBottle": {"remainingMl": 0},
                "handFeed": {"defaultDoseMl": 250, "feedsPerDay": 3, "windowStart": "11:00", "windowEnd": "21:00"}}
    feeds = [{"at": _iso(datetime(2026, 8, 13, 11, 2, tzinfo=tz)), "ml": 250}]
    cultures = {"enabled": True, "jars": {}, "bottle": {"remainingMl": 300, "doseMl": 40, "feedsPerDay": 2, "windowStart": "10:00", "windowEnd": "18:00",
                                                       "history": [{"event": "fed_tank", "at": _iso(datetime(2026, 8, 13, 7, 0, tzinfo=tz)), "ml": 40}]}}
    tl = _tl(now, products=products, hatchery=hatchery, brine_feeds=feeds, cultures=cultures, culture_bottle_species={"rotifer_L"})
    rj = _by_id(tl, "shelf:rj:")
    assert [(e["at"], e["status"]) for e in rj] == [(660, "done"), (960, "late"), (1260, "planned")], rj
    brine = _by_id(tl, "brine:")
    assert [(e["at"], e["status"]) for e in brine] == [(660, "done"), (960, "late"), (1260, "planned")] and brine[0]["doneAt"] == 662, brine
    bottle = [e for e in tl["events"] if e["source"] == "cultures-bottle"]
    # The 07:00 pour is within half the gap of the 10:00 slot, so it owns it.
    assert [(e["at"], e["status"], e["doneAt"]) for e in bottle] == [(600, "done", 420), (1080, "planned", None)], bottle
    assert bottle[0]["kind"] == "dose" and bottle[0]["name"] == "Rotifers from the bottle" and bottle[0]["ml"] == 40.0
    # A window slot goes missed once its successor is due: at 18:10 the 16:00 Reef Juice slot is still late (21:00 not due) but the bottle's 10:00 was missed at 18:00.
    later = _tl(datetime(2026, 8, 13, 21, 5, tzinfo=tz), products=products, hatchery=hatchery, brine_feeds=feeds)
    assert [(e["at"], e["status"]) for e in _by_id(later, "shelf:rj:")] == [(660, "done"), (960, "missed"), (1260, "due")]
    # No window on the brine = any-time chips, as before.
    plain = _tl(now, hatchery={**hatchery, "handFeed": {"defaultDoseMl": 250, "feedsPerDay": 2}}, brine_feeds=feeds)
    assert [e["at"] for e in _by_id(plain, "brine:")] == [None, None] and sorted(e["status"] for e in _by_id(plain, "brine:")) == ["done", "due"]
    # An empty bottle plans nothing, its pours still show.
    empty = _tl(now, cultures={**cultures, "bottle": {**cultures["bottle"], "remainingMl": 0}})
    assert [e["unplanned"] for e in empty["events"] if e["source"] == "cultures-bottle"] == [True]


# Keep this LAST: a test defined below the runner is a test that never runs.
if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok  {name}")
            except Exception as err:  # noqa: BLE001 - report every failure kind
                failures += 1
                print(f"FAIL  {name}: {type(err).__name__}: {err}")
    raise SystemExit(1 if failures else 0)
