"""Culture audit regressions: volume conservation, clocks, advice and action atomicity.

Run: python3 tests/test_cultures_audit.py
"""
from __future__ import annotations

import copy
import math
import traceback
from datetime import timedelta

from test_cultures import (NOW, REAL, CONF_SETTINGS, _jar, _entry, _config,
                           _cultures, _iso, cultures, integration,
                           FakeConnection, FakeHass, run)


def test_refill_conserves_volume_and_salinity_across_supported_range():
    for litres in (0.2, 2.5, 50):
        for pct in (0, 5, 25, 50, 100):
            for target in (5, 20, 27, 35, 45):
                for stock in (20, 35, 45):
                    g = cultures.refill_guide(litres, pct, target, stock)
                    assert g['targetPpt'] == target
                    if target > stock:
                        assert g['available'] is False and g['mixMl'] == 0
                    else:
                        assert g['mixMl'] + g['rodiMl'] == g['totalMl']
                        # Integer-ml rounding introduces at most half a ml of stock error.
                        assert abs(g['mixMl'] * stock - g['totalMl'] * target) <= stock / 2 + 1e-8


def test_harvest_refill_replaces_purge_as_well_as_crop():
    jar = {**_jar(), 'vesselKind': 'cone', 'purgeMl': 50, 'salinityPpt': 27}
    g = cultures.harvest_guide(jar, 35)
    assert (g['totalMl'], g['purgeMl'], g['refillMl'], g['mixMl'], g['rodiMl']) == (625, 50, 675, 521, 154)
    jar['vesselKind'] = 'tub'
    assert cultures.harvest_guide(jar)['refillMl'] == 625


def test_invalid_clock_and_temperature_inputs_cannot_break_summary():
    for value in (math.nan, math.inf, -math.inf, True, 'unknown'):
        assert not cultures.temperature_advice(value, 'tigriopus')['available']
        jar = _jar(started_ago_days=20, now=NOW)
        jar['cadence'] = {k: value for k in cultures.CADENCE_FIELDS}
        st = cultures.culture_state(jar, NOW)
        assert all(math.isfinite(v) for v in st['cadence'].values())
    for stamp in ('2026-09-01T12:00:00', 'junk', _iso(NOW + timedelta(days=1))):
        assert cultures.culture_state({'state': {'startedAt': stamp}}, NOW)['status'] == 'none'
        assert cultures.bottle_state({'remainingMl': 20, 'filledAt': stamp}, 5, NOW)['status'] == 'stale'
    assert cultures.bottle_state({'remainingMl': 20, 'filledAt': _iso(NOW)}, 0, NOW)['status'] == 'stale'


def test_temperature_sensor_units_and_missing_sensor_fallback():
    cfg = _config(_entry(temp_entity='sensor.rack'))
    cfg['nps']['hatchery'] = {'tempEntity': 'sensor.room'}
    hass = FakeHass(states={'sensor.room': '24'})
    c = cfg['nps']['cultures']
    assert integration._cultures_temp_c(hass, cfg, c) == 24
    for value, unit in ((77, '°F'), (298.15, 'K'), (25, '°C')):
        hass.states.set('sensor.rack', value, {'unit_of_measurement': unit})
        assert abs(integration._cultures_temp_c(hass, cfg, c) - 25) < 1e-6
    hass.states.set('sensor.rack', 'NaN')
    assert integration._cultures_temp_c(hass, cfg, c) == 24


def test_topups_do_not_refresh_unknown_age_or_old_enrichment():
    old = _iso(NOW - timedelta(hours=25))
    for stamp in ('', 'junk', _iso(NOW + timedelta(days=1))):
        b = {'remainingMl': 100, 'volumeMl': 1000, 'filledAt': stamp, 'history': []}
        integration._cultures_bottle_fill(b, 100, NOW, False, {})
        assert cultures.bottle_state(b, 5, NOW)['status'] == 'stale'
    b = {'remainingMl': 100, 'volumeMl': 1000, 'filledAt': old, 'enrichedAt': old, 'lastLoadEnriched': True}
    integration._cultures_bottle_fill(b, 100, NOW, True, {})
    assert b['enrichedAt'] == old and cultures.bottle_boost(b, 24, NOW)['status'] == 'faded'
    integration._cultures_bottle_fill(b, 100, NOW, False, {})
    assert not b['lastLoadEnriched']
    integration._cultures_bottle_fill(b, 100, NOW, True, {})
    assert not b['lastLoadEnriched'], 'new enriched food cannot enrich the old plain portion'


def test_bottle_overflow_records_only_the_accepted_volume():
    b = {'remainingMl': 950, 'volumeMl': 1000, 'filledAt': _iso(NOW), 'history': []}
    integration._cultures_bottle_fill(b, 200, NOW, False, {})
    assert b['remainingMl'] == 1000 and b['history'][0]['ml'] == 50


def test_empty_feed_refuses_and_undo_restores_last_dose():
    entry = _entry(bottle={'remainingMl': 20, 'volumeMl': 1000, 'filledAt': _iso(REAL), 'doseMl': 20})
    hass, conn = FakeHass(entries=[entry]), FakeConnection()
    run(integration.websocket_cultures_bottle(hass, conn, {'id': 1, 'action': 'fed'}))
    b = _cultures(entry)['bottle']
    stamp = b['history'][0]['at']
    assert b['remainingMl'] == 0
    before = copy.deepcopy(_cultures(entry))
    run(integration.websocket_cultures_bottle(hass, conn, {'id': 2, 'action': 'fed'}))
    assert conn.errors[-1].code == 'bottle_unavailable' and _cultures(entry) == before
    run(integration.websocket_cultures_bottle(hass, conn, {'id': 3, 'action': 'undo', 'at': stamp}))
    assert _cultures(entry)['bottle']['remainingMl'] == 20
    assert cultures.bottle_usage_ml_per_day(_cultures(entry)['bottle']['history'], REAL + timedelta(minutes=1)) is None


def test_rejected_combined_harvest_has_no_feed_or_sign_side_effects():
    for age, volume, enrichment_busy, expected in ((2, None, False, 'establishing'), (20, 5000, False, 'invalid_volume'), (20, 625, True, 'enrich_busy')):
        cfg = _config(_entry(jars={'c1': _jar(started_ago_days=age)}))
        if enrichment_busy:
            cfg['nps']['cultures']['enrichment']['state']['startedAt'] = _iso(REAL)
        before = copy.deepcopy(cfg)
        error = integration._cultures_log_apply(FakeHass(), cfg, 'c1', fed=True, harvested=True, tint='clear', sign='milky', ml=volume, enrich=enrichment_busy)
        assert error[0] == expected
        assert cfg == before


def test_restart_clears_slow_clearing_history_and_harvest_debt():
    jar = _jar(started_ago_days=20, now=REAL, lastTint='green')
    history = []
    for back, hours in ((1, 20), (30, 20), (60, 8), (80, 8), (100, 8)):
        history += [{'event': 'tint', 'at': _iso(REAL - timedelta(hours=back)), 'tint': 'clear'},
                    {'event': 'feed', 'at': _iso(REAL - timedelta(hours=back + hours))}]
    jar['history'] = history
    assert cultures.culture_state(jar, REAL)['restart']['reason'] == 'slow'
    cfg = _config(_entry(jars={'c1': jar}))
    assert integration._cultures_restart_apply(FakeHass(), cfg, 'c1') is None
    st = cultures.culture_state(cfg['nps']['cultures']['jars']['c1'], REAL + timedelta(minutes=1))
    assert not st['restart']['due'] and not st['harvest']['due'] and not st['clearingSlow']


def test_clearing_does_not_treat_an_unfed_harvest_or_crash_as_a_feed():
    rows = [{'event': 'feed', 'at': _iso(NOW - timedelta(hours=12))},
            {'event': 'harvest', 'at': _iso(NOW - timedelta(hours=2)), 'fed': False},
            {'event': 'tint', 'at': _iso(NOW), 'tint': 'clear'}]
    assert cultures.clearing_samples(rows) == [12]
    rows[1]['event'] = 'crashed'
    assert cultures.clearing_samples(rows) == []


def test_routine_restarts_cannot_create_a_shorter_and_shorter_cadence():
    history = [{'event': event, 'at': _iso(NOW - timedelta(days=day))}
               for event, day in (('seeded', 42), ('restart', 28), ('restart', 14), ('restart', 0))]
    jar = {'species': 'rotifer_L', 'history': history}
    assert cultures.learned_cadences(jar, [history], NOW)['suggest']['restartIntervalDays'] is None
    failures = [{'event': event, 'at': _iso(NOW - timedelta(days=day))}
                for event, day in (('seeded', 30), ('crashed', 20), ('seeded', 19), ('crashed', 9))]
    jar['history'] = failures
    assert cultures.learned_cadences(jar, [failures], NOW)['suggest']['restartIntervalDays'] == 9


def test_daily_means_do_not_count_three_draws_over_two_days():
    rows = [{'event': 'harvest', 'at': _iso(NOW - timedelta(days=d)), 'ml': 625} for d in (0, 1, 2)]
    assert cultures.yield_ml_per_day(rows, NOW) == 625
    rows = [{**r, 'event': 'fed_tank', 'ml': 20} for r in rows]
    assert cultures.bottle_usage_ml_per_day(rows, NOW) == 20
    rows[0]['undoneAt'] = _iso(NOW)
    assert cultures.bottle_usage_ml_per_day(rows, NOW) == 13.3


def test_copepod_advice_does_not_require_a_harvest_to_control_ammonia():
    debt = {'due': True, 'hoursOverdue': 300}
    assert cultures.feed_advice('clear', {'due': True}, debt, 240, 'tigriopus')['action'] != 'harvest_first'
    jar = _jar('tigriopus', 60, now=NOW, lastHarvestAt=_iso(NOW - timedelta(days=30)))
    risk = cultures.risk_line(jar, cultures.culture_state(jar, NOW), {}, NOW)
    assert risk['level'] == 'watch' and 'ammonia is' not in risk['reason']


def test_bottle_demand_cannot_shorten_the_culture_recovery_interval():
    clock = {'available': True, 'due': False, 'hoursUntil': 20, 'at': _iso(NOW + timedelta(hours=20))}
    result = cultures.next_harvest({'status': 'empty', 'remainingMl': 0}, 1000, clock, True)
    assert result == {'status': 'wait', 'hoursUntil': 20, 'driver': 'jar'}


def test_split_rejects_wrong_species_and_uses_only_the_stock_share():
    jar = {**_jar(started_ago_days=20, lastTint='green'), 'salinityPpt': 27}
    cfg = _config(_entry(jars={'c1': jar, 'c2': _jar('tigriopus')}))
    before = copy.deepcopy(cfg)
    error, _ = integration._cultures_split_apply(FakeHass(), cfg, 'c1', 'c2', REAL)
    assert error[0] == 'species_mismatch' and cfg == before
    cfg = _config(_entry(jars={'c1': jar}))
    debits, original = [], integration._mixing_hatchery_debit
    integration._mixing_hatchery_debit = lambda h, c, litres, why: debits.append(litres)
    try:
        error, _ = integration._cultures_split_apply(FakeHass(), cfg, 'c1', '', REAL)
        assert error is None and debits == [1.929]
    finally:
        integration._mixing_hatchery_debit = original


def test_starter_plan_needs_a_measurement_and_preserves_mass_balance():
    assert cultures.acclimation_plan(None, 35)['available'] is False
    for start, target in ((27, 35), (35, 27), (10, 30), (27, 38)):
        plan = cultures.acclimation_plan(start, target, 500)
        salinity, volume = start, 500
        for step in plan['steps']:
            actual = (salinity * volume + target * step['addMl']) / (volume + step['addMl'])
            assert abs(actual - salinity) <= 5.05
            assert abs(actual - step['ppt']) < 0.11
            salinity, volume = actual, volume + step['addMl']
        assert abs(target - salinity) <= 5.05
    assert 'sieve' in cultures.acclimation_plan(27, 27)['line']


def test_heat_guard_finds_first_crossing_even_when_forecast_is_unsorted():
    rows = [{'at': _iso(NOW + timedelta(hours=h)), 'roomC': temp} for h, temp in ((8, 32), (4, 28), (1, math.nan), (2, 25))]
    result = cultures.heat_guard(rows, 'tigriopus', NOW)
    assert result['hoursUntil'] == 4 and result['peakC'] == 32


def test_maintenance_uses_first_harvest_and_fractional_culture_clocks():
    jar = _jar('tigriopus', 2, now=NOW)
    cfg = _config(_entry(jars={'c1': jar}, maintenance={'enabled': True, 'tasks': {'culture_c1_harvest': {'enabled': True, 'cadenceDays': 1}}}))
    assert not integration._maintenance_due_items(cfg, NOW)
    jar = _jar(started_ago_days=20, now=NOW, lastHarvestAt=_iso(NOW - timedelta(hours=13)))
    jar['cadence'] = {'harvestIntervalDays': 0.5}
    cfg['nps']['cultures']['jars']['c1'] = jar
    assert integration._maintenance_due_items(cfg, NOW)[0]['id'] == 'culture_c1_harvest'
    jar['state']['crashedAt'] = _iso(NOW)
    assert not integration._maintenance_due_items(cfg, NOW)


def test_zero_egg_count_is_recorded_and_not_treated_as_missing():
    cfg = _config(_entry(jars={'c1': _jar(started_ago_days=20)}))
    assert integration._cultures_log_apply(FakeHass(), cfg, 'c1', egg_ratio=0) is None
    assert cfg['nps']['cultures']['jars']['c1']['history'][0]['eggRatio'] == 0


def test_early_enrichment_completion_cannot_claim_a_finished_soak():
    entry = _entry()
    cfg = _config(entry)
    cfg['nps']['cultures']['enrichment']['state'] = {'startedAt': _iso(REAL), 'portionMl': 100, 'jarId': 'c1'}
    entry.options[CONF_SETTINGS] = cfg
    hass, conn = FakeHass(entries=[entry]), FakeConnection()
    run(integration.websocket_cultures_enrich_done(hass, conn, {'id': 1}))
    assert conn.errors[-1].code == 'soak_not_ready'
    assert _cultures(entry)['bottle']['remainingMl'] == 0
    cfg['nps']['cultures']['enrichment']['state']['startedAt'] = _iso(REAL - timedelta(hours=7))
    entry.options[CONF_SETTINGS] = cfg
    run(integration.websocket_cultures_enrich_done(hass, conn, {'id': 2}))
    b = _cultures(entry)['bottle']
    assert b['lastLoadEnriched'] and b['filledAt'] == _iso(REAL - timedelta(hours=7))
    assert b['enrichedAt'] == _iso(REAL - timedelta(hours=1))


def test_normaliser_and_engine_share_cadence_validation():
    for sid in cultures.species_ids():
        for value in (0, -1, 99999, math.inf, True, '12', 'junk'):
            overrides = {k: value for k in cultures.CADENCE_FIELDS}
            jar = integration._normalise_cultures({'jars': {'c1': {'species': sid, 'cadence': overrides}}})['jars']['c1']
            assert jar['cadence'] == cultures.cadence_for(sid, overrides)
    for value in ('junk', math.inf, True, -1, 61):
        jar = integration._normalise_cultures({'jars': {'c1': {'starterPpt': value}}})['jars']['c1']
        assert jar['starterPpt'] is None


def test_disabling_calendar_restarts_does_not_hide_a_rotifer_warning():
    jar = _jar(started_ago_days=20, now=NOW, lastSignAt=_iso(NOW), lastSign='milky')
    jar['cadence'] = {'restartIntervalDays': 0}
    st = cultures.culture_state(jar, NOW)
    assert st['restart']['due'] and st['restart']['reason'] == 'sign'


def test_small_vessel_gets_a_warning_when_purge_pushes_removal_above_thirty_percent():
    jar = {**_jar(), 'volumeL': 0.2, 'vesselKind': 'cone', 'purgeMl': 50}
    guide = cultures.harvest_guide(jar)
    assert guide['removalPct'] == 50 and '50.0%' in guide['warning']


def test_nps_uses_the_exact_culture_due_time_and_measured_tank_volume():
    from test_nps import _tl, _by_id
    jar = _jar('tigriopus', 40, now=NOW, lastHarvestAt=_iso(NOW - timedelta(days=10) + timedelta(hours=1)))
    cfg = {'enabled': True, 'jars': {'c1': jar}}
    assert not _by_id(_tl(NOW, cultures=cfg), 'culture:c1')
    assert _by_id(_tl(NOW + timedelta(hours=1), cultures=cfg), 'culture:c1')[0]['status'] == 'due'
    jar['history'] = [{'event': 'harvest', 'at': _iso(NOW - timedelta(hours=1)), 'ml': 625, 'tankMl': 80}]
    rows = _by_id(_tl(NOW, cultures=cfg), 'culture:c1')
    assert rows[0]['actualMl'] == 80


def test_rig_uses_the_due_cones_recipe_not_the_first_cone():
    jars = [{'id': 'a', 'name': 'A', 'vesselKind': 'cone', 'state': {'status': 'producing'}, 'due': [],
             'harvestGuide': {'totalMl': 250, 'mixMl': 250, 'rodiMl': 0, 'targetPpt': 35}},
            {'id': 'b', 'name': 'B', 'vesselKind': 'cone', 'state': {'status': 'producing'}, 'due': ['harvest'],
             'harvestGuide': {'totalMl': 625, 'mixMl': 521, 'rodiMl': 154, 'targetPpt': 27, 'purgeMl': 50}}]
    rig = cultures.rig_state(jars, {})
    assert rig['jug']['jarName'] == 'B' and rig['jug']['mixMl'] == 521 and 'B:' in rig['caption']


def test_history_retention_supports_learning_and_a_week_of_frequent_feeds():
    rows = [{'event': 'fed_tank', 'at': _iso(NOW - timedelta(hours=n)), 'ml': 20} for n in range(168)]
    normal = integration._normalise_cultures({'bottle': {'history': rows}, 'jars': {'c1': {'history': rows}}})
    assert len(normal['bottle']['history']) == 168 and len(normal['jars']['c1']['history']) == 168


if __name__ == '__main__':
    names = [k for k in sorted(globals()) if k.startswith('test_')]
    failures = 0
    for name in names:
        try:
            globals()[name]()
            print('PASS', name)
        except Exception:
            failures += 1
            traceback.print_exc()
    print(f'{len(names) - failures}/{len(names)} passed')
    raise SystemExit(bool(failures))
