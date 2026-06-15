"""Constants for the OpenReef integration."""

from __future__ import annotations

DOMAIN = "openreef"
NAME = "OpenReef"
PANEL_ICON = "mdi:fishbowl"
PANEL_URL = "openreef"
PANEL_STATIC_URL = "/openreef_static"

CONF_SETTINGS = "settings"
CORE_SCHEMA_VERSION = 43
INTEGRATION_VERSION = "0.4.98"

# Camera V2 — event-triggered capture (Phase A). Clips/snapshots are stored in a
# managed dir under the HA config directory and served back to the panel same-origin.
CAPTURES_DIR_NAME = "openreef_captures"
CAPTURES_STATIC_URL = "/openreef_captures"
CAPTURE_MAX_RECORDS = 50           # hard cap on stored capture records (own cap, not the activity-50)
CAPTURE_DEFAULT_RETENTION = 10     # default "keep last N"
CAPTURE_DEFAULT_DURATION = 12      # seconds of clip
CAPTURE_MIN_DURATION = 3
CAPTURE_MAX_DURATION = 60
CAPTURE_DEFAULT_LOOKBACK = 0       # pre-roll seconds (needs a warm HLS buffer; default off)
CAPTURE_MAX_LOOKBACK = 30
CAPTURE_DEFAULT_COOLDOWN = 20      # per-trigger debounce seconds
CAPTURE_MAX_COOLDOWN = 600

# Camera V2 — reef timelapse (Phase B). Frames are JPEGs written into a per-camera
# subdir of the captures dir and played back in-panel as a zero-ffmpeg slideshow.
# Retention is a 4-tier downsampling ladder: every frame recently, then 1/day,
# 1/week, 1/month as frames age — so years of growth fit in a few hundred frames.
TIMELAPSE_SUBDIR = "timelapse"
TIMELAPSE_DEFAULT_CADENCE = 30     # minutes between frames
TIMELAPSE_MIN_CADENCE = 5
TIMELAPSE_MAX_CADENCE = 1440
TIMELAPSE_DEFAULT_WINDOW_START = "08:00"
TIMELAPSE_DEFAULT_WINDOW_END = "22:00"
TIMELAPSE_DEFAULT_DETAIL_DAYS = 14    # keep every frame for this long
TIMELAPSE_DEFAULT_DAILY_DAYS = 90     # then 1/day until this age
TIMELAPSE_DEFAULT_WEEKLY_DAYS = 365   # then 1/week until this age
TIMELAPSE_DEFAULT_MONTHLY_DAYS = 0    # then 1/month until this age (0 = keep forever)
TIMELAPSE_MAX_DAYS = 3650             # clamp for any tier boundary (~10 years)

# Camera V2 — feed-watch (Phase D). A snapshot burst across the whole Feed-mode
# window, grouped as a scrubbable "feed session" to confirm every fish ate.
# Supersedes the Phase A feed-mode clip trigger while enabled.
FEEDS_SUBDIR = "feeds"
FEEDWATCH_DEFAULT_CADENCE = 10        # seconds between frames during a feeding
FEEDWATCH_MIN_CADENCE = 3
FEEDWATCH_MAX_CADENCE = 60
FEEDWATCH_DEFAULT_RETENTION = 25      # feed sessions kept
FEEDWATCH_MAX_RETENTION = 200
FEEDWATCH_MAX_MINUTES = 20            # hard cap when the feed timer has no fixed duration

# Parameters the advisory Dosing & Consumption Advisor tracks. These are the
# consumable chemistry parameters a doser/Trident owner replenishes daily.
DOSING_PARAMETERS = ("alkalinity", "calcium", "magnesium")
MANUAL_TEST_PARAMETERS = (
    "alkalinity",
    "calcium",
    "magnesium",
    "nitrate",
    "phosphate",
    "salinity",
    "ph",
    "temp",
)

DEFAULT_TANK_PROFILE = "mixed_reef"
TANK_PROFILE_CHOICES = {
    "fish_only_fowlr": "Fish-only / FOWLR",
    "soft_coral": "Soft coral",
    "lps": "LPS reef",
    "sps": "SPS reef",
    "mixed_reef": "Mixed reef",
    "anemone_dominant": "Anemone-dominant",
}

MANUAL_TEST_CADENCE_PRESETS = {
    "fish_only_fowlr": {
        "alkalinity": 30,
        "calcium": 30,
        "magnesium": 60,
        "nitrate": 14,
        "phosphate": 30,
        "salinity": 14,
        "ph": 30,
        "temp": 7,
    },
    "soft_coral": {
        "alkalinity": 7,
        "calcium": 21,
        "magnesium": 30,
        "nitrate": 14,
        "phosphate": 14,
        "salinity": 7,
        "ph": 30,
        "temp": 7,
    },
    "lps": {
        "alkalinity": 7,
        "calcium": 14,
        "magnesium": 30,
        "nitrate": 7,
        "phosphate": 7,
        "salinity": 7,
        "ph": 21,
        "temp": 7,
    },
    "sps": {
        "alkalinity": 3,
        "calcium": 7,
        "magnesium": 14,
        "nitrate": 7,
        "phosphate": 7,
        "salinity": 7,
        "ph": 14,
        "temp": 7,
    },
    "mixed_reef": {
        "alkalinity": 4,
        "calcium": 14,
        "magnesium": 21,
        "nitrate": 7,
        "phosphate": 7,
        "salinity": 7,
        "ph": 21,
        "temp": 7,
    },
    "anemone_dominant": {
        "alkalinity": 14,
        "calcium": 21,
        "magnesium": 30,
        "nitrate": 7,
        "phosphate": 7,
        "salinity": 7,
        "ph": 14,
        "temp": 7,
    },
}

# Maintenance Tasks V1 — curated default reef chores (HA-native, no Google). Seeded
# once into config["maintenance"]["tasks"] (disabled by default); the user enables /
# edits / removes them and adds their own. Kept OUT of DEFAULT_CORE_CONFIG so a user's
# deletes stick (a `seeded` flag prevents re-adding them).
MAINTENANCE_TASK_DEFAULTS = {
    "water_change": {"label": "Water change", "cadenceDays": 7},
    "clean_skimmer": {"label": "Clean skimmer cup", "cadenceDays": 7},
    "replace_filter_sock": {"label": "Replace filter sock / floss", "cadenceDays": 7},
    "blow_detritus": {"label": "Blow detritus off rocks", "cadenceDays": 7},
    "clean_glass": {"label": "Clean glass / viewing panes", "cadenceDays": 3},
    "refill_dosing": {"label": "Refill dosing / kalk reservoir", "cadenceDays": 14},
    "inspect_ato": {"label": "Check / clean ATO reservoir", "cadenceDays": 14},
    "replace_carbon": {"label": "Replace carbon", "cadenceDays": 30},
    "replace_gfo": {"label": "Replace GFO (phosphate media)", "cadenceDays": 30},
    "calibrate_ph": {"label": "Calibrate pH probe", "cadenceDays": 30},
    "calibrate_salinity": {"label": "Calibrate salinity / refractometer", "cadenceDays": 30},
    "clean_pumps": {"label": "Clean / descale pumps & powerheads", "cadenceDays": 90},
    "replace_rodi": {"label": "Replace RO/DI filters", "cadenceDays": 180},
}

MAINTENANCE_TASK_CADENCE_MIN = 1
MAINTENANCE_TASK_CADENCE_MAX = 365
MAINTENANCE_TASK_CRITICAL_MAX = 730
MAINTENANCE_COMPLETIONS_MAX = 50   # kept per task

# Maintenance Tasks V2 — HA-native reminders. A single daily tick (at this local
# time) re-evaluates due/overdue tasks and fires an in-HA persistent notification
# plus an optional one-shot phone push (HA companion app) — free, unlimited, and
# never paywalled, unlike the apps. The single daily time IS the anti-spam control.
MAINTENANCE_REMINDER_DEFAULT_TIME = "09:00"

SERVICE_RECORD_TASK_COMPLETION = "record_task_completion"
SERVICE_APPLY_MODE = "apply_mode"
SERVICE_ARM_EQUIPMENT = "arm_equipment"
SERVICE_DISARM_EQUIPMENT = "disarm_equipment"
SERVICE_RECORD_MANUAL_READING = "record_manual_reading"
SERVICE_ACKNOWLEDGE_ALERT = "acknowledge_alert"
SERVICE_TEST_NOTIFICATION = "test_notification"
SERVICE_REFRESH_TRUST_CHECK = "refresh_trust_check"
SERVICE_HEARTBEAT = "heartbeat"

ISSUE_MISSING_ENTITIES = "missing_entities"
ISSUE_ARMED_UNAVAILABLE = "armed_unavailable"
ISSUE_LEGACY_LABS_CONFIG = "legacy_labs_config"

MVP_SENSORS = {
    "temp": {
        "label": "Display Tank Temperature",
        "enabled": True,
        "group": "tank",
        "unit": "°C",
        "min": 24.5,
        "max": 27.5,
        "target": {
            "domains": ["sensor"],
            "keywords": ["temperature", "temp", "display", "tank"],
            "prefer": ["reef", "tank", "display", "aquarium", "water", "saltwater", "apex", "neptune"],
            "avoid": ["room", "ambient", "air"],
            "device_classes": ["temperature"],
            "units": ["°C", "°F", "C", "F"],
        },
    },
    "ph": {
        "label": "pH Level",
        "enabled": False,
        "group": "chemistry",
        "unit": "",
        "min": 7.8,
        "max": 8.4,
        "target": {
            "domains": ["sensor"],
            "keywords": ["ph"],
            "prefer": ["reef", "tank", "aquarium", "water", "saltwater", "apex", "neptune"],
            "avoid": ["phone", "phase", "room"],
            "device_classes": [],
            "units": [],
        },
    },
    "salinity": {
        "label": "Salinity",
        "enabled": False,
        "group": "chemistry",
        "unit": "ppt",
        "min": 32,
        "max": 36,
        "target": {
            "domains": ["sensor"],
            "keywords": ["salinity", "specific gravity", "sg", "conductivity"],
            "prefer": ["reef", "tank", "aquarium", "salt", "ppt", "apex", "neptune"],
            "avoid": ["room", "ambient", "air"],
            "device_classes": [],
            "units": ["ppt", "SG", "sg", "mS/cm"],
        },
    },
    "sump_temp": {
        "label": "Sump Temperature",
        "enabled": False,
        "group": "sump",
        "unit": "°C",
        "min": 24.5,
        "max": 27.5,
        "target": {
            "domains": ["sensor"],
            "keywords": ["temperature", "temp", "sump", "rear chamber", "chamber"],
            "prefer": ["sump", "rear", "chamber", "filter", "refugium", "apex", "neptune"],
            "avoid": ["room", "ambient", "air", "display"],
            "device_classes": ["temperature"],
            "units": ["°C", "°F", "C", "F"],
        },
    },
    "alkalinity": {
        "label": "Alkalinity",
        "enabled": False,
        "group": "chemistry",
        "unit": "dKH",
        "min": 7.0,
        "max": 11.0,
        "target": {
            "domains": ["sensor"],
            "keywords": ["alkalinity", "alk", "kh", "dkh", "trident", "neptune"],
            "prefer": ["trident", "apex", "neptune", "reef", "tank", "aquarium"],
            "avoid": ["room", "ambient", "air"],
            "device_classes": [],
            "units": ["dKH", "dkh", "KH"],
        },
    },
    "orp": {
        "label": "ORP",
        "enabled": False,
        "group": "chemistry",
        "unit": "mV",
        "min": 250,
        "max": 450,
        "target": {
            "domains": ["sensor"],
            "keywords": ["orp", "oxidation", "redox", "apex", "neptune"],
            "prefer": ["apex", "neptune", "reef", "tank", "aquarium"],
            "avoid": ["room", "ambient", "air"],
            "device_classes": [],
            "units": ["mV", "mv"],
        },
    },
    "calcium": {
        "label": "Calcium",
        "enabled": False,
        "group": "chemistry",
        "unit": "ppm",
        "min": 380,
        "max": 460,
        "target": {
            "domains": ["sensor"],
            "keywords": ["calcium", "ca", "trident", "neptune"],
            "prefer": ["trident", "apex", "neptune", "reef", "tank", "aquarium"],
            "avoid": ["room", "ambient", "air"],
            "device_classes": [],
            "units": ["ppm", "mg/L", "mg/l"],
        },
    },
    "magnesium": {
        "label": "Magnesium",
        "enabled": False,
        "group": "chemistry",
        "unit": "ppm",
        "min": 1250,
        "max": 1450,
        "target": {
            "domains": ["sensor"],
            "keywords": ["magnesium", "mg", "trident", "neptune"],
            "prefer": ["trident", "apex", "neptune", "reef", "tank", "aquarium"],
            "avoid": ["room", "ambient", "air"],
            "device_classes": [],
            "units": ["ppm", "mg/L", "mg/l"],
        },
    },
    "nitrate": {
        "label": "Nitrate",
        "enabled": False,
        "group": "chemistry",
        "unit": "ppm",
        "min": 0.5,
        "max": 20,
        "target": {
            "domains": ["sensor"],
            "keywords": ["nitrate", "no3", "trident", "np", "neptune"],
            "prefer": ["trident", "apex", "neptune", "reef", "tank", "aquarium"],
            "avoid": ["room", "ambient", "air"],
            "device_classes": [],
            "units": ["ppm", "mg/L", "mg/l"],
        },
    },
    "phosphate": {
        "label": "Phosphate",
        "enabled": False,
        "group": "chemistry",
        "unit": "ppm",
        "min": 0.02,
        "max": 0.12,
        "target": {
            "domains": ["sensor"],
            "keywords": ["phosphate", "po4", "trident", "np", "neptune"],
            "prefer": ["trident", "apex", "neptune", "reef", "tank", "aquarium"],
            "avoid": ["room", "ambient", "air"],
            "device_classes": [],
            "units": ["ppm", "mg/L", "mg/l"],
        },
    },
    "dissolved_oxygen": {
        "label": "Dissolved Oxygen",
        "enabled": False,
        "group": "water",
        "unit": "mg/L",
        "min": 5,
        "max": 9,
        "target": {
            "domains": ["sensor"],
            "keywords": ["dissolved oxygen", "oxygen", "do", "o2"],
            "prefer": ["reef", "tank", "aquarium", "water", "saltwater", "apex", "neptune"],
            "avoid": ["room", "ambient", "air"],
            "device_classes": [],
            "units": ["mg/L", "mg/l", "ppm"],
        },
    },
    "flow": {
        "label": "Flow Rate",
        "enabled": False,
        "group": "flow",
        "unit": "L/h",
        "min": 1,
        "max": 10000,
        "target": {
            "domains": ["sensor"],
            "keywords": ["flow", "flow rate", "return", "pump", "fmm", "fm"],
            "prefer": ["flow", "return", "reef", "tank", "aquarium", "apex", "neptune"],
            "avoid": ["battery", "signal"],
            "device_classes": [],
            "units": ["L/h", "l/h", "lph", "gph"],
        },
    },
    "par": {
        "label": "PAR",
        "enabled": False,
        "group": "lighting",
        "unit": "umol/m2/s",
        "min": 50,
        "max": 350,
        "target": {
            "domains": ["sensor"],
            "keywords": ["par", "photosynthetic", "light", "quantum"],
            "prefer": ["par", "reef", "tank", "aquarium", "light"],
            "avoid": ["power", "energy", "cost"],
            "device_classes": [],
            "units": ["umol/m2/s", "µmol/m²/s", "PAR"],
        },
    },
    "leak": {
        "label": "Leak Detector",
        "enabled": False,
        "group": "safety",
        "kind": "binary",
        "unit": "",
        "min": 0,
        "max": 0,
        "target": {
            "domains": ["binary_sensor", "sensor"],
            "keywords": ["leak", "water leak", "moisture", "flood", "wet"],
            "prefer": ["leak", "moisture", "stand", "cabinet", "sump", "apex", "neptune"],
            "avoid": ["battery", "signal"],
            "device_classes": ["moisture", "problem"],
            "units": [],
        },
    },
    "high_water": {
        "label": "High Water Level",
        "enabled": False,
        "group": "water",
        "kind": "binary",
        "unit": "",
        "min": 0,
        "max": 0,
        "target": {
            "domains": ["binary_sensor", "sensor"],
            "keywords": ["high water", "high level", "overflow", "optical", "level"],
            "prefer": ["high", "level", "overflow", "sump", "tank", "apex", "neptune"],
            "avoid": ["battery", "signal"],
            "device_classes": ["moisture", "problem"],
            "units": [],
        },
    },
    "low_water": {
        "label": "Low Water Level",
        "enabled": False,
        "group": "water",
        "kind": "binary",
        "unit": "",
        "min": 0,
        "max": 0,
        "target": {
            "domains": ["binary_sensor", "sensor"],
            "keywords": ["low water", "low level", "dry", "optical", "level"],
            "prefer": ["low", "level", "dry", "sump", "tank", "apex", "neptune"],
            "avoid": ["battery", "signal"],
            "device_classes": ["moisture", "problem"],
            "units": [],
        },
    },
    "room_temp": {
        "label": "Room Temp",
        "enabled": False,
        "group": "room",
        "unit": "°C",
        "min": 16,
        "max": 28,
        "target": {
            "domains": ["sensor"],
            "keywords": ["temperature", "temp", "room"],
            "prefer": ["room", "ambient", "air"],
            "avoid": ["reef", "tank", "aquarium", "water", "saltwater"],
            "device_classes": ["temperature"],
            "units": ["°C", "°F", "C", "F"],
        },
    },
    "co2": {
        "label": "CO2 Level",
        "enabled": False,
        "group": "room",
        "unit": "ppm",
        "min": 350,
        "max": 1200,
        "target": {
            "domains": ["sensor"],
            "keywords": ["co2", "carbon dioxide"],
            "prefer": ["room", "ambient", "air"],
            "avoid": ["reef", "tank", "aquarium", "water", "saltwater"],
            "device_classes": ["carbon_dioxide"],
            "units": ["ppm"],
        },
    },
    "humidity": {
        "label": "Humidity",
        "enabled": False,
        "group": "room",
        "unit": "%",
        "min": 30,
        "max": 70,
        "target": {
            "domains": ["sensor"],
            "keywords": ["humidity", "humid"],
            "prefer": ["room", "ambient", "air"],
            "avoid": ["reef", "tank", "aquarium", "water", "saltwater"],
            "device_classes": ["humidity"],
            "units": ["%"],
        },
    },
}

# Coral Spawning — the reef-location simulator. OpenReef compiles a curated reef's
# seasonal photoperiod + temperature + lunar program into the exact Apex Season
# Table / Profiles / code reefers hand-author today (Craggs / Rich Ross method).
# Monthly SST is approximate climatology (the GBR/Singapore curves are validated
# against Craggs' published profiles); these are intentionally curated presets,
# with dynamic SST data a later phase. spawn windows follow the documented
# "N nights after the full moon" of the spawning month.
SPAWNING_DEFAULT_SOLAR_NOON_HOUR = 13.0   # local clock time the photoperiod centers on
SPAWNING_SUNUP_RAMP_MIN = 60              # default dawn ramp (minutes)
SPAWNING_SUNSET_RAMP_MIN = 60             # default dusk ramp (minutes) — proximate spawn trigger
SPAWNING_OFFSET_MONTHS_MAX = 11

# Lighting schedule — gates light-dependent alerts (PAR especially) to the hours
# the lights are actually meant to be on, so a 0-PAR reading at night doesn't fire
# a false "below minimum" alert. Reuses the spawning solar math for reef mode.
LIGHTING_SCHEDULE_DEFAULT_GRACE_MIN = 30  # dawn/dusk ramp grace (minutes) — no low alert inside it
LIGHTING_SCHEDULE_GRACE_MAX = 240
LIGHTING_OFFSET_HOURS_MAX = 12.0

REEF_PRESETS: dict[str, dict] = {
    "gbr_central": {
        "label": "Great Barrier Reef (Central)",
        "region": "Coral Sea, Australia",
        "lat": -18.5,
        "lon": 147.5,
        # Davies/central GBR monthly SST (austral summer Dec–Mar). Jan…Dec °C.
        "sstMonthlyC": [28.6, 29.0, 28.7, 27.6, 26.1, 24.7, 23.8, 23.7, 24.6, 26.2, 27.6, 28.2],
        "spawnReefMonth": 11,                 # November mass spawning
        "daysAfterFullMoon": (12, 15),        # per Rich Ross GBR template (packedhead.net)
        "middayParBand": (378, 498),          # Craggs 2017 insolation band
        "note": "Classic Acropora mass spawning. Austral seasons — offset +6 to align to a N-hemisphere summer.",
    },
    "singapore": {
        "label": "Singapore (Kusu Reef)",
        "region": "Coral Triangle, equatorial",
        "lat": 1.3,
        "lon": 103.85,
        "sstMonthlyC": [27.6, 28.0, 28.6, 29.4, 29.9, 29.6, 29.1, 29.0, 28.6, 28.6, 28.1, 27.7],
        "spawnReefMonth": 4,                  # Craggs recorded April spawning
        "daysAfterFullMoon": (2, 6),
        "middayParBand": (378, 498),
        "note": "Equatorial — tiny day-length swing (~minutes); temperature + lunar do the work.",
    },
    "red_sea_aqaba": {
        "label": "Red Sea (Gulf of Aqaba)",
        "region": "Northern Red Sea",
        "lat": 29.5,
        "lon": 34.9,
        "sstMonthlyC": [22.0, 21.4, 21.5, 22.6, 24.2, 25.6, 26.6, 27.0, 26.8, 25.6, 24.2, 22.8],
        "spawnReefMonth": 7,                  # summer spawning
        "daysAfterFullMoon": (2, 7),
        "middayParBand": (300, 450),
        "note": "Strong seasonal swing (cool ~21°C winter). Higher-latitude reef.",
    },
    "hawaii_oahu": {
        "label": "Hawaiʻi (Oʻahu)",
        "region": "Central Pacific",
        "lat": 21.4,
        "lon": -157.8,
        "sstMonthlyC": [24.6, 24.2, 24.2, 24.6, 25.2, 26.0, 26.6, 27.0, 27.1, 26.6, 25.8, 25.0],
        "spawnReefMonth": 7,
        "daysAfterFullMoon": (2, 6),
        "middayParBand": (300, 450),
        "note": "Montipora-led summer spawning; many local spawners cue to the new moon.",
    },
    "caribbean_florida": {
        "label": "Caribbean / Florida Keys",
        "region": "Tropical W. Atlantic",
        "lat": 24.7,
        "lon": -81.0,
        "sstMonthlyC": [23.9, 24.1, 25.0, 26.6, 28.0, 29.4, 30.0, 30.1, 29.6, 28.2, 26.3, 24.7],
        "spawnReefMonth": 8,                  # Acropora palmata/cervicornis, August
        "daysAfterFullMoon": (2, 6),
        "middayParBand": (300, 450),
        "note": "Acropora palmata / cervicornis — restoration-priority Atlantic species.",
    },
}

# --------------------------------------------------------------------------- #
# ICP test importer
# --------------------------------------------------------------------------- #
# Reefers post water samples to ICP labs (Triton, ATI, Fauna Marin, Oceamo, …)
# and get back a panel of ~40 elements. The importer parses a lab file (CSV/PDF)
# in the panel, the backend re-validates it here, stores the full report under
# config["icpReports"], and *fans out* the overlapping core params (Alk/Ca/Mg/
# NO3/PO4/salinity) into the existing manualReadings streams so reef-score,
# the dosing advisor and trends pick them up automatically. ICP also acts as a
# calibration/drift check against the user's frequent test-kit readings.
#
# The registry below is the canonical element table, keyed by chemical symbol
# (plus a few compound tokens — KH/NO3/PO4/Sal — for the non-element params labs
# report). It is OPEN-ENDED: a lab element with no registry entry is still stored
# (category "unknown"), it just gets no canonical range/flag. Each entry carries
# the canonical UNIT OpenReef stores in (units are normalised per-element, never
# per-file — that's what defeats the Si/P mg/L-vs-µg/L 1000× trap) and an alias
# list (lab + German/locale labels, slugified) used to map a lab label → symbol.
ICP_STORAGE_KEY = "icpReports"
ICP_TEMPLATES_KEY = "icpTemplates"
ICP_REPORTS_MAX = 60            # stored ICP reports kept (oldest dropped)
ICP_REPORT_ELEMENTS_MAX = 100   # element rows kept per report
ICP_TEMPLATES_MAX = 25          # saved generic-mapper templates kept

# symbol/token → existing MANUAL_TEST_PARAMETERS id. Only these fan out into the
# core reading streams. The registry's canonical unit for each of these MATCHES
# the MVP_SENSORS unit for the target param, so the fanned value needs no further
# conversion (Ca/Mg/NO3/PO4 → ppm, KH → dKH, Sal → ppt).
ICP_CORE_PARAM_MAP = {
    "Ca": "calcium",
    "Mg": "magnesium",
    "KH": "alkalinity",
    "NO3": "nitrate",
    "PO4": "phosphate",
    "Sal": "salinity",
}

# Drift/calibration check: how far an ICP value may sit from the user's recent
# (non-ICP) test-kit trend before we flag a divergence, per core param.
ICP_DRIFT_TOLERANCE = {"alkalinity": 0.5, "calcium": 20.0, "magnesium": 50.0}
ICP_DRIFT_WINDOW_DAYS = 14

# category: major | minor | nutrient | trace | heavy_metal | organic | physical
# unit: canonical unit stored (ppm = mg/L, ppb = µg/L). range: OpenReef canonical
# fallback (used only when the lab file carries no range); None = no opinion.
# Heavy-metal "high" is a contamination threshold — any value above it flags
# "contaminant"; a heavy metal with no range flags "contaminant" on any detection.
ICP_ELEMENTS = {
    # --- core / fan-out (canonical unit matches MVP_SENSORS) ---------------- #
    "Ca": {"name": "Calcium", "category": "major", "unit": "ppm", "range": {"low": 380, "high": 450},
           "aliases": ["ca", "calcium", "kalzium", "calcio"]},
    "Mg": {"name": "Magnesium", "category": "major", "unit": "ppm", "range": {"low": 1250, "high": 1400},
           "aliases": ["mg", "magnesium"]},
    "KH": {"name": "Alkalinity", "category": "physical", "unit": "dKH", "range": {"low": 7.0, "high": 9.5},
           "aliases": ["kh", "alk", "alkalinity", "alkalinitaet", "alkalinitat", "carbonate hardness",
                       "karbonathaerte", "karbonatharte", "dkh", "acid binding capacity", "saeurebindungsvermoegen"]},
    "NO3": {"name": "Nitrate", "category": "nutrient", "unit": "ppm", "range": {"low": 1.0, "high": 10.0},
            "aliases": ["no3", "nitrate", "nitrat"]},
    "PO4": {"name": "Phosphate", "category": "nutrient", "unit": "ppm", "range": {"low": 0.02, "high": 0.10},
            "aliases": ["po4", "phosphate", "phosphat", "orthophosphate", "orthophosphat"],
            "species_note": "phosphate ion; PO4 = P × 3.066 — distinct from elemental P"},
    "Sal": {"name": "Salinity", "category": "physical", "unit": "ppt", "range": {"low": 33.0, "high": 35.0},
            "aliases": ["sal", "salinity", "salinitaet", "salinitat", "salt", "psu"]},
    # --- other major / minor ions ------------------------------------------ #
    "Na": {"name": "Sodium", "category": "major", "unit": "ppm", "range": {"low": 10500, "high": 11500},
           "aliases": ["na", "sodium", "natrium"]},
    "K": {"name": "Potassium", "category": "major", "unit": "ppm", "range": {"low": 380, "high": 420},
          "aliases": ["k", "potassium", "kalium"]},
    "Sr": {"name": "Strontium", "category": "minor", "unit": "ppm", "range": {"low": 7.0, "high": 9.0},
           "aliases": ["sr", "strontium"]},
    "B": {"name": "Boron", "category": "minor", "unit": "ppm", "range": {"low": 4.0, "high": 5.0},
          "aliases": ["b", "boron", "bor"]},
    "S": {"name": "Sulfur", "category": "major", "unit": "ppm", "range": {"low": 840, "high": 960},
          "aliases": ["s", "sulfur", "sulphur", "schwefel"],
          "species_note": "elemental sulfur; distinct from sulfate (SO4 = S × 2.996)"},
    "SO4": {"name": "Sulfate", "category": "major", "unit": "ppm", "range": {"low": 2400, "high": 2900},
            "aliases": ["so4", "sulfate", "sulphate", "sulfat"],
            "species_note": "sulfate ion; distinct from elemental S"},
    "Br": {"name": "Bromine", "category": "minor", "unit": "ppm", "range": {"low": 60, "high": 75},
           "aliases": ["br", "bromine", "bromide", "brom", "bromid"]},
    "Cl": {"name": "Chloride", "category": "major", "unit": "ppm", "range": {"low": 19000, "high": 20000},
           "aliases": ["cl", "chloride", "chlor", "chlorid", "chlorine"]},
    "F": {"name": "Fluoride", "category": "minor", "unit": "ppm", "range": {"low": 1.0, "high": 1.5},
          "aliases": ["f", "fluoride", "fluorid", "fluorine"]},
    "Li": {"name": "Lithium", "category": "trace", "unit": "ppb", "range": {"low": 150, "high": 200},
           "aliases": ["li", "lithium"]},
    # --- nutrients --------------------------------------------------------- #
    "P": {"name": "Phosphorus", "category": "nutrient", "unit": "ppb", "range": {"low": 0, "high": 40},
          "aliases": ["p", "phosphorus", "phosphor"],
          "species_note": "elemental P; some labs report mg/L, others µg/L — PO4 = P × 3.066"},
    "Si": {"name": "Silicon", "category": "nutrient", "unit": "ppb", "range": {"low": 0, "high": 100},
           "aliases": ["si", "silicon", "silicate", "silicat", "silizium", "silica", "silikat"],
           "species_note": "Si; reported mg/L on some labs (e.g. Fauna Marin), µg/L on most — 1000× hazard"},
    "NO2": {"name": "Nitrite", "category": "nutrient", "unit": "ppm", "range": {"low": 0, "high": 0.05},
            "aliases": ["no2", "nitrite", "nitrit"]},
    # --- trace elements (µg/L) --------------------------------------------- #
    "I": {"name": "Iodine", "category": "trace", "unit": "ppb", "range": {"low": 50, "high": 70},
          "aliases": ["i", "iodine", "iod", "jod", "iodide", "iodid"]},
    "Fe": {"name": "Iron", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["fe", "iron", "eisen"]},
    "Mn": {"name": "Manganese", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["mn", "manganese", "mangan"]},
    "Mo": {"name": "Molybdenum", "category": "trace", "unit": "ppb", "range": {"low": 8, "high": 14},
           "aliases": ["mo", "molybdenum", "molybdaen", "molybdan"]},
    "Ni": {"name": "Nickel", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["ni", "nickel"]},
    "Co": {"name": "Cobalt", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["co", "cobalt", "kobalt"]},
    "Cr": {"name": "Chromium", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["cr", "chromium", "chrom", "chrome"]},
    "V": {"name": "Vanadium", "category": "trace", "unit": "ppb", "range": None,
          "aliases": ["v", "vanadium", "vanadin"]},
    "Zn": {"name": "Zinc", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["zn", "zinc", "zink"]},
    "Ba": {"name": "Barium", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["ba", "barium"]},
    "Be": {"name": "Beryllium", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["be", "beryllium"]},
    "Se": {"name": "Selenium", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["se", "selenium", "selen"]},
    "Rb": {"name": "Rubidium", "category": "trace", "unit": "ppb", "range": {"low": 100, "high": 130},
           "aliases": ["rb", "rubidium"]},
    "W": {"name": "Tungsten", "category": "trace", "unit": "ppb", "range": None,
          "aliases": ["w", "tungsten", "wolfram"]},
    "Ti": {"name": "Titanium", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["ti", "titanium", "titan"]},
    "La": {"name": "Lanthanum", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["la", "lanthanum", "lanthan"],
           "species_note": "elevated La flags carry-over from lanthanum-chloride phosphate removers"},
    "Sc": {"name": "Scandium", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["sc", "scandium"]},
    "Ga": {"name": "Gallium", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["ga", "gallium"]},
    "Cs": {"name": "Caesium", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["cs", "caesium", "cesium", "caesium"]},
    "Te": {"name": "Tellurium", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["te", "tellurium", "tellur"]},
    "In": {"name": "Indium", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["in", "indium"]},
    "Zr": {"name": "Zirconium", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["zr", "zirconium", "zirkonium"]},
    "Nd": {"name": "Neodymium", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["nd", "neodymium", "neodym"]},
    "Ru": {"name": "Ruthenium", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["ru", "ruthenium"]},
    "Ce": {"name": "Cerium", "category": "trace", "unit": "ppb", "range": None,
           "aliases": ["ce", "cerium", "cer"]},
    # --- heavy metals & contaminants (µg/L; "high" = contamination threshold) #
    "Cu": {"name": "Copper", "category": "heavy_metal", "unit": "ppb", "range": {"low": 0, "high": 5},
           "aliases": ["cu", "copper", "kupfer"], "species_note": "toxic to invertebrates"},
    "Al": {"name": "Aluminium", "category": "heavy_metal", "unit": "ppb", "range": {"low": 0, "high": 10},
           "aliases": ["al", "aluminium", "aluminum"]},
    "Pb": {"name": "Lead", "category": "heavy_metal", "unit": "ppb", "range": {"low": 0, "high": 2},
           "aliases": ["pb", "lead", "blei"]},
    "Hg": {"name": "Mercury", "category": "heavy_metal", "unit": "ppb", "range": {"low": 0, "high": 1},
           "aliases": ["hg", "mercury", "quecksilber"]},
    "Cd": {"name": "Cadmium", "category": "heavy_metal", "unit": "ppb", "range": {"low": 0, "high": 1},
           "aliases": ["cd", "cadmium"]},
    "As": {"name": "Arsenic", "category": "heavy_metal", "unit": "ppb", "range": {"low": 0, "high": 3},
           "aliases": ["as", "arsenic", "arsen"]},
    "Sb": {"name": "Antimony", "category": "heavy_metal", "unit": "ppb", "range": {"low": 0, "high": 2},
           "aliases": ["sb", "antimony", "antimon"]},
    "Sn": {"name": "Tin", "category": "heavy_metal", "unit": "ppb", "range": {"low": 0, "high": 2},
           "aliases": ["sn", "tin", "zinn"]},
    "Ag": {"name": "Silver", "category": "heavy_metal", "unit": "ppb", "range": {"low": 0, "high": 1},
           "aliases": ["ag", "silver", "silber"]},
    "Bi": {"name": "Bismuth", "category": "heavy_metal", "unit": "ppb", "range": {"low": 0, "high": 2},
           "aliases": ["bi", "bismuth", "wismut"]},
    "Tl": {"name": "Thallium", "category": "heavy_metal", "unit": "ppb", "range": {"low": 0, "high": 1},
           "aliases": ["tl", "thallium"]},
    "U": {"name": "Uranium", "category": "heavy_metal", "unit": "ppb", "range": {"low": 0, "high": 5},
          "aliases": ["u", "uranium", "uran"]},
    "Th": {"name": "Thorium", "category": "heavy_metal", "unit": "ppb", "range": {"low": 0, "high": 2},
           "aliases": ["th", "thorium"]},
    # --- organics (heterogeneous — never coerce into one DOC field) -------- #
    "TOC": {"name": "Total Organic Carbon", "category": "organic", "unit": "mg/L", "range": None,
            "aliases": ["toc", "total organic carbon"]},
    "TIC": {"name": "Total Inorganic Carbon", "category": "organic", "unit": "mg/L", "range": None,
            "aliases": ["tic", "total inorganic carbon"]},
    "TNb": {"name": "Total Nitrogen (bound)", "category": "organic", "unit": "mg/L", "range": None,
            "aliases": ["tnb", "total nitrogen", "gebundener stickstoff"]},
    "DOC": {"name": "Dissolved Organic Carbon", "category": "organic", "unit": "mg/L", "range": None,
            "aliases": ["doc", "dissolved organic carbon"]},
    "SAC254": {"name": "Spectral Absorption (254nm)", "category": "organic", "unit": "1/m", "range": None,
               "aliases": ["sac254", "sak254", "spektraler absorptionskoeffizient"]},
    # --- physical ---------------------------------------------------------- #
    "pH": {"name": "pH", "category": "physical", "unit": "", "range": {"low": 7.9, "high": 8.4},
           "aliases": ["ph", "ph-wert"]},
}

DEFAULT_CORE_CONFIG = {
    "schemaVersion": CORE_SCHEMA_VERSION,
    "tank": {
        "name": NAME,
        "owner": "",
        "profile": DEFAULT_TANK_PROFILE,
    },
    "display": {
        "themeColor": "#00b4d8",
        "setupComplete": False,
        "missionCards": {
            "live": True,
            "controls": True,
            "energy": True,
        },
    },
    "sensors": {
        sensor_id: {
            "entity_id": "",
            "label": meta["label"],
            "enabled": meta["enabled"],
            "group": meta["group"],
            "kind": meta.get("kind", "numeric"),
            "unit": meta["unit"],
            "min": meta["min"],
            "max": meta["max"],
            "alertsEnabled": True,
            "warningBuffer": 10,
            # Gate low-side alerts to the lighting schedule (light-dependent sensors
            # like PAR read ~0 when lights are off — don't alert then). Default on
            # for lighting-group sensors only.
            "lightGated": meta.get("group") == "lighting",
        }
        for sensor_id, meta in MVP_SENSORS.items()
    },
    "equipment": {},
    "cameras": {},
    "capture": {
        "enabled": False,
        "cameraIds": [],
        "durationSeconds": CAPTURE_DEFAULT_DURATION,
        "lookbackSeconds": CAPTURE_DEFAULT_LOOKBACK,
        "retention": CAPTURE_DEFAULT_RETENTION,
        "cooldownSeconds": CAPTURE_DEFAULT_COOLDOWN,
        "triggers": {
            "criticalAlerts": True,
            "warningAlerts": False,
            "modeChanges": False,
            "skimmerAutoOff": True,
            "atoWindows": False,
            "feedMode": False,
        },
    },
    "captures": [],
    "timelapse": {
        "enabled": False,
        "cameraId": "",
        "cadenceMinutes": TIMELAPSE_DEFAULT_CADENCE,
        "windowStart": TIMELAPSE_DEFAULT_WINDOW_START,
        "windowEnd": TIMELAPSE_DEFAULT_WINDOW_END,
        "retention": {
            "detailDays": TIMELAPSE_DEFAULT_DETAIL_DAYS,
            "dailyUntilDays": TIMELAPSE_DEFAULT_DAILY_DAYS,
            "weeklyUntilDays": TIMELAPSE_DEFAULT_WEEKLY_DAYS,
            "monthlyUntilDays": TIMELAPSE_DEFAULT_MONTHLY_DAYS,
        },
    },
    # Camera V2 — live overlay + shareable tank card (Phase C). Selected stats (+ optional
    # Reef Buddy avatar and a cheeky anti-Apex quip) burned onto the live feed and into a
    # one-tap shareable image. Purely a frontend read of live state; config just persists
    # the user's selections.
    "overlay": {
        "enabled": False,
        "stats": ["temp", "ph", "alkalinity"],
        "showReefHealth": True,
        "showTankName": True,
        "showAvatar": True,
        "showQuip": True,
        "position": "bottom-left",
    },
    "feedWatch": {
        "enabled": False,
        "cameraId": "",
        "cadenceSeconds": FEEDWATCH_DEFAULT_CADENCE,
        "retentionSessions": FEEDWATCH_DEFAULT_RETENTION,
    },
    "feedSessions": [],
    "energy": {
        "tariff": 0.28,
        "currency": "GBP",
        "daily_energy_entity_id": "",
        "weekly_energy_entity_id": "",
        "monthly_energy_entity_id": "",
        "daily_cost_entity_id": "",
        "weekly_cost_entity_id": "",
        "monthly_cost_entity_id": "",
    },
    "mode": {
        "active": "running",
        "startedAt": "",
        "expiresAt": "",
        "autoReturn": False,
        "returnPlan": {},
    },
    "modePreviews": {
        "feed": {},
        "maintenance": {},
    },
    "modeTimers": {
        "feed": {
            "durationMinutes": 10,
            "autoReturn": False,
        },
        "maintenance": {
            "durationMinutes": 60,
            "autoReturn": False,
        },
    },
    "customModes": [],
    "modeSettings": {
        "feed": {
            "label": "Feed",
            "description": "Temporarily changes selected armed equipment after confirmation.",
        },
        "maintenance": {
            "label": "Maintenance",
            "description": "Applies a hands-in-tank equipment plan after confirmation.",
        },
    },
    "modeSchedule": {
        "enabled": False,
        "items": [],
        "lastRuns": {},
    },
    "alerts": {
        "persistentNotifications": False,
        "notifyCriticalOnly": True,
        "hysteresisPercent": 2,
        "wavemakerReminders": True,
        "wavemakerReminderMinutes": 10,
        "muteUntil": {},
        "history": [],
        "lastStates": {},
    },
    "watchdog": {
        "enabled": True,
        "heartbeatEnabled": True,
        "heartbeatEveryHours": 24,
        "missedAfterHours": 30,
        "notifyTarget": "",
        "lastCheck": "",
        "lastHeartbeat": "",
        "lastNotificationTest": "",
        "lastMissedAlert": "",
    },
    "sensorHealth": {
        "enabled": True,
        "staleAfterMinutes": 180,
        "flatlineHours": 12,
        "jumpWindowMinutes": 30,
        "jumpPercent": 25,
        "temperatureMismatchC": 1.5,
        "lastValues": {},
        "lastJumps": {},
    },
    "alertEscalation": {
        "enabled": False,
        "criticalOnly": True,
        "repeatMinutes": 30,
        "notifyTarget": "",
        "acknowledgeRequired": True,
        "sirenEntityId": "",
        "lightEntityId": "",
        "acknowledged": {},
        "lastEscalated": {},
        "outputsActive": False,
    },
    "trustCheck": {
        "enabled": True,
        "lastRun": "",
        "lastStatus": "unknown",
        "lastBackupReview": "",
    },
    "edgeFailsafes": {
        "enabled": False,
        "heater": False,
        "ato": False,
        "returnPump": False,
        "lastReviewed": "",
        "notes": "",
    },
    "reefReplay": {
        "enabled": True,
        "incidentWindowMinutes": 20,
        "retention": 25,
    },
    "interlocks": {
        "heaterRequiresTankTemp": True,
        "atoMaxRuntimeEnabled": False,
        "atoMaxRuntimeSeconds": 300,
        "atoDutyCycleEnabled": False,
        "atoDutyCycleOnSeconds": 120,
        "atoDutyCycleIntervalMinutes": 60,
        "atoDutyCycleAnchorTime": "00:00",
        "returnPumpSkimmerWarning": True,
        "skimmerAutoOffWhenReturnPumpOff": False,
        "atoReturnPumpWarning": True,
        "atoBlockWhenReturnPumpOff": False,
    },
    "activity": [],
    "modes": [],
    "manualReadings": {},
    "manualTests": {
        "enabled": True,
        "schedules": {
            parameter: {
                "enabled": False,
                "cadenceDays": MANUAL_TEST_CADENCE_PRESETS[DEFAULT_TANK_PROFILE][parameter],
                "criticalAfterDays": MANUAL_TEST_CADENCE_PRESETS[DEFAULT_TANK_PROFILE][parameter] * 2,
                "preferredSource": "",
            }
            for parameter in MANUAL_TEST_PARAMETERS
        },
    },
    "maintenance": {
        "enabled": True,
        "seeded": False,
        "tasks": {},
        "completions": {},
        "reminders": {
            "enabled": True,
            "time": MAINTENANCE_REMINDER_DEFAULT_TIME,
            "notifyTarget": "",
            "persistent": True,
        },
    },
    # Reef Pulse — full-screen presentation / kiosk mode. Display-only (no control
    # actions); every block is user-toggleable. cameraId "" = auto (first online).
    # backdrop: auto = camera when one is online, else the data wall; camera/wall force it.
    "pulse": {
        "enabled": True,
        "showHealthRing": True,
        "showStats": True,
        "showTicker": True,
        "showMode": True,
        "showBuddy": True,
        "showClock": True,
        "kioskAutoStart": False,
        "cameraId": "",
        "backdrop": "auto",
        "graphRange": "24h",
        "showSparklines": True,
        "showCategories": True,
        "showEquipment": True,
        "showToday": True,
    },
    "dosing": {
        "enabled": True,
        "system": {
            "primaryProduct": "",
            "secondaryProduct": "",
            "secondaryDelivery": "",
            "tankVolumeLitres": 0,
            "sharedDailyDoseMl": 0,
            "kalkDailyDoseMl": 0,
            "kalkConcentrationTspPerGallon": 0,
            "kalkEvaporationLimitMlPerDay": 0,
            "kalkMaxPh": 8.45,
            "kalkMaxPhRise": 0.2,
            "freshTestRequired": True,
            "safetyAcknowledged": False,
            "customProductName": "",
            "customProductClass": "custom_verified_strength",
            "customNotes": "",
        },
        "parameters": {
            parameter: {
                "productPreset": "custom",
                "doserMlPerDay": 0,
                "potencyPerMl": 0,
                "target": 0,
                "tankVolumeLitres": 0,
                "productDoseMl": 0,
                "productVolumeLitres": 0,
                "productRaise": 0,
            }
            for parameter in DOSING_PARAMETERS
        },
    },
    # Lighting schedule — drives when light-dependent (lightGated) sensor alerts
    # may fire. mode "off" = no gating (alerts always evaluated, legacy behaviour).
    "lightingSchedule": {
        "mode": "off",                 # off | simple | reef
        "onTime": "08:00",             # simple mode
        "offTime": "20:00",            # simple mode
        "reefPreset": "gbr_central",   # reef mode — reuses REEF_PRESETS
        "offsetHours": 0,              # reef mode — shift the photoperiod to your clock
        "rampGraceMinutes": LIGHTING_SCHEDULE_DEFAULT_GRACE_MIN,
    },
    # Coral Spawning — reef-location simulator. Persists the user's selection; the
    # program itself is compiled on demand (openreef/generate_spawning_program).
    "spawningProgram": {
        "enabled": False,
        "reefPreset": "gbr_central",
        "offsetMonths": 0,
        "solarNoonHour": SPAWNING_DEFAULT_SOLAR_NOON_HOUR,
        "tempUnit": "C",
        "tempProbe": "Tmp",
        "acknowledgedAdvisory": False,
    },
    # ICP test importer — stored lab reports + saved generic-mapper templates.
    # Reports are appended on import; overlapping core params are also fanned out
    # into manualReadings (see ICP_CORE_PARAM_MAP).
    "icpReports": [],
    "icpTemplates": [],
}

DEFAULT_SETTINGS = {
    **DEFAULT_CORE_CONFIG,
}
