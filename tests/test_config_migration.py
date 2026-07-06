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


def test_air_pump_profile_survives_migration():
    result = normalise({"equipment": {"air_pump": {"label": "Air Pump", "type": "air_pump"}}})
    pump = result["equipment"].get("air_pump", {})
    assert pump.get("type") == "air_pump"
    assert pump.get("armed", False) is False


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


def test_capture_block_defaults_injected():
    # A pre-camera-V2 config gains the capture block + empty captures list on migration.
    result = normalise({"schemaVersion": 32, "tank": {"name": "Reef"}})
    assert result["schemaVersion"] == CURRENT_SCHEMA
    capture = result.get("capture")
    assert isinstance(capture, dict)
    assert capture["enabled"] is False
    assert isinstance(capture["triggers"], dict)
    # Critical alerts default on; the noisier triggers default off.
    assert capture["triggers"]["criticalAlerts"] is True
    assert capture["triggers"]["modeChanges"] is False
    assert isinstance(result.get("captures"), list)


def test_capture_garbage_coerced_and_clamped():
    bad = {
        "capture": {
            "enabled": "yes",
            "durationSeconds": 99999,
            "lookbackSeconds": -5,
            "retention": 0,
            "cooldownSeconds": "nope",
            "cameraIds": "not a list",
            "triggers": "broken",
        },
        "captures": "totally not a list",
    }
    result = normalise(bad)  # must not raise
    capture = result["capture"]
    assert isinstance(capture, dict)
    assert capture["enabled"] is True
    # Numerics clamped into their valid ranges.
    assert 3 <= capture["durationSeconds"] <= 60
    assert capture["lookbackSeconds"] >= 0
    assert capture["retention"] >= 1
    assert isinstance(capture["cooldownSeconds"], int)
    assert capture["cameraIds"] == []
    assert isinstance(capture["triggers"], dict)
    assert isinstance(result["captures"], list)


def test_capture_camera_ids_filtered_to_real_cameras():
    cfg = {
        "cameras": {"display": {"entity_id": "camera.reef_display"}},
        "capture": {"cameraIds": ["display", "ghost_camera", 42]},
    }
    result = normalise(cfg)
    assert result["capture"]["cameraIds"] == ["display"]


def test_captures_list_truncated_to_max():
    MAX = integration.const.CAPTURE_MAX_RECORDS
    cfg = {"captures": [{"id": str(i)} for i in range(MAX + 25)]}
    result = normalise(cfg)
    assert len(result["captures"]) == MAX
    # Non-dict capture records are dropped without crashing.
    result2 = normalise({"captures": [{"id": "a"}, "junk", 7, {"id": "b"}]})
    assert [rec["id"] for rec in result2["captures"]] == ["a", "b"]


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


def test_timelapse_defaults_injected():
    result = normalise({})
    tl = result.get("timelapse")
    assert isinstance(tl, dict)
    assert tl["enabled"] is False
    assert tl["cadenceMinutes"] == 30
    assert isinstance(tl.get("retention"), dict)
    for key in ("detailDays", "dailyUntilDays", "weeklyUntilDays", "monthlyUntilDays"):
        assert key in tl["retention"]


def test_timelapse_garbage_coerced_and_clamped():
    bad = {
        "timelapse": {
            "enabled": "yes",
            "cadenceMinutes": 999999,
            "windowStart": "nope",
            "cameraId": 123,
            "retention": "broken",
        }
    }
    result = normalise(bad)  # must not raise
    tl = result["timelapse"]
    assert isinstance(tl, dict)
    assert tl["cadenceMinutes"] <= 1440          # clamped to the max cadence
    assert tl["windowStart"] == "08:00"          # invalid time falls back to default
    assert tl["cameraId"] == ""                  # non-str / unknown camera dropped
    assert isinstance(tl["retention"], dict)
    assert all(isinstance(v, int) for v in tl["retention"].values())


def test_timelapse_non_dict_block_coerced():
    for junk in ("a string", 7, ["x"], None):
        result = normalise({"timelapse": junk})
        assert isinstance(result.get("timelapse"), dict)


def test_overlay_defaults_injected():
    result = normalise({})
    overlay = result.get("overlay")
    assert isinstance(overlay, dict)
    assert overlay["enabled"] is False
    assert isinstance(overlay["stats"], list)
    assert "temp" in overlay["stats"]  # default survives the MVP-sensor filter
    assert overlay["position"] in ("top-left", "top-right", "bottom-left", "bottom-right")
    for key in ("showReefHealth", "showTankName", "showAvatar", "showQuip"):
        assert isinstance(overlay[key], bool)


def test_overlay_garbage_coerced_and_filtered():
    bad = {
        "overlay": {
            "enabled": "yes",
            "stats": ["temp", "not_a_sensor", 5, "ph"],
            "position": "middle",
            "showAvatar": "nah",
        }
    }
    result = normalise(bad)  # must not raise
    overlay = result["overlay"]
    assert overlay["enabled"] is True            # "yes" coerced to bool
    assert "not_a_sensor" not in overlay["stats"]  # unknown sensor dropped
    assert 5 not in overlay["stats"]               # non-str dropped
    assert overlay["stats"] == ["temp", "ph"]      # only real sensor ids, order kept
    assert overlay["position"] == "bottom-left"    # invalid corner -> default
    assert isinstance(overlay["showAvatar"], bool)


def test_overlay_non_dict_block_coerced():
    for junk in ("a string", 7, ["x"], None):
        result = normalise({"overlay": junk})
        assert isinstance(result.get("overlay"), dict)


def test_feedwatch_defaults_injected():
    result = normalise({})
    fw = result.get("feedWatch")
    assert isinstance(fw, dict)
    assert fw["enabled"] is False
    assert fw["cadenceSeconds"] == 10
    assert fw["retentionSessions"] == 25
    assert isinstance(result.get("feedSessions"), list)


def test_feedwatch_garbage_coerced_and_clamped():
    bad = {
        "feedWatch": {
            "enabled": "y",
            "cameraId": 1,
            "cadenceSeconds": 999,
            "retentionSessions": -5,
        }
    }
    result = normalise(bad)  # must not raise
    fw = result["feedWatch"]
    assert fw["enabled"] is True
    assert fw["cameraId"] == ""           # non-str / unknown camera dropped
    assert fw["cadenceSeconds"] == 60     # clamped to max
    assert fw["retentionSessions"] == 1   # clamped to min


def test_feedwatch_non_dict_and_sessions_truncated():
    for junk in ("a string", 7, ["x"], None):
        result = normalise({"feedWatch": junk})
        assert isinstance(result.get("feedWatch"), dict)
    sessions = [{"id": str(i)} for i in range(10)] + ["junk", 5]
    result = normalise({"feedWatch": {"retentionSessions": 3}, "feedSessions": sessions})
    assert len(result["feedSessions"]) == 3
    assert all(isinstance(s, dict) for s in result["feedSessions"])


def test_maintenance_defaults_seeded():
    result = normalise({})
    maintenance = result.get("maintenance")
    assert isinstance(maintenance, dict)
    assert maintenance["enabled"] is True
    assert maintenance["seeded"] is True
    assert len(maintenance["tasks"]) >= 10
    wc = maintenance["tasks"]["water_change"]
    assert wc["enabled"] is False and wc["builtin"] is True
    assert wc["cadenceDays"] == 7 and wc["criticalAfterDays"] == 14


def test_maintenance_deleted_builtin_stays_gone():
    # seeded already True + a list missing most builtins -> they're NOT re-added.
    cfg = {"maintenance": {"seeded": True, "tasks": {"water_change": {"label": "WC", "cadenceDays": 5, "enabled": True}}}}
    maintenance = normalise(cfg)["maintenance"]
    assert set(maintenance["tasks"].keys()) == {"water_change"}
    assert maintenance["tasks"]["water_change"]["cadenceDays"] == 5


def test_maintenance_custom_task_survives_and_clamps():
    cfg = {"maintenance": {"seeded": True, "tasks": {
        "uv": {"label": "UV bulb", "cadenceDays": 9999, "criticalAfterDays": 1, "enabled": True, "builtin": False},
    }}}
    task = normalise(cfg)["maintenance"]["tasks"]["uv"]
    assert task["label"] == "UV bulb" and task["builtin"] is False
    assert task["cadenceDays"] == 365            # clamped to max
    assert task["criticalAfterDays"] == 365      # forced >= cadence


def test_maintenance_completions_restricted_and_truncated():
    cfg = {"maintenance": {"seeded": True,
        "tasks": {"wc": {"label": "WC", "enabled": True}},
        "completions": {
            "wc": [{"timestamp": f"2026-01-{(i % 28) + 1:02d}T00:00:00Z", "notes": "x"} for i in range(80)],
            "ghost": [{"timestamp": "2026-01-01T00:00:00Z"}],
        }}}
    completions = normalise(cfg)["maintenance"]["completions"]
    assert "ghost" not in completions        # completions for unknown tasks dropped
    assert len(completions["wc"]) == 50      # capped at MAINTENANCE_COMPLETIONS_MAX


def test_maintenance_garbage_block_coerced():
    for junk in ("a string", 7, ["x"], None):
        assert isinstance(normalise({"maintenance": junk}).get("maintenance"), dict)


# --- V2: reminders block + per-task schedule/notify/volume fields ------------

def test_maintenance_reminders_defaults_injected():
    reminders = normalise({})["maintenance"]["reminders"]
    assert reminders["enabled"] is True
    assert reminders["time"] == "09:00"
    assert reminders["notifyTarget"] == ""
    assert reminders["persistent"] is True


def test_maintenance_reminders_bad_time_defaults_and_trims():
    cfg = {"maintenance": {"seeded": True, "tasks": {}, "reminders": {
        "time": "9am", "notifyTarget": "  mobile_app_x  ", "persistent": False}}}
    reminders = normalise(cfg)["maintenance"]["reminders"]
    assert reminders["time"] == "09:00"                  # invalid HH:MM -> default
    assert reminders["notifyTarget"] == "mobile_app_x"   # trimmed
    assert reminders["persistent"] is False


def test_maintenance_task_schedule_fields_coerced():
    cfg = {"maintenance": {"seeded": True, "tasks": {"wc": {
        "label": "WC", "enabled": True,
        "scheduleMode": "weird",                # -> interval
        "scheduleDays": [5, 5, 9, "1", -2],     # dedup + clamp 0..6 -> [1, 5]
        "scheduleMonthDays": [1, 40, 15, 15],   # clamp 1..31 -> [1, 15]
        "notify": 0, "logsVolume": 1,
        "snoozedUntil": "not-a-date",           # -> None
    }}}}
    task = normalise(cfg)["maintenance"]["tasks"]["wc"]
    assert task["scheduleMode"] == "interval"
    assert task["scheduleDays"] == [1, 5]
    assert task["scheduleMonthDays"] == [1, 15]
    assert task["notify"] is False and task["logsVolume"] is True
    assert task["snoozedUntil"] is None


def test_maintenance_fixed_schedule_and_snooze_round_trip():
    when = "2026-06-10T09:00:00+00:00"
    cfg = {"maintenance": {"seeded": True, "tasks": {"wc": {
        "label": "WC", "enabled": True, "scheduleMode": "fixed", "scheduleDays": [5], "snoozedUntil": when}}}}
    task = normalise(cfg)["maintenance"]["tasks"]["wc"]
    assert task["scheduleMode"] == "fixed"
    assert task["scheduleDays"] == [5]
    assert task["snoozedUntil"] == when          # valid ISO kept


def test_maintenance_completion_volume_and_skip():
    cfg = {"maintenance": {"seeded": True,
        "tasks": {"wc": {"label": "WC", "enabled": True}},
        "completions": {"wc": [
            {"timestamp": "2026-01-01T00:00:00Z", "volume": 20.5, "volumeUnit": "L"},
            {"timestamp": "2026-01-02T00:00:00Z", "skipped": True},
            {"timestamp": "2026-01-03T00:00:00Z", "volume": "bad"},   # non-number -> dropped
        ]}}}
    entries = normalise(cfg)["maintenance"]["completions"]["wc"]
    assert entries[0]["volume"] == 20.5 and entries[0]["volumeUnit"] == "L"
    assert entries[1]["skipped"] is True
    assert "volume" not in entries[2]


def test_maintenance_water_change_logs_volume_default():
    seeded = normalise({})["maintenance"]["tasks"]
    assert seeded["water_change"]["logsVolume"] is True
    assert seeded["clean_glass"]["logsVolume"] is False


# --- Reef Pulse (presentation/kiosk mode) ------------------------------------

def test_pulse_defaults_injected():
    pulse = normalise({})["pulse"]
    assert pulse["enabled"] is True
    assert pulse["showHealthRing"] is True
    assert pulse["showStats"] is True
    assert pulse["showTicker"] is True
    assert pulse["showMode"] is True
    assert pulse["showBuddy"] is True
    assert pulse["showClock"] is True
    assert pulse["kioskAutoStart"] is False   # kiosk must be opt-in
    assert pulse["cameraId"] == ""


def test_pulse_garbage_block_coerced():
    for junk in ("a string", 7, ["x"], None):
        assert isinstance(normalise({"pulse": junk}).get("pulse"), dict)


def test_pulse_booleans_coerced_and_unknown_camera_cleared():
    cfg = {
        "pulse": {"enabled": 0, "showTicker": "", "kioskAutoStart": 1, "cameraId": "ghost"},
        "cameras": {"display": {"entity_id": "camera.tank", "label": "Display"}},
    }
    pulse = normalise(cfg)["pulse"]
    assert pulse["enabled"] is False
    assert pulse["showTicker"] is False
    assert pulse["kioskAutoStart"] is True
    assert pulse["cameraId"] == ""          # unknown camera id dropped


def test_pulse_known_camera_kept():
    cfg = {
        "pulse": {"cameraId": "display"},
        "cameras": {"display": {"entity_id": "camera.tank", "label": "Display"}},
    }
    assert normalise(cfg)["pulse"]["cameraId"] == "display"


def test_pulse_wall_defaults_injected():
    pulse = normalise({})["pulse"]
    assert pulse["backdrop"] == "auto"
    assert pulse["graphRange"] == "24h"
    assert pulse["showSparklines"] is True
    assert pulse["showCategories"] is True
    assert pulse["showEquipment"] is True
    assert pulse["showToday"] is True


def test_pulse_enums_validated():
    pulse = normalise({"pulse": {"backdrop": "hologram", "graphRange": "1y"}})["pulse"]
    assert pulse["backdrop"] == "auto"        # unknown -> default
    assert pulse["graphRange"] == "24h"
    pulse = normalise({"pulse": {"backdrop": "wall", "graphRange": "7d", "showToday": 0}})["pulse"]
    assert pulse["backdrop"] == "wall"        # valid values kept
    assert pulse["graphRange"] == "7d"
    assert pulse["showToday"] is False


def test_vision_defaults_added_to_older_config():
    """A v45 tester config gains the vision block, disabled, on upgrade."""
    config = normalise({"tank": {"name": "Ragnar"}})
    assert config["schemaVersion"] == DEFAULTS["schemaVersion"]
    vision = config["vision"]
    assert vision["enabled"] is False
    assert vision["topicPrefix"] == "frigate"
    assert vision["cameraName"] == ""
    assert vision["species"] == [] and vision["zones"] == []
    assert vision["surfaceZone"] == "surface"
    assert vision["alerts"] == {"missingFishHours": 0, "surfaceDistress": False}
    assert vision["feedReport"]["enabled"] is False
    assert config["visionReports"] == []
    assert config["visionSummary"] == {}


def test_vision_garbage_clamped():
    """Corrupted vision values normalise to safe defaults instead of crashing."""
    config = normalise({"vision": "corrupt", "visionReports": "nope", "visionSummary": 7})
    assert config["vision"]["enabled"] is False
    assert config["visionReports"] == [] and config["visionSummary"] == {}
    config = normalise(
        {
            "vision": {
                "enabled": 1,
                "topicPrefix": "  /frigate/  ",
                "cameraName": 42,
                "species": ["clownfish", "clownfish", 3, "  wrasse  ", ""],
                "zones": "anemone",
                "surfaceZone": 42,
                "alerts": {"missingFishHours": 99999, "surfaceDistress": "yes"},
                "feedReport": {"windowSeconds": 5, "enabled": "on"},
            },
            "visionReports": [{"ok": True}, "junk", {"ok": 2}],
        }
    )
    vision = config["vision"]
    assert vision["enabled"] is True
    assert vision["topicPrefix"] == "frigate"          # stripped of slashes/space
    assert vision["cameraName"] == ""                  # non-string dropped
    assert vision["species"] == ["clownfish", "wrasse"]  # deduped, trimmed, non-strings out
    assert vision["zones"] == []                       # non-list -> empty
    assert vision["surfaceZone"] == "surface"          # non-string -> default
    assert vision["alerts"]["missingFishHours"] == 168  # clamped to a week
    assert vision["alerts"]["surfaceDistress"] is True
    assert vision["feedReport"]["windowSeconds"] == 30  # clamped to minimum
    assert config["visionReports"] == [{"ok": True}, {"ok": 2}]  # dicts only



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
