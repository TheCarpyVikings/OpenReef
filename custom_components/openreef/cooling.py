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
               gate_c: float = 1.0, latched: bool = False) -> bool:
    """Is cooling on the table right now? The rig's fan hangs off the guard's
    cool socket (not in HA), so the gate is inferred: the room is at or above
    the target minus the gate, or the tank is already over target. A humid
    but cool day stays silent — that is the whole point of the feature.

    ``latched`` is the answer this returned last tick. Once true, the room has
    to fall FAN_GATE_HYST_C below the gate to turn it false again — otherwise a
    room sitting on the gate flips this, and every vent and dehumidifier
    decision downstream of it, every five minutes. The give is the room arm's
    alone: the tank arm already stands 0.2 °C clear of target and water moves
    far too slowly to chatter, and widening it would leave a tank parked on
    target — a well-controlled one — reading "needs cooling" forever."""
    try:
        target = float(target_c)
    except (TypeError, ValueError):
        return False
    give = FAN_GATE_HYST_C if latched else 0.0
    if room_c is not None and float(room_c) >= target - float(gate_c) - give:
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
# Layer 2 — current vent advice and the dehumidifier plan
# --------------------------------------------------------------------------- #

from datetime import datetime  # noqa: E402

# "Unrescuable": the fans are already gone AND the room is far over target —
# a dehumidifier's own heat could worsen the current conditions.
UNRESCUABLE_OVER_TARGET_C = 4.0
UNRESCUABLE_INDEX = 0.10

# "Losing": the fans are on, the tank is still over target and the band is
# under good — the honest signal that dehumidifying changes the outcome. A
# room that lives in the thin band all summer (Reece's, 43–57 % every hour of
# 2026-09-13) never trips WARN_BANDS, yet its fans are visibly not holding the
# water. Stop-side deadband only, per §13: the start is never made easier.
LOSING_HYST_C = 0.2
# Room humidity ceiling — a house rule (mould, electronics, salt creep), not a
# cooling rule; RH is the wrong cooling metric (§2) so it stays out of the
# index. Holds until RH falls this far under the ceiling.
CEILING_HYST_RH = 5.0

VENT_DEW_GAP_C = 2.0                # vent only while outdoor dew ≤ indoor dew − this
VENT_TEMP_SLACK_C = 1.0             # …and outdoor air is no warmer than room + this

# Deadbands. Every gate here is bang-bang against a live sensor, and the thing
# each gate switches on is the thing that erases its own reason: the intake fan
# pulls drier air in, the indoor dew point falls toward outdoor, the gap closes
# and the fan stops — then the room re-humidifies and it starts again. So a gate
# that has already fired holds until the signal has moved back past it by this
# much. Widening the *stop* threshold, never the start one: nothing below begins
# venting or cooling any sooner than it did before.
VENT_DEW_GAP_HYST_C = 0.5           # keep venting until the dew gap falls this far under dewGapC
VENT_TEMP_HYST_C = 0.5              # …and tolerate outdoor air this much warmer once running
FAN_GATE_HYST_C = 0.3               # room must drop this far below the gate to un-need the fans

# The second reason to vent (§13): sensible cooling. Venting helps a reef room by
# two independent paths and only the first was ever modelled — drying the air
# (raises the tank fans' evaporative headroom), and simply being cooler (a 24 °C
# room conducts less heat into a 26 °C tank than a 28 °C room does). Room
# temperature cancels out of the headroom index entirely, so the second path is
# invisible to `evaluate` — yet `fan_needed` is itself a room-temperature test.
VENT_COOL_GAP_C = 2.0               # free-cool while the room is at least this much hotter than outside
VENT_COOL_GAP_HYST_C = 0.5          # …and keep going until that closes to within this of the gap
VENT_DEW_NEUTRAL_HYST_C = 0.3       # free-cooling needs dew-neutral air; this much give once running
VENT_COOL_MIN_OUTDOOR_C = 10.0      # never free-cool on air colder than this (0 = no floor)
PURGE_WATER_FLOOR_C = 2.0           # stop the night purge once the TANK is this far below target

def rh_from_dew(temp_c: float, dew_c: float) -> float:
    """Relative humidity % from dry-bulb and dew point (clamped 1–100)."""
    rh = 100.0 * saturation_vapour_pressure_kpa(dew_c) / saturation_vapour_pressure_kpa(temp_c)
    return min(100.0, max(1.0, rh))


def _to_c(value: Any, unit: str) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return (v - 32.0) * 5.0 / 9.0 if "F" in str(unit).upper() else v


def vent_advice(room_c: float | None, dew_c: float | None, out_c: float | None,
                out_dew_c: float | None, gap_c: float = VENT_DEW_GAP_C,
                venting: bool = False, cool_vent: bool = True,
                cool_gap_c: float = VENT_COOL_GAP_C,
                cool_min_outdoor_c: float = VENT_COOL_MIN_OUTDOOR_C) -> dict[str, Any]:
    """Right now: is the air outside drier (and no warmer) than the air inside?
    If so, the intake fan beats the dehumidifier for free.

    ``venting`` means air is already moving — the fan plug is on, or a bound
    window reads open. That air is what drags the indoor dew point down toward
    outdoor, so the gap that justified venting narrows the moment venting works.
    While it is moving both gates relax (dew by VENT_DEW_GAP_HYST_C, temperature
    by VENT_TEMP_HYST_C) so the fan is not switched off by its own success."""
    if None in (room_c, dew_c, out_c, out_dew_c):
        return {"advised": False, "known": False, "reason": "no outdoor reading"}
    gap = float(dew_c) - float(out_dew_c)
    try:
        need = float(gap_c)
    except (TypeError, ValueError):
        need = VENT_DEW_GAP_C
    if venting:
        need -= VENT_DEW_GAP_HYST_C
    drier = gap >= need
    slack = VENT_TEMP_SLACK_C + (VENT_TEMP_HYST_C if venting else 0.0)
    cool_enough = float(out_c) <= float(room_c) + slack
    advised = drier and cool_enough
    if advised:
        reason = (f"outdoor dew point {out_dew_c:.1f} °C is {gap:.1f} °C below indoors — "
                  "vent (intake fan + window) instead of dehumidifying")
    elif not drier:
        # Always print the gap and the bar it missed. Without them a "close up"
        # in the activity log is undiagnosable: you cannot tell a room sitting
        # 0.1 °C under the threshold from one that is genuinely muggy.
        reason = (f"outdoor air is wetter than indoors (dew point {out_dew_c:.1f} °C) — keep the windows shut"
                  if gap <= 0 else
                  f"outdoor dew point {out_dew_c:.1f} °C is only {gap:.1f} °C below indoors, "
                  f"needs {need:.1f} — keep the windows shut")
    else:
        reason = (f"outdoor air is drier but warmer ({out_c:.1f} °C vs room {room_c:.1f} °C) — "
                  "vent later, when it cools")
    # --- the second route: sensible cooling, no drying claim ------------------
    # Dew-neutral and temperature-positive is an unambiguous win. We deliberately
    # do NOT weigh "cooler but wetter": converting the two paths to a common
    # currency needs the room's thermal coupling to the tank, in watts per °C of
    # room excess, which OpenReef does not know and cannot learn from what it
    # records. Refuse the trade rather than guess at it.
    cooler_by = float(room_c) - float(out_c)
    try:
        cool_need = float(cool_gap_c)
    except (TypeError, ValueError):
        cool_need = VENT_COOL_GAP_C
    try:
        floor_c = float(cool_min_outdoor_c)
    except (TypeError, ValueError):
        floor_c = VENT_COOL_MIN_OUTDOOR_C
    if venting:
        cool_need -= VENT_COOL_GAP_HYST_C
    cooler = cooler_by >= cool_need
    # Free-cooling is self-defeating the same way venting-to-dry is: cool air
    # cools the room, which closes the very gap that justified it.
    dew_neutral = gap >= (-VENT_DEW_NEUTRAL_HYST_C if venting else 0.0)
    # The floor is a SAFETY gate, not an efficiency one — a deadband here would
    # relax it in the hazardous direction, so it gets none.
    warm_enough = floor_c <= 0 or float(out_c) >= floor_c
    freecool = bool(cool_vent) and cooler and dew_neutral and warm_enough
    # Only explain a refusal when there was a real opportunity to refuse, so the
    # panel can say why obviously cooler air is being declined.
    freecool_reason = ""
    if bool(cool_vent) and cooler and not advised:
        if not dew_neutral:
            freecool_reason = (f"outdoor air is {cooler_by:.1f} °C cooler but wetter "
                               f"(dew point {out_dew_c:.1f} °C) — it would cost the fans "
                               "more than it saves")
        elif not warm_enough:
            freecool_reason = (f"outdoor air is {cooler_by:.1f} °C cooler but only {out_c:.1f} °C — "
                               "too cold to blow at the tank")
    return {"advised": advised, "known": True, "reason": reason,
            "outdoorC": round(float(out_c), 1), "outdoorDewC": round(float(out_dew_c), 1),
            "gapC": round(gap, 1), "hysteresis": bool(venting),
            "freecool": freecool, "coolerBy": round(cooler_by, 1),
            "freecoolReason": freecool_reason}


def dehumidifier_plan(live: dict[str, Any] | None, live_needed: bool, projection: dict[str, Any] | None,
                      now: datetime, lead_h: float, target_c: float,
                      vent_active: bool = False, losing_over_c: float = 0.0, max_rh: float = 0.0,
                      water_known: bool = False, latched: str | None = None) -> dict[str, Any]:
    """Should the dehumidifier be running right now, and why. Stateless: the
    actuator layer adds the short-cycle timing and the manual-override hold;
    ``latched`` is the kind this returned last tick, and only relaxes the
    stop side of the gate it names (losing / ceiling).

    Decisions use current fan performance, measured tank temperature and
    humidity. Legacy projection/lead arguments are ignored. Venting overrides
    a running plan so we do not dehumidify air being exchanged outdoors.
    """
    plan = _dehumidifier_plan_raw(live, live_needed, None, now, 0, target_c,
                                  losing_over_c, max_rh, water_known, latched)
    if vent_active and plan["shouldRun"]:
        return {"shouldRun": False, "kind": "vented", "startAt": plan.get("startAt"), "until": plan.get("until"),
                "reason": "venting instead — outdoor air is drier than indoors, so the dehumidifier stays off"}
    return plan


def _losing(live: dict[str, Any] | None, live_needed: bool, target_c: float, over_c: float,
            water_known: bool, latched: bool) -> dict[str, Any] | None:
    """The tank-outcome trigger (§14.2). The band gate stays strict even while
    latched: once the fans are back in good they are doing the job and the
    compressor's heat has no business in the room."""
    try:
        over = float(over_c)
    except (TypeError, ValueError):
        over = 0.0
    if not live or not live_needed or over <= 0 or not water_known:
        return None
    if live.get("band") == "good":
        return None
    excess = float(live.get("waterC", 0)) - float(target_c)
    if excess < over - (LOSING_HYST_C if latched else 0.0):
        return None
    pct = round(float(live.get("index", 0)) * 100)
    return {"shouldRun": True, "kind": "losing", "startAt": None, "until": None,
            "reason": f"the fans are on but the tank is still {excess:.1f} °C over target at {pct} %"}


def _ceiling(live: dict[str, Any] | None, max_rh: float, latched: bool) -> dict[str, Any] | None:
    """The room humidity ceiling (§14.2). Not gated on cooling: this is about
    the house, and a cool muggy evening counts."""
    try:
        ceiling = float(max_rh)
    except (TypeError, ValueError):
        ceiling = 0.0
    if not live or ceiling <= 0 or live.get("rh") is None:
        return None
    rh = float(live["rh"])
    if rh < ceiling - (CEILING_HYST_RH if latched else 0.0):
        return None
    return {"shouldRun": True, "kind": "ceiling", "startAt": None, "until": None,
            "reason": f"room humidity {rh:.0f} % is over the {ceiling:.0f} % ceiling"}


def _dehumidifier_plan_raw(live: dict[str, Any] | None, live_needed: bool, projection: dict[str, Any] | None,
                           now: datetime, lead_h: float, target_c: float,
                           losing_over_c: float = 0.0, max_rh: float = 0.0,
                           water_known: bool = False, latched: str | None = None) -> dict[str, Any]:
    if live and live_needed and live.get("band") in WARN_BANDS:
        room = float(live.get("roomC", 0))
        if room >= target_c + UNRESCUABLE_OVER_TARGET_C and float(live.get("index", 0)) < UNRESCUABLE_INDEX:
            return {"shouldRun": False, "kind": "unrescuable", "startAt": None, "until": None,
                    "reason": (f"room {room:.1f} °C at {live.get('rh', 0):.0f} % — a dehumidifier cannot "
                               "restore cooling safely under these current conditions")}
        pct = round(float(live.get("index", 0)) * 100)
        return {"shouldRun": True, "kind": "now", "startAt": now.isoformat(), "until": None,
                "reason": f"the fans are down to {pct} % right now"}
    losing = _losing(live, live_needed, target_c, losing_over_c, water_known, latched == "losing")
    if losing:
        losing["startAt"] = now.isoformat()
        return losing
    ceiling = _ceiling(live, max_rh, latched == "ceiling")
    if ceiling:
        ceiling["startAt"] = now.isoformat()
        return ceiling
    return {"shouldRun": False, "kind": "none", "startAt": None, "until": None,
            "reason": "current readings do not call for dehumidification"}


# --------------------------------------------------------------------------- #
# Layer 3 — the intake fan: when venting is worth running now
# --------------------------------------------------------------------------- #

VENT_RUN_KINDS = ("cool", "freecool")


def vent_decision(advice: dict[str, Any], fan_needed: bool, projection: dict[str, Any] | None,
                  now: datetime, night_purge: bool, window_open: bool | None,
                  water_c: float | None = None, target_c: float | None = None,
                  purge_floor_c: float = PURGE_WATER_FLOOR_C) -> dict[str, Any]:
    """Vent only for a current cooling need and suitable outdoor readings.
    A closed window blocks the fan. Legacy projection/night-purge arguments
    are ignored so old callers cannot restart forecast-driven ventilation.
    """
    if not advice.get("known"):
        return {"shouldRun": False, "kind": "none", "wants": None, "reason": advice.get("reason", "no outdoor reading")}
    kind = None
    reason = ""
    if advice.get("advised") and fan_needed:
        kind = "cool"
        reason = (f"the room needs cooling and outdoor air is drier ({advice['outdoorC']:.1f} °C, "
                  f"dew point {advice['outdoorDewC']:.1f} °C, {advice['gapC']:.1f} °C below indoors)")
    elif advice.get("freecool") and fan_needed:
        kind = "freecool"
        reason = (f"the room is {advice['coolerBy']:.1f} °C hotter than outside "
                  f"({advice['outdoorC']:.1f} °C) and no wetter — free cooling")
    if kind is None:
        # Prefer the free-cooling refusal when there was one: "cooler but wetter"
        # explains a declined obvious opportunity, where the dew-gap line alone
        # reads like a bug.
        if advice.get("freecoolReason"):
            fallback = advice["freecoolReason"]
        elif not advice.get("advised") and not advice.get("freecool"):
            fallback = advice.get("reason", "")
        else:
            fallback = "outdoor air is worth having, but the room doesn't need it right now"
        return {"shouldRun": False, "kind": "none", "wants": None, "reason": fallback}
    if window_open is False:
        return {"shouldRun": False, "kind": "blocked", "wants": kind,
                "reason": f"{reason} — but the window is closed"}
    return {"shouldRun": True, "kind": kind, "wants": kind, "reason": reason}
