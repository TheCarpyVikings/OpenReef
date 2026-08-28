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

from datetime import datetime
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
MIX_BATCH_TYPES = ("salt", "rodi")
MIX_LAYOUTS = ("dual", "single")


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
    35 ppt figure. Approximate by nature — the refractometer is the truth."""
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

def stage_sequence(layout: Any, batch_type: Any, heat_enabled: Any) -> tuple[str, ...]:
    """The stages THIS batch walks, in order — the panel's progress rail.
    Transfer exists only on a dual layout mixing salt; Heat only when enabled
    and salting; rodi batches go straight from filling to ready."""
    stages = ["filling"]
    salt = str(batch_type or "salt") != "rodi"
    if salt and str(layout or "dual") == "dual":
        stages.append("transferring")
    if salt and bool(heat_enabled):
        stages.append("heating")
    if salt:
        stages.append("salting")
    stages.extend(["ready", "storing"])
    return tuple(stages)


def batch_state(batch: Any, cfg: Any, now: datetime) -> dict[str, Any]:
    """Where the batch sits, evaluated from its stamps — never mutated here.

    Adds the read-side clocks: the salting mix timer (percent / testUnlocked,
    hatchery-shaped) and the storing age (retestDue past storage.retestAfterDays,
    or past the brand's useWithinH when that is tighter)."""
    batch = batch if isinstance(batch, dict) else {}
    cfg = cfg if isinstance(cfg, dict) else {}
    status = str(batch.get("state") or "idle")
    btype = str(batch.get("type") or "salt")
    litres = _f(batch.get("litres"))
    used = _f(batch.get("usedLitres"))
    remaining = max(0.0, litres - used)
    salt_cfg = cfg.get("salt") if isinstance(cfg.get("salt"), dict) else {}
    out: dict[str, Any] = {
        "status": status, "type": btype,
        "litres": round(litres, 1), "remainingLitres": round(remaining, 1),
        "stages": list(stage_sequence(cfg.get("layout"), btype,
                                      (cfg.get("heat") or {}).get("enabled"))),
        "mix": {"percent": None, "hoursLeft": None, "testUnlocked": False},
        "ageDays": None, "retestDue": False,
        # Storing circulation: a burst is running while circulateUntil is ahead
        # of now — the diagram spins the impellers off this, never off a guess.
        "circulating": False,
        "loggedPpt": batch.get("loggedPpt"),
    }
    if status in ("ready", "storing"):
        until = _parse_iso(batch.get("circulateUntil"))
        out["circulating"] = until is not None and until > now
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
            if btype == "salt":
                due = retest_days > 0 and age_d >= retest_days
                if use_within_h > 0:
                    due = due or age_d * 24.0 >= use_within_h
                out["retestDue"] = due
    return out


# ---------------------------------------------------------------- level ledger

def vessel_levels(cfg: Any) -> dict[str, Any]:
    """Estimated levels: stored anchors moved by confirmed events (fill done,
    transfer done, batch used). RODI level is the dual layout's store; on a
    single layout the one vessel IS the batch, so only the mix side reports.
    estimated=True until real level entities take over (sensor-first, later)."""
    cfg = cfg if isinstance(cfg, dict) else {}
    vessels = cfg.get("vessels") if isinstance(cfg.get("vessels"), dict) else {}
    batch = cfg.get("batch") if isinstance(cfg.get("batch"), dict) else {}
    dual = str(cfg.get("layout") or "dual") == "dual"
    rodi = vessels.get("rodi") if isinstance(vessels.get("rodi"), dict) else {}
    mix = vessels.get("mix") if isinstance(vessels.get("mix"), dict) else {}
    rodi_vol = max(0.0, _f(rodi.get("volumeLitres")))
    mix_vol = max(0.0, _f(mix.get("volumeLitres")))
    mix_l = max(0.0, _f(batch.get("litres")) - _f(batch.get("usedLitres")))
    if str(batch.get("state") or "idle") == "idle":
        mix_l = 0.0
    out = {"mix": {"litres": round(mix_l, 1), "volumeLitres": mix_vol,
                   "percent": round(min(100.0, mix_l / mix_vol * 100.0), 0)
                   if mix_vol > 0 else None,
                   "estimated": True}}
    if dual:
        rodi_l = min(rodi_vol, max(0.0, _f(rodi.get("estimatedLitres")))) \
            if rodi_vol > 0 else max(0.0, _f(rodi.get("estimatedLitres")))
        out["rodi"] = {"litres": round(rodi_l, 1), "volumeLitres": rodi_vol,
                       "percent": round(min(100.0, rodi_l / rodi_vol * 100.0), 0)
                       if rodi_vol > 0 else None,
                       "estimated": True}
    return out


# ---------------------------------------------------------------- guards

def start_guard_reasons(cfg: Any, litres: Any, batch_type: Any) -> list[str]:
    """Why a batch must not start. Reason strings only — the orchestrator and
    panel decide presentation (the AWC start_guard_reasons contract)."""
    cfg = cfg if isinstance(cfg, dict) else {}
    reasons: list[str] = []
    if not cfg.get("enabled"):
        reasons.append("Mixing station is not enabled")
    batch = cfg.get("batch") if isinstance(cfg.get("batch"), dict) else {}
    if str(batch.get("state") or "idle") not in ("idle",):
        reasons.append("A batch is already in progress — finish or abort it first")
    btype = str(batch_type or "salt")
    if btype not in MIX_BATCH_TYPES:
        reasons.append(f"Unknown batch type '{btype}'")
    lit = _f(litres)
    if lit <= 0:
        reasons.append("Batch size must be more than 0 litres")
    vessels = cfg.get("vessels") if isinstance(cfg.get("vessels"), dict) else {}
    dual = str(cfg.get("layout") or "dual") == "dual"
    mix_vol = _f((vessels.get("mix") or {}).get("volumeLitres"))
    if mix_vol > 0 and lit > mix_vol:
        reasons.append(f"Batch of {lit:g} L exceeds the mixing vessel ({mix_vol:g} L)")
    if dual and btype == "salt":
        rodi_vol = _f((vessels.get("rodi") or {}).get("volumeLitres"))
        if rodi_vol > 0 and lit > rodi_vol:
            reasons.append(f"Batch of {lit:g} L exceeds the RODI vessel ({rodi_vol:g} L)")
    salt_cfg = cfg.get("salt") if isinstance(cfg.get("salt"), dict) else {}
    if btype == "salt" and _f(salt_cfg.get("targetPpt"), REFERENCE_PPT) <= 0:
        reasons.append("Target salinity must be set")
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
    if state["status"] not in ("ready", "storing") or state["type"] != "salt":
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
    litres = _f(batch.get("litres"))
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
    }
