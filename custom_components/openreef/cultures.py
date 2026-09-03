"""Live cultures engine — pure maths for the rotifer / copepod jars.

Design stance (mirrors nps.py / awc.py): every function here is a pure
function of its inputs — no Home Assistant imports, no I/O, no wall clock.
Orchestration (WS handlers, ledgers, reminders) lives in __init__.py.

The brine hatchery is a batch measured in hours. A culture is a standing
population measured in days: a rotifer jar is a chemostat (daily harvest ==
water change == ammonia control, sieve-and-restart every fortnight so the
week-4 ciliate crash never arrives), a copepod jar is a slow, forgiving
population (feed every few days, harvest weekly, water change monthly).
Species presets carry the numbers from the 2026-09 research sweep
(docs/live-cultures-brainstorm.md §1–§2); the keeper can override any
cadence per jar and the engine reads the merged view.

Honesty rules (the AWC tradition): a clock with no stamp is "unknown", never
a guess; a chore is due when its interval has elapsed since it was last
DONE (or since the jar was seeded, for a jar that has never had it done);
temperature advice never moves a clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .awc import _f, _parse_iso

CULTURE_JARS_MAX = 4
TINTS: tuple[str, ...] = ("green", "clearing", "clear")

# Species presets. tempMin/MaxC = the productive band; tempHardMaxC = the
# line above which the copy stops advising and starts warning (Reece's
# Tigriopus culture died in a UK heatwave — the flat ran hot for days).
# feedIntervalH: how often the jar wants looking at / feeding by tint.
# harvestIntervalDays + harvestPct: the standing harvest, which for rotifers
# IS the water change (waterChangeIntervalDays 0 = no separate chore).
# restartIntervalDays: the sieve-and-restart into a clean jar (0 = never).
# firstHarvestDays: let a freshly seeded jar establish before the first draw.
# splitMinAgeDays: when "Split into B" becomes sensible.
# bottleShelfDays: how long a harvest keeps in the fridge bottle (0 = the
# harvest goes straight into the tank — no bottle for this species).
SPECIES: tuple[dict[str, Any], ...] = (
    {"id": "rotifer_L", "name": "Rotifers (L-type)", "kind": "rotifer",
     "latin": "Brachionus plicatilis",
     "tempMinC": 18.0, "tempMaxC": 26.0, "tempHardMaxC": 30.0,
     "salinityPpt": 35.0,
     "feedIntervalH": 12.0,
     "harvestIntervalDays": 1.0, "harvestPct": 25.0,
     "restartIntervalDays": 14.0,
     "waterChangeIntervalDays": 0.0, "waterChangePct": 0.0,
     "firstHarvestDays": 3.0, "splitMinAgeDays": 10.0,
     "sieveUm": 53, "bottleShelfDays": 3.0,
     "note": "Room temperature, no light, an open airline at ~1 bubble/s (no airstone — "
             "fine foam strips rotifers). Keep the water lightly green: clear means feed. "
             "Harvest 25% a day through 53 µm — the water you take out IS the water change. "
             "Sieve the whole jar into a clean one every fortnight; that is what stops the "
             "week-4 crash."},
    {"id": "tigriopus", "name": "Tigriopus copepods", "kind": "copepod",
     "latin": "Tigriopus californicus",
     "tempMinC": 20.0, "tempMaxC": 25.0, "tempHardMaxC": 28.0,
     "salinityPpt": 35.0,
     "feedIntervalH": 60.0,
     "harvestIntervalDays": 7.0, "harvestPct": 20.0,
     "restartIntervalDays": 0.0,
     "waterChangeIntervalDays": 21.0, "waterChangePct": 35.0,
     "firstHarvestDays": 7.0, "splitMinAgeDays": 21.0,
     "sieveUm": 53, "bottleShelfDays": 0.0,
     "note": "Reef salinity, steady room temperature, gentle air. Phyto every 2–3 days — "
             "just enough to tint the water. Wait a week before the first harvest, then "
             "~20% a week (53 µm keeps the nauplii, 150 µm the adults). A generation is "
             "about a month, so patience beats fiddling. Hard warning above 28 °C: a hot "
             "spell is what kills this culture."},
)
_SPECIES_BY_ID = {s["id"]: s for s in SPECIES}
CADENCE_FIELDS: tuple[str, ...] = (
    "feedIntervalH", "harvestIntervalDays", "harvestPct", "restartIntervalDays",
    "waterChangeIntervalDays", "waterChangePct",
)


def species_ids() -> tuple[str, ...]:
    return tuple(s["id"] for s in SPECIES)


def species_preset(species_id: Any) -> dict[str, Any]:
    return dict(_SPECIES_BY_ID.get(str(species_id or ""), _SPECIES_BY_ID["rotifer_L"]))


def cadence_for(species_id: Any, overrides: Any) -> dict[str, float]:
    """The preset cadence with the keeper's per-jar overrides applied. An
    override <= 0 on an interval means "never" only where the preset also
    allows it (restart / water change); feed and harvest always run."""
    preset = species_preset(species_id)
    over = overrides if isinstance(overrides, dict) else {}
    merged: dict[str, float] = {}
    for key in CADENCE_FIELDS:
        base = _f(preset.get(key))
        val = over.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            merged[key] = float(val)
        else:
            merged[key] = base
    if merged["feedIntervalH"] <= 0:
        merged["feedIntervalH"] = _f(preset["feedIntervalH"])
    if merged["harvestIntervalDays"] <= 0:
        merged["harvestIntervalDays"] = _f(preset["harvestIntervalDays"])
    merged["harvestPct"] = min(60.0, max(5.0, merged["harvestPct"] or _f(preset["harvestPct"])))
    return merged


def _due(last_iso: Any, anchor_iso: Any, interval: timedelta, now: datetime) -> dict[str, Any]:
    """Chore clock: due when ``interval`` has passed since the chore was last
    done, or since the anchor (seeded / restarted) if it never was."""
    last = _parse_iso(last_iso) or _parse_iso(anchor_iso)
    if last is None:
        return {"available": False, "due": False, "at": None, "hoursUntil": None,
                "hoursOverdue": None}
    at = last + interval
    delta_h = (at - now).total_seconds() / 3600.0
    return {
        "available": True,
        "due": delta_h <= 0,
        "at": at.isoformat(),
        "hoursUntil": round(max(0.0, delta_h), 1),
        "hoursOverdue": round(max(0.0, -delta_h), 1),
    }


def culture_state(jar: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Where a jar sits: ``none`` (not seeded), ``crashed``, ``establishing``
    (seeded, first harvest not yet sensible), ``producing`` — plus every chore
    clock, the split eligibility and the restart-cycle percent."""
    state = jar.get("state") if isinstance(jar.get("state"), dict) else {}
    species = species_preset(jar.get("species"))
    cad = cadence_for(jar.get("species"), jar.get("cadence"))
    started = _parse_iso(state.get("startedAt"))
    crashed = _parse_iso(state.get("crashedAt"))
    out: dict[str, Any] = {
        "status": "none", "ageDays": None, "daysSinceRestart": None,
        "percent": None, "splitEligible": False, "cadence": cad,
        "feed": _due(None, None, timedelta(hours=1), now),
        "harvest": _due(None, None, timedelta(hours=1), now),
        "restart": _due(None, None, timedelta(hours=1), now),
        "waterChange": _due(None, None, timedelta(hours=1), now),
        "nextChore": None,
    }
    if started is None:
        return out
    if crashed is not None and crashed >= started:
        out["status"] = "crashed"
        out["ageDays"] = round(max(0.0, (crashed - started).total_seconds() / 86400.0), 1)
        return out
    age_days = max(0.0, (now - started).total_seconds() / 86400.0)
    restart_anchor = _parse_iso(state.get("lastRestartAt")) or started
    since_restart = max(0.0, (now - restart_anchor).total_seconds() / 86400.0)
    out["ageDays"] = round(age_days, 1)
    out["daysSinceRestart"] = round(since_restart, 1)
    establishing = age_days < _f(species["firstHarvestDays"])
    out["status"] = "establishing" if establishing else "producing"

    out["feed"] = _due(state.get("lastFedAt"), state.get("startedAt"),
                       timedelta(hours=cad["feedIntervalH"]), now)
    # The first harvest lands when establishment ends (firstHarvestDays after
    # the seed), every later one an interval after the last — a jar still
    # establishing reports the wait honestly, never "due".
    first_harvest = started + timedelta(days=_f(species["firstHarvestDays"]))
    last_harvest = _parse_iso(state.get("lastHarvestAt")) if not establishing else None
    if last_harvest is not None and last_harvest >= first_harvest:
        out["harvest"] = _due(last_harvest.isoformat(), None,
                              timedelta(days=cad["harvestIntervalDays"]), now)
    else:
        out["harvest"] = _due(first_harvest.isoformat(), None, timedelta(0), now)
    if cad["restartIntervalDays"] > 0:
        out["restart"] = _due(restart_anchor.isoformat(), None,
                              timedelta(days=cad["restartIntervalDays"]), now)
        out["percent"] = round(min(100.0, 100.0 * since_restart / cad["restartIntervalDays"]))
    if cad["waterChangeIntervalDays"] > 0:
        out["waterChange"] = _due(state.get("lastWaterChangeAt"), state.get("startedAt"),
                                  timedelta(days=cad["waterChangeIntervalDays"]), now)
    out["splitEligible"] = (age_days >= _f(species["splitMinAgeDays"])
                            and str(state.get("lastTint") or "") != "clear")
    # The next chore the keeper should expect (soonest "at"), due ones first.
    chores = []
    for key in ("feed", "harvest", "restart", "waterChange"):
        clock = out[key]
        if clock.get("available") and clock.get("at"):
            chores.append((0 if clock["due"] else 1, clock["at"], key))
    if chores:
        chores.sort()
        _rank, at, key = chores[0]
        out["nextChore"] = {"key": key, "at": at, "due": out[key]["due"],
                            "hoursUntil": out[key]["hoursUntil"]}
    return out


def feed_advice(tint: Any, feed_clock: dict[str, Any]) -> dict[str, Any]:
    """What the tint says, married to the feed clock. Clear water = the jar
    ate everything = feed now, whatever the clock. Green at feed time = it is
    still full of food = skip this one (overfeeding drives ammonia). Clearing
    = feed on schedule."""
    tint = str(tint or "")
    due = bool(feed_clock.get("due"))
    if tint == "clear":
        return {"action": "feed_now", "reason": "clear water — the jar is hungry"}
    if tint == "green":
        return {"action": "skip" if due else "wait",
                "reason": "still green — plenty of food in the water; feeding now just makes ammonia"}
    if tint == "clearing":
        return {"action": "feed_now" if due else "wait",
                "reason": "clearing — feed on schedule"}
    return {"action": "feed_now" if due else "wait", "reason": "no tint logged yet"}


def temperature_advice(temp_c: Any, species_id: Any) -> dict[str, Any]:
    """Advisory only: where the room sits against the species band. ``hot`` is
    the hard line — the heatwave that killed the last Tigriopus culture."""
    species = species_preset(species_id)
    try:
        t = float(temp_c)
    except (TypeError, ValueError):
        return {"available": False, "status": "unknown", "tempC": None,
                "minC": species["tempMinC"], "maxC": species["tempMaxC"],
                "hardMaxC": species["tempHardMaxC"]}
    if t >= _f(species["tempHardMaxC"]):
        status = "hot"
    elif t > _f(species["tempMaxC"]):
        status = "warm"
    elif t < _f(species["tempMinC"]):
        status = "cool"
    else:
        status = "ok"
    return {"available": True, "status": status, "tempC": round(t, 1),
            "minC": species["tempMinC"], "maxC": species["tempMaxC"],
            "hardMaxC": species["tempHardMaxC"]}


def refill_guide(volume_l: Any, pct: Any, target_ppt: Any, mix_ppt: float = 35.0) -> dict[str, Any]:
    """The measured jug: how much water a harvest / water change moves, and —
    for a brackish jar — how to cut the mixing station's 35 ppt to hit it."""
    vol = max(0.0, _f(volume_l))
    frac = min(1.0, max(0.0, _f(pct) / 100.0))
    total_ml = round(vol * frac * 1000.0)
    target = _f(target_ppt)
    if target <= 0 or target >= mix_ppt:
        return {"totalMl": total_ml, "mixMl": total_ml, "rodiMl": 0, "targetPpt": mix_ppt}
    mix_ml = round(total_ml * target / mix_ppt)
    return {"totalMl": total_ml, "mixMl": mix_ml, "rodiMl": total_ml - mix_ml,
            "targetPpt": round(target, 1)}


def bottle_state(bottle: dict[str, Any], shelf_days: Any, now: datetime) -> dict[str, Any]:
    """The rotifer fridge bottle's own clock — fail-closed like every other
    freshness clock: a filled bottle with no stamp is stale."""
    remaining = max(0.0, _f(bottle.get("remainingMl")))
    if remaining <= 0:
        return {"status": "empty", "remainingMl": 0.0, "hoursLeft": None, "filledAt": ""}
    filled = _parse_iso(bottle.get("filledAt"))
    shelf_h = max(1.0, _f(shelf_days)) * 24.0
    if filled is None:
        return {"status": "stale", "remainingMl": remaining, "hoursLeft": 0.0, "filledAt": ""}
    left_h = shelf_h - (now - filled).total_seconds() / 3600.0
    if left_h <= 0:
        status = "stale"
    elif left_h <= shelf_h * 0.25:
        status = "aging"
    else:
        status = "fresh"
    return {"status": status, "remainingMl": remaining,
            "hoursLeft": round(max(0.0, left_h), 1), "filledAt": filled.isoformat()}


def stagger_days(jar_a: dict[str, Any], jar_b: dict[str, Any], now: datetime) -> float | None:
    """How far apart two jars' restart cycles sit (the A/B backup is only a
    backup when they never restart together)."""
    a = culture_state(jar_a, now)
    b = culture_state(jar_b, now)
    if a["daysSinceRestart"] is None or b["daysSinceRestart"] is None:
        return None
    return round(abs(a["daysSinceRestart"] - b["daysSinceRestart"]), 1)
