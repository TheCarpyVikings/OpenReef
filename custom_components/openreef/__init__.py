"""OpenReef Home Assistant companion integration."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_SETTINGS,
    DEFAULT_SETTINGS,
    DOMAIN,
    ISSUE_MISSING_ENTITIES,
    SERVICE_APPLY_MODE,
    SERVICE_RECORD_MANUAL_READING,
)

type OpenReefConfigEntry = ConfigEntry


APPLY_MODE_SCHEMA = vol.Schema({vol.Required("mode_id"): cv.string})

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


def _settings_from_entry(entry: OpenReefConfigEntry | None) -> dict[str, Any]:
    if entry is None:
        return deepcopy(DEFAULT_SETTINGS)
    settings = entry.options.get(CONF_SETTINGS)
    if isinstance(settings, dict):
        return deepcopy(settings)
    return deepcopy(DEFAULT_SETTINGS)


def _normalise_entity_id(value: Any) -> str | None:
    if isinstance(value, str) and "." in value:
        return value
    return None


def _collect_entity_ids(settings: dict[str, Any]) -> set[str]:
    entity_ids: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        else:
            entity_id = _normalise_entity_id(value)
            if entity_id:
                entity_ids.add(entity_id)

    walk(settings.get("entities", {}))
    walk(settings.get("lighting", {}).get("channels", {}))
    return entity_ids


def _validate_settings(hass: HomeAssistant, settings: dict[str, Any]) -> dict[str, Any]:
    entity_ids = sorted(_collect_entity_ids(settings))
    missing = [entity_id for entity_id in entity_ids if hass.states.get(entity_id) is None]
    locked_controls: list[str] = []

    equipment = settings.get("entities", {}).get("equipment", {})
    if isinstance(equipment, dict):
        for config in equipment.values():
            if not isinstance(config, dict):
                continue
            switch_entity = _normalise_entity_id(config.get("switch"))
            if switch_entity and not config.get("controlEnabled", False):
                locked_controls.append(switch_entity)

    return {
        "entity_count": len(entity_ids),
        "missing_entities": missing,
        "locked_controls": sorted(locked_controls),
    }


async def _async_refresh_issues(
    hass: HomeAssistant, entry: OpenReefConfigEntry | None
) -> None:
    settings = _settings_from_entry(entry)
    validation = _validate_settings(hass, settings)

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


async def _async_update_settings(
    hass: HomeAssistant, entry: OpenReefConfigEntry, settings: dict[str, Any]
) -> None:
    options = dict(entry.options)
    options[CONF_SETTINGS] = settings
    hass.config_entries.async_update_entry(entry, options=options)
    await _async_refresh_issues(hass, entry)


def _equipment_for_mode(settings: dict[str, Any], mode_id: str) -> dict[str, str]:
    for mode in settings.get("modes", []):
        if isinstance(mode, dict) and mode.get("id") == mode_id:
            config = mode.get("equipmentConfig", {})
            return config if isinstance(config, dict) else {}
    raise ServiceValidationError(f"OpenReef mode '{mode_id}' does not exist")


async def _handle_apply_mode(hass: HomeAssistant, call: ServiceCall) -> None:
    entry = _first_entry(hass)
    if entry is None:
        raise HomeAssistantError("OpenReef is not configured")

    settings = _settings_from_entry(entry)
    mode_id = call.data["mode_id"]
    equipment_config = _equipment_for_mode(settings, mode_id)
    equipment = settings.get("entities", {}).get("equipment", {})

    if not isinstance(equipment, dict):
        raise ServiceValidationError("OpenReef equipment mapping is invalid")

    applied = 0
    skipped_locked: list[str] = []

    for equipment_key, desired_state in equipment_config.items():
        if desired_state not in {"on", "off"}:
            continue

        config = equipment.get(equipment_key)
        if not isinstance(config, dict):
            continue

        switch_entity = _normalise_entity_id(config.get("switch"))
        if not switch_entity:
            continue

        if not config.get("controlEnabled", False):
            skipped_locked.append(switch_entity)
            continue

        await hass.services.async_call(
            "switch",
            f"turn_{desired_state}",
            {ATTR_ENTITY_ID: switch_entity},
            blocking=True,
            context=call.context,
        )
        applied += 1

    if applied == 0 and skipped_locked:
        raise ServiceValidationError(
            "OpenReef mode matched equipment, but all mapped controls are locked"
        )


async def _handle_record_manual_reading(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    entry = _first_entry(hass)
    if entry is None:
        raise HomeAssistantError("OpenReef is not configured")

    settings = _settings_from_entry(entry)
    readings = settings.setdefault("manualReadings", {})
    if not isinstance(readings, dict):
        readings = {}
        settings["manualReadings"] = readings

    parameter = call.data["parameter"]
    date = call.data.get("date") or datetime.now(timezone.utc).date().isoformat()
    readings.setdefault(parameter, []).append({"date": date, "value": call.data["value"]})

    await _async_update_settings(hass, entry, settings)


@websocket_api.websocket_command({vol.Required("type"): "openreef/get_config"})
@callback
def websocket_get_config(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the current OpenReef configuration."""
    entry = _first_entry(hass)
    connection.send_result(
        msg["id"],
        {
            "configured": entry is not None,
            "settings": _settings_from_entry(entry),
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
async def websocket_update_config(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Persist OpenReef configuration from the add-on UI."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return

    await _async_update_settings(hass, entry, msg["settings"])
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command({vol.Required("type"): "openreef/validate_mappings"})
@websocket_api.async_response
async def websocket_validate_mappings(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Validate OpenReef mapped entities against the HA state registry."""
    entry = _first_entry(hass)
    validation = _validate_settings(hass, _settings_from_entry(entry))
    connection.send_result(msg["id"], validation)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up OpenReef services and websocket commands."""
    websocket_api.async_register_command(hass, websocket_get_config)
    websocket_api.async_register_command(hass, websocket_update_config)
    websocket_api.async_register_command(hass, websocket_validate_mappings)

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

    return True


async def async_setup_entry(hass: HomeAssistant, entry: OpenReefConfigEntry) -> bool:
    """Set up OpenReef from a config entry."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await _async_refresh_issues(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OpenReefConfigEntry) -> bool:
    """Unload an OpenReef config entry."""
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    ir.async_delete_issue(hass, DOMAIN, ISSUE_MISSING_ENTITIES)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: OpenReefConfigEntry) -> None:
    """Reload an OpenReef config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
