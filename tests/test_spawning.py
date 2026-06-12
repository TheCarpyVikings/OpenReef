"""Coral Spawning engine — astronomy, presets, compiler, and config normalisation.

The spawning engine (custom_components/openreef/spawning.py) is pure stdlib, so it
unit-tests cleanly. We validate the astronomy against known anchors (the 2000-01-06
new moon, equinox/solstice day lengths) rather than re-deriving it, then assert the
compiler emits the exact Apex code reefers hand-author, and that config
normalisation clamps the persisted selection.

Run standalone:  python3 tests/test_spawning.py
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
import openreef as integration  # noqa: E402
from openreef import spawning  # noqa: E402
from openreef.const import CORE_SCHEMA_VERSION, REEF_PRESETS  # noqa: E402

from _fake_ha import FakeConnection, FakeEntry, FakeHass  # noqa: E402

normalise = integration._normalise_core_config
CONF_SETTINGS = integration.CONF_SETTINGS


def _d(y, m, day):
    return date(y, m, day)


# --- Solar: day length -------------------------------------------------------

def test_equinox_day_length_near_12h_everywhere():
    for lat in (0.0, 1.3, -18.5, 29.5, 24.7):
        dl = spawning.day_length_hours(lat, _d(2026, 3, 20))
        assert 11.7 < dl < 12.5, f"equinox dl {dl} at lat {lat}"


def test_southern_reef_summer_longer_than_winter():
    # GBR (~18.5S): austral summer (Dec) day length > austral winter (Jun).
    dec = spawning.day_length_hours(-18.5, _d(2026, 12, 21))
    jun = spawning.day_length_hours(-18.5, _d(2026, 6, 21))
    assert dec > jun + 1.5, f"dec {dec} jun {jun}"
    assert 12.8 < dec < 13.8


def test_equatorial_daylength_barely_moves():
    lengths = [spawning.day_length_hours(1.3, _d(2026, m, 15)) for m in range(1, 13)]
    assert max(lengths) - min(lengths) < 0.4, f"swing {max(lengths) - min(lengths)}"


def test_anchored_sun_times_symmetric():
    sunrise, sunset, dl = spawning.anchored_sun_times(-18.5, _d(2026, 11, 15), 13.0)
    sr_h = int(sunrise[:2]) + int(sunrise[3:]) / 60
    ss_h = int(sunset[:2]) + int(sunset[3:]) / 60
    assert abs((sr_h + ss_h) / 2 - 13.0) < 0.05, "photoperiod not centered on solar noon"
    assert abs((ss_h - sr_h) - dl) < 0.05, "sunset-sunrise != day length"


# --- Lunar: validate against known anchors -----------------------------------

def test_known_new_moon_2000_01_06():
    events = spawning.lunar_events(datetime(2000, 1, 3, tzinfo=timezone.utc),
                                   datetime(2000, 1, 10, tzinfo=timezone.utc))
    dates = [nm.date() for nm in events["new_moons"]]
    assert _d(2000, 1, 6) in dates, f"got {dates}"


def test_known_full_moon_2000_01_21():
    events = spawning.lunar_events(datetime(2000, 1, 18, tzinfo=timezone.utc),
                                   datetime(2000, 1, 24, tzinfo=timezone.utc))
    assert events["full_moons"], "no full moon found"
    fm = events["full_moons"][0]
    assert abs((fm.date() - _d(2000, 1, 21)).days) <= 1, f"full moon {fm}"


def test_new_moons_spaced_one_synodic_month():
    events = spawning.lunar_events(datetime(2026, 1, 1, tzinfo=timezone.utc),
                                   datetime(2026, 12, 31, tzinfo=timezone.utc))
    nm = events["new_moons"]
    assert 11 <= len(nm) <= 13, f"expected ~12 new moons, got {len(nm)}"
    gaps = [(nm[i + 1] - nm[i]).total_seconds() / 86400 for i in range(len(nm) - 1)]
    for g in gaps:
        assert 29.0 < g < 30.1, f"new-moon gap {g}"


def test_illumination_zero_at_new_one_at_full():
    events = spawning.lunar_events(datetime(2026, 1, 1, tzinfo=timezone.utc),
                                   datetime(2026, 3, 1, tzinfo=timezone.utc))
    nm = events["new_moons"][0]
    fm = events["full_moons"][0]
    assert spawning.moon_illumination(nm) < 0.05, "new moon should be ~dark"
    assert spawning.moon_illumination(fm) > 0.95, "full moon should be ~lit"


# --- Compiler: the artifacts a reefer pastes into the Apex --------------------

def test_generate_program_shape():
    prog = spawning.generate_program("gbr_central", 2026, today=datetime(2026, 6, 12, tzinfo=timezone.utc))
    assert prog["preset"]["id"] == "gbr_central"
    assert len(prog["seasonTable"]) == 12
    assert 11 <= len(prog["newMoonDates"]) <= 13
    for row in prog["seasonTable"]:
        assert ":" in row["sunrise"] and ":" in row["sunset"]
        assert 10 < row["dayLengthHours"] < 14


def test_generate_program_emits_rich_ross_code():
    snips = spawning.generate_program("gbr_central", 2026)["codeSnippets"]
    assert "If Sun 000/-360 Then Sunup" in snips["daylight_3step"]["code"]
    assert "If Sun 360/000 Then Sunset" in snips["daylight_3step"]["code"]
    assert "If Sun 180/-180 Then Midday" in snips["daylight_3step"]["code"]
    assert "If Moon 000/000 Then ON" in snips["lunar_lsm"]["code"]
    assert "If Output vMoon = ON Then Moonlight" in snips["radion_moonlight"]["code"]
    assert "RT-0.2" in snips["temperature_heater"]["code"]


def test_temp_probe_and_unit_flow_into_code():
    snips = spawning.generate_program(
        "gbr_central", 2026, temp_unit="F", temp_probe="SP1tmp"
    )["codeSnippets"]
    assert "SP1tmp" in snips["temperature_heater"]["code"]
    assert "°F" in snips["temperature_heater"]["label"]
    # Season table temps should be Fahrenheit when requested
    row = spawning.generate_program("gbr_central", 2026, temp_unit="F")["seasonTable"][0]
    assert row["temp"] == round(row["tempC"] * 9 / 5 + 32, 1)


def test_offset_shifts_local_spawning_month():
    # GBR spawns reef-month 11 (Nov). With a +6 offset it maps to local May.
    pred = spawning.predict_spawn_window(REEF_PRESETS["gbr_central"], 2026, 6)
    assert pred["localSpawnMonth"] == 5, pred
    # local January should now mimic reef July
    row = spawning.build_environmental_model(REEF_PRESETS["gbr_central"], 2026, 6, 13.0, "C")[0]
    assert row["reefMonth"] == 7, row


def test_spawn_prediction_window_uses_days_after_full_moon():
    pred = spawning.predict_spawn_window(
        REEF_PRESETS["gbr_central"], 2026, 0, today=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    assert pred["daysAfterFullMoon"] == [12, 15]
    assert "windowStart" in pred and "windowEnd" in pred
    start = datetime.fromisoformat(pred["windowStart"]).date()
    full = datetime.fromisoformat(pred["fullMoonUtc"]).date()
    assert (start - full).days == 12


def test_unknown_preset_raises():
    raised = False
    try:
        spawning.generate_program("atlantis", 2026)
    except KeyError:
        raised = True
    assert raised


def test_list_presets_metadata():
    presets = spawning.list_presets()
    assert {p["id"] for p in presets} == set(REEF_PRESETS)
    for p in presets:
        assert p["hemisphere"] in ("N", "S")
        assert len(p["tempRangeC"]) == 2


# --- Preset data integrity ---------------------------------------------------

def test_presets_well_formed():
    for pid, p in REEF_PRESETS.items():
        assert len(p["sstMonthlyC"]) == 12, pid
        assert 1 <= p["spawnReefMonth"] <= 12, pid
        lo, hi = p["daysAfterFullMoon"]
        assert 0 <= lo <= hi <= 30, pid
        assert -90 < p["lat"] < 90, pid


# --- Config normalisation ----------------------------------------------------

def test_default_config_has_spawning_section():
    cfg = normalise({})
    assert cfg["schemaVersion"] == CORE_SCHEMA_VERSION
    sp = cfg["spawningProgram"]
    assert sp["reefPreset"] in REEF_PRESETS
    assert sp["enabled"] is False


def test_normalise_clamps_and_validates():
    cfg = normalise(
        {
            "spawningProgram": {
                "enabled": True,
                "reefPreset": "atlantis",     # invalid -> default
                "offsetMonths": 20,            # clamp to 11
                "solarNoonHour": 99,           # clamp to 23.5
                "tempUnit": "f",               # -> F
                "tempProbe": "  MyProbe  ",
            }
        }
    )
    sp = cfg["spawningProgram"]
    assert sp["enabled"] is True
    assert sp["reefPreset"] == "gbr_central"
    assert sp["offsetMonths"] == 11
    assert sp["solarNoonHour"] == 23.5
    assert sp["tempUnit"] == "F"
    assert sp["tempProbe"] == "MyProbe"


def test_normalise_negative_offset_floors_to_zero():
    cfg = normalise({"spawningProgram": {"offsetMonths": -4, "tempUnit": "bogus"}})
    assert cfg["spawningProgram"]["offsetMonths"] == 0
    assert cfg["spawningProgram"]["tempUnit"] == "C"


# --- Websocket handlers (the real backend entry points) ----------------------

def test_ws_list_reef_presets():
    conn = FakeConnection()
    integration.websocket_list_reef_presets(FakeHass(entries=[]), conn, {"id": 1})
    assert not conn.errors
    presets = conn.results[0].payload["presets"]
    assert {p["id"] for p in presets} == set(REEF_PRESETS)


def test_ws_generate_uses_explicit_preset():
    entry = FakeEntry(options={CONF_SETTINGS: {"spawningProgram": {"reefPreset": "singapore"}}})
    conn = FakeConnection()
    integration.websocket_generate_spawning_program(
        FakeHass(entries=[entry]), conn, {"id": 2, "reefPreset": "caribbean_florida", "tempUnit": "F"}
    )
    assert not conn.errors, conn.error_codes
    prog = conn.results[0].payload["program"]
    assert prog["preset"]["id"] == "caribbean_florida"
    assert prog["params"]["tempUnit"] == "F"
    assert len(prog["seasonTable"]) == 12


def test_ws_generate_falls_back_to_saved_selection():
    entry = FakeEntry(options={CONF_SETTINGS: {"spawningProgram": {"reefPreset": "red_sea_aqaba", "offsetMonths": 3}}})
    conn = FakeConnection()
    integration.websocket_generate_spawning_program(FakeHass(entries=[entry]), conn, {"id": 3})
    assert not conn.errors, conn.error_codes
    prog = conn.results[0].payload["program"]
    assert prog["preset"]["id"] == "red_sea_aqaba"
    assert prog["params"]["offsetMonths"] == 3


def test_ws_generate_unknown_preset_errors():
    conn = FakeConnection()
    integration.websocket_generate_spawning_program(
        FakeHass(entries=[]), conn, {"id": 4, "reefPreset": "atlantis"}
    )
    assert "unknown_preset" in conn.error_codes


# --- tiny standalone runner --------------------------------------------------

def _main() -> int:
    tests = sorted(
        (name, obj) for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    )
    passed = 0
    failed = []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{passed}/{len(tests)} passed", "" if not failed else f"— FAILED: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
