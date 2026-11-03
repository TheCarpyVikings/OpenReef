"""HA lifecycle and durable storage for passive heater monitoring.

Only notification services are used. This module never controls a heater,
controller, fan or smart plug, including during learning and urgent alerts.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval

from . import heater_health as engine
from .const import DOMAIN

KEY = "heater_health_monitor"
LOGGER = logging.getLogger(__name__)
STALE_SECONDS = 20 * 60


def configured(config):
    return {key: item for key, item in config.get("equipment", {}).items()
            if engine.normalise_settings(item.get("heaterMonitor"))["mode"] != "off"}


def _sensor(config, key):
    sensor = config.get("sensors", {}).get(key, {})
    return sensor.get("entity_id", "") if sensor.get("enabled") else ""


def _stamp(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).timestamp() if value.tzinfo is None else value.timestamp()
    if isinstance(value, str):
        try:
            return _stamp(datetime.fromisoformat(value))
        except ValueError:
            pass
    return None


def _state(hass, entity, now):
    state = hass.states.get(entity) if entity else None
    if state is None or state.state in ("unavailable", "unknown", "none", ""):
        return None
    at = next((_stamp(getattr(state, field, None)) for field in
               ("last_reported", "last_updated", "last_changed")
               if _stamp(getattr(state, field, None)) is not None), None)
    if at is None or now - at > STALE_SECONDS or at - now > 60:
        return None
    return state


def _number(hass, entity, now, kind):
    state = _state(hass, entity, now)
    value = engine.number(state.state) if state else None
    if value is None:
        return None
    unit = str(state.attributes.get("unit_of_measurement", "")).strip().lower()
    if kind == "temperature":
        if unit in ("°f", "f"):
            value = (value - 32) * 5 / 9
        elif unit not in ("°c", "c"):
            return None
        return value if -20 <= value <= 60 else None
    if unit == "kw":
        value *= 1000
    elif unit != "w":
        return None
    return value if 0 <= value <= 20000 else None


def bindings(config, item):
    settings = engine.normalise_settings(item.get("heaterMonitor"))
    return [settings["mode"], item.get("power_entity_id", ""),
            _sensor(config, "temp"), _sensor(config, "room_temp"), settings["climateEntity"]]


def sample(hass, config, item, now):
    mode, power, water, room, climate = bindings(config, item)
    values = {"watts": _number(hass, power, now, "power"),
              "waterC": _number(hass, water, now, "temperature"),
              "roomC": _number(hass, room, now, "temperature")}
    missing = [label for key, label in (("watts", "power monitor"), ("waterC", "tank temperature"),
                                       ("roomC", "room temperature")) if values[key] is None]
    duplicate = power and sum(x.get("power_entity_id") == power for x in configured(config).values()) > 1
    ctl = _state(hass, climate, now) if climate else None
    action = ctl.attributes.get("hvac_action") if ctl else None
    action = action if action in ("heating", "cooling", "idle", "off") else None
    sensor = config.get("sensors", {}).get("temp", {})
    bounds = [engine.number(sensor.get(k)) for k in ("min", "max")]
    if str(sensor.get("unit", "°C")).lower() in ("f", "°f"):
        bounds = [(x - 32) * 5 / 9 if x is not None else None for x in bounds]
    awc = config.get("automaticWaterChange", {}).get("state", {})
    hold = _stamp(awc.get("atoSuspendedUntil"))
    paused = (config.get("mode", {}).get("active", "running") != "running" or
              awc.get("status", "idle") not in ("idle", "complete", "fault") or
              (hold is not None and hold > now))
    return {"at": now, **values, "action": action, "minC": bounds[0], "maxC": bounds[1],
            "paused": paused, "error": ("This power monitor is assigned to more than one monitored device. Monitor the shared controller once."
                if duplicate else "Check fresh readings and units for: " + ", ".join(missing) if missing else None)}


def _restore(raw, now):
    """Reject corrupt state rather than turning invalid history into confidence."""
    if not isinstance(raw, dict) or raw.get("version") != 1:
        return None
    try:
        if not isinstance(raw["binding"], list) or len(raw["binding"]) != 5:
            return None
        for key in ("reference", "recent", "loads", "hours"):
            if not isinstance(raw[key], list):
                return None
        if len(raw["loads"]) > engine.MAX_LOADS or len(raw["reference"]) > engine.MAX_REFERENCES:
            return None
        for cycle in raw["reference"] + raw["recent"]:
            if any(engine.number(cycle[k]) is None for k in ("at", "seconds", "watts", "gap", "start", "end", "rate", "hour")):
                return None
            if cycle["watts"] <= 0 or cycle["seconds"] <= 0:
                return None
        for load in raw["loads"]:
            if not load["id"].startswith("p") or not load["id"][1:].isdigit() or load["role"] not in (None, "idle", "heating", "cooling"):
                return None
            if any(engine.number(load[k]) is None for k in ("watts", "seconds", "visits", "first")):
                return None
            if load.get("source") not in ("observed", "confirmed", "power", "controller"):
                return None
        for hour in raw["hours"]:
            if any(engine.number(hour[k]) is None for k in ("hour", "seconds", "heating", "cooling", "heatingWh", "coolingWh", "unassignedWh")):
                return None
        result = {**engine.new_state(now), **deepcopy(raw)}
        result["recent"] = result["recent"][-12:]
        result["hours"] = result["hours"][-24:]
        # Never bridge the unobserved time during a restart.
        result.update(last=None, segment=None, current="unknown", issue=None)
        result.pop("noHeatSince", None)
        result.pop("overrunSince", None)
        return result
    except (KeyError, TypeError, AttributeError):
        return None


class Monitor:
    def __init__(self, hass, entry, store, config_getter, notify):
        self.hass, self.entry, self.store = hass, entry, store
        self.config_getter, self.notify = config_getter, notify
        self.states = {}
        self.lock = asyncio.Lock()
        self.unsubs = []
        self.fingerprint = None
        self.stopped = False
        self.last_save_scheduled = 0

    async def load(self):
        raw = await self.store.async_load()
        now = datetime.now(timezone.utc).timestamp()
        if isinstance(raw, dict):
            for key, state in list(raw.items())[:100]:
                restored = _restore(state, now)
                if restored:
                    self.states[key] = restored

    def _persist(self):
        # Frequent sensor events must not keep postponing the storage deadline.
        now = datetime.now(timezone.utc).timestamp()
        if now - self.last_save_scheduled >= 60:
            self.last_save_scheduled = now
            self.store.async_delay_save(lambda: deepcopy(self.states), 5)

    async def configure(self):
        async with self.lock:
            changed = await self._configure_locked()
        if changed:
            await self.tick()

    async def _configure_locked(self):
        config = self.config_getter()
        gear = configured(config)
        fingerprint = [(key, bindings(config, item)) for key, item in gear.items()]
        if fingerprint == self.fingerprint:
            return False
        for unsub in self.unsubs:
            unsub()
        self.unsubs = []
        self.fingerprint = fingerprint
        now = datetime.now(timezone.utc).timestamp()
        # Retain disabled equipment history, but never its in-progress cycle.
        for key, state in self.states.items():
            if key not in gear:
                state.update(last=None, segment=None)
                await self._dismiss(key, state)
        for key, item in gear.items():
            binding = bindings(config, item)
            if key not in self.states or self.states[key].get("binding") != binding:
                old = self.states.get(key)
                if old:
                    await self._dismiss(key, old)
                self.states[key] = engine.new_state(now, binding)
                if old:
                    self.states[key]["previous"] = {"at": now, "reference": old["reference"], "loads": old["loads"]}
        # Deleted equipment cannot grow the persistent file forever.
        self.states = {key: value for key, value in self.states.items() if key in config.get("equipment", {})}
        entities = sorted({entity for _, bound in fingerprint for entity in bound[1:] if entity})
        if gear:
            async def on_event(_event):
                await self.tick()
            async def on_timer(_now):
                await self.tick()
            if entities:
                self.unsubs.append(async_track_state_change_event(self.hass, entities, on_event))
            self.unsubs.append(async_track_time_interval(self.hass, on_timer, timedelta(seconds=60)))
        self._persist()
        return True

    def _notification_id(self, key):
        suffix = hashlib.sha256(f"{self.entry.entry_id}:{key}".encode()).hexdigest()[:16]
        return f"openreef_heater_{suffix}"

    async def _dismiss(self, key, state):
        if state.get("noticeActive"):
            try:
                await self.hass.services.async_call("persistent_notification", "dismiss",
                    {"notification_id": self._notification_id(key)}, blocking=False)
            except Exception:
                LOGGER.warning("Could not dismiss heater notification", exc_info=True)
        state["noticeActive"] = False

    async def tick(self, at=None):
        async with self.lock:
            if self.stopped or self.hass.data.get(DOMAIN, {}).get("unloading"):
                return
            config = self.config_getter()
            now = at if at is not None else datetime.now(timezone.utc).timestamp()
            for key, item in configured(config).items():
                state = self.states.get(key)
                if state is None or state.get("binding") != bindings(config, item):
                    continue  # A concurrent settings save will configure the new binding.
                result = engine.observe(state, sample(self.hass, config, item, now),
                                        engine.normalise_settings(item.get("heaterMonitor"))["mode"])
                issue = result["issue"]
                if issue:
                    signature = issue["code"] + ":" + issue["severity"]
                    if state.get("notified") != signature:
                        history = state.setdefault("notificationHistory", {})
                        cooldown = 900 if issue["severity"] == "critical" else 21600
                        if now - history.get(signature, 0) >= cooldown:
                            message = issue["message"] + " Open OpenReef → Energy → Heater health."
                            await self.notify(config, self._notification_id(key),
                                              f"{item.get('label') or key}: {issue['title']}", message)
                            state.update(notified=signature, noticeActive=True)
                            history[signature] = now
                            await self.store.async_save(deepcopy(self.states))
                        else:
                            await self._dismiss(key, state)
                else:
                    await self._dismiss(key, state)
                    state["notified"] = None
            self._persist()

    def snapshot(self):
        now = datetime.now(timezone.utc).timestamp()
        config = self.config_getter()
        return {key: {**engine.summary(self.states[key], now), "label": item.get("label") or key,
                       "mode": engine.normalise_settings(item.get("heaterMonitor"))["mode"]}
                for key, item in configured(config).items() if key in self.states}

    async def respond(self, key, action, load_id="", role=""):
        async with self.lock:
            if self.stopped or key not in configured(self.config_getter()) or key not in self.states:
                raise ValueError("Enable monitoring for this equipment first")
            state = self.states[key]
            now = datetime.now(timezone.utc).timestamp()
            if action == "identify":
                engine.identify(state, load_id, role)
            elif action in ("replaced", "settings_changed"):
                self.states[key] = engine.restart(state, now, action == "settings_changed")
            elif action == "acknowledge":
                # Keep the issue and baseline visible; do not treat silence or
                # 'nothing changed' as a successful repair or a new normal.
                state["acknowledgedAt"] = now
            else:
                raise ValueError("Unknown heater monitoring action")
            await self._dismiss(key, state)
            await self.store.async_save(deepcopy(self.states))
        await self.tick()

    async def stop(self):
        for unsub in self.unsubs:
            unsub()
        self.unsubs = []
        async with self.lock:
            self.stopped = True
            await self.store.async_save(deepcopy(self.states))


async def configure(hass, entry, config_getter, notify):
    runtime = hass.data.setdefault(DOMAIN, {})
    # Serialise startup/config-save races before loading storage or subscribing.
    lock = runtime.setdefault(KEY + "_lock", asyncio.Lock())
    async with lock:
        if runtime.get("unloading"):
            return
        monitor = runtime.get(KEY)
        if monitor is None:
            if not configured(config_getter()):
                return
            from homeassistant.helpers.storage import Store
            monitor = Monitor(hass, entry, Store(hass, 1, f"openreef.heater_health.{entry.entry_id}"), config_getter, notify)
            await monitor.load()
            runtime[KEY] = monitor
        await monitor.configure()


async def stop(hass):
    runtime = hass.data.setdefault(DOMAIN, {})
    async with runtime.setdefault(KEY + "_lock", asyncio.Lock()):
        monitor = runtime.pop(KEY, None)
        if monitor:
            await monitor.stop()
