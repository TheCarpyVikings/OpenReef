"""Cooling headroom (Layer 1): the psychrometrics in cooling.py, the
normaliser, the sensor snapshot against the fake HA, the gated
once-per-band warning tick, and the two WS handlers.

What is pinned is the JUDGEMENT the feature exists for: a fan over a reef
tank is limited by the room's dew point against the water, so a cool humid
day must stay silent while a hot humid one warns — and warns once.

Run standalone:  python3 tests/test_cooling.py
Or with pytest:  pytest tests/
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
import openreef as integration  # noqa: E402
from openreef import cooling  # noqa: E402

from _fake_ha import FakeConnection, FakeEntry, FakeHass, FakeState, run  # noqa: E402

CONF_SETTINGS = integration.CONF_SETTINGS
normalise = integration._normalise_core_config
NOW = datetime(2026, 7, 14, 14, 0, tzinfo=timezone.utc)


def _fresh(value, unit="°C"):
    return FakeState(str(value), {"unit_of_measurement": unit}, last_changed=datetime.now(timezone.utc))


def _entry(enabled=True, room="sensor.room", hum="sensor.hum", water="sensor.tank", **over):
    cfg = {"coolingHeadroom": {
        "enabled": enabled, "roomTempEntity": room, "humidityEntity": hum,
        "waterTempEntity": water, "targetTempC": 25.5, **over,
    }}
    return FakeEntry(options={CONF_SETTINGS: normalise(cfg)})


def _hass(entry, room=30.0, rh=80.0, tank=26.0, states=None):
    base = {"sensor.room": _fresh(room), "sensor.hum": _fresh(rh, "%"), "sensor.tank": _fresh(tank)}
    base.update(states or {})
    return FakeHass(states=base, entries=[entry])


def _notes(hass):
    # A config save also runs the watchdog heartbeat (creates/dismisses its own
    # notifications), so count only the creates that are ours.
    return [c for c in hass.services.calls
            if c.domain == "persistent_notification" and c.service == "create"
            and "cooling" in str(c.data.get("notification_id", ""))]


def _activity(entry):
    return [a for a in (entry.options[CONF_SETTINGS].get("activity") or [])
            if "Cooling headroom" in a["message"]]


# --------------------------------------------------------------------------- #
# cooling.py — the published figures
# --------------------------------------------------------------------------- #

def test_dew_point_and_wet_bulb_match_published_values():
    assert abs(cooling.dew_point_c(20, 50) - 9.3) < 0.1        # Magnus, textbook
    assert abs(cooling.wet_bulb_c(20, 50) - 13.7) < 0.2         # Stull 2011 worked example
    assert abs(cooling.dew_point_c(30, 80) - 26.2) < 0.1        # the reversed case on a 26 °C tank
    assert cooling.dew_point_c(25, 100) - 25 < 0.01             # saturated air: dew point = dry bulb


def test_reference_day_scores_one_and_the_table_rows_hold():
    good = cooling.evaluate(26, 28, 40)
    assert good["band"] == "good" and abs(good["index"] - 1.0) < 0.01 and good["netFan"] == "cooling"
    cool_humid = cooling.evaluate(26, 22, 80)
    assert cool_humid["band"] in ("good", "thin") and cool_humid["index"] > 0.6
    hot_humid = cooling.evaluate(26, 30, 60)
    assert hot_humid["band"] == "thin" and 0.4 <= hot_humid["index"] < 0.5
    weak = cooling.evaluate(26, 30, 70)
    assert weak["band"] == "weak"
    reversed_ = cooling.evaluate(26, 30, 80)
    assert reversed_["band"] == "reversed" and reversed_["netFan"] == "heating"
    assert reversed_["index"] == 0 and reversed_["marginC"] < 0
    # Dew point at the water but the room COOLER than the water: dead, not heating.
    dead = cooling.evaluate(20, 20, 100)
    assert dead["band"] == "dead" and dead["netFan"] == "none"


def test_cool_but_humid_beats_hot_and_dry_when_that_is_what_the_dew_point_says():
    # Reece's observation, quantified: 22 °C/80 % vs 28 °C/40 % — the hot dry
    # day wins because its dew point is lower.
    assert cooling.evaluate(26, 22, 80)["marginC"] < cooling.evaluate(26, 28, 40)["marginC"]
    assert cooling.evaluate(26, 22, 80)["index"] < cooling.evaluate(26, 28, 40)["index"]


def test_band_edges_are_kept_ordered_whatever_the_config_says():
    r = cooling.evaluate(26, 30, 60, bands={"good": 0.2, "thin": 0.9, "weak": 0.95})
    assert r["band"] in cooling.BAND_ORDER
    edges = cooling._bands({"good": "junk", "thin": None, "weak": 5})
    assert edges["weak"] < edges["thin"] < edges["good"] <= 1.0


def test_junk_reference_falls_back_to_default():
    assert cooling.evaluate(26, 28, 40, reference_vpd_kpa="x")["index"] == cooling.evaluate(26, 28, 40)["index"]
    assert cooling.evaluate(26, 28, 40, reference_vpd_kpa=0)["index"] == cooling.evaluate(26, 28, 40)["index"]


def test_fan_needed_gate():
    assert cooling.fan_needed(24.5, None, 25.5, 1.0)          # within the gate
    assert not cooling.fan_needed(20.0, None, 25.5, 1.0)      # a cool room
    assert cooling.fan_needed(20.0, 26.0, 25.5, 1.0)          # tank already over target
    assert not cooling.fan_needed(None, None, 25.5)
    assert not cooling.fan_needed(30.0, None, "junk")


def test_what_if_table_and_warning_copy():
    table = cooling.what_if_table(26)
    assert table["humidities"] == [50.0, 70.0, 80.0]
    assert [row["roomC"] for row in table["rows"]] == [22.0, 26.0, 30.0]
    assert table["rows"][2]["cells"][2]["band"] == "reversed"
    title, msg = cooling.warning_copy(cooling.evaluate(26, 30, 80), 25.5)
    assert "reversed" in title and "dew point 26.2" in msg
    title, msg = cooling.warning_copy(cooling.evaluate(26, 30, 70), 25.5)
    assert "fraction" in title and "%" in msg


# --------------------------------------------------------------------------- #
# normaliser
# --------------------------------------------------------------------------- #

def test_normaliser_defaults_and_junk_tolerance():
    cfg = normalise(None)["coolingHeadroom"]
    assert cfg["enabled"] is False and cfg["targetMode"] == "fixed" and cfg["targetTempC"] == 25.5
    junk = normalise({"coolingHeadroom": {
        "enabled": "yes", "targetMode": "lunar", "targetTempC": 99, "fanGateC": -3,
        "bands": {"good": 0.1, "thin": 0.9, "weak": "x"}, "roomTempEntity": "not an entity",
    }})["coolingHeadroom"]
    assert junk["enabled"] is True and junk["targetMode"] == "fixed"
    assert junk["targetTempC"] == 32.0 and junk["fanGateC"] == 0.0
    assert junk["bands"]["weak"] < junk["bands"]["thin"] < junk["bands"]["good"]
    assert junk["roomTempEntity"] == ""
    garbage = normalise({"coolingHeadroom": "nonsense"})["coolingHeadroom"]
    assert garbage["enabled"] is False


# --------------------------------------------------------------------------- #
# snapshot — sensors in, story out
# --------------------------------------------------------------------------- #

def test_snapshot_reads_the_bound_sensors_and_warns_when_reversed():
    entry = _entry()
    hass = _hass(entry, room=30, rh=80, tank=26)
    snap = integration.cooling_snapshot(hass, integration._config_from_entry(entry), NOW)
    assert snap["result"]["band"] == "reversed" and snap["fanNeeded"] and snap["warn"]
    assert snap["waterSource"] == "sensor" and snap["issues"] == {}
    assert snap["whatIf"]["rows"][0]["roomC"] == 22.0


def test_snapshot_inherits_the_mapped_sensors_when_no_override_is_set():
    entry = _entry(room="", hum="", water="")
    cfg = entry.options[CONF_SETTINGS]
    cfg["sensors"]["room_temp"].update({"entity_id": "sensor.room", "enabled": True})
    cfg["sensors"]["humidity"].update({"entity_id": "sensor.hum", "enabled": True})
    cfg["sensors"]["temp"].update({"entity_id": "sensor.tank", "enabled": True})
    hass = _hass(entry, room=28, rh=40, tank=26)
    snap = integration.cooling_snapshot(hass, integration._config_from_entry(entry), NOW)
    assert snap["entities"] == {"water": "sensor.tank", "room": "sensor.room", "humidity": "sensor.hum"}
    assert snap["result"]["band"] == "good"


def test_snapshot_without_a_tank_probe_uses_the_target_as_the_water():
    entry = _entry(water="")
    hass = _hass(entry, room=30, rh=70)
    snap = integration.cooling_snapshot(hass, integration._config_from_entry(entry), NOW)
    assert snap["waterSource"] == "target" and snap["waterC"] == 25.5
    assert "water" not in snap["issues"] and snap["result"] is not None


def test_snapshot_converts_fahrenheit_and_flags_bad_sensors():
    entry = _entry()
    hass = _hass(entry, states={
        "sensor.room": _fresh(86, "°F"),             # 30 °C
        "sensor.hum": FakeState("unavailable"),
        "sensor.tank": _fresh(78.8, "°F"),           # 26 °C
    })
    snap = integration.cooling_snapshot(hass, integration._config_from_entry(entry), NOW)
    assert snap["roomC"] == 30.0 and snap["waterC"] == 26.0
    assert snap["result"] is None and not snap["warn"]
    assert "unavailable" in snap["issues"]["humidity"]
    hass.states.set("sensor.hum", _fresh("wet", "%"))
    hass.states.set("sensor.tank", FakeState("26", {"unit_of_measurement": "°C"}))  # stale stamp (2026-01-01)
    hass.states.set("sensor.room", _fresh(120))
    snap = integration.cooling_snapshot(hass, integration._config_from_entry(entry), NOW)
    assert "not numeric" in snap["issues"]["humidity"]
    assert "silent" in snap["issues"]["water"] and snap["waterSource"] == "target"
    assert "implausible" in snap["issues"]["room"]


def test_snapshot_follows_the_spawning_target_when_asked():
    entry = _entry(targetMode="spawning")
    cfg = entry.options[CONF_SETTINGS]
    cfg["spawningProgram"].update({"enabled": True, "reefPreset": "gbr_central"})
    hass = _hass(entry, room=20, rh=50)
    snap = integration.cooling_snapshot(hass, integration._config_from_entry(entry), NOW)
    assert snap["targetSource"] == "spawning" and snap["targetC"] != 25.5
    # Program off → falls back to the fixed number, no crash.
    cfg["spawningProgram"]["enabled"] = False
    snap = integration.cooling_snapshot(hass, integration._config_from_entry(entry), NOW)
    assert snap["targetSource"] == "fixed" and snap["targetC"] == 25.5


# --------------------------------------------------------------------------- #
# the tick — gated, once per band, transitions logged
# --------------------------------------------------------------------------- #

def test_tick_disabled_keeps_no_runtime_and_says_nothing():
    entry = _entry(enabled=False)
    hass = _hass(entry, room=30, rh=80)
    run(integration._async_cooling_tick(hass, entry, NOW))
    assert integration.COOLING_RUNTIME not in hass.data.get(integration.DOMAIN, {})
    assert not hass.services.calls


def test_tick_cool_humid_day_stays_silent():
    # 20 °C at 90 %: humid, but the fans are not needed — the whole point.
    entry = _entry()
    hass = _hass(entry, room=20, rh=90, tank=25.5)
    run(integration._async_cooling_tick(hass, entry, NOW))
    runtime = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]
    assert runtime["snapshot"]["result"]["band"] in ("good", "thin")
    assert not _notes(hass) and not _activity(entry)


def test_tick_hot_humid_day_warns_once_and_logs_the_transition():
    entry = _entry()
    hass = _hass(entry, room=30, rh=80, tank=26)
    run(integration._async_cooling_tick(hass, entry, NOW))
    run(integration._async_cooling_tick(hass, entry, NOW + timedelta(minutes=5)))
    assert len(_notes(hass)) == 1
    assert len(_activity(entry)) == 1
    assert _activity(entry)[0]["type"] == "critical"


def test_tick_escalates_from_weak_to_reversed_then_logs_recovery():
    entry = _entry()
    hass = _hass(entry, room=30, rh=70, tank=26)          # weak
    run(integration._async_cooling_tick(hass, entry, NOW))
    assert len(_notes(hass)) == 1
    hass.states.set("sensor.hum", _fresh(85, "%"))         # reversed
    run(integration._async_cooling_tick(hass, entry, NOW + timedelta(hours=1)))
    assert len(_notes(hass)) == 2                          # a worse band is news
    hass.states.set("sensor.hum", _fresh(40, "%"))         # a dry evening
    run(integration._async_cooling_tick(hass, entry, NOW + timedelta(hours=2)))
    assert len(_notes(hass)) == 2
    msgs = [a["message"] for a in _activity(entry)]
    assert any("headroom again" in m for m in msgs)
    runtime = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]
    assert "warnBand" not in runtime


def test_tick_notify_off_still_logs_but_never_notifies():
    entry = _entry(notify=False)
    hass = _hass(entry, room=30, rh=80, tank=26)
    run(integration._async_cooling_tick(hass, entry, NOW))
    assert not _notes(hass)
    assert any("Cooling headroom" in a["message"] for a in _activity(entry))


def test_tick_broken_sensor_is_an_issue_not_a_warning():
    entry = _entry()
    hass = _hass(entry, states={"sensor.hum": FakeState("unavailable")})
    run(integration._async_cooling_tick(hass, entry, NOW))
    assert not _notes(hass)
    snap = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]["snapshot"]
    assert snap["result"] is None and "humidity" in snap["issues"]


# --------------------------------------------------------------------------- #
# WS
# --------------------------------------------------------------------------- #

def test_ws_status_and_simulate():
    entry = _entry()
    hass = _hass(entry, room=30, rh=60, tank=26)
    conn = FakeConnection()
    integration.websocket_cooling_status(hass, conn, {"id": 1, "type": "openreef/cooling_status"})
    payload = conn.results[-1].payload
    assert payload["result"]["band"] == "thin" and payload["enabled"] is True
    integration.websocket_cooling_simulate(
        hass, conn, {"id": 2, "type": "openreef/cooling_simulate", "roomC": 28, "rh": 40})
    sim = conn.results[-1].payload
    assert sim["band"] == "good" and sim["waterC"] == 25.5   # no waterC given → the target
    integration.websocket_cooling_simulate(
        hass, conn, {"id": 3, "type": "openreef/cooling_simulate", "roomC": 200, "rh": 500, "waterC": 26})
    sim = conn.results[-1].payload
    assert sim["roomC"] == cooling.ROOM_TEMP_MAX_C and sim["rh"] == 100.0


def test_ws_not_configured():
    hass = FakeHass(states={}, entries=[])
    conn = FakeConnection()
    integration.websocket_cooling_status(hass, conn, {"id": 1, "type": "openreef/cooling_status"})
    assert conn.error_codes == ["not_configured"]


# Keep this LAST: a test defined below the runner is a test that never runs.
if __name__ == "__main__":
    failures = 0
    names = [name for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    for name in names:
        try:
            globals()[name]()
            print(f"  ok  {name}")
        except Exception as err:  # noqa: BLE001 - report every failure kind
            failures += 1
            print(f"FAIL  {name}: {type(err).__name__}: {err}")
    print(f"\n{len(names) - failures}/{len(names)} passed")
    raise SystemExit(1 if failures else 0)
