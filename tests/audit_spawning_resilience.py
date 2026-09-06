"""Read-only spawning beta audit; real engine and executor, fake HA/devices.

Run: python3 tests/audit_spawning_resilience.py [--annual]
FAIL means a desired reliability property is not met, not a harness error.
This is intentionally outside test_*.py discovery: it records unresolved audit
findings rather than teaching CI that the present bugs are correct behaviour.
No installed Home Assistant, network, credentials or real equipment are used.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import time
from unittest.mock import patch
from zoneinfo import ZoneInfo

import test_spawning as fixtures
from _fake_ha import FakeConnection, FakeIntervalScheduler, FakeState

i = fixtures.integration
brain = fixtures.spawning
UTC = timezone.utc
NOON = datetime(2026, 6, 17, 13, tzinfo=UTC)
RESULTS = []


def record(name, healthy, **evidence):
    result = {"check": name, "result": "PASS" if healthy else "FAIL", **evidence}
    RESULTS.append(result)
    print(json.dumps(result, default=str), flush=True)


def runtime(hass):
    return hass.data.get(i.DOMAIN, {}).get(i.SPAWNING_RUNTIME, {})


def sensor(value, when=NOON):
    st = FakeState(str(value), {"unit_of_measurement": "°C"}, last_changed=when)
    st.last_updated = when
    st.last_reported = when
    return st


def notes(hass):
    return [c.data for c in hass.services.calls if c.domain == "persistent_notification"]


async def tick(hass, entry, when=NOON):
    with patch.object(i.dt_util, "utcnow", return_value=when.astimezone(UTC)), patch.object(i.dt_util, "now", return_value=when):
        await i._async_spawning_tick(hass, entry, when)


async def fault_checks():
    entry = fixtures._exec_entry()
    hass = fixtures._exec_hass(entry)
    hass.services.responses[("switch", "turn_on")] = None  # accepts but never changes state
    for minute in range(3):
        await tick(hass, entry, NOON + timedelta(minutes=minute))
    writes = fixtures._switch_calls(hass, "turn_on")
    record("unfulfilled light command retries without inventing a human override",
           len(writes) > 1 and not runtime(hass).get("overrides"),
           writes=len(writes), actual=hass.states.get("switch.tank_light").state,
           overrides=runtime(hass).get("overrides"), issues=runtime(hass).get("issues"))

    entry = fixtures._exec_entry()
    hass = fixtures._exec_hass(entry)
    await tick(hass, entry)
    hass.states.set("switch.tank_light", "unavailable")
    await tick(hass, entry, NOON + timedelta(minutes=1))
    hass.states.set("switch.tank_light", "off")  # plug's boot default
    await tick(hass, entry, NOON + timedelta(minutes=2))
    record("plug reboot recovers the daylight state with the default policy",
           hass.states.get("switch.tank_light").state == "on",
           actual=hass.states.get("switch.tank_light").state,
           overrides=runtime(hass).get("overrides"))

    conn = FakeConnection()
    i.websocket_spawning_execution_resume(hass, conn, {"id": 1})
    await tick(hass, entry, NOON + timedelta(minutes=3))
    record("Resume now actually resumes on the following tick",
           hass.states.get("switch.tank_light").state == "on",
           actual=hass.states.get("switch.tank_light").state,
           overrides=runtime(hass).get("overrides"))

    # Recreate HA runtime, retaining only the saved entry and equipment states.
    restarted = fixtures._exec_hass(entry, {"switch.tank_light": "off"})
    await tick(restarted, entry, NOON + timedelta(minutes=4))
    record("first post-restart tick reconstructs correct daylight from saved config",
           restarted.states.get("switch.tank_light").state == "on")

    entry = fixtures._exec_entry()
    hass = fixtures._exec_hass(entry)
    hass.services.fail_on.add(("switch", "turn_on"))
    await tick(hass, entry)
    hass.services.fail_on.clear()
    await tick(hass, entry, NOON + timedelta(minutes=1))
    record("raised service error recovers on the next tick",
           hass.states.get("switch.tank_light").state == "on")

    entry = fixtures._temp_entry()
    healthy_probe = sensor(24.4, NOON - timedelta(minutes=20))
    healthy_probe.last_reported = NOON
    hass = fixtures._exec_hass(entry, {
        "sensor.tank_temp": healthy_probe, "switch.heater": "on", "switch.fan": "off"})
    await tick(hass, entry)
    record("fresh identical sensor reports are accepted",
           "temp" not in runtime(hass).get("issues", {}),
           heater=hass.states.get("switch.heater").state,
           issues=runtime(hass).get("issues"))

    entry = fixtures._temp_entry()
    hass = fixtures._exec_hass(entry, {
        "sensor.tank_temp": "unavailable", "switch.heater": "on", "switch.fan": "off"})
    hass.services.fail_on.add(("switch", "turn_off", "switch.heater"))
    await tick(hass, entry)
    messages = " ".join(n.get("message", "") for n in notes(hass))
    record("failed safety OFF is reported as unconfirmed, not switched off",
           "were switched OFF" not in messages,
           heater=hass.states.get("switch.heater").state,
           issues=runtime(hass).get("issues"), notifications=notes(hass))

    entry = fixtures._temp_entry()
    hass = fixtures._exec_hass(entry, {
        "sensor.tank_temp": sensor(24.4), "switch.heater": "off", "switch.fan": "off"})
    hass.services.fail_on.add(("switch", "turn_on", "switch.heater"))
    await tick(hass, entry)
    record("temperature command exception creates an actuator issue or alert",
           bool(runtime(hass).get("issues")) or bool(notes(hass)),
           issues=runtime(hass).get("issues"), notifications=notes(hass))

    entry = fixtures._temp_entry()
    hass = fixtures._exec_hass(entry, {
        "sensor.tank_temp": sensor(24.4), "switch.heater": "off", "switch.fan": "off"})
    await tick(hass, entry)
    entry.options[fixtures.CONF_SETTINGS]["spawningProgram"]["execution"]["armed"] = False
    hass.states.set("sensor.tank_temp", sensor(30))
    await tick(hass, entry)
    record("disarm provides a safe handoff for an already energised heater",
           hass.states.get("switch.heater").state == "off",
           heater=hass.states.get("switch.heater").state)

    entry = fixtures._temp_entry()
    hass = fixtures._exec_hass(entry, {
        "sensor.tank_temp": sensor(24.4), "switch.heater": "off", "switch.fan": "off",
        "switch.replacement_heater": "off"})
    await tick(hass, entry)
    entry.options[fixtures.CONF_SETTINGS]["spawningProgram"]["execution"]["temp"]["heaterEntity"] = "switch.replacement_heater"
    await tick(hass, entry)
    record("rebinding temperature control releases the old heater safely",
           hass.states.get("switch.heater").state == "off",
           old_heater=hass.states.get("switch.heater").state,
           new_heater=hass.states.get("switch.replacement_heater").state)

    entry = fixtures._temp_entry()
    hass = fixtures._exec_hass(entry, {
        "sensor.tank_temp": sensor(24.7), "switch.heater": "on", "switch.fan": "on"})
    await tick(hass, entry)
    record("heater and cooler cannot remain simultaneously on inside the deadband",
           not all(hass.states.get(ent).state == "on" for ent in ("switch.heater", "switch.fan")),
           heater=hass.states.get("switch.heater").state, cooler=hass.states.get("switch.fan").state)

    entry = fixtures._exec_entry(moonEntity="switch.tank_light")
    cfg = entry.options[fixtures.CONF_SETTINGS]["spawningProgram"]["execution"]
    hass = fixtures._exec_hass(entry)
    conn = FakeConnection()
    await i.websocket_save_config(hass, conn, {"id": 1, "config": i._config_from_entry(entry)})
    await tick(hass, entry)
    record("duplicate daylight and moonlight bindings are rejected and cannot actuate",
           bool(conn.errors) and not fixtures._switch_calls(hass, "turn_on"), bindings=cfg)

    # A pending service yields control to an actual concurrent config edit.
    entry = fixtures._exec_entry()
    hass = fixtures._exec_hass(entry)
    entered, release = asyncio.Event(), asyncio.Event()
    original = hass.services.async_call

    async def delayed(domain, service, data=None, **kwargs):
        if domain == "switch":
            entered.set()
            await release.wait()
        return await original(domain, service, data, **kwargs)

    hass.services.async_call = delayed
    task = asyncio.create_task(tick(hass, entry))
    await entered.wait()
    new_cfg = i._config_from_entry(entry)
    new_cfg["spawningProgram"]["execution"]["armed"] = False
    await i._async_save_config(hass, entry, new_cfg)
    release.set()
    await task
    record("concurrent user disarm survives an older tick finishing its activity save",
           not entry.options[fixtures.CONF_SETTINGS]["spawningProgram"]["execution"]["armed"],
           armed_after=entry.options[fixtures.CONF_SETTINGS]["spawningProgram"]["execution"]["armed"])

    entry = fixtures._exec_entry(temp=fixtures._TEMP_BINDINGS)
    hass = fixtures._exec_hass(entry, {
        "sensor.tank_temp": "unavailable", "switch.heater": "on", "switch.fan": "off"})
    entered, release = asyncio.Event(), asyncio.Event()
    original = hass.services.async_call

    async def stalled_light(domain, service, data=None, **kwargs):
        if data and "switch.tank_light" in data.values():
            entered.set()
            await release.wait()
        return await original(domain, service, data, **kwargs)

    hass.services.async_call = stalled_light
    task = asyncio.create_task(tick(hass, entry))
    await entered.wait()
    for _ in range(5):
        await asyncio.sleep(0)
    record("stalled daylight service does not block sensor-fault heater shutdown",
           hass.states.get("switch.heater").state == "off",
           heater_while_light_pending=hass.states.get("switch.heater").state,
           temperature_issue_recorded="temp" in runtime(hass).get("issues", {}))
    release.set()
    await task

    # Model saves at t=0,30,...,300 s; cancellation postpones each due tick.
    scheduler = FakeIntervalScheduler()
    entry = fixtures._exec_entry()
    hass = fixtures._exec_hass(entry)
    due = None
    timer = None
    fired = 0
    with patch.object(i, "async_track_time_interval", scheduler.track):
        for second in range(0, 301, 30):
            if due is not None and second >= due:
                await tick(hass, entry, NOON + timedelta(seconds=second))
                fired += 1
                due += int(timer["interval"].total_seconds())
            await i._async_save_config(hass, entry, i._config_from_entry(entry))
            spawn_timer = next(r for r in scheduler.pending()
                               if "_async_schedule_spawning_tick" in r["callback"].__qualname__)
            if spawn_timer is not timer:
                due = second + int(spawn_timer["interval"].total_seconds())
                timer = spawn_timer
    record("unrelated saves every 30 seconds cannot starve spawning for five minutes",
           fired > 0, ticks=fired, light=hass.states.get("switch.tank_light").state)


def calendar_checks():
    cfg = fixtures._sp_cfg()
    prediction = brain.predict_spawn_window(fixtures.REEF_PRESETS["gbr_central"], 2026, 0)
    last_evening = datetime.fromisoformat(prediction["windowEnd"]).replace(hour=23, tzinfo=UTC)
    actual = brain.execution_desired_state(cfg, last_evening)
    record("last predicted spawn evening remains inside its window",
           actual["inSpawnWindow"], original_window=prediction,
           evaluated_at=last_evening, actual_window=actual["spawnWindow"])

    # Find a December full moon whose predicted nights carry into January.
    for year in range(2026, 2040):
        pred = brain.predict_spawn_window(fixtures.REEF_PRESETS["gbr_central"], year, 1)
        end = datetime.fromisoformat(pred["windowEnd"]).replace(hour=1, tzinfo=UTC)
        if end.year > year:
            start = datetime.fromisoformat(pred["windowStart"]).replace(tzinfo=UTC)
            when = max(start, datetime(year + 1, 1, 1, tzinfo=UTC)) + timedelta(hours=1)
            shifted = {**cfg, "offsetMonths": 1}
            actual = brain.execution_desired_state(shifted, when)
            record("December spawn window is retained after New Year",
                   actual["spawnWindow"] == {"start": pred["windowStart"], "end": pred["windowEnd"]}, evaluated_at=when,
                   original_window=pred, actual_window=actual["spawnWindow"])
            break

    defaults = i._normalise_core_config({})["spawningProgram"]["execution"]["temp"]
    for pid, preset in fixtures.REEF_PRESETS.items():
        temps = preset["sstMonthlyC"]
        compatible = min(temps) - 0.2 >= defaults["minC"] and max(temps) + 0.2 <= defaults["maxC"]
        error = brain.temperature_profile_error({"reefPreset": pid, "execution": {"temp": {**defaults, "enabled": True}}})
        record("incompatible preset/default limits are explicitly rejected: " + pid,
               bool(error) != compatible,
               validation_error=error,
               target_min=min(temps), target_max=max(temps),
               minC=defaults["minC"], maxC=defaults["maxC"],
               largest_monthly_step=max(abs(temps[m] - temps[m-1]) for m in range(12)))


def annual_checks():
    cfg = fixtures._sp_cfg()
    tz = ZoneInfo("Europe/London")
    start = datetime(2026, 9, 6, tzinfo=tz).astimezone(UTC)
    end = datetime(2027, 9, 6, tzinfo=tz).astimezone(UTC)
    now = start
    count = invalid = simultaneous = 0
    transitions = 0
    last_light = None
    wall_start = time.perf_counter()
    while now < end:
        local = now.astimezone(tz)
        state = brain.execution_desired_state(cfg, local)
        invalid += not state.get("valid")
        simultaneous += bool(state.get("light") and state.get("moon"))
        if last_light is not None and state["light"] != last_light:
            transitions += 1
        last_light = state["light"]
        count += 1
        now += timedelta(minutes=1)
        if count % 50000 == 0:
            print(json.dumps({"progress": count, "of": 525600}), flush=True)
    record("365 days of minute-by-minute GBR desired states including UK DST",
           invalid == 0 and simultaneous == 0 and transitions == 730,
           evaluations=count, invalid=invalid, overlapping_light_and_moon=simultaneous,
           daylight_transitions=transitions, elapsed_seconds=round(time.perf_counter()-wall_start, 2))

    # All locations and seasonal offsets, including a leap year, sampled daily.
    samples = invalid = 0
    for year in (2027, 2028):
        for pid in fixtures.REEF_PRESETS:
            for offset in range(12):
                now = datetime(year, 1, 1, 13, tzinfo=tz)
                while now.year == year:
                    state = brain.execution_desired_state({**cfg, "reefPreset": pid, "offsetMonths": offset}, now)
                    invalid += not state.get("valid") or not 0 < state["dayLengthHours"] < 24
                    samples += 1
                    now += timedelta(days=1)
    record("all five presets and twelve offsets across normal and leap years",
           invalid == 0, evaluations=samples, invalid=invalid)


async def annual_executor_check():
    """Exercise the beta's daylight-only executor with hourly fake-HA ticks.

    The separate minute sweep checks exact clock boundaries. This checks saved
    config, real reconciliation, activity retention and periodic runtime loss.
    It is not a simulation of HA startup internals or real relay operation.
    """
    tz = ZoneInfo("Europe/London")
    now = datetime(2026, 9, 6, tzinfo=tz).astimezone(UTC)
    end = datetime(2027, 9, 6, tzinfo=tz).astimezone(UTC)
    entry = fixtures._exec_entry()
    hass = fixtures._exec_hass(entry)
    samples = mismatches = restarts = writes = 0
    while now < end:
        if samples and samples % (30 * 24) == 0:
            writes += len(fixtures._switch_calls(hass, "turn_on")) + len(fixtures._switch_calls(hass, "turn_off"))
            hass = fixtures._exec_hass(entry, {"switch.tank_light": hass.states.get("switch.tank_light").state})
            restarts += 1
        local = now.astimezone(tz)
        await tick(hass, entry, local)
        expected = brain.execution_desired_state(entry.options[fixtures.CONF_SETTINGS]["spawningProgram"], local)["light"]
        mismatches += (hass.states.get("switch.tank_light").state == "on") != expected
        samples += 1
        now += timedelta(hours=1)
    writes += len(fixtures._switch_calls(hass, "turn_on")) + len(fixtures._switch_calls(hass, "turn_off"))
    record("beta daylight executor across 365 days with twelve simulated runtime resets",
           mismatches == 0, hourly_ticks=samples, simulated_restarts=restarts,
           mismatches=mismatches, light_commands=writes,
           activity_entries_retained=len(entry.options[fixtures.CONF_SETTINGS]["activity"]))


async def annual_temperature_check():
    """Scripted cold/warm readings over a year; not a physical tank heat model."""
    tz = ZoneInfo("Europe/London")
    now = datetime(2026, 9, 6, tzinfo=tz).astimezone(UTC)
    end = datetime(2027, 9, 6, tzinfo=tz).astimezone(UTC)
    entry = fixtures._exec_entry(moonEntity="switch.moon", temp=fixtures._TEMP_BINDINGS)
    outputs = ("switch.heater", "switch.fan", "switch.tank_light", "switch.moon")
    hass = fixtures._exec_hass(entry, {e: "off" for e in outputs})
    count = restarts = wrong = overlap = writes = lighting_mismatches = 0
    while now < end:
        if count and count % 720 == 0:
            writes += sum(c.domain == "switch" for c in hass.services.calls)
            hass = fixtures._exec_hass(entry, {
                e: hass.states.get(e).state for e in outputs
            })
            restarts += 1
        local = now.astimezone(tz)
        target = brain.seasonal_temperature(fixtures.REEF_PRESETS["gbr_central"], local.date())
        cold = (count // 6) % 2 == 0
        probe = sensor(target + (-0.4 if cold else 0.4), now)
        if count % 2:
            probe.state = str(float(probe.state) * 9 / 5 + 32)
            probe.attributes["unit_of_measurement"] = "°F"
        hass.states.set("sensor.tank_temp", probe)
        await tick(hass, entry, local)
        heating = hass.states.get("switch.heater").state == "on"
        cooling = hass.states.get("switch.fan").state == "on"
        desired = brain.execution_desired_state(entry.options[fixtures.CONF_SETTINGS]["spawningProgram"], local)
        lighting_mismatches += any(
            (hass.states.get(e).state == "on") != desired[key]
            for e, key in (("switch.tank_light", "light"), ("switch.moon", "moon"))
        )
        overlap += heating and cooling
        wrong += heating != cold or cooling == cold
        count += 1
        now += timedelta(hours=1)
    writes += sum(c.domain == "switch" for c in hass.services.calls)
    record("full OpenReef executor across 365 days with C/F readings and twelve runtime resets",
           wrong == 0 and overlap == 0 and lighting_mismatches == 0, hourly_ticks=count, simulated_restarts=restarts,
           wrong_thermal_outputs=wrong, simultaneous_heat_cool=overlap, lighting_mismatches=lighting_mismatches, output_commands=writes,
           note="Scripted ±0.4°C demand; fan restart delay set to zero; not a physical heat-capacity model")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annual", action="store_true", help="also run the full minute/year and preset matrix (several minutes)")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)  # failures are deliberately injected; evidence is printed above
    asyncio.run(fault_checks())
    calendar_checks()
    if args.annual:
        annual_checks()
        asyncio.run(annual_executor_check())
        asyncio.run(annual_temperature_check())
    failures = sum(r["result"] == "FAIL" for r in RESULTS)
    print(json.dumps({"summary": {"checks": len(RESULTS), "failed": failures, "passed": len(RESULTS)-failures}}))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
