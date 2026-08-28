"""Saltwater Mixing Station — Stage A: the mixing.py engine, its normaliser,
and the mixing_summary WS read (docs/mixing-station-brainstorm.md §12).

Covers: the brand table + dose/correction honesty (custom brand with no g/L
gives NO figure), the layout-aware stage sequence (heat BEFORE salt, transfer
dual-only), the stamped batch clocks (mix window, storing age/retest — brand
use-within tightening included), the estimated level ledger, start guards,
_normalise_mixing_config (junk tolerance, clamps, a running batch's stamps
surviving a normalise pass), and websocket_mixing_summary against the fake HA.

Run standalone:  python3 tests/test_mixing.py
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
from openreef import mixing  # noqa: E402

from _fake_ha import FakeConnection, FakeEntry, FakeHass, run  # noqa: E402

CONF_SETTINGS = integration.CONF_SETTINGS
NOW = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _cfg(**over):
    cfg = {
        "enabled": True,
        "layout": "dual",
        "vessels": {
            "rodi": {"volumeLitres": 50, "estimatedLitres": 40, "levelSensorEntity": ""},
            "mix": {"volumeLitres": 50, "levelSensorEntity": ""},
        },
        "salt": {"brand": "nyos_pure", "targetPpt": 35.0, "mixHours": 0, "customGPerL": 0},
        "heat": {"enabled": True, "targetC": 25.0, "tempSensorEntity": ""},
        "storage": {"circulateEveryH": 6, "circulateForMin": 10, "retestAfterDays": 7},
        "batch": {"state": "idle", "type": "salt", "startedAt": "", "stageAt": "",
                  "litres": 0, "loggedPpt": 0, "testedAt": "", "usedLitres": 0},
    }
    cfg.update(over)
    return cfg


# ---------------------------------------------------------------- brand table

def test_brand_table_has_the_locked_lineup():
    ids = mixing.brand_ids()
    assert "nyos_pure" in ids and "custom" in ids
    assert "redsea_coralpro" in ids and "instant_ocean" in ids
    assert mixing.brand_info("nope")["id"] == "custom"   # unknown falls to custom


def test_custom_brand_gives_no_figure_without_g_per_l():
    assert mixing.brand_g_per_l("custom") == 0.0
    assert mixing.brand_g_per_l("custom", 37.0) == 37.0
    assert mixing.salt_dose("custom", 50, 35) == {
        "available": False, "grams": None, "gPerL": None}


def test_mix_hours_override_beats_brand_default_and_floors_at_2h():
    assert mixing.mix_hours("nyos_pure") == 2.0
    assert mixing.mix_hours("instant_ocean") == 12.0
    assert mixing.mix_hours("instant_ocean", 3.5) == 3.5
    assert mixing.mix_hours("custom") == 2.0    # no brand default → floor


# ---------------------------------------------------------------- dose maths

def test_salt_dose_scales_off_the_brand_figure():
    dose = mixing.salt_dose("nyos_pure", 50, 35)
    assert dose["available"] and dose["grams"] == 1950 and dose["gPerL"] == 39.0
    # Off-reference target scales linearly.
    dose33 = mixing.salt_dose("nyos_pure", 50, 33)
    assert dose33["gPerL"] == round(39.0 * 33 / 35, 1)


def test_correction_pass_low_and_high():
    assert mixing.salinity_correction(35.2, 35, 50, "nyos_pure")["status"] == "pass"
    low = mixing.salinity_correction(33.0, 35, 50, "nyos_pure")
    assert low["status"] == "low"
    assert low["addGrams"] == round(2.0 / 35.0 * 39.0 * 50, 0)
    high = mixing.salinity_correction(37.0, 35, 50, "nyos_pure")
    assert high["status"] == "high" and high["addGrams"] is None
    assert high["diluteLitres"] == round(50 * (37.0 / 35.0 - 1.0), 1)


def test_correction_low_with_unknown_brand_figure_stays_honest():
    low = mixing.salinity_correction(33.0, 35, 50, "custom")
    assert low["status"] == "low" and low["addGrams"] is None


# ---------------------------------------------------------------- stage plan

def test_stage_sequence_dual_salt_with_heat():
    assert mixing.stage_sequence("dual", "salt", True) == (
        "filling", "transferring", "heating", "salting", "ready", "storing")


def test_stage_sequence_heat_precedes_salting_always():
    stages = mixing.stage_sequence("single", "salt", True)
    assert stages.index("heating") < stages.index("salting")
    assert "transferring" not in stages          # single vessel — no transfer


def test_stage_sequence_rodi_batch_skips_heat_salt_and_transfer():
    assert mixing.stage_sequence("dual", "rodi", True) == ("filling", "ready", "storing")


# ---------------------------------------------------------------- batch clocks

def test_batch_state_idle():
    st = mixing.batch_state(_cfg()["batch"], _cfg(), NOW)
    assert st["status"] == "idle" and st["mix"]["testUnlocked"] is False


def test_salting_clock_runs_then_unlocks_the_test():
    cfg = _cfg()
    batch = dict(cfg["batch"], state="salting", litres=50,
                 stageAt=_iso(NOW - timedelta(hours=1)))
    st = mixing.batch_state(batch, cfg, NOW)      # NYOS window: 2 h
    assert st["mix"]["percent"] == 50 and st["mix"]["testUnlocked"] is False
    batch["stageAt"] = _iso(NOW - timedelta(hours=3))
    st = mixing.batch_state(batch, cfg, NOW)
    assert st["mix"]["testUnlocked"] is True and st["mix"]["hoursLeft"] == 0.0


def test_storing_age_flags_retest_after_the_window():
    cfg = _cfg()
    batch = dict(cfg["batch"], state="storing", litres=50, usedLitres=10,
                 testedAt=_iso(NOW - timedelta(days=8)))
    st = mixing.batch_state(batch, cfg, NOW)
    assert st["retestDue"] is True and st["remainingLitres"] == 40.0
    batch["testedAt"] = _iso(NOW - timedelta(days=2))
    assert mixing.batch_state(batch, cfg, NOW)["retestDue"] is False


def test_brand_use_within_tightens_the_retest_clock():
    cfg = _cfg()
    cfg["salt"]["brand"] = "redsea_coralpro"       # use within ~4 h
    batch = dict(cfg["batch"], state="ready", litres=50,
                 testedAt=_iso(NOW - timedelta(hours=6)))
    assert mixing.batch_state(batch, cfg, NOW)["retestDue"] is True


def test_rodi_batch_never_flags_retest():
    cfg = _cfg()
    batch = dict(cfg["batch"], state="storing", type="rodi", litres=50,
                 testedAt=_iso(NOW - timedelta(days=30)))
    assert mixing.batch_state(batch, cfg, NOW)["retestDue"] is False


# ---------------------------------------------------------------- level ledger

def test_vessel_levels_dual_reads_anchor_and_batch():
    cfg = _cfg()
    cfg["batch"] = dict(cfg["batch"], state="storing", litres=50, usedLitres=20)
    levels = mixing.vessel_levels(cfg)
    assert levels["rodi"]["litres"] == 40.0 and levels["rodi"]["percent"] == 80
    assert levels["mix"]["litres"] == 30.0 and levels["mix"]["estimated"] is True


def test_vessel_levels_idle_mix_is_empty_and_anchor_clamps_to_volume():
    cfg = _cfg()
    cfg["vessels"]["rodi"]["estimatedLitres"] = 500   # junk above the vessel
    levels = mixing.vessel_levels(cfg)
    assert levels["mix"]["litres"] == 0.0
    assert levels["rodi"]["litres"] == 50.0           # clamped to the vessel


def test_vessel_levels_single_layout_has_no_rodi_store():
    cfg = _cfg(layout="single")
    assert "rodi" not in mixing.vessel_levels(cfg)


# ---------------------------------------------------------------- guards

def test_start_guards_catch_the_obvious():
    cfg = _cfg(enabled=False)
    reasons = mixing.start_guard_reasons(cfg, 0, "espresso")
    text = " ".join(reasons)
    assert "not enabled" in text and "0 litres" in text and "espresso" in text
    cfg = _cfg()
    cfg["batch"]["state"] = "salting"
    assert any("already in progress" in r for r in mixing.start_guard_reasons(cfg, 20, "salt"))
    assert any("exceeds the mixing vessel" in r
               for r in mixing.start_guard_reasons(_cfg(), 80, "salt"))
    assert mixing.start_guard_reasons(_cfg(), 40, "salt") == []


# ---------------------------------------------------------------- summary

def test_summary_shape_and_vessel_fallback_dose():
    sum_ = mixing.summary(_cfg(), NOW)
    assert sum_["enabled"] and sum_["layout"] == "dual"
    assert sum_["brand"]["id"] == "nyos_pure" and len(sum_["brands"]) >= 10
    # No batch litres yet → the guide quotes a full mix vessel (50 L).
    assert sum_["dose"]["grams"] == 1950
    assert sum_["mixHours"] == 2.0 and sum_["targetPpt"] == 35.0
    assert sum_["levels"]["mix"]["litres"] == 0.0


# ---------------------------------------------------------------- normaliser

def test_normalise_junk_becomes_defaults():
    config = integration._normalise_core_config({"mixingStation": "garbage"})
    mix_cfg = config["mixingStation"]
    assert mix_cfg["enabled"] is False and mix_cfg["layout"] == "dual"
    assert mix_cfg["batch"]["state"] == "idle"
    assert set(mix_cfg["switches"]) == {"rodiBooster", "mixPumpA", "mixPumpB", "heater"}


def test_normalise_clamps_without_moving_a_running_batch():
    stamp = _iso(NOW - timedelta(hours=1))
    config = integration._normalise_core_config({"mixingStation": {
        "enabled": True,
        "layout": "triangular",
        "vessels": {"rodi": {"volumeLitres": 50, "estimatedLitres": 900}},
        "salt": {"brand": "not_a_brand", "targetPpt": 99},
        "heat": {"enabled": True, "targetC": 60},
        "batch": {"state": "salting", "type": "salt", "stageAt": stamp,
                  "startedAt": stamp, "litres": 40},
    }})
    mix_cfg = config["mixingStation"]
    assert mix_cfg["layout"] == "dual"
    assert mix_cfg["vessels"]["rodi"]["estimatedLitres"] == 50.0   # capped by vessel
    assert mix_cfg["salt"]["brand"] == "nyos_pure"
    assert mix_cfg["salt"]["targetPpt"] == 45.0
    assert mix_cfg["heat"]["targetC"] == 32.0
    # The R-rule that matters: a normalise pass never rewrites the clock.
    assert mix_cfg["batch"]["state"] == "salting"
    assert mix_cfg["batch"]["stageAt"] == stamp and mix_cfg["batch"]["litres"] == 40.0


def test_normalise_used_litres_capped_by_batch():
    config = integration._normalise_core_config({"mixingStation": {
        "batch": {"state": "storing", "litres": 30, "usedLitres": 400},
    }})
    assert config["mixingStation"]["batch"]["usedLitres"] == 30.0


# ---------------------------------------------------------------- WS summary

def test_ws_mixing_summary_returns_the_engine_blob():
    entry = FakeEntry(options={CONF_SETTINGS: integration._normalise_core_config(
        {"mixingStation": _cfg()})})
    hass = FakeHass(entries=[entry])
    conn = FakeConnection()
    run(integration.websocket_mixing_summary(hass, conn, {"id": 1}))
    payload = conn.results[-1].payload
    assert payload["success"] is True
    summary = payload["summary"]
    assert summary["enabled"] is True and summary["batch"]["status"] == "idle"
    assert summary["dose"]["available"] is True
    assert any(b["id"] == "nyos_pure" for b in summary["brands"])


def test_ws_mixing_summary_unconfigured():
    hass = FakeHass(entries=[])
    conn = FakeConnection()
    run(integration.websocket_mixing_summary(hass, conn, {"id": 2}))
    assert conn.errors and conn.errors[-1].code == "not_configured"


# ---------------------------------------------------------------- Stage B: the workflow runs
# Real orchestration in __init__.py against the fake HA: plug actuation, the
# fill-cap timer, stage advances, salinity logging, abort, orphan recovery and
# sim mode (the test_awc_safety technique — timers fired by hand).

from _fake_ha import install_scheduler  # noqa: E402

_STATION_SWITCHES = {
    "switch.mix_booster": "off", "switch.mix_pump_a": "off",
    "switch.mix_pump_b": "off", "switch.mix_heater": "off",
}


def _station_cfg(**over):
    cfg = _cfg()
    cfg["switches"] = {
        "rodiBooster": {"switchEntity": "switch.mix_booster"},
        "mixPumpA": {"switchEntity": "switch.mix_pump_a"},
        "mixPumpB": {"switchEntity": "switch.mix_pump_b"},
        "heater": {"switchEntity": "switch.mix_heater"},
    }
    cfg["rodi"] = {"rateLph": 0, "fillCapMin": 240}
    cfg.update(over)
    return cfg


def _station(cfg_over=None):
    cfg = _station_cfg(**(cfg_over or {}))
    entry = FakeEntry(options={CONF_SETTINGS: integration._normalise_core_config(
        {"mixingStation": cfg})})
    hass = FakeHass(states=dict(_STATION_SWITCHES), entries=[entry])
    return hass, entry


def _mix_state(entry):
    return integration._config_from_entry(entry)["mixingStation"]


def _switch_calls(hass, entity):
    # Under the HA stubs ATTR_ENTITY_ID is a stub object, not "entity_id" —
    # match by value the way _FakeServices itself does.
    return [(c.service, entity) for c in hass.services.calls
            if c.domain == "switch" and entity in c.data.values()]


def test_start_refused_while_busy_returns_reasons_not_an_error():
    hass, entry = _station({"batch": {"state": "salting", "type": "salt", "litres": 40}})
    conn = FakeConnection()
    run(integration.websocket_mixing_start_batch(
        hass, conn, {"id": 1, "litres": 40, "batch_type": "salt"}))
    payload = conn.results[-1].payload
    assert payload["success"] is False
    assert any("already in progress" in r for r in payload["reasons"])
    assert not hass.services.calls                      # nothing energised


def test_start_energises_the_booster_and_arms_the_cap():
    scheduler = install_scheduler(integration)
    hass, entry = _station()
    conn = FakeConnection()
    before = len(scheduler.scheduled)
    run(integration.websocket_mixing_start_batch(
        hass, conn, {"id": 1, "litres": 40, "batch_type": "salt"}))
    assert conn.results[-1].payload["success"] is True
    assert ("turn_on", "switch.mix_booster") in _switch_calls(hass, "switch.mix_booster")
    batch = _mix_state(entry)["batch"]
    assert batch["state"] == "filling" and batch["litres"] == 40.0
    # The cap timer is armed ~fillCapMin out (240 min) — find it among any
    # re-arms the save pass registered.
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc)
    caps = [r for r in scheduler.scheduled[before:]
            if not r["cancelled"] and 235 * 60 < (r["run_at"] - now).total_seconds() < 245 * 60]
    assert len(caps) == 1, "expected exactly one fill-cap timer"


def test_fill_cap_fires_booster_off_batch_stays_filling():
    scheduler = install_scheduler(integration)
    hass, entry = _station()
    conn = FakeConnection()
    before = len(scheduler.scheduled)
    run(integration.websocket_mixing_start_batch(
        hass, conn, {"id": 1, "litres": 40, "batch_type": "salt"}))
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc)
    cap = next(r for r in scheduler.scheduled[before:]
               if not r["cancelled"] and 235 * 60 < (r["run_at"] - now).total_seconds() < 245 * 60)

    async def _fire():
        await cap["callback"](cap["run_at"])
    run(_fire())
    assert ("turn_off", "switch.mix_booster") in _switch_calls(hass, "switch.mix_booster")
    assert _mix_state(entry)["batch"]["state"] == "filling"   # the user still confirms
    assert integration.MIXING_FILL_UNSUB not in hass.data.get(integration.DOMAIN, {})


def test_advance_walks_the_dual_heat_chain_and_moves_the_ledger():
    install_scheduler(integration)
    hass, entry = _station()
    conn = FakeConnection()
    run(integration.websocket_mixing_start_batch(
        hass, conn, {"id": 1, "litres": 40, "batch_type": "salt"}))
    # Fill done: booster off, RODI store credited (40 anchor + 40 fill, capped at 50).
    run(integration.websocket_mixing_advance(hass, conn, {"id": 2}))
    state = _mix_state(entry)
    assert state["batch"]["state"] == "transferring"
    assert ("turn_off", "switch.mix_booster") in _switch_calls(hass, "switch.mix_booster")
    assert state["vessels"]["rodi"]["estimatedLitres"] == 50.0
    # Transferred 38 L: anchor debited, heater on, stage heating.
    run(integration.websocket_mixing_advance(hass, conn, {"id": 3, "litres": 38}))
    state = _mix_state(entry)
    assert state["batch"]["state"] == "heating"
    assert state["vessels"]["rodi"]["estimatedLitres"] == 12.0
    assert ("turn_on", "switch.mix_heater") in _switch_calls(hass, "switch.mix_heater")
    # At temperature: both pumps on, stage salting.
    run(integration.websocket_mixing_advance(hass, conn, {"id": 4}))
    assert _mix_state(entry)["batch"]["state"] == "salting"
    assert ("turn_on", "switch.mix_pump_a") in _switch_calls(hass, "switch.mix_pump_a")
    assert ("turn_on", "switch.mix_pump_b") in _switch_calls(hass, "switch.mix_pump_b")


def test_log_salinity_low_stays_salting_with_real_correction():
    install_scheduler(integration)
    hass, entry = _station({"batch": {"state": "salting", "type": "salt", "litres": 40,
                                      "stageAt": _iso(NOW)}})
    conn = FakeConnection()
    run(integration.websocket_mixing_log_salinity(hass, conn, {"id": 1, "ppt": 33.0}))
    payload = conn.results[-1].payload
    assert payload["correction"]["status"] == "low"
    assert payload["correction"]["addGrams"] == round(2.0 / 35.0 * 39.0 * 40, 0)
    batch = _mix_state(entry)["batch"]
    assert batch["state"] == "salting" and batch["loggedPpt"] == 33.0


def test_log_salinity_pass_goes_ready_and_switches_everything_off():
    install_scheduler(integration)
    hass, entry = _station({"batch": {"state": "salting", "type": "salt", "litres": 40,
                                      "stageAt": _iso(NOW)}})
    conn = FakeConnection()
    run(integration.websocket_mixing_log_salinity(hass, conn, {"id": 1, "ppt": 35.2}))
    payload = conn.results[-1].payload
    assert payload["correction"]["status"] == "pass"
    assert payload["summary"]["batch"]["status"] == "ready"
    batch = _mix_state(entry)["batch"]
    assert batch["state"] == "ready" and batch["testedAt"]
    for entity in ("switch.mix_pump_a", "switch.mix_pump_b", "switch.mix_heater"):
        assert ("turn_off", entity) in _switch_calls(hass, entity)


def test_rodi_batch_goes_straight_from_fill_to_ready():
    install_scheduler(integration)
    hass, entry = _station()
    conn = FakeConnection()
    run(integration.websocket_mixing_start_batch(
        hass, conn, {"id": 1, "litres": 30, "batch_type": "rodi"}))
    run(integration.websocket_mixing_advance(hass, conn, {"id": 2}))
    batch = _mix_state(entry)["batch"]
    assert batch["state"] == "ready" and batch["type"] == "rodi"
    # No salt stages ⇒ pumps and heater were never ENERGISED (ready's
    # belt-and-braces stop pass may still turn them off).
    assert ("turn_on", "switch.mix_pump_a") not in _switch_calls(hass, "switch.mix_pump_a")
    assert ("turn_on", "switch.mix_heater") not in _switch_calls(hass, "switch.mix_heater")


def test_single_layout_skips_the_transfer():
    install_scheduler(integration)
    hass, entry = _station({"layout": "single"})
    conn = FakeConnection()
    run(integration.websocket_mixing_start_batch(
        hass, conn, {"id": 1, "litres": 40, "batch_type": "salt"}))
    run(integration.websocket_mixing_advance(hass, conn, {"id": 2}))
    assert _mix_state(entry)["batch"]["state"] == "heating"


def test_abort_switches_everything_off_and_resets():
    install_scheduler(integration)
    hass, entry = _station({"batch": {"state": "salting", "type": "salt", "litres": 40,
                                      "stageAt": _iso(NOW)}})
    conn = FakeConnection()
    run(integration.websocket_mixing_abort(hass, conn, {"id": 1}))
    batch = _mix_state(entry)["batch"]
    assert batch["state"] == "idle" and batch["litres"] == 0
    for entity in _STATION_SWITCHES:
        assert ("turn_off", entity) in _switch_calls(hass, entity)
    # Idle abort is an error, not a silent success.
    run(integration.websocket_mixing_abort(hass, conn, {"id": 2}))
    assert conn.errors and conn.errors[-1].code == "not_running"


def test_orphan_recovery_fill_stops_the_booster():
    install_scheduler(integration)
    hass, entry = _station({"batch": {"state": "filling", "type": "salt", "litres": 40,
                                      "stageAt": _iso(NOW)}})
    run(integration._async_mixing_recover_orphaned(hass, entry))
    assert ("turn_off", "switch.mix_booster") in _switch_calls(hass, "switch.mix_booster")
    assert _mix_state(entry)["batch"]["state"] == "filling"


def test_orphan_recovery_salting_restarts_pumps_never_the_heater():
    install_scheduler(integration)
    hass, entry = _station({"batch": {"state": "salting", "type": "salt", "litres": 40,
                                      "stageAt": _iso(NOW)}})
    run(integration._async_mixing_recover_orphaned(hass, entry))
    assert ("turn_on", "switch.mix_pump_a") in _switch_calls(hass, "switch.mix_pump_a")
    assert ("turn_on", "switch.mix_pump_b") in _switch_calls(hass, "switch.mix_pump_b")
    assert ("turn_off", "switch.mix_heater") in _switch_calls(hass, "switch.mix_heater")
    assert ("turn_on", "switch.mix_heater") not in _switch_calls(hass, "switch.mix_heater")


def test_sim_mode_never_touches_real_switches():
    install_scheduler(integration)
    hass, entry = _station({"simulate": True})
    conn = FakeConnection()
    run(integration.websocket_mixing_start_batch(
        hass, conn, {"id": 1, "litres": 40, "batch_type": "salt"}))
    assert conn.results[-1].payload["success"] is True
    # No switch-domain calls at all (the save pass may touch notifications).
    assert not [c for c in hass.services.calls if c.domain == "switch"]
    sim = hass.data[integration.DOMAIN][integration.MIXING_RUNTIME]["simSwitches"]
    assert sim["rodiBooster"] is True


# ---------------------------------------------------------------- Stage C: storing & the ledger
# Circulation chain (stamps ARE the schedule), mark-used, level corrections,
# retests on stored batches, the reminder bridge, mid-burst orphan recovery.

def _stored_batch(**over):
    batch = {"state": "storing", "type": "salt", "litres": 40, "usedLitres": 0,
             "stageAt": _iso(NOW), "testedAt": _iso(NOW),
             "circulateUntil": "", "nextCirculateAt": "", "lastCirculatedAt": ""}
    batch.update(over)
    return batch


def test_engine_circulating_follows_the_stamp():
    cfg = _cfg()
    batch = _stored_batch(circulateUntil=_iso(NOW + timedelta(minutes=5)))
    assert mixing.batch_state(batch, cfg, NOW)["circulating"] is True
    batch["circulateUntil"] = _iso(NOW - timedelta(minutes=5))
    assert mixing.batch_state(batch, cfg, NOW)["circulating"] is False


def test_pass_from_salting_stamps_the_circulation_cadence():
    install_scheduler(integration)
    hass, entry = _station({"batch": {"state": "salting", "type": "salt", "litres": 40,
                                      "stageAt": _iso(NOW)}})
    conn = FakeConnection()
    run(integration.websocket_mixing_log_salinity(hass, conn, {"id": 1, "ppt": 35.0}))
    batch = _mix_state(entry)["batch"]
    from datetime import datetime as _dt, timezone as _tz
    next_at = _dt.fromisoformat(batch["nextCirculateAt"])
    hours_out = (next_at - _dt.now(_tz.utc)).total_seconds() / 3600.0
    assert 5.9 < hours_out < 6.1                     # storage.circulateEveryH = 6


def test_circulation_chain_burst_starts_stops_and_rearms():
    from datetime import datetime as _dt, timezone as _tz
    scheduler = install_scheduler(integration)
    now = _dt.now(_tz.utc)
    hass, entry = _station({"batch": _stored_batch(
        nextCirculateAt=(now + timedelta(hours=1)).isoformat())})

    async def _arm():
        await integration._async_schedule_mixing_circulation(
            hass, entry, integration._config_from_entry(entry))
    run(_arm())
    start = next(r for r in scheduler.scheduled if not r["cancelled"])

    async def _fire(record):
        await record["callback"](record["run_at"])
    before = len(scheduler.scheduled)
    run(_fire(start))
    # Burst started: pumps on, ready→storing edge stamped, stop leg armed by the save.
    assert ("turn_on", "switch.mix_pump_a") in _switch_calls(hass, "switch.mix_pump_a")
    batch = _mix_state(entry)["batch"]
    assert batch["state"] == "storing" and batch["circulateUntil"]
    assert batch["nextCirculateAt"] == ""
    stop = next(r for r in scheduler.scheduled[before:]
                if not r["cancelled"] and 9 * 60 < (r["run_at"] - _dt.now(_tz.utc)).total_seconds() < 11 * 60)
    run(_fire(stop))
    # Burst stopped: pumps off, cadence re-anchored, last-stir stamped.
    assert ("turn_off", "switch.mix_pump_a") in _switch_calls(hass, "switch.mix_pump_a")
    batch = _mix_state(entry)["batch"]
    assert batch["circulateUntil"] == "" and batch["lastCirculatedAt"]
    hours_out = (_dt.fromisoformat(batch["nextCirculateAt"]) - _dt.now(_tz.utc)).total_seconds() / 3600.0
    assert 5.9 < hours_out < 6.1


def test_rodi_batches_never_circulate():
    install_scheduler(integration)
    hass, entry = _station({"batch": _stored_batch(
        type="rodi", nextCirculateAt=_iso(NOW + timedelta(hours=1)))})

    async def _arm():
        await integration._async_schedule_mixing_circulation(
            hass, entry, integration._config_from_entry(entry))
    run(_arm())
    assert integration.MIXING_CIRC_UNSUB not in hass.data.get(integration.DOMAIN, {})


def test_mark_used_debits_then_closes_the_batch():
    install_scheduler(integration)
    hass, entry = _station({"batch": _stored_batch()})
    conn = FakeConnection()
    run(integration.websocket_mixing_mark_used(hass, conn, {"id": 1, "litres": 15}))
    batch = _mix_state(entry)["batch"]
    assert batch["state"] == "storing" and batch["usedLitres"] == 15.0
    run(integration.websocket_mixing_mark_used(hass, conn, {"id": 2, "litres": 25}))
    batch = _mix_state(entry)["batch"]
    assert batch["state"] == "idle" and batch["litres"] == 0
    # Drawing from an empty station is an error, not a silent success.
    run(integration.websocket_mixing_mark_used(hass, conn, {"id": 3, "litres": 5}))
    assert conn.errors and conn.errors[-1].code == "invalid_state"


def test_set_level_corrects_both_vessels_honestly():
    install_scheduler(integration)
    hass, entry = _station({"batch": _stored_batch()})
    conn = FakeConnection()
    run(integration.websocket_mixing_set_level(
        hass, conn, {"id": 1, "vessel": "rodi", "litres": 200}))   # clamps to the vessel
    assert _mix_state(entry)["vessels"]["rodi"]["estimatedLitres"] == 50.0
    run(integration.websocket_mixing_set_level(
        hass, conn, {"id": 2, "vessel": "mix", "litres": 25}))
    assert _mix_state(entry)["batch"]["usedLitres"] == 15.0        # 40 total − 25 left
    # No batch ⇒ nothing in the mix vessel to correct.
    hass2, entry2 = _station()
    conn2 = FakeConnection()
    run(integration.websocket_mixing_set_level(
        hass2, conn2, {"id": 3, "vessel": "mix", "litres": 10}))
    assert conn2.errors[-1].code == "invalid_state"
    # A single-vessel layout has no RODI store to correct.
    hass3, entry3 = _station({"layout": "single"})
    conn3 = FakeConnection()
    run(integration.websocket_mixing_set_level(
        hass3, conn3, {"id": 4, "vessel": "rodi", "litres": 10}))
    assert conn3.errors[-1].code == "invalid_vessel"


def test_retest_pass_refreshes_stay_stored_fail_returns_to_the_pumps():
    install_scheduler(integration)
    hass, entry = _station({"batch": _stored_batch(
        testedAt=_iso(NOW - timedelta(days=8)),
        nextCirculateAt=_iso(NOW + timedelta(hours=2)))})
    conn = FakeConnection()
    run(integration.websocket_mixing_log_salinity(hass, conn, {"id": 1, "ppt": 35.1}))
    batch = _mix_state(entry)["batch"]
    assert batch["state"] == "storing"
    assert batch["testedAt"] != _iso(NOW - timedelta(days=8))     # clock refreshed
    # Drifted high: back onto the pumps, circulation stamps cleared.
    run(integration.websocket_mixing_log_salinity(hass, conn, {"id": 2, "ppt": 37.5}))
    payload = conn.results[-1].payload
    assert payload["correction"]["status"] == "high"
    batch = _mix_state(entry)["batch"]
    assert batch["state"] == "salting" and batch["nextCirculateAt"] == ""
    assert ("turn_on", "switch.mix_pump_a") in _switch_calls(hass, "switch.mix_pump_a")


def test_reminder_bridge_never_conjures_and_serves_the_keepers_task():
    install_scheduler(integration)
    # No task added ⇒ a test must not create one.
    hass, entry = _station({"batch": {"state": "salting", "type": "salt", "litres": 40,
                                      "stageAt": _iso(NOW)}})
    conn = FakeConnection()
    run(integration.websocket_mixing_log_salinity(hass, conn, {"id": 1, "ppt": 35.0}))
    config = integration._config_from_entry(entry)
    assert "mixing_retest" not in config["maintenance"]["tasks"]
    # Keeper-added task: a test logs a completion and re-times the cadence.
    cfg_over = {"batch": {"state": "salting", "type": "salt", "litres": 40,
                          "stageAt": _iso(NOW)},
                "storage": {"circulateEveryH": 6, "circulateForMin": 10,
                            "retestAfterDays": 5}}
    cfg = _station_cfg(**cfg_over)
    entry2 = FakeEntry(options={CONF_SETTINGS: integration._normalise_core_config({
        "mixingStation": cfg,
        "maintenance": {"tasks": {"mixing_retest": {
            "label": "Retest stored saltwater", "cadenceDays": 7,
            "criticalAfterDays": 14, "enabled": True, "notify": True}}},
    })})
    hass2 = FakeHass(states=dict(_STATION_SWITCHES), entries=[entry2])
    conn2 = FakeConnection()
    run(integration.websocket_mixing_log_salinity(hass2, conn2, {"id": 1, "ppt": 35.0}))
    config2 = integration._config_from_entry(entry2)
    task = config2["maintenance"]["tasks"]["mixing_retest"]
    assert task["cadenceDays"] == 5 and task["enabled"] is True
    completions = config2["maintenance"]["completions"]["mixing_retest"]
    assert completions and completions[0]["source"] == "mixing"
    # Batch gone ⇒ the chore stands down instead of nagging an empty vessel.
    run(integration.websocket_mixing_abort(hass2, conn2, {"id": 2}))
    config2 = integration._config_from_entry(entry2)
    assert config2["maintenance"]["tasks"]["mixing_retest"]["enabled"] is False


def test_orphan_recovery_mid_burst_stops_pumps_and_reanchors():
    install_scheduler(integration)
    hass, entry = _station({"batch": _stored_batch(
        circulateUntil=_iso(NOW + timedelta(minutes=5)))})
    run(integration._async_mixing_recover_orphaned(hass, entry))
    assert ("turn_off", "switch.mix_pump_a") in _switch_calls(hass, "switch.mix_pump_a")
    batch = _mix_state(entry)["batch"]
    assert batch["circulateUntil"] == "" and batch["nextCirculateAt"]


# ---------------------------------------------------------------- Stage D: the Trust Moat
# AWC asks the mixing station before it runs; a completed change draws from
# the batch ledger. Engine verdicts + the real _async_awc_start seam.

def test_awc_guard_reason_verdicts():
    now = NOW
    # Unhooked or irrelevant ⇒ silence.
    cfg = _cfg(enabled=False)
    assert mixing.awc_guard_reason(cfg, 10, now) is None
    cfg = _cfg(integrations={"awcGuard": "off"})
    assert mixing.awc_guard_reason(cfg, 10, now) is None
    assert mixing.awc_guard_reason(_cfg(), 0, now) is None
    # No batch ⇒ the configured mode speaks.
    cfg = _cfg(integrations={"awcGuard": "warn"})
    verdict = mixing.awc_guard_reason(cfg, 10, now)
    assert verdict["mode"] == "warn" and "no ready saltwater batch" in verdict["message"]
    cfg["integrations"]["awcGuard"] = "block"
    assert mixing.awc_guard_reason(cfg, 10, now)["mode"] == "block"
    # A RODI batch is not saltwater.
    cfg["batch"] = {"state": "ready", "type": "rodi", "litres": 40, "usedLitres": 0,
                    "testedAt": _iso(now)}
    assert mixing.awc_guard_reason(cfg, 10, now) is not None
    # Aged past the retest window ⇒ not vouched.
    cfg["batch"] = {"state": "storing", "type": "salt", "litres": 40, "usedLitres": 0,
                    "testedAt": _iso(now - timedelta(days=9))}
    assert "retest window" in mixing.awc_guard_reason(cfg, 10, now)["message"]
    # Not enough left ⇒ says how short.
    cfg["batch"] = {"state": "storing", "type": "salt", "litres": 40, "usedLitres": 35,
                    "testedAt": _iso(now)}
    assert "only 5 L" in mixing.awc_guard_reason(cfg, 10, now)["message"]
    # Tested, in date, sufficient ⇒ vouched.
    cfg["batch"]["usedLitres"] = 0
    assert mixing.awc_guard_reason(cfg, 10, now) is None


_AWC_SENSORS = {
    "binary_sensor.high": "off", "binary_sensor.leak": "off",
    "binary_sensor.fresh_empty": "off", "binary_sensor.waste_full": "off",
}


def _awc_station_entry(guard="block", batch=None):
    """An entry where the AWC could genuinely start — calibrated pumps, stocked
    reservoir, safety sensors bound — so the ONLY thing standing in its way is
    the mixing-station guard under test."""
    awc = {
        "enabled": True,
        "tankVolumeLitres": 200,
        "pumps": {
            "drain": {"switchEntity": "switch.awc_drain", "mlPerS": 100},
            "fill": {"switchEntity": "switch.awc_fill", "mlPerS": 100},
        },
        "reservoirs": {
            "fresh": {"capacityLitres": 25, "remainingMl": 25000,
                      "emptyEntity": "binary_sensor.fresh_empty"},
            "waste": {"capacityLitres": 25, "filledMl": 0,
                      "fullEntity": "binary_sensor.waste_full"},
        },
        "safety": {"highLevelEntity": "binary_sensor.high",
                   "leakEntity": "binary_sensor.leak", "maxSingleChangePercent": 25},
        "schedule": {"method": "batch_sequential"},
    }
    mix_cfg = _station_cfg(integrations={"awcGuard": guard, "atoFromRodi": False})
    if batch is not None:
        mix_cfg["batch"] = batch
    entry = FakeEntry(options={CONF_SETTINGS: integration._normalise_core_config(
        {"automaticWaterChange": awc, "mixingStation": mix_cfg})})
    states = dict(_STATION_SWITCHES)
    states.update(_AWC_SENSORS)
    states.update({"switch.awc_drain": "off", "switch.awc_fill": "off"})
    return FakeHass(states=states, entries=[entry]), entry


def test_awc_block_guard_refuses_without_a_tested_batch():
    install_scheduler(integration)
    hass, entry = _awc_station_entry(guard="block")
    started, reasons = run(integration._async_awc_start(
        hass, entry, 10, "batch_sequential", True, None))
    assert started is False
    assert any(r.get("code") == "mixing_batch" for r in reasons)
    # Nothing energised on a refusal.
    assert not [c for c in hass.services.calls if c.domain == "switch"]


def test_awc_block_guard_stands_aside_for_a_vouched_batch():
    install_scheduler(integration)
    hass, entry = _awc_station_entry(guard="block", batch=_stored_batch())
    started, reasons = run(integration._async_awc_start(
        hass, entry, 10, "batch_sequential", True, None))
    assert started is True and not reasons


def test_awc_warn_guard_lets_it_run_but_says_so():
    install_scheduler(integration)
    hass, entry = _awc_station_entry(guard="warn")
    started, reasons = run(integration._async_awc_start(
        hass, entry, 10, "batch_sequential", True, None))
    assert started is True and not reasons
    activity = integration._config_from_entry(entry)["activity"]
    assert any("without the mixing station's blessing" in a.get("message", "")
               for a in activity)


def test_awc_guard_off_is_silent():
    install_scheduler(integration)
    hass, entry = _awc_station_entry(guard="off")
    started, _reasons = run(integration._async_awc_start(
        hass, entry, 10, "batch_sequential", True, None))
    assert started is True
    activity = integration._config_from_entry(entry)["activity"]
    assert not any("mixing station" in a.get("message", "").lower() for a in activity)


def test_debit_helper_draws_down_and_closes_only_when_coupled():
    install_scheduler(integration)
    # Coupled + live batch: partial debit, then exhaustion closes the batch.
    hass, entry = _station({"batch": _stored_batch(),
                            "integrations": {"awcGuard": "warn", "atoFromRodi": False}})
    config = integration._config_from_entry(entry)
    integration._mixing_debit_batch(hass, config, 15, "the water change")
    assert config["mixingStation"]["batch"]["usedLitres"] == 15.0
    integration._mixing_debit_batch(hass, config, 30, "the water change")
    assert config["mixingStation"]["batch"]["state"] == "idle"
    # Uncoupled (guard off): the ledger must NOT phantom-drain.
    hass2, entry2 = _station({"batch": _stored_batch(),
                              "integrations": {"awcGuard": "off", "atoFromRodi": False}})
    config2 = integration._config_from_entry(entry2)
    integration._mixing_debit_batch(hass2, config2, 15, "the water change")
    assert config2["mixingStation"]["batch"]["usedLitres"] == 0.0


# ---------------------------------------------------------------- Stage E: the RODI utility
# Draws outside a batch (store top-up or the external T-off), the timed-run
# flow calibration, and the filter-litres ledger — 0.7.88.


def test_draw_guards_demand_rate_booster_and_room():
    # No rate, no bound booster: both refusals, honestly worded.
    cfg = _cfg(rodi={"rateLph": 0, "fillCapMin": 240})
    reasons = mixing.draw_guard_reasons(cfg, 10, "store")
    assert any("flow rate is unknown" in r for r in reasons)
    assert any("booster plug" in r for r in reasons)
    # Simulate + a rate: a store draw that fits passes clean...
    cfg = _cfg(simulate=True, rodi={"rateLph": 120, "fillCapMin": 240})
    assert mixing.draw_guard_reasons(cfg, 10, "store") == []
    # ...but the store only has 10 L free (40 of 50) — 20 L overflows.
    assert any("overflow" in r for r in mixing.draw_guard_reasons(cfg, 20, "store"))
    # Single layout has no store — external is the only draw destination.
    single = _cfg(simulate=True, layout="single", rodi={"rateLph": 120, "fillCapMin": 240})
    assert any("RODI-only batch" in r for r in mixing.draw_guard_reasons(single, 10, "store"))
    assert mixing.draw_guard_reasons(single, 10, "external") == []


def test_draw_guards_respect_the_busy_booster():
    filling = _cfg(simulate=True, rodi={"rateLph": 120, "fillCapMin": 240},
                   batch={"state": "filling", "type": "salt", "litres": 40})
    assert any("batch fill is using the booster" in r
               for r in mixing.draw_guard_reasons(filling, 5, "external"))
    drawing = _cfg(simulate=True, rodi={
        "rateLph": 120, "fillCapMin": 240,
        "draw": {"active": True, "litres": 10, "destination": "store",
                 "startedAt": _iso(NOW), "endsAt": _iso(NOW + timedelta(minutes=5))}})
    assert any("already running" in r
               for r in mixing.draw_guard_reasons(drawing, 5, "external"))
    # And a batch must not start over a live draw either.
    assert any("RODI draw is running" in r
               for r in mixing.start_guard_reasons(drawing, 40, "salt"))


def test_rodi_status_reads_the_draw_clock_pro_rata():
    cfg = _cfg(rodi={
        "rateLph": 120, "fillCapMin": 240,
        "draw": {"active": True, "litres": 10, "destination": "external",
                 "startedAt": _iso(NOW - timedelta(minutes=2, seconds=30)),
                 "endsAt": _iso(NOW + timedelta(minutes=2, seconds=30))}})
    status = mixing.rodi_status(cfg, NOW)
    assert status["draw"]["litresDone"] == 5.0
    assert status["draw"]["percent"] == 50.0
    assert status["draw"]["minutesLeft"] in (2.0, 3.0)   # 2.5 min, rounded whole
    assert status["draw"]["destination"] == "external"


def test_calibration_rate_maths_refuses_noise():
    assert mixing.calibration_rate(2.5, 600) == 15.0      # 2.5 L in 10 min
    assert mixing.calibration_rate(1.0, 30) == 0.0        # under a minute = noise
    assert mixing.calibration_rate(0, 600) == 0.0         # nothing measured


def test_filter_ledger_flags_due_only_when_rated():
    due = mixing.rodi_status(_cfg(rodi={
        "rateLph": 0, "fillCapMin": 240,
        "litresProcessed": 1500, "filterRatedL": 1500}), NOW)
    assert due["filterDue"] is True
    untracked = mixing.rodi_status(_cfg(rodi={
        "rateLph": 0, "fillCapMin": 240,
        "litresProcessed": 99999, "filterRatedL": 0}), NOW)
    assert untracked["filterDue"] is False


def _rodi_over(**extra):
    base = {"rateLph": 120, "fillCapMin": 240}
    base.update(extra)
    return {"rodi": base}


def test_rodi_draw_runs_the_booster_and_the_stop_leg_finishes_it():
    scheduler = install_scheduler(integration)
    hass, entry = _station(_rodi_over())
    conn = FakeConnection()
    before = len(scheduler.scheduled)
    run(integration.websocket_mixing_rodi_draw(
        hass, conn, {"id": 1, "litres": 10, "destination": "store"}))
    assert conn.results[-1].payload["success"] is True
    assert ("turn_on", "switch.mix_booster") in _switch_calls(hass, "switch.mix_booster")
    rodi = _mix_state(entry)["rodi"]
    assert rodi["draw"]["active"] is True and rodi["draw"]["litres"] == 10.0
    # 10 L at 120 L/h = 5 min: the save pass armed exactly one stop leg there.
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc)
    stops = [r for r in scheduler.scheduled[before:]
             if not r["cancelled"] and 4 * 60 < (r["run_at"] - now).total_seconds() < 6 * 60]
    assert len(stops) == 1, "expected exactly one draw stop leg"

    async def _fire():
        await stops[0]["callback"](stops[0]["run_at"])
    run(_fire())
    state = _mix_state(entry)
    assert ("turn_off", "switch.mix_booster") in _switch_calls(hass, "switch.mix_booster")
    assert state["rodi"]["draw"]["active"] is False
    assert state["vessels"]["rodi"]["estimatedLitres"] == 50.0    # 40 anchor + 10 drawn
    assert state["rodi"]["litresProcessed"] == 10.0
    assert integration.MIXING_RODI_UNSUB not in hass.data.get(integration.DOMAIN, {})


def test_rodi_draw_external_taps_the_t_never_the_store():
    scheduler = install_scheduler(integration)
    hass, entry = _station(_rodi_over())
    conn = FakeConnection()
    before = len(scheduler.scheduled)
    run(integration.websocket_mixing_rodi_draw(
        hass, conn, {"id": 1, "litres": 20, "destination": "external"}))
    assert conn.results[-1].payload["success"] is True
    stop = next(r for r in scheduler.scheduled[before:] if not r["cancelled"])

    async def _fire():
        await stop["callback"](stop["run_at"])
    run(_fire())
    state = _mix_state(entry)
    assert state["vessels"]["rodi"]["estimatedLitres"] == 40.0    # the anchor never moved
    assert state["rodi"]["litresProcessed"] == 20.0               # the membrane still counted


def test_rodi_draw_refused_without_a_rate_and_summary_carries_the_status():
    install_scheduler(integration)
    hass, entry = _station()                                       # rateLph 0
    conn = FakeConnection()
    run(integration.websocket_mixing_rodi_draw(
        hass, conn, {"id": 1, "litres": 10, "destination": "store"}))
    payload = conn.results[-1].payload
    assert payload["success"] is False
    assert any("flow rate is unknown" in r for r in payload["reasons"])
    assert not hass.services.calls
    # The summary blob now carries the rodi block the panel renders from.
    run(integration.websocket_mixing_summary(hass, conn, {"id": 2}))
    summary = conn.results[-1].payload["summary"]
    assert summary["rodi"]["rateLph"] == 0.0 and summary["rodi"]["draw"] is None


def test_rodi_stop_credits_only_what_ran():
    install_scheduler(integration)
    started = datetime.now(timezone.utc) - timedelta(minutes=3)
    hass, entry = _station(_rodi_over(rateLph=100, draw={
        "active": True, "litres": 20, "destination": "store",
        "startedAt": _iso(started), "endsAt": _iso(started + timedelta(minutes=12))}))
    conn = FakeConnection()
    run(integration.websocket_mixing_rodi_stop(hass, conn, {"id": 1}))
    assert conn.results[-1].payload["success"] is True
    state = _mix_state(entry)
    assert state["rodi"]["draw"]["active"] is False
    assert state["vessels"]["rodi"]["estimatedLitres"] == 45.0     # 40 + 3 min at 100 L/h
    assert state["rodi"]["litresProcessed"] == 5.0
    assert ("turn_off", "switch.mix_booster") in _switch_calls(hass, "switch.mix_booster")


def test_calibrate_start_arms_the_cap_and_finish_sets_the_rate():
    scheduler = install_scheduler(integration)
    hass, entry = _station()
    conn = FakeConnection()
    before = len(scheduler.scheduled)
    run(integration.websocket_mixing_calibrate(hass, conn, {"id": 1, "action": "start"}))
    assert conn.results[-1].payload["success"] is True
    assert ("turn_on", "switch.mix_booster") in _switch_calls(hass, "switch.mix_booster")
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc)
    caps = [r for r in scheduler.scheduled[before:]
            if not r["cancelled"] and 29 * 60 < (r["run_at"] - now).total_seconds() < 31 * 60]
    assert len(caps) == 1, "expected exactly one calibration cap leg"
    # A separate station whose run started 10 minutes ago finishes with 20 L.
    started = datetime.now(timezone.utc) - timedelta(minutes=10)
    hass2, entry2 = _station(_rodi_over(
        rateLph=0, calibration={"active": True, "startedAt": _iso(started)}))
    conn2 = FakeConnection()
    run(integration.websocket_mixing_calibrate(
        hass2, conn2, {"id": 2, "action": "finish", "litres": 20}))
    assert conn2.results[-1].payload["success"] is True
    rodi = _mix_state(entry2)["rodi"]
    assert rodi["rateLph"] == 120.0 and rodi["calibratedAt"]
    assert rodi["calibration"]["active"] is False
    assert rodi["litresProcessed"] == 20.0
    assert ("turn_off", "switch.mix_booster") in _switch_calls(hass2, "switch.mix_booster")


def test_calibrate_finish_too_short_keeps_the_old_rate():
    install_scheduler(integration)
    started = datetime.now(timezone.utc) - timedelta(seconds=20)
    hass, entry = _station(_rodi_over(
        rateLph=80, calibration={"active": True, "startedAt": _iso(started)}))
    conn = FakeConnection()
    run(integration.websocket_mixing_calibrate(
        hass, conn, {"id": 1, "action": "finish", "litres": 5}))
    payload = conn.results[-1].payload
    assert payload["success"] is False
    assert any("at least" in r for r in payload["reasons"])
    rodi = _mix_state(entry)["rodi"]
    assert rodi["rateLph"] == 80.0 and rodi["calibration"]["active"] is False
    assert ("turn_off", "switch.mix_booster") in _switch_calls(hass, "switch.mix_booster")


def test_calibration_cap_cancels_a_forgotten_run():
    scheduler = install_scheduler(integration)
    hass, entry = _station()
    conn = FakeConnection()
    before = len(scheduler.scheduled)
    run(integration.websocket_mixing_calibrate(hass, conn, {"id": 1, "action": "start"}))
    cap = next(r for r in scheduler.scheduled[before:] if not r["cancelled"])

    async def _fire():
        await cap["callback"](cap["run_at"])
    run(_fire())
    rodi = _mix_state(entry)["rodi"]
    assert rodi["calibration"]["active"] is False
    assert rodi["rateLph"] == 0.0                                  # rate untouched
    assert ("turn_off", "switch.mix_booster") in _switch_calls(hass, "switch.mix_booster")


def test_filters_changed_resets_the_counter():
    install_scheduler(integration)
    hass, entry = _station(_rodi_over(litresProcessed=1234.5, filterRatedL=1500))
    conn = FakeConnection()
    run(integration.websocket_mixing_filters_changed(hass, conn, {"id": 1}))
    rodi = _mix_state(entry)["rodi"]
    assert rodi["litresProcessed"] == 0.0 and rodi["filterChangedAt"]
    assert rodi["filterRatedL"] == 1500.0                          # the rating survives


def test_fill_confirm_feeds_the_filter_ledger():
    install_scheduler(integration)
    hass, entry = _station()
    conn = FakeConnection()
    run(integration.websocket_mixing_start_batch(
        hass, conn, {"id": 1, "litres": 40, "batch_type": "salt"}))
    run(integration.websocket_mixing_advance(hass, conn, {"id": 2}))
    assert _mix_state(entry)["rodi"]["litresProcessed"] == 40.0


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok  {name}")
            except AssertionError as err:
                failures += 1
                print(f"FAIL  {name}: {err}")
    raise SystemExit(1 if failures else 0)
