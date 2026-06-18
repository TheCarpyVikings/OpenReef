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
from homeassistant.helpers.event import (
    async_track_point_in_time,
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
    AWC_AMOUNT_UNITS,
    AWC_DEFAULT_DRIFT_WARN_PCT,
    AWC_DEFAULT_HOLDOFF_MINUTES,
    AWC_DEFAULT_MAX_INSTANT_IMBALANCE_L,
    AWC_DEFAULT_MAX_SINGLE_CHANGE_PCT,
    AWC_DEFAULT_NET_IMBALANCE_L,
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
    AWC_STATUSES,
    AWC_TANK_MAX_L,
    AWC_TICK_DEFAULT_SECONDS,
    AWC_TICK_MAX_SECONDS,
    AWC_TICK_MIN_SECONDS,
    CONF_SETTINGS,
    DEFAULT_CORE_CONFIG,
    DEFAULT_TANK_PROFILE,
    DOMAIN,
    DOSING_PARAMETERS,
    ISSUE_ARMED_UNAVAILABLE,
    ISSUE_LEGACY_LABS_CONFIG,
    ISSUE_MISSING_ENTITIES,
    INTEGRATION_VERSION,
    MAINTENANCE_COMPLETIONS_MAX,
    MAINTENANCE_REMINDER_DEFAULT_TIME,
    MAINTENANCE_TASK_CADENCE_MAX,
    MAINTENANCE_TASK_CADENCE_MIN,
    MAINTENANCE_TASK_CRITICAL_MAX,
    MAINTENANCE_TASK_DEFAULTS,
    MODE_EQUIPMENT_TIMER_MAX_SECONDS,
    MODE_EQUIPMENT_CYCLE_MIN_SECONDS,
    MODE_VERIFY_DEFAULT_DELAY_SECONDS,
    EQUIPMENT_MAX_OFF_MAX_SECONDS,
    ICP_REPORTS_MAX,
    MANUAL_TEST_CADENCE_PRESETS,
    MANUAL_TEST_PARAMETERS,
    MVP_SENSORS,
    NAME,
    PANEL_ICON,
    PANEL_STATIC_URL,
    PANEL_URL,
    REEF_PRESETS,
    SPAWNING_DEFAULT_SOLAR_NOON_HOUR,
    SPAWNING_OFFSET_MONTHS_MAX,
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
)
from . import awc as awc_engine
from . import icp
from . import spawning

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
    for role in AWC_PUMP_ROLES:
        raw = raw_pumps.get(role) if isinstance(raw_pumps.get(role), dict) else {}
        # exchangeFactor: a non-positive / junk value means "no correction" (1.0),
        # never a runaway multiplier.
        factor = _awc_num(raw.get("exchangeFactor"), 1.0, 0.0, 10.0)
        pumps[role] = {
            "switchEntity": _normalise_entity_id(raw.get("switchEntity")),
            "mlPerS": round(_awc_num(raw.get("mlPerS"), 0, 0, AWC_PUMP_MAX_ML_PER_S), 3),
            "interceptMl": round(_awc_num(raw.get("interceptMl"), 0, -100000, 100000), 3),
            "exchangeFactor": round(factor if factor > 0 else 1.0, 4),
            "calibratedAt": _awc_str(raw.get("calibratedAt"), 40),
            "tubingInstalledAt": _awc_str(raw.get("tubingInstalledAt"), 40),
        }
    awc_cfg["pumps"] = pumps

    raw_res = awc_cfg.get("reservoirs") if isinstance(awc_cfg.get("reservoirs"), dict) else {}
    fresh = raw_res.get("fresh") if isinstance(raw_res.get("fresh"), dict) else {}
    waste = raw_res.get("waste") if isinstance(raw_res.get("waste"), dict) else {}
    awc_cfg["reservoirs"] = {
        "fresh": {
            "capacityLitres": round(_awc_num(fresh.get("capacityLitres"), 25, 0, AWC_RESERVOIR_MAX_L), 2),
            "remainingMl": round(_awc_num(fresh.get("remainingMl"), 0, 0, AWC_RESERVOIR_MAX_L * 1000), 1),
            "emptyEntity": _normalise_entity_id(fresh.get("emptyEntity")),
        },
        "waste": {
            "capacityLitres": round(_awc_num(waste.get("capacityLitres"), 25, 0, AWC_RESERVOIR_MAX_L), 2),
            "filledMl": round(_awc_num(waste.get("filledMl"), 0, 0, AWC_RESERVOIR_MAX_L * 1000), 1),
            "fullEntity": _normalise_entity_id(waste.get("fullEntity")),
        },
    }

    raw_safety = awc_cfg.get("safety") if isinstance(awc_cfg.get("safety"), dict) else {}
    warn_mult = round(_awc_num(raw_safety.get("anomalyWarnMult"), 2.0, 1.0, 100.0), 2)
    abort_mult = round(_awc_num(raw_safety.get("anomalyAbortMult"), 3.0, 1.0, 100.0), 2)
    awc_cfg["safety"] = {
        "highLevelEntity": _normalise_entity_id(raw_safety.get("highLevelEntity")),
        "leakEntity": _normalise_entity_id(raw_safety.get("leakEntity")),
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
    awc_cfg["schedule"] = {
        "enabled": bool(raw_sched.get("enabled", False)),
        # Live controller runs sequential + simultaneous; anything else (continuous) is
        # projection-only, so coerce it to the safe sequential default.
        "method": method if method in AWC_LIVE_METHODS else "batch_sequential",
        "amountUnit": unit if unit in AWC_AMOUNT_UNITS else "percent",
        "amount": round(_awc_num(raw_sched.get("amount"), 0, 0, 100000), 2),
        "period": period if period in AWC_PERIODS else "week",
        "times": _normalise_schedule_times(raw_sched.get("times"), "02:00"),
        "days": [d for d in (raw_sched.get("days") or []) if d in _AWC_WEEKDAYS],
        "windowStart": _normalise_schedule_time(raw_sched.get("windowStart")) or "01:00",
        "windowEnd": _normalise_schedule_time(raw_sched.get("windowEnd")) or "05:00",
    }

    raw_state = awc_cfg.get("state") if isinstance(awc_cfg.get("state"), dict) else {}
    status = str(raw_state.get("status", "idle"))
    state_method = str(raw_state.get("method", ""))
    safe_state_method = state_method if state_method in AWC_LIVE_METHODS else ""
    if not safe_state_method and status in ("draining", "filling", "exchanging", "paused"):
        safe_state_method = "batch_sequential"
    awc_cfg["state"] = {
        "status": status if status in AWC_STATUSES else "idle",
        "fault": _awc_str(raw_state.get("fault"), 200),
        "faultSince": _awc_str(raw_state.get("faultSince"), 40),
        "method": safe_state_method,
        "startedAt": _awc_str(raw_state.get("startedAt"), 40),
        "lastRun": _awc_str(raw_state.get("lastRun"), 40),
        "nextRun": _awc_str(raw_state.get("nextRun"), 40),
        "targetLitres": round(_awc_num(raw_state.get("targetLitres"), 0, 0, AWC_TANK_MAX_L), 3),
        "drainedMl": round(_awc_num(raw_state.get("drainedMl"), 0, 0, 1e9), 1),
        "filledMl": round(_awc_num(raw_state.get("filledMl"), 0, 0, 1e9), 1),
        "legStartedAt": _awc_str(raw_state.get("legStartedAt"), 40),
        "legEndsAt": _awc_str(raw_state.get("legEndsAt"), 40),
        "drainEndsAt": _awc_str(raw_state.get("drainEndsAt"), 40),
        "fillEndsAt": _awc_str(raw_state.get("fillEndsAt"), 40),
        "exchangeBaselineGapMl": round(_awc_num(raw_state.get("exchangeBaselineGapMl"), 0, 0, 1e9), 1),
        "pausedReason": _awc_str(raw_state.get("pausedReason"), 200),
        "atoSuspendedUntil": _awc_str(raw_state.get("atoSuspendedUntil"), 40),
    }

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
            })
    awc_cfg["history"] = history
    awc_cfg["todayLitres"] = round(_awc_num(awc_cfg.get("todayLitres"), 0, 0, 1e6), 3)
    awc_cfg["weekLitres"] = round(_awc_num(awc_cfg.get("weekLitres"), 0, 0, 1e6), 3)
    awc_cfg["monthLitres"] = round(_awc_num(awc_cfg.get("monthLitres"), 0, 0, 1e6), 3)


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
    ):
        pulse[field] = bool(pulse.get(field, pulse_defaults[field]))
    camera_id = pulse.get("cameraId")
    cameras_block = config.get("cameras")
    known_cameras = cameras_block if isinstance(cameras_block, dict) else {}
    pulse["cameraId"] = camera_id if isinstance(camera_id, str) and camera_id in known_cameras else ""
    pulse["backdrop"] = pulse.get("backdrop") if pulse.get("backdrop") in ("auto", "camera", "wall") else "auto"
    pulse["graphRange"] = pulse.get("graphRange") if pulse.get("graphRange") in ("24h", "7d") else "24h"

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

    lighting_cfg = config.setdefault("lightingSchedule", {})
    if not isinstance(lighting_cfg, dict):
        config["lightingSchedule"] = deepcopy(DEFAULT_CORE_CONFIG["lightingSchedule"])
    else:
        ls_defaults = DEFAULT_CORE_CONFIG["lightingSchedule"]
        mode = lighting_cfg.get("mode")
        lighting_cfg["mode"] = mode if mode in {"off", "simple", "reef"} else "off"
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

    _normalise_awc_config(config)

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
    lighting_cfg = config.get("lightingSchedule")
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
    # interval mode (default): age since last done vs cadence / critical thresholds
    cadence = task.get("cadenceDays", 7)
    if last_done is None:
        return "warning"
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
    Mirrors the maintenance/watchdog notification pattern."""
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
    alerts = config.get("alerts", {})
    target = (
        str(alerts.get("modeNotifyTarget", "")).strip()
        if isinstance(alerts, dict)
        else ""
    )
    if target:
        await hass.services.async_call(
            "notify",
            target,
            {"title": f"OpenReef: {title}", "message": message},
            blocking=False,
        )


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


def _awc_binary_on(hass: HomeAssistant, entity_id: str | None) -> bool:
    """True when a configured binary safety sensor reads active. Unavailable/unset →
    False (the firmware owns real-time guarding; the backend won't act on a flaky read)."""
    if not entity_id:
        return False
    state = hass.states.get(entity_id)
    if state is None or state.state in UNAVAILABLE_STATES:
        return False
    return str(state.state).lower() in _AWC_ON_STATES


def _awc_live_state(hass: HomeAssistant, config: dict[str, Any]) -> dict[str, Any]:
    awc = _awc_cfg(config)
    safety = awc.get("safety", {}) if isinstance(awc.get("safety"), dict) else {}
    reservoirs = awc.get("reservoirs", {}) if isinstance(awc.get("reservoirs"), dict) else {}
    fresh = reservoirs.get("fresh", {}) if isinstance(reservoirs.get("fresh"), dict) else {}
    waste = reservoirs.get("waste", {}) if isinstance(reservoirs.get("waste"), dict) else {}
    mode = config.get("mode", {})
    return {
        "leak": _awc_binary_on(hass, safety.get("leakEntity")),
        "highLevel": _awc_binary_on(hass, safety.get("highLevelEntity")),
        "freshEmpty": _awc_binary_on(hass, fresh.get("emptyEntity")),
        "wasteFull": _awc_binary_on(hass, waste.get("fullEntity")),
        "returnPumpIssue": bool(_return_pump_dependency_issues(hass, config)),
        "inFeedMode": isinstance(mode, dict) and mode.get("active") == "feed",
    }


def _awc_ato_suspended(config: dict[str, Any]) -> bool:
    """ATO is held while a change is running/paused, while a fault is latched, and for
    the post-change stabilization hold-off (prevents the GHL-style salinity crash)."""
    awc = _awc_cfg(config)
    state = awc.get("state", {}) if isinstance(awc.get("state"), dict) else {}
    if not awc.get("ato", {}).get("suspendDuringChange", True):
        return False
    if state.get("status") in (*_AWC_RUNNING_STATES, "paused", "fault"):
        return True
    until = _parse_datetime(state.get("atoSuspendedUntil"))
    return until is not None and until > datetime.now(timezone.utc)


async def _async_awc_set_pump(
    hass: HomeAssistant, config: dict[str, Any], role: str, on: bool, context: Any
) -> None:
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
    for role in roles:
        await _async_awc_set_pump(hass, config, role, False, context)


async def _async_awc_stop_pumps_best_effort(
    hass: HomeAssistant, config: dict[str, Any], roles: Iterable[str], context: Any
) -> None:
    """Emergency cleanup path used when actuation failed mid-start."""
    for role in roles:
        try:
            await _async_awc_set_pump(hass, config, role, False, context)
        except Exception:  # noqa: BLE001 - best-effort emergency stop
            _LOGGER.exception("Failed to turn off AWC %s pump during emergency cleanup", role)


async def _async_awc_kill_equipment_profile(
    hass: HomeAssistant, config: dict[str, Any], profile: str, context: Any
) -> None:
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
    if "drain" in pumps and "fill" in pumps:
        return await _async_awc_begin_exchange(hass, config, now, context)
    acfg = _awc_cfg(config)
    state = acfg["state"]
    slice_l = float(leg["sliceMl"]) / 1000.0
    expected = awc_engine.leg_runtime_s(slice_l, acfg, pumps)
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
    if "drain" in pumps and "fill" in pumps:
        state["status"] = "exchanging"
    elif "drain" in pumps:
        state["status"] = "draining"
    else:
        state["status"] = "filling"
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
    target_ml = state.get("targetLitres", 0) * 1000.0
    pumps = acfg.get("pumps", {})
    drain = pumps.get("drain", {}) if isinstance(pumps.get("drain"), dict) else {}
    fill = pumps.get("fill", {}) if isinstance(pumps.get("fill"), dict) else {}
    drain_remaining_l = max(0.0, target_ml - state.get("drainedMl", 0)) / 1000.0
    fill_remaining_l = max(0.0, target_ml - state.get("filledMl", 0)) / 1000.0
    drain_rt = awc_engine.runtime_for_volume_s(drain_remaining_l, drain.get("mlPerS"), drain.get("exchangeFactor", 1.0))
    fill_rt = awc_engine.runtime_for_volume_s(fill_remaining_l, fill.get("mlPerS"), fill.get("exchangeFactor", 1.0))

    # A side with volume still to move but a zero/uncalibrated runtime would otherwise be
    # energised on a zero-length timer and phantom-credit the full target on the next tick
    # (non-fail-safe). Refuse to begin — mirrors the start-time no_calibration guard.
    if (drain_remaining_l > 1e-6 and drain_rt <= 0) or (fill_remaining_l > 1e-6 and fill_rt <= 0):
        state["status"] = "fault"
        state["fault"] = "Cannot run simultaneous change: a pump is not calibrated"
        state["faultSince"] = now.isoformat()
        state["legStartedAt"] = ""
        state["legEndsAt"] = ""
        state["drainEndsAt"] = ""
        state["fillEndsAt"] = ""
        return False, state["fault"]

    roles_on = []
    if drain_remaining_l > 1e-6:
        roles_on.append("drain")
    if fill_remaining_l > 1e-6:
        roles_on.append("fill")
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
        state["drainEndsAt"] = ""
        state["fillEndsAt"] = ""
        state["pausedReason"] = ""
        return False, state["fault"]

    drain_end = now + timedelta(seconds=drain_rt) if "drain" in roles_on else now
    fill_end = now + timedelta(seconds=fill_rt) if "fill" in roles_on else now
    state["status"] = "exchanging"
    state["legStartedAt"] = now.isoformat()
    state["drainEndsAt"] = drain_end.isoformat()
    state["fillEndsAt"] = fill_end.isoformat()
    # Baseline the imbalance cap to the gap that exists right now, so a resume-to-balance
    # leg (which starts with a large pre-existing gap it's correcting) isn't false-aborted.
    state["exchangeBaselineGapMl"] = abs(state.get("drainedMl", 0) - state.get("filledMl", 0))
    pending = [now + timedelta(seconds=AWC_EXCHANGE_TICK_SECONDS)]
    if "drain" in roles_on:
        pending.append(drain_end)
    if "fill" in roles_on:
        pending.append(fill_end)
    state["legEndsAt"] = min(pending).isoformat()
    state["pausedReason"] = ""
    return True, ""


async def _async_awc_suspend_ato(hass: HomeAssistant, config: dict[str, Any], context: Any) -> None:
    """Actively turn off any armed ATO equipment; the safety-block gate then keeps it
    off for the whole change + hold-off."""
    await _async_awc_kill_equipment_profile(hass, config, "ato", context)


async def _async_awc_start(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any],
    target_litres: float, method: str | None, manual: bool, context: Any,
) -> tuple[bool, list[dict[str, str]]]:
    """Preflight a change and begin its first leg. Returns (started, blocking_reasons)."""
    acfg = _awc_cfg(config)
    state = acfg["state"]
    if state.get("status") in _AWC_RUNNING_STATES:
        return False, [{"code": "busy", "severity": "block", "message": "A water change is already running"}]
    if state.get("status") == "paused":
        return False, [{"code": "paused", "severity": "block",
                        "message": "A water change is paused; resume or stop it before starting another"}]
    method = method or acfg.get("schedule", {}).get("method", _AWC_SAFE_METHOD)
    if method not in AWC_LIVE_METHODS:
        return False, [{"code": "unsupported_method", "severity": "block",
                        "message": "AWC supports sequential or simultaneous changes (continuous is projection-only)"}]
    target = round(float(target_litres or 0), 3)

    # Local time is only needed for the quiet-hours guard; compute it lazily.
    now_min = 0
    if acfg.get("guards", {}).get("quietHoursEnabled"):
        local_now = dt_util.now()
        now_min = local_now.hour * 60 + local_now.minute
    live = _awc_live_state(hass, config)
    reasons = awc_engine.start_guard_reasons(acfg, live, now_min, manual)
    if target <= 0:
        reasons.append({"code": "no_volume", "severity": "block", "message": "Enter a volume to change"})
    reasons.extend(awc_engine.reservoir_preflight_reasons(acfg, target))
    if awc_engine.exceeds_single_change_cap(acfg, target):
        pct = acfg.get("safety", {}).get("maxSingleChangePercent", 25)
        reasons.append({"code": "max_single_change", "severity": "block",
                        "message": f"Exceeds the {pct}% single-change cap"})
    if method == "batch_simultaneous" and target > 0:
        cap = acfg.get("safety", {}).get("maxInstantaneousImbalanceLitres", AWC_DEFAULT_MAX_INSTANT_IMBALANCE_L)
        excursion = awc_engine.simultaneous_max_excursion_l(acfg, target)
        if cap > 0 and excursion > cap + 1e-6:
            reasons.append({"code": "imbalance_too_large", "severity": "block",
                            "message": f"Pumps too rate-mismatched for a simultaneous {target:.1f} L change "
                                       f"(~{excursion:.1f} L sump swing > {cap} L cap) — use sequential or rate-match"})
    if reasons:
        return False, reasons

    now = datetime.now(timezone.utc)
    if acfg.get("ato", {}).get("suspendDuringChange", True):
        await _async_awc_suspend_ato(hass, config, context)
        state["atoSuspendedUntil"] = ""  # the "running" status covers the suspension
    state["method"] = method
    state["targetLitres"] = target
    state["drainedMl"] = 0
    state["filledMl"] = 0
    state["startedAt"] = now.isoformat()
    state["fault"] = ""
    state["faultSince"] = ""
    state["pausedReason"] = ""
    state["legStartedAt"] = ""
    state["legEndsAt"] = ""
    state["drainEndsAt"] = ""
    state["fillEndsAt"] = ""
    state["exchangeBaselineGapMl"] = 0

    target_ml = target * 1000.0
    if method == "batch_simultaneous":
        begun, reason = await _async_awc_begin_exchange(hass, config, now, context)
    else:
        leg = awc_engine.plan_leg(method, 0, 0, target_ml, target_ml)
        if leg is None:
            return True, []
        begun, reason = await _async_awc_begin_leg(hass, config, method, leg, now, context)
    if not begun:
        _append_activity(config, reason, "control")
        await _async_save_config(hass, entry, config)
        return False, [{"code": "pump_start_failed", "severity": "fault", "message": reason}]
    _append_activity(config, f"Water change started: {target:.1f} L ({method.replace('_', ' ')})", "control")
    await _async_save_config(hass, entry, config)
    return True, []


async def _async_awc_pause(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any],
    reason: str, context: Any,
) -> None:
    await _async_awc_stop_pumps(hass, config, ("drain", "fill"), context)
    state = _awc_cfg(config)["state"]
    state["status"] = "paused"
    state["pausedReason"] = reason
    state["legStartedAt"] = ""
    state["legEndsAt"] = ""
    state["drainEndsAt"] = ""
    state["fillEndsAt"] = ""
    state["exchangeBaselineGapMl"] = 0
    _append_activity(config, f"Water change paused: {reason}", "warning")
    await _async_send_mode_notification(
        hass, config, "openreef_awc_paused", "Water change paused", reason,
    )
    await _async_save_config(hass, entry, config)


async def _async_awc_abort(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any],
    reason: str, latch: bool, master_kill: bool, context: Any,
) -> None:
    await _async_awc_stop_pumps(hass, config, ("drain", "fill"), context)
    if master_kill:
        await _async_awc_kill_equipment_profile(hass, config, "return_pump", context)
    awc = _awc_cfg(config)
    state = awc["state"]
    now = datetime.now(timezone.utc)
    drained_l = state.get("drainedMl", 0) / 1000.0
    filled_l = state.get("filledMl", 0) / 1000.0
    if drained_l > 0 or filled_l > 0:
        _awc_record_history(awc, now, drained_l, filled_l, state.get("method", ""), True, reason)
    if latch:
        state["status"] = "fault"
        state["fault"] = reason
        state["faultSince"] = now.isoformat()
    else:
        state["status"] = "idle"
        state["fault"] = ""
        state["atoSuspendedUntil"] = ""  # user abort restores the ATO
    state["legStartedAt"] = ""
    state["legEndsAt"] = ""
    state["drainEndsAt"] = ""
    state["fillEndsAt"] = ""
    state["exchangeBaselineGapMl"] = 0
    state["drainedMl"] = 0
    state["filledMl"] = 0
    state["targetLitres"] = 0
    _append_activity(config, f"Water change {'FAULT' if latch else 'aborted'}: {reason}",
                     "warning" if latch else "control")
    await _async_send_mode_notification(
        hass, config, "openreef_awc_fault",
        "Water change fault" if latch else "Water change aborted", reason,
    )
    await _async_save_config(hass, entry, config)


def _awc_record_history(
    awc: dict[str, Any], now: datetime, drained_l: float, filled_l: float,
    method: str, partial: bool, notes: str,
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


async def _async_awc_finalize(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any], context: Any,
) -> None:
    await _async_awc_stop_pumps(hass, config, ("drain", "fill"), context)
    awc = _awc_cfg(config)
    state = awc["state"]
    now = datetime.now(timezone.utc)
    drained_l = state.get("drainedMl", 0) / 1000.0
    filled_l = state.get("filledMl", 0) / 1000.0
    _awc_record_history(awc, now, drained_l, filled_l, state.get("method", ""), False, "")
    awc["todayLitres"] = round(awc.get("todayLitres", 0) + filled_l, 3)
    awc["weekLitres"] = round(awc.get("weekLitres", 0) + filled_l, 3)
    awc["monthLitres"] = round(awc.get("monthLitres", 0) + filled_l, 3)
    holdoff = awc.get("ato", {}).get("stabilizationHoldoffMinutes", AWC_DEFAULT_HOLDOFF_MINUTES)
    if awc.get("ato", {}).get("suspendDuringChange", True) and holdoff > 0:
        state["atoSuspendedUntil"] = (now + timedelta(minutes=holdoff)).isoformat()
    else:
        state["atoSuspendedUntil"] = ""
    state["status"] = "idle"
    state["lastRun"] = now.isoformat()
    state["legStartedAt"] = ""
    state["legEndsAt"] = ""
    state["drainEndsAt"] = ""
    state["fillEndsAt"] = ""
    state["exchangeBaselineGapMl"] = 0
    state["drainedMl"] = 0
    state["filledMl"] = 0
    state["targetLitres"] = 0
    state["method"] = ""
    state["pausedReason"] = ""
    _append_activity(config, f"Water change complete: {filled_l:.1f} L exchanged", "control")
    await _async_save_config(hass, entry, config)
    await _async_arm_awc_ato_restore(hass, entry, config)


async def _async_awc_leg_complete(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any], context: Any,
) -> None:
    """A leg timer fired: stop the leg, account its volume, check safety, then begin the
    next leg / pause / fault / finalize."""
    awc = _awc_cfg(config)
    state = awc["state"]
    if state.get("status") not in _AWC_RUNNING_STATES:
        return
    method = state.get("method") or awc.get("schedule", {}).get("method", _AWC_SAFE_METHOD)
    target_ml = state.get("targetLitres", 0) * 1000.0
    drained = state.get("drainedMl", 0)
    filled = state.get("filledMl", 0)

    leg = awc_engine.plan_leg(method, drained, filled, target_ml, target_ml)
    if leg is None:
        await _async_awc_finalize(hass, entry, config, context)
        return
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

    # Account the leg's volume against progress + the dead-reckoned reservoirs.
    slice_ml = float(leg["sliceMl"])
    reservoirs = awc.get("reservoirs", {})
    if "drain" in pumps:
        state["drainedMl"] = drained + slice_ml
        waste = reservoirs.get("waste", {})
        cap_ml = waste.get("capacityLitres", 0) * 1000.0
        waste["filledMl"] = min(cap_ml, waste.get("filledMl", 0) + slice_ml) if cap_ml else waste.get("filledMl", 0) + slice_ml
    if "fill" in pumps:
        state["filledMl"] = filled + slice_ml
        fresh = reservoirs.get("fresh", {})
        fresh["remainingMl"] = max(0.0, fresh.get("remainingMl", 0) - slice_ml)

    next_leg = awc_engine.plan_leg(method, state["drainedMl"], state["filledMl"], target_ml, target_ml)
    if next_leg is None:
        await _async_awc_finalize(hass, entry, config, context)
        return

    needs_drain = "drain" in next_leg["pumps"]
    needs_fill = "fill" in next_leg["pumps"]
    live = _awc_live_state(hass, config)
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
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any], context: Any,
) -> None:
    """Simultaneous-mode monitor tick: dead-reckon each pump from its own stop time,
    account the reservoirs incrementally, stop pumps as they finish, enforce the
    instantaneous imbalance cap + live safety, then finalize or re-arm. Independent
    per-pump timing means each pump moves exactly the target — no over-pump."""
    awc = _awc_cfg(config)
    state = awc["state"]
    if state.get("status") != "exchanging":
        return
    now = datetime.now(timezone.utc)
    target_ml = state.get("targetLitres", 0) * 1000.0
    pumps = awc.get("pumps", {})
    drain = pumps.get("drain", {}) if isinstance(pumps.get("drain"), dict) else {}
    fill = pumps.get("fill", {}) if isinstance(pumps.get("fill"), dict) else {}
    drain_ends = _parse_datetime(state.get("drainEndsAt"))
    fill_ends = _parse_datetime(state.get("fillEndsAt"))
    drain_rem_s = (drain_ends - now).total_seconds() if drain_ends else 0.0
    fill_rem_s = (fill_ends - now).total_seconds() if fill_ends else 0.0

    drained_ml, drain_done = awc_engine.exchange_side_progress(
        drain_rem_s, drain.get("mlPerS"), drain.get("exchangeFactor", 1.0), target_ml)
    filled_ml, fill_done = awc_engine.exchange_side_progress(
        fill_rem_s, fill.get("mlPerS"), fill.get("exchangeFactor", 1.0), target_ml)

    # Incremental reservoir dead-reckoning (delta since the last tick).
    reservoirs = awc.get("reservoirs", {})
    d_drain = max(0.0, drained_ml - state.get("drainedMl", 0))
    d_fill = max(0.0, filled_ml - state.get("filledMl", 0))
    if d_drain > 0:
        waste = reservoirs.get("waste", {})
        cap_ml = waste.get("capacityLitres", 0) * 1000.0
        waste["filledMl"] = min(cap_ml, waste.get("filledMl", 0) + d_drain) if cap_ml else waste.get("filledMl", 0) + d_drain
    if d_fill > 0:
        fresh = reservoirs.get("fresh", {})
        fresh["remainingMl"] = max(0.0, fresh.get("remainingMl", 0) - d_fill)
    state["drainedMl"] = drained_ml
    state["filledMl"] = filled_ml

    if drain_done:
        await _async_awc_set_pump(hass, config, "drain", False, context)
    if fill_done:
        await _async_awc_set_pump(hass, config, "fill", False, context)

    cap = awc.get("safety", {}).get("maxInstantaneousImbalanceLitres", AWC_DEFAULT_MAX_INSTANT_IMBALANCE_L)
    baseline = state.get("exchangeBaselineGapMl", 0)
    if awc_engine.exchange_imbalance_exceeds(drained_ml, filled_ml, cap, baseline):
        await _async_awc_abort(
            hass, entry, config,
            f"Simultaneous imbalance exceeded {cap} L "
            f"(drain {drained_ml / 1000:.2f} L / fill {filled_ml / 1000:.2f} L) — pumps too mismatched",
            True, False, context,
        )
        return

    live = _awc_live_state(hass, config)
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
        config = _config_from_entry(latest_entry)
        # Dispatch by method: simultaneous runs the monitor tick, sequential the leg handler.
        if _awc_cfg(config).get("state", {}).get("method") == "batch_simultaneous":
            await _async_awc_exchange_tick(hass, latest_entry, config, None)
        else:
            await _async_awc_leg_complete(hass, latest_entry, config, None)

    hass.data.setdefault(DOMAIN, {})[AWC_UNSUB] = async_track_point_in_time(hass, _handle, run_at)


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
    await _async_arm_awc_timer(hass, entry, ends)


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
        latest_config = _config_from_entry(latest_entry)
        state = _awc_cfg(latest_config).get("state", {})
        if state.get("status") in (*_AWC_RUNNING_STATES, "paused"):
            return
        u = _parse_datetime(state.get("atoSuspendedUntil"))
        if u is not None and u > datetime.now(timezone.utc):
            return
        state["atoSuspendedUntil"] = ""
        _append_activity(latest_config, "ATO resumed after water-change stabilization hold-off", "control")
        await _async_save_config(hass, latest_entry, latest_config)

    store[AWC_ATO_RESTORE_UNSUB] = async_track_point_in_time(hass, _handle, run_at)


async def _async_awc_relaunch(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any],
    context: Any, log_message: str,
) -> bool:
    """Resume/relaunch the current change from persisted progress (resume-to-balance),
    dispatching sequential vs simultaneous. Returns True if it relaunched or completed,
    False if blocked (fault latched / paused)."""
    awc = _awc_cfg(config)
    state = awc["state"]
    method = state.get("method") or awc.get("schedule", {}).get("method", _AWC_SAFE_METHOD)
    target_ml = state.get("targetLitres", 0) * 1000.0
    drained = state.get("drainedMl", 0)
    filled = state.get("filledMl", 0)
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
        needs_drain = "drain" in leg["pumps"]
        needs_fill = "fill" in leg["pumps"]

    live = _awc_live_state(hass, config)
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

    now = datetime.now(timezone.utc)
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
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any], context: Any,
) -> bool:
    """Attempt to resume a paused change. Returns True if it resumed/completed."""
    if _awc_cfg(config).get("state", {}).get("status") != "paused":
        return False
    return await _async_awc_relaunch(hass, entry, config, context, "Water change resumed")


async def _async_awc_resume_on_startup(
    hass: HomeAssistant, entry: OpenReefConfigEntry, config: dict[str, Any],
) -> None:
    """On startup, recover an interrupted change. A running change is re-begun from the
    persisted drained/filled (resume-to-balance); a paused change is re-evaluated."""
    status = _awc_cfg(config).get("state", {}).get("status")
    if status in _AWC_RUNNING_STATES:
        await _async_awc_relaunch(hass, entry, config, None, "Water change resumed after restart (resume-to-balance)")
    elif status == "paused":
        await _async_awc_try_resume(hass, entry, config, None)


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
    config = _config_from_entry(entry)
    acfg = _awc_cfg(config)
    state = acfg.get("state", {})

    # Auto-resume a paused change as soon as its blocking condition clears.
    if state.get("status") == "paused":
        await _async_awc_try_resume(hass, entry, config, None)
        return
    if state.get("status") in (*_AWC_RUNNING_STATES, "fault"):
        return  # busy or latched — never auto-start over a fault

    if not acfg.get("enabled"):
        return
    sched = acfg.get("schedule", {})
    _awc_refresh_next_run(config, now_local)
    if not sched.get("enabled"):
        await _async_save_config(hass, entry, config)
        return

    method = sched.get("method", _AWC_SAFE_METHOD)
    if method not in AWC_LIVE_METHODS:  # continuous is projection-only; fall back to safe default
        method = _AWC_SAFE_METHOD
    tank = acfg.get("tankVolumeLitres", 0)
    last_run = _parse_datetime(state.get("lastRun"))

    if awc_engine.is_due(sched, last_run, now_local):
        litres = awc_engine.per_change_litres(sched, tank)
        if litres > 0:
            await _async_awc_start(hass, entry, config, litres, method, False, None)
            return
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

    config = await _async_save_config(hass, entry, msg["config"])
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
        {
            "success": True,
            "version": INTEGRATION_VERSION,
            "config": config,
            "trust_check": _trust_check_summary(hass, config),
            "heartbeat": _watchdog_status(config),
            "reef_replay": _reef_replay_incidents(config),
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
    config = _config_from_entry(entry)
    acfg = _awc_cfg(config)
    litres = msg.get("litres")
    if litres is None and msg.get("percent") is not None:
        litres = acfg.get("tankVolumeLitres", 0) * float(msg["percent"]) / 100.0
    started, reasons = await _async_awc_start(
        hass, entry, config, litres or 0, msg.get("method"), True, connection.context(msg)
    )
    config = _config_from_entry(entry)
    _awc_send(connection, msg, hass, config, started=started, reasons=reasons)


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
    config = _config_from_entry(entry)
    if _awc_cfg(config).get("state", {}).get("status") != "paused":
        connection.send_error(msg["id"], "not_paused", "No paused water change to resume")
        return
    resumed = await _async_awc_try_resume(hass, entry, config, connection.context(msg))
    _awc_send(connection, msg, hass, _config_from_entry(entry), resumed=resumed)


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
    config = _config_from_entry(entry)
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
    state.update({
        "status": "idle", "fault": "", "faultSince": "", "atoSuspendedUntil": "",
        "drainedMl": 0, "filledMl": 0, "targetLitres": 0,
        "legStartedAt": "", "legEndsAt": "", "drainEndsAt": "", "fillEndsAt": "",
        "exchangeBaselineGapMl": 0, "method": "", "pausedReason": "",
    })
    _append_activity(config, "Water change fault acknowledged and cleared", "control")
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
        connection.send_error(msg["id"], "invalid_role", "Pump role must be 'drain' or 'fill'")
        return
    config = _config_from_entry(entry)
    pump = _awc_cfg(config).get("pumps", {}).get(role, {})
    if msg.get("points"):
        fit = awc_engine.calibrate_linear([(p[0], p[1]) for p in msg["points"]])
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
    pump["mlPerS"] = round(ml_per_s, 3)
    pump["interceptMl"] = round(intercept, 3)
    pump["calibratedAt"] = datetime.now(timezone.utc).isoformat()
    _append_activity(config, f"AWC {role} pump calibrated: {pump['mlPerS']} ml/s", "control")
    config = await _async_save_config(hass, entry, config)
    _awc_send(connection, msg, hass, config, role=role, mlPerS=pump["mlPerS"])


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
        connection.send_error(msg["id"], "invalid_reservoir", "Reservoir must be 'fresh' or 'waste'")
        return
    config = _config_from_entry(entry)
    reservoirs = _awc_cfg(config).get("reservoirs", {})
    if kind == "fresh":
        fresh = reservoirs.get("fresh", {})
        fresh["remainingMl"] = fresh.get("capacityLitres", 0) * 1000.0
        _append_activity(config, "Fresh saltwater reservoir marked full", "control")
    else:
        reservoirs.get("waste", {})["filledMl"] = 0
        _append_activity(config, "Waste reservoir marked empty", "control")
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
    summary = awc_engine.summary(acfg, dt_util.now())
    connection.send_result(msg["id"], {
        "summary": summary,
        "state": acfg.get("state", {}),
        "schedule": acfg.get("schedule", {}),
        "live": _awc_live_state(hass, config),
        "atoSuspended": _awc_ato_suspended(config),
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
    lighting_cfg = (
        config.get("lightingSchedule")
        if isinstance(config.get("lightingSchedule"), dict)
        else {}
    )
    connection.send_result(
        msg["id"], {"lighting": spawning.lighting_window_summary(lighting_cfg, dt_util.now())}
    )


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
    websocket_api.async_register_command(hass, websocket_acknowledge_alert)
    websocket_api.async_register_command(hass, websocket_test_notification)
    websocket_api.async_register_command(hass, websocket_refresh_trust_check)
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
    websocket_api.async_register_command(hass, websocket_generate_spawning_program)
    websocket_api.async_register_command(hass, websocket_lighting_window)
    websocket_api.async_register_command(hass, websocket_icp_dashboard)
    websocket_api.async_register_command(hass, websocket_import_icp_report)
    websocket_api.async_register_command(hass, websocket_delete_icp_report)
    websocket_api.async_register_command(hass, websocket_awc_run_now)
    websocket_api.async_register_command(hass, websocket_awc_abort)
    websocket_api.async_register_command(hass, websocket_awc_resume)
    websocket_api.async_register_command(hass, websocket_awc_acknowledge)
    websocket_api.async_register_command(hass, websocket_awc_calibrate)
    websocket_api.async_register_command(hass, websocket_awc_reset_reservoir)
    websocket_api.async_register_command(hass, websocket_awc_set_schedule)
    websocket_api.async_register_command(hass, websocket_awc_summary)

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
    await _async_schedule_awc(hass, entry, normalised)
    await _async_schedule_awc_scheduler(hass, entry, normalised)
    await _async_finalize_orphaned_feed_sessions(hass, entry)
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
    _clear_watchdog(hass)
    _clear_awc_timer(hass)
    _clear_awc_scheduler(hass)
    _store = hass.data.setdefault(DOMAIN, {})
    _awc_restore = _store.pop(AWC_ATO_RESTORE_UNSUB, None)
    if _awc_restore is not None:
        _awc_restore()
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
