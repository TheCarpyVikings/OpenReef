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
    assert config["nps"] == {"enabled": False}
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
