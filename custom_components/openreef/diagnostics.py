"""Diagnostics for OpenReef."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.redact import async_redact_data

from .const import CONF_SETTINGS, INTEGRATION_VERSION

TO_REDACT = {
    "haToken",
    "openaiApiKey",
    "geminiApiKey",
    "simliApiKey",
    "google_client_secret",
    "google_client_id",
    "refresh_token",
    "access_token",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for an OpenReef config entry."""
    settings = entry.options.get(CONF_SETTINGS, {})
    mapped_entities = 0
    armed_equipment = 0
    if isinstance(settings, dict):
        for sensor in settings.get("sensors", {}).values():
            if isinstance(sensor, dict) and sensor.get("entity_id"):
                mapped_entities += 1
        for equipment in settings.get("equipment", {}).values():
            if not isinstance(equipment, dict):
                continue
            mapped_entities += len(
                [
                    value
                    for value in [
                        equipment.get("switch_entity_id"),
                        equipment.get("power_entity_id"),
                        equipment.get("energy_entity_id"),
                        equipment.get("cost_entity_id"),
                    ]
                    if value
                ]
            )
            if equipment.get("armed"):
                armed_equipment += 1

    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "has_settings": CONF_SETTINGS in entry.options,
        "integration_version": INTEGRATION_VERSION,
        "schema_version": settings.get("schemaVersion") if isinstance(settings, dict) else None,
        "mapped_entities": mapped_entities,
        "armed_equipment": armed_equipment,
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for an OpenReef device."""
    return await async_get_config_entry_diagnostics(hass, entry)
