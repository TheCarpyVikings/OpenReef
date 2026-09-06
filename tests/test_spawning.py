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
from types import SimpleNamespace
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

from _fake_ha import FakeConnection, FakeEntry, FakeHass, FakeState, run  # noqa: E402

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
    assert "RT+-0.2" in snips["temperature_heater"]["code"]


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


# --- Lighting schedule (drives alert gating) ---------------------------------

def test_lighting_window_off_is_none():
    assert spawning.lighting_window({"mode": "off"}, _d(2026, 1, 15)) is None
    assert spawning.lighting_window(None, _d(2026, 1, 15)) is None


def test_lighting_window_simple():
    win = spawning.lighting_window({"mode": "simple", "onTime": "08:00", "offTime": "20:00"}, _d(2026, 1, 15))
    assert win == (480, 1200)


def test_is_lights_on_no_schedule_is_true():
    assert spawning.is_lights_on({"mode": "off"}, datetime(2026, 1, 15, 3, 0), 30) is True
    assert spawning.is_lights_on(None, datetime(2026, 1, 15, 3, 0), 30) is True


def test_is_lights_on_simple_boundaries():
    s = {"mode": "simple", "onTime": "08:00", "offTime": "20:00"}
    assert spawning.is_lights_on(s, datetime(2026, 1, 1, 7, 59), 0) is False
    assert spawning.is_lights_on(s, datetime(2026, 1, 1, 8, 0), 0) is True
    assert spawning.is_lights_on(s, datetime(2026, 1, 1, 19, 59), 0) is True
    assert spawning.is_lights_on(s, datetime(2026, 1, 1, 20, 0), 0) is False


def test_grace_narrows_window():
    s = {"mode": "simple", "onTime": "08:00", "offTime": "20:00"}
    assert spawning.is_lights_on(s, datetime(2026, 1, 1, 8, 15), 30) is False
    assert spawning.is_lights_on(s, datetime(2026, 1, 1, 8, 45), 30) is True
    assert spawning.is_lights_on(s, datetime(2026, 1, 1, 19, 45), 30) is False


def test_grace_clamped_when_window_short():
    # Absurd grace on a 2h window must not invert it — the midpoint stays alertable.
    s = {"mode": "simple", "onTime": "12:00", "offTime": "14:00"}
    assert spawning.is_lights_on(s, datetime(2026, 1, 1, 13, 0), 600) is True


def test_equal_times_never_suppress():
    # Degenerate schedule (onTime == offTime) must read as lights-on 24h so a real
    # low reading is never silently suppressed — at any grace, any hour.
    s = {"mode": "simple", "onTime": "08:00", "offTime": "08:00"}
    for grace in (0, 30):
        for h in (2, 8, 14, 23):
            assert spawning.is_lights_on(s, datetime(2026, 1, 1, h, 0), grace) is True, (grace, h)


def test_midnight_wrap_window():
    s = {"mode": "simple", "onTime": "20:00", "offTime": "06:00"}
    assert spawning.is_lights_on(s, datetime(2026, 1, 1, 23, 0), 0) is True
    assert spawning.is_lights_on(s, datetime(2026, 1, 1, 12, 0), 0) is False


def test_reef_window_tracks_offset():
    base = spawning.lighting_window({"mode": "reef", "reefPreset": "gbr_central", "offsetHours": 0}, _d(2026, 1, 15))
    shifted = spawning.lighting_window({"mode": "reef", "reefPreset": "gbr_central", "offsetHours": 2}, _d(2026, 1, 15))
    assert shifted[0] == (base[0] + 120) % 1440
    assert shifted[1] == (base[1] + 120) % 1440


def test_lighting_window_summary_reef():
    summ = spawning.lighting_window_summary(
        {"mode": "reef", "reefPreset": "gbr_central", "offsetHours": 2, "rampGraceMinutes": 30},
        datetime(2026, 1, 15, 14, 0),
    )
    assert summ["configured"] is True and summ["lightsOnNow"] is True
    assert ":" in summ["onTime"] and ":" in summ["offTime"]
    assert summ["reefLabel"] == "Great Barrier Reef (Central)"


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


# --- Smart-plug execution: desired state (pure engine) -----------------------

def _sp_cfg(**exec_over):
    cfg = {
        "reefPreset": "gbr_central",
        "offsetMonths": 0,
        "solarNoonHour": 13.0,
        "execution": {"moonMinIlluminationPct": 25},
    }
    cfg["execution"].update(exec_over)
    return cfg


def test_execution_desired_state_day_and_night():
    cfg = _sp_cfg()
    day = spawning.execution_desired_state(cfg, datetime(2026, 6, 17, 13, 0, tzinfo=timezone.utc))
    assert day["valid"] and day["light"] is True and day["moon"] is False
    night = spawning.execution_desired_state(cfg, datetime(2026, 6, 17, 1, 0, tzinfo=timezone.utc))
    assert night["light"] is False
    # GBR austral winter: a genuinely short day, centred on the 13:00 solar noon.
    assert 10.0 < day["dayLengthHours"] < 12.0
    sr_h = int(day["sunrise"].split(":")[0])
    ss_h = int(day["sunset"].split(":")[0])
    assert sr_h < 13 < ss_h


def test_execution_offset_maps_reef_date():
    cfg = _sp_cfg()
    cfg["offsetMonths"] = 4
    state = spawning.execution_desired_state(cfg, datetime(2026, 8, 15, 13, 0, tzinfo=timezone.utc))
    assert state["reefDate"] == "2026-04-15"
    assert state["reefMonthName"] == "April"


def test_execution_moon_dark_night_hold():
    cfg = _sp_cfg()
    # 2000-01-06 was a new moon: the night must stay genuinely dark.
    new_moon_night = spawning.execution_desired_state(
        cfg, datetime(2000, 1, 6, 22, 0, tzinfo=timezone.utc)
    )
    assert new_moon_night["light"] is False
    assert new_moon_night["moonQualifies"] is False and new_moon_night["moon"] is False
    # 2000-01-21 was a full moon: moonlight runs through the night window.
    full_moon_night = spawning.execution_desired_state(
        cfg, datetime(2000, 1, 21, 22, 0, tzinfo=timezone.utc)
    )
    assert full_moon_night["moonIlluminationPct"] > 90
    assert full_moon_night["moon"] is True


def test_execution_next_transition():
    cfg = _sp_cfg()
    pre_dawn = spawning.execution_desired_state(cfg, datetime(2026, 6, 17, 5, 0, tzinfo=timezone.utc))
    assert pre_dawn["nextTransition"]["kind"] == "sunrise"
    assert pre_dawn["nextTransition"]["tomorrow"] is False
    late = spawning.execution_desired_state(cfg, datetime(2026, 6, 17, 23, 0, tzinfo=timezone.utc))
    assert late["nextTransition"]["kind"] == "sunrise"
    assert late["nextTransition"]["tomorrow"] is True
    assert late["nextTransition"]["inMinutes"] > 0


def test_execution_unknown_preset_invalid():
    assert spawning.execution_desired_state({"reefPreset": "atlantis"}, datetime(2026, 1, 1, tzinfo=timezone.utc))["valid"] is False


# --- Smart-plug execution: config normalisation ------------------------------

def test_normalise_execution_defaults():
    ex = normalise({})["spawningProgram"]["execution"]
    assert ex == {
        "mode": "apex", "armed": False, "lightEntity": None, "moonEntity": None,
        "moonMinIlluminationPct": 25, "overridePolicy": "hold",
        "temp": {
            "enabled": False, "acknowledged": False, "sensorEntity": None,
            "heaterEntity": None, "coolEntity": None, "maxC": 27.5, "minC": 22.0,
            "staleMinutes": 15, "coolMinOffSeconds": 180,
        },
    }


def test_normalise_execution_clamps():
    ex = normalise({"spawningProgram": {"execution": {
        "mode": "banana", "armed": 1, "lightEntity": "sensor.nope",
        "moonEntity": "light.moon_bar", "moonMinIlluminationPct": 250,
        "overridePolicy": "shout", "junkKey": True,
    }}})["spawningProgram"]["execution"]
    assert ex["mode"] == "apex" and ex["armed"] is True
    assert ex["lightEntity"] is None                # wrong domain dropped
    assert ex["moonEntity"] == "light.moon_bar"     # light.* allowed
    assert ex["moonMinIlluminationPct"] == 100
    assert ex["overridePolicy"] == "hold"
    assert "junkKey" not in ex


def test_normalise_lighting_mode_spawning_survives():
    assert normalise({"lightingSchedule": {"mode": "spawning"}})["lightingSchedule"]["mode"] == "spawning"


# --- Smart-plug execution: the reconcile tick --------------------------------

def _exec_entry(extra=None, **exec_over):
    execution = {
        "mode": "openreef", "armed": True, "lightEntity": "switch.tank_light",
        "moonEntity": None, "moonMinIlluminationPct": 25, "overridePolicy": "hold",
    }
    execution.update(exec_over)
    cfg = {"spawningProgram": {
        "enabled": True, "reefPreset": "gbr_central", "offsetMonths": 0,
        "solarNoonHour": 13.0, "execution": execution,
    }}
    cfg.update(extra or {})
    return FakeEntry(options={CONF_SETTINGS: normalise(cfg)})


def _exec_hass(entry, states=None):
    base = {"switch.tank_light": "off"}
    base.update(states or {})
    return FakeHass(states=base, entries=[entry])


def _switch_calls(hass, service, entity="switch.tank_light"):
    return [c for c in hass.services.calls
            if c.service == service and entity in c.data.values()]


def _noon(minute=0):
    return datetime(2026, 6, 17, 13, minute, tzinfo=timezone.utc)


def _night():
    return datetime(2026, 6, 17, 23, 0, tzinfo=timezone.utc)


def test_tick_asserts_daylight_and_is_idempotent():
    entry = _exec_entry()
    hass = _exec_hass(entry)
    run(integration._async_spawning_tick(hass, entry, _noon()))
    assert len(_switch_calls(hass, "turn_on")) == 1
    assert hass.states.get("switch.tank_light").state == "on"
    run(integration._async_spawning_tick(hass, entry, _noon(1)))
    assert len(_switch_calls(hass, "turn_on")) == 1  # reconciled: no service spam
    activity = entry.options[CONF_SETTINGS]["activity"]
    assert any("took the daylight plug" in a["message"] for a in activity)


def test_tick_hold_respects_manual_change_until_transition():
    entry = _exec_entry()
    hass = _exec_hass(entry)
    run(integration._async_spawning_tick(hass, entry, _noon()))
    hass.states.set("switch.tank_light", "off")  # direct HA user action
    hass.states.get("switch.tank_light").context = SimpleNamespace(user_id="tester", parent_id=None)
    run(integration._async_spawning_tick(hass, entry, _noon(2)))
    assert len(_switch_calls(hass, "turn_on")) == 1  # held, not re-asserted
    runtime = hass.data[integration.DOMAIN][integration.SPAWNING_RUNTIME]
    assert "light" in runtime["overrides"]
    # Sunset passes: desired flips to off, the override clears, nothing to switch.
    run(integration._async_spawning_tick(hass, entry, _night()))
    assert runtime["overrides"] == {}
    assert len(_switch_calls(hass, "turn_off")) == 0


def test_tick_reassert_policy_corrects_within_a_tick():
    entry = _exec_entry(overridePolicy="reassert")
    hass = _exec_hass(entry)
    run(integration._async_spawning_tick(hass, entry, _noon()))
    hass.states.set("switch.tank_light", "off")
    run(integration._async_spawning_tick(hass, entry, _noon(2)))
    assert len(_switch_calls(hass, "turn_on")) == 2


def test_tick_unavailable_entity_alerts_once_and_keeps_trying():
    entry = _exec_entry()
    hass = _exec_hass(entry, {"switch.tank_light": "unavailable"})
    run(integration._async_spawning_tick(hass, entry, _noon()))
    run(integration._async_spawning_tick(hass, entry, _noon(1)))
    assert not _switch_calls(hass, "turn_on")
    notes = [c for c in hass.services.calls if c.domain == "persistent_notification"]
    assert len(notes) == 1  # cooldown-deduped
    runtime = hass.data[integration.DOMAIN][integration.SPAWNING_RUNTIME]
    assert "light" in runtime["issues"]


def test_tick_disarmed_never_touches_the_plugs():
    entry = _exec_entry(armed=False)
    hass = _exec_hass(entry)
    run(integration._async_spawning_tick(hass, entry, _noon()))
    assert not hass.services.calls


def test_tick_moonlight_follows_the_real_moon():
    entry = _exec_entry(moonEntity="switch.moon")
    # New-moon night: a moonlight plug left on must be switched off (dark night).
    hass = _exec_hass(entry, {"switch.moon": "on"})
    run(integration._async_spawning_tick(
        hass, entry, datetime(2000, 1, 6, 22, 0, tzinfo=timezone.utc)))
    assert len(_switch_calls(hass, "turn_off", "switch.moon")) == 1
    # Full-moon night: moonlight comes on.
    hass2 = _exec_hass(entry, {"switch.moon": "off"})
    run(integration._async_spawning_tick(
        hass2, entry, datetime(2000, 1, 21, 22, 0, tzinfo=timezone.utc)))
    assert len(_switch_calls(hass2, "turn_on", "switch.moon")) == 1


# --- Stage C: RT target sensor + guarded seasonal heat/cool ------------------

_TEMP_BINDINGS = {
    "enabled": True, "acknowledged": True, "sensorEntity": "sensor.tank_temp",
    "heaterEntity": "switch.heater", "coolEntity": "switch.fan",
    "maxC": 29.5, "coolMinOffSeconds": 0,
}
_GBR_JUNE_RT = spawning.seasonal_temperature(REEF_PRESETS["gbr_central"], _noon().date())


def _fresh(value, attrs=None):
    return FakeState(str(value), {"unit_of_measurement": "°C", **(attrs or {})}, last_changed=datetime.now(timezone.utc))


def _temp_entry(**temp_over):
    temp = dict(_TEMP_BINDINGS)
    temp.update(temp_over)
    return _exec_entry(lightEntity=None, temp=temp)


def test_temp_normalise_requires_ack_and_bindings():
    no_ack = normalise({"spawningProgram": {"execution": {"temp": {
        "enabled": True, "sensorEntity": "sensor.t", "heaterEntity": "switch.h",
    }}}})["spawningProgram"]["execution"]["temp"]
    assert no_ack["enabled"] is False  # unacknowledged never arms
    ok = normalise({"spawningProgram": {"execution": {"temp": dict(_TEMP_BINDINGS)}}})
    assert ok["spawningProgram"]["execution"]["temp"]["enabled"] is True
    swapped = normalise({"spawningProgram": {"execution": {"temp": {
        **_TEMP_BINDINGS, "maxC": 21.0, "minC": 25.0,
    }}}})["spawningProgram"]["execution"]["temp"]
    assert swapped["minC"] < swapped["maxC"]  # inverted clamps fall back to defaults


def test_tick_publish_only_mode_sets_sensor_and_never_switches():
    # Feature on, execution left on "apex": the sensor publishes, nothing actuates.
    entry = _exec_entry(mode="apex", armed=False)
    hass = _exec_hass(entry)
    run(integration._async_spawning_tick(hass, entry, _noon()))
    sensor = hass.states.get("sensor.openreef_spawning_target_temp")
    assert sensor is not None and sensor.state == f"{_GBR_JUNE_RT:.1f}"
    assert sensor.attributes["reefMonth"] == "June"
    assert not hass.services.calls


def test_tick_temp_bang_bang_mirrors_apex_snippets():
    entry = _temp_entry()
    # Cold tank: heater on, fan stays off.
    hass = _exec_hass(entry, {
        "sensor.tank_temp": _fresh(_GBR_JUNE_RT - 0.7),
        "switch.heater": "off", "switch.fan": "off",
    })
    run(integration._async_spawning_tick(hass, entry, _noon()))
    assert len(_switch_calls(hass, "turn_on", "switch.heater")) == 1
    assert not _switch_calls(hass, "turn_on", "switch.fan")
    # Warm tank: heater (left on) switches off, fan comes on.
    hass2 = _exec_hass(entry, {
        "sensor.tank_temp": _fresh(_GBR_JUNE_RT + 0.7),
        "switch.heater": "on", "switch.fan": "off",
    })
    run(integration._async_spawning_tick(hass2, entry, _noon()))
    assert len(_switch_calls(hass2, "turn_off", "switch.heater")) == 1
    assert len(_switch_calls(hass2, "turn_on", "switch.fan")) == 1
    # Inside the band: hysteresis holds whatever is running — no calls at all.
    hass3 = _exec_hass(entry, {
        "sensor.tank_temp": _fresh(_GBR_JUNE_RT),
        "switch.heater": "on", "switch.fan": "off",
    })
    run(integration._async_spawning_tick(hass3, entry, _noon()))
    assert not [c for c in hass3.services.calls if c.domain == "switch"]


def test_tick_temp_hard_clamp_beats_the_curve():
    entry = _temp_entry(maxC=24.0)
    hass = _exec_hass(entry, {
        "sensor.tank_temp": _fresh(24.2),  # below RT−tol (wants heat) but at/above maxC
        "switch.heater": "on", "switch.fan": "off",
    })
    run(integration._async_spawning_tick(hass, entry, _noon()))
    assert len(_switch_calls(hass, "turn_off", "switch.heater")) == 1


def test_tick_temp_stale_sensor_fails_everything_off():
    entry = _temp_entry()
    hass = _exec_hass(entry, {
        "sensor.tank_temp": "24.0",  # default FakeState timestamp = long stale
        "switch.heater": "on", "switch.fan": "on",
    })
    run(integration._async_spawning_tick(hass, entry, _noon()))
    assert len(_switch_calls(hass, "turn_off", "switch.heater")) == 1
    assert len(_switch_calls(hass, "turn_off", "switch.fan")) == 1
    runtime = hass.data[integration.DOMAIN][integration.SPAWNING_RUNTIME]
    assert "temp" in runtime["issues"]
    assert len([c for c in hass.services.calls if c.domain == "persistent_notification"]) == 1


def test_tick_temp_fahrenheit_sensor_converts():
    entry = _temp_entry()
    hass = _exec_hass(entry, {
        "sensor.tank_temp": _fresh(75.2, {"unit_of_measurement": "°F"}),  # 24.0 °C
        "switch.heater": "off", "switch.fan": "off",
    })
    run(integration._async_spawning_tick(hass, entry, _noon()))
    assert len(_switch_calls(hass, "turn_on", "switch.heater")) == 1
    runtime = hass.data[integration.DOMAIN][integration.SPAWNING_RUNTIME]
    assert abs(runtime["tempReading"] - 24.0) < 0.05


# --- Stage D: spawn-window night capture --------------------------------------

def test_tick_captures_one_window_night():
    prediction = spawning.predict_spawn_window(
        REEF_PRESETS["gbr_central"], 2026, 0,
        today=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    night = datetime.fromisoformat(prediction["windowStart"] + "T22:00:00+00:00")
    entry = _exec_entry(
        mode="apex", armed=False,
        extra={"capture": {"enabled": True, "triggers": {"spawnWindowNight": True}}},
    )
    hass = _exec_hass(entry)
    run(integration._async_spawning_tick(hass, entry, night))
    assert hass.tasks.count("openreef_capture") == 1
    run(integration._async_spawning_tick(hass, entry, night.replace(minute=30)))
    assert hass.tasks.count("openreef_capture") == 1  # one capture per night


def test_tick_no_capture_when_trigger_off():
    prediction = spawning.predict_spawn_window(
        REEF_PRESETS["gbr_central"], 2026, 0,
        today=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    night = datetime.fromisoformat(prediction["windowStart"] + "T22:00:00+00:00")
    entry = _exec_entry(mode="apex", armed=False,
                        extra={"capture": {"enabled": True}})  # trigger defaults off
    hass = _exec_hass(entry)
    run(integration._async_spawning_tick(hass, entry, night))
    assert "openreef_capture" not in hass.tasks


# --- Smart-plug execution: websocket + lighting bridge -----------------------

def test_ws_execution_status_shape():
    entry = _exec_entry()
    hass = _exec_hass(entry)
    conn = FakeConnection()
    integration.websocket_spawning_execution_status(hass, conn, {"id": 1})
    assert not conn.errors, conn.error_codes
    payload = conn.results[0].payload
    assert payload["execution"]["mode"] == "openreef"
    assert payload["state"]["valid"] is True
    assert payload["entities"]["light"]["entity"] == "switch.tank_light"
    assert payload["runtime"]["controlling"] is True


def test_ws_execution_resume_clears_overrides():
    entry = _exec_entry()
    hass = _exec_hass(entry)
    hass.data.setdefault(integration.DOMAIN, {})[integration.SPAWNING_RUNTIME] = {
        "overrides": {"light": {"since": "x", "desiredAtOverride": True}}
    }
    conn = FakeConnection()
    integration.websocket_spawning_execution_resume(hass, conn, {"id": 2})
    assert not conn.errors, conn.error_codes
    assert hass.data[integration.DOMAIN][integration.SPAWNING_RUNTIME]["overrides"] == {}


def test_effective_lighting_cfg_resolves_spawning_mode():
    config = normalise({
        "lightingSchedule": {"mode": "spawning"},
        "spawningProgram": {"reefPreset": "gbr_central", "solarNoonHour": 13.0},
    })
    now = datetime(2026, 6, 17, 13, 0, tzinfo=timezone.utc)
    eff = integration._effective_lighting_cfg(config, now)
    state = spawning.execution_desired_state(config["spawningProgram"], now)
    assert eff["mode"] == "simple"
    assert eff["onTime"] == state["sunrise"] and eff["offTime"] == state["sunset"]
    # Non-spawning modes pass through untouched.
    plain = normalise({"lightingSchedule": {"mode": "simple"}})
    assert integration._effective_lighting_cfg(plain, now)["mode"] == "simple"


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
