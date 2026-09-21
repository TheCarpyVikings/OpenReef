"""Live cultures engine — pure maths for the rotifer / copepod jars.

Design stance (mirrors nps.py / awc.py): every function here is a pure
function of its inputs — no Home Assistant imports, no I/O, no wall clock.
Orchestration (WS handlers, ledgers, reminders) lives in __init__.py.

The brine hatchery is a batch measured in hours. A culture is a standing
population measured in days: a rotifer jar uses daily partial harvest and
replacement water; a copepod jar needs slower, density-led harvesting.
Calendar presets are reminders, not measurements of population or water quality.
Species presets carry the numbers from the 2026-09 research sweep
(docs/live-cultures-brainstorm.md §1–§2; the phyto vessel from
docs/phyto-culture-brainstorm.md §3–§5); the keeper can override any
cadence per jar and the engine reads the merged view.

Honesty rules (the AWC tradition): a clock with no stamp is "unknown", never
a guess; a chore is due when its interval has elapsed since it was last
DONE (or since the jar was seeded, for a jar that has never had it done);
temperature advice never moves a clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import math
from typing import Any

from .awc import _f, _parse_iso as _awc_parse_iso
from .mixing import sg_from_ppt

CULTURE_JARS_MAX = 6
# The rotifer / pod scale: the FOOD in the water (green = fed, clear = hungry).
TINTS: tuple[str, ...] = ("green", "clearing", "clear")
# The phyto scale (docs/phyto-culture-brainstorm.md §5.1) reads the other way:
# the CULTURE is the colour. pale → green → dark is growth, dark is the
# harvest colour; off (grey, yellow, brown) is a sign in itself — never
# harvest an off-colour vessel into anything. Every reader asks tints_for().
PHYTO_TINTS: tuple[str, ...] = ("pale", "green", "dark", "off")
ALL_TINTS: tuple[str, ...] = TINTS + PHYTO_TINTS
# bottle = a lit carboy / the Reefphyto 4 L container; reactor = a purpose-
# built lit tube with a drain tap (drawn differently, same clocks).
VESSEL_KINDS: tuple[str, ...] = ("cone", "tub", "jar", "bottle", "reactor")
# Where a harvest goes (0.7.161): the fridge bottle, straight into the tank,
# or the enrichment soak first. A species without a bottle only knows "tank".
HARVEST_DESTINATIONS: tuple[str, ...] = ("bottle", "tank", "soak")
# Where a phyto SPLIT goes — several in one tap (doc §5.3): the home fridge
# bottle, straight into the tank, the drip's jar, a second vessel (B), or —
# Stage C — a rotifer cone as its feed (a DRAW, see PHYTO_DRAW_MAX_PCT).
SPLIT_DESTINATIONS: tuple[str, ...] = ("bottle", "tank", "drip", "vessel", "cone")
# Crash signs the keeper can tap (doc §8.5): each one is a restart (rotifers)
# or a water change (pods) due NOW, whatever the calendar says.
SIGNS: tuple[str, ...] = ("foam", "milky", "smell", "surface")
# A phyto vessel's signs (§5.3): each brings the fresh vessel forward and
# blocks the split until a tint tap says green or dark again.
PHYTO_SIGNS: tuple[str, ...] = ("yellow", "brown", "cloudy", "clumping", "foam", "smell", "settling")
ALL_SIGNS: tuple[str, ...] = SIGNS + tuple(s for s in PHYTO_SIGNS if s not in SIGNS)
SIGN_WORDS = {"foam": "foam on the surface", "milky": "milky water", "smell": "a smell",
              "surface": "clustering at the surface",
              "yellow": "yellowing", "brown": "browning", "cloudy": "cloudy water",
              "clumping": "clumping", "settling": "settling out"}
PHYTO_MODES: tuple[str, ...] = ("batch", "daily")
PHYTO_LOOK_H = 24.0            # the daily tint tap — the one readout the method has
PHYTO_PEAK_HELD_DAYS = 3.0     # dark this long without a split = "a culture held at peak turns"
PHYTO_SPLIT_WARN_PCT = 70.0    # above this the seed left behind is thin (the 30 % seed rule)
PHYTO_SEED_RATIO = 4.0         # the starter page's 1:4 — 250 ml into 1 L of new water
PHYTO_RECOVER_DAYS = 2.0       # an off-colour vessel that has not recovered in two days is a crash
BOTTLE_RESEED_DAYS = 7.0       # a fridge bottle under a week old is a legitimate starter
SHAKE_EVERY_H = 48.0           # Reefphyto: shake the bottle every one to two days
# Light (doc §5.6, Stage B): sun on the rack, the LED on a plug, or both — in
# sun+lamp the plug runs from SUNSET until daylight + lamp = the target, never
# past latestOff (a 16 h day always leaves the eight dark hours). Daylight is
# astronomical (HA's sun entity) — an upper bound of what the window gives.
LIGHT_MODES: tuple[str, ...] = ("sun", "lamp", "sun+lamp")
LIGHT_SHORT_DAY_H = 12.0       # under this the window alone will not green a vessel — the nudge
LIGHT_LOST_DAY_H = 12.0        # under this delivered by window end = a lost day of light (act)
LIGHT_ON_AT_DEFAULT = "07:00"  # lamp mode: on at this, for lightHours
LIGHT_LATEST_OFF_DEFAULT = "00:00"   # sun+lamp: the lamp never runs past this
LIGHT_WEEK_LOW_H = 14.0        # a week under this beside a slow cycle earns the learned line
BACKUP_REFRESH_MIN_DAYS = 7.0  # B is refreshed from A every restartCycles splits, never sooner than a week
# §4.1: what a faint tint in the display costs, as an ESTIMATE — one tint of
# ~10,000 cells/ml from a dark home culture of ~1.5×10⁷ cells/ml. The culture
# is uncounted; nothing here is ever shown as the bottle's cells/ml.
TINT_CELLS_PER_ML = 10_000.0
HOME_CULTURE_CELLS_PER_ML_ESTIMATE = 1.5e7
# Stage C (doc §4.1, §5.5): the cone's "light green" ~1 × 10⁶ cells/ml — one
# tint dose of a 2.5 L cone from a dark home culture ≈ 170 ml, an ESTIMATE.
CONE_TINT_CELLS_PER_ML = 1.0e6
# A phyto split that takes less than this share of the working volume is a
# DRAW (a cone dose, a syringe for the tank): the vessel's ledger moves, its
# colour, split clock and cycle counter do not. Daily mode always re-anchors.
PHYTO_DRAW_MAX_PCT = 30.0
SECCHI_FIT_MIN_POINTS = 4          # cm readings across ≥ 2 days before the fit speaks
SECCHI_BAND_MIN_READINGS = 2       # readings at a tint before its band is drawn on the stick
# Stage D (doc §6): the green index — the culture's optical density against
# the white card behind it (a phone photo, the camera's frame) or a colour
# sensor's blank. Red and green carry the chlorophyll; blue carries nothing.
INDEX_SOURCES: tuple[str, ...] = ("phone", "camera", "sensor")
INDEX_OD_MAX = 3.0                 # past this the patch is black: saturated, not measured
INDEX_FIT_MIN_POINTS = 4           # readings across ≥ 2 days before the curve speaks
INDEX_BAND_MIN_READINGS = 2        # readings beside a tint before that tint has an index band
INDEX_PEAK_DAYS = 3.0              # the index at or over dark this long without a split = held at peak
INDEX_CALIBRATION_MAX_AGE_DAYS = 2.0   # a count calibrates the index read within two days of it
PH_TREND_DAYS = 3                  # daily pH maxima compared over this many days
PH_FLAT_DELTA = 0.05               # pH per day under which the curve is flat
LEARN_SAMPLES = 3          # rolling window, the hatch clock's contract
SLOW_FACTOR = 1.5          # two slower clearing observations prompt inspection
# Supplier-specific soak default; storage/boost windows are scheduling estimates,
# not assays of DHA or viability. See docs/cultures-audit-2026-09-10.md.
ENRICH_SOAK_H = 6.0
ENRICH_DROPS = 3
ENRICH_DROP_ML = 0.05
BOOST_WARM_H = 8.0
BOOST_COLD_H = 24.0
BOTTLE_EVENTS: tuple[str, ...] = ("filled", "fed_tank", "enriched", "emptied")
GUARD_LOOKAHEAD_H = 24.0       # the heatwave guard looks one day ahead (doc §8.8 #2)
TINT_STRIP_DAYS = 14
RIG_CONES_MAX = 4
# 0.7.140 (doc §8.12): the purge is a journal fact, so the run-length learning
# can compare observed run lengths at different purge volumes; the guard
# takes the rack's own offset over the room; the starter's acclimation is
# arithmetic, not a shrug.
PURGE_RUNS_MIN = 2             # runs at EACH purge volume before the note speaks
RACK_OFFSET_MAX_C = 5.0        # chosen projection correction cap, not a physical limit
RACK_OFFSET_WINDOW_H = 1.5     # the projection row that counts as "now"
STARTER_PPT = 27.0             # culture target only; NEVER a measured shipping salinity
ACCLIMATE_STEP_PPT = 5.0       # FAO flags transfers differing by more than 5 ppt
ACCLIMATE_WAIT_MIN = 15       # handling guideline, not a validated acclimation time
ACCLIMATE_STEPS_MAX = 4

# Species presets. tempMin/MaxC = the productive band; tempHardMaxC = the
# line above which the copy stops advising and starts warning (Reece's
# Tigriopus culture died in a UK heatwave — the flat ran hot for days).
# feedIntervalH: how often the jar wants looking at / feeding by tint.
# harvestIntervalDays + harvestPct: the standing harvest, which for rotifers
# IS the water change (waterChangeIntervalDays 0 = no separate chore).
# restartIntervalDays: the sieve-and-restart into a clean jar (0 = never).
# firstHarvestDays: let a freshly seeded jar establish before the first draw.
# splitMinAgeDays: when "Split into B" becomes sensible.
# bottleShelfDays: estimated fridge handling window (0 = the
# harvest goes straight into the tank — no bottle for this species).
SPECIES: tuple[dict[str, Any], ...] = (
    {"id": "rotifer_L", "name": "Rotifers (L-type)", "kind": "rotifer",
     "latin": "Brachionus plicatilis",
     # V2 (doc §8.2): Reefphyto cultures at SG 1.019–1.021; FAO says optimal
     # reproduction below 35 ppt; this does not establish a crash-free salinity.
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
             "(no airstone). Feed the concentrate to a leafy green, little and often: inspect "
             "activity when clear, and check before adding food when still green. Before a harvest: air off, settle, bleed "
             "the tip to waste, then 25 % a day through the 50 µm net — the water you take out IS "
             "the water change; refill with matched water. Sieve the whole cone into a clean one "
             "every fortnight as a preventive routine; investigate milkiness, persistent foam or smell. "
             "First harvest is conditional on density and activity, not age alone. Check water quality "
             "and replace evaporation with RODI. Feed dose depends on the product and population."},
    {"id": "tigriopus", "name": "Tigriopus copepods", "kind": "copepod",
     "latin": "Tigriopus californicus",
     # V2: Reefphyto's copepod guide (35 ppt optimal, 22–26 °C, first harvest
     # 4–6 weeks, ≤25–30 % with 7–10 days between). The precautionary
     # warn 28 / act 30 / critical 32 tiers are not measured lethal limits;
     # direct heat stress and water-quality deterioration both matter.
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
             "harvested volume back as matched saltwater; water volume does not measure the share of "
             "a bottom-dwelling population harvested. Test water quality weekly and use RODI for evaporation. "
             "Detected ammonia/nitrite calls for matched water changes. Heat thresholds are precautionary: "
             "heat can directly stress the animals and worsen oxygen and ammonia problems."},
    # The phyto vessel (docs/phyto-culture-brainstorm.md §5.1, Reefphyto's
    # starter page + the 2026-09 papers). Not an animal: the CULTURE is the
    # colour, there is no feed, the harvest is a SPLIT that puts new water and
    # f/2 in, and the restart is a fresh, sterilised vessel every few splits.
    # harvest* mirrors split* so the chore clocks stay one machine
    # (cadence_for maps them); feedIntervalH is the daily look. Heat tiers are
    # precautionary — papers: an abrupt decline near 30 °C — never measured limits.
    {"id": "nanno", "name": "Nannochloropsis (phyto)", "kind": "phyto",
     "latin": "Nannochloropsis oculata",
     "vesselKind": "bottle",
     "tempMinC": 20.0, "tempMaxC": 27.0, "tempHardMaxC": 29.0,
     "tempActC": 30.0, "tempCriticalC": 32.0,
     "salinityPpt": 35.0,
     "feedIntervalH": 24.0,
     "harvestIntervalDays": 8.0, "harvestPct": 60.0,
     "restartIntervalDays": 0.0,
     "waterChangeIntervalDays": 0.0, "waterChangePct": 0.0,
     "firstHarvestDays": 7.0, "splitMinAgeDays": 7.0,
     "sieveUm": 0, "adultSieveUm": 0, "bottleShelfDays": 21.0,
     "purgeMl": 0.0,
     "splitPct": 60.0, "splitIntervalDays": 8.0, "restartCycles": 4.0, "lightHours": 16.0,
     "recoverDays": 4.0, "nutrientMlPerL": 1.5, "nutrientProduct": "Phytoplankton Nutrient (f/2)",
     "starterShelfDays": 28.0, "starterMl": 250.0, "volumeL": 4.0,
     "seedWorkingL": 1.25, "kitWorkingL": 3.5,
     "lightKelvin": "6000–6500 K", "lightCm": "10–15",
     "tintTarget": "dense, dark green — the harvest colour; grey, yellow or cloudy is a sign",
     "feedProduct": "",
     "enrichSoakH": 0.0, "enrichDrops": "", "boostWarmH": 0.0, "boostColdH": 0.0,
     "note": "A lit vessel, not an animal: the culture IS the colour. 35 ppt (the tank's water), "
             "20–27 °C and sensitive near 30, gentle air, a 6000–6500 K lamp 10–15 cm away for 16 h "
             "and 8 h dark — or the sun, while the days are long enough. Seed the starter 1:4 into new "
             "water with 1.5 ml of f/2 per litre of the NEW water; never re-dose f/2 mid-cycle. Look "
             "daily against a white card: pale → green → dark in about a week. Dark = split: 50–70 % "
             "out (the fridge bottle, the tank, the drip) and the same in as fresh water + f/2, "
             "leaving at least 30 % as seed. A culture held dark for days turns — split or dose more. "
             "Yellow, brown, cloudy, clumping or a smell means do not harvest into anything; two "
             "days without recovery is a crash — reseed from B. A fresh, sterilised vessel every "
             "3–4 splits. Its own airline, syringe and jug — never the rotifer kit. The bottle keeps "
             "2–3 weeks in the fridge, shaken every day or two; the starter itself is best used "
             "within four weeks. Tint and days do not count cells."},
)
_SPECIES_BY_ID = {s["id"]: s for s in SPECIES}
CADENCE_FIELDS: tuple[str, ...] = (
    "feedIntervalH", "harvestIntervalDays", "harvestPct", "restartIntervalDays",
    "waterChangeIntervalDays", "waterChangePct",
    # The phyto vessel's own (only a phyto preset carries them).
    "splitPct", "splitIntervalDays", "restartCycles", "lightHours",
)
CADENCE_CAPS = {
    "feedIntervalH": (1, 168), "harvestIntervalDays": (0.5, 30), "harvestPct": (5, 60),
    "restartIntervalDays": (0, 90), "waterChangeIntervalDays": (0, 90), "waterChangePct": (0, 100),
    "splitPct": (10, 90), "splitIntervalDays": (1, 30), "restartCycles": (0, 20), "lightHours": (0, 24),
}


def _parse_iso(value: Any) -> datetime | None:
    """A culture clock needs an explicit timezone; ambiguous stamps are unknown."""
    parsed = _awc_parse_iso(value)
    return parsed if parsed is not None and parsed.utcoffset() is not None else None


def species_ids() -> tuple[str, ...]:
    return tuple(s["id"] for s in SPECIES)


def species_preset(species_id: Any) -> dict[str, Any]:
    return dict(_SPECIES_BY_ID.get(str(species_id or ""), _SPECIES_BY_ID["rotifer_L"]))


def species_kind(species_id: Any) -> str:
    return str(species_preset(species_id).get("kind") or "rotifer")


def tints_for(species_id: Any) -> tuple[str, ...]:
    """The tint scale a species is read on: the food in the water for the
    animals, the culture's own colour for phyto (§5.1) — every reader asks."""
    return PHYTO_TINTS if species_kind(species_id) == "phyto" else TINTS


def signs_for(species_id: Any) -> tuple[str, ...]:
    return PHYTO_SIGNS if species_kind(species_id) == "phyto" else SIGNS


def phyto_seed_tint(species_id: Any) -> str:
    """The water's colour the moment a ceremony ends: an animal's jar is fed
    (green); a freshly seeded or split phyto vessel is diluted (pale)."""
    return "pale" if species_kind(species_id) == "phyto" else "green"


def cadence_for(species_id: Any, overrides: Any) -> dict[str, float]:
    """The preset cadence with the keeper's per-jar overrides applied. An
    override <= 0 on an interval means "never" only where the preset also
    allows it (restart / water change); feed and harvest always run."""
    preset = species_preset(species_id)
    over = overrides if isinstance(overrides, dict) else {}
    merged: dict[str, float] = {}
    for key in CADENCE_FIELDS:
        if key not in preset:               # the phyto fields live only on a phyto preset
            continue
        base = _f(preset.get(key))
        val = over.get(key)
        if not isinstance(val, bool) and math.isfinite(_f(val, math.nan)):
            merged[key] = float(val)
        else:
            merged[key] = base
    if merged["feedIntervalH"] <= 0:
        merged["feedIntervalH"] = _f(preset["feedIntervalH"])
    if merged["harvestIntervalDays"] <= 0:
        merged["harvestIntervalDays"] = _f(preset["harvestIntervalDays"])
    merged["harvestPct"] = merged["harvestPct"] or _f(preset["harvestPct"])
    for key, (lo, hi) in CADENCE_CAPS.items():
        if key in merged:
            merged[key] = min(hi, max(lo, merged[key]))
    if preset.get("kind") == "phyto":
        # The split IS the harvest: the keeper edits split*, the chore clocks
        # read harvest* — mapped here, once, after the clamps (a 70 % split
        # is a legitimate phyto number the rotifer cap would refuse).
        if merged.get("splitPct", 0) <= 0:
            merged["splitPct"] = _f(preset["splitPct"])
        if merged.get("splitIntervalDays", 0) <= 0:
            merged["splitIntervalDays"] = _f(preset["splitIntervalDays"])
        merged["harvestPct"] = merged["splitPct"]
        merged["harvestIntervalDays"] = merged["splitIntervalDays"]
    return merged


def _due(last_iso: Any, anchor_iso: Any, interval: timedelta, now: datetime) -> dict[str, Any]:
    """Chore clock: due when ``interval`` has passed since the chore was last
    done, or since the anchor (seeded / restarted) if it never was."""
    last = _parse_iso(last_iso)
    anchor = _parse_iso(anchor_iso)
    last = max(last, anchor) if last is not None and anchor is not None else last or anchor
    if last is None or last > now:
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
    if started is None or started > now:
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
    if species["kind"] == "phyto":
        return _phyto_state(jar, state, species, cad, started, restart_anchor, now, out)
    establishing = age_days < _f(species["firstHarvestDays"])
    out["status"] = "establishing" if establishing else "producing"

    # A skipped feed (0.7.184) holds the feed clock for one interval without
    # pretending the jar was fed: the anchor moves to the skip, lastFedAt
    # stays where it was (the clearing maths read the history, not this).
    skip_at = _parse_iso(state.get("lastFeedSkippedAt"))
    fed_at = _parse_iso(state.get("lastFedAt"))
    skip_live = skip_at is not None and started <= skip_at <= now
    feed_anchor = skip_at.isoformat() if skip_live else state.get("startedAt")
    out["feed"] = _due(state.get("lastFedAt"), feed_anchor,
                       timedelta(hours=cad["feedIntervalH"]), now)
    out["feed"]["skipped"] = bool(skip_live and (fed_at is None or skip_at > fed_at))
    # The first harvest lands when establishment ends (firstHarvestDays after
    # the seed), every later one an interval after the last — a jar still
    # establishing reports the wait honestly, never "due".
    first_harvest = started + timedelta(days=_f(species["firstHarvestDays"]))
    last_harvest = _parse_iso(state.get("lastHarvestAt")) if not establishing else None
    if last_harvest is not None and last_harvest >= first_harvest:
        out["harvest"] = _due(last_harvest.isoformat(), None,
                              timedelta(days=cad["harvestIntervalDays"]), now)
    else:
        out["harvest"] = _due(started.isoformat(), None,
                              timedelta(days=_f(species["firstHarvestDays"])), now)
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
    signed = sign_at is not None and restart_anchor <= sign_at <= now
    wc_anchor = _parse_iso(state.get("lastWaterChangeAt")) or started
    slow = False
    samples = clearing_samples([row for at, row in _chronological(jar.get("history"))
                                if restart_anchor <= at <= now])
    if len(samples) >= 4:
        baseline = sum(samples[2:5]) / len(samples[2:5])
        slow = baseline > 0 and samples[0] > SLOW_FACTOR * baseline and samples[1] > SLOW_FACTOR * baseline
    out["clearingSlow"] = slow
    if species["kind"] == "rotifer" and (signed or slow):
        out["restart"].update({"available": True, "due": True, "hoursUntil": 0.0,
                               "at": (sign_at if signed else now).isoformat(),
                               "hoursOverdue": round((now - sign_at).total_seconds() / 3600, 1) if signed else 0.0,
                               "reason": "sign" if signed else "slow"})
    elif species["kind"] == "copepod" and cad["waterChangePct"] > 0 and sign_at is not None \
            and wc_anchor <= sign_at <= now:
        out["waterChange"] = {"available": True, "due": True, "at": sign_at.isoformat(),
                              "hoursUntil": 0.0, "hoursOverdue": round(max(0.0, (now - sign_at).total_seconds() / 3600.0), 1),
                              "reason": "sign"}
    # A species with a percentage but no interval changes water on a SIGN
    # (drift, ammonia, cloudy water) — no clock, but the ceremony exists.
    out["waterChangeOnDemand"] = (cad["waterChangeIntervalDays"] <= 0 < cad["waterChangePct"])
    out["splitEligible"] = (age_days >= _f(species["splitMinAgeDays"])
                            and str(state.get("lastTint") or "") in ("green", "clearing")
                            and not signed and not slow)
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


def _dark_run_days(history: Any, since: datetime, now: datetime) -> float:
    """Days the vessel has read DARK without a break since ``since`` (the last
    split): the peak-held clock. Any other tint tap ends the run."""
    run_start: datetime | None = None
    for at, row in _chronological(history):
        if at < since or at > now:
            continue
        tint = str(row.get("tint") or "")
        if row.get("event") in ("harvest", "restart", "seeded", "crashed"):
            run_start = None
            continue
        if tint == "dark":
            run_start = run_start or at
        elif tint in PHYTO_TINTS:
            run_start = None
    if run_start is None:
        return 0.0
    return round(max(0.0, (now - run_start).total_seconds() / 86400.0), 1)


def _phyto_state(jar: dict[str, Any], state: dict[str, Any], species: dict[str, Any],
                 cad: dict[str, float], started: datetime, fresh_anchor: datetime,
                 now: datetime, out: dict[str, Any]) -> dict[str, Any]:
    """The phyto vessel's clocks (doc §5.2) — light, not food. ``establishing``
    is the first cycle (seeded, not yet dark or a week old); ``producing`` from
    the first split, or the moment a tap says DARK (ready on a sign — the
    restart-on-a-sign shape inverted). Clocks: ``look`` (daily tint tap),
    ``harvest`` (= the SPLIT: the interval since the last split, brought
    forward by a dark tap), ``restart`` (= the FRESH VESSEL: ``restartCycles``
    splits since the last one, or a sign). No feed, no water change."""
    history = jar.get("history")
    age_days = max(0.0, (now - started).total_seconds() / 86400.0)
    tint = str(state.get("lastTint") or "")
    last_split = _parse_iso(state.get("lastHarvestAt"))
    if last_split is not None and last_split < started:
        last_split = None
    split_anchor = last_split or started
    days_since_split = max(0.0, (now - split_anchor).total_seconds() / 86400.0)
    first_days = _f(species["firstHarvestDays"])
    establishing = last_split is None and age_days < first_days and tint != "dark"
    out["status"] = "establishing" if establishing else "producing"
    interval = max(0.5, _f(cad.get("harvestIntervalDays"), 8.0))
    if last_split is not None:
        out["harvest"] = _due(last_split.isoformat(), None, timedelta(days=interval), now)
    else:
        out["harvest"] = _due(started.isoformat(), None, timedelta(days=first_days), now)
    out["harvest"]["reason"] = "cap" if out["harvest"]["due"] else None
    if tint == "dark" and not establishing:
        out["harvest"].update({"available": True, "due": True, "hoursUntil": 0.0,
                               "at": now.isoformat() if not out["harvest"].get("due") else out["harvest"]["at"],
                               "reason": "dark"})
    restart_cycles = _f(cad.get("restartCycles"))
    backup_of = str(state.get("backupOf") or "")
    out["backupOf"] = backup_of
    out["refresh"] = {"available": False, "due": False, "at": None, "hoursUntil": None, "hoursOverdue": None,
                      "reason": None}
    if backup_of:
        # B (doc §5.8, Stage B): a windowsill bottle seeded by A's split and
        # refreshed from A every restartCycles splits (a week at the least).
        # The calendar never asks B for a split — only a dark look does.
        refresh_days = max(BACKUP_REFRESH_MIN_DAYS, interval * (restart_cycles if restart_cycles > 0 else 4.0))
        out["refresh"] = _due(None, started.isoformat(), timedelta(days=refresh_days), now)
        out["refresh"]["reason"] = "backup" if out["refresh"]["due"] else None
        out["refresh"]["everyDays"] = round(refresh_days, 1)
        if out["harvest"].get("reason") == "cap":
            out["harvest"].update({"due": False, "reason": None, "hoursOverdue": 0.0})
    # A sign since the last fresh vessel brings it forward and blocks the
    # split until a tint tap after the sign says green or dark (doc §5.3).
    sign_at = _parse_iso(state.get("lastSignAt"))
    signed = sign_at is not None and fresh_anchor <= sign_at <= now
    ok_after_sign = False
    if signed:
        for at, row in _chronological(history):
            if at > sign_at and str(row.get("tint") or "") in ("green", "dark"):
                ok_after_sign = True
                break
    out["harvestBlocked"] = (signed and not ok_after_sign) or tint == "off"
    cycles = int(max(0.0, _f(state.get("cyclesSinceFresh"))))
    if restart_cycles > 0:
        due = cycles >= restart_cycles
        left = max(0.0, restart_cycles - cycles)
        at = now if due else split_anchor + timedelta(days=interval * max(1.0, left))
        delta_h = (at - now).total_seconds() / 3600.0
        out["restart"] = {"available": True, "due": due, "at": at.isoformat(),
                          "hoursUntil": round(max(0.0, delta_h), 1), "hoursOverdue": 0.0,
                          "reason": "cycles" if due else None}
        out["percent"] = round(min(100.0, 100.0 * cycles / restart_cycles))
    if signed:
        out["restart"].update({"available": True, "due": True, "hoursUntil": 0.0, "at": sign_at.isoformat(),
                               "hoursOverdue": round((now - sign_at).total_seconds() / 3600, 1),
                               "reason": "sign"})
    out["look"] = _due(state.get("lastLookedAt"), state.get("startedAt"), timedelta(hours=PHYTO_LOOK_H), now)
    out["feed"]["skipped"] = False
    out["clearingSlow"] = False
    out["waterChangeOnDemand"] = False
    dark_days = _dark_run_days(history, split_anchor, now)
    out["cycle"] = {"day": round(days_since_split, 1), "ofDays": round(interval, 1),
                    "percent": round(min(100.0, 100.0 * days_since_split / interval))}
    out["daysSinceSplit"] = round(days_since_split, 1)
    out["darkDays"] = dark_days
    out["peakHeld"] = dark_days >= PHYTO_PEAK_HELD_DAYS and not establishing
    out["cyclesSinceFresh"] = cycles
    out["restartCycles"] = restart_cycles
    out["workingL"] = round(_f(state.get("workingL")) or _f(jar.get("volumeL")), 2)
    out["mode"] = str(jar.get("mode") or "batch") if str(jar.get("mode") or "") in PHYTO_MODES else "batch"
    out["splitEligible"] = (not establishing and tint in ("green", "dark") and not out["harvestBlocked"])
    chores = []
    for key in ("look", "harvest", "restart", "refresh"):
        clock = out[key]
        if clock.get("available") and clock.get("at"):
            chores.append((0 if clock["due"] else 1, clock["at"], key))
    if chores:
        chores.sort()
        _rank, at, key = chores[0]
        out["nextChore"] = {"key": key, "at": at, "due": out[key]["due"], "hoursUntil": out[key]["hoursUntil"]}
    return out


def density_advice(tint: Any, st: dict[str, Any], days_to_dark: Any = None) -> dict[str, Any]:
    """The phyto vessel's ``feed_advice`` sibling (doc §5.2): what the colour
    asks for. ``split_now`` on dark (and louder when held at peak), ``hold``
    on off-colour or a blocking sign, ``wait`` while it greens. Tint and
    elapsed days do not count cells — the copy says so, once, in the tile."""
    tint = str(tint or "")
    status = str(st.get("status") or "")
    if status not in ("establishing", "producing"):
        return {"action": "none", "reason": ""}
    days_since = _f(st.get("daysSinceSplit"))
    interval = _f((st.get("cycle") or {}).get("ofDays"), 8.0)
    expect = _f(days_to_dark) if _f(days_to_dark) > 0 else interval
    remaining = max(0.0, expect - days_since)
    if st.get("harvestBlocked") or tint == "off":
        return {"action": "hold",
                "reason": ("off-colour — do not harvest into anything; check the smell, the light and the "
                           "temperature. Not recovered in two days? mark it crashed and reseed from B")}
    if tint == "dark":
        if st.get("peakHeld"):
            return {"action": "split_now",
                    "reason": (f"dark for {_f(st.get('darkDays')):g} days without a split — a culture held at "
                               "peak turns; split now, or dose more of it")}
        return {"action": "split_now", "reason": "dark — split now: the bottle, the tank, the drip"}
    if tint == "green":
        return {"action": "wait", "reason": f"growing — dark in ~{remaining:.0f} d" + (" (your own record)" if _f(days_to_dark) > 0 else "")}
    if tint == "pale":
        if days_since < 3:
            return {"action": "wait", "reason": "pale — recovering after the split; light and air, nothing else"}
        if days_since >= expect:
            return {"action": "check", "reason": f"still pale at day {days_since:.0f} — check the light, the air and whether f/2 went in"}
        return {"action": "wait", "reason": f"pale — greening; dark in ~{remaining:.0f} d if the light holds"}
    return {"action": "check", "reason": "no colour logged yet — look at it against a white card"}


def darkening_samples(history: Any) -> list[float]:
    """Days from a seed or a split to the first DARK tap after it — how fast
    the vessel darkens under its light. A split, a fresh vessel or a crash
    before it darkened voids that sample. Newest first, capped at a month."""
    samples: list[float] = []
    anchor: datetime | None = None
    for at, row in _chronological(history):
        event = row.get("event")
        if event in ("seeded", "harvest", "restart"):
            anchor = at
            continue
        if event == "crashed":
            anchor = None
            continue
        if anchor is not None and str(row.get("tint") or "") == "dark":
            days = (at - anchor).total_seconds() / 86400.0
            if 0 < days <= 30:
                samples.append(round(days, 1))
            anchor = None
    samples.reverse()
    return samples


def split_guide(jar: dict[str, Any], mix_ppt: Any = 35.0, ml: Any = None,
                fresh_ml: Any = None) -> dict[str, Any]:
    """The split jug (doc §4.2, §5.3): what comes out (default the split
    percentage of the WORKING volume), what goes in as fresh water at the
    vessel's salinity (default like-for-like; more = a SCALE-UP, the working
    volume moves), and the f/2 that rides the fresh water only — never the
    whole vessel, never mid-cycle. Refused above the working volume and when
    the container would overflow; warned when the seed left behind is thin."""
    cad = cadence_for(jar.get("species"), jar.get("cadence"))
    preset = species_preset(jar.get("species"))
    state = jar.get("state") if isinstance(jar.get("state"), dict) else {}
    working_ml = max(0.0, (_f(state.get("workingL")) or _f(jar.get("volumeL"))) * 1000.0)
    container_ml = max(working_ml, _f(jar.get("volumeL")) * 1000.0)
    out_ml = round(_f(ml, working_ml * cad["harvestPct"] / 100.0), 1)
    fresh = round(_f(fresh_ml, out_ml), 1)
    after = working_ml - out_ml + fresh
    removal_pct = out_ml / working_ml * 100.0 if working_ml > 0 else 0.0
    refill = refill_guide(fresh / 1000.0, 100, jar.get("salinityPpt"), mix_ppt)
    nutrient = jar.get("nutrient") if isinstance(jar.get("nutrient"), dict) else {}
    per_l = _f(nutrient.get("mlPerL"))
    if per_l <= 0:
        per_l = _f(preset.get("nutrientMlPerL"), 1.5)
    nutrient_ml = round(fresh / 1000.0 * per_l, 1)
    warning = ""
    if working_ml > 0 and removal_pct > PHYTO_SPLIT_WARN_PCT:
        warning = (f"a {removal_pct:.0f} % split leaves a thin seed — 50–70 % is the rule; "
                   "expect a slower return to dark")
    out: dict[str, Any] = {
        **refill, "totalMl": out_ml, "outMl": out_ml, "freshMl": fresh, "refillMl": fresh,
        "nutrientMl": nutrient_ml, "nutrientMlPerL": per_l,
        "workingMlBefore": round(working_ml), "workingMlAfter": round(after),
        "containerMl": round(container_ml), "scaleUp": fresh > out_ml + 0.5,
        "removalPct": round(removal_pct, 1), "seedPct": round(max(0.0, 100.0 - removal_pct), 1),
        "warning": warning, "purgeMl": 0.0,
    }
    if working_ml <= 0:
        out.update({"available": False, "reason": "Set the vessel's working volume first."})
    elif out_ml < 0 or (out_ml <= 0 and fresh <= 0):
        out.update({"available": False, "reason": "Enter a positive split volume, or fresh water for a scale-up."})
    elif out_ml > working_ml + 0.5:
        out.update({"available": False, "reason": f"The vessel only holds {working_ml / 1000:g} L of culture."})
    elif after > container_ml + 0.5:
        out.update({"available": False, "reason": f"The container holds {container_ml / 1000:g} L — {after / 1000:.2f} L would overflow."})
    return out


def seed_guide(jar: dict[str, Any], mix_ppt: Any = 35.0, starter_ml: Any = None,
               working_l: Any = None) -> dict[str, Any]:
    """The day the starter lands (doc §5.3, §5.11): the starter into new water
    at the vessel's salinity with f/2 by the NEW water. Default = the starter
    page's 1:4 (250 ml into 1 L, 1.25 L working); ``working_l`` overrides it —
    the kit's 3.5 L is the same card's alternative. Refused past the container."""
    preset = species_preset(jar.get("species"))
    state = jar.get("state") if isinstance(jar.get("state"), dict) else {}
    starter = _f(starter_ml)
    if starter <= 0:
        starter = _f(jar.get("starterMl")) or _f(preset.get("starterMl"), 250.0)
    container_ml = _f(jar.get("volumeL")) * 1000.0
    working = _f(working_l)
    if working <= 0:
        # The recipe's default; a small container (a windowsill B) caps it —
        # the ratio is a recipe, the container is a fact.
        working = round(starter * (1.0 + PHYTO_SEED_RATIO) / 1000.0, 2)
        if container_ml > 0 and working * 1000.0 > container_ml:
            working = round(container_ml / 1000.0, 2)
    working_ml = working * 1000.0
    fresh = max(0.0, working_ml - starter)
    refill = refill_guide(fresh / 1000.0, 100, jar.get("salinityPpt"), mix_ppt)
    nutrient = jar.get("nutrient") if isinstance(jar.get("nutrient"), dict) else {}
    per_l = _f(nutrient.get("mlPerL"))
    if per_l <= 0:
        per_l = _f(preset.get("nutrientMlPerL"), 1.5)
    out: dict[str, Any] = {
        **refill, "starterMl": round(starter), "freshMl": round(fresh), "workingMl": round(working_ml),
        "workingL": round(working, 2), "containerMl": round(container_ml),
        "nutrientMl": round(fresh / 1000.0 * per_l, 1), "nutrientMlPerL": per_l,
        "ratio": round(fresh / starter, 1) if starter > 0 else None,
        "kitWorkingL": _f(preset.get("kitWorkingL"), 3.5),
    }
    if container_ml > 0 and working_ml > container_ml + 0.5:
        out.update({"available": False, "reason": f"The container holds {container_ml / 1000:g} L — set a smaller working volume."})
    del state
    return out


def home_dose_ml(tank_l: Any) -> float:
    """The home bottle's first hand dose (§4.1): one faint tint of the display
    from a dark home culture — an ESTIMATE the keeper raises or lowers against
    the glass. 52 L → ~35 ml."""
    litres = max(0.0, _f(tank_l))
    if litres <= 0:
        return 0.0
    return float(max(1.0, round(litres * 1000.0 * TINT_CELLS_PER_ML / HOME_CULTURE_CELLS_PER_ML_ESTIMATE)))


def sizing_line(working_l: Any, split_pct: Any, interval_days: Any, demand_ml_day: Any,
                customers: str = "") -> dict[str, Any]:
    """§4.1 / §5.11 — the line that bites first: what this vessel makes a day
    on its split cadence against what the rack drinks (the bottle's hand
    dose, the drip, later the cone). Advice, never a number pretending to be
    a count: a 3.5 L vessel out-produces a hand-dosed 52 L tank 5–10×."""
    working = max(0.0, _f(working_l))
    pct = max(0.0, _f(split_pct))
    interval = max(0.5, _f(interval_days, 8.0))
    per_day = working * 1000.0 * pct / 100.0 / interval
    demand = max(0.0, _f(demand_ml_day))
    if working <= 0 or pct <= 0:
        return {"available": False, "yieldMlDay": None, "demandMlDay": demand or None, "ratio": None, "idealL": None, "line": ""}
    cadence = f"at a {pct:g} % split every {interval:g} days"
    if demand <= 0:
        return {"available": True, "yieldMlDay": round(per_day), "demandMlDay": None, "ratio": None, "idealL": None,
                "line": (f"this vessel makes ~{per_day:.0f} ml a day {cadence} — set the home bottle's hand "
                         "dose and this line says what the rack drinks")}
    ratio = per_day / demand
    ideal = max(0.5, demand / (pct / 100.0 / interval) / 1000.0)
    who = f" ({customers})" if customers else ""
    if ratio > 1.5:
        verdict = (f"{ratio:.0f}× more than it needs — run it at ~{ideal:.1f} L, or scale up when the drip "
                   "or the cone drinks it; the bottle absorbs the difference for three weeks")
    elif ratio < 0.7:
        verdict = f"less than it needs — scale up at the next split (~{ideal:.1f} L would cover it)"
    else:
        verdict = "about right"
    return {"available": True, "yieldMlDay": round(per_day), "demandMlDay": round(demand), "ratio": round(ratio, 1),
            "idealL": round(ideal, 2),
            "line": f"the rack drinks ~{demand:.0f} ml a day{who}; this vessel makes ~{per_day:.0f} {cadence} — {verdict}"}


def starter_state(opened_iso: Any, shelf_days: Any, now: datetime) -> dict[str, Any]:
    """The starter bottle's own four-week clock (Reefphyto: use within four
    weeks) — advisory, the same shape as every other freshness clock."""
    opened = _parse_iso(opened_iso)
    shelf = max(0.0, _f(shelf_days))
    if opened is None or opened > now or shelf <= 0:
        return {"available": False, "status": "unknown", "daysLeft": None, "ageDays": None}
    age = (now - opened).total_seconds() / 86400.0
    left = shelf - age
    status = "stale" if left <= 0 else "aging" if left <= shelf * 0.25 else "fresh"
    return {"available": True, "status": status, "daysLeft": round(max(0.0, left), 1), "ageDays": round(age, 1)}


def _hhmm(value: Any, default: str) -> tuple[int, int]:
    """'HH:MM' → (h, m); junk falls back to the default."""
    for cand in (value, default):
        try:
            h, m = str(cand).strip().split(":")[:2]
            h, m = int(h), int(m)
            if 0 <= h <= 23 and 0 <= m <= 59:
                return h, m
        except (TypeError, ValueError, AttributeError):
            continue
    return 0, 0


def _last_at(now_local: datetime, hhmm: Any, default: str) -> datetime:
    """The most recent occurrence of a local clock time at or before now."""
    h, m = _hhmm(hhmm, default)
    at = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
    return at if at <= now_local else at - timedelta(days=1)


def _next_at(after: datetime, hhmm: Any, default: str) -> datetime:
    """The first occurrence of a local clock time strictly after ``after``."""
    h, m = _hhmm(hhmm, default)
    at = after.replace(hour=h, minute=m, second=0, microsecond=0)
    return at if at > after else at + timedelta(days=1)


def sun_day(sun: Any, now: datetime) -> dict[str, Any]:
    """HA's sun entity read for the vessel (doc §5.6): from the two FUTURE
    stamps it carries (next_rising, next_setting) — day when the setting comes
    first, night otherwise — the astronomical day length and the sunset the
    lamp's window hangs off: the LAST sunset at night (the window may be
    open), the coming one by day. Never a guess: no stamps, ``available``
    False. Daylight is an upper bound of what the rack's window gives."""
    sun = sun if isinstance(sun, dict) else {}
    rising = _parse_iso(sun.get("next_rising"))
    setting = _parse_iso(sun.get("next_setting"))
    if rising is None or setting is None:
        return {"available": False, "isDay": None, "daylightH": None, "sunsetAt": None,
                "sunriseAt": None, "nextSunsetAt": None}
    day = setting < rising
    if day:
        daylight_h = (setting - (rising - timedelta(days=1))).total_seconds() / 3600.0
        window_sunset = setting
    else:
        daylight_h = (setting - rising).total_seconds() / 3600.0
        window_sunset = setting - timedelta(days=1)
    daylight_h = max(0.0, min(24.0, daylight_h))
    return {"available": True, "isDay": day, "daylightH": round(daylight_h, 2),
            "sunsetAt": window_sunset.isoformat(), "sunriseAt": rising.isoformat(),
            "nextSunsetAt": setting.isoformat()}


def light_window(light: Any, target_h: Any, now_local: datetime, sun: Any = None) -> dict[str, Any]:
    """The plug's window today (doc §5.6). ``lamp``: on at ``onAt`` for the
    target hours. ``sun+lamp``: on at SUNSET, off when daylight + lamp = the
    target, never past ``latestOff`` — with no sun reading the lamp falls back
    to the ``lamp`` rule and says so. ``sun``: no window. ``now_local`` sets
    the zone the clock times are read in. Pure — the tick and the card both
    ask this, so they can never disagree."""
    light = light if isinstance(light, dict) else {}
    mode = str(light.get("mode") or "sun")
    mode = mode if mode in LIGHT_MODES else "sun"
    target = max(0.0, min(24.0, _f(target_h, 16.0)))
    tz = now_local.tzinfo
    day = sun_day(sun, now_local) if mode == "sun+lamp" else {"available": False}
    out: dict[str, Any] = {"mode": mode, "targetH": target, "plannedLampH": 0.0, "onAt": None, "offAt": None,
                           "active": False, "over": False, "rule": "none", "sunAvailable": bool(day.get("available")),
                           "daylightH": day.get("daylightH")}
    if mode == "sun" or target <= 0:
        return out
    if mode == "sun+lamp" and day.get("available"):
        sunset = _parse_iso(day["sunsetAt"]).astimezone(tz)
        lamp_h = max(0.0, target - _f(day["daylightH"]))
        out["plannedLampH"] = round(lamp_h, 2)
        out["rule"] = "sunset"
        if lamp_h <= 0:
            out["rule"] = "sun_enough"
            return out
        off = sunset + timedelta(hours=lamp_h)
        cap = _next_at(sunset, light.get("latestOff"), LIGHT_LATEST_OFF_DEFAULT)
        if cap < off:
            off = cap
            out["rule"] = "latest_off"
            out["plannedLampH"] = round((off - sunset).total_seconds() / 3600.0, 2)
        on = sunset
    else:
        on = _last_at(now_local, light.get("onAt"), LIGHT_ON_AT_DEFAULT)
        off = on + timedelta(hours=target)
        out["plannedLampH"] = round(target, 2)
        out["rule"] = "on_at" if mode == "lamp" else "on_at_fallback"
    out["onAt"] = on.isoformat()
    out["offAt"] = off.isoformat()
    out["active"] = on <= now_local < off
    out["over"] = now_local >= off
    return out


def _lamp_minutes_today(state: dict[str, Any], now_local: datetime) -> float:
    """Own stamps only: the minutes banked today plus the burst still running,
    counted from local midnight when it started yesterday."""
    today = now_local.date().isoformat()
    minutes = _f(state.get("lightMinutesToday")) if str(state.get("lightDay") or "") == today else 0.0
    on_at = _parse_iso(state.get("lightOnAt"))
    if on_at is not None:
        on_local = on_at.astimezone(now_local.tzinfo)
        midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start = max(on_local, midnight)
        if start < now_local:
            minutes += (now_local - start).total_seconds() / 60.0
    return max(0.0, minutes)


def light_state(jar: dict[str, Any], cad: dict[str, float], now_local: datetime, sun: Any = None,
                plug_state: Any = None) -> dict[str, Any]:
    """The vessel's light as the card says it (doc §5.6): the mode, today's
    daylight (astronomical), the lamp's window and what it delivered (own
    stamps), the short-day nudge, the lamp-off watch, the lost-day act.
    ``plug_state`` is the switch's state string (on / off / unavailable /
    None = no entity). Advisory: the tick decides from light_window."""
    light = jar.get("light") if isinstance(jar.get("light"), dict) else {}
    state = jar.get("state") if isinstance(jar.get("state"), dict) else {}
    mode = str(light.get("mode") or "sun")
    mode = mode if mode in LIGHT_MODES else "sun"
    plug = str(light.get("switchEntity") or "")
    target = max(0.0, min(24.0, _f(cad.get("lightHours"), 16.0)))
    day = sun_day(sun, now_local)
    window = light_window(light, target, now_local, sun)
    lamp_min = _lamp_minutes_today(state, now_local) if mode != "sun" and plug else 0.0
    lamp_h = round(lamp_min / 60.0, 2)
    daylight = _f(day.get("daylightH")) if day.get("available") else None
    counts_sun = mode in ("sun", "sun+lamp")
    delivered = round(lamp_h + (daylight or 0.0), 1) if (counts_sun and daylight is not None) or mode == "lamp" else None
    plug_on = str(plug_state or "") == "on"
    lit = bool((counts_sun and day.get("isDay")) or plug_on)
    status, line, nudge = "ok", "", ""
    hours_in = None
    if window.get("active"):
        hours_in = round((now_local - _parse_iso(window["onAt"]).astimezone(now_local.tzinfo)).total_seconds() / 3600.0, 1)
    if mode == "sun":
        if daylight is None:
            status, line = "unknown", "daylight unknown — no sun entity to read"
        elif daylight < LIGHT_SHORT_DAY_H:
            status = "watch"
            line = f"daylight {daylight:.1f} h (astronomical — the window gives less)"
            nudge = f"the days are under {LIGHT_SHORT_DAY_H:g} h — put the LED on the plug"
        elif daylight < target:
            status = "watch"
            line = f"daylight {daylight:.1f} h (astronomical — the window gives less) — under the {target:g} h target"
        else:
            line = f"daylight {daylight:.1f} h (astronomical — the window gives less)"
    else:
        if not plug:
            status, line = "watch", "no plug bound — bind the LED's switch in Culture settings"
        elif window.get("active") and not plug_on:
            status = "watch"
            what = "unavailable" if str(plug_state or "") in ("unavailable", "unknown", "") else "off"
            line = f"lamp {what} {hours_in:g} h into its window"
        elif window.get("over") and delivered is not None and delivered < LIGHT_LOST_DAY_H:
            status = "act"
            line = f"{delivered:g} h of light today — the culture lost a day of light; expect the split to slip"
        if mode == "sun+lamp":
            if daylight is None:
                sun_words = "no sun entity — the lamp runs on its on-at time instead"
                if status == "ok":
                    status = "watch"
            else:
                sun_words = f"daylight {daylight:.1f} h (astronomical — the window gives less)"
            plan = window.get("plannedLampH") or 0.0
            when = ""
            if window.get("onAt") and window.get("offAt"):
                on_l = _parse_iso(window["onAt"]).astimezone(now_local.tzinfo)
                off_l = _parse_iso(window["offAt"]).astimezone(now_local.tzinfo)
                when = f" from sunset {on_l.strftime('%H:%M')} → {off_l.strftime('%H:%M')}" if window["rule"] in ("sunset", "latest_off") \
                    else f" {on_l.strftime('%H:%M')} → {off_l.strftime('%H:%M')}"
            lamp_words = (f"lamp {plan:.1f} h{when}" if plan > 0 else "the sun alone reaches the target — the lamp stays off")
            if window["rule"] == "latest_off":
                lamp_words += f" (capped at {str(light.get('latestOff') or LIGHT_LATEST_OFF_DEFAULT)})"
            readout = f"{sun_words} · {lamp_words} · {lamp_h:.1f} h lamp so far"
        else:
            on_l = _parse_iso(window["onAt"]).astimezone(now_local.tzinfo) if window.get("onAt") else None
            off_l = _parse_iso(window["offAt"]).astimezone(now_local.tzinfo) if window.get("offAt") else None
            readout = (f"lamp {target:g} h {on_l.strftime('%H:%M')} → {off_l.strftime('%H:%M')} · {lamp_h:.1f} h so far"
                       if on_l and off_l else f"lamp {target:g} h a day")
        line = f"{readout}" + (f" — {line}" if line else "")
    return {"mode": mode, "switchEntity": plug, "tempEntity": str(light.get("tempEntity") or ""),
            "targetH": target, "daylightH": daylight, "sunAvailable": bool(day.get("available")),
            "isDay": day.get("isDay"), "sunsetAt": day.get("sunsetAt"), "sunriseAt": day.get("sunriseAt"),
            "lampH": lamp_h, "deliveredH": delivered, "plannedLampH": window.get("plannedLampH"),
            "window": {"onAt": window.get("onAt"), "offAt": window.get("offAt"), "active": bool(window.get("active")),
                       "over": bool(window.get("over")), "rule": window.get("rule"), "hoursIn": hours_in},
            "plugState": str(plug_state) if plug_state is not None else "", "plugOn": plug_on, "lit": lit,
            "shortDay": bool(daylight is not None and daylight < LIGHT_SHORT_DAY_H),
            "status": status, "line": line, "nudge": nudge,
            "aerationNote": "Air is never switched — a still culture settles and dies; only the lamp rides the plug."}


def light_samples(history: Any, days: int = 7) -> list[float]:
    """Hours of light delivered per day, from the daily ``light`` rows the
    tick writes (lamp by own stamps + astronomical daylight). Newest first."""
    rows = [(at, row) for at, row in _chronological(history) if row.get("event") == "light" and not row.get("undoneAt")]
    rows.sort(key=lambda item: item[0], reverse=True)
    out = []
    for _at, row in rows[:days]:
        hours = row.get("lightH")
        if isinstance(hours, (int, float)) and not isinstance(hours, bool) and math.isfinite(hours):
            out.append(round(float(hours), 1))
    return out


def darkening_by_depth(history: Any) -> dict[str, Any]:
    """Recovery by split depth (doc §5.10, the purge_note shape): the days to
    the first dark tap after a split, grouped by how much came out. Two runs
    at each of two depths before it speaks; it never claims a cause."""
    buckets: dict[str, list[float]] = {}
    anchor: tuple[datetime, str] | None = None
    for at, row in _chronological(history):
        event = row.get("event")
        if event in ("harvest", "restart"):
            ml = _f(row.get("ml"))
            after = _f(row.get("workingMl"))
            before = after - _f(row.get("freshMl")) + ml
            pct = 100.0 * ml / before if before > 0 and ml > 0 else None
            if pct is None:
                anchor = None
                continue
            label = "≤ 50 %" if pct <= 50 else "50–65 %" if pct <= 65 else "> 65 %"
            anchor = (at, label)
            continue
        if event in ("seeded", "crashed"):
            anchor = None
            continue
        if anchor is not None and str(row.get("tint") or "") == "dark":
            days = (at - anchor[0]).total_seconds() / 86400.0
            if 0 < days <= 30:
                buckets.setdefault(anchor[1], []).append(days)
            anchor = None
    spoken = {k: v for k, v in buckets.items() if len(v) >= PURGE_RUNS_MIN}
    if len(spoken) < 2:
        return {"available": False, "line": "", "byDepth": {k: round(sum(v) / len(v), 1) for k, v in buckets.items()}}
    parts = [f"{k} splits took ~{sum(v) / len(v):.0f} d to darken" for k, v in sorted(spoken.items())]
    return {"available": True, "byDepth": {k: round(sum(v) / len(v), 1) for k, v in buckets.items()},
            "line": ", ".join(parts) + " — this does not establish the cause"}


def secchi_samples(history: Any) -> list[dict[str, Any]]:
    """Every Secchi reading with the tint beside it and the days since the
    split (or seed) it belongs to — the stick's calibration data (doc §6).
    A crash ends the cycle; taken-back rows never count. Oldest first."""
    out: list[dict[str, Any]] = []
    anchor: datetime | None = None
    for at, row in _chronological(history):
        event = row.get("event")
        if event in ("seeded", "harvest", "restart"):
            anchor = at
            continue
        if event == "crashed":
            anchor = None
            continue
        cm = row.get("secchiCm")
        if not isinstance(cm, (int, float)) or isinstance(cm, bool) or not math.isfinite(cm) or cm <= 0:
            continue
        days = round((at - anchor).total_seconds() / 86400.0, 2) if anchor is not None else None
        out.append({"at": at.isoformat(), "cm": round(float(cm), 1), "tint": str(row.get("tint") or ""),
                    "days": days if days is not None and 0 <= days <= 30 else None})
    return out


def _median(values: list[float], digits: int = 1) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    return round(ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0, digits)


def secchi_fit(history: Any, cm_now: Any = None) -> dict[str, Any]:
    """The printable stick's calibration (doc §6, Stage C), from the keeper's
    own readings and nothing else. Two halves: the BANDS — the median depth
    at which the vessel read pale, green and dark (two readings at a tint
    before its band is drawn) — and the LOG FIT — Secchi depth falls as the
    culture grows, so ln(cm) against days since the split is a line; its
    slope gives the halving time and, with a dark band, how many days a
    reading of ``cm_now`` is from dark. Four points over two days before
    the fit speaks; a slope that is not downward is reported, never used.
    Cells are never counted: the stick reads depth, the tints are the words."""
    samples = secchi_samples(history)
    by_tint: dict[str, list[float]] = {}
    for smp in samples:
        if smp["tint"] in PHYTO_TINTS and smp["tint"] != "off":
            by_tint.setdefault(smp["tint"], []).append(smp["cm"])
    bands = {tint: _median(vals) if len(vals) >= SECCHI_BAND_MIN_READINGS else None for tint, vals in by_tint.items()}
    counts = {tint: len(vals) for tint, vals in by_tint.items()}
    dark_cm = bands.get("dark")
    green_cm = bands.get("green")
    pale_cm = bands.get("pale")
    stick = None
    ordered = [v for v in (dark_cm, green_cm, pale_cm) if v is not None]
    if len(ordered) >= 2 and ordered == sorted(ordered) and len(set(ordered)) == len(ordered):
        stick = {"darkMaxCm": round((dark_cm + green_cm) / 2.0, 1) if dark_cm is not None and green_cm is not None else None,
                 "greenMaxCm": round((green_cm + pale_cm) / 2.0, 1) if green_cm is not None and pale_cm is not None else None}
        if stick["darkMaxCm"] is None and dark_cm is not None and pale_cm is not None:
            stick["darkMaxCm"] = round((dark_cm + pale_cm) / 2.0, 1)
    points = [(smp["days"], math.log(smp["cm"])) for smp in samples if smp["days"] is not None and smp["cm"] > 0]
    fit: dict[str, Any] = {"available": False, "points": len(points), "slopePerDay": None, "halvingDays": None, "r2": None}
    distinct_days = {round(d, 1) for d, _ in points}
    if len(points) >= SECCHI_FIT_MIN_POINTS and len(distinct_days) >= 2:
        n = float(len(points))
        mx = sum(d for d, _ in points) / n
        my = sum(y for _, y in points) / n
        sxx = sum((d - mx) ** 2 for d, _ in points)
        sxy = sum((d - mx) * (y - my) for d, y in points)
        syy = sum((y - my) ** 2 for _, y in points)
        if sxx > 0:
            slope = sxy / sxx                       # ln(cm) per day; downward while it grows
            r2 = (sxy * sxy) / (sxx * syy) if syy > 0 else 0.0
            fit.update({"slopePerDay": round(slope, 3), "r2": round(r2, 2)})
            if slope < 0:
                fit["available"] = True
                fit["halvingDays"] = round(math.log(2.0) / -slope, 1)
    days_to_dark = None
    now_cm = _f(cm_now)
    if fit["available"] and dark_cm and now_cm > 0:
        days_to_dark = round(max(0.0, math.log(now_cm / dark_cm) / -fit["slopePerDay"]), 1) if now_cm > dark_cm else 0.0
    words: list[str] = []
    if any(v is not None for v in bands.values()):
        named = [f"{tint} ~{bands[tint]:g} cm" for tint in ("dark", "green", "pale") if bands.get(tint) is not None]
        words.append("on your stick: " + ", ".join(named) + f" ({len(samples)} readings)")
    if fit["available"]:
        words.append(f"the depth halves every ~{fit['halvingDays']:g} d ({fit['points']} readings, your fit)")
    if days_to_dark is not None:
        words.append(f"today's {now_cm:g} cm is ~{days_to_dark:g} d from dark" if days_to_dark > 0 else f"today's {now_cm:g} cm is dark on your stick")
    return {"available": bool(words), "readings": len(samples), "bands": bands, "counts": counts,
            "stick": stick, "fit": fit, "daysToDark": days_to_dark, "lastCm": samples[-1]["cm"] if samples else None,
            "line": "Secchi: " + " · ".join(words) if words else ""}


def green_index(sample: Any, reference: Any) -> dict[str, Any]:
    """The green index (doc §6, Stage D): the optical density of the culture
    patch against the white card in the same shot (or a sensor's blank).
    Per channel T = patch / card (a patch brighter than its card reads 0 —
    the card was not lit the same), OD = −log10 T capped at INDEX_OD_MAX;
    the index is the mean of the red and green densities (chlorophyll's
    bands — blue carries nothing and is only reported). ``looksOff`` = green
    absorbed more than red: the patch reads yellow-brown, not green — a hint
    to look, never a sign by itself. Pure; the panel sends channel means,
    the sensor its counts, and this is the only place the maths lives."""
    def chan(src: Any, key: str) -> float:
        val = _f((src or {}).get(key), -1.0) if isinstance(src, dict) else -1.0
        return val if math.isfinite(val) else -1.0
    r, g, b = chan(sample, "r"), chan(sample, "g"), chan(sample, "b")
    rr, rg, rb = chan(reference, "r"), chan(reference, "g"), chan(reference, "b")
    if min(r, g, b) < 0 or min(rr, rg) <= 0 or rb < 0:
        return {"available": False, "reason": "a reading needs the culture patch and the white card, both lit", "od": None,
                "odR": None, "odG": None, "odB": None, "tR": None, "tG": None, "tB": None, "looksOff": False, "brighter": False}
    def od(v: float, ref: float) -> tuple[float, float]:
        if ref <= 0:
            return 1.0, 0.0
        t = max(1e-3, min(1.0, v / ref))
        return round(t, 4), round(min(INDEX_OD_MAX, max(0.0, -math.log10(t))), 3)
    t_r, od_r = od(r, rr)
    t_g, od_g = od(g, rg)
    t_b, od_b = od(b, rb) if rb > 0 else (None, None)
    brighter = (r > rr * 1.05) or (g > rg * 1.05)
    index = round((od_r + od_g) / 2.0, 3)
    return {"available": True, "od": index, "odR": od_r, "odG": od_g, "odB": od_b, "tR": t_r, "tG": t_g, "tB": t_b,
            "looksOff": bool(od_g > od_r + 0.02 and index > 0.05), "brighter": bool(brighter),
            "saturated": bool(index >= INDEX_OD_MAX)}


def index_samples(history: Any) -> list[dict[str, Any]]:
    """Every index reading with the days since the split it belongs to and
    the tint logged with (or nearest before) it. Oldest first; a crash ends
    the cycle; taken-back rows never count."""
    rows = _chronological(history)
    # The tint beside a reading: the keeper's tap nearest in time within half
    # a day (photo then tap, or tap then photo — either order), else the last
    # tint seen before it. A split resets the colour to pale.
    taps = [(at, str(row.get("tint"))) for at, row in rows if str(row.get("tint") or "") in PHYTO_TINTS]
    def tint_for(at: datetime, before: str) -> str:
        near = [(abs((tap_at - at).total_seconds()), tint) for tap_at, tint in taps
                if abs((tap_at - at).total_seconds()) <= 12 * 3600]
        return min(near)[1] if near else before
    out: list[dict[str, Any]] = []
    anchor: datetime | None = None
    tint = ""
    for at, row in rows:
        event = row.get("event")
        if event in ("seeded", "harvest", "restart"):
            anchor = at
            if not row.get("draw"):
                tint = "pale"
            continue
        if event == "crashed":
            anchor = None
            tint = ""
            continue
        if str(row.get("tint") or "") in PHYTO_TINTS:
            tint = str(row.get("tint"))
        if event != "index":
            continue
        od_val = row.get("od")
        if not isinstance(od_val, (int, float)) or isinstance(od_val, bool) or not math.isfinite(od_val) or od_val < 0:
            continue
        days = round((at - anchor).total_seconds() / 86400.0, 2) if anchor is not None else None
        out.append({"at": at.isoformat(), "od": round(float(od_val), 3), "tint": tint_for(at, tint),
                    "source": str(row.get("source") or ""),
                    "days": days if days is not None and 0 <= days <= 30 else None,
                    "looksOff": bool(row.get("looksOff"))})
    return out


def index_fit(history: Any, od_now: Any = None) -> dict[str, Any]:
    """The curve (doc §6): per-tint median index BANDS (two readings beside a
    tint before it has one) — the dark band is what "split now" reads off —
    and the LOG FIT of ln(index) against days since the split: the growth
    rate, the doubling time, and how many days a reading of ``od_now`` is
    from the dark band. Four points over two days, an upward slope only.
    ``readsDark`` = today's index at or over the dark band. Never cells."""
    samples = index_samples(history)
    by_tint: dict[str, list[float]] = {}
    for smp in samples:
        if smp["tint"] in ("pale", "green", "dark"):
            by_tint.setdefault(smp["tint"], []).append(smp["od"])
    bands = {tint: _median(vals, 3) if len(vals) >= INDEX_BAND_MIN_READINGS else None for tint, vals in by_tint.items()}
    counts = {tint: len(vals) for tint, vals in by_tint.items()}
    dark_od = bands.get("dark")
    points = [(smp["days"], math.log(smp["od"])) for smp in samples if smp["days"] is not None and smp["od"] > 0]
    fit: dict[str, Any] = {"available": False, "points": len(points), "ratePerDay": None, "doublingDays": None, "r2": None}
    if len(points) >= INDEX_FIT_MIN_POINTS and len({round(d, 1) for d, _ in points}) >= 2:
        n = float(len(points))
        mx = sum(d for d, _ in points) / n
        my = sum(y for _, y in points) / n
        sxx = sum((d - mx) ** 2 for d, _ in points)
        sxy = sum((d - mx) * (y - my) for d, y in points)
        syy = sum((y - my) ** 2 for _, y in points)
        if sxx > 0:
            slope = sxy / sxx
            fit.update({"ratePerDay": round(slope, 3), "r2": round((sxy * sxy) / (sxx * syy), 2) if syy > 0 else 0.0})
            if slope > 0:
                fit["available"] = True
                fit["doublingDays"] = round(math.log(2.0) / slope, 1)
    now_od = _f(od_now, -1.0)
    days_to_dark = None
    reads_dark = None
    if dark_od and now_od >= 0:
        reads_dark = now_od >= dark_od
        if fit["available"] and now_od > 0:
            days_to_dark = 0.0 if reads_dark else round(math.log(dark_od / now_od) / fit["ratePerDay"], 1)
    words: list[str] = []
    if any(v is not None for v in bands.values()):
        named = [f"{tint} ~{bands[tint]:g}" for tint in ("pale", "green", "dark") if bands.get(tint) is not None]
        words.append("your index: " + ", ".join(named) + f" ({len(samples)} readings)")
    if fit["available"]:
        words.append(f"it doubles every ~{fit['doublingDays']:g} d ({fit['points']} readings, your fit)")
    if reads_dark:
        words.append(f"today's {now_od:g} reads dark — look, then split")
    elif days_to_dark is not None:
        words.append(f"today's {now_od:g} is ~{days_to_dark:g} d from dark")
    elif now_od >= 0 and not words:
        words.append(f"today's index {now_od:g} — the bands come with the tints you log beside it")
    return {"available": bool(samples), "readings": len(samples), "bands": bands, "counts": counts, "darkOd": dark_od,
            "fit": fit, "daysToDark": days_to_dark, "readsDark": reads_dark, "lastOd": samples[-1]["od"] if samples else None,
            "lastAt": samples[-1]["at"] if samples else None, "lastSource": samples[-1]["source"] if samples else "",
            "looksOff": bool(samples and samples[-1]["looksOff"]),
            "line": "Index: " + " · ".join(words) if words else ""}


def index_dark_days(history: Any, now: datetime) -> float:
    """Days the index has read at or over the dark band without a split —
    the peak-held clock off the curve. 0 without a dark band."""
    fit = index_fit(history)
    dark_od = fit.get("darkOd")
    if not dark_od:
        return 0.0
    run_start: datetime | None = None
    for at, row in _chronological(history):
        if at > now:
            continue
        if row.get("event") in ("harvest", "restart", "seeded", "crashed") and not row.get("draw"):
            run_start = None
            continue
        if row.get("event") != "index":
            continue
        od_val = _f(row.get("od"), -1.0)
        if od_val >= dark_od:
            run_start = run_start or at
        elif od_val >= 0:
            run_start = None
    return round(max(0.0, (now - run_start).total_seconds() / 86400.0), 1) if run_start else 0.0


def estimate_cells(od: Any, calibration: Any) -> dict[str, Any]:
    """Cells per ml from an index reading, ONLY through the keeper's own count
    (doc §7: never a figure without a count or a calibrated index): a count of
    N at an index of X makes today's index Y worth N × Y / X — Beer–Lambert's
    straight line, labelled an estimate and dated to the count."""
    cal = calibration if isinstance(calibration, dict) else {}
    cells = _f(cal.get("cellsPerMl"))
    cal_od = _f(cal.get("od"))
    od_now = _f(od, -1.0)
    if cells <= 0 or cal_od <= 0 or od_now < 0:
        return {"available": False, "cellsPerMl": None, "factor": None, "calibratedAt": str(cal.get("at") or ""), "note": ""}
    factor = cells / cal_od
    est = round(od_now * factor)
    return {"available": True, "cellsPerMl": float(est), "factor": round(factor), "calibratedAt": str(cal.get("at") or ""),
            "calibrationOd": round(cal_od, 3), "calibrationCells": cells,
            "note": f"~{est:,.0f} cells/ml, estimated from your count of {cells:,.0f} at an index of {cal_od:g}"}


def ph_trend(history: Any, days: int = PH_TREND_DAYS) -> dict[str, Any]:
    """The vessel's pH as the cheapest "is it alive" signal (doc §6): the
    daily maxima the tick banks — rising while it grows, flat at stationary
    (split), falling on a crash. Advice only; two days before it speaks."""
    rows = [(at, row) for at, row in _chronological(history) if row.get("event") == "light" and not row.get("undoneAt")
            and isinstance(row.get("phMax"), (int, float)) and not isinstance(row.get("phMax"), bool)]
    rows.sort(key=lambda item: item[0])
    recent = rows[-(days + 1):]
    if len(recent) < 2:
        return {"available": False, "trend": "unknown", "line": "", "days": len(recent), "first": None, "last": None}
    first, last = _f(recent[0][1].get("phMax")), _f(recent[-1][1].get("phMax"))
    span_days = max(1.0, (recent[-1][0] - recent[0][0]).total_seconds() / 86400.0)
    per_day = (last - first) / span_days
    if per_day >= PH_FLAT_DELTA:
        trend, line = "rising", f"pH {first:.1f} → {last:.1f} over {span_days:.0f} d — growing"
    elif per_day <= -PH_FLAT_DELTA:
        trend, line = "falling", f"pH falling {first:.1f} → {last:.1f} over {span_days:.0f} d — a crash? look at it, smell it"
    else:
        trend, line = "flat", f"pH flat at ~{last:.1f} — stationary; a culture that has stopped climbing is ready to split"
    return {"available": True, "trend": trend, "line": line, "days": len(recent), "first": round(first, 2), "last": round(last, 2),
            "perDay": round(per_day, 3)}


def daily_draw_pct(split_pct: Any, days_to_dark: Any) -> float:
    """The semi-continuous draw (doc §5.2): the daily fraction that matches
    the batch cycle's growth, held to the guide's 20–30 % a day."""
    pct = max(10.0, min(90.0, _f(split_pct, 60.0)))
    days = max(1.0, _f(days_to_dark, 8.0))
    daily = 100.0 * (1.0 - (1.0 - pct / 100.0) ** (1.0 / days))
    return float(round(max(20.0, min(30.0, daily))))


def feed_advice(tint: Any, feed_clock: dict[str, Any], harvest_clock: Any = None,
                harvest_interval_h: Any = None, species_id: Any = "rotifer_L") -> dict[str, Any]:
    """Inspection and feeding advice from reported tint and chore clocks.
    A rotifer jar missing two harvests needs its water exchange checked first.
    Tint and elapsed time do not measure population, oxygen or ammonia."""
    tint = str(tint or "")
    due = bool(feed_clock.get("due"))
    if species_preset(species_id)["kind"] == "rotifer" and isinstance(harvest_clock, dict) and harvest_clock.get("due") and _f(harvest_interval_h) > 0 \
            and _f(harvest_clock.get("hoursOverdue")) >= _f(harvest_interval_h):
        return {"action": "harvest_first",
                "reason": "two harvests missed — check activity and water quality; a healthy rotifer jar needs its harvest and refill"}
    if tint == "clear":
        return {"action": "feed_now", "reason": "clear water — check activity, then feed lightly if the culture is healthy"}
    if tint == "green":
        return {"action": "skip" if due else "wait",
                "reason": "still green — check before adding more food; overfeeding can worsen water quality"}
    if tint == "clearing":
        return {"action": "feed_now" if due else "wait",
                "reason": "clearing — feed on schedule"}
    return {"action": "check" if due else "wait", "reason": "no tint logged yet — inspect the water before feeding"}


def temperature_advice(temp_c: Any, species_id: Any) -> dict[str, Any]:
    """Advisory only: where the room sits against the species band. ``hot`` is
    the warning line, ``critical`` the line above which the copy stops
    advising and tells the keeper to move the culture; ``act`` flags the
    middle tier (warn 28 / act 30 / critical 32 for Tigriopus).
    These precautionary tiers do not measure animal tolerance or water quality."""
    species = species_preset(species_id)
    base = {"minC": species["tempMinC"], "maxC": species["tempMaxC"],
            "hardMaxC": species["tempHardMaxC"],
            "actC": species.get("tempActC", species["tempHardMaxC"]),
            "criticalC": species.get("tempCriticalC", species["tempHardMaxC"])}
    try:
        t = float(temp_c)
    except (TypeError, ValueError):
        return {"available": False, "status": "unknown", "tempC": None, "act": False, **base}
    if isinstance(temp_c, bool) or not math.isfinite(t) or not -50 <= t <= 60:
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


def refill_guide(volume_l: Any, pct: Any, target_ppt: Any, mix_ppt: Any = 35.0,
                 phyto_ml: Any = None, phyto_ppt: Any = None) -> dict[str, Any]:
    """The measured jug: how much water a fill / harvest / water change moves,
    and — for a brackish jar — how to cut the mixing station's water to hit
    it. ``mix_ppt`` is the station's target (35 unless the keeper set another);
    the split is a straight dilution, RODI counted as 0 ppt. ``sg`` is the
    target on the hobby anchor line, for the refractometer. Stage C (doc
    §4.2): with ``phyto_ml`` at ``phyto_ppt`` the jug goes THREE-WAY — the
    phyto carries its own salt, the station's water and RODI make up the rest
    to the target; more phyto than the target salt allows is refused, never
    fudged (cone at 27 ppt, 675 ml, 350 ml of 35 ppt phyto → 171 mix + 154 RODI)."""
    vol = max(0.0, _f(volume_l))
    frac = min(1.0, max(0.0, _f(pct) / 100.0))
    total_ml = round(vol * frac * 1000.0)
    mix = _f(mix_ppt)
    if mix <= 0:
        mix = 35.0
    target = _f(target_ppt)
    if target > mix:
        return {"available": False, "totalMl": total_ml, "mixMl": 0, "rodiMl": 0,
                "targetPpt": round(target, 1), "mixPpt": round(mix, 1), "sg": sg_from_ppt(target),
                "reason": f"Cannot make {target:g} ppt by diluting {mix:g} ppt water; prepare stronger saltwater and measure it first."}
    if target < 0:
        target = 0.0
    phyto = float(round(min(float(total_ml), max(0.0, _f(phyto_ml))))) if _f(phyto_ml) > 0 else 0.0
    if phyto > 0:
        p_ppt = max(0.0, _f(phyto_ppt, mix))
        water = total_ml - phyto                                  # whole millilitres from here on
        salt_needed = total_ml * target - phyto * p_ppt          # ppt·ml the water must carry
        base = {"totalMl": total_ml, "phytoMl": round(phyto), "phytoPpt": round(p_ppt, 1),
                "targetPpt": round(target, 1), "mixPpt": round(mix, 1), "sg": sg_from_ppt(target)}
        if salt_needed < -0.5:
            most = int(total_ml * target / p_ppt) if p_ppt > 0 else total_ml
            return {**base, "available": False, "mixMl": 0, "rodiMl": round(water),
                    "resultPpt": round(phyto * p_ppt / total_ml, 1) if total_ml else None,
                    "reason": (f"{phyto:g} ml of {p_ppt:g} ppt phyto alone would put the refill over {target:g} ppt — "
                               f"cut the phyto to {most} ml, or refill the whole jar")}
        mix_ml = round(salt_needed / mix)
        if mix_ml > water + 0.5:
            return {**base, "available": False, "mixMl": round(water), "rodiMl": 0,
                    "resultPpt": round((phyto * p_ppt + water * mix) / total_ml, 1) if total_ml else None,
                    "reason": (f"Cannot reach {target:g} ppt with {phyto:g} ml of {p_ppt:g} ppt phyto and {mix:g} ppt water — "
                               "less phyto, or stronger saltwater")}
        mix_ml = min(round(water), max(0, mix_ml))
        return {**base, "mixMl": mix_ml, "rodiMl": round(water) - mix_ml, "resultPpt": round(target, 1)}
    if target == mix:
        return {"totalMl": total_ml, "mixMl": total_ml, "rodiMl": 0, "targetPpt": round(mix, 1),
                "mixPpt": round(mix, 1), "sg": sg_from_ppt(mix)}
    mix_ml = round(total_ml * target / mix)
    return {"totalMl": total_ml, "mixMl": mix_ml, "rodiMl": total_ml - mix_ml,
            "targetPpt": round(target, 1), "mixPpt": round(mix, 1), "sg": sg_from_ppt(target)}


def cone_dose_ml(volume_l: Any) -> float:
    """One tint of an animal jar from a dark home culture (doc §4.1): a
    2.5 L cone to ~1 × 10⁶ cells/ml ≈ 170 ml. An estimate to a leafy green —
    nobody has counted this culture; the keeper raises or lowers it by eye."""
    litres = max(0.1, _f(volume_l, 2.5))
    ml = litres * 1000.0 * CONE_TINT_CELLS_PER_ML / HOME_CULTURE_CELLS_PER_ML_ESTIMATE
    return float(max(10.0, round(ml / 10.0) * 10.0))


def harvest_guide(jar: dict[str, Any], mix_ppt: Any = 35.0, ml: Any = None,
                  phyto_ml: Any = None, phyto_ppt: Any = None) -> dict[str, Any]:
    """Harvest volume is separate from the purge; replace both withdrawals.
    Stage C: ``phyto_ml`` at ``phyto_ppt`` rides the refill (the three-way jug)."""
    cad = cadence_for(jar.get("species"), jar.get("cadence"))
    harvest = round(_f(ml, _f(jar.get("volumeL")) * cad["harvestPct"] * 10), 1)
    purge = max(0.0, _f(jar.get("purgeMl"))) if jar.get("vesselKind") == "cone" else 0.0
    refill = refill_guide((harvest + purge) / 1000, 100, jar.get("salinityPpt"), mix_ppt, phyto_ml, phyto_ppt)
    removal_pct = (harvest + purge) / max(1.0, _f(jar.get("volumeL")) * 1000) * 100
    warning = (f"Harvest plus purge removes {removal_pct:.1f}% of the working volume; "
               "this exceeds the default 25–30% harvest guidance. Reduce the withdrawal and check population recovery.") if removal_pct > 30 else ""
    if removal_pct > 100:
        refill.update({"available": False, "reason": "Harvest plus purge exceeds the vessel's working volume."})
    return {**refill, "totalMl": harvest, "refillMl": refill["totalMl"], "purgeMl": purge,
            "removalPct": round(removal_pct, 1), "warning": warning}


def bottle_state(bottle: dict[str, Any], shelf_days: Any, now: datetime) -> dict[str, Any]:
    """The rotifer fridge bottle's own clock — fail-closed like every other
    freshness clock: a filled bottle with no stamp is stale."""
    remaining = max(0.0, _f(bottle.get("remainingMl")))
    if remaining <= 0:
        return {"status": "empty", "remainingMl": 0.0, "hoursLeft": None, "filledAt": ""}
    filled = _parse_iso(bottle.get("filledAt"))
    shelf_h = max(0.0, _f(shelf_days)) * 24.0
    if filled is None or filled > now or shelf_h <= 0:
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

    # The lit vessels (doc §5.9): a phyto carboy is drawn right of the cones,
    # before the tub — its own list, its own captions, its own jug.
    phyto: list[dict[str, Any]] = []
    for j in jars:
        if str(j.get("kind") or "") != "phyto":
            continue
        st = j.get("state") if isinstance(j.get("state"), dict) else {}
        status = str(st.get("status") or "none")
        running = status in ("establishing", "producing")
        due = set(j.get("due") or [])
        cycle = st.get("cycle") if isinstance(st.get("cycle"), dict) else {}
        first = max(1.0, _f(j.get("firstHarvestDays"), 7.0))
        pct = _f(cycle.get("percent")) if cycle else (min(100.0, 100.0 * _f(st.get("ageDays")) / first) if running else 0.0)
        advice = j.get("densityAdvice") if isinstance(j.get("densityAdvice"), dict) else {}
        temp = j.get("temp") if isinstance(j.get("temp"), dict) else {}
        bottle = j.get("homeBottle") if isinstance(j.get("homeBottle"), dict) else {}
        guide = j.get("splitGuide") if isinstance(j.get("splitGuide"), dict) else {}
        tint = str(j.get("tint") or "") if running else ""
        light = j.get("light") if isinstance(j.get("light"), dict) else {}
        light_on = running and (bool(light.get("lit")) if light.get("mode") in LIGHT_MODES and (light.get("sunAvailable") or light.get("switchEntity")) else True)
        phyto.append({
            "id": str(j.get("id") or ""), "name": str(j.get("name") or ""),
            "kind": str(j.get("vesselKind") or "bottle"), "status": status, "tint": tint,
            "pct": round(pct), "airOn": running, "lightOn": light_on,
            "lightWatch": running and light.get("status") in ("watch", "act"),
            "backup": bool(str(j.get("backupOf") or (st.get("backupOf") or ""))),
            "refreshHot": "refresh" in due,
            "splitHot": "harvest" in due and not st.get("harvestBlocked"),
            "freshHot": "restart" in due, "lookHot": "look" in due,
            "offColour": bool(st.get("harvestBlocked")) or tint == "off",
            "peakHeld": bool(st.get("peakHeld")), "advice": str(advice.get("action") or ""),
            "tempStatus": str(temp.get("status") or "unknown"),
            "establishDays": round(_f(st.get("ageDays"))) if status == "establishing" else None,
            "firstHarvestDays": round(first),
            "cycleDay": round(_f(cycle.get("day"))) if cycle else None,
            "cycleOf": round(_f(cycle.get("ofDays"))) if cycle else None,
            "workingL": _f(st.get("workingL")) or _f(j.get("volumeL")),
            "bottleMl": round(_f(bottle.get("remainingMl"))),
            "bottleStatus": str(((bottle.get("expiry") or {}) if isinstance(bottle.get("expiry"), dict) else {}).get("status") or ("empty" if _f(bottle.get("remainingMl")) <= 0 else "")),
            "scaleUp": bool(guide.get("scaleUp")),
        })
    for j in jars:
        if str(j.get("kind") or "") == "phyto":
            continue
        v = _vessel(j)
        if v["kind"] == "tub":
            if tub is None:
                tub = v
        elif len(cones) < RIG_CONES_MAX:
            cones.append(v)
    # "B is drawn greyed on the shared manifold until it exists" (doc §8.11
    # #7): one running cone earns a ghost beside it — the never-zero doctrine
    # in the drawing, not a jar in the config.
    if len(cones) == 1 and cones[0]["status"] in ("establishing", "producing"):
        lead_name = cones[0]["name"]
        cones.append({
            "id": "", "name": (lead_name[:-2] + " B") if lead_name.endswith(" A") else "B",
            "kind": cones[0]["kind"], "status": "ghost", "tint": "", "pct": 0, "airOn": False,
            "purgeHot": False, "harvestHot": False, "refillHot": False, "feedHot": False,
            "restartHot": False, "tempStatus": "unknown", "establishDays": None,
            "firstHarvestDays": cones[0]["firstHarvestDays"],
            "note": "comes with the first restart",
        })
    cone_jars = [j for j in jars if str(j.get("vesselKind") or "jar") != "tub" and str(j.get("kind") or "") != "phyto"]
    first_cone = next((j for j in cone_jars if "restart" in (j.get("due") or [])), None)
    first_cone = first_cone or next((j for j in cone_jars if "harvest" in (j.get("due") or [])), None)
    first_cone = first_cone or next(iter(cone_jars), None)
    first_status = str(((first_cone or {}).get("state") or {}).get("status") or "none")
    # Day 0 the jug is the FILL (the whole vessel, cut to the jar's salinity);
    # once the cone runs it is the harvest's refill.
    fill_mode = first_status in ("none", "crashed")
    guide_key = "fillGuide" if fill_mode else "harvestGuide"
    guide = (first_cone.get(guide_key) if first_cone and isinstance(first_cone.get(guide_key), dict)
             else {}) or {}
    jug = {
        "mode": "fill" if fill_mode else "harvest",
        "harvestMl": round(_f(guide.get("totalMl"))), "mixMl": round(_f(guide.get("mixMl"))),
        "rodiMl": round(_f(guide.get("rodiMl"))), "ppt": _f(guide.get("targetPpt"), 35.0),
        "mixPpt": _f(guide.get("mixPpt"), 35.0),
        "purgeMl": round(_f(guide.get("purgeMl"), _f((first_cone or {}).get("purgeMl")))) if first_cone else 0,
        "jarName": str((first_cone or {}).get("name") or ""),
        "available": guide.get("available", True), "reason": guide.get("reason", ""),
        "sieveUm": int(_f(first_cone.get("sieveUm"), 50)) if first_cone else 50,
    }
    remaining = max(0.0, _f(bottle.get("remainingMl")))
    volume = max(1.0, _f(bottle.get("volumeMl"), 1000.0))
    bottle_out = {"ml": round(remaining), "pct": round(min(100.0, 100.0 * remaining / volume)),
                  "status": str(bottle.get("status") or "empty")}

    # The split jug (doc §5.9): the first phyto vessel with a split due, else
    # the first running one — out, fresh in, the f/2, a scale-up named.
    lead_phyto = next((j for j in jars if str(j.get("kind") or "") == "phyto"
                       and "harvest" in (j.get("due") or [])), None)
    lead_phyto = lead_phyto or next((j for j in jars if str(j.get("kind") or "") == "phyto"
                                     and str((j.get("state") or {}).get("status") or "") in ("establishing", "producing")), None)
    lead_phyto = lead_phyto or next((j for j in jars if str(j.get("kind") or "") == "phyto"), None)
    pg = (lead_phyto.get("splitGuide") if lead_phyto and isinstance(lead_phyto.get("splitGuide"), dict) else {}) or {}
    phyto_jug = {
        "jarName": str((lead_phyto or {}).get("name") or ""),
        "outMl": round(_f(pg.get("outMl"))), "freshMl": round(_f(pg.get("freshMl"))),
        "mixMl": round(_f(pg.get("mixMl"))), "rodiMl": round(_f(pg.get("rodiMl"))),
        "ppt": _f(pg.get("targetPpt"), 35.0), "nutrientMl": _f(pg.get("nutrientMl")),
        "scaleUp": bool(pg.get("scaleUp")), "workingLAfter": round(_f(pg.get("workingMlAfter")) / 1000.0, 2),
        "available": pg.get("available", True), "reason": pg.get("reason", ""),
    } if lead_phyto else None
    vessels = cones + ([tub] if tub else [])
    caption = "IDLE — seed the cone and the rig comes alive" if not phyto or cones or tub else "IDLE — seed the vessel and the rig comes alive"
    stage = "idle"
    by_temp = {"critical": 3, "hot": 2}
    hot = sorted((v for v in vessels + phyto if v["tempStatus"] in by_temp and v["status"] in ("establishing", "producing")),
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
    elif guide.get("available") is False:
        stage, caption = "mixing", str(guide.get("reason"))
    elif any(v["restartHot"] for v in cones):
        stage, caption = "restart", ("RESTART DUE — air off, settle, bleed the tip, the whole cone "
                                     "through the net into a clean one")
    elif any(v["harvestHot"] for v in cones):
        stage = "harvest"
        refill = (f"{jug['mixMl']} ml mix + {jug['rodiMl']} ml RODI" if jug["rodiMl"]
                  else f"{jug['mixMl']} ml fresh")
        caption = (f"HARVEST — {jug['jarName']}: air off briefly, watch settling, bleed ~{jug['purgeMl']} ml off the tip, then "
                   f"{jug['harvestMl']} ml through the {jug['sieveUm']} µm net · refill {refill}")
    elif tub and tub["harvestHot"]:
        stage, caption = "tub_harvest", ("POD HARVEST — 25 % through 300 µm for adults, 50 µm "
                                         "for nauplii · replace the removed water with matched saltwater; check population recovery")
    elif any(p["offColour"] and p["status"] in ("establishing", "producing") for p in phyto):
        p = next(p for p in phyto if p["offColour"] and p["status"] in ("establishing", "producing"))
        stage, caption = "off_colour", (f"OFF-COLOUR — {p['name']}: harvest into nothing · smell, light, heat? "
                                        "two days without recovery is a crash — reseed from B")
    elif any(p["freshHot"] for p in phyto):
        p = next(p for p in phyto if p["freshHot"])
        stage, caption = "fresh_vessel", (f"FRESH VESSEL — {p['name']}: split as usual, the seed into a "
                                          "sterilised container of new water + f/2 · bleach, rinse, dry the old one")
    elif any(p["splitHot"] for p in phyto) and phyto_jug:
        p = next(p for p in phyto if p["splitHot"])
        fresh = (f"{phyto_jug['mixMl']} ml mix + {phyto_jug['rodiMl']} ml RODI" if phyto_jug["rodiMl"]
                 else f"{phyto_jug['freshMl']} ml fresh")
        if phyto_jug["scaleUp"]:
            stage, caption = "scale_up", (f"SCALE UP — {p['name']}: {phyto_jug['outMl']} ml out, {fresh} in "
                                          f"@ {phyto_jug['ppt']:g} ppt + {phyto_jug['nutrientMl']:g} ml f/2 → {phyto_jug['workingLAfter']:g} L working")
        else:
            stage, caption = "split", (f"SPLIT — {p['name']}{' held at peak' if p['peakHeld'] else ''}: {phyto_jug['outMl']} ml out → "
                                       f"the bottle / the tank / the drip · {fresh} @ {phyto_jug['ppt']:g} ppt + {phyto_jug['nutrientMl']:g} ml f/2")
    elif any(v["feedHot"] for v in vessels):
        v = next(v for v in vessels if v["feedHot"])
        target = next((j.get("tintTarget") for j in jars if j.get("id") == v["id"]), "") or "a light green"
        stage, caption = "feed", f"FEED — {v['name']} to {target}, little and often"
    elif any(v["status"] == "establishing" for v in vessels):
        v = next(v for v in vessels if v["status"] == "establishing")
        stage, caption = "establishing", (f"ESTABLISHING — {v['name']} day {v['establishDays']} of "
                                          f"{v['firstHarvestDays']} · feed by the tint, no harvest yet")
    elif any(p["status"] == "establishing" for p in phyto):
        p = next(p for p in phyto if p["status"] == "establishing")
        stage, caption = "greening", (f"GREENING — {p['name']} day {p['establishDays']} of ~{p['firstHarvestDays']} · "
                                      "light on, air on, nothing to do but look")
    elif any(v["status"] == "producing" for v in vessels + phyto):
        stage, caption = "steady", "STEADY — nothing due · look at the water"
    elif any(v["status"] == "crashed" for v in vessels + phyto):
        stage, caption = "crashed", "CRASHED — reseed from the other jar, or from a fresh starter"
    return {"stage": stage, "caption": caption, "cones": cones, "tub": tub, "jug": jug,
            "bottle": bottle_out, "phyto": phyto, "phytoJug": phyto_jug}


# --------------------------------------------------------------------------- #
# V2 Stage B — the journal that learns (doc §8.5)
# --------------------------------------------------------------------------- #
UNDOABLE_EVENTS = ("feed", "tint", "skip", "sign", "index")


def _chronological(history: Any) -> list[tuple[datetime, dict[str, Any]]]:
    """Every dated row, oldest first. A taken-back row (``undoneAt``, 0.7.191)
    is invisible to every reader below — the clearing maths, the timeline,
    the risk line, the tint strip — the one choke point, so a wrong tap
    undone never colours a clock again."""
    rows = []
    for row in (history if isinstance(history, list) else []):
        if not isinstance(row, dict) or row.get("undoneAt"):
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
        if row.get("event") in ("seeded", "restart", "crashed"):
            fed_at = None
        if row.get("tint") == "clear" and fed_at is not None:
            hours = (at - fed_at).total_seconds() / 3600.0
            if 0 < hours <= 7 * 24:
                samples.append(round(hours, 1))
            fed_at = None
        if row.get("event") in ("feed", "seeded", "restart") or row.get("fed") is True:
            fed_at = at
    samples.reverse()
    return samples


def replay_state(history: Any, species_id: Any = None) -> dict[str, Any]:
    """The jar's tap stamps re-read from the surviving journal (0.7.191) —
    what ``state`` would say had the taken-back row never happened. Only
    the fields a daily tap writes: the last tint (a seed or restart puts the
    water back to green, the way the ceremonies do), the last feed, the last
    skip, the last sign (cleared by a seed or restart, as the ceremonies do).
    A crash stops the walk — nothing after it is a running jar's word."""
    out: dict[str, Any] = {"lastTint": phyto_seed_tint(species_id) if species_id else "green",
                           "lastFedAt": "", "lastFeedSkippedAt": "", "lastSignAt": "", "lastSign": ""}
    tint_done = sign_done = False
    for at, row in reversed(_chronological(history)):
        event = row.get("event")
        stamp = at.isoformat()
        if event == "crashed":
            break
        if not out["lastFedAt"] and (event in ("feed", "seeded", "restart") or row.get("fed") is True):
            out["lastFedAt"] = stamp
        if not out["lastFeedSkippedAt"] and row.get("skipped"):
            out["lastFeedSkippedAt"] = stamp
        if not tint_done and str(row.get("tint") or "") in ALL_TINTS:
            out["lastTint"] = str(row["tint"])
            tint_done = True
        if not sign_done and str(row.get("sign") or "") in ALL_SIGNS:
            out["lastSign"], out["lastSignAt"] = str(row["sign"]), stamp
            sign_done = True
        if event in ("seeded", "restart"):
            tint_done = sign_done = True            # green water, no sign — the ceremony's word
        if out["lastFedAt"] and out["lastFeedSkippedAt"] and tint_done and sign_done:
            break
    return out


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
            elif event == "crashed":
                seed_at = None
    samples.sort(key=lambda item: item[0], reverse=True)
    return [days for _at, days in samples]


def run_length_samples(history: Any, failures_only: bool = False) -> list[float]:
    """Observed days between seed/restart and a later restart or crash.
    Routine cleaning is not a failure; learning can request crashes only.
    Newest first."""
    samples: list[float] = []
    anchor: datetime | None = None
    for at, row in _chronological(history):
        event = row.get("event")
        if event in ("restart", "crashed") and anchor is not None and (not failures_only or event == "crashed"):
            days = (at - anchor).total_seconds() / 86400.0
            if 0 < days <= 90:
                samples.append(round(days, 1))
        if event in ("seeded", "restart"):
            anchor = at
        elif event == "crashed":
            anchor = None
    samples.reverse()
    return samples


def run_length_runs(history: Any) -> list[dict[str, Any]]:
    """Every finished run with the purge it was bled at: the run's harvest
    rows vote (most common purge wins), the restart row that ended it is the
    fallback. Newest first. ``run_length_samples`` is the days-only view."""
    runs: list[dict[str, Any]] = []
    anchor: datetime | None = None
    purges: list[float] = []
    for at, row in _chronological(history):
        event = row.get("event")
        if event == "harvest" and anchor is not None:
            purges.append(round(max(0.0, _f(row.get("purgeMl")))))
        if event in ("restart", "crashed") and anchor is not None:
            days = (at - anchor).total_seconds() / 86400.0
            if 0 < days <= 90:
                purge = (max(set(purges), key=purges.count) if purges
                         else round(max(0.0, _f(row.get("purgeMl")))))
                runs.append({"days": round(days, 1), "purgeMl": purge, "harvests": len(purges)})
        if event in ("seeded", "restart"):
            anchor = at
            purges = []
        elif event == "crashed":
            anchor = None
            purges = []
    runs.reverse()
    return runs


def purge_note(runs: Any) -> dict[str, Any]:
    """Compare observed runs at different purge volumes without inferring cause.
    Require PURGE_RUNS_MIN runs per volume before showing a comparison."""
    by_purge: dict[float, list[float]] = {}
    for run in (runs if isinstance(runs, list) else []):
        if not isinstance(run, dict):
            continue
        by_purge.setdefault(round(_f(run.get("purgeMl"))), []).append(_f(run.get("days")))
    table = {ml: {"days": round(sum(v) / len(v), 1), "runs": len(v)}
             for ml, v in by_purge.items() if len(v) >= PURGE_RUNS_MIN}
    if len(table) < 2:
        return {"available": False, "line": "", "byPurge": {str(int(k)): v for k, v in table.items()}}
    low, high = min(table), max(table)
    d_low, d_high = table[low]["days"], table[high]["days"]
    if d_high - d_low >= 1.0:
        verdict = f"~{d_high - d_low:.0f} more days observed with the bigger purge; this does not establish the cause"
    elif d_low - d_high >= 1.0:
        verdict = "shorter runs observed with the bigger purge; this does not establish the cause"
    else:
        verdict = "similar observed run lengths; no change recommended from this alone"
    line = (f"runs bled ~{high:.0f} ml lasted ~{d_high:g} d, ~{low:.0f} ml lasted ~{d_low:g} d "
            f"({table[high]['runs']} + {table[low]['runs']} runs) — {verdict}")
    return {"available": True, "line": line, "byPurge": {str(int(k)): v for k, v in table.items()}}


def _daily_volume(history: Any, now: datetime, window_days: float, event: str) -> float | None:
    """Mean daily logged volume, including today's partial day and zero-use days.

    Start at the first retained record or the calendar-window boundary. This
    avoids counting N daily draws across only N-1 intervals. It is an observed
    volume, not a population-density or food-nutrition estimate.
    """
    days = max(1, int(_f(window_days, 14)))
    start_day = (now - timedelta(days=days - 1)).date()
    rows = [(at.astimezone(now.tzinfo), row) for at, row in _chronological(history) if at <= now]
    if not rows:
        return None
    first_day = max(start_day, rows[0][0].date())
    total = sum(max(0.0, _f(row.get("ml"))) for at, row in rows
                if at.date() >= first_day and row.get("event") == event and not row.get("undoneAt"))
    return round(total / max(1, (now.date() - first_day).days + 1), 1) if total > 0 else None


def yield_ml_per_day(history: Any, now: datetime, window_days: float = 14.0) -> float | None:
    """Harvested ml per day over the recent window — the NPS runway's demand
    figure. None until something has been harvested."""
    return _daily_volume(history, now, window_days, "harvest")


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
    history = [row for at, row in _chronological(jar.get("history")) if at <= now]
    cad = cadence_for(jar.get("species"), jar.get("cadence"))
    clearing = _rolling(clearing_samples(history), "hours")
    siblings = [[row for at, row in _chronological(history) if at <= now]
                for history in (sibling_histories if isinstance(sibling_histories, list) else [])]
    first = _rolling(first_harvest_samples(siblings), "days")
    run = _rolling(run_length_samples(history), "days")
    failures = _rolling(run_length_samples(history, failures_only=True), "days")
    suggest: dict[str, Any] = {"feedIntervalH": None, "restartIntervalDays": None}
    if clearing["available"]:
        hours = max(2.0, min(72.0, round(clearing["hours"] * 0.9)))
        if abs(hours - cad["feedIntervalH"]) >= 1:
            suggest["feedIntervalH"] = hours
    if failures["available"] and cad["restartIntervalDays"] > 0:
        days = max(3.0, round(failures["days"] - 1))
        if days < cad["restartIntervalDays"]:
            suggest["restartIntervalDays"] = days
    out = {"clearingH": clearing, "firstHarvestDays": first, "runLengthDays": run, "failureDays": failures,
           "yieldMlDay": yield_ml_per_day(history, now), "suggest": suggest,
           "purge": purge_note(run_length_runs(history))}
    if species_kind(jar.get("species")) == "phyto":
        # Days-to-dark (doc §5.10): split → the first dark tap; rolling three,
        # two before it speaks; Apply moves splitIntervalDays (Stage B).
        dark = _rolling(darkening_samples(history), "days")
        out["daysToDark"] = dark
        suggest["splitIntervalDays"] = None
        suggest["mode"] = None
        mode = str(jar.get("mode") or "batch")
        if dark["available"]:
            days = max(2.0, min(21.0, round(dark["days"])))
            if abs(days - cad["harvestIntervalDays"]) >= 1 and mode != "daily":
                suggest["splitIntervalDays"] = days
            # Two learned cycles unlock the daily (semi-continuous) offer: a
            # small draw every day, sized to the culture — never to the tank.
            if mode != "daily":
                suggest["mode"] = "daily"
        out["dailyOffer"] = {"available": bool(dark["available"] and mode != "daily"),
                             "pct": daily_draw_pct(cad.get("harvestPct"), dark.get("days")) if dark["available"] else None}
        # Yield (litres a week — the demand line's other half), recovery by
        # split depth, and the light delivered against a slow cycle.
        y = out["yieldMlDay"]
        out["yieldLWeek"] = round(_f(y) * 7.0 / 1000.0, 2) if y else None
        out["depth"] = darkening_by_depth(history)
        week = light_samples(history)
        week_h = round(sum(week) / len(week), 1) if week else None
        samples = darkening_samples(history)
        slow = bool(samples and dark["available"] and samples[0] > dark["days"] + 1) or \
            bool(samples and not dark["available"] and samples[0] > cad["harvestIntervalDays"] + 1)
        # Stage C: the stick's calibration off the accrued cm readings.
        last_cm = next((row.get("secchiCm") for row in history[::-1]
                        if isinstance(row.get("secchiCm"), (int, float)) and not isinstance(row.get("secchiCm"), bool)), None)
        out["secchi"] = secchi_fit(history, last_cm)
        # Stage D: the index's bands and curve, the pH's slope.
        last_od = next((row.get("od") for row in history[::-1]
                        if row.get("event") == "index" and isinstance(row.get("od"), (int, float)) and not isinstance(row.get("od"), bool)), None)
        out["index"] = index_fit(history, last_od)
        out["ph"] = ph_trend(history)
        out["light"] = {"weekH": week_h, "days": len(week),
                        "line": (f"a week under {LIGHT_WEEK_LOW_H:g} h of light (~{week_h:g} h a day) beside a slow cycle — "
                                 "the light is the first thing to check; nothing here proves it")
                        if week_h is not None and len(week) >= 5 and week_h < LIGHT_WEEK_LOW_H and slow else ""}
    return out


def risk_line(jar: dict[str, Any], st: dict[str, Any], temp: dict[str, Any], now: datetime,
              light: Any = None, index: Any = None) -> dict[str, Any]:
    """The hatchery nose, made explainable (doc §8.8): one sentence with the
    cause, built only from stamps — never a score. ``act`` = do something
    today, ``watch`` = look harder, ``ok`` = leave it alone. ``light`` is the
    phyto vessel's light_state (Stage B) — its watch / act rides the line."""
    if st.get("status") not in ("establishing", "producing"):
        return {"level": "ok", "reason": ""}
    state = jar.get("state") if isinstance(jar.get("state"), dict) else {}
    cad = st.get("cadence") if isinstance(st.get("cadence"), dict) else cadence_for(jar.get("species"), jar.get("cadence"))
    act: list[str] = []
    watch: list[str] = []
    t_status = str((temp or {}).get("status") or "")
    if species_kind(jar.get("species")) == "phyto":
        # The vessel's own line (doc §5.10, the Stage A half): heat, an
        # off-colour tap, a blocking sign, peak-held, a split long overdue.
        if t_status == "critical" or (t_status == "hot" and (temp or {}).get("act")):
            act.append(f"{temp.get('tempC')} °C at the rack — the alga declines abruptly near 30; shade it, move it off the sunlit shelf, a cooler room")
        elif t_status == "hot":
            watch.append(f"{temp.get('tempC')} °C at the rack — over the warning line; shade it")
        tint = str(state.get("lastTint") or "")
        sign = str(state.get("lastSign") or "")
        if tint == "off":
            act.append("off-colour — harvest into nothing; check the smell, the light and the temperature")
        elif st.get("harvestBlocked") and sign:
            act.append(f"{SIGN_WORDS.get(sign, sign)} since the last fresh vessel — the split waits for a green or dark look")
        if st.get("peakHeld"):
            watch.append(f"held dark for {_f(st.get('darkDays')):g} days without a split — a culture held at peak turns")
        harvest = st.get("harvest") or {}
        if harvest.get("reason") == "cap" and _f(harvest.get("hoursOverdue")) >= 72 and tint not in ("dark", "off"):
            watch.append(f"not dark at day {_f(st.get('daysSinceSplit')):g} — light, heat, or f/2 skipped at the last split?")
        # Stage B (doc §5.10): the light, the f/2 at the last split, the fresh
        # vessel overdue by cycles, the backup's refresh, the starter's month.
        light = light if isinstance(light, dict) else {}
        if light.get("status") == "act" and light.get("line"):
            act.append(str(light["line"]).split(" — ", 1)[-1] if " — the culture" in str(light["line"]) else str(light["line"]))
        elif light.get("status") == "watch":
            watch.append(light.get("nudge") or (str(light.get("line") or "").rsplit(" — ", 1)[-1] if light.get("line") else "light under the target"))
        last_split = next((row for _at, row in reversed(_chronological(jar.get("history")))
                           if row.get("event") in ("harvest", "restart") and not row.get("undoneAt")), None)
        if isinstance(last_split, dict) and _f(last_split.get("freshMl")) > 0 and _f(last_split.get("nutrientMl")) <= 0:
            watch.append("no f/2 logged at the last split — the fresh water went in bare")
        restart = st.get("restart") or {}
        if restart.get("due") and restart.get("reason") == "cycles":
            watch.append(f"{_f(st.get('cyclesSinceFresh')):g} splits since a fresh vessel — sterilise the spare")
        refresh = st.get("refresh") or {}
        if refresh.get("due"):
            watch.append(f"the backup is {_f(st.get('ageDays')):g} days old — refresh it from the main vessel")
        preset = species_preset(jar.get("species"))
        starter = starter_state(state.get("starterOpenedAt"), preset.get("starterShelfDays"), now)
        if st.get("status") == "establishing" and starter.get("status") == "stale":
            watch.append("the starter bottle is past its four weeks — seed from it today or not at all")
        # Stage D (doc §6): the index held at the dark band, a photo that reads
        # yellow-brown, a pH that has turned down — advice off the curve.
        index = index if isinstance(index, dict) else {}
        held = index_dark_days(jar.get("history"), now) if index.get("darkOd") else 0.0
        if held >= INDEX_PEAK_DAYS and not st.get("peakHeld"):
            watch.append(f"the index has read dark for {held:g} days without a split — a culture held at peak turns")
        if index.get("looksOff") and tint != "off":
            watch.append("the last photo reads yellow-brown against the card, not green — look at it")
        ph = index.get("ph") if isinstance(index.get("ph"), dict) else {}
        if ph.get("trend") == "falling":
            watch.append(ph.get("line") or "the pH is falling — a crash? look at it")
        if act:
            return {"level": "act", "reason": "; ".join(act)}
        if watch:
            return {"level": "watch", "reason": "; ".join(watch)}
        return {"level": "ok", "reason": "no warning from the recorded observations"}
    if t_status == "critical" or (t_status == "hot" and (temp or {}).get("act")):
        act.append(f"room {temp.get('tempC')} °C — over the precautionary act line; check culture temperature, aeration and water quality")
    elif t_status == "hot":
        watch.append(f"room {temp.get('tempC')} °C — over the warning line")
    harvest = st.get("harvest") or {}
    interval_h = _f(cad.get("harvestIntervalDays")) * 24.0
    if harvest.get("due") and st.get("status") == "producing":
        if species_preset(jar.get("species"))["kind"] == "rotifer" and interval_h > 0 and _f(harvest.get("hoursOverdue")) >= interval_h:
            act.append("two harvests missed — check water quality and harvest/refill if the population is healthy")
        else:
            watch.append("harvest overdue")
    sign = str(state.get("lastSign") or "")
    restart = st.get("restart") or {}
    water = st.get("waterChange") or {}
    if sign and (restart.get("reason") == "sign" or water.get("reason") == "sign"):
        act.append(f"{SIGN_WORDS.get(sign, sign)} since the last "
                   f"{'restart' if restart.get('reason') == 'sign' else 'water change'}")
    if st.get("clearingSlow"):
        watch.append("clearing is slowing — check activity, temperature and feeding amounts")
    for at, row in _chronological(jar.get("history")):
        if (row.get("event") == "feed" or row.get("fed") is True) and row.get("tint") == "green" \
                and 0 <= (now - at).total_seconds() <= 86400:
            watch.append("fed on green water — check for excess feed and test water quality")
            break
    if act:
        return {"level": "act", "reason": "; ".join(act)}
    if watch:
        return {"level": "watch", "reason": "; ".join(watch)}
    return {"level": "ok", "reason": "no warning from the recorded observations"}


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
    if started is None or started > now:
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
    if enriched is None or enriched > now:
        return {"status": "faded", "hoursLeft": 0.0}
    cold = _f(cold_h) if _f(cold_h) > 0 else BOOST_COLD_H
    left = cold - (now - enriched).total_seconds() / 3600.0
    if left <= 0:
        return {"status": "faded", "hoursLeft": 0.0}
    return {"status": "gutloaded", "hoursLeft": round(left, 1)}


def bottle_usage_ml_per_day(history: Any, now: datetime, window_days: float = 7.0) -> float | None:
    """How fast the bottle is being fed out — ml a day over the recent window,
    None until a feed has been logged (never a guess)."""
    return _daily_volume(history, now, window_days, "fed_tank")


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
    # Bottle demand must not shorten a culture's recovery interval.
    if clock.get("available") and not clock.get("due"):
        return {"status": "wait", "hoursUntil": clock.get("hoursUntil"), "driver": "jar"}
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
def rack_offset_c(projection_hours: Any, temp_c: Any, now: datetime,
                  window_h: float = RACK_OFFSET_WINDOW_H) -> float | None:
    """How far the rack's own sensor reads over (or under) the room the
    projection describes, from the projection row nearest to now. None
    without a sensor reading or a row inside the window; clamped to
    ±RACK_OFFSET_MAX_C so a mis-linked sensor cannot invent a heatwave."""
    if not isinstance(temp_c, (int, float)) or isinstance(temp_c, bool) or not math.isfinite(temp_c):
        return None
    nearest: tuple[float, float] | None = None
    for row in (projection_hours if isinstance(projection_hours, list) else []):
        if not isinstance(row, dict):
            continue
        at = _parse_iso(row.get("at"))
        room = row.get("roomC")
        if at is None or not isinstance(room, (int, float)) or isinstance(room, bool) or not math.isfinite(room):
            continue
        gap = abs((at - now).total_seconds()) / 3600.0
        if gap <= window_h and (nearest is None or gap < nearest[0]):
            nearest = (gap, float(room))
    if nearest is None:
        return None
    offset = max(-RACK_OFFSET_MAX_C, min(RACK_OFFSET_MAX_C, float(temp_c) - nearest[1]))
    return round(offset, 1)


def heat_guard(projection_hours: Any, species_id: Any, now: datetime,
               lookahead_h: float = GUARD_LOOKAHEAD_H, offset_c: Any = 0.0) -> dict[str, Any]:
    """The heatwave guard: the cooling headroom's indoor projection (room °C
    per forecast hour, learned offsets included) against the species band.
    ``warn`` when the room is projected past the warning line inside the
    window (with WHEN), ``watch`` past the productive band, ``clear``
    otherwise; ``available`` False with no projection — never a guess.
    ``offset_c`` is the rack's measured lead over the room (rack_offset_c):
    the forecast is shifted by it, and the line says so."""
    species = species_preset(species_id)
    offset = _f(offset_c)
    if not (-RACK_OFFSET_MAX_C <= offset <= RACK_OFFSET_MAX_C):
        offset = 0.0
    rows = []
    for row in (projection_hours if isinstance(projection_hours, list) else []):
        if not isinstance(row, dict):
            continue
        at = _parse_iso(row.get("at"))
        room = row.get("roomC")
        if at is None or not isinstance(room, (int, float)) or isinstance(room, bool) or not math.isfinite(room):
            continue
        hours = (at - now).total_seconds() / 3600.0
        if -1.0 <= hours <= lookahead_h:
            rows.append((at, float(room) + offset, hours))
    base = {"offsetC": round(offset, 1) if abs(offset) >= 0.5 else 0.0}
    if not rows:
        return {**base, "available": False, "status": "unknown", "peakC": None, "peakAt": None,
                "crossAt": None, "hoursUntil": None, "line": ""}
    rows.sort(key=lambda row: row[0])
    peak_at, peak_c, _h = max(rows, key=lambda r: r[1])
    hard = _f(species["tempHardMaxC"])
    band = _f(species["tempMaxC"])
    where = "the rack" if base["offsetC"] else "room"
    rack_note = f", rack {offset:+.1f} °C over the room" if base["offsetC"] else ""
    cross = next((r for r in rows if r[1] >= hard), None)
    # The alga's copy (doc §5.6): it declines abruptly near 30 — shade, move,
    # cool; an animal's jar wants air and a water change ready.
    advice = ("shade it, move it off the sunlit shelf, a cooler room — the alga declines abruptly near 30 °C"
              if species.get("kind") == "phyto" else "extra air, shade, feed lightly, a 50 % change ready")
    if cross is not None:
        at, room, hours = cross
        return {**base, "available": True, "status": "warn", "peakC": round(peak_c, 1),
                "peakAt": peak_at.isoformat(), "crossAt": at.isoformat(),
                "hoursUntil": round(max(0.0, hours), 1),
                "line": (f"{where} passes {hard:g} °C in ~{max(0.0, hours):.0f} h (peak {peak_c:.1f} °C{rack_note}) — "
                         f"{advice}")}
    if peak_c > band:
        return {**base, "available": True, "status": "watch", "peakC": round(peak_c, 1),
                "peakAt": peak_at.isoformat(), "crossAt": None, "hoursUntil": None,
                "line": f"{where} peaks at {peak_c:.1f} °C{rack_note} — above the {band:g} °C band, keep an eye on it"}
    return {**base, "available": True, "status": "clear", "peakC": round(peak_c, 1),
            "peakAt": peak_at.isoformat(), "crossAt": None, "hoursUntil": None,
            "line": f"{where} peaks at {peak_c:.1f} °C{rack_note} — inside the band"}


def stagger_advice(jar_a: dict[str, Any], jar_b: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Two jars are only a backup when they never restart together: the ideal
    gap is half the restart interval; more than two days off it earns a line."""
    days = stagger_days(jar_a, jar_b, now)
    cad = cadence_for(jar_a.get("species"), jar_a.get("cadence"))
    interval = _f(cad.get("restartIntervalDays"))
    if days is None or interval <= 0:
        return {"available": False, "days": None, "idealDays": None, "advice": ""}
    ideal = round(interval / 2.0, 1)
    other_interval = cadence_for(jar_b.get("species"), jar_b.get("cadence"))["restartIntervalDays"]
    if interval != other_interval:
        return {"available": False, "days": None, "idealDays": None, "advice": "Different restart intervals — compare the next due dates."}
    gap = min(days % interval, interval - days % interval)
    off = abs(gap - ideal)
    if off <= 2.0:
        advice = f"restart cycles {gap:.0f} days apart — staggered; keep both cultures healthy"
    else:
        advice = (f"restart cycles only {gap:.0f} days apart (ideal {ideal:g}) — plan an earlier clean-jar restart "
                  "for one healthy culture; never delay a due restart or a response to warning signs")
    return {"available": True, "days": round(gap, 1), "idealDays": ideal, "advice": advice}


def tint_strip(history: Any, now: datetime, days: int = TINT_STRIP_DAYS) -> list[str]:
    """The last N days as one tint each (the latest tap that day), oldest
    first, "" for a day with no look — the culture card's strip."""
    by_day: dict[str, str] = {}
    for at, row in _chronological(history):
        tint = str(row.get("tint") or "")
        if tint not in ALL_TINTS or at > now:
            continue
        by_day[at.astimezone(now.tzinfo).date().isoformat()] = tint
    out = []
    for back in range(days - 1, -1, -1):
        out.append(by_day.get((now - timedelta(days=back)).date().isoformat(), ""))
    return out


TIMELINE_DAYS = 30
TIMELINE_ROWS_MAX = 240


def feed_timeline(history: Any, now: datetime, days: int = TIMELINE_DAYS) -> dict[str, Any]:
    """The feeding / water-tint timeline (0.7.184): every journal row inside
    the window as a compact mark, oldest first, plus the clearing spans — one
    per feed, from the feed to the first tap that found the water CLEAR, by
    the same rule as ``clearing_samples`` (a later feed before it cleared
    voids the span; a seed, restart or crash resets). The newest feed with no
    clear yet is an OPEN span measured to now — the keeper watching how long
    the water takes to clear before the next feed."""
    since = now - timedelta(days=max(1, int(days)))
    rows = [(at, row) for at, row in _chronological(history) if at <= now]
    marks: list[dict[str, Any]] = []
    tint_before = ""
    for at, row in rows:
        if at < since:
            if str(row.get("tint") or "") in ALL_TINTS:
                tint_before = str(row["tint"])
            elif row.get("event") in ("seeded", "restart", "crashed"):
                tint_before = ""
            continue
        tint = str(row.get("tint") or "")
        marks.append({
            "at": at.isoformat(),
            "event": str(row.get("event") or ""),
            "tint": tint if tint in ALL_TINTS else "",
            "fed": bool(row.get("fed")) or row.get("event") == "feed",
            "skipped": bool(row.get("skipped")),
            "ml": round(_f(row.get("ml")), 1) if _f(row.get("ml")) > 0 else 0,
            "sign": str(row.get("sign") or "") if str(row.get("sign") or "") in ALL_SIGNS else "",
            **({"secchiCm": row.get("secchiCm")} if isinstance(row.get("secchiCm"), (int, float)) and not isinstance(row.get("secchiCm"), bool) else {}),
            "tempC": row.get("tempC") if isinstance(row.get("tempC"), (int, float)) and not isinstance(row.get("tempC"), bool) else None,
        })
    marks = marks[-TIMELINE_ROWS_MAX:]
    spans: list[dict[str, Any]] = []
    fed_at: datetime | None = None
    for at, row in rows:
        if row.get("event") in ("seeded", "restart", "crashed"):
            fed_at = None
        if row.get("tint") == "clear" and fed_at is not None:
            hours = (at - fed_at).total_seconds() / 3600.0
            if 0 < hours <= 7 * 24 and at >= since:
                spans.append({"fedAt": fed_at.isoformat(), "clearAt": at.isoformat(),
                              "hours": round(hours, 1), "open": False})
            fed_at = None
        if row.get("event") in ("feed", "seeded", "restart") or row.get("fed") is True:
            fed_at = at
    if fed_at is not None and fed_at >= since:
        hours = (now - fed_at).total_seconds() / 3600.0
        if hours <= 7 * 24:
            spans.append({"fedAt": fed_at.isoformat(), "clearAt": None, "hours": round(hours, 1), "open": True})
    return {"days": int(days), "since": since.isoformat(), "tintBefore": tint_before,
            "marks": marks, "spans": spans}


def continuity_days(since_iso: Any, now: datetime) -> float | None:
    since = _parse_iso(since_iso)
    if since is None or since > now:
        return None
    return round(max(0.0, (now - since).total_seconds() / 86400.0), 1)


def acclimation_plan(from_ppt: Any, to_ppt: Any, pouch_ml: float = 500.0,
                     max_step: float = ACCLIMATE_STEP_PPT, wait_min: int = ACCLIMATE_WAIT_MIN) -> dict[str, Any]:
    """The arrival maths (doc §8.8 #7, FAO §3.5): the pouch is brought to the
    cone's water in equal steps of at most ``max_step`` ppt. Each addition of
    cone water is sized for exactly one step, then a wait; the last step is
    the net into the cone itself. Inside the rule from the start = float and
    pour. Additions are capped — a gap the cap cannot close says so instead
    of pretending."""
    if from_ppt is None or isinstance(from_ppt, bool) or not math.isfinite(_f(from_ppt, math.nan)):
        return {"available": False, "steps": [], "withinRule": False,
                "line": "measure the starter salinity and volume before acclimating; the supplier's culture target is not a shipping measurement"}
    start = _f(from_ppt)
    target = _f(to_ppt, STARTER_PPT)
    pouch = max(50.0, _f(pouch_ml, 500.0))
    gap = target - start
    max_step = max(0.1, _f(max_step, ACCLIMATE_STEP_PPT))
    n = max(1, math.ceil(abs(gap) / max_step))
    delta = gap / n
    steps: list[dict[str, Any]] = []
    ppt = start
    volume = pouch
    for _k in range(1, n):                              # n-1 additions, the n-th is the pour
        if len(steps) >= ACCLIMATE_STEPS_MAX:
            break
        remaining = target - ppt
        if abs(remaining - delta) < 1e-9:
            break
        add = max(1, round(volume * delta / (remaining - delta)))
        ppt = round((ppt * volume + target * add) / (volume + add), 1)
        volume += add
        steps.append({"addMl": add, "ppt": ppt, "waitMin": wait_min})
    final = round(target - ppt, 1)
    within = abs(final) <= max_step + 0.05
    if not steps:
        line = (f"the starter is at ~{start:g} ppt and the cone at {target:g}: float the pouch "
                f"{wait_min} min, then sieve and rinse into the prepared vessel — a {abs(final):g} ppt step is within the {max_step:g} ppt guideline")
    else:
        parts = [f"add {st['addMl']} ml of cone water, wait {st['waitMin']} min (~{st['ppt']:g} ppt)"
                 for st in steps]
        line = (f"the starter is at ~{start:g} ppt and the cone at {target:g}: float the pouch "
                f"{wait_min} min, then " + "; ".join(parts)
                + (f"; then net them into the cone — the last step is {abs(final):g} ppt" if within
                   else f"; the last step would still be {abs(final):g} ppt — too big: stop and obtain a supplier-specific acclimation protocol"))
    return {"fromPpt": round(start, 1), "toPpt": round(target, 1), "pouchMl": round(pouch),
            "steps": steps, "finalStepPpt": final, "withinRule": within, "line": line}
