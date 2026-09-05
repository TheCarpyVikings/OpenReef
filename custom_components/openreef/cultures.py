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
VESSEL_KINDS: tuple[str, ...] = ("cone", "tub", "jar")
RIG_CONES_MAX = 4

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
     # V2 (doc §8.2): Reefphyto cultures at SG 1.019–1.021; FAO says optimal
     # reproduction only below 35 ppt; 35 ppt is a longer-lived, lower-yield jar.
     "vesselKind": "cone",
     "tempMinC": 18.0, "tempMaxC": 26.0, "tempHardMaxC": 30.0,
     "tempActC": 30.0, "tempCriticalC": 33.0,
     "salinityPpt": 27.0,
     "feedIntervalH": 12.0,
     "harvestIntervalDays": 1.0, "harvestPct": 25.0,
     "restartIntervalDays": 14.0,
     "waterChangeIntervalDays": 0.0, "waterChangePct": 0.0,
     "firstHarvestDays": 6.0, "splitMinAgeDays": 14.0,
     "sieveUm": 50, "adultSieveUm": 0, "bottleShelfDays": 5.0,
     "purgeMl": 50.0,
     "tintTarget": "leafy green — spinach, not pea soup",
     "feedProduct": "Rotifer Feed Concentrate",
     "enrichSoakH": 6.0, "enrichDrops": "1–5", "boostWarmH": 8.0, "boostColdH": 24.0,
     "note": "Room temperature, no light, an open rigid airline to the cone tip at 1–2 bubbles/s "
             "(no airstone). Feed the concentrate to a leafy green, little and often: clear means "
             "hungry, still green at feed time means skip. Before a harvest: air off, settle, bleed "
             "the tip to waste, then 25 % a day through the 50 µm net — the water you take out IS "
             "the water change; refill with matched water. Sieve the whole cone into a clean one "
             "every fortnight, sooner on foam, milk or smell."},
    {"id": "tigriopus", "name": "Tigriopus copepods", "kind": "copepod",
     "latin": "Tigriopus californicus",
     # V2: Reefphyto's copepod guide (35 ppt optimal, 22–26 °C, first harvest
     # 4–6 weeks, ≤25–30 % with 7–10 days between). Heat does not kill the
     # animal below ~34 °C — a hot flat kills through oxygen and ammonia, so
     # the tiers are warn 28 / act 30 / critical 32 and the copy says why.
     "vesselKind": "tub",
     "tempMinC": 18.0, "tempMaxC": 26.0, "tempHardMaxC": 28.0,
     "tempActC": 30.0, "tempCriticalC": 32.0,
     "salinityPpt": 35.0,
     "feedIntervalH": 24.0,
     "harvestIntervalDays": 10.0, "harvestPct": 25.0,
     "restartIntervalDays": 0.0,
     "waterChangeIntervalDays": 0.0, "waterChangePct": 50.0,
     "firstHarvestDays": 28.0, "splitMinAgeDays": 35.0,
     "sieveUm": 50, "adultSieveUm": 300, "bottleShelfDays": 0.0,
     "purgeMl": 0.0,
     "tintTarget": "Granny Smith apple skin",
     "feedProduct": "Copepod Feed",
     "enrichSoakH": 0.0, "enrichDrops": "", "boostWarmH": 0.0, "boostColdH": 0.0,
     "note": "A flat tub, not a cone — they crawl. 35 ppt, 22–26 °C, open airline at 1–3 bubbles/s, "
             "loose lid, no light. Feed the Copepod Feed to a Granny Smith green, half rate in week "
             "one. A generation is a month: first harvest at four to six weeks, then no more than "
             "25–30 % with 7–10 days between (50 µm keeps the nauplii, 300 µm the adults); put the "
             "harvested volume back as fresh water. Any ammonia = a 50 % change now. Warn at 28 °C: "
             "heat kills through oxygen and ammonia, not the animal — extra air, shade, feed lightly."},
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
    # A species with a percentage but no interval changes water on a SIGN
    # (drift, ammonia, cloudy water) — no clock, but the ceremony exists.
    out["waterChangeOnDemand"] = (cad["waterChangeIntervalDays"] <= 0 < cad["waterChangePct"])
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
    the warning line, ``critical`` the line above which the copy stops
    advising and tells the keeper to move the culture; ``act`` flags the
    middle tier (doc §8.2: warn 28 / act 30 / critical 32 for Tigriopus —
    heat kills a jar through oxygen and ammonia long before it kills the
    animal, so the tiers are about the water, not the species' CTmax)."""
    species = species_preset(species_id)
    base = {"minC": species["tempMinC"], "maxC": species["tempMaxC"],
            "hardMaxC": species["tempHardMaxC"],
            "actC": species.get("tempActC", species["tempHardMaxC"]),
            "criticalC": species.get("tempCriticalC", species["tempHardMaxC"])}
    try:
        t = float(temp_c)
    except (TypeError, ValueError):
        return {"available": False, "status": "unknown", "tempC": None, "act": False, **base}
    if t >= _f(base["criticalC"]):
        status = "critical"
    elif t >= _f(species["tempHardMaxC"]):
        status = "hot"
    elif t > _f(species["tempMaxC"]):
        status = "warm"
    elif t < _f(species["tempMinC"]):
        status = "cool"
    else:
        status = "ok"
    return {"available": True, "status": status, "tempC": round(t, 1),
            "act": t >= _f(base["actC"]), **base}


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


def rig_state(jars: Any, bottle: Any) -> dict[str, Any]:
    """The live rig drawing's inputs (doc §8.4), computed from the summary's
    per-jar payloads so the panel only draws: rotifer cones (and plain jars)
    on the left band, one copepod tub, the measured jug, the fridge bottle
    and a caption that names the stage — heat first, then chores, then the
    quiet states. Pure: no clock, no I/O."""
    jars = [j for j in (jars if isinstance(jars, list) else []) if isinstance(j, dict)]
    bottle = bottle if isinstance(bottle, dict) else {}
    cones: list[dict[str, Any]] = []
    tub: dict[str, Any] | None = None

    def _vessel(j: dict[str, Any]) -> dict[str, Any]:
        st = j.get("state") if isinstance(j.get("state"), dict) else {}
        status = str(st.get("status") or "none")
        running = status in ("establishing", "producing")
        due = set(j.get("due") or [])
        first = max(1.0, _f(j.get("firstHarvestDays"), 6.0))
        if st.get("percent") is not None:
            pct = _f(st.get("percent"))
        elif status == "producing":
            pct = 100.0
        elif status == "establishing":
            pct = min(100.0, 100.0 * _f(st.get("ageDays")) / first)
        else:
            pct = 0.0
        advice = j.get("feedAdvice") if isinstance(j.get("feedAdvice"), dict) else {}
        temp = j.get("temp") if isinstance(j.get("temp"), dict) else {}
        return {
            "id": str(j.get("id") or ""), "name": str(j.get("name") or ""),
            "kind": str(j.get("vesselKind") or "jar"), "status": status,
            "tint": str(j.get("tint") or "") if running else "",
            "pct": round(pct),
            "airOn": running,
            "purgeHot": "harvest" in due or "restart" in due,
            "harvestHot": "harvest" in due,
            "refillHot": "harvest" in due or "restart" in due,
            "feedHot": running and advice.get("action") == "feed_now",
            "restartHot": "restart" in due,
            "tempStatus": str(temp.get("status") or "unknown"),
            "establishDays": round(_f(st.get("ageDays"))) if status == "establishing" else None,
            "firstHarvestDays": round(first),
        }

    for j in jars:
        v = _vessel(j)
        if v["kind"] == "tub":
            if tub is None:
                tub = v
        elif len(cones) < RIG_CONES_MAX:
            cones.append(v)
    first_cone = next((j for j in jars if str(j.get("vesselKind") or "jar") != "tub"), None)
    guide = (first_cone.get("harvestGuide") if first_cone and isinstance(first_cone.get("harvestGuide"), dict)
             else {}) or {}
    jug = {
        "harvestMl": round(_f(guide.get("totalMl"))), "mixMl": round(_f(guide.get("mixMl"))),
        "rodiMl": round(_f(guide.get("rodiMl"))), "ppt": _f(guide.get("targetPpt"), 35.0),
        "purgeMl": round(_f(first_cone.get("purgeMl"))) if first_cone else 0,
        "sieveUm": int(_f(first_cone.get("sieveUm"), 50)) if first_cone else 50,
    }
    remaining = max(0.0, _f(bottle.get("remainingMl")))
    volume = max(1.0, _f(bottle.get("volumeMl"), 1000.0))
    bottle_out = {"ml": round(remaining), "pct": round(min(100.0, 100.0 * remaining / volume)),
                  "status": str(bottle.get("status") or "empty")}

    vessels = cones + ([tub] if tub else [])
    caption = "IDLE — seed the cone and the rig comes alive"
    stage = "idle"
    by_temp = {"critical": 3, "hot": 2}
    hot = sorted((v for v in vessels if v["tempStatus"] in by_temp),
                 key=lambda v: -by_temp[v["tempStatus"]])
    if hot:
        v = hot[0]
        temp = next((j.get("temp") for j in jars if j.get("id") == v["id"]), None) or {}
        t = temp.get("tempC")
        if v["tempStatus"] == "critical":
            stage, caption = "heat", (f"ROOM {t} °C — over {v['name']}'s critical line: "
                                      "cool the room or move the culture NOW")
        else:
            stage, caption = "heat", (f"ROOM {t} °C — over {v['name']}'s {temp.get('hardMaxC')} °C line: "
                                      "extra air, shade, feed lightly, a 50 % change ready")
    elif any(v["restartHot"] for v in cones):
        stage, caption = "restart", ("RESTART DUE — air off, settle, bleed the tip, the whole cone "
                                     "through the net into a clean one")
    elif any(v["harvestHot"] for v in cones):
        stage = "harvest"
        refill = (f"{jug['mixMl']} ml mix + {jug['rodiMl']} ml RODI" if jug["rodiMl"]
                  else f"{jug['mixMl']} ml fresh")
        caption = (f"HARVEST — air off, settle 20 min, bleed ~{jug['purgeMl']} ml off the tip, then "
                   f"{jug['harvestMl']} ml through the {jug['sieveUm']} µm net · refill {refill}")
    elif tub and tub["harvestHot"]:
        stage, caption = "tub_harvest", ("POD HARVEST — 25 % through 300 µm for adults, 50 µm "
                                         "for nauplii · put the volume back as fresh water")
    elif any(v["feedHot"] for v in vessels):
        v = next(v for v in vessels if v["feedHot"])
        target = next((j.get("tintTarget") for j in jars if j.get("id") == v["id"]), "") or "a light green"
        stage, caption = "feed", f"FEED — {v['name']} to {target}, little and often"
    elif any(v["status"] == "establishing" for v in vessels):
        v = next(v for v in vessels if v["status"] == "establishing")
        stage, caption = "establishing", (f"ESTABLISHING — {v['name']} day {v['establishDays']} of "
                                          f"{v['firstHarvestDays']} · feed by the tint, no harvest yet")
    elif any(v["status"] == "producing" for v in vessels):
        stage, caption = "steady", "STEADY — nothing due · look at the water"
    elif any(v["status"] == "crashed" for v in vessels):
        stage, caption = "crashed", "CRASHED — reseed from the other jar, or from a fresh starter"
    return {"stage": stage, "caption": caption, "cones": cones, "tub": tub, "jug": jug,
            "bottle": bottle_out}
