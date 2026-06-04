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

    def get(self, entity_id):
        return self._states.get(entity_id)


class _FakeServices:
    def __init__(self):
        self.calls = []  # SimpleNamespace(domain, service, data, kwargs)

    async def async_call(self, domain, service, data=None, **kwargs):
        self.calls.append(
            SimpleNamespace(domain=domain, service=service, data=dict(data or {}), kwargs=kwargs)
        )


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


class FakeEntry:
    def __init__(self, options=None, entry_id="test_entry"):
        self.entry_id = entry_id
        self.options = dict(options or {})


class FakeHass:
    def __init__(self, states=None, entries=None, config_dir="/tmp/openreef_test"):
        self.states = _FakeStates(states)
        self.services = _FakeServices()
        self.config = _FakeConfig(config_dir)
        self.config_entries = _FakeConfigEntries(entries or [])
        self.data = {}
        self.tasks = []  # names passed to async_create_task

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


def run(coro):
    """Run an async handler to completion."""
    return asyncio.run(coro)
