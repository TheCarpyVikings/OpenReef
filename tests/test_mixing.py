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
