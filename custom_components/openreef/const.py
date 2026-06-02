"""Constants for the OpenReef integration."""

from __future__ import annotations

DOMAIN = "openreef"
NAME = "OpenReef"
PANEL_ICON = "mdi:fishbowl"
PANEL_URL = "openreef"
PANEL_STATIC_URL = "/openreef_static"

CONF_SETTINGS = "settings"
CORE_SCHEMA_VERSION = 31
INTEGRATION_VERSION = "0.4.62"

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

SERVICE_APPLY_MODE = "apply_mode"
SERVICE_ARM_EQUIPMENT = "arm_equipment"
SERVICE_DISARM_EQUIPMENT = "disarm_equipment"
SERVICE_RECORD_MANUAL_READING = "record_manual_reading"

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
        }
        for sensor_id, meta in MVP_SENSORS.items()
    },
    "equipment": {},
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
    "dosing": {
        "enabled": True,
        "system": {
            "primaryProduct": "",
            "secondaryProduct": "",
            "secondaryDelivery": "",
            "tankVolumeLitres": 0,
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
}

DEFAULT_SETTINGS = {
    **DEFAULT_CORE_CONFIG,
}
