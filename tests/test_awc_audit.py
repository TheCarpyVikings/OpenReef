"""Failure-injection regressions for the AWC actuator safety audit."""

from datetime import datetime, timedelta, timezone

from test_awc_safety import (
    integration, _entry, _hass, _start, _state, _awc, _has_call, _fire_leg,
    run, CONF_SETTINGS,
)


def test_restart_never_fills_based_on_drain_time_elapsed_during_power_loss():
    entry = _entry()
    now = datetime.now(timezone.utc)
    _state(entry).update({
        "status": "draining", "method": "batch_sequential", "targetLitres": 2.0,
        "movedMl": {}, "legStartedAt": (now - timedelta(minutes=5)).isoformat(),
        "legEndsAt": (now - timedelta(minutes=4)).isoformat(),
    })
    hass = _hass(entry)
    run(integration._async_awc_resume_on_startup(hass, entry, entry.options[CONF_SETTINGS]))
    assert _state(entry)["status"] == "fault"
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_fill")
    assert not _awc(entry)["history"], "Unknown downtime flow must not become measured progress"


def test_failed_drain_stop_never_starts_fill():
    entry = _entry()
    hass = _hass(entry)
    assert _start(hass, entry, 2.0)[0]
    hass.services.fail_on.add(("switch", "turn_off", "switch.awc_drain"))
    _fire_leg(hass, entry)
    assert _state(entry)["status"] == "fault"
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_fill")


def test_silent_start_rejection_never_becomes_a_completed_drain():
    entry = _entry()
    hass = _hass(entry)
    original = hass.services.async_call

    async def reject_on(domain, service, data=None, **kwargs):
        if service == "turn_on":
            return
        return await original(domain, service, data, **kwargs)

    hass.services.async_call = reject_on
    assert not _start(hass, entry, 2.0)[0]
    assert _state(entry)["status"] == "fault"
    assert not _awc(entry)["history"]


def test_persistence_failure_after_start_stops_pump():
    entry = _entry()
    hass = _hass(entry)
    original = integration._async_save_config

    async def cannot_save(*args, **kwargs):
        raise RuntimeError("storage unavailable")

    integration._async_save_config = cannot_save
    try:
        try:
            _start(hass, entry, 2.0)
        except RuntimeError:
            pass
    finally:
        integration._async_save_config = original
    assert hass.states.get("switch.awc_drain").state == "off"
    assert hass.states.get("switch.awc_fill").state == "off"


def test_persistence_failure_after_manual_resume_stops_pump():
    entry = _entry()
    hass = _hass(entry)
    _state(entry).update({"status": "paused", "method": "batch_sequential", "targetLitres": 2.0,
                          "movedMl": {"drain": 2000, "fill": 0}})
    original = integration._async_save_config

    async def cannot_save(*args, **kwargs):
        raise RuntimeError("storage unavailable")

    integration._async_save_config = cannot_save
    try:
        try:
            run(integration._async_awc_try_resume(hass, entry, None))
        except RuntimeError:
            pass
    finally:
        integration._async_save_config = original
    assert _has_call(hass.services.calls, "turn_on", "switch.awc_fill")
    assert hass.states.get("switch.awc_fill").state == "off"
    assert _state(entry)["status"] == "fault"


def test_paused_resume_rechecks_remaining_stock_before_more_drain():
    entry = _entry()
    hass = _hass(entry)
    _state(entry).update({"status": "paused", "method": "batch_sequential", "targetLitres": 2.0,
                          "movedMl": {"drain": 500, "fill": 0}})
    _awc(entry)["reservoirs"]["fresh"]["remainingMl"] = 1000
    assert not run(integration._async_awc_try_resume(hass, entry, None))
    assert _state(entry)["status"] == "paused"
    assert "recorded volume" in _state(entry)["pausedReason"]
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_drain")


def test_unavailable_pump_is_blocked_before_any_drain():
    entry = _entry()
    hass = _hass(entry, {"switch.awc_fill": "unavailable"})
    assert not _start(hass, entry, 2.0)[0]
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_drain")


def test_already_running_fill_blocks_before_drain():
    entry = _entry()
    hass = _hass(entry, {"switch.awc_fill": "on"})
    started, reasons = _start(hass, entry, 2.0)
    assert not started
    assert "pump_already_running" in {r["code"] for r in reasons}
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_drain")


def test_mid_run_pump_loss_never_credits_missing_drain():
    for lost_state in ("off", "unavailable"):
        entry = _entry()
        hass = _hass(entry)
        assert _start(hass, entry, 2.0)[0]
        hass.states.set("switch.awc_drain", lost_state)
        run(integration._async_awc_timer_fired(hass, entry, None))
        assert _state(entry)["status"] == "fault"
        assert not _has_call(hass.services.calls, "turn_on", "switch.awc_fill")
        assert not _awc(entry)["history"]
        assert not _state(entry)["movedMl"].get("drain", 0)


def test_silent_ato_stop_failure_prevents_drain():
    entry = _entry(equipment={"ato": {"type": "ato", "armed": True, "switch_entity_id": "switch.ato"}})
    hass = _hass(entry, {"switch.ato": "on"})
    original = hass.services.async_call

    async def reject_ato(domain, service, data=None, **kwargs):
        if "switch.ato" in (data or {}).values():
            return
        return await original(domain, service, data, **kwargs)

    hass.services.async_call = reject_ato
    try:
        _start(hass, entry, 2.0)
    except RuntimeError:
        pass
    assert _state(entry)["status"] == "fault"
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_drain")


def test_subsecond_pump_run_is_rejected_instead_of_rounded_up():
    entry = _entry()
    hass = _hass(entry)
    started, reasons = _start(hass, entry, 0.01)
    assert not started
    assert "volume_below_minimum" in {r["code"] for r in reasons}
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_drain")


def test_nonfinite_volume_is_refused_before_actuating_any_equipment():
    for amount in (float("nan"), float("inf")):
        entry = _entry()
        hass = _hass(entry)
        started, reasons = _start(hass, entry, amount)
        assert not started and reasons[0]["code"] == "invalid_volume"
        assert not hass.services.calls


def test_matched_drain_checks_leak_before_its_end_and_cancels_uncertain_debt():
    from test_nps import _fx_entry, _fx_state
    from _fake_ha import FakeHass, install_scheduler
    entry = _fx_entry(500, awc_over={"safety": {"leakEntity": "binary_sensor.leak"}})
    hass = FakeHass(states={"switch.drain": "off", "switch.fill": "off", "binary_sensor.leak": "off"}, entries=[entry])
    scheduler = install_scheduler(integration)
    assert run(integration._async_nps_matched_drain_maybe(hass, entry, datetime.now(timezone.utc)))
    hass.states.set("binary_sensor.leak", "on")
    run(scheduler.fire_all())
    assert hass.states.get("switch.drain").state == "off"
    assert entry.options[CONF_SETTINGS]["automaticWaterChange"]["state"]["status"] == "fault"
    assert _fx_state(entry)["owedMl"] == 0
    assert _fx_state(entry)["droppedMl"] == 500
    assert not entry.options[CONF_SETTINGS]["nps"]["feedExchange"]["enabled"]
    assert not scheduler.pending()


def test_matched_drain_requires_known_waste_capacity():
    from test_nps import _fx_entry, _fx_state
    from _fake_ha import FakeHass
    entry = _fx_entry(500, awc_over={"reservoirs": {"waste": {"capacityLitres": 0}}})
    hass = FakeHass(states={"switch.drain": "off", "switch.fill": "off"}, entries=[entry])
    assert not run(integration._async_nps_matched_drain_maybe(hass, entry, datetime.now(timezone.utc)))
    assert _fx_state(entry)["lastBlockedReason"] == "waste_capacity_unknown"


def test_slow_fill_over_firmware_runtime_limit_blocks_before_drain():
    entry = _entry()
    _awc(entry)["pumps"]["fill"]["mlPerS"] = 2
    hass = _hass(entry)
    started, reasons = _start(hass, entry, 1.0)
    assert not started
    assert "runtime_limit" in {r["code"] for r in reasons}
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_drain")


def test_late_leg_timer_does_not_invent_target_delivery_then_fill():
    entry = _entry()
    hass = _hass(entry)
    assert _start(hass, entry, 2.0)[0]
    _state(entry)["legEndsAt"] = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    run(integration._async_awc_timer_fired(hass, entry, None))
    assert _state(entry)["status"] == "fault"
    assert not _has_call(hass.services.calls, "turn_on", "switch.awc_fill")
    assert not _awc(entry)["history"]


def test_calibration_and_reservoir_reset_refuse_active_matched_drain():
    from test_nps import _fx_entry
    from _fake_ha import FakeHass, FakeConnection, install_scheduler
    entry = _fx_entry(500)
    hass = FakeHass(states={"switch.drain": "off", "switch.fill": "off"}, entries=[entry])
    install_scheduler(integration)
    assert run(integration._async_nps_matched_drain_maybe(hass, entry, datetime.now(timezone.utc)))
    for handler, message in (
        (integration.websocket_awc_calibrate, {"role": "drain", "seconds": 30, "volume_ml": 900}),
        (integration.websocket_awc_reset_reservoir, {"reservoir": "waste"}),
        (integration.websocket_awc_calibration_run, {"role": "fill", "seconds": 30}),
    ):
        connection = FakeConnection()
        run(handler(hass, connection, {"id": 1, **message}))
        assert connection.error_codes == ["busy"]


def test_partial_fill_debits_direct_draw_mixing_stock_once():
    entry = _entry()
    hass = _hass(entry)
    assert _start(hass, entry, 2.0)[0]
    _fire_leg(hass, entry)
    now = datetime.now(timezone.utc)
    _state(entry)["legStartedAt"] = (now - timedelta(seconds=10)).isoformat()
    _state(entry)["legEndsAt"] = (now + timedelta(seconds=10)).isoformat()
    original = integration._mixing_run_debit
    debits = []
    integration._mixing_run_debit = lambda _hass, _cfg, litres: debits.append(litres)
    try:
        async def abort_locked():
            async with integration._awc_lock(hass):
                await integration._async_awc_abort(hass, entry, integration._config_from_entry(entry), "stopped", False, False, None)
        run(abort_locked())
    finally:
        integration._mixing_run_debit = original
    assert len(debits) == 1
    assert abs(debits[0] - 1.0) < 0.1


def test_stir_commit_preserves_concurrent_awc_run_and_channel_disable():
    from test_nps import _care_entry
    from _fake_ha import FakeHass
    entry = _care_entry({"schedule": {"standing": {
        "enabled": True, "targetCellsPerMl": 10000, "turnoverPerDay": 22,
        "stir": {"switchEntity": "switch.stirrer", "everyHours": 8, "burstMinutes": 2}}}})
    hass = FakeHass(states={"switch.stirrer": "off"}, entries=[entry])
    original = hass.services.async_call
    changed = False

    async def interleaved(domain, service, data=None, **kwargs):
        nonlocal changed
        await original(domain, service, data, **kwargs)
        if domain == "switch" and service == "turn_on" and not changed:
            changed = True
            fresh = integration._config_from_entry(entry)
            fresh["automaticWaterChange"]["state"].update({"status": "filling", "targetLitres": 1.0,
                                                          "legEndsAt": "2030-01-01T00:00:00+00:00"})
            fresh["dosing"]["channels"]["drip"]["enabled"] = False
            entry.options[CONF_SETTINGS] = fresh

    hass.services.async_call = interleaved
    run(integration._async_dosing_standing_care_tick(hass, entry))
    fresh = entry.options[CONF_SETTINGS]
    assert fresh["automaticWaterChange"]["state"]["status"] == "filling"
    assert fresh["automaticWaterChange"]["state"]["legEndsAt"] == "2030-01-01T00:00:00+00:00"
    assert not fresh["dosing"]["channels"]["drip"]["enabled"]
    assert fresh["dosing"]["channels"]["drip"]["state"]["stirUntil"]
    # Disabling the channel during start must not strand its stirrer ON.
    run(integration._async_dosing_standing_care_tick(hass, entry))
    assert hass.states.get("switch.stirrer").state == "off"


def test_truce_engage_and_restore_commits_preserve_concurrent_awc_state():
    from test_nps import _truce_entry
    from _fake_ha import FakeHass
    for restoring in (False, True):
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        entry = _truce_entry(truce_state={"uv": {"restoreAt": past, "turnedOff": ["switch.uv"]}} if restoring else None)
        hass = FakeHass(states={"switch.uv": "off" if restoring else "on"}, entries=[entry])
        original = hass.services.async_call
        changed = False

        async def interleaved(domain, service, data=None, **kwargs):
            nonlocal changed
            await original(domain, service, data, **kwargs)
            if domain == "switch" and not changed:
                changed = True
                fresh = integration._config_from_entry(entry)
                fresh["automaticWaterChange"]["state"].update({"status": "filling", "targetLitres": 1.0,
                                                              "legEndsAt": "2030-01-01T00:00:00+00:00"})
                fresh["nps"]["truce"]["enabled"] = False
                entry.options[CONF_SETTINGS] = fresh

        hass.services.async_call = interleaved
        handler = integration._async_nps_truce_tick if restoring else integration._async_nps_truce_engage
        run(handler(hass, entry))
        fresh = entry.options[CONF_SETTINGS]
        assert fresh["automaticWaterChange"]["state"]["status"] == "filling"
        assert not fresh["nps"]["truce"]["enabled"]
        assert fresh["nps"]["truce"]["state"]["uv"]["turnedOff"] == ([] if restoring else ["switch.uv"])


def test_unrelated_stale_save_cannot_erase_running_or_fault_control_state():
    for status in ("filling", "fault"):
        entry = _entry()
        hass = _hass(entry)
        stale = integration._config_from_entry(entry)
        _state(entry).update({"status": status, "targetLitres": 2.0,
                              "fault": "latched failure" if status == "fault" else "",
                              "legEndsAt": "2030-01-01T00:00:00+00:00"})
        run(integration._async_save_config(hass, entry, stale))
        assert _state(entry)["status"] == status
        assert _state(entry)["legEndsAt"] == "2030-01-01T00:00:00+00:00"
        if status == "fault":
            assert _state(entry)["fault"] == "latched failure"


def test_unrelated_stale_save_preserves_awc_disable_bindings_and_locked_stock_debit():
    entry = _entry()
    hass = _hass(entry)
    stale = integration._config_from_entry(entry)
    stored = _awc(entry)
    stored["enabled"] = False
    stored["pumps"]["fill"]["switchEntity"] = "switch.new_fill"
    stored["safety"]["leakEntity"] = "binary_sensor.new_leak"
    stored["history"] = [{"completedAt": datetime.now(timezone.utc).isoformat(),
                          "drainedL": 1.0, "filledL": 1.0, "method": "batch_sequential"}]
    stored["todayLitres"] = 1.0
    # Firmware chaser accounting is a legitimate external water consumer and
    # takes the AWC lock. An unrelated older save cannot replenish that stock.
    run(integration._async_awc_credit_chaser_fill(hass, entry, 125.0))
    run(integration._async_save_config(hass, entry, stale))
    saved = _awc(entry)
    assert not saved["enabled"]
    assert saved["pumps"]["fill"]["switchEntity"] == "switch.new_fill"
    assert saved["safety"]["leakEntity"] == "binary_sensor.new_leak"
    assert saved["history"][0]["filledL"] == 1.0
    assert saved["todayLitres"] == 1.0
    assert saved["reservoirs"]["fresh"]["remainingMl"] == 24875.0
    assert saved["ledger"]["cumulativeFilledL"] == 0.125


def test_unrelated_stale_save_cannot_replenish_dosed_food_or_freshness():
    from test_nps import _ha_entry
    from _fake_ha import FakeHass
    entry = _ha_entry()
    hass = FakeHass(entries=[entry])
    stale = integration._config_from_entry(entry)
    reservoir = entry.options[CONF_SETTINGS]["dosing"]["channels"]["phyto_pump"]["reservoir"]
    reservoir.update({"remainingMl": 250, "mixedAt": "2020-01-01T00:00:00+00:00"})
    run(integration._async_save_config(hass, entry, stale))
    saved = entry.options[CONF_SETTINGS]["dosing"]["channels"]["phyto_pump"]["reservoir"]
    assert saved["remainingMl"] == 250
    assert saved["mixedAt"] == "2020-01-01T00:00:00+00:00"


def test_brine_hand_feed_waits_for_pump_accounting_and_reads_current_stock():
    import asyncio
    from test_nps import _fx_entry
    from _fake_ha import FakeHass, FakeConnection
    entry = _fx_entry()
    cfg = integration._config_from_entry(entry)
    cfg["dosing"]["channels"]["brine"]["reservoir"].update({
        "volumeMl": 500, "remainingMl": 300, "mixedAt": datetime.now(timezone.utc).isoformat()})
    entry.options[CONF_SETTINGS] = cfg
    hass = FakeHass(entries=[entry])
    connection = FakeConnection()

    async def scenario():
        async with integration._dosing_lock(hass):
            hand_feed = asyncio.create_task(integration.websocket_nps_hand_feed(
                hass, connection, {"id": 1, "ml": 30}))
            await asyncio.sleep(0)
            assert not hand_feed.done()
            # A real observed-dose transaction commits while it owns this lock.
            entry.options[CONF_SETTINGS]["dosing"]["channels"]["brine"]["reservoir"]["remainingMl"] = 250
        await hand_feed

    run(scenario())
    assert not connection.errors
    assert entry.options[CONF_SETTINGS]["dosing"]["channels"]["brine"]["reservoir"]["remainingMl"] == 220


def test_unrelated_stale_save_cannot_restore_mixing_stock_or_tested_batch():
    from test_mixing import _station
    from _fake_ha import FakeConnection
    hass, entry = _station({"batch": {"state": "ready", "litres": 10,
                                      "loggedPpt": 35, "testedAt": datetime.now(timezone.utc).isoformat()}})
    entry.options[CONF_SETTINGS]["mixingStation"]["vessels"]["mix"].update({"estimatedLitres": 10, "contents": "salt"})
    stale = integration._config_from_entry(entry)
    connection = FakeConnection()
    run(integration.websocket_mixing_mark_used(hass, connection, {"id": 1, "litres": 10}))
    assert not connection.errors
    run(integration._async_save_config(hass, entry, stale))
    station = entry.options[CONF_SETTINGS]["mixingStation"]
    assert station["vessels"]["mix"]["estimatedLitres"] == 0
    assert station["batch"]["state"] == "idle"


def test_mixing_actuator_await_serializes_with_awc_source_debit():
    import asyncio
    from test_mixing import _station
    from _fake_ha import FakeConnection
    hass, entry = _station({"batch": {"state": "ready", "litres": 10,
                                      "loggedPpt": 35, "testedAt": datetime.now(timezone.utc).isoformat()}})
    entry.options[CONF_SETTINGS]["mixingStation"]["vessels"]["mix"].update({"estimatedLitres": 10, "contents": "salt"})
    connection = FakeConnection()
    original = hass.services.async_call
    debit_task = None

    async def debit():
        async with integration._awc_lock(hass):
            current = integration._config_from_entry(entry)
            integration._mixing_debit_batch(hass, current, 1.0, "the water change")
            await integration._async_save_config(hass, entry, current)

    async def interleaved(domain, service, data=None, **kwargs):
        nonlocal debit_task
        if domain == "switch" and service == "turn_on" and debit_task is None:
            debit_task = asyncio.create_task(debit())
            await asyncio.sleep(0)
            assert not debit_task.done(), "Mixing and AWC must own the same water inventory lock"
        return await original(domain, service, data, **kwargs)

    hass.services.async_call = interleaved

    async def scenario():
        await integration.websocket_mixing_stir_now(hass, connection, {"id": 1})
        assert debit_task is not None
        await debit_task

    run(scenario())
    assert not connection.errors
    assert entry.options[CONF_SETTINGS]["mixingStation"]["vessels"]["mix"]["estimatedLitres"] == 9.0
    assert entry.options[CONF_SETTINGS]["mixingStation"]["batch"]["state"] == "storing"


def test_stale_save_preserves_automated_bottle_stock_but_unlinked_stock_remains_editable():
    from test_nps import _ha_entry, _ha_channel, _product
    from _fake_ha import FakeHass, FakeConnection
    entry = _ha_entry(_ha_channel(reservoir={"productId": "phyto", "productIsBottle": True}),
                      {"phyto": _product(remainingMl=500), "other": _product(remainingMl=500)})
    hass = FakeHass(entries=[entry])
    stale = integration._config_from_entry(entry)
    connection = FakeConnection()
    run(integration.websocket_consumable_log_dose(hass, connection,
        {"id": 1, "product_id": "phyto", "ml": 25}))
    assert not connection.errors
    stale["consumables"]["products"]["other"]["remainingMl"] = 450
    run(integration._async_save_config(hass, entry, stale))
    products = entry.options[CONF_SETTINGS]["consumables"]["products"]
    assert products["phyto"]["remainingMl"] == 475
    assert products["phyto"]["history"][-1]["ml"] == 25
    assert products["other"]["remainingMl"] == 450
    # The explicit refill endpoint owns the ledger and still works.
    run(integration.websocket_consumable_refill(hass, connection,
        {"id": 2, "product_id": "phyto", "ml": 100}))
    assert entry.options[CONF_SETTINGS]["consumables"]["products"]["phyto"]["remainingMl"] == 575


if __name__ == "__main__":
    failed = []
    tests = [(name, fn) for name, fn in globals().copy().items() if name.startswith("test_")]
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as exc:
            failed.append(name)
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - len(failed)}/{len(tests)} passed")
    raise SystemExit(bool(failed))
