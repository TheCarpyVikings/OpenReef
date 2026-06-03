"""OpenReef Home Assistant native controller integration."""

from __future__ import annotations

import logging
import re
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_point_in_time, async_track_time_change
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import (
    CAPTURE_DEFAULT_COOLDOWN,
    CAPTURE_DEFAULT_DURATION,
    CAPTURE_DEFAULT_LOOKBACK,
    CAPTURE_DEFAULT_RETENTION,
    CAPTURE_MAX_COOLDOWN,
    CAPTURE_MAX_DURATION,
    CAPTURE_MAX_LOOKBACK,
    CAPTURE_MAX_RECORDS,
    CAPTURE_MIN_DURATION,
    CAPTURES_DIR_NAME,
    CAPTURES_STATIC_URL,
    CONF_SETTINGS,
    DEFAULT_CORE_CONFIG,
    DEFAULT_TANK_PROFILE,
    DOMAIN,
    DOSING_PARAMETERS,
    ISSUE_ARMED_UNAVAILABLE,
    ISSUE_LEGACY_LABS_CONFIG,
    ISSUE_MISSING_ENTITIES,
    INTEGRATION_VERSION,
    MANUAL_TEST_CADENCE_PRESETS,
    MANUAL_TEST_PARAMETERS,
    MVP_SENSORS,
    NAME,
    PANEL_ICON,
    PANEL_STATIC_URL,
    PANEL_URL,
    SERVICE_APPLY_MODE,
    SERVICE_ARM_EQUIPMENT,
    SERVICE_DISARM_EQUIPMENT,
    SERVICE_RECORD_MANUAL_READING,
    TANK_PROFILE_CHOICES,
    TIMELAPSE_DEFAULT_CADENCE,
    TIMELAPSE_DEFAULT_DAILY_DAYS,
    TIMELAPSE_DEFAULT_DETAIL_DAYS,
    TIMELAPSE_DEFAULT_MONTHLY_DAYS,
    TIMELAPSE_DEFAULT_WEEKLY_DAYS,
    TIMELAPSE_DEFAULT_WINDOW_END,
    TIMELAPSE_DEFAULT_WINDOW_START,
    TIMELAPSE_MAX_CADENCE,
    TIMELAPSE_MAX_DAYS,
    TIMELAPSE_MIN_CADENCE,
    TIMELAPSE_SUBDIR,
)

type OpenReefConfigEntry = ConfigEntry

_LOGGER = logging.getLogger(__name__)


SEARCH_LIMIT = 10
UNAVAILABLE_STATES = {"unknown", "unavailable"}
BUILT_IN_MODES = {"running", "feed", "maintenance"}
WEEK_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
MODE_TIMER_UNSUB = "mode_timer_unsub"
MODE_SCHEDULE_UNSUB = "mode_schedule_unsub"
ATO_DUTY_CYCLE_UNSUB = "ato_duty_cycle_unsub"
ATO_DUTY_CYCLE_OFF_UNSUB = "ato_duty_cycle_off_unsub"
ATO_DUTY_CYCLE_LAST = "ato_duty_cycle_last"
DELAYED_EQUIPMENT_UNSUBS = "delayed_equipment_unsubs"
WAVEMAKER_REMINDER_UNSUB = "wavemaker_reminder_unsub"
WAVEMAKER_REMINDER_LAST = "wavemaker_reminder_last"
CAPTURES_PATH_REGISTERED = "captures_path_registered"
CAPTURE_LAST = "capture_last"
CAPTURE_INFLIGHT = "capture_inflight"
TIMELAPSE_UNSUB = "timelapse_unsub"
TIMELAPSE_LAST = "timelapse_last"
# Maps an OpenReef event type -> the user-configurable trigger toggle that gates it.
CAPTURE_TRIGGER_FIELD = {
    "critical_alert": "criticalAlerts",
    "warning_alert": "warningAlerts",
    "mode_change": "modeChanges",
    "skimmer_auto_off": "skimmerAutoOff",
    "ato_window": "atoWindows",
    "feed_mode": "feedMode",
}
EQUIPMENT_PROFILE_TYPES = {
    "return_pump",
    "display_wavemaker",
    "flow_pump",
    "heater",
    "skimmer",
    "ato",
    "lighting",
    "doser",
    "filtration",
    "other",
}

APPLY_MODE_SCHEMA = vol.Schema({vol.Required("mode_id"): cv.string})

EQUIPMENT_ARM_SCHEMA = vol.Schema({vol.Required("equipment_id"): cv.string})

RECORD_MANUAL_READING_SCHEMA = vol.Schema(
    {
        vol.Required("parameter"): cv.string,
        vol.Required("value"): vol.Coerce(float),
        vol.Optional("date"): cv.string,
    }
)


def _entries(hass: HomeAssistant) -> list[OpenReefConfigEntry]:
    return hass.config_entries.async_entries(DOMAIN)


def _first_entry(hass: HomeAssistant) -> OpenReefConfigEntry | None:
    entries = _entries(hass)
    return entries[0] if entries else None


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        elif isinstance(merged.get(key), dict) and not isinstance(value, dict):
            # A corrupted scalar must not clobber a structured default block
            # (otherwise later normalisation crashes on e.g. sensors.setdefault).
            continue
        else:
            merged[key] = deepcopy(value)
    return merged


def _normalise_entity_id(value: Any) -> str:
    if isinstance(value, str) and "." in value:
        return value.strip()
    return ""


def _normalise_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(
        "".join(char.lower() if char.isalnum() else " " for char in value).split()
    )


def _normalise_equipment_profile(value: Any) -> str:
    text = _normalise_text(value).replace(" ", "_")
    aliases = {
        "return": "return_pump",
        "returnpump": "return_pump",
        "return_pump": "return_pump",
        "wavemaker": "display_wavemaker",
        "wave_maker": "display_wavemaker",
        "display_wavemaker": "display_wavemaker",
        "powerhead": "display_wavemaker",
        "flow": "flow_pump",
        "flow_pump": "flow_pump",
        "pump": "flow_pump",
        "temperature": "heater",
        "heater": "heater",
        "chiller": "heater",
        "skimmer": "skimmer",
        "ato": "ato",
        "top_off": "ato",
        "rodi": "ato",
        "light": "lighting",
        "lights": "lighting",
        "lighting": "lighting",
        "doser": "doser",
        "dosers": "doser",
        "dosing": "doser",
        "filter": "filtration",
        "filtration": "filtration",
        "reactor": "filtration",
        "other": "other",
    }
    return aliases.get(text, text if text in EQUIPMENT_PROFILE_TYPES else "")


def _normalise_tank_profile(value: Any) -> str:
    if not isinstance(value, str):
        return DEFAULT_TANK_PROFILE
    key = value.strip().lower()
    return key if key in TANK_PROFILE_CHOICES else DEFAULT_TANK_PROFILE


def _infer_equipment_profile(equipment_id: str, equipment_config: dict[str, Any]) -> str:
    explicit = _normalise_equipment_profile(
        equipment_config.get("type") or equipment_config.get("profile")
    )
    if explicit:
        return explicit
    if equipment_config.get("displayWavemaker", False):
        return "display_wavemaker"

    text = _normalise_text(f"{equipment_id} {equipment_config.get('label') or ''}")
    if any(term in text for term in ("wave", "wavemaker", "powerhead", "gyre")):
        return "display_wavemaker"
    if "return" in text:
        return "return_pump"
    if any(term in text for term in ("heater", "chiller")):
        return "heater"
    if "skimmer" in text:
        return "skimmer"
    if any(term in text for term in ("ato", "top off", "rodi")):
        return "ato"
    if any(term in text for term in ("light", "kessil", "hydra")):
        return "lighting"
    if any(term in text for term in ("doser", "dosing")):
        return "doser"
    if any(term in text for term in ("filter", "reactor")):
        return "filtration"
    if "pump" in text:
        return "flow_pump"
    return "other"


def _normalise_mode_id(value: Any) -> str:
    text = _normalise_text(value).replace(" ", "_")
    if not text or text in BUILT_IN_MODES:
        return ""
    return text[:48]


def _normalise_schedule_id(value: Any, fallback: str) -> str:
    text = _normalise_text(value).replace(" ", "_")
    if not text:
        text = fallback
    return text[:64]


def _normalise_schedule_time(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    parts = value.strip().split(":")
    if len(parts) != 2:
        return ""
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return ""
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return ""
    return f"{hour:02d}:{minute:02d}"


def _hhmm_to_minutes(value: Any) -> int | None:
    """'HH:MM' -> minutes since midnight, or None if invalid."""
    normalised = _normalise_schedule_time(value)
    if not normalised:
        return None
    hour, minute = normalised.split(":")
    return int(hour) * 60 + int(minute)


def _normalise_schedule_times(value: Any, fallback: Any = None) -> list[str]:
    raw_times = value if isinstance(value, list) else []
    if not raw_times and fallback is not None:
        raw_times = [fallback]

    times: list[str] = []
    for raw_time in raw_times:
        schedule_time = _normalise_schedule_time(raw_time)
        if schedule_time and schedule_time not in times:
            times.append(schedule_time)
    return times[:24]


def _normalise_dosing_product_id(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower().replace(" ", "_")[:120]


def _normalise_dosing_delivery(value: Any) -> str:
    key = _normalise_dosing_product_id(value)
    return key if key in {"ato", "dosing_pump", "manual_top_off"} else ""


def _infer_dosing_primary_from_parameters(parameters: dict[str, Any]) -> str:
    presets: list[str] = []
    for raw in parameters.values():
        if not isinstance(raw, dict):
            continue
        preset = _normalise_dosing_product_id(raw.get("productPreset"))
        if preset and preset not in {"custom", "kalkwasser_calcium_hydroxide"}:
            presets.append(preset)
    if any(preset.startswith("seachem_reef_fusion") for preset in presets):
        return "seachem_reef_fusion"
    if any(preset.startswith("red_sea_foundation") for preset in presets):
        return "custom_verified_strength"
    for preset in presets:
        return preset
    return ""


def _normalise_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0]


def _has_phrase(haystack: str, phrase: str) -> bool:
    needle = _normalise_text(phrase)
    return bool(needle and needle in haystack)


def _has_token(haystack: str, token: str) -> bool:
    needle = _normalise_text(token)
    return bool(needle and f" {needle} " in f" {haystack} ")


def _score_terms(haystack: str, terms: list[str], points: int) -> int:
    score = 0
    for term in terms:
        normalised = _normalise_text(term)
        if not normalised:
            continue
        if len(normalised) <= 3:
            score += points if _has_token(haystack, normalised) else 0
        else:
            score += points if _has_phrase(haystack, normalised) else 0
    return score


def _legacy_to_core_config(settings: dict[str, Any]) -> dict[str, Any]:
    """Convert the old full-dashboard settings shape into the new core config."""
    core = deepcopy(DEFAULT_CORE_CONFIG)
    general = settings.get("general", {})
    entities = settings.get("entities", {})
    thresholds = settings.get("thresholds", {})
    labels = settings.get("labels", {})
    equipment_aliases = settings.get("equipment", {}).get("aliases", {})

    if isinstance(general, dict):
        core["tank"]["name"] = general.get("tankName") or NAME
        core["tank"]["owner"] = general.get("userName") or ""
        core["tank"]["profile"] = _normalise_tank_profile(general.get("tankProfile"))
        core["display"]["themeColor"] = general.get("themeColor") or "#00b4d8"
        core["energy"]["tariff"] = general.get("energyTariff") or 0.28

    tank = entities.get("tank", {}) if isinstance(entities, dict) else {}
    room = entities.get("room", {}) if isinstance(entities, dict) else {}
    sensor_sources = {
        "temp": tank.get("temp") if isinstance(tank, dict) else "",
        "ph": tank.get("ph") if isinstance(tank, dict) else "",
        "salinity": tank.get("salinity") if isinstance(tank, dict) else "",
        "room_temp": room.get("temp") if isinstance(room, dict) else "",
        "co2": room.get("co2") if isinstance(room, dict) else "",
        "humidity": room.get("humidity") if isinstance(room, dict) else "",
    }

    for sensor_id, entity_id in sensor_sources.items():
        if sensor_id not in core["sensors"]:
            continue
        core["sensors"][sensor_id]["entity_id"] = _normalise_entity_id(entity_id)
        core["sensors"][sensor_id]["enabled"] = bool(core["sensors"][sensor_id]["entity_id"])
        if isinstance(labels, dict) and labels.get(sensor_id):
            core["sensors"][sensor_id]["label"] = labels[sensor_id]
        if isinstance(thresholds, dict) and isinstance(thresholds.get(sensor_id), dict):
            threshold = thresholds[sensor_id]
            core["sensors"][sensor_id]["min"] = threshold.get(
                "min", core["sensors"][sensor_id]["min"]
            )
            core["sensors"][sensor_id]["max"] = threshold.get(
                "max", core["sensors"][sensor_id]["max"]
            )

    equipment = entities.get("equipment", {}) if isinstance(entities, dict) else {}
    if isinstance(equipment, dict):
        for equipment_id, config in equipment.items():
            if not isinstance(config, dict):
                continue
            core["equipment"][equipment_id] = {
                "label": equipment_aliases.get(equipment_id, equipment_id)
                if isinstance(equipment_aliases, dict)
                else equipment_id,
                "switch_entity_id": _normalise_entity_id(config.get("switch")),
                "power_entity_id": _normalise_entity_id(config.get("power")),
                "energy_entity_id": _normalise_entity_id(config.get("energy")),
                "cost_entity_id": "",
                "armed": bool(config.get("controlEnabled", False)),
            }

    energy = entities.get("energy", {}) if isinstance(entities, dict) else {}
    if isinstance(energy, dict):
        core["energy"].update(
            {
                "daily_energy_entity_id": _normalise_entity_id(energy.get("dailyEnergy")),
                "weekly_energy_entity_id": _normalise_entity_id(energy.get("weeklyEnergy")),
                "monthly_energy_entity_id": _normalise_entity_id(energy.get("monthlyEnergy")),
                "daily_cost_entity_id": _normalise_entity_id(energy.get("dailyCost")),
                "weekly_cost_entity_id": _normalise_entity_id(energy.get("weeklyCost")),
                "monthly_cost_entity_id": _normalise_entity_id(energy.get("monthlyCost")),
            }
        )

    core["modes"] = settings.get("modes") if isinstance(settings.get("modes"), list) else []
    if isinstance(core["modes"], list):
        for mode in core["modes"]:
            if not isinstance(mode, dict):
                continue
            mode_id = mode.get("id")
            if mode_id not in core["modeTimers"]:
                continue
            try:
                duration = int(mode.get("duration", core["modeTimers"][mode_id]["durationMinutes"]))
            except (TypeError, ValueError):
                continue
            core["modeTimers"][mode_id]["durationMinutes"] = max(0, min(duration, 720))
    core["mode"]["active"] = "running"
    core["mode"]["startedAt"] = ""
    core["manualReadings"] = (
        settings.get("manualReadings")
        if isinstance(settings.get("manualReadings"), dict)
        else {}
    )
    core["display"]["setupComplete"] = any(
        sensor.get("entity_id") for sensor in core["sensors"].values()
    )
    return core


def _normalise_core_config(settings: Any) -> dict[str, Any]:
    if not isinstance(settings, dict):
        return deepcopy(DEFAULT_CORE_CONFIG)
    if "general" in settings or "entities" in settings:
        return _legacy_to_core_config(settings)

    config = _deep_merge(DEFAULT_CORE_CONFIG, settings)
    config["schemaVersion"] = DEFAULT_CORE_CONFIG["schemaVersion"]

    tank = config.setdefault("tank", {})
    if not isinstance(tank, dict):
        config["tank"] = deepcopy(DEFAULT_CORE_CONFIG["tank"])
    else:
        tank["name"] = (
            tank.get("name").strip()[:80]
            if isinstance(tank.get("name"), str) and tank.get("name").strip()
            else NAME
        )
        tank["owner"] = (
            tank.get("owner").strip()[:80]
            if isinstance(tank.get("owner"), str)
            else ""
        )
        tank["profile"] = _normalise_tank_profile(tank.get("profile"))

    raw_sensors = settings.get("sensors") if isinstance(settings.get("sensors"), dict) else {}

    for sensor_id, meta in MVP_SENSORS.items():
        sensor = config["sensors"].setdefault(sensor_id, {})
        raw_sensor = raw_sensors.get(sensor_id) if isinstance(raw_sensors.get(sensor_id), dict) else {}
        sensor["entity_id"] = _normalise_entity_id(sensor.get("entity_id"))
        sensor.setdefault("label", meta["label"])
        if "enabled" in raw_sensor:
            sensor["enabled"] = bool(raw_sensor.get("enabled"))
        else:
            sensor["enabled"] = bool(sensor["entity_id"]) or bool(meta.get("enabled", False))
        sensor.setdefault("group", meta["group"])
        sensor["kind"] = meta.get("kind", "numeric")
        sensor.setdefault("unit", meta["unit"])
        sensor.setdefault("min", meta["min"])
        sensor.setdefault("max", meta["max"])
        sensor["alertsEnabled"] = bool(sensor.get("alertsEnabled", True))
        try:
            sensor["warningBuffer"] = float(sensor.get("warningBuffer", 10))
        except (TypeError, ValueError):
            sensor["warningBuffer"] = 10
        sensor["warningBuffer"] = max(0, min(sensor["warningBuffer"], 50))

    custom_modes = config.setdefault("customModes", [])
    normalised_custom_modes: list[dict[str, str]] = []
    custom_mode_ids: set[str] = set()
    if isinstance(custom_modes, list):
        for item in custom_modes[:8]:
            raw_id = item.get("id") if isinstance(item, dict) else item
            mode_id = _normalise_mode_id(raw_id)
            if not mode_id or mode_id in custom_mode_ids:
                continue
            normalised_custom_modes.append({"id": mode_id})
            custom_mode_ids.add(mode_id)
    config["customModes"] = normalised_custom_modes
    allowed_mode_ids = BUILT_IN_MODES | custom_mode_ids

    mode = config.setdefault("mode", {})
    if not isinstance(mode, dict):
        config["mode"] = deepcopy(DEFAULT_CORE_CONFIG["mode"])
    else:
        active = mode.get("active")
        mode["active"] = active if active in allowed_mode_ids else "running"
        mode["startedAt"] = mode.get("startedAt") if isinstance(mode.get("startedAt"), str) else ""
        mode["expiresAt"] = mode.get("expiresAt") if isinstance(mode.get("expiresAt"), str) else ""
        mode["autoReturn"] = bool(mode.get("autoReturn", False))
        if mode["active"] == "running":
            mode["expiresAt"] = ""
            mode["autoReturn"] = False
        return_plan = mode.get("returnPlan")
        if not isinstance(return_plan, dict):
            mode["returnPlan"] = {}
        else:
            mode["returnPlan"] = {
                equipment_id: desired_state
                for equipment_id, desired_state in return_plan.items()
                if isinstance(equipment_id, str) and desired_state in {"on", "off"}
            }

    mode_previews = config.setdefault("modePreviews", {})
    if not isinstance(mode_previews, dict):
        config["modePreviews"] = deepcopy(DEFAULT_CORE_CONFIG["modePreviews"])
    else:
        for mode_id in list(mode_previews):
            if mode_id == "running" or mode_id not in allowed_mode_ids:
                mode_previews.pop(mode_id)
        for mode_id in sorted(allowed_mode_ids - {"running"}):
            preview = mode_previews.setdefault(mode_id, {})
            if not isinstance(preview, dict):
                mode_previews[mode_id] = {}
                continue
            for equipment_id, desired_state in list(preview.items()):
                if not isinstance(equipment_id, str) or desired_state not in {
                    "on",
                    "off",
                    "unchanged",
                }:
                    preview.pop(equipment_id)

    mode_timers = config.setdefault("modeTimers", {})
    if not isinstance(mode_timers, dict):
        config["modeTimers"] = deepcopy(DEFAULT_CORE_CONFIG["modeTimers"])
    else:
        timer_defaults = {
            **DEFAULT_CORE_CONFIG["modeTimers"],
            **{
                mode_id: {"durationMinutes": 0, "autoReturn": False}
                for mode_id in custom_mode_ids
            },
        }
        for mode_id in list(mode_timers):
            if mode_id not in timer_defaults:
                mode_timers.pop(mode_id)
        for mode_id, defaults in timer_defaults.items():
            timer = mode_timers.setdefault(mode_id, {})
            if not isinstance(timer, dict):
                timer = deepcopy(defaults)
                mode_timers[mode_id] = timer
            try:
                timer["durationMinutes"] = int(
                    timer.get("durationMinutes", defaults["durationMinutes"])
                )
            except (TypeError, ValueError):
                timer["durationMinutes"] = defaults["durationMinutes"]
            timer["durationMinutes"] = max(0, min(timer["durationMinutes"], 720))
            timer["autoReturn"] = bool(timer.get("autoReturn", defaults["autoReturn"]))

    mode_settings = config.setdefault("modeSettings", {})
    if not isinstance(mode_settings, dict):
        config["modeSettings"] = deepcopy(DEFAULT_CORE_CONFIG["modeSettings"])
    else:
        settings_defaults = {
            **DEFAULT_CORE_CONFIG["modeSettings"],
            **{
                mode_id: {
                    "label": mode_id.replace("_", " ").title(),
                    "description": "Custom manual mode. Set the equipment plan before applying.",
                }
                for mode_id in custom_mode_ids
            },
        }
        for mode_id in list(mode_settings):
            if mode_id not in settings_defaults:
                mode_settings.pop(mode_id)
        for mode_id, defaults in settings_defaults.items():
            settings = mode_settings.setdefault(mode_id, {})
            if not isinstance(settings, dict):
                settings = deepcopy(defaults)
                mode_settings[mode_id] = settings
            label = settings.get("label")
            description = settings.get("description")
            settings["label"] = (
                label.strip()[:48]
                if isinstance(label, str) and label.strip()
                else defaults["label"]
            )
            settings["description"] = (
                description.strip()[:160]
                if isinstance(description, str) and description.strip()
                else defaults["description"]
            )

    mode_schedule = config.setdefault("modeSchedule", {})
    if not isinstance(mode_schedule, dict):
        config["modeSchedule"] = deepcopy(DEFAULT_CORE_CONFIG["modeSchedule"])
    else:
        mode_schedule["enabled"] = bool(mode_schedule.get("enabled", False))
        last_runs = mode_schedule.get("lastRuns")
        if not isinstance(last_runs, dict):
            last_runs = {}
        mode_schedule["lastRuns"] = {
            str(schedule_id): str(last_run)
            for schedule_id, last_run in last_runs.items()
            if isinstance(schedule_id, str) and isinstance(last_run, str)
        }
        items = mode_schedule.get("items")
        if not isinstance(items, list):
            mode_schedule["items"] = []
        else:
            safe_items: list[dict[str, Any]] = []
            used_schedule_ids: set[str] = set()
            for index, item in enumerate(items[:12]):
                if not isinstance(item, dict):
                    continue
                mode_id = item.get("mode")
                if mode_id not in allowed_mode_ids - {"running"}:
                    continue
                schedule_id = _normalise_schedule_id(
                    item.get("id"), f"{mode_id}_{index + 1}"
                )
                if schedule_id in used_schedule_ids:
                    schedule_id = f"{schedule_id}_{index + 1}"
                used_schedule_ids.add(schedule_id)
                schedule_times = _normalise_schedule_times(
                    item.get("times"), item.get("time")
                )
                days = [
                    day
                    for day in _normalise_list(item.get("days"))
                    if day in WEEK_DAYS
                ]
                safe_items.append(
                    {
                        "id": schedule_id,
                        "enabled": bool(item.get("enabled", False)),
                        "mode": mode_id,
                        "time": schedule_times[0] if schedule_times else "",
                        "times": schedule_times,
                        "days": days,
                        "requireAutoReturn": bool(item.get("requireAutoReturn", True)),
                    }
                )
            mode_schedule["items"] = safe_items

    equipment = config.setdefault("equipment", {})
    if not isinstance(equipment, dict):
        config["equipment"] = {}
    else:
        for equipment_id, equipment_config in list(equipment.items()):
            if not isinstance(equipment_config, dict):
                equipment.pop(equipment_id)
                continue
            equipment_config["label"] = equipment_config.get("label") or equipment_id
            equipment_config["switch_entity_id"] = _normalise_entity_id(
                equipment_config.get("switch_entity_id")
            )
            equipment_config["power_entity_id"] = _normalise_entity_id(
                equipment_config.get("power_entity_id")
            )
            equipment_config["energy_entity_id"] = _normalise_entity_id(
                equipment_config.get("energy_entity_id")
            )
            equipment_config["cost_entity_id"] = _normalise_entity_id(
                equipment_config.get("cost_entity_id")
            )
            equipment_config["armed"] = bool(equipment_config.get("armed", False))
            explicit_type = _normalise_equipment_profile(
                equipment_config.get("type") or equipment_config.get("profile")
            )
            equipment_type = explicit_type or _infer_equipment_profile(
                equipment_id, equipment_config
            )
            equipment_config["type"] = equipment_type
            display_wavemaker = bool(
                equipment_type == "display_wavemaker"
                or (
                    not explicit_type
                    and (
                        equipment_config.get("displayWavemaker", False)
                        or _looks_like_display_wavemaker(equipment_id, equipment_config)
                    )
                )
            )
            equipment_config["displayWavemaker"] = display_wavemaker
            equipment_config["allowAutoRestart"] = (
                bool(equipment_config.get("allowAutoRestart", False))
                if display_wavemaker
                else bool(equipment_config.get("allowAutoRestart", True))
            )
            equipment_config["wavemakerNotifications"] = bool(
                equipment_config.get("wavemakerNotifications", display_wavemaker)
            )
            try:
                power_on_delay = int(equipment_config.get("powerOnDelaySeconds", 0))
            except (TypeError, ValueError):
                power_on_delay = 0
            equipment_config["powerOnDelaySeconds"] = max(0, min(power_on_delay, 1800))

    cameras = config.setdefault("cameras", {})
    if not isinstance(cameras, dict):
        config["cameras"] = {}
    else:
        for camera_id, camera_config in list(cameras.items()):
            if not isinstance(camera_config, dict):
                cameras.pop(camera_id)
                continue
            label = camera_config.get("label")
            camera_config["label"] = (
                label.strip()[:80]
                if isinstance(label, str) and label.strip()
                else camera_id
            )
            camera_config["entity_id"] = _normalise_entity_id(camera_config.get("entity_id"))

    def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = default
        return max(low, min(value, high))

    capture = config.setdefault("capture", {})
    if not isinstance(capture, dict):
        capture = {}
        config["capture"] = capture
    capture["enabled"] = bool(capture.get("enabled", False))
    capture["durationSeconds"] = _clamp_int(
        capture.get("durationSeconds"), CAPTURE_DEFAULT_DURATION, CAPTURE_MIN_DURATION, CAPTURE_MAX_DURATION
    )
    capture["lookbackSeconds"] = _clamp_int(
        capture.get("lookbackSeconds"), CAPTURE_DEFAULT_LOOKBACK, 0, CAPTURE_MAX_LOOKBACK
    )
    capture["retention"] = _clamp_int(
        capture.get("retention"), CAPTURE_DEFAULT_RETENTION, 1, CAPTURE_MAX_RECORDS
    )
    capture["cooldownSeconds"] = _clamp_int(
        capture.get("cooldownSeconds"), CAPTURE_DEFAULT_COOLDOWN, 0, CAPTURE_MAX_COOLDOWN
    )
    known_cameras = config.get("cameras", {})
    camera_ids = capture.get("cameraIds")
    if not isinstance(camera_ids, list):
        camera_ids = []
    capture["cameraIds"] = [
        cid for cid in camera_ids if isinstance(cid, str) and cid in known_cameras
    ]
    default_triggers = DEFAULT_CORE_CONFIG["capture"]["triggers"]
    triggers = capture.get("triggers")
    if not isinstance(triggers, dict):
        triggers = {}
    capture["triggers"] = {
        key: bool(triggers.get(key, default_triggers[key])) for key in default_triggers
    }

    captures = config.get("captures")
    if not isinstance(captures, list):
        captures = []
    config["captures"] = [record for record in captures if isinstance(record, dict)][
        :CAPTURE_MAX_RECORDS
    ]

    timelapse = config.setdefault("timelapse", {})
    if not isinstance(timelapse, dict):
        timelapse = {}
        config["timelapse"] = timelapse
    timelapse["enabled"] = bool(timelapse.get("enabled", False))
    tl_camera = timelapse.get("cameraId")
    timelapse["cameraId"] = (
        tl_camera if isinstance(tl_camera, str) and tl_camera in known_cameras else ""
    )
    timelapse["cadenceMinutes"] = _clamp_int(
        timelapse.get("cadenceMinutes"),
        TIMELAPSE_DEFAULT_CADENCE,
        TIMELAPSE_MIN_CADENCE,
        TIMELAPSE_MAX_CADENCE,
    )
    timelapse["windowStart"] = (
        _normalise_schedule_time(timelapse.get("windowStart")) or TIMELAPSE_DEFAULT_WINDOW_START
    )
    timelapse["windowEnd"] = (
        _normalise_schedule_time(timelapse.get("windowEnd")) or TIMELAPSE_DEFAULT_WINDOW_END
    )
    default_retention = DEFAULT_CORE_CONFIG["timelapse"]["retention"]
    tl_retention = timelapse.get("retention")
    if not isinstance(tl_retention, dict):
        tl_retention = {}
    timelapse["retention"] = {
        key: _clamp_int(tl_retention.get(key), default_retention[key], 0, TIMELAPSE_MAX_DAYS)
        for key in default_retention
    }

    overlay = config.setdefault("overlay", {})
    if not isinstance(overlay, dict):
        overlay = {}
        config["overlay"] = overlay
    overlay["enabled"] = bool(overlay.get("enabled", False))
    overlay_stats = overlay.get("stats")
    if not isinstance(overlay_stats, list):
        overlay_stats = []
    overlay["stats"] = [s for s in overlay_stats if isinstance(s, str) and s in MVP_SENSORS]
    overlay["showReefHealth"] = bool(overlay.get("showReefHealth", True))
    overlay["showTankName"] = bool(overlay.get("showTankName", True))
    overlay["showAvatar"] = bool(overlay.get("showAvatar", True))
    overlay["showQuip"] = bool(overlay.get("showQuip", True))
    overlay["position"] = (
        overlay.get("position")
        if overlay.get("position") in ("top-left", "top-right", "bottom-left", "bottom-right")
        else "bottom-left"
    )

    mode_previews = config.get("modePreviews", {})
    if isinstance(mode_previews, dict):
        for preview in mode_previews.values():
            if isinstance(preview, dict):
                for equipment_id in list(preview):
                    if equipment_id not in config["equipment"]:
                        preview.pop(equipment_id)
    mode = config.get("mode", {})
    if isinstance(mode, dict) and isinstance(mode.get("returnPlan"), dict):
        for equipment_id in list(mode["returnPlan"]):
            if equipment_id not in config["equipment"]:
                mode["returnPlan"].pop(equipment_id)

    alerts = config.setdefault("alerts", {})
    if not isinstance(alerts, dict):
        config["alerts"] = deepcopy(DEFAULT_CORE_CONFIG["alerts"])
    else:
        alerts["persistentNotifications"] = bool(alerts.get("persistentNotifications", False))
        alerts["notifyCriticalOnly"] = bool(alerts.get("notifyCriticalOnly", True))
        try:
            hysteresis_percent = float(alerts.get("hysteresisPercent", 2))
        except (TypeError, ValueError):
            hysteresis_percent = 2
        alerts["hysteresisPercent"] = max(0, min(hysteresis_percent, 20))
        alerts["wavemakerReminders"] = bool(alerts.get("wavemakerReminders", True))
        try:
            reminder_minutes = int(alerts.get("wavemakerReminderMinutes", 10))
        except (TypeError, ValueError):
            reminder_minutes = 10
        alerts["wavemakerReminderMinutes"] = max(1, min(reminder_minutes, 240))
        mute_until = alerts.get("muteUntil")
        alerts["muteUntil"] = (
            {
                sensor_id: muted_until
                for sensor_id, muted_until in mute_until.items()
                if sensor_id in MVP_SENSORS and isinstance(muted_until, str)
            }
            if isinstance(mute_until, dict)
            else {}
        )
        last_states = alerts.get("lastStates")
        alerts["lastStates"] = (
            {
                sensor_id: state
                for sensor_id, state in last_states.items()
                if sensor_id in MVP_SENSORS
                and state in {"resolved", "warning", "critical", "muted"}
            }
            if isinstance(last_states, dict)
            else {}
        )
        history = alerts.get("history")
        alerts["history"] = (
            [
                item
                for item in history[:50]
                if isinstance(item, dict)
                and isinstance(item.get("timestamp"), str)
                and isinstance(item.get("sensor_id"), str)
                and isinstance(item.get("state"), str)
                and isinstance(item.get("title"), str)
            ]
            if isinstance(history, list)
            else []
        )

    interlocks = config.setdefault("interlocks", {})
    if not isinstance(interlocks, dict):
        config["interlocks"] = deepcopy(DEFAULT_CORE_CONFIG["interlocks"])
    else:
        interlocks["heaterRequiresTankTemp"] = bool(
            interlocks.get("heaterRequiresTankTemp", True)
        )
        interlocks["atoMaxRuntimeEnabled"] = bool(
            interlocks.get("atoMaxRuntimeEnabled", False)
        )
        raw_runtime_seconds = interlocks.get("atoMaxRuntimeSeconds")
        if raw_runtime_seconds is None and "atoMaxRuntimeMinutes" in interlocks:
            try:
                raw_runtime_seconds = int(interlocks.get("atoMaxRuntimeMinutes", 5)) * 60
            except (TypeError, ValueError):
                raw_runtime_seconds = 300
        try:
            interlocks["atoMaxRuntimeSeconds"] = int(raw_runtime_seconds)
        except (TypeError, ValueError):
            interlocks["atoMaxRuntimeSeconds"] = 300
        interlocks["atoMaxRuntimeSeconds"] = max(
            5, min(interlocks["atoMaxRuntimeSeconds"], 1800)
        )
        interlocks.pop("atoMaxRuntimeMinutes", None)
        interlocks["atoDutyCycleEnabled"] = bool(
            interlocks.get("atoDutyCycleEnabled", False)
        )
        try:
            interlocks["atoDutyCycleOnSeconds"] = int(
                interlocks.get("atoDutyCycleOnSeconds", 120)
            )
        except (TypeError, ValueError):
            interlocks["atoDutyCycleOnSeconds"] = 120
        interlocks["atoDutyCycleOnSeconds"] = max(
            5, min(interlocks["atoDutyCycleOnSeconds"], 1800)
        )
        try:
            interlocks["atoDutyCycleIntervalMinutes"] = int(
                interlocks.get("atoDutyCycleIntervalMinutes", 60)
            )
        except (TypeError, ValueError):
            interlocks["atoDutyCycleIntervalMinutes"] = 60
        interlocks["atoDutyCycleIntervalMinutes"] = max(
            5, min(interlocks["atoDutyCycleIntervalMinutes"], 1440)
        )
        interlocks["atoDutyCycleOnSeconds"] = min(
            interlocks["atoDutyCycleOnSeconds"],
            interlocks["atoDutyCycleIntervalMinutes"] * 60,
        )
        interlocks["atoDutyCycleAnchorTime"] = (
            _normalise_schedule_time(interlocks.get("atoDutyCycleAnchorTime"))
            or "00:00"
        )
        interlocks["returnPumpSkimmerWarning"] = bool(
            interlocks.get("returnPumpSkimmerWarning", True)
        )
        interlocks["skimmerAutoOffWhenReturnPumpOff"] = bool(
            interlocks.get("skimmerAutoOffWhenReturnPumpOff", False)
        )
        interlocks["atoReturnPumpWarning"] = bool(
            interlocks.get("atoReturnPumpWarning", True)
        )
        interlocks["atoBlockWhenReturnPumpOff"] = bool(
            interlocks.get("atoBlockWhenReturnPumpOff", False)
        )

    activity = config.setdefault("activity", [])
    if not isinstance(activity, list):
        config["activity"] = []
    else:
        config["activity"] = [
            item
            for item in activity[:50]
            if isinstance(item, dict)
            and isinstance(item.get("timestamp"), str)
            and isinstance(item.get("message"), str)
        ]

    manual_readings = config.setdefault("manualReadings", {})
    if not isinstance(manual_readings, dict):
        config["manualReadings"] = {}
    else:
        normalised_readings: dict[str, list[dict[str, Any]]] = {}
        for parameter in MANUAL_TEST_PARAMETERS:
            entries = manual_readings.get(parameter)
            if not isinstance(entries, list):
                continue
            safe_entries: list[dict[str, Any]] = []
            for index, item in enumerate(entries[:250]):
                if not isinstance(item, dict):
                    continue
                try:
                    value = float(item.get("value"))
                except (TypeError, ValueError):
                    continue
                timestamp = item.get("timestamp") or item.get("date")
                if not isinstance(timestamp, str) or not timestamp:
                    continue
                sensor = config.get("sensors", {}).get(parameter, {})
                unit = item.get("unit") or sensor.get("unit") or MVP_SENSORS.get(parameter, {}).get("unit", "")
                source = item.get("source") or item.get("kit") or ""
                notes = item.get("notes") or ""
                entry_id = item.get("id") or f"{timestamp}:{index}"
                safe_entries.append(
                    {
                        "id": str(entry_id)[:120],
                        "timestamp": timestamp,
                        "value": value,
                        "unit": str(unit)[:20],
                        "source": str(source)[:80],
                        "notes": str(notes)[:500],
                    }
                )
            normalised_readings[parameter] = safe_entries
        config["manualReadings"] = normalised_readings

    manual_tests = config.setdefault("manualTests", {})
    if not isinstance(manual_tests, dict):
        config["manualTests"] = deepcopy(DEFAULT_CORE_CONFIG["manualTests"])
        manual_tests = config["manualTests"]
    manual_tests["enabled"] = bool(manual_tests.get("enabled", True))
    raw_schedules = manual_tests.get("schedules")
    raw_schedules = raw_schedules if isinstance(raw_schedules, dict) else {}
    profile = config.get("tank", {}).get("profile", DEFAULT_TANK_PROFILE)
    profile_defaults = MANUAL_TEST_CADENCE_PRESETS.get(
        profile, MANUAL_TEST_CADENCE_PRESETS[DEFAULT_TANK_PROFILE]
    )
    schedules: dict[str, dict[str, Any]] = {}
    for parameter in MANUAL_TEST_PARAMETERS:
        raw = raw_schedules.get(parameter)
        raw = raw if isinstance(raw, dict) else {}
        try:
            cadence_days = int(raw.get("cadenceDays", profile_defaults.get(parameter, 14)))
        except (TypeError, ValueError):
            cadence_days = profile_defaults.get(parameter, 14)
        cadence_days = max(1, min(cadence_days, 365))
        try:
            critical_after_days = int(raw.get("criticalAfterDays", cadence_days * 2))
        except (TypeError, ValueError):
            critical_after_days = cadence_days * 2
        schedules[parameter] = {
            "enabled": bool(raw.get("enabled", False)),
            "cadenceDays": cadence_days,
            "criticalAfterDays": max(cadence_days, min(critical_after_days, 730)),
            "preferredSource": str(raw.get("preferredSource", ""))[:80],
        }
    manual_tests["schedules"] = schedules

    dosing = config.setdefault("dosing", {})
    if not isinstance(dosing, dict):
        config["dosing"] = deepcopy(DEFAULT_CORE_CONFIG["dosing"])
    else:
        dosing["enabled"] = bool(dosing.get("enabled", True))
        raw_parameters = dosing.get("parameters")
        raw_parameters = raw_parameters if isinstance(raw_parameters, dict) else {}
        raw_system = dosing.get("system")
        raw_system = raw_system if isinstance(raw_system, dict) else {}
        default_system = deepcopy(DEFAULT_CORE_CONFIG["dosing"]["system"])
        system: dict[str, Any] = {}
        inferred_primary = _infer_dosing_primary_from_parameters(raw_parameters)
        inferred_secondary = (
            "kalkwasser_calcium_hydroxide"
            if any(
                isinstance(raw, dict)
                and _normalise_dosing_product_id(raw.get("productPreset"))
                == "kalkwasser_calcium_hydroxide"
                for raw in raw_parameters.values()
            )
            else ""
        )
        for field in ("primaryProduct", "secondaryProduct", "customProductClass"):
            fallback = default_system[field]
            if field == "primaryProduct":
                fallback = inferred_primary
            if field == "secondaryProduct":
                fallback = inferred_secondary
            system[field] = _normalise_dosing_product_id(raw_system.get(field)) or fallback
        system["secondaryDelivery"] = _normalise_dosing_delivery(
            raw_system.get("secondaryDelivery")
        )
        for field in ("freshTestRequired", "safetyAcknowledged"):
            system[field] = bool(raw_system.get(field, default_system[field]))
        for field in ("customProductName", "customNotes"):
            value = raw_system.get(field, default_system[field])
            system[field] = str(value)[:240] if value is not None else ""
        try:
            tank_volume = float(raw_system.get("tankVolumeLitres", 0))
        except (TypeError, ValueError):
            tank_volume = 0.0
        if tank_volume <= 0:
            tank_volume = max(
                (
                    float(raw.get("tankVolumeLitres", 0) or 0)
                    for raw in raw_parameters.values()
                    if isinstance(raw, dict)
                ),
                default=0.0,
            )
        system["tankVolumeLitres"] = max(0.0, tank_volume)
        for field in (
            "kalkDailyDoseMl",
            "kalkConcentrationTspPerGallon",
            "kalkEvaporationLimitMlPerDay",
            "kalkMaxPh",
            "kalkMaxPhRise",
        ):
            try:
                value = float(raw_system.get(field, default_system[field]))
            except (TypeError, ValueError):
                value = float(default_system[field])
            system[field] = max(0.0, value)
        dosing["system"] = system
        parameters: dict[str, dict[str, Any]] = {}
        known_parameters = set(DOSING_PARAMETERS)
        for optional_parameter in ("nitrate", "phosphate"):
            if optional_parameter in raw_parameters:
                known_parameters.add(optional_parameter)
        for parameter in sorted(known_parameters):
            raw = raw_parameters.get(parameter)
            raw = raw if isinstance(raw, dict) else {}
            entry: dict[str, Any] = {
                "productPreset": str(raw.get("productPreset", "custom"))[:120],
            }
            for field in (
                "doserMlPerDay",
                "potencyPerMl",
                "target",
                "tankVolumeLitres",
                "productDoseMl",
                "productVolumeLitres",
                "productRaise",
            ):
                try:
                    value = float(raw.get(field, 0))
                except (TypeError, ValueError):
                    value = 0.0
                entry[field] = max(0.0, value)
            parameters[parameter] = entry
        dosing["parameters"] = parameters

    return config


def _config_from_entry(entry: OpenReefConfigEntry | None) -> dict[str, Any]:
    if entry is None:
        return deepcopy(DEFAULT_CORE_CONFIG)
    return _normalise_core_config(entry.options.get(CONF_SETTINGS))


def _collect_entity_ids(config: dict[str, Any]) -> set[str]:
    entity_ids: set[str] = set()

    for sensor in config.get("sensors", {}).values():
        if isinstance(sensor, dict):
            if not sensor.get("enabled", False):
                continue
            entity_id = _normalise_entity_id(sensor.get("entity_id"))
            if entity_id:
                entity_ids.add(entity_id)

    for equipment in config.get("equipment", {}).values():
        if not isinstance(equipment, dict):
            continue
        for key in (
            "switch_entity_id",
            "power_entity_id",
            "energy_entity_id",
            "cost_entity_id",
        ):
            entity_id = _normalise_entity_id(equipment.get(key))
            if entity_id:
                entity_ids.add(entity_id)

    energy = config.get("energy", {})
    if isinstance(energy, dict):
        for key in (
            "daily_energy_entity_id",
            "weekly_energy_entity_id",
            "monthly_energy_entity_id",
            "daily_cost_entity_id",
            "weekly_cost_entity_id",
            "monthly_cost_entity_id",
        ):
            entity_id = _normalise_entity_id(energy.get(key))
            if entity_id:
                entity_ids.add(entity_id)

    return entity_ids


def _validate_config(hass: HomeAssistant, config: dict[str, Any]) -> dict[str, Any]:
    entity_ids = sorted(_collect_entity_ids(config))
    missing = [entity_id for entity_id in entity_ids if hass.states.get(entity_id) is None]
    locked_controls: list[str] = []
    armed_unavailable: list[str] = []

    equipment = config.get("equipment", {})
    if isinstance(equipment, dict):
        for equipment_config in equipment.values():
            if not isinstance(equipment_config, dict):
                continue
            switch_entity = _normalise_entity_id(equipment_config.get("switch_entity_id"))
            if not switch_entity:
                continue
            if not equipment_config.get("armed", False):
                locked_controls.append(switch_entity)
                continue
            state = hass.states.get(switch_entity)
            if state is None or state.state in UNAVAILABLE_STATES:
                armed_unavailable.append(switch_entity)

    return {
        "entity_count": len(entity_ids),
        "missing_entities": missing,
        "locked_controls": sorted(locked_controls),
        "armed_unavailable": sorted(armed_unavailable),
        "setup_complete": bool(config.get("display", {}).get("setupComplete")),
    }


def _runtime_state_for_entity(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    state = hass.states.get(entity_id)
    if state is None:
        return {
            "entity_id": entity_id,
            "state": None,
            "unit": None,
            "last_changed": None,
            "available": False,
        }

    return {
        "entity_id": entity_id,
        "state": state.state,
        "unit": state.attributes.get("unit_of_measurement"),
        "last_changed": state.last_changed.isoformat(),
        "available": state.state not in UNAVAILABLE_STATES,
    }


def _area_name_for_entry(
    area_registry: ar.AreaRegistry, registry_entry: er.RegistryEntry | None
) -> str | None:
    area_id = getattr(registry_entry, "area_id", None)
    if not area_id:
        return None
    area = area_registry.async_get_area(area_id)
    return area.name if area else None


def _entity_search_candidate(
    hass: HomeAssistant,
    area_registry: ar.AreaRegistry,
    entity_id: str,
    registry_entry: er.RegistryEntry | None,
    target: dict[str, Any],
) -> dict[str, Any] | None:
    domains = _normalise_list(target.get("domains"))
    domain = _domain(entity_id)
    if domains and domain not in domains:
        return None

    state = hass.states.get(entity_id)
    attributes = state.attributes if state is not None else {}
    name = (
        getattr(registry_entry, "name", None)
        or getattr(registry_entry, "original_name", None)
        or attributes.get("friendly_name")
        or entity_id
    )
    device_class = getattr(registry_entry, "device_class", None) or attributes.get(
        "device_class"
    )
    unit = attributes.get("unit_of_measurement")
    state_class = attributes.get("state_class")

    haystack = _normalise_text(
        " ".join(
            str(value)
            for value in [entity_id, name, device_class, unit, state_class]
            if value
        )
    )

    keywords = _normalise_list(target.get("keywords"))
    prefer = _normalise_list(target.get("prefer"))
    avoid = _normalise_list(target.get("avoid"))
    device_classes = _normalise_list(target.get("device_classes"))
    units = _normalise_list(target.get("units"))
    state_classes = _normalise_list(target.get("state_classes"))

    score = 30
    score += _score_terms(haystack, keywords, 18)
    score += _score_terms(haystack, prefer, 10)
    score -= _score_terms(haystack, avoid, 16)

    if isinstance(device_class, str) and device_class in device_classes:
        score += 35
    if isinstance(unit, str) and unit.lower() in {candidate.lower() for candidate in units}:
        score += 24
    if isinstance(state_class, str) and state_class in state_classes:
        score += 16
    if _has_phrase(haystack, "reef") or _has_phrase(haystack, "tank") or _has_phrase(
        haystack, "aquarium"
    ):
        score += 5
    if entity_id == target.get("id"):
        score += 20

    if score <= 35:
        return None

    return {
        "entity_id": entity_id,
        "name": str(name),
        "domain": domain,
        "device_class": device_class if isinstance(device_class, str) else None,
        "unit": unit if isinstance(unit, str) else None,
        "area": _area_name_for_entry(area_registry, registry_entry),
        "score": score,
    }


def _search_entities(
    hass: HomeAssistant, target: dict[str, Any], limit: int
) -> list[dict[str, Any]]:
    entity_registry = er.async_get(hass)
    area_registry = ar.async_get(hass)
    candidates: dict[str, dict[str, Any]] = {}

    for registry_entry in entity_registry.entities.values():
        candidate = _entity_search_candidate(
            hass, area_registry, registry_entry.entity_id, registry_entry, target
        )
        if candidate is not None:
            candidates[registry_entry.entity_id] = candidate

    return sorted(
        candidates.values(),
        key=lambda candidate: (-candidate["score"], candidate["entity_id"]),
    )[:limit]


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _alert_mute_until(
    config: dict[str, Any], sensor_id: str, now: datetime | None = None
) -> datetime | None:
    alerts = config.get("alerts", {})
    mute_until = alerts.get("muteUntil", {}) if isinstance(alerts, dict) else {}
    muted_until = _parse_datetime(mute_until.get(sensor_id)) if isinstance(mute_until, dict) else None
    if muted_until is None:
        return None
    if muted_until <= (now or datetime.now(timezone.utc)):
        if isinstance(mute_until, dict):
            mute_until.pop(sensor_id, None)
        return None
    return muted_until


def _append_alert_history(
    alert_config: dict[str, Any],
    sensor_id: str,
    label: str,
    state: str,
    title: str,
    message: str,
) -> None:
    history = alert_config.setdefault("history", [])
    if not isinstance(history, list):
        history = []
        alert_config["history"] = history
    history.insert(
        0,
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sensor_id": sensor_id,
            "label": label,
            "state": state,
            "title": title,
            "message": message,
        },
    )
    alert_config["history"] = history[:50]


def _sensor_kind(sensor_id: str, sensor: dict[str, Any]) -> str:
    kind = sensor.get("kind") or MVP_SENSORS.get(sensor_id, {}).get("kind") or "numeric"
    return str(kind)


def _sensor_binary_state(state: str) -> str:
    value = state.strip().lower()
    if value in {
        "on",
        "wet",
        "detected",
        "leaking",
        "leak",
        "flood",
        "problem",
        "unsafe",
        "active",
        "high",
        "low",
        "1",
        "true",
    }:
        return "critical"
    if value in {
        "off",
        "dry",
        "clear",
        "safe",
        "ok",
        "normal",
        "inactive",
        "closed",
        "0",
        "false",
    }:
        return "ok"
    return "warning"


def _sensor_alert_items(hass: HomeAssistant, config: dict[str, Any]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    sensors = config.get("sensors", {})
    if not isinstance(sensors, dict):
        return alerts
    alert_config = config.get("alerts", {})
    last_states = (
        alert_config.get("lastStates", {})
        if isinstance(alert_config, dict)
        and isinstance(alert_config.get("lastStates"), dict)
        else {}
    )
    try:
        hysteresis_percent = float(
            alert_config.get("hysteresisPercent", 2)
            if isinstance(alert_config, dict)
            else 2
        )
    except (TypeError, ValueError):
        hysteresis_percent = 2
    hysteresis_percent = max(0, min(hysteresis_percent, 20))
    now = datetime.now(timezone.utc)

    for sensor_id, sensor in sensors.items():
        if not isinstance(sensor, dict):
            continue
        if not sensor.get("enabled", False) or not sensor.get("alertsEnabled", True):
            continue
        if _alert_mute_until(config, sensor_id, now) is not None:
            continue
        entity_id = _normalise_entity_id(sensor.get("entity_id"))
        label = str(sensor.get("label") or sensor_id)
        if not entity_id:
            alerts.append(
                {
                    "id": sensor_id,
                    "severity": "warning",
                    "title": f"{label} is not mapped",
                    "message": "Map this sensor or disable alerts for it in OpenReef.",
                }
            )
            continue

        state = hass.states.get(entity_id)
        if state is None or state.state in UNAVAILABLE_STATES:
            alerts.append(
                {
                    "id": sensor_id,
                    "severity": "warning",
                    "title": f"{label} is not reporting",
                    "message": f"{entity_id} is unavailable.",
                }
            )
            continue

        if _sensor_kind(sensor_id, sensor) == "binary":
            binary_status = _sensor_binary_state(str(state.state))
            if binary_status == "critical":
                alerts.append(
                    {
                        "id": sensor_id,
                        "severity": "critical",
                        "title": f"{label} active",
                        "message": f"{entity_id} reports {state.state}.",
                    }
                )
            elif binary_status == "warning":
                alerts.append(
                    {
                        "id": sensor_id,
                        "severity": "warning",
                        "title": f"{label} state needs review",
                        "message": f"{entity_id} reports {state.state}.",
                    }
                )
            continue

        try:
            value = float(state.state)
            minimum = float(sensor.get("min"))
            maximum = float(sensor.get("max"))
            warning_buffer = float(sensor.get("warningBuffer", 10))
        except (TypeError, ValueError):
            continue

        unit = str(sensor.get("unit") or "").strip()
        if value < minimum or value > maximum:
            alerts.append(
                {
                    "id": sensor_id,
                    "severity": "critical",
                    "title": f"{label} outside range",
                    "message": f"{value:g} {unit}".strip()
                    + f" is outside {minimum:g} - {maximum:g} {unit}".rstrip(),
                }
            )
            continue

        buffer = (maximum - minimum) * max(0, min(warning_buffer, 50)) / 100
        hysteresis = (maximum - minimum) * hysteresis_percent / 100
        lower_warning = minimum + buffer
        upper_warning = maximum - buffer
        previous_state = last_states.get(sensor_id)
        sticky_warning = previous_state in {"warning", "critical"} and (
            value < lower_warning + hysteresis or value > upper_warning - hysteresis
        )
        if value < lower_warning or value > upper_warning or sticky_warning:
            alerts.append(
                {
                    "id": sensor_id,
                    "severity": "warning",
                    "title": f"{label} near threshold",
                    "message": f"{value:g} {unit}".strip()
                    + f" is near {minimum:g} - {maximum:g} {unit}".rstrip(),
                }
            )

    return alerts


def _equipment_label(equipment_id: str, mapped: dict[str, Any]) -> str:
    return str(mapped.get("label") or equipment_id)


def _looks_like_display_wavemaker(equipment_id: str, mapped: dict[str, Any]) -> bool:
    text = f"{equipment_id} {mapped.get('label') or ''}".lower()
    return any(term in text for term in ("wave", "wavemaker", "powerhead", "gyre"))


def _is_protected_display_wavemaker(mapped: dict[str, Any]) -> bool:
    return bool(mapped.get("displayWavemaker", False)) and not bool(
        mapped.get("allowAutoRestart", False)
    )


def _display_wavemaker_warning_items(
    hass: HomeAssistant, config: dict[str, Any]
) -> list[dict[str, str]]:
    equipment = config.get("equipment", {})
    if not isinstance(equipment, dict):
        return []

    active_mode = "running"
    mode = config.get("mode", {})
    if isinstance(mode, dict):
        active_mode = str(mode.get("active") or "running")

    items: list[dict[str, str]] = []
    for equipment_id, mapped in equipment.items():
        if not isinstance(mapped, dict):
            continue
        if active_mode != "running" or not mapped.get("displayWavemaker", False):
            continue
        if not mapped.get("armed", False):
            continue
        switch_entity = _normalise_entity_id(mapped.get("switch_entity_id"))
        if not switch_entity:
            continue
        state = hass.states.get(switch_entity)
        if state is None or state.state != "off":
            continue
        label = _equipment_label(equipment_id, mapped)
        items.append(
            {
                "id": equipment_id,
                "entity_id": switch_entity,
                "label": label,
                "title": f"{label} is still off",
                "message": (
                    "**Display wavemaker is still off. Inspect the tank before "
                    "manually restarting it. Flow is critical for corals.**"
                ),
            }
        )
    return items


def _sync_alert_state(hass: HomeAssistant, config: dict[str, Any]) -> list[dict[str, str]]:
    """Reconcile alert states, append history on transitions, and return new transitions.

    The returned list (one entry per ok->warning/critical/etc transition this call detected)
    lets callers fire event-triggered camera captures without re-deriving the alert logic.
    """
    transitions: list[dict[str, str]] = []
    alert_config = config.setdefault("alerts", {})
    if not isinstance(alert_config, dict):
        return transitions
    sensors = config.get("sensors", {})
    if not isinstance(sensors, dict):
        return transitions

    active_items = {item["id"]: item for item in _sensor_alert_items(hass, config)}
    previous_states = alert_config.get("lastStates", {})
    if not isinstance(previous_states, dict):
        previous_states = {}
    next_states: dict[str, str] = {}
    now = datetime.now(timezone.utc)

    for sensor_id, sensor in sensors.items():
        if not isinstance(sensor, dict):
            continue
        if not sensor.get("enabled", False) or not sensor.get("alertsEnabled", True):
            continue
        label = str(sensor.get("label") or sensor_id)
        item = active_items.get(sensor_id)
        muted_until = _alert_mute_until(config, sensor_id, now)
        if muted_until is not None:
            state = "muted"
            title = f"{label} alert muted"
            message = f"Muted until {muted_until.isoformat()}"
        elif item is not None:
            state = item["severity"]
            title = item["title"]
            message = item["message"]
        else:
            state = "resolved"
            title = f"{label} resolved"
            message = "Reading is back inside the configured alert behaviour."

        previous = previous_states.get(sensor_id)
        if previous != state and (previous is not None or state != "resolved"):
            _append_alert_history(alert_config, sensor_id, label, state, title, message)
            transitions.append(
                {"sensor_id": sensor_id, "label": label, "state": state, "title": title}
            )
        next_states[sensor_id] = state

    alert_config["lastStates"] = next_states
    return transitions


async def _async_sync_alert_notifications(
    hass: HomeAssistant, config: dict[str, Any]
) -> None:
    sensors = config.get("sensors", {})
    sensor_ids = list(sensors) if isinstance(sensors, dict) else list(MVP_SENSORS)
    alert_config = config.get("alerts", {})
    enabled = isinstance(alert_config, dict) and alert_config.get(
        "persistentNotifications", False
    )
    critical_only = not isinstance(alert_config, dict) or alert_config.get(
        "notifyCriticalOnly", True
    )
    alert_items = _sensor_alert_items(hass, config) if enabled else []
    active_ids = {
        item["id"]
        for item in alert_items
        if not critical_only or item["severity"] == "critical"
    }

    for sensor_id in sensor_ids:
        notification_id = f"openreef_alert_{sensor_id}"
        if sensor_id not in active_ids:
            await hass.services.async_call(
                "persistent_notification",
                "dismiss",
                {"notification_id": notification_id},
                blocking=False,
            )

    for item in alert_items:
        if critical_only and item["severity"] != "critical":
            continue
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "notification_id": f"openreef_alert_{item['id']}",
                "title": f"OpenReef: {item['title']}",
                "message": item["message"],
            },
            blocking=False,
        )

    equipment = config.get("equipment", {})
    equipment_ids = list(equipment) if isinstance(equipment, dict) else []
    wavemaker_reminders_enabled = not isinstance(alert_config, dict) or alert_config.get(
        "wavemakerReminders", True
    )
    wavemaker_items = (
        _display_wavemaker_warning_items(hass, config)
        if wavemaker_reminders_enabled
        else []
    )
    active_wavemaker_ids = {
        item["id"]
        for item in wavemaker_items
        if isinstance(equipment, dict)
        and isinstance(equipment.get(item["id"]), dict)
        and equipment[item["id"]].get("wavemakerNotifications", True)
    }

    for equipment_id in equipment_ids:
        notification_id = f"openreef_display_wavemaker_{equipment_id}"
        if equipment_id not in active_wavemaker_ids:
            await hass.services.async_call(
                "persistent_notification",
                "dismiss",
                {"notification_id": notification_id},
                blocking=False,
            )

    for item in wavemaker_items:
        if item["id"] not in active_wavemaker_ids:
            continue
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "notification_id": f"openreef_display_wavemaker_{item['id']}",
                "title": f"OpenReef: {item['title']}",
                "message": item["message"],
            },
            blocking=False,
        )


def _clear_mode_timer(hass: HomeAssistant) -> None:
    unsub = hass.data.setdefault(DOMAIN, {}).pop(MODE_TIMER_UNSUB, None)
    if unsub is not None:
        unsub()


def _clear_mode_schedule(hass: HomeAssistant) -> None:
    unsub = hass.data.setdefault(DOMAIN, {}).pop(MODE_SCHEDULE_UNSUB, None)
    if unsub is not None:
        unsub()


def _clear_ato_duty_cycle(hass: HomeAssistant) -> None:
    unsub = hass.data.setdefault(DOMAIN, {}).pop(ATO_DUTY_CYCLE_UNSUB, None)
    if unsub is not None:
        unsub()
    off_unsub = hass.data.setdefault(DOMAIN, {}).pop(ATO_DUTY_CYCLE_OFF_UNSUB, None)
    if off_unsub is not None:
        off_unsub()


def _clear_delayed_equipment_calls(hass: HomeAssistant) -> None:
    delayed = hass.data.setdefault(DOMAIN, {}).pop(DELAYED_EQUIPMENT_UNSUBS, {})
    if isinstance(delayed, dict):
        for unsub in delayed.values():
            if unsub is not None:
                unsub()


def _clear_wavemaker_reminders(hass: HomeAssistant) -> None:
    unsub = hass.data.setdefault(DOMAIN, {}).pop(WAVEMAKER_REMINDER_UNSUB, None)
    if unsub is not None:
        unsub()


def _clear_timelapse(hass: HomeAssistant) -> None:
    unsub = hass.data.setdefault(DOMAIN, {}).pop(TIMELAPSE_UNSUB, None)
    if unsub is not None:
        unsub()


def _wavemaker_reminder_interval(config: dict[str, Any]) -> int:
    alerts = config.get("alerts", {})
    if not isinstance(alerts, dict):
        return 10 * 60
    try:
        minutes = int(alerts.get("wavemakerReminderMinutes", 10))
    except (TypeError, ValueError):
        minutes = 10
    return max(1, min(minutes, 240)) * 60


async def _async_schedule_wavemaker_reminders(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry | None,
    config: dict[str, Any] | None = None,
) -> None:
    _clear_wavemaker_reminders(hass)
    if entry is None:
        return

    config = config or _config_from_entry(entry)
    alerts = config.get("alerts", {})
    if not isinstance(alerts, dict) or not alerts.get("wavemakerReminders", True):
        return

    last_store = hass.data.setdefault(DOMAIN, {}).setdefault(
        WAVEMAKER_REMINDER_LAST, {}
    )
    entry_store = last_store.setdefault(entry.entry_id, {})
    start_ts = datetime.now(timezone.utc).timestamp()
    for item in _display_wavemaker_warning_items(hass, config):
        entry_store.setdefault(item["id"], start_ts)

    async def _handle_wavemaker_reminder(now: datetime) -> None:
        latest_entry = _first_entry(hass)
        if latest_entry is None or latest_entry.entry_id != entry.entry_id:
            return

        latest_config = _config_from_entry(latest_entry)
        latest_alerts = latest_config.get("alerts", {})
        if not isinstance(latest_alerts, dict) or not latest_alerts.get(
            "wavemakerReminders", True
        ):
            return

        equipment = latest_config.get("equipment", {})
        warning_items = _display_wavemaker_warning_items(hass, latest_config)
        active_ids = {item["id"] for item in warning_items}
        last_store = hass.data.setdefault(DOMAIN, {}).setdefault(
            WAVEMAKER_REMINDER_LAST, {}
        )
        entry_store = last_store.setdefault(entry.entry_id, {})
        for equipment_id in list(entry_store):
            if equipment_id not in active_ids:
                entry_store.pop(equipment_id, None)
        if isinstance(equipment, dict):
            for equipment_id in equipment:
                if equipment_id in active_ids:
                    continue
                await hass.services.async_call(
                    "persistent_notification",
                    "dismiss",
                    {
                        "notification_id": (
                            f"openreef_display_wavemaker_{equipment_id}"
                        )
                    },
                    blocking=False,
                )

        interval_seconds = _wavemaker_reminder_interval(latest_config)
        due_items: list[dict[str, str]] = []
        now_ts = now.timestamp()
        for item in warning_items:
            mapped = equipment.get(item["id"]) if isinstance(equipment, dict) else None
            if not isinstance(mapped, dict) or not mapped.get(
                "wavemakerNotifications", True
            ):
                continue
            last_sent = float(entry_store.get(item["id"], 0) or 0)
            if now_ts - last_sent < interval_seconds:
                continue
            due_items.append(item)
            entry_store[item["id"]] = now_ts

        if not due_items:
            return

        for item in due_items:
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "notification_id": f"openreef_display_wavemaker_{item['id']}",
                    "title": f"OpenReef: {item['title']}",
                    "message": item["message"],
                },
                blocking=False,
            )

        labels = ", ".join(item["label"] for item in due_items)
        _append_activity(
            latest_config,
            f"Display wavemaker reminder: {labels} still off in Running",
            "critical",
        )
        options = dict(latest_entry.options)
        options[CONF_SETTINGS] = _normalise_core_config(latest_config)
        hass.config_entries.async_update_entry(latest_entry, options=options)

    hass.data.setdefault(DOMAIN, {})[
        WAVEMAKER_REMINDER_UNSUB
    ] = async_track_time_change(hass, _handle_wavemaker_reminder, second=15)


async def _async_schedule_mode_timer(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry | None,
    config: dict[str, Any] | None = None,
) -> None:
    _clear_mode_timer(hass)
    if entry is None:
        return

    config = config or _config_from_entry(entry)
    mode = config.get("mode", {})
    if not isinstance(mode, dict):
        return
    active = mode.get("active")
    if active == "running" or not mode.get("autoReturn", False):
        return

    expires_at = _parse_datetime(mode.get("expiresAt"))
    if expires_at is None:
        return

    scheduled_expires_at = mode.get("expiresAt")
    scheduled_mode = str(active)
    run_at = expires_at
    now = datetime.now(timezone.utc)
    if run_at <= now:
        run_at = now + timedelta(seconds=1)

    async def _handle_mode_timer(_now: datetime) -> None:
        latest_entry = _first_entry(hass)
        if latest_entry is None or latest_entry.entry_id != entry.entry_id:
            return

        latest_config = _config_from_entry(latest_entry)
        latest_mode = latest_config.get("mode", {})
        if not isinstance(latest_mode, dict):
            return
        if (
            latest_mode.get("active") != scheduled_mode
            or latest_mode.get("expiresAt") != scheduled_expires_at
            or not latest_mode.get("autoReturn", False)
        ):
            return

        try:
            await _async_apply_mode(hass, latest_entry, "running", None)
        except ServiceValidationError as err:
            latest_config = _config_from_entry(latest_entry)
            latest_mode = latest_config.setdefault("mode", {})
            if isinstance(latest_mode, dict):
                latest_mode["autoReturn"] = False
            _append_activity(
                latest_config,
                f"Auto-return to Running blocked: {err}",
                "warning",
            )
            await _async_save_config(hass, latest_entry, latest_config)

    hass.data.setdefault(DOMAIN, {})[MODE_TIMER_UNSUB] = async_track_point_in_time(
        hass, _handle_mode_timer, run_at
    )


def _mode_has_actions(config: dict[str, Any], mode_id: str) -> bool:
    try:
        equipment_config = _equipment_for_mode(config, mode_id)
    except ServiceValidationError:
        return False
    return any(state in {"on", "off"} for state in equipment_config.values())


async def _async_mark_schedule_run(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry,
    config: dict[str, Any],
    schedule_id: str,
    run_key: str,
    message: str,
    activity_type: str,
) -> None:
    schedule = config.setdefault("modeSchedule", {})
    if isinstance(schedule, dict):
        last_runs = schedule.setdefault("lastRuns", {})
        if isinstance(last_runs, dict):
            last_runs[schedule_id] = run_key
    _append_activity(config, message, activity_type)
    await _async_save_config(hass, entry, config)


async def _async_schedule_mode_schedule(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry | None,
    config: dict[str, Any] | None = None,
) -> None:
    _clear_mode_schedule(hass)
    if entry is None:
        return

    config = config or _config_from_entry(entry)
    schedule = config.get("modeSchedule", {})
    if not isinstance(schedule, dict) or not schedule.get("enabled", False):
        return
    items = schedule.get("items")
    if not isinstance(items, list) or not any(
        isinstance(item, dict)
        and item.get("enabled", False)
        and _normalise_schedule_times(item.get("times"), item.get("time"))
        for item in items
    ):
        return

    async def _handle_mode_schedule(now: datetime) -> None:
        latest_entry = _first_entry(hass)
        if latest_entry is None or latest_entry.entry_id != entry.entry_id:
            return

        latest_config = _config_from_entry(latest_entry)
        latest_schedule = latest_config.get("modeSchedule", {})
        if not isinstance(latest_schedule, dict) or not latest_schedule.get("enabled", False):
            return
        latest_items = latest_schedule.get("items")
        if not isinstance(latest_items, list):
            return

        day = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[now.weekday()]
        schedule_time = now.strftime("%H:%M")
        run_key = f"{now.date().isoformat()}:{schedule_time}"
        last_runs = latest_schedule.get("lastRuns")
        if not isinstance(last_runs, dict):
            last_runs = {}
            latest_schedule["lastRuns"] = last_runs

        for item in latest_items:
            if not isinstance(item, dict) or not item.get("enabled", False):
                continue
            item_times = _normalise_schedule_times(item.get("times"), item.get("time"))
            if schedule_time not in item_times:
                continue
            days = item.get("days")
            if isinstance(days, list) and days and day not in days:
                continue
            schedule_id = str(item.get("id") or f"{item.get('mode')}_{schedule_time}")
            if last_runs.get(schedule_id) == run_key:
                continue

            mode_id = str(item.get("mode") or "")
            mode_label = _mode_label(latest_config, mode_id)
            timer = latest_config.get("modeTimers", {}).get(mode_id, {})
            requires_auto_return = bool(item.get("requireAutoReturn", True))
            mode = latest_config.get("mode", {})
            active_mode = mode.get("active") if isinstance(mode, dict) else "running"

            if active_mode != "running":
                await _async_mark_schedule_run(
                    hass,
                    latest_entry,
                    latest_config,
                    schedule_id,
                    run_key,
                    f"Scheduled {mode_label} skipped: OpenReef is already in {_mode_label(latest_config, str(active_mode))} mode",
                    "warning",
                )
                return

            if requires_auto_return and not (
                isinstance(timer, dict) and timer.get("autoReturn", False)
            ):
                await _async_mark_schedule_run(
                    hass,
                    latest_entry,
                    latest_config,
                    schedule_id,
                    run_key,
                    f"Scheduled {mode_label} skipped: auto-return is required but disabled",
                    "warning",
                )
                return

            if not _mode_has_actions(latest_config, mode_id):
                await _async_mark_schedule_run(
                    hass,
                    latest_entry,
                    latest_config,
                    schedule_id,
                    run_key,
                    f"Scheduled {mode_label} skipped: no equipment actions are configured",
                    "warning",
                )
                return

            try:
                await _async_apply_mode(hass, latest_entry, mode_id, None)
            except ServiceValidationError as err:
                await _async_mark_schedule_run(
                    hass,
                    latest_entry,
                    _config_from_entry(latest_entry),
                    schedule_id,
                    run_key,
                    f"Scheduled {mode_label} blocked: {err}",
                    "warning",
                )
                return

            applied_config = _config_from_entry(latest_entry)
            await _async_mark_schedule_run(
                hass,
                latest_entry,
                applied_config,
                schedule_id,
                run_key,
                f"Scheduled {mode_label} ran",
                "control",
            )
            return

    hass.data.setdefault(DOMAIN, {})[MODE_SCHEDULE_UNSUB] = async_track_time_change(
        hass, _handle_mode_schedule, second=0
    )


def _ato_duty_cycle_window(
    config: dict[str, Any], now: datetime
) -> tuple[bool, str, datetime]:
    interlocks = config.get("interlocks", {})
    if not isinstance(interlocks, dict):
        return False, "", now

    anchor_time = _normalise_schedule_time(
        interlocks.get("atoDutyCycleAnchorTime")
    ) or "00:00"
    anchor_hour, anchor_minute = (int(part) for part in anchor_time.split(":"))
    interval_seconds = max(
        5 * 60,
        min(int(interlocks.get("atoDutyCycleIntervalMinutes", 60) or 60), 1440)
        * 60,
    )
    on_seconds = max(
        5,
        min(int(interlocks.get("atoDutyCycleOnSeconds", 120) or 120), 1800),
    )
    on_seconds = min(on_seconds, interval_seconds)

    seconds_since_midnight = now.hour * 3600 + now.minute * 60 + now.second
    anchor_seconds = anchor_hour * 3600 + anchor_minute * 60
    offset = (seconds_since_midnight - anchor_seconds) % (24 * 3600)
    window_start_offset = offset - (offset % interval_seconds)
    window_start_seconds = (anchor_seconds + window_start_offset) % (24 * 3600)
    window_start = now.replace(
        hour=window_start_seconds // 3600,
        minute=(window_start_seconds % 3600) // 60,
        second=0,
        microsecond=0,
    )
    if window_start > now:
        window_start -= timedelta(days=1)

    active = offset % interval_seconds < on_seconds
    window_key = f"{window_start.date().isoformat()}:{window_start.strftime('%H:%M')}"
    return active, window_key, window_start + timedelta(seconds=on_seconds)


def _armed_ato_equipment(config: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return _armed_equipment_by_profile(config, "ato")


def _equipment_profile_for_config(equipment_id: str, mapped: dict[str, Any]) -> str:
    return _normalise_equipment_profile(
        mapped.get("type") or mapped.get("profile")
    ) or _infer_equipment_profile(equipment_id, mapped)


def _armed_equipment_by_profile(
    config: dict[str, Any], profile: str
) -> list[tuple[str, dict[str, Any]]]:
    equipment = config.get("equipment", {})
    if not isinstance(equipment, dict):
        return []
    return [
        (equipment_id, mapped)
        for equipment_id, mapped in equipment.items()
        if isinstance(mapped, dict)
        and mapped.get("armed", False)
        and _equipment_profile_for_config(equipment_id, mapped) == profile
        and _normalise_entity_id(mapped.get("switch_entity_id"))
    ]


def _return_pump_dependency_issues(
    hass: HomeAssistant, config: dict[str, Any]
) -> list[str]:
    issues: list[str] = []
    for equipment_id, mapped in _armed_equipment_by_profile(config, "return_pump"):
        switch_entity = _normalise_entity_id(mapped.get("switch_entity_id"))
        state = hass.states.get(switch_entity)
        if state is None or state.state in UNAVAILABLE_STATES or state.state == "off":
            issues.append(_equipment_label(equipment_id, mapped))
    return issues


def _ato_return_pump_block_reason(hass: HomeAssistant, config: dict[str, Any]) -> str:
    interlocks = config.get("interlocks", {})
    if not isinstance(interlocks, dict) or not interlocks.get(
        "atoBlockWhenReturnPumpOff", False
    ):
        return ""
    issues = _return_pump_dependency_issues(hass, config)
    if not issues:
        return ""
    return "ATO is held because return flow is not confirmed: " + ", ".join(issues)


def _equipment_safety_block_reason(
    hass: HomeAssistant,
    config: dict[str, Any],
    equipment_id: str,
    mapped: dict[str, Any],
    desired_state: str,
) -> str:
    if (
        desired_state == "on"
        and _equipment_profile_for_config(equipment_id, mapped) == "ato"
    ):
        return _ato_return_pump_block_reason(hass, config)
    return ""


async def _async_auto_off_skimmers_for_return_pump(
    hass: HomeAssistant,
    config: dict[str, Any],
    context: Any,
) -> list[dict[str, str]]:
    interlocks = config.get("interlocks", {})
    if not isinstance(interlocks, dict) or not interlocks.get(
        "skimmerAutoOffWhenReturnPumpOff", False
    ):
        return []

    changed: list[dict[str, str]] = []
    for equipment_id, mapped in _armed_equipment_by_profile(config, "skimmer"):
        switch_entity = _normalise_entity_id(mapped.get("switch_entity_id"))
        state = hass.states.get(switch_entity)
        if state is None or state.state in UNAVAILABLE_STATES or state.state != "on":
            continue
        await hass.services.async_call(
            "switch",
            "turn_off",
            {ATTR_ENTITY_ID: switch_entity},
            blocking=True,
            context=context,
        )
        changed.append(
            {
                "equipment_id": equipment_id,
                "entity_id": switch_entity,
                "label": _equipment_label(equipment_id, mapped),
                "state": "off",
                "reason": "Return pump safety auto-off",
            }
        )

    if changed:
        labels = ", ".join(item["label"] for item in changed)
        _append_activity(
            config,
            f"Return pump safety turned off skimmer(s): {labels}",
            "control",
        )
    return changed


async def _async_set_ato_duty_cycle_state(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry,
    target_state: str,
    window_key: str,
    reason: str,
) -> None:
    latest_config = _config_from_entry(entry)
    mode = latest_config.get("mode", {})
    if not isinstance(mode, dict) or mode.get("active") != "running":
        return

    if target_state == "on":
        block_reason = _ato_return_pump_block_reason(hass, latest_config)
        if block_reason:
            interlocks = latest_config.setdefault("interlocks", {})
            last_block = (
                interlocks.get("atoDutyCycleLastReturnPumpBlock")
                if isinstance(interlocks, dict)
                else None
            )
            if last_block != window_key:
                if isinstance(interlocks, dict):
                    interlocks["atoDutyCycleLastReturnPumpBlock"] = window_key
                _append_activity(
                    latest_config,
                    f"ATO safety window held: {block_reason}",
                    "warning",
                )
                await _async_save_config(hass, entry, latest_config)
            return

    changed: list[str] = []
    unavailable: list[str] = []
    for equipment_id, mapped in _armed_ato_equipment(latest_config):
        switch_entity = _normalise_entity_id(mapped.get("switch_entity_id"))
        state = hass.states.get(switch_entity)
        if state is None or state.state in UNAVAILABLE_STATES:
            unavailable.append(_equipment_label(equipment_id, mapped))
            continue
        if state.state == target_state:
            continue
        await hass.services.async_call(
            "switch",
            f"turn_{target_state}",
            {ATTR_ENTITY_ID: switch_entity},
            blocking=True,
        )
        changed.append(_equipment_label(equipment_id, mapped))

    if not changed and not unavailable:
        return

    if changed:
        _append_activity(
            latest_config,
            f"ATO safety window {reason}: {', '.join(changed)} turned {target_state}",
            "control",
        )
    if unavailable:
        _append_activity(
            latest_config,
            f"ATO safety window skipped unavailable ATO: {', '.join(unavailable)}",
            "warning",
        )

    interlocks = latest_config.setdefault("interlocks", {})
    if isinstance(interlocks, dict):
        interlocks["atoDutyCycleLastWindow"] = window_key
    await _async_save_config(hass, entry, latest_config)
    if changed:
        _dispatch_capture(hass, entry, "ato_window", f"ATO safety window {reason}")


async def _async_schedule_ato_duty_cycle(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry | None,
    config: dict[str, Any] | None = None,
) -> None:
    _clear_ato_duty_cycle(hass)
    if entry is None:
        return

    config = config or _config_from_entry(entry)
    interlocks = config.get("interlocks", {})
    if (
        not isinstance(interlocks, dict)
        or not interlocks.get("atoDutyCycleEnabled", False)
    ):
        return

    async def _handle_ato_duty_cycle(now: datetime) -> None:
        latest_entry = _first_entry(hass)
        if latest_entry is None or latest_entry.entry_id != entry.entry_id:
            return

        latest_config = _config_from_entry(latest_entry)
        latest_interlocks = latest_config.get("interlocks", {})
        if (
            not isinstance(latest_interlocks, dict)
            or not latest_interlocks.get("atoDutyCycleEnabled", False)
        ):
            return

        if not _armed_ato_equipment(latest_config):
            return

        active, window_key, off_at = _ato_duty_cycle_window(latest_config, now)
        if active:
            last_store = hass.data.setdefault(DOMAIN, {}).setdefault(
                ATO_DUTY_CYCLE_LAST, {}
            )
            entry_store = last_store.setdefault(entry.entry_id, {})
            if entry_store.get("active_window") != window_key:
                entry_store["active_window"] = window_key
                await _async_set_ato_duty_cycle_state(
                    hass, latest_entry, "on", window_key, "started"
                )

            async def _turn_off_at_end(_now: datetime) -> None:
                newest_entry = _first_entry(hass)
                if newest_entry is None or newest_entry.entry_id != entry.entry_id:
                    return
                await _async_set_ato_duty_cycle_state(
                    hass, newest_entry, "off", window_key, "ended"
                )

            run_at = off_at if off_at > now else now + timedelta(seconds=1)
            off_unsub = hass.data.setdefault(DOMAIN, {}).pop(
                ATO_DUTY_CYCLE_OFF_UNSUB, None
            )
            if off_unsub is not None:
                off_unsub()
            hass.data.setdefault(DOMAIN, {})[ATO_DUTY_CYCLE_OFF_UNSUB] = (
                async_track_point_in_time(hass, _turn_off_at_end, run_at)
            )
            return

        await _async_set_ato_duty_cycle_state(
            hass, latest_entry, "off", window_key, "outside schedule"
        )

    hass.data.setdefault(DOMAIN, {})[ATO_DUTY_CYCLE_UNSUB] = async_track_time_change(
        hass, _handle_ato_duty_cycle, second=0
    )
    await _handle_ato_duty_cycle(dt_util.now())


async def _async_schedule_timelapse(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry | None,
    config: dict[str, Any] | None = None,
) -> None:
    """Arm the per-minute timelapse tick (mirrors the ATO duty-cycle scheduler).

    Fires every minute; captures a frame only inside the daylight window and once the
    cadence has elapsed since the last frame. Does NOT capture immediately on (re)arm —
    so saving settings or restarting won't spam frames.
    """
    _clear_timelapse(hass)
    if entry is None:
        return

    config = config or _config_from_entry(entry)
    timelapse_cfg = config.get("timelapse", {})
    if not isinstance(timelapse_cfg, dict) or not timelapse_cfg.get("enabled", False):
        return

    async def _handle_timelapse(now: datetime) -> None:
        latest_entry = _first_entry(hass)
        if latest_entry is None or latest_entry.entry_id != entry.entry_id:
            return
        latest_cfg = _config_from_entry(latest_entry).get("timelapse", {})
        if not isinstance(latest_cfg, dict) or not latest_cfg.get("enabled", False):
            return

        # Inside the daylight window only (local time) — skip dark lights-off frames.
        start = _hhmm_to_minutes(latest_cfg.get("windowStart"))
        end = _hhmm_to_minutes(latest_cfg.get("windowEnd"))
        if start is None or end is None:
            return
        now_min = now.hour * 60 + now.minute
        in_window = start <= now_min <= end if start <= end else (now_min >= start or now_min <= end)
        if not in_window:
            return

        cadence = max(
            TIMELAPSE_MIN_CADENCE,
            min(int(latest_cfg.get("cadenceMinutes", TIMELAPSE_DEFAULT_CADENCE)), TIMELAPSE_MAX_CADENCE),
        )
        last_store = hass.data.setdefault(DOMAIN, {}).setdefault(TIMELAPSE_LAST, {})
        last = last_store.get(entry.entry_id)
        if last is not None and (now - last).total_seconds() < cadence * 60 - 1:
            return

        if await _async_capture_timelapse_frame(hass, latest_entry) is not None:
            last_store[entry.entry_id] = now

    hass.data.setdefault(DOMAIN, {})[TIMELAPSE_UNSUB] = async_track_time_change(
        hass, _handle_timelapse, second=0
    )


async def _async_refresh_issues(
    hass: HomeAssistant, entry: OpenReefConfigEntry | None
) -> None:
    config = _config_from_entry(entry)
    validation = _validate_config(hass, config)

    if validation["missing_entities"]:
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_MISSING_ENTITIES,
            breaks_in_ha_version=None,
            data={"count": len(validation["missing_entities"])},
            is_fixable=False,
            issue_domain=DOMAIN,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_MISSING_ENTITIES,
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_MISSING_ENTITIES)

    if validation["armed_unavailable"]:
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_ARMED_UNAVAILABLE,
            breaks_in_ha_version=None,
            data={"count": len(validation["armed_unavailable"])},
            is_fixable=False,
            issue_domain=DOMAIN,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_ARMED_UNAVAILABLE,
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_ARMED_UNAVAILABLE)

    raw_settings = entry.options.get(CONF_SETTINGS) if entry is not None else None
    if isinstance(raw_settings, dict) and ("general" in raw_settings or "entities" in raw_settings):
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_LEGACY_LABS_CONFIG,
            breaks_in_ha_version=None,
            is_fixable=True,
            issue_domain=DOMAIN,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_LEGACY_LABS_CONFIG,
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_LEGACY_LABS_CONFIG)


async def _async_save_config(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any]
) -> dict[str, Any]:
    normalised = _normalise_core_config(config)
    transitions = _sync_alert_state(hass, normalised)
    options = dict(entry.options)
    options[CONF_SETTINGS] = normalised
    hass.config_entries.async_update_entry(entry, options=options)
    await _async_refresh_issues(hass, entry)
    await _async_sync_alert_notifications(hass, normalised)
    await _async_schedule_mode_timer(hass, entry, normalised)
    await _async_schedule_mode_schedule(hass, entry, normalised)
    await _async_schedule_ato_duty_cycle(hass, entry, normalised)
    await _async_schedule_wavemaker_reminders(hass, entry, normalised)
    await _async_schedule_timelapse(hass, entry, normalised)
    # Event-triggered camera capture on a fresh ok->warning/critical transition.
    for transition in transitions:
        if transition.get("state") == "critical":
            _dispatch_capture(hass, entry, "critical_alert", transition.get("title", "Critical alert"))
        elif transition.get("state") == "warning":
            _dispatch_capture(hass, entry, "warning_alert", transition.get("title", "Warning"))
    return normalised


def _append_activity(config: dict[str, Any], message: str, activity_type: str = "info") -> None:
    activity = config.setdefault("activity", [])
    if not isinstance(activity, list):
        activity = []
        config["activity"] = activity
    activity.insert(
        0,
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": message,
            "type": activity_type,
        },
    )
    config["activity"] = activity[:50]


def _mode_label(config: dict[str, Any], mode_id: str) -> str:
    settings = config.get("modeSettings", {})
    mode_settings = settings.get(mode_id) if isinstance(settings, dict) else None
    if isinstance(mode_settings, dict):
        label = mode_settings.get("label")
        if isinstance(label, str) and label.strip():
            return label.strip()
    return mode_id.replace("_", " ").title()


def _equipment_for_mode(config: dict[str, Any], mode_id: str) -> dict[str, str]:
    if mode_id == "running":
        mode = config.get("mode", {})
        return_plan = mode.get("returnPlan") if isinstance(mode, dict) else {}
        if isinstance(return_plan, dict):
            return {
                equipment_id: desired_state
                for equipment_id, desired_state in return_plan.items()
                if desired_state in {"on", "off"}
            }
        return {}

    mode_previews = config.get("modePreviews", {})
    if isinstance(mode_previews, dict) and isinstance(mode_previews.get(mode_id), dict):
        return {
            equipment_id: desired_state
            for equipment_id, desired_state in mode_previews[mode_id].items()
            if desired_state in {"on", "off"}
        }

    for mode in config.get("modes", []):
        if isinstance(mode, dict) and mode.get("id") == mode_id:
            equipment_config = mode.get("equipmentConfig", {})
            return equipment_config if isinstance(equipment_config, dict) else {}
    raise ServiceValidationError(f"OpenReef mode '{mode_id}' does not exist")


def _equipment_power_on_delay(mapped: dict[str, Any]) -> int:
    try:
        delay = int(mapped.get("powerOnDelaySeconds", 0))
    except (TypeError, ValueError):
        delay = 0
    return max(0, min(delay, 1800))


def _delayed_equipment_key(entry: OpenReefConfigEntry, equipment_id: str) -> str:
    return f"{entry.entry_id}:{equipment_id}"


async def _async_schedule_delayed_equipment_on(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry,
    equipment_id: str,
    mapped: dict[str, Any],
    delay_seconds: int,
    context: Any,
) -> None:
    key = _delayed_equipment_key(entry, equipment_id)
    delayed = hass.data.setdefault(DOMAIN, {}).setdefault(DELAYED_EQUIPMENT_UNSUBS, {})
    old_unsub = delayed.pop(key, None)
    if old_unsub is not None:
        old_unsub()

    switch_entity = _normalise_entity_id(mapped.get("switch_entity_id"))
    label = _equipment_label(equipment_id, mapped)
    run_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)

    async def _turn_on_after_delay(_now: datetime) -> None:
        delayed_store = hass.data.setdefault(DOMAIN, {}).setdefault(
            DELAYED_EQUIPMENT_UNSUBS, {}
        )
        delayed_store.pop(key, None)

        latest_entry = _first_entry(hass)
        if latest_entry is None or latest_entry.entry_id != entry.entry_id:
            return

        latest_config = _config_from_entry(latest_entry)
        latest_mode = latest_config.get("mode", {})
        if not isinstance(latest_mode, dict) or latest_mode.get("active") != "running":
            return

        latest_equipment = latest_config.get("equipment", {})
        latest_mapped = (
            latest_equipment.get(equipment_id)
            if isinstance(latest_equipment, dict)
            else None
        )
        if (
            not isinstance(latest_mapped, dict)
            or not latest_mapped.get("armed", False)
            or _normalise_entity_id(latest_mapped.get("switch_entity_id"))
            != switch_entity
        ):
            return

        state = hass.states.get(switch_entity)
        if state is None or state.state in UNAVAILABLE_STATES or state.state == "on":
            return

        await hass.services.async_call(
            "switch",
            "turn_on",
            {ATTR_ENTITY_ID: switch_entity},
            blocking=True,
            context=context,
        )
        _append_activity(
            latest_config,
            f"Delayed restart completed: {label} turned on after {delay_seconds}s",
            "control",
        )
        await _async_save_config(hass, latest_entry, latest_config)

    delayed[key] = async_track_point_in_time(hass, _turn_on_after_delay, run_at)


async def _async_apply_mode(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry,
    mode_id: str,
    context: Any,
) -> dict[str, Any]:
    config = _config_from_entry(entry)
    equipment_config = _equipment_for_mode(config, mode_id)
    equipment = config.get("equipment", {})
    current_mode = config.get("mode", {}) if isinstance(config.get("mode"), dict) else {}
    existing_return_plan = (
        current_mode.get("returnPlan") if isinstance(current_mode.get("returnPlan"), dict) else {}
    )
    return_plan: dict[str, str] = dict(existing_return_plan)
    should_capture_return_plan = mode_id != "running"

    if not isinstance(equipment, dict):
        raise ServiceValidationError("OpenReef equipment mapping is invalid")

    applied: list[dict[str, str]] = []
    skipped_locked: list[dict[str, str]] = []
    skipped_missing: list[dict[str, str]] = []
    return_pump_turned_off = False

    for equipment_key, desired_state in equipment_config.items():
        if desired_state not in {"on", "off"}:
            continue

        mapped = equipment.get(equipment_key)
        if not isinstance(mapped, dict):
            continue

        switch_entity = _normalise_entity_id(mapped.get("switch_entity_id"))
        if not switch_entity:
            skipped_missing.append(
                {"equipment_id": equipment_key, "reason": "No switch entity mapped"}
            )
            continue

        if not mapped.get("armed", False):
            skipped_locked.append(
                {
                    "equipment_id": equipment_key,
                    "entity_id": switch_entity,
                    "label": str(mapped.get("label") or equipment_key),
                    "reason": "Disarmed in Settings",
                }
            )
            continue

        state = hass.states.get(switch_entity)
        if state is None or state.state in UNAVAILABLE_STATES:
            skipped_missing.append(
                {
                    "equipment_id": equipment_key,
                    "entity_id": switch_entity,
                    "label": str(mapped.get("label") or equipment_key),
                    "reason": "Switch unavailable",
                }
            )
            continue

        if (
            should_capture_return_plan
            and equipment_key not in return_plan
            and state.state in {"on", "off"}
        ):
            return_plan[equipment_key] = state.state

        if desired_state == "on" and _is_protected_display_wavemaker(mapped):
            skipped_locked.append(
                {
                    "equipment_id": equipment_key,
                    "entity_id": switch_entity,
                    "label": _equipment_label(equipment_key, mapped),
                    "reason": "Display wavemaker automatic restart blocked",
                }
            )
            continue

        interlocks = config.get("interlocks", {})
        if (
            mode_id == "running"
            and desired_state == "on"
            and mapped.get("type") == "ato"
            and isinstance(interlocks, dict)
            and interlocks.get("atoDutyCycleEnabled", False)
        ):
            skipped_locked.append(
                {
                    "equipment_id": equipment_key,
                    "entity_id": switch_entity,
                    "label": _equipment_label(equipment_key, mapped),
                    "reason": "ATO duty cycle controls power windows",
                }
            )
            continue

        safety_block_reason = _equipment_safety_block_reason(
            hass, config, equipment_key, mapped, desired_state
        )
        if safety_block_reason:
            skipped_locked.append(
                {
                    "equipment_id": equipment_key,
                    "entity_id": switch_entity,
                    "label": _equipment_label(equipment_key, mapped),
                    "reason": safety_block_reason,
                }
            )
            continue

        if (
            mode_id == "running"
            and desired_state == "on"
            and state.state != "on"
            and _equipment_power_on_delay(mapped) > 0
        ):
            delay_seconds = _equipment_power_on_delay(mapped)
            await _async_schedule_delayed_equipment_on(
                hass, entry, equipment_key, mapped, delay_seconds, context
            )
            applied.append(
                {
                    "equipment_id": equipment_key,
                    "entity_id": switch_entity,
                    "label": str(mapped.get("label") or equipment_key),
                    "state": "delayed_on",
                    "delay_seconds": str(delay_seconds),
                }
            )
            continue

        await hass.services.async_call(
            "switch",
            f"turn_{desired_state}",
            {ATTR_ENTITY_ID: switch_entity},
            blocking=True,
            context=context,
        )
        applied.append(
            {
                "equipment_id": equipment_key,
                "entity_id": switch_entity,
                "label": str(mapped.get("label") or equipment_key),
                "state": desired_state,
            }
        )
        if (
            desired_state == "off"
            and _equipment_profile_for_config(equipment_key, mapped) == "return_pump"
        ):
            return_pump_turned_off = True

    if return_pump_turned_off:
        applied.extend(
            await _async_auto_off_skimmers_for_return_pump(hass, config, context)
        )

    if (
        not applied
        and skipped_locked
        and not skipped_missing
        and all(item.get("reason") == "Disarmed in Settings" for item in skipped_locked)
    ):
        raise ServiceValidationError(
            "OpenReef mode matched equipment, but all mapped controls are locked"
        )

    now = datetime.now(timezone.utc)
    mode_timer = (
        config.get("modeTimers", {}).get(mode_id, {})
        if isinstance(config.get("modeTimers"), dict)
        else {}
    )
    duration_minutes = 0
    auto_return = False
    expires_at = ""
    if should_capture_return_plan and isinstance(mode_timer, dict):
        try:
            duration_minutes = int(mode_timer.get("durationMinutes", 0))
        except (TypeError, ValueError):
            duration_minutes = 0
        duration_minutes = max(0, min(duration_minutes, 720))
        if duration_minutes:
            expires_at = (now + timedelta(minutes=duration_minutes)).isoformat()
            auto_return = bool(mode_timer.get("autoReturn", False))

    config["mode"] = {
        "active": mode_id,
        "startedAt": now.isoformat(),
        "expiresAt": expires_at,
        "autoReturn": auto_return,
        "returnPlan": return_plan if should_capture_return_plan else {},
    }
    mode_label = _mode_label(config, mode_id)
    timer_detail = ""
    if should_capture_return_plan and duration_minutes:
        timer_detail = (
            f", timer {duration_minutes}m, auto-return {'on' if auto_return else 'off'}"
        )
    display_restart_blocked = sum(
        1
        for item in skipped_locked
        if item.get("reason") == "Display wavemaker automatic restart blocked"
    )
    safety_detail = (
        f", {display_restart_blocked} display wavemaker restart blocked"
        if display_restart_blocked
        else ""
    )
    _append_activity(
        config,
        f"{mode_label} mode applied: {len(applied)} changed, {len(skipped_locked)} locked, {len(skipped_missing)} unavailable{safety_detail}{timer_detail}",
        "control",
    )
    await _async_save_config(hass, entry, config)

    # One capture per mode action, most-specific enabled trigger wins (feed > safety > mode).
    capture_triggers = config.get("capture", {}).get("triggers", {})
    if not isinstance(capture_triggers, dict):
        capture_triggers = {}
    capture_candidates: list[tuple[str, str, str]] = []
    if mode_id == "feed":
        capture_candidates.append(("feed_mode", "feedMode", f"{mode_label} mode"))
    if return_pump_turned_off:
        capture_candidates.append(
            ("skimmer_auto_off", "skimmerAutoOff", f"{mode_label} mode — return pump safety")
        )
    capture_candidates.append(("mode_change", "modeChanges", f"{mode_label} mode applied"))
    for event_type, field, capture_label in capture_candidates:
        if capture_triggers.get(field):
            _dispatch_capture(hass, entry, event_type, capture_label)
            break

    return {
        "success": True,
        "mode_id": mode_id,
        "applied": applied,
        "skipped_locked": skipped_locked,
        "skipped_missing": skipped_missing,
    }


async def _handle_apply_mode(hass: HomeAssistant, call: ServiceCall) -> None:
    entry = _first_entry(hass)
    if entry is None:
        raise HomeAssistantError("OpenReef is not configured")

    await _async_apply_mode(hass, entry, call.data["mode_id"], call.context)


async def _handle_arm_equipment(
    hass: HomeAssistant, call: ServiceCall, armed: bool
) -> None:
    entry = _first_entry(hass)
    if entry is None:
        raise HomeAssistantError("OpenReef is not configured")

    equipment_id = call.data["equipment_id"]
    config = _config_from_entry(entry)
    equipment = config.get("equipment", {})
    equipment_config = equipment.get(equipment_id) if isinstance(equipment, dict) else None
    if not isinstance(equipment_config, dict):
        raise ServiceValidationError("Equipment is not mapped in OpenReef")

    switch_entity = _normalise_entity_id(equipment_config.get("switch_entity_id"))
    if armed and (_domain(switch_entity) != "switch" or hass.states.get(switch_entity) is None):
        raise ServiceValidationError("Armed equipment must map to an available switch")

    equipment_config["armed"] = armed
    await _async_save_config(hass, entry, config)


async def _handle_arm_equipment_service(hass: HomeAssistant, call: ServiceCall) -> None:
    await _handle_arm_equipment(hass, call, True)


async def _handle_disarm_equipment_service(hass: HomeAssistant, call: ServiceCall) -> None:
    await _handle_arm_equipment(hass, call, False)


async def _handle_record_manual_reading(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    entry = _first_entry(hass)
    if entry is None:
        raise HomeAssistantError("OpenReef is not configured")

    config = _config_from_entry(entry)
    readings = config.setdefault("manualReadings", {})
    if not isinstance(readings, dict):
        readings = {}
        config["manualReadings"] = readings

    parameter = call.data["parameter"]
    if parameter not in MANUAL_TEST_PARAMETERS:
        raise ServiceValidationError(f"Unsupported OpenReef manual test parameter: {parameter}")
    timestamp = call.data.get("timestamp") or call.data.get("date") or datetime.now(timezone.utc).isoformat()
    sensor = config.get("sensors", {}).get(parameter, {})
    unit = call.data.get("unit") or sensor.get("unit") or MVP_SENSORS.get(parameter, {}).get("unit", "")
    source = call.data.get("source") or ""
    notes = call.data.get("notes") or ""
    readings.setdefault(parameter, []).append(
        {
            "id": f"{parameter}:{timestamp}:{len(readings.get(parameter, []))}",
            "timestamp": timestamp,
            "value": call.data["value"],
            "unit": unit,
            "source": source,
            "notes": notes,
        }
    )

    await _async_save_config(hass, entry, config)


@websocket_api.websocket_command({vol.Required("type"): "openreef/get_config"})
@websocket_api.async_response
async def websocket_get_config(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the current OpenReef core configuration."""
    entry = _first_entry(hass)
    config = _config_from_entry(entry)
    if entry is not None:
        _sync_alert_state(hass, config)
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_SETTINGS: config}
        )
        await _async_sync_alert_notifications(hass, config)
    connection.send_result(
        msg["id"],
        {
            "configured": entry is not None,
            "version": INTEGRATION_VERSION,
            "config": config,
            "settings": config,
            "sensor_meta": MVP_SENSORS,
            "validation": _validate_config(hass, config),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/save_config",
        vol.Required("config"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_save_config(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Persist OpenReef core configuration."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return

    config = await _async_save_config(hass, entry, msg["config"])
    connection.send_result(
        msg["id"],
        {
            "success": True,
            "version": INTEGRATION_VERSION,
            "config": config,
            "validation": _validate_config(hass, config),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/update_config",
        vol.Required("settings"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_update_config_alias(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Backward-compatible alias for older Labs builds."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return

    config = await _async_save_config(hass, entry, msg["settings"])
    connection.send_result(
        msg["id"],
        {"success": True, "version": INTEGRATION_VERSION, "config": config},
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/search_entities",
        vol.Required("target"): dict,
        vol.Optional("limit", default=SEARCH_LIMIT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=SEARCH_LIMIT)
        ),
    }
)
@callback
def websocket_search_entities(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return a bounded list of targeted entity suggestions."""
    connection.send_result(
        msg["id"],
        {
            "candidates": _search_entities(hass, msg["target"], msg["limit"]),
            "limit": msg["limit"],
        },
    )


@websocket_api.websocket_command({vol.Required("type"): "openreef/validate_config"})
@websocket_api.async_response
async def websocket_validate_config(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Validate OpenReef mapped entities against the HA state registry."""
    entry = _first_entry(hass)
    config = _config_from_entry(entry)
    if entry is not None:
        _sync_alert_state(hass, config)
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_SETTINGS: config}
        )
    validation = _validate_config(hass, config)
    await _async_sync_alert_notifications(hass, config)
    connection.send_result(msg["id"], validation)


@websocket_api.websocket_command({vol.Required("type"): "openreef/validate_mappings"})
@websocket_api.async_response
async def websocket_validate_mappings_alias(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Backward-compatible validation alias for older Labs builds."""
    entry = _first_entry(hass)
    config = _config_from_entry(entry)
    if entry is not None:
        _sync_alert_state(hass, config)
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_SETTINGS: config}
        )
    validation = _validate_config(hass, config)
    await _async_sync_alert_notifications(hass, config)
    connection.send_result(msg["id"], validation)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/mute_alert",
        vol.Required("sensor_id"): cv.string,
        vol.Optional("duration_minutes", default=60): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=10080)
        ),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_mute_alert(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Mute or unmute one OpenReef sensor alert."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return

    sensor_id = msg["sensor_id"]
    config = _config_from_entry(entry)
    sensors = config.get("sensors", {})
    if not isinstance(sensors, dict) or sensor_id not in sensors:
        connection.send_error(msg["id"], "invalid_sensor", "Unknown OpenReef sensor")
        return

    alert_config = config.setdefault("alerts", {})
    mute_until = alert_config.setdefault("muteUntil", {})
    duration = msg["duration_minutes"]
    if duration <= 0:
        mute_until.pop(sensor_id, None)
    else:
        muted_until = datetime.now(timezone.utc) + timedelta(minutes=duration)
        mute_until[sensor_id] = muted_until.isoformat()

    config = await _async_save_config(hass, entry, config)
    connection.send_result(
        msg["id"],
        {
            "success": True,
            "version": INTEGRATION_VERSION,
            "config": config,
            "validation": _validate_config(hass, config),
        },
    )


@websocket_api.websocket_command({vol.Required("type"): "openreef/clear_alert_history"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_clear_alert_history(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Clear stored OpenReef alert history."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return

    config = _config_from_entry(entry)
    config.setdefault("alerts", {})["history"] = []
    config = await _async_save_config(hass, entry, config)
    connection.send_result(
        msg["id"],
        {
            "success": True,
            "version": INTEGRATION_VERSION,
            "config": config,
            "validation": _validate_config(hass, config),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/apply_mode",
        vol.Required("mode_id"): cv.string,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_apply_mode(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Apply one confirmed OpenReef mode to explicitly armed equipment."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return

    try:
        result = await _async_apply_mode(
            hass, entry, msg["mode_id"], connection.context(msg)
        )
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_mode", str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/toggle_equipment",
        vol.Required("equipment_id"): cv.string,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_toggle_equipment(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Toggle one explicitly armed mapped switch entity."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return

    config = _config_from_entry(entry)
    equipment = config.get("equipment", {})
    if not isinstance(equipment, dict):
        connection.send_error(msg["id"], "invalid_config", "OpenReef equipment mapping is invalid")
        return

    equipment_id = msg["equipment_id"]
    mapped = equipment.get(equipment_id)
    if not isinstance(mapped, dict):
        connection.send_error(msg["id"], "not_mapped", "Equipment is not mapped in OpenReef")
        return

    switch_entity = _normalise_entity_id(mapped.get("switch_entity_id"))
    if not switch_entity or _domain(switch_entity) != "switch":
        connection.send_error(msg["id"], "invalid_entity", "Equipment must map to a switch entity")
        return

    if not mapped.get("armed", False):
        connection.send_error(msg["id"], "not_armed", "OpenReef control is not armed for this equipment")
        return

    state = hass.states.get(switch_entity)
    if state is None or state.state in UNAVAILABLE_STATES:
        connection.send_error(msg["id"], "missing_entity", "Mapped switch entity is not available")
        return

    if state.state not in {"on", "off"}:
        connection.send_error(msg["id"], "invalid_state", "Mapped switch is not on or off")
        return

    target_state = "off" if state.state == "on" else "on"
    safety_block_reason = _equipment_safety_block_reason(
        hass, config, equipment_id, mapped, target_state
    )
    if safety_block_reason:
        connection.send_error(msg["id"], "safety_blocked", safety_block_reason)
        return

    await hass.services.async_call(
        "switch",
        f"turn_{target_state}",
        {ATTR_ENTITY_ID: switch_entity},
        blocking=True,
        context=connection.context(msg),
    )

    safety_actions: list[dict[str, str]] = []
    if target_state == "off" and _equipment_profile_for_config(equipment_id, mapped) == "return_pump":
        safety_actions = await _async_auto_off_skimmers_for_return_pump(
            hass, config, connection.context(msg)
        )
        if safety_actions:
            config = await _async_save_config(hass, entry, config)
            _dispatch_capture(hass, entry, "skimmer_auto_off", "Return pump safety auto-off")

    connection.send_result(
        msg["id"],
        {
            "success": True,
            "equipment_id": equipment_id,
            "entity_id": switch_entity,
            "state": _runtime_state_for_entity(hass, switch_entity),
            "target_state": target_state,
            "safety_actions": safety_actions,
            "config": config,
            "validation": _validate_config(hass, config),
        },
    )


# --- Camera V2 / Phase A: event-triggered capture -----------------------------------------

def _captures_dir(hass: HomeAssistant) -> Path:
    """Managed directory (under the HA config dir) for captured clips and thumbnails."""
    return Path(hass.config.path(CAPTURES_DIR_NAME))


async def _async_register_captures_path(hass: HomeAssistant) -> None:
    """Create + serve the captures directory once, same-origin to the panel.

    We add our own subdirectory to ``allowlist_external_dirs`` in memory so the stable
    ``camera.record`` service can write clips here without the tester editing
    ``configuration.yaml`` — it only ever widens the allowlist to a dir we fully control.
    """
    data = hass.data.setdefault(DOMAIN, {})
    if data.get(CAPTURES_PATH_REGISTERED):
        return
    captures_dir = _captures_dir(hass)
    await hass.async_add_executor_job(
        lambda: captures_dir.mkdir(parents=True, exist_ok=True)
    )
    try:
        hass.config.allowlist_external_dirs.add(str(captures_dir))
    except Exception:  # noqa: BLE001 - non-fatal; snapshot fallback still works
        _LOGGER.debug("Could not extend allowlist_external_dirs for captures", exc_info=True)
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                CAPTURES_STATIC_URL,
                str(captures_dir),
                cache_headers=False,
            )
        ]
    )
    data[CAPTURES_PATH_REGISTERED] = True


def _resolve_capture_camera(
    hass: HomeAssistant,
    config: dict[str, Any],
    capture_cfg: dict[str, Any],
    override: str | None = None,
) -> tuple[str, str, str] | None:
    """Pick the first online, mapped camera to capture. Returns (id, entity_id, label)."""
    cameras = config.get("cameras", {})
    if not isinstance(cameras, dict) or not cameras:
        return None
    if override and override in cameras:
        candidate_ids = [override]
    else:
        selected = capture_cfg.get("cameraIds")
        selected = [cid for cid in selected if cid in cameras] if isinstance(selected, list) else []
        candidate_ids = selected or list(cameras.keys())
    for cid in candidate_ids:
        cam = cameras.get(cid)
        if not isinstance(cam, dict):
            continue
        entity_id = _normalise_entity_id(cam.get("entity_id"))
        if not entity_id:
            continue
        state = hass.states.get(entity_id)
        if state is None or state.state in UNAVAILABLE_STATES:
            continue
        return cid, entity_id, str(cam.get("label") or cid)
    return None


async def _async_delete_capture_files(
    hass: HomeAssistant, records: list[dict[str, Any]]
) -> None:
    """Best-effort delete of the clip + thumbnail files for pruned/removed records."""
    captures_dir = _captures_dir(hass)
    paths: list[Path] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in ("video", "thumbnail"):
            name = record.get(key)
            if isinstance(name, str) and name:
                paths.append(captures_dir / name)
    if not paths:
        return

    def _remove() -> None:
        for path in paths:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                _LOGGER.debug("Could not delete capture file %s", path, exc_info=True)

    await hass.async_add_executor_job(_remove)


async def _async_record_clip(
    hass: HomeAssistant,
    camera_entity_id: str,
    video_path: Path,
    duration: int,
    lookback: int,
) -> bool:
    """Record an MP4 clip via the stable ``camera.record`` service. Returns True on success."""
    data: dict[str, Any] = {
        ATTR_ENTITY_ID: camera_entity_id,
        "filename": str(video_path),
        "duration": duration,
    }
    if lookback > 0:
        data["lookback"] = lookback
    await hass.services.async_call("camera", "record", data, blocking=True)
    return await hass.async_add_executor_job(video_path.exists)


async def _async_write_snapshot(hass: HomeAssistant, entity_id: str, path: Path) -> bool:
    """Grab a still from a camera entity and write it to ``path`` (parent must exist).

    Works on any camera, no allowlist. Best-effort — logs and returns False on failure,
    never raises. Shared by event-capture thumbnails and timelapse frames.
    """
    try:
        from homeassistant.components import camera as camera_component

        image = await camera_component.async_get_image(hass, entity_id, timeout=10)
        await hass.async_add_executor_job(path.write_bytes, image.content)
        return True
    except Exception:  # noqa: BLE001 - snapshot is best-effort
        _LOGGER.warning("OpenReef snapshot failed for %s", entity_id, exc_info=True)
        return False


async def _async_perform_capture(
    hass: HomeAssistant,
    capture_cfg: dict[str, Any],
    camera_id: str,
    camera_entity_id: str,
    camera_label: str,
    event_meta: dict[str, str],
    now: datetime,
) -> dict[str, Any]:
    """Take a snapshot (always) + a clip (best-effort) and return a capture record."""
    captures_dir = _captures_dir(hass)
    await hass.async_add_executor_job(
        lambda: captures_dir.mkdir(parents=True, exist_ok=True)
    )
    event_type = event_meta.get("eventType", "event")
    base = f"{event_type}_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    duration = max(
        CAPTURE_MIN_DURATION,
        min(int(capture_cfg.get("durationSeconds", CAPTURE_DEFAULT_DURATION)), CAPTURE_MAX_DURATION),
    )
    lookback = max(0, min(int(capture_cfg.get("lookbackSeconds", 0)), CAPTURE_MAX_LOOKBACK))

    thumbnail = ""
    video = ""
    status = "failed"

    # Snapshot first — works on any camera, no allowlist, and doubles as the gallery poster.
    if await _async_write_snapshot(hass, camera_entity_id, captures_dir / f"{base}.jpg"):
        thumbnail = f"{base}.jpg"
        status = "snapshot"

    # Clip is the headline; degrades to the snapshot if the camera has no stream.
    video_path = captures_dir / f"{base}.mp4"
    try:
        if await _async_record_clip(hass, camera_entity_id, video_path, duration, lookback):
            video = video_path.name
            status = "clip"
    except Exception:  # noqa: BLE001 - keep the snapshot on any clip failure
        _LOGGER.warning(
            "OpenReef clip recording failed for %s; keeping snapshot", camera_entity_id, exc_info=True
        )

    return {
        "id": uuid.uuid4().hex,
        "timestamp": now.isoformat(),
        "eventType": event_type,
        "label": event_meta.get("label", "Event"),
        "cameraId": camera_id,
        "cameraEntityId": camera_entity_id,
        "cameraLabel": camera_label,
        "video": video,
        "thumbnail": thumbnail,
        "durationSeconds": duration,
        "status": status,
    }


async def _async_capture_event(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry,
    event_meta: dict[str, str],
    camera_override: str | None = None,
) -> dict[str, Any] | None:
    """Capture a clip/snapshot for an OpenReef event. Never raises into the caller's path."""
    try:
        config = _config_from_entry(entry)
        capture_cfg = config.get("capture", {})
        if not isinstance(capture_cfg, dict):
            return None
        manual = event_meta.get("eventType") == "manual"
        if not manual and not capture_cfg.get("enabled", False):
            return None

        now = datetime.now(timezone.utc)
        trigger_key = event_meta.get("eventType", "manual")
        last_map = (
            hass.data.setdefault(DOMAIN, {})
            .setdefault(CAPTURE_LAST, {})
            .setdefault(entry.entry_id, {})
        )
        cooldown = int(capture_cfg.get("cooldownSeconds", CAPTURE_DEFAULT_COOLDOWN))
        if not manual and cooldown > 0:
            last = last_map.get(trigger_key)
            if last is not None and (now - last).total_seconds() < cooldown:
                return None

        camera = _resolve_capture_camera(hass, config, capture_cfg, camera_override)
        if camera is None:
            _LOGGER.debug("OpenReef capture skipped: no available camera (%s)", trigger_key)
            return None
        camera_id, camera_entity_id, camera_label = camera

        # Synchronous check-and-add before any await => the event loop serialises concurrent
        # dispatches, so the same camera never records two overlapping clips.
        inflight: set[str] = hass.data.setdefault(DOMAIN, {}).setdefault(CAPTURE_INFLIGHT, set())
        if camera_entity_id in inflight:
            return None
        inflight.add(camera_entity_id)
        try:
            record = await _async_perform_capture(
                hass, capture_cfg, camera_id, camera_entity_id, camera_label, event_meta, now
            )
        finally:
            inflight.discard(camera_entity_id)

        fresh = _config_from_entry(entry)
        captures = fresh.get("captures")
        if not isinstance(captures, list):
            captures = []
        captures.insert(0, record)
        retention = max(1, min(int(capture_cfg.get("retention", CAPTURE_DEFAULT_RETENTION)), CAPTURE_MAX_RECORDS))
        removed = captures[retention:]
        fresh["captures"] = captures[:retention]
        await _async_delete_capture_files(hass, removed)
        _append_activity(
            fresh,
            f"Captured {record['status']} from {camera_label}: {event_meta.get('label', 'event')}",
            "info",
        )
        last_map[trigger_key] = now
        await _async_save_config(hass, entry, fresh)
        return record
    except Exception:  # noqa: BLE001 - capture must never break the alert/safety path
        _LOGGER.exception("OpenReef camera capture failed")
        return None


def _dispatch_capture(
    hass: HomeAssistant, entry: OpenReefConfigEntry, event_type: str, label: str
) -> None:
    """Fire-and-forget a capture if enabled and this trigger's toggle is on."""
    config = _config_from_entry(entry)
    capture_cfg = config.get("capture", {})
    if not isinstance(capture_cfg, dict) or not capture_cfg.get("enabled", False):
        return
    triggers = capture_cfg.get("triggers", {})
    field = CAPTURE_TRIGGER_FIELD.get(event_type)
    if field and not (isinstance(triggers, dict) and triggers.get(field, False)):
        return
    hass.async_create_task(
        _async_capture_event(hass, entry, {"eventType": event_type, "label": label}),
        "openreef_capture",
    )


# --- Timelapse (Phase B): scheduled frames + tiered downsampling retention ---

def _timelapse_dir(hass: HomeAssistant, camera_id: str) -> Path:
    """Per-camera subdir of the captures dir holding (and serving) timelapse frames."""
    return _captures_dir(hass) / TIMELAPSE_SUBDIR / camera_id


_TIMELAPSE_FRAME_RE = re.compile(r"^(\d{8}_\d{6})\.jpg$")


def _timelapse_frame_timestamp(filename: str) -> datetime | None:
    """Parse 'YYYYMMDD_HHMMSS.jpg' to a naive (local wall-clock) datetime, or None."""
    match = _TIMELAPSE_FRAME_RE.match(filename)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def _timelapse_window_mid(timelapse_cfg: dict[str, Any]) -> int:
    """Minutes-since-midnight of the capture window's midpoint (for keeper selection)."""
    start = _hhmm_to_minutes(timelapse_cfg.get("windowStart"))
    end = _hhmm_to_minutes(timelapse_cfg.get("windowEnd"))
    if start is None:
        start = _hhmm_to_minutes(TIMELAPSE_DEFAULT_WINDOW_START) or 0
    if end is None:
        end = _hhmm_to_minutes(TIMELAPSE_DEFAULT_WINDOW_END) or (24 * 60 - 1)
    if end < start:
        end += 24 * 60  # window crosses midnight
    return ((start + end) // 2) % (24 * 60)


def _timelapse_keepers(
    timestamps: list[datetime], now: datetime, retention: dict[str, int], window_mid: int
) -> set[datetime]:
    """The 4-tier downsampling ladder (pure, unit-testable). Returns timestamps to KEEP.

    By age: ``<= detailDays`` keep every frame; ``<= dailyUntilDays`` keep 1/day;
    ``<= weeklyUntilDays`` keep 1/week (ISO year+week); ``<= monthlyUntilDays``
    (or forever when 0) keep 1/month; older -> drop. Each daily/weekly/monthly bucket
    keeps the frame whose time-of-day is closest to ``window_mid`` (consistent lighting).
    Re-evaluates all frames by age, so it converges/cascades on repeated runs.
    """
    detail = retention.get("detailDays", 0)
    daily = retention.get("dailyUntilDays", 0)
    weekly = retention.get("weeklyUntilDays", 0)
    monthly = retention.get("monthlyUntilDays", 0)

    keep: set[datetime] = set()
    buckets: dict[tuple, tuple[int, datetime]] = {}

    def _consider(key: tuple, ts: datetime) -> None:
        distance = abs((ts.hour * 60 + ts.minute) - window_mid)
        current = buckets.get(key)
        if current is None or distance < current[0]:
            buckets[key] = (distance, ts)

    for ts in timestamps:
        age_days = (now - ts).total_seconds() / 86400.0
        if age_days <= detail:
            keep.add(ts)
        elif age_days <= daily:
            _consider(("d", ts.year, ts.month, ts.day), ts)
        elif age_days <= weekly:
            iso = ts.isocalendar()
            _consider(("w", iso[0], iso[1]), ts)
        elif monthly == 0 or age_days <= monthly:
            _consider(("m", ts.year, ts.month), ts)
        # else: older than the final tier -> dropped

    for _distance, ts in buckets.values():
        keep.add(ts)
    return keep


async def _async_prune_timelapse(
    hass: HomeAssistant, camera_id: str, retention: dict[str, int], window_mid: int
) -> None:
    """Apply the tiered retention ladder to a camera's timelapse frames on disk."""
    frame_dir = _timelapse_dir(hass, camera_id)

    def _list() -> list[str]:
        if not frame_dir.is_dir():
            return []
        return [p.name for p in frame_dir.iterdir() if p.is_file() and p.suffix == ".jpg"]

    names = await hass.async_add_executor_job(_list)
    ts_by_name = {name: _timelapse_frame_timestamp(name) for name in names}
    timestamps = [ts for ts in ts_by_name.values() if ts is not None]
    if not timestamps:
        return
    now = dt_util.now().replace(tzinfo=None)
    keep = _timelapse_keepers(timestamps, now, retention, window_mid)
    to_delete = [name for name, ts in ts_by_name.items() if ts is None or ts not in keep]
    if not to_delete:
        return

    def _remove() -> None:
        for name in to_delete:
            try:
                (frame_dir / name).unlink()
            except FileNotFoundError:
                pass
            except OSError:
                _LOGGER.debug("Could not delete timelapse frame %s", name, exc_info=True)

    await hass.async_add_executor_job(_remove)


async def _async_capture_timelapse_frame(
    hass: HomeAssistant, entry: OpenReefConfigEntry, override: str | None = None
) -> dict[str, Any] | None:
    """Write one timelapse frame for the configured camera, then prune. Never raises."""
    try:
        config = _config_from_entry(entry)
        timelapse_cfg = config.get("timelapse", {})
        if not isinstance(timelapse_cfg, dict):
            return None
        target = override or timelapse_cfg.get("cameraId") or None
        resolved = _resolve_capture_camera(hass, config, {}, override=target)
        if resolved is None:
            return None
        camera_id, entity_id, camera_label = resolved
        frame_dir = _timelapse_dir(hass, camera_id)
        await hass.async_add_executor_job(lambda: frame_dir.mkdir(parents=True, exist_ok=True))
        name = f"{dt_util.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        if not await _async_write_snapshot(hass, entity_id, frame_dir / name):
            return None
        retention = timelapse_cfg.get("retention", {})
        if not isinstance(retention, dict):
            retention = {}
        await _async_prune_timelapse(
            hass, camera_id, retention, _timelapse_window_mid(timelapse_cfg)
        )
        return {"cameraId": camera_id, "cameraLabel": camera_label, "file": name}
    except Exception:  # noqa: BLE001 - timelapse must never break anything
        _LOGGER.exception("OpenReef timelapse frame capture failed")
        return None


@websocket_api.websocket_command({vol.Required("type"): "openreef/list_recordings"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_list_recordings(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the stored capture records + the base URL the panel serves them from."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    captures = config.get("captures", [])
    if not isinstance(captures, list):
        captures = []
    connection.send_result(msg["id"], {"captures": captures, "baseUrl": CAPTURES_STATIC_URL})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/delete_recording",
        # NB: the param must NOT be named "id" — that collides with the websocket
        # protocol's own message id, which the frontend overwrites before sending.
        vol.Required("recording_id"): cv.string,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_delete_recording(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete one capture's files + record."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    captures = config.get("captures", [])
    if not isinstance(captures, list):
        captures = []
    recording_id = msg["recording_id"]
    target = next(
        (rec for rec in captures if isinstance(rec, dict) and rec.get("id") == recording_id), None
    )
    if target is None:
        connection.send_error(msg["id"], "not_found", "Recording not found")
        return
    await _async_delete_capture_files(hass, [target])
    config["captures"] = [
        rec for rec in captures if not (isinstance(rec, dict) and rec.get("id") == recording_id)
    ]
    saved = await _async_save_config(hass, entry, config)
    connection.send_result(msg["id"], {"success": True, "config": saved})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/capture_now",
        vol.Optional("camera_id"): cv.string,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_capture_now(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Manually capture a clip/snapshot now (bypasses the enabled/trigger gate)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    record = await _async_capture_event(
        hass,
        entry,
        {"eventType": "manual", "label": "Manual capture"},
        camera_override=msg.get("camera_id"),
    )
    if not record:
        connection.send_error(
            msg["id"],
            "capture_failed",
            "Could not capture — check a camera is mapped and online",
        )
        return
    connection.send_result(
        msg["id"], {"success": True, "record": record, "config": _config_from_entry(entry)}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/list_timelapse_frames",
        vol.Optional("camera_id"): cv.string,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_list_timelapse_frames(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """List a camera's timelapse frames (oldest-first) for the in-panel player."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    timelapse_cfg = config.get("timelapse", {})
    if not isinstance(timelapse_cfg, dict):
        timelapse_cfg = {}
    camera_id = msg.get("camera_id") or timelapse_cfg.get("cameraId") or ""
    if not camera_id:
        resolved = _resolve_capture_camera(hass, config, {})
        camera_id = resolved[0] if resolved else ""
    cameras = config.get("cameras", {})
    camera_label = ""
    if isinstance(cameras, dict) and isinstance(cameras.get(camera_id), dict):
        camera_label = str(cameras[camera_id].get("label") or camera_id)

    frames: list[dict[str, str]] = []
    if camera_id:
        frame_dir = _timelapse_dir(hass, camera_id)

        def _list() -> list[str]:
            if not frame_dir.is_dir():
                return []
            return sorted(
                p.name for p in frame_dir.iterdir() if p.is_file() and p.suffix == ".jpg"
            )

        for name in await hass.async_add_executor_job(_list):
            ts = _timelapse_frame_timestamp(name)
            if ts is None:
                continue
            frames.append(
                {"file": f"{TIMELAPSE_SUBDIR}/{camera_id}/{name}", "ts": ts.isoformat()}
            )

    connection.send_result(
        msg["id"],
        {
            "frames": frames,
            "baseUrl": CAPTURES_STATIC_URL,
            "cameraId": camera_id,
            "cameraLabel": camera_label,
            "windowMidMinutes": _timelapse_window_mid(timelapse_cfg),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/capture_timelapse_frame",
        vol.Optional("camera_id"): cv.string,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_capture_timelapse_frame(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Grab one timelapse frame now (seed/test), ignoring window + cadence."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    result = await _async_capture_timelapse_frame(hass, entry, override=msg.get("camera_id"))
    if result is None:
        connection.send_error(
            msg["id"],
            "capture_failed",
            "Could not capture — check a camera is mapped and online",
        )
        return
    connection.send_result(msg["id"], {"success": True, "frame": result})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/clear_timelapse",
        vol.Optional("camera_id"): cv.string,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_clear_timelapse(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete all timelapse frames for a camera (reset)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    timelapse_cfg = config.get("timelapse", {})
    camera_id = msg.get("camera_id") or (
        timelapse_cfg.get("cameraId") if isinstance(timelapse_cfg, dict) else ""
    ) or ""
    if not camera_id:
        resolved = _resolve_capture_camera(hass, config, {})
        camera_id = resolved[0] if resolved else ""
    if camera_id:
        frame_dir = _timelapse_dir(hass, camera_id)

        def _wipe() -> None:
            if not frame_dir.is_dir():
                return
            for p in frame_dir.iterdir():
                if p.is_file() and p.suffix == ".jpg":
                    try:
                        p.unlink()
                    except OSError:
                        _LOGGER.debug("Could not delete timelapse frame %s", p, exc_info=True)

        await hass.async_add_executor_job(_wipe)
    connection.send_result(msg["id"], {"success": True, "cameraId": camera_id})


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Register the OpenReef native sidebar panel once."""
    if hass.data.setdefault(DOMAIN, {}).get("panel_registered"):
        return

    frontend_path = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                PANEL_STATIC_URL,
                str(frontend_path),
                cache_headers=False,
            )
        ]
    )

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="openreef-panel",
        frontend_url_path=PANEL_URL,
        sidebar_title=NAME,
        sidebar_icon=PANEL_ICON,
        module_url=f"{PANEL_STATIC_URL}/openreef-panel.js?v={INTEGRATION_VERSION}",
        embed_iframe=False,
        require_admin=False,
        config={"domain": DOMAIN},
    )
    hass.data[DOMAIN]["panel_registered"] = True


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up OpenReef services and websocket commands."""
    websocket_api.async_register_command(hass, websocket_get_config)
    websocket_api.async_register_command(hass, websocket_save_config)
    websocket_api.async_register_command(hass, websocket_update_config_alias)
    websocket_api.async_register_command(hass, websocket_search_entities)
    websocket_api.async_register_command(hass, websocket_validate_config)
    websocket_api.async_register_command(hass, websocket_validate_mappings_alias)
    websocket_api.async_register_command(hass, websocket_mute_alert)
    websocket_api.async_register_command(hass, websocket_clear_alert_history)
    websocket_api.async_register_command(hass, websocket_apply_mode)
    websocket_api.async_register_command(hass, websocket_toggle_equipment)
    websocket_api.async_register_command(hass, websocket_list_recordings)
    websocket_api.async_register_command(hass, websocket_delete_recording)
    websocket_api.async_register_command(hass, websocket_capture_now)
    websocket_api.async_register_command(hass, websocket_list_timelapse_frames)
    websocket_api.async_register_command(hass, websocket_capture_timelapse_frame)
    websocket_api.async_register_command(hass, websocket_clear_timelapse)

    hass.services.async_register(
        DOMAIN,
        SERVICE_APPLY_MODE,
        _handle_apply_mode,
        schema=APPLY_MODE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RECORD_MANUAL_READING,
        _handle_record_manual_reading,
        schema=RECORD_MANUAL_READING_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ARM_EQUIPMENT,
        _handle_arm_equipment_service,
        schema=EQUIPMENT_ARM_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DISARM_EQUIPMENT,
        _handle_disarm_equipment_service,
        schema=EQUIPMENT_ARM_SCHEMA,
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: OpenReefConfigEntry) -> bool:
    """Set up OpenReef from a config entry."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry
    await _async_register_panel(hass)
    await _async_register_captures_path(hass)
    raw_settings = entry.options.get(CONF_SETTINGS)
    normalised = _config_from_entry(entry)
    is_legacy = isinstance(raw_settings, dict) and (
        "general" in raw_settings or "entities" in raw_settings
    )
    _sync_alert_state(hass, normalised)
    if normalised != raw_settings and not is_legacy:
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_SETTINGS: normalised}
        )
    await _async_refresh_issues(hass, entry)
    await _async_sync_alert_notifications(hass, normalised)
    await _async_schedule_mode_timer(hass, entry, normalised)
    await _async_schedule_mode_schedule(hass, entry, normalised)
    await _async_schedule_ato_duty_cycle(hass, entry, normalised)
    await _async_schedule_wavemaker_reminders(hass, entry, normalised)
    await _async_schedule_timelapse(hass, entry, normalised)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OpenReefConfigEntry) -> bool:
    """Unload an OpenReef config entry."""
    _clear_mode_timer(hass)
    _clear_mode_schedule(hass)
    _clear_ato_duty_cycle(hass)
    _clear_delayed_equipment_calls(hass)
    _clear_wavemaker_reminders(hass)
    _clear_timelapse(hass)
    hass.data.setdefault(DOMAIN, {}).setdefault(ATO_DUTY_CYCLE_LAST, {}).pop(
        entry.entry_id, None
    )
    hass.data.setdefault(DOMAIN, {}).setdefault(WAVEMAKER_REMINDER_LAST, {}).pop(
        entry.entry_id, None
    )
    hass.data.setdefault(DOMAIN, {}).setdefault(CAPTURE_LAST, {}).pop(entry.entry_id, None)
    hass.data.setdefault(DOMAIN, {}).setdefault(TIMELAPSE_LAST, {}).pop(entry.entry_id, None)
    config = _config_from_entry(entry)
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    ir.async_delete_issue(hass, DOMAIN, ISSUE_MISSING_ENTITIES)
    ir.async_delete_issue(hass, DOMAIN, ISSUE_ARMED_UNAVAILABLE)
    ir.async_delete_issue(hass, DOMAIN, ISSUE_LEGACY_LABS_CONFIG)
    for sensor_id in MVP_SENSORS:
        await hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {"notification_id": f"openreef_alert_{sensor_id}"},
            blocking=False,
        )
    equipment = config.get("equipment", {})
    if isinstance(equipment, dict):
        for equipment_id in equipment:
            await hass.services.async_call(
                "persistent_notification",
                "dismiss",
                {"notification_id": f"openreef_display_wavemaker_{equipment_id}"},
                blocking=False,
            )
    return True


async def async_reload_entry(hass: HomeAssistant, entry: OpenReefConfigEntry) -> None:
    """Reload an OpenReef config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
