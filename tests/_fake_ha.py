"""Minimal fake Home Assistant objects for unit-testing OpenReef's safety logic.

OpenReef's websocket handlers + interlock helpers only touch a small slice of HA:
``hass.states.get``, ``hass.services.async_call``, ``hass.config_entries``,
``hass.async_add_executor_job``, plus a websocket "connection" with
``send_result``/``send_error``/``context``. These fakes implement exactly that
slice and record calls, so tests can assert "the switch was (not) toggled" and
"this error code was sent". Use together with ``_ha_stubs.install()``.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from types import SimpleNamespace

_FIXED_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class FakeState:
    def __init__(self, state, attributes=None, last_changed=_FIXED_TS):
        self.state = state
        self.attributes = dict(attributes or {})
        self.last_changed = last_changed


class _FakeStates:
    def __init__(self, states=None):
        self._states = {}
        for entity_id, value in (states or {}).items():
            self.set(entity_id, value)

    def set(self, entity_id, value, attributes=None):
        self._states[entity_id] = value if isinstance(value, FakeState) else FakeState(value, attributes)

    def async_set(self, entity_id, value, attributes=None):
        # Bare state-machine write (no entity platform) — the dosing pH mirror uses this.
        self.set(entity_id, value, attributes)

    def get(self, entity_id):
        return self._states.get(entity_id)


class _FakeServices:
    def __init__(self, states=None):
        self.calls = []  # SimpleNamespace(domain, service, data, kwargs)
        # When wired to a _FakeStates, switch.turn_on/off mutate the entity state so
        # scheduled-callback re-checks (per-equipment timers, max-off) behave like HA.
        self._states = states
        # Failure injection: add (domain, service) or (domain, service, entity_id)
        # tuples to make matching calls raise HomeAssistantError — the
        # ESP-unreachable / rejected-write test hook.
        self.fail_on = set()
        # Response injection for return_response calls (weather.get_forecasts):
        # (domain, service) → payload, or a callable(data, kwargs) → payload.
        self.responses = {}

    async def async_call(self, domain, service, data=None, **kwargs):
        data = dict(data or {})
        self.calls.append(
            SimpleNamespace(domain=domain, service=service, data=data, kwargs=kwargs)
        )
        if (domain, service) in self.responses:
            await asyncio.sleep(0)
            resp = self.responses[(domain, service)]
            return resp(data, kwargs) if callable(resp) else resp
        # Yield to the event loop like a real (blocking=True) service call: without
        # this, asyncio.gather races never interleave, so lock-contention tests
        # exercised nothing (a task could hold a lock across "awaits" atomically).
        await asyncio.sleep(0)
        entity_ids = [v for v in data.values() if isinstance(v, str) and "." in v]
        if (domain, service) in self.fail_on or any(
            (domain, service, ent) in self.fail_on for ent in entity_ids
        ):
            from homeassistant.exceptions import HomeAssistantError  # stubbed real class
            raise HomeAssistantError(f"injected failure: {domain}.{service}")
        if (
            domain == "switch"
            and service in ("turn_on", "turn_off")
            and self._states is not None
        ):
            new_state = "on" if service == "turn_on" else "off"
            # ATTR_ENTITY_ID is stubbed, so the key is opaque — mutate by value(s).
            for value in data.values():
                if isinstance(value, str):
                    self._states.set(value, new_state)
                elif isinstance(value, (list, tuple)):
                    for item in value:
                        if isinstance(item, str):
                            self._states.set(item, new_state)
        if (
            domain == "number"
            and service == "set_value"
            and self._states is not None
        ):
            # Mirror HA: the number entity's state becomes the written value, so the
            # dosing sync's read-back verification is testable. Entity ids are the
            # dotted strings among the values (ATTR_ENTITY_ID's key is opaque).
            new_value = data.get("value")
            for key, value in data.items():
                if key == "value":
                    continue
                if isinstance(value, str) and "." in value:
                    self._states.set(value, str(new_value))


class _FakeConfig:
    def __init__(self, config_dir):
        self._dir = config_dir
        self.allowlist_external_dirs = set()

    def path(self, *parts):
        return os.path.join(self._dir, *parts)


class _FakeConfigEntries:
    def __init__(self, entries):
        self._entries = list(entries)

    def async_entries(self, domain=None):
        return list(self._entries)

    def async_update_entry(self, entry, options=None, **kwargs):
        if options is not None:
            entry.options = options
        return True


class _FakeBus:
    def __init__(self):
        self.events = []  # SimpleNamespace(event_type, data)
        self.listeners = []  # SimpleNamespace(event_type, callback, cancelled)

    def async_fire(self, event_type, event_data=None):
        self.events.append(SimpleNamespace(event_type=event_type, data=dict(event_data or {})))

    def async_listen_once(self, event_type, callback):
        record = SimpleNamespace(event_type=event_type, callback=callback, cancelled=False)
        self.listeners.append(record)

        def _unsub():
            record.cancelled = True

        return _unsub


class FakeEntry:
    def __init__(self, options=None, entry_id="test_entry"):
        self.entry_id = entry_id
        self.options = dict(options or {})


class FakeHass:
    def __init__(self, states=None, entries=None, config_dir="/tmp/openreef_test", is_running=True):
        self.states = _FakeStates(states)
        self.services = _FakeServices(self.states)
        self.config = _FakeConfig(config_dir)
        self.config_entries = _FakeConfigEntries(entries or [])
        self.bus = _FakeBus()
        self.data = {}
        self.tasks = []  # names passed to async_create_task
        self.is_running = is_running  # False = HA still booting (startup races)

    async def async_add_executor_job(self, func, *args):
        return func(*args)

    def async_create_task(self, coro, name=None, **kwargs):
        # We assert that a task was (or wasn't) dispatched; we don't run the
        # fire-and-forget coroutine. Close it so there's no "never awaited" warning.
        self.tasks.append(name)
        try:
            coro.close()
        except (AttributeError, RuntimeError):
            pass
        return SimpleNamespace(name=name)


class FakeConnection:
    def __init__(self):
        self.results = []  # SimpleNamespace(id, payload)
        self.errors = []   # SimpleNamespace(id, code, message)

    def send_result(self, msg_id, payload=None):
        self.results.append(SimpleNamespace(id=msg_id, payload=payload))

    def send_error(self, msg_id, code, message):
        self.errors.append(SimpleNamespace(id=msg_id, code=code, message=message))

    def context(self, msg=None):
        return SimpleNamespace(id="test-context")

    @property
    def error_codes(self):
        return [error.code for error in self.errors]


class FakeScheduler:
    """Captures callbacks registered via ``async_track_point_in_time`` so tests can
    fire them deterministically. The integration imports the helper by name, so a test
    installs this by monkeypatching ``integration.async_track_point_in_time``
    (see ``install_scheduler``). Re-arms (e.g. a cycling timer that schedules its next
    phase) register new records, so firing again advances the cycle.
    """

    def __init__(self):
        self.scheduled = []  # list of {callback, run_at, cancelled}

    def track(self, hass, callback, run_at):
        record = {"callback": callback, "run_at": run_at, "cancelled": False}
        self.scheduled.append(record)

        def _unsub():
            record["cancelled"] = True

        return _unsub

    def pending(self):
        return [r for r in self.scheduled if not r["cancelled"]]

    async def fire_all(self, now=None):
        """Fire every currently-pending callback once (snapshot pass). Records armed
        during this pass (future phases) are NOT fired here — call again to advance."""
        fired = 0
        for record in list(self.scheduled):
            if record["cancelled"]:
                continue
            record["cancelled"] = True
            fired += 1
            await record["callback"](now if now is not None else record["run_at"])
        return fired

    async def fire_due(self, now):
        """Fire only callbacks whose run_at <= now (snapshot pass)."""
        fired = 0
        for record in list(self.scheduled):
            if record["cancelled"] or record["run_at"] > now:
                continue
            record["cancelled"] = True
            fired += 1
            await record["callback"](now)
        return fired


def install_scheduler(integration):
    """Replace the integration's point-in-time scheduler with a capturing fake.
    Returns the FakeScheduler so tests can fire timers."""
    scheduler = FakeScheduler()
    integration.async_track_point_in_time = scheduler.track
    return scheduler


class FakeIntervalScheduler:
    """Captures ``async_track_time_interval`` registrations so tests can assert a
    periodic tick was (re)armed and fire it deterministically."""

    def __init__(self):
        self.intervals = []  # list of {callback, interval, cancelled}

    def track(self, hass, callback, interval):
        record = {"callback": callback, "interval": interval, "cancelled": False}
        self.intervals.append(record)

        def _unsub():
            record["cancelled"] = True

        return _unsub

    def pending(self):
        return [r for r in self.intervals if not r["cancelled"]]

    async def fire_all(self, now=None):
        fired = 0
        for record in list(self.intervals):
            if record["cancelled"]:
                continue
            fired += 1
            await record["callback"](now)
        return fired


def install_interval_scheduler(integration):
    """Replace ``async_track_time_interval`` with a capturing fake (companion to
    install_scheduler for the 60 s AWC/dosing ticks)."""
    scheduler = FakeIntervalScheduler()
    integration.async_track_time_interval = scheduler.track
    return scheduler


def run(coro):
    """Run an async handler to completion."""
    return asyncio.run(coro)
