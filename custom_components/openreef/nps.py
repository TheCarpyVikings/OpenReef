"""Automated NPS system engine — pure maths for the consumables (bottle) tracker.

Design stance (mirrors awc.py / dosing.py): everything here is a pure function of
its inputs — no Home Assistant imports, no I/O, no clocks. Orchestration (WS
handlers, dose-event decrements) lives in __init__.py.

Stage A scope: the system-wide consumables engine. A "product" is a bottle the
user owns (phyto, zooplankton blend, bacteria, 2-part...) with a size, a live
remaining ledger, an opened-shelf-life clock, and a usage history. The engine
grades each bottle (runway, low, expiry) and builds the food-shelf summary the
NPS tab renders. Later stages add feed plans, the brine feed-exchange planner,
species plans, and the nutrient budget.

Honesty rules (the AWC tradition): runway is a dead-reckoned forecast from the
logged usage window — no usage history means no forecast, never a guess. Expiry
is opt-in per product (shelfLifeDaysOpened 0 = shelf-stable) and fail-closed the
same way dosing.freshness_state is: an expiring product with no openedAt stamp
counts as expired — never trust food of unknown age.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .awc import _f, _parse_iso

RUNWAY_WINDOW_DAYS = 14        # usage averaging window for days-left forecasts
LOW_PERCENT_DEFAULT = 10.0     # lowThresholdMl 0 = auto ⇒ this % of the bottle
AGING_FRACTION = 0.25          # final quarter of shelf life ⇒ "aging" (dosing parity)

# Seed library from the 2026-08 NPS research sweep (docs/nps-system-brainstorm.md
# §3): real products with handling metadata. The panel offers these as one-tap
# presets; everything stays user-editable, and "custom" is always available.
# particleUm ranges feed the Stage D species/particle matcher.
PRODUCT_LIBRARY: tuple[dict[str, Any], ...] = (
    {"name": "Live phytoplankton blend", "brand": "AlgaeBarn OceanMagik", "category": "phyto",
     "bottleMl": 946, "shelfLifeDaysOpened": 28, "refrigerated": True, "stirDaily": True,
     "particleUmMin": 1, "particleUmMax": 10},
    {"name": "Phyto-Feast", "brand": "Reef Nutrition", "category": "phyto",
     "bottleMl": 177, "shelfLifeDaysOpened": 42, "refrigerated": True, "stirDaily": True,
     "particleUmMin": 1, "particleUmMax": 20},
    {"name": "Oyster-Feast", "brand": "Reef Nutrition", "category": "zooPrepared",
     "bottleMl": 177, "shelfLifeDaysOpened": 42, "refrigerated": True, "stirDaily": False,
     "particleUmMin": 1, "particleUmMax": 200},
    {"name": "Roti-Feast", "brand": "Reef Nutrition", "category": "zooPrepared",
     "bottleMl": 177, "shelfLifeDaysOpened": 42, "refrigerated": True, "stirDaily": False,
     "particleUmMin": 150, "particleUmMax": 300},
    {"name": "R.O.E. (oyster eggs)", "brand": "Reef Nutrition", "category": "zooPrepared",
     "bottleMl": 177, "shelfLifeDaysOpened": 42, "refrigerated": True, "stirDaily": False,
     "particleUmMin": 150, "particleUmMax": 250},
    {"name": "GoldPods (shelf-stable)", "brand": "NYOS", "category": "zooPrepared",
     "bottleMl": 250, "shelfLifeDaysOpened": 0, "refrigerated": False, "stirDaily": False,
     "particleUmMin": 300, "particleUmMax": 2000},
    {"name": "Reef-Roids slurry", "brand": "PolypLab", "category": "blend",
     "bottleMl": 250, "shelfLifeDaysOpened": 1, "refrigerated": True, "stirDaily": True,
     "particleUmMin": 150, "particleUmMax": 200},
    {"name": "Ultra Sea Fan", "brand": "Fauna Marin", "category": "zooPrepared",
     "bottleMl": 100, "shelfLifeDaysOpened": 90, "refrigerated": True, "stirDaily": False,
     "particleUmMin": 50, "particleUmMax": 300},
    {"name": "Live baby brine (rinsed, tank-salinity)", "brand": "Home hatchery", "category": "zooLive",
     "bottleMl": 1000, "shelfLifeDaysOpened": 2, "refrigerated": True, "stirDaily": False,
     "particleUmMin": 400, "particleUmMax": 500},
    {"name": "Waste-Away", "brand": "Dr Tim's", "category": "bacteria",
     "bottleMl": 473, "shelfLifeDaysOpened": 180, "refrigerated": False, "stirDaily": False,
     "particleUmMin": 0, "particleUmMax": 2},
)

CATEGORY_LABELS = {
    "phyto": "Phytoplankton", "zooLive": "Live zooplankton",
    "zooPrepared": "Zooplankton (prepared)", "blend": "Blend",
    "bacteria": "Bacteria", "amino": "Amino acids", "trace": "Trace",
    "twoPart": "2-part", "other": "Other",
}


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(str(category or ""), "Other")


def usage_ml_per_day(product: dict[str, Any], now: datetime,
                     window_days: float = RUNWAY_WINDOW_DAYS) -> float | None:
    """Average daily use from the logged history window. ``dose`` (manual),
    ``pump`` (dose-event decrement) and ``transfer`` (poured into a pump
    reservoir) all count as demand; ``refill`` is supply and doesn't. None = no
    usage logged in the window — the honest no-forecast answer, never a guess."""
    history = product.get("history")
    if not isinstance(history, list) or window_days <= 0:
        return None
    window_s = window_days * 86400.0
    used = 0.0
    seen = False
    oldest_age_s = 0.0
    for event in history:
        if not isinstance(event, dict) or event.get("kind") not in ("dose", "pump", "transfer"):
            continue
        at = _parse_iso(event.get("at"))
        if at is None:
            continue
        try:
            age_s = (now - at).total_seconds()
        except TypeError:
            continue
        if age_s < 0 or age_s > window_s:
            continue
        used += max(0.0, _f(event.get("ml")))
        seen = True
        oldest_age_s = max(oldest_age_s, age_s)
    if not seen or used <= 0:
        return None
    # Average over the observed span (min 1 day) so a shelf logged for 3 days
    # doesn't have its usage diluted across the whole 14-day window.
    span_days = min(window_days, max(1.0, oldest_age_s / 86400.0))
    return used / span_days


def expiry_state(product: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Opened-bottle expiry. shelfLifeDaysOpened <= 0 = shelf-stable (fresh).
    Expiring product without an openedAt stamp = expired (fail-closed, the
    dosing.freshness_state rule)."""
    shelf_days = _f(product.get("shelfLifeDaysOpened"))
    if shelf_days <= 0:
        return {"status": "fresh", "daysLeft": None, "ageDays": None}
    opened = _parse_iso(product.get("openedAt"))
    if opened is None:
        return {"status": "expired", "daysLeft": 0.0, "ageDays": None}
    try:
        age_d = max(0.0, (now - opened).total_seconds() / 86400.0)
    except TypeError:
        return {"status": "expired", "daysLeft": 0.0, "ageDays": None}
    left_d = shelf_days - age_d
    if left_d <= 0:
        status = "expired"
    elif left_d <= shelf_days * AGING_FRACTION:
        status = "aging"
    else:
        status = "fresh"
    return {"status": status, "daysLeft": round(max(0.0, left_d), 1),
            "ageDays": round(age_d, 1)}


def consumable_state(product: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Everything the food shelf shows for one bottle."""
    bottle = max(0.0, _f(product.get("bottleMl")))
    remaining = min(bottle, max(0.0, _f(product.get("remainingMl")))) if bottle else 0.0
    low_threshold = max(0.0, _f(product.get("lowThresholdMl")))
    if low_threshold <= 0 and bottle > 0:
        low_threshold = bottle * LOW_PERCENT_DEFAULT / 100.0
    daily = usage_ml_per_day(product, now)
    expiry = expiry_state(product, now)
    days_left = round(remaining / daily, 1) if daily and daily > 0 else None
    return {
        "bottleMl": bottle,
        "remainingMl": round(remaining, 1),
        "percent": round(remaining / bottle * 100.0, 1) if bottle > 0 else None,
        "usageMlPerDay": round(daily, 2) if daily else None,
        "daysUntilEmpty": days_left,
        "low": bool(bottle > 0 and remaining <= low_threshold),
        "empty": bool(bottle > 0 and remaining <= 0),
        "expiry": expiry,
        "stirDaily": bool(product.get("stirDaily")),
        "refrigerated": bool(product.get("refrigerated")),
        "categoryLabel": category_label(product.get("category")),
    }


def shelf_summary(products: dict[str, Any], now: datetime) -> dict[str, Any]:
    """The whole food shelf: per-product states plus the attention counts the
    tab header and (later) notifications read."""
    states: dict[str, dict[str, Any]] = {}
    low = expired = 0
    for pid, product in products.items():
        if not isinstance(product, dict):
            continue
        state = consumable_state(product, now)
        states[str(pid)] = state
        if state["low"] or state["empty"]:
            low += 1
        if state["expiry"]["status"] == "expired":
            expired += 1
    return {"products": states, "lowCount": low, "expiredCount": expired,
            "count": len(states)}
