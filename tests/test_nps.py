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
