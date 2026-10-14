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

import copy
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


def _activity(entry, prefix="Cooling headroom"):
    return [a for a in (entry.options[CONF_SETTINGS].get("activity") or [])
            if prefix in a["message"]]


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



# --------------------------------------------------------------------------- #
# Layer 2 — forecast parsing, the projection, the plan, vent advice
# --------------------------------------------------------------------------- #

def _fc(hours, base=None, out_c=None, out_rh=None, unit_f=False):
    """Hourly forecast entries: out_c/out_rh callables of the hour index."""
    base = base or NOW
    items = []
    for i in range(hours):
        at = base + timedelta(hours=i)
        t = out_c(i) if callable(out_c) else (out_c if out_c is not None else 20.0)
        rh = out_rh(i) if callable(out_rh) else (out_rh if out_rh is not None else 60.0)
        if unit_f:
            t = t * 9 / 5 + 32
        items.append({"datetime": at.isoformat(), "temperature": t, "humidity": rh})
    return items


def test_plan_uses_live_readings_and_ignores_legacy_forecasts():
    projection = {"firstAffectedAt": NOW.isoformat(), "lastAffectedAt": (NOW + timedelta(hours=24)).isoformat(),
                  "worst": {"index": 0.0}, "hours": [{"roomC": 40.0}]}
    for cached in (None, projection):
        live_bad = cooling.evaluate(26, 28, 75)
        plan = cooling.dehumidifier_plan(live_bad, True, cached, NOW, 3, 25.5)
        assert plan["shouldRun"] and plan["kind"] == "now" and plan["until"] is None
        live_hopeless = cooling.evaluate(26, 31, 85)
        plan = cooling.dehumidifier_plan(live_hopeless, True, cached, NOW, 3, 25.5)
        assert not plan["shouldRun"] and plan["kind"] == "unrescuable"
        for live in (cooling.evaluate(25.5, 23, 60), cooling.evaluate(26, 20, 95), None):
            quiet = cooling.dehumidifier_plan(live, False, cached, NOW, 12, 25.5)
            assert quiet["kind"] == "none" and not quiet["shouldRun"]


def test_plan_losing_is_reeces_2026_09_13_screenshot():
    # 48 % (thin), tank 25.1 vs a 24.8 target, fans on — no WARN band, no
    # affected hour, and until §14 the plan read "no hour … losing".
    live = cooling.evaluate(25.1, 26.1, 68)
    assert live["band"] == "thin"
    quiet = cooling.dehumidifier_plan(live, True, None, NOW, 3, 24.8)
    assert quiet["kind"] == "none"
    plan = cooling.dehumidifier_plan(live, True, None, NOW, 3, 24.8, losing_over_c=0.3, water_known=True)
    assert plan["shouldRun"] and plan["kind"] == "losing"
    assert "0.3 °C over target at 48 %" in plan["reason"] and plan["startAt"] == NOW.isoformat()
    # Gates: 0 = off; no probe never fires; fans not needed; band good = the fans are doing it.
    assert cooling.dehumidifier_plan(live, True, None, NOW, 3, 24.8, losing_over_c=0, water_known=True)["kind"] == "none"
    assert cooling.dehumidifier_plan(live, True, None, NOW, 3, 24.8, losing_over_c=0.3, water_known=False)["kind"] == "none"
    assert cooling.dehumidifier_plan(live, False, None, NOW, 3, 24.8, losing_over_c=0.3, water_known=True)["kind"] == "none"
    good = cooling.evaluate(25.1, 24.0, 40)
    assert good["band"] == "good"
    assert cooling.dehumidifier_plan(good, True, None, NOW, 3, 24.8, losing_over_c=0.3, water_known=True)["kind"] == "none"
    # Stop-side deadband: latched, 0.2 under the bar still runs; unlatched it does not.
    near = cooling.evaluate(25.0, 26.1, 68)                     # 0.2 over target
    assert cooling.dehumidifier_plan(near, True, None, NOW, 3, 24.8, losing_over_c=0.3, water_known=True)["kind"] == "none"
    assert cooling.dehumidifier_plan(near, True, None, NOW, 3, 24.8, losing_over_c=0.3, water_known=True,
                                     latched="losing")["kind"] == "losing"
    assert cooling.dehumidifier_plan(near, True, None, NOW, 3, 24.8, losing_over_c=0.3, water_known=True,
                                     latched="ceiling")["kind"] == "none"  # only its own gate relaxes
    # Vented still wins.
    assert cooling.dehumidifier_plan(live, True, None, NOW, 3, 24.8, vent_active=True, losing_over_c=0.3,
                                     water_known=True)["kind"] == "vented"


def test_plan_ceiling_is_a_house_rule_with_its_own_deadband():
    muggy = cooling.evaluate(25.5, 21.0, 72)                    # cool, wet: fans not needed
    assert cooling.dehumidifier_plan(muggy, False, None, NOW, 3, 25.5)["kind"] == "none"
    plan = cooling.dehumidifier_plan(muggy, False, None, NOW, 3, 25.5, max_rh=70)
    assert plan["shouldRun"] and plan["kind"] == "ceiling" and "72 % is over the 70 % ceiling" in plan["reason"]
    assert cooling.dehumidifier_plan(muggy, False, None, NOW, 3, 25.5, max_rh=0)["kind"] == "none"
    # 66 %: under the bar cold, still over it while latched (holds to 65).
    easing = cooling.evaluate(25.5, 21.0, 66)
    assert cooling.dehumidifier_plan(easing, False, None, NOW, 3, 25.5, max_rh=70)["kind"] == "none"
    assert cooling.dehumidifier_plan(easing, False, None, NOW, 3, 25.5, max_rh=70, latched="ceiling")["kind"] == "ceiling"
    assert cooling.dehumidifier_plan(cooling.evaluate(25.5, 21.0, 64), False, None, NOW, 3, 25.5, max_rh=70,
                                     latched="ceiling")["kind"] == "none"
    assert cooling.dehumidifier_plan(muggy, False, None, NOW, 3, 25.5, max_rh=70, vent_active=True)["kind"] == "vented"
    assert cooling.dehumidifier_plan(None, False, None, NOW, 3, 25.5, max_rh=70)["kind"] == "none"


def test_plan_priority_is_current_fan_performance_tank_temperature_then_humidity():
    kw = {"losing_over_c": 0.3, "max_rh": 70, "water_known": True}
    projection = {"firstAffectedAt": NOW.isoformat(), "worst": {"index": 0}}
    for cached in (None, projection):
        assert cooling.dehumidifier_plan(cooling.evaluate(26, 28, 75), True, cached, NOW, 3, 25.5, **kw)["kind"] == "now"
        assert cooling.dehumidifier_plan(cooling.evaluate(25.9, 26.1, 68), True, cached, NOW, 3, 25.5, **kw)["kind"] == "losing"
        assert cooling.dehumidifier_plan(cooling.evaluate(25.5, 23, 75), False, cached, NOW, 3, 25.5, **kw)["kind"] == "ceiling"
        assert cooling.dehumidifier_plan(cooling.evaluate(25.5, 23, 60), False, cached, NOW, 3, 25.5, **kw)["kind"] == "none"


def test_normaliser_dehumidifier_losing_and_ceiling_fields():
    cfg = normalise({"coolingHeadroom": {"dehumidifier": {"losingOverC": "9", "maxRh": 120}}})["coolingHeadroom"]
    assert cfg["dehumidifier"]["losingOverC"] == 3.0 and cfg["dehumidifier"]["maxRh"] == 95.0
    cfg = normalise({"coolingHeadroom": {"dehumidifier": {"losingOverC": -1, "maxRh": "junk"}}})["coolingHeadroom"]
    assert cfg["dehumidifier"]["losingOverC"] == 0.0 and cfg["dehumidifier"]["maxRh"] == 0.0
    cfg = normalise({"coolingHeadroom": {}})["coolingHeadroom"]
    assert cfg["dehumidifier"]["losingOverC"] == 0.3 and cfg["dehumidifier"]["maxRh"] == 0.0


def test_tick_losing_notifies_once_and_auto_runs_the_plug_then_latches():
    # Reece's room in auto: thin band, tank 0.3 over — the plug goes on, one
    # notification, and a tick with the tank 0.2 over keeps it (latched).
    entry = _l2_entry(mode="auto", armed=True, targetTempC=24.8)
    now = datetime.now(timezone.utc)
    hass = _l2_hass(entry, room=26.1, rh=68, tank=25.1)
    run(integration._async_cooling_tick(hass, entry, now))
    snap = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]["snapshot"]
    assert snap["result"]["band"] == "thin" and snap["plan"]["kind"] == "losing"
    assert len(_plug_calls(hass, "turn_on")) == 1
    notes = [n for n in _notes(hass) if "plan_losing" in str(n.data.get("notification_id"))]
    assert len(notes) == 1 and "Dehumidifier plan" in notes[0].data.get("title", "")
    assert any("still 0.3 °C over target" in a["message"] and a["type"] == "warning"
               for a in _activity(entry, "Dehumidifier"))
    hass.states.set("sensor.tank", _fresh(25.0))
    hass.states.set("switch.dehum", "on")
    run(integration._async_cooling_tick(hass, entry, now + timedelta(minutes=5)))
    snap = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]["snapshot"]
    assert snap["plan"]["kind"] == "losing", "0.2 over holds while latched"
    assert len(notes) == 1 and not _plug_calls(hass, "turn_off")
    # Tank back on target: the plan releases (min-on may hold the plug, the plan does not).
    hass.states.set("sensor.tank", _fresh(24.8))
    run(integration._async_cooling_tick(hass, entry, now + timedelta(minutes=10)))
    snap = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]["snapshot"]
    assert snap["plan"]["kind"] == "none"


def test_tick_ceiling_advises_on_a_cool_muggy_evening():
    entry = _entry(weatherEntity="weather.home", vent={"mode": "off"},
                   dehumidifier={"mode": "advise", "switchEntity": "switch.dehum", "maxRh": 70})
    now = datetime.now(timezone.utc)
    hass = _l2_hass(entry, room=21.0, rh=74, tank=25.5)
    run(integration._async_cooling_tick(hass, entry, now))
    snap = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]["snapshot"]
    assert not snap["fanNeeded"] and snap["plan"]["kind"] == "ceiling"
    notes = [n for n in _notes(hass) if "plan_ceiling" in str(n.data.get("notification_id"))]
    assert len(notes) == 1 and "Start the dehumidifier" in notes[0].data.get("title", "")
    assert any("74 % is over the 70 % ceiling" in a["message"] and a["type"] == "info"
               for a in _activity(entry, "Dehumidifier"))
    assert not _plug_calls(hass, "turn_on")


def test_vent_advice_prefers_drier_cooler_outdoor_air():
    yes = cooling.vent_advice(28.0, 22.0, 18.0, 12.0)
    assert yes["advised"] and yes["gapC"] == 10.0
    # A near miss names the gap and the bar, so the activity log is diagnosable.
    wet = cooling.vent_advice(28.0, 22.0, 18.0, 21.0)
    assert not wet["advised"] and "only 1.0 °C below indoors, needs 2.0" in wet["reason"]
    wetter = cooling.vent_advice(28.0, 22.0, 18.0, 23.0)
    assert not wetter["advised"] and "wetter than indoors" in wetter["reason"]
    warm = cooling.vent_advice(28.0, 22.0, 33.0, 12.0)
    assert not warm["advised"] and "warmer (33.0 °C vs room 28.0 °C)" in warm["reason"]
    assert not cooling.vent_advice(None, 22.0, 18.0, 12.0)["known"]


def test_normaliser_layer2_fields():
    cfg = normalise({"coolingHeadroom": {"weatherEntity": "weather.home", "lookaheadHours": 999,
                                         "dehumidifier": {"mode": "turbo", "armed": "y", "switchEntity": "switch.dehum",
                                                          "leadHours": 40, "minOnMinutes": 1, "overridePolicy": "x"}}})["coolingHeadroom"]
    assert cfg["weatherEntity"] == "weather.home" and cfg["lookaheadHours"] == 48
    d = cfg["dehumidifier"]
    assert d["mode"] == "advise" and d["armed"] is True and d["switchEntity"] == "switch.dehum"
    assert d["leadHours"] == 12 and d["minOnMinutes"] == 5 and d["overridePolicy"] == "hold"
    assert normalise({"coolingHeadroom": {"dehumidifier": "junk"}})["coolingHeadroom"]["dehumidifier"]["mode"] == "advise"


# --------------------------------------------------------------------------- #
# Layer 2 — the tick with a weather entity and a plug
# --------------------------------------------------------------------------- #

def _weather_state(temp=20.0, rh=60.0, unit="°C"):
    return FakeState("cloudy", {"temperature": temp, "humidity": rh, "temperature_unit": unit},
                     last_changed=datetime.now(timezone.utc))


def _l2_entry(mode="advise", armed=False, plug="switch.dehum", **over):
    # Layer 2 fixtures keep the intake fan off so its advice can't leak in.
    over.setdefault("vent", {"mode": "off"})
    return _entry(weatherEntity="weather.home", lookaheadHours=24,
                  dehumidifier={"mode": mode, "armed": armed, "switchEntity": plug,
                                "leadHours": 3, "minOnMinutes": 20, "minOffMinutes": 10, "maxRunHours": 8},
                  **over)


def _l2_hass(entry, room=23.0, rh=60.0, tank=25.5, out=(20.0, 60.0), plug="off", forecast=None):
    hass = _hass(entry, room=room, rh=rh, tank=tank, states={
        "weather.home": _weather_state(*out), "switch.dehum": plug})
    if forecast is not None:
        hass.services.responses[("weather", "get_forecasts")] = {"weather.home": {"forecast": forecast}}
    return hass


def _humid_afternoon(base):
    # Hits from +5 h: outdoor 27 °C at 70 % (room = +3 → 30 °C, dew ≈ 21 + 5 = 26 → dead).
    return _fc(12, base=base, out_c=lambda i: 20 if i < 5 else 27, out_rh=70)


def _plug_calls(hass, service):
    return [c for c in hass.services.calls if c.domain == "switch" and c.service == service]


def test_tick_ignores_stored_forecasts_and_offsets_and_does_not_fetch_or_learn():
    entry = _l2_entry(mode="auto", armed=True)
    now = datetime.now(timezone.utc)
    hass = _l2_hass(entry, forecast=_humid_afternoon(now))
    runtime = hass.data.setdefault(integration.DOMAIN, {}).setdefault(integration.COOLING_RUNTIME, {})
    runtime.update({"forecast": {"hours": [{"at": now, "outC": 40, "outDewC": 35}]},
                    "learning": {"byHour": {str(now.hour): {"n": 84, "t": 12, "dew": 12}}},
                    "offsets": {"offsetT": 12, "offsetDew": 12}})
    before = copy.deepcopy(runtime["learning"])
    for minutes in (0, 5, 180):
        run(integration._async_cooling_tick(hass, entry, now + timedelta(minutes=minutes)))
        snap = runtime["snapshot"]
        assert snap["projection"] is None and snap["plan"]["kind"] == "none"
        assert "offsets" not in snap and "learned" not in snap
        assert snap["weather"]["outC"] == 20.0 and snap["vent"]["known"]
    assert runtime["learning"] == before
    assert not [c for c in hass.services.calls if c.service == "get_forecasts"]
    assert not _notes(hass) and not _plug_calls(hass, "turn_on")


def test_tick_advise_notifies_for_current_need_only():
    entry = _l2_entry()
    now = datetime.now(timezone.utc)
    hass = _l2_hass(entry, forecast=_humid_afternoon(now))
    run(integration._async_cooling_tick(hass, entry, now))
    assert not _notes(hass)
    hass.states.set("sensor.room", _fresh(28))
    hass.states.set("sensor.hum", _fresh(75, "%"))
    run(integration._async_cooling_tick(hass, entry, now + timedelta(minutes=5)))
    run(integration._async_cooling_tick(hass, entry, now + timedelta(minutes=10)))
    notes = [n for n in _notes(hass) if "plan_now" in str(n.data.get("notification_id"))]
    assert len(notes) == 1 and "Start the dehumidifier" in notes[0].data["title"]
    assert not _plug_calls(hass, "turn_on")


def test_tick_without_a_weather_entity_stays_layer_one():
    entry = _entry()
    hass = _hass(entry, room=23, rh=60)
    run(integration._async_cooling_tick(hass, entry, NOW))
    snap = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]["snapshot"]
    assert snap["projection"] is None and snap["plan"]["kind"] == "none"
    assert not snap["vent"]["known"] and "weather" not in snap["issues"]
    assert not [c for c in hass.services.calls if c.service == "get_forecasts"]


def test_cached_advance_plans_cannot_drive_actuators():
    for kind in ("ahead", "scheduled"):
        assert integration._cooling_desired({"plan": {"shouldRun": True, "kind": kind}}, "dehumidifier")[0] is False
    for kind in ("purge", "predry"):
        assert integration._cooling_desired({"ventDecision": {"shouldRun": True, "kind": kind}}, "vent")[0] is False
    assert integration._cooling_desired({"plan": {"shouldRun": True, "kind": "now"}}, "dehumidifier")[0] is True
    assert integration._cooling_desired({"ventDecision": {"shouldRun": True, "kind": "cool"}}, "vent")[0] is True


def test_tick_uses_current_weather_without_requesting_forecasts():
    entry = _l2_entry()
    hass = _l2_hass(entry)
    hass.services.fail_on.add(("weather", "get_forecasts"))
    run(integration._async_cooling_tick(hass, entry, datetime.now(timezone.utc)))
    snap = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]["snapshot"]
    assert snap["weather"]["available"] and "forecast" not in snap["issues"]
    hass.states.set("weather.home", FakeState("unavailable"))
    run(integration._async_cooling_tick(hass, entry, datetime.now(timezone.utc)))
    snap = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]["snapshot"]
    assert "weather" in snap["issues"] and "forecast" not in snap["issues"]
    assert not [c for c in hass.services.calls if c.service == "get_forecasts"]


def test_auto_disarmed_never_switches_and_armed_drives_the_plan():
    now = datetime.now(timezone.utc)
    entry = _l2_entry(mode="auto", armed=False)
    hass = _l2_hass(entry, room=28, rh=75)
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3)))
    assert not _plug_calls(hass, "turn_on")
    entry = _l2_entry(mode="auto", armed=True)
    hass = _l2_hass(entry, room=28, rh=75)
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3)))     # live demand → on
    assert len(_plug_calls(hass, "turn_on")) == 1 and hass.states.get("switch.dehum").state == "on"
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3, minutes=5)))
    assert len(_plug_calls(hass, "turn_on")) == 1                                   # reconciled, no spam
    assert any("Dehumidifier switched on" in a["message"] for a in
               entry.options[CONF_SETTINGS]["activity"])


def test_auto_short_cycle_guard_and_max_run():
    now = datetime.now(timezone.utc)
    entry = _l2_entry(mode="auto", armed=True)
    hass = _l2_hass(entry, room=28, rh=75)
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3)))     # on
    runtime = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]
    # Current readings recover a minute later → min-on holds it.
    hass.states.set("sensor.room", _fresh(23))
    hass.states.set("sensor.hum", _fresh(60, "%"))
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3, minutes=1)))
    assert not _plug_calls(hass, "turn_off")
    runtime["dehum"]["lastOn"] = (now - timedelta(hours=1)).isoformat()
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3, minutes=2)))
    assert len(_plug_calls(hass, "turn_off")) == 1
    # Max run: asserted on for longer than the cap → off + a bucket nudge.
    hass.states.set("sensor.room", _fresh(28))
    hass.states.set("sensor.hum", _fresh(75, "%"))
    runtime["dehum"] = {"asserted": "on", "lastOn": (now - timedelta(hours=9)).isoformat()}
    hass.states.set("switch.dehum", "on")
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=1)))
    assert len(_plug_calls(hass, "turn_off")) == 2
    assert any("max_run" in str(n.data.get("notification_id")) for n in _notes(hass))


def test_auto_hold_respects_a_hand_on_the_plug_and_leaving_auto_fails_off():
    now = datetime.now(timezone.utc)
    entry = _l2_entry(mode="auto", armed=True)
    hass = _l2_hass(entry, room=28, rh=75)
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3)))     # on
    hass.states.set("switch.dehum", "off")                                         # a human
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3, minutes=5)))
    assert len(_plug_calls(hass, "turn_on")) == 1                                   # held
    runtime = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]
    assert runtime["dehum"]["override"]["state"] == "off"
    # Current readings recover → the hold releases.
    hass.states.set("sensor.room", _fresh(23))
    hass.states.set("sensor.hum", _fresh(60, "%"))
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=4)))
    assert "override" not in runtime["dehum"]
    # Leaving auto while we hold it on switches it off once.
    hass.states.set("switch.dehum", "on")
    runtime["dehum"] = {"asserted": "on", "lastOn": now.isoformat()}
    entry.options[CONF_SETTINGS]["coolingHeadroom"]["dehumidifier"]["mode"] = "advise"
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=4, minutes=5)))
    assert len(_plug_calls(hass, "turn_off")) == 1 and runtime["dehum"] == {}


def test_auto_unavailable_plug_alerts_once():
    now = datetime.now(timezone.utc)
    entry = _l2_entry(mode="auto", armed=True)
    hass = _l2_hass(entry, plug="unavailable", forecast=_humid_afternoon(now))
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3)))
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3, minutes=5)))
    assert not _plug_calls(hass, "turn_on")
    assert len([n for n in _notes(hass) if "plug_unavailable" in str(n.data.get("notification_id"))]) == 1


def test_ws_dehumidifier_actions():
    now = datetime.now(timezone.utc)
    entry = _l2_entry(mode="auto", armed=True)
    hass = _l2_hass(entry, forecast=_humid_afternoon(now))
    run(integration._async_cooling_tick(hass, entry, now))                          # plan: scheduled (off)
    conn = FakeConnection()
    run(integration.websocket_cooling_dehumidifier(hass, conn, {"id": 1, "type": "x", "action": "run"}))
    assert conn.results[-1].payload["state"] == "on" and hass.states.get("switch.dehum").state == "on"
    runtime = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]
    assert runtime["dehum"]["override"]["state"] == "on"                          # held against the plan
    run(integration._async_cooling_tick(hass, entry, now + timedelta(minutes=5)))
    assert not _plug_calls(hass, "turn_off")                                       # the hold wins
    run(integration.websocket_cooling_dehumidifier(hass, conn, {"id": 2, "type": "x", "action": "resume"}))
    assert "override" not in runtime["dehum"]
    run(integration._async_cooling_tick(hass, entry, now + timedelta(minutes=25)))  # past min-on
    assert len(_plug_calls(hass, "turn_off")) == 1                                 # plan re-asserted
    integration.websocket_cooling_status(hass, conn, {"id": 3, "type": "openreef/cooling_status"})
    assert conn.results[-1].payload["dehumidifier"]["controlling"] is True
    unbound = _entry()
    hass2 = _hass(unbound)
    run(integration.websocket_cooling_dehumidifier(hass2, conn, {"id": 4, "type": "x", "action": "run"}))
    assert conn.error_codes[-1] == "not_bound"



# --------------------------------------------------------------------------- #
# Layer 3 — the intake fan
# --------------------------------------------------------------------------- #

def _calls(hass, service, entity):
    return [c for c in hass.services.calls
            if c.domain == "switch" and c.service == service and entity in c.data.values()]


def _l3_entry(vent_mode="auto", armed=True, fan="switch.vent", window="", night_purge=True,
              dehum_mode="auto", dehum_armed=True):
    return _l2_entry(mode=dehum_mode, armed=dehum_armed,
                     vent={"mode": vent_mode, "armed": armed, "switchEntity": fan, "windowEntity": window,
                           "dewGapC": 2.0, "nightPurge": night_purge, "minOnMinutes": 10, "minOffMinutes": 10})


def _l3_hass(entry, room=23.0, rh=60.0, out=(20.0, 60.0), fan="off", window=None, forecast=None):
    # Indoors 23 °C / 60 % → dew 14.8; outdoors 20 °C / 60 % → dew 12.0: a 2.8 °C gap, vent advised.
    hass = _l2_hass(entry, room=room, rh=rh, out=out, forecast=forecast)
    hass.states.set("switch.vent", fan)
    if window is not None:
        hass.states.set("binary_sensor.window", window)
    return hass


def _advice(advised=True, gap=2.8, freecool=True, cooler_by=6.0):
    return {"advised": advised, "known": True, "reason": "r", "outdoorC": 20.0, "outdoorDewC": 12.0,
            "gapC": gap, "freecool": freecool, "coolerBy": cooler_by, "freecoolReason": ""}


def test_vent_decision_kinds():
    proj_hit = {"firstAffectedAt": (NOW + timedelta(hours=5)).isoformat(), "worst": {"index": 0.2},
                "dayKind": "humid-heat", "purgeWindow": None}
    assert cooling.vent_decision(_advice(), True, None, NOW, True, None)["kind"] == "cool"
    predry = cooling.vent_decision(_advice(), False, proj_hit, NOW, True, None)
    assert predry["kind"] == "none" and not predry["shouldRun"]
    purge_proj = {"firstAffectedAt": None, "worst": None, "dayKind": "dry-heat",
                  "purgeWindow": {"from": (NOW - timedelta(hours=1)).isoformat(), "to": (NOW + timedelta(hours=2)).isoformat(), "outC": 12}}
    purge = cooling.vent_decision(_advice(), False, purge_proj, NOW, True, None)
    assert purge["kind"] == "none" and not purge["shouldRun"]
    assert cooling.vent_decision(_advice(), False, purge_proj, NOW, False, None)["kind"] == "none"    # purge off
    assert cooling.vent_decision(_advice(), False, dict(purge_proj, dayKind="quiet"), NOW, True, None)["kind"] == "none"
    assert cooling.vent_decision(_advice(), False, purge_proj, NOW + timedelta(hours=6), True, None)["kind"] == "none"  # outside the window
    blocked = cooling.vent_decision(_advice(), True, None, NOW, True, False)
    assert blocked["kind"] == "blocked" and not blocked["shouldRun"] and blocked["wants"] == "cool"
    assert cooling.vent_decision(_advice(), True, None, NOW, True, True)["shouldRun"]                # window open
    # Genuinely wet outdoor air fails BOTH routes — not drier, and not dew-neutral.
    wet = cooling.vent_decision(_advice(advised=False, freecool=False), True, None, NOW, True, None)
    assert wet["kind"] == "none" and not wet["shouldRun"]
    assert cooling.vent_decision({"known": False, "reason": "no outdoor reading"}, True, None, NOW, True, None)["kind"] == "none"


def test_vent_gap_is_configurable_and_plan_yields_to_venting():
    assert cooling.vent_advice(28.0, 22.0, 18.0, 20.5, gap_c=2.0)["advised"] is False   # 1.5 °C gap
    assert cooling.vent_advice(28.0, 22.0, 18.0, 20.5, gap_c=1.0)["advised"] is True
    live = cooling.evaluate(26, 28, 75)
    vented = cooling.dehumidifier_plan(live, True, None, NOW, 3, 25.5, vent_active=True)
    assert vented["kind"] == "vented" and not vented["shouldRun"]
    assert cooling.dehumidifier_plan(cooling.evaluate(26, 20, 50), False, None, NOW, 3, 25.5, vent_active=True)["kind"] == "none"


def test_vent_advice_deadband_holds_a_running_fan_through_its_own_success():
    # 1.6 °C gap: under the 2.0 start threshold, over the 1.5 stop threshold.
    assert cooling.vent_advice(28.0, 22.0, 18.0, 20.4, gap_c=2.0)["advised"] is False
    assert cooling.vent_advice(28.0, 22.0, 18.0, 20.4, gap_c=2.0, venting=True)["advised"] is True
    # Past the far side of the deadband it stops even while running.
    assert cooling.vent_advice(28.0, 22.0, 18.0, 20.6, gap_c=2.0, venting=True)["advised"] is False
    # Temperature gate widens the same way: room + 1.0 to start, + 1.5 to hold.
    assert cooling.vent_advice(28.0, 22.0, 29.3, 12.0)["advised"] is False
    assert cooling.vent_advice(28.0, 22.0, 29.3, 12.0, venting=True)["advised"] is True
    assert cooling.vent_advice(28.0, 22.0, 29.6, 12.0, venting=True)["advised"] is False
    # The deadband only ever widens the stop side — a start is never made easier.
    assert cooling.vent_advice(28.0, 22.0, 18.0, 20.6, gap_c=2.0)["advised"] is False


def test_fan_needed_latch_keeps_a_room_off_the_gate_from_flapping():
    # Gate is target - 1.0 = 24.5; latched it holds down to 24.2.
    assert cooling.fan_needed(24.4, None, 25.5, 1.0) is False
    assert cooling.fan_needed(24.4, None, 25.5, 1.0, latched=True) is True
    assert cooling.fan_needed(24.1, None, 25.5, 1.0, latched=True) is False
    # Latching never lowers the bar for a first start.
    assert cooling.fan_needed(24.3, None, 25.5, 1.0) is False
    assert cooling.fan_needed(24.6, None, 25.5, 1.0) is True
    # The tank arm gets NO give: a tank parked on target must not latch on
    # forever just because the room once crossed the gate.
    assert cooling.fan_needed(20.0, 25.5, 25.5, 1.0, latched=True) is False
    assert cooling.fan_needed(20.0, 25.6, 25.5, 1.0, latched=True) is False   # still under target + 0.2
    assert cooling.fan_needed(20.0, 25.8, 25.5, 1.0) is True
    assert cooling.fan_needed(None, None, 25.5, 1.0, latched=True) is False
    assert cooling.fan_needed(30.0, None, "junk", 1.0, latched=True) is False


def test_snapshot_latches_fan_needed_and_deadbands_a_running_vent_fan():
    entry = _l2_entry(vent={"mode": "auto", "armed": True, "switchEntity": "switch.fan"})
    hass = _l2_hass(entry)
    hass.states.set("switch.fan", FakeState("off"))
    cfg = integration._config_from_entry(entry)
    runtime: dict = {}

    def _snap(room):
        hass.states.set("sensor.room", _fresh(room))
        return integration.cooling_snapshot(hass, cfg, NOW, runtime)

    # Gate is 25.5 - 1.0 = 24.5. Inside the deadband but never latched: no.
    assert _snap(24.4)["fanNeeded"] is False
    assert runtime["fanNeededLatch"] is False
    # Cross the gate, then fall back into the deadband: the latch holds it.
    assert _snap(24.6)["fanNeeded"] is True
    assert _snap(24.4)["fanNeeded"] is True
    assert runtime["fanNeededLatch"] is True
    # Past the far side (24.2) it lets go.
    assert _snap(24.0)["fanNeeded"] is False
    # A snapshot with no runtime must not latch — the stateless callers.
    hass.states.set("sensor.room", _fresh(24.4))
    assert integration.cooling_snapshot(hass, cfg, NOW, None)["fanNeeded"] is False
    # The running plug relaxes the vent gates; switching it off tightens them.
    hass.states.set("switch.fan", FakeState("on"))
    assert integration.cooling_snapshot(hass, cfg, NOW, runtime)["vent"]["hysteresis"] is True
    hass.states.set("switch.fan", FakeState("off"))
    assert integration.cooling_snapshot(hass, cfg, NOW, runtime)["vent"]["hysteresis"] is False


def test_actuator_state_publishes_the_hold_that_explains_a_disagreeing_plug():
    from datetime import timedelta as _td
    entry = _l2_entry(vent={"mode": "auto", "armed": True, "switchEntity": "switch.fan",
                            "dewGapC": 5.0, "minOnMinutes": 60, "minOffMinutes": 10})
    # Muggy and barely cooler: under the dew bar (5.0) AND under the cool gap
    # (2.0), so neither route wants the fan while the plug is on.
    hass = _l2_hass(entry, room=27.0, rh=45.0, out=(26.8, 43.0))
    hass.states.set("switch.fan", FakeState("on"))
    cfg = integration._config_from_entry(entry)
    # Plan says off (the gap is nowhere near 3.0), plug is on, switched on 20
    # minutes ago under a 60-minute min-on: the panel must be able to say why.
    started = (NOW.astimezone(timezone.utc) - _td(minutes=20)).isoformat()
    runtime = {"vent": {"asserted": "on", "lastOn": started}}
    snap = integration.cooling_snapshot(hass, cfg, NOW, runtime)
    assert snap["ventDecision"]["shouldRun"] is False and snap["ventFan"]["state"] == "on"
    hold = snap["ventFan"]["hold"]
    assert hold and hold["kind"] == "minOn" and hold["minutes"] == 60
    assert hold["until"].startswith((NOW.astimezone(timezone.utc) + _td(minutes=40)).isoformat()[:16])
    # Past the window there is nothing left to explain.
    runtime["vent"]["lastOn"] = (NOW.astimezone(timezone.utc) - _td(minutes=90)).isoformat()
    assert integration.cooling_snapshot(hass, cfg, NOW, runtime)["ventFan"]["hold"] is None
    # A plug that agrees with the plan is never "held".
    hass.states.set("switch.fan", FakeState("off"))
    runtime["vent"]["lastOn"] = started
    assert integration.cooling_snapshot(hass, cfg, NOW, runtime)["ventFan"]["hold"] is None
    # A manual hold reaches the panel too — the release button depends on it.
    runtime["vent"]["override"] = {"since": started, "state": "on", "plannedRun": False}
    ov = integration.cooling_snapshot(hass, cfg, NOW, runtime)["ventFan"]["override"]
    assert ov == {"state": "on", "since": started}
    # No runtime at all must not explode or invent a hold.
    assert integration.cooling_snapshot(hass, cfg, NOW, None)["ventFan"]["override"] is None


def test_freecool_reeces_2026_09_06_reading_is_the_acceptance_case():
    # The reading that started all this: outdoor 24.3 °C at 43 % (dew 10.8) into
    # a room 4.1 °C hotter, dew gap 1.4 — refused by the drying rule, obviously
    # worth having. Room 28.4/38 % puts the dew gap under 2.0 and the room well
    # over its gate.
    entry = _l2_entry(vent={"mode": "auto", "armed": True, "switchEntity": "switch.fan"})
    hass = _l2_hass(entry, room=28.4, rh=38.0, tank=25.5, out=(24.3, 43.0))
    hass.states.set("switch.fan", FakeState("off"))
    snap = integration.cooling_snapshot(hass, integration._config_from_entry(entry), NOW, {})
    assert snap["vent"]["advised"] is False               # the drying rule still says no
    assert snap["vent"]["gapC"] < 2.0 and snap["vent"]["coolerBy"] >= 2.0
    assert snap["fanNeeded"] is True
    assert snap["ventDecision"]["kind"] == "freecool" and snap["ventDecision"]["shouldRun"]
    assert "free cooling" in snap["ventDecision"]["reason"]


def test_freecool_gates_and_their_deadbands():
    def adv(room, out, out_dew, dew=None, venting=False, **kw):
        return cooling.vent_advice(room, dew if dew is not None else out_dew + 1.4,
                                   out, out_dew, 2.0, venting, **kw)
    # Cooler by 4.1 and dew-neutral (+1.4) → freecool, but never `advised`.
    yes = adv(28.4, 24.3, 10.8)
    assert yes["freecool"] is True and yes["advised"] is False and yes["coolerBy"] == 4.1
    # Cool gap: 2.0 to start, holds to 1.5 while running, never easier to start.
    assert adv(26.4, 24.3, 10.8)["freecool"] is True                       # 2.1 — over the bar
    assert adv(26.2, 24.3, 10.8)["freecool"] is False                      # 1.9 — under 2.0
    assert adv(26.2, 24.3, 10.8, venting=True)["freecool"] is True         # …held while running
    assert adv(25.7, 24.3, 10.8, venting=True)["freecool"] is False        # 1.4 — past the deadband
    # Dew-neutral: 0.0 to start, -0.3 while running. Never buy temperature with
    # moisture, and say so — this is the line that explains a declined chance.
    wetter = adv(28.4, 24.3, 12.0, dew=11.6)
    assert wetter["freecool"] is False and "cost the fans more than it saves" in wetter["freecoolReason"]
    assert adv(28.4, 24.3, 12.0, dew=11.8, venting=True)["freecool"] is True    # -0.2, inside the give
    assert adv(28.4, 24.3, 12.0, dew=11.6, venting=True)["freecool"] is False   # -0.4, past it
    # The cold floor is a SAFETY gate: strict, and it gets no deadband.
    cold = adv(28.4, 8.0, 4.0)
    assert cold["freecool"] is False and "too cold to blow at the tank" in cold["freecoolReason"]
    assert adv(28.4, 8.0, 4.0, venting=True)["freecool"] is False
    assert adv(28.4, 8.0, 4.0, cool_min_outdoor_c=0)["freecool"] is True        # 0 disables the floor
    # coolVent off removes the route entirely, refusal copy included.
    off = adv(28.4, 24.3, 10.8, cool_vent=False)
    assert off["freecool"] is False and off["freecoolReason"] == ""
    # No opportunity, no explanation to give.
    assert adv(24.5, 24.3, 10.8)["freecoolReason"] == ""


def test_freecool_priority_and_the_purge_floor():
    proj_hit = {"firstAffectedAt": (NOW + timedelta(hours=5)).isoformat(), "worst": {"index": 0.2},
                "dayKind": "humid-heat", "purgeWindow": None}
    # cool beats freecool when both routes are open.
    assert cooling.vent_decision(_advice(), True, None, NOW, True, None)["kind"] == "cool"
    # freecool beats predry: a present need before a future preparation.
    assert cooling.vent_decision(_advice(), True, proj_hit, NOW, True, None)["kind"] == "cool"
    assert cooling.vent_decision(_advice(advised=False), True, proj_hit, NOW, True, None)["kind"] == "freecool"
    # predry still needs the drying route — pre-drying with dew-neutral air is
    # not a thing, so freecool alone must not reach it.
    assert cooling.vent_decision(_advice(advised=False), False, proj_hit, NOW, True, None)["kind"] == "none"
    assert cooling.vent_decision(_advice(), False, proj_hit, NOW, True, None)["kind"] == "none"
    # The purge now rides the freecool gates, not the dew gap.
    purge_proj = {"firstAffectedAt": None, "worst": None, "dayKind": "dry-heat",
                  "purgeWindow": {"from": (NOW - timedelta(hours=1)).isoformat(),
                                  "to": (NOW + timedelta(hours=2)).isoformat(), "outC": 12}}
    assert cooling.vent_decision(_advice(advised=False), False, purge_proj, NOW, True, None)["kind"] == "none"
    assert cooling.vent_decision(_advice(freecool=False), False, purge_proj, NOW, True, None)["kind"] == "none"
    # …and stops on the TANK, not the room: a reef room sits well under the
    # tank's target every night, which is exactly when a purge is worth running.
    warm = cooling.vent_decision(_advice(), False, purge_proj, NOW, True, None, 25.5, 25.5, 2.0)
    assert warm["kind"] == "none"                                   # tank on target, room irrelevant
    cold = cooling.vent_decision(_advice(), False, purge_proj, NOW, True, None, 23.4, 25.5, 2.0)
    assert cold["kind"] == "none"                                    # tank 2.1 under target — stop
    # No probe (water falls back to the target) must never block a purge.
    assert cooling.vent_decision(_advice(), False, purge_proj, NOW, True, None, None, 25.5, 2.0)["kind"] == "none"


def test_normaliser_vent_block():
    cfg = normalise({"coolingHeadroom": {"vent": {"mode": "x", "armed": 1, "switchEntity": "switch.fan",
                                                  "windowEntity": "binary_sensor.win", "dewGapC": 99, "nightPurge": 0,
                                                  "minOnMinutes": 1}}})["coolingHeadroom"]["vent"]
    assert cfg["mode"] == "advise" and cfg["armed"] is True and cfg["switchEntity"] == "switch.fan"
    assert cfg["windowEntity"] == "binary_sensor.win" and cfg["dewGapC"] == 6.0 and cfg["nightPurge"] is False
    assert cfg["minOnMinutes"] == 5 and cfg["overridePolicy"] == "hold"
    assert normalise(None)["coolingHeadroom"]["vent"]["mode"] == "advise"


def test_tick_vent_auto_cools_now_and_takes_the_dehumidifier_plan_away():
    now = datetime.now(timezone.utc)
    entry = _l3_entry()
    hass = _l3_hass(entry, room=28, rh=75)
    run(integration._async_cooling_tick(hass, entry, now))
    snap = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]["snapshot"]
    assert snap["vent"]["advised"] and snap["ventDecision"]["kind"] == "cool"
    assert len(_calls(hass, "turn_on", "switch.vent")) == 1 and hass.states.get("switch.vent").state == "on"
    assert snap["ventActive"] is True and snap["plan"]["kind"] == "vented"
    # Continued current demand: ventilation keeps the dehumidifier off.
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3)))
    snap = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]["snapshot"]
    assert snap["plan"]["kind"] == "vented"
    assert not _calls(hass, "turn_on", "switch.dehum")
    assert len(_calls(hass, "turn_on", "switch.vent")) == 1                       # reconciled, no spam
    msgs = [a["message"] for a in entry.options[CONF_SETTINGS]["activity"]]
    assert any(m.startswith("Vent: the room needs cooling") for m in msgs)
    assert any("Intake fan switched on" in m for m in msgs)


def test_tick_vent_window_closed_blocks_the_fan_and_leaves_the_dehumidifier_alone():
    now = datetime.now(timezone.utc)
    entry = _l3_entry(window="binary_sensor.window")
    hass = _l3_hass(entry, room=28, rh=75, window="off")
    run(integration._async_cooling_tick(hass, entry, now))
    run(integration._async_cooling_tick(hass, entry, now + timedelta(minutes=5)))
    snap = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]["snapshot"]
    assert snap["ventDecision"]["kind"] == "blocked" and snap["window"]["open"] is False
    assert not _calls(hass, "turn_on", "switch.vent")
    blocked = [n for n in _notes(hass) if "vent_blocked" in str(n.data.get("notification_id"))]
    assert len(blocked) == 1 and "Open the window" in blocked[0].data.get("title", "")
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3)))
    assert len(_calls(hass, "turn_on", "switch.dehum")) == 1                      # not vented → dehumidify
    # Window opens: the fan runs and the dehumidifier lets go (after its min-on).
    hass.states.set("binary_sensor.window", "on")
    runtime = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]
    runtime["dehum"]["lastOn"] = (now - timedelta(hours=1)).isoformat()
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3, minutes=5)))
    assert len(_calls(hass, "turn_on", "switch.vent")) == 1
    assert len(_calls(hass, "turn_off", "switch.dehum")) == 1


def test_tick_open_window_in_advise_mode_counts_as_vented():
    now = datetime.now(timezone.utc)
    entry = _l3_entry(vent_mode="advise", armed=False, window="binary_sensor.window")
    hass = _l3_hass(entry, room=28, rh=75, window="on")
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3)))
    snap = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]["snapshot"]
    assert snap["ventActive"] is True and snap["plan"]["kind"] == "vented"
    assert not _calls(hass, "turn_on", "switch.dehum") and not _calls(hass, "turn_on", "switch.vent")
    vent_notes = [n for n in _notes(hass) if "vent_cool" in str(n.data.get("notification_id"))]
    assert len(vent_notes) == 1 and "Vent the room" in vent_notes[0].data.get("title", "")


def test_tick_vent_closes_up_when_outdoor_air_turns_wet():
    now = datetime.now(timezone.utc)
    entry = _l3_entry()
    hass = _l3_hass(entry, room=28, rh=75)
    run(integration._async_cooling_tick(hass, entry, now))
    assert hass.states.get("switch.vent").state == "on"
    hass.states.set("weather.home", _weather_state(28.0, 95.0))                   # muggy: dew 19.2 > indoors
    runtime = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]
    runtime["vent"]["lastOn"] = (now - timedelta(hours=1)).isoformat()
    run(integration._async_cooling_tick(hass, entry, now + timedelta(minutes=30)))
    snap = runtime["snapshot"]
    assert not snap["vent"]["advised"] and snap["ventDecision"]["kind"] == "none"
    assert len(_calls(hass, "turn_off", "switch.vent")) == 1
    assert any("Vent: close up" in a["message"] for a in entry.options[CONF_SETTINGS]["activity"])


def test_tick_does_not_run_night_purge_even_with_legacy_setting_enabled():
    now = datetime.now(timezone.utc)
    forecast = _fc(14, base=now, out_c=lambda i: 12 if i < 6 else 32, out_rh=70)
    for enabled in (False, True):
        entry = _l3_entry(night_purge=enabled)
        hass = _l3_hass(entry, room=22, rh=55, out=(12, 70), forecast=forecast)
        run(integration._async_cooling_tick(hass, entry, now))
        snap = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]["snapshot"]
        assert snap["projection"] is None and snap["ventDecision"]["kind"] == "none"
        assert not _calls(hass, "turn_on", "switch.vent")


def test_leaving_vent_auto_fails_off_and_ws_vent_actions():
    now = datetime.now(timezone.utc)
    entry = _l3_entry()
    hass = _l3_hass(entry, room=28, rh=75)
    run(integration._async_cooling_tick(hass, entry, now))
    assert hass.states.get("switch.vent").state == "on"
    entry.options[CONF_SETTINGS]["coolingHeadroom"]["vent"]["mode"] = "advise"
    run(integration._async_cooling_tick(hass, entry, now + timedelta(minutes=5)))
    assert len(_calls(hass, "turn_off", "switch.vent")) == 1
    runtime = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]
    assert runtime["vent"] == {}
    conn = FakeConnection()
    run(integration.websocket_cooling_vent(hass, conn, {"id": 1, "type": "x", "action": "run"}))
    assert conn.results[-1].payload["state"] == "on" and hass.states.get("switch.vent").state == "on"
    run(integration.websocket_cooling_vent(hass, conn, {"id": 2, "type": "x", "action": "stop"}))
    assert hass.states.get("switch.vent").state == "off"
    integration.websocket_cooling_status(hass, conn, {"id": 3, "type": "openreef/cooling_status"})
    payload = conn.results[-1].payload
    assert payload["ventFan"]["asserted"] == "off" and payload["ventDecision"]["kind"] == "cool"
    unbound = _l3_entry(fan="")
    run(integration.websocket_cooling_vent(_l3_hass(unbound), conn, {"id": 4, "type": "x", "action": "run"}))
    assert conn.error_codes[-1] == "not_bound"



# --------------------------------------------------------------------------- #
# Startup lifecycle
# --------------------------------------------------------------------------- #



def test_schedule_defers_the_first_read_until_ha_has_started():
    now = datetime.now(timezone.utc)
    entry = _l2_entry()
    hass = _l2_hass(entry, forecast=_humid_afternoon(now))
    hass.is_running = False
    run(integration._async_schedule_cooling_tick(hass, entry))
    assert not [c for c in hass.services.calls if c.service == "get_forecasts"]   # nothing while booting
    assert integration.COOLING_TICK_UNSUB in hass.data[integration.DOMAIN]
    hass.is_running = True
    started = [l for l in hass.bus.listeners if l.event_type == integration.EVENT_HOMEASSISTANT_STARTED]
    assert len(started) == 1
    run(started[0].callback(None))                                                # HA fires "started"
    assert not [c for c in hass.services.calls if c.service == "get_forecasts"]
    assert hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]["snapshot"]["projection"] is None
    # Already running: the first read happens inline.
    entry2 = _l2_entry()
    hass2 = _l2_hass(entry2, forecast=_humid_afternoon(now))
    run(integration._async_schedule_cooling_tick(hass2, entry2))
    assert not [c for c in hass2.services.calls if c.service == "get_forecasts"]
    assert "snapshot" in hass2.data[integration.DOMAIN][integration.COOLING_RUNTIME]


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
