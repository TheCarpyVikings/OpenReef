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
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
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

SEARCH_LIMIT = 10
RUNTIME_ENTITY_LIMIT = 100
UNAVAILABLE_STATES = {"unknown", "unavailable"}


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


def _normalise_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(
        "".join(char.lower() if char.isalnum() else " " for char in value).split()
    )


def _normalise_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


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
        score += points if (
            _has_token(haystack, term) if len(_normalise_text(term)) <= 3 else _has_phrase(haystack, term)
        ) else 0
    return score


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
    attributes = state.attributes if state else {}
    name = (
        getattr(registry_entry, "name", None)
        or getattr(registry_entry, "original_name", None)
        or attributes.get("friendly_name")
        or entity_id
    )
    device_class = getattr(registry_entry, "device_class", None) or attributes.get("device_class")
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
    if _has_phrase(haystack, "reef") or _has_phrase(haystack, "tank") or _has_phrase(haystack, "aquarium"):
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

    # Some entities may not have a registry entry. This loop stays in-process and
    # returns only bounded summaries; it never serializes the full state machine.
    for state in hass.states.async_all():
        if state.entity_id in candidates:
            continue
        candidate = _entity_search_candidate(hass, area_registry, state.entity_id, None, target)
        if candidate is not None:
            candidates[state.entity_id] = candidate

    return sorted(
        candidates.values(),
        key=lambda candidate: (-candidate["score"], candidate["entity_id"]),
    )[:limit]


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


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/get_runtime_state",
        vol.Optional("entity_ids"): vol.All(cv.ensure_list, [cv.entity_id]),
    }
)
@callback
def websocket_get_runtime_state(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return minimal runtime state for configured or explicitly requested entities."""
    if "entity_ids" in msg:
        entity_ids = msg["entity_ids"]
    else:
        entity_ids = sorted(_collect_entity_ids(_settings_from_entry(_first_entry(hass))))

    entity_ids = list(dict.fromkeys(entity_ids))[:RUNTIME_ENTITY_LIMIT]
    connection.send_result(
        msg["id"],
        {
            "states": [_runtime_state_for_entity(hass, entity_id) for entity_id in entity_ids],
            "entity_count": len(entity_ids),
        },
    )


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

    settings = _settings_from_entry(entry)
    equipment = settings.get("entities", {}).get("equipment", {})
    if not isinstance(equipment, dict):
        connection.send_error(msg["id"], "invalid_config", "OpenReef equipment mapping is invalid")
        return

    equipment_id = msg["equipment_id"]
    config = equipment.get(equipment_id)
    if not isinstance(config, dict):
        connection.send_error(msg["id"], "not_mapped", "Equipment is not mapped in OpenReef")
        return

    switch_entity = _normalise_entity_id(config.get("switch"))
    if not switch_entity or _domain(switch_entity) != "switch":
        connection.send_error(msg["id"], "invalid_entity", "Equipment must map to a switch entity")
        return

    if not config.get("controlEnabled", False):
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
    websocket_api.async_register_command(hass, websocket_search_entities)
    websocket_api.async_register_command(hass, websocket_get_runtime_state)
    websocket_api.async_register_command(hass, websocket_toggle_equipment)
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
