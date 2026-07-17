"""Dosing channels — orchestration: normaliser clamps, write-then-verify sync,
AWC suspend hooks, the 60 s tick (accounting, rollover, missed doses), the pH
mirror, and the WebSocket command surface.

Exercises the REAL orchestration in ``__init__.py`` with HA stubbed (``_ha_stubs``)
+ faked (``_fake_ha``). The verify timer is driven via ``install_scheduler``;
``dt_util`` is replaced with a fixed clock (the stub's universal object doesn't do
arithmetic).

Run standalone:  python3 tests/test_dosing_sync.py
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

from _fake_ha import FakeConnection, FakeEntry, FakeHass, install_scheduler, run  # noqa: E402

CONF_SETTINGS = integration.CONF_SETTINGS

NOW_LOCAL = datetime(2026, 1, 1, 12, 0, 0)
NOW_UTC = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class _FixedDt:
    """dt_util replacement: fixed, real datetimes (the stub's _Universal can't be
    multiplied); any other attribute stays lenient."""

    def now(self):
        return NOW_LOCAL

    def utcnow(self):
        return NOW_UTC

    def __getattr__(self, name):
        return _ha_stubs._Universal()


integration.dt_util = _FixedDt()

ENTITIES = {
    "doseVolumeNumber": "number.kalk_dose_volume",
    "doseIntervalNumber": "number.kalk_dose_interval",
    "nightIntervalNumber": "number.kalk_night_interval",
    "maxDailyNumber": "number.kalk_max_daily",
    "windowStartNumber": "number.kalk_window_start",
    "windowEndNumber": "number.kalk_window_end",
    "nightStartNumber": "number.kalk_night_start",
    "nightEndNumber": "number.kalk_night_end",
    "stepsPerMlNumber": "number.kalk_steps_per_ml",
    "phStopNumber": "number.kalk_ph_stop",
    "phResumeNumber": "number.kalk_ph_resume",
    "manualDoseMlNumber": "number.kalk_manual_dose",
    "enabledSwitch": "switch.kalk_enabled",
    "haSuspendSwitch": "switch.kalk_ha_suspend",
    "phGuardSwitch": "switch.kalk_ph_guard",
    "primeButton": "button.kalk_prime",
    "doseNowButton": "button.kalk_dose_now",
    "manualDoseButton": "button.kalk_manual_dose_btn",
    "calibrateButton": "button.kalk_calibrate",
    "dosedTodaySensor": "sensor.kalk_dosed_today",
    "reservoirLowSensor": "binary_sensor.kalk_reservoir_low",
}

_STATES = {
    **{ent: "0" for role, ent in ENTITIES.items() if ent.startswith("number.")},
    **{ent: "off" for role, ent in ENTITIES.items() if ent.startswith("switch.")},
    **{ent: "idle" for role, ent in ENTITIES.items() if ent.startswith("button.")},
    "sensor.kalk_dosed_today": "0.0",
    "binary_sensor.kalk_reservoir_low": "off",
    "sensor.tank_ph": "8.10",
}


def _channel(chemical="kalk", **over):
    ch = {
        "name": "Kalk",
        "chemical": chemical,
        "enabled": True,
        "driver": {"type": "openreef_esphome_stepper", "entities": dict(ENTITIES)},
        "schedule": {"enabled": True, "mlPerDay": 300, "mode": "continuous",
                     "windowStart": "00:00", "windowEnd": "00:00"},
        "guards": {"phEntity": "sensor.tank_ph", "phPauseAbove": 8.45, "phResumeBelow": 8.30,
                   "maxPerDoseMl": 10},
        "reservoir": {"volumeMl": 5000, "remainingMl": 5000, "lowThresholdMl": 500},
        "calibration": {"stepsPerMl": 11851, "measuredMl": 27,
                        "calibratedAt": NOW_UTC.isoformat()},
    }
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(ch.get(key), dict):
            ch[key].update(value)
        else:
            ch[key] = value
    return ch


def _entry(channels=None, awc_state=None):
    cfg = {"dosing": {"enabled": True, "channels": channels if channels is not None else {"kalk": _channel()}}}
    if awc_state is not None:
        cfg["automaticWaterChange"] = {"enabled": True, "state": awc_state}
    return FakeEntry(options={CONF_SETTINGS: integration._normalise_core_config(cfg)})


def _hass(entry, states=None):
    return FakeHass(states={**_STATES, **(states or {})}, entries=[entry])


def _saved_channel(entry, cid="kalk"):
    return entry.options[CONF_SETTINGS]["dosing"]["channels"][cid]


def _calls(hass, domain, service):
    return [c for c in hass.services.calls if c.domain == domain and c.service == service]


def _seed_midnight_baseline(hass, entry, cid="kalk"):
    """Anchor the missed-dose baseline at midnight (the tick otherwise anchors a
    newly-seen plan at 'now', which is exactly the false-alarm protection)."""
    config = entry.options[CONF_SETTINGS]
    channel = config["dosing"]["channels"][cid]
    plan = integration.dosing_engine.compile_schedule(channel, None, NOW_LOCAL)["plan"]
    fp = integration._dosing_plan_fingerprint(channel, plan)
    hass.data.setdefault(integration.DOMAIN, {}).setdefault(
        integration.DOSING_RUNTIME, {}
    ).setdefault("channels", {})[cid] = {"planFp": fp, "baselineMinute": 0, "baselineMl": 0.0}


# --------------------------------------------------------------------------- #
# Normaliser
# --------------------------------------------------------------------------- #
def test_normaliser_clamps_and_defaults():
    entry = _entry(channels={"kalk": _channel(
        chemical="plutonium",
        schedule={"mlPerDay": 999999, "mode": "warp"},
        guards={"phPauseAbove": 8.45, "phResumeBelow": 8.44},
        reservoir={"volumeMl": 9e9, "remainingMl": 9e9},
    )})
    ch = _saved_channel(entry)
    assert ch["chemical"] == "other"
    assert ch["schedule"]["mlPerDay"] == 5000.0
    assert ch["schedule"]["mode"] == "continuous"
    # The hysteresis invariant: resume always sits below pause (8.44 → clamped 8.40).
    assert ch["guards"]["phResumeBelow"] == 8.40
    assert ch["guards"]["phResumeBelow"] < ch["guards"]["phPauseAbove"]
    assert ch["reservoir"]["volumeMl"] == 50000.0
    assert ch["reservoir"]["remainingMl"] <= ch["reservoir"]["volumeMl"]
    assert ch["wear"]["tubeLifeHours"] == 1000.0
    assert ch["sync"]["state"] == "unsynced"
    assert set(ch["driver"]["entities"]) == set(
        integration.DOSING_BINDING_ROLES + integration.DOSING_BRUSHED_BINDING_ROLES)


def test_normaliser_caps_channel_count_and_drops_junk():
    channels = {f"ch{i}": _channel(chemical="alk") for i in range(12)}
    channels["junk"] = "not a dict"
    entry = _entry(channels=channels)
    saved = entry.options[CONF_SETTINGS]["dosing"]["channels"]
    assert len(saved) <= integration.DOSING_MAX_CHANNELS
    assert "junk" not in saved


def test_normaliser_preserves_calibration_history():
    entry = _entry(channels={"kalk": _channel(calibration={
        "stepsPerMl": 11851, "history": [{"stepsPerMl": 11851, "measuredMl": 27, "calibratedAt": "x"}] * 15,
    })})
    assert len(_saved_channel(entry)["calibration"]["history"]) == integration.DOSING_CAL_HISTORY_MAX


# --------------------------------------------------------------------------- #
# AWC suspend predicate + hooks
# --------------------------------------------------------------------------- #
def test_dosing_awc_suspended_predicate():
    entry = _entry(awc_state={"status": "draining"})
    assert integration._dosing_awc_suspended(entry.options[CONF_SETTINGS]) is True
    entry = _entry(awc_state={"status": "idle"})
    assert integration._dosing_awc_suspended(entry.options[CONF_SETTINGS]) is False
    holdoff = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    entry = _entry(awc_state={"status": "idle", "atoSuspendedUntil": holdoff})
    assert integration._dosing_awc_suspended(entry.options[CONF_SETTINGS]) is True


def test_awc_suspend_hook_flips_firmware_switch():
    entry = _entry()
    hass = _hass(entry)
    config = entry.options[CONF_SETTINGS]
    run(integration._async_dosing_awc_suspend(hass, config, True, None))
    assert hass.states.get("switch.kalk_ha_suspend").state == "on"
    run(integration._async_dosing_awc_suspend(hass, config, False, None))
    assert hass.states.get("switch.kalk_ha_suspend").state == "off"


def test_awc_suspend_hook_respects_optout():
    entry = _entry(channels={"kalk": _channel(guards={"suspendDuringAwc": False})})
    hass = _hass(entry)
    run(integration._async_dosing_awc_suspend(hass, entry.options[CONF_SETTINGS], True, None))
    assert hass.states.get("switch.kalk_ha_suspend").state == "off"


# --------------------------------------------------------------------------- #
# Sync: write-then-verify
# --------------------------------------------------------------------------- #
def test_sync_writes_verify_and_mark_synced():
    entry = _entry()
    hass = _hass(entry)
    scheduler = install_scheduler(integration)
    run(integration._async_dosing_sync_pass(hass, entry))
    # Numbers were written (the fake mirrors them into state)...
    assert hass.states.get("number.kalk_dose_volume").state == "2.08"
    assert hass.states.get("number.kalk_steps_per_ml").state == "11851.0"
    # ...enable switch goes on (calibrated + pH bound), pH guard switch follows the binding.
    assert hass.states.get("switch.kalk_enabled").state == "on"
    assert hass.states.get("switch.kalk_ph_guard").state == "on"
    # The verify timer is armed; firing it lands the terminal synced state.
    assert scheduler.pending()
    run(scheduler.fire_all())
    saved = _saved_channel(entry)
    assert saved["sync"]["state"] == "synced"
    assert saved["sync"]["lastSyncedAt"]
    assert saved["calibration"]["syncedToDevice"] is True


def test_sync_device_offline_parks_pending_writes():
    entry = _entry()
    hass = FakeHass(states={"sensor.tank_ph": "8.10"}, entries=[entry])  # no doser entities at all
    install_scheduler(integration)
    run(integration._async_dosing_sync_pass(hass, entry))
    saved = _saved_channel(entry)
    assert saved["sync"]["state"] == "offline"
    assert saved["sync"]["pendingWrites"]


def test_sync_verify_failure_is_loud_never_silent():
    entry = _entry()
    hass = _hass(entry)
    hass.services._states = None  # device "accepts" calls but nothing sticks
    scheduler = install_scheduler(integration)
    run(integration._async_dosing_sync_pass(hass, entry))
    run(scheduler.fire_all())  # verify #1 → mismatch → one retry, re-armed
    run(scheduler.fire_all())  # verify #2 → still mismatched → failed + notification
    saved = _saved_channel(entry)
    assert saved["sync"]["state"] == "failed"
    notes = _calls(hass, "persistent_notification", "create")
    assert any("sync failed" in str(c.data).lower() for c in notes)


# --------------------------------------------------------------------------- #
# pH mirror
# --------------------------------------------------------------------------- #
def test_ph_mirror_publishes_and_fails_closed():
    entry = _entry()
    hass = _hass(entry)
    integration._dosing_publish_mirror(hass, "sensor.tank_ph")
    mirror = hass.states.get(integration.DOSING_PH_MIRROR_ENTITY)
    assert mirror.state == "8.100"
    hass.states.set("sensor.tank_ph", "unavailable")
    integration._dosing_publish_mirror(hass, "sensor.tank_ph")
    assert hass.states.get(integration.DOSING_PH_MIRROR_ENTITY).state == "unavailable"


def test_ph_mirror_source_is_first_kalk_channel():
    entry = _entry()
    config = entry.options[CONF_SETTINGS]
    assert integration._dosing_mirror_source(config) == "sensor.tank_ph"
    entry = _entry(channels={"alk": _channel(chemical="alk")})
    assert integration._dosing_mirror_source(entry.options[CONF_SETTINGS]) == ""


# --------------------------------------------------------------------------- #
# Tick: accounting, rollover, missed doses
# --------------------------------------------------------------------------- #
def test_tick_rollover_at_noon_is_anomalous_no_log_no_alarm():
    # R16: a reset far from midnight (tz-skewed doser, NVS wipe) must not append
    # a bogus dated-yesterday rollup, and the missed baseline anchors at NOW so
    # no phantom "missed 150 ml" alarm follows.
    entry = _entry(channels={"kalk": _channel(state={"lastSensorMl": 280.0})})
    hass = _hass(entry, states={"sensor.kalk_dosed_today": "2.08"})
    install_scheduler(integration)
    run(integration._async_dosing_tick(hass, entry))
    run(integration._async_dosing_tick(hass, entry))
    saved = _saved_channel(entry)
    assert saved["dailyLog"] == [], "anomalous reset must not log a rollup"
    assert saved["state"]["rolloverAnomaly"] is True
    assert not saved["state"].get("missedSince"), "baseline must anchor at now"


def test_tick_rollover_near_midnight_logs_and_reconciles_blind_window():
    # Near-midnight reset: rollup appended, and the pre-midnight blind window
    # (doses between the last sample and the reset) reconciled into the ledgers
    # (R34) — deliveredMl covers prev + the plan-bounded gap.
    class _MidnightDt(_FixedDt):
        def now(self):
            return datetime(2026, 1, 2, 0, 30, 0)

    original_dt = integration.dt_util
    integration.dt_util = _MidnightDt()
    try:
        entry = _entry(channels={"kalk": _channel(
            state={"lastSensorMl": 280.0, "lastSensorAt": NOW_UTC.isoformat()})})
        hass = _hass(entry, states={"sensor.kalk_dosed_today": "2.08"})
        install_scheduler(integration)
        run(integration._async_dosing_tick(hass, entry))
        saved = _saved_channel(entry)
        assert saved["dailyLog"], "near-midnight rollover must append the rollup"
        entry_row = saved["dailyLog"][0]
        assert entry_row["deliveredMl"] >= 280.0
        assert entry_row["deliveredMl"] <= 375.0  # never past the auto daily cap
        assert saved["state"]["rolloverAnomaly"] is False
        # The blind-window gap is debited from the reservoir along with the delta.
        assert saved["reservoir"]["remainingMl"] < 5000.0 - (entry_row["deliveredMl"] - 280.0)
    finally:
        integration.dt_util = original_dt


def test_tick_missed_doses_alert_after_debounce():
    # Baseline anchored at midnight, sensor stuck at 0 → by noon the trajectory says
    # ~150 ml expected. Two consecutive ticks (debounce) latch the missed state.
    entry = _entry()
    hass = _hass(entry)
    install_scheduler(integration)
    _seed_midnight_baseline(hass, entry)
    run(integration._async_dosing_tick(hass, entry))
    run(integration._async_dosing_tick(hass, entry))
    saved = _saved_channel(entry)
    assert saved["state"]["missedSince"], "missed state must latch after two ticks"
    assert saved["state"]["missedMl"] > 100
    notes = _calls(hass, "persistent_notification", "create")
    assert any("missed" in str(c.data).lower() for c in notes)


def test_tick_sensor_unavailable_never_accrues_missed():
    # The doser keeps dosing autonomously through HA/network blips — an unreadable
    # sensor must never turn into a "missed doses" alarm (review finding).
    entry = _entry()
    hass = _hass(entry, states={"sensor.kalk_dosed_today": "unavailable"})
    install_scheduler(integration)
    _seed_midnight_baseline(hass, entry)
    run(integration._async_dosing_tick(hass, entry))
    run(integration._async_dosing_tick(hass, entry))
    saved = _saved_channel(entry)
    assert not saved["state"].get("missedSince")
    assert not any("missed" in str(c.data).lower()
                   for c in _calls(hass, "persistent_notification", "create"))


def test_tick_midday_plan_change_anchors_baseline_at_now():
    # First sight of a plan anchors expectations at 'now' — a schedule edited at
    # noon must not owe the whole morning (review finding). No baseline seeding.
    entry = _entry()
    hass = _hass(entry)
    install_scheduler(integration)
    run(integration._async_dosing_tick(hass, entry))
    run(integration._async_dosing_tick(hass, entry))
    saved = _saved_channel(entry)
    assert not saved["state"].get("missedSince")


def test_tick_first_observation_establishes_baseline_without_debit():
    # A brand-new channel bound to a doser that already dosed 150 ml today must not
    # one-shot-debit the reservoir by 150 ml (review finding).
    entry = _entry()
    hass = _hass(entry, states={"sensor.kalk_dosed_today": "150.0"})
    install_scheduler(integration)
    run(integration._async_dosing_tick(hass, entry))
    saved = _saved_channel(entry)
    assert saved["reservoir"]["remainingMl"] == 5000.0
    assert saved["wear"]["runSeconds"] == 0.0


def test_tick_recalibration_due_nags_and_respects_toggle():
    stale = (NOW_UTC - timedelta(days=90)).isoformat()
    entry = _entry(channels={"kalk": _channel(calibration={"stepsPerMl": 11851, "calibratedAt": stale})})
    hass = _hass(entry)
    install_scheduler(integration)
    run(integration._async_dosing_tick(hass, entry))
    notes = _calls(hass, "persistent_notification", "create")
    assert any("recalibrate" in str(c.data).lower() for c in notes)
    # The calibrationDue family toggle silences it.
    cfg = {"dosing": {"enabled": True, "notifications": {"calibrationDue": False},
                      "channels": {"kalk": _channel(calibration={"stepsPerMl": 11851, "calibratedAt": stale})}}}
    entry2 = FakeEntry(options={CONF_SETTINGS: integration._normalise_core_config(cfg)})
    hass2 = _hass(entry2)
    run(integration._async_dosing_tick(hass2, entry2))
    assert not any("recalibrate" in str(c.data).lower()
                   for c in _calls(hass2, "persistent_notification", "create"))


def test_normaliser_notifications_families_default_on():
    entry = _entry()
    notifications = entry.options[CONF_SETTINGS]["dosing"]["notifications"]
    assert notifications == {
        "missedDose": True, "reservoirLow": True, "tubeLife": True,
        "calibrationDue": True, "syncIssues": True, "staleFood": True,
    }


def test_tick_accumulates_wear_and_reservoir_on_flush():
    # lastSensorAt set ⇒ this is a known channel (not first observation), so the
    # 0 → 10 ml delta debits the ledgers and the first-tick flush persists them.
    entry = _entry(channels={"kalk": _channel(
        state={"lastSensorMl": 0.0, "lastSensorAt": NOW_UTC.isoformat()})})
    hass = _hass(entry, states={"sensor.kalk_dosed_today": "10.0",
                                "number.kalk_dose_speed": "400"})
    install_scheduler(integration)
    run(integration._async_dosing_tick(hass, entry))
    saved = _saved_channel(entry)
    assert saved["state"]["lastSensorMl"] == 10.0
    assert saved["reservoir"]["remainingMl"] == 4990.0
    assert saved["wear"]["runSeconds"] > 0


# --------------------------------------------------------------------------- #
# Hardening Wave 3: dosing firmware-truth & suspend reconciliation
# --------------------------------------------------------------------------- #
def test_sync_zero_volume_disables_the_pump():
    # R2: mlPerDay=0 is a safety edit — the enable switch must go OFF and the
    # zero must be WRITTEN (previously the firmware kept dosing its old volume
    # while the panel said "nothing will dose").
    entry = _entry(channels={"kalk": _channel(schedule={"mlPerDay": 0, "enabled": True})})
    hass = _hass(entry, states={"switch.kalk_enabled": "on", "number.kalk_dose_volume": "2.08"})
    install_scheduler(integration)
    run(integration._async_dosing_sync_pass(hass, entry))
    assert hass.states.get("switch.kalk_enabled").state == "off"
    assert float(hass.states.get("number.kalk_dose_volume").state) == 0.0


def test_tick_reasserts_and_releases_the_suspend_switch():
    # R3: the firmware 4 h auto-expiry is a dead-man for a DEAD HA; a live HA
    # re-asserts the hold every tick and releases a lapsed lockout on time.
    real_now = datetime.now(timezone.utc)
    future = (real_now + timedelta(hours=5)).isoformat()
    entry = _entry(channels={"kalk": _channel(
        state={"suspendedUntil": future, "lastSensorAt": NOW_UTC.isoformat()})})
    hass = _hass(entry)  # switch reads off: the firmware expiry released it
    install_scheduler(integration)
    run(integration._async_dosing_tick(hass, entry))
    assert hass.states.get("switch.kalk_ha_suspend").state == "on", "hold must be re-asserted"

    past = (real_now - timedelta(minutes=1)).isoformat()
    entry2 = _entry(channels={"kalk": _channel(
        state={"suspendedUntil": past, "lastSensorAt": NOW_UTC.isoformat()})})
    hass2 = _hass(entry2, states={"switch.kalk_ha_suspend": "on"})
    run(integration._async_dosing_tick(hass2, entry2))
    assert hass2.states.get("switch.kalk_ha_suspend").state == "off", "lapsed lockout releases on time"
    assert not _saved_channel(entry2)["state"]["suspendedUntil"]


def test_awc_release_respects_active_panic_lockout():
    # R15: finalize/abort/holdoff/acknowledge must not cancel a user lockout.
    future = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    entry = _entry(channels={"kalk": _channel(state={"suspendedUntil": future})})
    hass = _hass(entry, states={"switch.kalk_ha_suspend": "on"})
    run(integration._async_dosing_awc_suspend(hass, entry.options[CONF_SETTINGS], False, None))
    assert hass.states.get("switch.kalk_ha_suspend").state == "on"


def test_respread_invalidated_by_schedule_edit():
    # R17: halving the daily volume after a high test must kill the stale
    # catch-up cadence immediately — the safety edit wins.
    resp = {"date": NOW_LOCAL.date().isoformat(), "dayIntervalMin": 5, "nightIntervalMin": 5,
            "basePerDoseMl": 5.0, "baseDayIntervalMin": 90, "baseNightIntervalMin": 90}
    ch = _channel(chemical="alk",
                  schedule={"mlPerDay": 20, "mode": "doses", "dosesPerDay": 8,
                            "windowStart": "08:00", "windowEnd": "20:00"},
                  state={"respread": resp, "lastSensorAt": NOW_UTC.isoformat()})
    entry = _entry(channels={"alk": ch})
    hass = _hass(entry)
    install_scheduler(integration)
    run(integration._async_dosing_tick(hass, entry))
    assert _saved_channel(entry, "alk")["state"]["respread"] == {}


def test_drift_after_respread_expiry_is_silent():
    # R31: the firmware still holding the expired catch-up intervals is EXPECTED
    # divergence — resync without the scary "settings drifted" notification.
    ch = _channel(state={"lastSensorAt": NOW_UTC.isoformat()}, sync={"state": "synced"})
    entry = _entry(channels={"kalk": ch})
    hass = _hass(entry)  # numbers read "0" vs desired 2.08 -> drift
    runtime = hass.data.setdefault(integration.DOMAIN, {}).setdefault(integration.DOSING_RUNTIME, {})
    runtime.setdefault("channels", {})["kalk"] = {"suppressDriftNotify": True, "lastSensorMl": 0.0}
    install_scheduler(integration)
    run(integration._async_dosing_tick(hass, entry))
    assert not any("drifted" in str(c.data).lower()
                   for c in _calls(hass, "persistent_notification", "create"))
    assert hass.tasks, "the silent resync must still be kicked"


def test_ws_respread_refused_when_sensor_untrusted():
    # R33: the cap preflight would run against dosedTodayMl=0 — refuse instead
    # of re-dosing already-delivered volume.
    ch = _channel(chemical="alk",
                  schedule={"mlPerDay": 40, "mode": "doses", "dosesPerDay": 8,
                            "windowStart": "08:00", "windowEnd": "20:00"},
                  state={"missedMl": 8.0, "missedSince": NOW_UTC.isoformat()})
    entry = _entry(channels={"alk": ch})
    hass = _hass(entry, states={"sensor.kalk_dosed_today": "unavailable"})
    conn = FakeConnection()
    run(integration.websocket_dosing_respread_missed(hass, conn, {"id": 1, "channel_id": "alk"}))
    payload = conn.results[-1].payload
    assert payload["applied"] is False and "unavailable" in payload["reason"]
    saved = _saved_channel(entry, "alk")
    assert saved["state"]["missedSince"], "the pending decision must survive the refusal"


def test_dosing_save_grafts_only_dosing_keys():
    # R32: a dosing pass holds a stale snapshot across awaits — its save must
    # not revert a concurrent AWC write.
    entry = _entry()
    hass = _hass(entry)
    stale = integration._config_from_entry(entry)
    fresh = integration._config_from_entry(entry)
    fresh.setdefault("automaticWaterChange", {})["todayLitres"] = 7.5
    run(integration._async_save_config(hass, entry, fresh))          # concurrent writer lands
    stale["dosing"]["channels"]["kalk"]["wear"]["runSeconds"] = 123.0
    run(integration._async_dosing_save(hass, entry, stale))          # dosing flush with stale blob
    cfg = entry.options[CONF_SETTINGS]
    assert cfg["automaticWaterChange"]["todayLitres"] == 7.5, "AWC write must survive"
    assert cfg["dosing"]["channels"]["kalk"]["wear"]["runSeconds"] == 123.0


# --------------------------------------------------------------------------- #
# WebSocket surface
# --------------------------------------------------------------------------- #
def test_ws_dose_now_bounds_and_success():
    entry = _entry()
    hass = _hass(entry, states={"switch.kalk_enabled": "on"})
    conn = FakeConnection()
    run(integration.websocket_dosing_dose_now(hass, conn, {"id": 1, "channel_id": "kalk", "ml": 50}))
    assert "dose_out_of_bounds" in conn.error_codes
    run(integration.websocket_dosing_dose_now(hass, conn, {"id": 2, "channel_id": "kalk", "ml": 5}))
    payload = conn.results[-1].payload
    assert payload["started"] is True
    assert hass.states.get("number.kalk_manual_dose").state == "5.0"
    presses = _calls(hass, "button", "press")
    assert presses, "manual dose must press the firmware button"


def test_ws_dose_now_blocked_by_guards():
    entry = _entry(channels={"kalk": _channel(calibration={"stepsPerMl": 0})})
    hass = _hass(entry, states={"switch.kalk_enabled": "on"})
    conn = FakeConnection()
    run(integration.websocket_dosing_dose_now(hass, conn, {"id": 1, "channel_id": "kalk", "ml": 2}))
    payload = conn.results[-1].payload
    assert payload["started"] is False
    assert "not_calibrated" in [r["code"] for r in payload["reasons"]]
    assert not _calls(hass, "button", "press")


def test_ws_dose_now_blocked_without_ph_until_acknowledged():
    entry = _entry(channels={"kalk": _channel(guards={"phEntity": ""})})
    hass = _hass(entry, states={"switch.kalk_enabled": "on"})
    conn = FakeConnection()
    run(integration.websocket_dosing_dose_now(hass, conn, {"id": 1, "channel_id": "kalk", "ml": 2}))
    assert conn.results[-1].payload["started"] is False
    run(integration.websocket_dosing_acknowledge(hass, conn, {"id": 2, "channel_id": "kalk", "kind": "ph_missing"}))
    assert _saved_channel(entry)["guards"]["phMissingAcknowledged"] is True
    run(integration.websocket_dosing_dose_now(hass, conn, {"id": 3, "channel_id": "kalk", "ml": 2}))
    assert conn.results[-1].payload["started"] is True


def test_ws_calibrate_appends_history_and_blocks_junk():
    entry = _entry(channels={"kalk": _channel(calibration={"stepsPerMl": 0, "history": []})})
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_dosing_calibrate(hass, conn, {"id": 1, "channel_id": "kalk", "measured_ml": 0}))
    assert "invalid_measurement" in conn.error_codes
    run(integration.websocket_dosing_calibrate(hass, conn, {"id": 2, "channel_id": "kalk", "measured_ml": 27}))
    saved = _saved_channel(entry)
    assert saved["calibration"]["stepsPerMl"] == 11851.9
    assert len(saved["calibration"]["history"]) == 1
    run(integration.websocket_dosing_calibrate(hass, conn, {"id": 3, "channel_id": "kalk", "measured_ml": 26}))
    saved = _saved_channel(entry)
    assert len(saved["calibration"]["history"]) == 2, "history is kept for drift comparison (unlike AWC)"


def test_ws_reset_reservoir_recommends_reprime():
    entry = _entry(channels={"kalk": _channel(reservoir={"remainingMl": 120})})
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_dosing_reset_reservoir(hass, conn, {"id": 1, "channel_id": "kalk"}))
    saved = _saved_channel(entry)
    assert saved["reservoir"]["remainingMl"] == saved["reservoir"]["volumeMl"]
    assert saved["reservoir"]["refilledAt"]
    assert conn.results[-1].payload["reprimeRecommended"] is True


def test_ws_reset_tube_zeroes_wear():
    entry = _entry(channels={"kalk": _channel(wear={"runSeconds": 3600.0, "doseCount": 99})})
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_dosing_reset_tube(hass, conn, {"id": 1, "channel_id": "kalk"}))
    saved = _saved_channel(entry)
    assert saved["wear"]["runSeconds"] == 0.0
    assert saved["wear"]["doseCount"] == 0
    assert saved["wear"]["tubeInstalledAt"]


def test_ws_respread_kalk_resolves_to_skip():
    entry = _entry(channels={"kalk": _channel(state={"missedMl": 20.0, "missedSince": NOW_UTC.isoformat()})})
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_dosing_respread_missed(hass, conn, {"id": 1, "channel_id": "kalk"}))
    payload = conn.results[-1].payload
    assert payload["applied"] is False
    saved = _saved_channel(entry)
    assert saved["state"]["missedMl"] == 0.0 and not saved["state"]["missedSince"]


def test_ws_respread_2part_applies_same_day_override():
    ch = _channel(chemical="alk", schedule={"mlPerDay": 40, "mode": "doses", "dosesPerDay": 8,
                                            "windowStart": "08:00", "windowEnd": "20:00"},
                  state={"missedMl": 8.0, "missedSince": NOW_UTC.isoformat()})
    entry = _entry(channels={"alk": ch})
    hass = _hass(entry, states={"sensor.kalk_dosed_today": "5.0"})
    conn = FakeConnection()
    run(integration.websocket_dosing_respread_missed(hass, conn, {"id": 1, "channel_id": "alk"}))
    payload = conn.results[-1].payload
    assert payload["applied"] is True
    saved = _saved_channel(entry, "alk")
    assert saved["state"]["respread"]["date"] == NOW_LOCAL.date().isoformat()
    assert saved["state"]["respread"]["dayIntervalMin"] > 0


def test_ws_skip_missed_clears_state():
    entry = _entry(channels={"kalk": _channel(state={"missedMl": 20.0, "missedSince": NOW_UTC.isoformat()})})
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_dosing_respread_missed(hass, conn, {"id": 1, "channel_id": "kalk", "skip": True}))
    saved = _saved_channel(entry)
    assert saved["state"]["missedMl"] == 0.0 and not saved["state"]["missedSince"]


def test_ws_suspend_resume_touch_only_the_suspend_switch():
    entry = _entry()
    hass = _hass(entry, states={"switch.kalk_enabled": "on"})
    conn = FakeConnection()
    run(integration.websocket_dosing_suspend(hass, conn, {"id": 1, "channel_id": "kalk", "hours": 4}))
    saved = _saved_channel(entry)
    assert saved["state"]["suspendedUntil"]
    assert hass.states.get("switch.kalk_ha_suspend").state == "on"
    assert hass.states.get("switch.kalk_enabled").state == "on", "never conflate lockout with user intent"
    run(integration.websocket_dosing_resume(hass, conn, {"id": 2, "channel_id": "kalk"}))
    saved = _saved_channel(entry)
    assert not saved["state"]["suspendedUntil"]
    assert hass.states.get("switch.kalk_ha_suspend").state == "off"


def test_ws_dry_run_previews_without_motor():
    entry = _entry()
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_dosing_dry_run(hass, conn, {"id": 1, "channel_id": "kalk"}))
    payload = conn.results[-1].payload
    assert payload["preview"]["count"] > 100  # 24 h continuous kalk
    assert abs(payload["preview"]["totalMl"] - 300) < 5
    assert not _calls(hass, "button", "press")
    assert not _calls(hass, "number", "set_value")


def test_ws_summary_reports_channels_and_bindings():
    entry = _entry(awc_state={"status": "draining"})
    hass = _hass(entry, states={"switch.kalk_enabled": "on", "sensor.kalk_dosed_today": "150.0"})
    conn = FakeConnection()
    run(integration.websocket_dosing_summary(hass, conn, {"id": 1}))
    payload = conn.results[-1].payload
    assert payload["awcSuspended"] is True
    entry_summary = payload["summary"]["kalk"]
    assert entry_summary["dosedTodayMl"] == 150.0
    assert "awc_active" in [r["code"] for r in entry_summary["guards"]]
    assert payload["bindings"]["kalk"]["bound"] == len(ENTITIES)
    assert "lastSkipSensor" in payload["bindings"]["kalk"]["missing"]


def test_ws_delete_channel():
    entry = _entry()
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_dosing_delete_channel(hass, conn, {"id": 1, "channel_id": "kalk"}))
    assert entry.options[CONF_SETTINGS]["dosing"]["channels"] == {}
    run(integration.websocket_dosing_delete_channel(hass, conn, {"id": 2, "channel_id": "kalk"}))
    assert "unknown_channel" in conn.error_codes


def test_ws_unknown_channel_errors():
    entry = _entry()
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_dosing_prime(hass, conn, {"id": 1, "channel_id": "nope"}))
    assert "unknown_channel" in conn.error_codes


def test_ws_prime_is_bounded_and_stamps_primed_at():
    entry = _entry()
    hass = _hass(entry)
    conn = FakeConnection()
    run(integration.websocket_dosing_prime(hass, conn, {"id": 1, "channel_id": "kalk", "seconds": 9999}))
    presses = _calls(hass, "button", "press")
    assert len(presses) == 6, "30 s cap ⇒ at most 6 five-second presses"
    assert _saved_channel(entry)["reservoir"]["primedAt"]


# --- Stage C: live-food freshness enforcement + chaser accounting ---------------

def _livefood(**over):
    base = dict(
        chemical="livefood",
        driver={"type": "openreef_esphome_brushed",
                "entities": {**ENTITIES, "chaserSkippedSensor": "binary_sensor.phyto_chaser_skipped"}},
        calibration={"mlPerS": 2.0},
        schedule={"enabled": True, "mlPerDay": 40, "mode": "doses", "dosesPerDay": 10,
                  "windowStart": "00:00", "windowEnd": "00:00"},
    )
    base.update(over)
    return _channel(**base)


def test_stale_livefood_forces_enable_off_and_notifies_once():
    # FAIL-CLOSED: no mixedAt stamp = stale. HA owns the freshness signal — the tick
    # asserts the firmware enable switch OFF and says so once per cooldown.
    ch = _livefood(reservoir={"shelfLifeDays": 1, "mixedAt": ""})
    entry = _entry(channels={"phyto": ch})
    hass = _hass(entry, states={ENTITIES["enabledSwitch"]: "on",
                                "binary_sensor.phyto_chaser_skipped": "off"})
    run(integration._async_dosing_tick(hass, entry))
    offs = [c for c in _calls(hass, "switch", "turn_off")
            if ENTITIES["enabledSwitch"] in c.data.values()]
    assert offs, "stale culture must force the firmware enable OFF"

    def _stale_notes():
        return [c for c in hass.services.calls if c.domain == "persistent_notification"
                and c.data.get("notification_id") == "openreef_dosing_stale_phyto"]
    assert len(_stale_notes()) == 1
    run(integration._async_dosing_tick(hass, entry))
    assert len(_stale_notes()) == 1  # notify-once cooldown holds
    saved = _saved_channel(entry, "phyto")
    assert integration._dosing_desired_switches(saved)["enabledSwitch"] is False


def test_mark_refreshed_restarts_clock_and_reenables():
    ch = _livefood(reservoir={"shelfLifeDays": 1, "mixedAt": ""})
    entry = _entry(channels={"phyto": ch})
    hass = _hass(entry, states={"binary_sensor.phyto_chaser_skipped": "off"})
    run(integration._async_dosing_tick(hass, entry))  # latches stale
    conn = FakeConnection()
    run(integration.websocket_dosing_mark_refreshed(hass, conn, {"id": 1, "channel_id": "phyto"}))
    assert not conn.errors, conn.error_codes
    saved = _saved_channel(entry, "phyto")
    assert saved["reservoir"]["mixedAt"]
    assert integration._dosing_desired_switches(saved)["enabledSwitch"] is True


def test_chaser_debits_awc_fresh_reservoir_unless_skipped():
    # A landed dose on a brushed channel with a 5 s chaser at 2 ml/s debits 10 ml
    # from the AWC fresh reservoir and counts it into the fill ledger; the
    # firmware's chaser-skipped flag suppresses the debit.
    ch = _livefood(chaserSeconds=5, reservoir={"shelfLifeDays": 0})  # no expiry
    entry = _entry(channels={"phyto": ch})
    cfg = entry.options[CONF_SETTINGS]
    cfg.setdefault("automaticWaterChange", {})["enabled"] = True
    cfg["automaticWaterChange"].setdefault("reservoirs", {})["fresh"] = {
        "capacityLitres": 25, "remainingMl": 25000}
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(cfg)
    hass = _hass(entry, states={"binary_sensor.phyto_chaser_skipped": "off"})
    run(integration._async_dosing_tick(hass, entry))   # baseline at 0
    hass.states.set("sensor.kalk_dosed_today", "4.0")  # one 4 ml dose landed
    run(integration._async_dosing_tick(hass, entry))
    awc = entry.options[CONF_SETTINGS]["automaticWaterChange"]
    assert abs(awc["reservoirs"]["fresh"]["remainingMl"] - 24990) < 0.6
    assert abs(awc["ledger"]["cumulativeFilledL"] - 0.01) < 1e-6
    hass.states.set("binary_sensor.phyto_chaser_skipped", "on")
    hass.states.set("sensor.kalk_dosed_today", "8.0")
    run(integration._async_dosing_tick(hass, entry))
    awc = entry.options[CONF_SETTINGS]["automaticWaterChange"]
    assert abs(awc["reservoirs"]["fresh"]["remainingMl"] - 24990) < 0.6  # unchanged


def test_manual_dose_blocked_on_stale_food():
    # The firmware enable switch is already off — but the HA-side manual gate must
    # SAY why, not fail opaquely at the device.
    ch = _livefood(reservoir={"shelfLifeDays": 1, "mixedAt": ""})
    entry = _entry(channels={"phyto": ch})
    hass = _hass(entry, states={"binary_sensor.phyto_chaser_skipped": "off"})
    conn = FakeConnection()
    run(integration.websocket_dosing_dose_now(hass, conn, {"id": 1, "channel_id": "phyto", "ml": 2}))
    payload = conn.results[0].payload
    assert payload["started"] is False
    assert any(r["code"] == "stale_food" for r in payload["reasons"])


# --- Stage E: 2-part spacing orchestration --------------------------------------

def test_dose_now_spacing_gate_blocks_and_queues():
    from datetime import datetime, timezone, timedelta
    ca = _channel(chemical="ca", schedule={"enabled": True, "mlPerDay": 100, "mode": "doses",
                                           "dosesPerDay": 10})
    entry = _entry(channels={"kalk": _channel(), "ca": ca})
    cfg = entry.options[CONF_SETTINGS]
    cfg["dosing"]["spacing"] = {"enabled": True, "matrix": {"alk|ca": 30}, "queued": None}
    cfg["dosing"]["channels"]["ca"]["state"]["lastDoseAt"] = (
        datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(cfg)
    hass = _hass(entry, states={ENTITIES["enabledSwitch"]: "on"})
    conn = FakeConnection()
    run(integration.websocket_dosing_dose_now(hass, conn, {"id": 1, "channel_id": "kalk", "ml": 2}))
    payload = conn.results[0].payload
    assert payload["started"] is False
    assert any(r["code"] == "spacing" for r in payload["reasons"])
    conn2 = FakeConnection()
    run(integration.websocket_dosing_dose_now(
        hass, conn2, {"id": 2, "channel_id": "kalk", "ml": 2, "queue": True}))
    p2 = conn2.results[0].payload
    assert p2["queued"] is True and p2["started"] is False
    saved = entry.options[CONF_SETTINGS]["dosing"]["spacing"]["queued"]
    assert saved and saved["channelId"] == "kalk" and saved["ml"] == 2.0
    # nothing actuated while blocked
    assert not [c for c in _calls(hass, "button", "press")
                if ENTITIES["manualDoseButton"] in c.data.values()]


def test_spacing_queue_fires_when_clear_and_drops_when_blocked():
    from datetime import datetime, timezone, timedelta
    entry = _entry()
    cfg = entry.options[CONF_SETTINGS]
    cfg["dosing"]["spacing"] = {"enabled": True, "matrix": {"alk|ca": 30}, "queued": {
        "channelId": "kalk", "ml": 2.0,
        "requestedAt": datetime.now(timezone.utc).isoformat(),
        "notBefore": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}}
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(cfg)
    hass = _hass(entry, states={ENTITIES["enabledSwitch"]: "on"})
    run(integration._async_dosing_tick(hass, entry))
    assert entry.options[CONF_SETTINGS]["dosing"]["spacing"]["queued"] is None
    assert [c for c in _calls(hass, "button", "press")
            if ENTITIES["manualDoseButton"] in c.data.values()],         "queued dose must actuate the bounded manual-dose path"
    # blocked at FIRE time (channel went uncalibrated while queued) → dropped
    entry2 = _entry(channels={"kalk": _channel(calibration={"stepsPerMl": 0})})
    cfg2 = entry2.options[CONF_SETTINGS]
    cfg2["dosing"]["spacing"] = {"enabled": True, "matrix": {}, "queued": {
        "channelId": "kalk", "ml": 2.0, "requestedAt": "",
        "notBefore": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}}
    entry2.options[CONF_SETTINGS] = integration._normalise_core_config(cfg2)
    hass2 = _hass(entry2)
    run(integration._async_dosing_tick(hass2, entry2))
    assert entry2.options[CONF_SETTINGS]["dosing"]["spacing"]["queued"] is None
    assert not [c for c in _calls(hass2, "button", "press")
                if ENTITIES["manualDoseButton"] in c.data.values()]


def test_min_gap_and_phase_offset_writes():
    from datetime import datetime
    ca = _channel(chemical="ca", schedule={"enabled": True, "mlPerDay": 100, "mode": "doses",
                                           "dosesPerDay": 10, "windowStart": "08:00",
                                           "windowEnd": "12:00"})
    entry = _entry(channels={"kalk": _channel(), "ca": ca})
    cfg = entry.options[CONF_SETTINGS]
    cfg["dosing"]["spacing"] = {"enabled": True, "matrix": {"alk|ca": 30}, "queued": None}
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(cfg)
    config = entry.options[CONF_SETTINGS]
    now_local = datetime(2026, 7, 17, 9, 0)
    kalk_writes = integration._dosing_desired_writes(config["dosing"]["channels"]["kalk"], config, now_local)
    ca_writes = integration._dosing_desired_writes(config["dosing"]["channels"]["ca"], config, now_local)
    assert kalk_writes["minGapNumber"] == 30.0
    assert ca_writes["minGapNumber"] == 30.0
    # ca (sorts after alk) staggers +30 min at the WRITE layer; config untouched
    assert ca_writes["windowStartNumber"] == 8 * 60 + 30
    assert ca_writes["windowEndNumber"] == 12 * 60 + 30
    assert config["dosing"]["channels"]["ca"]["schedule"]["windowStart"] == "08:00"
    # disabling spacing zeroes the firmware gap
    cfg2 = entry.options[CONF_SETTINGS]
    cfg2["dosing"]["spacing"]["enabled"] = False
    entry.options[CONF_SETTINGS] = integration._normalise_core_config(cfg2)
    config2 = entry.options[CONF_SETTINGS]
    assert integration._dosing_desired_writes(
        config2["dosing"]["channels"]["kalk"], config2, now_local)["minGapNumber"] == 0.0


def test_import_sanitize_drops_queued_spacing_dose():
    # A restored backup must never fire a days-old deferred dose.
    incoming = {"dosing": {"spacing": {"enabled": True, "matrix": {"alk|ca": 30},
                                       "queued": {"channelId": "kalk", "ml": 2.0,
                                                  "requestedAt": "", "notBefore": ""}}}}
    integration._sanitize_imported_config(incoming, {})
    assert incoming["dosing"]["spacing"]["queued"] is None


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
