"""Minimal stubs so the integration's pure config-migration logic can be imported
and unit-tested without installing Home Assistant or voluptuous.

`custom_components/openreef/__init__.py` imports a lot of `homeassistant.*` and
`voluptuous` at module level, but `_normalise_core_config` (and the helpers it
calls) are pure dict logic with no HA/vol usage. The module also uses
`from __future__ import annotations`, so type hints are never evaluated. That
means we only need every imported NAME to exist as something harmless.

`install()` registers lenient stub modules in `sys.modules` whose every attribute
is a universal callable that behaves as both a value and a (bare/factory)
decorator. Call it before importing the integration package.
"""

from __future__ import annotations

import sys
import types


def _u(*args, **kwargs):
    # Bare decorator (`@dec`): return the decorated object unchanged.
    if len(args) == 1 and callable(args[0]) and not kwargs:
        return args[0]
    # Factory decorator (`@dec(...)`) or a plain value: return self, which is
    # itself callable, so it also works as the resulting bare decorator.
    return _u


class _LenientModule(types.ModuleType):
    def __getattr__(self, name):  # noqa: D401 - any attribute resolves leniently
        return _u


def _mod(name: str) -> _LenientModule:
    existing = sys.modules.get(name)
    if isinstance(existing, _LenientModule):
        return existing
    module = _LenientModule(name)
    sys.modules[name] = module
    return module


_HA_MODULES = [
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.http",
    "homeassistant.components.panel_custom",
    "homeassistant.components.websocket_api",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.area_registry",
    "homeassistant.helpers.config_validation",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.event",
    "homeassistant.helpers.issue_registry",
    "homeassistant.helpers.typing",
    "homeassistant.util",
    "homeassistant.util.dt",
]


def install() -> None:
    """Register the stub modules. Idempotent."""
    vol = _mod("voluptuous")
    vol.Invalid = type("Invalid", (Exception,), {})

    # Parents are listed before children, so each child's parent already exists.
    for name in _HA_MODULES:
        module = _mod(name)
        parent_name, _, child = name.rpartition(".")
        if parent_name and parent_name in sys.modules:
            # Set as a real attribute so `from parent import child` returns the
            # submodule (whose __getattr__ then yields the universal callable),
            # not the parent's universal-callable __getattr__ result.
            setattr(sys.modules[parent_name], child, module)

    # A couple of names are used as real exception classes elsewhere; provide them
    # so any future test that exercises those paths doesn't get a non-exception.
    exc = sys.modules["homeassistant.exceptions"]
    exc.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
    exc.ServiceValidationError = type("ServiceValidationError", (Exception,), {})
