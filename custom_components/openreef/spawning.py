"""Coral Spawning — the Reef Location → Environmental Program engine ("the Brain").

This module is the crown jewel of the spawning feature and is deliberately a
**pure, dependency-free, side-effect-free** computation (stdlib only — no
Home Assistant, no network, no external astronomy libs). That keeps it trivially
unit-testable and means the same code runs in CI and on a Pi.

What it does
------------
Advanced reefers already spawn *Acropora* at home on a Neptune Apex by replaying
a reef's seasonal photoperiod, seasonal temperature and lunar cycle (the method
pioneered by Jamie Craggs / Project Coral, and documented for hobbyists by Rich
Ross at packedhead.net). The miserable part is **authoring the data tables**:
scraping a year of sunrise/sunset/new-moon data off timeanddate.com, digging up
seasonal SST, and hand-writing the Apex code.

This engine eliminates that. Given a curated reef preset + a start year, it
computes:

  * the reef's seasonal **day-length** curve (latitude-driven) → sunrise/sunset
  * the reef's seasonal **temperature** curve (preset SST climatology)
  * accurate **new- and full-moon dates** for the year (Meeus, ch. 49)
  * a **spawn-window prediction** (full moon of the spawning month + the
    documented "N days after full moon" offset)

…and compiles it into the exact artifacts a reefer pastes into the Apex:
the **Season Table** values, the lighting **Profiles**, and the **code**
snippets (temperature / daylight / lunar), following Rich Ross's documented
Apex-Local workflow verbatim.

Design note — anchoring: we preserve the biologically important *day length*
and its seasonal drift, but center the photoperiod on a user-chosen "solar noon"
(default 13:00 local) so the tank runs on a convenient clock rather than the
reef's raw UTC times. An optional whole-month **offset** maps the reef's season
onto the user's calendar (Craggs' "out-of-season" offset profile), e.g. a
Northern-hemisphere reefer can run a Great Barrier Reef cycle aligned to their
own summer. The lunar cycle stays tied to the real moon (a stock Apex derives
moon timing from real new-moon dates), which is fine: temperature + photoperiod
set the *month* of readiness; the real full moon of that month sets the *night*.

Sources: Craggs et al. 2017 (Ecology & Evolution, PMC5743687); Craggs et al.
2025 out-of-season offset profiles (Proc. R. Soc. B, rspb.2025.1558); Rich Ross,
"Coral Spawning Resources" (packedhead.net). Reef SST values are approximate
monthly climatology (validated against the GBR/Singapore profiles Craggs
published) and are intentionally curated presets — dynamic SST data is a later
phase.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .const import (
    REEF_PRESETS,
    SPAWNING_DEFAULT_SOLAR_NOON_HOUR,
    SPAWNING_SUNSET_RAMP_MIN,
    SPAWNING_SUNUP_RAMP_MIN,
)

SYNODIC_MONTH = 29.530588853  # mean days between new moons


# --------------------------------------------------------------------------- #
# Time helpers
# --------------------------------------------------------------------------- #
def _julian_day(dt: datetime) -> float:
    """Julian Day (UTC) for a timezone-aware or naive-as-UTC datetime."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    y, m = dt.year, dt.month
    d = dt.day + (dt.hour + (dt.minute + dt.second / 60) / 60) / 24
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + b - 1524.5


def _jd_to_datetime(jd: float) -> datetime:
    """Inverse of :func:`_julian_day` — returns a UTC datetime."""
    jd += 0.5
    z = math.floor(jd)
    f = jd - z
    if z < 2299161:
        a = z
    else:
        alpha = math.floor((z - 1867216.25) / 36524.25)
        a = z + 1 + alpha - alpha // 4
    b = a + 1524
    c = math.floor((b - 122.1) / 365.25)
    d = math.floor(365.25 * c)
    e = math.floor((b - d) / 30.6001)
    day = b - d - math.floor(30.6001 * e) + f
    month = e - 1 if e < 14 else e - 13
    year = c - 4716 if month > 2 else c - 4715
    day_int = int(math.floor(day))
    frac = day - day_int
    seconds = int(round(frac * 86400))
    base = datetime(year, month, day_int, tzinfo=timezone.utc)
    return base + timedelta(seconds=seconds)


def _fmt_hhmm(hour_float: float) -> str:
    """Format a 0–24 (may wrap) float hour as 'HH:MM'."""
    hour_float %= 24
    h = int(hour_float)
    m = int(round((hour_float - h) * 60))
    if m == 60:
        h, m = (h + 1) % 24, 0
    return f"{h:02d}:{m:02d}"


# --------------------------------------------------------------------------- #
# Solar — day length & anchored sunrise/sunset
# --------------------------------------------------------------------------- #
def solar_declination_deg(when: date) -> float:
    """Sun's declination (deg) via the Spencer/NOAA series. ±0.2° — plenty for
    day length."""
    n = when.timetuple().tm_yday
    gamma = 2 * math.pi / 365 * (n - 1)
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )
    return math.degrees(decl)


def day_length_hours(lat_deg: float, when: date) -> float:
    """Hours between sunrise and sunset at a latitude (zenith 90.833° includes
    refraction + solar radius). Clamped for high latitudes."""
    decl = math.radians(solar_declination_deg(when))
    lat = math.radians(lat_deg)
    cos_h = (math.cos(math.radians(90.833)) - math.sin(lat) * math.sin(decl)) / (
        math.cos(lat) * math.cos(decl)
    )
    cos_h = max(-1.0, min(1.0, cos_h))
    half_arc_deg = math.degrees(math.acos(cos_h))
    return 2 * half_arc_deg / 15.0


def anchored_sun_times(
    lat_deg: float, when: date, solar_noon_hour: float = SPAWNING_DEFAULT_SOLAR_NOON_HOUR
) -> tuple[str, str, float]:
    """(sunrise, sunset, day_length_hours) with the photoperiod centered on
    ``solar_noon_hour`` local time, preserving the reef's true day length."""
    dl = day_length_hours(lat_deg, when)
    sunrise = solar_noon_hour - dl / 2
    sunset = solar_noon_hour + dl / 2
    return _fmt_hhmm(sunrise), _fmt_hhmm(sunset), dl


# --------------------------------------------------------------------------- #
# Lunar — phase, illumination, and accurate new/full moon instants
# --------------------------------------------------------------------------- #
def _phase_jde(k: float) -> float:
    """Julian Ephemeris Day of a lunar phase, Meeus *Astronomical Algorithms*
    ch. 49. ``k`` integer → new moon; ``k`` + 0.5 → full moon. The periodic
    correction below is the one Meeus gives for **both** new and full moon.
    Accuracy a few minutes (planetary A-terms omitted — negligible here)."""
    t = k / 1236.85
    jde = (
        2451550.09766
        + 29.530588861 * k
        + 0.00015437 * t**2
        - 0.000000150 * t**3
        + 0.00000000073 * t**4
    )
    e = 1 - 0.002516 * t - 0.0000074 * t**2
    m = math.radians((2.5534 + 29.10535670 * k - 0.0000014 * t**2 - 0.00000011 * t**3) % 360)
    mp = math.radians(
        (201.5643 + 385.81693528 * k + 0.0107582 * t**2 + 0.00001238 * t**3 - 0.000000058 * t**4)
        % 360
    )
    f = math.radians(
        (160.7108 + 390.67050284 * k - 0.0016118 * t**2 - 0.00000227 * t**3 + 0.000000011 * t**4)
        % 360
    )
    om = math.radians((124.7746 - 1.56375588 * k + 0.0020672 * t**2 + 0.00000215 * t**3) % 360)
    corr = (
        -0.40720 * math.sin(mp)
        + 0.17241 * e * math.sin(m)
        + 0.01608 * math.sin(2 * mp)
        + 0.01039 * math.sin(2 * f)
        + 0.00739 * e * math.sin(mp - m)
        - 0.00514 * e * math.sin(mp + m)
        + 0.00208 * e * e * math.sin(2 * m)
        - 0.00111 * math.sin(mp - 2 * f)
        - 0.00057 * math.sin(mp + 2 * f)
        + 0.00056 * e * math.sin(2 * mp + m)
        - 0.00042 * math.sin(3 * mp)
        + 0.00042 * e * math.sin(m + 2 * f)
        + 0.00038 * e * math.sin(m - 2 * f)
        - 0.00024 * e * math.sin(2 * mp - m)
        - 0.00017 * math.sin(om)
        - 0.00007 * math.sin(mp + 2 * m)
        + 0.00004 * math.sin(2 * mp - 2 * f)
        + 0.00004 * math.sin(3 * m)
        + 0.00003 * math.sin(mp + m - 2 * f)
        + 0.00003 * math.sin(2 * mp + 2 * f)
        - 0.00003 * math.sin(mp + m + 2 * f)
        + 0.00003 * math.sin(mp - m + 2 * f)
        - 0.00002 * math.sin(mp - m - 2 * f)
        - 0.00002 * math.sin(3 * mp + m)
        + 0.00002 * math.sin(4 * mp)
    )
    return jde + corr


def _k_for(when: datetime) -> float:
    frac_year = when.year + (when.timetuple().tm_yday - 1) / 365.25
    return (frac_year - 2000) * 12.3685


def lunar_events(start: datetime, end: datetime) -> dict[str, list[datetime]]:
    """All new- and full-moon instants (UTC) within [start, end]."""
    new_moons: list[datetime] = []
    full_moons: list[datetime] = []
    k0 = math.floor(_k_for(start)) - 2
    for i in range(k0, k0 + 16):
        nm = _jd_to_datetime(_phase_jde(i))
        if start <= nm <= end:
            new_moons.append(nm)
        fm = _jd_to_datetime(_phase_jde(i + 0.5))
        if start <= fm <= end:
            full_moons.append(fm)
    new_moons.sort()
    full_moons.sort()
    return {"new_moons": new_moons, "full_moons": full_moons}


def last_new_moon_before(when: datetime) -> datetime:
    """Instant of the new moon immediately preceding ``when``."""
    k = math.floor(_k_for(when))
    for i in range(k + 2, k - 4, -1):
        nm = _jd_to_datetime(_phase_jde(i))
        if nm <= when:
            return nm
    return _jd_to_datetime(_phase_jde(k))


def moon_age_days(when: datetime) -> float:
    """Days since the last new moon (0 … ~29.53)."""
    return (when - last_new_moon_before(when)).total_seconds() / 86400.0


def moon_illumination(when: datetime) -> float:
    """Illuminated fraction 0 (new) … 1 (full), smooth synodic approximation —
    accurate enough to drive a lunar-intensity curve."""
    age = moon_age_days(when)
    return (1 - math.cos(2 * math.pi * age / SYNODIC_MONTH)) / 2


def moon_phase_name(age_days: float) -> str:
    frac = (age_days % SYNODIC_MONTH) / SYNODIC_MONTH
    names = [
        (0.02, "New moon"),
        (0.24, "Waxing crescent"),
        (0.27, "First quarter"),
        (0.48, "Waxing gibbous"),
        (0.52, "Full moon"),
        (0.73, "Waning gibbous"),
        (0.77, "Last quarter"),
        (0.98, "Waning crescent"),
    ]
    for threshold, name in names:
        if frac <= threshold:
            return name
    return "New moon"


# --------------------------------------------------------------------------- #
# Temperature climatology
# --------------------------------------------------------------------------- #
def _c_to_unit(celsius: float, unit: str) -> float:
    return celsius if unit.upper() == "C" else celsius * 9 / 5 + 32


def _reef_month(local_month: int, offset_months: int) -> int:
    """Map a local calendar month (1–12) back to the reef's month given a whole
    -month seasonal offset."""
    return ((local_month - 1 - offset_months) % 12) + 1


# --------------------------------------------------------------------------- #
# The compiler
# --------------------------------------------------------------------------- #
_MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]
_MONTHS_FULL = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def build_environmental_model(
    preset: dict[str, Any],
    year: int,
    offset_months: int,
    solar_noon_hour: float,
    temp_unit: str,
) -> list[dict[str, Any]]:
    """12 monthly rows of the reef's anchored sun/temperature program, mapped onto
    the local calendar (this is what fills the Apex Season Table)."""
    lat = preset["lat"]
    sst = preset["sstMonthlyC"]
    rows: list[dict[str, Any]] = []
    for local_month in range(1, 13):
        reef_month = _reef_month(local_month, offset_months)
        rep = date(year, reef_month, 15)
        sunrise, sunset, dl = anchored_sun_times(lat, rep, solar_noon_hour)
        temp_c = sst[reef_month - 1]
        rows.append(
            {
                "localMonth": local_month,
                "localMonthName": _MONTHS[local_month - 1],
                "localDate": f"{_MONTHS[local_month - 1]} 15",
                "reefMonth": reef_month,
                "reefMonthName": _MONTHS[reef_month - 1],
                "sunrise": sunrise,
                "sunset": sunset,
                "dayLengthHours": round(dl, 2),
                "tempC": round(temp_c, 1),
                "temp": round(_c_to_unit(temp_c, temp_unit), 1),
                "tempUnit": temp_unit.upper(),
            }
        )
    return rows


def predict_spawn_window(
    preset: dict[str, Any], year: int, offset_months: int, today: datetime | None = None
) -> dict[str, Any]:
    """Predict the spawning night window: the full moon of the (offset-mapped)
    spawning month + the preset's documented 'N days after full moon' range."""
    reef_spawn_month = preset["spawnReefMonth"]
    local_spawn_month = ((reef_spawn_month - 1 + offset_months) % 12) + 1
    lo, hi = preset["daysAfterFullMoon"]

    # Search a 2-month window around the local spawning month for its full moon,
    # rolling into next year if the window has already passed today.
    candidates: list[dict[str, Any]] = []
    for yr in (year, year + 1):
        start = datetime(yr, 1, 1, tzinfo=timezone.utc)
        end = datetime(yr + 1, 2, 1, tzinfo=timezone.utc)
        for fm in lunar_events(start, end)["full_moons"]:
            if fm.month == local_spawn_month:
                candidates.append(
                    {
                        "fullMoonUtc": fm.isoformat(),
                        "windowStart": (fm + timedelta(days=lo)).date().isoformat(),
                        "windowEnd": (fm + timedelta(days=hi)).date().isoformat(),
                        "_window_end_dt": fm + timedelta(days=hi),
                    }
                )

    chosen = None
    if today is not None:
        for c in candidates:
            if c["_window_end_dt"] >= today:
                chosen = c
                break
    chosen = chosen or (candidates[0] if candidates else None)

    result = {
        "reefSpawnMonth": reef_spawn_month,
        "reefSpawnMonthName": _MONTHS_FULL[reef_spawn_month - 1],
        "localSpawnMonth": local_spawn_month,
        "localSpawnMonthName": _MONTHS_FULL[local_spawn_month - 1],
        "daysAfterFullMoon": [lo, hi],
    }
    if chosen:
        result.update(
            {
                "fullMoonUtc": chosen["fullMoonUtc"],
                "windowStart": chosen["windowStart"],
                "windowEnd": chosen["windowEnd"],
            }
        )
        if today is not None:
            nights = (chosen["_window_end_dt"].date() - today.date()).days
            result["nightsUntilWindowEnd"] = nights
            start_dt = datetime.fromisoformat(chosen["windowStart"]).date()
            result["nightsUntilWindowStart"] = (start_dt - today.date()).days
    return result


def _code_snippets(temp_probe: str, temp_unit: str) -> dict[str, dict[str, str]]:
    """The exact Apex code reefers hand-write, per Rich Ross's documented
    workflow. ``RT`` is the reference temperature the Season Table drives, so this
    code is constant boilerplate — the *table* carries the seasonal values."""
    tol = "0.2"  # ±0.2° tolerance (Rich Ross / Craggs ±0.1–0.2°)
    unit = temp_unit.upper()
    return {
        "temperature_heater": {
            "label": f"Heater (±{tol}°{unit}, tracks Season Table RT)",
            "target": "Heater outlet",
            "code": (
                "Fallback OFF\n"
                "Set OFF\n"
                f"If {temp_probe} < RT-{tol} Then ON\n"
                f"If {temp_probe} > RT+{tol} Then OFF"
            ),
            "note": "RT is the seasonal reference temperature set by the Season Table.",
        },
        "temperature_chiller": {
            "label": f"Chiller (±{tol}°{unit}, tracks Season Table RT)",
            "target": "Chiller outlet",
            "code": (
                "Fallback OFF\n"
                "Set OFF\n"
                f"If {temp_probe} > RT+{tol} Then ON\n"
                f"If {temp_probe} < RT-{tol} Then OFF"
            ),
            "note": "Mirror of the heater — keeps the tank inside RT ± tolerance.",
        },
        "daylight_3step": {
            "label": "Daylight — 3 step (sunrise / midday / sunset)",
            "target": "Light virtual output or Profile selector",
            "code": (
                "Fallback OFF\n"
                "Set OFF\n"
                "If Sun 000/-360 Then Sunup\n"
                "If Sun 360/000 Then Sunset\n"
                "If Sun 180/-180 Then Midday"
            ),
            "note": "Sun NNN/NNN is minutes relative to the Season Table's sunrise/sunset.",
        },
        "daylight_5step": {
            "label": "Daylight — 5 step (smoother ramps)",
            "target": "Light virtual output or Profile selector",
            "code": (
                "Fallback OFF\n"
                "Set OFF\n"
                "If Sun 000/-360 Then Sunup1\n"
                "If Sun 090/-270 Then Sunup2\n"
                "If Sun 180/-180 Then Midday\n"
                "If Sun 270/-090 Then Afternoon\n"
                "If Sun 360/000 Then Sunset"
            ),
            "note": "Add Sunup1/Sunup2/Afternoon Profiles for a gentler dawn/dusk.",
        },
        "lunar_lsm": {
            "label": "Lunar — moonrise→moonset (LSM / vMoon)",
            "target": "Lunar Simulation Module or vMoon virtual output",
            "code": "Fallback OFF\nSet OFF\nIf Moon 000/000 Then ON",
            "note": "Apex derives moon timing from the new-moon dates in the Season Table.",
        },
        "radion_moonlight": {
            "label": "Radion moonlight (MXM) — follow vMoon",
            "target": "Radion (MXM) Advanced tab",
            "code": "If Output vMoon = ON Then Moonlight",
            "note": "Switches the MXM-linked Radion to its Moonlight profile when vMoon is on.",
        },
    }


def _profiles(preset: dict[str, Any]) -> list[dict[str, Any]]:
    """Template lighting Profiles (Sunup/Midday/Sunset/Moonlight) for MXM-driven
    Radions. Intensities are sensible starting points the reefer matches to their
    fixture/coral; Midday targets the reef's published PAR band."""
    par_lo, par_hi = preset.get("middayParBand", (350, 450))
    return [
        {
            "name": "Sunup",
            "type": "Profile",
            "intensityPercent": 25,
            "rampMinutes": SPAWNING_SUNUP_RAMP_MIN,
            "note": "Gentle dawn ramp up from 0%. Warmer/low-blue start.",
        },
        {
            "name": "Midday",
            "type": "Profile",
            "intensityPercent": 100,
            "rampMinutes": 0,
            "note": f"Peak — match your fixture to ~{par_lo}–{par_hi} µmol·m⁻²·s⁻¹ PAR at coral height.",
        },
        {
            "name": "Sunset",
            "type": "Profile",
            "intensityPercent": 25,
            "rampMinutes": SPAWNING_SUNSET_RAMP_MIN,
            "note": "Gentle dusk ramp down to 0%. Sunset is the proximate spawn trigger — keep it smooth.",
        },
        {
            "name": "Moonlight",
            "type": "Profile",
            "intensityPercent": 2,
            "rampMinutes": 0,
            "note": "Dim blue (~1–2%). Real dark nights matter — light pollution desynchronises spawning.",
        },
    ]


def _walkthrough() -> list[str]:
    """Guided steps mirroring Rich Ross's documented Apex-Local workflow."""
    return [
        "Open Apex Local: in Apex Fusion click your Apex name (top-left) → Network → copy the IP, then open that IP in a browser and log in.",
        "Go to the gear icon → wrench → sun icon to open the Season Table.",
        "Enter the 12 monthly rows below: for each month set sunrise, sunset and the reference temperature (RT).",
        "Enter the New-Moon dates below into the lunar / Season Table new-moon fields.",
        "Create the four Profiles (Sunup, Midday, Sunset, Moonlight) for your MXM-linked Radions using the intensities below.",
        "Paste the code snippets into the matching outlets/virtual outputs (heater, daylight, lunar, Radion moonlight).",
        "⚠️ Re-check the Apex new-moon table every January 1 — it auto-resets, which silently drifts your lunar timing.",
    ]


def generate_program(
    preset_id: str,
    year: int,
    *,
    offset_months: int = 0,
    solar_noon_hour: float = SPAWNING_DEFAULT_SOLAR_NOON_HOUR,
    temp_unit: str = "C",
    temp_probe: str = "Tmp",
    today: datetime | None = None,
) -> dict[str, Any]:
    """Compile a complete, copy-paste-ready spawning program for a reef preset.

    Returns a JSON-serialisable dict: preset metadata, the 12-row Season Table,
    the lighting Profiles, the Apex code snippets, the year's new/full-moon
    dates, the spawn-window prediction, the guided walkthrough, and sources.
    Raises ``KeyError`` for an unknown preset id.
    """
    preset = REEF_PRESETS[preset_id]
    offset_months = int(offset_months) % 12
    temp_unit = "F" if str(temp_unit).upper() == "F" else "C"

    model = build_environmental_model(preset, year, offset_months, solar_noon_hour, temp_unit)
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime(year, 12, 31, 23, 59, tzinfo=timezone.utc)
    events = lunar_events(start, end)

    return {
        "preset": {
            "id": preset_id,
            "label": preset["label"],
            "region": preset["region"],
            "lat": preset["lat"],
            "lon": preset["lon"],
            "hemisphere": "S" if preset["lat"] < 0 else "N",
        },
        "params": {
            "year": year,
            "offsetMonths": offset_months,
            "solarNoonHour": solar_noon_hour,
            "tempUnit": temp_unit,
            "tempProbe": temp_probe,
        },
        "seasonTable": model,
        "profiles": _profiles(preset),
        "codeSnippets": _code_snippets(temp_probe, temp_unit),
        "newMoonDates": [d.date().isoformat() for d in events["new_moons"]],
        "fullMoonDates": [d.date().isoformat() for d in events["full_moons"]],
        "spawnPrediction": predict_spawn_window(preset, year, offset_months, today),
        "walkthrough": _walkthrough(),
        "tempRangeC": [round(min(preset["sstMonthlyC"]), 1), round(max(preset["sstMonthlyC"]), 1)],
        "sources": [
            {"label": "Craggs et al. 2017 — ex-situ mesocosm protocol", "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC5743687/"},
            {"label": "Craggs et al. 2025 — out-of-season offset profiles", "url": "https://royalsocietypublishing.org/doi/10.1098/rspb.2025.1558"},
            {"label": "Rich Ross — Coral Spawning Resources (Apex workflow)", "url": "https://packedhead.net/coral-spawning-resources/"},
        ],
        "disclaimer": (
            "Curated reef presets with approximate monthly SST climatology. OpenReef generates the "
            "program; your Apex executes it with its own failsafes. Spawning needs sexually mature, "
            "same-species colonies, genuine dark nights, and many months of conditioning."
        ),
    }


# --------------------------------------------------------------------------- #
# Lighting schedule — used to gate light-dependent alerts (e.g. PAR) to the
# hours the lights are actually meant to be on. Reuses the same solar day-length
# math as the spawning compiler. Two modes:
#   simple — explicit on/off clock times
#   reef   — a reef preset's seasonal day length, centered on mean solar noon
#            (12:00) then shifted by the user's offset, so it tracks how a reefer
#            runs a mimicked reef's sunrise/sunset (e.g. "Cairns time + 2h").
# A ramp-grace buffer narrows the *alertable* window at both ends so the dawn/dusk
# ramp (when PAR is legitimately low) doesn't trip a false low-PAR alert.
# --------------------------------------------------------------------------- #
def _parse_hhmm(value: Any, default_minutes: int) -> int:
    try:
        hh, mm = str(value).split(":")
        return (int(hh) % 24) * 60 + (int(mm) % 60)
    except (ValueError, AttributeError):
        return default_minutes


def lighting_window(lighting_cfg: dict[str, Any] | None, local_date: date) -> tuple[int, int] | None:
    """Lights-on window as (start, end) minutes since local midnight, or None when
    no schedule is configured (mode 'off'). ``end`` may be < ``start`` if it wraps
    past midnight."""
    cfg = lighting_cfg or {}
    mode = cfg.get("mode", "off")
    if mode == "simple":
        start = _parse_hhmm(cfg.get("onTime"), 8 * 60)
        end = _parse_hhmm(cfg.get("offTime"), 20 * 60)
        return start, end
    if mode == "reef":
        preset = REEF_PRESETS.get(cfg.get("reefPreset"))
        if not preset:
            return None
        try:
            offset = float(cfg.get("offsetHours", 0))
        except (TypeError, ValueError):
            offset = 0.0
        dl = day_length_hours(preset["lat"], local_date)
        start = int(round((12.0 - dl / 2 + offset) * 60)) % 1440
        end = int(round((12.0 + dl / 2 + offset) * 60)) % 1440
        return start, end
    return None


def _in_window(minute: int, start: int, end: int) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end  # wraps past midnight


def is_lights_on(lighting_cfg: dict[str, Any] | None, local_dt: datetime, grace_minutes: int = 0) -> bool:
    """Is ``local_dt`` inside the lights-on window (narrowed by the ramp grace at
    both ends)? Returns True when no schedule is configured, so callers never
    suppress alerts unless the user opted into a schedule."""
    win = lighting_window(lighting_cfg, local_dt.date())
    if win is None:
        return True
    start, end = win
    if start == end:
        # Degenerate window (equal on/off times, or a zero-length day): treat as
        # lights-on 24h so a real low reading is NEVER silently suppressed. To turn
        # gating off entirely, use mode "off".
        return True
    length = (end - start) % 1440 or 1440
    grace = max(0, int(grace_minutes))
    if 2 * grace >= length:
        grace = max(0, (length - 1) // 2)
    start2 = (start + grace) % 1440
    end2 = (end - grace) % 1440
    minute = local_dt.hour * 60 + local_dt.minute
    return _in_window(minute, start2, end2)


def lighting_window_summary(lighting_cfg: dict[str, Any] | None, local_dt: datetime) -> dict[str, Any]:
    """Human-facing summary of today's lighting window for the panel."""
    cfg = lighting_cfg or {}
    mode = cfg.get("mode", "off")
    win = lighting_window(cfg, local_dt.date())
    try:
        grace = int(cfg.get("rampGraceMinutes", 0))
    except (TypeError, ValueError):
        grace = 0
    out: dict[str, Any] = {"mode": mode, "configured": win is not None}
    if win is not None:
        start, end = win
        out["onTime"] = _fmt_hhmm(start / 60)
        out["offTime"] = _fmt_hhmm(end / 60)
        out["graceMinutes"] = max(0, grace)
        out["lightsOnNow"] = is_lights_on(cfg, local_dt, grace)
        if mode == "reef":
            preset = REEF_PRESETS.get(cfg.get("reefPreset"))
            if preset:
                out["reefLabel"] = preset["label"]
                out["dayLengthHours"] = round(day_length_hours(preset["lat"], local_dt.date()), 2)
    return out


def list_presets() -> list[dict[str, Any]]:
    """Lightweight metadata for the reef picker (no heavy computation)."""
    out: list[dict[str, Any]] = []
    for preset_id, p in REEF_PRESETS.items():
        out.append(
            {
                "id": preset_id,
                "label": p["label"],
                "region": p["region"],
                "lat": p["lat"],
                "lon": p["lon"],
                "hemisphere": "S" if p["lat"] < 0 else "N",
                "spawnMonth": _MONTHS_FULL[p["spawnReefMonth"] - 1],
                "tempRangeC": [round(min(p["sstMonthlyC"]), 1), round(max(p["sstMonthlyC"]), 1)],
                "note": p.get("note", ""),
            }
        )
    return out
