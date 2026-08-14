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
    assert nps.hatch_prime_state("", NOW)["status"] == "unknown"


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


def test_egg_type_hours_and_normaliser():
    assert nps.egg_type_hours("decapsulated") == 16
    assert nps.egg_type_hours("nonsense") == 24        # unknown → standard
    config = integration._normalise_core_config({
        "nps": {"hatchery": {"eggType": "made_up", "hatchHours": 200}},
    })
    hatchery = config["nps"]["hatchery"]
    assert hatchery["eggType"] == "standard"
    assert hatchery["hatchHours"] == 48                # clamped
    assert hatchery["state"]["hatchStartedAt"] == ""


def test_ws_hatch_start_and_cancel():
    entry = _entry({})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_nps_hatch_start(hass, conn, {"id": 1}))
    started = entry.options[CONF_SETTINGS]["nps"]["hatchery"]["state"]["hatchStartedAt"]
    assert started, "hatch start did not stamp the clock"
    run(integration.websocket_nps_hatch_cancel(hass, conn, {"id": 2}))
    assert entry.options[CONF_SETTINGS]["nps"]["hatchery"]["state"]["hatchStartedAt"] == ""
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


def test_ws_hatch_loaded_stamps_the_hand_dose_clock():
    # Harvested without a pump: loadedAt is stamped, and the overlap case
    # (24 h hatch vs 24 h shelf) re-anchors the start reminder to DUE NOW —
    # a stale snooze must not suppress it.
    entry = _hatch_reminder_entry(hatch_hours=24,
                                  started=_iso(NOW - timedelta(hours=25)))
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    before = datetime.now(timezone.utc)
    run(integration.websocket_nps_hatch_cancel(hass, conn, {"id": 1, "harvested": True}))
    saved = entry.options[CONF_SETTINGS]
    loaded = saved["nps"]["hatchery"]["state"]["loadedAt"]
    assert loaded and datetime.fromisoformat(loaded) >= before - timedelta(seconds=5)
    assert not saved["maintenance"]["tasks"]["brine_hatch_start"].get("snoozedUntil")


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
