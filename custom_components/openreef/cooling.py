"""Cooling headroom — the psychrometrics of a fan blowing room air over a
warm reef tank (docs/cooling-headroom-brainstorm.md §1).

A tank fan is not an HVAC evaporative cooler: it evaporates water off a
~26 °C surface, so what limits it is the gap between the water temperature
and the room's DEW POINT (equivalently the vapour-pressure deficit between
the water surface and the air), not room humidity and not room wet-bulb.
When the room's dew point reaches the water temperature nothing evaporates,
and if the room air is also warmer than the water the fan heats the tank.

Pure functions only — no Home Assistant imports — so the tests can pin the
published figures exactly. The backend owns every number; the panel renders.
"""

from __future__ import annotations

import math
from typing import Any

# Magnus formula, Alduchov & Eskridge (1996) coefficients (over water).
MAGNUS_A = 17.625
MAGNUS_B = 243.04

# Index reference: a 28 °C / 40 % room over a 26 °C tank — a textbook "good
# fan day" — scores 1.0. Anything wetter/warmer scores below it.
REFERENCE_VPD_KPA = 1.85

# Band edges on the index (fraction of the reference VPD). Tunable per config.
DEFAULT_BANDS = {"good": 0.70, "thin": 0.40, "weak": 0.15}
BAND_ORDER = ("good", "thin", "weak", "dead", "reversed")
# Bands where the fans are no longer doing their job — the warning tier.
WARN_BANDS = ("weak", "dead", "reversed")

# Plausibility clamps: outside these the sensor is not measuring a room.
ROOM_TEMP_MIN_C = -10.0
ROOM_TEMP_MAX_C = 50.0
WATER_TEMP_MIN_C = 10.0
WATER_TEMP_MAX_C = 40.0

BAND_COPY = {
    "good": ("Fans have full headroom", "ok"),
    "thin": ("Fan headroom thinning", "ok"),
    "weak": ("Fans working at a fraction", "warning"),
    "dead": ("Evaporative cooling has stopped", "warning"),
    "reversed": ("Room air is condensing on the tank — the fan is heating it", "critical"),
}


def saturation_vapour_pressure_kpa(temp_c: float) -> float:
    """Saturation vapour pressure over water, kPa (Magnus)."""
    return 0.61094 * math.exp(MAGNUS_A * temp_c / (temp_c + MAGNUS_B))


def dew_point_c(temp_c: float, rh_pct: float) -> float:
    """Dew point, °C, from dry-bulb °C and relative humidity %."""
    rh = min(100.0, max(1.0, float(rh_pct)))
    gamma = math.log(rh / 100.0) + MAGNUS_A * temp_c / (MAGNUS_B + temp_c)
    return MAGNUS_B * gamma / (MAGNUS_A - gamma)


def wet_bulb_c(temp_c: float, rh_pct: float) -> float:
    """Wet-bulb °C, Stull (2011) empirical fit — valid 5–99 % RH, −20–50 °C,
    MAE < 0.3 °C. Informational only: the water surface, not the air, is what
    the fan cools, so the dew-point margin is the number that decides."""
    rh = min(99.0, max(5.0, float(rh_pct)))
    t = float(temp_c)
    return (
        t * math.atan(0.151977 * math.sqrt(rh + 8.313659))
        + math.atan(t + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh)
        - 4.686035
    )


def _bands(bands: dict[str, Any] | None) -> dict[str, float]:
    out = dict(DEFAULT_BANDS)
    if isinstance(bands, dict):
        for key in DEFAULT_BANDS:
            try:
                out[key] = float(bands.get(key, out[key]))
            except (TypeError, ValueError):
                pass
    # Keep the edges ordered whatever the config says: good > thin > weak > 0.
    out["weak"] = min(max(out["weak"], 0.01), 0.98)
    out["thin"] = min(max(out["thin"], out["weak"] + 0.01), 0.99)
    out["good"] = min(max(out["good"], out["thin"] + 0.01), 1.0)
    return out


def band_for(index: float, vpd_kpa: float, room_c: float, water_c: float,
             bands: dict[str, Any] | None = None) -> str:
    edges = _bands(bands)
    if vpd_kpa <= 0:
        return "reversed" if room_c > water_c else "dead"
    if index < edges["weak"]:
        return "dead"
    if index < edges["thin"]:
        return "weak"
    if index < edges["good"]:
        return "thin"
    return "good"


def evaluate(water_c: float, room_c: float, rh_pct: float,
             reference_vpd_kpa: float = REFERENCE_VPD_KPA,
             bands: dict[str, Any] | None = None) -> dict[str, Any]:
    """The whole story for one reading: dew point, margin, VPD, index, band,
    and which way the fan is actually pushing heat."""
    water = float(water_c)
    room = float(room_c)
    rh = min(100.0, max(1.0, float(rh_pct)))
    try:
        ref = float(reference_vpd_kpa)
    except (TypeError, ValueError):
        ref = REFERENCE_VPD_KPA
    if not ref > 0:
        ref = REFERENCE_VPD_KPA
    dew = dew_point_c(room, rh)
    vpd = saturation_vapour_pressure_kpa(water) - rh / 100.0 * saturation_vapour_pressure_kpa(room)
    index = max(0.0, min(vpd / ref, 1.5))  # >1 is allowed (drier than the reference day)
    band = band_for(index, vpd, room, water, bands)
    if vpd <= 0:
        net = "heating" if room > water else "none"
    elif room > water and band in ("weak", "dead"):
        net = "marginal"
    else:
        net = "cooling"
    title, status = BAND_COPY[band]
    return {
        "waterC": round(water, 2),
        "roomC": round(room, 2),
        "rh": round(rh, 1),
        "dewC": round(dew, 2),
        "wetBulbC": round(wet_bulb_c(room, rh), 2),
        "marginC": round(water - dew, 2),
        "vpdKpa": round(vpd, 3),
        "index": round(index, 3),
        "band": band,
        "status": status,
        "title": title,
        "netFan": net,
    }


def fan_needed(room_c: float | None, water_c: float | None, target_c: float,
               gate_c: float = 1.0) -> bool:
    """Is cooling on the table right now? The rig's fan hangs off the guard's
    cool socket (not in HA), so the gate is inferred: the room is at or above
    the target minus the gate, or the tank is already over target. A humid
    but cool day stays silent — that is the whole point of the feature."""
    try:
        target = float(target_c)
    except (TypeError, ValueError):
        return False
    if room_c is not None and float(room_c) >= target - float(gate_c):
        return True
    if water_c is not None and float(water_c) > target + 0.2:
        return True
    return False


def what_if_table(water_c: float, reference_vpd_kpa: float = REFERENCE_VPD_KPA,
                  bands: dict[str, Any] | None = None,
                  rooms: tuple[float, ...] = (22.0, 26.0, 30.0),
                  humidities: tuple[float, ...] = (50.0, 70.0, 80.0)) -> dict[str, Any]:
    """The reference grid for today's tank: what the fans are worth at a few
    room temp / humidity combinations. Rendered as a table in Settings so the
    keeper builds the intuition without a calculator."""
    rows = []
    for room in rooms:
        cells = []
        for rh in humidities:
            r = evaluate(water_c, room, rh, reference_vpd_kpa, bands)
            cells.append({"rh": rh, "index": r["index"], "band": r["band"], "dewC": r["dewC"]})
        rows.append({"roomC": room, "cells": cells})
    return {"humidities": list(humidities), "rows": rows}


def warning_copy(result: dict[str, Any], target_c: float | None) -> tuple[str, str]:
    """Title + message for the once-per-cooldown warning. Plain voice: this
    is a warning, not a calm state."""
    band = result.get("band")
    room = result.get("roomC")
    rh = result.get("rh")
    dew = result.get("dewC")
    water = result.get("waterC")
    where = f"Room {room:.1f} °C at {rh:.0f} % — dew point {dew:.1f} °C against a {water:.1f} °C tank."
    if band == "reversed":
        return (
            "Evaporative cooling has reversed",
            f"{where} The room's dew point is above the water: nothing evaporates and the fan is "
            "warming the tank. Dehumidify or vent the room, or plan for a chiller.",
        )
    if band == "dead":
        return (
            "Evaporative cooling has stopped",
            f"{where} The fans are just moving warm air. Dehumidify or vent the room before the "
            "tank climbs.",
        )
    pct = round(float(result.get("index", 0)) * 100)
    return (
        "Fan cooling is down to a fraction",
        f"{where} The fans are working at about {pct} % of a dry day. Dehumidifying now buys "
        "headroom before the afternoon.",
    )


# --------------------------------------------------------------------------- #
# Layer 2 — the 24 h projection, the day kind, vent advice, the dehumidifier plan
# --------------------------------------------------------------------------- #

from datetime import datetime, timedelta, timezone  # noqa: E402

# Indoor-vs-outdoor offsets when nothing has been measured yet: a tank room
# runs warmer and wetter than the street. Replaced by the live difference
# (smoothed) as soon as both sides read.
DEFAULT_OFFSET_T_C = 2.0
DEFAULT_OFFSET_DEW_C = 3.0
OFFSET_T_RANGE = (-3.0, 12.0)
OFFSET_DEW_RANGE = (-3.0, 12.0)
OFFSET_ALPHA = 0.3                  # EMA weight of the newest live difference

# "Unrescuable": the fans are already gone AND the room is far over target —
# a dehumidifier's own heat would land in the peak. Chiller day, not a job.
UNRESCUABLE_OVER_TARGET_C = 4.0
UNRESCUABLE_INDEX = 0.10

VENT_DEW_GAP_C = 2.0                # vent only while outdoor dew ≤ indoor dew − this
VENT_TEMP_SLACK_C = 1.0             # …and outdoor air is no warmer than room + this

DAY_KINDS = ("quiet", "dry-heat", "humid-heat", "chiller")
DAY_KIND_COPY = {
    "quiet": "Quiet day — the fans aren't needed",
    "dry-heat": "Dry-heat day — the fans will cope",
    "humid-heat": "Humid-heat day — dehumidify ahead of the afternoon",
    "chiller": "Chiller day — neither fans nor dehumidifier will hold it",
}


def rh_from_dew(temp_c: float, dew_c: float) -> float:
    """Relative humidity % from dry-bulb and dew point (clamped 1–100)."""
    rh = 100.0 * saturation_vapour_pressure_kpa(dew_c) / saturation_vapour_pressure_kpa(temp_c)
    return min(100.0, max(1.0, rh))


def _parse_when(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _to_c(value: Any, unit: str) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return (v - 32.0) * 5.0 / 9.0 if "F" in str(unit).upper() else v


def parse_forecast(items: Any, temp_unit: str = "°C") -> list[dict[str, Any]]:
    """HA hourly forecast entries → [{at, outC, outRh, outDewC}], tolerant of
    fields an integration omits: a missing dew point is computed from the
    humidity, a missing humidity from the dew point; an hour with neither, or
    no temperature, is dropped. Sorted by time."""
    out: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        at = _parse_when(item.get("datetime"))
        temp = _to_c(item.get("temperature"), temp_unit)
        if at is None or temp is None:
            continue
        rh = None
        try:
            if item.get("humidity") is not None:
                rh = float(item["humidity"])
        except (TypeError, ValueError):
            rh = None
        dew = _to_c(item.get("dew_point"), temp_unit) if item.get("dew_point") is not None else None
        if dew is None and rh is None:
            continue
        if dew is None:
            dew = dew_point_c(temp, rh)
        if rh is None:
            rh = rh_from_dew(temp, dew)
        out.append({"at": at, "outC": round(temp, 2), "outRh": round(min(100.0, max(1.0, rh)), 1),
                    "outDewC": round(dew, 2)})
    out.sort(key=lambda h: h["at"])
    return out


def smooth_offsets(previous: dict[str, Any] | None, room_c: float | None, dew_c: float | None,
                   out_c: float | None, out_dew_c: float | None) -> dict[str, float]:
    """Indoor-minus-outdoor offsets, exponentially smoothed across ticks.
    Falls back to the previous (or default) pair when either side is missing."""
    prev_t = DEFAULT_OFFSET_T_C
    prev_dew = DEFAULT_OFFSET_DEW_C
    if isinstance(previous, dict):
        try:
            prev_t = float(previous.get("offsetT", prev_t))
            prev_dew = float(previous.get("offsetDew", prev_dew))
        except (TypeError, ValueError):
            pass
    if room_c is not None and out_c is not None:
        prev_t = (1 - OFFSET_ALPHA) * prev_t + OFFSET_ALPHA * (float(room_c) - float(out_c))
    if dew_c is not None and out_dew_c is not None:
        prev_dew = (1 - OFFSET_ALPHA) * prev_dew + OFFSET_ALPHA * (float(dew_c) - float(out_dew_c))
    prev_t = min(OFFSET_T_RANGE[1], max(OFFSET_T_RANGE[0], prev_t))
    prev_dew = min(OFFSET_DEW_RANGE[1], max(OFFSET_DEW_RANGE[0], prev_dew))
    return {"offsetT": round(prev_t, 2), "offsetDew": round(prev_dew, 2)}


def project(hours: list[dict[str, Any]], now: datetime, lookahead_h: float, water_c: float,
            target_c: float, offsets: dict[str, float], gate_c: float,
            reference_vpd_kpa: float = REFERENCE_VPD_KPA,
            bands: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Each forecast hour, indoors: room = outdoor + offsetT, dew = outdoor dew
    + offsetDew, then the same evaluate() the live reading gets. Returns None
    when there is nothing inside the window."""
    if not hours:
        return None
    start = now - timedelta(hours=1)
    end = now + timedelta(hours=float(lookahead_h))
    off_t = float(offsets.get("offsetT", DEFAULT_OFFSET_T_C))
    off_dew = float(offsets.get("offsetDew", DEFAULT_OFFSET_DEW_C))
    rows: list[dict[str, Any]] = []
    for h in hours:
        at = h["at"]
        if at < start or at > end:
            continue
        room = float(h["outC"]) + off_t
        dew = min(float(h["outDewC"]) + off_dew, room - 0.1)   # air cannot be past saturation
        rh = rh_from_dew(room, dew)
        r = evaluate(water_c, room, rh, reference_vpd_kpa, bands)
        needed = fan_needed(room, None, target_c, gate_c)
        affected = needed and r["band"] in WARN_BANDS
        unrescuable = affected and room >= target_c + UNRESCUABLE_OVER_TARGET_C and r["index"] < UNRESCUABLE_INDEX
        rows.append({
            "at": at.isoformat(), "outC": h["outC"], "outDewC": h["outDewC"],
            "roomC": round(room, 1), "rh": round(rh), "dewC": round(dew, 1),
            "index": r["index"], "band": r["band"], "fanNeeded": needed,
            "affected": affected, "unrescuable": unrescuable,
        })
    if not rows:
        return None
    needed_rows = [r for r in rows if r["fanNeeded"]]
    affected_rows = [r for r in rows if r["affected"]]
    worst = min(needed_rows, key=lambda r: r["index"]) if needed_rows else None
    if any(r["unrescuable"] for r in rows):
        kind = "chiller"
    elif affected_rows:
        kind = "humid-heat"
    elif needed_rows:
        kind = "dry-heat"
    else:
        kind = "quiet"
    coolest = min(rows, key=lambda r: r["outC"])
    purge = [r["at"] for r in rows if r["outC"] <= coolest["outC"] + 2.0]
    return {
        "hours": rows,
        "worst": {"at": worst["at"], "index": worst["index"], "band": worst["band"]} if worst else None,
        "firstAffectedAt": affected_rows[0]["at"] if affected_rows else None,
        "lastAffectedAt": affected_rows[-1]["at"] if affected_rows else None,
        "affectedHours": len(affected_rows),
        "neededHours": len(needed_rows),
        "dayKind": kind,
        "dayKindLabel": DAY_KIND_COPY[kind],
        "purgeWindow": {"from": purge[0], "to": purge[-1], "outC": coolest["outC"]} if purge else None,
        "offsets": {"offsetT": round(off_t, 2), "offsetDew": round(off_dew, 2)},
    }


def vent_advice(room_c: float | None, dew_c: float | None, out_c: float | None,
                out_dew_c: float | None, gap_c: float = VENT_DEW_GAP_C) -> dict[str, Any]:
    """Right now: is the air outside drier (and no warmer) than the air inside?
    If so, the intake fan beats the dehumidifier for free."""
    if None in (room_c, dew_c, out_c, out_dew_c):
        return {"advised": False, "known": False, "reason": "no outdoor reading"}
    gap = float(dew_c) - float(out_dew_c)
    try:
        need = float(gap_c)
    except (TypeError, ValueError):
        need = VENT_DEW_GAP_C
    drier = gap >= need
    cool_enough = float(out_c) <= float(room_c) + VENT_TEMP_SLACK_C
    advised = drier and cool_enough
    if advised:
        reason = (f"outdoor dew point {out_dew_c:.1f} °C is {gap:.1f} °C below indoors — "
                  "vent (intake fan + window) instead of dehumidifying")
    elif not drier:
        reason = f"outdoor air is as wet as indoors (dew point {out_dew_c:.1f} °C) — keep the windows shut"
    else:
        reason = f"outdoor air is drier but warmer ({out_c:.1f} °C) — vent later, when it cools"
    return {"advised": advised, "known": True, "reason": reason,
            "outdoorC": round(float(out_c), 1), "outdoorDewC": round(float(out_dew_c), 1),
            "gapC": round(gap, 1)}


def _hhmm(iso: str | None) -> str:
    dt = _parse_when(iso)
    return dt.astimezone().strftime("%H:%M") if dt else "?"


def dehumidifier_plan(live: dict[str, Any] | None, live_needed: bool, projection: dict[str, Any] | None,
                      now: datetime, lead_h: float, target_c: float,
                      vent_active: bool = False) -> dict[str, Any]:
    """Should the dehumidifier be running right now, and why. Stateless: the
    actuator layer adds the short-cycle timing and the manual-override hold.

    kinds: now (fans already down), ahead (inside the lead window of a
    projected hit), scheduled (a hit is coming, not yet time), unrescuable
    (chiller day — its heat would land in the peak), vented (the room is being
    vented with drier outdoor air — drying air you blow out of the window is
    waste), none."""
    plan = _dehumidifier_plan_raw(live, live_needed, projection, now, lead_h, target_c)
    if vent_active and plan["shouldRun"]:
        return {"shouldRun": False, "kind": "vented", "startAt": plan.get("startAt"), "until": plan.get("until"),
                "reason": "venting instead — outdoor air is drier than indoors, so the dehumidifier stays off"}
    return plan


def _dehumidifier_plan_raw(live: dict[str, Any] | None, live_needed: bool, projection: dict[str, Any] | None,
                           now: datetime, lead_h: float, target_c: float) -> dict[str, Any]:
    if live and live_needed and live.get("band") in WARN_BANDS:
        room = float(live.get("roomC", 0))
        if room >= target_c + UNRESCUABLE_OVER_TARGET_C and float(live.get("index", 0)) < UNRESCUABLE_INDEX:
            return {"shouldRun": False, "kind": "unrescuable", "startAt": None, "until": None,
                    "reason": (f"room {room:.1f} °C at {live.get('rh', 0):.0f} % — a dehumidifier cannot "
                               "rescue this afternoon; this is a chiller day")}
        pct = round(float(live.get("index", 0)) * 100)
        until = projection.get("lastAffectedAt") if projection else None
        return {"shouldRun": True, "kind": "now", "startAt": now.isoformat(), "until": until,
                "reason": f"the fans are down to {pct} % right now"}
    if projection and projection.get("firstAffectedAt"):
        first = _parse_when(projection["firstAffectedAt"])
        last = _parse_when(projection.get("lastAffectedAt")) or first
        start = first - timedelta(hours=float(lead_h))
        until = last + timedelta(hours=1)
        worst = projection.get("worst") or {}
        pct = round(float(worst.get("index", 0)) * 100)
        if start <= now <= until:
            return {"shouldRun": True, "kind": "ahead", "startAt": start.isoformat(), "until": until.isoformat(),
                    "reason": f"fan headroom drops to {pct} % from {_hhmm(projection['firstAffectedAt'])}"}
        if now < start:
            return {"shouldRun": False, "kind": "scheduled", "startAt": start.isoformat(), "until": until.isoformat(),
                    "reason": (f"start by {_hhmm(start.isoformat())} — headroom drops to {pct} % "
                               f"from {_hhmm(projection['firstAffectedAt'])}")}
    hours = projection.get("hours") if projection else None
    span = f"the next {len(hours)} h" if hours else "the forecast"
    return {"shouldRun": False, "kind": "none", "startAt": None, "until": None,
            "reason": f"no hour in {span} where the fans are needed and losing"}


# --------------------------------------------------------------------------- #
# Layer 3 — the intake fan: when venting is worth running, and the night purge
# --------------------------------------------------------------------------- #

VENT_RUN_KINDS = ("cool", "predry", "purge")


def in_purge_window(projection: dict[str, Any] | None, now: datetime) -> bool:
    window = projection.get("purgeWindow") if projection else None
    if not window:
        return False
    start = _parse_when(window.get("from"))
    end = _parse_when(window.get("to"))
    if start is None or end is None:
        return False
    return start <= now <= end + timedelta(hours=1)


def vent_decision(advice: dict[str, Any], fan_needed: bool, projection: dict[str, Any] | None,
                  now: datetime, night_purge: bool, window_open: bool | None) -> dict[str, Any]:
    """Should the intake fan be pulling outdoor air in right now, and why.

    Only ever while the outdoor air is drier and no warmer (``advice``), and
    only for a reason: cool (the room needs cooling now), predry (a losing
    hour is coming — dry the room for free first), purge (night purge: the
    coolest outdoor hours ahead of a day that needs the fans). A bound window
    sensor reading closed blocks it (kind ``blocked``) — the panel and the
    notification say "open the window" instead of running a fan against glass.
    Winter takes care of itself: a cool room with nothing coming has no reason."""
    if not advice.get("known"):
        return {"shouldRun": False, "kind": "none", "wants": None, "reason": advice.get("reason", "no outdoor reading")}
    kind = None
    reason = ""
    if advice.get("advised"):
        if fan_needed:
            kind = "cool"
            reason = (f"the room needs cooling and outdoor air is drier ({advice['outdoorC']:.1f} °C, "
                      f"dew point {advice['outdoorDewC']:.1f} °C, {advice['gapC']:.1f} °C below indoors)")
        elif projection and projection.get("firstAffectedAt"):
            worst = projection.get("worst") or {}
            pct = round(float(worst.get("index", 0)) * 100)
            kind = "predry"
            reason = (f"pre-drying the room with outdoor air (dew point {advice['outdoorDewC']:.1f} °C) — "
                      f"headroom drops to {pct} % from {_hhmm(projection['firstAffectedAt'])}")
        elif night_purge and projection and projection.get("dayKind") != "quiet" and in_purge_window(projection, now):
            window = projection.get("purgeWindow") or {}
            kind = "purge"
            reason = (f"night purge — the coolest outdoor air ({advice['outdoorC']:.1f} °C) until "
                      f"{_hhmm(window.get('to'))}, ahead of a {projection.get('dayKind')} day")
    if kind is None:
        return {"shouldRun": False, "kind": "none", "wants": None,
                "reason": advice.get("reason", "") if not advice.get("advised")
                else "outdoor air is drier, but the room doesn't need it right now"}
    if window_open is False:
        return {"shouldRun": False, "kind": "blocked", "wants": kind,
                "reason": f"{reason} — but the window is closed"}
    return {"shouldRun": True, "kind": kind, "wants": kind, "reason": reason}
