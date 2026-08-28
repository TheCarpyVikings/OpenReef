"""OpenReef Home Assistant native controller integration."""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import math
import re
import uuid
from collections.abc import Iterable
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
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
    CORAL_COLOURS,
    CORAL_SCAPES,
    CORAL_SPECIES,
    AWC_AMOUNT_UNITS,
    AWC_DEFAULT_DRIFT_WARN_PCT,
    AWC_DEFAULT_HOLDOFF_MINUTES,
    AWC_DEFAULT_MAX_INSTANT_IMBALANCE_L,
    AWC_DEFAULT_MAX_SINGLE_CHANGE_PCT,
    AWC_DEFAULT_NET_IMBALANCE_L,
    AWC_BLOCKED_SLOT_EXPIRY_HOURS,
    AWC_EXCHANGE_TICK_SECONDS,
    AWC_LIVE_METHODS,
    AWC_DEFAULT_RUNTIME_MARGIN,
    AWC_HISTORY_MAX,
    AWC_HOLDOFF_MAX_MINUTES,
    AWC_METHODS,
    AWC_PERIODS,
    AWC_PUMP_MAX_ML_PER_S,
    AWC_PUMP_ROLES,
    AWC_RESERVOIR_KINDS,
    AWC_RESERVOIR_MAX_L,
    AWC_RUNTIME_CEILING_SECONDS,
    AWC_RUNTIME_FLOOR_SECONDS,
    AWC_SPINUP_MAX_ML,
    AWC_SPINUP_MAX_SECONDS,
    AWC_SPINUP_MIN_CAP_ML,
    AWC_STATUSES,
    AWC_TANK_MAX_L,
    AWC_TICK_DEFAULT_SECONDS,
    AWC_TICK_MAX_SECONDS,
    AWC_TICK_MIN_SECONDS,
    CONF_GUARDIAN_KEYS,
    CONF_SETTINGS,
    GUARDIAN_MAX_AUDIO_B64,
    GUARDIAN_MAX_TOKENS,
    GUARDIAN_MAX_TOOL_ROUNDS,
    GUARDIAN_MODEL,
    GUARDIAN_STT_MODEL,
    GUARDIAN_TTS_MODEL,
    DEFAULT_CORE_CONFIG,
    DEFAULT_TANK_PROFILE,
    CORE_SCHEMA_VERSION,
    DOMAIN,
    DOSING_BRUSHED_BINDING_ROLES,
    DOSING_LIVEFOOD_SHELF_LIFE_DAYS,
    DOSING_PARAMETERS,
    ISSUE_ARMED_UNAVAILABLE,
    ISSUE_LEGACY_LABS_CONFIG,
    ISSUE_MISSING_ENTITIES,
    INTEGRATION_VERSION,
    MAINTENANCE_AWC_TASK_ID,
    MAINTENANCE_COMPLETIONS_MAX,
    MAINTENANCE_HAND_FEED_TASK_ID,
    MAINTENANCE_HATCH_HARVEST_TASK_ID,
    MAINTENANCE_HATCH_START_TASK_ID,
    MAINTENANCE_REMINDER_DEFAULT_TIME,
    MAINTENANCE_SOURCE_AWC,
    MAINTENANCE_SOURCE_HATCHERY,
    MAINTENANCE_TASK_CADENCE_HOURS_MAX,
    MAINTENANCE_TASK_CADENCE_MAX,
    MAINTENANCE_TASK_CADENCE_MIN,
    MAINTENANCE_TASK_CRITICAL_HOURS_MAX,
    MAINTENANCE_TASK_CRITICAL_MAX,
    MAINTENANCE_TASK_DEFAULTS,
    MODE_EQUIPMENT_TIMER_MAX_SECONDS,
    MODE_EQUIPMENT_CYCLE_MIN_SECONDS,
    MODE_VERIFY_DEFAULT_DELAY_SECONDS,
    EQUIPMENT_MAX_OFF_MAX_SECONDS,
    ICP_REPORTS_MAX,
    MANUAL_TEST_CADENCE_PRESETS,
    MANUAL_TEST_PARAMETERS,
    MAINTENANCE_MIXING_RETEST_TASK_ID,
    MAINTENANCE_SOURCE_MIXING,
    MIXING_BATCH_TYPES,
    MIXING_CAL_CAP_MIN,
    MIXING_CAL_MIN_SECONDS,
    MIXING_CIRCULATE_EVERY_MAX_H,
    MIXING_CIRCULATE_FOR_MAX_MIN,
    MIXING_DRAW_DESTINATIONS,
    MIXING_FILL_CAP_DEFAULT_MIN,
    MIXING_FILTER_RATED_MAX_L,
    MIXING_LITRES_PROCESSED_MAX,
    MIXING_FILL_CAP_MAX_MIN,
    MIXING_HEAT_TARGET_MAX_C,
    MIXING_HEAT_TARGET_MIN_C,
    MIXING_LAYOUTS,
    MIXING_MIX_HOURS_MAX,
    MIXING_RETEST_MAX_DAYS,
    MIXING_RODI_RATE_MAX_LPH,
    MIXING_STATUSES,
    MIXING_SWITCH_ROLES,
    MIXING_TARGET_PPT_MAX,
    MIXING_TARGET_PPT_MIN,
    MIXING_VESSEL_MAX_L,
    MVP_SENSORS,
    NAME,
    PANEL_ICON,
    PANEL_STATIC_URL,
    PANEL_URL,
    REEF_PRESETS,
    SPAWNING_DEFAULT_SOLAR_NOON_HOUR,
    SPAWNING_OFFSET_MONTHS_MAX,
    SPAWNING_RUNTIME,
    SPAWNING_TARGET_TEMP_ENTITY,
    SPAWNING_TEMP_DRIFT_ALERT_C,
    SPAWNING_TEMP_PLAUSIBLE_MAX_C,
    SPAWNING_TEMP_PLAUSIBLE_MIN_C,
    SPAWNING_TEMP_STALE_MINUTES,
    SPAWNING_TEMP_TOLERANCE_C,
    SPAWNING_TICK_SECONDS,
    SPAWNING_TICK_UNSUB,
    LIGHTING_SCHEDULE_DEFAULT_GRACE_MIN,
    LIGHTING_SCHEDULE_GRACE_MAX,
    LIGHTING_OFFSET_HOURS_MAX,
    SERVICE_APPLY_MODE,
    SERVICE_ACKNOWLEDGE_ALERT,
    SERVICE_ARM_EQUIPMENT,
    SERVICE_DISARM_EQUIPMENT,
    SERVICE_HEARTBEAT,
    SERVICE_REFRESH_TRUST_CHECK,
    FEEDS_SUBDIR,
    FEEDWATCH_DEFAULT_CADENCE,
    FEEDWATCH_DEFAULT_RETENTION,
    FEEDWATCH_MAX_CADENCE,
    FEEDWATCH_MAX_MINUTES,
    FEEDWATCH_MAX_RETENTION,
    FEEDWATCH_MIN_CADENCE,
    SERVICE_RECORD_MANUAL_READING,
    SERVICE_RECORD_TASK_COMPLETION,
    SERVICE_TEST_NOTIFICATION,
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
    salinity_sg_to_ppt,
    salinity_value_looks_like_sg,
)
from . import awc as awc_engine
from . import beta as beta_feedback  # BETA-FEEDBACK: remove after beta (see docs/beta-feedback.md)
from . import dosing as dosing_engine
from . import guardian as guardian_engine
from . import icp
from . import mixing as mixing_engine
from . import nps as nps_engine
from . import spawning
from . import vision
from .const import (
    CONSUMABLE_BOTTLE_MAX_ML,
    CONSUMABLE_CATEGORIES,
    CONSUMABLE_HISTORY_MAX,
    CONSUMABLES_MAX_PRODUCTS,
    DOSING_BINDING_ROLES,
    DOSING_CAL_HISTORY_MAX,
    DOSING_CHANNEL_CHEMICALS,
    DOSING_CHANNEL_MODES,
    DOSING_DAILY_LOG_MAX,
    DOSING_DRIVER_TYPES,
    DOSING_EVENTS_MAX,
    DOSING_FLUSH_INTERVAL_S,
    DOSING_HA_MAX_DOSE_RUN_S,
    DOSING_HA_TIMED_BINDING_ROLES,
    DOSING_MANUAL_PRIME_MAX_S,
    DOSING_MAX_CHANNELS,
    DOSING_MAX_PER_DOSE_ML,
    DOSING_MIRROR_UNSUB,
    DOSING_ML_PER_DAY_MAX,
    DOSING_PH_MIRROR_ENTITY,
    DOSING_RECAL_NAG_DAYS,
    DOSING_RESERVOIR_MAX_ML,
    DOSING_ROLLOVER_ANOMALY_MINUTES,
    DOSING_RUNTIME,
    DOSING_SUSPEND_MAX_HOURS,
    DOSING_SYNC_STATES,
    DOSING_SYNC_VERIFY_DELAY_S,
    DOSING_TICK_SECONDS,
    DOSING_TICK_UNSUB,
    DOSING_TUBE_LIFE_HOURS_DEFAULT,
    DOSING_VERIFY_UNSUB,
    VISION_ARM_TASK,
    VISION_DEFAULT_FEED_WINDOW,
    VISION_FINGERPRINT,
    VISION_FLUSH_INTERVAL_S,
    VISION_MAX_FEED_WINDOW,
    VISION_MAX_MISSING_HOURS,
    VISION_MAX_REPORTS,
    VISION_MAX_SPECIES,
    VISION_MAX_ZONES,
    VISION_MIN_FEED_WINDOW,
    VISION_NOTIFY_COOLDOWN_S,
    VISION_RUNTIME,
    VISION_STATE_UNSUB,
    VISION_SURFACE_SECONDS,
    VISION_TICK_MINUTES,
    VISION_TICK_UNSUB,
    VISION_UNSUB,
)

type OpenReefConfigEntry = ConfigEntry

_LOGGER = logging.getLogger(__name__)


SEARCH_LIMIT = 10
UNAVAILABLE_STATES = {"unknown", "unavailable"}
BUILT_IN_MODES = {"running", "feed", "maintenance"}
WEEK_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
MODE_TIMER_UNSUB = "mode_timer_unsub"
MODE_SCHEDULE_UNSUB = "mode_schedule_unsub"
CONFIG_UPDATED_EVENT = f"{DOMAIN}_config_updated"
ATO_DUTY_CYCLE_UNSUB = "ato_duty_cycle_unsub"
ATO_DUTY_CYCLE_OFF_UNSUB = "ato_duty_cycle_off_unsub"
ATO_DUTY_CYCLE_LAST = "ato_duty_cycle_last"
DELAYED_EQUIPMENT_UNSUBS = "delayed_equipment_unsubs"
# Mode Actions V2 registries. EQUIPMENT_TIMER_UNSUBS / MAX_OFF_UNSUBS are dict
# registries keyed f"{entry_id}:{equipment_id}" (mirroring DELAYED_EQUIPMENT_UNSUBS);
# MODE_VERIFY_UNSUB is a single one-shot read-back unsub like MODE_TIMER_UNSUB.
EQUIPMENT_TIMER_UNSUBS = "equipment_timer_unsubs"
MAX_OFF_UNSUBS = "max_off_unsubs"
MODE_VERIFY_UNSUB = "mode_verify_unsub"
WAVEMAKER_REMINDER_UNSUB = "wavemaker_reminder_unsub"
WAVEMAKER_REMINDER_LAST = "wavemaker_reminder_last"
MAINTENANCE_REMINDER_UNSUB = "maintenance_reminder_unsub"
MAINTENANCE_REMINDER_LAST = "maintenance_reminder_last"
WATCHDOG_UNSUB = "watchdog_unsub"
# Boot-time repairs race: mapped entities and armed equipment routinely read
# missing/unavailable while HA is still starting other integrations (ESPHome
# nodes connect AFTER their integration sets up). Judging them during boot
# raised the "missing mapped entities" / "armed equipment unavailable" repairs
# on EVERY restart/update — alarming and always self-clearing. The first
# evaluation is deferred to STARTED + a grace window instead.
ISSUE_REFRESH_UNSUB = "issue_refresh_unsub"
ISSUE_BOOT_GRACE_SECONDS = 60
CAPTURES_PATH_REGISTERED = "captures_path_registered"
CAPTURE_LAST = "capture_last"
CAPTURE_INFLIGHT = "capture_inflight"
CAMERA_IO_INFLIGHT = "camera_io_inflight"
TIMELAPSE_UNSUB = "timelapse_unsub"
TIMELAPSE_LAST = "timelapse_last"
FEEDWATCH_UNSUB = "feedwatch_unsub"
FEEDWATCH_SESSION = "feedwatch_session"
# Automatic Water Change: AWC_UNSUB is the single in-flight leg/tick timer (re-armed
# each leg, like MODE_TIMER_UNSUB); AWC_ATO_RESTORE_UNSUB is the post-change ATO
# stabilization hold-off; AWC_SCHEDULE_UNSUB is the periodic scheduled-change tick.
AWC_UNSUB = "awc_unsub"
AWC_ATO_RESTORE_UNSUB = "awc_ato_restore_unsub"
AWC_SCHEDULE_UNSUB = "awc_schedule_unsub"
# Serialises every AWC run-state transition (start / leg-complete / exchange-tick /
# relaunch / user abort / acknowledge). The leg timer, the ~minute scheduler, and the
# websocket handlers can otherwise interleave across their awaits — double-starting a
# change or double-debiting the reservoirs. Inner helpers (abort/pause/finalize) stay
# UNLOCKED and must only be called by a lock-holding entry point (asyncio.Lock is not
# re-entrant). This lock is also the foundation the N-source orchestration builds on.
AWC_STATE_LOCK = "awc_state_lock"
# Non-persistent runtime (cooldown stamps for the advisory notification tier and the
# demo mode's virtual pump states) — mirrors DOSING_RUNTIME; resetting on restart
# just means at most one re-notify / a fresh sim sandbox.
AWC_RUNTIME = "awc_runtime"
AWC_CALRUN_UNSUB = "awc_calrun_unsub"  # timed calibration-run stop timer
NPS_DRAIN_UNSUB = "nps_drain_unsub"    # feed-exchange matched-drain stop timer
# Mixing station: serialises batch-state transitions the same way AWC_STATE_LOCK
# does for water changes (start / advance / cap-fire / abort can interleave).
MIXING_STATE_LOCK = "mixing_state_lock"
MIXING_FILL_UNSUB = "mixing_fill_unsub"  # booster fill-cap stop timer
MIXING_CIRC_UNSUB = "mixing_circ_unsub"  # storing-circulation chain (start OR stop leg)
MIXING_RODI_UNSUB = "mixing_rodi_unsub"  # RODI draw stop leg OR calibration cap (mutually exclusive)
MIXING_RUNTIME = "mixing_runtime"        # sim switch states (mirrors AWC_RUNTIME)
_AWC_SIM_HAZARDS = ("leak", "highLevel", "freshEmpty", "wasteFull", "returnPumpIssue")
# Bulky runtime record lists stripped from a settings export (and preserved through
# an import) — they describe the tank's past, not its configuration.
_EXPORT_STRIP_KEYS = ("captures", "feedSessions", "visionReports", "activity")
# Maps an OpenReef event type -> the user-configurable trigger toggle that gates it.
CAPTURE_TRIGGER_FIELD = {
    "critical_alert": "criticalAlerts",
    "warning_alert": "warningAlerts",
    "mode_change": "modeChanges",
    "skimmer_auto_off": "skimmerAutoOff",
    "ato_window": "atoWindows",
    "feed_mode": "feedMode",
    "nps_feed_exchange": "npsFeedExchange",
    "spawn_window_night": "spawnWindowNight",
}
EQUIPMENT_PROFILE_TYPES = {
    "return_pump",
    "display_wavemaker",
    "flow_pump",
    "air_pump",
    "heater",
    "skimmer",
    "ato",
    "lighting",
    "doser",
    "filtration",
    "uv",
    "ozone",
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

RECORD_TASK_COMPLETION_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Optional("notes"): cv.string,
        vol.Optional("date"): cv.string,
        vol.Optional("volume"): vol.Coerce(float),
        vol.Optional("volume_unit"): cv.string,
    }
)

ACKNOWLEDGE_ALERT_SCHEMA = vol.Schema({vol.Required("sensor_id"): cv.string})

TEST_NOTIFICATION_SCHEMA = vol.Schema({vol.Optional("message"): cv.string})

EMPTY_SERVICE_SCHEMA = vol.Schema({})


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
        "air": "air_pump",
        "airpump": "air_pump",
        "air_pump": "air_pump",
        "aerator": "air_pump",
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
        "uv": "uv",
        "uv_sterilizer": "uv",
        "steriliser": "uv",
        "sterilizer": "uv",
        "ozone": "ozone",
        "ozonizer": "ozone",
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
    if any(term in text for term in ("air pump", "airpump", "aerator")):
        return "air_pump"
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
    core["icpReports"] = (
        settings.get("icpReports") if isinstance(settings.get("icpReports"), list) else []
    )
    core["icpTemplates"] = (
        settings.get("icpTemplates") if isinstance(settings.get("icpTemplates"), list) else []
    )
    core["icpDashboard"] = (
        settings.get("icpDashboard") if isinstance(settings.get("icpDashboard"), dict) else {}
    )
    core["display"]["setupComplete"] = any(
        sensor.get("entity_id") for sensor in core["sensors"].values()
    )
    return core


_AWC_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _awc_str(value: Any, maxlen: int) -> str:
    """Preserve free text / ISO timestamps (unlike _normalise_text, which slugs)."""
    if value is None:
        return ""
    return str(value).strip()[:maxlen]


def _awc_num(value: Any, default: float, lo: float, hi: float | None = None) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        out = float(default)
    if out != out or out in (float("inf"), float("-inf")):
        out = float(default)
    out = max(lo, out)
    if hi is not None:
        out = min(out, hi)
    return float(out)  # max/min can return an int bound; keep the type stable


def _normalise_dosing_channels(dosing: dict[str, Any]) -> None:
    """Clamp/validate ``dosing.channels`` in place (the multi-pump dosing feature).

    Channels are user-created (dynamic like ``equipment``), so the whole per-channel
    schema lives here rather than in DEFAULT_CORE_CONFIG. Two invariants matter for
    safety: ``phResumeBelow`` always sits under ``phPauseAbove`` (the hysteresis pair
    that makes "dose until pH = X" unbuildable), and no reservoir/volume ceiling can
    ever *disable* a channel — clamps warn upstream, never silently degrade."""
    raw_channels = dosing.get("channels")
    raw_channels = raw_channels if isinstance(raw_channels, dict) else {}
    channels: dict[str, dict[str, Any]] = {}
    for channel_id in list(raw_channels)[:DOSING_MAX_CHANNELS]:
        raw = raw_channels.get(channel_id)
        if not isinstance(raw, dict):
            continue
        cid = str(channel_id)[:40]
        if not cid:
            continue

        raw_driver = raw.get("driver") if isinstance(raw.get("driver"), dict) else {}
        raw_entities = raw_driver.get("entities") if isinstance(raw_driver.get("entities"), dict) else {}
        driver_type = raw_driver.get("type")
        _all_roles = tuple(dict.fromkeys(
            DOSING_BINDING_ROLES + DOSING_BRUSHED_BINDING_ROLES + DOSING_HA_TIMED_BINDING_ROLES))
        entities = {role: _normalise_entity_id(raw_entities.get(role)) for role in _all_roles}

        raw_schedule = raw.get("schedule") if isinstance(raw.get("schedule"), dict) else {}
        raw_night = raw_schedule.get("night") if isinstance(raw_schedule.get("night"), dict) else {}
        raw_guards = raw.get("guards") if isinstance(raw.get("guards"), dict) else {}
        raw_reservoir = raw.get("reservoir") if isinstance(raw.get("reservoir"), dict) else {}
        raw_cal = raw.get("calibration") if isinstance(raw.get("calibration"), dict) else {}
        raw_wear = raw.get("wear") if isinstance(raw.get("wear"), dict) else {}
        raw_ramp = raw.get("ramp") if isinstance(raw.get("ramp"), dict) else {}
        raw_sync = raw.get("sync") if isinstance(raw.get("sync"), dict) else {}
        raw_state = raw.get("state") if isinstance(raw.get("state"), dict) else {}

        ph_pause = _awc_num(raw_guards.get("phPauseAbove"), 8.45, 0.0, 9.5)
        ph_resume = _awc_num(raw_guards.get("phResumeBelow"), 8.30, 0.0, 9.5)
        if ph_pause > 0:
            ph_resume = min(ph_resume, round(ph_pause - 0.05, 2))
        volume_ml = _awc_num(raw_reservoir.get("volumeMl"), 0, 0, DOSING_RESERVOIR_MAX_ML)

        history = []
        for item in (raw_cal.get("history") if isinstance(raw_cal.get("history"), list) else [])[:DOSING_CAL_HISTORY_MAX]:
            if isinstance(item, dict):
                history.append({
                    "stepsPerMl": _awc_num(item.get("stepsPerMl"), 0, 0, 1e6),
                    "mlPerS": _awc_num(item.get("mlPerS"), 0, 0, 200),
                    "measuredMl": _awc_num(item.get("measuredMl"), 0, 0, 1000),
                    "calibratedAt": _awc_str(item.get("calibratedAt"), 40),
                })
        checkpoints = []
        for item in (raw_ramp.get("checkpoints") if isinstance(raw_ramp.get("checkpoints"), list) else [])[:20]:
            if isinstance(item, dict):
                checkpoints.append({
                    "at": _awc_str(item.get("at"), 40),
                    "testedValue": _awc_num(item.get("testedValue"), 0, 0, 1e6),
                })
        respread = raw_state.get("respread") if isinstance(raw_state.get("respread"), dict) else {}
        pending = raw_sync.get("pendingWrites") if isinstance(raw_sync.get("pendingWrites"), dict) else {}

        channels[cid] = {
            "name": _awc_str(raw.get("name"), 60) or cid,
            "chemical": raw.get("chemical") if raw.get("chemical") in DOSING_CHANNEL_CHEMICALS else "other",
            "enabled": bool(raw.get("enabled")),
            "createdAt": _awc_str(raw.get("createdAt"), 40),
            # Post-dose fresh-chaser seconds (brushed live-food heads): firmware runs
            # the rinse; HA debits the AWC fresh reservoir for it. 0 = no chaser.
            "chaserSeconds": _awc_num(raw.get("chaserSeconds"), 0, 0, 120),
            "driver": {
                "type": driver_type if driver_type in DOSING_DRIVER_TYPES else DOSING_DRIVER_TYPES[0],
                "version": int(_awc_num(raw_driver.get("version"), 1, 1, 99)),
                "entities": entities,
            },
            "schedule": {
                "enabled": bool(raw_schedule.get("enabled")),
                "mlPerDay": _awc_num(raw_schedule.get("mlPerDay"), 0, 0, DOSING_ML_PER_DAY_MAX),
                "mode": raw_schedule.get("mode") if raw_schedule.get("mode") in DOSING_CHANNEL_MODES else "continuous",
                "dosesPerDay": int(_awc_num(raw_schedule.get("dosesPerDay"), 8, 1, 96)),
                "windowStart": _normalise_schedule_time(raw_schedule.get("windowStart")) or "00:00",
                "windowEnd": _normalise_schedule_time(raw_schedule.get("windowEnd")) or "00:00",
                "night": {
                    "enabled": bool(raw_night.get("enabled")),
                    "percent": _awc_num(raw_night.get("percent"), 50, 0, 90),
                    "useLightingSchedule": bool(raw_night.get("useLightingSchedule", True)),
                    "windowStart": _normalise_schedule_time(raw_night.get("windowStart")) or "22:00",
                    "windowEnd": _normalise_schedule_time(raw_night.get("windowEnd")) or "08:00",
                },
            },
            "guards": {
                "phEntity": _normalise_entity_id(raw_guards.get("phEntity")),
                "phPauseAbove": ph_pause,
                "phResumeBelow": ph_resume,
                "phMissingAcknowledged": bool(raw_guards.get("phMissingAcknowledged")),
                "suspendDuringAwc": bool(raw_guards.get("suspendDuringAwc", True)),
                "quietHoursEnabled": bool(raw_guards.get("quietHoursEnabled")),
                "quietStart": _normalise_schedule_time(raw_guards.get("quietStart")) or "01:00",
                "quietEnd": _normalise_schedule_time(raw_guards.get("quietEnd")) or "05:00",
                "maxPerDoseMl": _awc_num(raw_guards.get("maxPerDoseMl"), DOSING_MAX_PER_DOSE_ML, 0.1, DOSING_MAX_PER_DOSE_ML),
                "maxDailyMl": _awc_num(raw_guards.get("maxDailyMl"), 0, 0, DOSING_ML_PER_DAY_MAX),
                "minDoseIntervalMinutes": int(_awc_num(raw_guards.get("minDoseIntervalMinutes"), 1, 1, 240)),
                "evaporationLimitMlPerDay": _awc_num(raw_guards.get("evaporationLimitMlPerDay"), 0, 0, DOSING_ML_PER_DAY_MAX),
            },
            "reservoir": {
                "volumeMl": volume_ml,
                "remainingMl": _awc_num(raw_reservoir.get("remainingMl"), 0, 0, volume_ml or DOSING_RESERVOIR_MAX_ML),
                "lowThresholdMl": _awc_num(raw_reservoir.get("lowThresholdMl"), 500, 0, DOSING_RESERVOIR_MAX_ML),
                "refilledAt": _awc_str(raw_reservoir.get("refilledAt"), 40),
                "primedAt": _awc_str(raw_reservoir.get("primedAt"), 40),
                # Live-food freshness: when the culture was mixed/refreshed, and how
                # long it keeps (0 = never expires; livefood defaults to 1 day).
                "mixedAt": _awc_str(raw_reservoir.get("mixedAt"), 40),
                "shelfLifeDays": _awc_num(
                    raw_reservoir.get("shelfLifeDays"),
                    DOSING_LIVEFOOD_SHELF_LIFE_DAYS if raw.get("chemical") == "livefood" else 0,
                    0, 60),
                # Consumables bridge: which tracked bottle this reservoir draws
                # from, and whether the bottle IS the reservoir (pump doses then
                # debit the bottle ledger directly; otherwise 'Refilled' debits
                # the bottle by the transferred volume).
                "productId": _awc_str(raw_reservoir.get("productId"), 64),
                "productIsBottle": bool(raw_reservoir.get("productIsBottle")),
            },
            "calibration": {
                "stepsPerMl": _awc_num(raw_cal.get("stepsPerMl"), 0, 0, 1e6),
                # Brushed heads calibrate in flow terms, not steps.
                "mlPerS": _awc_num(raw_cal.get("mlPerS"), 0, 0, 200),
                "spinUpMl": _awc_num(raw_cal.get("spinUpMl"), 0, -50, 50),
                "measuredMl": _awc_num(raw_cal.get("measuredMl"), 0, 0, 1000),
                "calibratedAt": _awc_str(raw_cal.get("calibratedAt"), 40),
                "syncedToDevice": bool(raw_cal.get("syncedToDevice")),
                "history": history,
            },
            "wear": {
                "runSeconds": _awc_num(raw_wear.get("runSeconds"), 0, 0, 1e9),
                "doseCount": int(_awc_num(raw_wear.get("doseCount"), 0, 0, 1e9)),
                "tubeInstalledAt": _awc_str(raw_wear.get("tubeInstalledAt"), 40),
                "tubeLifeHours": _awc_num(raw_wear.get("tubeLifeHours"), DOSING_TUBE_LIFE_HOURS_DEFAULT, 1, 100000),
            },
            "ramp": {
                "enabled": bool(raw_ramp.get("enabled")),
                "startPercent": _awc_num(raw_ramp.get("startPercent"), 60, 10, 100),
                "stepPercent": _awc_num(raw_ramp.get("stepPercent"), 10, 1, 50),
                "maxDkhPerDay": _awc_num(raw_ramp.get("maxDkhPerDay"), 1.0, 0.1, 3.0),
                "startedAt": _awc_str(raw_ramp.get("startedAt"), 40),
                "checkpoints": checkpoints,
            },
            "sync": {
                "state": raw_sync.get("state") if raw_sync.get("state") in DOSING_SYNC_STATES else "unsynced",
                "lastSyncedAt": _awc_str(raw_sync.get("lastSyncedAt"), 40),
                "lastError": _awc_str(raw_sync.get("lastError"), 200),
                "pendingWrites": {
                    str(role): _awc_num(value, 0, -1e6, 1e6)
                    for role, value in list(pending.items())[:len(DOSING_BINDING_ROLES)]
                    if role in DOSING_BINDING_ROLES
                },
            },
            "state": {
                "lastSensorMl": _awc_num(raw_state.get("lastSensorMl"), 0, 0, 1e6),
                # ha_switch_timed run trace: persisted so a restart can stop an
                # orphaned pump and credit the elapsed volume honestly.
                "haDoseDate": _awc_str(raw_state.get("haDoseDate"), 20),
                "haDosedTodayMl": _awc_num(raw_state.get("haDosedTodayMl"), 0, 0, 1e6),
                "haRunStartedAt": _awc_str(raw_state.get("haRunStartedAt"), 40),
                "haRunEndsAt": _awc_str(raw_state.get("haRunEndsAt"), 40),
                "haRunTargetMl": _awc_num(raw_state.get("haRunTargetMl"), 0, 0, 100000),
                "lastDoseAt": _awc_str(raw_state.get("lastDoseAt"), 40),
                "lastSensorAt": _awc_str(raw_state.get("lastSensorAt"), 40),
                "missedMl": _awc_num(raw_state.get("missedMl"), 0, 0, 1e6),
                "missedSince": _awc_str(raw_state.get("missedSince"), 40),
                "suspendedUntil": _awc_str(raw_state.get("suspendedUntil"), 40),
                "phLatchedHigh": bool(raw_state.get("phLatchedHigh")),
                "rolloverAnomaly": bool(raw_state.get("rolloverAnomaly")),
                "respread": {
                    "date": _awc_str(respread.get("date"), 20),
                    "dayIntervalMin": int(_awc_num(respread.get("dayIntervalMin"), 0, 0, 240)),
                    "nightIntervalMin": int(_awc_num(respread.get("nightIntervalMin"), 0, 0, 240)),
                    "basePerDoseMl": _awc_num(respread.get("basePerDoseMl"), 0, 0, 100),
                    "baseDayIntervalMin": int(_awc_num(respread.get("baseDayIntervalMin"), 0, 0, 240)),
                    "baseNightIntervalMin": int(_awc_num(respread.get("baseNightIntervalMin"), 0, 0, 240)),
                } if respread else {},
            },
            "dailyLog": [
                item for item in (raw.get("dailyLog") if isinstance(raw.get("dailyLog"), list) else [])
                if isinstance(item, dict)
            ][:DOSING_DAILY_LOG_MAX],
            "events": [
                item for item in (raw.get("events") if isinstance(raw.get("events"), list) else [])
                if isinstance(item, dict)
            ][:DOSING_EVENTS_MAX],
        }
    dosing["channels"] = channels


def _normalise_hatchery(raw: Any, default_enabled: bool = False) -> dict[str, Any]:
    """Hatchery v2 (doc §9): vessels with per-BATCH egg/hours stamps, the brine
    dosing-container ledger, hatch history, hand-feed defaults, temp sensor.

    ``enabled`` gates the STANDALONE hatchery tab (0.7.71) — breeders run
    hatcheries with zero NPS corals. Existing configs inherit nps.enabled via
    ``default_enabled`` so nothing changes for NPS users; pass the same
    default from EVERY caller or a migration-time save flips it off.

    Migration from v1: the single ``state.hatchStartedAt`` clock becomes vessel
    ``v1``; the v1 ``state.loadedAt`` stamp becomes ``reservoir.mixedAt``."""
    raw = raw if isinstance(raw, dict) else {}
    raw_state = raw.get("state") if isinstance(raw.get("state"), dict) else {}
    egg_type = (raw.get("eggType")
                if raw.get("eggType") in nps_engine.egg_type_ids() else "standard")
    hatch_hours = _awc_num(raw.get("hatchHours"), 24, 8, 48)
    raw_vessels = raw.get("vessels") if isinstance(raw.get("vessels"), dict) else {}
    vessels: dict[str, dict[str, Any]] = {}
    for vid, raw_vessel in list(raw_vessels.items())[:nps_engine.HATCH_VESSEL_CAP]:
        if not isinstance(raw_vessel, dict):
            continue
        vessel_state = (raw_vessel.get("state")
                        if isinstance(raw_vessel.get("state"), dict) else {})
        vessels[_awc_str(vid, 24) or f"v{len(vessels) + 1}"] = {
            "name": _awc_str(raw_vessel.get("name"), 40) or f"Hatchery {len(vessels) + 1}",
            "volumeL": _awc_num(raw_vessel.get("volumeL"), 1.0, 0.1, 10),
            "state": {
                "hatchStartedAt": _awc_str(vessel_state.get("hatchStartedAt"), 40),
                # Per-batch stamps: settings changes only touch the NEXT batch.
                "eggType": (vessel_state.get("eggType")
                            if vessel_state.get("eggType") in nps_engine.egg_type_ids()
                            else egg_type),
                "hatchHours": _awc_num(vessel_state.get("hatchHours"), hatch_hours, 8, 48),
                "readyNotifiedAt": _awc_str(vessel_state.get("readyNotifiedAt"), 40),
            },
        }
    if not vessels:
        vessels["v1"] = {
            "name": "Hatchery 1", "volumeL": 1.0,
            "state": {
                "hatchStartedAt": _awc_str(raw_state.get("hatchStartedAt"), 40),
                "eggType": egg_type, "hatchHours": hatch_hours,
                "readyNotifiedAt": "",
            },
        }
    raw_reservoir = raw.get("reservoir") if isinstance(raw.get("reservoir"), dict) else {}
    volume_ml = _awc_num(raw_reservoir.get("volumeMl"), 0, 0, 50000)
    reservoir = {
        "volumeMl": volume_ml,
        "remainingMl": _awc_num(raw_reservoir.get("remainingMl"), 0, 0,
                                volume_ml if volume_ml > 0 else 50000),
        "loadVolumeMl": _awc_num(raw_reservoir.get("loadVolumeMl"), 0, 0, 50000),
        "refrigerated": bool(raw_reservoir.get("refrigerated", False)),
        "mixedAt": (_awc_str(raw_reservoir.get("mixedAt"), 40)
                    or _awc_str(raw_state.get("loadedAt"), 40)),
        # An enriched load runs a tighter freshness clock (doc §10.5). The
        # boost decays from when the SOAK finished, not from the load.
        "lastLoadEnriched": bool(raw_reservoir.get("lastLoadEnriched", False)),
        "enrichedAt": _awc_str(raw_reservoir.get("enrichedAt"), 40),
    }
    raw_enrich = raw.get("enrichment") if isinstance(raw.get("enrichment"), dict) else {}
    raw_enrich_state = (raw_enrich.get("state")
                        if isinstance(raw_enrich.get("state"), dict) else {})
    enrichment = {
        "hours": _awc_num(raw_enrich.get("hours"), nps_engine.ENRICH_DEFAULT_HOURS, 2, 36),
        "doseMl": _awc_num(raw_enrich.get("doseMl"), 1, 0.5, 50),
        # Instar I can't eat — the Selcon goes in this many hours after load
        # (the molt; ~6-12 h warm, longer on a cool bench). 0 = dose at load.
        "doseDelayH": _awc_num(raw_enrich.get("doseDelayH"),
                               nps_engine.INSTAR_II_HOURS, 0, 24),
        "productId": _awc_str(raw_enrich.get("productId"), 40),
        "splitDose": bool(raw_enrich.get("splitDose", False)),
        "state": {
            "startedAt": _awc_str(raw_enrich_state.get("startedAt"), 40),
            "sourceVesselId": _awc_str(raw_enrich_state.get("sourceVesselId"), 24),
            "eggType": _awc_str(raw_enrich_state.get("eggType"), 24),
            "plannedHatchHours": _awc_num(raw_enrich_state.get("plannedHatchHours"), 0, 0, 96),
            "actualHatchHours": _awc_num(raw_enrich_state.get("actualHatchHours"), 0, 0, 240),
            "enrichHours": _awc_num(raw_enrich_state.get("enrichHours"), 0, 0, 48),
            "doseDelayH": _awc_num(raw_enrich_state.get("doseDelayH"), 0, 0, 24),
            "batchLoadedAt": _awc_str(raw_enrich_state.get("batchLoadedAt"), 40),
            "firstDoseAt": _awc_str(raw_enrich_state.get("firstDoseAt"), 40),
            "secondDoseAt": _awc_str(raw_enrich_state.get("secondDoseAt"), 40),
            "readyNotifiedAt": _awc_str(raw_enrich_state.get("readyNotifiedAt"), 40),
            "firstDoseNotifiedAt": _awc_str(raw_enrich_state.get("firstDoseNotifiedAt"), 40),
            "secondDoseNotifiedAt": _awc_str(raw_enrich_state.get("secondDoseNotifiedAt"), 40),
        },
    }
    history: list[dict[str, Any]] = []
    raw_history = raw.get("history") if isinstance(raw.get("history"), list) else []
    for item in raw_history[:nps_engine.HATCH_HISTORY_MAX]:
        if not isinstance(item, dict):
            continue
        entry = {
            "vesselId": _awc_str(item.get("vesselId"), 24),
            "startedAt": _awc_str(item.get("startedAt"), 40),
            "harvestedAt": _awc_str(item.get("harvestedAt"), 40),
            "plannedHours": _awc_num(item.get("plannedHours"), 0, 0, 96),
            "actualHours": _awc_num(item.get("actualHours"), 0, 0, 240),
            "eggType": _awc_str(item.get("eggType"), 24),
        }
        if item.get("enriched"):
            entry["enriched"] = True
            entry["enrichedHours"] = _awc_num(item.get("enrichedHours"), 0, 0, 96)
        history.append(entry)
    raw_hand = raw.get("handFeed") if isinstance(raw.get("handFeed"), dict) else {}
    return {
        "enabled": bool(raw.get("enabled", default_enabled)),
        "eggType": egg_type,
        "hatchHours": hatch_hours,
        "vessels": vessels,
        "reservoir": reservoir,
        "enrichment": enrichment,
        "history": history,
        "handFeed": {
            "defaultDoseMl": _awc_num(raw_hand.get("defaultDoseMl"), 30, 1, 1000),
            "feedsPerDay": _awc_num(raw_hand.get("feedsPerDay"), 2, 1, 24),
        },
        "tempEntity": _awc_str(raw.get("tempEntity"), 80),
    }


def _normalise_nps_config(config: dict[str, Any]) -> None:
    """Clamp/validate the Automated NPS system gate and the system-wide
    consumables (bottle) registry in place. Products are user-created like
    dosing channels, so this owns the per-product schema; the maths live in
    nps.py."""
    nps_cfg = config.get("nps")
    nps_cfg = nps_cfg if isinstance(nps_cfg, dict) else {}
    raw_fx = nps_cfg.get("feedExchange") if isinstance(nps_cfg.get("feedExchange"), dict) else {}
    raw_fx_state = raw_fx.get("state") if isinstance(raw_fx.get("state"), dict) else {}
    raw_hatchery = nps_cfg.get("hatchery") if isinstance(nps_cfg.get("hatchery"), dict) else {}
    raw_truce = nps_cfg.get("truce") if isinstance(nps_cfg.get("truce"), dict) else {}
    raw_truce_state = raw_truce.get("state") if isinstance(raw_truce.get("state"), dict) else {}
    truce_state: dict[str, Any] = {}
    for profile in ("uv", "ozone", "skimmer"):
        raw_p = raw_truce_state.get(profile) if isinstance(raw_truce_state.get(profile), dict) else {}
        raw_off = raw_p.get("turnedOff") if isinstance(raw_p.get("turnedOff"), list) else []
        truce_state[profile] = {
            "restoreAt": _awc_str(raw_p.get("restoreAt"), 40),
            "turnedOff": [str(e)[:120] for e in raw_off if isinstance(e, str)][:20],
        }
    raw_species = nps_cfg.get("species") if isinstance(nps_cfg.get("species"), list) else []
    valid_species = set(nps_engine.species_ids())
    config["nps"] = {
        "enabled": bool(nps_cfg.get("enabled", False)),
        "species": list(dict.fromkeys(
            str(s) for s in raw_species if str(s) in valid_species)),
        # Brine feed-exchange (Stage B): dose + chaser volumes bank an owed
        # matched drain; the state block is persisted runtime (an in-flight
        # drain must survive a restart for orphan recovery to stop the pump).
        "feedExchange": {
            "enabled": bool(raw_fx.get("enabled", False)),
            "channelId": _awc_str(raw_fx.get("channelId"), 64),
            "minDrainMl": _awc_num(raw_fx.get("minDrainMl"), 150, 10, 5000),
            "maxOwedMl": _awc_num(raw_fx.get("maxOwedMl"), 2000, 100, 20000),
            "state": {
                "owedMl": _awc_num(raw_fx_state.get("owedMl"), 0, 0, 100000),
                "droppedMl": _awc_num(raw_fx_state.get("droppedMl"), 0, 0, 1e9),
                "totalDrainedL": _awc_num(raw_fx_state.get("totalDrainedL"), 0, 0, 1e9),
                "lastDrainAt": _awc_str(raw_fx_state.get("lastDrainAt"), 40),
                "lastDrainMl": _awc_num(raw_fx_state.get("lastDrainMl"), 0, 0, 100000),
                "drainStartedAt": _awc_str(raw_fx_state.get("drainStartedAt"), 40),
                "drainEndsAt": _awc_str(raw_fx_state.get("drainEndsAt"), 40),
                "drainTargetMl": _awc_num(raw_fx_state.get("drainTargetMl"), 0, 0, 100000),
                "lastBlockedReason": _awc_str(raw_fx_state.get("lastBlockedReason"), 120),
            },
        },
        # Hatchery (v2): vessels, brine ledger, history — see _normalise_hatchery.
        "hatchery": _normalise_hatchery(raw_hatchery, bool(nps_cfg.get("enabled", False))),
        # Feed truce (Stage C): plankton-hostile equipment pauses. The state
        # tracks exactly which entities the truce itself turned off — restore
        # never touches equipment the keeper had off already.
        "truce": {
            "enabled": bool(raw_truce.get("enabled", False)),
            "uvOffMinutes": _awc_num(raw_truce.get("uvOffMinutes"), 120, 5, 720),
            "ozoneOffMinutes": _awc_num(raw_truce.get("ozoneOffMinutes"), 120, 5, 720),
            "skimmerOffMinutes": _awc_num(raw_truce.get("skimmerOffMinutes"), 45, 5, 720),
            "state": truce_state,
        },
    }

    raw_block = config.get("consumables")
    raw_block = raw_block if isinstance(raw_block, dict) else {}
    raw_products = raw_block.get("products")
    raw_products = raw_products if isinstance(raw_products, dict) else {}
    products: dict[str, Any] = {}
    for pid, raw in list(raw_products.items())[:CONSUMABLES_MAX_PRODUCTS]:
        if not isinstance(raw, dict):
            continue
        pid = str(pid)[:64]
        if not pid:
            continue
        bottle_ml = _awc_num(raw.get("bottleMl"), 0, 0, CONSUMABLE_BOTTLE_MAX_ML)
        history = [
            {
                "at": _awc_str(item.get("at"), 40),
                "ml": round(_awc_num(item.get("ml"), 0, 0, CONSUMABLE_BOTTLE_MAX_ML), 2),
                "kind": item.get("kind")
                if item.get("kind") in ("dose", "pump", "transfer", "refill") else "dose",
            }
            for item in (raw.get("history") if isinstance(raw.get("history"), list) else [])
            if isinstance(item, dict)
        ][-CONSUMABLE_HISTORY_MAX:]
        products[pid] = {
            "name": _awc_str(raw.get("name"), 120) or "Product",
            "brand": _awc_str(raw.get("brand"), 120),
            "category": raw.get("category")
            if raw.get("category") in CONSUMABLE_CATEGORIES else "other",
            "bottleMl": bottle_ml,
            "remainingMl": _awc_num(
                raw.get("remainingMl"), 0, 0, bottle_ml or CONSUMABLE_BOTTLE_MAX_ML),
            "lowThresholdMl": _awc_num(raw.get("lowThresholdMl"), 0, 0, CONSUMABLE_BOTTLE_MAX_ML),
            # Opened-bottle expiry clock (0 = shelf-stable, never expires).
            "openedAt": _awc_str(raw.get("openedAt"), 40),
            "shelfLifeDaysOpened": _awc_num(raw.get("shelfLifeDaysOpened"), 0, 0, 3650),
            "refrigerated": bool(raw.get("refrigerated")),
            "stirDaily": bool(raw.get("stirDaily")),
            # Particle window for the Stage D species/particle-size matcher.
            "particleUmMin": _awc_num(raw.get("particleUmMin"), 0, 0, 100000),
            "particleUmMax": _awc_num(raw.get("particleUmMax"), 0, 0, 100000),
            "notes": _awc_str(raw.get("notes"), 400),
            "createdAt": _awc_str(raw.get("createdAt"), 40),
            "history": history,
        }
    config["consumables"] = {"products": products}


def _normalise_awc_config(config: dict[str, Any]) -> None:
    """Clamp/validate the Automatic Water Change section in place. Volume-primary AWC:
    calibration, reservoirs, layered safety, ATO coordination, run guards, the flexible
    schedule, and the persisted runtime state (so an in-flight change survives a restart)."""
    defaults = DEFAULT_CORE_CONFIG["automaticWaterChange"]
    awc_cfg = config.get("automaticWaterChange")
    if not isinstance(awc_cfg, dict):
        config["automaticWaterChange"] = deepcopy(defaults)
        return
    config["automaticWaterChange"] = awc_cfg

    awc_cfg["enabled"] = bool(awc_cfg.get("enabled", False))
    awc_cfg["tankVolumeLitres"] = round(_awc_num(awc_cfg.get("tankVolumeLitres"), 0, 0, AWC_TANK_MAX_L), 2)
    awc_cfg["continuousTickSeconds"] = int(
        _awc_num(awc_cfg.get("continuousTickSeconds"), AWC_TICK_DEFAULT_SECONDS,
                 AWC_TICK_MIN_SECONDS, AWC_TICK_MAX_SECONDS)
    )
    awc_cfg["sumpEnabled"] = bool(awc_cfg.get("sumpEnabled", False))
    awc_cfg["diagramInPulse"] = bool(awc_cfg.get("diagramInPulse", False))

    raw_pumps = awc_cfg.get("pumps") if isinstance(awc_cfg.get("pumps"), dict) else {}
    pumps: dict[str, Any] = {}
    # fill2 (second source pump, Stage B) is strictly OPT-IN: a legacy config must
    # normalise to exactly drain+fill — the role only exists once the config defines it.
    pump_roles = ["drain", "fill"]
    if isinstance(raw_pumps.get("fill2"), dict):
        pump_roles.append("fill2")
    default_reservoir = {"drain": "waste", "fill": "fresh", "fill2": "fresh2"}
    for role in pump_roles:
        raw = raw_pumps.get(role) if isinstance(raw_pumps.get(role), dict) else {}
        # exchangeFactor: a non-positive / junk value means "no correction" (1.0),
        # never a runaway multiplier.
        factor = _awc_num(raw.get("exchangeFactor"), 1.0, 0.0, 10.0)
        rid = raw.get("reservoirId")
        pumps[role] = {
            "switchEntity": _normalise_entity_id(raw.get("switchEntity")),
            "mlPerS": round(_awc_num(raw.get("mlPerS"), 0, 0, AWC_PUMP_MAX_ML_PER_S), 3),
            "interceptMl": round(_awc_num(raw.get("interceptMl"), 0, -100000, 100000), 3),
            # spinUpMl: per-dose priming/startup offset applied to the run time (bounded so a
            # bad fit can't distort runtime); primeMl: the one-time tube-fill residual, stored
            # for a future first-run-after-purge correction (inert in the run maths today).
            "spinUpMl": round(_awc_num(raw.get("spinUpMl"), 0, -AWC_SPINUP_MAX_ML, AWC_SPINUP_MAX_ML), 3),
            "primeMl": round(_awc_num(raw.get("primeMl"), 0, -100000, 100000), 3),
            "exchangeFactor": round(factor if factor > 0 else 1.0, 4),
            "calibratedAt": _awc_str(raw.get("calibratedAt"), 40),
            "tubingInstalledAt": _awc_str(raw.get("tubingInstalledAt"), 40),
            # Lifetime wear odometers (persist independently of the capped history).
            "runSeconds": round(_awc_num(raw.get("runSeconds"), 0, 0, 1e9), 1),
            "startCount": int(_awc_num(raw.get("startCount"), 0, 0, 1e9)),
            # N-source plumbing (Stage B): every pump has a direction and a reservoir.
            "direction": "out" if role == "drain" else "in",
            "reservoirId": (str(rid)
                            if rid in (("waste",) if role == "drain" else ("fresh", "fresh2"))
                            else default_reservoir[role]),
        }
    awc_cfg["pumps"] = pumps

    raw_res = awc_cfg.get("reservoirs") if isinstance(awc_cfg.get("reservoirs"), dict) else {}

    def _norm_source_reservoir(raw_src: dict[str, Any]) -> dict[str, Any]:
        """Normalise a SOURCE (fill-side) reservoir — fresh and fresh2 share one schema,
        incl. the Stage A drift fields and the Stage B source salinity (0 = unknown)."""
        return {
            "capacityLitres": round(_awc_num(raw_src.get("capacityLitres"), 25, 0, AWC_RESERVOIR_MAX_L), 2),
            "remainingMl": round(_awc_num(raw_src.get("remainingMl"), 0, 0, AWC_RESERVOIR_MAX_L * 1000), 1),
            "emptyEntity": _normalise_entity_id(raw_src.get("emptyEntity")),
            # Drift detection (Stage A): model-dispensed since the last confirmed full,
            # graded against capacity when the empty float trips / on reset-to-full.
            "dispensedSinceFullMl": round(_awc_num(raw_src.get("dispensedSinceFullMl"), 0, 0, 1e9), 1),
            "driftPct": (round(_awc_num(raw_src.get("driftPct"), 0, -1000, 1000), 1)
                         if isinstance(raw_src.get("driftPct"), (int, float)) else None),
            "driftStatus": _awc_str(raw_src.get("driftStatus"), 20),
            "driftCheckedAt": _awc_str(raw_src.get("driftCheckedAt"), 40),
            "fullConfirmedAt": _awc_str(raw_src.get("fullConfirmedAt"), 40),
            "saltPpt": round(_awc_num(raw_src.get("saltPpt"), 0, 0, 45), 1),
        }

    fresh = raw_res.get("fresh") if isinstance(raw_res.get("fresh"), dict) else {}
    waste = raw_res.get("waste") if isinstance(raw_res.get("waste"), dict) else {}
    reservoirs: dict[str, Any] = {
        "fresh": _norm_source_reservoir(fresh),
        "waste": {
            "capacityLitres": round(_awc_num(waste.get("capacityLitres"), 25, 0, AWC_RESERVOIR_MAX_L), 2),
            "filledMl": round(_awc_num(waste.get("filledMl"), 0, 0, AWC_RESERVOIR_MAX_L * 1000), 1),
            "fullEntity": _normalise_entity_id(waste.get("fullEntity")),
        },
    }
    if "fresh2" in raw_res or "fill2" in pumps:
        fresh2 = raw_res.get("fresh2") if isinstance(raw_res.get("fresh2"), dict) else {}
        reservoirs["fresh2"] = _norm_source_reservoir(fresh2)
    awc_cfg["reservoirs"] = reservoirs

    # Source policy (Stage B): which fill source a change draws WHOLLY from.
    raw_policy = awc_cfg.get("sourcePolicy") if isinstance(awc_cfg.get("sourcePolicy"), dict) else {}
    valid_fill = [r for r in ("fill", "fill2") if r in pumps]
    order = [r for r in (raw_policy.get("order") or []) if r in valid_fill]
    order += [r for r in valid_fill if r not in order]
    ratio_raw = raw_policy.get("ratio") if isinstance(raw_policy.get("ratio"), dict) else {}
    policy_mode = str(raw_policy.get("mode", "single")).lower()
    awc_cfg["sourcePolicy"] = {
        "mode": policy_mode if policy_mode in ("single", "primary", "alternate", "ratio") else "single",
        "order": order,
        "ratio": {r: round(_awc_num(ratio_raw.get(r), 1.0, 0, 1000), 2) for r in valid_fill},
        "lastSourceUsed": (str(raw_policy.get("lastSourceUsed"))
                           if raw_policy.get("lastSourceUsed") in valid_fill else ""),
    }

    raw_safety = awc_cfg.get("safety") if isinstance(awc_cfg.get("safety"), dict) else {}
    warn_mult = round(_awc_num(raw_safety.get("anomalyWarnMult"), 2.0, 1.0, 100.0), 2)
    abort_mult = round(_awc_num(raw_safety.get("anomalyAbortMult"), 3.0, 1.0, 100.0), 2)
    awc_cfg["safety"] = {
        "highLevelEntity": _normalise_entity_id(raw_safety.get("highLevelEntity")),
        "leakEntity": _normalise_entity_id(raw_safety.get("leakEntity")),
        # Running with NO leak sensor bound is informed consent, not a default
        # (pumps-only nodes ship without one — MULTINODE_PIVOT_BRIEF). The engine
        # blocks starts until this is true or a leak entity is bound.
        "floodMissingAcknowledged": bool(raw_safety.get("floodMissingAcknowledged", False)),
        "maxRuntimeSeconds": int(_awc_num(raw_safety.get("maxRuntimeSeconds"), 0, 0, AWC_RUNTIME_CEILING_SECONDS)),
        "maxRuntimeMargin": round(_awc_num(raw_safety.get("maxRuntimeMargin"), AWC_DEFAULT_RUNTIME_MARGIN, 1.0, 10.0), 2),
        "anomalyWarnMult": warn_mult,
        "anomalyAbortMult": max(abort_mult, warn_mult),  # abort can never trip before warn
        "maxSingleChangePercent": round(_awc_num(raw_safety.get("maxSingleChangePercent"), AWC_DEFAULT_MAX_SINGLE_CHANGE_PCT, 1, 100), 1),
        "driftWarnPercent": round(_awc_num(raw_safety.get("driftWarnPercent"), AWC_DEFAULT_DRIFT_WARN_PCT, 1, 100), 1),
        "netImbalanceWarnLitres": round(_awc_num(raw_safety.get("netImbalanceWarnLitres"), AWC_DEFAULT_NET_IMBALANCE_L, 0, 1000), 2),
        "autoTrimImbalance": bool(raw_safety.get("autoTrimImbalance", False)),
        "maxInstantaneousImbalanceLitres": round(_awc_num(raw_safety.get("maxInstantaneousImbalanceLitres"), AWC_DEFAULT_MAX_INSTANT_IMBALANCE_L, 0, 1000), 2),
    }

    raw_ato = awc_cfg.get("ato") if isinstance(awc_cfg.get("ato"), dict) else {}
    awc_cfg["ato"] = {
        "suspendDuringChange": bool(raw_ato.get("suspendDuringChange", True)),
        "stabilizationHoldoffMinutes": int(_awc_num(raw_ato.get("stabilizationHoldoffMinutes"), AWC_DEFAULT_HOLDOFF_MINUTES, 0, AWC_HOLDOFF_MAX_MINUTES)),
        # Changes at/under this volume skip the ATO + dosing suspends entirely and get
        # no stabilization hold-off (0 = off) — hourly 40 ml micro-changes must not
        # hold the ATO/doser around the clock.
        "microChangeThresholdMl": int(_awc_num(raw_ato.get("microChangeThresholdMl"), 0, 0, 100000)),
    }

    # Notifications home (Stage A) — one place to silence each family, mirroring the
    # dosing section. All default ON.
    raw_awc_notify = awc_cfg.get("notifications")
    raw_awc_notify = raw_awc_notify if isinstance(raw_awc_notify, dict) else {}
    awc_cfg["notifications"] = {
        key: bool(raw_awc_notify.get(key, True))
        for key in ("pausedFault", "reservoirLow", "calibrationDue", "netDrift", "driftDetected")
    }

    # Simulation / demo mode (Stage A): virtual pumps + injectable hazards; every
    # real actuation path no-ops while enabled. Default OFF, hazards clear.
    raw_sim = awc_cfg.get("simulation") if isinstance(awc_cfg.get("simulation"), dict) else {}
    raw_hazards = raw_sim.get("hazards") if isinstance(raw_sim.get("hazards"), dict) else {}
    awc_cfg["simulation"] = {
        "enabled": bool(raw_sim.get("enabled", False)),
        "hazards": {
            key: bool(raw_hazards.get(key, False)) for key in _AWC_SIM_HAZARDS
        },
        # The pre-demo accounting snapshot (reservoirs/ledger/history/wear/state),
        # restored verbatim when the demo ends — carried as-is, only ever written
        # by awc_sim_set from an already-normalised config.
        "snapshot": raw_sim.get("snapshot") if isinstance(raw_sim.get("snapshot"), dict) else None,
    }

    raw_guards = awc_cfg.get("guards") if isinstance(awc_cfg.get("guards"), dict) else {}
    awc_cfg["guards"] = {
        "quietHoursEnabled": bool(raw_guards.get("quietHoursEnabled", False)),
        "quietStart": _normalise_schedule_time(raw_guards.get("quietStart")) or "01:00",
        "quietEnd": _normalise_schedule_time(raw_guards.get("quietEnd")) or "05:00",
        "blockDuringFeed": bool(raw_guards.get("blockDuringFeed", True)),
        "blockOnReturnPumpIssue": bool(raw_guards.get("blockOnReturnPumpIssue", True)),
    }

    raw_sched = awc_cfg.get("schedule") if isinstance(awc_cfg.get("schedule"), dict) else {}
    method = str(raw_sched.get("method", "batch_sequential"))
    unit = str(raw_sched.get("amountUnit", "percent")).lower()
    period = str(raw_sched.get("period", "week")).lower()
    sched_mode = str(raw_sched.get("mode", "times")).lower()
    awc_cfg["schedule"] = {
        "enabled": bool(raw_sched.get("enabled", False)),
        # Live controller runs sequential + simultaneous; anything else (continuous) is
        # projection-only, so coerce it to the safe sequential default.
        "method": method if method in AWC_LIVE_METHODS else "batch_sequential",
        # times = explicit HH:MM slots (default); interval = every-N-minutes
        # micro-change cadence generated inside the window below.
        "mode": sched_mode if sched_mode in ("times", "interval") else "times",
        "everyMinutes": int(_awc_num(raw_sched.get("everyMinutes"), 60, 15, 1440)),
        "amountUnit": unit if unit in AWC_AMOUNT_UNITS else "percent",
        "amount": round(_awc_num(raw_sched.get("amount"), 0, 0, 100000), 2),
        "period": period if period in AWC_PERIODS else "week",
        "times": _normalise_schedule_times(raw_sched.get("times"), "02:00"),
        # Dedupe while preserving order: runs_per_week counts this list's length,
        # so a duplicated day would silently halve every per-change amount.
        "days": list(dict.fromkeys(d for d in (raw_sched.get("days") or []) if d in _AWC_WEEKDAYS)),
        "windowStart": _normalise_schedule_time(raw_sched.get("windowStart")) or "01:00",
        "windowEnd": _normalise_schedule_time(raw_sched.get("windowEnd")) or "05:00",
    }

    raw_state = awc_cfg.get("state") if isinstance(awc_cfg.get("state"), dict) else {}
    status = str(raw_state.get("status", "idle"))
    state_method = str(raw_state.get("method", ""))
    safe_state_method = state_method if state_method in AWC_LIVE_METHODS else ""
    if not safe_state_method and status in ("draining", "filling", "exchanging", "paused"):
        safe_state_method = "batch_sequential"
    # Per-role progress/stop-time migration (Stage B). An EMPTY movedMl/endsAt dict is
    # treated as absent: the defaults deep-merge `{}` into every config, so a legacy
    # blob arrives here with BOTH the empty new-shape dicts and its old scalar fields —
    # the scalars are the authoritative seed exactly once, on that upgrade pass.
    raw_moved = raw_state.get("movedMl") if isinstance(raw_state.get("movedMl"), dict) else None
    if not raw_moved:
        raw_moved = {"drain": raw_state.get("drainedMl"), "fill": raw_state.get("filledMl")}
    raw_ends = raw_state.get("endsAt") if isinstance(raw_state.get("endsAt"), dict) else None
    if not raw_ends:
        raw_ends = {"drain": raw_state.get("drainEndsAt"), "fill": raw_state.get("fillEndsAt")}
    # exchangeBaselineNetMl is SIGNED (drained − filled). One-shot upgrade edge: the
    # legacy exchangeBaselineGapMl stored |drained − filled|, so recover the sign from
    # whichever side was ahead. The default-merged net of 0 must not shadow a genuine
    # legacy gap — post-migration states never carry the gap key, so gap>0 ⇒ legacy.
    legacy_gap = _awc_num(raw_state.get("exchangeBaselineGapMl"), 0, 0, 1e9)
    net_raw = raw_state.get("exchangeBaselineNetMl")
    baseline_net = round(_awc_num(net_raw, 0, -1e9, 1e9), 1)
    if baseline_net == 0 and legacy_gap > 0:
        drained_ahead = _awc_num(raw_moved.get("drain"), 0, 0, 1e9) >= _awc_num(raw_moved.get("fill"), 0, 0, 1e9)
        baseline_net = round(legacy_gap if drained_ahead else -legacy_gap, 1)
    awc_cfg["state"] = {
        "status": status if status in AWC_STATUSES else "idle",
        "fault": _awc_str(raw_state.get("fault"), 200),
        "faultSince": _awc_str(raw_state.get("faultSince"), 40),
        "method": safe_state_method,
        "startedAt": _awc_str(raw_state.get("startedAt"), 40),
        "lastRun": _awc_str(raw_state.get("lastRun"), 40),
        "nextRun": _awc_str(raw_state.get("nextRun"), 40),
        "targetLitres": round(_awc_num(raw_state.get("targetLitres"), 0, 0, AWC_TANK_MAX_L), 3),
        "movedMl": {r: round(_awc_num(raw_moved.get(r), 0, 0, 1e9), 1) for r in pumps},
        "legStartedAt": _awc_str(raw_state.get("legStartedAt"), 40),
        "legEndsAt": _awc_str(raw_state.get("legEndsAt"), 40),
        "endsAt": {r: _awc_str(raw_ends.get(r), 40) for r in pumps},
        "activeSourceRole": (str(raw_state.get("activeSourceRole"))
                             if raw_state.get("activeSourceRole") in valid_fill else ""),
        "exchangeBaselineNetMl": baseline_net,
        "pausedReason": _awc_str(raw_state.get("pausedReason"), 200),
        "atoSuspendedUntil": _awc_str(raw_state.get("atoSuspendedUntil"), 40),
        "anomalyWarned": bool(raw_state.get("anomalyWarned", False)),
        "scheduleArmedAt": _awc_str(raw_state.get("scheduleArmedAt"), 40),
        "blockedSlotKey": _awc_str(raw_state.get("blockedSlotKey"), 40),
        "microChange": bool(raw_state.get("microChange", False)),
        # Timed calibration run in flight (the stop timer is in-memory only — this
        # persisted trace is what lets a restart stop the orphaned pump).
        "calRunRole": (str(raw_state.get("calRunRole"))
                       if raw_state.get("calRunRole") in AWC_PUMP_ROLES else ""),
        "calRunEndsAt": _awc_str(raw_state.get("calRunEndsAt"), 40),
    }
    # The running change's fill source was removed from config (the panel guards
    # this, but a stale-status save can slip through): the run cannot continue and
    # its per-role progress just lost its key. Latch a fault so the ATO/dosing
    # posture holds and the user is told to CHECK THE PUMP — the removed pump's
    # switch may still be energised and only its firmware watchdog can stop it.
    _removed_active = raw_state.get("activeSourceRole")
    if (_removed_active and _removed_active not in valid_fill
            and awc_cfg["state"]["status"] in ("draining", "filling", "exchanging", "paused")):
        awc_cfg["state"]["status"] = "fault"
        awc_cfg["state"]["fault"] = (
            "The fill source used by the running change was removed — check that "
            "its pump is physically off, then acknowledge")
        awc_cfg["state"]["faultSince"] = (
            awc_cfg["state"]["faultSince"] or datetime.now(timezone.utc).isoformat())

    raw_history = awc_cfg.get("history")
    history: list[dict[str, Any]] = []
    if isinstance(raw_history, list):
        for item in raw_history[:AWC_HISTORY_MAX]:
            if not isinstance(item, dict):
                continue
            h_method = str(item.get("method", ""))
            history.append({
                "completedAt": _awc_str(item.get("completedAt"), 40),
                "drainedL": round(_awc_num(item.get("drainedL"), 0, 0, AWC_RESERVOIR_MAX_L), 3),
                "filledL": round(_awc_num(item.get("filledL"), 0, 0, AWC_RESERVOIR_MAX_L), 3),
                "method": h_method if h_method in AWC_METHODS else "",
                "partial": bool(item.get("partial", False)),
                "notes": _awc_str(item.get("notes"), 200),
                "source": _awc_str(item.get("source"), 10),
            })
    awc_cfg["history"] = history
    awc_cfg["todayLitres"] = round(_awc_num(awc_cfg.get("todayLitres"), 0, 0, 1e6), 3)
    awc_cfg["weekLitres"] = round(_awc_num(awc_cfg.get("weekLitres"), 0, 0, 1e6), 3)
    awc_cfg["monthLitres"] = round(_awc_num(awc_cfg.get("monthLitres"), 0, 0, 1e6), 3)

    # Persistent net-imbalance ledger — decoupled from the CAPPED history above, which at
    # micro-change cadence (24/day) holds only ~4 days: the anti-salinity-drift number must
    # accumulate over the ledger's whole life (until an explicit user reset). On first
    # upgrade, seed from the summed history so the displayed net is continuous.
    raw_ledger = awc_cfg.get("ledger")
    if isinstance(raw_ledger, dict):
        per_raw = raw_ledger.get("perSource") if isinstance(raw_ledger.get("perSource"), dict) else {}
        awc_cfg["ledger"] = {
            "cumulativeDrainedL": round(_awc_num(raw_ledger.get("cumulativeDrainedL"), 0, 0, 1e9), 3),
            "cumulativeFilledL": round(_awc_num(raw_ledger.get("cumulativeFilledL"), 0, 0, 1e9), 3),
            "resetAt": _awc_str(raw_ledger.get("resetAt"), 40),
            # Per-source delivered litres (drives the 'ratio' source policy) and the
            # approximate net salt the changes have added (Stage B drift indicator).
            "perSource": {r: round(_awc_num(per_raw.get(r), 0, 0, 1e9), 3) for r in valid_fill},
            "netSaltGrams": round(_awc_num(raw_ledger.get("netSaltGrams"), 0, -1e9, 1e9), 1),
        }
    else:
        awc_cfg["ledger"] = {
            "cumulativeDrainedL": round(sum(h["drainedL"] for h in history), 3),
            "cumulativeFilledL": round(sum(h["filledL"] for h in history), 3),
            "resetAt": "",
            "perSource": {r: 0.0 for r in valid_fill},
            "netSaltGrams": 0.0,
        }


def _normalise_mixing_config(config: dict[str, Any]) -> None:
    """Clamp/validate the Saltwater Mixing Station section in place. Layout,
    vessels (volumes + the estimated-level anchor), the four switch roles,
    salt brand/target, heat, storage circulation, and the stamped batch state
    (docs/mixing-station-brainstorm.md §4). The batch block is preserved, only
    clamped — a normalise pass must never move a running batch."""
    defaults = DEFAULT_CORE_CONFIG["mixingStation"]
    mix_cfg = config.get("mixingStation")
    if not isinstance(mix_cfg, dict):
        config["mixingStation"] = deepcopy(defaults)
        return
    config["mixingStation"] = mix_cfg

    mix_cfg["enabled"] = bool(mix_cfg.get("enabled", False))
    mix_cfg["simulate"] = bool(mix_cfg.get("simulate", False))
    layout = str(mix_cfg.get("layout") or "dual")
    mix_cfg["layout"] = layout if layout in MIXING_LAYOUTS else "dual"

    raw_vessels = mix_cfg.get("vessels") if isinstance(mix_cfg.get("vessels"), dict) else {}
    raw_rodi_v = raw_vessels.get("rodi") if isinstance(raw_vessels.get("rodi"), dict) else {}
    raw_mix_v = raw_vessels.get("mix") if isinstance(raw_vessels.get("mix"), dict) else {}
    rodi_vol = round(_awc_num(raw_rodi_v.get("volumeLitres"), 50, 0, MIXING_VESSEL_MAX_L), 1)
    mix_cfg["vessels"] = {
        "rodi": {
            "volumeLitres": rodi_vol,
            # The honest anchor: moved by confirmed events, capped by the vessel.
            "estimatedLitres": round(_awc_num(
                raw_rodi_v.get("estimatedLitres"), 0, 0,
                rodi_vol if rodi_vol > 0 else MIXING_VESSEL_MAX_L), 1),
            "levelSensorEntity": _normalise_entity_id(raw_rodi_v.get("levelSensorEntity")),
        },
        "mix": {
            "volumeLitres": round(_awc_num(raw_mix_v.get("volumeLitres"), 50, 0, MIXING_VESSEL_MAX_L), 1),
            "levelSensorEntity": _normalise_entity_id(raw_mix_v.get("levelSensorEntity")),
        },
    }

    raw_switches = mix_cfg.get("switches") if isinstance(mix_cfg.get("switches"), dict) else {}
    mix_cfg["switches"] = {
        role: {"switchEntity": _normalise_entity_id(
            (raw_switches.get(role) or {}).get("switchEntity")
            if isinstance(raw_switches.get(role), dict) else None)}
        for role in MIXING_SWITCH_ROLES
    }

    raw_rodi = mix_cfg.get("rodi") if isinstance(mix_cfg.get("rodi"), dict) else {}
    raw_draw = raw_rodi.get("draw") if isinstance(raw_rodi.get("draw"), dict) else {}
    raw_cal = raw_rodi.get("calibration") if isinstance(raw_rodi.get("calibration"), dict) else {}
    draw_dest = str(raw_draw.get("destination") or "store")
    mix_cfg["rodi"] = {
        "rateLph": round(_awc_num(raw_rodi.get("rateLph"), 0, 0, MIXING_RODI_RATE_MAX_LPH), 1),
        "fillCapMin": int(_awc_num(raw_rodi.get("fillCapMin"),
                                   MIXING_FILL_CAP_DEFAULT_MIN, 1, MIXING_FILL_CAP_MAX_MIN)),
        "calibratedAt": _awc_str(raw_rodi.get("calibratedAt"), 40),
        "litresProcessed": round(_awc_num(raw_rodi.get("litresProcessed"), 0, 0,
                                          MIXING_LITRES_PROCESSED_MAX), 1),
        "filterRatedL": round(_awc_num(raw_rodi.get("filterRatedL"), 0, 0,
                                       MIXING_FILTER_RATED_MAX_L), 1),
        "filterChangedAt": _awc_str(raw_rodi.get("filterChangedAt"), 40),
        # Live-run stamps preserved, only clamped — a normalise pass must never
        # move a running draw or calibration (the batch-block rule).
        "draw": {
            "active": bool(raw_draw.get("active", False)),
            "litres": round(_awc_num(raw_draw.get("litres"), 0, 0, MIXING_VESSEL_MAX_L), 1),
            "destination": draw_dest if draw_dest in MIXING_DRAW_DESTINATIONS else "store",
            "startedAt": _awc_str(raw_draw.get("startedAt"), 40),
            "endsAt": _awc_str(raw_draw.get("endsAt"), 40),
        },
        "calibration": {
            "active": bool(raw_cal.get("active", False)),
            "startedAt": _awc_str(raw_cal.get("startedAt"), 40),
        },
    }

    raw_salt = mix_cfg.get("salt") if isinstance(mix_cfg.get("salt"), dict) else {}
    brand = str(raw_salt.get("brand") or "nyos_pure")
    mix_cfg["salt"] = {
        "brand": brand if brand in mixing_engine.brand_ids() else "nyos_pure",
        "targetPpt": round(_awc_num(raw_salt.get("targetPpt"), 35.0,
                                    MIXING_TARGET_PPT_MIN, MIXING_TARGET_PPT_MAX), 1),
        "mixHours": round(_awc_num(raw_salt.get("mixHours"), 0, 0, MIXING_MIX_HOURS_MAX), 1),
        "customGPerL": round(_awc_num(raw_salt.get("customGPerL"), 0, 0, 100), 1),
    }

    raw_heat = mix_cfg.get("heat") if isinstance(mix_cfg.get("heat"), dict) else {}
    mix_cfg["heat"] = {
        "enabled": bool(raw_heat.get("enabled", False)),
        "targetC": round(_awc_num(raw_heat.get("targetC"), 25.0,
                                  MIXING_HEAT_TARGET_MIN_C, MIXING_HEAT_TARGET_MAX_C), 1),
        "tempSensorEntity": _normalise_entity_id(raw_heat.get("tempSensorEntity")),
    }
    mix_cfg["salinitySensorEntity"] = _normalise_entity_id(mix_cfg.get("salinitySensorEntity"))

    raw_storage = mix_cfg.get("storage") if isinstance(mix_cfg.get("storage"), dict) else {}
    mix_cfg["storage"] = {
        "circulateEveryH": int(_awc_num(raw_storage.get("circulateEveryH"), 6, 0,
                                        MIXING_CIRCULATE_EVERY_MAX_H)),
        "circulateForMin": int(_awc_num(raw_storage.get("circulateForMin"), 10, 1,
                                        MIXING_CIRCULATE_FOR_MAX_MIN)),
        "retestAfterDays": int(_awc_num(raw_storage.get("retestAfterDays"), 7, 0,
                                        MIXING_RETEST_MAX_DAYS)),
    }

    raw_batch = mix_cfg.get("batch") if isinstance(mix_cfg.get("batch"), dict) else {}
    state = str(raw_batch.get("state") or "idle")
    btype = str(raw_batch.get("type") or "salt")
    batch_litres = round(_awc_num(raw_batch.get("litres"), 0, 0, MIXING_VESSEL_MAX_L), 1)
    mix_cfg["batch"] = {
        "state": state if state in MIXING_STATUSES else "idle",
        "type": btype if btype in MIXING_BATCH_TYPES else "salt",
        "startedAt": _awc_str(raw_batch.get("startedAt"), 40),
        "stageAt": _awc_str(raw_batch.get("stageAt"), 40),
        "litres": batch_litres,
        "loggedPpt": round(_awc_num(raw_batch.get("loggedPpt"), 0, 0, 100), 2),
        "testedAt": _awc_str(raw_batch.get("testedAt"), 40),
        "usedLitres": round(_awc_num(raw_batch.get("usedLitres"), 0, 0,
                                     batch_litres if batch_litres > 0 else MIXING_VESSEL_MAX_L), 1),
        "circulateUntil": _awc_str(raw_batch.get("circulateUntil"), 40),
        "nextCirculateAt": _awc_str(raw_batch.get("nextCirculateAt"), 40),
        "lastCirculatedAt": _awc_str(raw_batch.get("lastCirculatedAt"), 40),
    }

    raw_integrations = mix_cfg.get("integrations") if isinstance(mix_cfg.get("integrations"), dict) else {}
    awc_guard = str(raw_integrations.get("awcGuard") or "warn")
    mix_cfg["integrations"] = {
        "awcGuard": awc_guard if awc_guard in ("off", "warn", "block") else "warn",
        "atoFromRodi": bool(raw_integrations.get("atoFromRodi", False)),
    }


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
        tank["volumeLitres"] = round(_awc_num(tank.get("volumeLitres"), 0, 0, AWC_TANK_MAX_L), 2)

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
        if "lightGated" in raw_sensor:
            sensor["lightGated"] = bool(raw_sensor.get("lightGated"))
        else:
            sensor["lightGated"] = bool(sensor.get("lightGated", meta.get("group") == "lighting"))

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
        # Per-equipment timer runtime state (Mode Actions V2). Cleared in running; kept
        # corruption-proof so the restart re-arm path can never crash.
        equipment_timers = mode.get("equipmentTimers")
        if not isinstance(equipment_timers, dict) or mode["active"] == "running":
            mode["equipmentTimers"] = {}
        else:
            cleaned_timers: dict[str, dict[str, Any]] = {}
            for equipment_id, timer_state in equipment_timers.items():
                if not isinstance(equipment_id, str) or not isinstance(timer_state, dict):
                    continue
                phase = timer_state.get("phase")
                action = timer_state.get("action")
                if phase not in {"delay", "hold", "on", "off", "done"}:
                    continue
                if action not in {"on", "off"}:
                    continue
                cleaned_timers[equipment_id] = {
                    "timerMode": timer_state.get("timerMode")
                    if timer_state.get("timerMode") in {"once", "cycle"}
                    else "once",
                    "phase": phase,
                    "action": action,
                    "nextFireAt": timer_state.get("nextFireAt")
                    if isinstance(timer_state.get("nextFireAt"), str)
                    else "",
                    "onSeconds": _clamp_seconds(timer_state.get("onSeconds")),
                    "offSeconds": _clamp_seconds(timer_state.get("offSeconds")),
                    "holdSeconds": _clamp_seconds(timer_state.get("holdSeconds")),
                }
            mode["equipmentTimers"] = cleaned_timers
        # Per-equipment max-off cap runtime state.
        max_off_timers = mode.get("maxOffTimers")
        if not isinstance(max_off_timers, dict) or mode["active"] == "running":
            mode["maxOffTimers"] = {}
        else:
            cleaned_caps: dict[str, dict[str, str]] = {}
            for equipment_id, cap_state in max_off_timers.items():
                if not isinstance(equipment_id, str) or not isinstance(cap_state, dict):
                    continue
                fire_at = cap_state.get("fireAt")
                if not isinstance(fire_at, str) or not fire_at:
                    continue
                cleaned_caps[equipment_id] = {
                    "fireAt": fire_at,
                    "switch_entity_id": _normalise_entity_id(
                        cap_state.get("switch_entity_id")
                    ),
                }
            mode["maxOffTimers"] = cleaned_caps

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

    # Per-equipment timers (Mode Actions V2). Sibling to modePreviews; one entry per
    # equipment with a timer. Clamp durations, enforce the cycle floor, auto-disable
    # degenerate timers, and strip timers whose preview action is not on/off.
    mode_equipment_timers = config.setdefault("modeEquipmentTimers", {})
    normalised_previews = config.get("modePreviews", {})
    if not isinstance(mode_equipment_timers, dict):
        config["modeEquipmentTimers"] = deepcopy(
            DEFAULT_CORE_CONFIG["modeEquipmentTimers"]
        )
    else:
        for mode_id in list(mode_equipment_timers):
            if mode_id == "running" or mode_id not in allowed_mode_ids:
                mode_equipment_timers.pop(mode_id)
        for mode_id in sorted(allowed_mode_ids - {"running"}):
            block = mode_equipment_timers.setdefault(mode_id, {})
            if not isinstance(block, dict):
                mode_equipment_timers[mode_id] = {}
                continue
            preview_block = (
                normalised_previews.get(mode_id, {})
                if isinstance(normalised_previews, dict)
                else {}
            )
            for equipment_id, timer in list(block.items()):
                if not isinstance(equipment_id, str) or not isinstance(timer, dict):
                    block.pop(equipment_id)
                    continue
                if not isinstance(preview_block, dict) or preview_block.get(
                    equipment_id
                ) not in {"on", "off"}:
                    block.pop(equipment_id)
                    continue
                normalised_timer = _normalise_equipment_timer(timer)
                if normalised_timer["enabled"] and not _equipment_timer_active(
                    normalised_timer
                ):
                    normalised_timer["enabled"] = False
                block[equipment_id] = normalised_timer

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
            # Max-off safety cap (Mode Actions V2): 0 = disabled. Force-restores a
            # device held off by a mode/timer past this limit.
            equipment_config["maxOffSeconds"] = _equipment_max_off_seconds(
                equipment_config
            )

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

    feedwatch = config.setdefault("feedWatch", {})
    if not isinstance(feedwatch, dict):
        feedwatch = {}
        config["feedWatch"] = feedwatch
    feedwatch["enabled"] = bool(feedwatch.get("enabled", False))
    fw_camera = feedwatch.get("cameraId")
    feedwatch["cameraId"] = (
        fw_camera if isinstance(fw_camera, str) and fw_camera in known_cameras else ""
    )
    feedwatch["cadenceSeconds"] = _clamp_int(
        feedwatch.get("cadenceSeconds"),
        FEEDWATCH_DEFAULT_CADENCE,
        FEEDWATCH_MIN_CADENCE,
        FEEDWATCH_MAX_CADENCE,
    )
    feedwatch["retentionSessions"] = _clamp_int(
        feedwatch.get("retentionSessions"),
        FEEDWATCH_DEFAULT_RETENTION,
        1,
        FEEDWATCH_MAX_RETENTION,
    )
    feed_sessions = config.get("feedSessions")
    if not isinstance(feed_sessions, list):
        feed_sessions = []
    config["feedSessions"] = [s for s in feed_sessions if isinstance(s, dict)][
        : feedwatch["retentionSessions"]
    ]

    vision_cfg = config.setdefault("vision", {})
    if not isinstance(vision_cfg, dict):
        vision_cfg = deepcopy(DEFAULT_CORE_CONFIG["vision"])
        config["vision"] = vision_cfg
    vision_cfg["enabled"] = bool(vision_cfg.get("enabled", False))
    v_prefix = vision_cfg.get("topicPrefix")
    vision_cfg["topicPrefix"] = (
        v_prefix.strip().strip("/")[:64]
        if isinstance(v_prefix, str) and v_prefix.strip().strip("/")
        else "frigate"
    )
    v_camera = vision_cfg.get("cameraName")
    vision_cfg["cameraName"] = v_camera.strip()[:64] if isinstance(v_camera, str) else ""
    v_surface = vision_cfg.get("surfaceZone")
    vision_cfg["surfaceZone"] = (
        v_surface.strip()[:64]
        if isinstance(v_surface, str) and v_surface.strip()
        else "surface"
    )
    for v_key, v_cap in (("species", VISION_MAX_SPECIES), ("zones", VISION_MAX_ZONES)):
        v_raw = vision_cfg.get(v_key)
        v_cleaned: list[str] = []
        if isinstance(v_raw, list):
            for v_item in v_raw:
                if isinstance(v_item, str) and v_item.strip():
                    v_val = v_item.strip()[:64]
                    if v_val not in v_cleaned:
                        v_cleaned.append(v_val)
        vision_cfg[v_key] = v_cleaned[:v_cap]
    v_alerts = vision_cfg.get("alerts")
    if not isinstance(v_alerts, dict):
        v_alerts = {}
        vision_cfg["alerts"] = v_alerts
    v_alerts["missingFishHours"] = _clamp_int(
        v_alerts.get("missingFishHours"), 0, 0, VISION_MAX_MISSING_HOURS
    )
    v_alerts["surfaceDistress"] = bool(v_alerts.get("surfaceDistress", False))
    v_feed = vision_cfg.get("feedReport")
    if not isinstance(v_feed, dict):
        v_feed = {}
        vision_cfg["feedReport"] = v_feed
    v_feed["enabled"] = bool(v_feed.get("enabled", False))
    v_feed["windowSeconds"] = _clamp_int(
        v_feed.get("windowSeconds"),
        VISION_DEFAULT_FEED_WINDOW,
        VISION_MIN_FEED_WINDOW,
        VISION_MAX_FEED_WINDOW,
    )
    v_reports = config.get("visionReports")
    config["visionReports"] = (
        [r for r in v_reports if isinstance(r, dict)][:VISION_MAX_REPORTS]
        if isinstance(v_reports, list)
        else []
    )
    v_summary = config.get("visionSummary")
    config["visionSummary"] = v_summary if isinstance(v_summary, dict) else {}

    config["guardian"] = guardian_engine.sanitize_guardian_cfg(config.get("guardian"))

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
        # Mode Actions V2 — exit verification + stuck alerts.
        alerts["modeVerifyEnabled"] = bool(alerts.get("modeVerifyEnabled", True))
        try:
            verify_delay = int(
                alerts.get("modeVerifyDelaySeconds", MODE_VERIFY_DEFAULT_DELAY_SECONDS)
            )
        except (TypeError, ValueError):
            verify_delay = MODE_VERIFY_DEFAULT_DELAY_SECONDS
        alerts["modeVerifyDelaySeconds"] = max(2, min(verify_delay, 120))
        alerts["modeStuckNotify"] = bool(alerts.get("modeStuckNotify", True))
        alerts["modeNotifyTarget"] = str(alerts.get("modeNotifyTarget", "")).strip()[:120]
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

    watchdog = config.setdefault("watchdog", {})
    if not isinstance(watchdog, dict):
        watchdog = {}
        config["watchdog"] = watchdog
    watchdog["enabled"] = bool(watchdog.get("enabled", True))
    watchdog["heartbeatEnabled"] = bool(watchdog.get("heartbeatEnabled", True))
    watchdog["heartbeatEveryHours"] = _clamp_int(
        watchdog.get("heartbeatEveryHours"), 24, 1, 168
    )
    watchdog["missedAfterHours"] = _clamp_int(
        watchdog.get("missedAfterHours"), 30, 2, 336
    )
    watchdog["notifyTarget"] = str(watchdog.get("notifyTarget", "")).strip()[:120]
    for field in ("lastCheck", "lastHeartbeat", "lastNotificationTest", "lastMissedAlert"):
        watchdog[field] = (
            watchdog.get(field) if isinstance(watchdog.get(field), str) else ""
        )

    sensor_health = config.setdefault("sensorHealth", {})
    if not isinstance(sensor_health, dict):
        sensor_health = {}
        config["sensorHealth"] = sensor_health
    sensor_health["enabled"] = bool(sensor_health.get("enabled", True))
    sensor_health["staleAfterMinutes"] = _clamp_int(
        sensor_health.get("staleAfterMinutes"), 180, 5, 10080
    )
    sensor_health["flatlineHours"] = _clamp_int(
        sensor_health.get("flatlineHours"), 12, 1, 336
    )
    sensor_health["jumpWindowMinutes"] = _clamp_int(
        sensor_health.get("jumpWindowMinutes"), 30, 1, 1440
    )
    try:
        jump_percent = float(sensor_health.get("jumpPercent", 25))
    except (TypeError, ValueError):
        jump_percent = 25
    sensor_health["jumpPercent"] = max(1, min(jump_percent, 100))
    try:
        mismatch_c = float(sensor_health.get("temperatureMismatchC", 1.5))
    except (TypeError, ValueError):
        mismatch_c = 1.5
    sensor_health["temperatureMismatchC"] = max(0.1, min(mismatch_c, 10))
    last_values = sensor_health.get("lastValues")
    sensor_health["lastValues"] = (
        {
            sensor_id: item
            for sensor_id, item in last_values.items()
            if sensor_id in MVP_SENSORS and isinstance(item, dict)
        }
        if isinstance(last_values, dict)
        else {}
    )
    last_jumps = sensor_health.get("lastJumps")
    sensor_health["lastJumps"] = (
        {
            sensor_id: item
            for sensor_id, item in last_jumps.items()
            if sensor_id in MVP_SENSORS and isinstance(item, dict)
        }
        if isinstance(last_jumps, dict)
        else {}
    )

    escalation = config.setdefault("alertEscalation", {})
    if not isinstance(escalation, dict):
        escalation = {}
        config["alertEscalation"] = escalation
    escalation["enabled"] = bool(escalation.get("enabled", False))
    escalation["criticalOnly"] = bool(escalation.get("criticalOnly", True))
    escalation["repeatMinutes"] = _clamp_int(
        escalation.get("repeatMinutes"), 30, 1, 1440
    )
    escalation["notifyTarget"] = str(escalation.get("notifyTarget", "")).strip()[:120]
    escalation["acknowledgeRequired"] = bool(
        escalation.get("acknowledgeRequired", True)
    )
    escalation["sirenEntityId"] = _normalise_entity_id(escalation.get("sirenEntityId"))
    escalation["lightEntityId"] = _normalise_entity_id(escalation.get("lightEntityId"))
    escalation["outputsActive"] = bool(escalation.get("outputsActive", False))
    acknowledged = escalation.get("acknowledged")
    escalation["acknowledged"] = (
        {
            sensor_id: timestamp
            for sensor_id, timestamp in acknowledged.items()
            if sensor_id in MVP_SENSORS and isinstance(timestamp, str)
        }
        if isinstance(acknowledged, dict)
        else {}
    )
    last_escalated = escalation.get("lastEscalated")
    escalation["lastEscalated"] = (
        {
            sensor_id: timestamp
            for sensor_id, timestamp in last_escalated.items()
            if sensor_id in MVP_SENSORS and isinstance(timestamp, str)
        }
        if isinstance(last_escalated, dict)
        else {}
    )

    trust_check = config.setdefault("trustCheck", {})
    if not isinstance(trust_check, dict):
        trust_check = {}
        config["trustCheck"] = trust_check
    trust_check["enabled"] = bool(trust_check.get("enabled", True))
    trust_check["lastRun"] = (
        trust_check.get("lastRun") if isinstance(trust_check.get("lastRun"), str) else ""
    )
    trust_check["lastStatus"] = (
        trust_check.get("lastStatus")
        if trust_check.get("lastStatus") in {"ok", "warning", "critical", "unknown"}
        else "unknown"
    )
    trust_check["lastBackupReview"] = (
        trust_check.get("lastBackupReview")
        if isinstance(trust_check.get("lastBackupReview"), str)
        else ""
    )

    edge_failsafes = config.setdefault("edgeFailsafes", {})
    if not isinstance(edge_failsafes, dict):
        edge_failsafes = {}
        config["edgeFailsafes"] = edge_failsafes
    edge_failsafes["enabled"] = bool(edge_failsafes.get("enabled", False))
    edge_failsafes["heater"] = bool(edge_failsafes.get("heater", False))
    edge_failsafes["ato"] = bool(edge_failsafes.get("ato", False))
    edge_failsafes["returnPump"] = bool(edge_failsafes.get("returnPump", False))
    edge_failsafes["lastReviewed"] = (
        edge_failsafes.get("lastReviewed")
        if isinstance(edge_failsafes.get("lastReviewed"), str)
        else ""
    )
    edge_failsafes["notes"] = (
        edge_failsafes.get("notes").strip()[:500]
        if isinstance(edge_failsafes.get("notes"), str)
        else ""
    )

    reef_replay = config.setdefault("reefReplay", {})
    if not isinstance(reef_replay, dict):
        reef_replay = {}
        config["reefReplay"] = reef_replay
    reef_replay["enabled"] = bool(reef_replay.get("enabled", True))
    reef_replay["incidentWindowMinutes"] = _clamp_int(
        reef_replay.get("incidentWindowMinutes"), 20, 5, 120
    )
    reef_replay["retention"] = _clamp_int(reef_replay.get("retention"), 25, 5, 100)

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
                # Salinity may be logged as specific gravity (e.g. a Tropic Marin
                # hydrometer). Canonicalize to ppt here — backend-authoritative —
                # so reef-score, dosing and AWC always read ppt. Idempotent: a
                # value already in ppt magnitude is never re-converted, and the
                # "SG" display hint is preserved so the panel can show it back.
                display_unit = ""
                if parameter == "salinity":
                    raw_du = str(item.get("displayUnit") or item.get("display_unit") or "").strip().upper()
                    unit_l = str(unit).strip().lower()
                    flagged_sg = raw_du == "SG" or unit_l in {
                        "sg", "s.g.", "specific gravity", "specificgravity", "specific_gravity",
                    }
                    if salinity_value_looks_like_sg(value):
                        value = salinity_sg_to_ppt(value)
                        unit = MVP_SENSORS.get("salinity", {}).get("unit", "ppt")
                        display_unit = "SG"
                    elif flagged_sg:
                        # Already canonical ppt but the user works in SG — keep the hint.
                        unit = MVP_SENSORS.get("salinity", {}).get("unit", "ppt")
                        display_unit = "SG"
                entry: dict[str, Any] = {
                    "id": str(entry_id)[:120],
                    "timestamp": timestamp,
                    "value": value,
                    "unit": str(unit)[:20],
                    "source": str(source)[:80],
                    "notes": str(notes)[:500],
                }
                if display_unit:
                    entry["displayUnit"] = display_unit
                safe_entries.append(entry)
            normalised_readings[parameter] = safe_entries
        config["manualReadings"] = normalised_readings

    # ICP test importer — re-validate every stored report authoritatively (recompute
    # flags/units; ignore any client-supplied status) and cap to the most recent N.
    icp_reports = config.get("icpReports")
    if not isinstance(icp_reports, list):
        config["icpReports"] = []
    else:
        safe_reports: list[dict[str, Any]] = []
        for item in icp_reports[-ICP_REPORTS_MAX:]:
            report = icp.normalise_report(item)
            if report is not None:
                safe_reports.append(report)
        config["icpReports"] = safe_reports
    config["icpTemplates"] = icp.normalise_templates(config.get("icpTemplates"))
    config["icpDashboard"] = icp.normalise_dashboard_settings(config.get("icpDashboard"))

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

    maintenance = config.setdefault("maintenance", {})
    if not isinstance(maintenance, dict):
        config["maintenance"] = deepcopy(DEFAULT_CORE_CONFIG["maintenance"])
        maintenance = config["maintenance"]
    maintenance["enabled"] = bool(maintenance.get("enabled", True))
    # Automatic water changes are logged against the water-change task so the chore,
    # the reminders and the trend chart all count the water AWC actually moved.
    maintenance["logAwcChanges"] = bool(maintenance.get("logAwcChanges", True))
    # "This snapshot of the completion history was current at". Re-stamped on every
    # save and round-tripped by the panel; _merge_recent_completions uses the stamp a
    # client sends back to tell "logged after your snapshot" from "you deleted it".
    synced_at = maintenance.get("completionsSyncedAt")
    maintenance["completionsSyncedAt"] = (
        synced_at if isinstance(synced_at, str) and _parse_datetime(synced_at) is not None else ""
    )
    raw_tasks = maintenance.get("tasks")
    raw_tasks = raw_tasks if isinstance(raw_tasks, dict) else {}
    # Seed the curated defaults exactly once; after that the user owns the list
    # (so deleted/edited tasks persist and are never silently re-added).
    if not maintenance.get("seeded", False):
        for task_id, default in MAINTENANCE_TASK_DEFAULTS.items():
            raw_tasks.setdefault(
                task_id,
                {
                    "label": default["label"],
                    "cadenceDays": default["cadenceDays"],
                    "enabled": False,
                    "builtin": True,
                },
            )
        maintenance["seeded"] = True
    tasks: dict[str, dict[str, Any]] = {}
    for task_id, raw in raw_tasks.items():
        if not isinstance(raw, dict):
            continue
        default = MAINTENANCE_TASK_DEFAULTS.get(task_id, {})
        label = raw.get("label")
        if not (isinstance(label, str) and label.strip()):
            label = default.get("label") or task_id
        try:
            cadence_days = int(raw.get("cadenceDays", default.get("cadenceDays", 7)))
        except (TypeError, ValueError):
            cadence_days = default.get("cadenceDays", 7)
        cadence_days = max(
            MAINTENANCE_TASK_CADENCE_MIN, min(cadence_days, MAINTENANCE_TASK_CADENCE_MAX)
        )
        try:
            critical_after_days = int(raw.get("criticalAfterDays", cadence_days * 2))
        except (TypeError, ValueError):
            critical_after_days = cadence_days * 2
        # Optional hour-grained cadence (see const.py) — absent means day-based.
        try:
            cadence_hours = float(raw.get("cadenceHours") or 0)
        except (TypeError, ValueError):
            cadence_hours = 0.0
        if cadence_hours > 0:
            cadence_hours = max(1.0, min(round(cadence_hours, 1), MAINTENANCE_TASK_CADENCE_HOURS_MAX))
            try:
                critical_after_hours = float(raw.get("criticalAfterHours") or cadence_hours * 2)
            except (TypeError, ValueError):
                critical_after_hours = cadence_hours * 2
            critical_after_hours = max(
                cadence_hours, min(round(critical_after_hours, 1), MAINTENANCE_TASK_CRITICAL_HOURS_MAX)
            )
        schedule_mode = raw.get("scheduleMode")
        if schedule_mode not in ("interval", "fixed"):
            schedule_mode = "interval"
        snoozed_until = raw.get("snoozedUntil")
        if not (isinstance(snoozed_until, str) and _parse_datetime(snoozed_until) is not None):
            snoozed_until = None
        tasks[task_id] = {
            "label": str(label).strip()[:80],
            "cadenceDays": cadence_days,
            "criticalAfterDays": max(
                cadence_days, min(critical_after_days, MAINTENANCE_TASK_CRITICAL_MAX)
            ),
            "enabled": bool(raw.get("enabled", False)),
            "notes": str(raw.get("notes", ""))[:300],
            "builtin": bool(raw.get("builtin", task_id in MAINTENANCE_TASK_DEFAULTS)),
            "scheduleMode": schedule_mode,
            "scheduleDays": _ints_in_range(raw.get("scheduleDays"), 0, 6),
            "scheduleMonthDays": _ints_in_range(raw.get("scheduleMonthDays"), 1, 31),
            "notify": bool(raw.get("notify", True)),
            "snoozedUntil": snoozed_until,
            "logsVolume": bool(raw.get("logsVolume", task_id == "water_change")),
        }
        if cadence_hours > 0:
            tasks[task_id]["cadenceHours"] = cadence_hours
            tasks[task_id]["criticalAfterHours"] = critical_after_hours
    maintenance["tasks"] = tasks

    raw_completions = maintenance.get("completions")
    raw_completions = raw_completions if isinstance(raw_completions, dict) else {}
    completions: dict[str, list[dict[str, Any]]] = {}
    for task_id in tasks:
        entries = raw_completions.get(task_id)
        if not isinstance(entries, list):
            continue
        safe: list[dict[str, Any]] = []
        for index, item in enumerate(entries[:MAINTENANCE_COMPLETIONS_MAX]):
            if not isinstance(item, dict):
                continue
            timestamp = item.get("timestamp") or item.get("date")
            if not isinstance(timestamp, str) or not timestamp:
                continue
            entry_id = item.get("id") or f"{task_id}:{timestamp}:{index}"
            safe_entry: dict[str, Any] = {
                "id": str(entry_id)[:120],
                "timestamp": timestamp,
                "notes": str(item.get("notes", ""))[:500],
            }
            if item.get("skipped"):
                safe_entry["skipped"] = True
            # Only automatic entries carry a source; a hand-logged completion has none,
            # which is what lets the panel tell the two apart in history and the chart.
            if item.get("source") in (MAINTENANCE_SOURCE_AWC, MAINTENANCE_SOURCE_HATCHERY,
                                      MAINTENANCE_SOURCE_MIXING):
                safe_entry["source"] = item["source"]
            volume = item.get("volume")
            if isinstance(volume, (int, float)) and not isinstance(volume, bool):
                safe_entry["volume"] = round(float(volume), 2)
                safe_entry["volumeUnit"] = "L" if item.get("volumeUnit") == "L" else "pct"
            safe.append(safe_entry)
        if safe:
            completions[task_id] = safe
    maintenance["completions"] = completions

    raw_reminders = maintenance.get("reminders")
    raw_reminders = raw_reminders if isinstance(raw_reminders, dict) else {}
    reminder_time = raw_reminders.get("time", MAINTENANCE_REMINDER_DEFAULT_TIME)
    if not (
        isinstance(reminder_time, str)
        and re.match(r"^([01]\d|2[0-3]):[0-5]\d$", reminder_time)
    ):
        reminder_time = MAINTENANCE_REMINDER_DEFAULT_TIME
    maintenance["reminders"] = {
        "enabled": bool(raw_reminders.get("enabled", True)),
        "time": reminder_time,
        "notifyTarget": str(raw_reminders.get("notifyTarget", "")).strip()[:120],
        "persistent": bool(raw_reminders.get("persistent", True)),
    }

    # Reef Pulse (presentation/kiosk mode) — display-only frontend feature; the
    # backend just keeps its config block well-formed.
    pulse = config.setdefault("pulse", {})
    if not isinstance(pulse, dict):
        config["pulse"] = deepcopy(DEFAULT_CORE_CONFIG["pulse"])
        pulse = config["pulse"]
    pulse_defaults = DEFAULT_CORE_CONFIG["pulse"]
    for field in (
        "enabled",
        "showHealthRing",
        "showStats",
        "showTicker",
        "showMode",
        "showBuddy",
        "showClock",
        "kioskAutoStart",
        "showSparklines",
        "showCategories",
        "showEquipment",
        "showToday",
        "showInsights",
        "showShare",
        "keepAwake",
        "nightDim",
        "allowModes",
    ):
        pulse[field] = bool(pulse.get(field, pulse_defaults[field]))
    camera_id = pulse.get("cameraId")
    cameras_block = config.get("cameras")
    known_cameras = cameras_block if isinstance(cameras_block, dict) else {}
    pulse["cameraId"] = camera_id if isinstance(camera_id, str) and camera_id in known_cameras else ""
    pulse["backdrop"] = pulse.get("backdrop") if pulse.get("backdrop") in ("auto", "camera", "wall", "timelapse", "diagram") else "auto"
    pulse["graphRange"] = pulse.get("graphRange") if pulse.get("graphRange") in ("24h", "7d") else "24h"
    pulse["timelapseStyle"] = pulse.get("timelapseStyle") if pulse.get("timelapseStyle") in ("growth", "day") else "growth"
    pulse["sizePreset"] = pulse.get("sizePreset") if pulse.get("sizePreset") in ("normal", "far") else "normal"
    for field, default in (("nightDimFrom", "22:00"), ("nightDimTo", "07:00")):
        value = pulse.get(field)
        pulse[field] = value if isinstance(value, str) and re.fullmatch(r"\d{1,2}:\d{2}", value) else default
    lux_entity = pulse.get("nightDimLuxEntity")
    pulse["nightDimLuxEntity"] = lux_entity.strip() if isinstance(lux_entity, str) else ""
    try:
        threshold = float(pulse.get("nightDimLuxThreshold", 10))
    except (TypeError, ValueError):
        threshold = 10.0
    pulse["nightDimLuxThreshold"] = threshold if threshold > 0 else 10.0

    # Living tank diagram — the backend keeps the block well-formed; slot ids are
    # resolved (and unknown ones dropped back to scene defaults) by the panel.
    diagram = config.setdefault("diagram", {})
    if not isinstance(diagram, dict):
        config["diagram"] = deepcopy(DEFAULT_CORE_CONFIG["diagram"])
        diagram = config["diagram"]
    diagram["systemType"] = diagram.get("systemType") if diagram.get("systemType") in ("sump", "aio") else "sump"
    diagram["scape"] = diagram.get("scape") if diagram.get("scape") in CORAL_SCAPES else "island"
    diagram["allowControls"] = bool(diagram.get("allowControls", True))
    diagram["showAlerts"] = bool(diagram.get("showAlerts", True))
    diagram["showReadings"] = bool(diagram.get("showReadings", True))
    raw_layout = diagram.get("layout")
    diagram_layout: dict = {}
    if isinstance(raw_layout, dict):
        for slot_key, slot_value in list(raw_layout.items())[:40]:
            if (
                isinstance(slot_key, str)
                and isinstance(slot_value, str)
                and re.fullmatch(r"[A-Za-z0-9:_-]{1,64}", slot_key)
                and re.fullmatch(r"[A-Za-z0-9_-]{1,32}", slot_value)
            ):
                diagram_layout[slot_key] = slot_value
    diagram["layout"] = diagram_layout

    # Reef Layer livestock — registered corals drawn on the diagram rockwork.
    # Unknown species/colours coerce to safe defaults rather than crash the
    # scene; the panel resolves slot placement (diagram.layout coral:<id>).
    livestock = config.setdefault("livestock", {})
    if not isinstance(livestock, dict):
        config["livestock"] = deepcopy(DEFAULT_CORE_CONFIG["livestock"])
        livestock = config["livestock"]
    raw_corals = livestock.get("corals")
    corals: dict = {}
    if isinstance(raw_corals, dict):
        for coral_id, entry in list(raw_corals.items())[:16]:
            if not (
                isinstance(coral_id, str)
                and isinstance(entry, dict)
                and re.fullmatch(r"[A-Za-z0-9_-]{1,32}", coral_id)
            ):
                continue
            photo = str(entry.get("photoUrl") or "")[:300]
            if photo and not (photo.startswith("/") or photo.startswith("http://") or photo.startswith("https://")):
                photo = ""
            corals[coral_id] = {
                "name": str(entry.get("name") or "")[:48],
                "species": entry.get("species") if entry.get("species") in CORAL_SPECIES else "zoa",
                "colour": entry.get("colour") if entry.get("colour") in CORAL_COLOURS else "purple",
                "addedAt": str(entry.get("addedAt") or "")[:32],
                "notes": str(entry.get("notes") or "")[:500],
                "photoUrl": photo,
            }
    livestock["corals"] = corals

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
        for field in ("primaryProduct", "secondaryProduct"):
            fallback = inferred_primary if field == "primaryProduct" else inferred_secondary
            if field in raw_system:
                # Empty string is a deliberate user choice ("no primary"/"no secondary").
                # Only infer from old per-parameter presets when the new system field is absent.
                system[field] = _normalise_dosing_product_id(raw_system.get(field))
            else:
                system[field] = fallback
        custom_class = _normalise_dosing_product_id(
            raw_system.get("customProductClass", default_system["customProductClass"])
        )
        system["customProductClass"] = custom_class or default_system["customProductClass"]
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
        _normalise_dosing_channels(dosing)
        raw_notify = dosing.get("notifications")
        raw_notify = raw_notify if isinstance(raw_notify, dict) else {}
        dosing["notifications"] = {
            key: bool(raw_notify.get(key, True))
            for key in ("missedDose", "reservoirLow", "tubeLife", "calibrationDue", "syncIssues", "staleFood")
        }
        # 2-part chemical spacing (Stage E): the pair matrix is minutes required
        # between groups (alk|ca etc.); a single queued deferred dose survives
        # restarts. Keys are canonicalised alphabetically.
        raw_spacing = dosing.get("spacing") if isinstance(dosing.get("spacing"), dict) else {}
        raw_matrix = raw_spacing.get("matrix") if isinstance(raw_spacing.get("matrix"), dict) else {}
        matrix: dict[str, float] = {}
        for key, value in raw_matrix.items():
            parts = sorted(p.strip() for p in str(key).split("|"))
            if len(parts) == 2 and parts[0] != parts[1] and all(p in ("alk", "ca", "mg") for p in parts):
                matrix["|".join(parts)] = round(_awc_num(value, 0, 0, 1440), 1)
        raw_queued = raw_spacing.get("queued") if isinstance(raw_spacing.get("queued"), dict) else None
        queued = None
        if raw_queued and raw_queued.get("channelId"):
            queued = {
                "channelId": str(raw_queued.get("channelId"))[:64],
                "ml": round(_awc_num(raw_queued.get("ml"), 0, 0, DOSING_MAX_PER_DOSE_ML), 2),
                "requestedAt": _awc_str(raw_queued.get("requestedAt"), 40),
                "notBefore": _awc_str(raw_queued.get("notBefore"), 40),
            }
            if queued["ml"] <= 0:
                queued = None
        dosing["spacing"] = {
            "enabled": bool(raw_spacing.get("enabled", False)),
            "matrix": matrix,
            "queued": queued,
        }

    _normalise_nps_config(config)

    lighting_cfg = config.setdefault("lightingSchedule", {})
    if not isinstance(lighting_cfg, dict):
        config["lightingSchedule"] = deepcopy(DEFAULT_CORE_CONFIG["lightingSchedule"])
    else:
        ls_defaults = DEFAULT_CORE_CONFIG["lightingSchedule"]
        mode = lighting_cfg.get("mode")
        lighting_cfg["mode"] = mode if mode in {"off", "simple", "reef", "spawning"} else "off"
        lighting_cfg["onTime"] = (
            _normalise_schedule_time(lighting_cfg.get("onTime")) or ls_defaults["onTime"]
        )
        lighting_cfg["offTime"] = (
            _normalise_schedule_time(lighting_cfg.get("offTime")) or ls_defaults["offTime"]
        )
        ls_preset = lighting_cfg.get("reefPreset")
        lighting_cfg["reefPreset"] = (
            ls_preset if ls_preset in REEF_PRESETS else ls_defaults["reefPreset"]
        )
        try:
            ls_offset = float(lighting_cfg.get("offsetHours", 0))
        except (TypeError, ValueError):
            ls_offset = 0.0
        lighting_cfg["offsetHours"] = round(
            max(-LIGHTING_OFFSET_HOURS_MAX, min(ls_offset, LIGHTING_OFFSET_HOURS_MAX)), 2
        )
        try:
            ls_grace = int(lighting_cfg.get("rampGraceMinutes", LIGHTING_SCHEDULE_DEFAULT_GRACE_MIN))
        except (TypeError, ValueError):
            ls_grace = LIGHTING_SCHEDULE_DEFAULT_GRACE_MIN
        lighting_cfg["rampGraceMinutes"] = max(0, min(ls_grace, LIGHTING_SCHEDULE_GRACE_MAX))

    spawning_cfg = config.setdefault("spawningProgram", {})
    if not isinstance(spawning_cfg, dict):
        config["spawningProgram"] = deepcopy(DEFAULT_CORE_CONFIG["spawningProgram"])
    else:
        sp_defaults = DEFAULT_CORE_CONFIG["spawningProgram"]
        spawning_cfg["enabled"] = bool(spawning_cfg.get("enabled", False))
        preset = spawning_cfg.get("reefPreset")
        spawning_cfg["reefPreset"] = preset if preset in REEF_PRESETS else sp_defaults["reefPreset"]
        try:
            offset = int(spawning_cfg.get("offsetMonths", 0))
        except (TypeError, ValueError):
            offset = 0
        spawning_cfg["offsetMonths"] = max(0, min(offset, SPAWNING_OFFSET_MONTHS_MAX))
        try:
            noon = float(spawning_cfg.get("solarNoonHour", SPAWNING_DEFAULT_SOLAR_NOON_HOUR))
        except (TypeError, ValueError):
            noon = SPAWNING_DEFAULT_SOLAR_NOON_HOUR
        spawning_cfg["solarNoonHour"] = round(max(0.0, min(noon, 23.5)), 2)
        unit = str(spawning_cfg.get("tempUnit", "C")).upper()
        spawning_cfg["tempUnit"] = "F" if unit == "F" else "C"
        probe = spawning_cfg.get("tempProbe")
        spawning_cfg["tempProbe"] = (
            probe.strip()[:16]
            if isinstance(probe, str) and probe.strip()
            else sp_defaults["tempProbe"]
        )
        spawning_cfg["acknowledgedAdvisory"] = bool(spawning_cfg.get("acknowledgedAdvisory", False))
        execution = spawning_cfg.get("execution")
        if not isinstance(execution, dict):
            execution = {}
        ex_defaults = sp_defaults["execution"]
        ex_mode = execution.get("mode")
        entities: dict[str, Any] = {}
        for key in ("lightEntity", "moonEntity"):
            ent = execution.get(key)
            entities[key] = (
                ent.strip()
                if isinstance(ent, str) and ent.strip().split(".", 1)[0] in ("switch", "light")
                and "." in ent.strip() and len(ent.strip()) > len(ent.strip().split(".", 1)[0]) + 1
                else None
            )
        try:
            moon_pct = int(execution.get("moonMinIlluminationPct", ex_defaults["moonMinIlluminationPct"]))
        except (TypeError, ValueError):
            moon_pct = ex_defaults["moonMinIlluminationPct"]
        policy = execution.get("overridePolicy")
        temp_in = execution.get("temp")
        if not isinstance(temp_in, dict):
            temp_in = {}
        t_defaults = ex_defaults["temp"]
        t_sensor = temp_in.get("sensorEntity")
        t_sensor = (
            t_sensor.strip()
            if isinstance(t_sensor, str) and t_sensor.strip().startswith("sensor.")
            and len(t_sensor.strip()) > len("sensor.")
            else None
        )
        t_plugs: dict[str, Any] = {}
        for key in ("heaterEntity", "coolEntity"):
            ent = temp_in.get(key)
            t_plugs[key] = (
                ent.strip()
                if isinstance(ent, str) and ent.strip().startswith("switch.")
                and len(ent.strip()) > len("switch.")
                else None
            )
        try:
            t_max = round(max(20.0, min(32.0, float(temp_in.get("maxC", t_defaults["maxC"])))), 1)
        except (TypeError, ValueError):
            t_max = t_defaults["maxC"]
        try:
            t_min = round(max(15.0, min(26.0, float(temp_in.get("minC", t_defaults["minC"])))), 1)
        except (TypeError, ValueError):
            t_min = t_defaults["minC"]
        if t_min >= t_max:
            t_min, t_max = t_defaults["minC"], t_defaults["maxC"]
        t_ack = bool(temp_in.get("acknowledged", False))
        # enabled only sticks with the guard acknowledged and a working binding —
        # the tick can then trust an enabled temp block to be complete.
        t_enabled = (
            bool(temp_in.get("enabled", False)) and t_ack and t_sensor is not None
            and (t_plugs["heaterEntity"] is not None or t_plugs["coolEntity"] is not None)
        )
        spawning_cfg["execution"] = {
            "mode": ex_mode if ex_mode in ("apex", "openreef") else ex_defaults["mode"],
            "armed": bool(execution.get("armed", False)),
            "lightEntity": entities["lightEntity"],
            "moonEntity": entities["moonEntity"],
            "moonMinIlluminationPct": max(0, min(100, moon_pct)),
            "overridePolicy": policy if policy in ("hold", "reassert") else "hold",
            "temp": {
                "enabled": t_enabled,
                "acknowledged": t_ack,
                "sensorEntity": t_sensor,
                "heaterEntity": t_plugs["heaterEntity"],
                "coolEntity": t_plugs["coolEntity"],
                "maxC": t_max,
                "minC": t_min,
            },
        }

    _normalise_awc_config(config)
    _normalise_mixing_config(config)

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


def _sensor_low_suppressed(
    config: dict[str, Any], sensor: dict[str, Any], now_local: datetime | None = None
) -> bool:
    """True when a light-gated sensor's low readings should be ignored right now
    because the lighting schedule says the lights are off / still ramping. Cheap
    early-outs first, so non-gated sensors and the default (mode 'off') never touch
    the clock and behave exactly as before this feature existed."""
    if not isinstance(sensor, dict) or not sensor.get("lightGated"):
        return False
    lighting_cfg = _effective_lighting_cfg(config, now_local)
    if not isinstance(lighting_cfg, dict) or lighting_cfg.get("mode", "off") == "off":
        return False
    try:
        grace = int(lighting_cfg.get("rampGraceMinutes", 0))
    except (TypeError, ValueError):
        grace = 0
    return not spawning.is_lights_on(lighting_cfg, now_local or dt_util.now(), grace)


def _sensor_alert_items(
    hass: HomeAssistant, config: dict[str, Any], *, now_local: datetime | None = None
) -> list[dict[str, str]]:
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
        suppress_low = _sensor_low_suppressed(config, sensor, now_local)
        if value > maximum or (value < minimum and not suppress_low):
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
        if value < minimum:
            # Below minimum but the lights are off / still ramping — expected for a
            # light-dependent sensor, so don't alert (and skip the warning band).
            continue

        buffer = (maximum - minimum) * max(0, min(warning_buffer, 50)) / 100
        hysteresis = (maximum - minimum) * hysteresis_percent / 100
        lower_warning = minimum + buffer
        upper_warning = maximum - buffer
        previous_state = last_states.get(sensor_id)
        was_alerting = previous_state in {"warning", "critical"}
        low_warn = value < lower_warning or (was_alerting and value < lower_warning + hysteresis)
        high_warn = value > upper_warning or (was_alerting and value > upper_warning - hysteresis)
        if suppress_low:
            low_warn = False
        if low_warn or high_warn:
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


def _state_timestamp(state: Any, attr: str, fallback_attr: str = "last_changed") -> datetime | None:
    value = getattr(state, attr, None) or getattr(state, fallback_attr, None)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return _parse_datetime(value)


def _sensor_numeric_value(hass: HomeAssistant, sensor: dict[str, Any]) -> float | None:
    entity_id = _normalise_entity_id(sensor.get("entity_id"))
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in UNAVAILABLE_STATES:
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


def _sensor_health_items(hass: HomeAssistant, config: dict[str, Any]) -> list[dict[str, str]]:
    sensor_health = config.get("sensorHealth", {})
    if not isinstance(sensor_health, dict) or not sensor_health.get("enabled", False):
        return []
    sensors = config.get("sensors", {})
    if not isinstance(sensors, dict):
        return []

    now = datetime.now(timezone.utc)
    stale_after = int(sensor_health.get("staleAfterMinutes", 180))
    flatline_hours = int(sensor_health.get("flatlineHours", 12))
    jump_window = int(sensor_health.get("jumpWindowMinutes", 30))
    jump_percent = float(sensor_health.get("jumpPercent", 25))
    mismatch_c = float(sensor_health.get("temperatureMismatchC", 1.5))
    last_values = sensor_health.setdefault("lastValues", {})
    last_jumps = sensor_health.setdefault("lastJumps", {})
    items: list[dict[str, str]] = []

    for sensor_id, sensor in sensors.items():
        if not isinstance(sensor, dict) or not sensor.get("enabled", False):
            continue
        if sensor.get("alertsEnabled", True) is False:
            continue
        if _sensor_kind(sensor_id, sensor) == "binary":
            continue
        entity_id = _normalise_entity_id(sensor.get("entity_id"))
        if not entity_id:
            continue
        state = hass.states.get(entity_id)
        if state is None or state.state in UNAVAILABLE_STATES:
            continue
        label = str(sensor.get("label") or sensor_id)
        last_updated = _state_timestamp(state, "last_updated")
        if last_updated is not None and now - last_updated > timedelta(minutes=stale_after):
            items.append(
                {
                    "id": sensor_id,
                    "severity": "warning",
                    "title": f"{label} has stale data",
                    "message": f"{entity_id} has not updated for more than {stale_after} minutes.",
                }
            )

        value = _sensor_numeric_value(hass, sensor)
        if value is None:
            continue
        last_changed = _state_timestamp(state, "last_changed")
        if last_changed is not None and now - last_changed > timedelta(hours=flatline_hours):
            items.append(
                {
                    "id": sensor_id,
                    "severity": "warning",
                    "title": f"{label} looks flatlined",
                    "message": f"{entity_id} has not changed for more than {flatline_hours} hours.",
                }
            )

        previous = last_values.get(sensor_id) if isinstance(last_values, dict) else None
        if isinstance(previous, dict):
            previous_time = _parse_datetime(previous.get("updatedAt"))
            try:
                previous_value = float(previous.get("value"))
                minimum = float(sensor.get("min"))
                maximum = float(sensor.get("max"))
            except (TypeError, ValueError):
                previous_time = None
            if (
                previous_time is not None
                and now - previous_time <= timedelta(minutes=jump_window)
                and maximum > minimum
            ):
                span = maximum - minimum
                if abs(value - previous_value) > span * jump_percent / 100:
                    last_jumps[sensor_id] = {
                        "timestamp": now.isoformat(),
                        "previous": previous_value,
                        "current": value,
                    }

        jump = last_jumps.get(sensor_id) if isinstance(last_jumps, dict) else None
        jump_time = _parse_datetime(jump.get("timestamp")) if isinstance(jump, dict) else None
        if jump_time is not None and now - jump_time <= timedelta(minutes=jump_window):
            unit = str(sensor.get("unit") or "").strip()
            items.append(
                {
                    "id": sensor_id,
                    "severity": "warning",
                    "title": f"{label} jumped suddenly",
                    "message": f"{entity_id} changed faster than the configured probe-health limit. Current reading: {value:g} {unit}".strip(),
                }
            )
        elif isinstance(last_jumps, dict):
            last_jumps.pop(sensor_id, None)

    temp = sensors.get("temp")
    sump_temp = sensors.get("sump_temp")
    if isinstance(temp, dict) and isinstance(sump_temp, dict):
        temp_value = _sensor_numeric_value(hass, temp)
        sump_value = _sensor_numeric_value(hass, sump_temp)
        if temp_value is not None and sump_value is not None and abs(temp_value - sump_value) > mismatch_c:
            items.append(
                {
                    "id": "temp",
                    "severity": "warning",
                    "title": "Display and sump temperature disagree",
                    "message": f"Display and sump probes differ by {abs(temp_value - sump_value):g} °C.",
                }
            )

    return items


def _store_sensor_health_values(hass: HomeAssistant, config: dict[str, Any]) -> None:
    sensor_health = config.get("sensorHealth", {})
    sensors = config.get("sensors", {})
    if (
        not isinstance(sensor_health, dict)
        or not sensor_health.get("enabled", False)
        or not isinstance(sensors, dict)
    ):
        return
    last_values = sensor_health.setdefault("lastValues", {})
    if not isinstance(last_values, dict):
        last_values = {}
        sensor_health["lastValues"] = last_values
    now = datetime.now(timezone.utc).isoformat()
    for sensor_id, sensor in sensors.items():
        if not isinstance(sensor, dict) or _sensor_kind(sensor_id, sensor) == "binary":
            continue
        value = _sensor_numeric_value(hass, sensor)
        if value is None:
            continue
        last_values[sensor_id] = {"value": value, "updatedAt": now}


def _severity_rank(severity: str) -> int:
    return {"ok": 0, "unknown": 1, "warning": 2, "critical": 3}.get(severity, 0)


def _active_alert_items(
    hass: HomeAssistant, config: dict[str, Any], *, now_local: datetime | None = None
) -> list[dict[str, str]]:
    by_sensor: dict[str, dict[str, str]] = {}
    for item in [*_sensor_alert_items(hass, config, now_local=now_local), *_sensor_health_items(hass, config)]:
        sensor_id = item.get("id")
        if not sensor_id:
            continue
        previous = by_sensor.get(sensor_id)
        if previous is None or _severity_rank(item.get("severity", "ok")) > _severity_rank(
            previous.get("severity", "ok")
        ):
            by_sensor[sensor_id] = item
    return list(by_sensor.values())


def _alert_acknowledged(config: dict[str, Any], sensor_id: str) -> bool:
    escalation = config.get("alertEscalation", {})
    acknowledged = escalation.get("acknowledged", {}) if isinstance(escalation, dict) else {}
    return isinstance(acknowledged, dict) and sensor_id in acknowledged


def _watchdog_status(config: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    watchdog = config.get("watchdog", {})
    if not isinstance(watchdog, dict) or not watchdog.get("enabled", True):
        return {"status": "disabled", "lastHeartbeat": "", "missed": False, "nextDue": ""}
    now = now or datetime.now(timezone.utc)
    heartbeat = _parse_datetime(watchdog.get("lastHeartbeat"))
    every_hours = int(watchdog.get("heartbeatEveryHours", 24))
    missed_after = int(watchdog.get("missedAfterHours", 30))
    if heartbeat is None:
        return {"status": "unknown", "lastHeartbeat": "", "missed": False, "nextDue": ""}
    missed = now - heartbeat > timedelta(hours=missed_after)
    next_due = heartbeat + timedelta(hours=every_hours)
    return {
        "status": "critical" if missed else "ok",
        "lastHeartbeat": heartbeat.isoformat(),
        "missed": missed,
        "nextDue": next_due.isoformat(),
    }


def _trust_item(key: str, label: str, status: str, detail: str) -> dict[str, str]:
    return {"key": key, "label": label, "status": status, "detail": detail}


def _trust_check_summary(
    hass: HomeAssistant, config: dict[str, Any], *, update: bool = False
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    items: list[dict[str, str]] = []
    sensors = config.get("sensors", {})
    enabled_sensors = [
        (sensor_id, sensor)
        for sensor_id, sensor in sensors.items()
        if isinstance(sensor, dict) and sensor.get("enabled", False)
    ] if isinstance(sensors, dict) else []
    mapped_sensors = [
        (sensor_id, sensor)
        for sensor_id, sensor in enabled_sensors
        if _normalise_entity_id(sensor.get("entity_id"))
    ]
    active_alerts = _active_alert_items(hass, config)
    critical_alerts = [item for item in active_alerts if item.get("severity") == "critical"]
    warning_alerts = [item for item in active_alerts if item.get("severity") == "warning"]
    if critical_alerts:
        items.append(_trust_item("sensors", "Sensor trust", "critical", f"{len(critical_alerts)} critical sensor alert(s) active."))
    elif warning_alerts:
        items.append(_trust_item("sensors", "Sensor trust", "warning", f"{len(warning_alerts)} sensor warning(s) active."))
    elif enabled_sensors and len(mapped_sensors) == len(enabled_sensors):
        items.append(_trust_item("sensors", "Sensor trust", "ok", f"{len(mapped_sensors)}/{len(enabled_sensors)} enabled sensors mapped and reporting within current rules."))
    else:
        items.append(_trust_item("sensors", "Sensor trust", "warning", f"{len(mapped_sensors)}/{len(enabled_sensors)} enabled sensors mapped."))

    validation = _validate_config(hass, config)
    missing = validation.get("missing_entities", [])
    armed_unavailable = validation.get("armed_unavailable", [])
    if armed_unavailable:
        items.append(_trust_item("mappings", "Unsafe mappings", "critical", f"{len(armed_unavailable)} armed device(s) are unavailable."))
    elif missing:
        items.append(_trust_item("mappings", "Unsafe mappings", "warning", f"{len(missing)} mapped entity/entities need review."))
    else:
        items.append(_trust_item("mappings", "Unsafe mappings", "ok", "No missing mapped entities or armed unavailable devices found."))

    alert_config = config.get("alerts", {})
    escalation = config.get("alertEscalation", {})
    watchdog = config.get("watchdog", {})
    has_persistent = isinstance(alert_config, dict) and alert_config.get("persistentNotifications", False)
    has_escalation_target = isinstance(escalation, dict) and bool(escalation.get("notifyTarget"))
    notification_test = (
        watchdog.get("lastNotificationTest")
        if isinstance(watchdog, dict) and isinstance(watchdog.get("lastNotificationTest"), str)
        else ""
    )
    if has_persistent or has_escalation_target:
        state = "ok" if notification_test else "warning"
        detail = "Notification path configured"
        if not notification_test:
            detail += ", but no test has been recorded."
        items.append(_trust_item("notifications", "Notification path", state, detail))
    else:
        items.append(_trust_item("notifications", "Notification path", "warning", "No persistent notification or escalation target is configured."))

    heartbeat_status = _watchdog_status(config, now)
    if heartbeat_status["status"] == "disabled":
        items.append(_trust_item("heartbeat", "Heartbeat", "warning", "Watchdog heartbeat is disabled."))
    elif heartbeat_status["status"] == "critical":
        items.append(_trust_item("heartbeat", "Heartbeat", "critical", "OpenReef missed its configured heartbeat window."))
    elif heartbeat_status["status"] == "ok":
        items.append(_trust_item("heartbeat", "Heartbeat", "ok", f"Last heartbeat {heartbeat_status['lastHeartbeat']}."))
    else:
        items.append(_trust_item("heartbeat", "Heartbeat", "warning", "No heartbeat has been recorded yet."))

    cameras = config.get("cameras", {})
    mapped_cameras = [
        camera
        for camera in cameras.values()
        if isinstance(camera, dict) and _normalise_entity_id(camera.get("entity_id"))
    ] if isinstance(cameras, dict) else []
    unavailable_cameras = [
        camera
        for camera in mapped_cameras
        if (
            hass.states.get(_normalise_entity_id(camera.get("entity_id"))) is None
            or hass.states.get(_normalise_entity_id(camera.get("entity_id"))).state in UNAVAILABLE_STATES
        )
    ]
    if unavailable_cameras:
        items.append(_trust_item("cameras", "Camera reachability", "warning", f"{len(unavailable_cameras)} mapped camera(s) are unavailable."))
    elif mapped_cameras:
        items.append(_trust_item("cameras", "Camera reachability", "ok", f"{len(mapped_cameras)} mapped camera(s) reachable."))
    else:
        items.append(_trust_item("cameras", "Camera reachability", "unknown", "No camera is mapped, so incident clips cannot be proven yet."))

    # Vision trust item only exists when the feature is enabled — a tester who
    # has no Frigate/MQTT never sees a line about hardware they don't own.
    vision_trust_cfg = config.get("vision", {})
    if isinstance(vision_trust_cfg, dict) and vision_trust_cfg.get("enabled"):
        vision_store = hass.data.get(DOMAIN)
        vision_store = vision_store if isinstance(vision_store, dict) else {}
        vision_runtime = vision_store.get(VISION_RUNTIME)
        last_event_at = vision_runtime.get("lastEventAt") if isinstance(vision_runtime, dict) else None
        vision_arm_task = vision_store.get(VISION_ARM_TASK)
        if vision_store.get(VISION_UNSUB) is None:
            if vision_arm_task is not None and not vision_arm_task.done():
                # Arming is a background task (the broker may take ~50s at boot);
                # don't report a scary false warning on the very save that
                # enabled vision.
                items.append(_trust_item("vision", "Vision (Frigate)", "unknown", "Connecting to the MQTT broker…"))
            else:
                items.append(_trust_item("vision", "Vision (Frigate)", "warning", "Vision is enabled but MQTT is not connected; tank intelligence is idle."))
        elif last_event_at is None:
            items.append(_trust_item("vision", "Vision (Frigate)", "unknown", "Subscribed to Frigate events; none received yet."))
        else:
            event_age_s = dt_util.utcnow().timestamp() - last_event_at
            if event_age_s < 3600:
                items.append(_trust_item("vision", "Vision (Frigate)", "ok", "Receiving Frigate detection events."))
            else:
                items.append(_trust_item("vision", "Vision (Frigate)", "warning", f"No Frigate events for {int(event_age_s // 3600)}h — camera or NVR may be down."))

    captures = config.get("captures", [])
    alert_history = config.get("alerts", {}).get("history", []) if isinstance(config.get("alerts"), dict) else []
    if isinstance(captures, list) or isinstance(alert_history, list):
        items.append(_trust_item("recorder", "Incident history", "ok", "OpenReef local alert/capture history store is present."))
    else:
        items.append(_trust_item("recorder", "Incident history", "unknown", "OpenReef could not verify the local incident history store."))

    trust = config.get("trustCheck", {})
    backup_review = (
        _parse_datetime(trust.get("lastBackupReview"))
        if isinstance(trust, dict)
        else None
    )
    if backup_review is None:
        items.append(_trust_item("backup", "Backup review", "unknown", "No backup review has been recorded in OpenReef."))
    elif now - backup_review > timedelta(days=14):
        items.append(_trust_item("backup", "Backup review", "warning", "Backup review is older than 14 days."))
    else:
        items.append(_trust_item("backup", "Backup review", "ok", "Backup review recorded within the last 14 days."))

    equipment = config.get("equipment", {})
    edge_failsafes = config.get("edgeFailsafes", {})
    required_failsafes: set[str] = set()
    if isinstance(equipment, dict):
        for equipment_id, mapped in equipment.items():
            if not isinstance(mapped, dict) or not mapped.get("armed", False):
                continue
            profile = _equipment_profile_for_config(equipment_id, mapped)
            if profile == "heater":
                required_failsafes.add("heater")
            elif profile == "ato":
                required_failsafes.add("ato")
            elif profile == "return_pump":
                required_failsafes.add("returnPump")
    if not required_failsafes:
        items.append(_trust_item("edge_failsafes", "Edge failsafes", "unknown", "No armed heater, ATO, or return pump needs an on-device failsafe yet."))
    elif not isinstance(edge_failsafes, dict) or not edge_failsafes.get("enabled", False):
        items.append(_trust_item("edge_failsafes", "Edge failsafes", "warning", "Life-support equipment is armed, but ESPHome/on-device failsafes are not marked as reviewed."))
    else:
        missing_failsafes = sorted(
            label
            for key, label in (
                ("heater", "heater"),
                ("ato", "ATO"),
                ("returnPump", "return pump"),
            )
            if key in required_failsafes and not edge_failsafes.get(key, False)
        )
        review_time = _parse_datetime(edge_failsafes.get("lastReviewed"))
        if missing_failsafes:
            items.append(_trust_item("edge_failsafes", "Edge failsafes", "warning", "Missing reviewed on-device failsafe(s): " + ", ".join(missing_failsafes) + "."))
        elif review_time is None:
            items.append(_trust_item("edge_failsafes", "Edge failsafes", "warning", "On-device failsafes are marked, but no review date is recorded."))
        elif now - review_time > timedelta(days=180):
            items.append(_trust_item("edge_failsafes", "Edge failsafes", "warning", "On-device failsafe review is older than 180 days."))
        else:
            items.append(_trust_item("edge_failsafes", "Edge failsafes", "ok", "Required heater/ATO/return-pump failsafes are marked as reviewed."))

    worst = max(items, key=lambda item: _severity_rank(item["status"]))["status"] if items else "unknown"
    summary = {"status": worst, "checkedAt": now.isoformat(), "items": items}
    if update:
        trust_config = config.setdefault("trustCheck", {})
        if isinstance(trust_config, dict):
            trust_config["lastRun"] = summary["checkedAt"]
            trust_config["lastStatus"] = worst
    return summary


def _incident_events_near(
    events: list[dict[str, Any]], timestamp: datetime, window_minutes: int
) -> list[dict[str, Any]]:
    start = timestamp - timedelta(minutes=window_minutes)
    end = timestamp + timedelta(minutes=window_minutes)
    near: list[dict[str, Any]] = []
    for event in events:
        parsed = _parse_datetime(event.get("timestamp") or event.get("startedAt"))
        if parsed is not None and start <= parsed <= end:
            near.append(event)
    return near[:12]


def _reef_replay_incidents(config: dict[str, Any]) -> list[dict[str, Any]]:
    replay = config.get("reefReplay", {})
    if not isinstance(replay, dict) or not replay.get("enabled", True):
        return []
    window = int(replay.get("incidentWindowMinutes", 20))
    retention = int(replay.get("retention", 25))
    alerts = config.get("alerts", {})
    history = alerts.get("history", []) if isinstance(alerts, dict) else []
    activity = config.get("activity", [])
    captures = config.get("captures", [])
    feeds = config.get("feedSessions", [])
    event_pool: list[dict[str, Any]] = []
    if isinstance(activity, list):
        event_pool.extend(
            {**event, "source": "activity"}
            for event in activity
            if isinstance(event, dict)
        )
    if isinstance(captures, list):
        event_pool.extend(
            {**event, "source": "capture", "timestamp": event.get("timestamp") or event.get("startedAt")}
            for event in captures
            if isinstance(event, dict)
        )
    if isinstance(feeds, list):
        event_pool.extend(
            {**event, "source": "feed", "timestamp": event.get("startedAt")}
            for event in feeds
            if isinstance(event, dict)
        )

    incidents: list[dict[str, Any]] = []
    if isinstance(history, list):
        for alert in history:
            if not isinstance(alert, dict):
                continue
            timestamp = _parse_datetime(alert.get("timestamp"))
            if timestamp is None:
                continue
            incidents.append(
                {
                    "id": f"alert-{alert.get('sensor_id', 'sensor')}-{int(timestamp.timestamp())}",
                    "timestamp": timestamp.isoformat(),
                    "title": alert.get("title") or alert.get("label") or "OpenReef alert",
                    "severity": alert.get("state") or "warning",
                    "message": alert.get("message") or "",
                    "events": _incident_events_near(event_pool, timestamp, window),
                }
            )
    if not incidents:
        for event in event_pool[:retention]:
            timestamp = _parse_datetime(event.get("timestamp") or event.get("startedAt"))
            if timestamp is None:
                continue
            incidents.append(
                {
                    "id": f"{event.get('source', 'event')}-{int(timestamp.timestamp())}",
                    "timestamp": timestamp.isoformat(),
                    "title": event.get("message") or event.get("label") or "OpenReef event",
                    "severity": event.get("type") or "info",
                    "message": event.get("message") or "",
                    "events": [event],
                }
            )
    return incidents[:retention]


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


def _sync_alert_state(
    hass: HomeAssistant, config: dict[str, Any], *, now_local: datetime | None = None
) -> list[dict[str, str]]:
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

    active_items = {item["id"]: item for item in _active_alert_items(hass, config, now_local=now_local)}
    previous_states = alert_config.get("lastStates", {})
    if not isinstance(previous_states, dict):
        previous_states = {}
    escalation = config.get("alertEscalation", {})
    acknowledged = (
        escalation.get("acknowledged", {})
        if isinstance(escalation, dict) and isinstance(escalation.get("acknowledged"), dict)
        else {}
    )
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
        elif _sensor_low_suppressed(config, sensor, now_local):
            # Lights are off — we can't judge a light-dependent sensor now, so hold the
            # last known state rather than flapping resolved->alert at every dusk/dawn.
            carried = previous_states.get(sensor_id)
            if carried is not None:
                next_states[sensor_id] = carried
            continue
        else:
            state = "resolved"
            title = f"{label} resolved"
            message = "Reading is back inside the configured alert behaviour."
            acknowledged.pop(sensor_id, None)

        previous = previous_states.get(sensor_id)
        if previous != state and (previous is not None or state != "resolved"):
            _append_alert_history(alert_config, sensor_id, label, state, title, message)
            transitions.append(
                {"sensor_id": sensor_id, "label": label, "state": state, "title": title}
            )
        next_states[sensor_id] = state

    alert_config["lastStates"] = next_states
    _store_sensor_health_values(hass, config)
    return transitions


def _ints_in_range(value: Any, low: int, high: int) -> list[int]:
    """Coerce a value into a sorted, de-duplicated list of ints within [low, high]."""
    out: list[int] = []
    if isinstance(value, list):
        for item in value:
            try:
                number = int(item)
            except (TypeError, ValueError):
                continue
            if low <= number <= high and number not in out:
                out.append(number)
    return sorted(out)


def _maintenance_last_done(entries: Any) -> datetime | None:
    """Latest non-skipped completion datetime (UTC) for a task, or None.

    Skipped entries are logged history but never count as 'done', so they don't reset
    a task's cadence — matching the panel's _maintenanceLatestDone.
    """
    if not isinstance(entries, list):
        return None
    best: datetime | None = None
    for item in entries:
        if not isinstance(item, dict) or item.get("skipped"):
            continue
        parsed = _parse_datetime(item.get("timestamp") or item.get("date"))
        if parsed is not None and (best is None or parsed > best):
            best = parsed
    return best


def _maintenance_scheduled_dates(task: dict[str, Any], today):
    """Return (last, prev) scheduled dates <= today for a fixed-schedule task, or
    (None, None) if it has no schedule. Weekdays are Mon=0..Sun=6 (date.weekday())."""
    days = set(task.get("scheduleDays") or [])
    month_days = set(task.get("scheduleMonthDays") or [])
    if not days and not month_days:
        return None, None
    found = []
    cursor = today
    for _ in range(366):
        if cursor.weekday() in days or cursor.day in month_days:
            found.append(cursor)
            if len(found) == 2:
                break
        cursor = cursor - timedelta(days=1)
    return (found[0] if found else None), (found[1] if len(found) > 1 else None)


def _maintenance_task_state(
    task: dict[str, Any], last_done: datetime | None, now: datetime
) -> str:
    """'ok' | 'warning' (due) | 'critical' (overdue) | 'unknown'. Lockstep with the
    panel's _maintenanceDueState — keep both implementations in sync."""
    if task.get("scheduleMode") == "fixed":
        tz = now.tzinfo or timezone.utc
        today = now.astimezone(tz).date()
        last_sched, prev_sched = _maintenance_scheduled_dates(task, today)
        if last_sched is None:
            return "unknown"
        done_date = last_done.astimezone(tz).date() if last_done is not None else None
        if done_date is not None and done_date >= last_sched:
            return "ok"
        if prev_sched is not None and (done_date is None or done_date < prev_sched):
            return "critical"
        return "warning"
    # interval mode (default): age since last done vs cadence / critical thresholds.
    # cadenceHours > 0 switches the same comparison to an hour clock (hatch chores).
    if last_done is None:
        return "warning"
    cadence_h = task.get("cadenceHours")
    if isinstance(cadence_h, (int, float)) and not isinstance(cadence_h, bool) and cadence_h > 0:
        age_h = (now - last_done).total_seconds() / 3600.0
        if age_h > task.get("criticalAfterHours", cadence_h * 2):
            return "critical"
        if age_h > cadence_h:
            return "warning"
        return "ok"
    cadence = task.get("cadenceDays", 7)
    age_days = (now - last_done).total_seconds() / 86400.0
    if age_days > task.get("criticalAfterDays", cadence * 2):
        return "critical"
    if age_days > cadence:
        return "warning"
    return "ok"


def _maintenance_due_items(
    config: dict[str, Any], now: datetime | None = None
) -> list[dict[str, str]]:
    """Backend mirror of the panel's due logic: enabled, non-snoozed tasks that are
    due (warning) or overdue (critical). Drives HA-native reminders so they fire even
    when the panel is closed. Returns [{id, label, severity, title, message}]."""
    maintenance = config.get("maintenance", {})
    if not isinstance(maintenance, dict) or not maintenance.get("enabled", True):
        return []
    tasks = maintenance.get("tasks", {})
    if not isinstance(tasks, dict):
        return []
    completions = maintenance.get("completions", {})
    if not isinstance(completions, dict):
        completions = {}
    now = now or datetime.now(timezone.utc)
    items: list[dict[str, str]] = []
    for task_id, task in tasks.items():
        if not isinstance(task, dict) or not task.get("enabled", False):
            continue
        snoozed = _parse_datetime(task.get("snoozedUntil"))
        if snoozed is not None and snoozed > now:
            continue
        last_done = _maintenance_last_done(completions.get(task_id))
        state = _maintenance_task_state(task, last_done, now)
        if state not in ("warning", "critical"):
            continue
        label = str(task.get("label") or task_id)
        if state == "critical":
            title = f"{label} overdue"
            message = f"{label} is overdue — give it some attention."
        else:
            title = f"{label} due"
            message = f"{label} is due for maintenance."
        items.append(
            {
                "id": task_id,
                "label": label,
                "severity": state,
                "title": title,
                "message": message,
            }
        )
    return items


async def _async_sync_alert_notifications(
    hass: HomeAssistant, config: dict[str, Any]
) -> bool:
    changed = False
    sensors = config.get("sensors", {})
    sensor_ids = list(sensors) if isinstance(sensors, dict) else list(MVP_SENSORS)
    alert_config = config.get("alerts", {})
    enabled = isinstance(alert_config, dict) and alert_config.get(
        "persistentNotifications", False
    )
    critical_only = not isinstance(alert_config, dict) or alert_config.get(
        "notifyCriticalOnly", True
    )
    all_alert_items = _active_alert_items(hass, config)
    alert_items = all_alert_items if enabled else []
    active_ids = {
        item["id"]
        for item in alert_items
        if not critical_only or item["severity"] == "critical"
        if not _alert_acknowledged(config, item["id"])
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
        if _alert_acknowledged(config, item["id"]):
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

    if await _async_sync_alert_escalation(hass, config, all_alert_items):
        changed = True

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

    # Maintenance reminders — in-HA persistent notifications for due/overdue tasks.
    # Idempotent + re-synced on every save, so marking a task done clears it instantly.
    # The once-daily phone push is fired separately by _handle_maintenance_reminder.
    maintenance = config.get("maintenance", {})
    reminders = maintenance.get("reminders", {}) if isinstance(maintenance, dict) else {}
    maint_tasks = maintenance.get("tasks", {}) if isinstance(maintenance, dict) else {}
    maintenance_enabled = (
        isinstance(reminders, dict)
        and reminders.get("enabled", True)
        and reminders.get("persistent", True)
    )
    maintenance_due = _maintenance_due_items(config) if maintenance_enabled else []
    maintenance_notify_ids = {
        item["id"]
        for item in maintenance_due
        if isinstance(maint_tasks.get(item["id"]), dict)
        and maint_tasks[item["id"]].get("notify", True)
    }
    for task_id in list(maint_tasks) if isinstance(maint_tasks, dict) else []:
        if task_id not in maintenance_notify_ids:
            await hass.services.async_call(
                "persistent_notification",
                "dismiss",
                {"notification_id": f"openreef_maintenance_{task_id}"},
                blocking=False,
            )
    for item in maintenance_due:
        if item["id"] not in maintenance_notify_ids:
            continue
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "notification_id": f"openreef_maintenance_{item['id']}",
                "title": f"OpenReef: {item['title']}",
                "message": item["message"],
            },
            blocking=False,
        )

    return changed


async def _async_toggle_escalation_outputs(
    hass: HomeAssistant, config: dict[str, Any], turn_on: bool
) -> bool:
    escalation = config.get("alertEscalation", {})
    if not isinstance(escalation, dict):
        return False
    changed = False
    for field in ("sirenEntityId", "lightEntityId"):
        entity_id = _normalise_entity_id(escalation.get(field))
        if not entity_id:
            continue
        await hass.services.async_call(
            _domain(entity_id),
            "turn_on" if turn_on else "turn_off",
            {ATTR_ENTITY_ID: entity_id},
            blocking=False,
        )
        changed = True
    return changed


async def _async_sync_alert_escalation(
    hass: HomeAssistant, config: dict[str, Any], alert_items: list[dict[str, str]]
) -> bool:
    escalation = config.get("alertEscalation", {})
    if not isinstance(escalation, dict):
        return False
    changed = False
    now = datetime.now(timezone.utc)
    active_items = [
        item
        for item in alert_items
        if (not escalation.get("criticalOnly", True) or item.get("severity") == "critical")
        and not _alert_acknowledged(config, item.get("id", ""))
    ]

    if not escalation.get("enabled", False):
        if escalation.get("outputsActive", False):
            await _async_toggle_escalation_outputs(hass, config, False)
            escalation["outputsActive"] = False
            changed = True
        return changed

    last_escalated = escalation.setdefault("lastEscalated", {})
    if not isinstance(last_escalated, dict):
        last_escalated = {}
        escalation["lastEscalated"] = last_escalated
        changed = True
    repeat_minutes = int(escalation.get("repeatMinutes", 30))
    notify_target = str(escalation.get("notifyTarget", "")).strip()
    for item in active_items:
        sensor_id = item.get("id", "")
        previous = _parse_datetime(last_escalated.get(sensor_id))
        due = previous is None or now - previous >= timedelta(minutes=repeat_minutes)
        if not due:
            continue
        message = item.get("message") or item.get("title") or "OpenReef alert"
        if notify_target:
            await hass.services.async_call(
                "notify",
                notify_target,
                {"title": f"OpenReef: {item.get('title', 'Alert')}", "message": message},
                blocking=False,
            )
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "notification_id": f"openreef_escalation_{sensor_id}",
                "title": f"OpenReef escalation: {item.get('title', 'Alert')}",
                "message": f"{message}\n\nAcknowledge this alert in OpenReef to stop escalation repeats.",
            },
            blocking=False,
        )
        last_escalated[sensor_id] = now.isoformat()
        changed = True

    if active_items and not escalation.get("outputsActive", False):
        if await _async_toggle_escalation_outputs(hass, config, True):
            escalation["outputsActive"] = True
            changed = True
    elif not active_items and escalation.get("outputsActive", False):
        await _async_toggle_escalation_outputs(hass, config, False)
        escalation["outputsActive"] = False
        changed = True

    for sensor_id in list(last_escalated):
        if sensor_id not in {item.get("id") for item in alert_items}:
            last_escalated.pop(sensor_id, None)
            changed = True

    return changed


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


def _clear_equipment_timers(hass: HomeAssistant) -> None:
    timers = hass.data.setdefault(DOMAIN, {}).pop(EQUIPMENT_TIMER_UNSUBS, {})
    if isinstance(timers, dict):
        for unsub in timers.values():
            if unsub is not None:
                unsub()


def _clear_max_off_timers(hass: HomeAssistant) -> None:
    timers = hass.data.setdefault(DOMAIN, {}).pop(MAX_OFF_UNSUBS, {})
    if isinstance(timers, dict):
        for unsub in timers.values():
            if unsub is not None:
                unsub()


def _clear_mode_verify(hass: HomeAssistant) -> None:
    unsub = hass.data.setdefault(DOMAIN, {}).pop(MODE_VERIFY_UNSUB, None)
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


def _clear_feedwatch(hass: HomeAssistant) -> None:
    unsub = hass.data.setdefault(DOMAIN, {}).pop(FEEDWATCH_UNSUB, None)
    if unsub is not None:
        unsub()


def _clear_watchdog(hass: HomeAssistant) -> None:
    unsub = hass.data.setdefault(DOMAIN, {}).pop(WATCHDOG_UNSUB, None)
    if unsub is not None:
        unsub()


def _persist_entry_config(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any]
) -> dict[str, Any]:
    normalised = _normalise_core_config(config)
    options = dict(entry.options)
    options[CONF_SETTINGS] = normalised
    hass.config_entries.async_update_entry(entry, options=options)
    return normalised


async def _async_run_watchdog(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry,
    config: dict[str, Any] | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    config = config or _config_from_entry(entry)
    watchdog = config.get("watchdog", {})
    if not isinstance(watchdog, dict) or not watchdog.get("enabled", True):
        return config

    now = datetime.now(timezone.utc)
    heartbeat = _parse_datetime(watchdog.get("lastHeartbeat"))
    every_hours = int(watchdog.get("heartbeatEveryHours", 24))
    missed_after = int(watchdog.get("missedAfterHours", 30))
    due = force or heartbeat is None or now - heartbeat >= timedelta(hours=every_hours)
    missed = heartbeat is not None and now - heartbeat > timedelta(hours=missed_after)
    if not due and not missed:
        return config

    if missed:
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "notification_id": "openreef_watchdog_missed",
                "title": "OpenReef heartbeat recovered late",
                "message": (
                    f"OpenReef last checked in at {heartbeat.isoformat()}. "
                    "Review Home Assistant uptime, restart history, and notification delivery."
                ),
            },
            blocking=False,
        )
        watchdog["lastMissedAlert"] = now.isoformat()
        _append_activity(config, "OpenReef heartbeat recovered after a missed window", "warning")

    watchdog["lastCheck"] = now.isoformat()
    if watchdog.get("heartbeatEnabled", True):
        watchdog["lastHeartbeat"] = now.isoformat()
        target = str(watchdog.get("notifyTarget", "")).strip()
        if target:
            await hass.services.async_call(
                "notify",
                target,
                {
                    "title": "OpenReef heartbeat OK",
                    "message": "OpenReef completed its scheduled trust heartbeat.",
                },
                blocking=False,
            )
        _append_activity(config, "OpenReef heartbeat OK", "info")

    _trust_check_summary(hass, config, update=True)
    return _persist_entry_config(hass, entry, config)


async def _async_schedule_watchdog(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry | None,
    config: dict[str, Any] | None = None,
) -> None:
    _clear_watchdog(hass)
    if entry is None:
        return
    config = config or _config_from_entry(entry)
    watchdog = config.get("watchdog", {})
    if not isinstance(watchdog, dict) or not watchdog.get("enabled", True):
        return

    await _async_run_watchdog(hass, entry, config)

    async def _handle_watchdog(now: datetime) -> None:
        latest_entry = _first_entry(hass)
        if latest_entry is None or latest_entry.entry_id != entry.entry_id:
            _clear_watchdog(hass)
            return
        await _async_run_watchdog(hass, latest_entry)

    hass.data.setdefault(DOMAIN, {})[WATCHDOG_UNSUB] = async_track_time_interval(
        hass, _handle_watchdog, timedelta(minutes=30)
    )


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


def _clear_maintenance_reminders(hass: HomeAssistant) -> None:
    unsub = hass.data.setdefault(DOMAIN, {}).pop(MAINTENANCE_REMINDER_UNSUB, None)
    if unsub is not None:
        unsub()


def _maintenance_reminder_time(config: dict[str, Any]) -> tuple[int, int]:
    maintenance = config.get("maintenance", {})
    reminders = maintenance.get("reminders", {}) if isinstance(maintenance, dict) else {}
    value = (
        reminders.get("time", MAINTENANCE_REMINDER_DEFAULT_TIME)
        if isinstance(reminders, dict)
        else MAINTENANCE_REMINDER_DEFAULT_TIME
    )
    if not (isinstance(value, str) and re.match(r"^([01]\d|2[0-3]):[0-5]\d$", value)):
        value = MAINTENANCE_REMINDER_DEFAULT_TIME
    hour, _, minute = value.partition(":")
    return int(hour), int(minute)


async def _async_fire_maintenance_reminder(
    hass: HomeAssistant, entry: OpenReefConfigEntry, now: datetime
) -> None:
    """Re-sync maintenance persistent notifications, then fire one digest phone push
    for due/overdue tasks. Called once per daily tick (naturally rate-limited) and
    extracted from the scheduler so it's unit-testable."""
    latest_config = _config_from_entry(entry)
    # Keep the in-HA persistent notifications matching current due state.
    if await _async_sync_alert_notifications(hass, latest_config):
        _persist_entry_config(hass, entry, latest_config)
    maintenance = latest_config.get("maintenance", {})
    reminders = maintenance.get("reminders", {}) if isinstance(maintenance, dict) else {}
    if not isinstance(reminders, dict) or not reminders.get("enabled", True):
        return
    tasks = maintenance.get("tasks", {}) if isinstance(maintenance, dict) else {}
    push_items = [
        item
        for item in _maintenance_due_items(latest_config, now)
        if isinstance(tasks.get(item["id"]), dict)
        and tasks[item["id"]].get("notify", True)
    ]
    last_store = hass.data.setdefault(DOMAIN, {}).setdefault(
        MAINTENANCE_REMINDER_LAST, {}
    )
    previous_ids = last_store.get(entry.entry_id, set())
    current_ids = {item["id"] for item in push_items}
    last_store[entry.entry_id] = current_ids
    if not push_items:
        return
    labels = ", ".join(item["label"] for item in push_items)
    # One digest phone push per daily tick while tasks are due (the intended nag).
    target = str(reminders.get("notifyTarget", "")).strip()
    if target:
        overdue = sum(1 for item in push_items if item["severity"] == "critical")
        summary = f"{len(push_items)} reef task{'s' if len(push_items) != 1 else ''} due"
        if overdue:
            summary += f" ({overdue} overdue)"
        await hass.services.async_call(
            "notify",
            target,
            {"title": f"OpenReef: {summary}", "message": labels},
            blocking=False,
        )
    # Only log to the activity feed when the due set grows, so a long-overdue task
    # can't flood the (capped) history with a line every single day.
    new_ids = current_ids - previous_ids
    if new_ids:
        new_labels = ", ".join(
            item["label"] for item in push_items if item["id"] in new_ids
        )
        _append_activity(latest_config, f"Maintenance due: {new_labels}", "info")
        options = dict(entry.options)
        options[CONF_SETTINGS] = _normalise_core_config(latest_config)
        hass.config_entries.async_update_entry(entry, options=options)


async def _async_schedule_maintenance_reminders(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry | None,
    config: dict[str, Any] | None = None,
) -> None:
    """Register a single daily tick that re-evaluates due/overdue maintenance tasks
    and fires one digest phone push. Re-registered on every save (so the configured
    reminder time takes effect), mirroring the wavemaker reminder scheduler. The single
    daily fire is the anti-spam control — directly answers the apps' 'pops up every
    second' complaint."""
    _clear_maintenance_reminders(hass)
    if entry is None:
        return
    config = config or _config_from_entry(entry)
    maintenance = config.get("maintenance", {})
    reminders = maintenance.get("reminders", {}) if isinstance(maintenance, dict) else {}
    if not isinstance(reminders, dict) or not reminders.get("enabled", True):
        return

    async def _handle_maintenance_reminder(now: datetime) -> None:
        latest_entry = _first_entry(hass)
        if latest_entry is None or latest_entry.entry_id != entry.entry_id:
            return
        await _async_fire_maintenance_reminder(hass, latest_entry, now)

    hour, minute = _maintenance_reminder_time(config)
    hass.data.setdefault(DOMAIN, {})[
        MAINTENANCE_REMINDER_UNSUB
    ] = async_track_time_change(
        hass, _handle_maintenance_reminder, hour=hour, minute=minute, second=0
    )


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
            await _async_send_mode_notification(
                hass,
                latest_config,
                "openreef_mode_auto_return_blocked",
                "Auto-return to Running blocked",
                f"The timed mode could not return to Running: {err}. Equipment may still be in the mode state — review the dashboard.",
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
        if _awc_ato_suspended(config):
            return "ATO held: an automatic water change is in progress"
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
        if not block_reason and _awc_ato_suspended(latest_config):
            block_reason = "automatic water change in progress"
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


def _async_defer_issue_refresh_to_startup(hass: HomeAssistant) -> None:
    """Arm a one-shot issue refresh for STARTED + grace. Idempotent — the single
    store key holds whichever unsub is current (the listener, then the timer)."""
    store = hass.data.setdefault(DOMAIN, {})
    if store.get(ISSUE_REFRESH_UNSUB) is not None:
        return

    async def _fire(now: datetime) -> None:
        hass.data.setdefault(DOMAIN, {}).pop(ISSUE_REFRESH_UNSUB, None)
        latest_entry = _first_entry(hass)
        if latest_entry is None:
            return
        await _async_refresh_issues(hass, latest_entry)

    async def _started(_event: Any) -> None:
        # STARTED means every integration finished setting up — but network
        # devices (ESPHome nodes, controller polls) can still be connecting,
        # so give them a grace window before judging availability.
        hass.data.setdefault(DOMAIN, {})[ISSUE_REFRESH_UNSUB] = async_track_point_in_time(
            hass, _fire, datetime.now(timezone.utc) + timedelta(seconds=ISSUE_BOOT_GRACE_SECONDS)
        )

    store[ISSUE_REFRESH_UNSUB] = hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _started)


async def _async_refresh_issues(
    hass: HomeAssistant, entry: OpenReefConfigEntry | None
) -> None:
    if not getattr(hass, "is_running", True):
        # HA is still booting: entity states are not trustworthy yet. Defer the
        # first evaluation instead of raising repairs that self-clear minutes
        # later (they alarmed testers on every single update/restart).
        _async_defer_issue_refresh_to_startup(hass)
        return
    config = _config_from_entry(entry)
    validation = _validate_config(hass, config)

    if validation["missing_entities"]:
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_MISSING_ENTITIES,
            breaks_in_ha_version=None,
            is_fixable=False,
            issue_domain=DOMAIN,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_MISSING_ENTITIES,
            # Placeholders must ride translation_placeholders (as strings) —
            # `data` never reaches the frontend formatter, and the repair then
            # renders a raw formatjs MISSING_VALUE error instead of the message.
            translation_placeholders={"count": str(len(validation["missing_entities"]))},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_MISSING_ENTITIES)

    if validation["armed_unavailable"]:
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_ARMED_UNAVAILABLE,
            breaks_in_ha_version=None,
            is_fixable=False,
            issue_domain=DOMAIN,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_ARMED_UNAVAILABLE,
            translation_placeholders={"count": str(len(validation["armed_unavailable"]))},
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
    # Re-arming the AWC schedule (enable / slot-time / day edits) stamps the state so
    # the scheduler tick treats already-passed slots as not-backlog (R24): enabling a
    # schedule at 15:00 with a 02:00 slot must wait for tomorrow's 02:00, not start a
    # water change on the spot. Slot-DEFINING fields only — an amount tweak must not
    # swallow a genuinely pending slot.
    schedule_rearmed = (
        _awc_schedule_fingerprint(entry.options.get(CONF_SETTINGS))
        != _awc_schedule_fingerprint(config)
    )
    normalised = _normalise_core_config(config)
    # Every save re-stamps the completion history: whatever a client is handed from
    # here on is current as of now, which is the anchor _merge_recent_completions uses
    # when that client eventually posts the whole config back.
    normalised["maintenance"]["completionsSyncedAt"] = datetime.now(timezone.utc).isoformat()
    if schedule_rearmed:
        _awc_cfg(normalised).setdefault("state", {})["scheduleArmedAt"] = (
            datetime.now(timezone.utc).isoformat()
        )
    transitions = _sync_alert_state(hass, normalised)
    _trust_check_summary(hass, normalised, update=True)
    options = dict(entry.options)
    options[CONF_SETTINGS] = normalised
    hass.config_entries.async_update_entry(entry, options=options)
    await _async_refresh_issues(hass, entry)
    if await _async_sync_alert_notifications(hass, normalised):
        options = dict(entry.options)
        options[CONF_SETTINGS] = normalised
        hass.config_entries.async_update_entry(entry, options=options)
    await _async_schedule_mode_timer(hass, entry, normalised)
    await _async_schedule_equipment_timers(hass, entry, normalised)
    await _async_schedule_max_off_timers(hass, entry, normalised)
    await _async_schedule_mode_schedule(hass, entry, normalised)
    await _async_schedule_ato_duty_cycle(hass, entry, normalised)
    await _async_schedule_wavemaker_reminders(hass, entry, normalised)
    await _async_schedule_maintenance_reminders(hass, entry, normalised)
    await _async_schedule_timelapse(hass, entry, normalised)
    await _async_schedule_watchdog(hass, entry, normalised)
    await _async_schedule_awc(hass, entry, normalised)
    await _async_schedule_awc_scheduler(hass, entry, normalised)
    await _async_schedule_dosing_tick(hass, entry, normalised)
    await _async_schedule_spawning_tick(hass, entry, normalised)
    # The circulation chain re-arms from its persisted stamps on every save —
    # that save-driven re-arm IS how its burst legs chain (see the scheduler).
    await _async_schedule_mixing_circulation(hass, entry, normalised)
    # Same contract for the RODI draw stop leg / calibration cap.
    await _async_schedule_mixing_rodi(hass, entry, normalised)
    await _async_setup_dosing_mirror(hass, entry, normalised)
    if _dosing_channels(normalised):
        _async_kick_dosing_sync(hass, entry)
    # Fingerprint-guarded: a save that does not change the vision config is a
    # no-op here (runtime state and the MQTT subscription survive untouched).
    await _async_setup_vision(hass, entry, normalised)
    # Event-triggered camera capture on a fresh ok->warning/critical transition.
    for transition in transitions:
        if transition.get("state") == "critical":
            _dispatch_capture(hass, entry, "critical_alert", transition.get("title", "Critical alert"))
        elif transition.get("state") == "warning":
            _dispatch_capture(hass, entry, "warning_alert", transition.get("title", "Warning"))
    bus = getattr(hass, "bus", None)
    if bus is not None and hasattr(bus, "async_fire"):
        mode = normalised.get("mode", {}) if isinstance(normalised.get("mode"), dict) else {}
        bus.async_fire(
            CONFIG_UPDATED_EVENT,
            {
                "entry_id": entry.entry_id,
                "active_mode": str(mode.get("active") or "running"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
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


# --- Mode Actions V2: per-equipment timers, max-off caps, exit verification ------- #


def _clamp_seconds(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    return max(0, min(number, MODE_EQUIPMENT_TIMER_MAX_SECONDS))


def _equipment_max_off_seconds(mapped: dict[str, Any]) -> int:
    try:
        value = int(mapped.get("maxOffSeconds", 0))
    except (TypeError, ValueError):
        value = 0
    return max(0, min(value, EQUIPMENT_MAX_OFF_MAX_SECONDS))


def _normalise_equipment_timer(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce/clamp a single per-equipment timer dict. Stores durations in seconds and
    enforces the cycle phase floor. Does NOT decide enablement validity (callers/
    normalisation disable degenerate timers)."""
    timer_mode = raw.get("timerMode")
    timer_mode = timer_mode if timer_mode in {"once", "cycle"} else "once"
    on_seconds = _clamp_seconds(raw.get("onSeconds"))
    off_seconds = _clamp_seconds(raw.get("offSeconds"))
    if timer_mode == "cycle":
        on_seconds = max(MODE_EQUIPMENT_CYCLE_MIN_SECONDS, on_seconds) if on_seconds else 0
        off_seconds = max(MODE_EQUIPMENT_CYCLE_MIN_SECONDS, off_seconds) if off_seconds else 0
    return {
        "enabled": bool(raw.get("enabled", False)),
        "startDelaySeconds": _clamp_seconds(raw.get("startDelaySeconds")),
        "timerMode": timer_mode,
        "holdSeconds": _clamp_seconds(raw.get("holdSeconds")),
        "onSeconds": on_seconds,
        "offSeconds": off_seconds,
    }


def _equipment_timer_active(timer: dict[str, Any]) -> bool:
    """True when a normalised timer is enabled AND has a usable duration."""
    if not timer.get("enabled"):
        return False
    if timer.get("timerMode") == "cycle":
        return timer.get("onSeconds", 0) > 0 and timer.get("offSeconds", 0) > 0
    return timer.get("holdSeconds", 0) > 0


async def _async_send_mode_notification(
    hass: HomeAssistant,
    config: dict[str, Any],
    notification_id: str,
    title: str,
    message: str,
) -> None:
    """Create an in-HA persistent notification and, if configured, a phone push.
    Mirrors the maintenance/watchdog notification pattern. Best-effort by contract:
    several callers sit MID-TRANSITION inside the AWC lock (pumps stopped, volume not
    yet credited/saved) — a stale notify target raising ServiceNotFound there would
    discard the whole state transition, so a failed notification is logged, never
    raised."""
    try:
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "notification_id": notification_id,
                "title": f"OpenReef: {title}",
                "message": message,
            },
            blocking=False,
        )
    except Exception:  # noqa: BLE001 - notifications must never break a state transition
        _LOGGER.exception("Failed to create persistent notification %s", notification_id)
    alerts = config.get("alerts", {})
    target = (
        str(alerts.get("modeNotifyTarget", "")).strip()
        if isinstance(alerts, dict)
        else ""
    )
    if target:
        try:
            await hass.services.async_call(
                "notify",
                target,
                {"title": f"OpenReef: {title}", "message": message},
                blocking=False,
            )
        except Exception:  # noqa: BLE001 - a removed notify target must not raise here
            _LOGGER.warning("Notify target %s failed for %s", target, notification_id)


def _update_max_off_state(
    mode_state: dict[str, Any],
    mapped: dict[str, Any],
    equipment_id: str,
    switch_entity: str,
    target_state: str,
) -> None:
    """Arm (on a fresh off) or cancel (on an on) a device's max-off safety cap in the
    persisted mode runtime state."""
    timers = mode_state.setdefault("maxOffTimers", {})
    if not isinstance(timers, dict):
        timers = {}
        mode_state["maxOffTimers"] = timers
    if target_state == "off":
        seconds = _equipment_max_off_seconds(mapped)
        if seconds > 0 and switch_entity and equipment_id not in timers:
            timers[equipment_id] = {
                "fireAt": (
                    datetime.now(timezone.utc) + timedelta(seconds=seconds)
                ).isoformat(),
                "switch_entity_id": switch_entity,
            }
    elif target_state == "on":
        timers.pop(equipment_id, None)


async def _async_timer_drive_switch(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry,
    config: dict[str, Any],
    equipment_id: str,
    mapped: dict[str, Any],
    target_state: str,
    context: Any,
) -> tuple[bool, str]:
    """Drive one switch for a per-equipment timer transition, re-running the SAME safety
    guards as apply-mode. Returns (driven, reason). Updates max-off cap bookkeeping."""
    switch_entity = _normalise_entity_id(mapped.get("switch_entity_id"))
    if not switch_entity:
        return (False, "No switch entity mapped")
    if target_state == "on" and _is_protected_display_wavemaker(mapped):
        return (False, "Display wavemaker automatic restart blocked")
    block_reason = _equipment_safety_block_reason(
        hass, config, equipment_id, mapped, target_state
    )
    if block_reason:
        return (False, block_reason)
    await hass.services.async_call(
        "switch",
        f"turn_{target_state}",
        {ATTR_ENTITY_ID: switch_entity},
        blocking=True,
        context=context,
    )
    if (
        target_state == "off"
        and _equipment_profile_for_config(equipment_id, mapped) == "return_pump"
    ):
        await _async_auto_off_skimmers_for_return_pump(hass, config, context)
    mode_state = config.get("mode", {})
    if isinstance(mode_state, dict):
        _update_max_off_state(mode_state, mapped, equipment_id, switch_entity, target_state)
    return (True, "")


async def _async_arm_equipment_timer(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry,
    equipment_id: str,
    state: dict[str, Any],
) -> None:
    """Arm one per-equipment timer's next transition. Mirrors
    _async_schedule_delayed_equipment_on; the on-fire callback transitions phase and
    persists, letting _async_save_config re-arm the following phase (single path)."""
    if not isinstance(state, dict) or state.get("phase") in (None, "done"):
        return
    now = datetime.now(timezone.utc)
    run_at = _parse_datetime(state.get("nextFireAt"))
    if run_at is None or run_at <= now:
        run_at = now + timedelta(seconds=1)

    key = _delayed_equipment_key(entry, equipment_id)
    store = hass.data.setdefault(DOMAIN, {}).setdefault(EQUIPMENT_TIMER_UNSUBS, {})
    old_unsub = store.pop(key, None)
    if old_unsub is not None:
        old_unsub()

    config_now = _config_from_entry(entry)
    mode_now = config_now.get("mode", {})
    mode_snapshot = mode_now.get("active") if isinstance(mode_now, dict) else None

    async def _handle(_now: datetime) -> None:
        timer_store = hass.data.setdefault(DOMAIN, {}).setdefault(
            EQUIPMENT_TIMER_UNSUBS, {}
        )
        timer_store.pop(key, None)

        latest_entry = _first_entry(hass)
        if latest_entry is None or latest_entry.entry_id != entry.entry_id:
            return
        latest_config = _config_from_entry(latest_entry)
        latest_mode = latest_config.get("mode", {})
        if not isinstance(latest_mode, dict):
            return
        active = latest_mode.get("active")
        if active in (None, "running") or active != mode_snapshot:
            return
        timers = latest_mode.get("equipmentTimers", {})
        tstate = timers.get(equipment_id) if isinstance(timers, dict) else None
        if not isinstance(tstate, dict) or tstate.get("phase") in (None, "done"):
            return

        equipment = latest_config.get("equipment", {})
        mapped = equipment.get(equipment_id) if isinstance(equipment, dict) else None
        if not isinstance(mapped, dict) or not mapped.get("armed", False):
            return
        switch_entity = _normalise_entity_id(mapped.get("switch_entity_id"))
        if not switch_entity:
            return

        phase = tstate.get("phase")
        action = tstate.get("action") if tstate.get("action") in {"on", "off"} else "on"
        label = _equipment_label(equipment_id, mapped)
        fire_now = datetime.now(timezone.utc)

        sw_state = hass.states.get(switch_entity)
        if sw_state is None or sw_state.state in UNAVAILABLE_STATES:
            # Transient unavailable: cycles self-heal on the next phase; once-timers finish.
            if phase in {"on", "off", "delay"}:
                tstate["nextFireAt"] = (
                    fire_now + timedelta(seconds=MODE_EQUIPMENT_CYCLE_MIN_SECONDS)
                ).isoformat()
            else:
                tstate["phase"] = "done"
            await _async_save_config(hass, latest_entry, latest_config)
            return

        if phase == "delay":
            driven, reason = await _async_timer_drive_switch(
                hass, latest_entry, latest_config, equipment_id, mapped, action, None
            )
            if not driven:
                tstate["phase"] = "done"
                _append_activity(
                    latest_config, f"Per-device timer skipped {label}: {reason}", "warning"
                )
                await _async_save_config(hass, latest_entry, latest_config)
                return
            if tstate.get("timerMode") == "cycle":
                tstate["phase"] = action
                duration = tstate.get("onSeconds") or MODE_EQUIPMENT_CYCLE_MIN_SECONDS
            else:
                tstate["phase"] = "hold"
                duration = tstate.get("holdSeconds") or 1
            tstate["nextFireAt"] = (
                fire_now + timedelta(seconds=duration)
            ).isoformat()
            _append_activity(
                latest_config, f"Per-device timer started {label} ({action})", "control"
            )

        elif phase == "hold":
            return_plan = latest_mode.get("returnPlan", {})
            target = (
                return_plan.get(equipment_id)
                if isinstance(return_plan, dict)
                else None
            )
            if target in {"on", "off"}:
                driven, reason = await _async_timer_drive_switch(
                    hass, latest_entry, latest_config, equipment_id, mapped, target, None
                )
                if driven:
                    _append_activity(
                        latest_config,
                        f"Per-device timer reverted {label} to {target}",
                        "control",
                    )
                else:
                    _append_activity(
                        latest_config,
                        f"Per-device timer could not revert {label}: {reason}",
                        "warning",
                    )
            tstate["phase"] = "done"
            tstate["nextFireAt"] = ""

        elif phase in {"on", "off"}:
            target = "off" if phase == "on" else "on"
            driven, reason = await _async_timer_drive_switch(
                hass, latest_entry, latest_config, equipment_id, mapped, target, None
            )
            if not driven:
                tstate["phase"] = "done"
                _append_activity(
                    latest_config, f"Per-device cycle stopped {label}: {reason}", "warning"
                )
                await _async_save_config(hass, latest_entry, latest_config)
                return
            tstate["phase"] = target
            duration = (
                tstate.get("onSeconds") if target == action else tstate.get("offSeconds")
            ) or MODE_EQUIPMENT_CYCLE_MIN_SECONDS
            tstate["nextFireAt"] = (
                fire_now + timedelta(seconds=duration)
            ).isoformat()
        else:
            return

        await _async_save_config(hass, latest_entry, latest_config)

    store[key] = async_track_point_in_time(hass, _handle, run_at)


async def _async_schedule_equipment_timers(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry | None,
    config: dict[str, Any] | None = None,
) -> None:
    """Clear and re-arm every in-flight per-equipment timer for the active mode.
    Called from _async_save_config and on startup; cancels all when in running."""
    _clear_equipment_timers(hass)
    if entry is None:
        return
    config = config or _config_from_entry(entry)
    mode = config.get("mode", {})
    if not isinstance(mode, dict) or mode.get("active") in (None, "running"):
        return
    timers = mode.get("equipmentTimers", {})
    if not isinstance(timers, dict):
        return
    for equipment_id, state in timers.items():
        if not isinstance(state, dict) or state.get("phase") in (None, "done"):
            continue
        await _async_arm_equipment_timer(hass, entry, equipment_id, state)


async def _async_arm_max_off_timer(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry,
    equipment_id: str,
    state: dict[str, Any],
) -> None:
    """Arm one per-equipment max-off safety cap. On fire, force the device back on."""
    if not isinstance(state, dict):
        return
    run_at = _parse_datetime(state.get("fireAt"))
    if run_at is None:
        return
    now = datetime.now(timezone.utc)
    if run_at <= now:
        run_at = now + timedelta(seconds=1)

    key = _delayed_equipment_key(entry, equipment_id)
    store = hass.data.setdefault(DOMAIN, {}).setdefault(MAX_OFF_UNSUBS, {})
    old_unsub = store.pop(key, None)
    if old_unsub is not None:
        old_unsub()

    async def _handle(_now: datetime) -> None:
        cap_store = hass.data.setdefault(DOMAIN, {}).setdefault(MAX_OFF_UNSUBS, {})
        cap_store.pop(key, None)

        latest_entry = _first_entry(hass)
        if latest_entry is None or latest_entry.entry_id != entry.entry_id:
            return
        latest_config = _config_from_entry(latest_entry)
        latest_mode = latest_config.get("mode", {})
        if not isinstance(latest_mode, dict):
            return
        cap_timers = latest_mode.get("maxOffTimers", {})
        if not isinstance(cap_timers, dict) or equipment_id not in cap_timers:
            return
        equipment = latest_config.get("equipment", {})
        mapped = equipment.get(equipment_id) if isinstance(equipment, dict) else None
        if not isinstance(mapped, dict):
            cap_timers.pop(equipment_id, None)
            await _async_save_config(hass, latest_entry, latest_config)
            return
        switch_entity = _normalise_entity_id(mapped.get("switch_entity_id"))
        label = _equipment_label(equipment_id, mapped)
        sw_state = hass.states.get(switch_entity) if switch_entity else None
        if switch_entity and (sw_state is None or sw_state.state != "on"):
            await hass.services.async_call(
                "switch",
                "turn_on",
                {ATTR_ENTITY_ID: switch_entity},
                blocking=True,
                context=None,
            )
        cap_timers.pop(equipment_id, None)
        _append_activity(
            latest_config,
            f"Safety cap: {label} force-restored after its max-off limit",
            "warning",
        )
        await _async_send_mode_notification(
            hass,
            latest_config,
            f"openreef_max_off_{equipment_id}",
            "Equipment force-restored",
            f"{label} was held off past its safety limit and has been turned back on.",
        )
        await _async_save_config(hass, latest_entry, latest_config)

    store[key] = async_track_point_in_time(hass, _handle, run_at)


async def _async_schedule_max_off_timers(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry | None,
    config: dict[str, Any] | None = None,
) -> None:
    _clear_max_off_timers(hass)
    if entry is None:
        return
    config = config or _config_from_entry(entry)
    mode = config.get("mode", {})
    if not isinstance(mode, dict):
        return
    cap_timers = mode.get("maxOffTimers", {})
    if not isinstance(cap_timers, dict):
        return
    for equipment_id, state in cap_timers.items():
        await _async_arm_max_off_timer(hass, entry, equipment_id, state)


# --------------------------------------------------------------------------- #
# Automatic Water Change — orchestration (state machine + actuation). The pure
# decisions live in awc.py; this layer reads live HA state, drives the switches,
# persists state, and arms the single in-flight leg timer (re-armed each leg via
# _async_schedule_awc from _async_save_config, mirroring the per-equipment timers).
# --------------------------------------------------------------------------- #
_AWC_RUNNING_STATES = ("draining", "filling", "exchanging")
_AWC_ON_STATES = {"on", "true", "1", "detected", "wet", "open", "problem"}
_AWC_SAFE_METHOD = "batch_sequential"


def _awc_cfg(config: dict[str, Any]) -> dict[str, Any]:
    awc = config.get("automaticWaterChange")
    return awc if isinstance(awc, dict) else {}


# --- N-source state accessors (Stage B) -------------------------------------------
# A change draws WHOLLY from one selected fill source, so the state machine stays
# two-actor per change: "drain" + the active source role ("fill" or "fill2"). These
# helpers key the per-role progress/stop-time dicts so the orchestration reads the
# same regardless of which source is active.

def _awc_fill_role(state: dict[str, Any]) -> str:
    """The fill role the CURRENT change draws from ('fill' when idle/legacy)."""
    return state.get("activeSourceRole") or "fill"


def _awc_moved(state: dict[str, Any], role: str) -> float:
    mm = state.get("movedMl")
    return _awc_num(mm.get(role) if isinstance(mm, dict) else None, 0, 0, 1e9)


def _awc_set_moved(state: dict[str, Any], role: str, ml: float) -> None:
    state.setdefault("movedMl", {})[role] = round(ml, 1)


def _awc_ends(state: dict[str, Any], role: str) -> str:
    ea = state.get("endsAt")
    return ea.get(role, "") if isinstance(ea, dict) else ""


def _awc_set_ends(state: dict[str, Any], role: str, value: str) -> None:
    state.setdefault("endsAt", {})[role] = value


def _awc_all_pump_roles(config: dict[str, Any]) -> list[str]:
    """Every pump role this config can drive — the stop-everything set."""
    return ["drain", *awc_engine.fill_roles(_awc_cfg(config))]


def _awc_tank_ppt(config: dict[str, Any]) -> float:
    """The tank's target salinity in ppt for the net-salt ledger: the midpoint of the
    salinity sensor's alert band (sensors.salinity min/max — the closest thing the
    config has to a salinity target). SG-magnitude values convert to ppt; 0.0 when
    the band is unset/unparseable — the engine treats that as 'unknown'."""
    sensors = config.get("sensors") if isinstance(config.get("sensors"), dict) else {}
    sal = sensors.get("salinity") if isinstance(sensors.get("salinity"), dict) else {}
    values = []
    for key in ("min", "max"):
        try:
            value = float(sal.get(key))
        except (TypeError, ValueError):
            return 0.0
        if salinity_value_looks_like_sg(value):
            value = salinity_sg_to_ppt(value)
        values.append(value)
    mid = (values[0] + values[1]) / 2.0
    return round(mid, 2) if mid > 0 else 0.0


def _awc_sim_enabled(config: dict[str, Any]) -> bool:
    """Demo mode: virtual pumps, injectable hazards, zero real actuation."""
    sim = _awc_cfg(config).get("simulation")
    return isinstance(sim, dict) and bool(sim.get("enabled"))


def _awc_schedule_fingerprint(config: dict[str, Any] | None) -> tuple:
    """The slot-DEFINING schedule fields (R24): the master AWC toggle + schedule
    enabled + times + days. A change here means the user (re)armed the schedule,
    which consumes any already-passed slot — including flipping the MASTER toggle
    back on after a vacation, which re-enables the tick just like a schedule enable.
    Amount/method/unit edits are deliberately excluded — they don't move slots, so
    they must not swallow a genuinely pending one."""
    acfg = _awc_cfg(config or {})
    sched = acfg.get("schedule", {})
    if not isinstance(sched, dict):
        sched = {}
    times = sched.get("times") or [sched.get("startTime", "02:00")]
    if not isinstance(times, list):
        times = [times]
    days = sched.get("days") or []
    if not isinstance(days, list):
        days = []
    mode = str(sched.get("mode", "times")).lower()
    interval_part: tuple = ()
    if mode == "interval":
        # Interval cadence/window edits move slots just like a times edit does.
        interval_part = (
            str(sched.get("everyMinutes", "")),
            str(sched.get("windowStart", "")),
            str(sched.get("windowEnd", "")),
        )
    return (
        bool(acfg.get("enabled")),
        bool(sched.get("enabled")),
        mode,
        tuple(str(t) for t in times),
        tuple(str(d) for d in days),
        interval_part,
    )


def _awc_effective_tank_l(config: dict[str, Any]) -> float:
    """Net tank volume (L) the AWC engine should use: the AWC tab's own override when
    set, otherwise the Profile tank volume. Resolved at read time and never persisted,
    so editing the Profile volume flows through live — and the scheduler, the panel
    projection and the single-change safety cap all stay on one shared number."""
    own = _awc_num(_awc_cfg(config).get("tankVolumeLitres"), 0, 0, AWC_TANK_MAX_L)
    if own > 0:
        return own
    tank = config.get("tank") if isinstance(config.get("tank"), dict) else {}
    return _awc_num(tank.get("volumeLitres"), 0, 0, AWC_TANK_MAX_L)


def _awc_cfg_eff(config: dict[str, Any]) -> dict[str, Any]:
    """`_awc_cfg` with ``tankVolumeLitres`` resolved to the effective (possibly
    inherited) volume. READ-ONLY view for engine helpers that read tank volume out of
    the config dict (``summary``, the single-change cap). The state-mutation path keeps
    using `_awc_cfg` directly so writes still persist by reference."""
    acfg = _awc_cfg(config)
    eff = _awc_effective_tank_l(config)
    if not acfg or eff == _awc_num(acfg.get("tankVolumeLitres"), 0, 0, AWC_TANK_MAX_L):
        return acfg
    return {**acfg, "tankVolumeLitres": eff}


def _awc_binary_on(hass: HomeAssistant, entity_id: str | None) -> bool:
    """True when a configured binary safety sensor reads active. Unavailable/unset →
    False (see :func:`_awc_binary_unknown` for the fail-closed handling of a *configured*
    sensor that has gone unavailable)."""
    if not entity_id:
        return False
    state = hass.states.get(entity_id)
    if state is None or state.state in UNAVAILABLE_STATES:
        return False
    return str(state.state).lower() in _AWC_ON_STATES


def _awc_binary_unknown(hass: HomeAssistant, entity_id: str | None) -> bool:
    """True when a sensor is CONFIGURED but its state is missing/unavailable/unknown — i.e.
    we cannot trust it. A configured flood-hazard sensor (leak / display high-level) that has
    gone unavailable is a blind spot with no backend backstop (unlike the reservoir floats,
    which the dead-reckoning model and local firmware also guard), so we fail CLOSED on it:
    block a start and pause an in-flight change until it recovers — never latch, since a flaky
    sensor must not nuisance-fault. Unset entity ⇒ nothing to distrust ⇒ False."""
    if not entity_id:
        return False
    state = hass.states.get(entity_id)
    return state is None or state.state in UNAVAILABLE_STATES


def _awc_live_state(
    hass: HomeAssistant, config: dict[str, Any], fill_role: str = "fill"
) -> dict[str, Any]:
    """Live safety snapshot. ``fill_role`` selects whose SOURCE reservoir feeds the
    ``freshEmpty`` signal — in-run callers pass the change's active source role."""
    awc = _awc_cfg(config)
    if _awc_sim_enabled(config):
        # Demo mode: hazards come from the sim panel, not real sensors. Feed mode
        # stays real (it's an app state, and blocking on it is part of the demo).
        hazards = awc.get("simulation", {}).get("hazards", {})
        hazards = hazards if isinstance(hazards, dict) else {}
        mode = config.get("mode", {})
        return {
            "leak": bool(hazards.get("leak")),
            "highLevel": bool(hazards.get("highLevel")),
            "freshEmpty": bool(hazards.get("freshEmpty")),
            "wasteFull": bool(hazards.get("wasteFull")),
            "leakUnknown": False,
            "highLevelUnknown": False,
            "returnPumpIssue": bool(hazards.get("returnPumpIssue")),
            "inFeedMode": isinstance(mode, dict) and mode.get("active") == "feed",
        }
    safety = awc.get("safety", {}) if isinstance(awc.get("safety"), dict) else {}
    reservoirs = awc.get("reservoirs", {}) if isinstance(awc.get("reservoirs"), dict) else {}
    source_id = awc_engine.pump_reservoir_id(awc, fill_role or "fill")
    fresh = reservoirs.get(source_id, {}) if isinstance(reservoirs.get(source_id), dict) else {}
    waste = reservoirs.get("waste", {}) if isinstance(reservoirs.get("waste"), dict) else {}
    mode = config.get("mode", {})
    return {
        "leak": _awc_binary_on(hass, safety.get("leakEntity")),
        "highLevel": _awc_binary_on(hass, safety.get("highLevelEntity")),
        "freshEmpty": _awc_binary_on(hass, fresh.get("emptyEntity")),
        "wasteFull": _awc_binary_on(hass, waste.get("fullEntity")),
        # Fail-closed signal for the flood-hazard sensors: configured-but-unavailable.
        "leakUnknown": _awc_binary_unknown(hass, safety.get("leakEntity")),
        "highLevelUnknown": _awc_binary_unknown(hass, safety.get("highLevelEntity")),
        "returnPumpIssue": bool(_return_pump_dependency_issues(hass, config)),
        "inFeedMode": isinstance(mode, dict) and mode.get("active") == "feed",
    }


def _awc_ato_suspended(config: dict[str, Any]) -> bool:
    """ATO is held while a change is running/paused, while a fault is latched, and for
    the post-change stabilization hold-off (prevents the GHL-style salinity crash)."""
    awc = _awc_cfg(config)
    state = awc.get("state", {}) if isinstance(awc.get("state"), dict) else {}
    if _awc_sim_enabled(config):
        return False  # a VIRTUAL change must never hold the REAL ATO
    if not awc.get("ato", {}).get("suspendDuringChange", True):
        return False
    # Micro-change: too small to fight the ATO — the RUN itself never holds. But a
    # still-running hold-off stamped by a PREVIOUS (normal) change keeps holding
    # right through it, and a latched fault keeps the full posture regardless.
    if state.get("microChange") and state.get("status") != "fault":
        until = _parse_datetime(state.get("atoSuspendedUntil"))
        return until is not None and until > datetime.now(timezone.utc)
    if state.get("status") in (*_AWC_RUNNING_STATES, "paused", "fault"):
        return True
    until = _parse_datetime(state.get("atoSuspendedUntil"))
    return until is not None and until > datetime.now(timezone.utc)


async def _async_awc_set_pump(
    hass: HomeAssistant, config: dict[str, Any], role: str, on: bool, context: Any
) -> None:
    if _awc_sim_enabled(config):
        # Demo mode: record the virtual pump instead of driving hardware. Before the
        # entity check on purpose — a demo needs no real switch entities at all.
        sim_pumps = hass.data.setdefault(DOMAIN, {}).setdefault(
            AWC_RUNTIME, {}).setdefault("simPumps", {})
        sim_pumps[role] = bool(on)
        return
    pump = _awc_cfg(config).get("pumps", {}).get(role, {})
    entity = _normalise_entity_id(pump.get("switchEntity")) if isinstance(pump, dict) else ""
    if not entity:
        return
    await hass.services.async_call(
        "switch", "turn_on" if on else "turn_off",
        {ATTR_ENTITY_ID: entity}, blocking=True, context=context,
    )


async def _async_awc_stop_pumps(
    hass: HomeAssistant, config: dict[str, Any], roles: Iterable[str], context: Any
) -> None:
    """Turn every listed pump OFF, best-effort. This is the sole shutdown primitive —
    every caller (pause / abort / finalize / leg-complete / start-failure cleanup) is a
    stop path, so a failed ``turn_off`` on one pump must be logged and swallowed, NOT
    raised: otherwise the exception would skip stopping the *other* pumps and abandon the
    state transition (status latch, ATO restore, save) half-done — the exact "keep filling
    forever, untracked" hazard. A genuinely stuck actuator is caught by the mode-verify
    read-back, the runtime watchdog, and the local ESP firmware watchdog."""
    for role in roles:
        try:
            await _async_awc_set_pump(hass, config, role, False, context)
        except Exception:  # noqa: BLE001 - best-effort stop: log and keep stopping the rest
            _LOGGER.exception("Failed to turn off AWC %s pump during stop", role)


# Back-compat alias: the start-failure cleanup path reads clearer as "best_effort".
_async_awc_stop_pumps_best_effort = _async_awc_stop_pumps


async def _async_awc_kill_equipment_profile(
    hass: HomeAssistant, config: dict[str, Any], profile: str, context: Any
) -> None:
    if _awc_sim_enabled(config):
        return  # demo mode never touches real equipment
    for equipment_id, mapped in _armed_equipment_by_profile(config, profile):
        switch_entity = _normalise_entity_id(mapped.get("switch_entity_id"))
        if not switch_entity:
            continue
        state = hass.states.get(switch_entity)
        if state is not None and state.state == "off":
            continue
        await hass.services.async_call(
            "switch", "turn_off", {ATTR_ENTITY_ID: switch_entity},
            blocking=True, context=context,
        )


def _awc_bump_odometer(awc: dict[str, Any], role: str, seconds: float = 0.0, starts: int = 0) -> None:
    """Accumulate a pump's lifetime wear odometers (run-seconds / start-count). These
    persist independently of the capped history — the honest duty numbers at hourly
    micro-change cadence (~8,760 starts/yr/pump) that drive recalibration/tube nags."""
    pump = awc.get("pumps", {}).get(role) if isinstance(awc.get("pumps"), dict) else None
    if not isinstance(pump, dict):
        return
    if seconds > 0:
        pump["runSeconds"] = round(max(0.0, _awc_num(pump.get("runSeconds"), 0, 0, 1e9)) + seconds, 1)
    if starts > 0:
        pump["startCount"] = int(_awc_num(pump.get("startCount"), 0, 0, 1e9)) + starts


def _awc_notify_enabled(config: dict[str, Any], family: str) -> bool:
    notifications = _awc_cfg(config).get("notifications")
    notifications = notifications if isinstance(notifications, dict) else {}
    return bool(notifications.get(family, True))


async def _async_awc_notify(
    hass: HomeAssistant, config: dict[str, Any], family: str,
    notification_id: str, title: str, message: str,
) -> None:
    """Family-gated AWC notification (automaticWaterChange.notifications)."""
    if not _awc_notify_enabled(config, family):
        return
    await _async_send_mode_notification(hass, config, notification_id, title, message)


async def _async_awc_notify_once(
    hass: HomeAssistant, config: dict[str, Any], key: str, cooldown_s: float,
    family: str, title: str, message: str,
) -> None:
    """Advisory-tier notification with a hass.data cooldown (mirrors the dosing
    _async_dosing_notify_once pattern) — the minutely tick may re-detect the same
    condition thousands of times; the user hears about it once per cooldown."""
    if not _awc_notify_enabled(config, family):
        return
    runtime = hass.data.setdefault(DOMAIN, {}).setdefault(AWC_RUNTIME, {})
    notified = runtime.setdefault("notified", {})
    now = datetime.now(timezone.utc)
    previous = notified.get(key)
    if previous is not None:
        try:
            if (now - datetime.fromisoformat(previous)).total_seconds() < cooldown_s:
                return
        except (ValueError, TypeError):
            pass
    notified[key] = now.isoformat()
    await _async_send_mode_notification(hass, config, f"openreef_awc_{key}", title, message)


async def _async_awc_advisory_notifications(
    hass: HomeAssistant, config: dict[str, Any]
) -> None:
    """Minutely advisory tier (Stage A notifications home): reservoir-low,
    calibration-due, net-drift. Read-only on the peeked config — the cooldown map
    lives in hass.data, so nothing here needs the lock or a save. Rides the AWC
    scheduler tick, so it evaluates while a schedule is enabled (or a change is
    paused) — the population these advisories exist for."""
    acfg = _awc_cfg(config)
    if not acfg.get("enabled"):
        return
    # UTC-aware now: the age stamps (calibratedAt etc.) are UTC-aware, and naive-vs-
    # aware arithmetic silently yields None ages (= no nag, ever).
    summary = awc_engine.summary(_awc_cfg_eff(config), datetime.now(timezone.utc))
    for res_id, res in summary.get("reservoirs", {}).items():
        if res_id == "waste" or not isinstance(res, dict):
            continue
        pct = res.get("percent")
        # daysOfFreshRemaining is the primary-source projection; secondary sources
        # go by percent alone.
        days = summary.get("daysOfFreshRemaining") if res_id == "fresh" else None
        if (pct is not None and 0 < res.get("capacityL", 0) and pct <= 10) or (
                days is not None and 0 < days <= 2):
            days_txt = f" (~{days:.1f} days at the current schedule)" if days is not None else ""
            res_name = "fresh" if res_id == "fresh" else f"'{res_id}'"
            await _async_awc_notify_once(
                hass, config, f"reservoir_low_{res_id}", 24 * 3600, "reservoirLow",
                "Fresh saltwater running low",
                f"The {res_name} reservoir is at {pct:.0f}%{days_txt} — top it up "
                "before the next water change is blocked.")
    for role in ("drain", "fill", "fill2"):
        pump = summary.get("pumps", {}).get(role)
        if isinstance(pump, dict) and pump.get("recalibrationDue"):
            age = pump.get("calibrationAgeDays") or 0
            await _async_awc_notify_once(
                hass, config, f"recal_{role}", 7 * 24 * 3600, "calibrationDue",
                f"{role.capitalize()} pump recalibration due",
                f"The {role} pump was last calibrated {age:.0f} days ago — accuracy "
                "drifts with tube wear. Run a quick calibration.")
    ni = summary.get("netImbalance", {})
    if ni.get("status") == "warning":
        await _async_awc_notify_once(
            hass, config, "net_drift", 24 * 3600, "netDrift",
            "Water changes drifting out of balance",
            f"Cumulative fill vs drain is off by {ni.get('netL', 0):+.1f} L — trim the "
            f"next change by {ni.get('suggestedTrimL', 0):+.1f} L, or reset the ledger "
            "after correcting salinity.")


def _awc_debit_source(awc: dict[str, Any], role: str, ml: float) -> None:
    """Debit the given fill role's SOURCE reservoir dead-reckoned level AND bump its
    drift odometer (dispensedSinceFullMl) — the single choke point for every fill-side
    debit, so the drift check always grades a complete model figure against reality.
    The reservoir is resolved via the pump's reservoirId (fill→fresh, fill2→fresh2)."""
    if ml <= 0:
        return
    reservoirs = awc.get("reservoirs", {}) if isinstance(awc.get("reservoirs"), dict) else {}
    source = reservoirs.get(awc_engine.pump_reservoir_id(awc, role))
    if not isinstance(source, dict):
        return
    source["remainingMl"] = max(0.0, source.get("remainingMl", 0) - ml)
    source["dispensedSinceFullMl"] = _awc_num(source.get("dispensedSinceFullMl"), 0, 0, 1e9) + ml


def _awc_grade_fresh_drift(
    config: dict[str, Any], reservoir_id: str = "fresh"
) -> dict[str, Any] | None:
    """Grade fill-pump calibration drift (Stage A, the Trust-Moat seed): the model's
    dispensed-since-full vs the reservoir's known capacity, at the moment reality
    checks in (empty float trip / refill-from-empty). Stamps the verdict onto the
    source reservoir and latches via driftCheckedAt (once per fill cycle; reset-to-full
    re-arms). Returns the verdict, or None when there is nothing to grade."""
    fresh = _awc_cfg(config).get("reservoirs", {}).get(reservoir_id, {})
    if not isinstance(fresh, dict) or fresh.get("driftCheckedAt"):
        return None
    if not fresh.get("fullConfirmedAt"):
        # No confirmed-full anchor (fresh install / never marked full): the odometer
        # started counting from an unknown level, so grading it against capacity is
        # a guess — and false "recalibrate" alarms are exactly what the Trust Moat
        # forbids. The first mark-full arms the check.
        return None
    dispensed = _awc_num(fresh.get("dispensedSinceFullMl"), 0, 0, 1e9)
    cap_ml = _awc_num(fresh.get("capacityLitres"), 0, 0, 1e9) * 1000.0
    if dispensed <= 0 or cap_ml <= 0:
        return None
    if dispensed > cap_ml * 1.5:
        # Someone topped the reservoir up with a bucket without marking it full —
        # there is no honest reference for this cycle. Skip rather than accuse.
        return None
    verdict = awc_engine.drift_state(dispensed, cap_ml)
    fresh["driftPct"] = verdict["driftPct"]
    fresh["driftStatus"] = verdict["status"]
    fresh["driftCheckedAt"] = datetime.now(timezone.utc).isoformat()
    return verdict


async def _async_awc_notify_drift(
    hass: HomeAssistant, config: dict[str, Any], verdict: dict[str, Any],
    reservoir_id: str = "fresh",
) -> None:
    """Surface a recalibrate-worthy drift verdict: activity + one notification."""
    if not verdict.get("recalibrate"):
        return
    fresh = _awc_cfg(config).get("reservoirs", {}).get(reservoir_id, {})
    dispensed_l = _awc_num(fresh.get("dispensedSinceFullMl"), 0, 0, 1e9) / 1000.0
    cap_l = _awc_num(fresh.get("capacityLitres"), 0, 0, 1e9)
    pct = verdict.get("driftPct") or 0
    direction = "less" if pct > 0 else "more"
    res_name = "fresh" if reservoir_id == "fresh" else f"'{reservoir_id}'"
    pump_name = "fill" if reservoir_id == "fresh" else "fill2"
    msg = (f"The {pump_name}-pump model claims {dispensed_l:.1f} L dispensed but the {cap_l:.0f} L "
           f"{res_name} reservoir just ran empty ({pct:+.0f}%) — the pump is moving {direction} "
           f"water than its calibration says. Recalibrate the {pump_name} pump.")
    _append_activity(config, msg, "warning")
    # Per-reservoir notification id: a fresh2 verdict must not replace a fresh one
    # in the notification tray.
    await _async_awc_notify(
        hass, config, "driftDetected", f"openreef_awc_drift_{reservoir_id}",
        "Pump calibration drift detected", msg)


async def _async_awc_check_drift_on_empty(
    hass: HomeAssistant, entry: OpenReefConfigEntry, reservoir_id: str = "fresh"
) -> None:
    """Minutely drift hook: the source reservoir's empty float tripping is the reality
    reference. Cheap unlocked pre-checks; grading + save happen fetch-fresh under the
    lock."""
    fresh = _awc_cfg(_config_from_entry(entry)).get("reservoirs", {}).get(reservoir_id, {})
    if (not isinstance(fresh, dict)
            or not fresh.get("emptyEntity") or fresh.get("driftCheckedAt")
            or not fresh.get("fullConfirmedAt")
            or not _awc_binary_on(hass, fresh.get("emptyEntity"))):
        return
    async with _awc_lock(hass):
        config = _config_from_entry(entry)
        verdict = _awc_grade_fresh_drift(config, reservoir_id)
        if verdict is None:
            return
        await _async_awc_notify_drift(hass, config, verdict, reservoir_id)
        await _async_save_config(hass, entry, config)


def _awc_lock(hass: HomeAssistant) -> asyncio.Lock:
    """The per-instance AWC state lock (see AWC_STATE_LOCK). Held by the top-level entry
    points only — never acquire it from an inner helper they call."""
    store = hass.data.setdefault(DOMAIN, {})
    lock = store.get(AWC_STATE_LOCK)
    if lock is None:
        lock = store[AWC_STATE_LOCK] = asyncio.Lock()
    return lock


def _clear_awc_timer(hass: HomeAssistant) -> None:
    store = hass.data.setdefault(DOMAIN, {})
    unsub = store.pop(AWC_UNSUB, None)
    if unsub is not None:
        unsub()


async def _async_awc_begin_leg(
    hass: HomeAssistant, config: dict[str, Any], method: str, leg: dict[str, Any],
    now: datetime, context: Any,
) -> tuple[bool, str]:
    """Turn on a SINGLE-pump (sequential) leg and stamp its timing into state. The caller
    persists (which re-arms the leg timer via _async_schedule_awc). A both-pump leg is
    delegated to the exchange path (the sole owner of per-pump stop times) so it can never
    be driven by the single-leg timer."""
    pumps = leg["pumps"]
    if "drain" in pumps and any(p != "drain" for p in pumps):
        return await _async_awc_begin_exchange(hass, config, now, context)
    acfg = _awc_cfg(config)
    state = acfg["state"]
    slice_l = float(leg["sliceMl"]) / 1000.0
    expected = awc_engine.leg_runtime_s(slice_l, acfg, pumps)
    # A pump with volume to move but a zero/uncalibrated runtime would be energised on
    # a zero-length timer and credit the whole slice at the next fire (non-fail-safe).
    # Judged on the RATE (R13 parity): an UNCALIBRATED pump faults — this is
    # unreachable from a normal start (preflight blocks it) and covers mid-run
    # calibration loss. A CALIBRATED pump whose sliver of a slice rounds to a
    # non-positive runtime (spin-up correction on a post-resume remainder) instead
    # runs a floor tick so the ordinary leg-complete credit closes the change out.
    if slice_l > 1e-9 and expected <= 0:
        if any(
            _awc_num((acfg.get("pumps", {}).get(r) or {}).get("mlPerS"), 0, 0, 1e9) <= 0
            for r in pumps
        ):
            state["status"] = "fault"
            state["fault"] = "Cannot run water change: a pump is not calibrated"
            state["faultSince"] = now.isoformat()
            state["legStartedAt"] = ""
            state["legEndsAt"] = ""
            state["pausedReason"] = ""
            return False, state["fault"]
        expected = 1.0
    try:
        for role in pumps:
            await _async_awc_set_pump(hass, config, role, True, context)
    except Exception as exc:  # noqa: BLE001 - service-call failure is safety critical
        await _async_awc_stop_pumps_best_effort(hass, config, AWC_PUMP_ROLES, context)
        state["status"] = "fault"
        state["fault"] = f"AWC pump start failed: {exc}"
        state["faultSince"] = now.isoformat()
        state["legStartedAt"] = ""
        state["legEndsAt"] = ""
        state["pausedReason"] = ""
        return False, state["fault"]
    state["status"] = "draining" if "drain" in pumps else "filling"
    for role in pumps:
        _awc_bump_odometer(acfg, role, starts=1)
    state["legStartedAt"] = now.isoformat()
    state["legEndsAt"] = (now + timedelta(seconds=max(1.0, expected))).isoformat()
    state["pausedReason"] = ""
    return True, ""


async def _async_awc_begin_exchange(
    hass: HomeAssistant, config: dict[str, Any], now: datetime, context: Any,
) -> tuple[bool, str]:
    """Begin (or resume) a SIMULTANEOUS exchange: both pumps run together, each on its
    OWN independent timer sized to move exactly the remaining target volume at its
    calibrated rate. Neither over-pumps (the shared-timer hazard that got simultaneous
    deferred); a per-tick imbalance cap then bounds the mid-run sump excursion. The
    monitor tick re-arms at the soonest of (now + tick) and each pump's stop time."""
    acfg = _awc_cfg(config)
    state = acfg["state"]
    fill_role = _awc_fill_role(state)
    target_ml = state.get("targetLitres", 0) * 1000.0
    pumps = acfg.get("pumps", {})
    drain = pumps.get("drain", {}) if isinstance(pumps.get("drain"), dict) else {}
    fill = pumps.get(fill_role, {}) if isinstance(pumps.get(fill_role), dict) else {}
    drain_remaining_l = max(0.0, target_ml - _awc_moved(state, "drain")) / 1000.0
    fill_remaining_l = max(0.0, target_ml - _awc_moved(state, fill_role)) / 1000.0
    drain_rt = awc_engine.runtime_for_volume_s(drain_remaining_l, drain.get("mlPerS"), drain.get("exchangeFactor", 1.0), drain.get("spinUpMl", 0.0))
    fill_rt = awc_engine.runtime_for_volume_s(fill_remaining_l, fill.get("mlPerS"), fill.get("exchangeFactor", 1.0), fill.get("spinUpMl", 0.0))

    # An UNCALIBRATED side with volume still to move would be energised on a zero-length
    # timer and phantom-credit the full target on the next tick (non-fail-safe). Refuse
    # to begin — mirrors the start-time no_calibration guard. Judged on the RATE, not
    # the runtime: a calibrated side with a sliver left is handled below (R13).
    if (drain_remaining_l > 1e-6 and _awc_num(drain.get("mlPerS"), 0, 0, 1e9) <= 0) or (
            fill_remaining_l > 1e-6 and _awc_num(fill.get("mlPerS"), 0, 0, 1e9) <= 0):
        state["status"] = "fault"
        state["fault"] = "Cannot run simultaneous change: a pump is not calibrated"
        state["faultSince"] = now.isoformat()
        state["legStartedAt"] = ""
        state["legEndsAt"] = ""
        state["endsAt"] = {}
        return False, state["fault"]

    # A CALIBRATED side whose remaining sliver rounds to a non-positive runtime (the
    # spin-up correction near the very end) is FINISHED, not uncalibrated — resuming a
    # change 30 ml from its end must not latch a spurious calibration fault (R13).
    if drain_remaining_l > 1e-6 and drain_rt <= 0:
        drain_remaining_l = 0.0
    if fill_remaining_l > 1e-6 and fill_rt <= 0:
        fill_remaining_l = 0.0

    roles_on = []
    if drain_remaining_l > 1e-6:
        roles_on.append("drain")
    if fill_remaining_l > 1e-6:
        roles_on.append(fill_role)
    try:
        for role in roles_on:
            await _async_awc_set_pump(hass, config, role, True, context)
    except Exception as exc:  # noqa: BLE001 - service-call failure is safety critical
        await _async_awc_stop_pumps_best_effort(hass, config, AWC_PUMP_ROLES, context)
        state["status"] = "fault"
        state["fault"] = f"AWC pump start failed: {exc}"
        state["faultSince"] = now.isoformat()
        state["legStartedAt"] = ""
        state["legEndsAt"] = ""
        state["endsAt"] = {}
        state["pausedReason"] = ""
        return False, state["fault"]

    for role in roles_on:
        _awc_bump_odometer(acfg, role, starts=1)
    drain_end = now + timedelta(seconds=drain_rt) if "drain" in roles_on else now
    fill_end = now + timedelta(seconds=fill_rt) if fill_role in roles_on else now
    state["status"] = "exchanging"
    state["legStartedAt"] = now.isoformat()
    _awc_set_ends(state, "drain", drain_end.isoformat())
    _awc_set_ends(state, fill_role, fill_end.isoformat())
    # Baseline the imbalance band to the SIGNED net that exists right now, so a
    # resume-to-balance leg (which starts with a large pre-existing gap it's correcting)
    # isn't false-aborted — and can't reverse THROUGH zero and overfill unchecked.
    state["exchangeBaselineNetMl"] = round(
        _awc_moved(state, "drain") - _awc_moved(state, fill_role), 1)
    pending = [now + timedelta(seconds=AWC_EXCHANGE_TICK_SECONDS)]
    if "drain" in roles_on:
        pending.append(drain_end)
    if fill_role in roles_on:
        pending.append(fill_end)
    state["legEndsAt"] = min(pending).isoformat()
    state["pausedReason"] = ""
    return True, ""


async def _async_awc_suspend_ato(hass: HomeAssistant, config: dict[str, Any], context: Any) -> None:
    """Actively turn off any armed ATO equipment; the safety-block gate then keeps it
    off for the whole change + hold-off."""
    await _async_awc_kill_equipment_profile(hass, config, "ato", context)


async def _async_awc_start(
    hass: HomeAssistant, entry: OpenReefConfigEntry,
    target_litres: float, method: str | None, manual: bool, context: Any,
) -> tuple[bool, list[dict[str, str]]]:
    """Preflight a change and begin its first leg. Returns (started, blocking_reasons).
    Locked: the busy/preflight check and the begin must be atomic, or two overlapping
    starts (scheduler tick + manual run-now) both pass preflight and double-start.
    The config snapshot is taken INSIDE the lock (R1): every entry point previously
    deep-copied config before acquiring it, so the locked body's status checks ran on
    stale state — an aborted change could be resurrected by a queued start."""
    async with _awc_lock(hass):
        return await _async_awc_start_locked(
            hass, entry, _config_from_entry(entry), target_litres, method, manual, context
        )


async def _async_awc_start_locked(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any],
    target_litres: float, method: str | None, manual: bool, context: Any,
) -> tuple[bool, list[dict[str, str]]]:
    acfg = _awc_cfg(config)
    state = acfg["state"]
    if state.get("status") in _AWC_RUNNING_STATES:
        return False, [{"code": "busy", "severity": "block", "message": "A water change is already running"}]
    if state.get("status") == "paused":
        return False, [{"code": "paused", "severity": "block",
                        "message": "A water change is paused; resume or stop it before starting another"}]
    if hass.data.get(DOMAIN, {}).get(AWC_CALRUN_UNSUB) is not None:
        return False, [{"code": "busy", "severity": "block",
                        "message": "A calibration run is in progress"}]
    if hass.data.get(DOMAIN, {}).get(NPS_DRAIN_UNSUB) is not None:
        return False, [{"code": "busy", "severity": "block",
                        "message": "An NPS feed-exchange drain is in progress"}]
    method = method or acfg.get("schedule", {}).get("method", _AWC_SAFE_METHOD)
    if method not in AWC_LIVE_METHODS:
        return False, [{"code": "unsupported_method", "severity": "block",
                        "message": "AWC supports sequential or simultaneous changes (continuous is projection-only)"}]
    target = round(float(target_litres or 0), 3)

    # Select THE fill source for this change (each change draws wholly from one
    # source): the policy picks it; every guard below is judged against it.
    pick = awc_engine.select_fill_source(_awc_cfg_eff(config), target)
    if pick is not None:
        fill_role = pick["role"]
    else:
        policy = acfg.get("sourcePolicy") if isinstance(acfg.get("sourcePolicy"), dict) else {}
        policy_order = policy.get("order") or []
        fill_role = policy_order[0] if policy_order else "fill"

    # Local time is only needed for the quiet-hours guard; compute it lazily.
    now_min = 0
    if acfg.get("guards", {}).get("quietHoursEnabled"):
        local_now = dt_util.now()
        now_min = local_now.hour * 60 + local_now.minute
    live = _awc_live_state(hass, config, fill_role=fill_role)
    reasons = awc_engine.start_guard_reasons(acfg, live, now_min, manual, fill_role=fill_role)
    if _awc_sim_enabled(config):
        # Demo mode: virtual pumps need no real switch entities, and a virtual change
        # can't flood a floor, so the no-leak-sensor acknowledgement isn't demanded
        # either; every OTHER guard (calibration, reservoirs, hazards, caps) stays
        # honest — that's the demo.
        reasons = [r for r in reasons
                   if r.get("code") not in ("no_pump_entity", "flood_unacknowledged")]
    if target <= 0:
        reasons.append({"code": "no_volume", "severity": "block", "message": "Enter a volume to change"})
    reasons.extend(awc_engine.reservoir_preflight_reasons(acfg, target, source_role=fill_role))
    if (pick is None and target > 0
            and not any(r.get("code") in ("fresh_insufficient", "no_calibration") for r in reasons)):
        # No source can cover the change and the per-source preflight didn't already
        # say so (e.g. the fallback role's reservoir alone would have sufficed).
        reasons.append({"code": "fresh_insufficient", "severity": "block",
                        "message": "No fill source has enough recorded volume for this change"})
    if awc_engine.exceeds_single_change_cap(_awc_cfg_eff(config), target):
        pct = acfg.get("safety", {}).get("maxSingleChangePercent", 25)
        reasons.append({"code": "max_single_change", "severity": "block",
                        "message": f"Exceeds the {pct}% single-change cap"})
    if method == "batch_simultaneous" and target > 0:
        cap = acfg.get("safety", {}).get("maxInstantaneousImbalanceLitres", AWC_DEFAULT_MAX_INSTANT_IMBALANCE_L)
        excursion = awc_engine.simultaneous_max_excursion_l(acfg, target, fill_role)
        if cap > 0 and excursion > cap + 1e-6:
            reasons.append({"code": "imbalance_too_large", "severity": "block",
                            "message": f"Pumps too rate-mismatched for a simultaneous {target:.1f} L change "
                                       f"(~{excursion:.1f} L sump swing > {cap} L cap) — use sequential or rate-match"})
    # The Trust Moat (mixing doc §9): does the mixing station vouch for this
    # water? Skipped in demo mode like the other physical-world guards. "block"
    # joins the refusal reasons; "warn" lets the change run but says so below,
    # where the keeper will see it.
    mix_guard = None
    if not _awc_sim_enabled(config):
        mix_guard = mixing_engine.awc_guard_reason(
            _mixing_cfg(config), target, datetime.now(timezone.utc))
    if mix_guard is not None and mix_guard.get("mode") == "block":
        reasons.append({"code": "mixing_batch", "severity": "block",
                        "message": f"Mixing-station guard: {mix_guard.get('message', '')}"})
    if reasons:
        return False, reasons
    if mix_guard is not None:
        _append_activity(
            config, "Water change starting without the mixing station's blessing — "
            f"{mix_guard.get('message', '')}", "warning")

    now = datetime.now(timezone.utc)
    threshold_ml = _awc_num(acfg.get("ato", {}).get("microChangeThresholdMl"), 0, 0, 1e9)
    # Micro-change additionally requires the SELECTED source to be salt-matched to the
    # tank: skipping the ATO/dosing suspends is only safe when the water going in is
    # the same salinity as the water coming out (unknown salinities count as matched).
    micro = (threshold_ml > 0 and target * 1000.0 <= threshold_ml + 1e-6
             and awc_engine.source_salt_matched(
                 acfg.get("reservoirs", {}).get(awc_engine.pump_reservoir_id(acfg, fill_role)),
                 _awc_tank_ppt(config)))
    state["microChange"] = micro
    if not micro:
        if acfg.get("ato", {}).get("suspendDuringChange", True):
            await _async_awc_suspend_ato(hass, config, context)
            state["atoSuspendedUntil"] = ""  # the "running" status covers the suspension
        await _async_dosing_awc_suspend(hass, config, True, context)
    # else: a micro-change is too small to fight the ATO or matter to dosing — both
    # suspends are skipped so the hourly cadence doesn't hold them around the clock.
    state["method"] = method
    state["targetLitres"] = target
    state["activeSourceRole"] = fill_role
    state["movedMl"] = {}
    state["endsAt"] = {}
    state["exchangeBaselineNetMl"] = 0
    state["startedAt"] = now.isoformat()
    state["fault"] = ""
    state["faultSince"] = ""
    state["pausedReason"] = ""
    state["legStartedAt"] = ""
    state["legEndsAt"] = ""
    state["anomalyWarned"] = False
    state["blockedSlotKey"] = ""  # the slot (if any) is being served now
    for warning in (pick.get("warnings") or []) if pick else []:
        _append_activity(config, f"Water change source: {warning}", "warning")

    target_ml = target * 1000.0
    if method == "batch_simultaneous":
        begun, reason = await _async_awc_begin_exchange(hass, config, now, context)
    else:
        leg = awc_engine.plan_leg(method, 0, 0, target_ml, target_ml)
        if leg is None:
            return True, []
        # The engine plans in generic role labels — map "fill" to the ACTIVE source.
        leg = {**leg, "pumps": [fill_role if p == "fill" else p for p in leg["pumps"]]}
        begun, reason = await _async_awc_begin_leg(hass, config, method, leg, now, context)
    if not begun:
        _append_activity(config, reason, "control")
        await _async_save_config(hass, entry, config)
        return False, [{"code": "pump_start_failed", "severity": "fault", "message": reason}]
    source_policy = acfg.get("sourcePolicy")
    if isinstance(source_policy, dict):
        # Stamped only AFTER a successful begin: a failed start must not rotate the
        # alternate anchor and make the policy skip a source that never poured.
        source_policy["lastSourceUsed"] = fill_role
    _append_activity(config, f"Water change started: {target:.1f} L ({method.replace('_', ' ')})", "control")
    await _async_save_config(hass, entry, config)
    return True, []


async def _async_awc_pause(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any],
    reason: str, context: Any,
) -> None:
    await _async_awc_stop_pumps(hass, config, tuple(_awc_all_pump_roles(config)), context)
    awc = _awc_cfg(config)
    # Credit the elapsed portion of an in-flight sequential leg before parking (R9):
    # resume replans from drained/filled, so an uncredited half-leg would be replayed
    # in full — overfilling by whatever had already moved. Inert when the leg-complete
    # path already credited the slice and cleared the stamps.
    _awc_credit_interrupted_leg(awc, datetime.now(timezone.utc))
    state = awc["state"]
    state["status"] = "paused"
    state["pausedReason"] = reason
    state["legStartedAt"] = ""
    state["legEndsAt"] = ""
    state["endsAt"] = {}
    state["exchangeBaselineNetMl"] = 0
    # movedMl and activeSourceRole deliberately survive the pause — resume needs them.
    _append_activity(config, f"Water change paused: {reason}", "warning")
    await _async_awc_notify(
        hass, config, "pausedFault", "openreef_awc_paused", "Water change paused", reason,
    )
    await _async_save_config(hass, entry, config)


async def _async_awc_abort(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any],
    reason: str, latch: bool, master_kill: bool, context: Any,
) -> None:
    await _async_awc_stop_pumps(hass, config, tuple(_awc_all_pump_roles(config)), context)
    if master_kill:
        await _async_awc_kill_equipment_profile(hass, config, "return_pump", context)
    if latch and _awc_cfg(config).get("ato", {}).get("suspendDuringChange", True):
        # A latched hazard must leave the ATO physically OFF. Normal changes killed
        # it at start; a micro-change deliberately skipped that — but a fault is not
        # a micro situation, and the suspension predicate only blocks FUTURE
        # turn-ons, never an already-running top-off.
        await _async_awc_kill_equipment_profile(hass, config, "ato", context)
    awc = _awc_cfg(config)
    state = awc["state"]
    now = datetime.now(timezone.utc)
    # Credit the elapsed portion of an in-flight sequential leg BEFORE reading the
    # totals (R6): a Stop at 90% of a leg otherwise vanishes that near-whole-leg
    # volume from the history, ledger and reservoir models.
    _awc_credit_interrupted_leg(awc, now)
    fill_role = _awc_fill_role(state)  # read BEFORE the zeroing below clears it
    drained_l = _awc_moved(state, "drain") / 1000.0
    filled_l = _awc_moved(state, fill_role) / 1000.0
    if drained_l > 0 or filled_l > 0:
        _awc_record_history(awc, now, drained_l, filled_l, state.get("method", ""), True, reason,
                            config=config)
        awc["history"][0]["source"] = fill_role
        per_source = awc["ledger"].setdefault("perSource", {})
        per_source[fill_role] = round(
            _awc_num(per_source.get(fill_role), 0, 0, 1e9) + filled_l, 3)
        source_res = awc.get("reservoirs", {}).get(awc_engine.pump_reservoir_id(awc, fill_role), {})
        salt_delta = awc_engine.net_salt_delta_g(
            drained_l, filled_l, _awc_tank_ppt(config),
            source_res.get("saltPpt") if isinstance(source_res, dict) else 0)
        if salt_delta is not None:
            awc["ledger"]["netSaltGrams"] = round(
                _awc_num(awc["ledger"].get("netSaltGrams"), 0, -1e9, 1e9) + salt_delta, 1)
    if latch:
        state["status"] = "fault"
        state["fault"] = reason
        state["faultSince"] = now.isoformat()
    else:
        state["status"] = "idle"
        state["fault"] = ""
        state["atoSuspendedUntil"] = ""  # user abort restores the ATO
        # A user Stop consumes the schedule slot (R7): without this the minutely tick
        # sees an idle state whose slot is still unserved and restarts the change —
        # all day long, 60 s after every Stop.
        state["lastRun"] = now.isoformat()
    state["legStartedAt"] = ""
    state["legEndsAt"] = ""
    state["endsAt"] = {}
    state["exchangeBaselineNetMl"] = 0
    state["movedMl"] = {}
    state["activeSourceRole"] = ""
    state["targetLitres"] = 0
    state["microChange"] = False  # fault status overrides the flag in both predicates
    if not latch:
        # A latched fault keeps dosing held (status "fault" drives _dosing_awc_suspended);
        # a plain abort releases the firmware suspend switch immediately.
        await _async_dosing_awc_suspend(hass, config, False, context)
    _append_activity(config, f"Water change {'FAULT' if latch else 'aborted'}: {reason}",
                     "warning" if latch else "control")
    await _async_awc_notify(
        hass, config, "pausedFault", "openreef_awc_fault",
        "Water change fault" if latch else "Water change aborted", reason,
    )
    await _async_save_config(hass, entry, config)


def _preserve_runtime_mode(stored: Any, incoming: dict[str, Any]) -> None:
    """Keep the live ``mode`` block on a settings save, in place on ``incoming``.

    ``mode`` is server-side RUNTIME state — the active mode, its timer, the
    captured return plan and the per-equipment / max-off timers — written only
    by apply_mode and the schedulers. But a panel save posts the WHOLE config,
    so a snapshot fetched before a mode was applied silently reverted all of
    it. The observed casualty is the return plan: a settings save mid-mode
    wiped the captured pre-mode states, the next apply recaptured them from
    the already-switched equipment, and "Return to Running" then faithfully
    restored the mode's own states — a scrubbing air pump that never turned
    back off. The client has no business writing any of this; the stored block
    always wins.
    """
    if not isinstance(stored, dict) or not isinstance(incoming, dict):
        return
    stored_mode = stored.get("mode")
    if isinstance(stored_mode, dict):
        incoming["mode"] = deepcopy(stored_mode)


def _merge_recent_completions(stored: Any, incoming: dict[str, Any]) -> None:
    """Protect completions the client's snapshot predates, in place on ``incoming``.

    A panel save posts the WHOLE config, so a stale snapshot would silently drop any
    completion written since it was fetched — an automatic water change, or one logged
    by the ``record_task_completion`` service from an automation. Both are invisible to
    a panel sitting on unsaved edits, which is exactly when it refuses to refresh.

    A blunt union would resurrect deliberate deletes, so the rule is anchored on the
    ``completionsSyncedAt`` stamp the client was handed and sends back:

    * absent from the payload and NEWER than that stamp -> logged after the snapshot,
      restore it (a delete can only target an entry the client could see);
    * present, and the stored copy is a NEWER automatic entry -> the backend owns those
      (same-day runs merge in place), so take the stored volume/timestamp;
    * anything else -> the client's payload wins, so deletes and edits stick.

    Without a usable stamp (an old client, or an import) nothing is restored — the
    pre-0.6.3 behaviour, which is the safe direction to fail in.
    """
    if not isinstance(stored, dict) or not isinstance(incoming, dict):
        return
    stored_maintenance = stored.get("maintenance")
    incoming_maintenance = incoming.get("maintenance")
    if not isinstance(stored_maintenance, dict) or not isinstance(incoming_maintenance, dict):
        return
    stored_completions = stored_maintenance.get("completions")
    if not isinstance(stored_completions, dict):
        return
    synced = _parse_datetime(incoming_maintenance.get("completionsSyncedAt"))
    incoming_completions = incoming_maintenance.get("completions")
    if not isinstance(incoming_completions, dict):
        incoming_completions = {}
        incoming_maintenance["completions"] = incoming_completions

    for task_id, stored_entries in stored_completions.items():
        if not isinstance(stored_entries, list):
            continue
        entries = incoming_completions.get(task_id)
        if not isinstance(entries, list):
            entries = []
            incoming_completions[task_id] = entries
        index_by_id = {
            entry.get("id"): position
            for position, entry in enumerate(entries)
            if isinstance(entry, dict) and entry.get("id")
        }
        restored = False
        for stored_entry in stored_entries:
            if not isinstance(stored_entry, dict):
                continue
            stamp = _parse_datetime(stored_entry.get("timestamp"))
            if stamp is None:
                continue
            position = index_by_id.get(stored_entry.get("id"))
            if position is not None:
                if stored_entry.get("source") != MAINTENANCE_SOURCE_AWC:
                    continue
                client_stamp = _parse_datetime(entries[position].get("timestamp"))
                if client_stamp is None or stamp > client_stamp:
                    entries[position] = deepcopy(stored_entry)
                    restored = True
                continue
            if synced is not None and stamp > synced:
                entries.append(deepcopy(stored_entry))
                restored = True
        if restored:
            entries.sort(
                key=lambda entry: _parse_datetime(entry.get("timestamp") if isinstance(entry, dict) else None)
                or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )


def _maintenance_entry_local_day(entry: dict[str, Any]) -> date | None:
    parsed = _parse_datetime(entry.get("timestamp"))
    return dt_util.as_local(parsed).date() if parsed is not None else None


def _maintenance_log_awc_change(
    config: dict[str, Any], now: datetime, litres: float, partial: bool, reason: str,
) -> None:
    """Log an automatic water change against the Maintenance water-change task.

    Tagged ``source="awc"`` — hand-logged completions carry no source, which is how the
    panel tells them apart. Runs on the same LOCAL day merge into one entry: a continuous
    schedule fires many times a day, and one row per slice would bury the manual history
    under MAINTENANCE_COMPLETIONS_MAX. Partial (aborted/faulted) changes are logged too —
    the water really did move — with the reason in the note.
    """
    if litres <= 0:
        return
    maintenance = config.get("maintenance")
    if not isinstance(maintenance, dict) or maintenance.get("logAwcChanges") is False:
        return
    tasks = maintenance.get("tasks")
    if not isinstance(tasks, dict):
        return
    # The curated water-change task, or whichever task the user set to log volume.
    task_id = MAINTENANCE_AWC_TASK_ID if MAINTENANCE_AWC_TASK_ID in tasks else next(
        (
            candidate
            for candidate, task in tasks.items()
            if isinstance(task, dict) and task.get("logsVolume")
        ),
        "",
    )
    if not task_id:
        return
    completions = maintenance.setdefault("completions", {})
    if not isinstance(completions, dict):
        completions = {}
        maintenance["completions"] = completions
    entries = completions.setdefault(task_id, [])
    if not isinstance(entries, list):
        entries = []
        completions[task_id] = entries

    timestamp = now.isoformat()
    note = "Automatic water change" + (f" — partial: {reason}" if partial and reason else "")
    newest = entries[0] if entries and isinstance(entries[0], dict) else None
    if (
        newest is not None
        and newest.get("source") == MAINTENANCE_SOURCE_AWC
        and newest.get("volumeUnit") == "L"
        and not newest.get("skipped")
        and _maintenance_entry_local_day(newest) == dt_util.as_local(now).date()
    ):
        prior = newest.get("volume")
        prior_l = float(prior) if isinstance(prior, (int, float)) and not isinstance(prior, bool) else 0.0
        newest["volume"] = round(prior_l + litres, 2)
        newest["timestamp"] = timestamp
        newest["notes"] = ("Automatic water changes today"
                           + (f" — last one partial: {reason}" if partial and reason else ""))[:500]
        return

    entries.insert(0, {
        "id": f"{task_id}:awc:{timestamp}",
        "timestamp": timestamp,
        "notes": note[:500],
        "volume": round(litres, 2),
        "volumeUnit": "L",
        "source": MAINTENANCE_SOURCE_AWC,
    })
    del entries[MAINTENANCE_COMPLETIONS_MAX:]


def _awc_record_history(
    awc: dict[str, Any], now: datetime, drained_l: float, filled_l: float,
    method: str, partial: bool, notes: str, config: dict[str, Any] | None = None,
) -> None:
    history = awc.setdefault("history", [])
    if not isinstance(history, list):
        history = []
        awc["history"] = history
    history.insert(0, {
        "completedAt": now.isoformat(),
        "drainedL": round(drained_l, 3),
        "filledL": round(filled_l, 3),
        "method": method if method in AWC_METHODS else "",
        "partial": bool(partial),
        "notes": notes[:200],
    })
    awc["history"] = history[:AWC_HISTORY_MAX]
    # The persistent ledger accumulates EVERY change (incl. aborted partials) beyond the
    # capped history — the honest net-imbalance basis at micro-change cadence.
    ledger = awc.get("ledger")
    if not isinstance(ledger, dict):
        ledger = {"cumulativeDrainedL": 0.0, "cumulativeFilledL": 0.0, "resetAt": ""}
        awc["ledger"] = ledger
    ledger["cumulativeDrainedL"] = round(_awc_num(ledger.get("cumulativeDrainedL"), 0, 0, 1e9) + max(0.0, drained_l), 3)
    ledger["cumulativeFilledL"] = round(_awc_num(ledger.get("cumulativeFilledL"), 0, 0, 1e9) + max(0.0, filled_l), 3)
    # Same hook for every path that records a change (finalize, abort-with-volume,
    # fault-ack), so the maintenance log can't drift from the AWC history.
    if config is not None:
        _maintenance_log_awc_change(config, now, max(0.0, filled_l), partial, notes)


async def _async_awc_finalize(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any], context: Any,
) -> None:
    await _async_awc_stop_pumps(hass, config, tuple(_awc_all_pump_roles(config)), context)
    awc = _awc_cfg(config)
    state = awc["state"]
    now = datetime.now(timezone.utc)
    fill_role = _awc_fill_role(state)  # read BEFORE the zeroing below clears it
    drained_l = _awc_moved(state, "drain") / 1000.0
    filled_l = _awc_moved(state, fill_role) / 1000.0
    _awc_record_history(awc, now, drained_l, filled_l, state.get("method", ""), False, "",
                        config=config)
    awc["history"][0]["source"] = fill_role
    ledger = awc["ledger"]
    per_source = ledger.setdefault("perSource", {})
    per_source[fill_role] = round(_awc_num(per_source.get(fill_role), 0, 0, 1e9) + filled_l, 3)
    # Net-salt ledger (Stage B): approximate grams of salt this change added — salt in
    # with the fill minus salt out with the drain. Only accumulates when BOTH the tank
    # target and the source's saltPpt are known; an honest 'unknown' beats a wrong number.
    source_res = awc.get("reservoirs", {}).get(awc_engine.pump_reservoir_id(awc, fill_role), {})
    salt_delta = awc_engine.net_salt_delta_g(
        drained_l, filled_l, _awc_tank_ppt(config),
        source_res.get("saltPpt") if isinstance(source_res, dict) else 0)
    if salt_delta is not None:
        ledger["netSaltGrams"] = round(
            _awc_num(ledger.get("netSaltGrams"), 0, -1e9, 1e9) + salt_delta, 1)
    awc["todayLitres"] = round(awc.get("todayLitres", 0) + filled_l, 3)
    awc["weekLitres"] = round(awc.get("weekLitres", 0) + filled_l, 3)
    awc["monthLitres"] = round(awc.get("monthLitres", 0) + filled_l, 3)
    # The completed change drew its fill from the mixing station's batch —
    # keep that ledger honest too (mixing doc §9; no-op when uncoupled).
    _mixing_debit_batch(hass, config, filled_l, "the water change")
    holdoff = awc.get("ato", {}).get("stabilizationHoldoffMinutes", AWC_DEFAULT_HOLDOFF_MINUTES)
    if state.get("microChange"):
        holdoff = 0  # micro-changes get no stabilization hold-off of their own
    prior_holdoff = _parse_datetime(state.get("atoSuspendedUntil"))
    if awc.get("ato", {}).get("suspendDuringChange", True) and holdoff > 0:
        state["atoSuspendedUntil"] = (now + timedelta(minutes=holdoff)).isoformat()
    elif prior_holdoff is not None and prior_holdoff > now:
        # A previous change's hold-off is still running — a micro-change finishing
        # inside it must not cancel it (or release the dosing hold below).
        pass
    else:
        state["atoSuspendedUntil"] = ""
    state["status"] = "idle"
    state["lastRun"] = now.isoformat()
    state["legStartedAt"] = ""
    state["legEndsAt"] = ""
    state["endsAt"] = {}
    state["exchangeBaselineNetMl"] = 0
    state["movedMl"] = {}
    state["activeSourceRole"] = ""
    state["targetLitres"] = 0
    state["method"] = ""
    state["pausedReason"] = ""
    state["microChange"] = False
    _append_activity(config, f"Water change complete: {filled_l:.1f} L exchanged", "control")
    if not state.get("atoSuspendedUntil"):
        # No stabilisation hold-off ⇒ dosing resumes now. With a hold-off, the ATO-restore
        # timer clears the firmware suspend switch when it fires; the firmware's own
        # auto-expiry backstops a dead HA (hold-off minutes << 4 h expiry).
        await _async_dosing_awc_suspend(hass, config, False, context)
    await _async_save_config(hass, entry, config)
    await _async_arm_awc_ato_restore(hass, entry, config)


async def _async_awc_leg_complete(
    hass: HomeAssistant, entry: OpenReefConfigEntry, context: Any,
) -> None:
    """A leg timer fired: stop the leg, account its volume, check safety, then begin the
    next leg / pause / fault / finalize. Locked so the volume accounting can't interleave
    with a concurrent start/abort and double-credit progress or the reservoirs; the
    config is fetched inside the lock (R1) so the status check sees a concurrent abort."""
    async with _awc_lock(hass):
        await _async_awc_leg_complete_locked(hass, entry, _config_from_entry(entry), context)


async def _async_awc_leg_complete_locked(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any], context: Any,
) -> None:
    awc = _awc_cfg(config)
    state = awc["state"]
    if state.get("status") not in _AWC_RUNNING_STATES:
        return
    method = state.get("method") or awc.get("schedule", {}).get("method", _AWC_SAFE_METHOD)
    fill_role = _awc_fill_role(state)
    target_ml = state.get("targetLitres", 0) * 1000.0
    drained = _awc_moved(state, "drain")
    filled = _awc_moved(state, fill_role)

    leg = awc_engine.plan_leg(method, drained, filled, target_ml, target_ml)
    if leg is None:
        await _async_awc_finalize(hass, entry, config, context)
        return
    # The engine plans in generic role labels — map "fill" to the ACTIVE source.
    leg = {**leg, "pumps": [fill_role if p == "fill" else p for p in leg["pumps"]]}
    pumps = leg["pumps"]
    await _async_awc_stop_pumps(hass, config, pumps, context)

    # Anomaly: did this leg run far longer than its calibrated runtime?
    slice_l = float(leg["sliceMl"]) / 1000.0
    expected = awc_engine.leg_runtime_s(slice_l, awc, pumps)
    started = _parse_datetime(state.get("legStartedAt"))
    elapsed = (datetime.now(timezone.utc) - started).total_seconds() if started else expected
    safety = awc.get("safety", {})
    verdict = awc_engine.anomaly_verdict(elapsed, expected,
                                         safety.get("anomalyWarnMult", 2.0),
                                         safety.get("anomalyAbortMult", 3.0))
    if verdict == "abort":
        await _async_awc_abort(
            hass, entry, config,
            f"Runtime anomaly on {'/'.join(pumps)} leg ({elapsed:.0f}s vs {expected:.0f}s expected)",
            True, False, context,
        )
        return
    if verdict == "warn" and not state.get("anomalyWarned"):
        # Surface the warn tier once per change (T8) — previously computed and discarded.
        state["anomalyWarned"] = True
        warn_msg = (f"Water change leg on {'/'.join(pumps)} ran {elapsed:.0f}s vs "
                    f"{expected:.0f}s expected — check for a clogged line, kinked tube, "
                    "or a slipping pump")
        _append_activity(config, warn_msg, "warning")
        await _async_awc_notify(
            hass, config, "pausedFault", "openreef_awc_anomaly",
            "Water change running long", warn_msg)

    # Account the leg's volume against progress + the dead-reckoned reservoirs, and bump
    # each pump's lifetime run-seconds by its calibrated time for the credited volume.
    slice_ml = float(leg["sliceMl"])
    reservoirs = awc.get("reservoirs", {})
    for role in pumps:
        p = awc.get("pumps", {}).get(role, {}) if isinstance(awc.get("pumps"), dict) else {}
        _awc_bump_odometer(awc, role, seconds=awc_engine.runtime_for_volume_s(
            slice_ml / 1000.0, p.get("mlPerS"), p.get("exchangeFactor", 1.0), p.get("spinUpMl", 0.0)))
    if "drain" in pumps:
        _awc_set_moved(state, "drain", drained + slice_ml)
        waste = reservoirs.get("waste", {})
        cap_ml = waste.get("capacityLitres", 0) * 1000.0
        waste["filledMl"] = min(cap_ml, waste.get("filledMl", 0) + slice_ml) if cap_ml else waste.get("filledMl", 0) + slice_ml
    if fill_role in pumps:
        _awc_set_moved(state, fill_role, filled + slice_ml)
        _awc_debit_source(awc, fill_role, slice_ml)
    # The slice is credited — clear the leg stamps NOW so the abort/pause paths below
    # (which dead-reckon interrupted legs from these stamps, R6/R9) can never credit
    # this same leg a second time. begin_leg re-stamps for the next leg.
    state["legStartedAt"] = ""
    state["legEndsAt"] = ""

    next_leg = awc_engine.plan_leg(
        method, _awc_moved(state, "drain"), _awc_moved(state, fill_role), target_ml, target_ml)
    if next_leg is None:
        await _async_awc_finalize(hass, entry, config, context)
        return
    next_leg = {**next_leg,
                "pumps": [fill_role if p == "fill" else p for p in next_leg["pumps"]]}

    needs_drain = "drain" in next_leg["pumps"]
    needs_fill = fill_role in next_leg["pumps"]
    live = _awc_live_state(hass, config, fill_role=fill_role)
    verdict = awc_engine.in_run_safety(awc, live, needs_drain, needs_fill)
    if verdict["action"] == "fault":
        await _async_awc_abort(hass, entry, config, verdict["reason"], True, verdict.get("masterKill", False), context)
        return
    if verdict["action"] == "pause":
        await _async_awc_pause(hass, entry, config, verdict["reason"], context)
        return

    begun, reason = await _async_awc_begin_leg(hass, config, method, next_leg, datetime.now(timezone.utc), context)
    if not begun:
        _append_activity(config, reason, "control")
        await _async_save_config(hass, entry, config)
        return
    await _async_save_config(hass, entry, config)


async def _async_awc_exchange_tick(
    hass: HomeAssistant, entry: OpenReefConfigEntry, context: Any,
) -> None:
    """Simultaneous-mode monitor tick: dead-reckon each pump from its own stop time,
    account the reservoirs incrementally, stop pumps as they finish, enforce the
    instantaneous imbalance cap + live safety, then finalize or re-arm. Independent
    per-pump timing means each pump moves exactly the target — no over-pump. Locked so a
    re-entrant tick (or a concurrent abort) can't double-debit the reservoirs; config
    fetched inside the lock (R1)."""
    async with _awc_lock(hass):
        await _async_awc_exchange_tick_locked(hass, entry, _config_from_entry(entry), context)


async def _async_awc_exchange_tick_locked(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any], context: Any,
) -> None:
    awc = _awc_cfg(config)
    state = awc["state"]
    if state.get("status") != "exchanging":
        return
    now = datetime.now(timezone.utc)
    fill_role = _awc_fill_role(state)
    target_ml = state.get("targetLitres", 0) * 1000.0
    pumps = awc.get("pumps", {})
    drain = pumps.get("drain", {}) if isinstance(pumps.get("drain"), dict) else {}
    fill = pumps.get(fill_role, {}) if isinstance(pumps.get(fill_role), dict) else {}

    # Mid-run rate-zeroing (a raw settings write racing the run — the calibrate WS is
    # busy-blocked): dead-reckoning a zero rate reads as 'full target moved' and would
    # phantom-complete the change. Pause WITHOUT crediting this tick (R26).
    drain_unfinished = target_ml - _awc_moved(state, "drain") > 1e-6
    fill_unfinished = target_ml - _awc_moved(state, fill_role) > 1e-6
    if (drain_unfinished and _awc_num(drain.get("mlPerS"), 0, 0, 1e9) <= 0) or (
            fill_unfinished and _awc_num(fill.get("mlPerS"), 0, 0, 1e9) <= 0):
        # Credit the HEALTHY side's progress up to now first (the helper skips
        # zero-rate sides) — or its last tick of pumped volume would be replayed
        # on resume and its reservoir model would drift by the same amount.
        _awc_credit_interrupted_exchange(awc, now)
        await _async_awc_pause(
            hass, entry, config,
            "Pump calibration was cleared mid-run — recalibrate, then resume", context,
        )
        return

    drain_ends = _parse_datetime(_awc_ends(state, "drain"))
    fill_ends = _parse_datetime(_awc_ends(state, fill_role))
    drain_rem_s = (drain_ends - now).total_seconds() if drain_ends else 0.0
    fill_rem_s = (fill_ends - now).total_seconds() if fill_ends else 0.0

    drained_ml, drain_done = awc_engine.exchange_side_progress(
        drain_rem_s, drain.get("mlPerS"), drain.get("exchangeFactor", 1.0), target_ml)
    filled_ml, fill_done = awc_engine.exchange_side_progress(
        fill_rem_s, fill.get("mlPerS"), fill.get("exchangeFactor", 1.0), target_ml)

    # Incremental reservoir dead-reckoning (delta since the last tick).
    reservoirs = awc.get("reservoirs", {})
    d_drain = max(0.0, drained_ml - _awc_moved(state, "drain"))
    d_fill = max(0.0, filled_ml - _awc_moved(state, fill_role))
    if d_drain > 0:
        waste = reservoirs.get("waste", {})
        cap_ml = waste.get("capacityLitres", 0) * 1000.0
        waste["filledMl"] = min(cap_ml, waste.get("filledMl", 0) + d_drain) if cap_ml else waste.get("filledMl", 0) + d_drain
        _awc_bump_odometer(awc, "drain", seconds=awc_engine.runtime_for_volume_s(
            d_drain / 1000.0, drain.get("mlPerS"), drain.get("exchangeFactor", 1.0)))
    if d_fill > 0:
        _awc_debit_source(awc, fill_role, d_fill)
        _awc_bump_odometer(awc, fill_role, seconds=awc_engine.runtime_for_volume_s(
            d_fill / 1000.0, fill.get("mlPerS"), fill.get("exchangeFactor", 1.0)))
    _awc_set_moved(state, "drain", drained_ml)
    _awc_set_moved(state, fill_role, filled_ml)

    # Best-effort per-side stops (R11): a raising turn_off (ESP unreachable) must not
    # abandon the tick half-done — the accounting save and timer re-arm below still run
    # (the watchdog + read-back cover a genuinely stuck actuator).
    if drain_done:
        await _async_awc_stop_pumps(hass, config, ("drain",), context)
    if fill_done:
        await _async_awc_stop_pumps(hass, config, (fill_role,), context)

    cap = awc.get("safety", {}).get("maxInstantaneousImbalanceLitres", AWC_DEFAULT_MAX_INSTANT_IMBALANCE_L)
    baseline = state.get("exchangeBaselineNetMl", 0)
    if awc_engine.exchange_imbalance_exceeds(drained_ml, filled_ml, cap, baseline):
        await _async_awc_abort(
            hass, entry, config,
            f"Simultaneous imbalance exceeded {cap} L "
            f"(drain {drained_ml / 1000:.2f} L / fill {filled_ml / 1000:.2f} L) — pumps too mismatched",
            True, False, context,
        )
        return

    live = _awc_live_state(hass, config, fill_role=fill_role)
    verdict = awc_engine.in_run_safety(awc, live, not drain_done, not fill_done)
    if verdict["action"] == "fault":
        await _async_awc_abort(hass, entry, config, verdict["reason"], True, verdict.get("masterKill", False), context)
        return
    if verdict["action"] == "pause":
        await _async_awc_pause(hass, entry, config, verdict["reason"], context)
        return

    if drain_done and fill_done:
        await _async_awc_finalize(hass, entry, config, context)
        return

    candidates = [now + timedelta(seconds=AWC_EXCHANGE_TICK_SECONDS)]
    if not drain_done and drain_ends:
        candidates.append(drain_ends)
    if not fill_done and fill_ends:
        candidates.append(fill_ends)
    state["legEndsAt"] = min(candidates).isoformat()
    await _async_save_config(hass, entry, config)


async def _async_arm_awc_timer(
    hass: HomeAssistant, entry: OpenReefConfigEntry, run_at: datetime,
) -> None:
    now = datetime.now(timezone.utc)
    if run_at <= now:
        run_at = now + timedelta(seconds=1)
    _clear_awc_timer(hass)

    async def _handle(_now: datetime) -> None:
        hass.data.setdefault(DOMAIN, {}).pop(AWC_UNSUB, None)
        latest_entry = _first_entry(hass)
        if latest_entry is None or latest_entry.entry_id != entry.entry_id:
            return
        await _async_awc_timer_fired(hass, latest_entry, None)

    hass.data.setdefault(DOMAIN, {})[AWC_UNSUB] = async_track_point_in_time(hass, _handle, run_at)


async def _async_awc_timer_fired(
    hass: HomeAssistant, entry: OpenReefConfigEntry, context: Any,
) -> None:
    """Leg/exchange timer target. The method DISPATCH happens inside the lock on the
    fresh config (R1): with a pre-lock snapshot, a change aborted-and-restarted with a
    different method could route an exchanging state into the sequential handler.
    Sequential fires route through the mid-leg safety checkpoint (R9). The finally-arm
    keeps the monitor alive if a handler dies mid-flight — e.g. a save failure after
    the pumps were driven (R11): a dead timer while pumps run is the 'keep filling
    forever' hazard."""
    try:
        async with _awc_lock(hass):
            config = _config_from_entry(entry)
            if _awc_cfg(config).get("state", {}).get("method") == "batch_simultaneous":
                await _async_awc_exchange_tick_locked(hass, entry, config, context)
            else:
                await _async_awc_sequential_checkpoint_locked(hass, entry, config, context)
    finally:
        if hass.data.setdefault(DOMAIN, {}).get(AWC_UNSUB) is None:
            state = _awc_cfg(_config_from_entry(entry)).get("state", {})
            if state.get("status") in _AWC_RUNNING_STATES:
                await _async_arm_awc_timer(
                    hass, entry,
                    datetime.now(timezone.utc) + timedelta(seconds=AWC_EXCHANGE_TICK_SECONDS),
                )


async def _async_awc_sequential_checkpoint_locked(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any], context: Any,
) -> None:
    """Sequential timer target (R9): until the leg's scheduled end arrives this is a
    mid-leg SAFETY checkpoint — a leak tripping 10 s into a 3-minute drain leg must
    stop the pumps NOW, not when the leg finally completes (the exchange path has had
    this via its 2 s tick all along; this is the sequential parity). At/after the
    scheduled end it falls through to the ordinary leg-complete accounting."""
    awc = _awc_cfg(config)
    state = awc["state"]
    status = state.get("status")
    if status not in ("draining", "filling"):
        if status in _AWC_RUNNING_STATES:
            await _async_awc_leg_complete_locked(hass, entry, config, context)
        return
    ends = _parse_datetime(state.get("legEndsAt"))
    now = datetime.now(timezone.utc)
    if ends is None or now >= ends - timedelta(milliseconds=500):
        await _async_awc_leg_complete_locked(hass, entry, config, context)
        return
    live = _awc_live_state(hass, config, fill_role=_awc_fill_role(state))
    verdict = awc_engine.in_run_safety(awc, live, status == "draining", status == "filling")
    if verdict["action"] == "fault":
        await _async_awc_abort(hass, entry, config, verdict["reason"], True,
                               verdict.get("masterKill", False), context)
        return
    if verdict["action"] == "pause":
        await _async_awc_pause(hass, entry, config, verdict["reason"], context)
        return
    await _async_arm_awc_timer(
        hass, entry, min(ends, now + timedelta(seconds=AWC_EXCHANGE_TICK_SECONDS)))


async def _async_schedule_awc(
    hass: HomeAssistant, entry: OpenReefConfigEntry | None, config: dict[str, Any] | None = None,
) -> None:
    """Clear and (if a leg is in flight) re-arm the single AWC leg timer. Called from
    _async_save_config and startup. Pumps are driven at leg-begin, not here."""
    _clear_awc_timer(hass)
    if entry is None:
        return
    config = config or _config_from_entry(entry)
    awc = _awc_cfg(config)
    state = awc.get("state", {})
    if not isinstance(state, dict) or state.get("status") not in _AWC_RUNNING_STATES:
        return
    ends = _parse_datetime(state.get("legEndsAt"))
    if ends is None:
        return
    run_at = ends
    if state.get("method") != "batch_simultaneous" and state.get("status") in ("draining", "filling"):
        # Sequential legs get mid-leg safety checkpoints (R9): fire at the exchange-tick
        # cadence; the handler completes the leg only once `ends` actually arrives.
        run_at = min(ends, datetime.now(timezone.utc) + timedelta(seconds=AWC_EXCHANGE_TICK_SECONDS))
    await _async_arm_awc_timer(hass, entry, run_at)


async def _async_arm_awc_ato_restore(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any],
) -> None:
    """Arm the post-change ATO stabilization hold-off expiry: clears the suspension so
    the ATO resumes normal control."""
    store = hass.data.setdefault(DOMAIN, {})
    old = store.pop(AWC_ATO_RESTORE_UNSUB, None)
    if old is not None:
        old()
    until = _parse_datetime(_awc_cfg(config).get("state", {}).get("atoSuspendedUntil"))
    if until is None:
        return
    now = datetime.now(timezone.utc)
    run_at = until if until > now else now + timedelta(seconds=1)

    async def _handle(_now: datetime) -> None:
        hass.data.setdefault(DOMAIN, {}).pop(AWC_ATO_RESTORE_UNSUB, None)
        latest_entry = _first_entry(hass)
        if latest_entry is None or latest_entry.entry_id != entry.entry_id:
            return
        # Fetch + mutate under the lock (R1): this timer previously raced the leg
        # handlers' saves with an unlocked read-modify-write of the whole config.
        async with _awc_lock(hass):
            latest_config = _config_from_entry(latest_entry)
            state = _awc_cfg(latest_config).get("state", {})
            # 'fault' included (R12): a latched fault keeps dosing held — this expiry
            # must not release the suspend switch out from under it.
            if state.get("status") in (*_AWC_RUNNING_STATES, "paused", "fault"):
                return
            u = _parse_datetime(state.get("atoSuspendedUntil"))
            if u is not None and u > datetime.now(timezone.utc):
                return
            state["atoSuspendedUntil"] = ""
            await _async_dosing_awc_suspend(hass, latest_config, False, None)
            _append_activity(latest_config, "ATO resumed after water-change stabilization hold-off", "control")
            await _async_save_config(hass, latest_entry, latest_config)

    store[AWC_ATO_RESTORE_UNSUB] = async_track_point_in_time(hass, _handle, run_at)


def _awc_credit_interrupted_leg(awc: dict[str, Any], now: datetime) -> None:
    """Dead-reckon and credit a sequential leg that was interrupted mid-run (restart /
    power loss). Sequential legs otherwise credit volume only when the leg timer fires, so
    resume-to-balance would replay the WHOLE slice — 8 L already moved + a 10 L replay is
    ~8 L of overfill with the reservoir debited only 10 L. We credit the elapsed portion of
    the leg (clamped to its scheduled window) at the pump's calibrated rate, mirror it into
    the reservoir model, then clear the leg stamps so a re-entry can never double-credit.
    Directionally safe: after a power cut the pump stopped early, so elapsed-time credit can
    only OVER-credit ⇒ the change under-delivers rather than overfills; after an HA-only
    restart the pump genuinely kept running, and the credit is accurate up to the stamped
    stop time (beyond it lies firmware-watchdog territory). Simultaneous legs don't need
    this — their tick already persists per-pump progress every couple of seconds."""
    state = awc.get("state", {})
    role = {"draining": "drain", "filling": _awc_fill_role(state)}.get(state.get("status", ""))
    started = _parse_datetime(state.get("legStartedAt"))
    ends = _parse_datetime(state.get("legEndsAt"))
    if role is None or started is None or ends is None or ends <= started:
        return
    ran_s = max(0.0, (min(now, ends) - started).total_seconds())
    pump = awc.get("pumps", {}).get(role, {}) if isinstance(awc.get("pumps"), dict) else {}
    moved_ml = awc_engine.volume_for_runtime_l(
        ran_s, pump.get("mlPerS"), pump.get("exchangeFactor", 1.0), pump.get("spinUpMl", 0.0)
    ) * 1000.0
    target_ml = state.get("targetLitres", 0) * 1000.0
    moved_ml = max(0.0, min(moved_ml, target_ml - _awc_moved(state, role)))
    if moved_ml <= 0:
        state["legStartedAt"] = ""
        state["legEndsAt"] = ""
        return
    _awc_set_moved(state, role, _awc_moved(state, role) + moved_ml)
    _awc_bump_odometer(awc, role, seconds=ran_s)
    reservoirs = awc.get("reservoirs", {}) if isinstance(awc.get("reservoirs"), dict) else {}
    if role == "drain":
        waste = reservoirs.get("waste", {})
        cap_ml = waste.get("capacityLitres", 0) * 1000.0
        waste["filledMl"] = min(cap_ml, waste.get("filledMl", 0) + moved_ml) if cap_ml else waste.get("filledMl", 0) + moved_ml
    else:
        _awc_debit_source(awc, role, moved_ml)
    state["legStartedAt"] = ""
    state["legEndsAt"] = ""


def _awc_credit_interrupted_exchange(awc: dict[str, Any], now: datetime) -> None:
    """Dead-reckon run-on for an interrupted SIMULTANEOUS exchange (R10). The tick
    persists progress every ~2 s while HA is up, but across HA downtime the ESP kept
    each pump running toward its persisted stop time (nothing told it otherwise) —
    credit each side up to min(now, its stop time) before replanning, or
    resume-to-balance re-runs volume that already moved and the reservoir models drift
    by the same amount. Clears the per-side stop stamps so a re-entry can never
    double-credit (begin_exchange re-stamps them). Directionally safe on a power cut
    for the same reason as the sequential credit: over-credit ⇒ under-delivery, never
    an overfill. Uncalibrated sides are skipped — a zero rate dead-reckons as
    'phantom-complete', which is exactly the lie this function must not tell."""
    state = awc.get("state", {})
    if state.get("status") != "exchanging":
        return
    target_ml = state.get("targetLitres", 0) * 1000.0
    reservoirs = awc.get("reservoirs", {}) if isinstance(awc.get("reservoirs"), dict) else {}
    pumps = awc.get("pumps", {}) if isinstance(awc.get("pumps"), dict) else {}
    for role in ("drain", _awc_fill_role(state)):
        ends = _parse_datetime(_awc_ends(state, role))
        if ends is None:
            continue
        _awc_set_ends(state, role, "")
        pump = pumps.get(role, {}) if isinstance(pumps.get(role), dict) else {}
        if _awc_num(pump.get("mlPerS"), 0, 0, 1e9) <= 0:
            continue
        rem_s = max(0.0, (ends - now).total_seconds())
        moved_ml, _done = awc_engine.exchange_side_progress(
            rem_s, pump.get("mlPerS"), pump.get("exchangeFactor", 1.0), target_ml)
        delta = moved_ml - _awc_moved(state, role)
        if delta <= 0:
            continue
        _awc_set_moved(state, role, moved_ml)
        _awc_bump_odometer(awc, role, seconds=awc_engine.runtime_for_volume_s(
            delta / 1000.0, pump.get("mlPerS"), pump.get("exchangeFactor", 1.0)))
        if role == "drain":
            waste = reservoirs.get("waste", {})
            cap_ml = waste.get("capacityLitres", 0) * 1000.0
            waste["filledMl"] = min(cap_ml, waste.get("filledMl", 0) + delta) if cap_ml else waste.get("filledMl", 0) + delta
        else:
            _awc_debit_source(awc, role, delta)


async def _async_awc_relaunch(
    hass: HomeAssistant, entry: OpenReefConfigEntry,
    context: Any, log_message: str, resume_only: bool = False,
) -> bool:
    """Resume/relaunch the current change from persisted progress (resume-to-balance),
    dispatching sequential vs simultaneous. Returns True if it relaunched or completed,
    False if blocked (fault latched / paused). Locked: the interrupted-leg credit + the
    re-begin must be atomic against timers and other resumes; config fetched inside
    the lock (R1). ``resume_only`` restricts the relaunch to a still-PAUSED change —
    the resume paths pass it so a queued duplicate resume (double-click, or the
    minutely auto-resume racing a manual Resume) can't stop-and-restart the leg the
    first resume just began; only the startup path may relaunch a running change."""
    async with _awc_lock(hass):
        return await _async_awc_relaunch_locked(
            hass, entry, _config_from_entry(entry), context, log_message, resume_only
        )


async def _async_awc_relaunch_locked(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any],
    context: Any, log_message: str, resume_only: bool = False,
) -> bool:
    awc = _awc_cfg(config)
    state = awc["state"]
    # Re-validate on the fresh-under-lock status: a queued resume must not
    # resurrect a change that was aborted/acknowledged while it waited (R1).
    if state.get("status") not in (*_AWC_RUNNING_STATES, "paused"):
        return False
    if resume_only and state.get("status") != "paused":
        return False
    method = state.get("method") or awc.get("schedule", {}).get("method", _AWC_SAFE_METHOD)
    fill_role = _awc_fill_role(state)
    if method != "batch_simultaneous":
        # Credit the elapsed portion of an interrupted sequential leg BEFORE planning, so
        # the resumed leg targets only the genuinely-unmoved remainder (a pause path has
        # already cleared the leg stamps, so this is inert for a plain paused resume).
        _awc_credit_interrupted_leg(awc, datetime.now(timezone.utc))
    else:
        # Same for a simultaneous exchange interrupted by HA downtime: the ESP kept the
        # pumps running toward their persisted stop times after the last tick save —
        # credit that run-on before replanning (R10). Inert for a paused resume.
        _awc_credit_interrupted_exchange(awc, datetime.now(timezone.utc))
    target_ml = state.get("targetLitres", 0) * 1000.0
    drained = _awc_moved(state, "drain")
    filled = _awc_moved(state, fill_role)
    eps = 1e-6
    leg = None
    if method == "batch_simultaneous":
        needs_drain = (target_ml - drained) > eps
        needs_fill = (target_ml - filled) > eps
        if not needs_drain and not needs_fill:
            await _async_awc_finalize(hass, entry, config, context)
            return True
    else:
        leg = awc_engine.plan_leg(method, drained, filled, target_ml, target_ml)
        if leg is None:
            await _async_awc_finalize(hass, entry, config, context)
            return True
        # The engine plans in generic role labels — map "fill" to the ACTIVE source.
        leg = {**leg, "pumps": [fill_role if p == "fill" else p for p in leg["pumps"]]}
        needs_drain = "drain" in leg["pumps"]
        needs_fill = fill_role in leg["pumps"]

    live = _awc_live_state(hass, config, fill_role=fill_role)
    verdict = awc_engine.in_run_safety(awc, live, needs_drain, needs_fill)
    if verdict["action"] == "fault":
        await _async_awc_abort(hass, entry, config, verdict["reason"], True, verdict.get("masterKill", False), context)
        return False
    if verdict["action"] == "pause":
        if state.get("status") == "paused":
            if verdict["reason"] != state.get("pausedReason"):
                state["pausedReason"] = verdict["reason"]
                await _async_save_config(hass, entry, config)
        else:
            await _async_awc_pause(hass, entry, config, verdict["reason"], context)
        return False

    # A pump whose calibration was cleared while paused keeps the change PAUSED
    # (recalibrate → resume) — otherwise the minutely auto-resume would escalate the
    # benign pause into a latched fault via the begin-path calibration guards (R26).
    if state.get("status") == "paused":
        pumps_cfg = awc.get("pumps", {}) if isinstance(awc.get("pumps"), dict) else {}
        needed = [r for r, need in (("drain", needs_drain), (fill_role, needs_fill)) if need]
        if any(_awc_num((pumps_cfg.get(r) or {}).get("mlPerS"), 0, 0, 1e9) <= 0 for r in needed):
            reason = "A pump is not calibrated — recalibrate, then resume"
            if state.get("pausedReason") != reason:
                state["pausedReason"] = reason
                await _async_save_config(hass, entry, config)
            return False

    now = datetime.now(timezone.utc)
    # After an HA-only restart the ESP may still be running the OLD leg's pump (nothing
    # stopped it), and the re-planned leg may drive a DIFFERENT pump — stop everything
    # first so begin re-energises exactly the pumps the new plan calls for.
    await _async_awc_stop_pumps(hass, config, tuple(_awc_all_pump_roles(config)), context)
    if method == "batch_simultaneous":
        begun, reason = await _async_awc_begin_exchange(hass, config, now, context)
    else:
        begun, reason = await _async_awc_begin_leg(hass, config, method, leg, now, context)
    if not begun:
        _append_activity(config, reason, "control")
        await _async_save_config(hass, entry, config)
        return False
    _append_activity(config, log_message, "control")
    await _async_save_config(hass, entry, config)
    return True


async def _async_awc_try_resume(
    hass: HomeAssistant, entry: OpenReefConfigEntry, context: Any,
) -> bool:
    """Attempt to resume a paused change. Returns True if it resumed/completed.
    The paused peek here is advisory; relaunch re-validates fresh under the lock."""
    if _awc_cfg(_config_from_entry(entry)).get("state", {}).get("status") != "paused":
        return False
    return await _async_awc_relaunch(
        hass, entry, context, "Water change resumed", resume_only=True
    )


async def _async_awc_resume_on_startup(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any],
) -> None:
    """On startup, recover an interrupted change. A running change is re-begun from the
    persisted drained/filled (resume-to-balance); a paused change is re-evaluated."""
    status = _awc_cfg(config).get("state", {}).get("status")
    if status in _AWC_RUNNING_STATES:
        await _async_awc_relaunch(hass, entry, None, "Water change resumed after restart (resume-to-balance)")
    elif status == "paused":
        await _async_awc_try_resume(hass, entry, None)


def _awc_refresh_next_run(config: dict[str, Any], now_local: datetime) -> None:
    acfg = _awc_cfg(config)
    sched = acfg.get("schedule", {})
    last_run = _parse_datetime(acfg.get("state", {}).get("lastRun"))
    nxt = awc_engine.next_run(sched, last_run, now_local) if sched.get("enabled") else None
    acfg.get("state", {})["nextRun"] = nxt.isoformat() if nxt else ""


async def _async_awc_schedule_tick(
    hass: HomeAssistant, entry: OpenReefConfigEntry, now_local: datetime,
) -> None:
    """One scheduler tick (called ~every minute). Auto-resumes a paused change, or starts
    a due batch change (sequential or simultaneous). Continuous/trickle stays
    projection-only and is coerced to the safe sequential default."""
    config = _config_from_entry(entry)  # read-only peek; mutating paths re-fetch under the lock
    acfg = _awc_cfg(config)
    state = acfg.get("state", {})

    # Fill-pump drift check (Stage A): grade the model against reality the moment
    # a source reservoir's empty float trips — latched once per fill cycle, and
    # evaluated for every source reservoir the config actually has (Stage B).
    tick_reservoirs = acfg.get("reservoirs", {}) if isinstance(acfg.get("reservoirs"), dict) else {}
    for rid in ("fresh", "fresh2"):
        if isinstance(tick_reservoirs.get(rid), dict):
            await _async_awc_check_drift_on_empty(hass, entry, rid)
    # Advisory notification tier (Stage A): reservoir-low / recalibration-due /
    # net-drift, each once per cooldown.
    await _async_awc_advisory_notifications(hass, config)

    # Auto-resume a paused change as soon as its blocking condition clears.
    if state.get("status") == "paused":
        await _async_awc_try_resume(hass, entry, None)
        return
    if state.get("status") in (*_AWC_RUNNING_STATES, "fault"):
        return  # busy or latched — never auto-start over a fault

    if not acfg.get("enabled"):
        return
    # NPS feed-exchange (Stage B): the owed matched drain runs from the same
    # idle path — a started drain claims this tick (the busy gate keeps a
    # change from starting over it, and vice versa).
    if await _async_nps_matched_drain_maybe(hass, entry, now_local):
        return
    sched = acfg.get("schedule", {})
    if not sched.get("enabled"):
        await _async_awc_persist_next_run(hass, entry, now_local)
        return

    method = sched.get("method", _AWC_SAFE_METHOD)
    if method not in AWC_LIVE_METHODS:  # continuous is projection-only; fall back to safe default
        method = _AWC_SAFE_METHOD
    tank = _awc_effective_tank_l(config)
    last_run = _parse_datetime(state.get("lastRun"))
    armed_at = _parse_datetime(state.get("scheduleArmedAt"))
    if armed_at is not None and (last_run is None or armed_at > last_run):
        # A slot that had already passed when the schedule was (re)armed is not
        # unserved backlog (R24) — it waits for its next occurrence.
        last_run = armed_at

    slot = awc_engine.due_slot(sched, last_run, now_local)
    if slot is not None:
        litres = awc_engine.per_change_litres(sched, tank)
        if litres > 0:
            if (now_local - slot) >= timedelta(hours=AWC_BLOCKED_SLOT_EXPIRY_HOURS):
                # Stale-slot expiry (T7): a slot that stayed blocked/unserved this long
                # must not fire a surprise change whenever its blocker finally clears.
                await _async_awc_expire_slot(hass, entry, slot)
                return
            if str(sched.get("mode", "times")).lower() == "interval":
                # Coalesce missed interval slots into ONE catch-up change (HA down /
                # a blocked hour): n fresh unserved micro-slots → n× the per-slot
                # volume, clamped to the single-change cap. Slots past the expiry
                # window were forfeited (same T7 rule the latest slot lives under).
                fresh_slots = [
                    s for s in awc_engine.due_slots(sched, last_run, now_local)
                    if (now_local - s) < timedelta(hours=AWC_BLOCKED_SLOT_EXPIRY_HOURS)
                ]
                if len(fresh_slots) > 1:
                    litres *= len(fresh_slots)
                    pct = _awc_num(
                        acfg.get("safety", {}).get("maxSingleChangePercent"),
                        AWC_DEFAULT_MAX_SINGLE_CHANGE_PCT, 0, 100,
                    )
                    if tank > 0 and pct > 0:
                        # Floor the cap to the start path's 3-decimal precision: an
                        # exact-cap clamp re-tripped the cap guard after rounding
                        # (cap 15.8375 → target rounds to 15.838 > cap) and
                        # deadlocked the schedule for the rest of the day.
                        litres = min(litres, math.floor(tank * pct * 10) / 1000.0)
            started, reasons = await _async_awc_start(hass, entry, litres, method, False, None)
            if not started:
                await _async_awc_note_blocked_slot(hass, entry, slot, reasons)
            return
    await _async_awc_persist_next_run(hass, entry, now_local)


async def _async_awc_expire_slot(
    hass: HomeAssistant, entry: OpenReefConfigEntry, slot: datetime,
) -> None:
    """Consume a stale unserved schedule slot (T7): stamp it served and say so, so the
    tick stops retrying and the change can't fire hours late as a surprise. (Slots in
    the last expiry-window hours of the day leave due_slot candidacy at midnight
    instead — same volumetric outcome, just without this log entry.)"""
    async with _awc_lock(hass):
        config = _config_from_entry(entry)
        state = _awc_cfg(config).get("state", {})
        if state.get("status") in (*_AWC_RUNNING_STATES, "paused", "fault"):
            return
        # Re-validate the slot on the fresh config: a concurrent overlapping tick may
        # already have expired it (or a change ran) while we waited on the lock.
        last_run = _parse_datetime(state.get("lastRun"))
        armed_at = _parse_datetime(state.get("scheduleArmedAt"))
        if armed_at is not None and (last_run is None or armed_at > last_run):
            last_run = armed_at
        if last_run is not None and last_run >= slot:
            return
        state["lastRun"] = datetime.now(timezone.utc).isoformat()
        state["blockedSlotKey"] = ""
        _append_activity(
            config,
            f"Scheduled water change ({slot.strftime('%H:%M')}) expired unserved after "
            f"{AWC_BLOCKED_SLOT_EXPIRY_HOURS} h — start one manually if still wanted",
            "warning",
        )
        await _async_save_config(hass, entry, config)


async def _async_awc_note_blocked_slot(
    hass: HomeAssistant, entry: OpenReefConfigEntry, slot: datetime,
    reasons: list[dict[str, str]],
) -> None:
    """Surface a blocked scheduled start ONCE per slot (T7) — the minutely tick used
    to retry silently, leaving 'why didn't my water change run?' unanswerable."""
    codes = {r.get("code") for r in reasons if isinstance(r, dict)}
    if codes & {"busy", "paused"}:
        return  # a change is already in flight — not a real block
    # Key on the DAY + blocker, not the slot instant: interval mode mints a new slot
    # every everyMinutes, and a persistent blocker (quiet hours, an empty reservoir
    # overnight) would otherwise push a phone notification + a config save per slot,
    # up to 96 times a day. Same blocker, same day → one note.
    slot_key = f"{slot.date().isoformat()}|{'|'.join(sorted(str(c) for c in codes))}"
    async with _awc_lock(hass):
        config = _config_from_entry(entry)
        state = _awc_cfg(config).get("state", {})
        if state.get("blockedSlotKey") == slot_key:
            return
        state["blockedSlotKey"] = slot_key
        detail = "; ".join(
            str(r.get("message") or r.get("code") or "")
            for r in reasons[:3] if isinstance(r, dict)
        ) or "blocked"
        _append_activity(config, f"Scheduled water change blocked: {detail}", "warning")
        await _async_awc_notify(
            hass, config, "pausedFault", "openreef_awc_blocked",
            "Scheduled water change blocked", detail)
        await _async_save_config(hass, entry, config)


async def _async_awc_persist_next_run(
    hass: HomeAssistant, entry: OpenReefConfigEntry, now_local: datetime,
) -> None:
    """Persist the refreshed nextRun display value. Fetched + saved under the lock
    (R1): the tick's old trailing save wrote its whole minute-old snapshot back,
    which could clobber a change that started concurrently. Saves only on change."""
    async with _awc_lock(hass):
        config = _config_from_entry(entry)
        state = _awc_cfg(config).get("state", {})
        before = state.get("nextRun")
        _awc_refresh_next_run(config, now_local)
        if state.get("nextRun") != before:
            await _async_save_config(hass, entry, config)


def _clear_awc_scheduler(hass: HomeAssistant) -> None:
    store = hass.data.setdefault(DOMAIN, {})
    unsub = store.pop(AWC_SCHEDULE_UNSUB, None)
    if unsub is not None:
        unsub()


async def _async_schedule_awc_scheduler(
    hass: HomeAssistant, entry: OpenReefConfigEntry | None, config: dict[str, Any] | None = None,
) -> None:
    """Arm/disarm the ~minute scheduler tick that drives scheduled sequential changes
    and auto-resumes paused ones."""
    _clear_awc_scheduler(hass)
    if entry is None:
        return
    config = config or _config_from_entry(entry)
    acfg = _awc_cfg(config)
    if not acfg.get("enabled"):
        return
    # Run the tick if there's a schedule to drive OR a paused change to recover.
    if not acfg.get("schedule", {}).get("enabled") and acfg.get("state", {}).get("status") != "paused":
        return

    async def _handle(now: datetime) -> None:
        latest_entry = _first_entry(hass)
        if latest_entry is None or latest_entry.entry_id != entry.entry_id:
            return
        await _async_awc_schedule_tick(hass, latest_entry, dt_util.now())

    hass.data.setdefault(DOMAIN, {})[AWC_SCHEDULE_UNSUB] = async_track_time_interval(
        hass, _handle, timedelta(seconds=60)
    )


async def _async_verify_mode_state(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry,
    intended: list[dict[str, Any]],
) -> None:
    """Read back each intended device and alert on any that did not reach its target
    (catches stranded/offline gear). Read-only check plus notification; no control."""
    latest_config = _config_from_entry(entry)
    alerts = latest_config.get("alerts", {})
    if not isinstance(alerts, dict) or not alerts.get("modeStuckNotify", True):
        return
    mismatches: list[str] = []
    for item in intended:
        entity_id = item.get("entity_id")
        target = item.get("state")
        if not entity_id or target not in {"on", "off"}:
            continue
        name = item.get("label") or item.get("equipment_id") or entity_id
        sw_state = hass.states.get(entity_id)
        if sw_state is None or sw_state.state in UNAVAILABLE_STATES:
            mismatches.append(f"{name} (unavailable)")
        elif sw_state.state != target:
            mismatches.append(f"{name} (is {sw_state.state}, expected {target})")
    if not mismatches:
        return
    detail = "; ".join(mismatches)
    _append_activity(
        latest_config,
        f"Mode verification: {len(mismatches)} device(s) not in the expected state: {detail}",
        "warning",
    )
    await _async_send_mode_notification(
        hass,
        latest_config,
        "openreef_mode_verify",
        "Equipment did not switch as expected",
        detail,
    )
    await _async_save_config(hass, entry, latest_config)


async def _async_schedule_mode_verify(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry,
    config: dict[str, Any],
    intended: list[dict[str, Any]],
) -> None:
    """Schedule a one-shot read-back verification a few seconds after a mode apply."""
    _clear_mode_verify(hass)
    if not intended:
        return
    alerts = config.get("alerts", {})
    if not isinstance(alerts, dict) or not alerts.get("modeVerifyEnabled", True):
        return
    try:
        delay = int(alerts.get("modeVerifyDelaySeconds", MODE_VERIFY_DEFAULT_DELAY_SECONDS))
    except (TypeError, ValueError):
        delay = MODE_VERIFY_DEFAULT_DELAY_SECONDS
    delay = max(2, min(delay, 120))
    run_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
    snapshot = [dict(item) for item in intended]

    async def _handle(_now: datetime) -> None:
        hass.data.setdefault(DOMAIN, {}).pop(MODE_VERIFY_UNSUB, None)
        latest_entry = _first_entry(hass)
        if latest_entry is None or latest_entry.entry_id != entry.entry_id:
            return
        await _async_verify_mode_state(hass, latest_entry, snapshot)

    hass.data.setdefault(DOMAIN, {})[MODE_VERIFY_UNSUB] = async_track_point_in_time(
        hass, _handle, run_at
    )


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
    now = datetime.now(timezone.utc)

    # Per-equipment timers (Mode Actions V2). Only non-running modes carry them.
    equip_timer_cfg = config.get("modeEquipmentTimers", {})
    equip_timer_cfg = (
        equip_timer_cfg.get(mode_id, {}) if isinstance(equip_timer_cfg, dict) else {}
    )
    if not isinstance(equip_timer_cfg, dict):
        equip_timer_cfg = {}
    equipment_timer_state: dict[str, dict[str, Any]] = {}

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

        # Per-equipment timer (non-running modes only). With a start delay, defer the
        # whole action and seed phase "delay"; otherwise drive now and seed the
        # post-action phase (hold-then-revert or cycle).
        timer_cfg = None
        if should_capture_return_plan:
            raw_timer = equip_timer_cfg.get(equipment_key)
            if isinstance(raw_timer, dict) and raw_timer.get("enabled"):
                candidate = _normalise_equipment_timer(raw_timer)
                if _equipment_timer_active(candidate):
                    timer_cfg = candidate
        if timer_cfg is not None and timer_cfg["startDelaySeconds"] > 0:
            equipment_timer_state[equipment_key] = {
                "timerMode": timer_cfg["timerMode"],
                "phase": "delay",
                "action": desired_state,
                "nextFireAt": (
                    now + timedelta(seconds=timer_cfg["startDelaySeconds"])
                ).isoformat(),
                "onSeconds": timer_cfg["onSeconds"],
                "offSeconds": timer_cfg["offSeconds"],
                "holdSeconds": timer_cfg["holdSeconds"],
            }
            applied.append(
                {
                    "equipment_id": equipment_key,
                    "entity_id": switch_entity,
                    "label": str(mapped.get("label") or equipment_key),
                    "state": "timer_scheduled",
                    "delay_seconds": str(timer_cfg["startDelaySeconds"]),
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

        # Start-delay 0: device is already in its action state — seed the follow-up phase.
        if timer_cfg is not None:
            if timer_cfg["timerMode"] == "cycle":
                equipment_timer_state[equipment_key] = {
                    "timerMode": "cycle",
                    "phase": desired_state,
                    "action": desired_state,
                    "nextFireAt": (
                        now
                        + timedelta(
                            seconds=timer_cfg["onSeconds"]
                            or MODE_EQUIPMENT_CYCLE_MIN_SECONDS
                        )
                    ).isoformat(),
                    "onSeconds": timer_cfg["onSeconds"],
                    "offSeconds": timer_cfg["offSeconds"],
                    "holdSeconds": timer_cfg["holdSeconds"],
                }
            else:
                equipment_timer_state[equipment_key] = {
                    "timerMode": "once",
                    "phase": "hold",
                    "action": desired_state,
                    "nextFireAt": (
                        now + timedelta(seconds=timer_cfg["holdSeconds"] or 1)
                    ).isoformat(),
                    "onSeconds": 0,
                    "offSeconds": 0,
                    "holdSeconds": timer_cfg["holdSeconds"],
                }

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

    # Max-off safety caps: arm for any device this apply drove OFF (return-to-running
    # clears all caps — the "holding" is over). Cancel happens implicitly: devices
    # driven on/restored simply aren't re-added here.
    max_off_state: dict[str, dict[str, str]] = {}
    if should_capture_return_plan:
        for item in applied:
            if item.get("state") != "off":
                continue
            mapped_item = equipment.get(item.get("equipment_id"))
            if not isinstance(mapped_item, dict):
                continue
            cap_seconds = _equipment_max_off_seconds(mapped_item)
            entity_item = _normalise_entity_id(mapped_item.get("switch_entity_id"))
            if cap_seconds > 0 and entity_item:
                max_off_state[item["equipment_id"]] = {
                    "fireAt": (now + timedelta(seconds=cap_seconds)).isoformat(),
                    "switch_entity_id": entity_item,
                }

    config["mode"] = {
        "active": mode_id,
        "startedAt": now.isoformat(),
        "expiresAt": expires_at,
        "autoReturn": auto_return,
        "returnPlan": return_plan if should_capture_return_plan else {},
        "equipmentTimers": equipment_timer_state if should_capture_return_plan else {},
        "maxOffTimers": max_off_state if should_capture_return_plan else {},
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

    # Exit verification: read back the devices we drove to a definite state and alert if
    # any didn't get there (stranded/offline gear). One-shot, a few seconds out.
    intended_verify = [
        {
            "equipment_id": item["equipment_id"],
            "entity_id": item.get("entity_id"),
            "state": item["state"],
            "label": item.get("label"),
        }
        for item in applied
        if item.get("state") in {"on", "off"}
    ]
    await _async_schedule_mode_verify(hass, entry, config, intended_verify)

    # Feed-watch (Phase D) supersedes the single Phase A feed clip: start a snapshot burst
    # when entering feed (if enabled), and finalize any active session when leaving feed.
    feedwatch_cfg = config.get("feedWatch", {})
    feedwatch_on = isinstance(feedwatch_cfg, dict) and feedwatch_cfg.get("enabled", False)
    if mode_id != "feed" and hass.data.setdefault(DOMAIN, {}).setdefault(
        FEEDWATCH_SESSION, {}
    ).get(entry.entry_id):
        await _async_stop_feed_watch(hass, entry)
    elif mode_id == "feed" and feedwatch_on:
        await _async_start_feed_watch(hass, entry)

    # Vision feeding report card: open a response-latency window on entering feed
    # mode, close it on leaving. Deliberately independent of feedWatch — either
    # can be enabled without the other.
    vision_cfg = config.get("vision", {})
    vision_runtime = hass.data.setdefault(DOMAIN, {}).get(VISION_RUNTIME)
    if vision_runtime is not None and isinstance(vision_cfg, dict) and vision_cfg.get("enabled"):
        vision_now = dt_util.utcnow().timestamp()
        feed_report_cfg = (
            vision_cfg.get("feedReport")
            if isinstance(vision_cfg.get("feedReport"), dict)
            else {}
        )
        if mode_id == "feed":
            if feed_report_cfg.get("enabled"):
                vision.start_feed_session(vision_runtime, vision_now)
        elif vision_runtime.get("feedSession") is not None:
            # Close unconditionally when a session is open (even if feedReport
            # was disabled mid-feed — a stranded session would report
            # feeding:true forever); persist only while the feature is on.
            vision_report = vision.close_feed_session(
                vision_runtime,
                list(vision_cfg.get("species") or []),
                int(feed_report_cfg.get("windowSeconds") or VISION_DEFAULT_FEED_WINDOW),
                vision_now,
            )
            if vision_report is not None and feed_report_cfg.get("enabled"):
                # Fresh read + lightweight persist: re-saving this function's
                # stale `config` snapshot would revert the feedwatch session
                # finalization saved above and re-fire alert transitions
                # (duplicate history/notifications/captures).
                fresh_config = _config_from_entry(entry)
                fresh_reports = fresh_config.get("visionReports")
                if not isinstance(fresh_reports, list):
                    fresh_reports = []
                fresh_config["visionReports"] = ([vision_report] + fresh_reports)[
                    :VISION_MAX_REPORTS
                ]
                _persist_entry_config(hass, entry, fresh_config)

    # One capture per mode action, most-specific enabled trigger wins (feed > safety > mode).
    capture_triggers = config.get("capture", {}).get("triggers", {})
    if not isinstance(capture_triggers, dict):
        capture_triggers = {}
    capture_candidates: list[tuple[str, str, str]] = []
    if mode_id == "feed" and not feedwatch_on:
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


async def _async_acknowledge_alert(
    hass: HomeAssistant, entry: OpenReefConfigEntry, sensor_id: str
) -> dict[str, Any]:
    config = _config_from_entry(entry)
    sensors = config.get("sensors", {})
    if not isinstance(sensors, dict) or sensor_id not in sensors:
        raise ServiceValidationError("Unknown OpenReef sensor")
    escalation = config.setdefault("alertEscalation", {})
    acknowledged = escalation.setdefault("acknowledged", {})
    if not isinstance(acknowledged, dict):
        acknowledged = {}
        escalation["acknowledged"] = acknowledged
    acknowledged[sensor_id] = datetime.now(timezone.utc).isoformat()
    last_escalated = escalation.setdefault("lastEscalated", {})
    if isinstance(last_escalated, dict):
        last_escalated.pop(sensor_id, None)
    await hass.services.async_call(
        "persistent_notification",
        "dismiss",
        {"notification_id": f"openreef_alert_{sensor_id}"},
        blocking=False,
    )
    await hass.services.async_call(
        "persistent_notification",
        "dismiss",
        {"notification_id": f"openreef_escalation_{sensor_id}"},
        blocking=False,
    )
    _append_activity(config, f"Alert acknowledged: {sensor_id}", "info")
    return await _async_save_config(hass, entry, config)


async def _handle_acknowledge_alert(hass: HomeAssistant, call: ServiceCall) -> None:
    entry = _first_entry(hass)
    if entry is None:
        raise HomeAssistantError("OpenReef is not configured")
    await _async_acknowledge_alert(hass, entry, str(call.data["sensor_id"]))


async def _async_test_notification(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry,
    message: str = "",
) -> dict[str, Any]:
    config = _config_from_entry(entry)
    text = (
        message.strip()
        if isinstance(message, str) and message.strip()
        else "OpenReef notification test delivered."
    )
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "notification_id": "openreef_notification_test",
            "title": "OpenReef notification test",
            "message": text,
        },
        blocking=False,
    )
    watchdog = config.setdefault("watchdog", {})
    escalation = config.get("alertEscalation", {})
    target = str(escalation.get("notifyTarget", "")).strip() if isinstance(escalation, dict) else ""
    if not target and isinstance(watchdog, dict):
        target = str(watchdog.get("notifyTarget", "")).strip()
    if target:
        await hass.services.async_call(
            "notify",
            target,
            {"title": "OpenReef notification test", "message": text},
            blocking=False,
        )
    if isinstance(watchdog, dict):
        watchdog["lastNotificationTest"] = datetime.now(timezone.utc).isoformat()
    _append_activity(config, "Notification test sent", "info")
    return await _async_save_config(hass, entry, config)


async def _handle_test_notification(hass: HomeAssistant, call: ServiceCall) -> None:
    entry = _first_entry(hass)
    if entry is None:
        raise HomeAssistantError("OpenReef is not configured")
    await _async_test_notification(hass, entry, str(call.data.get("message") or ""))


async def _handle_refresh_trust_check(hass: HomeAssistant, call: ServiceCall) -> None:
    entry = _first_entry(hass)
    if entry is None:
        raise HomeAssistantError("OpenReef is not configured")
    config = _config_from_entry(entry)
    _trust_check_summary(hass, config, update=True)
    _append_activity(config, "Trust Check refreshed", "info")
    await _async_save_config(hass, entry, config)


async def _handle_heartbeat(hass: HomeAssistant, call: ServiceCall) -> None:
    entry = _first_entry(hass)
    if entry is None:
        raise HomeAssistantError("OpenReef is not configured")
    await _async_run_watchdog(hass, entry, force=True)


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


async def _handle_record_task_completion(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    entry = _first_entry(hass)
    if entry is None:
        raise HomeAssistantError("OpenReef is not configured")

    config = _config_from_entry(entry)
    maintenance = config.setdefault("maintenance", {})
    if not isinstance(maintenance, dict):
        maintenance = {}
        config["maintenance"] = maintenance
    tasks = maintenance.get("tasks", {})
    task_id = call.data["task_id"]
    if not isinstance(tasks, dict) or task_id not in tasks:
        raise ServiceValidationError(f"Unknown OpenReef maintenance task: {task_id}")

    timestamp = (
        call.data.get("timestamp")
        or call.data.get("date")
        or datetime.now(timezone.utc).isoformat()
    )
    completions = maintenance.setdefault("completions", {})
    if not isinstance(completions, dict):
        completions = {}
        maintenance["completions"] = completions
    entries = completions.setdefault(task_id, [])
    if not isinstance(entries, list):
        entries = []
        completions[task_id] = entries
    completion = {
        "id": f"{task_id}:{timestamp}:{len(entries)}",
        "timestamp": timestamp,
        "notes": str(call.data.get("notes") or ""),
    }
    volume = call.data.get("volume")
    if isinstance(volume, (int, float)) and not isinstance(volume, bool):
        completion["volume"] = round(float(volume), 2)
        completion["volumeUnit"] = "L" if call.data.get("volume_unit") == "L" else "pct"
    entries.insert(0, completion)
    _append_activity(
        config, f"Maintenance done: {tasks[task_id].get('label', task_id)}", "control"
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
    trust_check = _trust_check_summary(hass, config, update=True)
    if entry is not None:
        _sync_alert_state(hass, config)
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_SETTINGS: config}
        )
        if await _async_sync_alert_notifications(hass, config):
            hass.config_entries.async_update_entry(
                entry, options={**entry.options, CONF_SETTINGS: config}
            )
    connection.send_result(
        msg["id"],
        {
            "configured": entry is not None,
            "version": INTEGRATION_VERSION,
            "entry_id": entry.entry_id if entry is not None else "",
            "config": config,
            "settings": config,
            "sensor_meta": MVP_SENSORS,
            "validation": _validate_config(hass, config),
            "trust_check": trust_check,
            "heartbeat": _watchdog_status(config),
            "reef_replay": _reef_replay_incidents(config),
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

    # A panel posts the whole config, so anything logged since it last refreshed —
    # an automatic water change, a completion from an automation — would be dropped.
    _merge_recent_completions(entry.options.get(CONF_SETTINGS), msg["config"])
    _preserve_runtime_mode(entry.options.get(CONF_SETTINGS), msg["config"])
    # A hatch-clock change here has to reach the batch already incubating and
    # the reminders hanging off it, or the page contradicts itself (0.7.80).
    _nps_hatch_clock_follow(entry.options.get(CONF_SETTINGS), msg["config"])
    config = await _async_save_config(hass, entry, msg["config"])
    connection.send_result(
        msg["id"],
        {
            "success": True,
            "version": INTEGRATION_VERSION,
            "entry_id": entry.entry_id,
            "config": config,
            "validation": _validate_config(hass, config),
            "trust_check": _trust_check_summary(hass, config),
            "heartbeat": _watchdog_status(config),
            "reef_replay": _reef_replay_incidents(config),
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

    _preserve_runtime_mode(entry.options.get(CONF_SETTINGS), msg["settings"])
    config = await _async_save_config(hass, entry, msg["settings"])
    connection.send_result(
        msg["id"],
        {
            "success": True,
            "version": INTEGRATION_VERSION,
            "entry_id": entry.entry_id,
            "config": config,
            "trust_check": _trust_check_summary(hass, config),
            "heartbeat": _watchdog_status(config),
            "reef_replay": _reef_replay_incidents(config),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/coral_photo_upload",
        vol.Required("coralId"): str,
        vol.Required("image"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_coral_photo_upload(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Save a coral photo into the captures store and pin it to the coral.

    The panel downscales client-side (canvas, ≤1280px JPEG) before sending a
    data-URL, so the payload stays well under websocket limits. The coral id is
    trusted only after it round-trips the normalised registry — which enforces
    the [A-Za-z0-9_-] slug shape, making it path-safe by construction.
    """
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    coral_id = msg["coralId"]
    corals = (config.get("livestock") or {}).get("corals") or {}
    if coral_id not in corals:
        connection.send_error(msg["id"], "unknown_coral", "No such coral in the registry")
        return
    raw = msg["image"]
    if raw.startswith("data:"):
        _, _, raw = raw.partition(",")
    try:
        blob = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error):
        connection.send_error(msg["id"], "bad_image", "Image is not valid base64")
        return
    if len(blob) > 3_000_000:
        connection.send_error(msg["id"], "too_large", "Photo is over 3 MB even after resizing")
        return
    if blob.startswith(b"\xff\xd8\xff"):
        ext = "jpg"
    elif blob.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = "png"
    else:
        connection.send_error(msg["id"], "bad_image", "Only JPEG or PNG photos are supported")
        return
    await _async_register_captures_path(hass)
    corals_dir = _captures_dir(hass) / "corals"
    filename = f"{coral_id}.{ext}"

    def _write() -> None:
        corals_dir.mkdir(parents=True, exist_ok=True)
        (corals_dir / filename).write_bytes(blob)

    await hass.async_add_executor_job(_write)
    # Stable filename per coral; the ?v= stamp busts the browser cache on replace.
    url = f"{CAPTURES_STATIC_URL}/corals/{filename}?v={int(datetime.now(timezone.utc).timestamp())}"
    corals[coral_id]["photoUrl"] = url
    saved = await _async_save_config(hass, entry, config)
    connection.send_result(msg["id"], {"success": True, "url": url, "config": saved})


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
    if await _async_sync_alert_notifications(hass, config) and entry is not None:
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_SETTINGS: config}
        )
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
    if await _async_sync_alert_notifications(hass, config) and entry is not None:
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_SETTINGS: config}
        )
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
            "trust_check": _trust_check_summary(hass, config),
            "heartbeat": _watchdog_status(config),
            "reef_replay": _reef_replay_incidents(config),
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
            "trust_check": _trust_check_summary(hass, config),
            "heartbeat": _watchdog_status(config),
            "reef_replay": _reef_replay_incidents(config),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/acknowledge_alert",
        vol.Required("sensor_id"): cv.string,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_acknowledge_alert(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Acknowledge one active OpenReef alert and stop escalation repeats."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    try:
        config = await _async_acknowledge_alert(hass, entry, msg["sensor_id"])
    except ServiceValidationError as exc:
        connection.send_error(msg["id"], "invalid_sensor", str(exc))
        return
    connection.send_result(
        msg["id"],
        {
            "success": True,
            "version": INTEGRATION_VERSION,
            "config": config,
            "validation": _validate_config(hass, config),
            "trust_check": _trust_check_summary(hass, config),
            "heartbeat": _watchdog_status(config),
            "reef_replay": _reef_replay_incidents(config),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/test_notification",
        vol.Optional("message", default=""): cv.string,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_test_notification(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Send a Home Assistant persistent notification and optional notify target push."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = await _async_test_notification(hass, entry, msg.get("message", ""))
    connection.send_result(
        msg["id"],
        {
            "success": True,
            "version": INTEGRATION_VERSION,
            "config": config,
            "validation": _validate_config(hass, config),
            "trust_check": _trust_check_summary(hass, config),
            "heartbeat": _watchdog_status(config),
            "reef_replay": _reef_replay_incidents(config),
        },
    )


@websocket_api.websocket_command({vol.Required("type"): "openreef/refresh_trust_check"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_refresh_trust_check(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Refresh and persist the OpenReef Trust Check summary."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    trust_check = _trust_check_summary(hass, config, update=True)
    _append_activity(config, "Trust Check refreshed", "info")
    config = await _async_save_config(hass, entry, config)
    connection.send_result(
        msg["id"],
        {
            "success": True,
            "version": INTEGRATION_VERSION,
            "config": config,
            "validation": _validate_config(hass, config),
            "trust_check": trust_check,
            "heartbeat": _watchdog_status(config),
            "reef_replay": _reef_replay_incidents(config),
        },
    )


@websocket_api.websocket_command({vol.Required("type"): "openreef/get_heartbeat"})
@websocket_api.async_response
async def websocket_get_heartbeat(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return watchdog heartbeat status."""
    entry = _first_entry(hass)
    config = _config_from_entry(entry)
    connection.send_result(msg["id"], _watchdog_status(config))


@websocket_api.websocket_command({vol.Required("type"): "openreef/list_reef_replay"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_list_reef_replay(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the Tank Black Box / Reef Replay incident timeline."""
    entry = _first_entry(hass)
    config = _config_from_entry(entry)
    connection.send_result(msg["id"], {"incidents": _reef_replay_incidents(config)})


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


# --- Automatic Water Change: websocket actions --------------------------------------------

def _awc_send(connection: websocket_api.ActiveConnection, msg: dict[str, Any],
              hass: HomeAssistant, config: dict[str, Any], **extra: Any) -> None:
    connection.send_result(
        msg["id"], {"success": True, "config": config,
                    "validation": _validate_config(hass, config), **extra},
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/awc_run_now",
        vol.Optional("litres"): vol.Coerce(float),
        vol.Optional("percent"): vol.Coerce(float),
        vol.Optional("method"): cv.string,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_awc_run_now(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Manual 'change N litres now' — full interlocks apply, quiet-hours bypassed."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    # Pre-lock read is only used to resolve percent -> litres (benign); the start
    # itself re-fetches and re-validates under the lock (R1).
    litres = msg.get("litres")
    if litres is None and msg.get("percent") is not None:
        litres = _awc_effective_tank_l(_config_from_entry(entry)) * float(msg["percent"]) / 100.0
    started, reasons = await _async_awc_start(
        hass, entry, litres or 0, msg.get("method"), True, connection.context(msg)
    )
    _awc_send(connection, msg, hass, _config_from_entry(entry), started=started, reasons=reasons)


@websocket_api.websocket_command({vol.Required("type"): "openreef/awc_abort"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_awc_abort(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """User-initiated stop of an in-flight or paused change (no latch, ATO restored)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    # Locked with the fetch + re-check INSIDE (R1): the old pre-lock snapshot made
    # the re-check verify nothing — an abort queued behind a leg timer acted on
    # a minute-old status (inner _async_awc_abort stays unlocked by design).
    async with _awc_lock(hass):
        config = _config_from_entry(entry)
        status = _awc_cfg(config).get("state", {}).get("status")
        if status not in (*_AWC_RUNNING_STATES, "paused"):
            connection.send_error(msg["id"], "not_running", "No water change is in progress")
            return
        await _async_awc_abort(hass, entry, config, "Stopped by user", False, False, connection.context(msg))
    _awc_send(connection, msg, hass, _config_from_entry(entry))


@websocket_api.websocket_command({vol.Required("type"): "openreef/awc_resume"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_awc_resume(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Re-attempt a paused change now (e.g. after refilling the reservoir)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    if _awc_cfg(_config_from_entry(entry)).get("state", {}).get("status") != "paused":
        connection.send_error(msg["id"], "not_paused", "No paused water change to resume")
        return
    resumed = await _async_awc_try_resume(hass, entry, connection.context(msg))
    _awc_send(connection, msg, hass, _config_from_entry(entry), resumed=resumed)


@websocket_api.websocket_command({vol.Required("type"): "openreef/awc_acknowledge_flood"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_awc_acknowledge_flood(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Acknowledge running the AWC with no leak sensor bound (the kalk no-pH pattern:
    informed consent recorded once, then the flood_unacknowledged start guard clears).
    Pumps-only nodes ship without flood hardware by design — see MULTINODE_PIVOT_BRIEF."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    async with _awc_lock(hass):
        config = _config_from_entry(entry)  # fetched INSIDE the lock (R1)
        awc = _awc_cfg(config)
        safety = awc.setdefault("safety", {})
        if safety.get("leakEntity"):
            connection.send_error(
                msg["id"], "not_applicable",
                "A leak sensor is bound — there is nothing to acknowledge")
            return
        safety["floodMissingAcknowledged"] = True
        _append_activity(
            config,
            "Acknowledged: AWC runs with no leak sensor bound — reservoir sizing and "
            "lines-in-air are the flood protection",
            "warning",
        )
        config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({vol.Required("type"): "openreef/awc_acknowledge"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_awc_acknowledge(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Clear a latched fault and re-arm the feature (manual re-arm, two-tier policy)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    async with _awc_lock(hass):
        config = _config_from_entry(entry)  # fetched INSIDE the lock (R1)
        state = _awc_cfg(config).get("state", {})
        if state.get("status") != "fault":
            connection.send_error(msg["id"], "no_fault", "There is no latched fault to clear")
            return
        live = _awc_live_state(hass, config)
        active_hazards = []
        if live.get("leak"):
            active_hazards.append("leak sensor")
        if live.get("highLevel"):
            active_hazards.append("display high-level cutoff")
        if active_hazards:
            connection.send_error(
                msg["id"], "hazard_active",
                "Clear the active AWC hazard before acknowledging: " + ", ".join(active_hazards),
            )
            return
        # Record any partial progress the faulted change made before zeroing it.
        # Abort-latched faults already recorded (and zeroed) at abort time, so this
        # only fires for begin-failure faults, whose credited volume otherwise
        # vanished from history/ledger while the reservoir models kept the debit.
        ack_fill_role = _awc_fill_role(state)
        drained_l = _awc_moved(state, "drain") / 1000.0
        filled_l = _awc_moved(state, ack_fill_role) / 1000.0
        if drained_l > 0 or filled_l > 0:
            ack_awc = _awc_cfg(config)
            _awc_record_history(
                ack_awc, datetime.now(timezone.utc), drained_l, filled_l,
                state.get("method", ""), True,
                f"Fault acknowledged: {state.get('fault', '')}",
                config=config,
            )
            ack_awc["history"][0]["source"] = ack_fill_role
            ack_per = ack_awc["ledger"].setdefault("perSource", {})
            ack_per[ack_fill_role] = round(
                _awc_num(ack_per.get(ack_fill_role), 0, 0, 1e9) + filled_l, 3)
        state.update({
            "status": "idle", "fault": "", "faultSince": "", "atoSuspendedUntil": "",
            "movedMl": {}, "activeSourceRole": "", "targetLitres": 0,
            "legStartedAt": "", "legEndsAt": "", "endsAt": {},
            "exchangeBaselineNetMl": 0, "method": "", "pausedReason": "",
            "microChange": False,
        })
        _append_activity(config, "Water change fault acknowledged and cleared", "control")
        await _async_dosing_awc_suspend(hass, config, False, None)
        config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/awc_calibrate",
        vol.Required("role"): cv.string,
        vol.Optional("volume_ml"): vol.Coerce(float),
        vol.Optional("seconds"): vol.Coerce(float),
        vol.Optional("points"): [vol.All([vol.Coerce(float)], vol.Length(min=2, max=2))],
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_awc_calibrate(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Store a pump's ml/s (single-point) or slope+intercept (multi-point) calibration."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    role = msg["role"]
    if role not in AWC_PUMP_ROLES:
        connection.send_error(msg["id"], "invalid_role",
                              "Pump role must be 'drain', 'fill' or 'fill2'")
        return
    if not _awc_role_configured(entry, role):
        connection.send_error(msg["id"], "no_second_source",
                              "Add the second source in Water Change settings first")
        return
    points = [(p[0], p[1]) for p in msg.get("points") or []]
    if points:
        fit = awc_engine.calibrate_linear(points)
        ml_per_s, intercept = fit["mlPerS"], fit["interceptMl"]
    else:
        if msg.get("seconds") is None or msg.get("volume_ml") is None:
            connection.send_error(msg["id"], "missing_data", "Provide volume_ml + seconds, or points")
            return
        ml_per_s = awc_engine.ml_per_s_from_run(msg["volume_ml"], msg["seconds"])
        intercept = 0.0
    if ml_per_s <= 0:
        connection.send_error(msg["id"], "invalid_calibration", "Calibration produced a non-positive flow rate")
        return
    # Physical plausibility (R14, WS half): a fit whose line predicts NEGATIVE
    # volume for the shortest run provided is measurement noise, not a pump —
    # reject it loudly rather than persisting a silently-clamped fantasy.
    positive_runs = [s for s, _ in points if s > 0]
    if positive_runs and intercept < 0:
        if ml_per_s * min(positive_runs) + intercept < 0:
            connection.send_error(
                msg["id"], "implausible_calibration",
                "That fit predicts negative volume for your shortest run — redo the "
                "calibration with more varied run durations (e.g. 30 s and 90 s).",
            )
            return
    # Locked + busy-rejected while RUNNING (R28): recalibrating mid-run re-scales the
    # live dead-reckoning (spurious imbalance aborts) and raced the run's own saves.
    # PAUSED is deliberately allowed: pumps are off, the leg stamps are cleared (no
    # live dead-reckoning), and the calibration-loss pause paths instruct exactly
    # "recalibrate, then resume".
    async with _awc_lock(hass):
        config = _config_from_entry(entry)
        if _awc_cfg(config).get("state", {}).get("status") in _AWC_RUNNING_STATES:
            connection.send_error(msg["id"], "busy", "Finish or stop the running water change before recalibrating")
            return
        pump = _awc_cfg(config).setdefault("pumps", {}).setdefault(role, {})
        # Split the fitted intercept into a per-dose spin-up (bounded to a few seconds of
        # flow — the only part that belongs in the run maths) and a one-time prime residual
        # (a dry-tube point that smuggled the tube-fill volume into the intercept lands
        # here, not per-dose, so it can't over-correct every primed run). Single-point
        # calibrations have intercept 0 ⇒ both stay 0.
        spin_cap = max(AWC_SPINUP_MIN_CAP_ML, AWC_SPINUP_MAX_SECONDS * ml_per_s)
        spin_up = max(-spin_cap, min(spin_cap, intercept))
        pump["mlPerS"] = round(ml_per_s, 3)
        pump["interceptMl"] = round(intercept, 3)
        pump["spinUpMl"] = round(spin_up, 3)
        pump["primeMl"] = round(intercept - spin_up, 3)
        pump["calibratedAt"] = datetime.now(timezone.utc).isoformat()
        _append_activity(config, f"AWC {role} pump calibrated: {pump['mlPerS']} ml/s", "control")
        config = await _async_save_config(hass, entry, config)
        # Echo the post-normalisation value: the raw fit may have been clamped.
        saved = _awc_cfg(config).get("pumps", {}).get(role, {}).get("mlPerS", pump["mlPerS"])
    _awc_send(connection, msg, hass, config, role=role, mlPerS=saved)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/awc_reset_reservoir",
        vol.Required("reservoir"): cv.string,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_awc_reset_reservoir(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Reset a reservoir's dead-reckoned level: fresh→full, waste→empty (after a refill)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    kind = msg["reservoir"]
    if kind not in AWC_RESERVOIR_KINDS:
        connection.send_error(msg["id"], "invalid_reservoir",
                              "Reservoir must be 'fresh', 'fresh2' or 'waste'")
        return
    async with _awc_lock(hass):
        config = _config_from_entry(entry)  # fetched INSIDE the lock (R1)
        reservoirs = _awc_cfg(config).get("reservoirs", {})
        if kind in ("fresh", "fresh2"):
            fresh = reservoirs.get(kind)
            if not isinstance(fresh, dict):
                connection.send_error(msg["id"], "invalid_reservoir",
                                      f"Reservoir '{kind}' is not configured")
                return
            # Bookend drift check: refilling FROM EMPTY (float tripped) is the other
            # moment reality checks in — grade the finished fill cycle before zeroing.
            if _awc_binary_on(hass, fresh.get("emptyEntity")):
                verdict = _awc_grade_fresh_drift(config, kind)
                if verdict is not None:
                    await _async_awc_notify_drift(hass, config, verdict, kind)
            fresh["remainingMl"] = fresh.get("capacityLitres", 0) * 1000.0
            fresh["dispensedSinceFullMl"] = 0
            fresh["driftCheckedAt"] = ""  # new fill cycle — re-arm the check
            # The confirmed-full anchor the drift grade requires: from here the
            # odometer genuinely counts from a full reservoir.
            fresh["fullConfirmedAt"] = datetime.now(timezone.utc).isoformat()
            name = "Fresh saltwater" if kind == "fresh" else f"Source '{kind}'"
            _append_activity(config, f"{name} reservoir marked full", "control")
        else:
            reservoirs.get("waste", {})["filledMl"] = 0
            _append_activity(config, "Waste reservoir marked empty", "control")
        config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


def _sanitize_imported_config(incoming: dict[str, Any], current: dict[str, Any]) -> None:
    """Imported blobs describe SETTINGS, not live state: rebuild the AWC run state
    from scratch (idle; ledgers/history are data and ride along), force demo mode
    off, mark every dosing channel unsynced with no pending writes (write-then-
    verify re-syncs against the real firmware), and carry the CURRENT runtime
    record lists the export stripped so a restore doesn't wipe them."""
    awc = incoming.get("automaticWaterChange")
    if isinstance(awc, dict):
        awc["state"] = {}  # the normaliser rebuilds a clean idle state
        sim = awc.get("simulation")
        if isinstance(sim, dict):
            sim["enabled"] = False
            sim["snapshot"] = None  # a foreign snapshot must never restore here
    dosing = incoming.get("dosing")
    if isinstance(dosing, dict) and isinstance(dosing.get("spacing"), dict):
        # A queued spacing-deferred dose is live state, not a setting — restoring
        # one from a days-old backup must never fire it into today's tank.
        dosing["spacing"]["queued"] = None
    if isinstance(dosing, dict) and isinstance(dosing.get("channels"), dict):
        for channel in dosing["channels"].values():
            if not isinstance(channel, dict):
                continue
            channel["sync"] = {}  # normaliser default = unsynced, no pending writes
            ch_state = channel.get("state")
            if isinstance(ch_state, dict):
                ch_state["suspendedUntil"] = ""
    for key in _EXPORT_STRIP_KEYS:
        if key in current:
            incoming[key] = deepcopy(current[key])


@websocket_api.websocket_command({vol.Required("type"): "openreef/config_export"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_config_export(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Portable settings backup: the normalised config minus bulky runtime record
    lists (captures / feed sessions / vision reports / activity). No secrets live
    in the blob — bindings are entity ids, never credentials."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    for key in _EXPORT_STRIP_KEYS:
        config.pop(key, None)
    connection.send_result(msg["id"], {
        "kind": "openreef-config",
        "version": INTEGRATION_VERSION,
        "schema": CORE_SCHEMA_VERSION,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "config": config,
    })


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/config_import",
    vol.Required("payload"): dict,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_config_import(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Restore a config_export payload. Older schemas are fine — the ordinary
    normalise/save path IS the migration layer; newer ones are refused (fields
    from the future can't be guessed at). Refused while a change runs."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    payload = msg["payload"]
    if payload.get("kind") != "openreef-config" or not isinstance(payload.get("config"), dict):
        connection.send_error(msg["id"], "invalid_payload",
                              "That file is not an OpenReef settings backup")
        return
    schema = payload.get("schema")
    if isinstance(schema, (int, float)) and schema > CORE_SCHEMA_VERSION:
        connection.send_error(
            msg["id"], "newer_schema",
            f"This backup is from a newer OpenReef ({payload.get('version', 'unknown')}) "
            "— update the integration first, then import")
        return
    if hass.data.get(DOMAIN, {}).get(AWC_CALRUN_UNSUB) is not None:
        # The run's stop timer resolves the pump entity from the LIVE config — an
        # import could swap it mid-run and strand the physical pump on.
        connection.send_error(msg["id"], "busy",
                              "Wait for the calibration run to finish before importing")
        return
    async with _awc_lock(hass):
        config = _config_from_entry(entry)
        if _awc_cfg(config).get("state", {}).get("status") in (*_AWC_RUNNING_STATES, "paused"):
            connection.send_error(msg["id"], "busy",
                                  "Stop the running water change before importing settings")
            return
        incoming = deepcopy(payload["config"])
        _sanitize_imported_config(incoming, config)
        _append_activity(
            incoming,
            f"Settings imported from backup (v{payload.get('version', '?')})", "control")
        saved = await _async_save_config(hass, entry, incoming)
    connection.send_result(msg["id"], {
        "success": True, "config": saved, "validation": _validate_config(hass, saved)})



def _awc_role_configured(entry: OpenReefConfigEntry, role: str) -> bool:
    """fill2 is opt-in: WS actions naming it are refused until the second source is
    actually configured — the setdefault-based handlers would otherwise materialise
    a half-configured fill2/fresh2 pair on a legacy 2-pump setup."""
    if role != "fill2":
        return True
    return "fill2" in _awc_cfg(_config_from_entry(entry)).get("pumps", {})


async def _async_awc_recover_orphaned_calrun(
    hass: HomeAssistant, entry: OpenReefConfigEntry
) -> None:
    """A timed calibration run's stop timer is in-memory only: if HA restarted while
    one was in flight, the pump is still physically running with nothing armed to
    stop it. The persisted calRunRole stamp is the trace — stop it and clear."""
    if not _awc_cfg(_config_from_entry(entry)).get("state", {}).get("calRunRole"):
        return
    async with _awc_lock(hass):
        config = _config_from_entry(entry)
        state = _awc_cfg(config).get("state", {})
        role = state.get("calRunRole")
        if not role:
            return
        await _async_awc_stop_pumps(hass, config, (role,), None)
        state["calRunRole"] = ""
        state["calRunEndsAt"] = ""
        _append_activity(
            config, f"Calibration run interrupted by a restart — {role} pump stopped",
            "warning")
        await _async_save_config(hass, entry, config)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/awc_calibration_run",
    vol.Required("role"): cv.string,
    vol.Required("seconds"): vol.All(vol.Coerce(float), vol.Range(min=1, max=120)),
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_awc_calibration_run(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Timed calibration run: energise ONE pump for exactly N seconds (into a
    measuring vessel), then stop it — the actuated half of the multi-point
    calibration ceremony. Idle only; flood hazards must be clear; the scheduler is
    blocked from starting a change while a run is in flight."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    role = msg["role"]
    if role not in AWC_PUMP_ROLES:
        connection.send_error(msg["id"], "invalid_role",
                              "Pump role must be 'drain', 'fill' or 'fill2'")
        return
    if not _awc_role_configured(entry, role):
        connection.send_error(msg["id"], "no_second_source",
                              "Add the second source in Water Change settings first")
        return
    seconds = float(msg["seconds"])
    async with _awc_lock(hass):
        config = _config_from_entry(entry)
        if _awc_cfg(config).get("state", {}).get("status") != "idle":
            connection.send_error(msg["id"], "busy",
                                  "Calibration runs need the water change idle")
            return
        live = _awc_live_state(hass, config)
        if live.get("leak") or live.get("highLevel"):
            connection.send_error(msg["id"], "hazard_active",
                                  "Clear the leak / high-level hazard before running a pump")
            return
        store = hass.data.setdefault(DOMAIN, {})
        if store.get(AWC_CALRUN_UNSUB) is not None:
            connection.send_error(msg["id"], "busy", "A calibration run is already in progress")
            return
        pump = _awc_cfg(config).get("pumps", {}).get(role, {})
        if not _awc_sim_enabled(config) and not (isinstance(pump, dict) and pump.get("switchEntity")):
            connection.send_error(msg["id"], "no_pump_entity", f"No {role} pump entity configured")
            return
        try:
            await _async_awc_set_pump(hass, config, role, True, connection.context(msg))
        except Exception as exc:  # noqa: BLE001 - surface the failure, nothing started
            connection.send_error(msg["id"], "pump_start_failed",
                                  f"Could not start the {role} pump: {exc}")
            return
        ends_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)

        async def _stop(_now: datetime) -> None:
            latest = _first_entry(hass)
            async with _awc_lock(hass):
                # Pop the start-guard INSIDE the lock: popping before acquiring it
                # opened a window where a starter parked on the lock (the minutely
                # tick with a due slot) could begin a change and then have this stop
                # turn its pump off underneath it.
                hass.data.setdefault(DOMAIN, {}).pop(AWC_CALRUN_UNSUB, None)
                if latest is None:
                    return
                cfg = _config_from_entry(latest)
                await _async_awc_stop_pumps(hass, cfg, (role,), None)
                _awc_bump_odometer(_awc_cfg(cfg), role, seconds=seconds)
                st = _awc_cfg(cfg).get("state", {})
                st["calRunRole"] = ""
                st["calRunEndsAt"] = ""
                _append_activity(cfg, f"Calibration run finished: {role} pump ran {seconds:.0f} s",
                                 "control")
                await _async_save_config(hass, latest, cfg)

        store[AWC_CALRUN_UNSUB] = async_track_point_in_time(hass, _stop, ends_at)
        # Persist the in-flight run: the stop timer is in-memory only, so this stamp
        # is the sole trace a restart has for stopping the orphaned pump.
        run_state = _awc_cfg(config).get("state", {})
        run_state["calRunRole"] = role
        run_state["calRunEndsAt"] = ends_at.isoformat()
        _append_activity(config, f"Calibration run started: {role} pump for {seconds:.0f} s",
                         "control")
        await _async_save_config(hass, entry, config)
    connection.send_result(msg["id"], {
        "success": True, "role": role, "seconds": seconds, "endsAt": ends_at.isoformat()})


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/awc_sim_set",
    vol.Optional("enabled"): bool,
    vol.Optional("hazard"): cv.string,
    vol.Optional("value"): bool,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_awc_sim_set(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Toggle AWC simulation mode / inject a virtual hazard — the demo vehicle."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    async with _awc_lock(hass):
        config = _config_from_entry(entry)
        acfg = _awc_cfg(config)
        sim = acfg.setdefault("simulation", {"enabled": False, "hazards": {}})
        state = acfg.get("state", {})
        if "enabled" in msg:
            want = bool(msg["enabled"])
            if want != bool(sim.get("enabled")) and hass.data.get(DOMAIN, {}).get(AWC_CALRUN_UNSUB) is not None:
                # A timed calibration run is tracked only by its stop timer while
                # status stays idle — flipping the sandbox under it would strand a
                # REAL pump on (enable) or virtualise a real stop (disable).
                connection.send_error(msg["id"], "busy",
                                      "Wait for the calibration run to finish first")
                return
            if want and not sim.get("enabled"):
                if state.get("status") in (*_AWC_RUNNING_STATES, "paused"):
                    connection.send_error(
                        msg["id"], "busy",
                        "Stop the running water change before entering simulation mode")
                    return
                # SANDBOX the accounting: demo runs drive the REAL state machine, so
                # snapshot everything they mutate — restored verbatim on exit.
                # Virtual litres must never survive into the real reservoir / drift /
                # ledger / history / wear models or the schedule state.
                sim["snapshot"] = deepcopy({
                    "reservoirs": acfg.get("reservoirs", {}),
                    "ledger": acfg.get("ledger", {}),
                    "history": acfg.get("history", []),
                    "todayLitres": acfg.get("todayLitres", 0),
                    "weekLitres": acfg.get("weekLitres", 0),
                    "monthLitres": acfg.get("monthLitres", 0),
                    "pumps": acfg.get("pumps", {}),
                    "sourcePolicy": acfg.get("sourcePolicy", {}),
                    "state": state,
                })
            if not want and sim.get("enabled") and state.get("status") in (*_AWC_RUNNING_STATES, "paused"):
                # Leaving the sandbox mid-run: clean up the virtual change first
                # (sim is still enabled here, so the stops stay virtual).
                await _async_awc_abort(hass, entry, config, "Simulation ended", False, False, None)
            if want != bool(sim.get("enabled")):
                _append_activity(
                    config, f"AWC simulation mode {'enabled' if want else 'disabled'}", "control")
            sim["enabled"] = want
            if not want:
                snap = sim.get("snapshot")
                if isinstance(snap, dict):
                    # A second source ADDED during the demo keeps its just-configured
                    # reservoir (the snapshot predates it); a pair REMOVED during the
                    # demo must not be resurrected by the old reservoirs dict.
                    fresh2_now = deepcopy(acfg.get("reservoirs", {}).get("fresh2"))
                    for key in ("reservoirs", "ledger", "history", "sourcePolicy",
                                "todayLitres", "weekLitres", "monthLitres", "state"):
                        if key in snap:
                            acfg[key] = deepcopy(snap[key])
                    restored_res = acfg.setdefault("reservoirs", {})
                    if "fill2" in acfg.get("pumps", {}):
                        if "fresh2" not in restored_res and isinstance(fresh2_now, dict):
                            restored_res["fresh2"] = fresh2_now
                    else:
                        restored_res.pop("fresh2", None)
                    # Pumps: restore accounting/calibration only — entity/settings
                    # edits made during the demo are real config and stay.
                    for role, snap_pump in (snap.get("pumps") or {}).items():
                        cur = acfg.get("pumps", {}).get(role)
                        if isinstance(cur, dict) and isinstance(snap_pump, dict):
                            for f in ("mlPerS", "interceptMl", "spinUpMl", "primeMl",
                                      "calibratedAt", "runSeconds", "startCount"):
                                if f in snap_pump:
                                    cur[f] = snap_pump[f]
                sim["snapshot"] = None
                sim["hazards"] = {k: False for k in _AWC_SIM_HAZARDS}
                hass.data.setdefault(DOMAIN, {}).setdefault(AWC_RUNTIME, {})["simPumps"] = {}
        hazard = msg.get("hazard")
        if hazard is not None:
            if hazard not in _AWC_SIM_HAZARDS:
                connection.send_error(msg["id"], "invalid_hazard", "Unknown simulated hazard")
                return
            sim.setdefault("hazards", {})[hazard] = bool(msg.get("value", True))
        config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({vol.Required("type"): "openreef/awc_reset_ledger"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_awc_reset_ledger(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Zero the persistent net-imbalance ledger (after a manual salinity correction the
    accumulated drain-vs-fill net no longer describes the tank; start counting afresh)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    async with _awc_lock(hass):
        config = _config_from_entry(entry)  # fetched INSIDE the lock (R1)
        _awc_cfg(config)["ledger"] = {
            "cumulativeDrainedL": 0.0,
            "cumulativeFilledL": 0.0,
            "resetAt": datetime.now(timezone.utc).isoformat(),
        }
        _append_activity(config, "Water-change net-imbalance ledger reset", "control")
        config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/awc_tubing_replaced",
    vol.Required("role"): cv.string,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_awc_tubing_replaced(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Stamp a pump's tubing install date — the yearly tubing-age nag was dead code
    end-to-end because nothing ever set tubingInstalledAt (T6)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    role = msg["role"]
    if role not in AWC_PUMP_ROLES:
        connection.send_error(msg["id"], "invalid_role",
                              "Pump role must be 'drain', 'fill' or 'fill2'")
        return
    if not _awc_role_configured(entry, role):
        connection.send_error(msg["id"], "no_second_source",
                              "Add the second source in Water Change settings first")
        return
    config = _config_from_entry(entry)
    pump = _awc_cfg(config).setdefault("pumps", {}).setdefault(role, {})
    pump["tubingInstalledAt"] = datetime.now(timezone.utc).isoformat()
    _append_activity(config, f"AWC {role} pump tubing replaced", "control")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({vol.Required("type"): "openreef/awc_summary"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_awc_summary(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Derived AWC metrics for the panel: reservoir levels, days remaining, net-imbalance,
    honest dilution projection, calibration/tubing-age nags, plus the live state snapshot."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    acfg = _awc_cfg(config)
    summary = awc_engine.summary(_awc_cfg_eff(config), dt_util.now())
    state = acfg.get("state", {}) if isinstance(acfg.get("state"), dict) else {}
    fill_role = _awc_fill_role(state)
    # 0.6.0: the pre-B4 scalar aliases (drainedMl/filledMl/drainEndsAt/fillEndsAt)
    # are gone — consumers read the per-role movedMl/endsAt maps + activeSourceRole.
    connection.send_result(msg["id"], {
        "summary": summary,
        "state": state,
        "schedule": acfg.get("schedule", {}),
        "live": _awc_live_state(hass, config, fill_role=fill_role),
        "atoSuspended": _awc_ato_suspended(config),
        "simulation": acfg.get("simulation", {"enabled": False}),
        "simPumps": (hass.data.get(DOMAIN, {}).get(AWC_RUNTIME, {}).get("simPumps", {})
                     if _awc_sim_enabled(config) else {}),
    })


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/awc_set_schedule",
        vol.Required("schedule"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_awc_set_schedule(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Update the AWC schedule (normalisation validates/clamps the merged result)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    acfg = _awc_cfg(config)
    acfg["schedule"] = {**acfg.get("schedule", {}), **msg["schedule"]}
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


# --- Dosing channels: multi-pump dosing orchestration --------------------------------------
# The firmware executes the schedule and the full guard chain (dosing survives an HA
# outage); HA compiles daily-total-first schedules into the firmware's number entities
# with acknowledged read-back, watches the Dosed Today sensor for missed doses, and
# keeps the ledgers the firmware can't (reservoir, tube wear, calibration history,
# integrity). Maths in dosing.py; this section is pure orchestration.

def _dosing_channels(config: dict[str, Any]) -> dict[str, Any]:
    dosing = config.get("dosing") if isinstance(config.get("dosing"), dict) else {}
    channels = dosing.get("channels")
    return channels if isinstance(channels, dict) else {}


def _dosing_awc_suspended(config: dict[str, Any]) -> bool:
    """True while an automatic water change should hold dosing: running/paused/fault
    plus the post-change stabilisation hold-off. Mirrors _awc_ato_suspended but is NOT
    gated on the ATO toggle — each channel opts in via guards.suspendDuringAwc."""
    state = _awc_cfg(config).get("state", {})
    if _awc_sim_enabled(config):
        return False  # a VIRTUAL change must never hold the REAL doser
    # Micro-change: dosing keeps running through the RUN itself — but a previous
    # change's still-future hold-off keeps holding, and a fault holds regardless.
    if state.get("microChange") and state.get("status") != "fault":
        until = _parse_datetime(state.get("atoSuspendedUntil"))
        return until is not None and until > datetime.now(timezone.utc)
    if state.get("status") in (*_AWC_RUNNING_STATES, "paused", "fault"):
        return True
    until = state.get("atoSuspendedUntil")
    if until:
        try:
            return datetime.now(timezone.utc) < datetime.fromisoformat(str(until))
        except (ValueError, TypeError):
            return False
    return False


def _dosing_lighting_off_window(config: dict[str, Any], local_dt: datetime) -> tuple[int, int] | None:
    """The tank's lights-OFF window (minutes since midnight) for night weighting —
    the complement of the profile's lights-on window when one is configured."""
    lighting_cfg = _effective_lighting_cfg(config, local_dt)
    win = spawning.lighting_window(lighting_cfg, local_dt.date())
    if win is None:
        return None
    on_start, on_end = win
    if on_start == on_end:
        return None
    return on_end, on_start


def _dosing_live_state(hass: HomeAssistant, channel: dict[str, Any]) -> dict[str, Any]:
    """Entity snapshot the engine's guard mirror consumes. None means "not bound /
    can't tell" — the engine treats unknowns per-guard (fail closed only where the
    firmware would)."""
    entities = channel.get("driver", {}).get("entities", {})
    entities = entities if isinstance(entities, dict) else {}
    bound = [ent for ent in entities.values() if ent]
    available = 0
    for ent in bound:
        state = hass.states.get(ent)
        if state is not None and state.state not in UNAVAILABLE_STATES:
            available += 1
    device_online: bool | None = None if not bound else available > 0

    enabled: bool | None = None
    ent = entities.get("enabledSwitch")
    if ent:
        state = hass.states.get(ent)
        if state is not None and state.state not in UNAVAILABLE_STATES:
            enabled = str(state.state).lower() == "on"

    reservoir_low: bool | None = None
    ent = entities.get("reservoirLowSensor")
    if ent and not _awc_binary_unknown(hass, ent):
        reservoir_low = _awc_binary_on(hass, ent)

    guards = channel.get("guards", {}) if isinstance(channel.get("guards"), dict) else {}
    ph_entity = guards.get("phEntity") or ""
    ph_value: float | None = None
    ph_unavailable = False
    if ph_entity:
        state = hass.states.get(ph_entity)
        if state is None or state.state in UNAVAILABLE_STATES:
            ph_unavailable = True
        else:
            try:
                ph_value = float(state.state)
            except (TypeError, ValueError):
                ph_unavailable = True

    dosed = 0.0
    dosed_trusted = False
    ent = entities.get("dosedTodaySensor")
    if ent:
        state = hass.states.get(ent)
        if state is not None and state.state not in UNAVAILABLE_STATES:
            try:
                dosed = float(state.state)
                dosed_trusted = True
            except (TypeError, ValueError):
                dosed = 0.0
    if dosing_engine.is_ha_timed(channel):
        # No firmware sensor — the HA executor's dead-reckoned counter is the
        # honest number (never "trusted": there is no sensor to verify against).
        dosed = _awc_num((channel.get("state") or {}).get("haDosedTodayMl"), 0, 0, 1e6)

    return {
        "deviceOnline": device_online,
        "enabledSwitch": enabled,
        "reservoirLow": reservoir_low,
        "phValue": ph_value,
        "phUnavailable": ph_unavailable,
        "dosedTodayMl": dosed,
        "dosedSensorTrusted": dosed_trusted,
        "boundCount": len(bound),
        "availableCount": available,
    }


# --- pH mirror: the fixed entity id the kalk firmware subscribes to ------------------------

def _dosing_mirror_source(config: dict[str, Any]) -> str:
    """The pH entity the mirror follows: the first (sorted) kalk channel with one
    bound. One mirror, one kalk head per device — matches the firmware contract."""
    for cid in sorted(_dosing_channels(config)):
        channel = _dosing_channels(config)[cid]
        if channel.get("chemical") == "kalk":
            source = channel.get("guards", {}).get("phEntity")
            if source:
                return source
    return ""


def _dosing_publish_mirror(hass: HomeAssistant, source: str) -> None:
    """Republish the user-picked pH entity onto the fixed mirror id via a bare
    state-machine write (this integration deliberately creates no entity platforms).
    Source unavailable/non-numeric ⇒ mirror 'unavailable' ⇒ firmware NaN ⇒ the pH
    guard fails closed on-device."""
    value = "unavailable"
    if source:
        state = hass.states.get(source)
        if state is not None and state.state not in UNAVAILABLE_STATES:
            try:
                value = f"{float(state.state):.3f}"
            except (TypeError, ValueError):
                value = "unavailable"
    try:
        hass.states.async_set(
            DOSING_PH_MIRROR_ENTITY,
            value,
            {"friendly_name": "OpenReef Kalk pH Mirror", "source": source, "unit_of_measurement": "pH"},
        )
    except Exception:  # noqa: BLE001 — a mirror publish must never break a tick
        _LOGGER.exception("Dosing: failed to publish pH mirror state")


async def _async_setup_dosing_mirror(hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any]) -> None:
    store = hass.data.setdefault(DOMAIN, {})
    unsub = store.pop(DOSING_MIRROR_UNSUB, None)
    if unsub is not None:
        unsub()
    source = _dosing_mirror_source(config)
    has_kalk = any(ch.get("chemical") == "kalk" for ch in _dosing_channels(config).values())
    if not source:
        if has_kalk:
            # A kalk channel without a picked pH entity: keep the mirror honest so a
            # stale value from an earlier selection can never satisfy the guard.
            _dosing_publish_mirror(hass, "")
        return

    def _changed(event: Any) -> None:
        _dosing_publish_mirror(hass, source)

    store[DOSING_MIRROR_UNSUB] = async_track_state_change_event(hass, [source], _changed)
    _dosing_publish_mirror(hass, source)


# --- Settings sync: write-then-verify onto the firmware numbers ----------------------------

def _dosing_desired_writes(
    channel: dict[str, Any], config: dict[str, Any], now_local: datetime
) -> dict[str, float]:
    """Every firmware number this channel should hold, keyed by binding role."""
    compiled = dosing_engine.compile_schedule(channel, _dosing_lighting_off_window(config, now_local), now_local)
    writes = dict(compiled["writes"])
    spacing = (config.get("dosing") or {}).get("spacing", {})
    # Compile-time stagger (Stage E): shift a windowed doses-mode schedule by its
    # group's cumulative offset so conflicting groups interleave (alk :00 /
    # ca :30). Write-layer only — the configured window is untouched in config.
    group = dosing_engine.spacing_group(channel.get("chemical"))
    if (spacing.get("enabled") and group
            and str(channel.get("schedule", {}).get("mode")) == "doses"
            and "windowStartNumber" in writes and "windowEndNumber" in writes
            and writes["windowStartNumber"] != writes["windowEndNumber"]):
        groups_present = sorted({
            dosing_engine.spacing_group(ch.get("chemical"))
            for ch in _dosing_channels(config).values()
            if ch.get("enabled") and dosing_engine.spacing_group(ch.get("chemical"))
        })
        offset = dosing_engine.phase_offsets(spacing, groups_present).get(group, 0.0)
        if offset:
            writes["windowStartNumber"] = float((writes["windowStartNumber"] + offset) % 1440)
            writes["windowEndNumber"] = float((writes["windowEndNumber"] + offset) % 1440)
    if dosing_engine.is_brushed(channel):
        # Brushed heads run on flow-rate numbers, not stepper counts; the chaser
        # duration rides the same sync so the firmware always holds the setting.
        writes.pop("stepsPerMlNumber", None)
        ml_per_s = channel.get("calibration", {}).get("mlPerS") or 0
        if ml_per_s > 0:
            writes["flowMlPerSNumber"] = float(ml_per_s)
            writes["spinUpMlNumber"] = float(channel.get("calibration", {}).get("spinUpMl") or 0)
        writes["chaserSecondsNumber"] = float(channel.get("chaserSeconds") or 0)
        return writes
    steps_per_ml = channel.get("calibration", {}).get("stepsPerMl") or 0
    if steps_per_ml > 0:
        writes["stepsPerMlNumber"] = float(steps_per_ml)
    # Contract rev 3: the firmware's per-channel spacing guard input. Always
    # written (0 = off) so disabling spacing clears the device-held gap.
    writes["minGapNumber"] = float(round(
        dosing_engine.channel_min_gap_minutes(spacing, channel.get("chemical")), 1))
    return writes


def _dosing_desired_switches(channel: dict[str, Any], now: datetime | None = None) -> dict[str, bool]:
    """Desired firmware switch states. The enable switch only goes on when HA can
    stand behind the schedule: calibrated, (for kalk) the missing-pH state
    explicitly acknowledged, and (for live food) the culture still FRESH — the
    firmware can't see freshness, so HA owns the signal and the device holds the
    posture; the 60 s sync re-asserts it (the pH-mirror philosophy). haSuspendSwitch
    is NOT here — it belongs to the AWC hooks and the panic lockout, never to
    settings sync."""
    guards = channel.get("guards", {}) if isinstance(channel.get("guards"), dict) else {}
    if dosing_engine.is_brushed(channel):
        calibrated = (channel.get("calibration", {}).get("mlPerS") or 0) > 0
    else:
        calibrated = (channel.get("calibration", {}).get("stepsPerMl") or 0) > 0
    fresh_ok = True
    if channel.get("chemical") == "livefood":
        reservoir = channel.get("reservoir", {}) if isinstance(channel.get("reservoir"), dict) else {}
        fresh_ok = dosing_engine.freshness_state(
            reservoir, now or datetime.now(timezone.utc))["status"] != "stale"
    ph_ok = bool(guards.get("phEntity")) or bool(guards.get("phMissingAcknowledged")) or channel.get("chemical") != "kalk"
    schedule = channel.get("schedule", {}) if isinstance(channel.get("schedule"), dict) else {}
    schedule_on = bool(schedule.get("enabled"))
    has_volume = (schedule.get("mlPerDay") or 0) > 0
    return {
        # mlPerDay 0 is a safety edit: the enable switch must go OFF with it, or
        # the firmware keeps executing its previous schedule (R2).
        "enabledSwitch": bool(channel.get("enabled") and schedule_on and calibrated and ph_ok and has_volume and fresh_ok),
        "phGuardSwitch": bool(guards.get("phEntity")),
    }


async def _async_dosing_save(
    hass: HomeAssistant, entry: OpenReefConfigEntry, stale_config: dict[str, Any]
) -> None:
    """Persist dosing-side mutations without clobbering concurrent writers (R32).

    The sync pass and the tick hold a config snapshot across awaited service
    calls; saving that whole blob could silently revert an AWC leg credit or a
    non-dosing user save that landed meanwhile. Re-fetch and graft only what
    dosing owns — ``dosing.channels`` plus ``consumables.products`` (dose
    events debit linked bottles, so those ledgers move on dosing's clock too).
    NB: two concurrent writers can still interleave (the graft is wholesale per
    block); the single event loop makes that window rare and the 60 s tick
    self-corrects."""
    fresh = _config_from_entry(entry)
    stale_dosing = stale_config.get("dosing") if isinstance(stale_config.get("dosing"), dict) else {}
    if isinstance(stale_dosing.get("channels"), dict):
        fresh.setdefault("dosing", {})["channels"] = stale_dosing["channels"]
    stale_consumables = stale_config.get("consumables") \
        if isinstance(stale_config.get("consumables"), dict) else {}
    if isinstance(stale_consumables.get("products"), dict):
        fresh.setdefault("consumables", {})["products"] = stale_consumables["products"]
    await _async_save_config(hass, entry, fresh)


def _clear_dosing_verify(hass: HomeAssistant) -> None:
    unsub = hass.data.setdefault(DOMAIN, {}).pop(DOSING_VERIFY_UNSUB, None)
    if unsub is not None:
        unsub()


async def _async_dosing_sync_pass(
    hass: HomeAssistant, entry: OpenReefConfigEntry, channel_id: str | None = None
) -> None:
    """Diff every channel's desired firmware values against the live entities, write
    what differs, and arm the read-back verify. Every write is acknowledged — silent
    settings loss is the #1 doser-app trust breaker (Jebao/Kamoer lesson)."""
    store = hass.data.setdefault(DOMAIN, {})
    runtime = store.setdefault(DOSING_RUNTIME, {})
    runtime.pop("pass_scheduled", None)
    latest_entry = _first_entry(hass)
    if latest_entry is None or latest_entry.entry_id != entry.entry_id:
        return  # entry unloaded/replaced while the pass was queued
    config = _config_from_entry(entry)
    channels = _dosing_channels(config)
    if not channels:
        return
    desired_map = runtime.setdefault("desired", {})
    retries = runtime.setdefault("retries", {})
    now_local = dt_util.now()
    wrote_any = False
    changed = False

    for cid, channel in channels.items():
        if channel_id is not None and cid != channel_id:
            continue
        entities = channel.get("driver", {}).get("entities", {})
        entities = entities if isinstance(entities, dict) else {}
        sync = channel.setdefault("sync", {})
        desired = _dosing_desired_writes(channel, config, now_local)
        offline_roles: list[str] = []
        wrote: dict[str, float] = {}

        for role, value in desired.items():
            ent = entities.get(role)
            if not ent:
                continue
            state = hass.states.get(ent)
            if state is None or state.state in UNAVAILABLE_STATES:
                offline_roles.append(role)
                continue
            try:
                live_value = float(state.state)
            except (TypeError, ValueError):
                live_value = None
            if live_value is None or abs(live_value - value) > 0.011:
                await hass.services.async_call(
                    "number", "set_value", {ATTR_ENTITY_ID: ent, "value": value}, blocking=True
                )
                wrote[ent] = value

        for role, want_on in _dosing_desired_switches(channel).items():
            ent = entities.get(role)
            if not ent:
                continue
            state = hass.states.get(ent)
            if state is None or state.state in UNAVAILABLE_STATES:
                offline_roles.append(role)
                continue
            is_on = str(state.state).lower() == "on"
            if is_on != want_on:
                await hass.services.async_call(
                    "switch", "turn_on" if want_on else "turn_off", {ATTR_ENTITY_ID: ent}, blocking=True
                )

        if offline_roles:
            pending = {role: desired[role] for role in offline_roles if role in desired}
            if sync.get("state") != "offline" or sync.get("pendingWrites") != pending:
                sync["state"] = "offline"
                sync["lastError"] = f"{len(offline_roles)} device entities unavailable"
                sync["pendingWrites"] = pending
                changed = True
        elif wrote:
            desired_map[cid] = wrote
            retries[cid] = 0
            wrote_any = True
        else:
            if sync.get("state") != "synced" or sync.get("pendingWrites"):
                sync["state"] = "synced"
                sync["lastSyncedAt"] = datetime.now(timezone.utc).isoformat()
                sync["lastError"] = ""
                sync["pendingWrites"] = {}
                changed = True

    if wrote_any:
        _async_arm_dosing_verify(hass, entry)
    if changed:
        await _async_dosing_save(hass, entry, config)


def _async_arm_dosing_verify(hass: HomeAssistant, entry: OpenReefConfigEntry) -> None:
    _clear_dosing_verify(hass)

    async def _fired(now: datetime) -> None:
        hass.data.setdefault(DOMAIN, {}).pop(DOSING_VERIFY_UNSUB, None)
        latest_entry = _first_entry(hass)
        if latest_entry is None or latest_entry.entry_id != entry.entry_id:
            return
        await _async_dosing_verify(hass, entry)

    hass.data.setdefault(DOMAIN, {})[DOSING_VERIFY_UNSUB] = async_track_point_in_time(
        hass, _fired, dt_util.utcnow() + timedelta(seconds=DOSING_SYNC_VERIFY_DELAY_S)
    )


async def _async_dosing_verify(hass: HomeAssistant, entry: OpenReefConfigEntry) -> None:
    """The read-back half of write-then-verify: every written entity must now hold
    its value. One retry, then a loud 'failed' — never silent (reef-pi runaway lesson:
    fire-and-forget motor config is how tanks get dumped into)."""
    config = _config_from_entry(entry)
    channels = _dosing_channels(config)
    runtime = hass.data.setdefault(DOMAIN, {}).setdefault(DOSING_RUNTIME, {})
    desired_map = runtime.setdefault("desired", {})
    retries = runtime.setdefault("retries", {})
    changed = False
    rewrote = False

    for cid in list(desired_map):
        wrote = desired_map.get(cid) or {}
        channel = channels.get(cid)
        if channel is None:
            desired_map.pop(cid, None)
            continue
        sync = channel.setdefault("sync", {})
        mismatched: dict[str, float] = {}
        for ent, value in wrote.items():
            state = hass.states.get(ent)
            try:
                live_value = float(state.state) if state is not None else None
            except (TypeError, ValueError):
                live_value = None
            if live_value is None or abs(live_value - value) > 0.011:
                mismatched[ent] = value
        if not mismatched:
            sync["state"] = "synced"
            sync["lastSyncedAt"] = datetime.now(timezone.utc).isoformat()
            sync["lastError"] = ""
            sync["pendingWrites"] = {}
            if (channel.get("calibration", {}).get("stepsPerMl") or 0) > 0:
                channel.setdefault("calibration", {})["syncedToDevice"] = True
            desired_map.pop(cid, None)
            changed = True
        elif retries.get(cid, 0) < 1:
            retries[cid] = retries.get(cid, 0) + 1
            for ent, value in mismatched.items():
                await hass.services.async_call(
                    "number", "set_value", {ATTR_ENTITY_ID: ent, "value": value}, blocking=True
                )
            desired_map[cid] = mismatched
            rewrote = True
        else:
            sync["state"] = "failed"
            sync["lastError"] = f"{len(mismatched)} values did not stick on the device"
            desired_map.pop(cid, None)
            changed = True
            if _dosing_notify_enabled(config, "syncIssues"):
                await _async_send_mode_notification(
                    hass, config, f"openreef_dosing_sync_{cid}",
                    f"Dosing sync failed: {channel.get('name', cid)}",
                    "Settings written to the doser did not read back — the device may be "
                    "offline or rejecting writes. Dosing continues on its LAST synced schedule.",
                )

    if rewrote:
        _async_arm_dosing_verify(hass, entry)
    if changed:
        await _async_dosing_save(hass, entry, config)


def _async_kick_dosing_sync(hass: HomeAssistant, entry: OpenReefConfigEntry) -> None:
    """Schedule a sync pass out-of-band of the save that requested it (a pass saves
    its own terminal states; running it inline would recurse into save)."""
    runtime = hass.data.setdefault(DOMAIN, {}).setdefault(DOSING_RUNTIME, {})
    if runtime.get("pass_scheduled"):
        return
    runtime["pass_scheduled"] = True
    hass.async_create_task(_async_dosing_sync_pass(hass, entry))


# --- AWC coordination: hold dosing during a water change -----------------------------------

async def _async_dosing_awc_suspend(hass: HomeAssistant, config: dict[str, Any], active: bool, context: Any) -> None:
    """Flip each opted-in channel's firmware HA-suspend switch. Never the master
    enable — a dead HA mid-suspension must not silently disable dosing forever, so
    the firmware side auto-expires this switch (~4 h) as the dead-man backstop."""
    if _awc_sim_enabled(config):
        return  # a simulated change must not flip real firmware suspend switches
    for channel in _dosing_channels(config).values():
        guards = channel.get("guards", {}) if isinstance(channel.get("guards"), dict) else {}
        if not guards.get("suspendDuringAwc", True):
            continue
        ent = channel.get("driver", {}).get("entities", {}).get("haSuspendSwitch")
        if not ent:
            continue
        if not active:
            # A user panic lockout owns the switch: an AWC release (finalize/abort/
            # holdoff/acknowledge) must not cancel it (R15). The tick's suspend
            # reconciliation releases it when suspendedUntil lapses.
            until = _parse_datetime((channel.get("state") or {}).get("suspendedUntil"))
            if until is not None and until > datetime.now(timezone.utc):
                continue
        try:
            await hass.services.async_call(
                "switch", "turn_on" if active else "turn_off", {ATTR_ENTITY_ID: ent},
                blocking=True, context=context,
            )
        except Exception:  # noqa: BLE001 — a failed suspend must not abort the water change
            _LOGGER.exception("Dosing: failed to %s HA-suspend switch %s", "set" if active else "clear", ent)


# --- Periodic tick: accounting, missed doses, drift, alerts --------------------------------

def _clear_dosing_tick(hass: HomeAssistant) -> None:
    unsub = hass.data.setdefault(DOMAIN, {}).pop(DOSING_TICK_UNSUB, None)
    if unsub is not None:
        unsub()


def _clear_dosing(hass: HomeAssistant) -> None:
    _clear_dosing_tick(hass)
    _clear_dosing_verify(hass)
    store = hass.data.setdefault(DOMAIN, {})
    unsub = store.pop(DOSING_MIRROR_UNSUB, None)
    if unsub is not None:
        unsub()
    store.pop(DOSING_RUNTIME, None)


async def _async_schedule_dosing_tick(
    hass: HomeAssistant, entry: OpenReefConfigEntry | None, config: dict[str, Any] | None = None,
) -> None:
    _clear_dosing_tick(hass)
    if entry is None:
        return
    config = config or _config_from_entry(entry)
    dosing_cfg = config.get("dosing") if isinstance(config.get("dosing"), dict) else {}
    if not dosing_cfg.get("enabled", True) or not _dosing_channels(config):
        return

    async def _handle(now: datetime) -> None:
        latest_entry = _first_entry(hass)
        if latest_entry is None or latest_entry.entry_id != entry.entry_id:
            return
        await _async_dosing_tick(hass, latest_entry)

    hass.data.setdefault(DOMAIN, {})[DOSING_TICK_UNSUB] = async_track_time_interval(
        hass, _handle, timedelta(seconds=DOSING_TICK_SECONDS)
    )


def _dosing_plan_fingerprint(channel: dict[str, Any], plan: dict[str, Any]) -> tuple:
    """What the missed-dose baseline is anchored to: any change here (schedule edit,
    enable flip, respread) resets the expected-vs-actual comparison to 'from now',
    so a mid-day plan change can never manufacture a phantom shortfall."""
    return (
        bool(channel.get("enabled")),
        bool(channel.get("schedule", {}).get("enabled")) if isinstance(channel.get("schedule"), dict) else False,
        plan.get("perDoseMl"), plan.get("dayIntervalMin"), plan.get("nightIntervalMin"),
        plan.get("windowStart"), plan.get("windowEnd"),
        plan.get("nightStart"), plan.get("nightEnd"), plan.get("nightPercent"),
    )


def _dosing_notify_enabled(config: dict[str, Any], family: str) -> bool:
    dosing = config.get("dosing") if isinstance(config.get("dosing"), dict) else {}
    notifications = dosing.get("notifications") if isinstance(dosing.get("notifications"), dict) else {}
    return bool(notifications.get(family, True))


async def _async_dosing_notify_once(
    hass: HomeAssistant, config: dict[str, Any], runtime: dict[str, Any],
    key: str, cooldown_s: float, title: str, message: str,
) -> None:
    notified = runtime.setdefault("notified", {})
    now = datetime.now(timezone.utc)
    previous = notified.get(key)
    if previous is not None:
        try:
            if (now - datetime.fromisoformat(previous)).total_seconds() < cooldown_s:
                return
        except (ValueError, TypeError):
            pass
    notified[key] = now.isoformat()
    await _async_send_mode_notification(hass, config, f"openreef_dosing_{key}", title, message)


def _dosing_group_last_dose(hass: HomeAssistant, config: dict[str, Any]) -> dict[str, Any]:
    """When each spacing group last dosed (max lastDoseAt over its channels) —
    the HA-side input to spacing_verdict. Runtime stamps win over persisted state
    (state only flushes hourly/on transition; spacing must not run an hour stale)."""
    runtime_channels = hass.data.get(DOMAIN, {}).get(DOSING_RUNTIME, {}).get("channels", {})
    out: dict[str, Any] = {}
    for cid, channel in _dosing_channels(config).items():
        group = dosing_engine.spacing_group(channel.get("chemical"))
        if not group:
            continue
        candidates = [
            _parse_datetime((runtime_channels.get(cid) or {}).get("lastDoseAt")),
            _parse_datetime((channel.get("state") or {}).get("lastDoseAt")),
        ]
        last = max((c for c in candidates if c is not None), default=None)
        if last is not None and (out.get(group) is None or last > out[group]):
            out[group] = last
        out.setdefault(group, None)
    return out


async def _async_dosing_fire_bounded_dose(
    hass: HomeAssistant, channel: dict[str, Any], ml: float, cid: str | None = None,
) -> bool:
    """Actuate one bounded manual dose (write the volume, press the guarded
    firmware button) and optimistically stamp lastDoseAt so spacing sees it
    before the next sensor tick. Returns False when the button isn't bound."""
    ent = channel.get("driver", {}).get("entities", {}).get("manualDoseMlNumber")
    if ent:
        await hass.services.async_call(
            "number", "set_value", {ATTR_ENTITY_ID: ent, "value": ml}, blocking=True)
    if not await _async_dosing_press(hass, channel, "manualDoseButton"):
        return False
    stamp = datetime.now(timezone.utc).isoformat()
    channel.setdefault("state", {})["lastDoseAt"] = stamp
    if cid:
        hass.data.setdefault(DOMAIN, {}).setdefault(DOSING_RUNTIME, {}).setdefault(
            "channels", {}).setdefault(cid, {})["lastDoseAt"] = stamp
    return True


async def _async_awc_credit_chaser_fill(
    hass: HomeAssistant, entry: OpenReefConfigEntry, chaser_ml: float
) -> None:
    """Debit the AWC fresh reservoir for a firmware-run post-dose chaser rinse (the
    live-food head pulls its rinse from the AWC fresh line) and count it into the
    cumulative fill ledger — water entered the tank. Locked fetch-fresh: this is
    called from the dosing tick, which must never clobber AWC state (R1)."""
    if chaser_ml <= 0:
        return
    async with _awc_lock(hass):
        config = _config_from_entry(entry)
        awc = _awc_cfg(config)
        if not awc:
            return
        _awc_debit_source(awc, "fill", chaser_ml)
        ledger = awc.setdefault("ledger", {})
        ledger["cumulativeFilledL"] = round(
            _awc_num(ledger.get("cumulativeFilledL"), 0, 0, 1e9) + chaser_ml / 1000.0, 3)
        _append_activity(
            config, f"Live-food chaser rinse: {chaser_ml:.0f} ml from the fresh reservoir",
            "control")
        await _async_save_config(hass, entry, config)


# --- NPS feed-exchange (Stage B): matched drain for live-food dosing ------------------------

async def _async_nps_feed_exchange_accrue(
    hass: HomeAssistant, entry: OpenReefConfigEntry,
    channel_id: str, dose_ml: float, chaser_ml: float,
) -> None:
    """Bank a matched drain for a live-food dose: the dose AND its line-flush
    chaser both entered the tank, so the feed-exchange owes that whole volume
    back out (net-zero level — the ATO never fights the feed). Also credits the
    dose into the AWC fill ledger as external water in (the chaser was already
    credited by _async_awc_credit_chaser_fill), keeping the net-imbalance ledger
    honest. Locked fetch-fresh, the chaser-credit pattern."""
    if dose_ml <= 0 and chaser_ml <= 0:
        return
    async with _awc_lock(hass):
        config = _config_from_entry(entry)
        fx = (config.get("nps") or {}).get("feedExchange") or {}
        if not fx.get("enabled") or str(fx.get("channelId") or "") != str(channel_id):
            return
        state = fx.setdefault("state", {})
        owed, dropped = nps_engine.feed_exchange_owed(
            state.get("owedMl"), dose_ml, chaser_ml, fx.get("maxOwedMl"))
        state["owedMl"] = owed
        if dropped > 0:
            state["droppedMl"] = round(
                _awc_num(state.get("droppedMl"), 0, 0, 1e9) + dropped, 1)
            _append_activity(
                config,
                f"Feed-exchange owed cap reached — {dropped:.0f} ml will NOT be auto-drained "
                "(clear the drain blocker or raise the cap, then trim manually)", "warning")
        awc = _awc_cfg(config)
        if awc and dose_ml > 0:
            ledger = awc.setdefault("ledger", {})
            ledger["cumulativeFilledL"] = round(
                _awc_num(ledger.get("cumulativeFilledL"), 0, 0, 1e9) + dose_ml / 1000.0, 3)
        _append_activity(
            config,
            f"Feed-exchange: banked {dose_ml + chaser_ml:.0f} ml to drain "
            f"({dose_ml:.0f} ml brine + {chaser_ml:.0f} ml chaser) — owed {owed:.0f} ml",
            "control")
        await _async_save_config(hass, entry, config)


_NPS_TRUCE_PROFILES = (
    ("uv", "uvOffMinutes"), ("ozone", "ozoneOffMinutes"), ("skimmer", "skimmerOffMinutes"),
)


async def _async_nps_truce_engage(
    hass: HomeAssistant, entry: OpenReefConfigEntry, context: Any = None
) -> None:
    """A food/live-food dose just landed: pause the plankton-hostile equipment
    (UV kills what was dosed, ozone likewise, the skimmer strips it) for their
    configured windows. Armed equipment only; a repeat dose extends a running
    truce. Restore is stamp-driven — the minutely dosing tick is the backstop —
    so a restart can never leave equipment off forever."""
    config = _config_from_entry(entry)
    truce = (config.get("nps") or {}).get("truce") or {}
    if not truce.get("enabled"):
        return
    now = datetime.now(timezone.utc)
    state = truce.setdefault("state", {})
    changed = False
    for profile, minutes_key in _NPS_TRUCE_PROFILES:
        minutes = _awc_num(truce.get(minutes_key), 0, 0, 720)
        if minutes <= 0:
            continue
        targets = _armed_equipment_by_profile(config, profile)
        if not targets:
            continue
        pstate = state.setdefault(profile, {})
        turned_off = [e for e in (pstate.get("turnedOff") or []) if isinstance(e, str)]
        for _equipment_id, mapped in targets:
            switch_entity = _normalise_entity_id(mapped.get("switch_entity_id"))
            if not switch_entity:
                continue
            live = hass.states.get(switch_entity)
            if live is None or live.state != "on":
                continue  # off already (keeper's choice) or unavailable — never claim it
            try:
                await hass.services.async_call(
                    "switch", "turn_off", {ATTR_ENTITY_ID: switch_entity},
                    blocking=True, context=context)
            except Exception:  # noqa: BLE001 — a dead switch must not kill the tick
                continue
            if switch_entity not in turned_off:
                turned_off.append(switch_entity)
            changed = True
        if turned_off:
            pstate["turnedOff"] = turned_off
            restore_at = now + timedelta(minutes=minutes)
            existing = _parse_datetime(pstate.get("restoreAt"))
            if existing is None or restore_at > existing:
                pstate["restoreAt"] = restore_at.isoformat()
                changed = True
    if changed:
        _append_activity(
            config,
            "Feed truce: plankton-hostile equipment paused after a food dose",
            "control")
        await _async_save_config(hass, entry, config)


async def _async_nps_truce_tick(
    hass: HomeAssistant, entry: OpenReefConfigEntry
) -> None:
    """Restore truce-paused equipment whose window has passed (or whose truce
    was disabled mid-hold). Only entities the truce itself turned off are ever
    restored — a skimmer the keeper had off stays off. A failed turn-on stays
    in the list and retries next tick."""
    config = _config_from_entry(entry)
    truce = (config.get("nps") or {}).get("truce") or {}
    state = truce.get("state") or {}
    now = datetime.now(timezone.utc)
    changed = False
    for profile, _minutes_key in _NPS_TRUCE_PROFILES:
        pstate = state.get(profile) or {}
        turned_off = [e for e in (pstate.get("turnedOff") or []) if isinstance(e, str)]
        if not turned_off:
            continue
        restore_at = _parse_datetime(pstate.get("restoreAt"))
        due = (not truce.get("enabled")) or restore_at is None or restore_at <= now
        if not due:
            continue
        remaining: list[str] = []
        for switch_entity in turned_off:
            try:
                await hass.services.async_call(
                    "switch", "turn_on", {ATTR_ENTITY_ID: switch_entity},
                    blocking=True, context=None)
            except Exception:  # noqa: BLE001 — retry on the next tick
                remaining.append(switch_entity)
        pstate["turnedOff"] = remaining
        changed = True
        if not remaining:
            pstate["restoreAt"] = ""
            wet = " — expect it to run wet for a while (that's the export working)" \
                if profile == "skimmer" else ""
            _append_activity(config, f"Feed truce over: {profile} back on{wet}", "control")
    if changed:
        await _async_save_config(hass, entry, config)


# --- ha_switch_timed driver (Stage C): HA-executed dosing for generic pumps ------------------

async def _async_dosing_ha_finish(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any],
    cid: str, channel: dict[str, Any], actual_elapsed_s: float | None = None,
) -> None:
    """Stop an ha_switch_timed run and settle the books dead-reckoned: today
    counter, lastDoseAt, reservoir ledger (+ linked bottle), wear, and the
    feed-exchange/truce hooks the firmware channels get from their sensors.

    ``actual_elapsed_s`` None = the stop timer fired on time (credit the target).
    A value = the pump really ran that long (tick caught an overdue run, or a
    restart orphaned it) — credit the honest elapsed volume, UNCAPPED: if the
    pump over-ran, the ledger must say so, loudly."""
    driver = channel.get("driver") or {}
    switch_entity = (driver.get("entities") or {}).get("powerSwitch")
    if switch_entity:
        try:
            await hass.services.async_call(
                "switch", "turn_off", {ATTR_ENTITY_ID: switch_entity}, blocking=True)
        except Exception:  # noqa: BLE001 — could not stop: keep the stamps, retry next tick
            return
    rt = hass.data.setdefault(DOMAIN, {}).setdefault(DOSING_RUNTIME, {}) \
        .setdefault("channels", {}).setdefault(cid, {})
    unsub = rt.pop("haRunUnsub", None)
    if unsub is not None:
        try:
            unsub()
        except Exception:  # noqa: BLE001
            pass
    state = channel.setdefault("state", {})
    target_ml = _awc_num(state.get("haRunTargetMl"), 0, 0, 100000)
    started = _parse_datetime(state.get("haRunStartedAt"))
    ends = _parse_datetime(state.get("haRunEndsAt"))
    run_s = max(0.0, (ends - started).total_seconds()) \
        if started is not None and ends is not None else 0.0
    cal = channel.get("calibration") or {}
    dosed_ml = target_ml
    if actual_elapsed_s is not None:
        run_s = actual_elapsed_s
        dosed_ml = max(0.0, awc_engine.volume_for_runtime_l(
            actual_elapsed_s, _awc_num(cal.get("mlPerS"), 0, 0, 200), 1.0,
            _awc_num(cal.get("spinUpMl"), 0, -50, 50)) * 1000.0)
        if target_ml > 0 and dosed_ml > target_ml * 1.5:
            _dosing_record_event(
                channel, "warn",
                f"Pump ran unattended ~{run_s:.0f} s (~{dosed_ml:.0f} ml; the dose "
                f"was {target_ml:.0f} ml) — likely an HA outage mid-dose. "
                "Ledgers credited honestly; check the tank.")
    state["haRunStartedAt"] = ""
    state["haRunEndsAt"] = ""
    state["haRunTargetMl"] = 0
    if dosed_ml > 0:
        state["haDosedTodayMl"] = round(
            _awc_num(state.get("haDosedTodayMl"), 0, 0, 1e6) + dosed_ml, 2)
        state["lastDoseAt"] = datetime.now(timezone.utc).isoformat()
        reservoir = channel.setdefault("reservoir", {})
        reservoir["remainingMl"] = round(max(
            0.0, _awc_num(reservoir.get("remainingMl"), 0, 0, DOSING_RESERVOIR_MAX_ML)
            - dosed_ml), 1)
        product_id = str(reservoir.get("productId") or "")
        if product_id and reservoir.get("productIsBottle"):
            product = ((config.get("consumables") or {}).get("products") or {}).get(product_id)
            if isinstance(product, dict):
                _consumable_debit(product, dosed_ml, "pump")
        wear = channel.setdefault("wear", {})
        wear["runSeconds"] = round(_awc_num(wear.get("runSeconds"), 0, 0, 1e9) + run_s, 1)
        wear["doseCount"] = int(_awc_num(wear.get("doseCount"), 0, 0, 1e9)) + 1
        # The same NPS hooks firmware channels get from their dosed-today sensor.
        await _async_nps_feed_exchange_accrue(hass, entry, cid, dosed_ml, 0.0)
        if channel.get("chemical") in ("livefood", "food"):
            await _async_nps_truce_engage(hass, entry)
    await _async_dosing_save(hass, entry, config)


async def _async_dosing_ha_run(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any],
    cid: str, channel: dict[str, Any], target_ml: float, burst_s: float | None = None,
) -> bool:
    """Energise an ha_switch_timed channel's pump: for exactly the calibrated
    runtime of ``target_ml``, or (``burst_s``) a raw timed burst that credits
    nothing — the prime/calibration ceremony. Arms the stop timer and stamps the
    persisted in-flight trace (the matched-drain pattern). Caller validates
    guards; this validates the physics."""
    driver = channel.get("driver") or {}
    switch_entity = (driver.get("entities") or {}).get("powerSwitch")
    if not switch_entity:
        return False
    cal = channel.get("calibration") or {}
    if burst_s is not None:
        runtime_s = max(1.0, min(float(burst_s), DOSING_HA_MAX_DOSE_RUN_S))
        target_ml = 0.0
    else:
        ml_per_s = _awc_num(cal.get("mlPerS"), 0, 0, 200)
        if ml_per_s <= 0 or target_ml <= 0:
            return False
        runtime_s = awc_engine.runtime_for_volume_s(
            target_ml / 1000.0, ml_per_s, 1.0, _awc_num(cal.get("spinUpMl"), 0, -50, 50))
        if runtime_s <= 0 or runtime_s > DOSING_HA_MAX_DOSE_RUN_S:
            _dosing_record_event(
                channel, "skip",
                f"Dose skipped: {target_ml:g} ml needs {runtime_s:.0f} s — over the "
                f"{DOSING_HA_MAX_DOSE_RUN_S:.0f} s per-dose safety cap (check the flow calibration)")
            return False
    try:
        await hass.services.async_call(
            "switch", "turn_on", {ATTR_ENTITY_ID: switch_entity}, blocking=True)
    except Exception:  # noqa: BLE001 — nothing started
        return False
    started = datetime.now(timezone.utc)
    ends = started + timedelta(seconds=runtime_s)
    state = channel.setdefault("state", {})
    state["haRunStartedAt"] = started.isoformat()
    state["haRunEndsAt"] = ends.isoformat()
    state["haRunTargetMl"] = round(float(target_ml), 2)
    # Persist the stamps BEFORE arming the timer (the matched-drain rule): a
    # short dose's stop can fire before the tick's own save lands, and the
    # stop path fetches fresh — without this it would find no run to settle.
    await _async_dosing_save(hass, entry, config)

    async def _stop(_now: datetime) -> None:
        latest = _first_entry(hass)
        if latest is None:
            return
        cfg = _config_from_entry(latest)
        ch = _dosing_channels(cfg).get(cid)
        if ch is None or not (ch.get("state") or {}).get("haRunEndsAt"):
            return
        await _async_dosing_ha_finish(hass, latest, cfg, cid, ch)

    rt = hass.data.setdefault(DOMAIN, {}).setdefault(DOSING_RUNTIME, {}) \
        .setdefault("channels", {}).setdefault(cid, {})
    rt["haRunUnsub"] = async_track_point_in_time(hass, _stop, ends)
    return True


async def _async_dosing_ha_executor(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any],
    now_utc: datetime, now_local: datetime, lighting_off: Any,
) -> bool:
    """HA-executed scheduling for ha_switch_timed channels — the generic
    adapter: any HA switch plus a timed-flow calibration is a dosing pump.
    Deliberately best-effort (no doses while HA is down; on return the schedule
    resumes, capped by the daily plan — NEVER a catch-up bolus) and deliberately
    not for kalk (kalk without firmware failsafes is refused outright). The
    guard chain is ENFORCEMENT here, not the display mirror it is for firmware
    channels. One action per channel per tick. Returns True when channel state
    changed (the tick then saves as a transition)."""
    changed = False
    now_minutes = now_local.hour * 60 + now_local.minute
    today = now_local.strftime("%Y-%m-%d")
    for cid, channel in _dosing_channels(config).items():
        if not dosing_engine.is_ha_timed(channel):
            continue
        state = channel.setdefault("state", {})
        if state.get("haDoseDate") != today:
            state["haDoseDate"] = today
            state["haDosedTodayMl"] = 0.0
            changed = True
        ends = _parse_datetime(state.get("haRunEndsAt"))
        if ends is not None:
            if now_utc >= ends:
                # The stop timer missed (reload/latency): settle with the honest
                # elapsed volume, not the target.
                started = _parse_datetime(state.get("haRunStartedAt"))
                elapsed = max(0.0, (now_utc - started).total_seconds()) if started else 0.0
                await _async_dosing_ha_finish(
                    hass, entry, config, cid, channel, actual_elapsed_s=elapsed)
                changed = True
            continue
        if channel.get("chemical") == "kalk":
            continue  # refused outright — kalk needs firmware failsafes
        if not channel.get("enabled") or not (channel.get("schedule") or {}).get("enabled"):
            continue
        compiled = dosing_engine.compile_schedule(channel, lighting_off, now_local)
        plan = compiled["plan"]
        per_dose = _awc_num(plan.get("perDoseMl"), 0, 0, DOSING_MAX_PER_DOSE_ML)
        ml_per_day = _awc_num(plan.get("mlPerDay"), 0, 0, DOSING_ML_PER_DAY_MAX)
        if per_dose <= 0 or ml_per_day <= 0:
            continue
        dosed_today = _awc_num(state.get("haDosedTodayMl"), 0, 0, 1e6)
        if dosed_today + per_dose > ml_per_day + 0.01:
            continue  # today's plan is met — resuming later never boluses
        night_interval = int(_awc_num(plan.get("nightIntervalMin"), 0, 0, 100000))
        in_night = night_interval > 0 and awc_engine.within_window(
            now_minutes, int(_awc_num(plan.get("nightStart"), 1320, 0, 1439)),
            int(_awc_num(plan.get("nightEnd"), 480, 0, 1439)))
        in_day = awc_engine.within_window(
            now_minutes, int(_awc_num(plan.get("windowStart"), 0, 0, 1439)),
            int(_awc_num(plan.get("windowEnd"), 0, 0, 1439)))
        if in_night:
            interval_min = night_interval
        elif in_day:
            interval_min = int(_awc_num(plan.get("dayIntervalMin"), 60, 1, 100000)) or 60
        else:
            continue
        last = _parse_datetime(state.get("lastDoseAt"))
        if last is not None and (now_utc - last).total_seconds() < interval_min * 60 - 5:
            continue
        live = _dosing_live_state(hass, channel)
        live["dosedTodayMl"] = dosed_today
        reasons = dosing_engine.guard_reasons(channel, live, now_minutes, False, now_utc)
        if any(r.get("severity") == "block" for r in reasons):
            continue
        if await _async_dosing_ha_run(hass, entry, config, cid, channel, per_dose):
            _dosing_record_event(channel, "dose", f"HA-timed dose started: {per_dose:g} ml")
            changed = True
    return changed


async def _async_dosing_ha_recover(
    hass: HomeAssistant, entry: OpenReefConfigEntry
) -> None:
    """ha_switch_timed runs orphaned by a restart: the persisted haRunEndsAt
    stamp is the trace — stop the switch and credit the honest elapsed volume
    (which may exceed the target: the pump kept running while HA was down;
    the finish path warns loudly when it did)."""
    config = _config_from_entry(entry)
    now = datetime.now(timezone.utc)
    for cid, channel in _dosing_channels(config).items():
        if not dosing_engine.is_ha_timed(channel):
            continue
        state = channel.get("state") or {}
        if not state.get("haRunEndsAt"):
            continue
        started = _parse_datetime(state.get("haRunStartedAt"))
        elapsed = max(0.0, (now - started).total_seconds()) if started else 0.0
        await _async_dosing_ha_finish(
            hass, entry, config, cid, channel, actual_elapsed_s=elapsed)


async def _async_nps_drain_finish(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any],
    drained_ml: float, seconds: float, note: str = "",
) -> None:
    """Stop the drain pump and settle the books: waste gains, the owed ledger
    shrinks, the AWC drained ledger grows. Called from the stop timer (full
    planned volume) and from orphan recovery (elapsed-time partial). Caller
    holds the AWC lock."""
    await _async_awc_stop_pumps(hass, config, ("drain",), None)
    acfg = _awc_cfg(config)
    _awc_bump_odometer(acfg, "drain", seconds=seconds)
    drained_ml = max(0.0, float(drained_ml or 0))
    waste = acfg.setdefault("reservoirs", {}).setdefault("waste", {})
    waste["filledMl"] = round(_awc_num(waste.get("filledMl"), 0, 0, 1e9) + drained_ml, 1)
    ledger = acfg.setdefault("ledger", {})
    ledger["cumulativeDrainedL"] = round(
        _awc_num(ledger.get("cumulativeDrainedL"), 0, 0, 1e9) + drained_ml / 1000.0, 3)
    fx = (config.get("nps") or {}).get("feedExchange") or {}
    st = fx.setdefault("state", {})
    st["owedMl"] = round(max(0.0, _awc_num(st.get("owedMl"), 0, 0, 1e9) - drained_ml), 1)
    st["totalDrainedL"] = round(
        _awc_num(st.get("totalDrainedL"), 0, 0, 1e9) + drained_ml / 1000.0, 3)
    st["lastDrainAt"] = datetime.now(timezone.utc).isoformat()
    st["lastDrainMl"] = round(drained_ml, 1)
    st["drainStartedAt"] = ""
    st["drainEndsAt"] = ""
    st["drainTargetMl"] = 0
    _append_activity(
        config,
        f"Feed-exchange drain finished: {drained_ml:.0f} ml matched back out{note}",
        "control")
    await _async_save_config(hass, entry, config)


async def _async_nps_matched_drain_maybe(
    hass: HomeAssistant, entry: OpenReefConfigEntry, now_local: datetime,
) -> bool:
    """Run the owed feed-exchange drain when it's worth it and safe (called from
    the minutely AWC tick's idle path). A volume-primary timed run on the AWC
    drain pump — the calibration-run pattern, with full accounting. Returns True
    when a drain just started, so the tick doesn't also start a change."""
    peek_fx = (_config_from_entry(entry).get("nps") or {}).get("feedExchange") or {}
    if not peek_fx.get("enabled"):
        return False
    peek_state = peek_fx.get("state") or {}
    if _awc_num(peek_state.get("owedMl"), 0, 0, 1e9) \
            < _awc_num(peek_fx.get("minDrainMl"), 150, 10, 5000):
        return False
    store = hass.data.setdefault(DOMAIN, {})
    if store.get(AWC_CALRUN_UNSUB) is not None or store.get(NPS_DRAIN_UNSUB) is not None:
        return False
    async with _awc_lock(hass):
        config = _config_from_entry(entry)
        acfg = _awc_cfg(config)
        fx = (config.get("nps") or {}).get("feedExchange") or {}
        fx_state = fx.setdefault("state", {})
        if acfg.get("state", {}).get("status") != "idle":
            return False

        async def _note_blocked(reason_code: str, message: str) -> None:
            # Activity once per distinct blocker, not once per minute.
            if fx_state.get("lastBlockedReason") != reason_code:
                fx_state["lastBlockedReason"] = reason_code
                _append_activity(config, f"Feed-exchange drain waiting: {message}", "warning")
                await _async_save_config(hass, entry, config)

        live = _awc_live_state(hass, config)
        # fill_role="drain" narrows the pump checks to the drain alone — a
        # matched drain needs no fill source. Hazard/fail-closed/quiet-hours
        # guards apply exactly as they do to a scheduled change.
        reasons = awc_engine.start_guard_reasons(
            _awc_cfg_eff(config), live,
            now_local.hour * 60 + now_local.minute, False, fill_role="drain")
        if reasons:
            await _note_blocked(reasons[0]["code"], reasons[0]["message"])
            return False
        waste = (acfg.get("reservoirs") or {}).get("waste") or {}
        headroom_ml = None
        cap_l = _awc_num(waste.get("capacityLitres"), 0, 0, 100000)
        if cap_l > 0:
            headroom_ml = max(
                0.0, cap_l * 1000.0 - _awc_num(waste.get("filledMl"), 0, 0, 1e9))
        batch_ml = nps_engine.feed_exchange_batch(
            fx_state.get("owedMl"), fx.get("minDrainMl"), fx.get("maxOwedMl"), headroom_ml)
        if batch_ml <= 0:
            if headroom_ml is not None and headroom_ml < _awc_num(
                    fx.get("minDrainMl"), 150, 10, 5000):
                await _note_blocked(
                    "waste_headroom", "the waste reservoir is nearly full")
            return False
        pump = (acfg.get("pumps") or {}).get("drain") or {}
        ml_per_s = _awc_num(pump.get("mlPerS"), 0, 0, 1000)
        factor = _awc_num(pump.get("exchangeFactor"), 1.0, 0.1, 10)
        spin_up = _awc_num(pump.get("spinUpMl"), 0, -50, 50)
        runtime_s = awc_engine.runtime_for_volume_s(
            batch_ml / 1000.0, ml_per_s, factor, spin_up)
        if runtime_s <= 0:
            await _note_blocked("no_calibration", "the drain pump is not calibrated")
            return False
        # Never exceed the safety max-runtime (the firmware watchdog would
        # fail-lock the pump): shrink the batch to fit; the rest stays owed.
        max_run_s = _awc_num((acfg.get("safety") or {}).get("maxRuntimeSeconds"), 0, 0, 36000)
        if max_run_s > 0 and runtime_s > max_run_s:
            batch_ml = max(0.0, awc_engine.volume_for_runtime_l(
                max_run_s, ml_per_s, factor, spin_up) * 1000.0)
            runtime_s = max_run_s
            if batch_ml < _awc_num(fx.get("minDrainMl"), 150, 10, 5000):
                return False
        try:
            await _async_awc_set_pump(hass, config, "drain", True, None)
        except Exception:  # noqa: BLE001 — nothing started; try again next tick
            await _note_blocked("pump_start_failed", "the drain pump did not switch on")
            return False
        started_at = datetime.now(timezone.utc)
        ends_at = started_at + timedelta(seconds=runtime_s)

        async def _stop(_now: datetime) -> None:
            latest = _first_entry(hass)
            async with _awc_lock(hass):
                # Pop inside the lock (the calibration-run race lesson).
                hass.data.setdefault(DOMAIN, {}).pop(NPS_DRAIN_UNSUB, None)
                if latest is None:
                    return
                cfg = _config_from_entry(latest)
                await _async_nps_drain_finish(hass, latest, cfg, batch_ml, runtime_s)

        store[NPS_DRAIN_UNSUB] = async_track_point_in_time(hass, _stop, ends_at)
        # Persist the in-flight run: the stop timer is in-memory only, so these
        # stamps are the sole trace a restart has for stopping the orphan.
        fx_state["drainStartedAt"] = started_at.isoformat()
        fx_state["drainEndsAt"] = ends_at.isoformat()
        fx_state["drainTargetMl"] = round(batch_ml, 1)
        fx_state["lastBlockedReason"] = ""
        _append_activity(
            config,
            f"Feed-exchange drain started: {batch_ml:.0f} ml (~{runtime_s:.0f} s) to match "
            "live-food dosing", "control")
        await _async_save_config(hass, entry, config)
        # Optional camera trace (opt-in trigger): the feeding journal writes itself.
        _dispatch_capture(hass, entry, "nps_feed_exchange",
                          f"Feed-exchange drain {batch_ml:.0f} ml")
        return True


async def _async_nps_recover_orphaned_drain(
    hass: HomeAssistant, entry: OpenReefConfigEntry
) -> None:
    """A matched drain's stop timer is in-memory only: if HA restarted mid-run,
    the drain pump is still physically running with nothing armed to stop it.
    The persisted drainStartedAt/TargetMl stamps are the trace — stop it and
    credit the elapsed-time partial volume (the interrupted-leg pattern)."""
    peek = (_config_from_entry(entry).get("nps") or {}).get("feedExchange") or {}
    if not (peek.get("state") or {}).get("drainStartedAt"):
        return
    async with _awc_lock(hass):
        config = _config_from_entry(entry)
        fx = (config.get("nps") or {}).get("feedExchange") or {}
        st = fx.get("state") or {}
        started = _parse_datetime(st.get("drainStartedAt"))
        target_ml = _awc_num(st.get("drainTargetMl"), 0, 0, 100000)
        pump = (_awc_cfg(config).get("pumps") or {}).get("drain") or {}
        elapsed_s = 0.0
        if started is not None:
            elapsed_s = max(0.0, (datetime.now(timezone.utc) - started).total_seconds())
        moved_ml = min(target_ml, max(0.0, awc_engine.volume_for_runtime_l(
            elapsed_s,
            _awc_num(pump.get("mlPerS"), 0, 0, 1000),
            _awc_num(pump.get("exchangeFactor"), 1.0, 0.1, 10),
            _awc_num(pump.get("spinUpMl"), 0, -50, 50)) * 1000.0))
        await _async_nps_drain_finish(
            hass, entry, config, moved_ml, elapsed_s,
            note=" (interrupted by a restart — elapsed-time credit)")


async def _async_dosing_fire_queued(
    hass: HomeAssistant, entry: OpenReefConfigEntry, queued_peek: dict[str, Any]
) -> None:
    """Fire (or re-schedule, or drop) the queued spacing-deferred dose. Peeked from
    the tick's snapshot; every mutation happens on a FRESH fetch + save so the
    tick's graft-save never carries (or clobbers) spacing state."""
    not_before = _parse_datetime(queued_peek.get("notBefore"))
    if not_before is not None and not_before > datetime.now(timezone.utc):
        return
    config = _config_from_entry(entry)
    spacing = config.get("dosing", {}).get("spacing", {})
    queued = spacing.get("queued")
    if not queued:
        return
    cid = str(queued.get("channelId") or "")
    channel = _dosing_channels(config).get(cid)
    if channel is None:
        spacing["queued"] = None
        await _async_save_config(hass, entry, config)
        return
    verdict = dosing_engine.spacing_verdict(
        spacing, channel.get("chemical"), _dosing_group_last_dose(hass, config),
        datetime.now(timezone.utc))
    if not verdict["ok"]:
        # Another group dosed meanwhile — push the slot forward, never spin.
        spacing["queued"] = {**queued, "notBefore": (
            datetime.now(timezone.utc) + timedelta(minutes=verdict["waitMinutes"])
        ).isoformat()}
        await _async_save_config(hass, entry, config)
        return
    # The ordinary manual gates re-apply at FIRE time (fail-closed: a channel that
    # went stale/uncalibrated/suspended while queued must not dose).
    now_local = dt_util.now()
    live = _dosing_live_state(hass, channel)
    live["awcActive"] = _dosing_awc_suspended(config)
    live["now"] = datetime.now(timezone.utc)
    blocked = [
        r for r in dosing_engine.guard_reasons(
            channel, live, now_local.hour * 60 + now_local.minute, manual=True,
            now=datetime.now(timezone.utc))
        if r["severity"] == "block" and r["code"] != "disabled"
    ]
    if blocked:
        spacing["queued"] = None
        _dosing_record_event(
            channel, "spacing_queue", f"Queued dose dropped — {blocked[0]['code']}")
        await _async_save_config(hass, entry, config)
        return
    ml = _awc_num(queued.get("ml"), 0, 0, DOSING_MAX_PER_DOSE_ML)
    fired = ml > 0 and await _async_dosing_fire_bounded_dose(hass, channel, ml, cid=cid)
    spacing["queued"] = None
    _dosing_record_event(
        channel, "spacing_queue",
        f"Queued {ml:g} ml dose fired — spacing gap clear" if fired
        else "Queued dose dropped — manual-dose button not bound")
    await _async_save_config(hass, entry, config)


async def _async_nps_hatch_ready_push(
    hass: HomeAssistant, entry: OpenReefConfigEntry
) -> None:
    """Hour-precise 'brine ready to harvest' notification (hatchery v2). Each
    batch fires exactly once — readyNotifiedAt stamps the vessel. Fetch-fresh
    and self-persisting, so it can't clobber (or be clobbered by) the tick's
    accounting snapshot. Phone push reuses the maintenance reminders' target."""
    config = _config_from_entry(entry)
    nps_cfg = config.get("nps") or {}
    hatchery = nps_cfg.get("hatchery") or {}
    vessels = hatchery.get("vessels") if isinstance(hatchery.get("vessels"), dict) else {}
    # Standalone hatcheries (0.7.71): the gate is the hatchery's own flag —
    # breeders run brine rigs with NPS off. Pre-migration configs inherit.
    if not vessels or not hatchery.get("enabled", nps_cfg.get("enabled")):
        return
    now = datetime.now(timezone.utc)
    changed = False
    for vid, vessel in vessels.items():
        if not isinstance(vessel, dict):
            continue
        state = vessel.get("state") if isinstance(vessel.get("state"), dict) else {}
        if state.get("readyNotifiedAt"):
            continue
        started = _parse_datetime(state.get("hatchStartedAt"))
        if started is None:
            continue
        hours = _awc_num(state.get("hatchHours"), 24, 8, 48)
        if (now - started).total_seconds() / 3600.0 < hours:
            continue
        state["readyNotifiedAt"] = now.isoformat()
        changed = True
        name = str(vessel.get("name") or vid)
        title = f"OpenReef: Brine ready to harvest — {name}"
        message = (f"The {hours:g} h hatch is done. Rinse the nauplii (never dose "
                   "hatch water), resuspend at tank salinity, load the container, "
                   "then tap 'Hatched & loaded'. Harvesting promptly keeps the "
                   "yolk calories.")
        await hass.services.async_call(
            "persistent_notification", "create",
            {"notification_id": f"openreef_hatch_ready_{vid}",
             "title": title, "message": message},
            blocking=False)
        reminders = (config.get("maintenance") or {}).get("reminders") or {}
        target = str(reminders.get("notifyTarget", "")).strip() if isinstance(reminders, dict) else ""
        if target:
            await hass.services.async_call(
                "notify", target, {"title": title, "message": message}, blocking=False)
        _append_activity(config, f"Brine ready to harvest in {name}", "info")
    # Enrichment clocks (doc §10): soak done + optional T+10 top-up, each once.
    enrichment = hatchery.get("enrichment") if isinstance(hatchery.get("enrichment"), dict) else {}
    enrich_state = enrichment.get("state") if isinstance(enrichment.get("state"), dict) else {}
    enrich_started = _parse_datetime(enrich_state.get("startedAt"))
    if enrich_started is not None:
        elapsed_h = (now - enrich_started).total_seconds() / 3600.0
        enrich_hours = _awc_num(enrich_state.get("enrichHours"),
                                nps_engine.ENRICH_DEFAULT_HOURS, 2, 48)
        delay_h = _awc_num(enrich_state.get("doseDelayH"), 0, 0, 24)
        first_dose = _parse_datetime(enrich_state.get("firstDoseAt"))
        if first_dose is None and delay_h <= 0:
            first_dose = enrich_started  # immediate protocol (engine lockstep)
        fed_h = ((now - first_dose).total_seconds() / 3600.0
                 if first_dose is not None else None)
        # The molt clock runs on the BATCH's age (its load stamp), not on
        # when the soak was engaged (container semantics, 0.7.70).
        dose_ref = _parse_datetime(enrich_state.get("batchLoadedAt")) or enrich_started
        batch_age_h = (now - dose_ref).total_seconds() / 3600.0
        notices = []
        if (first_dose is None and delay_h > 0 and batch_age_h >= delay_h
                and not enrich_state.get("firstDoseNotifiedAt")):
            # The molt has landed — mouths are open, the Selcon can go in.
            enrich_state["firstDoseNotifiedAt"] = now.isoformat()
            notices.append((
                "openreef_enrich_dose",
                "OpenReef: Add the enrichment dose",
                "The batch has crossed instar II — add the Selcon and tap "
                "'Add dose' on the NPS tab. The soak clock proper starts there."))
        elif fed_h is not None and fed_h >= enrich_hours and not enrich_state.get("readyNotifiedAt"):
            enrich_state["readyNotifiedAt"] = now.isoformat()
            notices.append((
                "openreef_enrich_done",
                "OpenReef: Brine enrichment done — rinse & load",
                "The soak is finished. Rinse on a fine screen (emulsion residue "
                "breeds bacteria), load the container, then tap 'Enriched & "
                "loaded'. Warm-held enriched brine loses half its boost in a day."))
        elif (bool(enrichment.get("splitDose"))
              and fed_h is not None
              and fed_h >= nps_engine.ENRICH_SECOND_DOSE_H
              and fed_h < enrich_hours
              and not enrich_state.get("secondDoseAt")
              and not enrich_state.get("secondDoseNotifiedAt")):
            enrich_state["secondDoseNotifiedAt"] = now.isoformat()
            notices.append((
                "openreef_enrich_topup",
                "OpenReef: Enrichment top-up due",
                "The soak is 10 h past the first dose — add the second "
                "enrichment dose and tap 'Log top-up' on the NPS tab."))
        for notification_id, title, message in notices:
            changed = True
            await hass.services.async_call(
                "persistent_notification", "create",
                {"notification_id": notification_id, "title": title, "message": message},
                blocking=False)
            reminders = (config.get("maintenance") or {}).get("reminders") or {}
            target = str(reminders.get("notifyTarget", "")).strip() if isinstance(reminders, dict) else ""
            if target:
                await hass.services.async_call(
                    "notify", target, {"title": title, "message": message}, blocking=False)
            _append_activity(config, title.replace("OpenReef: ", ""), "info")
    if changed:
        _persist_entry_config(hass, entry, config)


async def _async_dosing_tick(hass: HomeAssistant, entry: OpenReefConfigEntry) -> None:
    """The 60 s watcher. Accounting deltas accumulate in hass.data and flush to the
    config blob hourly or on a transition — kalk doses ~144x/day and every blob save
    runs the full pipeline, so per-dose saves are deliberately off the table (per-dose
    granularity lives in the recorder history of the firmware's Dosed Today sensor)."""
    # Feed-truce restore backstop (Stage C): stamp-driven, fetch-fresh — runs
    # before the snapshot below so a restore can never be clobbered by it.
    await _async_nps_truce_tick(hass, entry)
    # Hatch-ready push (hatchery v2): hour-precise, from this minutely tick —
    # the daily maintenance-reminder tick is far too coarse for a harvest
    # window. Runs BEFORE the no-channels bail-out: hand-dosers have no pumps.
    await _async_nps_hatch_ready_push(hass, entry)

    config = _config_from_entry(entry)
    channels = _dosing_channels(config)
    if not channels:
        return
    store = hass.data.setdefault(DOMAIN, {})
    runtime = store.setdefault(DOSING_RUNTIME, {})
    channel_rt = runtime.setdefault("channels", {})
    now_utc = datetime.now(timezone.utc)
    now_local = dt_util.now()
    now_minutes = now_local.hour * 60 + now_local.minute
    lighting_off = _dosing_lighting_off_window(config, now_local)
    transition = False

    _dosing_publish_mirror(hass, _dosing_mirror_source(config))  # heartbeat

    # Spacing queue (Stage E): fire the single deferred dose once its gap clears.
    queued_peek = (config.get("dosing", {}).get("spacing") or {}).get("queued")
    if queued_peek:
        await _async_dosing_fire_queued(hass, entry, queued_peek)

    for cid, channel in channels.items():
        rt = channel_rt.setdefault(cid, {})
        state = channel.setdefault("state", {})
        entities = channel.get("driver", {}).get("entities", {})
        entities = entities if isinstance(entities, dict) else {}
        live = _dosing_live_state(hass, channel)
        compiled = dosing_engine.compile_schedule(channel, lighting_off, now_local)
        plan = compiled["plan"]

        # --- sensor delta accounting (rollover detection is value-based: clock-immune)
        sensor_ent = entities.get("dosedTodaySensor")
        sensor_state = hass.states.get(sensor_ent) if sensor_ent else None
        sensor_trusted = False
        if sensor_state is not None and sensor_state.state not in UNAVAILABLE_STATES:
            try:
                new_ml = float(sensor_state.state)
            except (TypeError, ValueError):
                new_ml = None
            if new_ml is not None:
                sensor_trusted = True
                prev = rt.get("lastSensorMl")
                if prev is None:
                    prev = float(state.get("lastSensorMl") or 0.0)
                    if not state.get("lastSensorAt") and prev <= 0 < new_ml:
                        # First-ever observation of a doser that already dosed today:
                        # establish the baseline without debiting the ledgers.
                        prev = new_ml
                if dosing_engine.detect_rollover(prev, new_ml):
                    near_midnight = (
                        now_minutes <= DOSING_ROLLOVER_ANOMALY_MINUTES
                        or now_minutes >= 1440 - DOSING_ROLLOVER_ANOMALY_MINUTES
                    )
                    state["rolloverAnomaly"] = not near_midnight
                    gap = 0.0
                    if near_midnight:
                        # Pre-midnight blind window (R34): doses landing between the
                        # tick's last sample and the firmware reset would otherwise
                        # never be debited from reservoir/wear. Reconcile against
                        # the plan, clamped to the daily cap headroom.
                        if channel.get("enabled") and channel.get("schedule", {}).get("enabled"):
                            expected_eod = dosing_engine.expected_dosed_ml(plan, 1440)
                            max_daily = plan.get("maxDailyMl") or 0
                            headroom = max(0.0, max_daily - prev) if max_daily > 0 else float("inf")
                            gap = min(max(0.0, expected_eod - prev), headroom)
                        log = channel.setdefault("dailyLog", [])
                        log.insert(0, {
                            "date": (now_local.date() - timedelta(days=1)).isoformat(),
                            "targetMl": plan.get("realisedMlPerDay", 0),
                            "deliveredMl": round(prev + gap, 2),
                        })
                        del log[DOSING_DAILY_LOG_MAX:]
                        rt["baselineMinute"] = 0
                        rt["baselineMl"] = 0.0
                    else:
                        # Anomalous reset (tz-skewed doser, NVS wipe): anchoring the
                        # baseline at minute 0 manufactured a giant false "missed"
                        # alarm (R16); anchor at NOW and skip the bogus dated-
                        # yesterday log entry instead.
                        rt["baselineMinute"] = now_minutes
                        rt["baselineMl"] = new_ml
                    if state.get("respread"):
                        # The tightened catch-up intervals expire with the day; the
                        # resulting firmware divergence is expected — resync without
                        # the scary "settings drifted" notification (R31).
                        state["respread"] = {}
                        rt["suppressDriftNotify"] = True
                        _async_kick_dosing_sync(hass, entry)
                    state["missedMl"] = 0.0
                    state["missedSince"] = ""
                    rt["missedStreak"] = 0
                    delta = max(0.0, new_ml) + gap
                    transition = True
                else:
                    delta = max(0.0, new_ml - prev)
                rt["lastSensorMl"] = new_ml
                if delta > 0:
                    rt["lastDoseAt"] = now_utc.isoformat()
                    state["lastDoseAt"] = now_utc.isoformat()
                    rt["pendingReservoirMl"] = rt.get("pendingReservoirMl", 0.0) + delta
                    speed = 400.0
                    speed_ent = entities.get("doseSpeedNumber")
                    if speed_ent:
                        speed_state = hass.states.get(speed_ent)
                        if speed_state is not None and speed_state.state not in UNAVAILABLE_STATES:
                            try:
                                speed = float(speed_state.state) or speed
                            except (TypeError, ValueError):
                                pass
                    rt["pendingRunSeconds"] = rt.get("pendingRunSeconds", 0.0) + dosing_engine.tube_wear_increment(
                        delta, channel.get("calibration", {}).get("stepsPerMl") or 0, speed
                    )
                    per_dose = plan.get("perDoseMl") or 0
                    if per_dose > 0:
                        rt["pendingDoses"] = rt.get("pendingDoses", 0) + max(1, round(delta / per_dose))
                    # Post-dose fresh chaser (brushed live-food heads): the firmware
                    # ran a rinse from the AWC fresh line after each dose — debit the
                    # AWC models for it, unless the firmware says it skipped (the AWC
                    # owned the fresh pump at the time).
                    chaser_s = _awc_num(channel.get("chaserSeconds"), 0, 0, 120)
                    chaser_credit_ml = 0.0
                    if chaser_s > 0 and dosing_engine.is_brushed(channel):
                        skipped_ent = entities.get("chaserSkippedSensor")
                        skipped_state = hass.states.get(skipped_ent) if skipped_ent else None
                        skipped = (skipped_state is not None
                                   and str(skipped_state.state).lower() == "on")
                        flow = _awc_num(channel.get("calibration", {}).get("mlPerS"), 0, 0, 200)
                        doses = max(1, round(delta / per_dose)) if per_dose > 0 else 1
                        if not skipped and flow > 0:
                            chaser_credit_ml = chaser_s * flow * doses
                            await _async_awc_credit_chaser_fill(
                                hass, entry, chaser_credit_ml)
                    # Feed-exchange (Stage B): the dose AND its chaser rinse are
                    # water IN — bank both as owed matched drain. The chaser is
                    # the bigger number at brine scale; skipping it would leave
                    # the tank creeping up every feeding day.
                    await _async_nps_feed_exchange_accrue(
                        hass, entry, cid, delta, chaser_credit_ml)
                    # Feed truce (Stage C): a food dose landed — pause UV/ozone/
                    # skimmer for their windows so the food survives to be eaten.
                    if channel.get("chemical") in ("livefood", "food"):
                        await _async_nps_truce_engage(hass, entry)

        # --- respread staleness (R17): a schedule edit after an accepted respread
        # invalidates the catch-up override — the safety edit wins immediately.
        if compiled["plan"].get("respreadStale") and state.get("respread"):
            state["respread"] = {}
            rt["suppressDriftNotify"] = True
            _async_kick_dosing_sync(hass, entry)
            transition = True

        # --- suspend-switch reconciliation (R3): the firmware's 4 h auto-expiry is
        # a dead-man for a DEAD HA — a live HA must re-assert the hold every tick
        # so a 24 h panic lockout (or a long AWC fault hold) never silently lapses
        # at hour 4; conversely a lapsed lockout releases on time, not at expiry.
        suspend_ent = entities.get("haSuspendSwitch")
        if suspend_ent:
            suspend_state = hass.states.get(suspend_ent)
            if suspend_state is not None and suspend_state.state not in UNAVAILABLE_STATES:
                until = _parse_datetime(state.get("suspendedUntil"))
                lockout_active = until is not None and until > now_utc
                awc_hold = (
                    bool(channel.get("guards", {}).get("suspendDuringAwc", True))
                    and _dosing_awc_suspended(config)
                )
                switch_on = str(suspend_state.state).lower() == "on"
                if lockout_active or awc_hold:
                    # (Re)assert even when already on: the turn_on restarts the
                    # firmware's auto-expiry window.
                    await hass.services.async_call(
                        "switch", "turn_on", {ATTR_ENTITY_ID: suspend_ent}, blocking=True
                    )
                elif switch_on:
                    await hass.services.async_call(
                        "switch", "turn_off", {ATTR_ENTITY_ID: suspend_ent}, blocking=True
                    )
                if until is not None and not lockout_active and state.get("suspendedUntil"):
                    state["suspendedUntil"] = ""
                    transition = True

        # --- live-food freshness posture (Stage C): the firmware can't see
        # freshness, so HA owns the signal and the device holds the posture — the
        # enable switch is asserted OFF every tick while the culture is stale
        # (mirror of the suspend re-assertion above); after a refresh the sync's
        # desired-switches path turns it back on.
        if channel.get("chemical") == "livefood":
            fresh = dosing_engine.freshness_state(
                channel.get("reservoir", {}) if isinstance(channel.get("reservoir"), dict) else {},
                now_utc)
            was_stale = bool(rt.get("staleFood"))
            is_stale = fresh["status"] == "stale"
            rt["staleFood"] = is_stale
            if is_stale:
                enable_ent = entities.get("enabledSwitch")
                if enable_ent:
                    enable_state = hass.states.get(enable_ent)
                    if (enable_state is not None
                            and str(enable_state.state).lower() == "on"):
                        await hass.services.async_call(
                            "switch", "turn_off", {ATTR_ENTITY_ID: enable_ent}, blocking=True
                        )
                if not was_stale:
                    _dosing_record_event(
                        channel, "stale",
                        "Live food past its shelf life — dosing disabled until refreshed")
                    transition = True
                if _dosing_notify_enabled(config, "staleFood"):
                    await _async_dosing_notify_once(
                        hass, config, runtime, f"stale_{cid}", 12 * 3600,
                        "Live food is stale",
                        f"{channel.get('name') or cid}: the culture is past its shelf "
                        "life — dosing is disabled until you refresh the reservoir "
                        "and tap 'Refreshed'.")
            elif was_stale:
                # Fresh again (mark_refreshed landed): re-assert the desired ON state
                # promptly rather than waiting for drift repair.
                _async_kick_dosing_sync(hass, entry)

        # --- missed-dose watcher (baselined, availability-gated, 2-tick debounce) ----
        # The baseline anchors "expected" to the moment the current plan took effect,
        # so a mid-day schedule edit or enable-flip can never manufacture a phantom
        # shortfall; a sensor HA can't read never accrues toward an alarm (the doser
        # keeps dosing autonomously through HA/network blips — that's the design).
        fp = _dosing_plan_fingerprint(channel, plan)
        actual = rt.get("lastSensorMl", state.get("lastSensorMl") or 0.0)
        if rt.get("planFp") != fp:
            rt["planFp"] = fp
            rt["baselineMinute"] = now_minutes
            rt["baselineMl"] = actual
            rt["missedStreak"] = 0
        if not sensor_trusted:
            rt["missedStreak"] = 0
        elif channel.get("enabled") and channel.get("schedule", {}).get("enabled"):
            base_minute = int(rt.get("baselineMinute") or 0)
            base_ml = float(rt.get("baselineMl") or 0.0)
            expected = (
                dosing_engine.expected_dosed_ml(plan, now_minutes)
                - dosing_engine.expected_dosed_ml(plan, base_minute)
            )
            missed = dosing_engine.missed_state(expected, actual - base_ml, plan.get("perDoseMl") or 0)
            if missed["status"] == "missed":
                rt["missedStreak"] = rt.get("missedStreak", 0) + 1
                if rt["missedStreak"] >= 2 and not state.get("missedSince"):
                    state["missedMl"] = missed["missedMl"]
                    state["missedSince"] = now_utc.isoformat()
                    transition = True
                    action = "skipped (kalk default)" if channel.get("chemical") == "kalk" else "awaiting your decision"
                    if _dosing_notify_enabled(config, "missedDose"):
                        await _async_dosing_notify_once(
                            hass, config, runtime, f"missed_{cid}", 6 * 3600,
                            f"Missed doses: {channel.get('name', cid)}",
                            f"{missed['missedMl']:.1f} ml behind schedule — {action}. "
                            "Open the Dosing tab to re-spread or skip.",
                        )
                elif state.get("missedSince"):
                    state["missedMl"] = missed["missedMl"]
            else:
                rt["missedStreak"] = 0
                if missed["status"] == "ok" and state.get("missedSince"):
                    state["missedMl"] = 0.0
                    state["missedSince"] = ""
                    transition = True

        # --- pH hysteresis latch mirror (display only; enforcement is firmware-side) --
        if channel.get("guards", {}).get("phEntity") and live.get("phValue") is not None:
            pause_above = channel["guards"].get("phPauseAbove") or 0
            resume_below = channel["guards"].get("phResumeBelow") or 0
            if not 0 < resume_below < pause_above:
                resume_below = round(pause_above - 0.1, 2)  # same fallback as the firmware write
            latched = bool(state.get("phLatchedHigh"))
            ph = live["phValue"]
            if pause_above > 0:
                if not latched and ph >= pause_above:
                    state["phLatchedHigh"] = True
                    transition = True
                elif latched and ph < resume_below:
                    state["phLatchedHigh"] = False
                    transition = True

        # --- reservoir / tube alerts (advisory — never disables dosing) --------------
        reservoir = channel.get("reservoir", {}) if isinstance(channel.get("reservoir"), dict) else {}
        remaining_eff = max(0.0, (reservoir.get("remainingMl") or 0.0) - rt.get("pendingReservoirMl", 0.0))
        low_threshold = reservoir.get("lowThresholdMl") or 0
        if (reservoir.get("volumeMl") or 0) > 0 and remaining_eff <= low_threshold and _dosing_notify_enabled(config, "reservoirLow"):
            await _async_dosing_notify_once(
                hass, config, runtime, f"reservoir_{cid}", 12 * 3600,
                f"Dosing reservoir low: {channel.get('name', cid)}",
                f"~{remaining_eff / 1000.0:.1f} L left — refill, then use 'Refilled — re-prime' so the ledger stays honest.",
            )
        cal_block = channel.get("calibration", {}) if isinstance(channel.get("calibration"), dict) else {}
        cal_age = awc_engine._age_days(cal_block.get("calibratedAt"), now_utc) if cal_block.get("calibratedAt") else None
        if (
            cal_age is not None and cal_age >= DOSING_RECAL_NAG_DAYS
            and (cal_block.get("stepsPerMl") or 0) > 0
            and _dosing_notify_enabled(config, "calibrationDue")
        ):
            await _async_dosing_notify_once(
                hass, config, runtime, f"recal_{cid}", 7 * 24 * 3600,
                f"Recalibrate doser: {channel.get('name', cid)}",
                f"Calibration is {cal_age:.0f} days old — peristaltic tubes drift, and calibration "
                "drift is the #1 cause of creeping chemistry. Run the 100-revolution calibration again.",
            )
        wear = channel.get("wear", {}) if isinstance(channel.get("wear"), dict) else {}
        run_hours = ((wear.get("runSeconds") or 0.0) + rt.get("pendingRunSeconds", 0.0)) / 3600.0
        if run_hours >= (wear.get("tubeLifeHours") or DOSING_TUBE_LIFE_HOURS_DEFAULT) and _dosing_notify_enabled(config, "tubeLife"):
            await _async_dosing_notify_once(
                hass, config, runtime, f"tube_{cid}", 24 * 3600,
                f"Replace pump tube: {channel.get('name', cid)}",
                f"{run_hours:.0f} h of run time — peristaltic tubes lose accuracy past their rated life. "
                "Replace, recalibrate, then reset the tube counter.",
            )

        # --- drift repair: live numbers vs desired (external edit / device reset) ----
        sync = channel.get("sync", {}) if isinstance(channel.get("sync"), dict) else {}
        if sync.get("state") == "synced" and cid not in runtime.get("desired", {}):
            desired = _dosing_desired_writes(channel, config, now_local)
            drifted = False
            for role, value in desired.items():
                ent = entities.get(role)
                if not ent:
                    continue
                drift_state = hass.states.get(ent)
                if drift_state is None or drift_state.state in UNAVAILABLE_STATES:
                    continue
                try:
                    if abs(float(drift_state.state) - value) > 0.011:
                        drifted = True
                        break
                except (TypeError, ValueError):
                    continue
            if drifted:
                # A just-expired/invalidated respread makes this divergence
                # expected — resync silently instead of crying "external edit".
                if rt.pop("suppressDriftNotify", None):
                    pass
                elif _dosing_notify_enabled(config, "syncIssues"):
                    await _async_dosing_notify_once(
                        hass, config, runtime, f"drift_{cid}", 6 * 3600,
                        f"Doser settings drifted: {channel.get('name', cid)}",
                        "The device's numbers no longer match OpenReef (external edit or device reset). "
                        "Re-syncing now — OpenReef's configuration is authoritative.",
                    )
                _async_kick_dosing_sync(hass, entry)

        # One-tick scope for the drift-notify suppression: the expected divergence
        # is detected (and the flag consumed) in this same iteration, or the kicked
        # resync removes it before the next — an unconsumed leftover must not
        # swallow a future GENUINE external-edit notification.
        rt.pop("suppressDriftNotify", None)

    # --- ha_switch_timed executor (Stage C): HA-side scheduling for generic pumps ------
    if await _async_dosing_ha_executor(hass, entry, config, now_utc, now_local, lighting_off):
        transition = True

    # --- flush policy: transitions save now; quiet accounting flushes hourly ----------
    last_flush = runtime.get("lastFlushAt")
    flush_due = True
    if last_flush is not None:
        try:
            flush_due = (now_utc - datetime.fromisoformat(last_flush)).total_seconds() >= DOSING_FLUSH_INTERVAL_S
        except (ValueError, TypeError):
            flush_due = True
    has_pending = any(
        rt.get("pendingReservoirMl") or rt.get("pendingRunSeconds") or rt.get("pendingDoses")
        for rt in channel_rt.values()
    )
    if transition or (flush_due and has_pending):
        for cid, channel in channels.items():
            rt = channel_rt.get(cid) or {}
            state = channel.setdefault("state", {})
            reservoir = channel.setdefault("reservoir", {})
            wear = channel.setdefault("wear", {})
            if rt.get("pendingReservoirMl"):
                pending_ml = rt.pop("pendingReservoirMl")
                reservoir["remainingMl"] = max(0.0, (reservoir.get("remainingMl") or 0.0) - pending_ml)
                # Consumables bridge: when the bottle IS the reservoir, pump
                # doses debit the tracked bottle too (its runway forecast
                # feeds on this history).
                product_id = str(reservoir.get("productId") or "")
                if product_id and reservoir.get("productIsBottle"):
                    product = ((config.get("consumables") or {}).get("products") or {}).get(product_id)
                    if isinstance(product, dict):
                        _consumable_debit(product, pending_ml, "pump")
            if rt.get("pendingRunSeconds"):
                wear["runSeconds"] = (wear.get("runSeconds") or 0.0) + rt.pop("pendingRunSeconds")
            if rt.get("pendingDoses"):
                wear["doseCount"] = int(wear.get("doseCount") or 0) + int(rt.pop("pendingDoses"))
            if rt.get("lastSensorMl") is not None:
                state["lastSensorMl"] = rt["lastSensorMl"]
                state["lastSensorAt"] = now_utc.isoformat()
        runtime["lastFlushAt"] = now_utc.isoformat()
        await _async_dosing_save(hass, entry, config)


# --- Dosing WebSocket API -------------------------------------------------------------------

def _dosing_channel_for_msg(
    connection: websocket_api.ActiveConnection, msg: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any] | None:
    channel = _dosing_channels(config).get(msg.get("channel_id"))
    if channel is None:
        connection.send_error(msg["id"], "unknown_channel", "No such dosing channel")
    return channel


async def _async_dosing_press(hass: HomeAssistant, channel: dict[str, Any], role: str) -> bool:
    ent = channel.get("driver", {}).get("entities", {}).get(role)
    if not ent:
        return False
    state = hass.states.get(ent)
    if state is None or state.state in UNAVAILABLE_STATES:
        return False
    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: ent}, blocking=True)
    return True


def _dosing_record_event(channel: dict[str, Any], kind: str, detail: str) -> None:
    events = channel.setdefault("events", [])
    events.insert(0, {"at": datetime.now(timezone.utc).isoformat(), "kind": kind, "detail": detail[:200]})
    del events[DOSING_EVENTS_MAX:]


@websocket_api.websocket_command({vol.Required("type"): "openreef/dosing_summary"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_dosing_summary(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Everything the Dosing tab needs: per-channel plan/guards/reservoir/integrity/
    tube/calibration/sync, plus the AWC-suspend flag and binding availability."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    channels = _dosing_channels(config)
    now_local = dt_util.now()
    awc_suspended = _dosing_awc_suspended(config)
    live_map: dict[str, dict[str, Any]] = {}
    bindings: dict[str, dict[str, Any]] = {}
    for cid, channel in channels.items():
        live = _dosing_live_state(hass, channel)
        live["awcActive"] = awc_suspended
        live_map[cid] = live
        entities = channel.get("driver", {}).get("entities", {})
        entities = entities if isinstance(entities, dict) else {}
        missing = [role for role, ent in entities.items() if not ent]
        unavailable = [
            role for role, ent in entities.items()
            if ent and (hass.states.get(ent) is None or hass.states.get(ent).state in UNAVAILABLE_STATES)
        ]
        bindings[cid] = {
            "bound": live["boundCount"],
            "total": len(DOSING_BINDING_ROLES),
            "missing": missing,
            "unavailable": unavailable,
        }
    runtime = hass.data.setdefault(DOMAIN, {}).setdefault(DOSING_RUNTIME, {})
    verifying = set(runtime.get("desired", {}) or {})
    summary = dosing_engine.summary(channels, live_map, now_local, _dosing_lighting_off_window(config, now_local))
    for cid in summary:
        if cid in verifying:
            summary[cid]["sync"]["state"] = "verifying"
    connection.send_result(msg["id"], {
        "summary": summary,
        "awcSuspended": awc_suspended,
        "bindings": bindings,
        "mirrorEntity": DOSING_PH_MIRROR_ENTITY,
    })


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/dosing_calibrate_start",
    vol.Required("channel_id"): cv.string,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_dosing_calibrate_start(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Press the firmware's bounded 100-revolution calibration button."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    channel = _dosing_channel_for_msg(connection, msg, config)
    if channel is None:
        return
    if dosing_engine.is_ha_timed(channel):
        # Generic adapter: no firmware button — a raw timed 30 s burst into the
        # measuring vessel (credits nothing; the run stamps make it crash-safe).
        if (channel.get("state") or {}).get("haRunEndsAt"):
            connection.send_error(msg["id"], "busy", "The pump is already running")
            return
        if not await _async_dosing_ha_run(
                hass, entry, config, msg["channel_id"], channel, 0.0,
                burst_s=DOSING_BRUSHED_CAL_RUN_S):
            connection.send_error(msg["id"], "not_bound",
                                  "Bind the pump switch entity first")
            return
        _dosing_record_event(channel, "calibrate_run", "30 s calibration burst started")
        config = await _async_save_config(hass, entry, config)
        _awc_send(connection, msg, hass, config)
        return
    if not await _async_dosing_press(hass, channel, "calibrateButton"):
        connection.send_error(msg["id"], "not_bound", "Calibrate button entity is not bound or unavailable")
        return
    _dosing_record_event(
        channel, "calibrate_run",
        "30 s calibration burst started" if dosing_engine.is_brushed(channel)
        else "100-revolution calibration run started")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/dosing_calibrate",
    vol.Required("channel_id"): cv.string,
    vol.Required("measured_ml"): vol.Coerce(float),
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_dosing_calibrate(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Store the measured 100-rev volume: derive steps/ml, append the drift-comparison
    history entry (AWC overwrites; dosing deliberately keeps history), and push the
    value to the firmware with read-back verification."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    channel = _dosing_channel_for_msg(connection, msg, config)
    if channel is None:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    cal = channel.setdefault("calibration", {})
    history = cal.setdefault("history", [])
    if dosing_engine.is_brushed(channel) or dosing_engine.is_ha_timed(channel):
        # Flow-calibrated drivers (brushed heads, generic HA switches) calibrate
        # in ml/s from the fixed 30 s burst.
        ml_per_s = dosing_engine.brushed_calibration_from_run(msg["measured_ml"])
        if ml_per_s <= 0:
            connection.send_error(msg["id"], "invalid_measurement",
                                  "Measured volume must be positive")
            return
        derived = {"mlPerS": ml_per_s, "measuredMl": round(float(msg["measured_ml"]), 1)}
        history.insert(0, {"mlPerS": ml_per_s, "measuredMl": derived["measuredMl"],
                           "calibratedAt": now_iso})
        del history[DOSING_CAL_HISTORY_MAX:]
        cal["mlPerS"] = ml_per_s
        cal["measuredMl"] = derived["measuredMl"]
        cal["calibratedAt"] = now_iso
        cal["syncedToDevice"] = False
        _dosing_record_event(channel, "calibrated",
                             f"{ml_per_s:g} ml/s from {derived['measuredMl']:g} ml in 30 s")
        config = await _async_save_config(hass, entry, config)
        _async_kick_dosing_sync(hass, entry)
        _awc_send(connection, msg, hass, config, calibration=derived)
        return
    derived = dosing_engine.calibration_from_measured(msg["measured_ml"])
    if derived is None:
        connection.send_error(msg["id"], "invalid_measurement", "Measured volume must be 1–1000 ml")
        return
    history.insert(0, {"stepsPerMl": derived["stepsPerMl"], "measuredMl": derived["measuredMl"], "calibratedAt": now_iso})
    del history[DOSING_CAL_HISTORY_MAX:]
    cal["stepsPerMl"] = derived["stepsPerMl"]
    cal["measuredMl"] = derived["measuredMl"]
    cal["calibratedAt"] = now_iso
    cal["syncedToDevice"] = False
    _dosing_record_event(channel, "calibrated", f"{derived['stepsPerMl']:.1f} steps/ml from {derived['measuredMl']:g} ml")
    config = await _async_save_config(hass, entry, config)
    _async_kick_dosing_sync(hass, entry)
    _awc_send(connection, msg, hass, config, calibration=derived)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/dosing_dose_now",
    vol.Required("channel_id"): cv.string,
    vol.Required("ml"): vol.Coerce(float),
    vol.Optional("queue"): bool,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_dosing_dose_now(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Bounded manual dose — never an unbounded ON (Apex's OFF/AUTO/ON tri-state
    caused a verified 4x overdose). The volume rides the firmware's guarded
    manual-dose script, so the same guard chain and daily accounting apply."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    channel = _dosing_channel_for_msg(connection, msg, config)
    if channel is None:
        return
    ml = float(msg["ml"])
    max_ml = min(channel.get("guards", {}).get("maxPerDoseMl") or DOSING_MAX_PER_DOSE_ML, DOSING_MAX_PER_DOSE_ML)
    if not 0 < ml <= max_ml:
        connection.send_error(msg["id"], "dose_out_of_bounds", f"Manual dose must be 0–{max_ml:g} ml")
        return
    now_local = dt_util.now()
    live = _dosing_live_state(hass, channel)
    live["awcActive"] = _dosing_awc_suspended(config)
    live["now"] = datetime.now(timezone.utc)
    reasons = [
        r for r in dosing_engine.guard_reasons(
            channel, live, now_local.hour * 60 + now_local.minute, manual=True,
            now=datetime.now(timezone.utc))
        if r["severity"] == "block" and r["code"] != "disabled"
    ]
    if reasons:
        _awc_send(connection, msg, hass, config, started=False, reasons=reasons)
        return
    spacing = config.get("dosing", {}).get("spacing", {})
    verdict = dosing_engine.spacing_verdict(
        spacing, channel.get("chemical"), _dosing_group_last_dose(hass, config),
        datetime.now(timezone.utc))
    if not verdict["ok"]:
        if msg.get("queue"):
            # Single-slot deferred dose: the 60 s tick fires it once the gap
            # clears (persisted — survives a restart). A newer queue request
            # replaces the old slot; one pending catch-up is the honest maximum.
            not_before = datetime.now(timezone.utc) + timedelta(minutes=verdict["waitMinutes"])
            config["dosing"]["spacing"]["queued"] = {
                "channelId": msg["channel_id"], "ml": ml,
                "requestedAt": datetime.now(timezone.utc).isoformat(),
                "notBefore": not_before.isoformat(),
            }
            _dosing_record_event(
                channel, "spacing_queue",
                f"{ml:g} ml queued — {verdict['conflict']} dosed too recently "
                f"(fires in ~{verdict['waitMinutes']:.0f} min)")
            config = await _async_save_config(hass, entry, config)
            _awc_send(connection, msg, hass, config, started=False, queued=True,
                      notBefore=not_before.isoformat())
            return
        _awc_send(connection, msg, hass, config, started=False, reasons=[{
            "code": "spacing", "severity": "block",
            "message": (f"{verdict['conflict']} dosed too recently — wait "
                        f"~{verdict['waitMinutes']:.0f} min (or queue it)")}])
        return
    if dosing_engine.is_ha_timed(channel):
        # Generic adapter: HA times the run itself; accounting settles when the
        # stop timer fires (the same guarded, bounded shape as firmware doses).
        if (channel.get("state") or {}).get("haRunEndsAt"):
            connection.send_error(msg["id"], "busy", "The pump is already running")
            return
        if not await _async_dosing_ha_run(
                hass, entry, config, msg["channel_id"], channel, ml):
            connection.send_error(msg["id"], "not_bound",
                                  "Bind the pump switch entity and calibrate the flow first")
            return
        _dosing_record_event(channel, "manual_dose", f"{ml:g} ml manual dose started")
        config = await _async_save_config(hass, entry, config)
        _awc_send(connection, msg, hass, config, started=True)
        return
    if not await _async_dosing_fire_bounded_dose(hass, channel, ml, cid=msg["channel_id"]):
        connection.send_error(msg["id"], "not_bound", "Manual-dose button entity is not bound or unavailable")
        return
    _dosing_record_event(channel, "manual_dose", f"{ml:g} ml manual dose requested")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config, started=True)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/dosing_prime",
    vol.Required("channel_id"): cv.string,
    vol.Optional("seconds"): vol.Coerce(float),
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_dosing_prime(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Bounded prime: the firmware button runs ~5 s per press; we press it
    ceil(seconds/5) times, capped at 30 s total."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    channel = _dosing_channel_for_msg(connection, msg, config)
    if channel is None:
        return
    seconds = min(DOSING_MANUAL_PRIME_MAX_S, max(1.0, float(msg.get("seconds") or 5.0)))
    if dosing_engine.is_ha_timed(channel):
        # Generic adapter: a raw timed burst instead of firmware button presses.
        if (channel.get("state") or {}).get("haRunEndsAt"):
            connection.send_error(msg["id"], "busy", "The pump is already running")
            return
        if not await _async_dosing_ha_run(
                hass, entry, config, msg["channel_id"], channel, 0.0, burst_s=seconds):
            connection.send_error(msg["id"], "not_bound", "Bind the pump switch entity first")
            return
        channel.setdefault("reservoir", {})["primedAt"] = datetime.now(timezone.utc).isoformat()
        _dosing_record_event(channel, "prime", f"Primed ~{seconds:.0f} s")
        config = await _async_save_config(hass, entry, config)
        _awc_send(connection, msg, hass, config)
        return
    presses = max(1, math.ceil(seconds / 5.0))
    for _ in range(presses):
        if not await _async_dosing_press(hass, channel, "primeButton"):
            connection.send_error(msg["id"], "not_bound", "Prime button entity is not bound or unavailable")
            return
    channel.setdefault("reservoir", {})["primedAt"] = datetime.now(timezone.utc).isoformat()
    _dosing_record_event(channel, "prime", f"Primed ~{presses * 5} s")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/dosing_reset_reservoir",
    vol.Required("channel_id"): cv.string,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_dosing_reset_reservoir(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """'Refilled' — reset the ledger to full and stamp refilledAt. The response nudges
    a re-prime: refill-without-reprime is a dose-integrity flag (air in the line
    silently under-doses)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    channel = _dosing_channel_for_msg(connection, msg, config)
    if channel is None:
        return
    reservoir = channel.setdefault("reservoir", {})
    before_ml = max(0.0, float(reservoir.get("remainingMl") or 0.0))
    reservoir["remainingMl"] = reservoir.get("volumeMl") or 0
    reservoir["refilledAt"] = datetime.now(timezone.utc).isoformat()
    # Consumables bridge: refilling the pump reservoir from a tracked bottle
    # debits the bottle by the transferred volume (unless the bottle IS the
    # reservoir — pump doses already debit it directly there).
    product_id = str(reservoir.get("productId") or "")
    if product_id and not reservoir.get("productIsBottle"):
        product = ((config.get("consumables") or {}).get("products") or {}).get(product_id)
        if isinstance(product, dict):
            added_ml = max(0.0, float(reservoir.get("volumeMl") or 0.0) - before_ml)
            _consumable_debit(product, added_ml, "transfer")
    runtime = hass.data.setdefault(DOMAIN, {}).setdefault(DOSING_RUNTIME, {})
    (runtime.get("channels", {}).get(msg["channel_id"]) or {}).pop("pendingReservoirMl", None)
    _dosing_record_event(channel, "refill", "Reservoir refilled — ledger reset to full")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config, reprimeRecommended=True)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/dosing_mark_refreshed",
    vol.Required("channel_id"): cv.string,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_dosing_mark_refreshed(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """'Refreshed' — stamp the live-food culture as newly mixed. The freshness clock
    restarts; the sync re-asserts the firmware enable switch if staleness had it
    held off."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    channel = _dosing_channel_for_msg(connection, msg, config)
    if channel is None:
        return
    channel.setdefault("reservoir", {})["mixedAt"] = datetime.now(timezone.utc).isoformat()
    runtime = hass.data.setdefault(DOMAIN, {}).setdefault(DOSING_RUNTIME, {})
    runtime.setdefault("channels", {}).setdefault(msg["channel_id"], {})["staleFood"] = False
    runtime.setdefault("notified", {}).pop(f"stale_{msg['channel_id']}", None)
    _dosing_record_event(channel, "refresh", "Culture refreshed — freshness clock restarted")
    config = await _async_save_config(hass, entry, config)
    _async_kick_dosing_sync(hass, entry)
    _awc_send(connection, msg, hass, config)


# --- Consumables (NPS food shelf) WebSocket API ---------------------------------------------

def _consumable_debit(product: dict[str, Any], ml: float, kind: str) -> None:
    """The single choke point for bottle ledger movement (the _awc_debit_source
    pattern): decrement remainingMl and append the usage history the runway
    forecast reads. Never raises — a bad bottle must not break a dose flush."""
    try:
        ml = max(0.0, float(ml or 0))
    except (TypeError, ValueError):
        return
    if ml <= 0:
        return
    remaining = max(0.0, float(product.get("remainingMl") or 0.0))
    product["remainingMl"] = round(max(0.0, remaining - ml), 2)
    history = product.setdefault("history", [])
    if isinstance(history, list):
        history.append({
            "at": datetime.now(timezone.utc).isoformat(),
            "ml": round(ml, 2),
            "kind": kind,
        })
        del history[:-CONSUMABLE_HISTORY_MAX]


def _consumable_for_msg(
    connection: websocket_api.ActiveConnection, msg: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any] | None:
    products = config.setdefault("consumables", {}).setdefault("products", {})
    product = products.get(msg.get("product_id"))
    if not isinstance(product, dict):
        connection.send_error(msg["id"], "unknown_product", "No such consumable product")
        return None
    return product


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/consumable_log_dose",
    vol.Required("product_id"): cv.string,
    vol.Required("ml"): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=CONSUMABLE_BOTTLE_MAX_ML)),
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_consumable_log_dose(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Manual-dose logging — the food shelf is useful with zero pumps: tap
    'dosed 5 ml' and the bottle ledger plus the usage history (which powers the
    days-left runway) both update."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    product = _consumable_for_msg(connection, msg, config)
    if product is None:
        return
    _consumable_debit(product, float(msg["ml"]), "dose")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/consumable_refill",
    vol.Required("product_id"): cv.string,
    vol.Optional("ml"): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=CONSUMABLE_BOTTLE_MAX_ML)),
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_consumable_refill(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """'New bottle' (no ml: ledger back to full, the opened-expiry clock
    restarts) or a partial top-up (ml: add volume without touching the opened
    clock — same bottle, more in it)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    product = _consumable_for_msg(connection, msg, config)
    if product is None:
        return
    bottle_ml = max(0.0, float(product.get("bottleMl") or 0.0))
    top_up = msg.get("ml")
    if top_up:
        remaining = max(0.0, float(product.get("remainingMl") or 0.0))
        cap = bottle_ml or CONSUMABLE_BOTTLE_MAX_ML
        added = min(float(top_up), max(0.0, cap - remaining))
        product["remainingMl"] = round(remaining + added, 2)
    else:
        added = bottle_ml
        product["remainingMl"] = bottle_ml
        product["openedAt"] = datetime.now(timezone.utc).isoformat()
    history = product.setdefault("history", [])
    if isinstance(history, list):
        history.append({
            "at": datetime.now(timezone.utc).isoformat(),
            "ml": round(max(0.0, added), 2),
            "kind": "refill",
        })
        del history[:-CONSUMABLE_HISTORY_MAX]
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


def _nps_hatch_log_completion(
    maintenance: dict[str, Any], task_id: str, now: datetime, note: str
) -> None:
    """Append a hatchery-sourced completion (panel entry shape) to a task."""
    completions = maintenance.setdefault("completions", {})
    if not isinstance(completions, dict):
        completions = {}
        maintenance["completions"] = completions
    entries = completions.setdefault(task_id, [])
    if not isinstance(entries, list):
        entries = []
        completions[task_id] = entries
    timestamp = now.isoformat()
    entries.insert(0, {
        "id": f"{task_id}:hatch:{timestamp}",
        "timestamp": timestamp,
        "notes": note[:500],
        "source": MAINTENANCE_SOURCE_HATCHERY,
    })
    del entries[MAINTENANCE_COMPLETIONS_MAX:]


def _nps_brine_supply(config: dict[str, Any]) -> tuple[Any, float, Any, Any]:
    """(loaded_iso, shelf_life_hours, remaining_ml, ml_per_day) for the
    next-hatch maths. A linked feed-exchange channel is the richest source
    (reservoir stamp + volume + dose rate); a hand-doser falls back to the
    hatchery's own 'Hatched & loaded' stamp with the default 24 h shelf life
    and no depletion data."""
    nps_cfg = config.get("nps") or {}
    channels = _dosing_channels(config)
    fx_channel = channels.get(str((nps_cfg.get("feedExchange") or {}).get("channelId") or ""))
    hatch_res = ((nps_cfg.get("hatchery") or {}).get("reservoir") or {})
    enriched_load = bool(hatch_res.get("lastLoadEnriched"))
    # The HUFA boost is transient (doc §10.5): 12 h warm / 48 h fridged — and
    # it decays from when the SOAK FINISHED (enrichedAt), not from the load,
    # so an evening enrich of a morning batch keeps an honest clock. Legacy
    # states without the stamp fall back to capping from the load.
    enriched_cap_h = (nps_engine.ENRICH_SHELF_H_FRIDGE if hatch_res.get("refrigerated")
                      else nps_engine.ENRICH_SHELF_H_ROOM)

    def _enriched_shelf(shelf_h: float, loaded_iso: Any) -> float:
        if not enriched_load:
            return shelf_h
        enriched_dt = _parse_datetime(hatch_res.get("enrichedAt"))
        loaded_dt = _parse_datetime(loaded_iso)
        if enriched_dt is None or loaded_dt is None:
            return min(shelf_h, enriched_cap_h)
        soak_offset_h = max(0.0, (enriched_dt - loaded_dt).total_seconds() / 3600.0)
        # NOT min()'d against the plain shelf (0.7.89): that 24 h exists because
        # unfed nauplii burn their yolk down, and a gut-loaded batch is the one
        # case where the premise is false. Capping here made the container go
        # "stale" a few hours after the soak the app itself asked for.
        return min(nps_engine.ENRICH_SHELF_MAX_H, soak_offset_h + enriched_cap_h)
    if isinstance(fx_channel, dict):
        reservoir = fx_channel.get("reservoir") or {}
        try:
            shelf_days = float(reservoir.get("shelfLifeDays"))
        except (TypeError, ValueError):
            shelf_days = 1.0
        shelf_h = shelf_days * 24.0 if shelf_days > 0 else 24.0
        shelf_h = _enriched_shelf(shelf_h, reservoir.get("mixedAt"))
        try:
            volume = float(reservoir.get("volumeMl") or 0)
        except (TypeError, ValueError):
            volume = 0.0
        remaining = reservoir.get("remainingMl") if volume > 0 else None
        rate = (fx_channel.get("schedule") or {}).get("mlPerDay")
        return reservoir.get("mixedAt"), shelf_h, remaining, rate
    # Hand-doser: the hatchery's own container ledger (v2). Shelf life follows
    # the fridge toggle; the dose rate is estimated from the hand-feed habits.
    hatchery = nps_cfg.get("hatchery") or {}
    reservoir = hatchery.get("reservoir") or {}
    shelf_h = (nps_engine.BRINE_SHELF_H_FRIDGE if reservoir.get("refrigerated")
               else nps_engine.BRINE_SHELF_H_ROOM)
    shelf_h = _enriched_shelf(shelf_h, reservoir.get("mixedAt"))
    volume = _awc_num(reservoir.get("volumeMl"), 0, 0, 50000)
    remaining = reservoir.get("remainingMl") if volume > 0 else None
    hand = hatchery.get("handFeed") or {}
    rate = (_awc_num(hand.get("defaultDoseMl"), 30, 1, 1000)
            * _awc_num(hand.get("feedsPerDay"), 2, 1, 24)) if volume > 0 else None
    return reservoir.get("mixedAt"), shelf_h, remaining, rate


def _nps_running_batches(config: dict[str, Any]) -> list[tuple[str, datetime, float]]:
    """(vessel_id, started, batch hatchHours) for every vessel mid-hatch."""
    hatchery = (config.get("nps") or {}).get("hatchery") or {}
    vessels = hatchery.get("vessels") if isinstance(hatchery.get("vessels"), dict) else {}
    running: list[tuple[str, datetime, float]] = []
    for vid, vessel in vessels.items():
        if not isinstance(vessel, dict):
            continue
        state = vessel.get("state") if isinstance(vessel.get("state"), dict) else {}
        started = _parse_datetime(state.get("hatchStartedAt"))
        if started is None:
            continue
        running.append((vid, started, _awc_num(state.get("hatchHours"), 24, 8, 48)))
    return running


def _nps_soonest_ready(config: dict[str, Any]) -> datetime | None:
    """When the next hatch ripens — the harvest reminder's anchor. The
    enrichment soak is a CONTAINER affair (0.7.70) and has its own push."""
    ends = [started + timedelta(hours=hours)
            for _vid, started, hours in _nps_running_batches(config)]
    return min(ends) if ends else None


def _nps_chain_batches(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Every batch of brine ON THE WAY, for the next-hatch chain: incubating
    vessels on their stamped clocks. Brine mid-soak is already IN the ledger —
    the container freshness/depletion covers it."""
    return [{"startedAt": started.isoformat(), "hatchHours": batch_h}
            for _vid, started, batch_h in _nps_running_batches(config)]


def _nps_container_load(
    config: dict[str, Any], hatchery: dict[str, Any], now: datetime, *, enriched: bool
) -> tuple[str, str] | None:
    """The load ledger, shared by plain harvest and enriched load: HARD stale
    gate, volume move (loadVolumeMl 0 = top-to-full, clamped at the brim),
    freshness stamp, enriched flag. Returns (code, message) on refusal."""
    reservoir = _nps_canonical_reservoir(config)
    remaining = _awc_num(reservoir.get("remainingMl"), 0, 0, 1e9)
    if remaining > 0:
        supply_loaded, shelf_h, _r, _rate = _nps_brine_supply(config)
        loaded_dt = _parse_datetime(supply_loaded)
        age_ok = (loaded_dt is not None
                  and (now - loaded_dt).total_seconds() / 3600.0 <= shelf_h)
        if not age_ok:
            return ("stale_brine",
                    "The container still holds brine past its shelf life — "
                    "discard it before loading the fresh batch.")
    volume = _awc_num(reservoir.get("volumeMl"), 0, 0, 50000)
    load = _awc_num(hatchery["reservoir"].get("loadVolumeMl"), 0, 0, 50000)
    remaining = _awc_num(reservoir.get("remainingMl"), 0, 0, 1e9)
    if volume > 0:
        reservoir["remainingMl"] = round(
            volume if load <= 0 else min(volume, remaining + load), 1)
    elif load > 0:
        reservoir["remainingMl"] = round(remaining + load, 1)
    reservoir["mixedAt"] = now.isoformat()
    hatchery["reservoir"]["lastLoadEnriched"] = bool(enriched)
    if not enriched:
        hatchery["reservoir"]["enrichedAt"] = ""  # a fresh load resets the boost stamp
    return None


def _nps_enrich_debit(config: dict[str, Any], enrichment: dict[str, Any]) -> None:
    """Debit the linked enrichment bottle by one dose (the shelf keeps count)."""
    product_id = str(enrichment.get("productId") or "")
    if not product_id:
        return
    products = (config.get("consumables") or {}).get("products") or {}
    product = products.get(product_id)
    if isinstance(product, dict):
        _consumable_debit(product, _awc_num(enrichment.get("doseMl"), 1, 0.5, 50), "dose")


def _nps_hatch_sync_reminders(config: dict[str, Any], now: datetime, event: str) -> None:
    """Keep the brine maintenance reminders honest as the hatchery is driven.

    ``started``: the 'start' chore was literally just done — log it (its next
    due lands one hatch-cycle out) and point the harvest reminder at the moment
    this hatch comes ripe (snoozed until start + hatchHours, so it pops due
    right then). ``harvested``: 'Hatched & loaded' — the harvest chore is done,
    log it. ``cancelled``: the batch was abandoned — drop a harvest snooze that
    now points at a hatch that will never come ripe.

    Only touches tasks the user has actually added (the 'Add hatchery
    reminders' button); config-only, callers save.
    """
    maintenance = config.get("maintenance")
    if not isinstance(maintenance, dict):
        return
    tasks = maintenance.get("tasks")
    if not isinstance(tasks, dict):
        return
    start_task = tasks.get(MAINTENANCE_HATCH_START_TASK_ID)
    harvest_task = tasks.get(MAINTENANCE_HATCH_HARVEST_TASK_ID)
    # Vessel-aware (v2): the harvest reminder always tracks the SOONEST-ripe
    # running batch; callers mutate vessel state BEFORE calling this.
    soonest = _nps_soonest_ready(config)
    if event == "started":
        if isinstance(start_task, dict):
            _nps_hatch_log_completion(
                maintenance, MAINTENANCE_HATCH_START_TASK_ID, now,
                "Logged automatically — hatch started from the NPS tab",
            )
            # Marking it done clears any snooze (lockstep with the panel's _completeTask).
            start_task["snoozedUntil"] = None
        if isinstance(harvest_task, dict) and soonest is not None and soonest > now:
            harvest_task["snoozedUntil"] = soonest.isoformat()
    elif event == "harvested":
        if isinstance(harvest_task, dict):
            _nps_hatch_log_completion(
                maintenance, MAINTENANCE_HATCH_HARVEST_TASK_ID, now,
                "Logged automatically — 'Hatched & loaded' on the NPS tab",
            )
            # Other vessels may still be brewing — keep tracking the next one.
            harvest_task["snoozedUntil"] = (
                soonest.isoformat() if soonest is not None and soonest > now else None
            )
        if isinstance(start_task, dict):
            # Point the "start the next hatch" reminder at the moment the
            # next-hatch maths recommends (this batch just loaded, so the clock
            # runs from now; other running batches chain it further out).
            hatch_hours = _awc_num(
                ((config.get("nps") or {}).get("hatchery") or {}).get("hatchHours"), 24, 8, 48
            )
            _loaded, shelf_h, _remaining, _rate = _nps_brine_supply(config)
            # Freshness-timed only: the reservoir is mid-reload at this exact
            # moment, so its remaining-ml is not yet trustworthy. The card's
            # live suggestion picks up depletion once the volume is reset.
            suggestion = nps_engine.next_hatch_suggestion(
                now, hatch_hours, now.isoformat(), shelf_h, None, None,
                _nps_chain_batches(config),
            )
            start_at = _parse_datetime(suggestion.get("startAt"))
            if (suggestion.get("status") in ("wait", "chained")
                    and start_at is not None and start_at > now):
                start_task["snoozedUntil"] = start_at.isoformat()
            else:
                # Overlap physics (or no window at all): the next start is due
                # NOW — a stale snooze must not suppress it.
                start_task["snoozedUntil"] = None
    elif event == "cancelled":
        # Re-anchor the harvest reminder onto whatever hatch now ripens soonest.
        if isinstance(harvest_task, dict):
            if soonest is not None and soonest > now:
                harvest_task["snoozedUntil"] = soonest.isoformat()
            else:
                snoozed = _parse_datetime(harvest_task.get("snoozedUntil"))
                if snoozed is not None and snoozed > now:
                    harvest_task["snoozedUntil"] = None


def _nps_hatch_retime_reminders(config: dict[str, Any], hours: float,
                                now: datetime) -> None:
    """Re-point the brine reminders at a NEW hatch clock.

    LOCKSTEP with the panel's ``_npsSeedHatchReminders`` cadence half: both
    chores run on the HOUR clock (``cadenceHours``), harvest carrying the
    tighter 12 h grace and start the looser 24 h. It only ever RE-TIMES tasks
    the keeper already added — a clock change must never conjure a reminder
    behind their back. The harvest snooze is re-anchored onto whatever batch
    now ripens soonest, so callers re-stamp vessels BEFORE calling.
    """
    maintenance = config.get("maintenance")
    if not isinstance(maintenance, dict):
        return
    tasks = maintenance.get("tasks")
    if not isinstance(tasks, dict):
        return
    cadence_days = max(1, round(hours / 24.0))
    for task_id, critical_h in (
        (MAINTENANCE_HATCH_START_TASK_ID, hours + 24),
        (MAINTENANCE_HATCH_HARVEST_TASK_ID, hours + 12),
    ):
        task = tasks.get(task_id)
        if not isinstance(task, dict):
            continue
        task["cadenceDays"] = cadence_days
        task["criticalAfterDays"] = cadence_days * 2
        task["cadenceHours"] = hours
        task["criticalAfterHours"] = critical_h
    harvest_task = tasks.get(MAINTENANCE_HATCH_HARVEST_TASK_ID)
    if isinstance(harvest_task, dict):
        soonest = _nps_soonest_ready(config)
        harvest_task["snoozedUntil"] = (
            soonest.isoformat() if soonest is not None and soonest > now else None)


def _nps_hatch_clock_follow(previous: Any, incoming: Any) -> None:
    """A saved hatch-clock change carries the batch already running with it.

    Reece hit this three times (0.7.80). Per-batch stamping is right — two
    vessels can genuinely run different egg types on different clocks — but on
    its own it strands a countdown quoting a number the keeper has already
    corrected, with no way back. So EVERY route that changes the clock (the
    learned-clock chip, the settings field, a config import) now moves the
    batches that are still incubating on the same egg type.

    Left alone, deliberately: a batch already ripe (no arithmetic un-hatches
    nauplii) and a batch on a different egg type. Both explain themselves on
    the tile, and both have an explicit per-vessel override.
    """
    if not isinstance(previous, dict) or not isinstance(incoming, dict):
        return
    was = ((previous.get("nps") or {}).get("hatchery") or {})
    now_cfg = ((incoming.get("nps") or {}).get("hatchery") or {})
    if not isinstance(was, dict) or not isinstance(now_cfg, dict):
        return
    old_h = _awc_num(was.get("hatchHours"), 0, 0, 48)
    new_h = _awc_num(now_cfg.get("hatchHours"), 0, 0, 48)
    if not new_h or not old_h or new_h == old_h:
        return
    egg = now_cfg.get("eggType")
    vessels = now_cfg.get("vessels") if isinstance(now_cfg.get("vessels"), dict) else {}
    now = datetime.now(timezone.utc)
    for vessel in vessels.values():
        if not isinstance(vessel, dict):
            continue
        state = vessel.get("state") if isinstance(vessel.get("state"), dict) else None
        if not isinstance(state, dict):
            continue
        started = _parse_datetime(state.get("hatchStartedAt"))
        if started is None:
            continue
        stamped = _awc_num(state.get("hatchHours"), old_h, 8, 48)
        if (now - started).total_seconds() / 3600.0 >= stamped:
            continue                       # ripe already — it keeps its result
        if state.get("eggType") and state.get("eggType") != egg:
            continue                       # a different animal on a different clock
        state["hatchHours"] = new_h
        state["readyNotifiedAt"] = ""
    _nps_hatch_retime_reminders(incoming, new_h, now)


def _nps_hatchery_v2(config: dict[str, Any]) -> dict[str, Any]:
    """Handlers may run against a config saved by an older version — run the
    hatchery block through the v2 normaliser (migration included) and write it
    back so every caller sees vessels/reservoir/history."""
    nps_cfg = config.setdefault("nps", {})
    nps_cfg["hatchery"] = _normalise_hatchery(
        nps_cfg.get("hatchery"), bool(nps_cfg.get("enabled", False)))
    return nps_cfg["hatchery"]


def _nps_canonical_reservoir(config: dict[str, Any]) -> dict[str, Any]:
    """The brine container the system should ledger against: the linked
    feed-exchange channel's reservoir when a pump is bound, else the
    hatchery's own (hand-dose) container."""
    channels = _dosing_channels(config)
    fx_channel = channels.get(
        str(((config.get("nps") or {}).get("feedExchange") or {}).get("channelId") or ""))
    if isinstance(fx_channel, dict):
        return fx_channel.setdefault("reservoir", {})
    # Reuse an already-migrated hatchery dict — re-running the normaliser here
    # would REPLACE it and orphan a caller's reference mid-mutation.
    hatchery = (config.get("nps") or {}).get("hatchery")
    if not (isinstance(hatchery, dict) and isinstance(hatchery.get("reservoir"), dict)):
        hatchery = _nps_hatchery_v2(config)
    return hatchery["reservoir"]


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/nps_hatch_start",
    vol.Optional("vessel_id"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_nps_hatch_start(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Stamp the incubation clock: cysts just went into a hatcher. v2: picks
    the first idle vessel (or the requested one) and stamps the CURRENT egg
    type + hours into the batch — later settings edits never rewrite a running
    countdown."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    hatchery = _nps_hatchery_v2(config)
    vessels = hatchery["vessels"]
    requested = str(msg.get("vessel_id") or "")
    if requested and requested not in vessels:
        connection.send_error(msg["id"], "unknown_vessel", f"No hatchery '{requested}'")
        return
    if requested and vessels[requested]["state"]["hatchStartedAt"]:
        connection.send_error(msg["id"], "vessel_busy",
                              f"{vessels[requested]['name']} is already mid-hatch")
        return
    target_id = requested or next(
        (vid for vid in sorted(vessels) if not vessels[vid]["state"]["hatchStartedAt"]), "")
    if not target_id:
        connection.send_error(msg["id"], "all_busy",
                              "Every hatchery is mid-hatch — harvest or cancel one first")
        return
    now = datetime.now(timezone.utc)
    state = vessels[target_id]["state"]
    state["hatchStartedAt"] = now.isoformat()
    state["eggType"] = hatchery["eggType"]
    state["hatchHours"] = hatchery["hatchHours"]
    state["readyNotifiedAt"] = ""
    _nps_hatch_sync_reminders(config, now, "started")
    _append_activity(
        config,
        f"Brine hatch started in {vessels[target_id]['name']} — the incubation clock is running",
        "control")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/nps_hatch_clock",
    vol.Optional("hours"): vol.Coerce(float),
    vol.Optional("vessel_id"): str,
    vol.Optional("restamp"): bool,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_nps_hatch_clock(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Set the hatch clock — the learned-hours advisory's one-tap apply.

    Backend-authoritative on purpose (0.7.79, Reece's live catch): the clock
    number is only a third of the job. The batch already incubating carries
    its own stamped countdown, and the harvest reminder carries a cadence and
    a snooze — write only the config value and the whole page keeps quoting
    the old hours. One command moves all three, fetch-fresh so it can never
    write back a stale snapshot of the ledger.

    Re-stamping rule: a batch still INCUBATING moves onto the new clock — the
    learned number is a better estimate of the very process already under way
    — but a batch already ready/overdue is left alone. Those nauplii have
    hatched, and no arithmetic un-hatches them.
    """
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    hatchery = _nps_hatchery_v2(config)
    previous = hatchery["hatchHours"]
    # No hours at all means "bring everything onto the clock we already have"
    # — the align button, for a batch stranded on an older stamp.
    hours = float(round(_awc_num(msg.get("hours"), previous, 8, 48)))
    hatchery["hatchHours"] = hours
    now = datetime.now(timezone.utc)
    restamp = bool(msg.get("restamp", True))
    only = str(msg.get("vessel_id") or "")
    if only and only not in hatchery["vessels"]:
        connection.send_error(msg["id"], "unknown_vessel", f"No hatchery '{only}'")
        return
    moved: list[dict[str, Any]] = []
    kept: list[str] = []
    for vid in sorted(hatchery["vessels"]):
        if only and vid != only:
            continue
        vessel = hatchery["vessels"][vid]
        state = vessel["state"]
        started = _parse_datetime(state.get("hatchStartedAt"))
        if started is None:
            continue
        name = str(vessel.get("name") or vid)
        elapsed = (now - started).total_seconds() / 3600.0
        ripe = elapsed >= _awc_num(state.get("hatchHours"), previous, 8, 48)
        # A sweeping change follows the egg type it was computed for: moving a
        # 36 h standard batch onto an 18 h decapsulated clock would be wrong.
        # Naming a vessel is an explicit override — move THAT batch.
        wrong_egg = not only and state.get("eggType") != hatchery["eggType"]
        if not restamp or ripe or wrong_egg:
            kept.append(name)
            continue
        state["hatchHours"] = hours
        # Re-arm the ready push: a longer clock must not stay "already told
        # you", and a shorter one that lands the batch ripe right now should
        # say so on the next tick.
        state["readyNotifiedAt"] = ""
        moved.append({"id": vid, "name": name,
                      "hoursLeft": round(max(hours - elapsed, 0.0), 1)})
    _nps_hatch_retime_reminders(config, hours, now)
    if hours != previous or moved:
        _append_activity(
            config,
            f"Hatch clock set to {hours:g} h"
            + (f" — {', '.join(b['name'] for b in moved)} moved onto it" if moved else ""),
            "control")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config,
              hours=hours, previous=previous, restamped=moved, kept=kept)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/nps_hatch_cancel",
    vol.Optional("harvested"): bool,
    vol.Optional("vessel_id"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_nps_hatch_cancel(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Clear a batch's clock — harvested (the normal end, chained after
    'Hatched & loaded') or abandoned. Harvesting is allowed EARLY (research:
    instar I at ~18 h is the most nutritious harvest) and v2 does the ledger
    work: HARD stale gate (never load fresh brine onto stale — discard first),
    move the load volume into the canonical container, stamp its freshness
    clock, and append the batch to the hatch history (planned vs actual hours
    feeds the learned-clock advisory)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    hatchery = _nps_hatchery_v2(config)
    vessels = hatchery["vessels"]
    now = datetime.now(timezone.utc)
    harvested = bool(msg.get("harvested"))
    requested = str(msg.get("vessel_id") or "")
    if requested and requested not in vessels:
        connection.send_error(msg["id"], "unknown_vessel", f"No hatchery '{requested}'")
        return
    running = _nps_running_batches(config)
    target_id = requested
    if not target_id and running:
        # Prefer the batch furthest through its clock (a ready one over a
        # half-done one); ties break on the oldest start.
        def _progress(item: tuple[str, datetime, float]) -> float:
            _vid, started, hours = item
            return (now - started).total_seconds() / 3600.0 / max(hours, 1.0)
        target_id = max(running, key=_progress)[0]
    if harvested:
        # HARD GATE (Reece, locked): stale brine never gets fresh brine poured
        # onto it — the container must be discarded first.
        error = _nps_container_load(config, hatchery, now, enriched=False)
        if error is not None:
            connection.send_error(msg["id"], error[0], error[1])
            return
        # The batch's story: planned vs actual hours feeds the learned clock.
        if target_id and vessels.get(target_id, {}).get("state", {}).get("hatchStartedAt"):
            state = vessels[target_id]["state"]
            started = _parse_datetime(state.get("hatchStartedAt"))
            actual_h = ((now - started).total_seconds() / 3600.0
                        if started is not None else 0.0)
            hatchery["history"].insert(0, {
                "vesselId": target_id,
                "startedAt": state.get("hatchStartedAt") or "",
                "harvestedAt": now.isoformat(),
                "plannedHours": _awc_num(state.get("hatchHours"), 24, 8, 48),
                "actualHours": round(actual_h, 1),
                "eggType": str(state.get("eggType") or hatchery["eggType"]),
            })
            del hatchery["history"][nps_engine.HATCH_HISTORY_MAX:]
    if target_id and target_id in vessels:
        vessels[target_id]["state"]["hatchStartedAt"] = ""
        vessels[target_id]["state"]["readyNotifiedAt"] = ""
    _nps_hatch_sync_reminders(config, now, "harvested" if harvested else "cancelled")
    if harvested:
        name = vessels.get(target_id, {}).get("name") or "the hatchery"
        _append_activity(config, f"Brine harvested from {name} — container loaded", "control")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/nps_hatch_enrich",
    vol.Optional("vessel_id"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_nps_hatch_enrich(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Enrich the LOADED brine (container action, Reece's mesh flow): the
    Selcon goes into the holding vessel, and any hatch running in a cone is
    NOT touched. The instar II dose reminder anchors on the BATCH's load
    stamp — an evening enrich of a morning batch is due immediately; an
    enrich right after loading waits out the molt. Debits happen at the
    dose, not at engage (unless the delay is 0 and the batch is old enough)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    hatchery = _nps_hatchery_v2(config)
    enrichment = hatchery["enrichment"]
    if enrichment["state"]["startedAt"]:
        connection.send_error(msg["id"], "enrich_busy",
                              "A soak is already running — finish or cancel it first")
        return
    reservoir = _nps_canonical_reservoir(config)
    remaining = _awc_num(reservoir.get("remainingMl"), 0, 0, 1e9)
    loaded_iso = str(reservoir.get("mixedAt") or "")
    if remaining <= 0 or not loaded_iso:
        connection.send_error(msg["id"], "no_brine",
                              "Nothing to enrich — the container holds no loaded brine")
        return
    now = datetime.now(timezone.utc)
    # Per-batch stamps — editing settings mid-soak never moves a running soak.
    delay_h = enrichment["doseDelayH"]
    loaded_dt = _parse_datetime(loaded_iso)
    batch_age_h = ((now - loaded_dt).total_seconds() / 3600.0
                   if loaded_dt is not None else 0.0)
    dose_now = delay_h <= 0 or batch_age_h >= delay_h
    enrichment["state"] = {
        "startedAt": now.isoformat(),
        "sourceVesselId": "",
        "eggType": hatchery["eggType"],
        "plannedHatchHours": 0,
        "actualHatchHours": round(batch_age_h, 1),
        "enrichHours": enrichment["hours"],
        "doseDelayH": delay_h,
        "batchLoadedAt": loaded_iso,
        # Old enough already (mouths open) -> the dose goes in right now.
        # Young batch -> hold in clean water; the dose push fires when the
        # BATCH crosses the molt and nps_enrich_dose logs it.
        "firstDoseAt": now.isoformat() if dose_now else "",
        "secondDoseAt": "", "readyNotifiedAt": "",
        "firstDoseNotifiedAt": "", "secondDoseNotifiedAt": "",
    }
    if dose_now:
        _nps_enrich_debit(config, enrichment)
    _append_activity(
        config,
        (f"Enrichment engaged — batch is {batch_age_h:.1f} h old, dose in now; "
         f"{enrichment['hours']:g} h soak running")
        if dose_now else
        (f"Enrichment engaged — batch is {batch_age_h:.1f} h old, holding until "
         f"the instar II dose at +{delay_h:g} h from load"),
        "control")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({vol.Required("type"): "openreef/nps_enrich_loaded"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_nps_enrich_loaded(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Soak done (container semantics): nothing moves — the gut-loaded brine
    is already in the holding vessel. Stamp the boost (its decay clock runs
    from HERE — DHA halves within a day warm) and stand the soak down. A
    second mesh cycle before feed-out is the optional rinse."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    hatchery = _nps_hatchery_v2(config)
    state = hatchery["enrichment"]["state"]
    if _parse_datetime(state.get("startedAt")) is None:
        connection.send_error(msg["id"], "no_enrichment", "Nothing is enriching")
        return
    now = datetime.now(timezone.utc)
    hatchery["reservoir"]["lastLoadEnriched"] = True
    hatchery["reservoir"]["enrichedAt"] = now.isoformat()
    hatchery["enrichment"]["state"] = {
        "startedAt": "", "sourceVesselId": "", "eggType": "",
        "plannedHatchHours": 0, "actualHatchHours": 0, "enrichHours": 0,
        "doseDelayH": 0, "batchLoadedAt": "", "firstDoseAt": "", "secondDoseAt": "",
        "readyNotifiedAt": "", "firstDoseNotifiedAt": "", "secondDoseNotifiedAt": "",
    }
    _append_activity(config, "Soak done — gut-loaded brine in the vessel; the boost "
                             "clock runs from now (mesh-rinse before feed-out if you like)",
                     "control")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({vol.Required("type"): "openreef/nps_enrich_cancel"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_nps_enrich_cancel(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Abandon the soak — the brine stays in the vessel, just un-soaked."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    hatchery = _nps_hatchery_v2(config)
    hatchery["enrichment"]["state"] = {
        "startedAt": "", "sourceVesselId": "", "eggType": "",
        "plannedHatchHours": 0, "actualHatchHours": 0, "enrichHours": 0,
        "doseDelayH": 0, "batchLoadedAt": "", "firstDoseAt": "", "secondDoseAt": "",
        "readyNotifiedAt": "", "firstDoseNotifiedAt": "", "secondDoseNotifiedAt": "",
    }
    _append_activity(config, "Enrichment abandoned — the soak stands down", "control")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({vol.Required("type"): "openreef/nps_enrich_dose"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_nps_enrich_dose(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Log the FIRST enrichment dose (delayed protocols): the batch crossed
    instar II, the Selcon goes in now — debit the bottle and anchor the soak
    clock proper here."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    hatchery = _nps_hatchery_v2(config)
    state = hatchery["enrichment"]["state"]
    if not state.get("startedAt"):
        connection.send_error(msg["id"], "no_enrichment", "Nothing is enriching")
        return
    if state.get("firstDoseAt"):
        connection.send_error(msg["id"], "already_dosed", "The dose is already logged")
        return
    _nps_enrich_debit(config, hatchery["enrichment"])
    state["firstDoseAt"] = datetime.now(timezone.utc).isoformat()
    _append_activity(config, "Enrichment dose added — the soak proper begins", "control")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({vol.Required("type"): "openreef/nps_enrich_second_dose"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_nps_enrich_second_dose(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Log the INVE-style top-up, 10 h after the FIRST dose: debits another
    dose and stamps the soak so the reminder stands down."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    hatchery = _nps_hatchery_v2(config)
    state = hatchery["enrichment"]["state"]
    if not state.get("startedAt"):
        connection.send_error(msg["id"], "no_enrichment", "Nothing is enriching")
        return
    if not state.get("firstDoseAt"):
        connection.send_error(msg["id"], "no_first_dose",
                              "Add the first dose before the top-up")
        return
    if state.get("secondDoseAt"):
        connection.send_error(msg["id"], "already_dosed", "The top-up is already logged")
        return
    _nps_enrich_debit(config, hatchery["enrichment"])
    state["secondDoseAt"] = datetime.now(timezone.utc).isoformat()
    _append_activity(config, "Enrichment top-up dosed", "control")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({vol.Required("type"): "openreef/nps_reservoir_discard"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_nps_reservoir_discard(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Dump the old brine: zero the canonical container and clear its clock.
    The stale hard gate sends people here before a fresh load."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    reservoir = _nps_canonical_reservoir(config)
    reservoir["remainingMl"] = 0
    reservoir["mixedAt"] = ""
    _append_activity(config, "Old brine discarded — the container is empty", "control")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/nps_hand_feed",
    vol.Optional("ml"): vol.Any(int, float),
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_nps_hand_feed(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """One-tap hand-feed ledger: debit the canonical brine container and log
    the hand-feed reminder done (if the user added it). Default dose comes
    from hatchery.handFeed.defaultDoseMl."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    hatchery = _nps_hatchery_v2(config)
    ml = _awc_num(msg.get("ml"), hatchery["handFeed"]["defaultDoseMl"], 0.5, 1000)
    reservoir = _nps_canonical_reservoir(config)
    remaining = _awc_num(reservoir.get("remainingMl"), 0, 0, 1e9)
    reservoir["remainingMl"] = round(max(0.0, remaining - ml), 1)
    now = datetime.now(timezone.utc)
    maintenance = config.get("maintenance")
    if isinstance(maintenance, dict):
        tasks = maintenance.get("tasks")
        feed_task = tasks.get(MAINTENANCE_HAND_FEED_TASK_ID) if isinstance(tasks, dict) else None
        if isinstance(feed_task, dict):
            _nps_hatch_log_completion(
                maintenance, MAINTENANCE_HAND_FEED_TASK_ID, now,
                f"Logged automatically — hand-fed {ml:g} ml from the NPS tab")
            feed_task["snoozedUntil"] = None
    _append_activity(config, f"Hand-fed {ml:g} ml of live brine", "control")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({vol.Required("type"): "openreef/nps_summary"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_nps_summary(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The food-shelf snapshot the NPS tab polls: per-bottle states (runway,
    low, expiry) are computed backend-side by nps.py so the panel never
    re-implements the maths (the maintenance lockstep lesson). Also carries the
    seeded product library the add-product picker offers."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    now_utc = datetime.now(timezone.utc)
    products = (config.get("consumables") or {}).get("products") or {}
    channels = _dosing_channels(config)
    fx = (config.get("nps") or {}).get("feedExchange") or {}
    fx_channel = channels.get(str(fx.get("channelId") or ""))
    freshness = prime = None
    hatchery_cfg = _nps_hatchery_v2(config)  # migration-safe v2 view
    reservoir_cfg = hatchery_cfg["reservoir"]
    supply_loaded, supply_shelf_h, supply_remaining, supply_rate = _nps_brine_supply(config)
    # An enriched load is on the BOOST clock, not the yolk clock (0.7.89).
    enriched_at = (str(reservoir_cfg.get("enrichedAt") or "")
                   if reservoir_cfg.get("lastLoadEnriched") else "")
    fridged = bool(reservoir_cfg.get("refrigerated"))
    if isinstance(fx_channel, dict):
        reservoir = fx_channel.get("reservoir") or {}
        if reservoir_cfg.get("lastLoadEnriched"):
            # The enriched cap outranks the channel's configured shelf life.
            freshness = dosing_engine.freshness_state(
                {"mixedAt": reservoir.get("mixedAt"),
                 "shelfLifeDays": supply_shelf_h / 24.0}, now_utc)
        else:
            freshness = dosing_engine.freshness_state(reservoir, now_utc)
        prime = nps_engine.hatch_prime_state(
            reservoir.get("mixedAt"), now_utc, enriched_at, fridged)
    else:
        # Hand-dosers track brine too: the hatchery's own container stamp
        # drives the same freshness/prime clocks (shelf life follows the
        # fridge toggle, tightened for an enriched load). No stamp yet ->
        # prime "unknown", freshness withheld (no dosing to block).
        loaded_at = reservoir_cfg.get("mixedAt") or ""
        prime = nps_engine.hatch_prime_state(
            loaded_at, now_utc, enriched_at, fridged)
        if loaded_at:
            freshness = dosing_engine.freshness_state(
                {"mixedAt": loaded_at, "shelfLifeDays": supply_shelf_h / 24.0}, now_utc)
    next_hatch = nps_engine.next_hatch_suggestion(
        now_utc,
        hatchery_cfg["hatchHours"],
        supply_loaded, supply_shelf_h, supply_remaining, supply_rate,
        # Per-batch clocks (0.7.62) + the enriching pseudo-batch (§10): brine
        # on the way is brine on the way, whatever vessel it sits in.
        _nps_chain_batches(config),
    )
    # Per-vessel clocks + the "primary" one the compact surfaces show.
    vessels_payload = []
    status_rank = {"overdue": 3, "ready": 2, "incubating": 1, "none": 0}
    primary_state: dict[str, Any] = {"status": "none", "hoursElapsed": None,
                                     "hoursLeft": None, "percent": None}
    idle_vessel = ""
    for vid in sorted(hatchery_cfg["vessels"]):
        vessel = hatchery_cfg["vessels"][vid]
        v_state = vessel["state"]
        hatch_st = nps_engine.hatch_state(
            v_state["hatchStartedAt"], v_state["hatchHours"], now_utc)
        if not v_state["hatchStartedAt"] and not idle_vessel:
            idle_vessel = vid
        vessels_payload.append({
            "id": vid, "name": vessel["name"], "volumeL": vessel["volumeL"],
            "eggType": v_state["eggType"], "hatchHours": v_state["hatchHours"],
            "state": hatch_st,
            "guide": nps_engine.cyst_dose_guide(vessel["volumeL"]),
        })
        if status_rank.get(hatch_st["status"], 0) > status_rank.get(primary_state["status"], 0):
            primary_state = hatch_st
    # Temperature advisory (never moves the clock) from the optional sensor.
    temp_advice = {"available": False, "expectedHours": None, "factor": None, "warm": False}
    instar_advice = nps_engine.instar_two_delay_hours(None)
    temp_entity = hatchery_cfg.get("tempEntity") or ""
    if temp_entity:
        temp_state = hass.states.get(temp_entity)
        try:
            temp_c = float(temp_state.state) if temp_state is not None else None
        except (TypeError, ValueError):
            temp_c = None
        if temp_c is not None:
            temp_advice = nps_engine.expected_hatch_hours(hatchery_cfg["hatchHours"], temp_c)
            temp_advice["tempC"] = round(temp_c, 1)
            # The molt is as temperature-driven as the hatch (0.7.89).
            instar_advice = nps_engine.instar_two_delay_hours(temp_c)
    # Container payload: the CANONICAL reservoir (pump channel's when linked).
    if isinstance(fx_channel, dict):
        ch_res = fx_channel.get("reservoir") or {}
        container = {
            "canonical": "channel",
            "volumeMl": _awc_num(ch_res.get("volumeMl"), 0, 0, 50000),
            "remainingMl": _awc_num(ch_res.get("remainingMl"), 0, 0, 50000),
            "mixedAt": str(ch_res.get("mixedAt") or ""),
        }
    else:
        container = {"canonical": "hatchery", **{
            k: reservoir_cfg[k] for k in
            ("volumeMl", "remainingMl", "mixedAt")}}
    container.update({
        "loadVolumeMl": reservoir_cfg["loadVolumeMl"],
        "refrigerated": bool(reservoir_cfg["refrigerated"]),
        "lastLoadEnriched": bool(reservoir_cfg["lastLoadEnriched"]),
        "shelfHours": round(supply_shelf_h, 1),
        "freshness": freshness,
    })
    connection.send_result(msg["id"], {
        "enabled": bool((config.get("nps") or {}).get("enabled")),
        "shelf": nps_engine.shelf_summary(products, now_utc),
        "library": [dict(item) for item in nps_engine.PRODUCT_LIBRARY],
        "categories": {key: nps_engine.category_label(key) for key in CONSUMABLE_CATEGORIES},
        # Feed-exchange (Stage B): the hatchery card's whole state — backend
        # computed (lockstep rule), including the brine freshness clock and the
        # 24 h nutritional-prime countdown of the linked live-food channel.
        "feedExchange": {
            "enabled": bool(fx.get("enabled")),
            "channelId": str(fx.get("channelId") or ""),
            "channelName": (fx_channel or {}).get("name") if isinstance(fx_channel, dict) else None,
            "minDrainMl": _awc_num(fx.get("minDrainMl"), 150, 10, 5000),
            "maxOwedMl": _awc_num(fx.get("maxOwedMl"), 2000, 100, 20000),
            "state": dict(fx.get("state") or {}),
            "freshness": freshness,
            "prime": prime,
            "drainActive": hass.data.get(DOMAIN, {}).get(NPS_DRAIN_UNSUB) is not None,
        },
        "foodChannels": [
            {"id": cid, "name": ch.get("name") or cid, "chemical": ch.get("chemical")}
            for cid, ch in sorted(channels.items())
            if isinstance(ch, dict) and ch.get("chemical") in ("livefood", "food")
        ],
        # Hatchery (v2): per-vessel clocks, the canonical container ledger,
        # and the daily-driver advice (nextHatch + learned clock + temp).
        "hatchery": {
            "enabled": bool(hatchery_cfg["enabled"]),
            "eggType": hatchery_cfg["eggType"],
            "hatchHours": hatchery_cfg["hatchHours"],
            "eggTypes": [dict(e) for e in nps_engine.EGG_TYPES],
            "history": [dict(item) for item in hatchery_cfg["history"][:10]],
            "vessels": vessels_payload,
            "idleVessel": idle_vessel,
            "vesselsNeeded": nps_engine.vessels_needed(
                hatchery_cfg["hatchHours"], supply_shelf_h),
            "state": primary_state,
            "reservoir": container,
            "enrichment": {
                "hours": hatchery_cfg["enrichment"]["hours"],
                "doseMl": hatchery_cfg["enrichment"]["doseMl"],
                "doseDelayH": hatchery_cfg["enrichment"]["doseDelayH"],
                "batchDoseDelayH": hatchery_cfg["enrichment"]["state"]["doseDelayH"],
                "productId": hatchery_cfg["enrichment"]["productId"],
                "productName": (products.get(hatchery_cfg["enrichment"]["productId"]) or {}).get("name")
                    if isinstance(products.get(hatchery_cfg["enrichment"]["productId"]), dict) else None,
                "splitDose": bool(hatchery_cfg["enrichment"]["splitDose"]),
                "sourceVesselId": hatchery_cfg["enrichment"]["state"]["sourceVesselId"],
                "state": nps_engine.enrich_state(
                    hatchery_cfg["enrichment"]["state"]["startedAt"],
                    hatchery_cfg["enrichment"]["state"]["enrichHours"],
                    bool(hatchery_cfg["enrichment"]["splitDose"]),
                    hatchery_cfg["enrichment"]["state"]["secondDoseAt"],
                    now_utc,
                    hatchery_cfg["enrichment"]["state"]["firstDoseAt"],
                    hatchery_cfg["enrichment"]["state"]["doseDelayH"],
                    hatchery_cfg["enrichment"]["state"]["batchLoadedAt"]),
            },
            "handFeed": dict(hatchery_cfg["handFeed"]),
            "learned": nps_engine.learned_hatch_hours(
                hatchery_cfg["history"], hatchery_cfg["eggType"]),
            "temp": temp_advice,
            "instar": instar_advice,
            "vesselPresets": [dict(p) for p in nps_engine.HATCH_VESSEL_PRESETS],
            "nextHatch": next_hatch,
        },
        # Species plans + nutrient budget (Stage D) — compiled backend-side.
        "speciesLibrary": [dict(s) for s in nps_engine.SPECIES_LIBRARY],
        "speciesPlan": nps_engine.compile_feed_plan(
            list((config.get("nps") or {}).get("species") or []), products, channels),
        "budget": nps_engine.nutrient_budget(
            products, now_utc, _awc_effective_tank_l(config),
            awc_engine.daily_equivalent_litres(
                (_awc_cfg(config) or {}).get("schedule") or {},
                _awc_effective_tank_l(config))
            if (_awc_cfg(config) or {}).get("enabled")
            and ((_awc_cfg(config) or {}).get("schedule") or {}).get("enabled") else 0.0),
    })


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/consumable_delete",
    vol.Required("product_id"): cv.string,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_consumable_delete(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Remove a product from the shelf. Any dosing-channel reservoir pointing at
    it keeps its own ledger — the productId link just dangles harmlessly until
    re-pointed (the delete-channel precedent)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    products = config.setdefault("consumables", {}).setdefault("products", {})
    if msg.get("product_id") not in products:
        connection.send_error(msg["id"], "unknown_product", "No such consumable product")
        return
    products.pop(msg["product_id"], None)
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/dosing_reset_tube",
    vol.Required("channel_id"): cv.string,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_dosing_reset_tube(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Tube replaced: zero the wear odometer (the awc_reset_ledger template)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    channel = _dosing_channel_for_msg(connection, msg, config)
    if channel is None:
        return
    wear = channel.setdefault("wear", {})
    wear["runSeconds"] = 0.0
    wear["doseCount"] = 0
    wear["tubeInstalledAt"] = datetime.now(timezone.utc).isoformat()
    runtime = hass.data.setdefault(DOMAIN, {}).setdefault(DOSING_RUNTIME, {})
    rt = runtime.get("channels", {}).get(msg["channel_id"]) or {}
    rt.pop("pendingRunSeconds", None)
    rt.pop("pendingDoses", None)
    _dosing_record_event(channel, "tube_reset", "Tube replaced — wear counter reset")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/dosing_respread_missed",
    vol.Required("channel_id"): cv.string,
    vol.Optional("skip"): bool,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_dosing_respread_missed(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The ask-first missed-dose decision: skip clears the state; respread tightens
    today's interval under the caps (kalk always resolves to skip — never a catch-up
    bolus). Missed volume is NEVER re-dosed automatically."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    channel = _dosing_channel_for_msg(connection, msg, config)
    if channel is None:
        return
    state = channel.setdefault("state", {})
    missed_ml = state.get("missedMl") or 0.0
    if msg.get("skip"):
        state["missedMl"] = 0.0
        state["missedSince"] = ""
        _dosing_record_event(channel, "missed_skipped", f"{missed_ml:.1f} ml missed volume skipped")
        config = await _async_save_config(hass, entry, config)
        _awc_send(connection, msg, hass, config, applied=False, skipped=True)
        return
    now_local = dt_util.now()
    now_minutes = now_local.hour * 60 + now_local.minute
    live = _dosing_live_state(hass, channel)
    if not live.get("dosedSensorTrusted"):
        # Without a readable dosed-today sensor the cap preflight would run
        # against 0.0 — refusing beats re-dosing already-delivered volume (R33).
        _awc_send(connection, msg, hass, config, applied=False,
                  reason="Dosed-today sensor is unavailable — re-spread refused until OpenReef can verify what's been delivered.")
        return
    compiled = dosing_engine.compile_schedule(channel, _dosing_lighting_off_window(config, now_local), now_local)
    plan_result = dosing_engine.respread_plan(channel, compiled["plan"], missed_ml, now_minutes, live["dosedTodayMl"])
    if plan_result.get("recommendation") != "respread":
        state["missedMl"] = 0.0
        state["missedSince"] = ""
        _dosing_record_event(channel, "missed_skipped", plan_result.get("reason", "Respread not possible"))
        config = await _async_save_config(hass, entry, config)
        _awc_send(connection, msg, hass, config, applied=False, reason=plan_result.get("reason", ""))
        return
    # Record the plan this respread was computed AGAINST: a later schedule edit
    # that changes these base values self-invalidates the override (R17).
    base_channel = {**channel, "state": {**state, "respread": {}}}
    base_plan = dosing_engine.compile_schedule(
        base_channel, _dosing_lighting_off_window(config, now_local), now_local
    )["plan"]
    state["respread"] = {
        "date": now_local.date().isoformat(),
        "dayIntervalMin": plan_result["dayIntervalMin"],
        "nightIntervalMin": plan_result["nightIntervalMin"],
        "basePerDoseMl": base_plan["perDoseMl"],
        "baseDayIntervalMin": base_plan["dayIntervalMin"],
        "baseNightIntervalMin": base_plan["nightIntervalMin"],
    }
    state["missedMl"] = 0.0
    state["missedSince"] = ""
    _dosing_record_event(channel, "missed_respread", plan_result.get("note", "Missed volume re-spread"))
    config = await _async_save_config(hass, entry, config)
    _async_kick_dosing_sync(hass, entry)
    _awc_send(connection, msg, hass, config, applied=True, note=plan_result.get("note", ""))


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/dosing_acknowledge",
    vol.Required("channel_id"): cv.string,
    vol.Required("kind"): cv.string,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_dosing_acknowledge(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Explicit user acknowledgments (currently: 'ph_missing' — running kalk with no
    pH failsafe, schedule and volume caps as the only protection)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    channel = _dosing_channel_for_msg(connection, msg, config)
    if channel is None:
        return
    if msg["kind"] != "ph_missing":
        connection.send_error(msg["id"], "unknown_kind", "Unknown acknowledgment kind")
        return
    channel.setdefault("guards", {})["phMissingAcknowledged"] = True
    _dosing_record_event(channel, "ack_no_ph", "Acknowledged: no pH failsafe configured")
    config = await _async_save_config(hass, entry, config)
    _async_kick_dosing_sync(hass, entry)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/dosing_sync_now",
    vol.Optional("channel_id"): cv.string,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_dosing_sync_now(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    await _async_dosing_sync_pass(hass, entry, msg.get("channel_id"))
    config = _config_from_entry(entry)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/dosing_suspend",
    vol.Required("channel_id"): cv.string,
    vol.Optional("hours"): vol.Coerce(float),
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_dosing_suspend(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Panic lockout: flip the firmware HA-suspend switch (never the master enable —
    user intent and automation must not be conflated) for up to 24 h. The firmware's
    own auto-expiry backstops a dead HA."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    channel = _dosing_channel_for_msg(connection, msg, config)
    if channel is None:
        return
    hours = min(float(DOSING_SUSPEND_MAX_HOURS), max(1.0, float(msg.get("hours") or 24.0)))
    channel.setdefault("state", {})["suspendedUntil"] = (
        datetime.now(timezone.utc) + timedelta(hours=hours)
    ).isoformat()
    ent = channel.get("driver", {}).get("entities", {}).get("haSuspendSwitch")
    if ent:
        await hass.services.async_call("switch", "turn_on", {ATTR_ENTITY_ID: ent}, blocking=True)
    _dosing_record_event(channel, "suspend", f"Dosing lockout for {hours:g} h")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/dosing_resume",
    vol.Required("channel_id"): cv.string,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_dosing_resume(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    channel = _dosing_channel_for_msg(connection, msg, config)
    if channel is None:
        return
    channel.setdefault("state", {})["suspendedUntil"] = ""
    ent = channel.get("driver", {}).get("entities", {}).get("haSuspendSwitch")
    if ent and not _dosing_awc_suspended(config):
        await hass.services.async_call("switch", "turn_off", {ATTR_ENTITY_ID: ent}, blocking=True)
    _dosing_record_event(channel, "resume", "Dosing lockout cleared")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/dosing_dry_run",
    vol.Required("channel_id"): cv.string,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_dosing_dry_run(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """'Tomorrow's plan' — the schedule computed dose-by-dose, no motor movement."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    channel = _dosing_channel_for_msg(connection, msg, config)
    if channel is None:
        return
    now_local = dt_util.now()
    compiled = dosing_engine.compile_schedule(channel, _dosing_lighting_off_window(config, now_local), now_local)
    connection.send_result(msg["id"], {
        "preview": dosing_engine.dry_run_preview(compiled["plan"]),
        "warnings": compiled["warnings"],
        "plan": compiled["plan"],
    })


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/dosing_ramp_checkpoint",
    vol.Required("channel_id"): cv.string,
    vol.Required("tested_value"): vol.Coerce(float),
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_dosing_ramp_checkpoint(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Log a new-tank ramp test checkpoint; the advisory target steps up in response."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    channel = _dosing_channel_for_msg(connection, msg, config)
    if channel is None:
        return
    ramp = channel.setdefault("ramp", {})
    checkpoints = ramp.setdefault("checkpoints", [])
    checkpoints.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "testedValue": float(msg["tested_value"]),
    })
    del checkpoints[20:]
    _dosing_record_event(channel, "ramp_checkpoint", f"Test logged: {float(msg['tested_value']):g}")
    config = await _async_save_config(hass, entry, config)
    ml_per_day = channel.get("schedule", {}).get("mlPerDay") or 0
    _awc_send(connection, msg, hass, config, ramp=dosing_engine.ramp_target(ramp, ml_per_day))


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/dosing_delete_channel",
    vol.Required("channel_id"): cv.string,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_dosing_delete_channel(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Remove a channel. Unlinking only — the pump's on-device schedule keeps running
    until its enable switch is turned off, and the panel warns exactly that."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    channels = _dosing_channels(config)
    if msg["channel_id"] not in channels:
        connection.send_error(msg["id"], "unknown_channel", "No such dosing channel")
        return
    channels.pop(msg["channel_id"])
    runtime = hass.data.setdefault(DOMAIN, {}).setdefault(DOSING_RUNTIME, {})
    runtime.get("channels", {}).pop(msg["channel_id"], None)
    runtime.get("desired", {}).pop(msg["channel_id"], None)
    _append_activity(config, f"Removed dosing channel: {msg['channel_id']}", "control")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config)


# --- Saltwater Mixing Station: orchestration + websocket actions ---------------------------
# Maths in mixing.py; the batch state machine's TRANSITIONS live here
# (docs/mixing-station-brainstorm.md §5). Stamped-timestamp state, a single
# HA-timed cap (the booster fill cap — the software backup behind the float
# valve), and the AWC locking/stop-path/orphan-recovery conventions throughout.

def _mixing_cfg(config: dict[str, Any]) -> dict[str, Any]:
    section = config.get("mixingStation")
    return section if isinstance(section, dict) else {}


def _mixing_lock(hass: HomeAssistant) -> asyncio.Lock:
    """The per-instance mixing state lock (see MIXING_STATE_LOCK). Held by the
    top-level entry points only — never acquire it from an inner helper."""
    store = hass.data.setdefault(DOMAIN, {})
    lock = store.get(MIXING_STATE_LOCK)
    if lock is None:
        lock = store[MIXING_STATE_LOCK] = asyncio.Lock()
    return lock


def _mixing_sim_enabled(config: dict[str, Any]) -> bool:
    """Simulate mode: virtual switches, zero real actuation — dry runs and demos."""
    return bool(_mixing_cfg(config).get("simulate"))


async def _async_mixing_set_switch(
    hass: HomeAssistant, config: dict[str, Any], role: str, on: bool, context: Any
) -> None:
    if _mixing_sim_enabled(config):
        # Before the entity check on purpose — a dry run needs no real plugs at all.
        sim = hass.data.setdefault(DOMAIN, {}).setdefault(
            MIXING_RUNTIME, {}).setdefault("simSwitches", {})
        sim[role] = bool(on)
        return
    switch = _mixing_cfg(config).get("switches", {}).get(role, {})
    entity = _normalise_entity_id(switch.get("switchEntity")) if isinstance(switch, dict) else ""
    if not entity:
        return
    await hass.services.async_call(
        "switch", "turn_on" if on else "turn_off",
        {ATTR_ENTITY_ID: entity}, blocking=True, context=context,
    )


async def _async_mixing_stop_switches(
    hass: HomeAssistant, config: dict[str, Any], roles: Iterable[str], context: Any
) -> None:
    """Turn every listed plug OFF, best-effort — the sole shutdown primitive.
    A failed turn_off must be logged and swallowed, never raised, or one dead
    plug abandons the state transition half-done (the AWC stop-path rule)."""
    for role in roles:
        try:
            await _async_mixing_set_switch(hass, config, role, False, context)
        except Exception:  # noqa: BLE001 - best-effort stop: log and keep stopping the rest
            _LOGGER.exception("Failed to turn off mixing-station %s during stop", role)


def _clear_mixing_fill_timer(hass: HomeAssistant) -> None:
    unsub = hass.data.setdefault(DOMAIN, {}).pop(MIXING_FILL_UNSUB, None)
    if unsub is not None:
        unsub()


def _clear_mixing_circ_timer(hass: HomeAssistant) -> None:
    unsub = hass.data.setdefault(DOMAIN, {}).pop(MIXING_CIRC_UNSUB, None)
    if unsub is not None:
        unsub()


def _mixing_clear_circ_stamps(batch: dict[str, Any]) -> None:
    batch["circulateUntil"] = ""
    batch["nextCirculateAt"] = ""


async def _async_schedule_mixing_circulation(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any]
) -> None:
    """(Re)arm the storing-circulation chain from its persisted stamps — pumps
    stir the stored batch for circulateForMin every circulateEveryH, never
    continuously (doc §5). The callbacks only stamp-and-save; the save pass
    re-enters here and arms whichever leg the stamps now call for, which is
    what makes the chain restart-proof: the stamps ARE the schedule."""
    _clear_mixing_circ_timer(hass)
    cfg = _mixing_cfg(config)
    batch = cfg.get("batch") if isinstance(cfg.get("batch"), dict) else {}
    storage = cfg.get("storage") if isinstance(cfg.get("storage"), dict) else {}
    every_h = _awc_num(storage.get("circulateEveryH"), 0, 0, MIXING_CIRCULATE_EVERY_MAX_H)
    if (not cfg.get("enabled") or batch.get("type") == "rodi" or every_h <= 0
            or str(batch.get("state") or "idle") not in ("ready", "storing")):
        return
    now = datetime.now(timezone.utc)
    store = hass.data.setdefault(DOMAIN, {})
    until = _parse_datetime(batch.get("circulateUntil"))
    if until is not None and until > now:
        # A burst is in flight — arm its stop leg.
        async def _stop(_now: datetime) -> None:
            latest = _first_entry(hass)
            async with _mixing_lock(hass):
                hass.data.setdefault(DOMAIN, {}).pop(MIXING_CIRC_UNSUB, None)
                if latest is None:
                    return
                cfg2 = _config_from_entry(latest)
                batch2 = _mixing_cfg(cfg2).get("batch", {})
                if str(batch2.get("state") or "idle") not in ("ready", "storing"):
                    return
                await _async_mixing_stop_switches(
                    hass, cfg2, ("mixPumpA", "mixPumpB"), None)
                stamp = datetime.now(timezone.utc)
                batch2["circulateUntil"] = ""
                batch2["lastCirculatedAt"] = stamp.isoformat()
                every2 = _awc_num(_mixing_cfg(cfg2).get("storage", {}).get("circulateEveryH"),
                                  0, 0, MIXING_CIRCULATE_EVERY_MAX_H)
                batch2["nextCirculateAt"] = (
                    (stamp + timedelta(hours=every2)).isoformat() if every2 > 0 else "")
                await _async_save_config(hass, latest, cfg2)  # save re-arms the start leg

        store[MIXING_CIRC_UNSUB] = async_track_point_in_time(hass, _stop, until)
        return
    next_at = _parse_datetime(batch.get("nextCirculateAt"))
    if next_at is None:
        return  # stamped when the batch goes ready; absent = nothing scheduled

    async def _start(_now: datetime) -> None:
        latest = _first_entry(hass)
        async with _mixing_lock(hass):
            hass.data.setdefault(DOMAIN, {}).pop(MIXING_CIRC_UNSUB, None)
            if latest is None:
                return
            cfg2 = _config_from_entry(latest)
            mix2 = _mixing_cfg(cfg2)
            batch2 = mix2.get("batch", {})
            if (not mix2.get("enabled") or batch2.get("type") == "rodi"
                    or str(batch2.get("state") or "idle") not in ("ready", "storing")):
                return
            for role in ("mixPumpA", "mixPumpB"):
                try:
                    await _async_mixing_set_switch(hass, cfg2, role, True, None)
                except Exception:  # noqa: BLE001 - one dead pump must not kill the burst
                    _LOGGER.exception("Could not start %s for the circulation burst", role)
            for_min = _awc_num(mix2.get("storage", {}).get("circulateForMin"),
                               10, 1, MIXING_CIRCULATE_FOR_MAX_MIN)
            stamp = datetime.now(timezone.utc)
            batch2["state"] = "storing"       # the first burst is the ready→storing edge
            batch2["circulateUntil"] = (stamp + timedelta(minutes=for_min)).isoformat()
            batch2["nextCirculateAt"] = ""
            await _async_save_config(hass, latest, cfg2)  # save re-arms the stop leg

    store[MIXING_CIRC_UNSUB] = async_track_point_in_time(
        hass, _start, max(next_at, now + timedelta(seconds=30)))


def _mixing_sync_reminders(config: dict[str, Any], now: datetime, event: str) -> None:
    """Hatchery-pattern bridge: only ever touches the retest chore IF THE
    KEEPER ADDED IT (the panel's seed button) — a sync must never conjure a
    reminder behind their back. 'tested' logs a completion (the due clock runs
    from the refractometer) and re-times the cadence to the current
    retestAfterDays; 'gone' disables the chore so an empty station never nags;
    'stored' re-enables it for a fresh batch."""
    maintenance = config.get("maintenance")
    if not isinstance(maintenance, dict):
        return
    tasks = maintenance.get("tasks")
    if not isinstance(tasks, dict):
        return
    task = tasks.get(MAINTENANCE_MIXING_RETEST_TASK_ID)
    if not isinstance(task, dict):
        return
    if event == "tested":
        retest_days = int(_awc_num(
            _mixing_cfg(config).get("storage", {}).get("retestAfterDays"),
            7, 0, MIXING_RETEST_MAX_DAYS))
        if retest_days > 0:
            task["cadenceDays"] = retest_days
            task["criticalAfterDays"] = retest_days * 2
        task["enabled"] = True
        task["snoozedUntil"] = None
        completions = maintenance.setdefault("completions", {})
        if not isinstance(completions, dict):
            completions = {}
            maintenance["completions"] = completions
        entries = completions.setdefault(MAINTENANCE_MIXING_RETEST_TASK_ID, [])
        if not isinstance(entries, list):
            entries = []
            completions[MAINTENANCE_MIXING_RETEST_TASK_ID] = entries
        timestamp = now.isoformat()
        entries.insert(0, {
            "id": f"{MAINTENANCE_MIXING_RETEST_TASK_ID}:mixing:{timestamp}",
            "timestamp": timestamp,
            "notes": "Logged automatically — salinity tested on the Mixing Station tab",
            "source": MAINTENANCE_SOURCE_MIXING,
        })
        del entries[MAINTENANCE_COMPLETIONS_MAX:]
    elif event == "gone":
        task["enabled"] = False
    elif event == "stored":
        task["enabled"] = True


def _mixing_close_batch(hass: HomeAssistant, config: dict[str, Any]) -> None:
    """The one way a batch leaves the books: circulation stopped, the batch
    block reset to idle, the keeper's retest chore stood down. Abort, an
    exhausted mark-used, and the AWC completion debit all end here."""
    _clear_mixing_circ_timer(hass)
    _mixing_cfg(config)["batch"] = {
        "state": "idle", "type": "salt", "startedAt": "", "stageAt": "",
        "litres": 0, "loggedPpt": 0, "testedAt": "", "usedLitres": 0,
        "circulateUntil": "", "nextCirculateAt": "", "lastCirculatedAt": "",
    }
    _mixing_sync_reminders(config, datetime.now(timezone.utc), "gone")


def _mixing_debit_batch(hass: HomeAssistant, config: dict[str, Any], litres: float,
                        note: str) -> None:
    """Draw litres from the live batch ledger (doc §9's completion debit).
    Quietly does nothing unless the station is enabled, coupled to AWC
    (awcGuard not 'off'), and holding a live salt batch — an AWC filling from
    some other reservoir must not phantom-drain this one."""
    cfg = _mixing_cfg(config)
    if (not cfg.get("enabled") or litres <= 0
            or str((cfg.get("integrations") or {}).get("awcGuard") or "warn") == "off"):
        return
    batch = cfg.get("batch") if isinstance(cfg.get("batch"), dict) else {}
    if str(batch.get("state") or "idle") not in ("ready", "storing") \
            or str(batch.get("type") or "salt") != "salt":
        return
    total = _awc_num(batch.get("litres"), 0, 0, MIXING_VESSEL_MAX_L)
    used = min(total, _awc_num(batch.get("usedLitres"), 0, 0, total) + litres)
    batch["usedLitres"] = round(used, 1)
    remaining = round(total - used, 1)
    if remaining <= 0.05:
        _mixing_close_batch(hass, config)
        _append_activity(config, f"Mixing station: batch used up by {note} — "
                         "the vessel stands empty", "control")
    else:
        _append_activity(
            config, f"Mixing station: {litres:g} L drawn by {note} — {remaining:g} L left",
            "control")


def _mixing_booster_driven(config: dict[str, Any]) -> bool:
    """Whether OpenReef itself drives the fill: sim mode, or a bound booster plug.
    A manual tap still walks the workflow — there is just nothing to switch or cap."""
    if _mixing_sim_enabled(config):
        return True
    switch = _mixing_cfg(config).get("switches", {}).get("rodiBooster", {})
    return bool(isinstance(switch, dict) and _normalise_entity_id(switch.get("switchEntity")))


def _mixing_next_stage(cfg: dict[str, Any], current: str) -> str | None:
    stages = mixing_engine.stage_sequence(
        cfg.get("layout"), (cfg.get("batch") or {}).get("type"),
        (cfg.get("heat") or {}).get("enabled"))
    try:
        idx = stages.index(current)
    except ValueError:
        return None
    return stages[idx + 1] if idx + 1 < len(stages) else None


async def _async_mixing_enter_stage(
    hass: HomeAssistant, config: dict[str, Any], stage: str, context: Any
) -> None:
    """Stamp the stage and actuate what it needs. The heater is stage-gated
    (doc §11): it only ever comes ON in 'heating' — by which point the vessel
    provably holds water — and stays on through 'salting' to hold temperature;
    every path into 'ready'/'idle' forces everything off."""
    batch = _mixing_cfg(config).setdefault("batch", {})
    if stage == "heating":
        await _async_mixing_set_switch(hass, config, "heater", True, context)
    elif stage == "salting":
        await _async_mixing_set_switch(hass, config, "mixPumpA", True, context)
        await _async_mixing_set_switch(hass, config, "mixPumpB", True, context)
    elif stage in ("ready", "idle"):
        await _async_mixing_stop_switches(hass, config, MIXING_SWITCH_ROLES, context)
    batch["state"] = stage
    batch["stageAt"] = datetime.now(timezone.utc).isoformat()


def _mixing_credit_rodi(cfg: dict[str, Any], delta_l: float) -> None:
    """Move the RODI store's honest anchor by a confirmed event (fill done +,
    transfer done −), clamped to [0, vessel volume]."""
    vessels = cfg.get("vessels") if isinstance(cfg.get("vessels"), dict) else {}
    rodi = vessels.get("rodi") if isinstance(vessels.get("rodi"), dict) else None
    if rodi is None:
        return
    vol = _awc_num(rodi.get("volumeLitres"), 0, 0, MIXING_VESSEL_MAX_L)
    level = _awc_num(rodi.get("estimatedLitres"), 0, 0, MIXING_VESSEL_MAX_L) + delta_l
    rodi["estimatedLitres"] = round(max(0.0, min(level, vol if vol > 0 else level)), 1)


def _mixing_add_processed(cfg: dict[str, Any], litres: float) -> None:
    """Bump the filter-litres ledger — every litre through the membrane counts:
    batch fills, draws, calibration runs."""
    if litres <= 0:
        return
    rodi = cfg.setdefault("rodi", {})
    if not isinstance(rodi, dict):
        return
    level = _awc_num(rodi.get("litresProcessed"), 0, 0, MIXING_LITRES_PROCESSED_MAX) + litres
    rodi["litresProcessed"] = round(min(level, MIXING_LITRES_PROCESSED_MAX), 1)


def _clear_mixing_rodi_timer(hass: HomeAssistant) -> None:
    unsub = hass.data.setdefault(DOMAIN, {}).pop(MIXING_RODI_UNSUB, None)
    if unsub is not None:
        unsub()


async def _async_mixing_finish_draw(
    hass: HomeAssistant, config: dict[str, Any], context: Any, stopped_early: bool
) -> None:
    """End the active RODI draw honestly: booster OFF, litres credited from the
    stamps (rate x elapsed — at the scheduled stop that IS the target; an early
    stop credits only what ran; a late fire credits the overrun, because the
    water kept flowing). Store draws move the anchor; every draw feeds the
    filter ledger. Caller holds the lock and saves."""
    cfg = _mixing_cfg(config)
    rodi = cfg.get("rodi") if isinstance(cfg.get("rodi"), dict) else {}
    draw = rodi.get("draw") if isinstance(rodi.get("draw"), dict) else {}
    if not draw.get("active"):
        return
    await _async_mixing_stop_switches(hass, config, ("rodiBooster",), context)
    now = datetime.now(timezone.utc)
    started = _parse_datetime(draw.get("startedAt"))
    rate = _awc_num(rodi.get("rateLph"), 0, 0, MIXING_RODI_RATE_MAX_LPH)
    target = _awc_num(draw.get("litres"), 0, 0, MIXING_VESSEL_MAX_L)
    elapsed_h = max(0.0, (now - started).total_seconds() / 3600.0) if started else 0.0
    done = round(rate * elapsed_h, 1)
    if not stopped_early:
        # The scheduled stop fired: never claim more than the float valve /
        # keeper asked for unless it genuinely overran (late fire after a
        # restart) — and say so when it did.
        if done > target + 0.5:
            _append_activity(
                config, f"Mixing station: RODI draw overran its stop — about {done:g} L "
                f"of a planned {target:g} L (restart delay); levels credited honestly",
                "warning")
        else:
            done = round(target, 1)
    dest = str(draw.get("destination") or "store")
    if dest == "store":
        _mixing_credit_rodi(cfg, done)
    _mixing_add_processed(cfg, done)
    rodi["draw"] = {"active": False, "litres": 0, "destination": dest,
                    "startedAt": "", "endsAt": ""}
    where = "into the RODI store" if dest == "store" else "to the T-off"
    if stopped_early:
        _append_activity(config, f"Mixing station: RODI draw stopped — about {done:g} L "
                         f"of {target:g} L {where}", "control")
    else:
        _append_activity(config, f"Mixing station: RODI draw done — {done:g} L {where}",
                         "control")


async def _async_schedule_mixing_rodi(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any]
) -> None:
    """(Re)arm the RODI-draw stop leg or the calibration cap from persisted
    stamps — the circulation chain's contract: callbacks stamp-and-save, the
    save pass re-enters here, and a restart re-arms whatever the stamps call
    for. These are safety legs, so they run even if the station was disabled
    mid-run — a booster left ON is never acceptable."""
    _clear_mixing_rodi_timer(hass)
    cfg = _mixing_cfg(config)
    rodi = cfg.get("rodi") if isinstance(cfg.get("rodi"), dict) else {}
    draw = rodi.get("draw") if isinstance(rodi.get("draw"), dict) else {}
    cal = rodi.get("calibration") if isinstance(rodi.get("calibration"), dict) else {}
    now = datetime.now(timezone.utc)
    store = hass.data.setdefault(DOMAIN, {})
    if draw.get("active"):
        ends = _parse_datetime(draw.get("endsAt")) or now

        async def _stop(_now: datetime) -> None:
            latest = _first_entry(hass)
            async with _mixing_lock(hass):
                # Pop the guard INSIDE the lock (the calrun lesson).
                hass.data.setdefault(DOMAIN, {}).pop(MIXING_RODI_UNSUB, None)
                if latest is None:
                    return
                cfg2 = _config_from_entry(latest)
                if not (_mixing_cfg(cfg2).get("rodi", {}).get("draw") or {}).get("active"):
                    return
                await _async_mixing_finish_draw(hass, cfg2, None, stopped_early=False)
                await _async_save_config(hass, latest, cfg2)

        store[MIXING_RODI_UNSUB] = async_track_point_in_time(
            hass, _stop, max(ends, now + timedelta(seconds=2)))
        return
    if cal.get("active"):
        started = _parse_datetime(cal.get("startedAt")) or now
        cap_at = started + timedelta(minutes=MIXING_CAL_CAP_MIN)

        async def _cap(_now: datetime) -> None:
            latest = _first_entry(hass)
            async with _mixing_lock(hass):
                hass.data.setdefault(DOMAIN, {}).pop(MIXING_RODI_UNSUB, None)
                if latest is None:
                    return
                cfg2 = _config_from_entry(latest)
                rodi2 = _mixing_cfg(cfg2).get("rodi", {})
                if not (rodi2.get("calibration") or {}).get("active"):
                    return
                await _async_mixing_stop_switches(hass, cfg2, ("rodiBooster",), None)
                rodi2["calibration"] = {"active": False, "startedAt": ""}
                _append_activity(
                    cfg2, f"Mixing station: flow calibration hit the {MIXING_CAL_CAP_MIN}-min "
                    "cap and was cancelled — run it again into a known container", "warning")
                await _async_save_config(hass, latest, cfg2)

        store[MIXING_RODI_UNSUB] = async_track_point_in_time(
            hass, _cap, max(cap_at, now + timedelta(seconds=2)))


async def _async_mixing_recover_orphaned(
    hass: HomeAssistant, entry: OpenReefConfigEntry
) -> None:
    """Restart mid-batch: the fill-cap timer is memory-only and plugs may be
    energised with nothing armed to manage them. Fail-safe per role (doc §11):
    booster and heater force OFF — unattended, their direction is the hazard;
    the mixing pumps re-assert ON during 'salting' — circulation is the safe
    direction and the vessel provably holds water by that stage."""
    state = _mixing_cfg(_config_from_entry(entry)).get("batch", {}).get("state")
    if state not in ("filling", "transferring", "heating", "salting", "ready", "storing"):
        return
    async with _mixing_lock(hass):
        config = _config_from_entry(entry)
        batch = _mixing_cfg(config).get("batch", {})
        st = batch.get("state")
        if st in ("ready", "storing"):
            # Only a restart mid-circulation-burst leaves pumps energised; the
            # cadence re-anchors from now and the schedule pass re-arms it.
            if not batch.get("circulateUntil"):
                return
            await _async_mixing_stop_switches(hass, config, ("mixPumpA", "mixPumpB"), None)
            batch["circulateUntil"] = ""
            every_h = _awc_num(_mixing_cfg(config).get("storage", {}).get("circulateEveryH"),
                               0, 0, MIXING_CIRCULATE_EVERY_MAX_H)
            batch["nextCirculateAt"] = (
                (datetime.now(timezone.utc) + timedelta(hours=every_h)).isoformat()
                if every_h > 0 else "")
            await _async_save_config(hass, entry, config)
            return
        if st == "filling":
            await _async_mixing_stop_switches(hass, config, ("rodiBooster",), None)
            _append_activity(
                config, "Mixing station: restart during the fill — booster stopped; "
                "confirm the fill to continue", "warning")
        elif st == "heating":
            await _async_mixing_stop_switches(hass, config, ("rodiBooster", "heater"), None)
            _append_activity(
                config, "Mixing station: restart during heating — heater off; "
                "confirm temperature to continue", "warning")
        elif st == "salting":
            await _async_mixing_stop_switches(hass, config, ("rodiBooster", "heater"), None)
            try:
                await _async_mixing_set_switch(hass, config, "mixPumpA", True, None)
                await _async_mixing_set_switch(hass, config, "mixPumpB", True, None)
            except Exception:  # noqa: BLE001 - recovery is best-effort; the clock still runs
                _LOGGER.exception("Could not re-start the mixing pumps after a restart")
            _append_activity(
                config, "Mixing station: restart during the mix — pumps re-started, "
                "heater stays off", "info")
        else:  # transferring — nothing of ours should be on; belt and braces
            await _async_mixing_stop_switches(hass, config, ("rodiBooster",), None)
            return
        await _async_save_config(hass, entry, config)


def _mixing_send(connection: websocket_api.ActiveConnection, msg: dict[str, Any],
                 hass: HomeAssistant, config: dict[str, Any], **extra: Any) -> None:
    """Every mixing reply carries the fresh backend-computed summary so the tab
    never renders a stale clock after an action."""
    summary = mixing_engine.summary(_mixing_cfg(config), datetime.now(timezone.utc))
    _awc_send(connection, msg, hass, config, summary=summary, **extra)


@websocket_api.websocket_command({vol.Required("type"): "openreef/mixing_summary"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_mixing_summary(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The mixing-station snapshot the tab polls: batch state + clocks, vessel
    levels, dose guide and brand catalogue — all computed backend-side by
    mixing.py so the panel never re-implements the maths (lockstep lesson)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    summary = mixing_engine.summary(_mixing_cfg(config), datetime.now(timezone.utc))
    connection.send_result(msg["id"], {"success": True, "summary": summary})


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/mixing_start_batch",
    vol.Required("litres"): vol.All(vol.Coerce(float), vol.Range(min=0, max=2000)),
    vol.Optional("batch_type", default="salt"): cv.string,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_mixing_start_batch(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Start a batch: guards, then into 'filling' — booster ON when bound (or
    simulated) with the fill-cap timer armed behind the physical float valve.
    A manual RODI tap still starts the stage; there is just nothing to switch."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    litres = float(msg["litres"])
    batch_type = str(msg.get("batch_type") or "salt")
    async with _mixing_lock(hass):
        config = _config_from_entry(entry)
        cfg = _mixing_cfg(config)
        reasons = mixing_engine.start_guard_reasons(cfg, litres, batch_type)
        if reasons:
            connection.send_result(msg["id"], {"success": False, "reasons": reasons})
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        cfg["batch"] = {
            "state": "filling", "type": batch_type, "startedAt": now_iso,
            "stageAt": now_iso, "litres": round(litres, 1),
            "loggedPpt": 0, "testedAt": "", "usedLitres": 0,
        }
        if _mixing_booster_driven(config):
            try:
                await _async_mixing_set_switch(
                    hass, config, "rodiBooster", True, connection.context(msg))
            except Exception as exc:  # noqa: BLE001 - surface the failure, nothing started
                connection.send_error(msg["id"], "booster_start_failed",
                                      f"Could not start the RODI booster: {exc}")
                return
            cap_min = int(_awc_num(cfg.get("rodi", {}).get("fillCapMin"),
                                   MIXING_FILL_CAP_DEFAULT_MIN, 1, MIXING_FILL_CAP_MAX_MIN))
            ends_at = datetime.now(timezone.utc) + timedelta(minutes=cap_min)

            async def _cap(_now: datetime) -> None:
                latest = _first_entry(hass)
                async with _mixing_lock(hass):
                    # Pop the guard INSIDE the lock (the calrun lesson): popping
                    # earlier opens a window for an interleaved transition.
                    hass.data.setdefault(DOMAIN, {}).pop(MIXING_FILL_UNSUB, None)
                    if latest is None:
                        return
                    cfg2 = _config_from_entry(latest)
                    if _mixing_cfg(cfg2).get("batch", {}).get("state") != "filling":
                        return
                    await _async_mixing_stop_switches(hass, cfg2, ("rodiBooster",), None)
                    _append_activity(
                        cfg2, "Mixing station: fill cap reached — booster stopped; "
                        "confirm the fill when you're back", "warning")
                    await _async_save_config(hass, latest, cfg2)

            _clear_mixing_fill_timer(hass)
            hass.data.setdefault(DOMAIN, {})[MIXING_FILL_UNSUB] = \
                async_track_point_in_time(hass, _cap, ends_at)
        _append_activity(
            config, f"Mixing station: batch started — {litres:g} L "
            f"{'RODI top-off' if batch_type == 'rodi' else 'saltwater'}", "control")
        config = await _async_save_config(hass, entry, config)
    _mixing_send(connection, msg, hass, config, started=True)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/mixing_advance",
    vol.Optional("litres"): vol.All(vol.Coerce(float), vol.Range(min=0, max=2000)),
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_mixing_advance(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Confirm the current stage done and enter the next one — the user IS the
    sensor in v1 (fill done / transferred / at temperature). Leaving 'filling'
    stops the booster and credits the RODI anchor; leaving 'transferring'
    debits it by the confirmed litres (optional ``litres``, default the batch)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    async with _mixing_lock(hass):
        config = _config_from_entry(entry)
        cfg = _mixing_cfg(config)
        batch = cfg.get("batch", {})
        state = str(batch.get("state") or "idle")
        if state not in ("filling", "transferring", "heating"):
            connection.send_error(msg["id"], "invalid_state",
                                  f"Nothing to confirm while the batch is '{state}'")
            return
        next_stage = _mixing_next_stage(cfg, state)
        if not next_stage:
            connection.send_error(msg["id"], "invalid_state", "No next stage from here")
            return
        context = connection.context(msg)
        if state == "filling":
            _clear_mixing_fill_timer(hass)
            await _async_mixing_stop_switches(hass, config, ("rodiBooster",), context)
            filled = _awc_num(batch.get("litres"), 0, 0, MIXING_VESSEL_MAX_L)
            if str(cfg.get("layout") or "dual") == "dual" and batch.get("type") != "rodi":
                _mixing_credit_rodi(cfg, filled)
            # Every confirmed fill went through the membrane — the filter
            # ledger counts it whatever the layout or batch type.
            _mixing_add_processed(cfg, filled)
        elif state == "transferring":
            moved = _awc_num(msg.get("litres"), _awc_num(batch.get("litres"), 0, 0,
                                                         MIXING_VESSEL_MAX_L),
                             0, MIXING_VESSEL_MAX_L)
            _mixing_credit_rodi(cfg, -moved)
        await _async_mixing_enter_stage(hass, config, next_stage, context)
        _append_activity(
            config, f"Mixing station: {state} confirmed → {next_stage}", "control")
        config = await _async_save_config(hass, entry, config)
    _mixing_send(connection, msg, hass, config)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/mixing_log_salinity",
    vol.Required("ppt"): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=60)),
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_mixing_log_salinity(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Log a refractometer reading against the target — the first test while
    'salting', or a RETEST on a ready/storing batch. In band: the batch goes
    (or stays) ready/storing with testedAt refreshed, the circulation cadence
    stamped, and the keeper's retest chore marked done. Out of band: back to
    (or stays in) 'salting' — pumps on, mix clock restarted — and the reply
    carries real grams-to-add or litres-to-dilute maths, never 'try again'."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    ppt = float(msg["ppt"])
    async with _mixing_lock(hass):
        config = _config_from_entry(entry)
        cfg = _mixing_cfg(config)
        batch = cfg.get("batch", {})
        state = str(batch.get("state") or "idle")
        if state not in ("salting", "ready", "storing"):
            connection.send_error(msg["id"], "invalid_state",
                                  "Salinity is logged while a batch is mixing or stored")
            return
        salt_cfg = cfg.get("salt", {})
        correction = mixing_engine.salinity_correction(
            ppt, salt_cfg.get("targetPpt"), batch.get("litres"),
            salt_cfg.get("brand"), salt_cfg.get("customGPerL"))
        now = datetime.now(timezone.utc)
        batch["loggedPpt"] = round(ppt, 2)
        if correction.get("status") == "pass":
            batch["testedAt"] = now.isoformat()
            if state == "salting":
                await _async_mixing_enter_stage(hass, config, "ready", connection.context(msg))
                every_h = _awc_num(cfg.get("storage", {}).get("circulateEveryH"),
                                   0, 0, MIXING_CIRCULATE_EVERY_MAX_H)
                batch["nextCirculateAt"] = (
                    (now + timedelta(hours=every_h)).isoformat() if every_h > 0 else "")
                _append_activity(
                    config, f"Mixing station: batch tested at {ppt:g} ppt — ready", "control")
            else:
                _append_activity(
                    config, f"Mixing station: retested {ppt:g} ppt — still good", "control")
            _mixing_sync_reminders(config, now, "tested")
        elif state in ("ready", "storing"):
            # A stored batch that drifted out of band goes back onto the pumps —
            # the honest fix is re-mixing, not a stale "ready" with an asterisk.
            _clear_mixing_circ_timer(hass)
            _mixing_clear_circ_stamps(batch)
            await _async_mixing_enter_stage(hass, config, "salting", connection.context(msg))
            _append_activity(
                config, f"Mixing station: retest {ppt:g} ppt out of band — back to mixing",
                "warning")
        else:
            _append_activity(
                config, f"Mixing station: tested {ppt:g} ppt — "
                f"{correction.get('status', 'out of band')}", "info")
        config = await _async_save_config(hass, entry, config)
    _mixing_send(connection, msg, hass, config, correction=correction)


@websocket_api.websocket_command({vol.Required("type"): "openreef/mixing_abort"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_mixing_abort(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Abort/discard the batch from any state: cap timer cancelled, every plug
    OFF best-effort, batch back to idle. The one command that always works."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    async with _mixing_lock(hass):
        config = _config_from_entry(entry)
        cfg = _mixing_cfg(config)
        if str(cfg.get("batch", {}).get("state") or "idle") == "idle":
            connection.send_error(msg["id"], "not_running", "No batch to abort")
            return
        _clear_mixing_fill_timer(hass)
        await _async_mixing_stop_switches(
            hass, config, MIXING_SWITCH_ROLES, connection.context(msg))
        _mixing_close_batch(hass, config)
        _append_activity(config, "Mixing station: batch aborted — everything switched off",
                         "warning")
        config = await _async_save_config(hass, entry, config)
    _mixing_send(connection, msg, hass, config)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/mixing_mark_used",
    vol.Required("litres"): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=2000)),
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_mixing_mark_used(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Debit the batch ledger by used litres (a water change, a top-off jug).
    An exhausted batch closes honestly: back to idle, circulation stopped, the
    retest chore stood down. AWC's Stage D completion will call this too."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    litres = float(msg["litres"])
    async with _mixing_lock(hass):
        config = _config_from_entry(entry)
        cfg = _mixing_cfg(config)
        batch = cfg.get("batch", {})
        if str(batch.get("state") or "idle") not in ("ready", "storing"):
            connection.send_error(msg["id"], "invalid_state",
                                  "Only a ready or stored batch can be drawn from")
            return
        total = _awc_num(batch.get("litres"), 0, 0, MIXING_VESSEL_MAX_L)
        used = min(total, _awc_num(batch.get("usedLitres"), 0, 0, total) + litres)
        batch["usedLitres"] = round(used, 1)
        remaining = round(total - used, 1)
        if remaining <= 0.05:
            _mixing_close_batch(hass, config)
            _append_activity(config, "Mixing station: batch used up — the vessel stands empty",
                             "control")
        else:
            _append_activity(
                config, f"Mixing station: {litres:g} L used — {remaining:g} L left", "control")
        config = await _async_save_config(hass, entry, config)
    _mixing_send(connection, msg, hass, config)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/mixing_set_level",
    vol.Required("vessel"): cv.string,
    vol.Required("litres"): vol.All(vol.Coerce(float), vol.Range(min=0, max=2000)),
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_mixing_set_level(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Manual level correction — the keeper looked at the container and the
    estimate was wrong. 'rodi' re-anchors the store's ledger; 'mix' re-anchors
    the live batch's remaining litres (usedLitres absorbs the difference)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    vessel = str(msg["vessel"])
    litres = float(msg["litres"])
    if vessel not in ("rodi", "mix"):
        connection.send_error(msg["id"], "invalid_vessel", "Vessel must be 'rodi' or 'mix'")
        return
    async with _mixing_lock(hass):
        config = _config_from_entry(entry)
        cfg = _mixing_cfg(config)
        if vessel == "rodi":
            if str(cfg.get("layout") or "dual") != "dual":
                connection.send_error(msg["id"], "invalid_vessel",
                                      "A single-vessel layout has no RODI store")
                return
            rodi = cfg.setdefault("vessels", {}).setdefault("rodi", {})
            vol = _awc_num(rodi.get("volumeLitres"), 0, 0, MIXING_VESSEL_MAX_L)
            rodi["estimatedLitres"] = round(
                max(0.0, min(litres, vol if vol > 0 else litres)), 1)
        else:
            batch = cfg.get("batch", {})
            if str(batch.get("state") or "idle") == "idle":
                connection.send_error(msg["id"], "invalid_state",
                                      "No batch in the mix vessel to correct")
                return
            total = _awc_num(batch.get("litres"), 0, 0, MIXING_VESSEL_MAX_L)
            batch["usedLitres"] = round(max(0.0, min(total, total - litres)), 1)
        _append_activity(
            config, f"Mixing station: {vessel} level corrected to {litres:g} L", "control")
        config = await _async_save_config(hass, entry, config)
    _mixing_send(connection, msg, hass, config)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/mixing_rodi_draw",
    vol.Required("litres"): vol.All(vol.Coerce(float), vol.Range(min=0, max=2000)),
    vol.Optional("destination", default="store"): cv.string,
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_mixing_rodi_draw(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Run the RODI unit OUTSIDE any batch — a litre-targeted booster run into
    the store, or an external T-off (the ATO reservoir). rate x time is the
    meter, so the guards refuse without a known flow rate; the stop leg is
    armed by the save pass off the endsAt stamp (stamps ARE the schedule)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    litres = float(msg["litres"])
    destination = str(msg.get("destination") or "store")
    async with _mixing_lock(hass):
        config = _config_from_entry(entry)
        cfg = _mixing_cfg(config)
        reasons = mixing_engine.draw_guard_reasons(cfg, litres, destination)
        if reasons:
            connection.send_result(msg["id"], {"success": False, "reasons": reasons})
            return
        try:
            await _async_mixing_set_switch(
                hass, config, "rodiBooster", True, connection.context(msg))
        except Exception as exc:  # noqa: BLE001 - surface the failure, nothing started
            connection.send_error(msg["id"], "booster_start_failed",
                                  f"Could not start the RODI booster: {exc}")
            return
        rate = _awc_num(cfg.get("rodi", {}).get("rateLph"), 0, 0, MIXING_RODI_RATE_MAX_LPH)
        now = datetime.now(timezone.utc)
        minutes = litres / rate * 60.0
        cfg.setdefault("rodi", {})["draw"] = {
            "active": True, "litres": round(litres, 1), "destination": destination,
            "startedAt": now.isoformat(),
            "endsAt": (now + timedelta(minutes=minutes)).isoformat(),
        }
        where = "the RODI store" if destination == "store" else "the T-off"
        _append_activity(
            config, f"Mixing station: RODI draw started — {litres:g} L to {where} "
            f"(about {minutes:.0f} min at {rate:g} L/h)", "control")
        config = await _async_save_config(hass, entry, config)  # save arms the stop leg
    _mixing_send(connection, msg, hass, config, started=True)


@websocket_api.websocket_command({vol.Required("type"): "openreef/mixing_rodi_stop"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_mixing_rodi_stop(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Stop the running draw early — only what actually ran gets credited."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    async with _mixing_lock(hass):
        config = _config_from_entry(entry)
        cfg = _mixing_cfg(config)
        if not (cfg.get("rodi", {}).get("draw") or {}).get("active"):
            connection.send_error(msg["id"], "invalid_state", "No RODI draw is running")
            return
        _clear_mixing_rodi_timer(hass)
        await _async_mixing_finish_draw(
            hass, config, connection.context(msg), stopped_early=True)
        config = await _async_save_config(hass, entry, config)
    _mixing_send(connection, msg, hass, config)


@websocket_api.websocket_command({
    vol.Required("type"): "openreef/mixing_calibrate",
    vol.Required("action"): vol.In(("start", "finish", "cancel")),
    vol.Optional("litres"): vol.All(vol.Coerce(float), vol.Range(min=0, max=2000)),
})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_mixing_calibrate(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Timed-run flow calibration: start runs the booster into the keeper's
    known container; finish takes the measured litres and sets rateLph from
    litres/elapsed. A run under a minute is refused — that maths is noise, not
    data. The cap leg (save-armed) cancels a forgotten run."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    action = str(msg["action"])
    async with _mixing_lock(hass):
        config = _config_from_entry(entry)
        cfg = _mixing_cfg(config)
        rodi = cfg.setdefault("rodi", {})
        cal = rodi.get("calibration") if isinstance(rodi.get("calibration"), dict) else {}
        if action == "start":
            reasons: list[str] = []
            if not cfg.get("enabled"):
                reasons.append("Mixing station is not enabled")
            if not _mixing_booster_driven(config):
                reasons.append("Bind the RODI booster plug (or turn on Simulate) — "
                               "a calibration run needs OpenReef on the switch")
            busy = mixing_engine.rodi_busy_reason(cfg)
            if busy:
                reasons.append(f"The booster is busy — {busy}")
            if reasons:
                connection.send_result(msg["id"], {"success": False, "reasons": reasons})
                return
            try:
                await _async_mixing_set_switch(
                    hass, config, "rodiBooster", True, connection.context(msg))
            except Exception as exc:  # noqa: BLE001
                connection.send_error(msg["id"], "booster_start_failed",
                                      f"Could not start the RODI booster: {exc}")
                return
            rodi["calibration"] = {"active": True,
                                   "startedAt": datetime.now(timezone.utc).isoformat()}
            _append_activity(
                config, "Mixing station: flow calibration started — let it run into a "
                "known container, then enter the litres", "control")
        else:
            if not cal.get("active"):
                connection.send_error(msg["id"], "invalid_state",
                                      "No calibration run is active")
                return
            _clear_mixing_rodi_timer(hass)
            await _async_mixing_stop_switches(
                hass, config, ("rodiBooster",), connection.context(msg))
            started = _parse_datetime(cal.get("startedAt"))
            rodi["calibration"] = {"active": False, "startedAt": ""}
            failure: str | None = None
            if action == "finish":
                elapsed_s = max(0.0, (datetime.now(timezone.utc) - started).total_seconds()) \
                    if started else 0.0
                litres = _awc_num(msg.get("litres"), 0, 0, MIXING_VESSEL_MAX_L)
                rate = mixing_engine.calibration_rate(litres, elapsed_s)
                if rate <= 0:
                    # The run is over either way (booster stopped) — record the
                    # failure honestly and leave the stored rate untouched.
                    failure = ("Not enough to calibrate from — the run must be at "
                               f"least {MIXING_CAL_MIN_SECONDS} s with measured "
                               "litres above 0; the rate is unchanged")
                    _append_activity(
                        config, "Mixing station: flow calibration too short to "
                        "trust — rate unchanged", "warning")
                else:
                    rate = round(min(rate, MIXING_RODI_RATE_MAX_LPH), 1)
                    rodi["rateLph"] = rate
                    rodi["calibratedAt"] = datetime.now(timezone.utc).isoformat()
                    _mixing_add_processed(cfg, litres)
                    _append_activity(
                        config, f"Mixing station: RODI rate calibrated — {rate:g} L/h "
                        f"from a {elapsed_s / 60.0:.1f}-min run of {litres:g} L",
                        "control")
            else:
                _append_activity(
                    config, "Mixing station: flow calibration cancelled — rate unchanged",
                    "control")
            if failure is not None:
                config = await _async_save_config(hass, entry, config)
                connection.send_result(msg["id"], {"success": False, "reasons": [failure]})
                return
        config = await _async_save_config(hass, entry, config)
    _mixing_send(connection, msg, hass, config)


@websocket_api.websocket_command({vol.Required("type"): "openreef/mixing_filters_changed"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_mixing_filters_changed(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The keeper serviced the RODI filters — the litre counter starts again."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    async with _mixing_lock(hass):
        config = _config_from_entry(entry)
        rodi = _mixing_cfg(config).setdefault("rodi", {})
        rodi["litresProcessed"] = 0
        rodi["filterChangedAt"] = datetime.now(timezone.utc).isoformat()
        _append_activity(config, "Mixing station: RODI filters marked changed — "
                         "the litre counter starts again", "control")
        config = await _async_save_config(hass, entry, config)
    _mixing_send(connection, msg, hass, config)


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
    if not _mark_camera_io_started(hass, camera_entity_id):
        _LOGGER.debug("OpenReef clip skipped for %s: camera is already busy", camera_entity_id)
        return False
    try:
        data: dict[str, Any] = {
            ATTR_ENTITY_ID: camera_entity_id,
            "filename": str(video_path),
            "duration": duration,
        }
        if lookback > 0:
            data["lookback"] = lookback
        await hass.services.async_call("camera", "record", data, blocking=True)
        return await hass.async_add_executor_job(video_path.exists)
    finally:
        _mark_camera_io_finished(hass, camera_entity_id)


def _mark_camera_io_started(hass: HomeAssistant, entity_id: str) -> bool:
    """Best-effort guard against overlapping camera reads for fragile USB cameras."""
    inflight: set[str] = hass.data.setdefault(DOMAIN, {}).setdefault(CAMERA_IO_INFLIGHT, set())
    if entity_id in inflight:
        return False
    inflight.add(entity_id)
    return True


def _mark_camera_io_finished(hass: HomeAssistant, entity_id: str) -> None:
    inflight: set[str] = hass.data.setdefault(DOMAIN, {}).setdefault(CAMERA_IO_INFLIGHT, set())
    inflight.discard(entity_id)


async def _async_write_snapshot(hass: HomeAssistant, entity_id: str, path: Path) -> bool:
    """Grab a still from a camera entity and write it to ``path`` (parent must exist).

    Works on any camera, no allowlist. Best-effort — logs and returns False on failure,
    never raises. Shared by event-capture thumbnails and timelapse frames.
    """
    if not _mark_camera_io_started(hass, entity_id):
        _LOGGER.debug("OpenReef snapshot skipped for %s: camera is already busy", entity_id)
        return False
    try:
        from homeassistant.components import camera as camera_component

        image = await camera_component.async_get_image(hass, entity_id, timeout=10)
        await hass.async_add_executor_job(path.write_bytes, image.content)
        return True
    except Exception:  # noqa: BLE001 - snapshot is best-effort
        _LOGGER.warning("OpenReef snapshot failed for %s", entity_id, exc_info=True)
        return False
    finally:
        _mark_camera_io_finished(hass, entity_id)


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


# --- Feed-watch (Phase D): a snapshot burst across the Feed-mode window ---

def _feeds_dir(hass: HomeAssistant, session_id: str) -> Path:
    """Per-session subdir of the captures dir holding (and serving) feed-watch frames."""
    return _captures_dir(hass) / FEEDS_SUBDIR / session_id


async def _async_delete_feed_dir(hass: HomeAssistant, session_id: str) -> None:
    """Best-effort remove of a feed session's frame directory."""
    directory = _feeds_dir(hass, session_id)

    def _remove() -> None:
        if not directory.is_dir():
            return
        for child in directory.iterdir():
            try:
                child.unlink()
            except OSError:
                pass
        try:
            directory.rmdir()
        except OSError:
            pass

    await hass.async_add_executor_job(_remove)


def _feed_session_frame_count(directory: Path) -> int:
    """Count a feed session's frames on disk — runs in the executor."""
    if not directory.is_dir():
        return 0
    return sum(1 for p in directory.iterdir() if p.is_file() and p.suffix == ".jpg")


async def _async_stop_feed_watch(hass: HomeAssistant, entry: OpenReefConfigEntry) -> None:
    """Finalize the active feed-watch session (if any) and stop the burst timer."""
    _clear_feedwatch(hass)
    state = (
        hass.data.setdefault(DOMAIN, {})
        .setdefault(FEEDWATCH_SESSION, {})
        .pop(entry.entry_id, None)
    )
    if not state:
        return
    session_id = state.get("id")
    frame_count = await hass.async_add_executor_job(
        _feed_session_frame_count, _feeds_dir(hass, session_id)
    )
    config = _config_from_entry(entry)
    sessions = config.get("feedSessions")
    if isinstance(sessions, list):
        for session in sessions:
            if isinstance(session, dict) and session.get("id") == session_id:
                session["status"] = "done"
                session["endedAt"] = dt_util.utcnow().isoformat()
                session["frameCount"] = frame_count
                break
    await _async_save_config(hass, entry, config)


async def _async_finalize_orphaned_feed_sessions(
    hass: HomeAssistant, entry: OpenReefConfigEntry
) -> None:
    """A feed session left ``recording`` after an HA restart can never be finalized by
    the burst timer (it lived only in hass.data), so it would show a perpetual REC badge.
    Mark any lingering recording sessions as done on setup, recounting frames from disk."""
    config = _config_from_entry(entry)
    sessions = config.get("feedSessions")
    if not isinstance(sessions, list):
        return
    changed = False
    for session in sessions:
        if not (isinstance(session, dict) and session.get("status") == "recording"):
            continue
        session_id = session.get("id")
        if session_id:
            session["frameCount"] = await hass.async_add_executor_job(
                _feed_session_frame_count, _feeds_dir(hass, session_id)
            )
        session["status"] = "done"
        session.setdefault("endedAt", session.get("startedAt", ""))
        changed = True
    if changed:
        await _async_save_config(hass, entry, config)


async def _async_start_feed_watch(hass: HomeAssistant, entry: OpenReefConfigEntry) -> None:
    """Start a feed-watch session: snapshot the camera every cadenceSeconds for the feed
    window. Never raises into the mode path."""
    try:
        if (
            hass.data.setdefault(DOMAIN, {})
            .setdefault(FEEDWATCH_SESSION, {})
            .get(entry.entry_id)
        ):
            await _async_stop_feed_watch(hass, entry)

        config = _config_from_entry(entry)
        feedwatch_cfg = config.get("feedWatch", {})
        if not isinstance(feedwatch_cfg, dict) or not feedwatch_cfg.get("enabled", False):
            return
        resolved = _resolve_capture_camera(
            hass, config, {}, override=feedwatch_cfg.get("cameraId") or None
        )
        if resolved is None:
            return
        camera_id, entity_id, camera_label = resolved

        now = dt_util.utcnow()
        cadence = max(
            FEEDWATCH_MIN_CADENCE,
            min(int(feedwatch_cfg.get("cadenceSeconds", FEEDWATCH_DEFAULT_CADENCE)), FEEDWATCH_MAX_CADENCE),
        )
        mode = config.get("mode", {})
        expires = _parse_datetime(mode.get("expiresAt")) if isinstance(mode, dict) else None
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        end_at = expires if expires and expires > now else now + timedelta(minutes=FEEDWATCH_MAX_MINUTES)
        max_frames = min(2000, int((end_at - now).total_seconds() / cadence) + 5)

        session_id = uuid.uuid4().hex
        frame_dir = _feeds_dir(hass, session_id)
        await hass.async_add_executor_job(lambda: frame_dir.mkdir(parents=True, exist_ok=True))
        if not await _async_write_snapshot(
            hass, entity_id, frame_dir / f"000_{now.strftime('%H%M%S')}.jpg"
        ):
            # Camera isn't delivering — don't open an empty session.
            await _async_delete_feed_dir(hass, session_id)
            return

        sessions = config.get("feedSessions")
        if not isinstance(sessions, list):
            sessions = []
        sessions.insert(
            0,
            {
                "id": session_id,
                "startedAt": now.isoformat(),
                "cameraId": camera_id,
                "cameraLabel": camera_label,
                "frameCount": 1,
                "status": "recording",
            },
        )
        retention = max(
            1,
            min(
                int(feedwatch_cfg.get("retentionSessions", FEEDWATCH_DEFAULT_RETENTION)),
                FEEDWATCH_MAX_RETENTION,
            ),
        )
        pruned = sessions[retention:]
        config["feedSessions"] = sessions[:retention]
        for old in pruned:
            if isinstance(old, dict) and old.get("id"):
                await _async_delete_feed_dir(hass, old["id"])
        await _async_save_config(hass, entry, config)

        hass.data.setdefault(DOMAIN, {}).setdefault(FEEDWATCH_SESSION, {})[entry.entry_id] = {
            "id": session_id,
            "endAt": end_at,
            "frames": 1,
            "maxFrames": max_frames,
        }

        async def _handle_feed_tick(_tick: datetime) -> None:
            current = (
                hass.data.setdefault(DOMAIN, {})
                .setdefault(FEEDWATCH_SESSION, {})
                .get(entry.entry_id)
            )
            if not current or current.get("id") != session_id:
                _clear_feedwatch(hass)
                return
            latest_mode = _config_from_entry(entry).get("mode", {})
            active = latest_mode.get("active") if isinstance(latest_mode, dict) else None
            if (
                active != "feed"
                or dt_util.utcnow() >= current["endAt"]
                or current["frames"] >= current["maxFrames"]
            ):
                await _async_stop_feed_watch(hass, entry)
                return
            index = current["frames"]
            name = f"{index:03d}_{dt_util.utcnow().strftime('%H%M%S')}.jpg"
            if await _async_write_snapshot(hass, entity_id, frame_dir / name):
                current["frames"] = index + 1

        hass.data.setdefault(DOMAIN, {})[FEEDWATCH_UNSUB] = async_track_time_interval(
            hass, _handle_feed_tick, timedelta(seconds=cadence)
        )
    except Exception:  # noqa: BLE001 - feed-watch must never break the mode path
        _LOGGER.exception("OpenReef feed-watch failed to start")


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


def _feed_first_frame(directory: Path) -> str:
    """First (earliest) frame filename in a feed session dir, or '' — runs in executor."""
    if not directory.is_dir():
        return ""
    names = sorted(p.name for p in directory.iterdir() if p.is_file() and p.suffix == ".jpg")
    return names[0] if names else ""


@websocket_api.websocket_command({vol.Required("type"): "openreef/list_feed_sessions"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_list_feed_sessions(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """List feed-watch sessions (newest first), each with a thumbnail frame."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    sessions = config.get("feedSessions")
    if not isinstance(sessions, list):
        sessions = []
    enriched = []
    for session in sessions:
        if not isinstance(session, dict) or not session.get("id"):
            continue
        session_id = session["id"]
        first = await hass.async_add_executor_job(_feed_first_frame, _feeds_dir(hass, session_id))
        item = dict(session)
        item["thumbnail"] = f"{FEEDS_SUBDIR}/{session_id}/{first}" if first else ""
        enriched.append(item)
    connection.send_result(msg["id"], {"sessions": enriched, "baseUrl": CAPTURES_STATIC_URL})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/list_feed_frames",
        vol.Required("session_id"): cv.string,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_list_feed_frames(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """List one feed session's frames (in order) for the scrubber player."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    session_id = msg["session_id"]
    frame_dir = _feeds_dir(hass, session_id)

    def _list() -> list[str]:
        if not frame_dir.is_dir():
            return []
        return sorted(p.name for p in frame_dir.iterdir() if p.is_file() and p.suffix == ".jpg")

    frames = [
        {"file": f"{FEEDS_SUBDIR}/{session_id}/{name}"}
        for name in await hass.async_add_executor_job(_list)
    ]
    connection.send_result(
        msg["id"], {"frames": frames, "baseUrl": CAPTURES_STATIC_URL, "sessionId": session_id}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/delete_feed_session",
        vol.Required("session_id"): cv.string,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_delete_feed_session(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete one feed session (frames on disk + its record)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    session_id = msg["session_id"]
    await _async_delete_feed_dir(hass, session_id)
    config = _config_from_entry(entry)
    sessions = config.get("feedSessions")
    if isinstance(sessions, list):
        config["feedSessions"] = [
            s for s in sessions if not (isinstance(s, dict) and s.get("id") == session_id)
        ]
    saved = await _async_save_config(hass, entry, config)
    connection.send_result(msg["id"], {"success": True, "sessionId": session_id, "config": saved})


# --------------------------------------------------------------------------- #
# Coral Spawning — smart-plug execution (the reconcile tick)
#
# spawning.execution_desired_state() is the pure brain; this tick is the hands.
# Declarative reconcile, never scheduled timers: every minute it asks what the
# plugs SHOULD be and corrects only mismatches — restart-safe, DST-safe, and a
# config edit takes effect on the next tick because saves re-arm the scheduler.
# Manual changes are detected by stamp-and-compare (we remember what we last
# asserted; a mismatch we didn't cause is a human) — policy "hold" respects the
# human until the next natural sunrise/sunset, "reassert" corrects within a
# minute. Disarmed or mode "apex", the tick is never even registered: OpenReef
# releases the plugs wherever they stand.
# --------------------------------------------------------------------------- #
_SPAWNING_EXEC_CHANNELS = (("light", "lightEntity", "daylight"), ("moon", "moonEntity", "moonlight"))


def _spawning_execution_cfg(config: dict[str, Any]) -> dict[str, Any]:
    sp_cfg = config.get("spawningProgram")
    if not isinstance(sp_cfg, dict):
        return {}
    execution = sp_cfg.get("execution")
    return execution if isinstance(execution, dict) else {}


def _spawning_execution_enabled(execution: dict[str, Any]) -> bool:
    temp_cfg = execution.get("temp") if isinstance(execution.get("temp"), dict) else {}
    return (
        execution.get("mode") == "openreef"
        and bool(execution.get("armed"))
        and bool(
            execution.get("lightEntity") or execution.get("moonEntity") or temp_cfg.get("enabled")
        )
    )


def _clear_spawning_tick(hass: HomeAssistant) -> None:
    store = hass.data.setdefault(DOMAIN, {})
    unsub = store.pop(SPAWNING_TICK_UNSUB, None)
    if unsub is not None:
        unsub()


async def _async_schedule_spawning_tick(
    hass: HomeAssistant, entry: OpenReefConfigEntry | None, config: dict[str, Any] | None = None
) -> None:
    """Arm/disarm the minutely spawning reconcile tick (idempotent, called on
    every save). The tick also runs in a publish-only mode for any user with the
    spawning feature on — refreshing the RT target sensor and firing spawn-window
    captures with zero actuation — so the gate is execution-enabled OR feature-on.
    Fully off, the runtime (asserted stamps, overrides) is dropped so a re-arm
    starts with a clean sync instead of stale override state."""
    _clear_spawning_tick(hass)
    if entry is None:
        return
    config = config or _config_from_entry(entry)
    sp_cfg = config.get("spawningProgram")
    feature_on = isinstance(sp_cfg, dict) and bool(sp_cfg.get("enabled"))
    if not (feature_on or _spawning_execution_enabled(_spawning_execution_cfg(config))):
        hass.data.setdefault(DOMAIN, {}).pop(SPAWNING_RUNTIME, None)
        return

    async def _handle(now: datetime) -> None:
        latest_entry = _first_entry(hass)
        if latest_entry is None or latest_entry.entry_id != entry.entry_id:
            return
        await _async_spawning_tick(hass, latest_entry, dt_util.now())

    hass.data.setdefault(DOMAIN, {})[SPAWNING_TICK_UNSUB] = async_track_time_interval(
        hass, _handle, timedelta(seconds=SPAWNING_TICK_SECONDS)
    )


async def _async_spawning_notify_once(
    hass: HomeAssistant, config: dict[str, Any], key: str, cooldown_s: int, title: str, message: str
) -> bool:
    """Cooldown-deduped notification for tick-detected conditions — the minutely
    tick may re-detect the same fault thousands of times; the user hears about
    it once per cooldown. Stamps live in hass.data (no save, no lock)."""
    runtime = hass.data.setdefault(DOMAIN, {}).setdefault(SPAWNING_RUNTIME, {})
    notified = runtime.setdefault("notified", {})
    now = datetime.now(timezone.utc)
    previous = notified.get(key)
    if previous is not None:
        try:
            if (now - datetime.fromisoformat(previous)).total_seconds() < cooldown_s:
                return False
        except (ValueError, TypeError):
            pass
    notified[key] = now.isoformat()
    await _async_send_mode_notification(hass, config, f"openreef_spawning_{key}", title, message)
    return True


def _spawning_publish_target_sensor(
    hass: HomeAssistant, sp_cfg: dict[str, Any], state: dict[str, Any] | None
) -> None:
    """Publish today's seasonal target temperature (RT) as a bare state-machine
    sensor — this integration deliberately creates no entity platforms (same
    pattern as the dosing pH mirror). Stage C step 1, zero risk: wire your own
    generic_thermostat to it, or just watch the seasonal drift."""
    attrs: dict[str, Any] = {
        "friendly_name": "OpenReef Spawning Target Temperature",
        "unit_of_measurement": "°C",
        "device_class": "temperature",
    }
    value = "unavailable"
    if state and state.get("valid"):
        value = f"{float(state['targetTempC']):.1f}"
        preset = REEF_PRESETS.get(sp_cfg.get("reefPreset")) or {}
        attrs.update(
            {
                "reef": preset.get("label", ""),
                "reefMonth": state.get("reefMonthName"),
                "sunrise": state.get("sunrise"),
                "sunset": state.get("sunset"),
                "dayLengthHours": state.get("dayLengthHours"),
                "moonIlluminationPct": state.get("moonIlluminationPct"),
                "inSpawnWindow": state.get("inSpawnWindow"),
            }
        )
    try:
        hass.states.async_set(SPAWNING_TARGET_TEMP_ENTITY, value, attrs)
    except Exception:  # noqa: BLE001 — a sensor publish must never break the tick
        _LOGGER.exception("Spawning: failed to publish the target-temperature sensor")


def _spawning_maybe_capture_window_night(
    hass: HomeAssistant,
    entry: OpenReefConfigEntry,
    runtime: dict[str, Any],
    state: dict[str, Any],
    now_local: datetime,
) -> None:
    """Stage D: one camera capture per predicted spawn-window night, at the first
    tick after sunset (evening side only, so the post-midnight hours of the same
    night never re-fire). Opt-in via capture.triggers.spawnWindowNight."""
    if not (state.get("inSpawnWindow") and not state.get("light") and now_local.hour >= 12):
        return
    stamp = now_local.date().isoformat()
    if runtime.get("windowNightCaptured") == stamp:
        return
    runtime["windowNightCaptured"] = stamp
    _dispatch_capture(
        hass, entry, "spawn_window_night", f"Spawn-window night — sunset {state.get('sunset')}"
    )


async def _async_spawning_set_plug(hass: HomeAssistant, entity: str, on: bool) -> bool:
    """Best-effort actuator write for the temperature channels."""
    try:
        await hass.services.async_call(
            "switch", "turn_on" if on else "turn_off",
            {ATTR_ENTITY_ID: entity}, blocking=True, context=None,
        )
        return True
    except Exception:  # noqa: BLE001 — a dead plug must not kill the tick; retry next minute
        _LOGGER.exception("Spawning temperature control could not switch %s", entity)
        return False


async def _async_spawning_temp_reconcile(
    hass: HomeAssistant,
    config: dict[str, Any],
    execution: dict[str, Any],
    state: dict[str, Any],
    runtime: dict[str, Any],
) -> None:
    """Stage C step 2 — guarded seasonal heat/cool: symmetric bang-bang at
    RT ± tolerance, the exact mirror of the Apex heater/chiller snippets the
    compiler emits. The plugs' own on/off state is the hysteresis latch, so the
    software stays stateless. This is a SAFETY channel: manual overrides are
    never held here, every sensor doubt (unavailable, non-numeric, stale,
    implausible) switches BOTH actuators OFF and alerts, and hard clamps sit
    outside the seasonal curve. The required physical guard — an inline
    thermostat (e.g. an Inkbird) at the seasonal max — is part of the opt-in
    acknowledgement; heating's safe direction is OFF, cooling's is ON."""
    temp_cfg = execution.get("temp") if isinstance(execution.get("temp"), dict) else {}
    issues = runtime.setdefault("issues", {})
    if not temp_cfg.get("enabled"):
        for key in ("temp", "temp_heater", "temp_cool"):
            issues.pop(key, None)
        runtime.pop("tempReading", None)
        return
    heater = temp_cfg.get("heaterEntity")
    cooler = temp_cfg.get("coolEntity")
    sensor_entity = temp_cfg.get("sensorEntity")

    reading: float | None = None
    reason = ""
    st = hass.states.get(sensor_entity)
    if st is None or st.state in UNAVAILABLE_STATES:
        reason = f"temperature sensor ({sensor_entity}) is unavailable"
    else:
        try:
            reading = float(st.state)
        except (TypeError, ValueError):
            reason = f"temperature sensor ({sensor_entity}) is not numeric"
        if reading is not None:
            unit = str(st.attributes.get("unit_of_measurement", "")).upper()
            if "F" in unit:
                reading = (reading - 32.0) * 5.0 / 9.0
            last = getattr(st, "last_updated", None) or getattr(st, "last_changed", None)
            if isinstance(last, datetime):
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if (dt_util.utcnow() - last).total_seconds() > SPAWNING_TEMP_STALE_MINUTES * 60:
                    reason = f"temperature sensor ({sensor_entity}) has been silent too long"
            if not reason and not (
                SPAWNING_TEMP_PLAUSIBLE_MIN_C <= reading <= SPAWNING_TEMP_PLAUSIBLE_MAX_C
            ):
                reason = (
                    f"temperature reading {reading:.1f} °C is implausible — probe out of the water?"
                )
    if reason:
        issues["temp"] = reason
        runtime.pop("tempReading", None)
        for entity in (heater, cooler):
            if entity:
                await _async_spawning_set_plug(hass, entity, False)
        await _async_spawning_notify_once(
            hass, config, "temp_sensor", 6 * 3600,
            "Spawning temperature control failed safe",
            f"{reason.capitalize()}. Heater and cooling were switched OFF — the inline "
            "guard thermostat holds the tank until the sensor recovers.",
        )
        return
    issues.pop("temp", None)
    runtime["tempReading"] = round(reading, 2)

    rt = float(state["targetTempC"])
    tol = SPAWNING_TEMP_TOLERANCE_C
    if abs(reading - rt) > SPAWNING_TEMP_DRIFT_ALERT_C:
        await _async_spawning_notify_once(
            hass, config, "temp_drift", 6 * 3600,
            "Tank temperature drifting from the seasonal target",
            f"The tank reads {reading:.1f} °C against the {rt:.1f} °C seasonal target. "
            "Check the heater, the fan, and the inline guard thermostat's setpoint.",
        )
    try:
        max_c = float(temp_cfg.get("maxC", 27.5))
        min_c = float(temp_cfg.get("minC", 22.0))
    except (TypeError, ValueError):
        max_c, min_c = 27.5, 22.0

    for role, entity, on_side, off_side, clamp_off in (
        ("heater", heater, reading < rt - tol, reading > rt + tol, reading >= max_c),
        ("cool", cooler, reading > rt + tol, reading < rt - tol, reading <= min_c),
    ):
        if not entity:
            issues.pop(f"temp_{role}", None)
            continue
        st_e = hass.states.get(entity)
        if st_e is None or st_e.state in UNAVAILABLE_STATES:
            issues[f"temp_{role}"] = f"{role} plug ({entity}) is unavailable"
            await _async_spawning_notify_once(
                hass, config, f"unavailable_temp_{role}", 6 * 3600,
                "Spawning temperature plug unreachable",
                f"The {role} plug ({entity}) is unavailable — seasonal temperature "
                "control cannot switch it.",
            )
            continue
        issues.pop(f"temp_{role}", None)
        actual = st_e.state == "on"
        desired = True if on_side else False if off_side else actual  # band = hysteresis hold
        if clamp_off:
            desired = False  # hard clamp beats the curve, always
        if desired != actual:
            await _async_spawning_set_plug(hass, entity, desired)


async def _async_spawning_tick(
    hass: HomeAssistant, entry: OpenReefConfigEntry, now_local: datetime
) -> None:
    """Reconcile the spawning plugs to the program's desired state at ``now_local``.

    Also runs publish-only (feature on, execution disarmed/apex): the RT target
    sensor refreshes and spawn-window captures fire, but nothing is switched."""
    config = _config_from_entry(entry)
    sp_cfg = config.get("spawningProgram", {})
    execution = _spawning_execution_cfg(config)
    exec_enabled = _spawning_execution_enabled(execution)
    if not exec_enabled and not (isinstance(sp_cfg, dict) and sp_cfg.get("enabled")):
        return
    state = spawning.execution_desired_state(sp_cfg, now_local)
    runtime = hass.data.setdefault(DOMAIN, {}).setdefault(SPAWNING_RUNTIME, {})
    issues = runtime.setdefault("issues", {})
    if not state.get("valid"):
        issues["program"] = "the spawning program has no valid reef preset"
        _spawning_publish_target_sensor(hass, sp_cfg, None)
        return
    issues.pop("program", None)
    _spawning_publish_target_sensor(hass, sp_cfg, state)
    _spawning_maybe_capture_window_night(hass, entry, runtime, state, now_local)
    if not exec_enabled:
        return
    asserted = runtime.setdefault("asserted", {})
    overrides = runtime.setdefault("overrides", {})
    policy = execution.get("overridePolicy", "hold")
    activity: list[tuple[str, str]] = []

    for channel, entity_key, label in _SPAWNING_EXEC_CHANNELS:
        entity = execution.get(entity_key)
        if not entity:
            asserted.pop(channel, None)
            overrides.pop(channel, None)
            issues.pop(channel, None)
            continue
        desired = bool(state.get(channel))
        st = hass.states.get(entity)
        if st is None or st.state in ("unavailable", "unknown"):
            issues[channel] = f"{label} plug ({entity}) is unavailable"
            await _async_spawning_notify_once(
                hass, config, f"unavailable_{channel}", 6 * 3600,
                "Spawning plug unreachable",
                f"The spawning {label} plug ({entity}) is unavailable — the program "
                "cannot switch it. It will keep trying every minute.",
            )
            continue
        issues.pop(channel, None)
        actual = st.state == "on"

        override = overrides.get(channel)
        if override is not None:
            if bool(override.get("desiredAtOverride")) != desired:
                overrides.pop(channel, None)  # the natural transition passed — program resumes
            else:
                if (
                    channel == "light" and not desired and actual
                    and state.get("inSpawnWindow")
                ):
                    fired = await _async_spawning_notify_once(
                        hass, config, "spawn_window_light", 2 * 3600,
                        "Spawn-window night — lights are on",
                        "Tonight is inside the predicted spawn window and the daylight "
                        "plug was switched on by hand. Genuinely dark nights matter — "
                        "light pollution desynchronises spawning.",
                    )
                    if fired:
                        activity.append(("Spawn-window night with the lights on — dark nights matter", "warning"))
                continue  # respect the human until the next sunrise/sunset

        if actual == desired:
            asserted[channel] = desired
            continue

        prior = asserted.get(channel)
        if prior == desired and policy == "hold":
            # We already put this plug where the program wants it and something
            # else moved it — that's a human. Hold until the next transition.
            overrides[channel] = {
                "since": dt_util.utcnow().isoformat(),
                "desiredAtOverride": desired,
            }
            activity.append((
                f"Spawning {label} plug flipped by hand — holding until the next "
                f"{'sunset' if desired else 'sunrise'}",
                "info",
            ))
            continue

        domain = entity.split(".", 1)[0]
        try:
            await hass.services.async_call(
                domain, "turn_on" if desired else "turn_off",
                {ATTR_ENTITY_ID: entity}, blocking=True, context=None,
            )
        except Exception:  # noqa: BLE001 — a dead plug must not kill the tick; retry next minute
            _LOGGER.exception("Spawning execution could not switch %s", entity)
            issues[channel] = f"could not switch the {label} plug ({entity})"
            continue
        asserted[channel] = desired
        if channel == "light":
            if prior is None:
                activity.append((
                    f"Spawning program took the daylight plug — switched {'on' if desired else 'off'}",
                    "control",
                ))
            elif desired:
                activity.append((
                    f"Spawning sunrise — lights on until {state.get('sunset')} "
                    f"({state.get('dayLengthHours')} h {state.get('reefMonthName')} day)",
                    "control",
                ))
            else:
                night_note = (
                    " — spawn-window night, keep the room dark" if state.get("inSpawnWindow") else ""
                )
                activity.append((f"Spawning sunset — lights off{night_note}", "control"))

    await _async_spawning_temp_reconcile(hass, config, execution, state, runtime)

    if activity:
        for message, activity_type in activity:
            _append_activity(config, message, activity_type)
        await _async_save_config(hass, entry, config)


def _effective_lighting_cfg(
    config: dict[str, Any], now_local: datetime | None = None
) -> dict[str, Any] | None:
    """``lightingSchedule`` with mode "spawning" resolved to the executed spawning
    program's own sunrise/sunset — one sun model, so the PAR-alert gate and the
    plugs can never disagree. Falls back to mode "off" (the callers' never-
    suppress path) when the program can't produce a window."""
    lighting_cfg = config.get("lightingSchedule")
    if not isinstance(lighting_cfg, dict):
        return None
    if lighting_cfg.get("mode") != "spawning":
        return lighting_cfg
    state = spawning.execution_desired_state(
        config.get("spawningProgram") or {}, now_local or dt_util.now()
    )
    if not state.get("valid"):
        return {**lighting_cfg, "mode": "off"}
    return {**lighting_cfg, "mode": "simple", "onTime": state["sunrise"], "offTime": state["sunset"]}


@websocket_api.websocket_command({vol.Required("type"): "openreef/spawning_execution_status"})
@callback
def websocket_spawning_execution_status(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Live execution snapshot for the Spawning tab: the program's desired state
    right now, the configured plugs' actual states, and any overrides/issues."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    sp_cfg = config.get("spawningProgram", {})
    execution = _spawning_execution_cfg(config)
    state = spawning.execution_desired_state(sp_cfg, dt_util.now())
    runtime = hass.data.setdefault(DOMAIN, {}).get(SPAWNING_RUNTIME) or {}
    entities: dict[str, Any] = {}
    for channel, entity_key, _label in _SPAWNING_EXEC_CHANNELS:
        ent = execution.get(entity_key)
        if ent:
            st = hass.states.get(ent)
            entities[channel] = {"entity": ent, "state": st.state if st else None}
    temp_cfg = execution.get("temp") if isinstance(execution.get("temp"), dict) else {}
    for channel, entity_key in (
        ("tempSensor", "sensorEntity"), ("heater", "heaterEntity"), ("cool", "coolEntity"),
    ):
        ent = temp_cfg.get(entity_key)
        if ent:
            st = hass.states.get(ent)
            entities[channel] = {"entity": ent, "state": st.state if st else None}
    overrides = {
        channel: {
            "since": data.get("since"),
            "resumesAt": "sunset" if data.get("desiredAtOverride") else "sunrise",
        }
        for channel, data in (runtime.get("overrides") or {}).items()
    }
    connection.send_result(
        msg["id"],
        {
            "execution": execution,
            "state": state,
            "entities": entities,
            "runtime": {
                "overrides": overrides,
                "issues": sorted((runtime.get("issues") or {}).values()),
                "controlling": _spawning_execution_enabled(execution),
                "tempReading": runtime.get("tempReading"),
            },
        },
    )


@websocket_api.websocket_command({vol.Required("type"): "openreef/spawning_execution_resume"})
@websocket_api.require_admin
@callback
def websocket_spawning_execution_resume(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Clear a manual-override hold early — the next tick re-asserts the program."""
    runtime = hass.data.setdefault(DOMAIN, {}).setdefault(SPAWNING_RUNTIME, {})
    runtime["overrides"] = {}
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command({vol.Required("type"): "openreef/list_reef_presets"})
@callback
def websocket_list_reef_presets(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the curated reef presets for the spawning location picker."""
    connection.send_result(msg["id"], {"presets": spawning.list_presets()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/generate_spawning_program",
        vol.Optional("reefPreset"): cv.string,
        vol.Optional("year"): vol.All(vol.Coerce(int), vol.Range(min=2000, max=2100)),
        vol.Optional("offsetMonths"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=SPAWNING_OFFSET_MONTHS_MAX)
        ),
        vol.Optional("solarNoonHour"): vol.All(vol.Coerce(float), vol.Range(min=0, max=23.5)),
        vol.Optional("tempUnit"): vol.In(["C", "F", "c", "f"]),
        vol.Optional("tempProbe"): cv.string,
    }
)
@callback
def websocket_generate_spawning_program(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Compile a copy-paste-ready Apex spawning program for a reef preset.

    Read-only computation — falls back to the saved spawningProgram selection for
    any param the caller omits.
    """
    config = _config_from_entry(_first_entry(hass))
    saved = config.get("spawningProgram", {})
    if not isinstance(saved, dict):
        saved = {}
    preset_id = msg.get("reefPreset") or saved.get("reefPreset") or "gbr_central"
    if preset_id not in REEF_PRESETS:
        connection.send_error(msg["id"], "unknown_preset", f"Unknown reef preset '{preset_id}'")
        return
    now = datetime.now(timezone.utc)
    year = msg.get("year") or now.year
    offset = msg.get("offsetMonths")
    if offset is None:
        offset = saved.get("offsetMonths", 0)
    noon = msg.get("solarNoonHour")
    if noon is None:
        noon = saved.get("solarNoonHour", SPAWNING_DEFAULT_SOLAR_NOON_HOUR)
    unit = msg.get("tempUnit") or saved.get("tempUnit") or "C"
    probe = msg.get("tempProbe") or saved.get("tempProbe") or "Tmp"
    try:
        program = spawning.generate_program(
            preset_id,
            int(year),
            offset_months=int(offset or 0),
            solar_noon_hour=float(noon),
            temp_unit=str(unit),
            temp_probe=str(probe).strip()[:16] or "Tmp",
            today=now,
        )
    except KeyError:
        connection.send_error(msg["id"], "unknown_preset", f"Unknown reef preset '{preset_id}'")
        return
    connection.send_result(msg["id"], {"program": program})


@websocket_api.websocket_command({vol.Required("type"): "openreef/lighting_window"})
@callback
def websocket_lighting_window(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return today's computed lighting-on window + whether the lights are on now."""
    config = _config_from_entry(_first_entry(hass))
    raw_mode = (config.get("lightingSchedule") or {}).get("mode") if isinstance(config.get("lightingSchedule"), dict) else "off"
    lighting_cfg = _effective_lighting_cfg(config) or {}
    summary = spawning.lighting_window_summary(lighting_cfg, dt_util.now())
    if raw_mode == "spawning":
        summary["mode"] = "spawning"  # resolved via the executed spawning program
    connection.send_result(msg["id"], {"lighting": summary})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/import_icp_report",
        vol.Required("report"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_import_icp_report(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Store a parsed ICP lab report and fan its core params into the reading streams.

    The panel parses the lab file (CSV/PDF/xlsx) client-side; here we re-validate it
    authoritatively (``icp.normalise_report`` recomputes units/flags), append or
    replace by id (so a re-import is idempotent), fan the overlapping core params
    (Alk/Ca/Mg/NO3/PO4/salinity) into ``manualReadings`` tagged ``source="ICP:<lab>"``
    so reef-score/dosing/trends pick them up, then persist.
    """
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    report = icp.normalise_report(msg["report"])
    if report is None:
        connection.send_error(
            msg["id"], "invalid_report", "Could not read a valid ICP report from that file"
        )
        return

    config = _config_from_entry(entry)
    reports = config.get("icpReports")
    reports = (
        [r for r in reports if isinstance(r, dict) and r.get("id") != report["id"]]
        if isinstance(reports, list)
        else []
    )
    reports.append(report)
    config["icpReports"] = reports

    manual = config.setdefault("manualReadings", {})
    if not isinstance(manual, dict):
        manual = {}
        config["manualReadings"] = manual
    prefix = f"{report['id']}:"
    for parameter, rows in icp.core_fanout(report).items():
        existing = manual.get(parameter)
        kept = (
            [r for r in existing if isinstance(r, dict) and not str(r.get("id", "")).startswith(prefix)]
            if isinstance(existing, list)
            else []
        )
        kept.extend(rows)
        manual[parameter] = kept

    _append_activity(config, f"ICP report imported: {report['lab']} ({len(report['elements'])} elements)")
    saved = await _async_save_config(hass, entry, config)
    connection.send_result(
        msg["id"],
        {
            "success": True,
            "report": report,
            "config": saved,
            "drift": icp.drift_check(report, saved.get("manualReadings", {})),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/icp_dashboard",
        vol.Optional("settings"): dict,
    }
)
@callback
def websocket_icp_dashboard(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the unified ICP dashboard payload.

    Brand/range/group filters are dashboard-only. They do not change stored reports,
    manual-reading fan-out, reef score, or dosing-advisor inputs.
    """
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    settings = {
        **(config.get("icpDashboard") if isinstance(config.get("icpDashboard"), dict) else {}),
        **(msg.get("settings") if isinstance(msg.get("settings"), dict) else {}),
    }
    connection.send_result(
        msg["id"],
        icp.dashboard_payload(
            config.get("icpReports", []),
            config.get("manualReadings", {}),
            settings,
        ),
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/delete_icp_report",
        vol.Required("reportId"): cv.string,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_delete_icp_report(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete a stored ICP report and the core readings it fanned out (by id prefix)."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    report_id = msg["reportId"]
    config = _config_from_entry(entry)
    reports = config.get("icpReports")
    if isinstance(reports, list):
        config["icpReports"] = [
            r for r in reports if not (isinstance(r, dict) and r.get("id") == report_id)
        ]
    prefix = f"{report_id}:"
    manual = config.get("manualReadings")
    if isinstance(manual, dict):
        for parameter, rows in list(manual.items()):
            if isinstance(rows, list):
                manual[parameter] = [
                    r for r in rows
                    if not (isinstance(r, dict) and str(r.get("id", "")).startswith(prefix))
                ]
    saved = await _async_save_config(hass, entry, config)
    connection.send_result(msg["id"], {"success": True, "config": saved})


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


def _clear_vision(hass: HomeAssistant) -> None:
    """Tear down all vision wiring (subscriptions, tick, runtime, fingerprint)."""
    store = hass.data.setdefault(DOMAIN, {})
    arm_task = store.pop(VISION_ARM_TASK, None)
    if arm_task is not None:
        arm_task.cancel()
    event_unsub = store.pop(VISION_UNSUB, None)
    if event_unsub is not None:
        try:
            event_unsub()
        except Exception:  # noqa: BLE001 - teardown must never raise
            pass
    for state_unsub in store.pop(VISION_STATE_UNSUB, None) or []:
        try:
            state_unsub()
        except Exception:  # noqa: BLE001 - teardown must never raise
            pass
    tick_unsub = store.pop(VISION_TICK_UNSUB, None)
    if tick_unsub is not None:
        try:
            tick_unsub()
        except Exception:  # noqa: BLE001 - teardown must never raise
            pass
    store.pop(VISION_RUNTIME, None)
    store.pop(VISION_FINGERPRINT, None)


async def _async_setup_vision(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any]
) -> None:
    """Arm (or refresh) vision. Fully fenced — must never raise into entry setup
    or a config save, mirroring the _async_capture_event discipline.

    Re-arms ONLY when the vision fingerprint changes: _async_save_config calls
    this from ~50 unrelated call sites (mode applies, captures, AWC legs, panel
    saves) and none of them may destroy vision runtime state (an open feeding
    session, last-seen timestamps, zone counters) or churn the MQTT subscription.
    """
    try:
        store = hass.data.setdefault(DOMAIN, {})
        vision_cfg = config.get("vision") if isinstance(config.get("vision"), dict) else {}
        vision_fp = vision.fingerprint(vision_cfg)
        if store.get(VISION_FINGERPRINT) == vision_fp:
            return
        _clear_vision(hass)
        if vision_fp == "disabled":
            store[VISION_FINGERPRINT] = vision_fp
            return
        now_ts = dt_util.utcnow().timestamp()
        runtime = vision.new_runtime(
            list(vision_cfg.get("species") or []),
            list(vision_cfg.get("zones") or []),
            now_ts,
            str(vision_cfg.get("surfaceZone") or "surface"),
        )
        vision.rehydrate(runtime, config.get("visionSummary"), now_ts)
        store[VISION_RUNTIME] = runtime
        store[VISION_ARM_TASK] = hass.async_create_task(
            _async_arm_vision(hass, dict(vision_cfg))
        )

        async def _tick(_now) -> None:
            await _async_vision_tick(hass, entry)

        store[VISION_TICK_UNSUB] = async_track_time_interval(
            hass, _tick, timedelta(minutes=VISION_TICK_MINUTES)
        )
        # Fingerprint is committed LAST: if any wiring step above raised, the
        # next save retries setup instead of no-opping on a half-built stack.
        store[VISION_FINGERPRINT] = vision_fp
    except Exception:  # noqa: BLE001 - vision must never break OpenReef setup
        _clear_vision(hass)
        _LOGGER.exception("OpenReef vision: setup failed; will retry on next save")


async def _async_arm_vision(hass: HomeAssistant, vision_cfg: dict[str, Any]) -> None:
    """Background MQTT subscribe (never inline in entry setup — the broker may be
    retrying for up to ~50s at boot). Retried by the tick while unsubscribed."""
    try:
        try:
            from homeassistant.components import mqtt  # soft dependency
        except ImportError:
            _LOGGER.warning(
                "OpenReef vision: the MQTT integration is not available; vision stays idle"
            )
            return
        try:
            mqtt_ready = await mqtt.async_wait_for_mqtt_client(hass)
        except Exception:  # noqa: BLE001 - no MQTT config entry at all
            mqtt_ready = False
        if not mqtt_ready:
            _LOGGER.warning("OpenReef vision: MQTT not connected yet; will retry")
            return
        store = hass.data.setdefault(DOMAIN, {})
        runtime = store.get(VISION_RUNTIME)
        if runtime is None:
            return
        topic_prefix = str(vision_cfg.get("topicPrefix") or "frigate")
        camera_name = str(vision_cfg.get("cameraName") or "")

        @callback
        def _on_frigate_event(msg) -> None:
            try:
                event = vision.parse_frigate_event(msg.payload)
                if event and (not camera_name or event["camera"] == camera_name):
                    vision.apply_event(runtime, event, dt_util.utcnow().timestamp())
            except Exception:  # noqa: BLE001 - a broker payload must never break us
                _LOGGER.debug("OpenReef vision: dropped malformed event", exc_info=True)

        # Subscribe everything into locals first; the store is only written once
        # ALL subscriptions exist. VISION_UNSUB doubles as the tick's "armed"
        # sentinel, so committing it early on a partial failure would both kill
        # the retry and leak the already-created state subscriptions.
        created: list = []
        try:
            event_unsub = await mqtt.async_subscribe(
                hass, f"{topic_prefix}/events", _on_frigate_event
            )
            created.append(event_unsub)
            state_unsubs = []
            if camera_name:
                for state_kind, state_topic in (
                    ("anemone", f"{topic_prefix}/{camera_name}/classification/anemone_state"),
                    ("tank", f"{topic_prefix}/{camera_name}/classification/tank_state"),
                    ("count", f"{topic_prefix}/{camera_name}/all"),
                ):

                    @callback
                    def _on_state(msg, _kind: str = state_kind) -> None:
                        vision.apply_state_topic(runtime, _kind, msg.payload)

                    state_unsub = await mqtt.async_subscribe(hass, state_topic, _on_state)
                    created.append(state_unsub)
                    state_unsubs.append(state_unsub)
        except Exception:
            for unsub in created:
                try:
                    unsub()
                except Exception:  # noqa: BLE001 - cleanup must never raise
                    pass
            raise
        store[VISION_STATE_UNSUB] = state_unsubs
        store[VISION_UNSUB] = event_unsub
        _LOGGER.info("OpenReef vision: subscribed to %s/events", topic_prefix)
    except Exception:  # noqa: BLE001 - arm failures are retried, never fatal
        _LOGGER.exception("OpenReef vision: MQTT subscribe failed; will retry")


async def _async_vision_tick(hass: HomeAssistant, entry: OpenReefConfigEntry) -> None:
    """5-minute cadence: re-arm if the broker was down, evaluate cooldown-gated
    alerts, and flush the tiny summary hourly for restart rehydration."""
    try:
        store = hass.data.setdefault(DOMAIN, {})
        runtime = store.get(VISION_RUNTIME)
        if runtime is None:
            return
        config = _config_from_entry(entry)
        vision_cfg = config.get("vision") if isinstance(config.get("vision"), dict) else {}
        if not vision_cfg.get("enabled"):
            return
        arm_task = store.get(VISION_ARM_TASK)
        if store.get(VISION_UNSUB) is None and (arm_task is None or arm_task.done()):
            store[VISION_ARM_TASK] = hass.async_create_task(
                _async_arm_vision(hass, dict(vision_cfg))
            )
        now_ts = dt_util.utcnow().timestamp()
        alerts_cfg = (
            vision_cfg.get("alerts") if isinstance(vision_cfg.get("alerts"), dict) else {}
        )
        missing_hours = float(alerts_cfg.get("missingFishHours") or 0)
        if missing_hours > 0:
            missing = vision.missing_species(runtime, now_ts, missing_hours)
            for species in missing:
                if vision.should_notify(
                    runtime, f"missing:{species}", now_ts, VISION_NOTIFY_COOLDOWN_S
                ):
                    await _async_send_mode_notification(
                        hass,
                        config,
                        f"openreef_vision_missing_{species.lower().replace(' ', '_')}",
                        "Fish not seen",
                        f"{species} has not been positively identified in over "
                        f"{int(missing_hours)} hours. Last known sighting may need a look.",
                    )
            for species in runtime["lastSeen"]:
                if species not in missing:
                    vision.clear_notify(runtime, f"missing:{species}")
        if alerts_cfg.get("surfaceDistress"):
            loiterers = vision.surface_loiterers(runtime, now_ts, VISION_SURFACE_SECONDS)
            if loiterers:
                if vision.should_notify(runtime, "surface", now_ts, VISION_NOTIFY_COOLDOWN_S):
                    await _async_send_mode_notification(
                        hass,
                        config,
                        "openreef_vision_surface",
                        "Possible fish distress",
                        f"A fish has been at the water surface for over "
                        f"{VISION_SURFACE_SECONDS // 60} minutes. Check oxygen and flow.",
                    )
            else:
                vision.clear_notify(runtime, "surface")
        if now_ts - runtime.get("lastFlushAt", 0) >= VISION_FLUSH_INTERVAL_S:
            runtime["lastFlushAt"] = now_ts
            # Lightweight persist of the tiny summary (the watchdog's
            # _persist_entry_config pattern): a FRESH config read so a user
            # save landing during the notification awaits above is never
            # clobbered, and no scheduler re-arms / alert re-evaluation /
            # capture triggers from the heavy save path.
            fresh_config = _config_from_entry(entry)
            fresh_config["visionSummary"] = vision.summary(runtime, now_ts)
            _persist_entry_config(hass, entry, fresh_config)
    except Exception:  # noqa: BLE001 - the tick shares a loop with safety timers
        _LOGGER.exception("OpenReef vision: tick failed")


@websocket_api.websocket_command({vol.Required("type"): "openreef/vision_summary"})
@websocket_api.async_response
async def websocket_vision_summary(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the live vision aggregates + recent feeding reports for the panel."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    config = _config_from_entry(entry)
    vision_cfg = config.get("vision") if isinstance(config.get("vision"), dict) else {}
    store = hass.data.get(DOMAIN)
    store = store if isinstance(store, dict) else {}
    runtime = store.get(VISION_RUNTIME)
    reports = config.get("visionReports")
    connection.send_result(
        msg["id"],
        {
            "enabled": bool(vision_cfg.get("enabled")),
            "connected": store.get(VISION_UNSUB) is not None,
            "summary": (
                vision.summary(runtime, dt_util.utcnow().timestamp())
                if runtime is not None
                else (config.get("visionSummary") or None)
            ),
            "reports": reports[:VISION_MAX_REPORTS] if isinstance(reports, list) else [],
        },
    )


# --- Guardian (Lagertha live avatar) ----------------------------------------
# Stage A: read-only brain. Chained voice loop = OpenAI STT -> Claude tool loop
# -> OpenAI TTS. All pure prompt/tool/formatting logic lives in guardian.py;
# this section owns only what needs I/O: key storage, HA state gathering and
# the network calls. The anthropic/aiohttp imports are lazy so the
# dependency-free CI (tests/_ha_stubs) never loads them.


def _guardian_keys(entry: ConfigEntry | None) -> dict[str, str]:
    if entry is None:
        return {}
    keys = entry.options.get(CONF_GUARDIAN_KEYS)
    return keys if isinstance(keys, dict) else {}


def _guardian_snapshot(hass: HomeAssistant, config: dict[str, Any]) -> dict[str, Any]:
    """Assemble the read-ring context (plain dicts) that guardian.run_tool
    answers from. Gathering lives here (HA access); formatting and caps live
    in the pure engine."""
    sensors_rows: list[dict[str, Any]] = []
    sensors = config.get("sensors")
    for sensor_id, sensor in (sensors.items() if isinstance(sensors, dict) else []):
        if not isinstance(sensor, dict) or not sensor.get("enabled"):
            continue
        entity_id = _normalise_entity_id(sensor.get("entity_id"))
        value: Any = None
        available = False
        if entity_id:
            state = hass.states.get(entity_id)
            if state is not None and state.state not in UNAVAILABLE_STATES:
                available = True
                try:
                    value = round(float(state.state), 3)
                except (TypeError, ValueError):
                    value = state.state
        sensors_rows.append(
            {
                "id": sensor_id,
                "label": sensor.get("label"),
                "value": value,
                "unit": sensor.get("unit"),
                "min": sensor.get("min"),
                "max": sensor.get("max"),
                "available": available,
            }
        )
    tank = config.get("tank") if isinstance(config.get("tank"), dict) else {}
    alerts = config.get("alerts") if isinstance(config.get("alerts"), dict) else {}
    return {
        "tank": {
            "name": tank.get("name"),
            "profile": tank.get("profile"),
            "volumeLitres": _awc_effective_tank_l(config),
        },
        "sensors": sensors_rows,
        "manualReadings": config.get("manualReadings"),
        "dosing": config.get("dosing"),
        "awc": config.get("automaticWaterChange"),
        "awcTankLitres": _awc_effective_tank_l(config),
        "maintenanceDue": _maintenance_due_items(config),
        "icpReports": config.get("icpReports"),
        "visionSummary": config.get("visionSummary"),
        "alertHistory": alerts.get("history"),
    }


def _guardian_anthropic_client(api_key: str):
    """Lazy SDK import behind a seam tests monkeypatch with a fake client."""
    from anthropic import AsyncAnthropic  # noqa: PLC0415 - CI must not import this

    return AsyncAnthropic(api_key=api_key)


def _guardian_http(hass: HomeAssistant):
    """Shared aiohttp session behind a seam tests monkeypatch."""
    from homeassistant.helpers.aiohttp_client import (  # noqa: PLC0415
        async_get_clientsession,
    )

    return async_get_clientsession(hass)


async def _async_guardian_reply(
    hass: HomeAssistant, config: dict[str, Any], keys: dict[str, str], history: Any
) -> str:
    """One Guardian turn: Claude + read-ring tools until it stops calling them."""
    guardian_cfg = (
        config.get("guardian") if isinstance(config.get("guardian"), dict) else {}
    )
    messages: list[dict[str, Any]] = list(guardian_engine.fold_history(history))
    if not messages:
        raise HomeAssistantError("Nothing to reply to")
    client = _guardian_anthropic_client(keys.get("anthropic", ""))
    snapshot = _guardian_snapshot(hass, config)
    # System + tools are byte-stable across a session; the cache breakpoint
    # means every turn after the first reads the prefix at ~0.1x price.
    system = [
        {
            "type": "text",
            "text": guardian_engine.persona_prompt(config),
            "cache_control": {"type": "ephemeral"},
        }
    ]
    tools = guardian_engine.build_tools()
    response = None
    for _round in range(GUARDIAN_MAX_TOOL_ROUNDS):
        response = await client.messages.create(
            model=GUARDIAN_MODEL,
            max_tokens=GUARDIAN_MAX_TOKENS,
            system=system,
            tools=tools,
            messages=messages,
            output_config={"effort": guardian_cfg.get("effort", "low")},
        )
        if response.stop_reason == "refusal":
            return "I'd rather not answer that one, keeper."
        if response.stop_reason != "tool_use":
            break
        # Echo the assistant content verbatim (incl. thinking blocks — the
        # API requires them back unchanged when continuing on the same model).
        messages.append({"role": "assistant", "content": response.content})
        tool_results = [
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": guardian_engine.tool_result_json(
                    block.name, block.input, snapshot
                ),
            }
            for block in response.content
            if getattr(block, "type", None) == "tool_use"
        ]
        messages.append({"role": "user", "content": tool_results})
    text = "".join(
        block.text
        for block in (response.content if response is not None else [])
        if getattr(block, "type", None) == "text"
    ).strip()
    return text or "I heard you, keeper, but I have nothing useful to add."


async def _async_guardian_transcribe(
    hass: HomeAssistant, api_key: str, audio: bytes, mime: str
) -> str:
    """One PTT utterance -> text via OpenAI transcription."""
    import aiohttp  # noqa: PLC0415 - lazy so the dependency-free CI never loads it

    ext = "webm"
    if isinstance(mime, str) and "/" in mime:
        ext = mime.split("/", 1)[1].split(";", 1)[0][:8] or "webm"
    form = aiohttp.FormData()
    form.add_field(
        "file", audio, filename=f"utterance.{ext}", content_type=mime or "audio/webm"
    )
    form.add_field("model", GUARDIAN_STT_MODEL)
    session = _guardian_http(hass)
    async with session.post(
        "https://api.openai.com/v1/audio/transcriptions",
        data=form,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=aiohttp.ClientTimeout(total=60),
    ) as resp:
        if resp.status != 200:
            raise HomeAssistantError(f"Transcription failed (HTTP {resp.status})")
        data = await resp.json()
    text = data.get("text") if isinstance(data, dict) else None
    return text.strip() if isinstance(text, str) else ""


async def _async_guardian_tts(
    hass: HomeAssistant,
    api_key: str,
    guardian_cfg: dict[str, Any],
    text: str,
    fmt: str,
) -> tuple[str, str]:
    """Reply text -> base64 audio. mp3 for direct <audio> playback; pcm
    (24 kHz s16le) when the Simli face needs raw samples for lip-sync."""
    import aiohttp  # noqa: PLC0415

    response_format = "pcm" if fmt == "pcm" else "mp3"
    session = _guardian_http(hass)
    async with session.post(
        "https://api.openai.com/v1/audio/speech",
        json={
            "model": GUARDIAN_TTS_MODEL,
            "voice": guardian_cfg.get("voice", "shimmer"),
            "input": text[:4096],
            "response_format": response_format,
        },
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=aiohttp.ClientTimeout(total=60),
    ) as resp:
        if resp.status != 200:
            raise HomeAssistantError(f"Speech synthesis failed (HTTP {resp.status})")
        audio = await resp.read()
    return base64.b64encode(audio).decode("ascii"), response_format


async def _async_guardian_validate_keys(
    hass: HomeAssistant, keys: dict[str, str], changed: set[str]
) -> dict[str, str]:
    """Best-effort live check of newly provided keys so a typo surfaces at
    save time, not on the first conversation. Returns {key_name: problem}."""
    problems: dict[str, str] = {}
    if "anthropic" in changed and keys.get("anthropic"):
        try:
            client = _guardian_anthropic_client(keys["anthropic"])
            await client.models.retrieve(GUARDIAN_MODEL)
        except ImportError:
            problems["anthropic"] = "anthropic package not installed yet — restart Home Assistant"
        except Exception as exc:  # noqa: BLE001 - report, never raise, at save time
            problems["anthropic"] = f"Key check failed: {type(exc).__name__}"
    if "openai" in changed and keys.get("openai"):
        try:
            import aiohttp  # noqa: PLC0415

            session = _guardian_http(hass)
            async with session.get(
                f"https://api.openai.com/v1/models/{GUARDIAN_TTS_MODEL}",
                headers={"Authorization": f"Bearer {keys['openai']}"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 401:
                    problems["openai"] = "OpenAI rejected the key (401)"
                elif resp.status != 200:
                    problems["openai"] = f"Key check failed (HTTP {resp.status})"
        except Exception as exc:  # noqa: BLE001
            problems["openai"] = f"Key check failed: {type(exc).__name__}"
    return problems


@websocket_api.websocket_command({vol.Required("type"): "openreef/guardian_status"})
@websocket_api.async_response
async def websocket_guardian_status(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Key status (masked) + guardian settings for the panel tab."""
    entry = _first_entry(hass)
    config = _config_from_entry(entry)
    connection.send_result(
        msg["id"],
        {
            "keys": guardian_engine.keys_status(_guardian_keys(entry)),
            "settings": config.get("guardian", {}),
            "model": GUARDIAN_MODEL,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/guardian_set_keys",
        vol.Optional("anthropic"): str,
        vol.Optional("openai"): str,
        vol.Optional("simli"): str,
        vol.Optional("simli_face_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_guardian_set_keys(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Store BYO API keys. Missing field = unchanged, empty string = clear.
    Keys live outside CONF_SETTINGS so config export can never leak them."""
    entry = _first_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "OpenReef is not configured")
        return
    updates = {name: msg[name] for name in ("anthropic", "openai", "simli") if name in msg}
    if "simli_face_id" in msg:
        updates["simliFaceId"] = msg["simli_face_id"]
    merged = guardian_engine.clean_keys(_guardian_keys(entry), updates)
    problems = await _async_guardian_validate_keys(hass, merged, set(updates))
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_GUARDIAN_KEYS: merged}
    )
    connection.send_result(
        msg["id"],
        {"keys": guardian_engine.keys_status(merged), "problems": problems},
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/guardian_chat",
        vol.Required("history"): list,
    }
)
@websocket_api.async_response
async def websocket_guardian_chat(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Text turn: history (incl. the new user message) -> Lagertha's reply."""
    entry = _first_entry(hass)
    config = _config_from_entry(entry)
    keys = _guardian_keys(entry)
    if not guardian_engine.keys_status(keys)["anthropic"]["set"]:
        connection.send_error(
            msg["id"], "guardian_keys", "Add an Anthropic API key in the Guardian tab first"
        )
        return
    try:
        reply = await _async_guardian_reply(hass, config, keys, msg["history"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "guardian_error", str(err))
        return
    except Exception as err:  # noqa: BLE001 - network/SDK errors must not kill the WS
        connection.send_error(
            msg["id"], "guardian_error", f"Guardian brain error: {type(err).__name__}"
        )
        return
    connection.send_result(msg["id"], {"reply": reply})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "openreef/guardian_voice",
        vol.Required("audio"): str,
        vol.Optional("mime"): str,
        vol.Optional("history"): list,
        vol.Optional("tts", default="mp3"): vol.In(guardian_engine.TTS_FORMATS),
    }
)
@websocket_api.async_response
async def websocket_guardian_voice(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Voice turn: base64 PTT audio -> transcript -> reply -> spoken audio."""
    entry = _first_entry(hass)
    config = _config_from_entry(entry)
    keys = _guardian_keys(entry)
    status = guardian_engine.keys_status(keys)
    if not status["ready"]:
        connection.send_error(
            msg["id"],
            "guardian_keys",
            "Add your Anthropic and OpenAI API keys in the Guardian tab first",
        )
        return
    if len(msg["audio"]) > GUARDIAN_MAX_AUDIO_B64:
        connection.send_error(msg["id"], "audio_too_large", "Utterance too long")
        return
    try:
        audio = base64.b64decode(msg["audio"], validate=True)
    except (ValueError, TypeError):
        connection.send_error(msg["id"], "bad_audio", "Audio payload is not valid base64")
        return
    try:
        transcript = await _async_guardian_transcribe(
            hass, keys["openai"], audio, msg.get("mime", "audio/webm")
        )
        if not transcript:
            connection.send_result(
                msg["id"],
                {"transcript": "", "reply": "", "audio": None, "audioFormat": None},
            )
            return
        history = list(msg.get("history") or [])
        history.append({"role": "user", "content": transcript})
        reply = await _async_guardian_reply(hass, config, keys, history)
        audio_out = None
        out_fmt = None
        if msg["tts"] != "none":
            guardian_cfg = (
                config.get("guardian") if isinstance(config.get("guardian"), dict) else {}
            )
            audio_out, out_fmt = await _async_guardian_tts(
                hass, keys["openai"], guardian_cfg, reply, msg["tts"]
            )
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "guardian_error", str(err))
        return
    except Exception as err:  # noqa: BLE001
        connection.send_error(
            msg["id"], "guardian_error", f"Guardian voice error: {type(err).__name__}"
        )
        return
    connection.send_result(
        msg["id"],
        {
            "transcript": transcript,
            "reply": reply,
            "audio": audio_out,
            "audioFormat": out_fmt,
        },
    )


@websocket_api.websocket_command({vol.Required("type"): "openreef/guardian_simli_session"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_guardian_simli_session(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Hand the browser the Simli credentials it needs to open the WebRTC
    face. Admin-only and only on demand — guardian_status never carries key
    material. Voice-only mode (no Simli key) is a supported degradation."""
    keys = _guardian_keys(_first_entry(hass))
    status = guardian_engine.keys_status(keys)
    if not status["faceReady"]:
        connection.send_error(
            msg["id"], "guardian_keys", "Simli key and face ID are not both set"
        )
        return
    connection.send_result(
        msg["id"], {"apiKey": keys.get("simli", ""), "faceId": keys.get("simliFaceId", "")}
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up OpenReef services and websocket commands."""
    websocket_api.async_register_command(hass, websocket_get_config)
    websocket_api.async_register_command(hass, websocket_save_config)
    websocket_api.async_register_command(hass, websocket_update_config_alias)
    websocket_api.async_register_command(hass, websocket_coral_photo_upload)
    websocket_api.async_register_command(hass, websocket_search_entities)
    websocket_api.async_register_command(hass, websocket_validate_config)
    websocket_api.async_register_command(hass, websocket_validate_mappings_alias)
    websocket_api.async_register_command(hass, websocket_mute_alert)
    websocket_api.async_register_command(hass, websocket_clear_alert_history)
    websocket_api.async_register_command(hass, websocket_acknowledge_alert)
    websocket_api.async_register_command(hass, websocket_test_notification)
    websocket_api.async_register_command(hass, websocket_refresh_trust_check)
    websocket_api.async_register_command(hass, websocket_vision_summary)
    websocket_api.async_register_command(hass, websocket_get_heartbeat)
    websocket_api.async_register_command(hass, websocket_list_reef_replay)
    websocket_api.async_register_command(hass, websocket_apply_mode)
    websocket_api.async_register_command(hass, websocket_toggle_equipment)
    websocket_api.async_register_command(hass, websocket_list_recordings)
    websocket_api.async_register_command(hass, websocket_delete_recording)
    websocket_api.async_register_command(hass, websocket_capture_now)
    websocket_api.async_register_command(hass, websocket_list_timelapse_frames)
    websocket_api.async_register_command(hass, websocket_capture_timelapse_frame)
    websocket_api.async_register_command(hass, websocket_clear_timelapse)
    websocket_api.async_register_command(hass, websocket_list_feed_sessions)
    websocket_api.async_register_command(hass, websocket_list_feed_frames)
    websocket_api.async_register_command(hass, websocket_delete_feed_session)
    websocket_api.async_register_command(hass, websocket_list_reef_presets)
    websocket_api.async_register_command(hass, websocket_spawning_execution_status)
    websocket_api.async_register_command(hass, websocket_spawning_execution_resume)
    websocket_api.async_register_command(hass, websocket_generate_spawning_program)
    websocket_api.async_register_command(hass, websocket_lighting_window)
    websocket_api.async_register_command(hass, websocket_icp_dashboard)
    websocket_api.async_register_command(hass, websocket_import_icp_report)
    websocket_api.async_register_command(hass, websocket_delete_icp_report)
    websocket_api.async_register_command(hass, websocket_awc_run_now)
    websocket_api.async_register_command(hass, websocket_awc_abort)
    websocket_api.async_register_command(hass, websocket_awc_resume)
    websocket_api.async_register_command(hass, websocket_awc_acknowledge)
    websocket_api.async_register_command(hass, websocket_awc_acknowledge_flood)
    websocket_api.async_register_command(hass, websocket_awc_calibrate)
    websocket_api.async_register_command(hass, websocket_awc_reset_reservoir)
    websocket_api.async_register_command(hass, websocket_awc_reset_ledger)
    websocket_api.async_register_command(hass, websocket_awc_sim_set)
    websocket_api.async_register_command(hass, websocket_awc_calibration_run)
    websocket_api.async_register_command(hass, websocket_config_export)
    websocket_api.async_register_command(hass, websocket_config_import)
    websocket_api.async_register_command(hass, websocket_awc_tubing_replaced)
    websocket_api.async_register_command(hass, websocket_awc_set_schedule)
    websocket_api.async_register_command(hass, websocket_awc_summary)
    websocket_api.async_register_command(hass, websocket_dosing_summary)
    websocket_api.async_register_command(hass, websocket_dosing_calibrate_start)
    websocket_api.async_register_command(hass, websocket_dosing_calibrate)
    websocket_api.async_register_command(hass, websocket_dosing_dose_now)
    websocket_api.async_register_command(hass, websocket_dosing_prime)
    websocket_api.async_register_command(hass, websocket_dosing_reset_reservoir)
    websocket_api.async_register_command(hass, websocket_dosing_mark_refreshed)
    websocket_api.async_register_command(hass, websocket_dosing_reset_tube)
    websocket_api.async_register_command(hass, websocket_mixing_summary)
    websocket_api.async_register_command(hass, websocket_mixing_start_batch)
    websocket_api.async_register_command(hass, websocket_mixing_advance)
    websocket_api.async_register_command(hass, websocket_mixing_log_salinity)
    websocket_api.async_register_command(hass, websocket_mixing_abort)
    websocket_api.async_register_command(hass, websocket_mixing_mark_used)
    websocket_api.async_register_command(hass, websocket_mixing_set_level)
    websocket_api.async_register_command(hass, websocket_mixing_rodi_draw)
    websocket_api.async_register_command(hass, websocket_mixing_rodi_stop)
    websocket_api.async_register_command(hass, websocket_mixing_calibrate)
    websocket_api.async_register_command(hass, websocket_mixing_filters_changed)
    websocket_api.async_register_command(hass, websocket_nps_summary)
    websocket_api.async_register_command(hass, websocket_nps_hatch_start)
    websocket_api.async_register_command(hass, websocket_nps_hatch_cancel)
    websocket_api.async_register_command(hass, websocket_nps_hatch_clock)
    websocket_api.async_register_command(hass, websocket_nps_reservoir_discard)
    websocket_api.async_register_command(hass, websocket_nps_hand_feed)
    websocket_api.async_register_command(hass, websocket_nps_hatch_enrich)
    websocket_api.async_register_command(hass, websocket_nps_enrich_loaded)
    websocket_api.async_register_command(hass, websocket_nps_enrich_dose)
    websocket_api.async_register_command(hass, websocket_nps_enrich_cancel)
    websocket_api.async_register_command(hass, websocket_nps_enrich_second_dose)
    websocket_api.async_register_command(hass, websocket_consumable_log_dose)
    websocket_api.async_register_command(hass, websocket_consumable_refill)
    websocket_api.async_register_command(hass, websocket_consumable_delete)
    websocket_api.async_register_command(hass, websocket_dosing_respread_missed)
    websocket_api.async_register_command(hass, websocket_dosing_acknowledge)
    websocket_api.async_register_command(hass, websocket_dosing_sync_now)
    websocket_api.async_register_command(hass, websocket_dosing_suspend)
    websocket_api.async_register_command(hass, websocket_dosing_resume)
    websocket_api.async_register_command(hass, websocket_dosing_dry_run)
    websocket_api.async_register_command(hass, websocket_dosing_ramp_checkpoint)
    websocket_api.async_register_command(hass, websocket_dosing_delete_channel)
    websocket_api.async_register_command(hass, websocket_guardian_status)
    websocket_api.async_register_command(hass, websocket_guardian_set_keys)
    websocket_api.async_register_command(hass, websocket_guardian_chat)
    websocket_api.async_register_command(hass, websocket_guardian_voice)
    websocket_api.async_register_command(hass, websocket_guardian_simli_session)
    beta_feedback.async_register_ws(hass)  # BETA-FEEDBACK: remove after beta

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
        SERVICE_RECORD_TASK_COMPLETION,
        _handle_record_task_completion,
        schema=RECORD_TASK_COMPLETION_SCHEMA,
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
    hass.services.async_register(
        DOMAIN,
        SERVICE_ACKNOWLEDGE_ALERT,
        _handle_acknowledge_alert,
        schema=ACKNOWLEDGE_ALERT_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_TEST_NOTIFICATION,
        _handle_test_notification,
        schema=TEST_NOTIFICATION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_TRUST_CHECK,
        _handle_refresh_trust_check,
        schema=EMPTY_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_HEARTBEAT,
        _handle_heartbeat,
        schema=EMPTY_SERVICE_SCHEMA,
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
    if await _async_sync_alert_notifications(hass, normalised):
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_SETTINGS: normalised}
        )
    await _async_schedule_mode_timer(hass, entry, normalised)
    await _async_schedule_equipment_timers(hass, entry, normalised)
    await _async_schedule_max_off_timers(hass, entry, normalised)
    await _async_schedule_mode_schedule(hass, entry, normalised)
    await _async_schedule_ato_duty_cycle(hass, entry, normalised)
    await _async_schedule_wavemaker_reminders(hass, entry, normalised)
    await _async_schedule_maintenance_reminders(hass, entry, normalised)
    await _async_schedule_timelapse(hass, entry, normalised)
    await _async_schedule_watchdog(hass, entry, normalised)
    await _async_awc_resume_on_startup(hass, entry, normalised)
    # Restart mid-holdoff: re-arm the post-change ATO-restore expiry (R27) — without
    # this the dosing suspend only ever released via the firmware's 4 h dead-man.
    # Fresh fetch: resume may have just finalized a change and stamped a NEW hold-off
    # that the pre-resume snapshot doesn't carry.
    await _async_arm_awc_ato_restore(hass, entry, _config_from_entry(entry))
    # Stop a calibration-run pump orphaned by a restart mid-run.
    await _async_awc_recover_orphaned_calrun(hass, entry)
    # Stop a feed-exchange drain orphaned the same way (partial-volume credit).
    await _async_nps_recover_orphaned_drain(hass, entry)
    # Stop ha_switch_timed pumps orphaned mid-dose (honest elapsed credit).
    await _async_dosing_ha_recover(hass, entry)
    # Mixing station plugs orphaned mid-batch: booster/heater off, pumps
    # re-asserted during salting (doc §11 fail-safe directions), a mid-burst
    # circulation stopped and re-anchored.
    await _async_mixing_recover_orphaned(hass, entry)
    await _async_schedule_mixing_circulation(hass, entry, _config_from_entry(entry))
    await _async_schedule_mixing_rodi(hass, entry, _config_from_entry(entry))
    await _async_schedule_awc(hass, entry, normalised)
    await _async_schedule_awc_scheduler(hass, entry, normalised)
    await _async_schedule_dosing_tick(hass, entry, normalised)
    await _async_schedule_spawning_tick(hass, entry, normalised)
    await _async_setup_dosing_mirror(hass, entry, normalised)
    if _dosing_channels(normalised):
        _async_kick_dosing_sync(hass, entry)
    await _async_finalize_orphaned_feed_sessions(hass, entry)
    await _async_setup_vision(hass, entry, normalised)
    await beta_feedback.async_start(hass, entry)  # BETA-FEEDBACK: remove after beta
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OpenReefConfigEntry) -> bool:
    """Unload an OpenReef config entry."""
    _clear_mode_timer(hass)
    _clear_equipment_timers(hass)
    _clear_max_off_timers(hass)
    _clear_mode_verify(hass)
    _clear_mode_schedule(hass)
    _clear_ato_duty_cycle(hass)
    _clear_delayed_equipment_calls(hass)
    _clear_wavemaker_reminders(hass)
    _clear_maintenance_reminders(hass)
    _clear_timelapse(hass)
    _clear_feedwatch(hass)
    _clear_vision(hass)
    _clear_watchdog(hass)
    _clear_awc_timer(hass)
    _clear_awc_scheduler(hass)
    _clear_dosing(hass)
    _clear_spawning_tick(hass)
    hass.data.setdefault(DOMAIN, {}).pop(SPAWNING_RUNTIME, None)
    beta_feedback.async_stop(hass)  # BETA-FEEDBACK: remove after beta
    _store = hass.data.setdefault(DOMAIN, {})
    _awc_restore = _store.pop(AWC_ATO_RESTORE_UNSUB, None)
    if _awc_restore is not None:
        _awc_restore()
    # Cancel a pending calibration-run stop timer; the persisted calRunRole stamp
    # lets the next setup stop the pump (reload path).
    _awc_calrun = _store.pop(AWC_CALRUN_UNSUB, None)
    if _awc_calrun is not None:
        _awc_calrun()
    # Same for a feed-exchange drain: cancel the timer, the persisted
    # drainStartedAt stamp lets the next setup stop and credit the pump.
    _nps_drain = _store.pop(NPS_DRAIN_UNSUB, None)
    if _nps_drain is not None:
        _nps_drain()
    # And the mixing fill cap: cancel the timer; batch.state == "filling" is the
    # persisted trace the next setup uses to stop the orphaned booster.
    _mixing_fill = _store.pop(MIXING_FILL_UNSUB, None)
    if _mixing_fill is not None:
        _mixing_fill()
    # The circulation chain likewise: its stamps re-arm it on the next setup.
    _mixing_circ = _store.pop(MIXING_CIRC_UNSUB, None)
    if _mixing_circ is not None:
        _mixing_circ()
    # And the RODI draw/calibration leg — its stamps re-arm it too.
    _mixing_rodi = _store.pop(MIXING_RODI_UNSUB, None)
    if _mixing_rodi is not None:
        _mixing_rodi()
    _issue_refresh = _store.pop(ISSUE_REFRESH_UNSUB, None)
    if _issue_refresh is not None:
        _issue_refresh()
    hass.data.setdefault(DOMAIN, {}).setdefault(ATO_DUTY_CYCLE_LAST, {}).pop(
        entry.entry_id, None
    )
    hass.data.setdefault(DOMAIN, {}).setdefault(WAVEMAKER_REMINDER_LAST, {}).pop(
        entry.entry_id, None
    )
    hass.data.setdefault(DOMAIN, {}).setdefault(MAINTENANCE_REMINDER_LAST, {}).pop(
        entry.entry_id, None
    )
    hass.data.setdefault(DOMAIN, {}).setdefault(CAPTURE_LAST, {}).pop(entry.entry_id, None)
    hass.data.setdefault(DOMAIN, {}).setdefault(TIMELAPSE_LAST, {}).pop(entry.entry_id, None)
    hass.data.setdefault(DOMAIN, {}).setdefault(FEEDWATCH_SESSION, {}).pop(entry.entry_id, None)
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
        await hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {"notification_id": f"openreef_escalation_{sensor_id}"},
            blocking=False,
        )
    for notification_id in (
        "openreef_watchdog_missed",
        "openreef_notification_test",
    ):
        await hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {"notification_id": notification_id},
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
