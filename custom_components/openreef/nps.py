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
# 48 h refrigerated (sources span 24 h conservative to 2–3 days survival; we
# take the nutritional middle).
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

# Named vessel presets for the volume picker (product → working water volume).
# Research note: the Ziss line is ZH-700 / ZH-2000 — there is no ZH-1000.
HATCH_VESSEL_PRESETS: tuple[dict[str, Any], ...] = (
    {"id": "ziss_zh700", "name": "Ziss ZH-700", "volumeL": 0.7},
    {"id": "ziss_zh2000", "name": "Ziss ZH-2000", "volumeL": 2.0},
    {"id": "hobby_breeder", "name": "Hobby Artemia Breeder", "volumeL": 0.47},
    {"id": "jbl_artemio", "name": "JBL ArtemioSet", "volumeL": 0.5},
    {"id": "soda_bottle", "name": "2 L bottle rig", "volumeL": 1.6},
)


def expected_hatch_hours(base_hours: Any, temp_c: Any) -> dict[str, Any]:
    """Advisory only — never moves the real clock. At 28 °C the configured
    hours stand; each degree cooler stretches them ~8% (research: 24 h at 28 °C
    becomes ~36 h at 21 °C, 36–48 h at 20 °C), clamped at 2.2×. Warmer than
    optimum is not rewarded — above ~30 °C hatch quality drops, so we flag it
    instead of promising speed."""
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
    ``{"startedAt", "hatchHours"}`` dicts (hatchery v2: several vessels, each
    batch on its OWN stamped clock — a 36 h batch mid-run stays a 36 h batch
    even after the default drops to 24). The chain anchors on the batch that
    LOADS last — every load resets the container's clock, so the last batch to
    land is the one whose fade the next start must beat. ``busyCount`` reports
    how many batches are on the go.
    """
    hours = _f(hatch_hours)
    if hours <= 0:
        hours = 24.0
    shelf_h = _f(shelf_life_hours)
    if shelf_h <= 0:
        shelf_h = 24.0
    lead_h = hours + HATCH_HARVEST_BUFFER_H
    raw_starts = started_iso if isinstance(started_iso, (list, tuple)) else [started_iso]
    running: list[tuple[datetime, float]] = []
    for item in raw_starts:
        if isinstance(item, dict):
            stamp, batch_h = _parse_iso(item.get("startedAt")), _f(item.get("hatchHours"))
        else:
            stamp, batch_h = _parse_iso(item), 0.0
        if stamp is not None:
            running.append((stamp, batch_h if batch_h > 0 else hours))
    base: dict[str, Any] = {
        "status": "no_brine", "startAt": None, "hoursUntil": None,
        "readyBy": None, "driver": None,
        "hatchHours": round(hours, 1), "shelfHours": round(shelf_h, 1),
        "overlap": shelf_h < lead_h,
        "busyCount": len(running),
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

    if running:
        # Batches are on the go: the next start keeps the chain unbroken. The
        # anchor is when the LAST batch loads (its own stamped clock, floored
        # at now — a ripe batch loads about now); its brine fades shelf_h
        # later, and the following batch needs lead_h of runway.
        anchor = max(
            max(stamp + timedelta(hours=batch_h), now)
            for stamp, batch_h in running
        )
        ready_by = anchor + timedelta(hours=HATCH_HARVEST_BUFFER_H + shelf_h)
        start_at = ready_by - timedelta(hours=lead_h)
        if start_at <= now:
            return _finish("start_now", now, ready_by, "freshness")
        return _finish("chained", start_at, ready_by, "freshness")

    loaded = _parse_iso(loaded_iso)
    if loaded is None:
        return _finish("no_brine", None, None, None)
    fresh_by = loaded + timedelta(hours=shelf_h)
    ready_by, driver = fresh_by, "freshness"
    remaining = _f(remaining_ml, -1.0)
    rate = _f(ml_per_day)
    if remaining >= 0 and rate > 0:
        deplete_by = now + timedelta(hours=remaining / rate * 24.0)
        if deplete_by < ready_by:
            ready_by, driver = deplete_by, "depletion"
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
