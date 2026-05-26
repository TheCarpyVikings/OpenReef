"""Diagnostics for OpenReef."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.redact import async_redact_data

from .const import CONF_SETTINGS

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
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "has_settings": CONF_SETTINGS in entry.options,
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for an OpenReef device."""
    return await async_get_config_entry_diagnostics(hass, entry)
