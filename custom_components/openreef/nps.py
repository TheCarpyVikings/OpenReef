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
# The jar's own harvest clock (0.7.158): the strip reads the same function the
# Cultures card and the culture reminders read — never a re-derived copy.
from .cultures import culture_state

RUNWAY_WINDOW_DAYS = 14        # usage averaging window for days-left forecasts
LOW_PERCENT_DEFAULT = 10.0     # lowThresholdMl 0 = auto ⇒ this % of the bottle
AGING_FRACTION = 0.25          # final quarter of shelf life ⇒ "aging" (dosing parity)

# Feed-exchange (Stage B): every live-food dose PLUS its line-flush chaser is
# water IN — the matched drain owes both back out so the tank level (and the
# ATO) never notices feeding. The hatchery's 24 h handling window is a
# planning default; unfed nauplii lose energy from hatch onward.
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


# --------------------------------------------------------------------------- #
# The hatchery stocks the shelf (doc §14, 0.7.149): the brine on hand is a
# shelf entry the keeper never types in. Two physical vessels, two entries,
# each on ITS batch's nutritional clock — the yolk window, or the boost window
# once gut-loaded (hatch_prime_state) — with the hand feeds as its usage log.
# --------------------------------------------------------------------------- #
LIVE_BRINE_CONTAINER_ID = "live_brine_container"
LIVE_BRINE_BOTTLE_ID = "live_brine_bottle"
LIVE_ROTIFER_BOTTLE_ID = "live_rotifer_bottle"
LIVE_ROTIFER_CONE_PREFIX = "live_rotifer_cone_"     # + the jar id (0.7.161)
LIVE_USAGE_ROWS = 60                                 # a source's usage rows carried into the shelf
LIVE_BRINE_VESSELS = {
    "container": {"id": LIVE_BRINE_CONTAINER_ID, "kind": "brine",
                  "name": "Live baby brine (container)", "where": "the brine container",
                  "brand": "Home hatchery", "stockedBy": "the hatchery"},
    "bottle": {"id": LIVE_BRINE_BOTTLE_ID, "kind": "brine",
               "name": "Live baby brine (fridge bottle)", "where": "the feeding bottle in the fridge",
               "brand": "Home hatchery", "stockedBy": "the hatchery"},
    # The rotifer harvest bottle (0.7.151): the Cultures tab's ledger, on the
    # species' fridge shelf (5 days), with the DHA boost as a second window.
    "rotifers": {"id": LIVE_ROTIFER_BOTTLE_ID, "kind": "rotifers",
                 "name": "Live rotifers (fridge bottle)", "where": "the rotifer bottle in the fridge",
                 "brand": "Home culture", "stockedBy": "the Cultures tab"},
}


def live_library(kind: str = "brine") -> dict[str, Any]:
    """The seeded home-culture entry for a live kind — its particle window
    is the one fact the species matcher needs, kept in one place."""
    brand, fallback = (("Home hatchery", {"particleUmMin": 400, "particleUmMax": 500})
                       if kind == "brine" else
                       ("Home culture", {"particleUmMin": 90, "particleUmMax": 360}))
    for item in PRODUCT_LIBRARY:
        if item.get("brand") == brand and (kind == "brine" or "rotifer" in str(item.get("name", "")).lower()):
            return dict(item)
    return fallback


def live_brine_library() -> dict[str, Any]:
    return live_library("brine")


def _harvest_went_to_tank(row: dict[str, Any], bottle_species: bool) -> bool:
    """A harvest row that fed the tank: stamped ``to: tank`` (0.7.161), or an
    older row from a species that never had a bottle."""
    to = str(row.get("to") or "")
    return to == "tank" or (not to and not bottle_species)


def _harvest_tank_ml(row: dict[str, Any], bottle_species: bool) -> float | None:
    """The volume that reached the tank: the rinsed crop when it was measured,
    else the harvest itself for a species that goes in with its water."""
    if _f(row.get("tankMl")) > 0:
        return round(_f(row.get("tankMl")), 1)
    if not bottle_species:
        return round(_f(row.get("ml")), 1) or None
    return None


def live_cone_product(jar_id: str, name: str, harvest_clock: dict[str, Any], harvest_ml: Any,
                      last_harvest_iso: Any, history: Any) -> dict[str, Any]:
    """A producing rotifer cone whose harvests go straight into the tank, as a
    shelf entry (0.7.161). A SOURCE, not a bottle: no capacity, no fill, no
    shelf life — feeding does not empty a culture. Its clock is the cone's
    own harvest clock and its usage the tank harvests that carried a volume,
    so coverage reads it as food on hand and the log can price the habit."""
    lib = live_library("rotifers")
    usage = [{"at": str(row.get("at") or ""), "ml": round(_f(row.get("tankMl")), 1), "kind": "dose"}
             for row in (history if isinstance(history, list) else [])
             if isinstance(row, dict) and row.get("event") == "harvest"
             and str(row.get("to") or "") == "tank" and _f(row.get("tankMl")) > 0]
    clock = harvest_clock if isinstance(harvest_clock, dict) else {}
    return {
        "name": f"Live rotifers ({name}, straight from the cone)", "brand": "Home culture",
        "category": "zooLive", "bottleMl": 0, "remainingMl": 0, "lowThresholdMl": 0,
        "openedAt": "", "shelfLifeDaysOpened": 0, "refrigerated": False, "stirDaily": False,
        "particleUmMin": lib.get("particleUmMin", 90), "particleUmMax": lib.get("particleUmMax", 360),
        "notes": "", "createdAt": "", "history": usage[-LIVE_USAGE_ROWS:],
        "doseMl": 0, "doseEveryDays": 0, "doseStocking": "medium", "doseGuide": {}, "doseNote": "",
        "lastDosedAt": "",
        "live": {
            "kind": "rotifers", "vessel": "cone", "source": True,
            "jarId": str(jar_id), "jarName": str(name),
            "where": f"the cone ({name})", "stockedBy": "the Cultures tab",
            "harvestDue": bool(clock.get("due")), "harvestAt": clock.get("at"),
            "harvestHoursUntil": clock.get("hoursUntil"), "harvestMl": round(_f(harvest_ml)) or None,
            "lastHarvestAt": str(last_harvest_iso or ""),
            "hoursLeft": None, "expired": False,
        },
    }


def live_brine_product(vessel: str, remaining_ml: Any, capacity_ml: Any,
                       loaded_iso: Any, prime: dict[str, Any],
                       hand_feeds: list[dict[str, Any]] | None = None,
                       soak: dict[str, Any] | None = None,
                       boost: dict[str, Any] | None = None) -> dict[str, Any]:
    """One live shelf entry in the product shape every shelf reader already
    understands, plus a ``live`` block that says where it came from and
    where its clock sits. ``prime`` is ``hatch_prime_state`` for a brine
    batch, or the same shape built off the rotifer bottle's shelf clock;
    ``soak`` (the enrichment state) marks a container mid gut-load, whose
    yolk clock must NOT condemn it (doc §10.3.1); ``boost`` (rotifers) is
    the DHA window running beside the shelf clock — its fading never
    expires the bottle, they are still live food.

    Mid-soak the entry reads ``enriching`` with the soak's hours left; a
    faded batch (yolk spent, the boost gone, the bottle past its shelf) is
    ``expired`` — still on the shelf until the keeper discards it, but no
    longer counted as covering a mouth."""
    meta = LIVE_BRINE_VESSELS.get(vessel) or LIVE_BRINE_VESSELS["container"]
    lib = live_library(meta["kind"])
    remaining = max(0.0, _f(remaining_ml))
    capacity = max(remaining, _f(capacity_ml))
    status = str(prime.get("status") or "unknown")
    hours_left = prime.get("primeLeftHours")
    window_h = prime.get("windowHours")
    window = prime.get("window")
    soaking = bool(soak and soak.get("status") == "enriching")
    if soaking:
        status, window = "enriching", "soak"
        hours_left = soak.get("hoursLeft")
        window_h = None
    expired = (not soaking) and status in ("fading", "boost_fading", "unknown")
    history = [
        {"at": feed.get("at"), "ml": round(max(0.0, _f(feed.get("ml"))), 1), "kind": "dose"}
        for feed in (hand_feeds or [])
        if isinstance(feed, dict) and not feed.get("undoneAt") and feed.get("at")
        and (str(feed.get("event") or "") == "fed_tank" if meta["kind"] == "rotifers"
             else str(feed.get("from") or "container") == vessel)]
    enriched = bool(prime.get("enriched")) or soaking
    boost_left = None
    if isinstance(boost, dict) and boost.get("status") in ("gutloaded", "faded"):
        enriched = True
        boost_left = round(max(0.0, _f(boost.get("hoursLeft"))), 1)
    return {
        "name": meta["name"], "brand": meta["brand"], "category": "zooLive",
        "bottleMl": round(capacity, 1), "remainingMl": round(remaining, 1),
        "lowThresholdMl": 0,
        "openedAt": str(loaded_iso or ""),
        "shelfLifeDaysOpened": round(_f(window_h) / 24.0, 3) if _f(window_h) > 0 else 0,
        "refrigerated": bool(prime.get("refrigerated")), "stirDaily": False,
        "particleUmMin": _f(lib.get("particleUmMin"), 400.0),
        "particleUmMax": _f(lib.get("particleUmMax"), 500.0),
        "notes": f"Stocked by the hatchery from {meta['where']} — the amount and the "
                 "clock follow the ledger; feed from it and both update.",
        "createdAt": str(loaded_iso or ""), "history": history,
        "doseMl": 0, "doseEveryDays": 0, "doseEveryHours": 0, "doseFirstAt": "",
        "doseTimesPerDay": 0, "doseWindowEnd": "", "doseStocking": "medium",
        "doseGuide": {}, "doseNote": "", "lastDosedAt": "", "doseSkippedAt": "",
        "live": {
            "source": "hatchery" if meta["kind"] == "brine" else "cultures",
            "kind": meta["kind"], "vessel": vessel, "where": meta["where"],
            "stockedBy": meta["stockedBy"],
            "status": status, "window": window,
            "hoursLeft": None if hours_left is None else round(max(0.0, _f(hours_left)), 1),
            "windowHours": None if window_h is None else round(_f(window_h), 1),
            "ageHours": prime.get("ageHours"),
            "enriched": enriched,
            # Rotifers only: the DHA boost's hours left beside the shelf
            # clock (None = never enriched; 0 = the boost has worn off).
            "boostHoursLeft": boost_left,
            "refrigerated": bool(prime.get("refrigerated")),
            "expired": expired,
            "loadedAt": str(loaded_iso or ""),
        },
    }


def rotifer_bottle_prime(bottle_state: dict[str, Any], shelf_days: Any) -> dict[str, Any]:
    """The rotifer bottle's shelf clock in ``hatch_prime_state``'s shape, so
    one builder serves both live kinds: ``prime`` while the fridge shelf
    holds, ``fading`` past it (or fail-closed with no stamp)."""
    status = str(bottle_state.get("status") or "empty")
    hours_left = bottle_state.get("hoursLeft")
    window_h = max(1.0, _f(shelf_days)) * 24.0
    age_h = None
    if hours_left is not None and status != "stale":
        age_h = round(max(0.0, window_h - _f(hours_left)), 1)
    return {"status": "fading" if status in ("stale", "empty") else "prime",
            "ageHours": age_h,
            "primeLeftHours": None if hours_left is None else round(max(0.0, _f(hours_left)), 1),
            "enriched": False, "window": "shelf", "windowHours": round(window_h, 1),
            "soakAgeHours": None, "refrigerated": True}


def live_expiry_state(live: dict[str, Any]) -> dict[str, Any]:
    """The shelf's expiry pill for a live entry, in HOURS off the nutritional
    clock rather than days off an opened stamp: the last quarter of the
    window is ``aging`` (the shelf's own AGING_FRACTION), the fade is
    ``expired``. A soak in progress is fresh food that is not ready yet."""
    hours_left = live.get("hoursLeft")
    window_h = _f(live.get("windowHours"))
    if live.get("status") == "enriching":
        return {"status": "fresh", "daysLeft": None, "ageDays": None,
                "hoursLeft": hours_left, "soaking": True}
    if live.get("expired") or hours_left is None:
        return {"status": "expired", "daysLeft": 0.0,
                "ageDays": None if live.get("ageHours") is None else round(_f(live.get("ageHours")) / 24.0, 2),
                "hoursLeft": 0.0, "soaking": False}
    left_h = max(0.0, _f(hours_left))
    if left_h <= 0:
        status = "expired"
    elif window_h > 0 and left_h <= window_h * AGING_FRACTION:
        status = "aging"
    else:
        status = "fresh"
    return {"status": status, "daysLeft": round(left_h / 24.0, 2),
            "ageDays": None if live.get("ageHours") is None else round(_f(live.get("ageHours")) / 24.0, 2),
            "hoursLeft": round(left_h, 1), "soaking": False}


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
        if event.get("undoneAt"):
            continue   # taken back — the ml never left the bottle
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


def spread_slots(n: Any, window_start: Any, window_end: Any = None) -> list[int]:
    """N feeds a day as minutes-of-day (doc §13.4, 0.7.134). No start = no
    slots (any-time chips). Start only = spread evenly across 24 h from the
    start. Start and end = spread evenly INSIDE the window, first feed at the
    start and last at the end (3 feeds 11:00–21:00 = 11:00, 16:00, 21:00); a
    window that wraps midnight is fine. One feed = the window start."""
    count = max(0, int(_f(n)))
    start = _hhmm_min(window_start)
    if count <= 0 or start is None:
        return []
    end = _hhmm_min(window_end)
    if end is None or end == start:
        return sorted(int(round(start + k * 1440 / count)) % 1440 for k in range(count))
    span = end - start if end > start else 1440 - start + end
    if count == 1:
        return [start]
    return sorted(int(round(start + i * span / (count - 1))) % 1440 for i in range(count))


def _window_text(start: Any, end: Any) -> str:
    start_min, end_min = _hhmm_min(start), _hhmm_min(end)
    if start_min is None:
        return ""
    if end_min is None or end_min == start_min:
        return f" from {_min_hhmm(start_min)}"
    return f", {_min_hhmm(start_min)}–{_min_hhmm(end_min)}"


def hand_dose_slots(product: dict[str, Any]) -> dict[str, Any]:
    """The bottle's daily slots, derived from its cadence (doc §13.4):
    ``doseTimesPerDay`` = N feeds a day spread across the feeding window
    (``doseFirstAt`` → ``doseWindowEnd``; no end = across 24 h; no start =
    any-time chips); ``doseEveryHours`` = every N hours from the anchor;
    ``doseEveryDays`` = one slot at the anchor on due days. Priority in that
    order."""
    per_day = max(0, int(_f(product.get("doseTimesPerDay"))))
    hours = max(0.0, _f(product.get("doseEveryHours")))
    days = max(0.0, _f(product.get("doseEveryDays")))
    anchor = _hhmm_min(product.get("doseFirstAt"))
    first_at = _min_hhmm(anchor) if anchor is not None else ""
    if per_day > 0:
        slots = spread_slots(per_day, product.get("doseFirstAt"), product.get("doseWindowEnd"))
        text = ("once a day" if per_day == 1 else f"{per_day} a day") + _window_text(product.get("doseFirstAt"), product.get("doseWindowEnd"))
        return {"unit": "perDay", "n": float(per_day), "firstAt": first_at, "perDay": per_day,
                "slots": slots, "text": text}
    if hours > 0:
        hours = min(HAND_DOSE_HOURS_MAX, hours)
        count = max(1, int(24.0 // hours))
        slots = sorted(int(round(anchor + k * hours * 60)) % 1440 for k in range(count)) if anchor is not None else []
        text = f"every {hours:g} h" + (f" from {first_at}" if first_at else "") + (f" · {count} a day" if count > 1 else "")
        return {"unit": "hours", "n": hours, "firstAt": first_at, "perDay": count, "slots": slots, "text": text}
    if days > 0:
        text = ("every day" if days == 1 else f"every {days:g} days") + (f" at {first_at}" if first_at else "")
        return {"unit": "days", "n": days, "firstAt": first_at, "perDay": 1,
                "slots": [anchor] if anchor is not None else [], "text": text}
    return {"unit": "", "n": 0.0, "firstAt": "", "perDay": 0, "slots": [], "text": ""}


def _anchored_slot(base: datetime, slots: list[int], unit: str, tz: Any) -> datetime:
    """Days cadence: the anchor time on ``base``'s date — the day cadence
    gates the day, the anchor places the slot. Hours / per-day: ``base`` is
    the last dose (or skip); it OWNS the nearest slot, and the next slot is
    the one after that — a dose ten minutes late still owns its slot, and an
    uneven window (11:00, 16:00, 21:00) needs no spacing arithmetic."""
    local = base.astimezone(tz) if tz is not None else base
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    ordered = sorted(slots)
    if unit == "days":
        return day + timedelta(minutes=ordered[0])
    candidates = sorted(day + timedelta(days=d, minutes=slot) for d in (-1, 0, 1, 2) for slot in ordered)
    owned = min(candidates, key=lambda c: abs((c - local).total_seconds()))
    return next(c for c in candidates if c > owned)


def hand_dose_undo(product: dict[str, Any], now: datetime) -> dict[str, Any]:
    """The newest hand dose still inside the undo window (a day — the strip
    shows today, and any of today's feeds can be taken back, doc §13.16).
    Only ``dose`` rows (the keeper's taps) count; pump debits and transfers
    are the machine's; a tombstoned row (``undoneAt``) is already gone."""
    history = product.get("history") if isinstance(product.get("history"), list) else []
    for item in reversed(history):
        if not isinstance(item, dict) or item.get("kind") != "dose" or item.get("undoneAt"):
            continue
        at = _parse_iso(item.get("at"))
        if at is None:
            break
        try:
            age_min = (now - at).total_seconds() / 60.0
        except TypeError:
            break
        if 0 <= age_min <= HAND_DOSE_UNDO_MIN:
            return {"available": True, "ml": round(_f(item.get("ml")), 2), "at": str(item.get("at")),
                    "minutesLeft": round(HAND_DOSE_UNDO_MIN - age_min, 1)}
        break
    return {"available": False, "ml": None, "at": None, "minutesLeft": None}


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
        elif cadence["unit"] == "perDay":
            at = base + timedelta(hours=24.0 / max(1.0, cadence["n"]))
        else:
            at = base + timedelta(days=cadence["n"])
        if cadence["slots"]:
            at = _anchored_slot(base if cadence["unit"] != "days" else at, cadence["slots"], cadence["unit"], tz)
        try:
            delta_h = (at - now).total_seconds() / 3600.0
        except TypeError:
            delta_h = 0.0
        clock = {"available": True, "due": delta_h <= 0, "at": at.isoformat(),
                 "hoursUntil": round(max(0.0, delta_h), 1), "hoursOverdue": round(max(0.0, -delta_h), 1)}
    undo = hand_dose_undo(product, now)
    return {
        "planned": bool(cadence["unit"] or explicit > 0),
        "ml": ml,
        "undo": undo,
        "everyDays": every_days if cadence["unit"] == "days" else 0.0,
        "everyHours": every_hours if cadence["unit"] == "hours" else 0.0,
        "timesPerDay": cadence["perDay"] if cadence["unit"] == "perDay" else 0,
        "windowEnd": str(product.get("doseWindowEnd") or "") if cadence["unit"] == "perDay" else "",
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
    live = product.get("live") if isinstance(product.get("live"), dict) else None
    # A live entry (the hatchery's brine, doc §14) runs the nutritional clock
    # in hours, and is never "low": the hatchery's next-hatch maths owns its
    # runway, the shelf only reports it.
    expiry = live_expiry_state(live) if live else expiry_state(product, now)
    days_left = round(remaining / daily, 1) if daily and daily > 0 else None
    return {
        "bottleMl": bottle,
        "remainingMl": round(remaining, 1),
        "percent": round(remaining / bottle * 100.0, 1) if bottle > 0 else None,
        "usageMlPerDay": round(daily, 2) if daily else None,
        "daysUntilEmpty": days_left,
        "low": bool(bottle > 0 and remaining <= low_threshold) and not live,
        "empty": bool(bottle > 0 and remaining <= 0),
        "expiry": expiry,
        "stirDaily": bool(product.get("stirDaily")),
        "refrigerated": bool(product.get("refrigerated")),
        "categoryLabel": category_label(product.get("category")),
        "handDose": hand_dose_state(product, now, tank_l, tz),
        **({"live": dict(live)} if live else {}),
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


# Hatchery planning presets, not supplier ratings or observations of hatch-out.
# See docs/hatchery-audit-2026-09-10.md for evidence and model limitations.
EGG_TYPES: tuple[dict[str, Any], ...] = (
    {"id": "standard", "name": "Standard cysts (GSL)", "hours": 24,
     "note": "24 h starting estimate at 25–28 °C. Follow the supplier's salinity, light and aeration guidance; inspect hatch-out."},
    {"id": "decapsulated", "name": "Decapsulated cysts", "hours": 24,
     "note": "Use hatchable decapsulated cysts; dried feed-only products may not hatch. Timing depends on the product, not shell removal alone."},
    {"id": "premium", "name": "High-hatch premium cysts", "hours": 24,
     "note": "High hatch percentage describes yield, not speed. Start with the supplier's hatch time; 24 h is a planning default."},
    {"id": "cool_room", "name": "Cool room (below ~24 °C)", "hours": 36,
     "note": "36 h planning estimate only; cool-water hatches can take longer. Check hatch-out and the supplier's guidance."},
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

# 2 g/L is a conservative starting density. The temperature multiplier is
# an uncalibrated heuristic; it is not a universal Artemia growth equation.
HATCH_VESSEL_CAP = 4
HATCH_CYST_G_PER_L = 2.0
HATCH_TEMP_OPTIMUM_C = 28.0
HATCH_HISTORY_MAX = 50
HAND_FEED_LOG_MAX = 60        # stamped container/bottle feeds the strip reads (doc §13.10)
HAND_DOSE_UNDO_MIN = 24 * 60  # any of TODAY's feeds can be taken back (doc §13.16) — the strip shows the day

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

# Post-enrichment handling limits, not measured HUFA retention. Cold-storage
# results for unfed nauplii cannot establish enriched DHA retention. Selcon's
# current FAQ allows 1–12 h with aeration; the 12 h default is configurable.
# A second full dose at +10 h is opt-in and must suit the chosen product.
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
    # Fix the expiry at fridge entry. Recomputing age + max(remaining, 0)
    # moved an expired batch's deadline forward on every read.
    if room_spent_h >= room:
        return round(room + saved, 10)
    return round(in_at_h + (1.0 - room_spent_h / room) * fridge, 10)


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
    """Advisory heuristic: preset × (1 + 0.08 × degrees below 28 °C).

    This is not fitted to a cyst batch or validated across strains. Only
    provide numerical estimates at 18–32 °C; flag excessive heat separately.
    The input is a preset, never the keeper’s observed harvest duration, so
    a temperature effect is not counted twice. It never changes a real clock."""
    base = _f(base_hours)
    if base <= 0:
        base = 24.0
    temp = _f(temp_c, -999.0)
    if temp < 18 or temp > 32:
        return {"available": False, "expectedHours": None, "factor": None,
                "warm": 30 < temp <= 60}
    factor = 1.0 + max(0.0, (HATCH_TEMP_OPTIMUM_C - temp)) * 0.08
    factor = min(factor, 2.2)
    return {"available": True,
            "expectedHours": round(base * factor, 1),
            "factor": round(factor, 2),
            "warm": temp > 30.0}


def learned_hatch_hours(history: Any, egg_type: str, vessel_id: str = "") -> dict[str, Any]:
    """Last three logged start-to-harvest durations, optionally per vessel.
    Includes keeper delay: this does not measure biological hatch completion.
    Needs two samples and never applies a new clock automatically."""
    if not isinstance(history, list):
        return {"available": False, "hours": None, "samples": 0}
    actuals = [
        _f(item.get("actualHours"))
        for item in history
        if isinstance(item, dict) and item.get("eggType") == egg_type
        and (not vessel_id or item.get("vesselId") == vessel_id)
        and _f(item.get("actualHours")) > 0
    ]
    actuals = actuals[:3]
    if len(actuals) < 2:
        return {"available": False, "hours": None, "samples": len(actuals)}
    return {"available": True,
            "hours": round(sum(actuals) / len(actuals), 1),
            "samples": len(actuals)}


def vessels_needed(hatch_hours: Any, shelf_hours: Any) -> int:
    """Ideal steady-state vessel count, ceil(cycle / usable supply window).
    Assumes even spacing and immediate restart; mixed clocks need rack_rhythm."""
    hours = _f(hatch_hours)
    if hours <= 0:
        hours = 24.0
    shelf = _f(shelf_hours)
    if shelf <= 0:
        shelf = 24.0
    # Harvest handling overlaps the next incubation, as rack_rhythm assumes.
    # The buffer delays the first supply, not every steady-state cycle.
    return max(1, int(-(-hours // shelf)))


HATCH_RHYTHM_TIGHT_H = 2.0   # a gap this close to the shelf counts as tight
HATCH_RHYTHM_STEP_H = 0.5    # the grid the "hold it back" search walks


def rack_rhythm(
    now: datetime,
    vessels: Any,
    shelf_hours: Any,
    horizon_hours: Any = None,
) -> dict[str, Any]:
    """Where the rack's loads actually LAND, and the one delay that evens them.

    ``vessels_needed`` answers how many cones continuous supply takes; it says
    nothing about their phase. Two cones that land three hours apart and then
    go quiet for a day satisfy the count and still run the tank dry. This
    projects the real schedule instead of assuming an even rotation.

    Each vessel is walked forward on its OWN clock (0.7.147: different cysts
    per cone), restarting the moment it is harvested — a batch started at ``t``
    frees the cone at ``t + clock`` and reaches the container at
    ``t + clock + HATCH_HARVEST_BUFFER_H``. Batches already incubating cannot
    be moved, so their load rides along fixed. An idle cone is projected from
    now, its best case.

    ``vessels`` takes ``{"id", "name", "hatchHours", "startedAt", "batchHours"}``
    dicts; no ``startedAt`` means idle. The measure is the widest gap between
    consecutive loads: wider than the shelf and the brine runs out
    (``status`` ``dry``), within ``HATCH_RHYTHM_TIGHT_H`` of it and the rhythm
    holds with no margin (``tight``), otherwise ``even``.

    ``fix`` is the single actionable lever the keeper has — hold ONE cone back
    on its next start (an idle one: start it later). The search walks every
    vessel across a ``HATCH_RHYTHM_STEP_H`` grid up to one of its own cycles
    and keeps the delay that shrinks the worst gap most, shortest delay
    winning ties. It is only offered when the WIDEST gap actually narrows:
    leximin ranks the candidates, but shaving a lesser gap while the widest
    still outruns the shelf changes nothing the tank can feel.

    The measure starts at the first load the keeper can still MOVE — batches
    already incubating are committed, and the hole a clustered pair leaves
    behind them is the same under every plan. That hole is real, and it is
    ``next_hatch_suggestion``'s to report (``blocked``/``lateHours``, 0.7.154);
    counting it here would headline a number no choice can change and drown
    the rhythm underneath it. ``fromAt`` says where the window opens.

    Plans are then ranked LEXIMIN — the gap list sorted widest-first, compared
    element by element — so a plan that ties on the worst gap but evens out
    everything below it still wins. The window runs one full cycle PAST the
    reported horizon, counting every gap that STARTS inside it, so a delay can
    never flatter itself by pushing a load out of view.

    ``matched`` is the honest fallback when no delay helps: unequal clocks can
    lock a rhythm that no phase shift can open (36 h and 24 h repeat every
    72 h around a fixed 24 h hole), while one shared clock across ``n`` cones
    would land a batch every ``clock / n``. Advisory — it never says which
    cysts to buy.
    """
    shelf = _f(shelf_hours)
    if shelf <= 0:
        shelf = 24.0
    out: dict[str, Any] = {
        "available": False, "status": "even", "shelfHours": round(shelf, 1),
        "worstGapHours": None, "averageGapHours": None, "loads": [],
        "horizonHours": None, "fix": None, "matched": None, "vesselCount": 0,
        "fromAt": None,
    }
    entries: list[dict[str, Any]] = []
    for item in vessels or []:
        if not isinstance(item, dict):
            continue
        clock = _f(item.get("hatchHours"))
        if clock <= 0:
            clock = 24.0
        started = _parse_iso(item.get("startedAt"))
        batch_h = _f(item.get("batchHours"))
        if batch_h <= 0:
            batch_h = clock
        entries.append({
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or item.get("id") or ""),
            "clock": clock,
            # The cone empties at harvest; the brine reaches the container a
            # harvest buffer later. A ripe batch frees it now, never in the past.
            "free": max(started + timedelta(hours=batch_h), now) if started else now,
            "pending": (max(started + timedelta(hours=batch_h), now)
                        + timedelta(hours=HATCH_HARVEST_BUFFER_H)) if started else None,
            "idle": started is None,
        })
    if not entries:
        return out
    out["vesselCount"] = len(entries)
    horizon = _f(horizon_hours)
    if horizon <= 0:
        horizon = max(48.0, 3.0 * max(e["clock"] for e in entries))
    end = now + timedelta(hours=horizon)

    # Project one whole cycle past the horizon: the measure only counts gaps
    # that START in-window, but it needs the load that CLOSES the last one.
    tail = end + timedelta(hours=max(e["clock"] for e in entries) + HATCH_HARVEST_BUFFER_H)

    def loads_for(entry: dict[str, Any], delay_h: float = 0.0) -> list[datetime]:
        got: list[datetime] = []
        if entry["pending"] is not None and entry["pending"] <= tail:
            got.append(entry["pending"])
        start = entry["free"] + timedelta(hours=delay_h)
        while True:
            load = start + timedelta(hours=entry["clock"] + HATCH_HARVEST_BUFFER_H)
            if load > tail:
                break
            got.append(load)
            start = start + timedelta(hours=entry["clock"])
        return got

    # The window opens at the earliest load still on the table — everything
    # before it is already in a cone and cannot be re-timed.
    cutoff = min(e["free"] + timedelta(hours=e["clock"] + HATCH_HARVEST_BUFFER_H)
                 for e in entries)

    def gaps_of(loads: list[datetime]) -> list[float]:
        """Every movable gap that STARTS inside the horizon, widest first."""
        ordered = sorted(loads)
        gaps = [(b - a).total_seconds() / 3600.0
                for a, b in zip(ordered, ordered[1:]) if cutoff <= a <= end]
        gaps.sort(reverse=True)
        return gaps

    base = gaps_of([load for entry in entries for load in loads_for(entry)])
    if not base:
        return out
    worst, average = base[0], sum(base) / len(base)
    out.update({
        "available": True,
        "fromAt": cutoff.isoformat(),
        "loads": [d.isoformat() for d in sorted(
            load for entry in entries for load in loads_for(entry)
            if cutoff <= load <= end)[:24]],
        "worstGapHours": round(worst, 1),
        "averageGapHours": round(average, 1),
        "horizonHours": round(horizon, 1),
        "status": ("dry" if worst > shelf
                   else "tight" if worst > shelf - HATCH_RHYTHM_TIGHT_H else "even"),
    })
    if out["status"] == "even":
        return out

    best: tuple[list[float], float, dict[str, Any]] | None = None
    for idx, entry in enumerate(entries):
        others = [load for j, other in enumerate(entries) if j != idx
                  for load in loads_for(other)]
        steps = int(max(1.0, entry["clock"]) / HATCH_RHYTHM_STEP_H)
        for step in range(1, steps + 1):
            delay = step * HATCH_RHYTHM_STEP_H
            candidate = gaps_of(others + loads_for(entry, delay))
            if not candidate:
                continue
            if best is None or candidate < best[0] or (candidate == best[0] and delay < best[1]):
                best = (candidate, delay, entry)
    # Leximin RANKS the plans; the WORST gap gates them. Shaving the second
    # gap while the widest one still outruns the shelf does not stop the tank
    # going without — it just spends a keeper's evening for nothing.
    if best is not None and best[0][0] <= worst - HATCH_RHYTHM_STEP_H:
        gap_after, delay, entry = best[0][0], best[1], best[2]
        out["fix"] = {
            "vesselId": entry["id"], "vesselName": entry["name"],
            "delayHours": round(delay, 1), "gapAfterHours": round(gap_after, 1),
            "idle": bool(entry["idle"]),
        }
        return out

    # No phase shift helps. Unequal clocks are the usual reason, and one
    # shared clock across the rack lands a batch every clock / n.
    clocks = {entry["clock"] for entry in entries}
    if len(clocks) > 1:
        slowest = max(clocks)
        even_gap = slowest / len(entries)
        if even_gap < worst - HATCH_RHYTHM_STEP_H:
            out["matched"] = {"clockHours": round(slowest, 1),
                              "gapHours": round(even_gap, 1)}
    return out


def cyst_dose_guide(volume_l: Any) -> dict[str, Any]:
    """Grams at a 2 g/L starting density; count assumes 225,000 nauplii/g.
    The count is illustrative, not a measurement of this cyst batch's yield."""
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
    free_at_iso: Any = None,
    load_volume_ml: Any = None,
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

    ``blocked`` (0.7.154) is the full-rack case. The ideal start assumes a cone
    is free to take the cysts; with every one of them mid-hatch it is a moment
    nothing can honour. ``free_at_iso`` says when the first cone frees — pass it
    ONLY when every vessel is busy (an idle cone can start whenever the maths
    asks) — and when that lands after the ideal start, ``startAt`` becomes the
    free moment and ``lateHours`` owns how far past ``readyBy`` the batch then
    arrives. The shortfall is exactly the delay: the ideal start lands ON
    ``readyBy``, so every hour of waiting for a cone is an hour without brine.

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
    rate = _f(ml_per_day)
    load_ml = _f(load_volume_ml)
    if rate > 0 and load_ml > 0:
        chain_shelf_h = min(chain_shelf_h, load_ml / rate * 24.0)
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
        "overlap": chain_shelf_h < hours,
        "busyCount": len(running),
        "chainVessel": None,
        "chainLoadsAt": None,
        "freeAt": None,
        "lateHours": None,
        "supplyGapHours": None,
        "chainShelfHours": round(chain_shelf_h, 1),
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
            if ready_by is not None:
                out["lateHours"] = round(max(0.0, (
                    max(start_at, now) + timedelta(hours=lead_h) - ready_by
                ).total_seconds() / 3600.0), 1)
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
        if remaining == 0:
            supply_end, supply_driver = now, "depletion"
        elif remaining > 0 and rate > 0:
            deplete_by = now + timedelta(hours=remaining / rate * 24.0)
            if deplete_by < supply_end:
                supply_end, supply_driver = deplete_by, "depletion"

    # Every cone busy (0.7.154): the earliest REAL start is when one frees. A
    # ripe-but-unharvested batch frees the moment you pull it, so floor at now.
    free_at = _parse_iso(free_at_iso)
    if free_at is not None:
        free_at = max(free_at, now)
        base["freeAt"] = free_at.isoformat()

    if running:
        # Report holes before the final incoming load as well as planning
        # the batch after it. A late final load cannot cover an earlier gap.
        covered_until = max(now, supply_end) if supply_end is not None else now
        first_gap = 0.0
        for load_at in sorted(max(stamp + timedelta(hours=batch_h), now)
                              + timedelta(hours=HATCH_HARVEST_BUFFER_H)
                              for stamp, batch_h, _vid in running):
            if load_at > covered_until and not first_gap:
                first_gap = (load_at - covered_until).total_seconds() / 3600.0
            covered_until = max(covered_until, load_at + timedelta(hours=chain_shelf_h))
        base["supplyGapHours"] = round(first_gap, 1)
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
        base["chainLoadsAt"] = (anchor_dt + timedelta(hours=HATCH_HARVEST_BUFFER_H)).isoformat()
        ready_by, driver = anchor_dt + timedelta(hours=HATCH_HARVEST_BUFFER_H + chain_shelf_h), "chain"
        if supply_end is not None and supply_end > ready_by:
            ready_by, driver = supply_end, supply_driver
        start_at = ready_by - timedelta(hours=lead_h)
        if free_at is not None and free_at > max(start_at, now):
            # No vessel can honour the ideal start: name the moment one frees
            # and be honest about landing after the deadline rather than
            # printing a time the rack cannot keep.
            base["lateHours"] = round(
                (free_at + timedelta(hours=lead_h) - ready_by).total_seconds() / 3600.0, 1)
            return _finish("blocked", free_at, ready_by, driver)
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
    if temp < 18 or temp > 32:
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
    """The logged batch’s handling window, not a nutrient or viability assay.

    Legacy statuses ``prime``/``fading`` describe the plain 24 h warm / 48 h
    cold planning budget counted from load. Actual hatch age is unknown.
    ``gutloaded``/``boost_fading`` describe the enriched 12 h warm / 48 h
    cold budget counted from planned soak end. They cannot certify DHA
    content: product, strain, oxygen, density and temperature all matter.

    Both use brine_window_hours so refrigeration credit and expiry agree.
    ``refrigerated`` is the legacy cold-since-window-start flag."""
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
# group (0.7.150): the family the Settings grid files each species under —
# stony / gorgonian / soft / filter. Ids are config keys: never rename one.
# --------------------------------------------------------------------------- #
SPECIES_GROUPS: tuple[tuple[str, str], ...] = (
    ("stony", "Stony NPS corals"),
    ("gorgonian", "Gorgonians (non-photosynthetic)"),
    ("soft", "Soft corals, sea pens & lace corals"),
    ("filter", "Filter feeders, worms, anemones & echinoderms"),
)

SPECIES_LIBRARY: tuple[dict[str, Any], ...] = (
    {"id": "tubastraea", "group": "stony", "name": "Sun coral (Tubastraea)", "difficulty": 1,
     "particleUmMin": 300, "particleUmMax": 3000, "cadence": "pulse",
     "feedsPerDay": 1, "night": True, "trainable": True,
     "foods": ("zooPrepared", "zooLive", "blend"),
     "note": "Target feeding is what works; broadcast alone leaves polyps unfed. "
             "Trainable to open in daylight by feeding at the same time daily."},
    {"id": "dendrophyllia", "group": "stony", "name": "Dendrophyllia / Balanophyllia", "difficulty": 2,
     "particleUmMin": 300, "particleUmMax": 3000, "cadence": "pulse",
     "feedsPerDay": 2, "night": True, "trainable": True,
     "foods": ("zooPrepared", "zooLive", "blend"),
     "note": "Sun-coral care but hungrier — more feeds, more volume."},
    {"id": "chili", "group": "soft", "name": "Chili coral", "difficulty": 2,
     "particleUmMin": 150, "particleUmMax": 500, "cadence": "pulse",
     "feedsPerDay": 1, "night": True, "trainable": False,
     "foods": ("zooLive", "zooPrepared"),
     "note": "Strictly nocturnal — feed after lights-out when the polyps are open; "
             "baby brine and decapsulated cysts are the perfect mouthful."},
    {"id": "gorgonian_easy", "group": "gorgonian", "name": "Gorgonians — Menella, Swiftia, Diodogorgia",
     "difficulty": 2, "particleUmMin": 50, "particleUmMax": 500, "cadence": "pulse",
     "feedsPerDay": 1, "night": False, "trainable": False,
     "foods": ("zooPrepared", "zooLive"),
     "note": "The recommended starter NPS. Food must be no larger than the polyp mouth."},
    {"id": "gorgonian_hard", "group": "gorgonian", "name": "Gorgonians — Euplexaura, Guaiagorgia",
     "difficulty": 3, "particleUmMin": 50, "particleUmMax": 300, "cadence": "pulse",
     "feedsPerDay": 2, "night": False, "trainable": False,
     "foods": ("zooPrepared", "zooLive"),
     "note": "Daily fine zooplankton, no days off."},
    {"id": "rhizotrochus", "group": "stony", "name": "Rhizotrochus typus", "difficulty": 3,
     "particleUmMin": 1000, "particleUmMax": 20000, "cadence": "target",
     "feedsPerDay": 0, "night": True, "trainable": False,
     "foods": ("zooPrepared",),
     "note": "Whole meaty items by hand, 2–3× a week. Deepwater — runs happier cool."},
    {"id": "blueberry", "group": "gorgonian", "name": "Blueberry gorgonian (Acalycigorgia)", "difficulty": 5,
     "particleUmMin": 5, "particleUmMax": 200, "cadence": "continuous",
     "feedsPerDay": 8, "night": False, "trainable": False,
     # 0.7.162: oyster eggs are in its own note — prepared zooplankton was missing.
     "foods": ("phyto", "zooLive", "zooPrepared"),
     "note": "'Cut flowers of the hobby.' Near-continuous micro-plankton, rotifers, "
             "oyster eggs. Expert-only, honestly."},
    {"id": "dendronephthya", "group": "soft", "name": "Dendronephthya / Scleronephthya", "difficulty": 5,
     "particleUmMin": 1, "particleUmMax": 20, "cadence": "continuous",
     "feedsPerDay": 12, "night": False, "trainable": False,
     "foods": ("phyto",),
     "note": "Mostly a PHYTO feeder (weak nematocysts — 50–200× more carbon from "
             "phyto than zoo). The only proven method is a standing live-phyto "
             "density (5,000–50,000 cells/mL — a faint green tint), dosed "
             "continuously."},
    {"id": "filterfeeders", "group": "filter", "name": "Sponges, tunicates, flame scallops", "difficulty": 4,
     "particleUmMin": 1, "particleUmMax": 40, "cadence": "continuous",
     "feedsPerDay": 8, "night": False, "trainable": False,
     "foods": ("phyto", "bacteria"),
     "note": "Obligate filter feeders; decline is invisible until it's late. "
             "Standing phyto density is what keeps them."},
    {"id": "crinoid", "group": "filter", "name": "Feather star (crinoid)", "difficulty": 5,
     "particleUmMin": 300, "particleUmMax": 500, "cadence": "continuous",
     "feedsPerDay": 4, "night": False, "trainable": False,
     "foods": ("zooLive", "zooPrepared"),
     "note": "Two documented long-term successes, ever. The working protocol: four "
             "feeds a day, each spread over two hours, indefinitely."},
    # ---- 0.7.150: the catalogue expanded to the species the hobby actually keeps.
    {"id": "tubastraea_black", "group": "stony",
     "name": "Black sun coral (Tubastraea micranthus)", "difficulty": 3,
     "particleUmMin": 300, "particleUmMax": 3000, "cadence": "pulse",
     "feedsPerDay": 2, "night": True, "trainable": True,
     "foods": ("zooPrepared", "zooLive", "blend"),
     "note": "The tree-shaped sun coral: strong flow and more feeds than its orange "
             "cousins, or it starves quietly from the branch tips inward."},
    {"id": "gorgonian_atlantic", "group": "gorgonian",
     "name": "Atlantic sea whips — Leptogorgia, Lophogorgia", "difficulty": 2,
     "particleUmMin": 100, "particleUmMax": 500, "cadence": "pulse",
     "feedsPerDay": 1, "night": False, "trainable": False,
     "foods": ("zooPrepared", "zooLive"),
     "note": "Gulf and Caribbean collected — hardy for an NPS gorgonian; baby brine "
             "and Cyclops-sized foods suit the polyps."},
    {"id": "gorgonian_purple", "group": "gorgonian",
     "name": "Purple & red gorgonians — Astrogorgia, Muriceides, Nicella", "difficulty": 3,
     "particleUmMin": 50, "particleUmMax": 300, "cadence": "pulse",
     "feedsPerDay": 2, "night": False, "trainable": False,
     "foods": ("zooPrepared", "zooLive"),
     "note": "The Indo-Pacific imports sold as 'purple gorgonian'. Fine zooplankton "
             "daily; polyps out by day once settled."},
    {"id": "gorgonian_whip", "group": "gorgonian",
     "name": "Sea whips — Ellisella, Junceella, Ctenocella, Viminella", "difficulty": 3,
     "particleUmMin": 50, "particleUmMax": 300, "cadence": "pulse",
     "feedsPerDay": 2, "night": False, "trainable": False,
     "foods": ("zooPrepared", "zooLive"),
     "note": "The red and orange whips and candelabras. Fine zooplankton in strong "
             "laminar flow; algae taking the branches means it is losing."},
    {"id": "gorgonian_fan", "group": "gorgonian",
     "name": "Sea fans — Melithaea, Subergorgia, Annella", "difficulty": 4,
     "particleUmMin": 50, "particleUmMax": 300, "cadence": "pulse",
     "feedsPerDay": 3, "night": False, "trainable": False,
     "foods": ("zooPrepared", "zooLive"),
     "note": "Big fine-polyp fans: thousands of mouths, so several small feeds "
             "spread across the day rather than one. Bare patches never regrow."},
    {"id": "chironephthya", "group": "soft",
     "name": "Chironephthya / Siphonogorgia", "difficulty": 3,
     "particleUmMin": 50, "particleUmMax": 300, "cadence": "pulse",
     "feedsPerDay": 2, "night": True, "trainable": False,
     "foods": ("zooLive", "zooPrepared", "phyto"),
     "note": "The stiff-stalked NPS soft corals. Polyps open after dark — feed then, "
             "fine zooplankton with a little phyto."},
    {"id": "studeriotes", "group": "soft",
     "name": "Christmas tree coral (Studeriotes)", "difficulty": 4,
     "particleUmMin": 50, "particleUmMax": 300, "cadence": "pulse",
     "feedsPerDay": 2, "night": True, "trainable": False,
     "foods": ("zooLive", "zooPrepared", "phyto"),
     "note": "Retracts fully into its stalk by day and grows the crown back at night; "
             "it only feeds while the crown is out."},
    {"id": "seapen", "group": "soft",
     "name": "Sea pens — Cavernularia, Pteroeides, Virgularia", "difficulty": 4,
     "particleUmMin": 20, "particleUmMax": 300, "cadence": "pulse",
     "feedsPerDay": 2, "night": True, "trainable": False,
     "foods": ("zooLive", "zooPrepared", "phyto"),
     "note": "Needs a deep sand bed to anchor its foot; the crown rises after "
             "lights-out. Fine zooplankton and phyto then."},
    {"id": "lacecoral", "group": "soft",
     "name": "Lace corals — Distichopora, Stylaster", "difficulty": 5,
     "particleUmMin": 20, "particleUmMax": 200, "cadence": "continuous",
     "feedsPerDay": 6, "night": False, "trainable": False,
     "foods": ("zooLive", "zooPrepared", "phyto"),
     "note": "Hydrocorals, not true corals: tiny polyps, near-continuous fine plankton "
             "and rock-steady water. Most fade over months — honestly."},
    {"id": "cerianthus", "group": "filter",
     "name": "Tube anemone (Cerianthus)", "difficulty": 2,
     "particleUmMin": 500, "particleUmMax": 5000, "cadence": "pulse",
     "feedsPerDay": 1, "night": True, "trainable": False,
     "foods": ("zooPrepared", "zooLive", "blend"),
     "note": "Meaty foods a few times a week; a potent stinger that catches fish, so "
             "give it space from everything else."},
    {"id": "featherduster", "group": "filter",
     "name": "Feather dusters (Sabellastarte, Bispira)", "difficulty": 2,
     "particleUmMin": 2, "particleUmMax": 50, "cadence": "continuous",
     "feedsPerDay": 4, "night": False, "trainable": False,
     "foods": ("phyto", "bacteria"),
     "note": "Sheds the crown when starving and regrows it when fed. Standing phyto "
             "keeps it; a dropped crown is the warning, not the end."},
    {"id": "tubeworm", "group": "filter",
     "name": "Cocos & Christmas tree worms (Protula, Spirobranchus)", "difficulty": 4,
     "particleUmMin": 2, "particleUmMax": 50, "cadence": "continuous",
     "feedsPerDay": 6, "night": False, "trainable": False,
     "foods": ("phyto", "bacteria"),
     "note": "Hard-tube worms live on fine phyto and bacterioplankton, continuously. "
             "The Porites rock a Christmas tree worm rides on has its own needs."},
    {"id": "seaapple", "group": "filter",
     "name": "Sea apple (Pseudocolochirus)", "difficulty": 4,
     "particleUmMin": 2, "particleUmMax": 100, "cadence": "continuous",
     "feedsPerDay": 6, "night": False, "trainable": False,
     "foods": ("phyto", "zooLive", "bacteria"),
     "note": "A phyto and rotifer filter feeder that poisons the tank if it dies — "
             "every day of coverage matters. Keep it off pump intakes."},
    {"id": "basketstar", "group": "filter",
     "name": "Basket star (Astrophyton, Gorgonocephalus)", "difficulty": 4,
     "particleUmMin": 200, "particleUmMax": 1000, "cadence": "pulse",
     "feedsPerDay": 3, "night": True, "trainable": False,
     "foods": ("zooLive", "zooPrepared"),
     "note": "Strictly nocturnal — the arms unfurl after lights-out and net baby "
             "brine and mysis-sized zooplankton. Nothing by day."},
)

_SPECIES_BY_ID = {s["id"]: s for s in SPECIES_LIBRARY}

# What the animal eats, in words (0.7.162) — the report's chips and sentences.
# CATEGORY_LABELS names a product's category on the shelf; these name a mouth.
FOOD_WORDS = {
    "phyto": "live phyto", "zooLive": "live zooplankton",
    "zooPrepared": "prepared zooplankton", "blend": "a coral blend",
    "bacteria": "bacterioplankton",
}

# The foods a keeper actually has to hand, as size references for the mouth
# note (0.7.162). Judged by the matcher's own rule — right food type AND
# overlapping particle window — so "rotifers fit" means a rotifer bottle on
# the shelf WOULD count for this mouth, and a row can never contradict its
# own verdict. The windows are the shelf presets' (PRODUCT_LIBRARY).
MOUTHFUL_REFERENCES: tuple[tuple[str, str, float, float], ...] = (
    ("live phyto", "phyto", 1, 20),
    ("rotifers", "zooLive", 90, 360),
    ("oyster eggs", "zooPrepared", 150, 250),
    ("baby brine", "zooLive", 400, 500),
    ("adult copepods", "zooLive", 500, 1200),
    ("mysis-sized meaty food", "zooPrepared", 1000, 10000),
)


def species_ids() -> tuple[str, ...]:
    return tuple(s["id"] for s in SPECIES_LIBRARY)


def _ranges_overlap(a_min: float, a_max: float, b_min: float, b_max: float) -> bool:
    return max(_f(a_min), _f(b_min)) <= min(_f(a_max) or 1e9, _f(b_max) or 1e9)


def _words(items: list[str]) -> str:
    """'a' / 'a and b' / 'a, b and c'."""
    items = [str(i) for i in items if i]
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " and " + items[-1]


def particle_label(lo: Any, hi: Any) -> str:
    return f"{_f(lo):g}–{_f(hi):g} µm"


def mouth_note(sp: dict[str, Any]) -> dict[str, Any]:
    """The mouth in the keeper's own foods: which reference foods fit this
    species (right type AND size — the matcher's rule), which are too big,
    which too fine. A food of the right size but the wrong type goes
    unsaid: size is not why it fails."""
    fits: list[str] = []
    too_big: list[str] = []
    too_fine: list[str] = []
    lo, hi = _f(sp.get("particleUmMin")), _f(sp.get("particleUmMax"))
    for name, category, ref_lo, ref_hi in MOUTHFUL_REFERENCES:
        if _ranges_overlap(ref_lo, ref_hi, lo, hi):
            if category in (sp.get("foods") or ()):
                fits.append(name)
        elif ref_lo > hi:
            too_big.append(name)
        elif ref_hi < lo:
            too_fine.append(name)
    parts = []
    if fits:
        parts.append(f"{_words(fits)} {'fit' if len(fits) > 1 else 'fits'}")
    if too_big:
        parts.append(f"{_words(too_big)} {'are' if len(too_big) > 1 else 'is'} too big")
    if too_fine:
        parts.append(f"{_words(too_fine)} {'are' if len(too_fine) > 1 else 'is'} too fine")
    note = "; ".join(parts)
    return {"fits": fits, "tooBig": too_big, "tooFine": too_fine,
            "note": (note[0].upper() + note[1:] + ".") if note else ""}


def _rhythm(sp: dict[str, Any]) -> str:
    """How the animal wants feeding, as one clause."""
    n = max(0, int(_f(sp.get("feedsPerDay"))))
    if sp.get("cadence") == "target":
        return "Target-fed by hand, whole items to each polyp — automation assists, never replaces"
    if sp.get("cadence") == "continuous":
        return f"A standing food density — near-continuous, {n} small feeds a day at the least"
    when = "after lights-out" if sp.get("night") else "by day"
    line = f"{n} feed{'' if n == 1 else 's'} a day, {when}"
    return f"{line} — trainable to open by day" if sp.get("trainable") else line


def species_card(sp: dict[str, Any]) -> dict[str, Any]:
    """A library species as the panel describes it (0.7.162): everything the
    library knows plus the foods in words, the particle window as a label,
    the mouth note and the feeding rhythm — composed here, rendered there."""
    foods = list(sp.get("foods") or ())
    return {
        **sp,
        "foods": foods,
        "foodWords": [FOOD_WORDS.get(c, c) for c in foods],
        "particle": particle_label(sp.get("particleUmMin"), sp.get("particleUmMax")),
        "mouth": mouth_note(sp),
        "rhythm": _rhythm(sp),
    }


def compile_feed_plan(selected_ids: list[str], products: dict[str, Any],
                      channels: dict[str, Any],
                      pending: list[dict[str, Any]] | None = None,
                      quiet_product_ids: set[str] | frozenset[str] | None = None,
                      ) -> dict[str, Any]:
    """The species compiler: what the selected livestock needs, whether the
    shelf and pumps cover it, and per-pump schedule suggestions. Advisory
    only — suggestions carry cadence/window shape; the keeper owns ml/day
    (per-colony appetite is not something a library should guess).

    ``pending`` (doc §14): food on the way but not on the shelf yet — a
    hatch mid-incubation, a soak running — as ``{name, category,
    particleUmMin, particleUmMax, note}``. A mouth nothing on the shelf
    feeds, that a pending source WILL feed, is reported under ``soon``
    rather than as a gap: the keeper has already done the right thing.
    A live entry past its fade (``live.expired``) covers nothing.

    ``quiet_product_ids`` (0.7.162): bottles that feed a culture jar or the
    soak, not the tank. The cone's phyto concentrate matches a phyto
    feeder's mouth by type and size, yet none of it reaches the display —
    so it covers nothing and drives no pump, and a species it WOULD have
    fed names it under ``cultureFeeds`` so the report can say so.

    Each ``species`` entry is its ``species_card`` plus the verdict:
    ``status`` (covered / soon / gap / hand), ``fedBy`` (the shelf entries
    that feed it), ``pumps`` (the channels dosing one of them), ``coming``
    (the pending source, for soon), ``needs`` (for a gap), ``cultureFeeds``
    and one ``verdict`` sentence. ``gaps`` and ``soon`` keep their one-line
    forms; ``counts`` tallies the statuses."""
    selected = [_SPECIES_BY_ID[sid] for sid in selected_ids if sid in _SPECIES_BY_ID]
    quiet = {str(pid) for pid in (quiet_product_ids or ()) if pid}
    gaps: list[str] = []
    soon: list[str] = []
    warnings: list[str] = []
    suggestions: list[dict[str, Any]] = []
    product_items = [(pid, p) for pid, p in products.items() if isinstance(p, dict)
                     and pid not in quiet
                     and not (isinstance(p.get("live"), dict) and p["live"].get("expired"))]
    culture_items = [(pid, p) for pid, p in products.items()
                     if isinstance(p, dict) and pid in quiet]
    pending_list = [p for p in (pending or []) if isinstance(p, dict)]

    def _feeds(p: dict[str, Any], sp: dict[str, Any]) -> bool:
        return p.get("category") in sp["foods"] and _ranges_overlap(
            p.get("particleUmMin"), p.get("particleUmMax"),
            sp["particleUmMin"], sp["particleUmMax"])

    entries: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for sp in selected:
        card = species_card(sp)
        # Shelf coverage: any product in the right category AND particle window?
        fed_by = [{"id": pid, "name": str(p.get("name") or pid),
                   "live": isinstance(p.get("live"), dict)}
                  for pid, p in product_items if _feeds(p, sp)]
        spoken_for = [str(p.get("name") or pid) for pid, p in culture_items if _feeds(p, sp)]
        needs = (f"{' or '.join(FOOD_WORDS.get(c, c) for c in sp['foods'])} "
                 f"at {card['particle']}")
        coming: dict[str, Any] | None = None
        if fed_by:
            status = "covered"
        elif sp["cadence"] == "target":
            status = "hand"
        else:
            wanted = " or ".join(sp["foods"])
            source = next((p for p in pending_list if _feeds(p, sp)), None)
            if source is not None:
                note = str(source.get("note") or "").strip()
                coming = {"name": str(source.get("name") or "live food"), "note": note}
                status = "soon"
                soon.append(
                    f"{sp['name']}: nothing on the shelf feeds it yet — "
                    f"{coming['name']} will"
                    f"{f' ({note})' if note else ''}.")
            else:
                status = "gap"
                gaps.append(
                    f"{sp['name']}: nothing on the shelf feeds it "
                    f"(needs {wanted}, {sp['particleUmMin']:g}–{sp['particleUmMax']:g} µm).")
        entry = {**card, "status": status, "fedBy": fed_by, "pumps": [], "coming": coming,
                 "needs": needs, "cultureFeeds": spoken_for, "verdict": ""}
        entries.append(entry)
        by_id[sp["id"]] = entry

    # Per-pump suggestions: a channel whose linked bottle matches a selected
    # species inherits that species' cadence shape.
    for cid, channel in sorted(channels.items()):
        if not isinstance(channel, dict) \
                or channel.get("chemical") not in ("food", "livefood"):
            continue
        pid = str((channel.get("reservoir") or {}).get("productId") or "")
        if pid in quiet:
            continue                        # it doses a culture, not the tank
        product = products.get(pid)
        if not isinstance(product, dict):
            continue
        matches = [sp for sp in selected if _feeds(product, sp)]
        if not matches:
            if selected:
                warnings.append(
                    f"{channel.get('name') or cid}: its bottle "
                    f"({product.get('name')}) feeds none of the selected species — "
                    "check the particle size.")
            continue
        for sp in matches:
            by_id[sp["id"]]["pumps"].append(str(channel.get("name") or cid))
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

    # One sentence per animal, now the pumps are known.
    for entry in entries:
        if entry["status"] == "covered":
            fed = _words([f["name"] for f in entry["fedBy"]])
            pumps = _words(entry["pumps"])
            verdict = f"Fed by {fed}{f', dosed by {pumps}' if pumps else ''}."
        elif entry["status"] == "hand":
            verdict = "Target-fed by hand — the shelf is not asked to cover it."
        elif entry["status"] == "soon":
            note = entry["coming"]["note"]
            verdict = (f"Nothing on the shelf feeds it yet — {entry['coming']['name']} will"
                       f"{f' ({note})' if note else ''}.")
        else:
            verdict = f"Nothing on the shelf feeds it — needs {entry['needs']}."
        if entry["cultureFeeds"]:
            verdict += (f" {_words(entry['cultureFeeds'])} "
                        f"{'is' if len(entry['cultureFeeds']) == 1 else 'are'} "
                        "a culture's feed, so not counted.")
        entry["verdict"] = verdict

    hardest = max((s["difficulty"] for s in selected), default=0)
    if hardest >= 5:
        warnings.append(
            "You've selected expert-tier animals (difficulty 5). Most specimens "
            "starve slowly over 2–6 months even with good automation — source "
            "well, feed relentlessly, and let the camera and logs tell you the truth.")
    return {
        "species": entries,
        "counts": {k: sum(1 for e in entries if e["status"] == k)
                   for k in ("covered", "soon", "gap", "hand")},
        "gaps": gaps,
        "soon": soon,
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
    low = expired = dose_due = live_n = 0
    for pid, product in products.items():
        if not isinstance(product, dict):
            continue
        state = consumable_state(product, now, tank_l, tz)
        states[str(pid)] = state
        if state.get("live"):
            # The hatchery's own entries (doc §14): counted on the shelf, but
            # the hatchery card is the authority on their fade and runway —
            # the attention counts (and the digest's nags) stay the bottles'.
            live_n += 1
            continue
        if state["low"] or state["empty"]:
            low += 1
        if state["expiry"]["status"] == "expired":
            expired += 1
        if state["handDose"]["clock"]["due"]:
            dose_due += 1
    return {"products": states, "lowCount": low, "expiredCount": expired,
            "doseDueCount": dose_due, "count": len(states), "liveCount": live_n}


# ---------------------------------------------------------------------------
# The unified feed timeline (doc §13): every mouthful that goes into the tank
# today — pumped, poured, harvested — on one 24 h strip, planned slots that
# fill in when they happen. Backend-computed so the NPS tab, the Feeding tab
# and the Pulse wall all read one list (the lockstep rule).

TIMELINE_NEXT_MAX = 3
TIMELINE_STATUSES: tuple[str, ...] = (
    "planned", "expected", "due", "late", "missed", "skipped", "blocked", "done", "ghost",
    # A feed-truce band that is holding equipment off right now (doc §13.17).
    "running")

# The feed truce on the strip (doc §13.17): the pauses the truce actually ran
# (its per-profile history), the one running now, and the ones today's
# remaining pump doses will start — thin bands under the water-change row.
TRUCE_PROFILES: tuple[str, ...] = ("uv", "ozone", "skimmer")
TRUCE_PROFILE_LABELS = {"uv": "UV sterilizer", "ozone": "Ozone", "skimmer": "Skimmer"}
TRUCE_PROFILE_SHORT = {"uv": "UV", "ozone": "ozone", "skimmer": "skimmer"}
TRUCE_HISTORY_MAX = 24   # pauses kept per profile — a heavy feeding day, with room


def _minutes_text(minutes: float) -> str:
    """45 -> '45 min', 120 -> '2 h', 90 -> '1 h 30'."""
    m = int(round(_f(minutes)))
    if m >= 60 and m % 60 == 0:
        return f"{m // 60} h"
    if m > 60:
        return f"{m // 60} h {m % 60:02d}"
    return f"{m} min"


def _tl_hm(minute: int) -> str:
    minute = int(minute)
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _span_today(start_iso: Any, end_iso: Any, today, tz: Any) -> list[int] | None:
    """The part of [start, end] that falls on ``today``, as strip minutes —
    a pause that began last night shows from 00:00, one that outlives the
    day runs to 24:00. None when nothing of it is today's."""
    start, end = _parse_iso(start_iso), _parse_iso(end_iso)
    if start is None or end is None or end <= start:
        return None
    try:
        s_local = start.astimezone(tz) if tz is not None else start
        e_local = end.astimezone(tz) if tz is not None else end
    except (TypeError, ValueError):
        return None
    s_day, e_day = s_local.date(), e_local.date()
    if s_day > today or e_day < today:
        return None
    a = 0 if s_day < today else s_local.hour * 60 + s_local.minute
    b = 1440 if e_day > today else e_local.hour * 60 + e_local.minute
    return [a, b] if b > a else None


def _merge_spans(spans: list[list[int]]) -> list[list[int]]:
    """Coalesce overlapping or touching [a, b] spans — eight 90-minute phyto
    doses under a two-hour UV window are one band, not eight."""
    merged: list[list[int]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


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


def _event(**fields: Any) -> dict[str, Any]:
    """One strip event, every field present — extras and slots alike."""
    base = {"id": "", "at": None, "how": "hand", "source": "", "name": "", "productId": "",
            "ml": None, "actualMl": None, "status": "planned", "doneAt": None,
            "note": "", "kind": "dose", "band": None, "unplanned": False, "nextDate": None,
            # The logged row behind a done mark (its ISO stamp) and whether
            # the keeper can take it back from the card (doc §13.16).
            "doneStamp": None, "undoable": False,
            # What the feed truce will do after this pump dose (doc §13.17):
            # "UV 2 h · skimmer 45 min" — empty when nothing is armed.
            "truce": ""}
    base.update(fields)
    return base


def _match_done(planned: list[dict[str, Any]], done: list[dict[str, Any]],
                tolerance_min: float) -> list[dict[str, Any]]:
    """A logged dose that names its slot (``slot`` minute, 0.7.135 — the tap
    on that slot's card) takes that slot, whatever the clock said. Then,
    greedy: each remaining dose takes the nearest unmatched planned slot
    within tolerance (an any-time chip takes anything); the rest are extras.
    Mutates the planned events in place, returns the unplanned extras."""
    extras: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for item in sorted(done, key=lambda d: d["at"]):
        target = None
        if item.get("slot") is not None:
            target = next((ev for ev in planned if ev["at"] == item["slot"]
                           and ev.get("doneAt") is None and ev["status"] not in ("skipped", "ghost")), None)
        if target is None:
            rest.append(item)
            continue
        target["status"] = "done"
        target["doneAt"] = item["at"]
        target["doneStamp"] = item.get("stamp")
        if item.get("ml") is not None:
            target["actualMl"] = item["ml"]
    for item in rest:
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
            extras.append(_event(at=item["at"], ml=item.get("ml"), actualMl=item.get("ml"),
                                 status="done", doneAt=item["at"], doneStamp=item.get("stamp"), unplanned=True))
        else:
            best["status"] = "done"
            best["doneAt"] = item["at"]
            best["doneStamp"] = item.get("stamp")
            if item.get("ml") is not None:
                best["actualMl"] = item["ml"]
    return extras


def _slot_status(at: int | None, now_min: int, *, successor_min: int | None,
                 carried: bool, skipped: bool) -> str:
    """The hand-slot ladder (doc §13.5, Q2 as locked): timed slots are due for
    a short window, then late; a slot goes missed once its successor slot is
    due today (``successor_min``); with no successor today (a days cadence,
    or the day's last slot) it stays late until midnight — the shelf's
    overdue clock takes over next morning. Any-time chips are due all day."""
    if skipped:
        return "skipped"
    if at is None or carried:
        return "due"
    if at > now_min:
        return "planned"
    if now_min - at < HAND_DOSE_DUE_WINDOW_MIN:
        return "due"
    if successor_min is not None and now_min >= successor_min:
        return "missed"
    return "late"


def _timed_plan(events: list[dict[str, Any]], done: list[dict[str, Any]], now_min: int, *,
                carried: bool = False, skipped: bool = False) -> list[dict[str, Any]]:
    """Match the day's logged doses onto the planned slots, then grade what is
    left open. Timed slots take a dose within half the gap to their
    neighbours; any-time chips take anything. Returns the unplanned extras."""
    timed = sorted(e["at"] for e in events if e["at"] is not None)
    gaps = [b - a for a, b in zip(timed, timed[1:])] if len(timed) > 1 else []
    tolerance = min(gaps) / 2 if gaps else HAND_DOSE_ANYTIME_MATCH_MIN
    extras = _match_done(events, done, tolerance)
    first_open = True
    for slot in events:
        if slot["status"] == "done":
            continue
        successor = next((t for t in timed if slot["at"] is not None and t > slot["at"]), None)
        slot["status"] = _slot_status(slot["at"], now_min, successor_min=successor,
                                      carried=carried and first_open, skipped=skipped)
        first_open = False
    return extras


def feed_timeline(now_local: datetime, *, products: dict[str, Any], channels: dict[str, Any],
                  awc: dict[str, Any] | None = None, cultures: dict[str, Any] | None = None,
                  hatchery: dict[str, Any] | None = None,
                  brine_feeds: list[dict[str, Any]] | None = None,
                  lighting: dict[str, Any] | None = None, tank_l: Any = None,
                  fx_channel_id: str = "", fx_enabled: bool = False,
                  culture_bottle_species: Any = None,
                  quiet_product_ids: Any = None,
                  truce: dict[str, Any] | None = None) -> dict[str, Any]:
    """Today's feed strip. ``now_local`` must be tz-aware in the keeper's zone;
    every stamp is bucketed by that local day. Returns the events (sorted,
    any-time chips last), the night window, the next few, the counts and the
    plain-English honesty line."""
    tz = now_local.tzinfo
    today = now_local.date()
    now_min = now_local.hour * 60 + now_local.minute
    events: list[dict[str, Any]] = []
    bottle_species = set(culture_bottle_species or ())
    # Bottles whose logged doses feed something OTHER than the tank (the
    # enrichment soak, a culture jar): their history is not a tank feed, so
    # no extras — a keeper-set tank cadence still lands its planned slots.
    quiet = {str(pid) for pid in (quiet_product_ids or ())}

    ev = _event

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
            if not isinstance(item, dict) or item.get("kind") != "dose" or item.get("undoneAt"):
                continue
            minute, _ = _local_minute(item.get("at"), today, tz)
            if minute is not None:
                done.append({"at": minute, "ml": round(_f(item.get("ml")), 2), "slot": _hhmm_min(item.get("slot")),
                             "stamp": str(item.get("at"))})
        if pid in quiet:
            done = []
        if not cad["unit"]:
            # No cadence: anything logged today still shows — the strip is the day's truth.
            events.extend(ev(id=f"{source}:x{i}", at=d["at"], source=source, name=name, productId=pid,
                             ml=d["ml"], actualMl=d["ml"], status="done", doneAt=d["at"], doneStamp=d.get("stamp"),
                             unplanned=True)
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
                             ml=d["ml"], actualMl=d["ml"], status="done", doneAt=d["at"], doneStamp=d.get("stamp"),
                             unplanned=True)
                          for i, d in enumerate(done))
            continue
        carried = cad["unit"] == "days" and clock_day < today and not skipped_today
        slot_times: list[int | None] = list(cad["slots"]) if cad["slots"] else [None] * cad["perDay"]
        if not cad["slots"]:
            hand_hint = True
        planned = []
        for i, t in enumerate(slot_times):
            planned.append(ev(id=f"{source}:{i}", at=t, source=source, name=name, productId=pid, ml=ml,
                              note=note, status="planned"))
        extras = _timed_plan(planned, done, now_min, carried=carried, skipped=skipped_today)
        if carried:
            first = next((slot for slot in planned if slot["status"] == "due"), None)
            if first is not None:
                first["note"] = (f"overdue since {clock_day.strftime('%a')} · " + note).strip(" ·")
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
        bottled = species in bottle_species
        # A bottle species feeds straight when the jar's default says so
        # (0.7.161); a one-off straight harvest still lands as a done mark.
        straight = not bottled or str(jar.get("harvestTo") or "") == "tank"
        state = jar.get("state") if isinstance(jar.get("state"), dict) else {}
        if not state.get("startedAt"):
            continue
        name = f"{jar.get('name') or jid} harvest"
        source = f"culture:{jid}"
        done = []
        for item in (jar.get("history") if isinstance(jar.get("history"), list) else []):
            if isinstance(item, dict) and item.get("event") == "harvest" and _harvest_went_to_tank(item, bottled):
                minute, _ = _local_minute(item.get("at"), today, tz)
                if minute is not None:
                    done.append({"at": minute, "ml": _harvest_tank_ml(item, bottled)})
        if not straight and not done:
            continue
        # The jar's OWN clock (cultures.culture_state, 0.7.158): the first
        # harvest lands when establishment ends, every later one an interval
        # after the last. A jar still establishing plans nothing here — the
        # Cultures card says "first harvest in ~27 d", so must the strip — and
        # a crashed jar has no clock at all. A harvest is a day-granular
        # chore: due on its day, any time, like a days-cadence bottle.
        clock = culture_state(jar, now_local).get("harvest") or {}
        clock_at = _parse_iso(clock.get("at")) if clock.get("available") else None
        planned = []
        if straight and clock_at is not None:
            due_day = clock_at.astimezone(tz).date() if tz is not None else clock_at.date()
            if due_day <= today:
                planned.append(ev(id=f"{source}:0", source=source, name=name, ml=None, status="due",
                                  note=("through the net straight into the tank — the cone's own clock" if bottled
                                        else "pods straight into the display — the jar's own clock")))
        extras = _timed_plan(planned, done, now_min)
        for i, extra in enumerate(extras):
            extra.update({"id": f"{source}:x{i}", "source": source, "name": name,
                          "actualMl": extra.get("ml"), "note": "harvested into the display"})
        for e in planned + extras:
            e["jarId"] = jid
            e["hasBottle"] = bottled
        events.extend(planned)
        events.extend(extras)
    bottle = cultures.get("bottle") if isinstance(cultures.get("bottle"), dict) else {}
    if bottle:
        bottle_done = []
        for item in (bottle.get("history") if isinstance(bottle.get("history"), list) else []):
            if isinstance(item, dict) and item.get("event") == "fed_tank" and not item.get("undoneAt"):
                minute, _ = _local_minute(item.get("at"), today, tz)
                if minute is not None:
                    bottle_done.append({"at": minute, "ml": round(_f(item.get("ml")), 1) or None,
                                        "slot": _hhmm_min(item.get("slot")), "stamp": str(item.get("at"))})
        # The bottle's own plan (0.7.134): N feeds a day inside its window
        # while it holds rotifers; empty = nothing planned, done marks only.
        per_day = max(0, int(_f(bottle.get("feedsPerDay"))))
        slots = spread_slots(per_day, bottle.get("windowStart"), bottle.get("windowEnd"))
        dose = round(_f(bottle.get("doseMl")), 1) or None
        planned = []
        if per_day > 0 and _f(bottle.get("remainingMl")) > 0:
            times: list[int | None] = list(slots) if slots else [None] * per_day
            planned = [ev(id=f"cultures-bottle:{i}", at=t, source="cultures-bottle", name="Rotifers from the bottle",
                          ml=dose, status="planned", note="from the rotifer bottle — the Cultures tab's Fed button logs it")
                       for i, t in enumerate(times)]
        extras = _timed_plan(planned, bottle_done, now_min)
        for i, extra in enumerate(extras):
            extra.update({"id": f"cultures-bottle:x{i}", "source": "cultures-bottle", "name": "Rotifers from the bottle",
                          "actualMl": extra.get("ml"), "note": "fed from the rotifer bottle"})
        events.extend(planned)
        events.extend(extras)

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
        # The feeding window (0.7.134): 3 feeds 11:00–21:00 = 11:00, 16:00,
        # 21:00; no window = any-time chips, as before.
        slots = spread_slots(per_day, hand.get("windowStart"), hand.get("windowEnd"))
        times: list[int | None] = list(slots) if slots else [None] * per_day
        planned = [ev(id=f"brine:{i}", at=t, how="hand", source="brine", name="Live brine", ml=dose, status="planned",
                      note="from the brine container — Fed here or on the hatchery card logs it")
                   for i, t in enumerate(times if on_hand else [])]
        done = []
        for item in (brine_feeds or []):
            if isinstance(item, dict) and not item.get("undoneAt"):
                minute, _ = _local_minute(item.get("at"), today, tz)
                if minute is not None:
                    done.append({"at": minute, "ml": round(_f(item.get("ml")), 1) or None,
                                 "slot": _hhmm_min(item.get("slot")), "stamp": str(item.get("at"))})
        extras = _timed_plan(planned, done, now_min)
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

    # --- The feed truce (doc §13.17): what it did today, what it is doing
    # now, what today's remaining pump doses will make it do — one thin band
    # per armed profile under the water-change row. Only pump doses engage
    # it (the dosing tick's hook), so only pump ticks project a pause.
    truce = truce if isinstance(truce, dict) else {}
    profiles = truce.get("profiles") if isinstance(truce.get("profiles"), dict) else {}
    if truce.get("enabled") and profiles:
        armed = [(profile, profiles[profile]) for profile in TRUCE_PROFILES
                 if isinstance(profiles.get(profile), dict) and profiles[profile].get("armed")
                 and _f(profiles[profile].get("minutes")) > 0]
        if armed:
            consequence = " · ".join(
                f"{TRUCE_PROFILE_SHORT[profile]} {_minutes_text(prof['minutes'])}" for profile, prof in armed)
            for e in events:
                if e["how"] == "pump" and e["kind"] == "dose":
                    e["truce"] = consequence
        planned_ticks = sorted(e["at"] for e in events
                               if e["how"] == "pump" and e["kind"] == "dose"
                               and e["status"] == "planned" and e["at"] is not None)
        for profile, prof in armed:
            minutes = _f(prof.get("minutes"))
            names = [str(n) for n in (prof.get("names") if isinstance(prof.get("names"), list) else []) if str(n)]
            name = "Feed truce — " + (", ".join(names[:3]) if names else TRUCE_PROFILE_LABELS[profile])
            source = f"truce:{profile}"
            history = prof.get("history") if isinstance(prof.get("history"), list) else []
            for i, item in enumerate(history):
                if not isinstance(item, dict):
                    continue
                span = _span_today(item.get("at"), item.get("until"), today, tz)
                if span:
                    events.append(ev(id=f"{source}:h{i}", how="system", source=source, name=name, kind="band",
                                     band=span, status="done",
                                     note="paused after a food dose, then switched back on"))
            running_end = None
            if prof.get("active"):
                restore = _parse_iso(prof.get("restoreAt"))
                started = prof.get("pausedAt") or (
                    (restore - timedelta(minutes=minutes)).isoformat() if restore is not None else None)
                until = restore.isoformat() if restore is not None else now_local.isoformat()
                span = _span_today(started, until, today, tz)
                if span:
                    running_end = span[1]
                    if span[1] >= 1440:
                        back = "back on after midnight"
                    elif span[1] <= now_min:
                        back = f"back on at {_tl_hm(span[1])} — any minute now"
                    else:
                        back = f"back on at {_tl_hm(span[1])}, {_minutes_text(span[1] - now_min)} to go"
                    events.append(ev(id=f"{source}:run", how="system", source=source, name=name, kind="band",
                                     band=span, status="running",
                                     note=f"off since {_tl_hm(span[0])} — {back}"))
            spans = []
            for t in planned_ticks:
                a = t if running_end is None else max(t, running_end)
                b = min(1440, t + int(round(minutes)))
                if b > a:
                    spans.append([a, b])
            for i, span in enumerate(_merge_spans(spans)):
                after = [t for t in planned_ticks if t < span[1] and t + minutes > span[0]]
                times = ", ".join(_tl_hm(t) for t in after[:3]) + (f" +{len(after) - 3}" if len(after) > 3 else "")
                events.append(ev(id=f"{source}:p{i}", how="system", source=source, name=name, kind="band",
                                 band=span, status="planned",
                                 note=f"after the {times} dose{'s' if len(after) != 1 else ''} — {_minutes_text(minutes)} each"))

    # --- Night, next, counts, the honesty line.
    night = None
    if isinstance(lighting, dict) and lighting.get("configured"):
        on_min, off_min = _hhmm_min(lighting.get("onTime")), _hhmm_min(lighting.get("offTime"))
        if on_min is not None and off_min is not None and off_min > on_min:
            night = {"onMin": on_min, "offMin": off_min}

    # What the keeper can take back from a mark's card (doc §13.16): a logged
    # row from the shelf, the brine log or the rotifer bottle. Pump run stamps
    # and jar harvests are not undoable from here.
    for e in events:
        e["undoable"] = bool(e["status"] == "done" and e.get("doneStamp")
                             and (str(e["source"]).startswith("shelf:") or e["source"] in ("brine", "cultures-bottle")))
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


# --------------------------------------------------------------------------- #
# The feeding log (doc §13.19): every mouthful that went into the tank, as a
# list. The strip shows one day as marks; this sweeps the same ledgers across
# days and hands them over newest first — the shelf's dose/pump rows, the
# hatchery's stamped hand feeds, the rotifer bottle, the pods harvested
# straight into the display, and the doses OpenReef itself ran on a pump.
# Read-only: nothing is written, so there is nothing new to guard on save.
# --------------------------------------------------------------------------- #
FEED_LOG_DAYS_DEFAULT = 7
FEED_LOG_DAYS_MAX = 90
FEED_LOG_MAX = 300           # rows a summary carries — the ledgers keep fewer anyway
FEED_LOG_HOW: tuple[str, ...] = ("hand", "pump")


def _log_row(**fields: Any) -> dict[str, Any]:
    """One log row, every field present. ``at`` is the ledger's own stamp,
    verbatim, so an undo can name the row exactly as the strip does."""
    base = {"id": "", "at": "", "date": "", "time": "", "how": "hand", "source": "", "name": "",
            "productId": "", "ml": None, "from": "", "via": "", "slot": "", "note": "",
            "undone": False, "undoneAt": None, "undoable": False}
    base.update(fields)
    return base


def feed_log(now_local: datetime, *, products: dict[str, Any], channels: dict[str, Any],
             cultures: dict[str, Any] | None = None, hatchery: dict[str, Any] | None = None,
             brine_feeds: list[dict[str, Any]] | None = None,
             days: Any = FEED_LOG_DAYS_DEFAULT,
             quiet_product_ids: Any = None, culture_bottle_species: Any = None,
             limit: int = FEED_LOG_MAX) -> dict[str, Any]:
    """The feeds of the last ``days`` local days (today counts as one), newest
    first, with per-day counts and the plain-English line. ``now_local`` must
    be tz-aware in the keeper's zone — every stamp is bucketed by that day.

    Taken-back feeds stay in the list flagged ``undone`` (a log that hides its
    reversals is not a log) but never count. Bottles that feed the enrichment
    soak or a culture jar (``quiet_product_ids``) never appear — their doses
    are not tank feeds (0.7.133)."""
    tz = now_local.tzinfo
    try:
        days = int(_f(days)) or FEED_LOG_DAYS_DEFAULT
    except (TypeError, ValueError):
        days = FEED_LOG_DAYS_DEFAULT
    days = max(1, min(FEED_LOG_DAYS_MAX, days))
    today = now_local.date()
    since = today - timedelta(days=days - 1)
    quiet = {str(pid) for pid in (quiet_product_ids or ())}
    bottle_species = set(culture_bottle_species or ())
    undo_window = timedelta(minutes=HAND_DOSE_UNDO_MIN)
    rows: list[tuple[datetime, dict[str, Any]]] = []

    def add(iso: Any, **fields: Any) -> None:
        parsed = _parse_iso(iso)
        if parsed is None:
            return
        try:
            local = parsed.astimezone(tz) if tz is not None else parsed
        except (TypeError, ValueError):
            return
        day = local.date()
        if day < since or day > today:
            return
        row = _log_row(at=str(iso), date=day.isoformat(), time=f"{local.hour:02d}:{local.minute:02d}", **fields)
        row["id"] = f"{row['source']}@{row['at']}"
        # What the keeper can still take back (doc §13.16): a logged row from
        # the shelf, the brine log or the rotifer bottle, inside the window.
        row["undoable"] = bool(fields.get("undoable") and not row["undone"]
                               and timedelta(0) <= now_local - parsed <= undo_window)
        rows.append((parsed, row))

    # --- Pumps: which shelf bottle each food channel draws from (its pump
    # rows are the record), and the doses OpenReef timed itself otherwise.
    bottle_channel: dict[str, str] = {}
    unrecorded: list[str] = []
    for cid in sorted(channels):
        ch = channels[cid]
        if not isinstance(ch, dict) or ch.get("chemical") not in ("food", "livefood"):
            continue
        name = str(ch.get("name") or cid)
        reservoir = ch.get("reservoir") if isinstance(ch.get("reservoir"), dict) else {}
        pid = str(reservoir.get("productId") or "")
        bound = bool(pid and reservoir.get("productIsBottle") and isinstance(products.get(pid), dict) and pid not in quiet)
        if bound:
            bottle_channel.setdefault(pid, name)
            continue
        source = f"channel:{cid}"
        driver = ch.get("driver") if isinstance(ch.get("driver"), dict) else {}
        ha_timed = str(driver.get("type") or "") == "ha_switch_timed"
        for item in (ch.get("events") if isinstance(ch.get("events"), list) else []):
            # Only a run OpenReef started with a known volume is a feed here;
            # a firmware "requested" manual dose may still be refused.
            if not isinstance(item, dict) or item.get("kind") not in ("dose", "manual_dose") or item.get("ml") is None:
                continue
            add(item.get("at"), how="pump", source=source, name=name, ml=round(_f(item.get("ml")), 2),
                note="manual dose" if item.get("kind") == "manual_dose" else "")
        sched = ch.get("schedule") if isinstance(ch.get("schedule"), dict) else {}
        if ch.get("enabled") is not False and sched.get("enabled") and _f(sched.get("mlPerDay")) > 0 and not ha_timed:
            unrecorded.append(name)

    # --- The shelf: hand-logged doses and pump debits, per bottle.
    for pid in sorted(products):
        product = products[pid]
        if not isinstance(product, dict) or pid in quiet:
            continue
        name = str(product.get("name") or pid)
        source = f"shelf:{pid}"
        for item in (product.get("history") if isinstance(product.get("history"), list) else []):
            if not isinstance(item, dict) or item.get("kind") not in ("dose", "pump"):
                continue
            pumped = item.get("kind") == "pump"
            add(item.get("at"), how="pump" if pumped else "hand", source=source, name=name, productId=pid,
                ml=round(_f(item.get("ml")), 2), via=bottle_channel.get(pid, "") if pumped else "",
                slot=str(item.get("slot") or ""), undone=bool(item.get("undoneAt")),
                undoneAt=item.get("undoneAt") or None, undoable=not pumped)

    # --- Hand-fed brine: the hatchery's own stamped feeds (0.7.131), from the
    # container or the fridge bottle — whether or not an exchange pump exists.
    for item in (brine_feeds or []):
        if not isinstance(item, dict):
            continue
        add(item.get("at"), how="hand", source="brine", name="Live brine", ml=round(_f(item.get("ml")), 1) or None,
            **{"from": "bottle" if item.get("from") == "bottle" else "container"},
            slot=str(item.get("slot") or ""), undone=bool(item.get("undoneAt")),
            undoneAt=item.get("undoneAt") or None, undoable=True)

    # --- Cultures: pods harvested straight into the display (Q6), and the
    # rotifer bottle's feeds. A rotifer harvest fills the bottle, not the tank.
    cultures = cultures if isinstance(cultures, dict) else {}
    jars = cultures.get("jars") if isinstance(cultures.get("jars"), dict) else {}
    for jid in sorted(jars):
        jar = jars[jid]
        if not isinstance(jar, dict):
            continue
        bottled = str(jar.get("species") or "") in bottle_species
        name = (f"Rotifers from the cone ({jar.get('name') or jid})" if bottled
                else f"{jar.get('name') or jid} harvest")
        for item in (jar.get("history") if isinstance(jar.get("history"), list) else []):
            if isinstance(item, dict) and item.get("event") == "harvest" and _harvest_went_to_tank(item, bottled):
                add(item.get("at"), how="hand", source=f"culture:{jid}", name=name,
                    ml=_harvest_tank_ml(item, bottled),
                    note=("sieved harvest straight into the tank; culture water discarded" if bottled
                          else "harvested into the display"))
    bottle = cultures.get("bottle") if isinstance(cultures.get("bottle"), dict) else {}
    for item in (bottle.get("history") if isinstance(bottle.get("history"), list) else []):
        if isinstance(item, dict) and item.get("event") == "fed_tank":
            add(item.get("at"), how="hand", source="cultures-bottle", name="Rotifers from the bottle",
                ml=round(_f(item.get("ml")), 1) or None, slot=str(item.get("slot") or ""),
                undone=bool(item.get("undoneAt")), undoneAt=item.get("undoneAt") or None, undoable=True)

    # --- Newest first, the cap, the days, the counts, the line.
    rows.sort(key=lambda pair: (pair[0], pair[1]["source"]), reverse=True)
    truncated = len(rows) > max(1, int(limit))
    kept = [row for _, row in rows[:max(1, int(limit))]]
    per_day: list[dict[str, Any]] = []
    by_day: dict[str, dict[str, Any]] = {}
    for row in kept:
        bucket = by_day.get(row["date"])
        if bucket is None:
            bucket = by_day[row["date"]] = {"date": row["date"], "feeds": 0, "hand": 0, "pump": 0, "undone": 0}
            per_day.append(bucket)
        if row["undone"]:
            bucket["undone"] += 1
            continue
        bucket["feeds"] += 1
        bucket[row["how"]] += 1
    counts = {
        "feeds": sum(d["feeds"] for d in per_day),
        "hand": sum(d["hand"] for d in per_day),
        "pump": sum(d["pump"] for d in per_day),
        "undone": sum(d["undone"] for d in per_day),
    }
    span = "today" if days == 1 else f"in the last {days} days"
    if not counts["feeds"] and not counts["undone"]:
        text = (f"No feeds logged {span} — every Fed tap, logged dose and pump run lands here."
                if days == 1 else f"No feeds logged {span}.")
    else:
        bits = []
        if counts["hand"]:
            bits.append(f"{counts['hand']} by hand")
        if counts["pump"]:
            bits.append(f"{counts['pump']} pumped")
        text = f"{counts['feeds']} feed{'s' if counts['feeds'] != 1 else ''} {span}"
        if bits:
            text += " — " + ", ".join(bits)
        if counts["undone"]:
            text += f" · {counts['undone']} taken back"
        text += "."
    if unrecorded:
        names = ", ".join(unrecorded[:3]) + (f" +{len(unrecorded) - 3}" if len(unrecorded) > 3 else "")
        text += (f" {names}: the firmware runs its own clock, so each dose is logged only when the pump"
                 f" draws from a bottle on the shelf.")
    return {
        "date": today.isoformat(),
        "since": since.isoformat(),
        "days": days,
        "rows": kept,
        "perDay": per_day,
        "counts": counts,
        "truncated": truncated,
        "unrecorded": unrecorded,
        "text": text,
    }
