"""Constants for the OpenReef integration."""

from __future__ import annotations

DOMAIN = "openreef"
NAME = "OpenReef"

CONF_SETTINGS = "settings"

SERVICE_APPLY_MODE = "apply_mode"
SERVICE_RECORD_MANUAL_READING = "record_manual_reading"

ISSUE_MISSING_ENTITIES = "missing_entities"

DEFAULT_SETTINGS = {
    "schemaVersion": 1,
    "general": {
        "tankName": NAME,
        "userName": "",
        "themeColor": "#00b4d8",
        "activeMode": None,
        "energyTariff": 0.28,
        "haUrl": "",
        "haToken": "",
        "googleSheetId": "",
    },
    "entities": {
        "tank": {},
        "room": {},
        "equipment": {},
        "modes": {},
        "tankMain": {},
        "energy": {},
    },
    "equipment": {"aliases": {}},
    "modes": [],
    "thresholds": {},
    "manualReadings": {},
}
