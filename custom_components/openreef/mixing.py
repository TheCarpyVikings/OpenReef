"""Saltwater Mixing Station engine — pure maths for the batch workflow.

Design stance (mirrors awc.py / nps.py / dosing.py): everything here is a pure
function of its inputs — no Home Assistant imports, no I/O, no clocks.
Orchestration (WS handlers, plug switching, timers) lives in __init__.py.

Stage A scope (docs/mixing-station-brainstorm.md §12): batch state evaluation,
the salt brand table + dose/correction maths, level-ledger reads, start-guard
reasons, and the summary() blob the panel renders. The state machine's
TRANSITIONS are Stage B orchestration — this module only ever answers "where
does the batch sit right now, given these stamps".

Honesty rules (the AWC tradition): levels are stored anchors moved by confirmed
events (fill done, transfer done, batch used), never sensor cosplay — the panel
labels them "estimated" until real level entities are bound. Salt doses are
brand-published guides, clearly approximate; a "custom" brand with no g/L gives
no dose figure, never a guess. The mix clock is a stamped timestamp evaluated
on read (the hatchery pattern), so a settings edit can never rewrite a running
batch.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .awc import _f, _parse_iso

# ---------------------------------------------------------------- brand table

# gPerL35 = grams of salt per litre of RODI for 35 ppt, from the brands' own
# published dosing guidance (approximate — density scoops vary; the panel says
# "guide"). mixHoursDefault = the brand's recommended mixing window before use;
# useWithinH = brands that want the batch USED soon after mixing (0 = no rush).
SALT_BRANDS: tuple[dict[str, Any], ...] = (
    {"id": "nyos_pure", "label": "NYOS Pure", "gPerL35": 39.0,
     "mixHoursDefault": 2.0, "useWithinH": 0},
    {"id": "redsea_coralpro", "label": "Red Sea Coral Pro", "gPerL35": 39.0,
     "mixHoursDefault": 2.0, "useWithinH": 4},
    {"id": "redsea_salt", "label": "Red Sea Salt", "gPerL35": 38.0,
     "mixHoursDefault": 2.0, "useWithinH": 4},
    {"id": "instant_ocean", "label": "Instant Ocean", "gPerL35": 36.5,
     "mixHoursDefault": 12.0, "useWithinH": 0},
    {"id": "reef_crystals", "label": "Reef Crystals", "gPerL35": 37.5,
     "mixHoursDefault": 12.0, "useWithinH": 0},
    {"id": "tm_classic", "label": "Tropic Marin Classic", "gPerL35": 37.5,
     "mixHoursDefault": 2.0, "useWithinH": 0},
    {"id": "tm_proreef", "label": "Tropic Marin Pro-Reef", "gPerL35": 37.5,
     "mixHoursDefault": 2.0, "useWithinH": 0},
    {"id": "fritz_rpm", "label": "Fritz RPM", "gPerL35": 38.0,
     "mixHoursDefault": 2.0, "useWithinH": 0},
    {"id": "aquaforest_reef", "label": "Aquaforest Reef Salt", "gPerL35": 38.0,
     "mixHoursDefault": 2.0, "useWithinH": 24},
    {"id": "brightwell_neomarine", "label": "Brightwell NeoMarine", "gPerL35": 38.5,
     "mixHoursDefault": 2.0, "useWithinH": 0},
    # custom: the user supplies gPerL / hours in config; no figure until they do.
    {"id": "custom", "label": "Custom / other", "gPerL35": 0.0,
     "mixHoursDefault": 0.0, "useWithinH": 0},
)
_BRANDS_BY_ID = {b["id"]: b for b in SALT_BRANDS}

REFERENCE_PPT = 35.0
PPT_TOLERANCE = 0.5            # |measured − target| within this ⇒ batch passes
RETEST_DEFAULT_DAYS = 7.0
MIX_LAYOUTS = ("dual", "single")
VESSEL_CONTENTS = ("empty", "rodi", "salt")
SALINITY_UNITS = ("ppt", "sg")
# The hobby anchor every SG scale is drawn around: 35 ppt ↔ 1.0264 SG (20/20).
# A linear map through it is well inside hobby-instrument accuracy across the
# reef range (±0.001 SG on a swing-arm is ±1.3 ppt by itself). ppt stays the
# canonical stored unit everywhere; SG is a keeper-facing skin on it.
REFERENCE_SG = 1.0264
PPT_PER_SG_POINT = REFERENCE_PPT / (REFERENCE_SG - 1.0)   # ≈ 1325.8


def ppt_from_sg(sg: Any) -> float:
    """Specific gravity → ppt on the hobby anchor line. Non-physical readings
    (≤ 1.000) come back 0 — the guards treat that as 'no reading'."""
    return round(max(0.0, (_f(sg) - 1.0) * PPT_PER_SG_POINT), 2)


def sg_from_ppt(ppt: Any) -> float:
    """ppt → specific gravity, 4 decimals (the resolution SG scales print)."""
    return round(1.0 + max(0.0, _f(ppt)) / PPT_PER_SG_POINT, 4)


def brand_ids() -> tuple[str, ...]:
    return tuple(b["id"] for b in SALT_BRANDS)


def brand_info(brand: Any) -> dict[str, Any]:
    return dict(_BRANDS_BY_ID.get(str(brand or ""), _BRANDS_BY_ID["custom"]))


def brand_g_per_l(brand: Any, custom_g_per_l: Any = 0) -> float:
    """Effective g/L at 35 ppt: the brand's figure, or the user's own for
    "custom". 0 = unknown — callers must show nothing, not a guess."""
    info = brand_info(brand)
    if info["id"] == "custom":
        return max(0.0, _f(custom_g_per_l))
    return _f(info["gPerL35"])


def mix_hours(brand: Any, override_hours: Any = 0) -> float:
    """Mix window before the Test prompt unlocks: user override when > 0, else
    the brand default, else a conservative 2 h so the clock always runs."""
    override = _f(override_hours)
    if override > 0:
        return override
    default = _f(brand_info(brand)["mixHoursDefault"])
    return default if default > 0 else 2.0


# ---------------------------------------------------------------- dose maths

def salt_dose(brand: Any, litres: Any, target_ppt: Any,
              custom_g_per_l: Any = 0) -> dict[str, Any]:
    """The scoop guide: grams for this batch, linear-scaled off the brand's
    35 ppt figure. Approximate by nature — the keeper's salinity test is the truth."""
    g_per_l = brand_g_per_l(brand, custom_g_per_l)
    lit = _f(litres)
    ppt = _f(target_ppt, REFERENCE_PPT)
    if g_per_l <= 0 or lit <= 0 or ppt <= 0:
        return {"available": False, "grams": None, "gPerL": None}
    g_per_l_target = g_per_l * ppt / REFERENCE_PPT
    return {"available": True,
            "grams": round(g_per_l_target * lit, 0),
            "gPerL": round(g_per_l_target, 1)}


def salinity_correction(measured_ppt: Any, target_ppt: Any, litres: Any,
                        brand: Any, custom_g_per_l: Any = 0) -> dict[str, Any]:
    """What fixes an out-of-band test: LOW ⇒ grams of salt to add; HIGH ⇒
    litres of RODI to dilute (mass balance: V·m/t − V). Within tolerance ⇒
    pass. Dilution needs no brand figure; adding salt does."""
    measured = _f(measured_ppt)
    target = _f(target_ppt, REFERENCE_PPT)
    lit = _f(litres)
    if measured <= 0 or target <= 0 or lit <= 0:
        return {"available": False, "status": "unknown",
                "addGrams": None, "diluteLitres": None}
    delta = measured - target
    if abs(delta) <= PPT_TOLERANCE:
        return {"available": True, "status": "pass",
                "addGrams": None, "diluteLitres": None}
    if delta < 0:
        g_per_l = brand_g_per_l(brand, custom_g_per_l)
        add = round(-delta / REFERENCE_PPT * g_per_l * lit, 0) if g_per_l > 0 else None
        return {"available": True, "status": "low",
                "addGrams": add, "diluteLitres": None}
    return {"available": True, "status": "high", "addGrams": None,
            "diluteLitres": round(lit * (measured / target - 1.0), 1)}


# ---------------------------------------------------------------- stage plan

def mix_contents(cfg: Any) -> str:
    """What the mix vessel holds — the field the independent processes guard
    each other with (doc §15)."""
    cfg = cfg if isinstance(cfg, dict) else {}
    vessels = cfg.get("vessels") if isinstance(cfg.get("vessels"), dict) else {}
    mix_v = vessels.get("mix") if isinstance(vessels.get("mix"), dict) else {}
    contents = str(mix_v.get("contents") or "empty")
    return contents if contents in VESSEL_CONTENTS else "empty"


def mix_vessel_litres(cfg: Any) -> float:
    """The mix vessel's estimated litres — its own anchor, clamped by volume."""
    cfg = cfg if isinstance(cfg, dict) else {}
    vessels = cfg.get("vessels") if isinstance(cfg.get("vessels"), dict) else {}
    mix_v = vessels.get("mix") if isinstance(vessels.get("mix"), dict) else {}
    vol = max(0.0, _f(mix_v.get("volumeLitres")))
    litres = max(0.0, _f(mix_v.get("estimatedLitres")))
    return min(litres, vol) if vol > 0 else litres


def stage_sequence(heat_enabled: Any) -> tuple[str, ...]:
    """The stages a MIX RUN walks — the panel's progress rail. Water movement
    (fills, transfers) is not a run stage any more (doc §15): only the salt
    part is a machine, and Heat comes before the salt when enabled."""
    stages = ["heating"] if bool(heat_enabled) else []
    stages.extend(["salting", "ready", "storing"])
    return tuple(stages)


def batch_state(batch: Any, cfg: Any, now: datetime) -> dict[str, Any]:
    """Where the batch sits, evaluated from its stamps — never mutated here.

    Adds the read-side clocks: the salting mix timer (percent / testUnlocked,
    hatchery-shaped) and the storing age (retestDue past storage.retestAfterDays,
    or past the brand's useWithinH when that is tighter)."""
    batch = batch if isinstance(batch, dict) else {}
    cfg = cfg if isinstance(cfg, dict) else {}
    status = str(batch.get("state") or "idle")
    litres = _f(batch.get("litres"))
    # Remaining litres are the VESSEL's ledger — usage, AWC debits and manual
    # corrections all move the one anchor (doc §15).
    remaining = mix_vessel_litres(cfg)
    salt_cfg = cfg.get("salt") if isinstance(cfg.get("salt"), dict) else {}
    out: dict[str, Any] = {
        "status": status,
        "contents": mix_contents(cfg),
        "litres": round(litres, 1), "remainingLitres": round(remaining, 1),
        "stages": list(stage_sequence((cfg.get("heat") or {}).get("enabled"))),
        "mix": {"percent": None, "hoursLeft": None, "testUnlocked": False},
        "ageDays": None, "retestDue": False,
        # Storing circulation: a burst is running while circulateUntil is ahead
        # of now — the diagram spins the impellers off this, never off a guess.
        "circulating": False,
        "loggedPpt": batch.get("loggedPpt"),
        # Pre-converted for SG-reading keepers — the panel shows, never computes.
        "loggedSg": sg_from_ppt(batch.get("loggedPpt"))
        if _f(batch.get("loggedPpt")) > 0 else None,
    }
    if status in ("ready", "storing"):
        until = _parse_iso(batch.get("circulateUntil"))
        out["circulating"] = until is not None and until > now
        # The schedule, visible: the panel says "next stir at HH:MM" instead
        # of asking the keeper to trust an invisible timer. Empty mid-burst
        # by design — "circulating" carries that half of the story.
        out["nextCirculateAt"] = str(batch.get("nextCirculateAt") or "")
    if status == "salting":
        stamp = _parse_iso(batch.get("stageAt"))
        hours = mix_hours(salt_cfg.get("brand"), salt_cfg.get("mixHours"))
        if stamp is not None:
            elapsed_h = max(0.0, (now - stamp).total_seconds() / 3600.0)
            out["mix"] = {
                "percent": round(min(100.0, elapsed_h / hours * 100.0), 0),
                "hoursLeft": round(max(0.0, hours - elapsed_h), 1),
                "testUnlocked": elapsed_h >= hours,
            }
    if status in ("ready", "storing"):
        tested = _parse_iso(batch.get("testedAt")) or _parse_iso(batch.get("stageAt"))
        if tested is not None:
            age_d = max(0.0, (now - tested).total_seconds() / 86400.0)
            out["ageDays"] = round(age_d, 1)
            retest_days = _f((cfg.get("storage") or {}).get("retestAfterDays"),
                             RETEST_DEFAULT_DAYS)
            use_within_h = _f(brand_info(salt_cfg.get("brand")).get("useWithinH"))
            due = retest_days > 0 and age_d >= retest_days
            if use_within_h > 0:
                due = due or age_d * 24.0 >= use_within_h
            out["retestDue"] = due
    return out


# ---------------------------------------------------------------- level ledger

def vessel_levels(cfg: Any) -> dict[str, Any]:
    """Estimated levels: stored anchors moved by confirmed events (fill done,
    transfer logged, water used). Each vessel owns its ledger now — the mix
    side also says WHAT it holds (doc §15). estimated=True until real level
    entities take over (sensor-first, later)."""
    cfg = cfg if isinstance(cfg, dict) else {}
    vessels = cfg.get("vessels") if isinstance(cfg.get("vessels"), dict) else {}
    dual = str(cfg.get("layout") or "dual") == "dual"
    rodi = vessels.get("rodi") if isinstance(vessels.get("rodi"), dict) else {}
    mix = vessels.get("mix") if isinstance(vessels.get("mix"), dict) else {}
    rodi_vol = max(0.0, _f(rodi.get("volumeLitres")))
    mix_vol = max(0.0, _f(mix.get("volumeLitres")))
    mix_l = mix_vessel_litres(cfg)
    out = {"mix": {"litres": round(mix_l, 1), "volumeLitres": mix_vol,
                   "percent": round(min(100.0, mix_l / mix_vol * 100.0), 0)
                   if mix_vol > 0 else None,
                   "contents": mix_contents(cfg),
                   "estimated": True}}
    if dual:
        rodi_l = min(rodi_vol, max(0.0, _f(rodi.get("estimatedLitres")))) \
            if rodi_vol > 0 else max(0.0, _f(rodi.get("estimatedLitres")))
        out["rodi"] = {"litres": round(rodi_l, 1), "volumeLitres": rodi_vol,
                       "percent": round(min(100.0, rodi_l / rodi_vol * 100.0), 0)
                       if rodi_vol > 0 else None,
                       "estimated": True}
    return out


# ---------------------------------------------------------------- RODI utility

RODI_DRAW_DESTINATIONS = ("store", "mix", "external")


def _rodi_cfg(cfg: Any) -> dict[str, Any]:
    cfg = cfg if isinstance(cfg, dict) else {}
    rodi = cfg.get("rodi")
    return rodi if isinstance(rodi, dict) else {}


def rodi_busy_reason(cfg: Any) -> str | None:
    """Why the booster is spoken for right now — a draw and a calibration run
    are mutually exclusive users of the same plug."""
    rodi = _rodi_cfg(cfg)
    if (rodi.get("draw") or {}).get("active"):
        return "a RODI run is already going"
    if (rodi.get("calibration") or {}).get("active"):
        return "a flow calibration is running"
    return None


def _booster_driven(cfg: Any) -> bool:
    """Simulate counts; otherwise a bound booster plug. Engine-side twin of the
    orchestrator's check — a timed run is meaningless with nothing to switch."""
    cfg = cfg if isinstance(cfg, dict) else {}
    if cfg.get("simulate"):
        return True
    switch = (cfg.get("switches") or {}).get("rodiBooster")
    return bool(isinstance(switch, dict) and str(switch.get("switchEntity") or "").strip())


def draw_guard_reasons(cfg: Any, litres: Any, destination: Any) -> list[str]:
    """Why a RODI run must not start. Two shapes (doc §15): litres > 0 is a
    TIMED draw metered by rate x time (an unknown rate refuses honestly);
    litres == 0 is an OPEN-ENDED fill into one of our vessels — it runs until
    the keeper confirms it done (the float valve is the real stop, the fill
    cap the software backstop), so it needs no rate but does need a vessel.
    Water never lands on standing saltwater outside the dilution window."""
    cfg = cfg if isinstance(cfg, dict) else {}
    reasons: list[str] = []
    if not cfg.get("enabled"):
        reasons.append("Mixing station is not enabled")
    dest = str(destination or "store")
    if dest not in RODI_DRAW_DESTINATIONS:
        reasons.append(f"Unknown draw destination '{dest}'")
    if dest == "store" and str(cfg.get("layout") or "dual") == "single":
        reasons.append("Single-vessel layout has no RODI store — "
                       "fill the vessel instead")
    lit = _f(litres)
    if lit < 0:
        reasons.append("Draw litres cannot be negative")
    rate = _f(_rodi_cfg(cfg).get("rateLph"))
    if lit > 0 and rate <= 0:
        reasons.append("RODI flow rate is unknown — calibrate it (or set a rate "
                       "in settings) for a timed draw, or use an open-ended fill")
    if lit == 0 and dest == "external":
        reasons.append("An open-ended run needs one of our vessels — "
                       "a T-off has no float valve to stop at")
    if not _booster_driven(cfg):
        reasons.append("Bind the RODI booster plug (or turn on Simulate) — "
                       "a RODI run needs OpenReef on the switch")
    busy = rodi_busy_reason(cfg)
    if busy:
        reasons.append(f"The booster is busy — {busy}")
    state = str((cfg.get("batch") or {}).get("state") or "idle")
    if dest == "mix" and mix_contents(cfg) == "salt" and state != "salting":
        reasons.append("The vessel still holds mixed saltwater — "
                       "use or discard it before adding fresh RODI")
    if dest in ("store", "mix") and lit > 0:
        vessels = cfg.get("vessels") if isinstance(cfg.get("vessels"), dict) else {}
        vessel = vessels.get("rodi" if dest == "store" else "mix")
        vessel = vessel if isinstance(vessel, dict) else {}
        vol = _f(vessel.get("volumeLitres"))
        if vol > 0:
            free = max(0.0, vol - max(0.0, _f(vessel.get("estimatedLitres"))))
            if lit > free + 0.05:
                name = "store" if dest == "store" else "vessel"
                reasons.append(f"That would overflow the {name} — "
                               f"about {free:g} L of {vol:g} L free")
    return reasons


def rodi_status(cfg: Any, now: datetime) -> dict[str, Any]:
    """The RODI unit's honest snapshot: the configured/calibrated rate, the
    filter-litres ledger, and the live draw/calibration clocks (read from the
    stamps, never mutated here — the batch_state contract)."""
    rodi = _rodi_cfg(cfg)
    rate = max(0.0, _f(rodi.get("rateLph")))
    processed = max(0.0, _f(rodi.get("litresProcessed")))
    # Filters v2: each stage reports its own life. percentLeft is None when a
    # stage is untracked (rated 0) — the panel draws "unknown", never a guess.
    filters: list[dict[str, Any]] = []
    raw_filters = rodi.get("filters") if isinstance(rodi.get("filters"), list) else []
    for stage in raw_filters:
        if not isinstance(stage, dict):
            continue
        rated = max(0.0, _f(stage.get("ratedLitres")))
        used = max(0.0, _f(stage.get("litresProcessed")))
        filters.append({
            "id": str(stage.get("id") or ""),
            "label": str(stage.get("label") or ""),
            "type": str(stage.get("type") or "other"),
            "ratedLitres": round(rated, 1),
            "litresProcessed": round(used, 1),
            "percentLeft": round(max(0.0, min(100.0, (1 - used / rated) * 100.0)), 0)
            if rated > 0 else None,
            "due": rated > 0 and used >= rated,
            "changedAt": str(stage.get("changedAt") or ""),
        })
    out: dict[str, Any] = {
        "rateLph": round(rate, 2),
        "flushSeconds": int(max(0.0, _f(rodi.get("flushSeconds")))),
        "alertPct": int(max(0.0, _f(rodi.get("alertPct")))),
        "externalVolumeL": round(max(0.0, _f(rodi.get("externalVolumeL"))), 1),
        "calibratedAt": str(rodi.get("calibratedAt") or ""),
        "litresProcessed": round(processed, 1),
        # When the odometer started counting — empty on installs that inherited
        # litres from before the stamp existed (no date beats a false one).
        "meteredSince": str(rodi.get("meteredSince") or ""),
        "filters": filters,
        "filterDue": any(f["due"] for f in filters),
        "draw": None,
        "calibration": None,
    }
    draw = rodi.get("draw") if isinstance(rodi.get("draw"), dict) else {}
    if draw.get("active"):
        target = max(0.0, _f(draw.get("litres")))
        started = _parse_iso(draw.get("startedAt"))
        ends = _parse_iso(draw.get("endsAt"))
        # Production time only: the auto-flush runs the clock but makes no
        # water — inside the flush window litresDone honestly reads 0.
        flush_s = max(0.0, _f(rodi.get("flushSeconds")))
        elapsed_s = max(0.0, (now - started).total_seconds()) if started else 0.0
        elapsed_h = max(0.0, elapsed_s - flush_s) / 3600.0
        # Open-ended fill (target 0): no percent, no promise — litresDone only
        # when a rate makes it honest; endsAt is the fill-cap backstop.
        done = rate * elapsed_h if rate > 0 else None
        if done is not None and target > 0:
            done = min(target, done)
        out["draw"] = {
            "litres": round(target, 1),
            "openEnded": target <= 0,
            "destination": str(draw.get("destination") or "store"),
            "litresDone": round(done, 1) if done is not None else None,
            "percent": round(min(100.0, done / target * 100.0), 0)
            if target > 0 and done is not None else None,
            "minutesLeft": round(max(0.0, (ends - now).total_seconds() / 60.0), 0)
            if ends else None,
        }
    cal = rodi.get("calibration") if isinstance(rodi.get("calibration"), dict) else {}
    if cal.get("active"):
        started = _parse_iso(cal.get("startedAt"))
        stopped = _parse_iso(cal.get("stoppedAt"))
        # Stopped freezes the clock: the litres are read from THAT window,
        # not from however long the keeper takes to type them in.
        end = stopped or now
        elapsed = max(0.0, (end - started).total_seconds()) if started else 0.0
        cal_flush = max(0.0, _f(rodi.get("flushSeconds")))
        out["calibration"] = {
            "startedAt": str(cal.get("startedAt") or ""),
            "stopped": stopped is not None,
            "elapsedMin": round(elapsed / 60.0, 1),
            "elapsedSeconds": int(elapsed),
            # The part of the run that made water — flush already out, so the
            # panel shows, never computes.
            "productionSeconds": int(max(0.0, elapsed - cal_flush)),
        }
    return out


def draw_alert(cfg: Any) -> dict[str, Any] | None:
    """When (and about what) the near-full heads-up should fire for the active
    RODI run — rate-projected, so it is only ever offered when a rate makes it
    honest. None = nothing to arm (alerts off, no run, no rate, no container
    volume to measure against, already fired, or a timed draw that ends before
    the threshold). Returns {"at": datetime, "pct": int, "message": str}."""
    cfg = cfg if isinstance(cfg, dict) else {}
    rodi = _rodi_cfg(cfg)
    pct = _f(rodi.get("alertPct"))
    if pct <= 0:
        return None
    draw = rodi.get("draw") if isinstance(rodi.get("draw"), dict) else {}
    if not draw.get("active") or draw.get("alertedAt"):
        return None
    rate = _f(rodi.get("rateLph"))
    if rate <= 0:
        return None
    started = _parse_iso(draw.get("startedAt"))
    if started is None:
        return None
    dest = str(draw.get("destination") or "store")
    if dest in ("store", "mix"):
        vessels = cfg.get("vessels") if isinstance(cfg.get("vessels"), dict) else {}
        vessel = vessels.get("rodi" if dest == "store" else "mix")
        vessel = vessel if isinstance(vessel, dict) else {}
        vol = _f(vessel.get("volumeLitres"))
        if vol <= 0:
            return None
        # Anchors move at finish, so the current anchor IS the start level.
        level = max(0.0, _f(vessel.get("estimatedLitres")))
        remaining_to_threshold = vol * pct / 100.0 - level
        name = "RODI store" if dest == "store" else "mix vessel"
    else:
        ext_vol = _f(rodi.get("externalVolumeL"))
        if ext_vol <= 0:
            return None
        remaining_to_threshold = ext_vol * pct / 100.0
        name = "T-off container"
    # The flush produces nothing, so the projection starts after it.
    flush_s = max(0.0, _f(rodi.get("flushSeconds")))
    at = (started + timedelta(seconds=flush_s)
          + timedelta(hours=max(0.0, remaining_to_threshold) / rate))
    target = _f(draw.get("litres"))
    ends = _parse_iso(draw.get("endsAt"))
    # A TIMED draw that stops before the threshold never gets there — the
    # finish check covers the boundary case honestly.
    if target > 0 and ends is not None and at >= ends:
        return None
    return {
        "at": at, "pct": int(pct),
        "message": (f"The {name} is passing {pct:g}% full — the RODI run is "
                    "still going; stop it if that's enough water."),
    }


def draw_finish_alert(cfg: Any, dest: str, done_litres: float) -> str | None:
    """The boundary case at the end of a run: it finished AT or ABOVE the
    threshold without the mid-run alert firing. Returns the message, or None."""
    rodi = _rodi_cfg(cfg)
    pct = _f(rodi.get("alertPct"))
    if pct <= 0:
        return None
    if dest in ("store", "mix"):
        vessels = cfg.get("vessels") if isinstance(cfg.get("vessels"), dict) else {}
        vessel = vessels.get("rodi" if dest == "store" else "mix")
        vessel = vessel if isinstance(vessel, dict) else {}
        vol = _f(vessel.get("volumeLitres"))
        level = max(0.0, _f(vessel.get("estimatedLitres")))   # post-credit level
        if vol <= 0 or level < vol * pct / 100.0:
            return None
        name = "RODI store" if dest == "store" else "mix vessel"
        return (f"The {name} finished its fill at about "
                f"{min(100.0, level / vol * 100.0):.0f}% full.")
    ext_vol = _f(rodi.get("externalVolumeL"))
    if ext_vol <= 0 or done_litres < ext_vol * pct / 100.0:
        return None
    return (f"The T-off container took about {done_litres:g} L — around "
            f"{min(100.0, done_litres / ext_vol * 100.0):.0f}% of its "
            f"{ext_vol:g} L.")


def calibration_rate(litres: Any, elapsed_seconds: Any, flush_seconds: Any = 0) -> float:
    """L/h from a timed run, with the unit's auto-flush discounted — those
    seconds ran the clock but produced no water, and dividing by them would
    understate the true rate on every unit that flushes. 0 = not computable
    (nothing measured, or under a minute of PRODUCTION once the flush is
    subtracted) — callers refuse, never guess. Two decimals: at the trickle
    rates small RODI units run, a whole-decimal round moves a long fill's
    ETA by many minutes."""
    lit = _f(litres)
    secs = _f(elapsed_seconds) - max(0.0, _f(flush_seconds))
    if lit <= 0 or secs < 60.0:
        return 0.0
    return round(lit / (secs / 3600.0), 2)


# ---------------------------------------------------------------- guards

def mix_guard_reasons(cfg: Any) -> list[str]:
    """Why a MIX RUN must not start. The litres are whatever the vessel holds
    (doc §15) — so the real question is whether it holds plain RODI water.
    Reason strings only — the orchestrator and panel decide presentation."""
    cfg = cfg if isinstance(cfg, dict) else {}
    reasons: list[str] = []
    if not cfg.get("enabled"):
        reasons.append("Mixing station is not enabled")
    batch = cfg.get("batch") if isinstance(cfg.get("batch"), dict) else {}
    if str(batch.get("state") or "idle") not in ("idle",):
        reasons.append("A mix run is already going — finish or discard it first")
    contents = mix_contents(cfg)
    litres = mix_vessel_litres(cfg)
    if contents == "salt":
        reasons.append("The vessel already holds mixed saltwater — "
                       "use or discard it before mixing fresh")
    elif contents != "rodi" or litres <= 0:
        reasons.append("The vessel holds no RODI water yet — "
                       "transfer or fill some in first")
    rodi = _rodi_cfg(cfg)
    draw = rodi.get("draw") if isinstance(rodi.get("draw"), dict) else {}
    if draw.get("active") and str(draw.get("destination") or "") == "mix":
        reasons.append("The vessel is still filling — let the RODI run finish first")
    salt_cfg = cfg.get("salt") if isinstance(cfg.get("salt"), dict) else {}
    if _f(salt_cfg.get("targetPpt"), REFERENCE_PPT) <= 0:
        reasons.append("Target salinity must be set")
    return reasons


def transfer_guard_reasons(cfg: Any, litres: Any) -> list[str]:
    """Why a transfer (store → mix vessel, gravity + the keeper's ball valve)
    must not be logged. The smart part of doc §15: never onto standing
    saltwater — EXCEPT while 'salting', where adding RODI is exactly how a
    too-salty batch gets diluted."""
    cfg = cfg if isinstance(cfg, dict) else {}
    reasons: list[str] = []
    if not cfg.get("enabled"):
        reasons.append("Mixing station is not enabled")
    if str(cfg.get("layout") or "dual") != "dual":
        reasons.append("Single-vessel layout has no store to transfer from")
    lit = _f(litres)
    if lit <= 0:
        reasons.append("Transfer must be more than 0 litres")
    state = str((cfg.get("batch") or {}).get("state") or "idle")
    if mix_contents(cfg) == "salt" and state != "salting":
        reasons.append("The vessel still holds mixed saltwater — "
                       "use or discard it before transferring fresh RODI in")
    vessels = cfg.get("vessels") if isinstance(cfg.get("vessels"), dict) else {}
    mix_v = vessels.get("mix") if isinstance(vessels.get("mix"), dict) else {}
    vol = _f(mix_v.get("volumeLitres"))
    if vol > 0 and lit > 0:
        free = max(0.0, vol - mix_vessel_litres(cfg))
        if lit > free + 0.05:
            reasons.append(f"That would overflow the vessel — "
                           f"about {free:g} L of {vol:g} L free")
    return reasons


# ---------------------------------------------------------------- AWC guard

def awc_guard_reason(cfg: Any, litres: Any, now: datetime) -> dict[str, Any] | None:
    """The Trust Moat check (doc §9): can this station vouch for the water an
    automatic change is about to put in the tank? ``None`` means yes — a
    tested, in-date salt batch with enough litres. Anything else returns
    ``{"mode": "warn"|"block", "message": ...}`` and the AWC orchestrator
    decides whether that warns or refuses. ``integrations.awcGuard`` "off"
    always returns None — the keeper unhooked the two features."""
    cfg = cfg if isinstance(cfg, dict) else {}
    if not cfg.get("enabled"):
        return None
    mode = str((cfg.get("integrations") or {}).get("awcGuard") or "warn")
    if mode not in ("warn", "block"):
        return None
    lit = _f(litres)
    if lit <= 0:
        return None
    state = batch_state(cfg.get("batch"), cfg, now)
    if state["status"] not in ("ready", "storing"):
        message = "the mixing station has no ready saltwater batch"
    elif state["retestDue"]:
        message = "the stored batch is past its retest window — test it before it touches the tank"
    elif state["remainingLitres"] + 0.05 < lit:
        message = (f"only {state['remainingLitres']:g} L of tested saltwater on hand "
                   f"for a {lit:g} L change")
    else:
        return None
    return {"mode": mode, "message": message}


# ---------------------------------------------------------------- summary

def summary(cfg: Any, now: datetime) -> dict[str, Any]:
    """The single blob the panel renders: batch state + clocks, vessel levels,
    the dose guide for the configured batch size, and the brand catalogue."""
    cfg = cfg if isinstance(cfg, dict) else {}
    salt_cfg = cfg.get("salt") if isinstance(cfg.get("salt"), dict) else {}
    batch = cfg.get("batch") if isinstance(cfg.get("batch"), dict) else {}
    state = batch_state(batch, cfg, now)
    # Dose guide litres: the live run's, else what the vessel actually holds,
    # else the configured volume — the best honest figure available.
    litres = _f(batch.get("litres"))
    if litres <= 0:
        litres = mix_vessel_litres(cfg)
    if litres <= 0:
        litres = _f((cfg.get("vessels") or {}).get("mix", {}).get("volumeLitres"))
    return {
        "enabled": bool(cfg.get("enabled")),
        "layout": str(cfg.get("layout") or "dual"),
        "batch": state,
        "levels": vessel_levels(cfg),
        "dose": salt_dose(salt_cfg.get("brand"), litres,
                          salt_cfg.get("targetPpt"), salt_cfg.get("customGPerL")),
        "mixHours": mix_hours(salt_cfg.get("brand"), salt_cfg.get("mixHours")),
        "brand": brand_info(salt_cfg.get("brand")),
        "brands": [dict(b) for b in SALT_BRANDS],
        "targetPpt": _f(salt_cfg.get("targetPpt"), REFERENCE_PPT),
        # The keeper's display unit and the ready-converted target — the panel
        # shows SG without ever owning the conversion constant.
        "salinityUnit": str(salt_cfg.get("unit") or "ppt"),
        "targetSg": sg_from_ppt(_f(salt_cfg.get("targetPpt"), REFERENCE_PPT)),
        "rodi": rodi_status(cfg, now),
    }
