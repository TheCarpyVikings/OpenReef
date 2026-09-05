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

from datetime import datetime, timedelta
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
    {"name": "Selcon", "brand": "American Marine", "category": "other",
     "bottleMl": 60, "shelfLifeDaysOpened": 120, "refrigerated": True, "stirDaily": False,
     "particleUmMin": 0, "particleUmMax": 0,
     "notes": "HUFA/B12 enrichment emulsion for the hatchery's enrichment soak — "
              "shake well; use less if the water does not clear."},
    # Reefphyto (UK) — the cultures arc's shelf (docs/live-cultures-brainstorm.md §8.1),
    # numbers read from the product pages 2026-09-05.
    {"name": "Reef Juice (live phyto blend)", "brand": "Reefphyto", "category": "phyto",
     "bottleMl": 250, "shelfLifeDaysOpened": 90, "refrigerated": True, "stirDaily": True,
     "particleUmMin": 1, "particleUmMax": 20,
     "notes": "Tank dose only — Reefphyto: 'not designed as a culture feed'. 1 ml per 27 / 18 / 9 L "
              "a day for light / medium / heavy stocking (their blog: 2–3× a week is right for "
              "most reefs). Into flow at dusk, skimmer + UV off 30–60 min. Gentle shake, never freeze.",
     # The hand-dose plan (0.7.129): litres of tank per ml a day, per stocking
     # band — the shelf turns it into a dose from the Profile tank volume.
     "doseGuide": {"light": 27, "medium": 18, "heavy": 9}, "doseEveryDays": 1,
     "doseNote": "Into the flow at dusk, skimmer and UV off for an hour."},
    {"name": "Rotifer Feed Concentrate", "brand": "Reefphyto", "category": "phyto",
     "bottleMl": 50, "shelfLifeDaysOpened": 90, "refrigerated": True, "stirDaily": True,
     "particleUmMin": 1, "particleUmMax": 12,
     "notes": "The rotifer cone's food: Nannochloropsis oculata + Tetraselmis suecica only. Dose to "
              "a leafy green, little and often; top up when the water clears. Not a copepod feed."},
    {"name": "Copepod Feed", "brand": "Reefphyto", "category": "phyto",
     "bottleMl": 50, "shelfLifeDaysOpened": 90, "refrigerated": True, "stirDaily": True,
     "particleUmMin": 1, "particleUmMax": 20,
     "notes": "The Tigriopus tub's food — feed to a Granny Smith apple-skin green, half rate in "
              "week one, again when it clears."},
    {"name": "Rotifer & Artemia Enrichment", "brand": "Reefphyto", "category": "other",
     "bottleMl": 100, "shelfLifeDaysOpened": 90, "refrigerated": True, "stirDaily": True,
     "particleUmMin": 0, "particleUmMax": 0,
     "notes": "Live Nannochloropsis (EPA) + Isochrysis (DHA) — an algae enrichment, not an "
              "emulsion. 1–5 drops per portion of rotifers or nauplii, 6 h (their pages say 2–4 "
              "or 6–12), rinse before feeding."},
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
    {"name": "Live rotifers (fridge bottle)", "brand": "Home culture", "category": "zooLive",
     "bottleMl": 1000, "shelfLifeDaysOpened": 5, "refrigerated": True, "stirDaily": False,
     "particleUmMin": 90, "particleUmMax": 360,
     "notes": "Harvested from the cone through the 50 µm net; enrich a portion for DHA. The "
              "Cultures tab keeps this bottle's clock — add it here so the feed plans can pick it."},
    {"name": "Live Tigriopus (from the tub)", "brand": "Home culture", "category": "zooLive",
     "bottleMl": 500, "shelfLifeDaysOpened": 3, "refrigerated": True, "stirDaily": False,
     "particleUmMin": 120, "particleUmMax": 1200,
     "notes": "Nauplii through 50 µm, adults on 300 µm; pour into the refugium after lights-out."},
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


DOSE_STOCKINGS: tuple[str, ...] = ("light", "medium", "heavy")


def hand_dose_guide(product: dict[str, Any], tank_l: Any) -> dict[str, Any]:
    """A product that carries a dose guide (litres of tank per ml a day, per
    stocking band — Reef Juice's label) turned into a dose for THIS tank.
    Products without a guide are simply not guided: available False."""
    guide = product.get("doseGuide") if isinstance(product.get("doseGuide"), dict) else {}
    band = str(product.get("doseStocking") or "medium")
    if band not in DOSE_STOCKINGS:
        band = "medium"
    per = _f(guide.get(band))
    litres = max(0.0, _f(tank_l))
    if per <= 0:
        return {"available": False, "ml": None, "stocking": band, "perLitres": None}
    return {"available": litres > 0, "ml": round(litres / per, 1) if litres > 0 else None,
            "stocking": band, "perLitres": per}


HAND_DOSE_HOURS_MAX = 24.0
HAND_DOSE_DUE_WINDOW_MIN = 30      # a timed slot is "due" this long after its time, then "late"
HAND_DOSE_ANYTIME_MATCH_MIN = 1440  # an any-time chip takes a dose logged at any hour


def _hhmm_min(value: Any) -> int | None:
    """'HH:MM' -> minutes since midnight, or None."""
    if not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def _min_hhmm(minute: int) -> str:
    minute = int(minute) % 1440
    return f"{minute // 60:02d}:{minute % 60:02d}"


def hand_dose_slots(product: dict[str, Any]) -> dict[str, Any]:
    """The bottle's daily slots, derived from its cadence (doc §13.4): every N
    hours = floor(24/N) slots a day from the anchor time, restarting at the
    anchor each day; every N days = one slot at the anchor on due days. No
    anchor = the same count of "any time today" chips (slots empty)."""
    hours = max(0.0, _f(product.get("doseEveryHours")))
    days = max(0.0, _f(product.get("doseEveryDays")))
    anchor = _hhmm_min(product.get("doseFirstAt"))
    if hours > 0:
        hours = min(HAND_DOSE_HOURS_MAX, hours)
        per_day = max(1, int(24.0 // hours))
        unit, n = "hours", hours
    elif days > 0:
        per_day = 1
        unit, n = "days", days
    else:
        return {"unit": "", "n": 0.0, "firstAt": "", "perDay": 0, "slots": [], "text": ""}
    slots: list[int] = []
    if anchor is not None:
        if unit == "hours":
            slots = sorted(int(round(anchor + k * hours * 60)) % 1440 for k in range(per_day))
        else:
            slots = [anchor]
    if unit == "hours":
        text = f"every {hours:g} h"
        if anchor is not None:
            text += f" from {_min_hhmm(anchor)}"
        if per_day > 1:
            text += f" · {per_day} a day"
    else:
        text = "every day" if days == 1 else f"every {days:g} days"
        if anchor is not None:
            text += f" at {_min_hhmm(anchor)}"
    return {"unit": unit, "n": n, "firstAt": _min_hhmm(anchor) if anchor is not None else "",
            "perDay": per_day, "slots": slots, "text": text}


def _anchored_slot(base: datetime, slots: list[int], unit: str, tz: Any) -> datetime:
    """Where the cadence's next slot actually falls (local wall clock). Hours:
    the anchored slot nearest ``base`` (a dose ten minutes late still owns its
    slot, so the next one is the next one, not the one after). Days: the anchor
    time on ``base``'s date — the day cadence gates the day, the anchor places
    the slot."""
    local = base.astimezone(tz) if tz is not None else base
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    ordered = sorted(slots)
    if unit == "days":
        return day + timedelta(minutes=ordered[0])
    candidates = [day + timedelta(days=d, minutes=slot) for d in (-1, 0, 1) for slot in ordered]
    return min(candidates, key=lambda c: abs((c - local).total_seconds()))


def hand_dose_state(product: dict[str, Any], now: datetime, tank_l: Any = None,
                    tz: Any = None) -> dict[str, Any]:
    """The bottle's hand-dose plan: the size (the keeper's number, else the
    guide's), the cadence (days OR hours, doc §13.4), and a due clock off the
    last logged hand dose — or the last skip, which holds the cadence without
    pretending a dose happened. With an anchor time the clock snaps forward to
    the next anchored slot, so the shelf reminder, the due pill and the strip
    all read one function. A planned bottle never dosed is due now."""
    guide = hand_dose_guide(product, tank_l)
    explicit = max(0.0, _f(product.get("doseMl")))
    cadence = hand_dose_slots(product)
    every_days = max(0.0, _f(product.get("doseEveryDays")))
    every_hours = max(0.0, _f(product.get("doseEveryHours")))
    ml = round(explicit, 2) if explicit > 0 else guide["ml"]
    last_iso = str(product.get("lastDosedAt") or "")
    last = _parse_iso(last_iso)
    skipped = _parse_iso(product.get("doseSkippedAt"))
    base = last
    if skipped is not None and (base is None or skipped > base):
        base = skipped
    if not cadence["unit"]:
        clock = {"available": False, "due": False, "at": None, "hoursUntil": None, "hoursOverdue": None}
    elif base is None:
        clock = {"available": True, "due": True, "at": now.isoformat(), "hoursUntil": 0.0, "hoursOverdue": 0.0}
    else:
        if cadence["unit"] == "hours":
            at = base + timedelta(hours=cadence["n"])
        else:
            at = base + timedelta(days=cadence["n"])
        if cadence["slots"]:
            at = _anchored_slot(at, cadence["slots"], cadence["unit"], tz)
        try:
            delta_h = (at - now).total_seconds() / 3600.0
        except TypeError:
            delta_h = 0.0
        clock = {"available": True, "due": delta_h <= 0, "at": at.isoformat(),
                 "hoursUntil": round(max(0.0, delta_h), 1), "hoursOverdue": round(max(0.0, -delta_h), 1)}
    return {
        "planned": bool(cadence["unit"] or explicit > 0),
        "ml": ml,
        "everyDays": every_days if cadence["unit"] != "hours" else 0.0,
        "everyHours": every_hours if cadence["unit"] == "hours" else 0.0,
        "firstAt": cadence["firstAt"],
        "slotsPerDay": cadence["perDay"],
        "slots": [_min_hhmm(m) for m in cadence["slots"]],
        "cadenceText": cadence["text"],
        "stocking": guide["stocking"],
        "guide": guide,
        "note": str(product.get("doseNote") or ""),
        "lastAt": last_iso,
        "skippedAt": str(product.get("doseSkippedAt") or ""),
        "clock": clock,
    }


def consumable_state(product: dict[str, Any], now: datetime, tank_l: Any = None,
                     tz: Any = None) -> dict[str, Any]:
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
        "handDose": hand_dose_state(product, now, tank_l, tz),
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


# Hatchery (v1): the incubation clock. Hatch times from the 2026-08 research
# sweep — standard Great Salt Lake cysts run 18–24 h at 26–30 °C; decapsulated
# cysts (shell dissolved) harvest ~16 h; cooler rooms stretch everything.
# OVERDUE_GRACE: nauplii left in the hatcher keep burning yolk — past this the
# card starts nagging (they lose 30–50% of calories by 48 h post-hatch).
EGG_TYPES: tuple[dict[str, Any], ...] = (
    {"id": "standard", "name": "Standard cysts (GSL)", "hours": 24,
     "note": "The usual eBay/LFS cysts: 18–24 h at 26–30 °C, ~25 ppt, strong aeration."},
    {"id": "decapsulated", "name": "Decapsulated cysts", "hours": 16,
     "note": "Shell already dissolved — hatches faster (~16 h) and no shell separation."},
    {"id": "premium", "name": "High-hatch premium cysts", "hours": 20,
     "note": "90%+ hatch-rate grades tend to pop a little sooner (~20 h)."},
    {"id": "cool_room", "name": "Cool room (below ~24 °C)", "hours": 36,
     "note": "No heater on the hatcher? Budget up to 36 h — temperature rules the clock."},
)
_EGG_TYPES_BY_ID = {e["id"]: e for e in EGG_TYPES}
HATCH_OVERDUE_GRACE_H = 12.0


def egg_type_ids() -> tuple[str, ...]:
    return tuple(e["id"] for e in EGG_TYPES)


def egg_type_hours(egg_type: str) -> float:
    return float(_EGG_TYPES_BY_ID.get(str(egg_type or ""), _EGG_TYPES_BY_ID["standard"])["hours"])


def hatch_state(started_iso: Any, hatch_hours: float, now: datetime) -> dict[str, Any]:
    """Where the hatch sits: ``none`` (nothing brewing), ``incubating`` (with an
    honest percent and hours-to-go), ``ready`` (harvest window), or ``overdue``
    (still fine, but the yolk clock is running — harvest soon)."""
    started = _parse_iso(started_iso)
    hours = _f(hatch_hours)
    if hours <= 0:
        hours = 24.0
    if started is None:
        return {"status": "none", "hoursElapsed": None, "hoursLeft": None, "percent": None}
    try:
        elapsed_h = max(0.0, (now - started).total_seconds() / 3600.0)
    except TypeError:
        return {"status": "none", "hoursElapsed": None, "hoursLeft": None, "percent": None}
    if elapsed_h < hours:
        return {"status": "incubating",
                "hoursElapsed": round(elapsed_h, 1),
                "hoursLeft": round(hours - elapsed_h, 1),
                "percent": round(min(99.0, elapsed_h / hours * 100.0), 0)}
    status = "overdue" if elapsed_h > hours + HATCH_OVERDUE_GRACE_H else "ready"
    return {"status": status, "hoursElapsed": round(elapsed_h, 1),
            "hoursLeft": 0.0, "percent": 100.0}


# A harvested batch needs rinsing, resuspending and loading before it feeds —
# the next-start maths leaves this much slack on top of the incubation hours.
HATCH_HARVEST_BUFFER_H = 1.0

# Hatchery v2 (doc §9): vessel cap, dosing-density guide (research §9.6 — 2 g/L
# is the documented optimum, >2 reduces hatch-out), and the temperature rule of
# thumb (28 °C is the sweet spot; each degree cooler stretches the clock ~8%,
# capped where the sources run out of data).
HATCH_VESSEL_CAP = 4
HATCH_CYST_G_PER_L = 2.0
HATCH_TEMP_OPTIMUM_C = 28.0
HATCH_HISTORY_MAX = 50

# Fridge storage nearly stops nauplii metabolism: 24 h shelf life at room temp,
# 48 h refrigerated. Audit 2026-09-01 (doc §12): unfed nauplii lose ~20% dry
# weight / ~27% energy in their first 24 h warm (FAO 361); at 2–4 °C viability
# stays very high through 48 h with dry weight and biochemistry unchanged for
# most strains (Léger et al. 1983, "International study on Artemia XXIV").
# The two numbers are RATES, not a switch: brine_window_hours() below spends
# the batch at the room rate until it goes cold and at the fridge rate after
# — a load that sat warm for 20 h does not get 48 h for being fridged late.
BRINE_SHELF_H_ROOM = 24.0
BRINE_SHELF_H_FRIDGE = 48.0

# Enrichment chain (doc §10): the HUFA boost is TRANSIENT — DHA falls to under
# half within 24 h at room temp (Evjemo 1997), so an enriched load keeps a
# tighter clock: 12 h on the counter, 48 h fridged (<10 °C holds ≥24 h with
# <5% loss). Hobby single-dose soak defaults to 12 h; the INVE-style split
# protocol tops up at T+10 h. Done batches get a short grace — enriched brine
# degrades faster than a plain hatch.
ENRICH_SHELF_H_ROOM = 12.0
ENRICH_SHELF_H_FRIDGE = 48.0
ENRICH_DEFAULT_HOURS = 12.0
ENRICH_SECOND_DOSE_H = 10.0
ENRICH_OVERDUE_GRACE_H = 6.0
# An enriched container's window is the soak's own length PLUS the hold above
# (the boost decays from soak-end, not from the load), bounded so a bad stamp
# cannot grant a week of "fresh".
ENRICH_SHELF_MAX_H = 72.0

# Instar I has no mouth and no anus — it cannot eat, full stop. The molt to
# instar II lands ~8 h post-hatch at the 28 C optimum (FAO 361: "after about
# 8 h"; SRAC 702: "approximately 12 hours"; hatchery practice: harvest at
# 16 h + 6–8 h more at room temp — audit 2026-09-01, doc §12) and runs later
# on a cool bench, so the delay rides the SAME factor as the hatch clock.
# Dosing emulsion before the molt just fouls the water.
INSTAR_II_HOURS = 8.0
INSTAR_II_DELAY_MAX_H = 24.0

# Named vessel presets for the volume picker (product → working water volume).
# Research note: the Ziss line is ZH-700 / ZH-2000 — there is no ZH-1000.
HATCH_VESSEL_PRESETS: tuple[dict[str, Any], ...] = (
    {"id": "ziss_zh700", "name": "Ziss ZH-700", "volumeL": 0.7},
    {"id": "ziss_zh2000", "name": "Ziss ZH-2000", "volumeL": 2.0},
    {"id": "hobby_breeder", "name": "Hobby Artemia Breeder", "volumeL": 0.47},
    {"id": "jbl_artemio", "name": "JBL ArtemioSet", "volumeL": 0.5},
    {"id": "soda_bottle", "name": "2 L bottle rig", "volumeL": 1.6},
)


def brine_window_hours(loaded_iso: Any, now: datetime, room_h: Any, fridge_h: Any,
                       fridged_at_iso: Any = None, fridge_saved_h: Any = 0.0) -> float:
    """How many hours FROM THE LOAD this batch stays good — the two-rate clock
    behind every freshness number (doc §12, 0.7.115).

    A batch burns through its window at the room rate (``room_h`` to spend
    it all) until the moment it goes into the fridge, and at the fridge rate
    (``fridge_h``) from then on. So a fresh load fridged at once gets the
    full ``fridge_h``; one fridged after 12 warm hours of a 24 h window has
    half its life left and spends that half slowly — 12 + 24 = 36 h in all;
    one fridged after it is already spent gets nothing back. Taking it OUT
    banks the hours the fridge saved (``fridge_saved_h``, see
    ``fridge_saved_on_exit``) so the credit survives the spell ending.

    Returns hours-from-load, so it drops straight into every consumer that
    already reads ``mixedAt`` + a shelf length (freshness, next-hatch,
    vessels-needed) — nothing downstream has to know about the fridge."""
    room = _f(room_h)
    if room <= 0:
        room = BRINE_SHELF_H_ROOM
    fridge = max(_f(fridge_h), room)
    saved = max(0.0, _f(fridge_saved_h))
    loaded = _parse_iso(loaded_iso)
    if loaded is None:
        return round(room + saved, 2)
    try:
        age_h = max(0.0, (now - loaded).total_seconds() / 3600.0)
    except TypeError:
        return round(room + saved, 2)
    fridged = _parse_iso(fridged_at_iso)
    if fridged is None:
        return round(room + saved, 2)
    try:
        in_at_h = (fridged - loaded).total_seconds() / 3600.0
    except TypeError:
        return round(room + saved, 2)
    in_at_h = min(age_h, max(0.0, in_at_h))
    room_spent_h = max(0.0, in_at_h - saved)
    cold_h = max(0.0, age_h - in_at_h)
    consumed = room_spent_h / room + cold_h / fridge
    remaining = max(0.0, 1.0 - consumed)
    return round(age_h + remaining * fridge, 2)


def fridge_saved_on_exit(fridged_at_iso: Any, now: datetime,
                         room_h: Any, fridge_h: Any) -> tuple[float, float]:
    """The batch comes out of the fridge: (hours it spent cold, hours of shelf
    life that spell banked). Cold hours count against the window at only
    room/fridge of the room rate, so the rest is credit the room clock keeps
    — 20 h at 4 °C on a 24 h/48 h clock spends 10 warm-equivalent hours and
    banks the other 10."""
    room = _f(room_h)
    if room <= 0:
        room = BRINE_SHELF_H_ROOM
    fridge = max(_f(fridge_h), room)
    fridged = _parse_iso(fridged_at_iso)
    if fridged is None:
        return 0.0, 0.0
    try:
        cold_h = max(0.0, (now - fridged).total_seconds() / 3600.0)
    except TypeError:
        return 0.0, 0.0
    return round(cold_h, 2), round(cold_h * (1.0 - room / fridge), 2)


def expected_hatch_hours(base_hours: Any, temp_c: Any) -> dict[str, Any]:
    """Advisory only — never moves the real clock. At 28 °C the RATED hours
    stand; each degree cooler stretches them ~8% (research: 24 h at 28 °C
    becomes ~36 h at 21 °C, 36–48 h at 20 °C), clamped at 2.2×. Warmer than
    optimum is not rewarded — above ~30 °C hatch quality drops, so we flag it
    instead of promising speed.

    Feed it the egg type's RATED hours, never the keeper's clock (audit
    2026-09-01, doc §12): a clock set from the learned average was measured
    at this very temperature, and stretching it again double-counted the
    cold — "expect ~43.7 h, not 38 h" about batches that actually ran 36."""
    base = _f(base_hours)
    if base <= 0:
        base = 24.0
    temp = _f(temp_c, -999.0)
    if temp < -50 or temp > 60:
        return {"available": False, "expectedHours": None, "factor": None, "warm": False}
    factor = 1.0 + max(0.0, (HATCH_TEMP_OPTIMUM_C - temp)) * 0.08
    factor = min(factor, 2.2)
    return {"available": True,
            "expectedHours": round(base * factor, 1),
            "factor": round(factor, 2),
            "warm": temp > 30.0}


def learned_hatch_hours(history: Any, egg_type: str) -> dict[str, Any]:
    """Rolling average of the last three ACTUAL hatch durations for this egg
    type (early harvests included — that's the point). Needs two samples before
    it says anything; advisory-with-Apply like every other suggestion."""
    if not isinstance(history, list):
        return {"available": False, "hours": None, "samples": 0}
    actuals = [
        _f(item.get("actualHours"))
        for item in history
        if isinstance(item, dict) and item.get("eggType") == egg_type
        and _f(item.get("actualHours")) > 0
    ]
    actuals = actuals[:3]
    if len(actuals) < 2:
        return {"available": False, "hours": None, "samples": len(actuals)}
    return {"available": True,
            "hours": round(sum(actuals) / len(actuals), 1),
            "samples": len(actuals)}


def vessels_needed(hatch_hours: Any, shelf_hours: Any) -> int:
    """Continuous supply needs ceil(lead / shelf) staggered vessels — the
    documented two-vessel 12–24 h rotation falls straight out of this."""
    hours = _f(hatch_hours)
    if hours <= 0:
        hours = 24.0
    shelf = _f(shelf_hours)
    if shelf <= 0:
        shelf = 24.0
    lead = hours + HATCH_HARVEST_BUFFER_H
    return max(1, int(-(-lead // shelf)))


def cyst_dose_guide(volume_l: Any) -> dict[str, Any]:
    """The card's dosing hint: grams at the 2 g/L optimum, and the rough
    nauplii count at premium (90%-grade GSL ≈ 225k/g) yield."""
    volume = _f(volume_l)
    if volume <= 0:
        return {"available": False, "grams": None, "nauplii": None}
    grams = round(volume * HATCH_CYST_G_PER_L, 1)
    return {"available": True, "grams": grams,
            "nauplii": int(grams * 225000)}


def next_hatch_suggestion(
    now: datetime,
    hatch_hours: Any,
    loaded_iso: Any,
    shelf_life_hours: Any,
    remaining_ml: Any,
    ml_per_day: Any,
    started_iso: Any,
    chain_shelf_hours: Any = None,
) -> dict[str, Any]:
    """When to set the next batch of cysts going — the daily-driver question.

    The new batch must be READY (incubated + harvested, so ``hatch_hours`` plus
    a harvest buffer of lead time) by the earlier of two moments: the loaded
    brine going stale (``loaded_iso`` + shelf life) and the reservoir running
    dry (``remaining_ml`` at ``ml_per_day``; pass None when unknown — a
    hand-doser without volume tracking still gets freshness-timed advice).

    Statuses: ``wait`` (start at ``startAt``), ``start_now`` (the lead time has
    already begun eating into the window), ``overdue`` (the window is gone),
    ``no_brine`` (nothing loaded, nothing incubating — just start one), and
    ``chained`` (a hatch is already on the go; ``startAt`` is when to start the
    one AFTER it, assuming it loads on time — which nets out to the current
    start plus the shelf life). ``overlap`` flags the structural case where the
    hatch takes longer than the brine stays fresh, so batches must overlap and
    "wait" can never be the answer.

    ``started_iso`` accepts one stamp, a LIST of stamps, or a list of
    ``{"startedAt", "hatchHours", "id"}`` dicts (hatchery v2: several vessels,
    each batch on its OWN stamped clock — a 36 h batch mid-run stays a 36 h
    batch even after the default drops to 24). The chain anchors on the batch
    that LOADS last — every load resets the container's clock, so the last
    batch to land is the one whose fade the next start must beat — but brine
    ALREADY on hand (the container, the feeding bottle) covers the gap too
    (0.7.118): the next batch must land before the LATER of the incoming
    load fading and the supply on hand giving out (its fade, or its
    depletion at the feed rate). ``driver`` says which: ``chain`` (the
    incoming harvest), ``freshness`` or ``depletion`` (the supply on hand).
    ``busyCount`` reports how many batches are on the go; ``chainVessel``
    names the anchor batch's vessel when the dicts carry ``id``.
    """
    hours = _f(hatch_hours)
    if hours <= 0:
        hours = 24.0
    shelf_h = _f(shelf_life_hours)
    if shelf_h <= 0:
        shelf_h = 24.0
    # The chain's shelf is the PLAIN one (audit 2026-09-01, doc §12): the
    # batch that loads next is unfed at load, so an enriched container's
    # longer boost window must not be projected onto it.
    chain_shelf_h = _f(chain_shelf_hours)
    if chain_shelf_h <= 0:
        chain_shelf_h = shelf_h
    lead_h = hours + HATCH_HARVEST_BUFFER_H
    raw_starts = started_iso if isinstance(started_iso, (list, tuple)) else [started_iso]
    running: list[tuple[datetime, float, str]] = []
    for item in raw_starts:
        if isinstance(item, dict):
            stamp, batch_h = _parse_iso(item.get("startedAt")), _f(item.get("hatchHours"))
            vessel_id = str(item.get("id") or "")
        else:
            stamp, batch_h, vessel_id = _parse_iso(item), 0.0, ""
        if stamp is not None:
            running.append((stamp, batch_h if batch_h > 0 else hours, vessel_id))
    base: dict[str, Any] = {
        "status": "no_brine", "startAt": None, "hoursUntil": None,
        "readyBy": None, "driver": None,
        "hatchHours": round(hours, 1), "shelfHours": round(shelf_h, 1),
        "overlap": shelf_h < lead_h,
        "busyCount": len(running),
        "chainVessel": None,
    }

    def _finish(status: str, start_at: datetime | None, ready_by: datetime | None,
                driver: str | None) -> dict[str, Any]:
        out = dict(base)
        out["status"] = status
        out["driver"] = driver
        if ready_by is not None:
            out["readyBy"] = ready_by.isoformat()
        if start_at is not None:
            out["startAt"] = start_at.isoformat()
            out["hoursUntil"] = round(max(0.0, (start_at - now).total_seconds() / 3600.0), 1)
        return out

    # Brine on hand (container and/or feeding bottle) gives out at the
    # EARLIER of its fade and its depletion at the feed rate.
    loaded = _parse_iso(loaded_iso)
    supply_end: datetime | None = None
    supply_driver = "freshness"
    if loaded is not None:
        supply_end = loaded + timedelta(hours=shelf_h)
        remaining = _f(remaining_ml, -1.0)
        rate = _f(ml_per_day)
        if remaining >= 0 and rate > 0:
            deplete_by = now + timedelta(hours=remaining / rate * 24.0)
            if deplete_by < supply_end:
                supply_end, supply_driver = deplete_by, "depletion"

    if running:
        # Batches are on the go: the next start keeps the chain unbroken. The
        # anchor is when the LAST batch loads (its own stamped clock, floored
        # at now — a ripe batch loads about now); its brine fades shelf_h
        # later, and the following batch needs lead_h of runway. Brine
        # already on hand that outlives that load moves the deadline out.
        anchor_dt, _h, anchor_id = max(
            ((max(stamp + timedelta(hours=batch_h), now), batch_h, vid)
             for stamp, batch_h, vid in running),
            key=lambda item: item[0],
        )
        base["chainVessel"] = anchor_id or None
        ready_by, driver = anchor_dt + timedelta(hours=HATCH_HARVEST_BUFFER_H + chain_shelf_h), "chain"
        if supply_end is not None and supply_end > ready_by:
            ready_by, driver = supply_end, supply_driver
        start_at = ready_by - timedelta(hours=lead_h)
        if start_at <= now:
            return _finish("start_now", now, ready_by, driver)
        return _finish("chained", start_at, ready_by, driver)

    if loaded is None or supply_end is None:
        return _finish("no_brine", None, None, None)
    ready_by, driver = supply_end, supply_driver
    start_at = ready_by - timedelta(hours=lead_h)
    if ready_by <= now:
        return _finish("overdue", now, ready_by, driver)
    if start_at <= now:
        return _finish("start_now", now, ready_by, driver)
    return _finish("wait", start_at, ready_by, driver)


def enrich_state(started_iso: Any, enrich_hours: Any, split_dose: bool,
                 second_dose_iso: Any, now: datetime,
                 first_dose_iso: Any = None, dose_delay_h: Any = 0,
                 batch_loaded_iso: Any = None) -> dict[str, Any]:
    """Where the enrichment soak sits: ``none`` (vessel idle), ``enriching``
    (with an honest percent), ``done`` (rinse and load), or ``overdue`` (the
    boost is draining — enriched brine degrades fast warm).

    The dose delay (Reece's catch): instar I nauplii CANNOT eat — the molt to
    instar II lands ~6–12 h post-hatch at 26–28 °C, later on a cool bench, and
    a batch harvested off a 24 h clock is a mix of 0–8 h-olds. Emulsion dosed
    before the molt just fouls. So the soak clock proper anchors on the FIRST
    DOSE, not on the load: until Selcon goes in the batch is merely holding
    (percent 0, ``firstDoseDue`` fires once the delay has passed), and done /
    overdue / the split-dose top-up all count from ``first_dose_iso``. A zero
    delay keeps the old dose-at-load behaviour (the first dose IS the start).

    Container semantics (Reece's mesh flow): enrichment engages on brine that
    was ALREADY loaded — so the instar II delay counts from the BATCH's load
    stamp (``batch_loaded_iso``), not from the moment the button was tapped.
    Evening-enriching a morning batch is due immediately; enriching right
    after loading waits out the molt. Missing stamp falls back to the engage
    time (the pre-container behaviour)."""
    started = _parse_iso(started_iso)
    hours = _f(enrich_hours)
    if hours <= 0:
        hours = ENRICH_DEFAULT_HOURS
    if started is None:
        return {"status": "none", "hoursElapsed": None, "hoursLeft": None,
                "percent": None, "firstDoseDue": False, "secondDoseDue": False}
    try:
        elapsed_h = max(0.0, (now - started).total_seconds() / 3600.0)
    except TypeError:
        return {"status": "none", "hoursElapsed": None, "hoursLeft": None,
                "percent": None, "firstDoseDue": False, "secondDoseDue": False}
    delay_h = max(0.0, _f(dose_delay_h))
    first = _parse_iso(first_dose_iso)
    if first is None and delay_h <= 0:
        first = started  # immediate-dose protocol: food went in at soak start
    if first is None:
        # Holding — waiting for the molt. The age that matters is the BATCH's,
        # measured from its load stamp when we have one.
        dose_ref = _parse_iso(batch_loaded_iso) or started
        try:
            batch_age_h = max(0.0, (now - dose_ref).total_seconds() / 3600.0)
        except TypeError:
            batch_age_h = elapsed_h
        return {"status": "enriching", "hoursElapsed": round(elapsed_h, 1),
                "hoursLeft": None, "percent": 0.0,
                "firstDoseDue": batch_age_h >= delay_h, "secondDoseDue": False}
    fed_h = max(0.0, (now - first).total_seconds() / 3600.0)
    second_due = (bool(split_dose)
                  and _parse_iso(second_dose_iso) is None
                  and fed_h >= ENRICH_SECOND_DOSE_H
                  and fed_h < hours)
    if fed_h < hours:
        return {"status": "enriching",
                "hoursElapsed": round(elapsed_h, 1),
                "hoursLeft": round(hours - fed_h, 1),
                "percent": round(min(99.0, fed_h / hours * 100.0), 0),
                "firstDoseDue": False, "secondDoseDue": second_due}
    status = "overdue" if fed_h > hours + ENRICH_OVERDUE_GRACE_H else "done"
    return {"status": status, "hoursElapsed": round(elapsed_h, 1),
            "hoursLeft": 0.0, "percent": 100.0,
            "firstDoseDue": False, "secondDoseDue": False}


def instar_two_delay_hours(temp_c: Any = None,
                           base_hours: Any = INSTAR_II_HOURS) -> dict[str, Any]:
    """When the batch can first EAT — the honest dose-delay advice.

    The molt to instar II is as temperature-driven as the hatch itself, so it
    rides the same factor: ~8 h at 28 C, later on a cool bench. Advisory only,
    exactly like ``expected_hatch_hours`` — it never moves the keeper's
    setting, it just says what the water is doing."""
    base = _f(base_hours)
    if base <= 0:
        base = INSTAR_II_HOURS
    temp = _f(temp_c, -999.0)
    if temp < -50 or temp > 60:
        return {"available": False, "hours": round(base, 1), "factor": None}
    factor = min(1.0 + max(0.0, (HATCH_TEMP_OPTIMUM_C - temp)) * 0.08, 2.2)
    return {"available": True,
            "hours": round(min(INSTAR_II_DELAY_MAX_H, base * factor), 1),
            "factor": round(factor, 2)}


def hatch_prime_state(mixed_at_iso: Any, now: datetime,
                      enriched_at_iso: Any = None,
                      refrigerated: bool = False,
                      fridged_at_iso: Any = None,
                      fridge_saved_h: Any = 0.0) -> dict[str, Any]:
    """Where this hatch sits in its NUTRITIONAL window - and which window that
    even is, because enrichment swaps one clock for another.

    An UNENRICHED batch runs on yolk: ``prime`` for the first 24 h, then
    ``fading`` as the reserves burn down (30-50% of calories gone by 48 h).

    An ENRICHED batch has been FED. Calling it depleted at 24 h is simply
    wrong - it is gut-loaded, and it now carries the DHA that Great Salt Lake
    nauplii never have on their own. What ticks is no longer starvation but
    retro-conversion: the HUFA boost is transient (Evjemo 1997 - DHA under
    half within a day warm; <5% loss for 24 h+ below 10 C). So an enriched
    batch reads ``gutloaded`` while the boost holds (12 h room / 48 h fridge,
    counted from the END of the soak) and ``boost_fading`` after - still live
    food, no longer enriched food. Never "past prime, hatch fresh".

    This matters because the app's own protocol guarantees the collision: no
    mouths until the molt, then a 12 h soak, and the yolk window is spent by
    the time the soak finishes. The old single clock condemned every batch it
    had just told the keeper to gut-load (Reece, 0.7.89).

    ``primeLeftHours`` always means "hours left in the window that matters",
    so compact surfaces need no new arithmetic.

    The fridge is per batch (doc §12, 0.7.115): ``fridged_at_iso`` says when
    THIS load went cold and both windows run the two-rate clock from there
    (``brine_window_hours``). The yolk window is fridge-aware too — the old
    fixed 24 h called a cold, unfed batch "fading" while the container beside
    it still read fresh. ``refrigerated`` (legacy) means "cold since the
    window began"."""
    unknown = {"status": "unknown", "ageHours": None, "primeLeftHours": None,
               "enriched": False, "window": None, "windowHours": None,
               "soakAgeHours": None, "refrigerated": False}
    mixed = _parse_iso(mixed_at_iso)
    if mixed is None:
        return dict(unknown)
    try:
        age_h = max(0.0, (now - mixed).total_seconds() / 3600.0)
    except TypeError:
        return dict(unknown)
    enriched = _parse_iso(enriched_at_iso)
    if enriched is not None:
        stamp = (fridged_at_iso if _parse_iso(fridged_at_iso) is not None
                 else (enriched_at_iso if refrigerated else None))
        hold_h = brine_window_hours(enriched_at_iso, now, ENRICH_SHELF_H_ROOM,
                                    ENRICH_SHELF_H_FRIDGE, stamp, fridge_saved_h)
        try:
            soak_age_h = max(0.0, (now - enriched).total_seconds() / 3600.0)
        except TypeError:
            return dict(unknown)
        left_h = hold_h - soak_age_h
        return {"status": "gutloaded" if left_h > 0 else "boost_fading",
                "ageHours": round(age_h, 1),
                "primeLeftHours": round(max(0.0, left_h), 1),
                "enriched": True, "window": "boost",
                "windowHours": round(hold_h, 1),
                "soakAgeHours": round(soak_age_h, 1),
                "refrigerated": stamp is not None}
    stamp = (fridged_at_iso if _parse_iso(fridged_at_iso) is not None
             else (mixed_at_iso if refrigerated else None))
    window_h = brine_window_hours(mixed_at_iso, now, BRINE_PRIME_HOURS,
                                  BRINE_SHELF_H_FRIDGE, stamp, fridge_saved_h)
    left_h = window_h - age_h
    return {"status": "prime" if left_h > 0 else "fading",
            "ageHours": round(age_h, 1),
            "primeLeftHours": round(max(0.0, left_h), 1),
            "enriched": False, "window": "yolk",
            "windowHours": round(window_h, 1), "soakAgeHours": None,
            "refrigerated": stamp is not None}


# --------------------------------------------------------------------------- #
# Species plans (Stage D) — the research distilled into data + a compiler.
# Sources: docs/nps-system-brainstorm.md §3 (Reef Builders, Tidal Gardens,
# AlgaeBarn, Pod Your Reef, Reef Central long-term threads). Difficulty 1–5.
# cadence: pulse (discrete feeds), continuous (standing food density), target
# (per-polyp hand feeding — automation assists, never replaces).
# --------------------------------------------------------------------------- #
SPECIES_LIBRARY: tuple[dict[str, Any], ...] = (
    {"id": "tubastraea", "name": "Sun coral (Tubastraea)", "difficulty": 1,
     "particleUmMin": 300, "particleUmMax": 3000, "cadence": "pulse",
     "feedsPerDay": 1, "night": True, "trainable": True,
     "foods": ("zooPrepared", "zooLive", "blend"),
     "note": "Target feeding is what works; broadcast alone leaves polyps unfed. "
             "Trainable to open in daylight by feeding at the same time daily."},
    {"id": "dendrophyllia", "name": "Dendrophyllia / Balanophyllia", "difficulty": 2,
     "particleUmMin": 300, "particleUmMax": 3000, "cadence": "pulse",
     "feedsPerDay": 2, "night": True, "trainable": True,
     "foods": ("zooPrepared", "zooLive", "blend"),
     "note": "Sun-coral care but hungrier — more feeds, more volume."},
    {"id": "chili", "name": "Chili coral", "difficulty": 2,
     "particleUmMin": 150, "particleUmMax": 500, "cadence": "pulse",
     "feedsPerDay": 1, "night": True, "trainable": False,
     "foods": ("zooLive", "zooPrepared"),
     "note": "Strictly nocturnal — feed after lights-out when the polyps are open; "
             "baby brine and decapsulated cysts are the perfect mouthful."},
    {"id": "gorgonian_easy", "name": "Gorgonians — Menella, Swiftia, Diodogorgia",
     "difficulty": 2, "particleUmMin": 50, "particleUmMax": 500, "cadence": "pulse",
     "feedsPerDay": 1, "night": False, "trainable": False,
     "foods": ("zooPrepared", "zooLive"),
     "note": "The recommended starter NPS. Food must be no larger than the polyp mouth."},
    {"id": "gorgonian_hard", "name": "Gorgonians — Euplexaura, Guaiagorgia",
     "difficulty": 3, "particleUmMin": 50, "particleUmMax": 300, "cadence": "pulse",
     "feedsPerDay": 2, "night": False, "trainable": False,
     "foods": ("zooPrepared", "zooLive"),
     "note": "Daily fine zooplankton, no days off."},
    {"id": "rhizotrochus", "name": "Rhizotrochus typus", "difficulty": 3,
     "particleUmMin": 1000, "particleUmMax": 20000, "cadence": "target",
     "feedsPerDay": 0, "night": True, "trainable": False,
     "foods": ("zooPrepared",),
     "note": "Whole meaty items by hand, 2–3× a week. Deepwater — runs happier cool."},
    {"id": "blueberry", "name": "Blueberry gorgonian (Acalycigorgia)", "difficulty": 5,
     "particleUmMin": 5, "particleUmMax": 200, "cadence": "continuous",
     "feedsPerDay": 8, "night": False, "trainable": False,
     "foods": ("phyto", "zooLive"),
     "note": "'Cut flowers of the hobby.' Near-continuous micro-plankton, rotifers, "
             "oyster eggs. Expert-only, honestly."},
    {"id": "dendronephthya", "name": "Dendronephthya / Scleronephthya", "difficulty": 5,
     "particleUmMin": 1, "particleUmMax": 20, "cadence": "continuous",
     "feedsPerDay": 12, "night": False, "trainable": False,
     "foods": ("phyto",),
     "note": "Mostly a PHYTO feeder (weak nematocysts — 50–200× more carbon from "
             "phyto than zoo). The only proven method is a standing live-phyto "
             "density (5,000–50,000 cells/mL — a faint green tint), dosed "
             "continuously."},
    {"id": "filterfeeders", "name": "Sponges, tunicates, flame scallops", "difficulty": 4,
     "particleUmMin": 1, "particleUmMax": 40, "cadence": "continuous",
     "feedsPerDay": 8, "night": False, "trainable": False,
     "foods": ("phyto", "bacteria"),
     "note": "Obligate filter feeders; decline is invisible until it's late. "
             "Standing phyto density is what keeps them."},
    {"id": "crinoid", "name": "Feather star (crinoid)", "difficulty": 5,
     "particleUmMin": 300, "particleUmMax": 500, "cadence": "continuous",
     "feedsPerDay": 4, "night": False, "trainable": False,
     "foods": ("zooLive", "zooPrepared"),
     "note": "Two documented long-term successes, ever. The working protocol: four "
             "feeds a day, each spread over two hours, indefinitely."},
)

_SPECIES_BY_ID = {s["id"]: s for s in SPECIES_LIBRARY}


def species_ids() -> tuple[str, ...]:
    return tuple(s["id"] for s in SPECIES_LIBRARY)


def _ranges_overlap(a_min: float, a_max: float, b_min: float, b_max: float) -> bool:
    return max(_f(a_min), _f(b_min)) <= min(_f(a_max) or 1e9, _f(b_max) or 1e9)


def compile_feed_plan(selected_ids: list[str], products: dict[str, Any],
                      channels: dict[str, Any]) -> dict[str, Any]:
    """The species compiler: what the selected livestock needs, whether the
    shelf and pumps cover it, and per-pump schedule suggestions. Advisory
    only — suggestions carry cadence/window shape; the keeper owns ml/day
    (per-colony appetite is not something a library should guess)."""
    selected = [_SPECIES_BY_ID[sid] for sid in selected_ids if sid in _SPECIES_BY_ID]
    gaps: list[str] = []
    warnings: list[str] = []
    suggestions: list[dict[str, Any]] = []
    product_list = [p for p in products.values() if isinstance(p, dict)]

    for sp in selected:
        # Shelf coverage: any product in the right category AND particle window?
        covered = any(
            p.get("category") in sp["foods"] and _ranges_overlap(
                p.get("particleUmMin"), p.get("particleUmMax"),
                sp["particleUmMin"], sp["particleUmMax"])
            for p in product_list)
        if not covered and sp["cadence"] != "target":
            wanted = " or ".join(sp["foods"])
            gaps.append(
                f"{sp['name']}: nothing on the shelf feeds it "
                f"(needs {wanted}, {sp['particleUmMin']:g}–{sp['particleUmMax']:g} µm).")

    # Per-pump suggestions: a channel whose linked bottle matches a selected
    # species inherits that species' cadence shape.
    for cid, channel in sorted(channels.items()):
        if not isinstance(channel, dict) \
                or channel.get("chemical") not in ("food", "livefood"):
            continue
        product = products.get(str((channel.get("reservoir") or {}).get("productId") or ""))
        if not isinstance(product, dict):
            continue
        matches = [
            sp for sp in selected
            if product.get("category") in sp["foods"] and _ranges_overlap(
                product.get("particleUmMin"), product.get("particleUmMax"),
                sp["particleUmMin"], sp["particleUmMax"])]
        if not matches:
            if selected:
                warnings.append(
                    f"{channel.get('name') or cid}: its bottle "
                    f"({product.get('name')}) feeds none of the selected species — "
                    "check the particle size.")
            continue
        # The hungriest matching species shapes the schedule.
        driver_sp = max(matches, key=lambda s: s["feedsPerDay"])
        doses = max(1, int(driver_sp["feedsPerDay"]))
        if driver_sp["cadence"] == "continuous":
            doses = max(doses, 8)
        suggestions.append({
            "channelId": cid,
            "channelName": channel.get("name") or cid,
            "for": driver_sp["name"],
            "dosesPerDay": doses,
            "night": bool(driver_sp["night"]),
            "note": ("Nocturnal feeder — weight doses after lights-out"
                     if driver_sp["night"] else
                     "Spread doses across the day" if driver_sp["cadence"] == "continuous"
                     else "Discrete pulse feeds"),
        })

    hardest = max((s["difficulty"] for s in selected), default=0)
    if hardest >= 5:
        warnings.append(
            "You've selected expert-tier animals (difficulty 5). Most specimens "
            "starve slowly over 2–6 months even with good automation — source "
            "well, feed relentlessly, and let the camera and logs tell you the truth.")
    return {
        "species": [{"id": s["id"], "name": s["name"], "difficulty": s["difficulty"],
                     "cadence": s["cadence"], "note": s["note"]} for s in selected],
        "gaps": gaps,
        "warnings": warnings,
        "suggestions": suggestions,
    }


# --------------------------------------------------------------------------- #
# Nutrient budget (Stage D) — a deliberately rough model, labelled as such.
# Densities are order-of-magnitude estimates of dosable-food nutrient content
# (mg of N / P per ml of product). N→NO3 ×4.43, P→PO4 ×3.07 (molar mass).
# --------------------------------------------------------------------------- #
CATEGORY_NUTRIENTS = {
    "phyto":       {"n": 0.4, "p": 0.05},
    "zooLive":     {"n": 0.6, "p": 0.08},
    "zooPrepared": {"n": 1.2, "p": 0.15},
    "blend":       {"n": 1.5, "p": 0.20},
    "bacteria":    {"n": 0.1, "p": 0.01},
    "amino":       {"n": 0.8, "p": 0.02},
    "trace":       {"n": 0.0, "p": 0.0},
    "twoPart":     {"n": 0.0, "p": 0.0},
    "other":       {"n": 0.5, "p": 0.05},
}
NO3_BAND = (2.0, 20.0)     # NPS guardrails: never zero, never runaway
PO4_BAND = (0.01, 0.1)


def nutrient_budget(products: dict[str, Any], now: datetime,
                    tank_litres: float, daily_exchange_l: float) -> dict[str, Any]:
    """Feed load vs water-change export, from the shelf's own logged usage.
    Honesty rules: no logged usage ⇒ no budget (never a guess); the steady-state
    projection counts ONLY feeding in and water changes out — skimming, bacteria
    and algae all help you beyond this number, so reality should land lower."""
    tank_l = max(0.0, _f(tank_litres))
    load_n = load_p = 0.0
    feeding_ml_day = 0.0
    per_category: dict[str, float] = {}
    for product in products.values():
        if not isinstance(product, dict):
            continue
        daily = usage_ml_per_day(product, now)
        if not daily:
            continue
        density = CATEGORY_NUTRIENTS.get(str(product.get("category")),
                                         CATEGORY_NUTRIENTS["other"])
        feeding_ml_day += daily
        per_category[str(product.get("category"))] = round(
            per_category.get(str(product.get("category")), 0.0) + daily, 1)
        load_n += daily * density["n"]
        load_p += daily * density["p"]
    if feeding_ml_day <= 0 or tank_l <= 0:
        return {"available": False}
    no3_ppm_day = load_n * 4.43 / tank_l
    po4_ppm_day = load_p * 3.07 / tank_l
    fraction = max(0.0, _f(daily_exchange_l)) / tank_l
    steady_no3 = round(no3_ppm_day / fraction, 1) if fraction > 0 else None
    steady_po4 = round(po4_ppm_day / fraction, 3) if fraction > 0 else None
    if steady_no3 is None:
        verdict = "no_export"
    elif steady_no3 < NO3_BAND[0]:
        verdict = "clean"       # too clean for NPS — the corals starve politely
    elif steady_no3 <= NO3_BAND[1]:
        verdict = "balanced"
    else:
        verdict = "heavy"
    return {
        "available": True,
        "feedingMlPerDay": round(feeding_ml_day, 1),
        "perCategoryMlPerDay": per_category,
        "no3PpmPerDay": round(no3_ppm_day, 2),
        "po4PpmPerDay": round(po4_ppm_day, 4),
        "dailyExchangeL": round(max(0.0, _f(daily_exchange_l)), 2),
        "steadyNo3": steady_no3,
        "steadyPo4": steady_po4,
        "verdict": verdict,
    }


def shelf_summary(products: dict[str, Any], now: datetime, tank_l: Any = None,
                  tz: Any = None) -> dict[str, Any]:
    """The whole food shelf: per-product states plus the attention counts the
    tab header and (later) notifications read."""
    states: dict[str, dict[str, Any]] = {}
    low = expired = dose_due = 0
    for pid, product in products.items():
        if not isinstance(product, dict):
            continue
        state = consumable_state(product, now, tank_l, tz)
        states[str(pid)] = state
        if state["low"] or state["empty"]:
            low += 1
        if state["expiry"]["status"] == "expired":
            expired += 1
        if state["handDose"]["clock"]["due"]:
            dose_due += 1
    return {"products": states, "lowCount": low, "expiredCount": expired,
            "doseDueCount": dose_due, "count": len(states)}


# ---------------------------------------------------------------------------
# The unified feed timeline (doc §13): every mouthful that goes into the tank
# today — pumped, poured, harvested — on one 24 h strip, planned slots that
# fill in when they happen. Backend-computed so the NPS tab, the Feeding tab
# and the Pulse wall all read one list (the lockstep rule).

TIMELINE_NEXT_MAX = 3
TIMELINE_STATUSES: tuple[str, ...] = (
    "planned", "expected", "due", "late", "missed", "skipped", "blocked", "done", "ghost")


def _local_minute(iso: Any, today, tz: Any) -> tuple[int | None, Any]:
    """(minute-of-day if the stamp falls on ``today`` in ``tz``, the local date)."""
    parsed = _parse_iso(iso)
    if parsed is None:
        return None, None
    try:
        local = parsed.astimezone(tz) if tz is not None else parsed
    except (TypeError, ValueError):
        return None, None
    day = local.date()
    if day != today:
        return None, day
    return local.hour * 60 + local.minute, day


def _match_done(planned: list[dict[str, Any]], done: list[dict[str, Any]],
                tolerance_min: float) -> list[dict[str, Any]]:
    """Greedy: each logged dose takes the nearest unmatched planned slot within
    tolerance (an any-time chip takes anything); the rest are extras. Mutates
    the planned events in place, returns the unplanned extras."""
    extras: list[dict[str, Any]] = []
    for item in sorted(done, key=lambda d: d["at"]):
        best = None
        best_gap = None
        for ev in planned:
            if ev.get("doneAt") is not None or ev["status"] in ("skipped", "ghost"):
                continue
            if ev["at"] is None:
                gap = HAND_DOSE_ANYTIME_MATCH_MIN - 1
            else:
                gap = abs(ev["at"] - item["at"])
                if gap > tolerance_min:
                    continue
            if best is None or gap < best_gap:
                best, best_gap = ev, gap
        if best is None:
            extras.append({**item, "status": "done", "doneAt": item["at"], "unplanned": True})
        else:
            best["status"] = "done"
            best["doneAt"] = item["at"]
            if item.get("ml") is not None:
                best["actualMl"] = item["ml"]
    return extras


def _slot_status(at: int | None, now_min: int, *, unit: str, spacing_min: float,
                 carried: bool, skipped: bool) -> str:
    """The hand-slot ladder (doc §13.5, Q2 as locked): timed slots are due for
    a short window, then late; an hours cadence goes missed once its successor
    is due, a days cadence stays late until midnight — the shelf's overdue
    clock takes over next morning. Any-time chips are simply due all day."""
    if skipped:
        return "skipped"
    if at is None or carried:
        return "due"
    if at > now_min:
        return "planned"
    if now_min - at < HAND_DOSE_DUE_WINDOW_MIN:
        return "due"
    if unit == "hours" and spacing_min > 0 and now_min >= at + spacing_min:
        return "missed"
    return "late"


def feed_timeline(now_local: datetime, *, products: dict[str, Any], channels: dict[str, Any],
                  awc: dict[str, Any] | None = None, cultures: dict[str, Any] | None = None,
                  hatchery: dict[str, Any] | None = None,
                  brine_feeds: list[dict[str, Any]] | None = None,
                  lighting: dict[str, Any] | None = None, tank_l: Any = None,
                  fx_channel_id: str = "", fx_enabled: bool = False,
                  culture_bottle_species: Any = None) -> dict[str, Any]:
    """Today's feed strip. ``now_local`` must be tz-aware in the keeper's zone;
    every stamp is bucketed by that local day. Returns the events (sorted,
    any-time chips last), the night window, the next few, the counts and the
    plain-English honesty line."""
    tz = now_local.tzinfo
    today = now_local.date()
    now_min = now_local.hour * 60 + now_local.minute
    events: list[dict[str, Any]] = []
    bottle_species = set(culture_bottle_species or ())

    def ev(**fields: Any) -> dict[str, Any]:
        base = {"id": "", "at": None, "how": "hand", "source": "", "name": "", "productId": "",
                "ml": None, "actualMl": None, "status": "planned", "doneAt": None,
                "note": "", "kind": "dose", "band": None, "unplanned": False, "nextDate": None}
        base.update(fields)
        return base

    # --- Pumps: schedules as slots (the firmware owns the exact clock, so past
    # ticks are "expected"; the tick nearest the run stamp is the exact "done").
    for cid in sorted(channels):
        ch = channels[cid]
        if not isinstance(ch, dict) or ch.get("chemical") not in ("food", "livefood"):
            continue
        if ch.get("enabled") is False:
            continue
        sched = ch.get("schedule") if isinstance(ch.get("schedule"), dict) else {}
        ml_day = _f(sched.get("mlPerDay"))
        if not sched.get("enabled") or ml_day <= 0:
            continue
        name = str(ch.get("name") or cid)
        pid = str(((ch.get("reservoir") or {}) if isinstance(ch.get("reservoir"), dict) else {}).get("productId") or "")
        ws = _hhmm_min(sched.get("windowStart")) or 0
        we = _hhmm_min(sched.get("windowEnd")) or 0
        span = we - ws if we > ws else (1440 if we == ws else 1440 - ws + we)
        source = f"channel:{cid}"
        is_fx = bool(fx_channel_id) and str(cid) == str(fx_channel_id)
        note = "Live brine — the chaser flush banks owed drain for the matched exchange" if is_fx else ""
        if str(sched.get("mode") or "doses") == "continuous":
            events.append(ev(id=f"{source}:band", how="pump", source=source, name=name, productId=pid,
                             ml=round(ml_day, 2), kind="band", band=[ws, (ws + span) % 1440 or 1440],
                             status="planned", note=note or f"continuous — {ml_day:g} ml over the window"))
            continue
        n = max(1, min(96, int(_f(sched.get("dosesPerDay")) or 1)))
        step = span / n
        per = round(ml_day / n, 2)
        state = ch.get("state") if isinstance(ch.get("state"), dict) else {}
        last_min, _ = _local_minute(state.get("lastDoseAt"), today, tz)
        suspended = _parse_iso(state.get("suspendedUntil"))
        susp_min = None
        if suspended is not None:
            susp_min, susp_day = _local_minute(suspended.isoformat(), today, tz)
            if susp_min is None and susp_day is not None and susp_day > today:
                susp_min = 1440
        slots = []
        for i in range(n):
            t = int(round((ws + step * (i + 0.5)) % 1440))
            status = "planned" if t > now_min else "expected"
            if status == "planned" and susp_min is not None and t < susp_min:
                status = "blocked"
            slots.append(ev(id=f"{source}:{i}", at=t, how="pump", source=source, name=name,
                            productId=pid, ml=per, status=status,
                            note="paused by a guard — resumes when the suspension lifts" if status == "blocked" else note))
        if last_min is not None and slots:
            nearest = min(slots, key=lambda s: abs(s["at"] - last_min))
            nearest["status"] = "done"
            nearest["doneAt"] = last_min
        events.extend(slots)

    # --- The shelf: hand plans as slots (13.4), logged doses as done marks.
    hand_hint = False
    for pid in sorted(products):
        product = products[pid]
        if not isinstance(product, dict):
            continue
        plan = hand_dose_state(product, now_local, tank_l, tz)
        cad = hand_dose_slots(product)
        name = str(product.get("name") or pid)
        source = f"shelf:{pid}"
        done: list[dict[str, Any]] = []
        for item in (product.get("history") if isinstance(product.get("history"), list) else []):
            if not isinstance(item, dict) or item.get("kind") != "dose":
                continue
            minute, _ = _local_minute(item.get("at"), today, tz)
            if minute is not None:
                done.append({"at": minute, "ml": round(_f(item.get("ml")), 2)})
        if not cad["unit"]:
            # No cadence: anything logged today still shows — the strip is the day's truth.
            events.extend(ev(id=f"{source}:x{i}", at=d["at"], source=source, name=name, productId=pid,
                             ml=d["ml"], actualMl=d["ml"], status="done", doneAt=d["at"], unplanned=True)
                          for i, d in enumerate(done))
            continue
        skipped_min, skipped_day = _local_minute(product.get("doseSkippedAt"), today, tz)
        skipped_today = skipped_min is not None
        clock_at = _parse_iso(plan["clock"].get("at"))
        clock_day = clock_at.astimezone(tz).date() if clock_at is not None and tz is not None else (clock_at.date() if clock_at else today)
        ml = plan["ml"]
        note = plan["note"]
        if cad["unit"] == "days" and clock_day > today and not skipped_today:
            at = cad["slots"][0] if cad["slots"] else None
            events.append(ev(id=f"{source}:ghost", at=at, source=source, name=name, productId=pid, ml=ml,
                             status="ghost", nextDate=clock_day.isoformat(),
                             note=f"not today — next {clock_day.strftime('%a %d %b')}"))
            events.extend(ev(id=f"{source}:x{i}", at=d["at"], source=source, name=name, productId=pid,
                             ml=d["ml"], actualMl=d["ml"], status="done", doneAt=d["at"], unplanned=True)
                          for i, d in enumerate(done))
            continue
        carried = cad["unit"] == "days" and clock_day < today and not skipped_today
        slot_times: list[int | None] = list(cad["slots"]) if cad["slots"] else [None] * cad["perDay"]
        if not cad["slots"]:
            hand_hint = True
        planned = []
        spacing = cad["n"] * 60 if cad["unit"] == "hours" else 1440
        for i, t in enumerate(slot_times):
            planned.append(ev(id=f"{source}:{i}", at=t, source=source, name=name, productId=pid, ml=ml,
                              note=note, status="planned"))
        extras = _match_done(planned, done, spacing / 2 if cad["unit"] == "hours" else 1440)
        first_open = True
        for slot in planned:
            if slot["status"] == "done":
                continue
            slot["status"] = _slot_status(slot["at"], now_min, unit=cad["unit"], spacing_min=spacing,
                                          carried=carried and first_open, skipped=skipped_today)
            if carried and first_open and slot["status"] == "due":
                slot["note"] = (f"overdue since {clock_day.strftime('%a')} · " + note).strip(" ·")
            first_open = False
        for i, extra in enumerate(extras):
            extra.update({"id": f"{source}:x{i}", "source": source, "name": name, "productId": pid,
                          "actualMl": extra.get("ml"), "note": "extra dose — not on the plan"})
        events.extend(planned)
        events.extend(extras)

    # --- Cultures: a harvest into the display is a feed (Q6). Species with a
    # fridge bottle feed from the bottle; the rest go straight in.
    cultures = cultures if isinstance(cultures, dict) else {}
    jars = cultures.get("jars") if isinstance(cultures.get("jars"), dict) else {}
    for jid in sorted(jars):
        jar = jars[jid]
        if not isinstance(jar, dict):
            continue
        species = str(jar.get("species") or "")
        if species in bottle_species:
            continue
        state = jar.get("state") if isinstance(jar.get("state"), dict) else {}
        if not state.get("startedAt"):
            continue
        name = f"{jar.get('name') or jid} harvest"
        source = f"culture:{jid}"
        done = []
        for item in (jar.get("history") if isinstance(jar.get("history"), list) else []):
            if isinstance(item, dict) and item.get("event") == "harvest":
                minute, _ = _local_minute(item.get("at"), today, tz)
                if minute is not None:
                    done.append({"at": minute, "ml": round(_f(item.get("ml")), 1) or None})
        cad = jar.get("cadence") if isinstance(jar.get("cadence"), dict) else {}
        interval_d = _f(cad.get("harvestIntervalDays"))
        last = _parse_iso(state.get("lastHarvestAt"))
        planned = []
        if interval_d > 0:
            due_at = (last + timedelta(days=interval_d)) if last is not None else now_local
            due_day = due_at.astimezone(tz).date() if tz is not None else due_at.date()
            if due_day <= today:
                planned.append(ev(id=f"{source}:0", source=source, name=name, ml=None,
                                  status="due", note="pods straight into the display — the jar's own clock"))
        extras = _match_done(planned, done, 1440)
        for i, extra in enumerate(extras):
            extra.update({"id": f"{source}:x{i}", "source": source, "name": name,
                          "actualMl": extra.get("ml"), "note": "harvested into the display"})
        events.extend(planned)
        events.extend(extras)
    bottle = cultures.get("bottle") if isinstance(cultures.get("bottle"), dict) else {}
    for i, item in enumerate(bottle.get("history") if isinstance(bottle.get("history"), list) else []):
        if isinstance(item, dict) and item.get("event") == "fed_tank":
            minute, _ = _local_minute(item.get("at"), today, tz)
            if minute is not None:
                events.append(ev(id=f"cultures-bottle:x{i}", at=minute, source="cultures-bottle",
                                 name="Rotifers from the bottle", ml=round(_f(item.get("ml")), 1) or None,
                                 actualMl=round(_f(item.get("ml")), 1) or None, status="done", doneAt=minute,
                                 unplanned=True))

    # --- Hand-fed brine: the hatchery's feeds-a-day as any-time chips while
    # brine is on hand; the hand-feed reminder's completions are the done marks.
    hatchery = hatchery if isinstance(hatchery, dict) else {}
    if hatchery and not fx_enabled:
        res = hatchery.get("reservoir") if isinstance(hatchery.get("reservoir"), dict) else {}
        fridge = hatchery.get("fridgeBottle") if isinstance(hatchery.get("fridgeBottle"), dict) else {}
        on_hand = _f(res.get("remainingMl")) > 0 or _f(fridge.get("remainingMl")) > 0
        hand = hatchery.get("handFeed") if isinstance(hatchery.get("handFeed"), dict) else {}
        per_day = max(0, int(_f(hand.get("feedsPerDay"))))
        dose = round(_f(hand.get("defaultDoseMl")), 1) or None
        planned = [ev(id=f"brine:{i}", how="hand", source="brine", name="Live brine", ml=dose, status="due",
                      note="from the brine container — the hatchery card's Fed button logs it")
                   for i in range(per_day if on_hand else 0)]
        done = []
        for item in (brine_feeds or []):
            if isinstance(item, dict):
                minute, _ = _local_minute(item.get("at"), today, tz)
                if minute is not None:
                    done.append({"at": minute, "ml": round(_f(item.get("ml")), 1) or None})
        extras = _match_done(planned, done, 1440)
        for i, extra in enumerate(extras):
            extra.update({"id": f"brine:x{i}", "source": "brine", "name": "Live brine",
                          "actualMl": extra.get("ml"), "note": "hand-fed brine"})
        events.extend(planned)
        events.extend(extras)

    # --- The water exchange, quietly, below the axis.
    awc = awc if isinstance(awc, dict) else {}
    asched = awc.get("schedule") if isinstance(awc.get("schedule"), dict) else {}
    if awc.get("enabled") and asched.get("enabled"):
        if str(asched.get("mode") or "times") == "interval":
            ws = _hhmm_min(asched.get("windowStart")) or 0
            we = _hhmm_min(asched.get("windowEnd")) or 0
            span = we - ws if we > ws else (1440 if we == ws else 1440 - ws + we)
            events.append(ev(id="awc:band", how="system", source="awc", name="Water change", kind="band",
                             band=[ws, (ws + span) % 1440 or 1440], note="micro-changes through the window"))
        else:
            for i, t in enumerate(asched.get("times") if isinstance(asched.get("times"), list) else []):
                minute = _hhmm_min(t)
                if minute is not None:
                    events.append(ev(id=f"awc:{i}", at=minute, how="system", source="awc", name="Water change",
                                     status="planned" if minute > now_min else "expected",
                                     note="the Water Change tab owns the reservoirs"))

    # --- Night, next, counts, the honesty line.
    night = None
    if isinstance(lighting, dict) and lighting.get("configured"):
        on_min, off_min = _hhmm_min(lighting.get("onTime")), _hhmm_min(lighting.get("offTime"))
        if on_min is not None and off_min is not None and off_min > on_min:
            night = {"onMin": on_min, "offMin": off_min}

    events.sort(key=lambda e: (e["kind"] == "band", e["at"] is None, e["at"] if e["at"] is not None else 0,
                              e["how"] != "pump"))
    upcoming = [e for e in events if e["kind"] == "dose" and e["status"] in ("planned", "due", "late")]
    upcoming.sort(key=lambda e: (0 if e["at"] is None or e["at"] <= now_min else 1,
                                 e["at"] if e["at"] is not None else -1))
    nxt = []
    for e in upcoming[:TIMELINE_NEXT_MAX]:
        minutes = 0 if e["at"] is None or e["at"] <= now_min else e["at"] - now_min
        nxt.append({"id": e["id"], "name": e["name"], "how": e["how"], "at": e["at"], "ml": e["ml"],
                    "minutesUntil": minutes, "status": e["status"]})

    feeds = [e for e in events if e["kind"] == "dose" and e["how"] != "system" and e["status"] != "ghost"]
    counts = {
        "feeds": len(feeds),
        "pump": sum(1 for e in feeds if e["how"] == "pump"),
        "hand": sum(1 for e in feeds if e["how"] == "hand"),
        "done": sum(1 for e in feeds if e["status"] == "done"),
        "missed": sum(1 for e in feeds if e["status"] == "missed"),
        "late": sum(1 for e in feeds if e["status"] == "late"),
        "due": sum(1 for e in feeds if e["status"] == "due"),
        "extra": sum(1 for e in feeds if e["unplanned"]),
    }

    def _names(items: list[dict[str, Any]]) -> str:
        seen: list[str] = []
        for e in items:
            if e["name"] not in seen:
                seen.append(e["name"])
        return ", ".join(seen[:4]) + (f" +{len(seen) - 4}" if len(seen) > 4 else "")

    if not feeds and not any(e["kind"] == "band" and e["how"] == "pump" for e in events):
        text = "Nothing scheduled — schedules live on the pump cards, hand doses on the food shelf."
    else:
        parts = [f"{counts['feeds']} feed{'s' if counts['feeds'] != 1 else ''} today"]
        pumped = [e for e in feeds if e["how"] == "pump"]
        hand = [e for e in feeds if e["how"] == "hand"]
        bits = []
        if pumped:
            bits.append(f"{len(pumped)} pumped ({_names(pumped)})")
        if hand:
            bits.append(f"{len(hand)} by hand ({_names(hand)})")
        if bits:
            parts[0] += " — " + ", ".join(bits)
        tail = []
        if counts["done"]:
            tail.append(f"{counts['done']} done")
        if counts["missed"]:
            tail.append(f"{counts['missed']} missed")
        if counts["late"]:
            tail.append(f"{counts['late']} running late")
        text = ". ".join(parts + ([" · ".join(tail)] if tail else [])) + "."
    if hand_hint:
        text += " Set a first-dose time on the bottle and its chips land on the strip."

    return {
        "date": today.isoformat(),
        "nowMin": now_min,
        "night": night,
        "events": events,
        "next": nxt,
        "counts": counts,
        "text": text,
    }
