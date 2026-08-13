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

# Feed-exchange (Stage B): every live-food dose PLUS its line-flush chaser is
# water IN — the matched drain owes both back out so the tank level (and the
# ATO) never notices feeding. Research: nauplii lose 30–50% of caloric value
# between 24 h and 48 h post-hatch — the prime window below drives the
# hatchery card's countdown.
FEED_EXCHANGE_MIN_DRAIN_DEFAULT = 150.0   # ml — not worth spinning a pump below this
FEED_EXCHANGE_MAX_OWED_DEFAULT = 2000.0   # ml — a blocked drain must not bank a flood
BRINE_PRIME_HOURS = 24.0

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


def feed_exchange_owed(owed_ml: float, dose_ml: float, chaser_ml: float,
                       max_owed_ml: float) -> tuple[float, float]:
    """New owed-drain total after a brine dose. The dose AND its line-flush
    chaser both entered the tank, so both must drain back out. Clamped at
    ``max_owed_ml``: a drain blocked for days must not bank an unbounded
    catch-up drain (the AWC slot-coalescing lesson) — overflow is returned as
    ``dropped`` for the caller to report, never kept silently.

    Returns ``(owed_ml, dropped_ml)``."""
    add = max(0.0, _f(dose_ml)) + max(0.0, _f(chaser_ml))
    cap = _f(max_owed_ml)
    if cap <= 0:
        cap = FEED_EXCHANGE_MAX_OWED_DEFAULT
    new = max(0.0, _f(owed_ml)) + add
    return (round(min(new, cap), 1), round(max(0.0, new - cap), 1))


def feed_exchange_batch(owed_ml: float, min_drain_ml: float, max_batch_ml: float,
                        waste_headroom_ml: float | None = None) -> float:
    """The drain volume worth running now: everything owed, once it clears the
    minimum worth energising a pump for, clamped to the per-run cap and the
    waste reservoir's dead-reckoned headroom. 0 = keep waiting."""
    owed = max(0.0, _f(owed_ml))
    min_drain = _f(min_drain_ml)
    if min_drain <= 0:
        min_drain = FEED_EXCHANGE_MIN_DRAIN_DEFAULT
    batch = owed
    if _f(max_batch_ml) > 0:
        batch = min(batch, _f(max_batch_ml))
    if waste_headroom_ml is not None:
        batch = min(batch, max(0.0, _f(waste_headroom_ml)))
    return round(batch, 1) if batch >= min_drain else 0.0


def hatch_prime_state(mixed_at_iso: Any, now: datetime) -> dict[str, Any]:
    """Where this hatch sits in its nutritional window: ``prime`` (first 24 h,
    yolk reserves intact), ``fading`` (still alive, calories dropping), or
    ``unknown`` (no 'Hatched & loaded' stamp yet)."""
    mixed = _parse_iso(mixed_at_iso)
    if mixed is None:
        return {"status": "unknown", "ageHours": None, "primeLeftHours": None}
    try:
        age_h = max(0.0, (now - mixed).total_seconds() / 3600.0)
    except TypeError:
        return {"status": "unknown", "ageHours": None, "primeLeftHours": None}
    left_h = BRINE_PRIME_HOURS - age_h
    return {"status": "prime" if left_h > 0 else "fading",
            "ageHours": round(age_h, 1),
            "primeLeftHours": round(max(0.0, left_h), 1)}


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
