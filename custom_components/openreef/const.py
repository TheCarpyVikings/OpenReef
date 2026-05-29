"""Constants for the OpenReef integration."""

from __future__ import annotations

DOMAIN = "openreef"
NAME = "OpenReef"
PANEL_ICON = "mdi:fishbowl"
PANEL_URL = "openreef"
PANEL_STATIC_URL = "/openreef_static"

CONF_SETTINGS = "settings"
CORE_SCHEMA_VERSION = 22
INTEGRATION_VERSION = "0.4.23"

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
}

DEFAULT_SETTINGS = {
    **DEFAULT_CORE_CONFIG,
}
