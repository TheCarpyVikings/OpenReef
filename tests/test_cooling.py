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


def test_parse_forecast_tolerates_missing_fields_and_fahrenheit():
    items = _fc(3, out_c=20, out_rh=50, unit_f=True)
    items.append({"datetime": (NOW + timedelta(hours=3)).isoformat(), "temperature": 68.0,
                  "dew_point": 50.0})                              # dew, no humidity
    items.append({"datetime": (NOW + timedelta(hours=4)).isoformat(), "temperature": 68.0})  # neither → dropped
    items.append({"datetime": "junk", "temperature": 68.0, "humidity": 50})                 # bad time → dropped
    items.append("nonsense")
    hours = cooling.parse_forecast(items, "°F")
    assert len(hours) == 4
    assert hours[0]["outC"] == 20.0 and abs(hours[0]["outDewC"] - 9.3) < 0.1
    assert abs(hours[3]["outDewC"] - 10.0) < 0.01 and 50 < hours[3]["outRh"] < 55
    assert cooling.parse_forecast(None) == [] and cooling.parse_forecast({"x": 1}) == []
    z = cooling.parse_forecast([{"datetime": "2026-07-14T14:00:00Z", "temperature": 20, "humidity": 50}])
    assert z[0]["at"].tzinfo is not None


def test_offsets_smooth_towards_the_live_difference_and_clamp():
    first = cooling.smooth_offsets(None, 30.0, 24.0, 22.0, 15.0)     # +8 / +9 live
    assert cooling.DEFAULT_OFFSET_T_C < first["offsetT"] < 8.0
    later = first
    for _ in range(30):
        later = cooling.smooth_offsets(later, 30.0, 24.0, 22.0, 15.0)
    assert abs(later["offsetT"] - 8.0) < 0.05 and abs(later["offsetDew"] - 9.0) < 0.05
    same = cooling.smooth_offsets(later, None, None, 22.0, 15.0)   # indoor missing → unchanged
    assert same == later
    wild = cooling.smooth_offsets(None, 60.0, 40.0, 0.0, 0.0)
    assert wild["offsetT"] <= cooling.OFFSET_T_RANGE[1] and wild["offsetDew"] <= cooling.OFFSET_DEW_RANGE[1]


def test_projection_finds_the_humid_afternoon_and_classifies_the_day():
    # A UK humid-heat day: outdoor climbs 18 → 27 °C by hour 6 at 65 % RH, drops overnight.
    out_c = lambda i: 18 + 9 * max(0.0, 1 - abs(i - 6) / 6)
    hours = cooling.parse_forecast(_fc(24, out_c=out_c, out_rh=55))
    proj = cooling.project(hours, NOW, 24, 25.5, 25.5, {"offsetT": 3.0, "offsetDew": 5.0}, 1.0)
    assert proj["dayKind"] == "humid-heat" and proj["affectedHours"] >= 1
    assert proj["firstAffectedAt"] is not None and proj["worst"]["index"] < 0.4
    assert proj["neededHours"] > proj["affectedHours"]
    assert proj["purgeWindow"] and proj["purgeWindow"]["outC"] == 18.0
    # Same shape but dry: 35 % RH → fans needed, never losing.
    dry = cooling.project(cooling.parse_forecast(_fc(24, out_c=out_c, out_rh=35)), NOW, 24, 25.5, 25.5,
                          {"offsetT": 3.0, "offsetDew": 3.0}, 1.0)
    assert dry["dayKind"] == "dry-heat" and dry["affectedHours"] == 0
    # A cool day: nothing needed.
    quiet = cooling.project(cooling.parse_forecast(_fc(24, out_c=14, out_rh=90)), NOW, 24, 25.5, 25.5,
                            {"offsetT": 3.0, "offsetDew": 3.0}, 1.0)
    assert quiet["dayKind"] == "quiet" and quiet["worst"] is None
    # A brutal day: 32 °C outdoors at 75 % → room far over target and dead → chiller.
    hot = cooling.project(cooling.parse_forecast(_fc(24, out_c=32, out_rh=75)), NOW, 24, 25.5, 25.5,
                          {"offsetT": 3.0, "offsetDew": 3.0}, 1.0)
    assert hot["dayKind"] == "chiller"
    # Window respected; nothing inside → None.
    assert cooling.project(hours, NOW + timedelta(days=3), 24, 25.5, 25.5, {}, 1.0) is None
    assert cooling.project([], NOW, 24, 25.5, 25.5, {}, 1.0) is None


def test_plan_now_ahead_scheduled_none_and_unrescuable():
    live_bad = cooling.evaluate(26, 28, 75)                       # weak, room not far over target
    plan = cooling.dehumidifier_plan(live_bad, True, None, NOW, 3, 25.5)
    assert plan["shouldRun"] and plan["kind"] == "now"
    # Live bad but room far over target and index ≈ 0 → chiller day, don't start.
    live_hopeless = cooling.evaluate(26, 31, 85)
    plan = cooling.dehumidifier_plan(live_hopeless, True, None, NOW, 3, 25.5)
    assert not plan["shouldRun"] and plan["kind"] == "unrescuable"
    # Live fine, a hit at +5 h with a 3 h lead → scheduled now, ahead at +2 h, still on at +5 h, off after.
    out_c = lambda i: 20 if i < 5 else 27
    proj = cooling.project(cooling.parse_forecast(_fc(12, out_c=out_c, out_rh=70)), NOW, 24, 25.5, 25.5,
                           {"offsetT": 3.0, "offsetDew": 5.0}, 1.0)
    assert proj["firstAffectedAt"] == (NOW + timedelta(hours=5)).isoformat()
    live_ok = cooling.evaluate(25.5, 23, 60)
    sched = cooling.dehumidifier_plan(live_ok, False, proj, NOW, 3, 25.5)
    assert not sched["shouldRun"] and sched["kind"] == "scheduled"
    assert sched["startAt"] == (NOW + timedelta(hours=2)).isoformat()
    ahead = cooling.dehumidifier_plan(live_ok, False, proj, NOW + timedelta(hours=2), 3, 25.5)
    assert ahead["shouldRun"] and ahead["kind"] == "ahead" and "%" in ahead["reason"]
    still = cooling.dehumidifier_plan(live_ok, False, proj, NOW + timedelta(hours=11, minutes=30), 3, 25.5)
    assert still["shouldRun"]
    done = cooling.dehumidifier_plan(live_ok, False, proj, NOW + timedelta(hours=13), 3, 25.5)
    assert not done["shouldRun"] and done["kind"] == "none"
    # A cool humid live reading is not "now" — the gate holds.
    quiet = cooling.dehumidifier_plan(cooling.evaluate(26, 20, 95), False, None, NOW, 3, 25.5)
    assert quiet["kind"] == "none"


def test_vent_advice_prefers_drier_cooler_outdoor_air():
    yes = cooling.vent_advice(28.0, 22.0, 18.0, 12.0)
    assert yes["advised"] and yes["gapC"] == 10.0
    wet = cooling.vent_advice(28.0, 22.0, 18.0, 21.0)
    assert not wet["advised"] and "as wet" in wet["reason"]
    warm = cooling.vent_advice(28.0, 22.0, 33.0, 12.0)
    assert not warm["advised"] and "warmer" in warm["reason"]
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


def test_tick_reads_the_forecast_once_per_ttl_and_projects():
    entry = _l2_entry()
    now = datetime.now(timezone.utc)
    hass = _l2_hass(entry, forecast=_humid_afternoon(now))
    run(integration._async_cooling_tick(hass, entry, now))
    run(integration._async_cooling_tick(hass, entry, now + timedelta(minutes=5)))
    fetches = [c for c in hass.services.calls if c.service == "get_forecasts"]
    assert len(fetches) == 1 and fetches[0].kwargs.get("return_response") is True
    snap = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]["snapshot"]
    assert snap["projection"]["dayKind"] == "humid-heat"
    assert snap["plan"]["kind"] == "scheduled" and snap["weather"]["outC"] == 20.0
    assert snap["vent"]["known"] and snap["offsets"]["offsetT"] > 0
    assert not _plug_calls(hass, "turn_on")                    # advise never switches


def test_tick_advise_notifies_once_when_the_lead_window_opens():
    entry = _l2_entry()
    now = datetime.now(timezone.utc)
    hass = _l2_hass(entry, forecast=_humid_afternoon(now))
    run(integration._async_cooling_tick(hass, entry, now))
    assert not _notes(hass)                                    # scheduled: logged, not pushed
    assert any("start by" in a["message"] for a in _activity(entry, "Dehumidifier"))
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=2, minutes=1)))
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=2, minutes=6)))
    plan_notes = [n for n in _notes(hass) if "plan_ahead" in str(n.data.get("notification_id"))]
    assert len(plan_notes) == 1
    assert "Start the dehumidifier" in plan_notes[0].data.get("title", "")
    assert not _plug_calls(hass, "turn_on")


def test_tick_without_a_weather_entity_stays_layer_one():
    entry = _entry()
    hass = _hass(entry, room=23, rh=60)
    run(integration._async_cooling_tick(hass, entry, NOW))
    snap = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]["snapshot"]
    assert snap["projection"] is None and snap["plan"]["kind"] == "none"
    assert not snap["vent"]["known"] and "weather" not in snap["issues"]
    assert not [c for c in hass.services.calls if c.service == "get_forecasts"]


def test_tick_broken_forecast_is_an_issue_not_a_crash():
    entry = _l2_entry()
    hass = _l2_hass(entry)
    hass.services.responses[("weather", "get_forecasts")] = {"weather.home": {"forecast": "nope"}}
    run(integration._async_cooling_tick(hass, entry, datetime.now(timezone.utc)))
    snap = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]["snapshot"]
    assert "forecast" in snap["issues"] and snap["projection"] is None
    hass.states.set("weather.home", FakeState("unavailable"))
    hass.services.fail_on.add(("weather", "get_forecasts"))
    hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]["forecast"].clear()
    run(integration._async_cooling_tick(hass, entry, datetime.now(timezone.utc)))
    snap = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]["snapshot"]
    assert "weather" in snap["issues"] and "forecast" in snap["issues"]


def test_auto_disarmed_never_switches_and_armed_drives_the_plan():
    now = datetime.now(timezone.utc)
    entry = _l2_entry(mode="auto", armed=False)
    hass = _l2_hass(entry, forecast=_humid_afternoon(now))
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3)))
    assert not _plug_calls(hass, "turn_on")
    entry = _l2_entry(mode="auto", armed=True)
    hass = _l2_hass(entry, forecast=_humid_afternoon(now))
    run(integration._async_cooling_tick(hass, entry, now))                          # scheduled → off
    assert not _plug_calls(hass, "turn_on")
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3)))     # ahead → on
    assert len(_plug_calls(hass, "turn_on")) == 1 and hass.states.get("switch.dehum").state == "on"
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3, minutes=5)))
    assert len(_plug_calls(hass, "turn_on")) == 1                                   # reconciled, no spam
    assert any("Dehumidifier switched on" in a["message"] for a in
               entry.options[CONF_SETTINGS]["activity"])


def test_auto_short_cycle_guard_and_max_run():
    now = datetime.now(timezone.utc)
    entry = _l2_entry(mode="auto", armed=True)
    hass = _l2_hass(entry, forecast=_humid_afternoon(now))
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3)))     # on
    runtime = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]
    # Plan flips to none (the forecast comes back empty) a minute later → min-on holds it.
    hass.services.responses[("weather", "get_forecasts")] = {"weather.home": {"forecast": []}}
    runtime["forecast"].clear()
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3, minutes=1)))
    assert not _plug_calls(hass, "turn_off")
    runtime["dehum"]["lastOn"] = (now - timedelta(hours=1)).isoformat()
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3, minutes=2)))
    assert len(_plug_calls(hass, "turn_off")) == 1
    # Max run: asserted on for longer than the cap → off + a bucket nudge.
    runtime["forecast"] = {"entity": "weather.home", "at": now.timestamp() + 99999,
                           "hours": cooling.parse_forecast(_fc(12, base=now, out_c=27, out_rh=70)), "error": ""}
    runtime["dehum"] = {"asserted": "on", "lastOn": (now - timedelta(hours=9)).isoformat()}
    hass.states.set("switch.dehum", "on")
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=1)))
    assert len(_plug_calls(hass, "turn_off")) == 2
    assert any("max_run" in str(n.data.get("notification_id")) for n in _notes(hass))


def test_auto_hold_respects_a_hand_on_the_plug_and_leaving_auto_fails_off():
    now = datetime.now(timezone.utc)
    entry = _l2_entry(mode="auto", armed=True)
    hass = _l2_hass(entry, forecast=_humid_afternoon(now))
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3)))     # on
    hass.states.set("switch.dehum", "off")                                         # a human
    run(integration._async_cooling_tick(hass, entry, now + timedelta(hours=3, minutes=5)))
    assert len(_plug_calls(hass, "turn_on")) == 1                                   # held
    runtime = hass.data[integration.DOMAIN][integration.COOLING_RUNTIME]
    assert runtime["dehum"]["override"]["state"] == "off"
    # Plan flips to none (empty forecast) → the hold releases.
    hass.services.responses[("weather", "get_forecasts")] = {"weather.home": {"forecast": []}}
    runtime["forecast"].clear()
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
