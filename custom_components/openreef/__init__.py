"""OpenReef Home Assistant native controller integration."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
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
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_SETTINGS,
    DEFAULT_CORE_CONFIG,
    DOMAIN,
    ISSUE_ARMED_UNAVAILABLE,
    ISSUE_LEGACY_LABS_CONFIG,
    ISSUE_MISSING_ENTITIES,
    MVP_SENSORS,
    NAME,
    PANEL_ICON,
    PANEL_STATIC_URL,
    PANEL_URL,
    SERVICE_APPLY_MODE,
    SERVICE_ARM_EQUIPMENT,
    SERVICE_DISARM_EQUIPMENT,
    SERVICE_RECORD_MANUAL_READING,
)

type OpenReefConfigEntry = ConfigEntry


SEARCH_LIMIT = 10
UNAVAILABLE_STATES = {"unknown", "unavailable"}

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
        sensor.setdefault("unit", meta["unit"])
        sensor.setdefault("min", meta["min"])
        sensor.setdefault("max", meta["max"])
        sensor["alertsEnabled"] = bool(sensor.get("alertsEnabled", True))
        try:
            sensor["warningBuffer"] = float(sensor.get("warningBuffer", 10))
        except (TypeError, ValueError):
            sensor["warningBuffer"] = 10
        sensor["warningBuffer"] = max(0, min(sensor["warningBuffer"], 50))

    mode = config.setdefault("mode", {})
    if not isinstance(mode, dict):
        config["mode"] = deepcopy(DEFAULT_CORE_CONFIG["mode"])
    else:
        active = mode.get("active")
        mode["active"] = active if active in {"running", "feed", "maintenance"} else "running"
        mode["startedAt"] = mode.get("startedAt") if isinstance(mode.get("startedAt"), str) else ""
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
        for mode_id in ("feed", "maintenance"):
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
        try:
            interlocks["atoMaxRuntimeMinutes"] = int(
                interlocks.get("atoMaxRuntimeMinutes", 5)
            )
        except (TypeError, ValueError):
            interlocks["atoMaxRuntimeMinutes"] = 5
        interlocks["atoMaxRuntimeMinutes"] = max(
            1, min(interlocks["atoMaxRuntimeMinutes"], 120)
        )
        interlocks["returnPumpSkimmerWarning"] = bool(
            interlocks.get("returnPumpSkimmerWarning", True)
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


def _sensor_alert_items(hass: HomeAssistant, config: dict[str, Any]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    sensors = config.get("sensors", {})
    if not isinstance(sensors, dict):
        return alerts

    for sensor_id, sensor in sensors.items():
        if not isinstance(sensor, dict):
            continue
        if not sensor.get("enabled", False) or not sensor.get("alertsEnabled", True):
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
        if value < minimum + buffer or value > maximum - buffer:
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
    options = dict(entry.options)
    options[CONF_SETTINGS] = normalised
    hass.config_entries.async_update_entry(entry, options=options)
    await _async_refresh_issues(hass, entry)
    await _async_sync_alert_notifications(hass, normalised)
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

    if not applied and skipped_locked and not skipped_missing:
        raise ServiceValidationError(
            "OpenReef mode matched equipment, but all mapped controls are locked"
        )

    config["mode"] = {
        "active": mode_id,
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "returnPlan": return_plan if should_capture_return_plan else {},
    }
    mode_label = mode_id.replace("_", " ").title()
    _append_activity(
        config,
        f"{mode_label} mode applied: {len(applied)} changed, {len(skipped_locked)} locked, {len(skipped_missing)} unavailable",
        "control",
    )
    await _async_save_config(hass, entry, config)

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
    date = call.data.get("date") or datetime.now(timezone.utc).date().isoformat()
    readings.setdefault(parameter, []).append({"date": date, "value": call.data["value"]})

    await _async_save_config(hass, entry, config)


@websocket_api.websocket_command({vol.Required("type"): "openreef/get_config"})
@callback
def websocket_get_config(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the current OpenReef core configuration."""
    entry = _first_entry(hass)
    config = _config_from_entry(entry)
    connection.send_result(
        msg["id"],
        {
            "configured": entry is not None,
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
        {"success": True, "config": config, "validation": _validate_config(hass, config)},
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
    connection.send_result(msg["id"], {"success": True, "config": config})


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
    validation = _validate_config(hass, config)
    await _async_sync_alert_notifications(hass, config)
    connection.send_result(msg["id"], validation)


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

    if hass.states.get(switch_entity) is None:
        connection.send_error(msg["id"], "missing_entity", "Mapped switch entity is not available")
        return

    await hass.services.async_call(
        "switch",
        "toggle",
        {ATTR_ENTITY_ID: switch_entity},
        blocking=True,
        context=connection.context(msg),
    )

    connection.send_result(
        msg["id"],
        {
            "success": True,
            "equipment_id": equipment_id,
            "entity_id": switch_entity,
            "state": _runtime_state_for_entity(hass, switch_entity),
        },
    )


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
        module_url=f"{PANEL_STATIC_URL}/openreef-panel.js",
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
    websocket_api.async_register_command(hass, websocket_apply_mode)
    websocket_api.async_register_command(hass, websocket_toggle_equipment)

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
    raw_settings = entry.options.get(CONF_SETTINGS)
    normalised = _config_from_entry(entry)
    is_legacy = isinstance(raw_settings, dict) and (
        "general" in raw_settings or "entities" in raw_settings
    )
    if normalised != raw_settings and not is_legacy:
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_SETTINGS: normalised}
        )
    await _async_refresh_issues(hass, entry)
    await _async_sync_alert_notifications(hass, normalised)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OpenReefConfigEntry) -> bool:
    """Unload an OpenReef config entry."""
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
    return True


async def async_reload_entry(hass: HomeAssistant, entry: OpenReefConfigEntry) -> None:
    """Reload an OpenReef config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
