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

def test_stage_sequence_is_the_mix_run_only():
    # Fill and Transfer are their own processes now (doc §15) — never stages.
    assert mixing.stage_sequence(True) == ("heating", "salting", "ready", "storing")
    assert mixing.stage_sequence(False) == ("salting", "ready", "storing")


def test_vessel_ledger_reads():
    cfg = _cfg()
    assert mixing.mix_contents(cfg) == "empty"
    assert mixing.mix_vessel_litres(cfg) == 0.0
    cfg["vessels"]["mix"].update({"estimatedLitres": 70, "contents": "rodi"})
    assert mixing.mix_contents(cfg) == "rodi"
    assert mixing.mix_vessel_litres(cfg) == 50.0        # clamped by the vessel


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
    cfg["vessels"]["mix"].update({"estimatedLitres": 40, "contents": "salt"})
    batch = dict(cfg["batch"], state="storing", litres=50,
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


# ---------------------------------------------------------------- level ledger

def test_vessel_levels_each_vessel_owns_its_anchor():
    cfg = _cfg()
    cfg["vessels"]["mix"].update({"estimatedLitres": 30, "contents": "salt"})
    levels = mixing.vessel_levels(cfg)
    assert levels["rodi"]["litres"] == 40.0 and levels["rodi"]["percent"] == 80
    assert levels["mix"]["litres"] == 30.0 and levels["mix"]["estimated"] is True
    assert levels["mix"]["contents"] == "salt"


def test_vessel_levels_anchors_clamp_to_volume():
    cfg = _cfg()
    cfg["vessels"]["rodi"]["estimatedLitres"] = 500   # junk above the vessel
    levels = mixing.vessel_levels(cfg)
    assert levels["mix"]["litres"] == 0.0 and levels["mix"]["contents"] == "empty"
    assert levels["rodi"]["litres"] == 50.0           # clamped to the vessel


def test_vessel_levels_single_layout_has_no_rodi_store():
    cfg = _cfg(layout="single")
    assert "rodi" not in mixing.vessel_levels(cfg)


# ---------------------------------------------------------------- guards

def test_mix_guards_want_rodi_water_and_an_idle_run():
    cfg = _cfg(enabled=False)
    text = " ".join(mixing.mix_guard_reasons(cfg))
    assert "not enabled" in text and "no RODI water" in text
    # RODI water on hand and everything idle ⇒ clear to mix.
    cfg = _cfg()
    cfg["vessels"]["mix"].update({"estimatedLitres": 40, "contents": "rodi"})
    assert mixing.mix_guard_reasons(cfg) == []
    # A run in flight refuses. Standing saltwater with no run behind it does
    # NOT (doc §32): a topped-up or unfinished batch is salted back.
    cfg["batch"]["state"] = "salting"
    assert any("already going" in r for r in mixing.mix_guard_reasons(cfg))
    cfg["batch"]["state"] = "idle"
    cfg["vessels"]["mix"]["contents"] = "salt"
    assert mixing.mix_guard_reasons(cfg) == []
    # A vessel still filling from the RODI unit refuses too.
    cfg["vessels"]["mix"]["contents"] = "rodi"
    cfg["rodi"] = {"draw": {"active": True, "destination": "mix",
                            "litres": 0, "startedAt": _iso(NOW), "endsAt": ""}}
    assert any("still filling" in r for r in mixing.mix_guard_reasons(cfg))


def test_transfer_guards_block_standing_saltwater_except_dilution():
    cfg = _cfg()
    assert mixing.transfer_guard_reasons(cfg, 20) == []
    # Saltwater standing in the vessel: blocked...
    cfg["vessels"]["mix"].update({"estimatedLitres": 30, "contents": "salt"})
    cfg["batch"]["state"] = "storing"
    assert any("still holds mixed saltwater" in r
               for r in mixing.transfer_guard_reasons(cfg, 10))
    # ...EXCEPT while salting — that is how a hot batch gets diluted.
    cfg["batch"]["state"] = "salting"
    assert mixing.transfer_guard_reasons(cfg, 10) == []
    # Overflow refuses with the free litres named.
    assert any("overflow" in r for r in mixing.transfer_guard_reasons(cfg, 30))
    # Single layout has no store to pour from.
    single = _cfg(layout="single")
    assert any("no store" in r for r in mixing.transfer_guard_reasons(single, 10))


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
    # Legacy migration (schema ≤ 56): the pipeline batch seeds the vessel ledger.
    assert mix_cfg["vessels"]["mix"]["estimatedLitres"] == 40.0
    assert mix_cfg["vessels"]["mix"]["contents"] == "salt"


def test_normalise_folds_legacy_pipeline_and_rodi_batches():
    # A legacy rodi-type stored "batch" is plain water on hand, not a run.
    config = integration._normalise_core_config({"mixingStation": {
        "batch": {"state": "storing", "type": "rodi", "litres": 30, "usedLitres": 5},
    }})
    mix_cfg = config["mixingStation"]
    assert mix_cfg["batch"]["state"] == "idle"
    assert mix_cfg["vessels"]["mix"]["estimatedLitres"] == 25.0
    assert mix_cfg["vessels"]["mix"]["contents"] == "rodi"
    # Legacy in-flight fill/transfer states are not runs any more.
    config2 = integration._normalise_core_config({"mixingStation": {
        "batch": {"state": "filling", "type": "salt", "litres": 40},
    }})
    assert config2["mixingStation"]["batch"]["state"] == "idle"


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


def test_start_mix_refused_while_busy_returns_reasons_not_an_error():
    hass, entry = _station({"batch": {"state": "salting", "type": "salt", "litres": 40}})
    conn = FakeConnection()
    run(integration.websocket_mixing_start_mix(hass, conn, {"id": 1}))
    payload = conn.results[-1].payload
    assert payload["success"] is False
    assert any("already going" in r for r in payload["reasons"])
    assert not hass.services.calls                      # nothing energised


def test_open_ended_fill_runs_to_the_float_valve():
    # No rate configured — the float valve is the stop, "Fill done" the witness.
    scheduler = install_scheduler(integration)
    hass, entry = _station()
    conn = FakeConnection()
    before = len(scheduler.scheduled)
    run(integration.websocket_mixing_rodi_draw(
        hass, conn, {"id": 1, "litres": 0, "destination": "store"}))
    assert conn.results[-1].payload["success"] is True
    assert ("turn_on", "switch.mix_booster") in _switch_calls(hass, "switch.mix_booster")
    assert _mix_state(entry)["rodi"]["draw"]["active"] is True
    # The fill cap (240 min) is armed as the backstop.
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc)
    caps = [r for r in scheduler.scheduled[before:]
            if not r["cancelled"] and 235 * 60 < (r["run_at"] - now).total_seconds() < 245 * 60]
    assert len(caps) == 1, "expected exactly one fill-cap backstop"
    # Keeper confirms: booster off, store reads full (float valve), draw closed.
    run(integration.websocket_mixing_rodi_stop(hass, conn, {"id": 2}))
    state = _mix_state(entry)
    assert ("turn_off", "switch.mix_booster") in _switch_calls(hass, "switch.mix_booster")
    assert state["rodi"]["draw"]["active"] is False
    assert state["vessels"]["rodi"]["estimatedLitres"] == 50.0     # full at the valve


def test_open_ended_fill_cap_credits_nothing_blind():
    scheduler = install_scheduler(integration)
    hass, entry = _station()
    conn = FakeConnection()
    before = len(scheduler.scheduled)
    run(integration.websocket_mixing_rodi_draw(
        hass, conn, {"id": 1, "litres": 0, "destination": "store"}))
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc)
    cap = next(r for r in scheduler.scheduled[before:]
               if not r["cancelled"] and 235 * 60 < (r["run_at"] - now).total_seconds() < 245 * 60)

    async def _fire():
        await cap["callback"](cap["run_at"])
    run(_fire())
    state = _mix_state(entry)
    assert ("turn_off", "switch.mix_booster") in _switch_calls(hass, "switch.mix_booster")
    assert state["rodi"]["draw"]["active"] is False
    # No rate, no confirmation ⇒ no invented litres.
    assert state["vessels"]["rodi"]["estimatedLitres"] == 40.0


def test_the_independent_processes_chain_into_a_batch():
    # Fill store → transfer → start mix → at temperature → salting: each step
    # its own command, the vessel ledger the thread between them.
    install_scheduler(integration)
    hass, entry = _station()
    conn = FakeConnection()
    run(integration.websocket_mixing_rodi_draw(
        hass, conn, {"id": 1, "litres": 0, "destination": "store"}))
    run(integration.websocket_mixing_rodi_stop(hass, conn, {"id": 2}))
    assert _mix_state(entry)["vessels"]["rodi"]["estimatedLitres"] == 50.0
    # Gravity transfer logged: store debited, vessel holds RODI water.
    run(integration.websocket_mixing_transfer(hass, conn, {"id": 3, "litres": 40}))
    state = _mix_state(entry)
    assert state["vessels"]["rodi"]["estimatedLitres"] == 10.0
    assert state["vessels"]["mix"]["estimatedLitres"] == 40.0
    assert state["vessels"]["mix"]["contents"] == "rodi"
    assert state["batch"]["state"] == "idle"            # nothing forced a run
    # Start the mix: heat is enabled, so the heater leads.
    run(integration.websocket_mixing_start_mix(hass, conn, {"id": 4}))
    state = _mix_state(entry)
    assert state["batch"]["state"] == "heating" and state["batch"]["litres"] == 40.0
    assert state["vessels"]["mix"]["contents"] == "rodi"   # no salt yet
    assert ("turn_on", "switch.mix_heater") in _switch_calls(hass, "switch.mix_heater")
    # At temperature: pumps on, salt goes in, contents flip.
    run(integration.websocket_mixing_advance(hass, conn, {"id": 5}))
    state = _mix_state(entry)
    assert state["batch"]["state"] == "salting"
    assert state["vessels"]["mix"]["contents"] == "salt"
    assert ("turn_on", "switch.mix_pump_a") in _switch_calls(hass, "switch.mix_pump_a")
    assert ("turn_on", "switch.mix_pump_b") in _switch_calls(hass, "switch.mix_pump_b")


def test_transfer_refused_over_standing_saltwater():
    install_scheduler(integration)
    hass, entry = _station({"batch": _stored_batch()})
    conn = FakeConnection()
    run(integration.websocket_mixing_transfer(hass, conn, {"id": 1, "litres": 5}))
    payload = conn.results[-1].payload
    assert payload["success"] is False
    assert any("still holds mixed saltwater" in r for r in payload["reasons"])


def test_transfer_dilutes_a_salting_batch():
    install_scheduler(integration)
    hass, entry = _station({"batch": {"state": "salting", "type": "salt", "litres": 40,
                                      "stageAt": _iso(NOW)}})
    conn = FakeConnection()
    run(integration.websocket_mixing_transfer(hass, conn, {"id": 1, "litres": 5}))
    state = _mix_state(entry)
    assert conn.results[-1].payload["success"] is True
    assert state["vessels"]["mix"]["estimatedLitres"] == 45.0
    assert state["vessels"]["mix"]["contents"] == "salt"   # dilution never un-salts


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


def test_single_vessel_fills_directly_then_mixes():
    scheduler = install_scheduler(integration)
    hass, entry = _station({"layout": "single",
                            "rodi": {"rateLph": 120, "fillCapMin": 240}})
    conn = FakeConnection()
    before = len(scheduler.scheduled)
    run(integration.websocket_mixing_rodi_draw(
        hass, conn, {"id": 1, "litres": 20, "destination": "mix"}))
    assert conn.results[-1].payload["success"] is True
    # 20 L at 120 L/h = 10 min — pick OUR stop leg out of the save-pass re-arms.
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc)
    stop = next(r for r in scheduler.scheduled[before:]
                if not r["cancelled"] and 9 * 60 < (r["run_at"] - now).total_seconds() < 11 * 60)

    async def _fire():
        await stop["callback"](stop["run_at"])
    run(_fire())
    state = _mix_state(entry)
    assert state["vessels"]["mix"]["estimatedLitres"] == 20.0
    assert state["vessels"]["mix"]["contents"] == "rodi"
    run(integration.websocket_mixing_start_mix(hass, conn, {"id": 2}))
    assert _mix_state(entry)["batch"]["state"] == "heating"   # heat before salt


def test_discard_empties_salt_but_stopping_heat_keeps_the_rodi():
    install_scheduler(integration)
    hass, entry = _station({"batch": {"state": "salting", "type": "salt", "litres": 40,
                                      "stageAt": _iso(NOW)}})
    conn = FakeConnection()
    run(integration.websocket_mixing_abort(hass, conn, {"id": 1}))
    state = _mix_state(entry)
    assert state["batch"]["state"] == "idle"
    assert state["vessels"]["mix"]["estimatedLitres"] == 0.0    # salt water dumped
    assert state["vessels"]["mix"]["contents"] == "empty"
    for entity in _STATION_SWITCHES:
        assert ("turn_off", entity) in _switch_calls(hass, entity)
    # Idle abort is an error, not a silent success.
    run(integration.websocket_mixing_abort(hass, conn, {"id": 2}))
    assert conn.errors and conn.errors[-1].code == "not_running"
    # Stopping a HEATING run keeps the water — it is still plain RODI.
    hass2, entry2 = _station({"batch": {"state": "heating", "type": "salt", "litres": 40,
                                        "stageAt": _iso(NOW)}})
    conn2 = FakeConnection()
    run(integration.websocket_mixing_abort(hass2, conn2, {"id": 1}))
    state2 = _mix_state(entry2)
    assert state2["batch"]["state"] == "idle"
    assert state2["vessels"]["mix"]["estimatedLitres"] == 40.0
    assert state2["vessels"]["mix"]["contents"] == "rodi"


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
    run(integration.websocket_mixing_rodi_draw(
        hass, conn, {"id": 1, "litres": 0, "destination": "store"}))
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


def test_legacy_rodi_stored_batch_folds_to_water_on_hand():
    # A legacy rodi-type "stored batch" is plain water, not a run — and plain
    # water never circulates (circulation is gated on a live ready/storing run).
    install_scheduler(integration)
    hass, entry = _station({"batch": _stored_batch(
        type="rodi", nextCirculateAt=_iso(NOW + timedelta(hours=1)))})
    state = _mix_state(entry)
    assert state["batch"]["state"] == "idle"
    assert state["vessels"]["mix"]["contents"] == "rodi"

    async def _arm():
        await integration._async_schedule_mixing_circulation(
            hass, entry, integration._config_from_entry(entry))
    run(_arm())
    assert integration.MIXING_CIRC_UNSUB not in hass.data.get(integration.DOMAIN, {})


def test_summary_exposes_the_next_stir_stamp():
    # The panel says "next stir at 21:40" off this — the schedule must be
    # visible, not a timer the keeper is asked to trust.
    cfg = _cfg()
    stamp = _iso(NOW + timedelta(hours=3))
    out = mixing.batch_state(_stored_batch(nextCirculateAt=stamp), cfg, NOW)
    assert out["nextCirculateAt"] == stamp
    # Mid-burst the stamp is empty by design — "circulating" tells that half.
    burst = mixing.batch_state(
        _stored_batch(circulateUntil=_iso(NOW + timedelta(minutes=5))), cfg, NOW)
    assert burst["circulating"] is True and burst["nextCirculateAt"] == ""
    # No batch, no schedule: idle summaries carry no stir clock at all.
    assert "nextCirculateAt" not in mixing.batch_state({"state": "idle"}, cfg, NOW)


def test_cadence_turned_off_mid_burst_still_stops_the_pumps():
    # Setting "circulate every" to 0 while a burst runs must end the burst —
    # the schedule pass may never clear the stop leg and walk away, or the
    # pumps run until someone notices.
    from datetime import datetime as _dt, timezone as _tz
    scheduler = install_scheduler(integration)
    now = _dt.now(_tz.utc)
    hass, entry = _station({
        "storage": {"circulateEveryH": 0, "circulateForMin": 10, "retestAfterDays": 7},
        "batch": _stored_batch(circulateUntil=(now + timedelta(minutes=8)).isoformat())})

    async def _arm():
        await integration._async_schedule_mixing_circulation(
            hass, entry, integration._config_from_entry(entry))
    run(_arm())
    stop = next(r for r in scheduler.scheduled
                if not r["cancelled"] and 7 * 60 < (r["run_at"] - now).total_seconds() < 9 * 60)

    async def _fire(record):
        await record["callback"](record["run_at"])
    run(_fire(stop))
    assert ("turn_off", "switch.mix_pump_a") in _switch_calls(hass, "switch.mix_pump_a")
    assert ("turn_off", "switch.mix_pump_b") in _switch_calls(hass, "switch.mix_pump_b")
    batch = _mix_state(entry)["batch"]
    assert batch["circulateUntil"] == ""
    assert batch["nextCirculateAt"] == ""       # cadence 0 = honestly off, no next burst


def test_turning_the_cadence_on_heals_a_ready_batch_with_no_schedule():
    # A batch that went ready while the cadence was 0 has no stir stamp, and
    # the schedule arms only from stamps — turning circulation on later must
    # anchor one (the normaliser heals the void on any save), or "on" is a lie.
    from datetime import datetime as _dt, timezone as _tz
    install_scheduler(integration)
    hass, entry = _station({
        "storage": {"circulateEveryH": 6, "circulateForMin": 10, "retestAfterDays": 7},
        "batch": _stored_batch(state="ready")})
    batch = _mix_state(entry)["batch"]
    hours_out = (_dt.fromisoformat(batch["nextCirculateAt"])
                 - _dt.now(_tz.utc)).total_seconds() / 3600.0
    assert 5.9 < hours_out < 6.1
    # And with the cadence off, the void stays honestly empty — no phantom stir.
    hass2, entry2 = _station({
        "storage": {"circulateEveryH": 0, "circulateForMin": 10, "retestAfterDays": 7},
        "batch": _stored_batch(state="ready")})
    assert _mix_state(entry2)["batch"]["nextCirculateAt"] == ""


def test_mark_used_debits_the_vessel_then_closes_the_batch():
    install_scheduler(integration)
    hass, entry = _station({"batch": _stored_batch()})
    conn = FakeConnection()
    run(integration.websocket_mixing_mark_used(hass, conn, {"id": 1, "litres": 15}))
    state = _mix_state(entry)
    assert state["batch"]["state"] == "storing"
    assert state["vessels"]["mix"]["estimatedLitres"] == 25.0
    run(integration.websocket_mixing_mark_used(hass, conn, {"id": 2, "litres": 25}))
    state = _mix_state(entry)
    assert state["batch"]["state"] == "idle"
    assert state["vessels"]["mix"]["contents"] == "empty"
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
    state = _mix_state(entry)
    assert state["vessels"]["mix"]["estimatedLitres"] == 25.0
    assert state["vessels"]["mix"]["contents"] == "salt"           # still the same water
    # No run: a corrected-in level reads as plain RODI water on hand.
    hass2, entry2 = _station()
    conn2 = FakeConnection()
    run(integration.websocket_mixing_set_level(
        hass2, conn2, {"id": 3, "vessel": "mix", "litres": 10}))
    state2 = _mix_state(entry2)
    assert state2["vessels"]["mix"]["estimatedLitres"] == 10.0
    assert state2["vessels"]["mix"]["contents"] == "rodi"
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
    # Aged past the retest window ⇒ not vouched.
    cfg["vessels"]["mix"].update({"estimatedLitres": 40, "contents": "salt"})
    cfg["batch"] = {"state": "storing", "litres": 40,
                    "testedAt": _iso(now - timedelta(days=9))}
    assert "retest window" in mixing.awc_guard_reason(cfg, 10, now)["message"]
    # Not enough left in the VESSEL ⇒ says how short.
    cfg["batch"]["testedAt"] = _iso(now)
    cfg["vessels"]["mix"]["estimatedLitres"] = 5
    assert "only 5 L" in mixing.awc_guard_reason(cfg, 10, now)["message"]
    # Tested, in date, sufficient ⇒ vouched.
    cfg["vessels"]["mix"]["estimatedLitres"] = 40
    assert mixing.awc_guard_reason(cfg, 10, now) is None


_AWC_SENSORS = {
    "binary_sensor.high": "off", "binary_sensor.leak": "off",
    "binary_sensor.fresh_empty": "off", "binary_sensor.waste_full": "off",
}


def _awc_station_entry(guard="block", batch=None, fresh_ml=25000, fresh_from_vessel=True,
                       maintenance_from_vessel=True):
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
            "fresh": {"capacityLitres": 25, "remainingMl": fresh_ml,
                      "emptyEntity": "binary_sensor.fresh_empty"},
            "waste": {"capacityLitres": 25, "filledMl": 0,
                      "fullEntity": "binary_sensor.waste_full"},
        },
        "safety": {"highLevelEntity": "binary_sensor.high",
                   "leakEntity": "binary_sensor.leak", "maxSingleChangePercent": 25},
        "schedule": {"method": "batch_sequential"},
    }
    mix_cfg = _station_cfg(integrations={"awcGuard": guard, "atoFromRodi": False,
                                         "freshFromVessel": fresh_from_vessel,
                                         "maintenanceFromVessel": maintenance_from_vessel})
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
    # The guard reads the wall clock for the retest window, so the fixture's
    # frozen NOW (2026-08-28) went stale on 2026-09-04 — test it "today".
    hass, entry = _awc_station_entry(guard="block", batch=_stored_batch(testedAt=_iso(datetime.now(timezone.utc))))
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
    assert config["mixingStation"]["vessels"]["mix"]["estimatedLitres"] == 25.0
    integration._mixing_debit_batch(hass, config, 30, "the water change")
    assert config["mixingStation"]["batch"]["state"] == "idle"
    assert config["mixingStation"]["vessels"]["mix"]["contents"] == "empty"
    # Uncoupled (guard off): the ledger must NOT phantom-drain.
    hass2, entry2 = _station({"batch": _stored_batch(),
                              "integrations": {"awcGuard": "off", "atoFromRodi": False}})
    config2 = integration._config_from_entry(entry2)
    integration._mixing_debit_batch(hass2, config2, 15, "the water change")
    assert config2["mixingStation"]["vessels"]["mix"]["estimatedLitres"] == 40.0


def test_fresh_refill_transfers_the_litres_from_the_vessel():
    # "Fresh refilled" IS the physical transfer (doc §27): the container took
    # 15 L to reach full, so exactly 15 L leaves the mix vessel — the level
    # estimate and the dose guide's top-up story follow automatically.
    install_scheduler(integration)
    hass, entry = _awc_station_entry(guard="warn", batch=_stored_batch(), fresh_ml=10000)
    conn = FakeConnection()
    run(integration.websocket_awc_reset_reservoir(hass, conn, {"id": 1, "reservoir": "fresh"}))
    config = integration._config_from_entry(entry)
    assert config["automaticWaterChange"]["reservoirs"]["fresh"]["remainingMl"] == 25000.0
    assert config["mixingStation"]["vessels"]["mix"]["estimatedLitres"] == 25.0
    assert any("AWC fresh refill" in str(a.get("message", ""))
               for a in config.get("activity", []))
    # Guard off = fully uncoupled: the reservoir resets, the vessel stands.
    hass2, entry2 = _awc_station_entry(guard="off", batch=_stored_batch(), fresh_ml=10000)
    conn2 = FakeConnection()
    run(integration.websocket_awc_reset_reservoir(hass2, conn2, {"id": 2, "reservoir": "fresh"}))
    config2 = integration._config_from_entry(entry2)
    assert config2["automaticWaterChange"]["reservoirs"]["fresh"]["remainingMl"] == 25000.0
    assert config2["mixingStation"]["vessels"]["mix"]["estimatedLitres"] == 40.0
    # Direct-draw plumbing (flag off): a refill is just a ledger reset.
    hass3, entry3 = _awc_station_entry(guard="warn", batch=_stored_batch(),
                                       fresh_ml=10000, fresh_from_vessel=False)
    conn3 = FakeConnection()
    run(integration.websocket_awc_reset_reservoir(hass3, conn3, {"id": 3, "reservoir": "fresh"}))
    assert integration._config_from_entry(entry3)[
        "mixingStation"]["vessels"]["mix"]["estimatedLitres"] == 40.0


def test_fresh_topup_works_at_any_level_and_reports_the_transfer():
    # Not an empty-only reset: 18 of 25 L standing → exactly 7 L to full,
    # echoed back to the panel with the vessel's side of the transfer.
    install_scheduler(integration)
    hass, entry = _awc_station_entry(guard="warn", batch=_stored_batch(), fresh_ml=18000)
    conn = FakeConnection()
    run(integration.websocket_awc_reset_reservoir(hass, conn, {"id": 1, "reservoir": "fresh"}))
    payload = conn.results[0].payload
    assert payload["topUpL"] == 7.0
    assert payload["vessel"] == {"outcome": "debited", "drawnL": 7.0, "remainingL": 33.0}
    config = integration._config_from_entry(entry)
    assert config["automaticWaterChange"]["reservoirs"]["fresh"]["remainingMl"] == 25000.0
    assert config["mixingStation"]["vessels"]["mix"]["estimatedLitres"] == 33.0


def test_fresh_topup_shortfall_is_said_out_loud():
    # The vessel can't cover the top-up: it gives what it has, stands empty,
    # the batch closes — and both the payload and the activity say how short.
    install_scheduler(integration)
    hass, entry = _awc_station_entry(guard="warn", batch=_stored_batch(), fresh_ml=0)
    entry.options[CONF_SETTINGS]["mixingStation"]["vessels"]["mix"]["estimatedLitres"] = 10.0
    conn = FakeConnection()
    run(integration.websocket_awc_reset_reservoir(hass, conn, {"id": 1, "reservoir": "fresh"}))
    payload = conn.results[0].payload
    assert payload["topUpL"] == 25.0
    assert payload["vessel"] == {"outcome": "shortfall", "drawnL": 10.0, "shortfallL": 15.0}
    config = integration._config_from_entry(entry)
    assert config["mixingStation"]["vessels"]["mix"]["contents"] == "empty"
    assert config["mixingStation"]["batch"]["state"] == "idle"
    assert any(a.get("type") == "warning" and "15 L short" in str(a.get("message", ""))
               for a in config.get("activity", []))


def test_fresh_topup_with_untested_saltwater_warns_and_stands_off():
    # Salt standing but no tested batch: the vessel is NOT debited (the debit
    # only trusts a vouched batch) — but silence would be phantom saltwater,
    # so the payload and the activity both say so.
    install_scheduler(integration)
    hass, entry = _awc_station_entry(guard="warn", fresh_ml=15000)
    mix_v = entry.options[CONF_SETTINGS]["mixingStation"]["vessels"]["mix"]
    mix_v["estimatedLitres"] = 30.0
    mix_v["contents"] = "salt"
    conn = FakeConnection()
    run(integration.websocket_awc_reset_reservoir(hass, conn, {"id": 1, "reservoir": "fresh"}))
    payload = conn.results[0].payload
    assert payload["vessel"] == {"outcome": "untested"}
    config = integration._config_from_entry(entry)
    assert config["mixingStation"]["vessels"]["mix"]["estimatedLitres"] == 30.0
    assert any(a.get("type") == "warning" and "no tested batch" in str(a.get("message", ""))
               for a in config.get("activity", []))
    # A vessel of plain RODI (or nothing) is a genuinely quiet skip.
    hass2, entry2 = _awc_station_entry(guard="warn", fresh_ml=15000)
    conn2 = FakeConnection()
    run(integration.websocket_awc_reset_reservoir(hass2, conn2, {"id": 2, "reservoir": "fresh"}))
    assert conn2.results[0].payload["vessel"] == {"outcome": "no_water"}
    assert not any(a.get("type") == "warning"
                   for a in integration._config_from_entry(entry2).get("activity", []))


def test_fresh_already_full_confirms_without_a_transfer():
    install_scheduler(integration)
    hass, entry = _awc_station_entry(guard="warn", batch=_stored_batch(), fresh_ml=25000)
    conn = FakeConnection()
    run(integration.websocket_awc_reset_reservoir(hass, conn, {"id": 1, "reservoir": "fresh"}))
    payload = conn.results[0].payload
    assert payload["topUpL"] == 0.0
    assert payload["vessel"] == {"outcome": "direct"}
    assert integration._config_from_entry(entry)[
        "mixingStation"]["vessels"]["mix"]["estimatedLitres"] == 40.0


def test_run_debit_belongs_to_direct_draw_plumbing_only():
    # Container model (the default): the vessel paid at refill time, so a
    # completed change must not charge it again — that would count the same
    # litres twice. Direct-draw plumbing keeps the per-run debit.
    install_scheduler(integration)
    hass, entry = _awc_station_entry(guard="warn", batch=_stored_batch())
    config = integration._config_from_entry(entry)
    assert config["mixingStation"]["integrations"]["freshFromVessel"] is True
    integration._mixing_run_debit(hass, config, 12)
    assert config["mixingStation"]["vessels"]["mix"]["estimatedLitres"] == 40.0
    hass2, entry2 = _awc_station_entry(guard="warn", batch=_stored_batch(),
                                       fresh_from_vessel=False)
    config2 = integration._config_from_entry(entry2)
    assert config2["mixingStation"]["integrations"]["freshFromVessel"] is False
    integration._mixing_run_debit(hass2, config2, 12)
    assert config2["mixingStation"]["vessels"]["mix"]["estimatedLitres"] == 28.0


def test_hand_logged_water_change_debits_the_vessel():
    # Doc §28: the bucket change pays the vessel too. End-to-end through
    # websocket_save_config — the door every panel Mark-done comes through —
    # a NEW hand-logged volume entry draws its litres from the batch, and a
    # re-save of the same config never charges the same bucket twice.
    install_scheduler(integration)
    hass, entry = _awc_station_entry(guard="warn", batch=_stored_batch())
    incoming = copy.deepcopy(entry.options[CONF_SETTINGS])
    incoming["maintenance"]["completions"]["water_change"] = [{
        "id": "water_change:2026-08-30T18:40:00+00:00:0",
        "timestamp": "2026-08-30T18:40:00+00:00",
        "notes": "", "volume": 17.5, "volumeUnit": "L",
    }]
    run(integration.websocket_save_config(hass, FakeConnection(), {"id": 1, "config": incoming}))
    saved = entry.options[CONF_SETTINGS]
    assert saved["mixingStation"]["vessels"]["mix"]["estimatedLitres"] == 22.5
    assert any("the water change you logged" in str(a.get("message", ""))
               for a in saved.get("activity", []))
    again = copy.deepcopy(saved)
    run(integration.websocket_save_config(hass, FakeConnection(), {"id": 2, "config": again}))
    assert entry.options[CONF_SETTINGS][
        "mixingStation"]["vessels"]["mix"]["estimatedLitres"] == 22.5


def test_percent_log_converts_through_the_history_rows_tank_litres():
    # A % log debits exactly the litres its history row shows — the panel's
    # tank precedence (profile first, AWC volume as the stand-in) mirrored.
    install_scheduler(integration)
    hass, entry = _awc_station_entry(guard="warn", batch=_stored_batch())
    stored = entry.options[CONF_SETTINGS]
    incoming = copy.deepcopy(stored)
    incoming["maintenance"]["completions"]["water_change"] = [{
        "id": "water_change:pct:0", "timestamp": "2026-08-30T18:40:00+00:00",
        "volume": 10, "volumeUnit": "pct",
    }]
    integration._mixing_debit_manual_changes(hass, stored, incoming)
    # No profile/dosing volume in this fixture, so the AWC's 200 L stands in:
    # 10% = 20 L off the 40 L vessel.
    assert incoming["mixingStation"]["vessels"]["mix"]["estimatedLitres"] == 20.0
    # A profile tank volume outranks it, exactly like the history rows do.
    incoming2 = copy.deepcopy(stored)
    incoming2["tank"]["volumeLitres"] = 100
    incoming2["maintenance"]["completions"]["water_change"] = [{
        "id": "water_change:pct:1", "timestamp": "2026-08-30T18:41:00+00:00",
        "volume": 10, "volumeUnit": "pct",
    }]
    integration._mixing_debit_manual_changes(hass, stored, incoming2)
    assert incoming2["mixingStation"]["vessels"]["mix"]["estimatedLitres"] == 30.0


def test_awc_tagged_skipped_and_replayed_rows_never_debit():
    # source="awc" rows are the AWC coupling's to account, skips move no
    # water, and a row the stored config already knows is not new.
    install_scheduler(integration)
    hass, entry = _awc_station_entry(guard="warn", batch=_stored_batch())
    stored = copy.deepcopy(entry.options[CONF_SETTINGS])
    stored["maintenance"]["completions"]["water_change"] = [
        {"id": "old", "timestamp": "2026-08-25T10:49:00+00:00",
         "volume": 12, "volumeUnit": "L"},
    ]
    incoming = copy.deepcopy(stored)
    incoming["maintenance"]["completions"]["water_change"] = [
        {"id": "awc-row", "timestamp": "2026-08-30T18:40:00+00:00",
         "volume": 17.5, "volumeUnit": "L", "source": "awc"},
        {"id": "skip-row", "timestamp": "2026-08-30T18:41:00+00:00",
         "skipped": True, "volume": 5, "volumeUnit": "L"},
        {"id": "old", "timestamp": "2026-08-25T10:49:00+00:00",
         "volume": 12, "volumeUnit": "L"},
    ]
    integration._mixing_debit_manual_changes(hass, stored, incoming)
    assert incoming["mixingStation"]["vessels"]["mix"]["estimatedLitres"] == 40.0


def test_manual_change_debit_respects_flag_and_guard():
    install_scheduler(integration)
    new_row = [{
        "id": "water_change:new:0", "timestamp": "2026-08-30T18:40:00+00:00",
        "volume": 17.5, "volumeUnit": "L",
    }]
    # Flag off: this keeper's buckets come from somewhere else entirely.
    hass, entry = _awc_station_entry(guard="warn", batch=_stored_batch(),
                                     maintenance_from_vessel=False)
    stored = entry.options[CONF_SETTINGS]
    assert stored["mixingStation"]["integrations"]["maintenanceFromVessel"] is False
    incoming = copy.deepcopy(stored)
    incoming["maintenance"]["completions"]["water_change"] = list(new_row)
    integration._mixing_debit_manual_changes(hass, stored, incoming)
    assert incoming["mixingStation"]["vessels"]["mix"]["estimatedLitres"] == 40.0
    # Guard off: the ledger is never touched from outside the Mixing tab.
    hass2, entry2 = _awc_station_entry(guard="off", batch=_stored_batch())
    stored2 = entry2.options[CONF_SETTINGS]
    assert stored2["mixingStation"]["integrations"]["maintenanceFromVessel"] is True
    incoming2 = copy.deepcopy(stored2)
    incoming2["maintenance"]["completions"]["water_change"] = list(new_row)
    integration._mixing_debit_manual_changes(hass2, stored2, incoming2)
    assert incoming2["mixingStation"]["vessels"]["mix"]["estimatedLitres"] == 40.0


# ---------------------------------------------------------------- Stage E: the RODI utility
# Draws outside a batch (store top-up or the external T-off), the timed-run
# flow calibration, and the filter-litres ledger — 0.7.88.


def test_draw_guards_demand_rate_booster_and_room():
    # No rate, no bound booster: both refusals, honestly worded.
    cfg = _cfg(rodi={"rateLph": 0, "fillCapMin": 240})
    reasons = mixing.draw_guard_reasons(cfg, 10, "store")
    assert any("flow rate is unknown" in r for r in reasons)
    assert any("booster plug" in r for r in reasons)
    # An OPEN-ENDED fill (litres 0) needs no rate — the float valve is the stop.
    cfg = _cfg(simulate=True, rodi={"rateLph": 0, "fillCapMin": 240})
    assert mixing.draw_guard_reasons(cfg, 0, "store") == []
    # ...but a T-off has no float valve, so open-ended external refuses.
    assert any("no float valve" in r for r in mixing.draw_guard_reasons(cfg, 0, "external"))
    # Simulate + a rate: a store draw that fits passes clean...
    cfg = _cfg(simulate=True, rodi={"rateLph": 120, "fillCapMin": 240})
    assert mixing.draw_guard_reasons(cfg, 10, "store") == []
    # ...but the store only has 10 L free (40 of 50) — 20 L overflows.
    assert any("overflow" in r for r in mixing.draw_guard_reasons(cfg, 20, "store"))
    # Single layout has no store; its vessel takes the water directly.
    single = _cfg(simulate=True, layout="single", rodi={"rateLph": 120, "fillCapMin": 240})
    assert any("fill the vessel instead" in r
               for r in mixing.draw_guard_reasons(single, 10, "store"))
    assert mixing.draw_guard_reasons(single, 10, "external") == []
    assert mixing.draw_guard_reasons(single, 10, "mix") == []


def test_draw_guards_respect_the_busy_booster_and_standing_salt():
    drawing = _cfg(simulate=True, rodi={
        "rateLph": 120, "fillCapMin": 240,
        "draw": {"active": True, "litres": 10, "destination": "store",
                 "startedAt": _iso(NOW), "endsAt": _iso(NOW + timedelta(minutes=5))}})
    assert any("already going" in r
               for r in mixing.draw_guard_reasons(drawing, 5, "external"))
    # Fresh RODI never lands on standing saltwater — except as dilution.
    salty = _cfg(simulate=True, rodi={"rateLph": 120, "fillCapMin": 240})
    salty["vessels"]["mix"].update({"estimatedLitres": 30, "contents": "salt"})
    salty["batch"]["state"] = "storing"
    assert any("still holds mixed saltwater" in r
               for r in mixing.draw_guard_reasons(salty, 5, "mix"))
    salty["batch"]["state"] = "salting"
    assert mixing.draw_guard_reasons(salty, 5, "mix") == []


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
    # Two decimals: at trickle rates a whole-decimal round moves a long
    # fill's ETA by many minutes (2.3 L in 28 min is 4.93, not 4.9).
    assert mixing.calibration_rate(2.3, 1680) == 4.93
    assert mixing.rodi_status(_cfg(rodi={"rateLph": 4.93}), NOW)["rateLph"] == 4.93


def test_filter_stages_report_their_own_lives():
    cfg = _cfg(rodi={"rateLph": 0, "fillCapMin": 240, "litresProcessed": 5000,
                     "filters": [
                         {"id": "f1", "label": "Sediment 5µm", "type": "sediment",
                          "ratedLitres": 2000, "litresProcessed": 1500, "changedAt": ""},
                         {"id": "f2", "label": "", "type": "carbon",
                          "ratedLitres": 2000, "litresProcessed": 2200, "changedAt": ""},
                         {"id": "f3", "label": "DI", "type": "di",
                          "ratedLitres": 0, "litresProcessed": 900, "changedAt": ""},
                     ]})
    status = mixing.rodi_status(cfg, NOW)
    f1, f2, f3 = status["filters"]
    assert f1["percentLeft"] == 25.0 and f1["due"] is False
    assert f2["percentLeft"] == 0.0 and f2["due"] is True      # past its life
    assert f3["percentLeft"] is None and f3["due"] is False    # untracked ⇒ no guess
    assert status["filterDue"] is True                          # any stage due ⇒ due
    assert status["litresProcessed"] == 5000.0                  # odometer untouched


def test_normaliser_migrates_the_v1_counter_and_caps_the_list():
    # A 0.7.88-style single counter becomes one tracked stage, exactly once.
    config = integration._normalise_core_config({"mixingStation": _cfg(rodi={
        "rateLph": 0, "fillCapMin": 240,
        "litresProcessed": 800, "filterRatedL": 1500, "filterChangedAt": _iso(NOW)})})
    filters = config["mixingStation"]["rodi"]["filters"]
    assert len(filters) == 1
    assert filters[0]["ratedLitres"] == 1500.0 and filters[0]["litresProcessed"] == 800.0
    assert "filterRatedL" not in config["mixingStation"]["rodi"]   # legacy keys retired
    # Junk entries are dropped, ids assigned, and the list is capped at 10.
    config2 = integration._normalise_core_config({"mixingStation": _cfg(rodi={
        "rateLph": 0, "fillCapMin": 240,
        "filters": ["garbage"] + [{"type": "carbon"} for _ in range(12)]})})
    filters2 = config2["mixingStation"]["rodi"]["filters"]
    assert 1 <= len(filters2) <= 10
    assert all(f["id"] for f in filters2)
    assert len({f["id"] for f in filters2}) == len(filters2)      # ids unique


def test_processed_litres_fan_out_to_every_stage():
    scheduler = install_scheduler(integration)
    hass, entry = _station(_rodi_over(filters=[
        {"id": "f1", "label": "Sediment", "type": "sediment",
         "ratedLitres": 2000, "litresProcessed": 100, "changedAt": ""},
        {"id": "f2", "label": "Membrane", "type": "membrane",
         "ratedLitres": 30000, "litresProcessed": 500, "changedAt": ""},
    ]))
    conn = FakeConnection()
    before = len(scheduler.scheduled)
    run(integration.websocket_mixing_rodi_draw(
        hass, conn, {"id": 1, "litres": 10, "destination": "external"}))
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc)
    stop = next(r for r in scheduler.scheduled[before:]
                if not r["cancelled"] and 4 * 60 < (r["run_at"] - now).total_seconds() < 6 * 60)

    async def _fire():
        await stop["callback"](stop["run_at"])
    run(_fire())
    state = _mix_state(entry)
    stages = {f["id"]: f for f in state["rodi"]["filters"]}
    assert stages["f1"]["litresProcessed"] == 110.0
    assert stages["f2"]["litresProcessed"] == 510.0
    assert state["rodi"]["litresProcessed"] == 10.0            # odometer moved too


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


def test_flush_seconds_never_count_as_water():
    # Calibration: 10 L over 11 min with a 60 s flush is 10 L in 10 min of
    # PRODUCTION — 60 L/h, not 54.5. A run the flush swallows is refused.
    assert mixing.calibration_rate(10, 660, 60) == 60.0
    assert mixing.calibration_rate(1.0, 100, 60) == 0.0    # 40 s of production = noise
    # Live-draw progress reads 0 inside the flush window, then meters honestly.
    cfg = _cfg(rodi={"rateLph": 60, "flushSeconds": 120, "draw": {
        "active": True, "litres": 0, "destination": "store",
        "startedAt": _iso(NOW - timedelta(seconds=60)),
        "endsAt": _iso(NOW + timedelta(minutes=30))}})
    assert mixing.rodi_status(cfg, NOW)["draw"]["litresDone"] == 0.0
    cfg["rodi"]["draw"]["startedAt"] = _iso(NOW - timedelta(seconds=120 + 360))
    assert mixing.rodi_status(cfg, NOW)["draw"]["litresDone"] == 6.0   # 6 min of production
    assert mixing.rodi_status(cfg, NOW)["flushSeconds"] == 120
    # The near-full projection starts after the flush too.
    cfg2 = _cfg(
        vessels={"rodi": {"volumeLitres": 50, "estimatedLitres": 0},
                 "mix": {"volumeLitres": 50, "estimatedLitres": 0, "contents": "empty"}},
        rodi={"rateLph": 60, "flushSeconds": 300, "alertPct": 80, "draw": {
            "active": True, "litres": 0, "destination": "store",
            "startedAt": _iso(NOW), "endsAt": _iso(NOW + timedelta(hours=4))}})
    alert = mixing.draw_alert(cfg2)
    assert alert is not None
    minutes = (alert["at"] - NOW).total_seconds() / 60.0
    assert 44.9 < minutes < 45.1        # 40 L to threshold at 60 L/h = 40 min, + 5 min flush


def test_calibrate_finish_discounts_the_configured_flush():
    install_scheduler(integration)
    started = datetime.now(timezone.utc) - timedelta(minutes=11)
    hass, entry = _station(_rodi_over(
        rateLph=0, flushSeconds=60,
        calibration={"active": True, "startedAt": _iso(started)}))
    conn = FakeConnection()
    run(integration.websocket_mixing_calibrate(
        hass, conn, {"id": 1, "action": "finish", "litres": 10}))
    assert conn.results[-1].payload["success"] is True
    rodi = _mix_state(entry)["rodi"]
    assert 59.5 <= rodi["rateLph"] <= 60.5      # 10 L in 10 min of production
    # A run the flush swallows is refused, and the refusal names the flush.
    started2 = datetime.now(timezone.utc) - timedelta(seconds=70)
    hass2, entry2 = _station(_rodi_over(
        rateLph=80, flushSeconds=60,
        calibration={"active": True, "startedAt": _iso(started2)}))
    conn2 = FakeConnection()
    run(integration.websocket_mixing_calibrate(
        hass2, conn2, {"id": 2, "action": "finish", "litres": 2}))
    payload = conn2.results[-1].payload
    assert payload["success"] is False
    assert any("auto-flush" in r for r in payload["reasons"])
    assert _mix_state(entry2)["rodi"]["rateLph"] == 80.0


def test_dose_guide_tells_both_stories():
    # The FULL line follows the CONFIGURED volume — resizing the vessel moves
    # it even while water stands (the bug: contents pinned the one figure).
    cfg = _cfg()
    cfg["vessels"]["mix"].update({"volumeLitres": 50, "estimatedLitres": 15,
                                  "contents": "salt"})
    cfg["batch"] = {"state": "ready", "litres": 15}
    guide = mixing.summary(cfg, NOW)["doseGuide"]
    assert guide["full"] == mixing.salt_dose("nyos_pure", 50, 35)
    assert guide["fullLitres"] == 50.0 and guide["heldLitres"] == 15.0
    # Standing saltwater short of full ⇒ the top-up story: salt for the NEW
    # water only (35 L), the standing 15 L keeps its own.
    assert guide["topUpLitres"] == 35.0
    assert guide["topUp"] == mixing.salt_dose("nyos_pure", 35, 35)
    cfg["vessels"]["mix"]["volumeLitres"] = 80          # the keeper resizes
    guide = mixing.summary(cfg, NOW)["doseGuide"]
    assert guide["full"] == mixing.salt_dose("nyos_pure", 80, 35)
    assert guide["topUpLitres"] == 65.0
    # Standing RODI ⇒ a straight dose for what's on hand; no top-up story.
    cfg["vessels"]["mix"].update({"volumeLitres": 50, "estimatedLitres": 20,
                                  "contents": "rodi"})
    cfg["batch"] = {"state": "idle"}
    guide = mixing.summary(cfg, NOW)["doseGuide"]
    assert guide["topUp"] is None
    assert guide["standingRodi"] == mixing.salt_dose("nyos_pure", 20, 35)
    # A brim-full vessel needs no top-up line at all.
    cfg["vessels"]["mix"].update({"estimatedLitres": 50, "contents": "salt"})
    cfg["batch"] = {"state": "ready", "litres": 50}
    assert mixing.summary(cfg, NOW)["doseGuide"]["topUp"] is None
    # While a mix runs, the run's own dose rides along instead.
    cfg["vessels"]["mix"].update({"estimatedLitres": 40, "contents": "salt"})
    cfg["batch"] = {"state": "salting", "litres": 40, "stageAt": _iso(NOW)}
    guide = mixing.summary(cfg, NOW)["doseGuide"]
    assert guide["run"] == mixing.salt_dose("nyos_pure", 40, 35)
    assert guide["runLitres"] == 40.0 and guide["topUp"] is None


def test_calibrate_stop_freezes_the_window_and_finish_reads_it():
    # The ceremony's middle step: stop turns the water off and freezes the
    # clock — the litres are read from THAT window, however long the keeper
    # takes to type them. Here the run was stopped after 10 minutes and
    # finished 5 minutes later: 20 L in the FROZEN 10 min is 120 L/h (using
    # "now" would understate it to 80).
    install_scheduler(integration)
    hass, entry = _station(_rodi_over(
        rateLph=0, calibration={
            "active": True,
            "startedAt": _iso(datetime.now(timezone.utc) - timedelta(minutes=15)),
            "stoppedAt": _iso(datetime.now(timezone.utc) - timedelta(minutes=5))}))
    conn = FakeConnection()
    run(integration.websocket_mixing_calibrate(
        hass, conn, {"id": 1, "action": "finish", "litres": 20}))
    assert conn.results[-1].payload["success"] is True
    assert _mix_state(entry)["rodi"]["rateLph"] == 120.0
    # The stop action itself: booster off, run STILL active (it owns the
    # booster until finish/cancel), stamp written, second stop refused.
    hass2, entry2 = _station(_rodi_over(
        rateLph=0, calibration={
            "active": True,
            "startedAt": _iso(datetime.now(timezone.utc) - timedelta(minutes=3))}))
    conn2 = FakeConnection()
    run(integration.websocket_mixing_calibrate(hass2, conn2, {"id": 2, "action": "stop"}))
    assert ("turn_off", "switch.mix_booster") in _switch_calls(hass2, "switch.mix_booster")
    cal = _mix_state(entry2)["rodi"]["calibration"]
    assert cal["active"] is True and cal["stoppedAt"]
    assert mixing.rodi_busy_reason(_mix_state(entry2)) == "a flow calibration is running"
    run(integration.websocket_mixing_calibrate(hass2, conn2, {"id": 3, "action": "stop"}))
    assert conn2.errors and conn2.errors[-1].code == "invalid_state"
    # And the engine tells the frozen story: stopped, seconds, production.
    status = mixing.rodi_status(_cfg(rodi={
        "rateLph": 120, "flushSeconds": 60,
        "calibration": {"active": True,
                        "startedAt": _iso(NOW - timedelta(minutes=15)),
                        "stoppedAt": _iso(NOW - timedelta(minutes=5))}}), NOW)["calibration"]
    assert status["stopped"] is True and status["elapsedMin"] == 10.0
    assert status["elapsedSeconds"] == 600 and status["productionSeconds"] == 540


def test_stopped_calibration_cap_reanchors_from_the_stop():
    # A stopped run holds no booster hazard, so its tidy-up cap re-anchors
    # from the stop stamp — a 40-minute run still leaves the full window to
    # read the jug, and an abandoned measure is still swept away.
    from datetime import datetime as _dt, timezone as _tz
    scheduler = install_scheduler(integration)
    now = _dt.now(_tz.utc)
    hass, entry = _station(_rodi_over(
        rateLph=0, calibration={
            "active": True,
            "startedAt": _iso(now - timedelta(minutes=40)),
            "stoppedAt": _iso(now - timedelta(minutes=2))}))

    async def _arm():
        await integration._async_schedule_mixing_rodi(
            hass, entry, integration._config_from_entry(entry))
    run(_arm())
    cap = next(r for r in scheduler.scheduled
               if not r["cancelled"] and 27 * 60 < (r["run_at"] - now).total_seconds() < 29 * 60)

    async def _fire(record):
        await record["callback"](record["run_at"])
    run(_fire(cap))
    state = _mix_state(entry)
    assert state["rodi"]["calibration"]["active"] is False
    assert any("never arrived" in str(a.get("message", "")) for a in
               integration._config_from_entry(entry).get("activity", []))


def test_timed_draw_budgets_the_flush_and_credits_production_only():
    scheduler = install_scheduler(integration)
    hass, entry = _station(_rodi_over(rateLph=60, flushSeconds=120))
    conn = FakeConnection()
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc)
    run(integration.websocket_mixing_rodi_draw(
        hass, conn, {"id": 1, "litres": 10, "destination": "store"}))
    assert conn.results[-1].payload["success"] is True
    # 10 L at 60 L/h = 10 min of production + 2 min flush = a 12-min leg.
    stops = [r for r in scheduler.scheduled
             if not r["cancelled"] and 11 * 60 < (r["run_at"] - now).total_seconds() < 13 * 60]
    assert len(stops) == 1, "the stop leg must include the flush budget"
    # Stopped early 8 minutes in: only 6 min of production gets credited.
    started = _dt.now(_tz.utc) - timedelta(minutes=8)
    hass2, entry2 = _station(_rodi_over(rateLph=60, flushSeconds=120, draw={
        "active": True, "litres": 0, "destination": "store",
        "startedAt": _iso(started), "endsAt": _iso(started + timedelta(minutes=240))}))
    conn2 = FakeConnection()
    run(integration.websocket_mixing_rodi_stop(hass2, conn2, {"id": 2}))
    state = _mix_state(entry2)
    assert state["vessels"]["rodi"]["estimatedLitres"] == 46.0   # 40 + 6 min at 60 L/h
    assert state["rodi"]["litresProcessed"] == 6.0


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


def test_filters_changed_resets_one_stage_never_its_neighbours():
    install_scheduler(integration)
    hass, entry = _station(_rodi_over(litresProcessed=5000, filters=[
        {"id": "f1", "label": "Sediment", "type": "sediment",
         "ratedLitres": 2000, "litresProcessed": 1900, "changedAt": ""},
        {"id": "f2", "label": "Carbon", "type": "carbon",
         "ratedLitres": 2000, "litresProcessed": 1900, "changedAt": ""},
    ]))
    conn = FakeConnection()
    run(integration.websocket_mixing_filters_changed(
        hass, conn, {"id": 1, "filter_id": "f1"}))
    rodi = _mix_state(entry)["rodi"]
    stages = {f["id"]: f for f in rodi["filters"]}
    assert stages["f1"]["litresProcessed"] == 0.0 and stages["f1"]["changedAt"]
    assert stages["f2"]["litresProcessed"] == 1900.0               # neighbour untouched
    assert rodi["litresProcessed"] == 5000.0                       # odometer never resets
    # An unknown stage is an error, not a silent success.
    run(integration.websocket_mixing_filters_changed(
        hass, conn, {"id": 2, "filter_id": "nope"}))
    assert conn.errors and conn.errors[-1].code == "unknown_filter"


def test_transfers_never_double_count_the_filter_ledger():
    # The store's water already went through the membrane when it was drawn —
    # moving it to the vessel must not count it twice.
    install_scheduler(integration)
    hass, entry = _station(_rodi_over(litresProcessed=50))
    conn = FakeConnection()
    run(integration.websocket_mixing_transfer(hass, conn, {"id": 1, "litres": 20}))
    assert conn.results[-1].payload["success"] is True
    assert _mix_state(entry)["rodi"]["litresProcessed"] == 50.0


def test_unit_replaced_resets_every_clock_and_stamps_a_new_since():
    # A new unit arrives with new cartridges: the odometer's ONLY reset takes
    # every stage clock with it and stamps the new unit's first day.
    install_scheduler(integration)
    hass, entry = _station(_rodi_over(
        litresProcessed=5000, meteredSince="2026-01-01T00:00:00+00:00", filters=[
            {"id": "f1", "label": "Sediment", "type": "sediment",
             "ratedLitres": 2000, "litresProcessed": 1900, "changedAt": ""},
            {"id": "f2", "label": "Carbon", "type": "carbon",
             "ratedLitres": 2000, "litresProcessed": 500,
             "changedAt": "2026-05-01T00:00:00+00:00"},
        ]))
    conn = FakeConnection()
    run(integration.websocket_mixing_unit_replaced(hass, conn, {"id": 1}))
    assert conn.results[-1].payload["success"] is True
    rodi = _mix_state(entry)["rodi"]
    assert rodi["litresProcessed"] == 0.0
    assert rodi["meteredSince"] and rodi["meteredSince"] != "2026-01-01T00:00:00+00:00"
    for stage in rodi["filters"]:
        assert stage["litresProcessed"] == 0.0
        assert stage["changedAt"] == rodi["meteredSince"]


def test_unit_replaced_refused_while_the_booster_runs():
    # You don't swap a unit mid-draw — and the run's litres belong to one unit.
    install_scheduler(integration)
    hass, entry = _station(_rodi_over(litresProcessed=100))
    conn = FakeConnection()
    run(integration.websocket_mixing_rodi_draw(
        hass, conn, {"id": 1, "litres": 10, "destination": "store"}))
    run(integration.websocket_mixing_unit_replaced(hass, conn, {"id": 2}))
    payload = conn.results[-1].payload
    assert payload["success"] is False and payload["reasons"]
    assert _mix_state(entry)["rodi"]["litresProcessed"] == 100.0    # nothing reset


def test_metered_since_is_earned_by_the_first_litre_never_inherited():
    # A fresh odometer stamps its birthday with the first metered litre…
    cfg = {"rodi": {"litresProcessed": 0}}
    integration._mixing_add_processed(cfg, 10)
    first = cfg["rodi"]["meteredSince"]
    assert first
    integration._mixing_add_processed(cfg, 5)
    assert cfg["rodi"]["meteredSince"] == first                     # never re-stamped
    # …but an install that arrives already carrying litres keeps NO date —
    # OpenReef cannot know when that counting began, and no date beats a lie.
    inherited = {"rodi": {"litresProcessed": 122}}
    integration._mixing_add_processed(inherited, 10)
    assert not inherited["rodi"].get("meteredSince")


def test_rodi_status_and_normaliser_carry_the_metered_since_stamp():
    stamp = "2026-08-29T10:00:00+00:00"
    status = mixing.rodi_status(
        _cfg(rodi={"rateLph": 0, "meteredSince": stamp}), datetime.now(timezone.utc))
    assert status["meteredSince"] == stamp
    cfg = integration._normalise_core_config(
        {"mixingStation": {"rodi": {"meteredSince": stamp, "litresProcessed": 50}}})
    assert cfg["mixingStation"]["rodi"]["meteredSince"] == stamp
    trimmed = integration._normalise_core_config(
        {"mixingStation": {"rodi": {"meteredSince": "x" * 200}}})
    assert len(trimmed["mixingStation"]["rodi"]["meteredSince"]) == 40


# ---------------------------------------------------------------- salinity units
# Specific-gravity keepers (0.7.92): ppt stays canonical everywhere; SG is a
# display/input skin converted by the engine on the 35 ppt ↔ 1.0264 anchor.


def test_sg_conversion_round_trips_on_the_hobby_anchor():
    assert mixing.sg_from_ppt(35.0) == 1.0264
    assert mixing.ppt_from_sg(1.0264) == 35.0
    assert mixing.ppt_from_sg(1.0) == 0.0                  # non-physical → no reading
    assert abs(mixing.ppt_from_sg(mixing.sg_from_ppt(33.0)) - 33.0) < 0.1


def test_log_salinity_accepts_sg_and_stores_ppt():
    install_scheduler(integration)
    hass, entry = _station({"batch": {
        "state": "salting", "type": "salt", "litres": 40,
        "stageAt": _iso(datetime.now(timezone.utc) - timedelta(hours=3))}})
    conn = FakeConnection()
    run(integration.websocket_mixing_log_salinity(hass, conn, {"id": 1, "sg": 1.0264}))
    assert conn.results[-1].payload["success"] is True
    batch = _mix_state(entry)["batch"]
    assert batch["state"] == "ready" and abs(batch["loggedPpt"] - 35.0) < 0.1


def test_log_salinity_requires_a_reading_in_some_unit():
    install_scheduler(integration)
    hass, entry = _station({"batch": {"state": "salting", "type": "salt", "litres": 40}})
    conn = FakeConnection()
    run(integration.websocket_mixing_log_salinity(hass, conn, {"id": 1}))
    assert conn.errors and conn.errors[-1].code == "invalid_format"


def test_normalise_validates_the_salinity_unit():
    junk = integration._normalise_core_config({"mixingStation": _cfg(
        salt={"brand": "nyos_pure", "targetPpt": 35.0, "unit": "cups",
              "mixHours": 0, "customGPerL": 0})})["mixingStation"]
    assert junk["salt"]["unit"] == "ppt"
    sg = integration._normalise_core_config({"mixingStation": _cfg(
        salt={"brand": "nyos_pure", "targetPpt": 35.0, "unit": "sg",
              "mixHours": 0, "customGPerL": 0})})["mixingStation"]
    assert sg["salt"]["unit"] == "sg"


def test_summary_carries_the_unit_and_converted_targets():
    cfg = _cfg(salt={"brand": "nyos_pure", "targetPpt": 35.0, "unit": "sg",
                     "mixHours": 0, "customGPerL": 0},
               batch={"state": "ready", "type": "salt", "litres": 40, "usedLitres": 0,
                      "loggedPpt": 35.1, "testedAt": _iso(NOW), "stageAt": _iso(NOW)})
    summary = mixing.summary(cfg, NOW)
    assert summary["salinityUnit"] == "sg"
    assert summary["targetSg"] == 1.0264
    assert summary["batch"]["loggedSg"] == mixing.sg_from_ppt(35.1)
    # An untested batch offers no SG figure — never a fake 1.0000.
    assert mixing.batch_state({"state": "salting", "litres": 40}, cfg, NOW)["loggedSg"] is None


# ---------------------------------------------------------------- near-full alerts (§16)
# Rate-projected heads-up when a container is heading past its threshold —
# once per run, into HA (and the phone target) via the mode-notification path.


def _draw_over(dest="store", litres=0, ends_h=4.0, **rodi_extra):
    rodi = {"rateLph": 120, "fillCapMin": 240, "alertPct": 80,
            "draw": {"active": True, "litres": litres, "destination": dest,
                     "startedAt": _iso(NOW), "endsAt": _iso(NOW + timedelta(hours=ends_h)),
                     "alertedAt": ""}}
    rodi.update(rodi_extra)
    return rodi


def test_draw_alert_computes_the_crossing_from_the_anchor():
    # Store already at 40/50 with an 80% threshold: fire immediately.
    cfg = _cfg(simulate=True, rodi=_draw_over())
    alert = mixing.draw_alert(cfg)
    assert alert is not None and alert["at"] == NOW
    assert "RODI store" in alert["message"] and alert["pct"] == 80
    # Anchor at 10: 30 L to the threshold at 120 L/h = 15 minutes.
    cfg["vessels"]["rodi"]["estimatedLitres"] = 10
    alert = mixing.draw_alert(cfg)
    assert abs((alert["at"] - NOW).total_seconds() - 900) < 1
    # Off, rate-less, or already-fired runs never arm.
    assert mixing.draw_alert(_cfg(simulate=True, rodi=_draw_over(alertPct=0))) is None
    assert mixing.draw_alert(_cfg(simulate=True, rodi=_draw_over(rateLph=0))) is None
    fired = _cfg(simulate=True, rodi=_draw_over())
    fired["rodi"]["draw"]["alertedAt"] = _iso(NOW)
    assert mixing.draw_alert(fired) is None


def test_draw_alert_external_without_a_container_warns_on_the_run_itself():
    # No configured T-off volume ⇒ no container story — but a TIMED draw
    # still gets the nearly-done heads-up on its own target: 30 L at 80%
    # is 24 L = 12 minutes into a 120 L/h run.
    cfg = _cfg(simulate=True, rodi=_draw_over(dest="external", litres=30, ends_h=0.25))
    alert = mixing.draw_alert(cfg)
    assert alert is not None and abs((alert["at"] - NOW).total_seconds() - 720) < 1
    assert "30 L RODI run to the T-off" in alert["message"]
    assert "24 of 30 L" in alert["message"]
    # With a 20 L container the container story lands FIRST (16 L = 8 min)
    # and wins — earliest story fires, one alert per run.
    cfg["rodi"]["externalVolumeL"] = 20
    alert = mixing.draw_alert(cfg)
    assert alert is not None and abs((alert["at"] - NOW).total_seconds() - 480) < 1
    assert "T-off container" in alert["message"]


def test_draw_alert_timed_run_warns_near_its_own_finish_line():
    # A 10 L timed draw into a store sitting at 0/50 never reaches the
    # container's 80% — the run's own 80% (8 L = 4 min at 120 L/h) speaks.
    cfg = _cfg(simulate=True, rodi=_draw_over(litres=10, ends_h=10 / 120))
    cfg["vessels"]["rodi"]["estimatedLitres"] = 0
    alert = mixing.draw_alert(cfg)
    assert alert is not None and abs((alert["at"] - NOW).total_seconds() - 240) < 1
    assert "10 L RODI run to the RODI store" in alert["message"]
    # But a store already brimming flips it: the container's threshold comes
    # first (1 L to 80% of 50 = 30 s) and the overflow story wins.
    cfg["vessels"]["rodi"]["estimatedLitres"] = 39
    alert = mixing.draw_alert(cfg)
    assert alert is not None and abs((alert["at"] - NOW).total_seconds() - 30) < 1
    assert "RODI store is passing 80% full" in alert["message"]


def test_finish_alert_covers_the_boundary():
    # A run that ENDED at/above the threshold speaks at the finish line.
    cfg = _cfg(simulate=True, rodi={"rateLph": 120, "fillCapMin": 240, "alertPct": 80})
    cfg["vessels"]["rodi"]["estimatedLitres"] = 45   # post-credit level
    message = mixing.draw_finish_alert(cfg, "store", 10)
    assert message and "90% full" in message
    cfg["vessels"]["rodi"]["estimatedLitres"] = 20
    assert mixing.draw_finish_alert(cfg, "store", 10) is None
    cfg["rodi"]["externalVolumeL"] = 20
    assert "T-off container" in mixing.draw_finish_alert(cfg, "external", 16)
    assert mixing.draw_finish_alert(cfg, "external", 10) is None


def _notifications(hass):
    return [c for c in hass.services.calls
            if c.domain == "persistent_notification" and c.service == "create"
            and "openreef_mixing_nearfull" in c.data.values()]


def test_nearfull_alert_leg_fires_once_into_home_assistant():
    scheduler = install_scheduler(integration)
    # Store at 40/50, threshold 80% already crossed ⇒ the leg arms ~now.
    hass, entry = _station(_rodi_over(alertPct=80))
    conn = FakeConnection()
    before = len(scheduler.scheduled)
    run(integration.websocket_mixing_rodi_draw(
        hass, conn, {"id": 1, "litres": 0, "destination": "store"}))
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc)
    legs = [r for r in scheduler.scheduled[before:]
            if not r["cancelled"] and (r["run_at"] - now).total_seconds() < 5]
    assert len(legs) == 1, "expected exactly one near-full alert leg"

    async def _fire():
        await legs[0]["callback"](legs[0]["run_at"])
    run(_fire())
    assert len(_notifications(hass)) == 1
    state = _mix_state(entry)
    assert state["rodi"]["draw"]["active"] is True        # the run keeps going
    assert state["rodi"]["draw"]["alertedAt"]
    # The save re-arm must NOT arm a second alert leg for this run.
    config = integration._config_from_entry(entry)
    assert integration.mixing_engine.draw_alert(config["mixingStation"]) is None


def test_nearfull_boundary_notifies_at_the_finish_line():
    scheduler = install_scheduler(integration)
    # 16 L timed external draw into a 20 L T-off at 80%: crossing == the end,
    # so no mid-run leg — the finish check speaks instead.
    hass, entry = _station(_rodi_over(alertPct=80, externalVolumeL=20))
    conn = FakeConnection()
    before = len(scheduler.scheduled)
    run(integration.websocket_mixing_rodi_draw(
        hass, conn, {"id": 1, "litres": 16, "destination": "external"}))
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc)
    stop = next(r for r in scheduler.scheduled[before:]
                if not r["cancelled"] and 7 * 60 < (r["run_at"] - now).total_seconds() < 9 * 60)

    async def _fire():
        await stop["callback"](stop["run_at"])
    run(_fire())
    notes = _notifications(hass)
    assert len(notes) == 1
    assert _mix_state(entry)["rodi"]["draw"]["active"] is False


def test_alert_off_means_silence():
    scheduler = install_scheduler(integration)
    hass, entry = _station(_rodi_over(alertPct=0))
    conn = FakeConnection()
    before = len(scheduler.scheduled)
    run(integration.websocket_mixing_rodi_draw(
        hass, conn, {"id": 1, "litres": 0, "destination": "store"}))
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc)
    near = [r for r in scheduler.scheduled[before:]
            if not r["cancelled"] and (r["run_at"] - now).total_seconds() < 60]
    assert not near, "alerts off must arm no near-term leg"
    run(integration.websocket_mixing_rodi_stop(hass, conn, {"id": 2}))
    assert not _notifications(hass)


# ----------------------------------------------------------------------------
# The booster belongs to the RODI card. A mix-run transition (discard, or the
# run landing in ready/idle) sweeps its OWN plugs off; it must never reach
# across and cut a draw or a flow calibration mid-run — the keeper is standing
# there with a jug, and the RODI run's stamps would go on claiming litres that
# stopped flowing. 0.7.108.

def _cal_station(**over):
    started = datetime.now(timezone.utc) - timedelta(minutes=5)
    cfg = _rodi_over(rateLph=0, calibration={"active": True, "startedAt": _iso(started)})
    cfg.update(over)
    return _station(cfg)


def test_discard_mid_calibration_leaves_the_booster_making_water():
    install_scheduler(integration)
    hass, entry = _cal_station(batch={"state": "salting", "type": "salt", "litres": 40,
                                      "stageAt": _iso(NOW)})
    conn = FakeConnection()
    run(integration.websocket_mixing_abort(hass, conn, {"id": 1}))
    state = _mix_state(entry)
    assert state["batch"]["state"] == "idle"
    assert state["vessels"]["mix"]["estimatedLitres"] == 0.0        # the batch still goes
    assert state["vessels"]["mix"]["contents"] == "empty"
    for entity in ("switch.mix_pump_a", "switch.mix_pump_b", "switch.mix_heater"):
        assert ("turn_off", entity) in _switch_calls(hass, entity)
    # The calibration run is untouched: booster still on, stamps intact.
    assert ("turn_off", "switch.mix_booster") not in _switch_calls(hass, "switch.mix_booster")
    assert state["rodi"]["calibration"]["active"] is True
    assert state["rodi"]["calibration"]["startedAt"]
    # And the log says so rather than claiming everything went off.
    activity = integration._config_from_entry(entry).get("activity", [])
    assert any("left running" in a.get("message", "") for a in activity), activity


def test_discard_mid_draw_leaves_the_run_alone():
    install_scheduler(integration)
    started = datetime.now(timezone.utc) - timedelta(minutes=2)
    over = _rodi_over(draw={"active": True, "litres": 20, "destination": "store",
                            "startedAt": _iso(started),
                            "endsAt": _iso(started + timedelta(minutes=10))})
    over["batch"] = {"state": "salting", "type": "salt", "litres": 40, "stageAt": _iso(NOW)}
    hass, entry = _station(over)
    conn = FakeConnection()
    run(integration.websocket_mixing_abort(hass, conn, {"id": 1}))
    assert ("turn_off", "switch.mix_booster") not in _switch_calls(hass, "switch.mix_booster")
    assert _mix_state(entry)["rodi"]["draw"]["active"] is True


def test_batch_landing_in_ready_leaves_a_calibration_running():
    install_scheduler(integration)
    hass, entry = _cal_station(batch={"state": "salting", "type": "salt", "litres": 40,
                                      "stageAt": _iso(NOW - timedelta(hours=6))})
    conn = FakeConnection()
    run(integration.websocket_mixing_log_salinity(hass, conn, {"id": 1, "ppt": 35.0}))
    state = _mix_state(entry)
    assert state["batch"]["state"] == "ready"
    assert ("turn_off", "switch.mix_pump_a") in _switch_calls(hass, "switch.mix_pump_a")
    assert ("turn_off", "switch.mix_booster") not in _switch_calls(hass, "switch.mix_booster")
    assert state["rodi"]["calibration"]["active"] is True


def test_restart_recovery_never_cuts_a_live_calibration():
    install_scheduler(integration)
    hass, entry = _cal_station(batch={"state": "salting", "type": "salt", "litres": 40,
                                      "stageAt": _iso(NOW)})
    run(integration._async_mixing_recover_orphaned(hass, entry))
    assert ("turn_off", "switch.mix_heater") in _switch_calls(hass, "switch.mix_heater")
    assert ("turn_off", "switch.mix_booster") not in _switch_calls(hass, "switch.mix_booster")
    # With nothing holding the booster, the restart sweep still forces it off.
    hass2, entry2 = _station({"batch": {"state": "salting", "type": "salt", "litres": 40,
                                        "stageAt": _iso(NOW)}})
    run(integration._async_mixing_recover_orphaned(hass2, entry2))
    assert ("turn_off", "switch.mix_booster") in _switch_calls(hass2, "switch.mix_booster")



# ---------------------------------------------------------------- salt on hand (V3)

def _salted(kg=10.0, bucket=6.7, **over):
    """A station whose keeper has set the bucket: tracked, 40 L of RODI in the
    vessel ready to salt, NYOS at 35 ppt (39 g/L → 1.56 kg for the batch)."""
    cfg = {"saltStock": {"kg": kg, "bucketKg": bucket, "updatedAt": _iso(NOW), "history": []},
           "vessels": {"rodi": {"volumeLitres": 50, "estimatedLitres": 40, "levelSensorEntity": ""},
                       "mix": {"volumeLitres": 50, "estimatedLitres": 40, "contents": "rodi", "levelSensorEntity": ""}}}
    cfg.update(over)
    return cfg


def test_salt_stock_state_reads_batches_and_weeks_off_the_brand_dose():
    salt = {"brand": "nyos_pure", "targetPpt": 35.0, "customGPerL": 0}
    untracked = mixing.salt_stock_state(salt, {"kg": 0, "bucketKg": 0, "updatedAt": ""}, 50)
    assert untracked["tracked"] is False and untracked["low"] is False and "Not tracked" in untracked["text"]
    state = mixing.salt_stock_state(salt, {"kg": 10, "bucketKg": 6.7, "updatedAt": _iso(NOW)}, 50, weekly_litres=10)
    assert state["perBatchKg"] == 1.95 and state["batchesLeft"] == 5.1
    assert state["kgPerWeek"] == 0.39 and state["weeksLeft"] == 25.6
    assert state["low"] is False and state["text"].startswith("10 kg on hand · ≈5.1 batches of 50 L · ≈25.6 weeks")
    low = mixing.salt_stock_state(salt, {"kg": 1.2, "bucketKg": 6.7, "updatedAt": _iso(NOW)}, 50)
    assert low["low"] is True and low["text"].endswith("— time to order.") and low["weeksLeft"] is None
    tenth = mixing.salt_stock_state(salt, {"kg": 0.6, "bucketKg": 6.7, "updatedAt": _iso(NOW)}, 0)
    assert tenth["low"] is True and tenth["perBatchKg"] is None, "a tenth of a bucket is low even with no vessel size"
    out = mixing.salt_stock_state(salt, {"kg": 0, "bucketKg": 6.7, "updatedAt": _iso(NOW)}, 50)
    assert out["empty"] is True and out["low"] is False and out["text"].startswith("Out of salt")
    custom = mixing.salt_stock_state({"brand": "custom", "targetPpt": 35}, {"kg": 5, "updatedAt": _iso(NOW)}, 50)
    assert custom["perBatchKg"] is None and custom["batchesLeft"] is None and custom["low"] is False


def test_salt_stock_ledger_is_normalised_debited_on_salting_and_guarded():
    raw = _station_cfg(saltStock={"kg": "7.5", "bucketKg": 6.7, "updatedAt": _iso(NOW),
                                  "history": [{"at": _iso(NOW), "kg": 7.5, "delta": 6.7, "note": "new bucket"}, "junk", {"kg": 1}]})
    cfg = integration._normalise_core_config({"mixingStation": raw})["mixingStation"]
    assert cfg["saltStock"] == {"kg": 7.5, "bucketKg": 6.7, "updatedAt": _iso(NOW),
                                "history": [{"at": _iso(NOW), "kg": 7.5, "delta": 6.7, "note": "new bucket"}]}
    assert integration._normalise_core_config({"mixingStation": _station_cfg()})["mixingStation"]["saltStock"] == {
        "kg": 0.0, "bucketKg": 0.0, "updatedAt": "", "history": []}
    # Entering 'salting' debits the guide's grams for the vessel's litres.
    hass, entry = _station(_salted())
    config = integration._config_from_entry(entry)
    run(integration._async_mixing_enter_stage(hass, config, "salting", None))
    stock = config["mixingStation"]["saltStock"]
    assert stock["kg"] == 8.44 and stock["history"][-1]["note"] == "salted 40 L" and stock["history"][-1]["delta"] == -1.56
    # An untracked bucket is never invented: no updatedAt, no debit.
    hass2, entry2 = _station(_salted(updatedAt=""))
    config2 = integration._config_from_entry(entry2)
    config2["mixingStation"]["saltStock"]["updatedAt"] = ""
    run(integration._async_mixing_enter_stage(hass2, config2, "salting", None))
    assert config2["mixingStation"]["saltStock"]["kg"] == 10.0
    # Never below zero.
    hass3, entry3 = _station(_salted(kg=0.5))
    config3 = integration._config_from_entry(entry3)
    run(integration._async_mixing_enter_stage(hass3, config3, "salting", None))
    assert config3["mixingStation"]["saltStock"]["kg"] == 0.0
    # The stale-save guard: the stored ledger wins over whatever a client posts.
    stored = {"mixingStation": {"saltStock": {"kg": 8.44, "bucketKg": 6.7, "updatedAt": _iso(NOW), "history": []}}}
    incoming = {"mixingStation": {"saltStock": {"kg": 10.0, "bucketKg": 6.7, "updatedAt": "", "history": []}}}
    integration._mixing_preserve_runtime(stored, incoming)
    assert incoming["mixingStation"]["saltStock"]["kg"] == 8.44


def test_salt_stock_ws_set_bucket_size_and_the_summary_runway():
    hass, entry = _station()
    conn = FakeConnection()
    run(integration.websocket_mixing_salt_stock(hass, conn, {"id": 1, "action": "set", "kg": 10}))
    assert not conn.errors, conn.errors
    stock = conn.results[-1].payload["summary"]["saltStock"]
    assert stock["tracked"] and stock["kg"] == 10 and stock["batchesLeft"] == 5.1 and stock["weeksLeft"] is None
    run(integration.websocket_mixing_salt_stock(hass, conn, {"id": 2, "action": "size", "kg": 6.7}))
    assert conn.results[-1].payload["summary"]["saltStock"]["bucketKg"] == 6.7
    run(integration.websocket_mixing_salt_stock(hass, conn, {"id": 3, "action": "bucket"}))
    stock = conn.results[-1].payload["summary"]["saltStock"]
    assert stock["kg"] == 16.7 and _mix_state(entry)["saltStock"]["history"][-1]["note"] == "new bucket"
    run(integration.websocket_mixing_salt_stock(hass, conn, {"id": 4, "action": "bucket", "kg": 3.3}))
    assert conn.results[-1].payload["summary"]["saltStock"]["kg"] == 20.0
    # No size and no kilos: an honest refusal, not a silent no-op.
    hass2, entry2 = _station()
    conn2 = FakeConnection()
    run(integration.websocket_mixing_salt_stock(hass2, conn2, {"id": 5, "action": "bucket"}))
    assert conn2.error_codes == ["no_bucket_size"]
    # Weeks left come from the Maintenance log: 4 changes of 20 L in the last
    # month = 10 L a week = 0.39 kg a week.
    cfg = integration._config_from_entry(entry)
    cfg["maintenance"] = {"seeded": True, "enabled": True,
                          "tasks": {"water_change": {"label": "Water change", "cadenceDays": 7, "criticalAfterDays": 14,
                                                     "enabled": True, "logsVolume": True}},
                          "completions": {"water_change": [
                              {"id": f"wc{i}", "timestamp": _iso(datetime.now(timezone.utc) - timedelta(days=7 * i + 1)),
                               "volume": 20, "volumeUnit": "L"} for i in range(4)]
                              + [{"id": "old", "timestamp": _iso(datetime.now(timezone.utc) - timedelta(days=90)), "volume": 200, "volumeUnit": "L"},
                                 {"id": "skip", "timestamp": _iso(datetime.now(timezone.utc) - timedelta(days=2)), "volume": 999, "volumeUnit": "L", "skipped": True}]}}
    assert integration._maintenance_weekly_change_litres(cfg, datetime.now(timezone.utc)) == 10.0
    state = integration._mixing_salt_stock_state(cfg)
    assert state["kgPerWeek"] == 0.39 and state["weeksLeft"] == round(20.0 / 0.39, 1)
    # The digest's nag reads the same state.
    assert integration._maintenance_salt_nag(cfg, datetime.now(timezone.utc)) == []
    cfg["mixingStation"]["saltStock"]["kg"] = 1.2
    nag = integration._maintenance_salt_nag(cfg, datetime.now(timezone.utc))
    assert nag == [{"id": "salt", "label": "Salt", "detail": "1.2 kg left, ≈0.6 batches", "severity": "warning"}], nag
    cfg["mixingStation"]["saltStock"]["kg"] = 0
    assert integration._maintenance_salt_nag(cfg, datetime.now(timezone.utc))[0]["severity"] == "critical"
    cfg["mixingStation"]["enabled"] = False
    assert integration._maintenance_salt_nag(cfg, datetime.now(timezone.utc)) == []


def test_manual_water_change_is_stamped_with_the_vessels_water():
    """The new water's record (V3): a hand-logged change from the vessel
    carries the batch's tested salinity, the heat sensor's reading and the
    brand; typed figures win; AWC rows from the vessel carry ppt and brand."""
    hass, entry = _station({"vessels": {"rodi": {"volumeLitres": 50, "estimatedLitres": 40, "levelSensorEntity": ""},
                                        "mix": {"volumeLitres": 50, "estimatedLitres": 45, "contents": "salt", "levelSensorEntity": ""}},
                            "batch": {"state": "ready", "type": "salt", "litres": 45, "loggedPpt": 35.2, "testedAt": _iso(NOW)},
                            "heat": {"enabled": True, "targetC": 25.0, "tempSensorEntity": "sensor.mix_temp"}})
    hass.states.set("sensor.mix_temp", "25.3")
    stored = integration._config_from_entry(entry)
    stored["maintenance"] = {"seeded": True, "enabled": True,
                             "tasks": {"water_change": {"label": "Water change", "cadenceDays": 7, "criticalAfterDays": 14,
                                                        "enabled": True, "logsVolume": True}},
                             "completions": {"water_change": []}}
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(stored)
    incoming = copy.deepcopy(entry.options[CONF_SETTINGS])
    incoming["maintenance"]["completions"]["water_change"] = [
        {"id": "wc:new", "timestamp": _iso(datetime.now(timezone.utc)), "notes": "", "volume": 10, "volumeUnit": "L"},
        {"id": "wc:typed", "timestamp": _iso(datetime.now(timezone.utc) - timedelta(minutes=1)), "notes": "", "volume": 5,
         "volumeUnit": "L", "newWater": {"ppt": 34.8}},
    ]
    conn = FakeConnection()
    run(integration.websocket_save_config(hass, conn, {"id": 1, "config": incoming}))
    assert not conn.errors, conn.errors
    saved = {e["id"]: e for e in entry.options[CONF_SETTINGS]["maintenance"]["completions"]["water_change"]}
    label = mixing.brand_info("nyos_pure")["label"]
    assert saved["wc:new"]["newWater"] == {"ppt": 35.2, "brand": label, "tempC": 25.3}, saved["wc:new"]
    assert saved["wc:typed"]["newWater"] == {"ppt": 34.8, "brand": label, "tempC": 25.3}, "typed ppt wins"
    # The panel's completions fire the done event, with the stamp on board.
    done = [e for e in hass.bus.events if e.event_type == integration.const.MAINTENANCE_DONE_EVENT]
    assert len(done) == 2 and all(e.data["task_id"] == "water_change" and e.data["source"] == "panel" for e in done)
    assert {e.data["newWater"]["ppt"] for e in done} == {35.2, 34.8}
    # A re-save of the same rows is not a new completion: no done event (the
    # config-updated event fires on every save and is not counted here).
    done_before = sum(1 for e in hass.bus.events if e.event_type == integration.const.MAINTENANCE_DONE_EVENT)
    run(integration.websocket_save_config(hass, FakeConnection(), {"id": 2, "config": copy.deepcopy(entry.options[CONF_SETTINGS])}))
    assert sum(1 for e in hass.bus.events if e.event_type == integration.const.MAINTENANCE_DONE_EVENT) == done_before
    # The AWC path: fresh water from the vessel carries ppt and brand (no sensor in hand).
    cfg = integration._config_from_entry(entry)
    integration._maintenance_log_awc_change(cfg, datetime.now(timezone.utc), 8.0, False, "")
    awc_row = cfg["maintenance"]["completions"]["water_change"][0]
    assert awc_row["source"] == "awc" and awc_row["newWater"] == {"ppt": 35.2, "brand": label}
    # No salt in the vessel: nothing is stamped.
    cfg["mixingStation"]["vessels"]["mix"]["contents"] = "rodi"
    assert integration._mixing_new_water_stamp(hass, cfg) == {}

def test_small_draws_keep_their_millilitres():
    # 0.7.159: a 57 ml culture top-up is a real draw. The guard floors timed
    # draws at 10 ml (below that the clock is switch latency, not water), the
    # status keeps the ml instead of rounding 0.057 up to "0.1 L", and the
    # sentence helper says "57 ml" not "0.057 L".
    assert mixing.format_litres(0.057) == "57 ml"
    assert mixing.format_litres(10) == "10 L"
    assert mixing.format_litres(2.5) == "2.5 L"
    assert mixing.format_litres(0) == "0 L"
    cfg = _cfg(rodi={"rateLph": 9.21, "fillCapMin": 240}, simulate=True)
    cfg["switches"] = {"rodiBooster": {"switchEntity": "switch.mix_booster"}}
    assert any("10 ml" in r for r in mixing.draw_guard_reasons(cfg, 0.005, "external"))
    assert mixing.draw_guard_reasons(cfg, 0.01, "external") == []
    assert mixing.draw_guard_reasons(cfg, 0.057, "external") == []
    # 57 ml at 9.21 L/h is ~22 s: half-way through, the status reads ml, not 0.0/0.1.
    live = _cfg(rodi={
        "rateLph": 9.21, "fillCapMin": 240,
        "draw": {"active": True, "litres": 0.057, "destination": "external",
                 "startedAt": _iso(NOW - timedelta(seconds=11)),
                 "endsAt": _iso(NOW + timedelta(seconds=11))}})
    status = mixing.rodi_status(live, NOW)["draw"]
    assert status["litres"] == 0.057
    assert status["litresDone"] == 0.028
    assert status["percent"] == 49.0
    assert status["minutesLeft"] == 0.0
    # The nearly-done heads-up is for runs long enough to want one: a
    # sub-litre draw gets no run-finish story (only a container story could apply).
    live["rodi"]["alertPct"] = 80
    assert mixing.draw_alert(live) is None


def test_small_draw_runs_end_to_end_and_the_ledgers_add_it_up():
    scheduler = install_scheduler(integration)
    hass, entry = _station(_rodi_over(rateLph=9.21))
    conn = FakeConnection()
    before = len(scheduler.scheduled)
    run(integration.websocket_mixing_rodi_draw(
        hass, conn, {"id": 1, "litres": 0.057, "destination": "store"}))
    assert conn.results[-1].payload["success"] is True, conn.results[-1].payload
    rodi = _mix_state(entry)["rodi"]
    assert rodi["draw"]["active"] is True and rodi["draw"]["litres"] == 0.057
    log = integration._config_from_entry(entry)["activity"][-1]["message"]
    assert "57 ml" in log and " s at 9.21 L/h" in log, log
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc)
    stops = [r for r in scheduler.scheduled[before:]
             if not r["cancelled"] and 15 < (r["run_at"] - now).total_seconds() < 30]
    assert len(stops) == 1, "expected one stop leg about 22 s out"

    async def _fire():
        await stops[0]["callback"](stops[0]["run_at"])
    run(_fire())
    state = _mix_state(entry)
    assert state["rodi"]["draw"]["active"] is False
    assert state["vessels"]["rodi"]["estimatedLitres"] == 40.06     # 40 anchor + 57 ml (2 dp)
    assert state["rodi"]["litresProcessed"] == 0.06                  # odometer keeps the ml too
    assert "57 ml" in integration._config_from_entry(entry)["activity"][-1]["message"]
    # A sub-10 ml ask is refused with a reason, never an error.
    run(integration.websocket_mixing_rodi_draw(
        hass, conn, {"id": 2, "litres": 0.004, "destination": "store"}))
    assert conn.results[-1].payload["success"] is False
    assert any("10 ml" in r for r in conn.results[-1].payload["reasons"])


# ---------------------------------------------------------------- §32 top-up + fill to full (0.7.187)

def test_fill_to_full_reads_the_vessel_shortfall():
    cfg = _cfg(simulate=True, rodi={"rateLph": 9.21, "fillCapMin": 240})
    cfg["vessels"]["mix"].update({"volumeLitres": 35, "estimatedLitres": 4.1, "contents": "salt"})
    assert mixing.fill_to_full_litres(cfg, "mix") == 30.9
    assert mixing.fill_to_full_litres(cfg, "store") == 10.0        # 40 of 50
    assert mixing.fill_to_full_litres(cfg, "external") == 0.0      # no level to fill to
    cfg["vessels"]["mix"]["volumeLitres"] = 0
    assert mixing.fill_to_full_litres(cfg, "mix") == 0.0           # unsized
    cfg["vessels"]["mix"].update({"volumeLitres": 35, "estimatedLitres": 60})
    assert mixing.fill_to_full_litres(cfg, "mix") == 0.0           # over-full anchor reads full


def test_to_full_guards_name_the_missing_piece():
    cfg = _cfg(simulate=True, rodi={"rateLph": 9.21, "fillCapMin": 240})
    cfg["vessels"]["mix"].update({"volumeLitres": 35, "estimatedLitres": 4.1, "contents": "rodi"})
    room = mixing.fill_to_full_litres(cfg, "mix")
    assert mixing.draw_guard_reasons(cfg, room, "mix", to_full=True) == []
    # No rate: the to-full flavour of the refusal points at the float valve.
    cfg["rodi"]["rateLph"] = 0
    reasons = mixing.draw_guard_reasons(cfg, room, "mix", to_full=True)
    assert any("float valve instead" in r for r in reasons), reasons
    cfg["rodi"]["rateLph"] = 9.21
    # A T-off has no level to fill to — and no "open-ended" reason on top.
    reasons = mixing.draw_guard_reasons(cfg, 0, "external", to_full=True)
    assert any("no level to fill to" in r for r in reasons), reasons
    assert not any("open-ended" in r for r in reasons)
    # An unsized vessel.
    cfg["vessels"]["mix"]["volumeLitres"] = 0
    assert any("needs to know the size" in r
               for r in mixing.draw_guard_reasons(cfg, 0, "mix", to_full=True))
    # Already full says so — and never trips the 10 ml floor.
    cfg["vessels"]["mix"].update({"volumeLitres": 35, "estimatedLitres": 35})
    reasons = mixing.draw_guard_reasons(
        cfg, mixing.fill_to_full_litres(cfg, "mix"), "mix", to_full=True)
    assert any("already stands full" in r for r in reasons), reasons
    assert not any("10 ml" in r for r in reasons)


def test_top_up_flag_lets_fresh_rodi_land_on_a_stored_batch():
    salty = _cfg(simulate=True, rodi={"rateLph": 120, "fillCapMin": 240})
    salty["vessels"]["mix"].update({"estimatedLitres": 30, "contents": "salt"})
    salty["batch"]["state"] = "storing"
    # Unflagged: still refused, and the refusal now names the way through.
    reasons = mixing.draw_guard_reasons(salty, 5, "mix")
    assert any("still holds mixed saltwater" in r and "top it up" in r for r in reasons), reasons
    assert any("top it up" in r for r in mixing.transfer_guard_reasons(salty, 5))
    # Flagged: the water may land — timed, open-ended, to full, or a transfer.
    assert mixing.draw_guard_reasons(salty, 5, "mix", top_up=True) == []
    assert mixing.draw_guard_reasons(salty, 0, "mix", top_up=True) == []
    assert mixing.draw_guard_reasons(salty, 20, "mix", top_up=True, to_full=True) == []
    assert mixing.transfer_guard_reasons(salty, 5, top_up=True) == []
    # The flag is a no-op on plain RODI.
    salty["vessels"]["mix"]["contents"] = "rodi"
    salty["batch"]["state"] = "idle"
    assert mixing.draw_guard_reasons(salty, 5, "mix", top_up=True) == []
    # The store is never a top-up.
    assert mixing.draw_guard_reasons(salty, 5, "store", top_up=True) == []


def test_mix_guard_lets_standing_saltwater_be_salted_back():
    cfg = _cfg()
    cfg["vessels"]["mix"].update({"estimatedLitres": 35, "contents": "salt", "freshLitres": 30.9})
    assert mixing.mix_guard_reasons(cfg) == []
    # ...and unfinished saltwater with nothing fresh on it (no new salt owed).
    cfg["vessels"]["mix"]["freshLitres"] = 0
    assert mixing.mix_guard_reasons(cfg) == []
    # An empty vessel still refuses.
    cfg["vessels"]["mix"].update({"estimatedLitres": 0, "contents": "empty"})
    assert any("no RODI water yet" in r for r in mixing.mix_guard_reasons(cfg))


def test_fresh_litres_ledger_reads_clamped_and_shows_in_levels():
    cfg = _cfg()
    cfg["vessels"]["mix"].update({"estimatedLitres": 20, "contents": "salt", "freshLitres": 30.9})
    assert mixing.mix_vessel_fresh_litres(cfg) == 20.0     # never more than the vessel holds
    assert mixing.vessel_levels(cfg)["mix"]["freshLitres"] == 20.0
    cfg["vessels"]["mix"]["freshLitres"] = "junk"
    assert mixing.mix_vessel_fresh_litres(cfg) == 0.0
    assert mixing.vessel_levels(_cfg())["mix"]["freshLitres"] == 0.0


def test_dose_guide_tells_the_topped_up_and_re_salt_stories():
    cfg = _cfg()
    cfg["vessels"]["mix"].update({"volumeLitres": 35, "estimatedLitres": 35,
                                  "contents": "salt", "freshLitres": 30.9})
    cfg["batch"] = {"state": "idle"}
    guide = mixing.summary(cfg, NOW)["doseGuide"]
    # Fresh water standing on the old batch is owed its salt — 30.9 L of it.
    assert guide["freshLitres"] == 30.9
    assert guide["fresh"] == mixing.salt_dose("nyos_pure", 30.9, 35)
    assert guide["topUp"] is None                       # brim full: nothing more to add
    # Short of full: the fresh story AND the rest-of-the-way projection stack.
    cfg["vessels"]["mix"].update({"estimatedLitres": 14.1, "freshLitres": 10})
    guide = mixing.summary(cfg, NOW)["doseGuide"]
    assert guide["fresh"] == mixing.salt_dose("nyos_pure", 10, 35)
    assert guide["topUpLitres"] == 20.9
    assert guide["topUp"] == mixing.salt_dose("nyos_pure", 20.9, 35)
    # Stored (tested) saltwater has no fresh story — the old top-up projection only.
    cfg["vessels"]["mix"].update({"estimatedLitres": 14.1, "freshLitres": 0})
    cfg["batch"] = {"state": "storing", "litres": 14.1}
    guide = mixing.summary(cfg, NOW)["doseGuide"]
    assert guide["fresh"] is None and guide["topUpLitres"] == 20.9
    # The run that follows doses only the fresh litres — and says so.
    cfg["vessels"]["mix"].update({"estimatedLitres": 35, "freshLitres": 0})
    cfg["batch"] = {"state": "salting", "litres": 35, "doseLitres": 30.9, "stageAt": _iso(NOW)}
    guide = mixing.summary(cfg, NOW)["doseGuide"]
    assert guide["run"] == mixing.salt_dose("nyos_pure", 30.9, 35)
    assert guide["runLitres"] == 35.0 and guide["runDoseLitres"] == 30.9
    assert guide["runTopUp"] is True and guide["fresh"] is None and guide["topUp"] is None
    # A re-salt with nothing fresh: no new salt, and the flag says so.
    cfg["batch"]["doseLitres"] = 0
    guide = mixing.summary(cfg, NOW)["doseGuide"]
    assert guide["run"]["available"] is False and guide["runTopUp"] is True
    # A run from before the field (nothing stamped) reads as a full dose.
    cfg["batch"] = {"state": "salting", "litres": 35, "stageAt": _iso(NOW)}
    guide = mixing.summary(cfg, NOW)["doseGuide"]
    assert guide["run"] == mixing.salt_dose("nyos_pure", 35, 35) and guide["runTopUp"] is False
    assert mixing.batch_state(cfg["batch"], cfg, NOW)["doseLitres"] == 35.0
    assert mixing.batch_state({"state": "salting", "litres": 35, "doseLitres": 30.9},
                              cfg, NOW)["doseLitres"] == 30.9


def test_rodi_status_carries_the_fill_stop_and_the_to_full_draw():
    cfg = _cfg(rodi={"rateLph": 9.21, "fillStop": "timed",
                     "draw": {"active": True, "litres": 30.9, "destination": "mix", "toFull": True,
                              "startedAt": _iso(NOW - timedelta(hours=1)),
                              "endsAt": _iso(NOW + timedelta(hours=2, minutes=21))}})
    status = mixing.rodi_status(cfg, NOW)
    assert status["fillStop"] == "timed"
    assert status["draw"]["toFull"] is True and status["draw"]["litres"] == 30.9
    assert status["draw"]["litresDone"] == 9.21
    plain = mixing.rodi_status(_cfg(rodi={"fillStop": "junk"}), NOW)
    assert plain["fillStop"] == "float" and plain["draw"] is None


def test_normalise_carries_fresh_litres_fill_stop_and_dose_litres():
    raw = _station_cfg(rodi={"rateLph": 9.21, "fillCapMin": 240, "fillStop": "timed",
                             "draw": {"active": True, "litres": 30.9, "destination": "mix",
                                      "toFull": True, "startedAt": _iso(NOW), "endsAt": _iso(NOW)}})
    raw["vessels"]["mix"].update({"volumeLitres": 35, "estimatedLitres": 20,
                                  "contents": "salt", "freshLitres": 30.9})
    raw["batch"] = {"state": "salting", "litres": 20, "doseLitres": 16, "stageAt": _iso(NOW)}
    cfg = integration._normalise_core_config({"mixingStation": raw})["mixingStation"]
    assert cfg["vessels"]["mix"]["freshLitres"] == 20.0     # clamped to the litres held
    assert cfg["rodi"]["fillStop"] == "timed"
    assert cfg["rodi"]["draw"]["toFull"] is True
    assert cfg["batch"]["doseLitres"] == 16.0
    # Idempotent: a second pass moves nothing.
    again = integration._normalise_core_config({"mixingStation": copy.deepcopy(cfg)})["mixingStation"]
    assert again == cfg
    # Fresh litres mean nothing on RODI contents; junk stops fall back to float;
    # a batch with nothing stamped was dosed for all its litres.
    raw["vessels"]["mix"]["contents"] = "rodi"
    raw["rodi"]["fillStop"] = "sideways"
    del raw["batch"]["doseLitres"]
    cfg = integration._normalise_core_config({"mixingStation": raw})["mixingStation"]
    assert cfg["vessels"]["mix"]["freshLitres"] == 0.0
    assert cfg["rodi"]["fillStop"] == "float"
    assert cfg["batch"]["doseLitres"] == 20.0
    # Defaults on a bare station: float valve, nothing owed, nothing to full.
    bare = integration._normalise_core_config({"mixingStation": _station_cfg()})["mixingStation"]
    assert bare["rodi"]["fillStop"] == "float" and bare["rodi"]["draw"]["toFull"] is False
    assert bare["vessels"]["mix"]["freshLitres"] == 0.0 and bare["batch"]["doseLitres"] == 0.0


def test_stale_save_guard_carries_the_fresh_litres():
    stored = {"mixingStation": {"vessels": {"mix": {"estimatedLitres": 35, "contents": "salt",
                                                    "freshLitres": 30.9, "volumeLitres": 35}}}}
    incoming = {"mixingStation": {"vessels": {"mix": {"estimatedLitres": 4.1, "contents": "salt",
                                                      "freshLitres": 0, "volumeLitres": 35}}}}
    integration._mixing_preserve_runtime(stored, incoming)
    mix_v = incoming["mixingStation"]["vessels"]["mix"]
    assert mix_v["freshLitres"] == 30.9 and mix_v["estimatedLitres"] == 35
    assert mix_v["volumeLitres"] == 35                       # the setting stays the client's


def _topped_station(**rodi_extra):
    """A 35 L vessel holding 4.1 L of tested, stored saltwater; rate known."""
    rodi = {"rateLph": 9.21, "fillCapMin": 240}
    rodi.update(rodi_extra)
    return _station({
        "rodi": rodi,
        "vessels": {"rodi": {"volumeLitres": 50, "estimatedLitres": 40, "levelSensorEntity": ""},
                    "mix": {"volumeLitres": 35, "estimatedLitres": 4.1, "contents": "salt",
                            "levelSensorEntity": ""}},
        "batch": _stored_batch(litres=4.1, loggedPpt=35.0),
    })


def _activity_tail(entry, n=4):
    """The n most recent Mixing station lines, NEWEST FIRST — the activity log
    inserts at the front, and the save pass drops a heartbeat in above them."""
    rows = [a["message"] for a in integration._config_from_entry(entry)["activity"]
            if str(a.get("message", "")).startswith("Mixing station")]
    return rows[:n]


def test_top_up_fill_by_the_rate_demotes_the_batch_and_credits_the_fresh_litres():
    scheduler = install_scheduler(integration)
    hass, entry = _topped_station()
    conn = FakeConnection()
    # Unflagged, the stored batch still refuses — with the way through named.
    run(integration.websocket_mixing_rodi_draw(
        hass, conn, {"id": 1, "litres": 0, "destination": "mix", "toFull": True}))
    payload = conn.results[-1].payload
    assert payload["success"] is False
    assert any("top it up" in r for r in payload["reasons"]), payload
    assert _mix_state(entry)["batch"]["state"] == "storing"
    # Flagged: the litres are the vessel's own shortfall, the batch leaves the
    # books before the first litre, the vessel keeps its water and its salt.
    before = len(scheduler.scheduled)
    run(integration.websocket_mixing_rodi_draw(
        hass, conn, {"id": 2, "litres": 0, "destination": "mix", "toFull": True, "topUp": True}))
    payload = conn.results[-1].payload
    assert payload["success"] is True, payload
    state = _mix_state(entry)
    assert state["rodi"]["draw"]["active"] is True
    assert state["rodi"]["draw"]["litres"] == 30.9 and state["rodi"]["draw"]["toFull"] is True
    assert state["batch"]["state"] == "idle" and state["batch"]["loggedPpt"] == 0
    assert state["vessels"]["mix"]["contents"] == "salt"
    assert state["vessels"]["mix"]["estimatedLitres"] == 4.1
    assert state["vessels"]["mix"]["freshLitres"] == 0        # nothing has landed yet
    assert ("turn_on", "switch.mix_booster") in _switch_calls(hass, "switch.mix_booster")
    log = _activity_tail(entry, 3)
    assert any("topping up the stored batch" in m for m in log), log
    assert any("30.9 L to full" in m and "by the rate" in m for m in log), log
    # The reply's summary already tells the top-up story to the panel.
    assert payload["summary"]["batch"]["status"] == "idle"
    assert payload["summary"]["rodi"]["draw"]["toFull"] is True
    # The AWC can no longer be vouched water from it.
    guard = mixing.awc_guard_reason(_mix_state(entry), 2, datetime.now(timezone.utc))
    assert guard is not None and "no ready saltwater batch" in guard["message"]
    # The stop leg lands at the shortfall's own ETA: 30.9 L at 9.21 L/h ≈ 201 min.
    now = datetime.now(timezone.utc)
    stops = [r for r in scheduler.scheduled[before:]
             if not r["cancelled"] and 195 * 60 < (r["run_at"] - now).total_seconds() < 207 * 60]
    assert len(stops) == 1, "expected one stop leg about 201 min out"

    async def _fire():
        await stops[0]["callback"](stops[0]["run_at"])
    run(_fire())
    state = _mix_state(entry)
    assert state["rodi"]["draw"]["active"] is False
    assert state["vessels"]["mix"]["estimatedLitres"] == 35.0
    assert state["vessels"]["mix"]["freshLitres"] == 30.9
    assert state["vessels"]["mix"]["contents"] == "salt"
    assert "full by the rate" in _activity_tail(entry, 1)[0]
    # The guide now tells the fresh story; the mix run doses the fresh litres only.
    guide = mixing.summary(_mix_state(entry), datetime.now(timezone.utc))["doseGuide"]
    assert guide["fresh"] == mixing.salt_dose("nyos_pure", 30.9, 35)
    run(integration.websocket_mixing_salt_stock(hass, conn, {"id": 3, "action": "set", "kg": 10}))
    run(integration.websocket_mixing_start_mix(hass, conn, {"id": 4}))
    assert conn.results[-1].payload.get("success") is not False, conn.results[-1].payload
    state = _mix_state(entry)
    assert state["batch"]["state"] == "heating"            # heat is on in the fixture
    assert state["batch"]["litres"] == 35.0 and state["batch"]["doseLitres"] == 30.9
    assert state["vessels"]["mix"]["freshLitres"] == 30.9   # still owed until the salt goes in
    assert any("30.9 L of it fresh RODI" in m for m in _activity_tail(entry, 2))
    run(integration.websocket_mixing_advance(hass, conn, {"id": 5}))
    state = _mix_state(entry)
    assert state["batch"]["state"] == "salting"
    assert state["batch"]["doseLitres"] == 30.9
    assert state["vessels"]["mix"]["freshLitres"] == 0       # the dose has been taken for it
    # Salt on hand: 30.9 L × 39 g/L ≈ 1205 g left the bucket, not a full 35 L batch.
    stock = state["saltStock"]
    assert stock["history"][-1]["note"] == "salted 30.9 L", stock["history"][-1]
    assert abs(stock["kg"] - (10.0 - 1.205)) < 0.01, stock
    guide = mixing.summary(state, datetime.now(timezone.utc))["doseGuide"]
    assert guide["runTopUp"] is True and guide["runDoseLitres"] == 30.9
    # Tested at target: a stored batch again, nothing fresh outstanding.
    run(integration.websocket_mixing_log_salinity(hass, conn, {"id": 6, "ppt": 35.0}))
    state = _mix_state(entry)
    assert state["batch"]["state"] == "ready" and state["vessels"]["mix"]["freshLitres"] == 0
    assert mixing.awc_guard_reason(state, 20, datetime.now(timezone.utc)) is None


def test_top_up_by_the_float_valve_credits_what_the_rate_says_landed():
    scheduler = install_scheduler(integration)
    hass, entry = _topped_station()
    conn = FakeConnection()
    run(integration.websocket_mixing_rodi_draw(
        hass, conn, {"id": 1, "litres": 0, "destination": "mix", "topUp": True}))
    assert conn.results[-1].payload["success"] is True, conn.results[-1].payload
    state = _mix_state(entry)
    assert state["rodi"]["draw"]["active"] is True and state["rodi"]["draw"]["litres"] == 0
    assert state["rodi"]["draw"]["toFull"] is False
    assert state["batch"]["state"] == "idle"
    # Keeper says done straight away: with a rate, the credit is rate × time
    # (≈ 0 here) — never a claimed "full" — so the fresh ledger stays honest.
    run(integration.websocket_mixing_rodi_stop(hass, conn, {"id": 2}))
    state = _mix_state(entry)
    assert state["rodi"]["draw"]["active"] is False
    assert state["vessels"]["mix"]["estimatedLitres"] == 4.1
    assert state["vessels"]["mix"]["freshLitres"] == 0
    # ...and the vessel is still mixable (a re-salt with nothing owed), never stuck.
    assert mixing.mix_guard_reasons(state) == []
    assert scheduler is not None


def test_transfer_top_up_demotes_and_credits_fresh_litres():
    install_scheduler(integration)
    hass, entry = _topped_station()
    conn = FakeConnection()
    run(integration.websocket_mixing_transfer(hass, conn, {"id": 1, "litres": 10}))
    assert conn.results[-1].payload["success"] is False
    assert _mix_state(entry)["batch"]["state"] == "storing"
    run(integration.websocket_mixing_transfer(hass, conn, {"id": 2, "litres": 10, "topUp": True}))
    assert conn.results[-1].payload["success"] is True, conn.results[-1].payload
    state = _mix_state(entry)
    assert state["batch"]["state"] == "idle"
    assert state["vessels"]["mix"]["estimatedLitres"] == 14.1
    assert state["vessels"]["mix"]["freshLitres"] == 10.0
    assert state["vessels"]["mix"]["contents"] == "salt"
    assert state["vessels"]["rodi"]["estimatedLitres"] == 30.0
    assert "topping up the old batch" in _activity_tail(entry, 1)[0]
    # A second top-up onto the (now idle) topped-up vessel simply adds up.
    run(integration.websocket_mixing_transfer(hass, conn, {"id": 3, "litres": 5, "topUp": True}))
    assert _mix_state(entry)["vessels"]["mix"]["freshLitres"] == 15.0
    # Dilution while salting never counts as fresh — the dose has gone in.
    hass2, entry2 = _station({
        "vessels": {"rodi": {"volumeLitres": 50, "estimatedLitres": 40, "levelSensorEntity": ""},
                    "mix": {"volumeLitres": 50, "estimatedLitres": 40, "contents": "salt",
                            "levelSensorEntity": ""}},
        "batch": {"state": "salting", "type": "salt", "litres": 40, "stageAt": _iso(NOW)}})
    run(integration.websocket_mixing_transfer(hass2, FakeConnection(), {"id": 1, "litres": 5}))
    assert _mix_state(entry2)["vessels"]["mix"]["freshLitres"] == 0
    assert _mix_state(entry2)["vessels"]["mix"]["estimatedLitres"] == 45.0


def test_retest_out_of_band_remixes_without_a_second_dose():
    install_scheduler(integration)
    hass, entry = _station({
        "vessels": {"rodi": {"volumeLitres": 50, "estimatedLitres": 40, "levelSensorEntity": ""},
                    "mix": {"volumeLitres": 50, "estimatedLitres": 40, "contents": "salt",
                            "levelSensorEntity": ""}},
        "batch": _stored_batch(loggedPpt=35.0),
        "saltStock": {"kg": 10.0, "bucketKg": 0, "updatedAt": _iso(NOW), "history": []}})
    conn = FakeConnection()
    run(integration.websocket_mixing_log_salinity(hass, conn, {"id": 1, "ppt": 33.0}))
    state = _mix_state(entry)
    assert state["batch"]["state"] == "salting"
    assert state["saltStock"]["kg"] == 10.0, "a re-mix must not debit a second full batch"
    assert not any("salted" in h["note"] for h in state["saltStock"]["history"])
    assert state["batch"]["doseLitres"] == 40.0          # the original dose, on record
    # The reply still carries the correction grams — the keeper's own dose.
    assert conn.results[-1].payload["correction"]["status"] == "low"


def test_level_correction_scales_the_fresh_litres_pro_rata():
    install_scheduler(integration)
    hass, entry = _station({
        "vessels": {"rodi": {"volumeLitres": 50, "estimatedLitres": 40, "levelSensorEntity": ""},
                    "mix": {"volumeLitres": 35, "estimatedLitres": 35, "contents": "salt",
                            "freshLitres": 30.9, "levelSensorEntity": ""}}})
    conn = FakeConnection()
    run(integration.websocket_mixing_set_level(hass, conn, {"id": 1, "vessel": "mix", "litres": 17.5}))
    assert _mix_state(entry)["vessels"]["mix"]["freshLitres"] == 15.45
    run(integration.websocket_mixing_set_level(hass, conn, {"id": 2, "vessel": "mix", "litres": 0}))
    mix_v = _mix_state(entry)["vessels"]["mix"]
    assert mix_v["freshLitres"] == 0 and mix_v["contents"] == "empty"


def test_stopping_heat_on_a_top_up_run_keeps_the_fresh_litres():
    install_scheduler(integration)
    hass, entry = _station({
        "vessels": {"rodi": {"volumeLitres": 50, "estimatedLitres": 40, "levelSensorEntity": ""},
                    "mix": {"volumeLitres": 35, "estimatedLitres": 35, "contents": "salt",
                            "freshLitres": 30.9, "levelSensorEntity": ""}}})
    conn = FakeConnection()
    run(integration.websocket_mixing_start_mix(hass, conn, {"id": 1}))
    assert _mix_state(entry)["batch"]["state"] == "heating"
    run(integration.websocket_mixing_abort(hass, conn, {"id": 2}))
    state = _mix_state(entry)
    assert state["batch"]["state"] == "idle" and state["batch"]["doseLitres"] == 0
    assert state["vessels"]["mix"]["contents"] == "salt"
    assert state["vessels"]["mix"]["freshLitres"] == 30.9
    assert "keeps its saltwater" in _activity_tail(entry, 1)[0]
    # Discarding from salting drains everything, fresh ledger included.
    run(integration.websocket_mixing_start_mix(hass, conn, {"id": 3}))
    run(integration.websocket_mixing_advance(hass, conn, {"id": 4}))
    assert _mix_state(entry)["vessels"]["mix"]["freshLitres"] == 0    # dosed
    run(integration.websocket_mixing_abort(hass, conn, {"id": 5}))
    mix_v = _mix_state(entry)["vessels"]["mix"]
    assert mix_v["contents"] == "empty" and mix_v["estimatedLitres"] == 0 and mix_v["freshLitres"] == 0


# ---------------------------------------------------------------- §33 the keeper's measure (0.7.188)

# (grams, label, ml, gramsPerMeasure) → the words. The panel suite runs the
# SAME rows through its JS mirror, so the two can never disagree.
MEASURE_TABLE = [
    (1205, "jug", 1000, 1100, "1 level jug + about 100 ml"),
    (1365, "jug", 1000, 1100, "1 level jug + about 240 ml"),
    (2200, "jug", 1000, 1100, "2 level jugs"),
    (47, "jug", 1000, 1100, "about 40 ml in your jug"),
    (3, "jug", 1000, 1100, "under 10 ml in your jug"),
    (1099, "jug", 1000, 1100, "1 level jug"),            # 999 ml rounds over into a whole jug
    (580, "beaker", 250, 290, "2 level beakers"),
    (600, "beaker", 250, 290, "2 level beakers + about 20 ml"),
    (1450, "glass", 250, 290, "5 level glasses"),
    (300, "box", 250, 290, "1 level box + about 10 ml"),
]


def test_salt_measure_info_weighed_or_estimated():
    assert mixing.salt_measure_info({"measure": {"mode": "grams"}}) is None
    assert mixing.salt_measure_info({}) is None
    est = mixing.salt_measure_info({"measure": {"mode": "measure", "label": "jug",
                                                "ml": 1000, "gramsPerMeasure": 0}})
    assert est == {"label": "jug", "ml": 1000.0, "gramsPerMeasure": 1100.0,
                   "gPerMl": 1.1, "estimated": True}
    weighed = mixing.salt_measure_info({"measure": {"mode": "measure", "label": "beaker",
                                                    "ml": 250, "gramsPerMeasure": 290}})
    assert weighed["gramsPerMeasure"] == 290.0 and weighed["estimated"] is False
    assert weighed["gPerMl"] == 1.16
    assert mixing.salt_measure_info({"measure": {"mode": "measure", "ml": 0}}) is None
    assert mixing.salt_measure_info({"measure": {"mode": "measure", "ml": 500,
                                                 "label": "  "}})["label"] == "measure"


def test_salt_in_measures_speaks_level_measures_and_millilitres():
    for grams, label, ml, g_each, text in MEASURE_TABLE:
        out = mixing.salt_in_measures(grams, {"label": label, "ml": ml,
                                              "gramsPerMeasure": g_each, "estimated": False})
        assert out["text"] == text, (grams, label, ml, g_each, out)
    out = mixing.salt_in_measures(1365, {"label": "jug", "ml": 1000, "gramsPerMeasure": 1100,
                                         "estimated": True})
    assert out["wholes"] == 1 and out["remainderMl"] == 240 and out["totalMl"] == 1241
    assert out["estimated"] is True
    # Nothing to say without grams or a measure.
    assert mixing.salt_in_measures(None, {"ml": 1000, "gramsPerMeasure": 1100}) is None
    assert mixing.salt_in_measures(0, {"ml": 1000, "gramsPerMeasure": 1100}) is None
    assert mixing.salt_in_measures(100, None) is None
    assert mixing.salt_in_measures(100, {"ml": 1000, "gramsPerMeasure": 0}) is None
    assert mixing.plural_measure("jug", 1) == "jug" and mixing.plural_measure("jug", 2) == "jugs"
    assert mixing.plural_measure("glass", 3) == "glasses" and mixing.plural_measure("dish", 2) == "dishes"


def test_summary_hands_every_dose_its_measure():
    cfg = _cfg()
    cfg["salt"]["measure"] = {"mode": "measure", "label": "jug", "ml": 1000, "gramsPerMeasure": 1100}
    cfg["vessels"]["mix"].update({"volumeLitres": 50, "estimatedLitres": 15, "contents": "salt"})
    cfg["batch"] = {"state": "ready", "litres": 15}
    s = mixing.summary(cfg, NOW)
    assert s["saltMeasure"] == {"label": "jug", "ml": 1000.0, "gramsPerMeasure": 1100.0,
                                "gPerMl": 1.1, "estimated": False}
    full = s["doseGuide"]["full"]
    assert full["grams"] == 1950 and full["measure"]["text"] == "1 level jug + about 770 ml"
    assert s["doseGuide"]["topUp"]["measure"]["text"] == "1 level jug + about 240 ml"
    assert s["dose"]["measure"]["text"] == "about 530 ml in your jug"     # 15 L → 585 g
    # The fresh and run stories carry it too.
    cfg["vessels"]["mix"].update({"estimatedLitres": 50, "freshLitres": 35})
    cfg["batch"] = {"state": "idle"}
    assert mixing.summary(cfg, NOW)["doseGuide"]["fresh"]["measure"]["text"] == "1 level jug + about 240 ml"
    cfg["batch"] = {"state": "salting", "litres": 50, "doseLitres": 35, "stageAt": _iso(NOW)}
    assert mixing.summary(cfg, NOW)["doseGuide"]["run"]["measure"]["text"] == "1 level jug + about 240 ml"
    # Grams keepers: no measure key anywhere — old readers and old equality hold.
    del cfg["salt"]["measure"]
    s = mixing.summary(cfg, NOW)
    assert s["saltMeasure"] is None
    assert "measure" not in s["doseGuide"]["full"] and "measure" not in s["dose"]
    # A custom brand with no g/L: no grams, so no measure either — never a guess.
    cfg["salt"].update({"brand": "custom", "customGPerL": 0,
                        "measure": {"mode": "measure", "label": "jug", "ml": 1000}})
    s = mixing.summary(cfg, NOW)
    assert s["doseGuide"]["full"]["available"] is False and s["doseGuide"]["full"]["measure"] is None
    assert s["saltMeasure"]["estimated"] is True


def test_normalise_salt_measure_block():
    raw = _station_cfg()
    raw["salt"]["measure"] = {"mode": "measure", "label": "  Big jug of doom, very long indeed  ",
                              "ml": "750", "gramsPerMeasure": -5}
    m = integration._normalise_core_config({"mixingStation": raw})["mixingStation"]["salt"]["measure"]
    assert m["mode"] == "measure" and m["ml"] == 750 and m["gramsPerMeasure"] == 0
    assert m["label"] == "Big jug of doom, very lo" and len(m["label"]) == 24
    bare = integration._normalise_core_config({"mixingStation": _station_cfg()})["mixingStation"]
    assert bare["salt"]["measure"] == {"mode": "grams", "label": "jug", "ml": 1000, "gramsPerMeasure": 0}
    raw["salt"]["measure"] = {"mode": "cups", "ml": 999999, "gramsPerMeasure": "290.26"}
    m = integration._normalise_core_config({"mixingStation": raw})["mixingStation"]["salt"]["measure"]
    assert m["mode"] == "grams" and m["ml"] == 5000 and m["gramsPerMeasure"] == 290.3
    # Idempotent.
    cfg = integration._normalise_core_config({"mixingStation": raw})["mixingStation"]
    again = integration._normalise_core_config({"mixingStation": copy.deepcopy(cfg)})["mixingStation"]
    assert again["salt"] == cfg["salt"]


def test_correction_reply_speaks_the_measure():
    install_scheduler(integration)
    salt = {"brand": "nyos_pure", "targetPpt": 35.0, "mixHours": 0, "customGPerL": 0,
            "measure": {"mode": "measure", "label": "jug", "ml": 1000, "gramsPerMeasure": 1100}}
    hass, entry = _station({"batch": {"state": "salting", "type": "salt", "litres": 40,
                                      "stageAt": _iso(NOW)}, "salt": salt})
    conn = FakeConnection()
    run(integration.websocket_mixing_log_salinity(hass, conn, {"id": 1, "ppt": 33.0}))
    c = conn.results[-1].payload["correction"]
    assert c["addGrams"] == 89.0
    assert c["addMeasure"]["text"] == "about 80 ml in your jug"
    assert conn.results[-1].payload["summary"]["saltMeasure"]["label"] == "jug"
    # Too salty: dilution needs no salt, so no measure.
    run(integration.websocket_mixing_log_salinity(hass, conn, {"id": 2, "ppt": 37.0}))
    c = conn.results[-1].payload["correction"]
    assert c["status"] == "high" and c["addMeasure"] is None
    # A grams keeper gets the key, empty — the panel reads it as nothing.
    hass2, entry2 = _station({"batch": {"state": "salting", "type": "salt", "litres": 40,
                                        "stageAt": _iso(NOW)}})
    conn2 = FakeConnection()
    run(integration.websocket_mixing_log_salinity(hass2, conn2, {"id": 1, "ppt": 33.0}))
    assert conn2.results[-1].payload["correction"]["addMeasure"] is None


# ---------------------------------------------------------------- §35 mix now (0.7.190)

def test_stir_guards_want_a_quiet_finished_batch_and_a_pump():
    cfg = _cfg()
    cfg["switches"] = {"mixPumpA": {"switchEntity": "switch.pump_a"}}
    cfg["batch"] = _stored_batch()
    assert mixing.stir_guard_reasons(cfg, NOW) == []
    cfg["batch"]["state"] = "ready"
    assert mixing.stir_guard_reasons(cfg, NOW) == []
    cfg["batch"]["circulateUntil"] = _iso(NOW + timedelta(minutes=4, seconds=40))
    reasons = mixing.stir_guard_reasons(cfg, NOW)
    assert any("already stirring" in r and "5 min left" in r for r in reasons), reasons
    cfg["batch"] = {"state": "salting"}
    assert any("mix run is under way" in r for r in mixing.stir_guard_reasons(cfg, NOW))
    cfg["batch"] = {"state": "heating"}
    assert any("mix run is under way" in r for r in mixing.stir_guard_reasons(cfg, NOW))
    cfg["batch"] = {"state": "idle"}
    assert any("Nothing to stir" in r for r in mixing.stir_guard_reasons(cfg, NOW))
    cfg["batch"] = _stored_batch()
    cfg["switches"] = {"mixPumpB": {"switchEntity": "switch.pump_b"}}
    assert mixing.stir_guard_reasons(cfg, NOW) == []          # one pump is enough
    cfg["switches"] = {}
    assert any("Bind a mixing pump plug" in r for r in mixing.stir_guard_reasons(cfg, NOW))
    cfg["simulate"] = True
    assert mixing.stir_guard_reasons(cfg, NOW) == []
    cfg["enabled"] = False
    assert any("not enabled" in r for r in mixing.stir_guard_reasons(cfg, NOW))


def test_batch_state_says_how_long_the_stir_has_left():
    cfg = _cfg()
    burst = mixing.batch_state(
        _stored_batch(circulateUntil=_iso(NOW + timedelta(minutes=7, seconds=20))), cfg, NOW)
    assert burst["circulating"] is True and burst["stirMinutesLeft"] == 7.0
    quiet = mixing.batch_state(_stored_batch(), cfg, NOW)
    assert quiet["circulating"] is False and quiet["stirMinutesLeft"] is None
    assert "stirMinutesLeft" not in mixing.batch_state({"state": "idle"}, cfg, NOW)


def _fire_record(record):
    async def _go():
        await record["callback"](record["run_at"])
    run(_go())


def test_mix_now_runs_a_burst_and_the_schedule_retimes_from_it():
    scheduler = install_scheduler(integration)
    now = datetime.now(timezone.utc)
    # A ready batch with its first scheduled stir an hour out.
    hass, entry = _station({"batch": _stored_batch(
        state="ready", nextCirculateAt=(now + timedelta(hours=1)).isoformat())})

    async def _arm():
        await integration._async_schedule_mixing_circulation(
            hass, entry, integration._config_from_entry(entry))
    run(_arm())
    armed_start = next(r for r in scheduler.scheduled if not r["cancelled"])
    conn = FakeConnection()
    before = len(scheduler.scheduled)
    run(integration.websocket_mixing_stir_now(hass, conn, {"id": 1}))
    payload = conn.results[-1].payload
    assert payload.get("success") is not False, payload
    assert ("turn_on", "switch.mix_pump_a") in _switch_calls(hass, "switch.mix_pump_a")
    assert ("turn_on", "switch.mix_pump_b") in _switch_calls(hass, "switch.mix_pump_b")
    batch = _mix_state(entry)["batch"]
    assert batch["state"] == "storing"          # the first stir is the ready→storing edge
    assert batch["circulateUntil"] and batch["nextCirculateAt"] == ""
    assert payload["summary"]["batch"]["circulating"] is True
    assert payload["summary"]["batch"]["stirMinutesLeft"] == 10.0
    assert armed_start["cancelled"], "the scheduled start leg must be superseded by the stop leg"
    log = _activity_tail(entry, 1)[0]
    assert "stirring now" in log and "re-times from this one" in log, log
    # A second tap while stirring is refused with the minutes left, never an error.
    run(integration.websocket_mixing_stir_now(hass, conn, {"id": 2}))
    assert conn.results[-1].payload["success"] is False
    assert any("already stirring" in r for r in conn.results[-1].payload["reasons"])
    # The stop leg lands ~10 min out; firing it re-anchors the cadence from THIS stir.
    stop = next(r for r in scheduler.scheduled[before:]
                if not r["cancelled"]
                and 9 * 60 < (r["run_at"] - datetime.now(timezone.utc)).total_seconds() < 11 * 60)
    _fire_record(stop)
    assert ("turn_off", "switch.mix_pump_a") in _switch_calls(hass, "switch.mix_pump_a")
    batch = _mix_state(entry)["batch"]
    assert batch["circulateUntil"] == "" and batch["lastCirculatedAt"]
    hours_out = (datetime.fromisoformat(batch["nextCirculateAt"])
                 - datetime.now(timezone.utc)).total_seconds() / 3600.0
    assert 5.9 < hours_out < 6.1


def test_mix_now_with_circulation_off_is_a_one_off_and_refuses_elsewhere():
    scheduler = install_scheduler(integration)
    hass, entry = _station({"batch": _stored_batch(),
                            "storage": {"circulateEveryH": 0, "circulateForMin": 15,
                                        "retestAfterDays": 7}})
    conn = FakeConnection()
    before = len(scheduler.scheduled)
    run(integration.websocket_mixing_stir_now(hass, conn, {"id": 1}))
    assert conn.results[-1].payload.get("success") is not False, conn.results[-1].payload
    assert "one-off" in _activity_tail(entry, 1)[0]
    stop = next(r for r in scheduler.scheduled[before:]
                if not r["cancelled"]
                and 14 * 60 < (r["run_at"] - datetime.now(timezone.utc)).total_seconds() < 16 * 60)
    _fire_record(stop)
    batch = _mix_state(entry)["batch"]
    assert batch["circulateUntil"] == "" and batch["nextCirculateAt"] == ""
    assert ("turn_off", "switch.mix_pump_b") in _switch_calls(hass, "switch.mix_pump_b")
    # Not on an idle vessel, and not mid-mix — refused with a reason.
    hass2, entry2 = _station()
    conn2 = FakeConnection()
    run(integration.websocket_mixing_stir_now(hass2, conn2, {"id": 1}))
    assert conn2.results[-1].payload["success"] is False
    assert any("Nothing to stir" in r for r in conn2.results[-1].payload["reasons"])
    hass3, entry3 = _station({"batch": {"state": "salting", "type": "salt", "litres": 40,
                                        "stageAt": _iso(NOW)}})
    conn3 = FakeConnection()
    run(integration.websocket_mixing_stir_now(hass3, conn3, {"id": 1}))
    assert conn3.results[-1].payload["success"] is False
    assert any("mix run is under way" in r for r in conn3.results[-1].payload["reasons"])
    assert _mix_state(entry3)["batch"]["state"] == "salting"


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
