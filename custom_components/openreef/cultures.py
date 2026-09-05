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
# Crash signs the keeper can tap (doc §8.5): each one is a restart (rotifers)
# or a water change (pods) due NOW, whatever the calendar says.
SIGNS: tuple[str, ...] = ("foam", "milky", "smell", "surface")
SIGN_WORDS = {"foam": "foam on the surface", "milky": "milky water", "smell": "a smell",
              "surface": "clustering at the surface"}
LEARN_SAMPLES = 3          # rolling window, the hatch clock's contract
SLOW_FACTOR = 1.5          # clearing this much slower than usual, twice running = tiring
FEED_EVENTS: tuple[str, ...] = ("feed", "harvest", "seeded", "restart")
# The DHA step (doc §8.3, Stage C): Reefphyto's algae enrichment, drops into a
# portion of the crop, a short soak, then the fridge bottle runs a BOOST clock
# on top of its viability clock — FAO: EFA constant ~7 h warm, 30 % DHA gone by
# 12 h; the boost holds ~24 h cold (snippet-level, conservative).
ENRICH_SOAK_H = 6.0
ENRICH_DROPS = 3
ENRICH_DROP_ML = 0.05
BOOST_WARM_H = 8.0
BOOST_COLD_H = 24.0
BOTTLE_EVENTS: tuple[str, ...] = ("filled", "fed_tank", "enriched", "emptied")
GUARD_LOOKAHEAD_H = 24.0       # the heatwave guard looks one day ahead (doc §8.8 #2)
TINT_STRIP_DAYS = 14
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
        out["restart"]["reason"] = "cap" if out["restart"]["due"] else None
        out["percent"] = round(min(100.0, 100.0 * since_restart / cad["restartIntervalDays"]))
    if cad["waterChangeIntervalDays"] > 0:
        out["waterChange"] = _due(state.get("lastWaterChangeAt"), state.get("startedAt"),
                                  timedelta(days=cad["waterChangeIntervalDays"]), now)
    # Restart on a SIGN, not a date (doc §8.5): a crash-sign tap since the last
    # restart, or the water clearing much slower than it used to two feeds
    # running, brings the restart forward. A species without a restart (pods)
    # turns the sign into a water change instead.
    sign_at = _parse_iso(state.get("lastSignAt"))
    signed = sign_at is not None and sign_at >= restart_anchor
    wc_anchor = _parse_iso(state.get("lastWaterChangeAt")) or started
    slow = False
    samples = clearing_samples(jar.get("history"))
    if len(samples) >= 4:
        baseline = sum(samples[2:5]) / len(samples[2:5])
        slow = baseline > 0 and samples[0] > SLOW_FACTOR * baseline and samples[1] > SLOW_FACTOR * baseline
    out["clearingSlow"] = slow
    if cad["restartIntervalDays"] > 0 and (signed or slow):
        out["restart"].update({"available": True, "due": True, "hoursUntil": 0.0,
                               "at": (sign_at if signed else now).isoformat(),
                               "reason": "sign" if signed else "slow"})
    elif cad["restartIntervalDays"] <= 0 and cad["waterChangePct"] > 0 and sign_at is not None \
            and sign_at >= wc_anchor:
        out["waterChange"] = {"available": True, "due": True, "at": sign_at.isoformat(),
                              "hoursUntil": 0.0, "hoursOverdue": round(max(0.0, (now - sign_at).total_seconds() / 3600.0), 1),
                              "reason": "sign"}
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


def feed_advice(tint: Any, feed_clock: dict[str, Any], harvest_clock: Any = None,
                harvest_interval_h: Any = None) -> dict[str, Any]:
    """What the tint says, married to the feed clock. Clear water = the jar
    ate everything = feed now, whatever the clock. Green at feed time = it is
    still full of food = skip this one (overfeeding drives ammonia). Clearing
    = feed on schedule. Harvest DEBT outranks all of it (doc §8.8): two
    missed harvests means the ammonia is already climbing — harvest first."""
    tint = str(tint or "")
    due = bool(feed_clock.get("due"))
    if isinstance(harvest_clock, dict) and harvest_clock.get("due") and _f(harvest_interval_h) > 0 \
            and _f(harvest_clock.get("hoursOverdue")) >= _f(harvest_interval_h):
        return {"action": "harvest_first",
                "reason": "two harvests missed — harvest before you feed, the ammonia is climbing"}
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


# --------------------------------------------------------------------------- #
# V2 Stage B — the journal that learns (doc §8.5)
# --------------------------------------------------------------------------- #
def _chronological(history: Any) -> list[tuple[datetime, dict[str, Any]]]:
    rows = []
    for row in (history if isinstance(history, list) else []):
        if not isinstance(row, dict):
            continue
        at = _parse_iso(row.get("at"))
        if at is not None:
            rows.append((at, row))
    rows.sort(key=lambda item: item[0])
    return rows


def clearing_samples(history: Any) -> list[float]:
    """Hours from a feed to the next tap that found the water CLEAR — how fast
    the jar eats. A later feed before it cleared voids that sample (the jar
    never got there). Newest first, capped at a week per sample."""
    samples: list[float] = []
    fed_at: datetime | None = None
    for at, row in _chronological(history):
        if row.get("tint") == "clear" and fed_at is not None:
            hours = (at - fed_at).total_seconds() / 3600.0
            if 0 < hours <= 7 * 24:
                samples.append(round(hours, 1))
            fed_at = None
        if row.get("event") in FEED_EVENTS:
            fed_at = at
    samples.reverse()
    return samples


def first_harvest_samples(histories: Any) -> list[float]:
    """Days from a seed to that seed's first harvest, across every jar of the
    species (one jar rarely reseeds often enough to learn alone)."""
    samples: list[tuple[datetime, float]] = []
    for history in (histories if isinstance(histories, list) else []):
        seed_at: datetime | None = None
        for at, row in _chronological(history):
            event = row.get("event")
            if event == "seeded":
                seed_at = at
            elif event == "harvest" and seed_at is not None:
                days = (at - seed_at).total_seconds() / 86400.0
                if 0 < days <= 60:
                    samples.append((at, round(days, 1)))
                seed_at = None
    samples.sort(key=lambda item: item[0], reverse=True)
    return [days for _at, days in samples]


def run_length_samples(history: Any) -> list[float]:
    """Days a jar ran between seed/restart and the next restart or crash —
    what the fortnight cap should really be for THIS jar. Newest first."""
    samples: list[float] = []
    anchor: datetime | None = None
    for at, row in _chronological(history):
        event = row.get("event")
        if event in ("restart", "crashed") and anchor is not None:
            days = (at - anchor).total_seconds() / 86400.0
            if 0 < days <= 90:
                samples.append(round(days, 1))
        if event in ("seeded", "restart"):
            anchor = at
        elif event == "crashed":
            anchor = None
    samples.reverse()
    return samples


def yield_ml_per_day(history: Any, now: datetime, window_days: float = 14.0) -> float | None:
    """Harvested ml per day over the recent window — the NPS runway's demand
    figure. None until something has been harvested."""
    total = 0.0
    oldest: datetime | None = None
    for at, row in _chronological(history):
        if row.get("event") != "harvest":
            continue
        age_days = (now - at).total_seconds() / 86400.0
        if age_days < 0 or age_days > window_days:
            continue
        total += max(0.0, _f(row.get("ml")))
        oldest = at if oldest is None or at < oldest else oldest
    if oldest is None or total <= 0:
        return None
    span = max(1.0, (now - oldest).total_seconds() / 86400.0)
    return round(total / span)


def _rolling(samples: list[float], key: str) -> dict[str, Any]:
    """The hatch clock's contract: the last three ACTUALS, two before it says
    anything, advisory-with-Apply."""
    recent = samples[:LEARN_SAMPLES]
    if len(recent) < 2:
        return {"available": False, key: None, "samples": len(recent)}
    return {"available": True, key: round(sum(recent) / len(recent), 1), "samples": len(recent)}


def learned_cadences(jar: dict[str, Any], sibling_histories: Any, now: datetime) -> dict[str, Any]:
    """Everything the journal can teach about this jar, plus the two numbers
    it would change if the keeper taps Apply: feed a little before the water
    clears, restart a day before the run usually turns."""
    history = jar.get("history") if isinstance(jar.get("history"), list) else []
    cad = cadence_for(jar.get("species"), jar.get("cadence"))
    clearing = _rolling(clearing_samples(history), "hours")
    first = _rolling(first_harvest_samples(sibling_histories), "days")
    run = _rolling(run_length_samples(history), "days")
    suggest: dict[str, Any] = {"feedIntervalH": None, "restartIntervalDays": None}
    if clearing["available"]:
        hours = max(2.0, min(72.0, round(clearing["hours"] * 0.9)))
        if abs(hours - cad["feedIntervalH"]) >= 1:
            suggest["feedIntervalH"] = hours
    if run["available"] and cad["restartIntervalDays"] > 0:
        days = max(3.0, round(run["days"] - 1))
        if abs(days - cad["restartIntervalDays"]) >= 1:
            suggest["restartIntervalDays"] = days
    return {"clearingH": clearing, "firstHarvestDays": first, "runLengthDays": run,
            "yieldMlDay": yield_ml_per_day(history, now), "suggest": suggest}


def risk_line(jar: dict[str, Any], st: dict[str, Any], temp: dict[str, Any], now: datetime) -> dict[str, Any]:
    """The hatchery nose, made explainable (doc §8.8): one sentence with the
    cause, built only from stamps — never a score. ``act`` = do something
    today, ``watch`` = look harder, ``ok`` = leave it alone."""
    if st.get("status") not in ("establishing", "producing"):
        return {"level": "ok", "reason": ""}
    state = jar.get("state") if isinstance(jar.get("state"), dict) else {}
    cad = st.get("cadence") if isinstance(st.get("cadence"), dict) else cadence_for(jar.get("species"), jar.get("cadence"))
    act: list[str] = []
    watch: list[str] = []
    t_status = str((temp or {}).get("status") or "")
    if t_status == "critical" or (t_status == "hot" and (temp or {}).get("act")):
        act.append(f"room {temp.get('tempC')} °C — over the act line (oxygen and ammonia, not the animal)")
    elif t_status == "hot":
        watch.append(f"room {temp.get('tempC')} °C — over the warning line")
    harvest = st.get("harvest") or {}
    interval_h = _f(cad.get("harvestIntervalDays")) * 24.0
    if harvest.get("due") and st.get("status") == "producing":
        if interval_h > 0 and _f(harvest.get("hoursOverdue")) >= interval_h:
            act.append("two harvests missed — the ammonia is climbing, harvest before you feed")
        else:
            watch.append("harvest overdue")
    sign = str(state.get("lastSign") or "")
    restart = st.get("restart") or {}
    water = st.get("waterChange") or {}
    if sign and (restart.get("reason") == "sign" or water.get("reason") == "sign"):
        act.append(f"{SIGN_WORDS.get(sign, sign)} since the last "
                   f"{'restart' if restart.get('reason') == 'sign' else 'water change'}")
    if st.get("clearingSlow"):
        watch.append("clearing is slowing — the culture is tiring")
    for at, row in _chronological(jar.get("history")):
        if row.get("event") in ("feed", "harvest") and row.get("tint") == "green" \
                and 0 <= (now - at).total_seconds() <= 86400:
            watch.append("fed on green water — that is how ammonia starts")
            break
    if act:
        return {"level": "act", "reason": "; ".join(act)}
    if watch:
        return {"level": "watch", "reason": "; ".join(watch)}
    return {"level": "ok", "reason": "steady — nothing to worry about"}


# --------------------------------------------------------------------------- #
# V2 Stage C — the DHA step and the tank (doc §8.3, §8.6)
# --------------------------------------------------------------------------- #
def soak_state(started_iso: Any, soak_h: Any, warm_h: Any, now: datetime) -> dict[str, Any]:
    """Where the enrichment portion sits: ``none``, ``soaking`` (percent and
    hours left), ``done`` (rinse and bottle — the warm boost window is
    ticking) or ``fading`` (the warm window is spent; bottle it anyway, it is
    still live food, just no longer enriched food)."""
    started = _parse_iso(started_iso)
    hours = _f(soak_h) if _f(soak_h) > 0 else ENRICH_SOAK_H
    warm = _f(warm_h) if _f(warm_h) > 0 else BOOST_WARM_H
    if started is None:
        return {"status": "none", "percent": None, "hoursLeft": None, "hoursElapsed": None}
    elapsed = max(0.0, (now - started).total_seconds() / 3600.0)
    if elapsed < hours:
        return {"status": "soaking", "percent": round(min(99.0, 100.0 * elapsed / hours)),
                "hoursLeft": round(hours - elapsed, 1), "hoursElapsed": round(elapsed, 1)}
    status = "done" if elapsed < hours + warm else "fading"
    return {"status": status, "percent": 100, "hoursLeft": round(max(0.0, hours + warm - elapsed), 1),
            "hoursElapsed": round(elapsed, 1)}


def bottle_boost(bottle: dict[str, Any], cold_h: Any, now: datetime) -> dict[str, Any]:
    """The gut-loaded window on the fridge bottle, counted from the END of the
    soak (the hatchery's ``hatch_prime_state`` lesson): ``gutloaded`` while the
    cold window holds, ``faded`` after — still live food, no longer enriched
    food; ``none`` for an unenriched or empty bottle."""
    if _f(bottle.get("remainingMl")) <= 0 or not bottle.get("lastLoadEnriched"):
        return {"status": "none", "hoursLeft": None}
    enriched = _parse_iso(bottle.get("enrichedAt"))
    if enriched is None:
        return {"status": "faded", "hoursLeft": 0.0}
    cold = _f(cold_h) if _f(cold_h) > 0 else BOOST_COLD_H
    left = cold - (now - enriched).total_seconds() / 3600.0
    if left <= 0:
        return {"status": "faded", "hoursLeft": 0.0}
    return {"status": "gutloaded", "hoursLeft": round(left, 1)}


def bottle_usage_ml_per_day(history: Any, now: datetime, window_days: float = 7.0) -> float | None:
    """How fast the bottle is being fed out — ml a day over the recent window,
    None until a feed has been logged (never a guess)."""
    total = 0.0
    oldest: datetime | None = None
    for at, row in _chronological(history):
        if row.get("event") != "fed_tank":
            continue
        age_days = (now - at).total_seconds() / 86400.0
        if age_days < 0 or age_days > window_days:
            continue
        total += max(0.0, _f(row.get("ml")))
        oldest = at if oldest is None or at < oldest else oldest
    if oldest is None or total <= 0:
        return None
    return round(total / max(1.0, (now - oldest).total_seconds() / 86400.0), 1)


def next_harvest(bottle_state: dict[str, Any], ml_per_day: Any, harvest_clock: Any,
                 producing: bool) -> dict[str, Any]:
    """When to harvest next — the daily-driver question, the hatch's
    ``next_hatch_suggestion`` shape: before the bottle runs dry, before it
    goes stale, or simply when the jar's own clock says so; whichever comes
    first drives, and the copy names the driver."""
    if not producing:
        return {"status": "none", "hoursUntil": None, "driver": None}
    status = str(bottle_state.get("status") or "empty")
    clock = harvest_clock if isinstance(harvest_clock, dict) else {}
    if status in ("empty", "stale"):
        return {"status": "now", "hoursUntil": 0.0,
                "driver": "empty" if status == "empty" else "freshness"}
    candidates: list[tuple[float, str]] = []
    left = bottle_state.get("hoursLeft")
    if left is not None:
        candidates.append((max(0.0, _f(left)), "freshness"))
    rate = _f(ml_per_day)
    if rate > 0:
        candidates.append((max(0.0, _f(bottle_state.get("remainingMl")) / rate * 24.0), "depletion"))
    if clock.get("available") and clock.get("at"):
        candidates.append((0.0 if clock.get("due") else max(0.0, _f(clock.get("hoursUntil"))), "jar"))
    if not candidates:
        return {"status": "none", "hoursUntil": None, "driver": None}
    hours, driver = min(candidates, key=lambda item: item[0])
    if hours <= 0:
        return {"status": "now", "hoursUntil": 0.0, "driver": driver}
    return {"status": "wait", "hoursUntil": round(hours, 1), "driver": driver}


# --------------------------------------------------------------------------- #
# V2 Stage D — never zero, and the guard (doc §8.8)
# --------------------------------------------------------------------------- #
def heat_guard(projection_hours: Any, species_id: Any, now: datetime,
               lookahead_h: float = GUARD_LOOKAHEAD_H) -> dict[str, Any]:
    """The heatwave guard: the cooling headroom's indoor projection (room °C
    per forecast hour, learned offsets included) against the species band.
    ``warn`` when the room is projected past the warning line inside the
    window (with WHEN), ``watch`` past the productive band, ``clear``
    otherwise; ``available`` False with no projection — never a guess."""
    species = species_preset(species_id)
    rows = []
    for row in (projection_hours if isinstance(projection_hours, list) else []):
        if not isinstance(row, dict):
            continue
        at = _parse_iso(row.get("at"))
        room = row.get("roomC")
        if at is None or not isinstance(room, (int, float)) or isinstance(room, bool):
            continue
        hours = (at - now).total_seconds() / 3600.0
        if -1.0 <= hours <= lookahead_h:
            rows.append((at, float(room), hours))
    if not rows:
        return {"available": False, "status": "unknown", "peakC": None, "peakAt": None,
                "crossAt": None, "hoursUntil": None, "line": ""}
    peak_at, peak_c, _h = max(rows, key=lambda r: r[1])
    hard = _f(species["tempHardMaxC"])
    band = _f(species["tempMaxC"])
    cross = next((r for r in rows if r[1] >= hard), None)
    if cross is not None:
        at, room, hours = cross
        return {"available": True, "status": "warn", "peakC": round(peak_c, 1),
                "peakAt": peak_at.isoformat(), "crossAt": at.isoformat(),
                "hoursUntil": round(max(0.0, hours), 1),
                "line": (f"room passes {hard:g} °C in ~{max(0.0, hours):.0f} h (peak {peak_c:.1f} °C) — "
                         "extra air, shade, feed lightly, a 50 % change ready")}
    if peak_c > band:
        return {"available": True, "status": "watch", "peakC": round(peak_c, 1),
                "peakAt": peak_at.isoformat(), "crossAt": None, "hoursUntil": None,
                "line": f"room peaks at {peak_c:.1f} °C — above the {band:g} °C band, keep an eye on it"}
    return {"available": True, "status": "clear", "peakC": round(peak_c, 1),
            "peakAt": peak_at.isoformat(), "crossAt": None, "hoursUntil": None,
            "line": f"room peaks at {peak_c:.1f} °C — inside the band"}


def stagger_advice(jar_a: dict[str, Any], jar_b: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Two jars are only a backup when they never restart together: the ideal
    gap is half the restart interval; more than two days off it earns a line."""
    days = stagger_days(jar_a, jar_b, now)
    cad = cadence_for(jar_a.get("species"), jar_a.get("cadence"))
    interval = _f(cad.get("restartIntervalDays"))
    if days is None or interval <= 0:
        return {"available": False, "days": None, "idealDays": None, "advice": ""}
    ideal = round(interval / 2.0, 1)
    gap = days % interval if interval > 0 else days
    off = abs(gap - ideal)
    if off <= 2.0:
        advice = f"restart cycles {gap:.0f} days apart — a proper backup"
    else:
        advice = (f"restart cycles only {gap:.0f} days apart (ideal {ideal:g}) — hold one restart "
                  f"{off:.0f} day{'s' if off >= 1.5 else ''} to spread them")
    return {"available": True, "days": round(gap, 1), "idealDays": ideal, "advice": advice}


def tint_strip(history: Any, now: datetime, days: int = TINT_STRIP_DAYS) -> list[str]:
    """The last N days as one tint each (the latest tap that day), oldest
    first, "" for a day with no look — the culture card's strip."""
    by_day: dict[str, str] = {}
    for at, row in _chronological(history):
        tint = str(row.get("tint") or "")
        if tint not in TINTS:
            continue
        by_day[at.date().isoformat()] = tint
    out = []
    for back in range(days - 1, -1, -1):
        out.append(by_day.get((now - timedelta(days=back)).date().isoformat(), ""))
    return out


def continuity_days(since_iso: Any, now: datetime) -> float | None:
    since = _parse_iso(since_iso)
    if since is None:
        return None
    return round(max(0.0, (now - since).total_seconds() / 86400.0), 1)
