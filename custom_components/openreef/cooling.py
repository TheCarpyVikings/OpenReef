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
