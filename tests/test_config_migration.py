"""First tests for OpenReef config migration / normalisation.

These exercise the REAL `_normalise_core_config` from the integration (with Home
Assistant + voluptuous stubbed out — see `_ha_stubs.py`), because that function is
what runs against a beta tester's existing config on every update. A regression
here could silently wipe mappings or crash setup.

Run standalone (no pytest needed):   python3 tests/test_config_migration.py
Or with pytest if installed:          pytest tests/
"""

from __future__ import annotations

import copy
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
import openreef as integration  # noqa: E402  (runs __init__.py with stubs installed)

normalise = integration._normalise_core_config
DEFAULTS = integration.DEFAULT_CORE_CONFIG
CURRENT_SCHEMA = integration.const.CORE_SCHEMA_VERSION
NAME = integration.NAME
TANK_PROFILES = set(integration.TANK_PROFILE_CHOICES)
SEARCH_LIMIT = integration.SEARCH_LIMIT


# --- structural sanity (catches a malformed default that would crash migration) ---

def test_schema_version_is_int_and_matches_defaults():
    assert isinstance(CURRENT_SCHEMA, int)
    assert DEFAULTS["schemaVersion"] == CURRENT_SCHEMA


def test_defaults_have_core_blocks():
    for key in ("tank", "sensors", "equipment", "dosing"):
        assert key in DEFAULTS, f"DEFAULT_CORE_CONFIG missing {key!r}"
    assert isinstance(DEFAULTS["sensors"], dict)


def test_entity_search_is_capped():
    # Targeted, capped entity search is a hard product rule.
    assert SEARCH_LIMIT == 10


# --- migration behaviour ---

def test_none_returns_full_defaults():
    result = normalise(None)
    assert isinstance(result, dict)
    assert result["schemaVersion"] == CURRENT_SCHEMA
    assert set(DEFAULTS).issubset(set(result))


def test_non_dict_returns_full_defaults():
    for junk in ("a string", 42, [1, 2, 3], True):
        result = normalise(junk)
        assert isinstance(result, dict)
        assert result["schemaVersion"] == CURRENT_SCHEMA


def test_empty_dict_gets_defaults_and_schema_version():
    result = normalise({})
    assert result["schemaVersion"] == CURRENT_SCHEMA
    # Additive deep-merge: every default top-level key is present.
    assert set(DEFAULTS).issubset(set(result))
    assert isinstance(result.get("dosing"), dict)


def test_old_config_migrates_and_preserves_data():
    old = {
        "schemaVersion": 24,  # pre-dosing/manual-tests era
        "tank": {"name": "  My Reef  ", "owner": "Reece", "profile": "sps"},
        "sensors": {"temp": {"entity_id": "sensor.tank_temp", "enabled": True}},
    }
    result = normalise(old)
    # Schema bumped to current...
    assert result["schemaVersion"] == CURRENT_SCHEMA
    # ...new blocks added without touching old data.
    assert "dosing" in result
    # User data preserved (name trimmed + capped, profile + mapping kept).
    assert result["tank"]["name"] == "My Reef"
    assert result["tank"]["owner"] == "Reece"
    assert result["tank"]["profile"] == "sps"
    assert result["sensors"]["temp"]["entity_id"] == "sensor.tank_temp"
    assert result["sensors"]["temp"]["enabled"] is True


def test_garbage_values_coerced_without_crashing():
    bad = {
        "schemaVersion": "not a number",
        "tank": {"name": 12345, "owner": ["nope"], "profile": "not_a_profile"},
        "sensors": "totally not a dict",
        "dosing": {"enabled": "yeah", "parameters": "broken"},
    }
    result = normalise(bad)  # must not raise
    assert isinstance(result, dict)
    assert result["schemaVersion"] == CURRENT_SCHEMA
    # Non-string name falls back to the product name.
    assert result["tank"]["name"] == NAME
    # Invalid profile normalised to a real choice.
    assert result["tank"]["profile"] in TANK_PROFILES
    # Sensors rebuilt into a dict regardless of the junk input.
    assert isinstance(result["sensors"], dict)
    assert isinstance(result.get("dosing"), dict)


def test_no_data_loss_for_mapped_enabled_sensor():
    cfg = {"sensors": {"alkalinity": {"entity_id": "sensor.trident_alk", "enabled": True}}}
    result = normalise(cfg)
    assert result["sensors"]["alkalinity"]["entity_id"] == "sensor.trident_alk"
    assert result["sensors"]["alkalinity"]["enabled"] is True


def test_disarmed_by_default_after_migration():
    # Safety: nothing should come out of migration armed unless explicitly set.
    result = normalise({"equipment": {"heater": {"label": "Heater"}}})
    heater = result["equipment"].get("heater", {})
    assert heater.get("armed", False) is False


def test_camera_mapping_survives_migration():
    cfg = {"cameras": {"display": {"label": "Display Tank", "entity_id": "camera.reef_display"}}}
    result = normalise(cfg)
    assert isinstance(result.get("cameras"), dict)
    cam = result["cameras"]["display"]
    assert cam["entity_id"] == "camera.reef_display"
    assert cam["label"] == "Display Tank"


def test_garbage_cameras_block_coerced():
    for junk in ("not a dict", 7, ["x"]):
        result = normalise({"cameras": junk})
        assert isinstance(result.get("cameras"), dict)  # never crashes / never a scalar
    # A non-dict camera entry is dropped, a label-less one is labelled by id.
    result = normalise({"cameras": {"a": "broken", "b": {"entity_id": "camera.x"}}})
    assert "a" not in result["cameras"]
    assert result["cameras"]["b"]["label"] == "b"
    assert result["cameras"]["b"]["entity_id"] == "camera.x"


def test_idempotent():
    sample = {
        "schemaVersion": 24,
        "tank": {"name": "Reef", "profile": "mixed_reef"},
        "sensors": {"ph": {"entity_id": "sensor.ph", "enabled": True}},
    }
    once = normalise(copy.deepcopy(sample))
    twice = normalise(copy.deepcopy(once))
    assert once == twice, "normalisation is not stable across repeated runs"


def test_legacy_labs_config_routes_without_crash():
    # Old Labs-style configs go through the legacy converter.
    for legacy in ({"general": {}}, {"entities": {}}):
        result = normalise(legacy)
        assert isinstance(result, dict)
        assert "schemaVersion" in result


# --- tiny standalone runner (so this works without pytest installed) ---

def _main() -> int:
    tests = sorted(
        (name, obj)
        for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    )
    passed = 0
    failed = []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except Exception as exc:  # noqa: BLE001 - report everything
            failed.append(name)
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{passed}/{len(tests)} passed", "" if not failed else f"— FAILED: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
