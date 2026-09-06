"""Thermal failure/recovery tests with standard HA sensors and switches only."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

import test_spawning as f
from _fake_ha import FakeConnection, FakeState

i = f.integration
NOON = datetime(2026, 6, 17, 13, tzinfo=timezone.utc)
RT = f.spawning.seasonal_temperature(f.REEF_PRESETS['gbr_central'], NOON.date())


class TemperatureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = NOON
        for name in ('now', 'utcnow'):
            p = patch.object(i.dt_util, name, side_effect=lambda: self.now)
            p.start()
            self.addCleanup(p.stop)

    def probe(self, value=RT, unit='°C', age=0):
        st = FakeState(str(value), {'unit_of_measurement': unit}, self.now)
        st.last_reported = self.now - timedelta(minutes=age)
        return st

    def setup_tank(self, value=RT - 0.4, heater='off', cooler='off', **settings):
        entry = f._temp_entry(**settings)
        hass = f._exec_hass(entry, {
            'sensor.tank_temp': self.probe(value), 'switch.heater': heater, 'switch.fan': cooler,
        })
        return hass, entry

    async def tick(self, hass, entry, seconds=0):
        self.now += timedelta(seconds=seconds)
        await i._async_spawning_tick(hass, entry, self.now)

    def runtime(self, hass):
        return hass.data[i.DOMAIN][i.SPAWNING_RUNTIME]

    def state(self, hass, entity='switch.heater'):
        return hass.states.get(entity).state

    def change(self, hass, entry, **changes):
        cfg = i._config_from_entry(entry)
        cfg['spawningProgram']['execution'].update(changes)
        i._persist_entry_config(hass, entry, cfg)

    async def test_unchanged_reading_uses_latest_report_and_converts_fahrenheit(self):
        for unit, value in (('°C', RT - 0.4), ('°F', (RT - 0.4) * 9 / 5 + 32)):
            hass, entry = self.setup_tank()
            st = self.probe(value, unit)
            st.last_updated = NOON - timedelta(hours=2)
            st.last_changed = NOON - timedelta(hours=2)
            hass.states.set('sensor.tank_temp', st)
            await self.tick(hass, entry)
            self.assertEqual(self.state(hass), 'on')
            self.assertNotIn('temp', self.runtime(hass)['issues'])

    async def test_bad_probe_requests_both_off_and_exposes_fault(self):
        probes = [self.probe('nan'), self.probe('inf'), self.probe('nonsense'),
                  self.probe(14), self.probe(33), self.probe(24, 'K'),
                  self.probe(24, ''), self.probe(24, age=16), self.probe(24, age=-2)]
        restored = self.probe()
        restored.attributes['restored'] = True
        probes.append(restored)
        for probe in probes:
            with self.subTest(value=probe.state, attrs=probe.attributes):
                hass, entry = self.setup_tank(heater='on', cooler='on')
                hass.states.set('sensor.tank_temp', probe)
                await self.tick(hass, entry)
                self.assertEqual(self.state(hass), 'off')
                self.assertEqual(self.state(hass, 'switch.fan'), 'off')
                self.assertIn('temp', self.runtime(hass)['issues'])
                self.assertTrue(any(c.domain == 'persistent_notification' for c in hass.services.calls))

    async def test_report_timeout_can_match_other_integrations(self):
        hass, entry = self.setup_tank(staleMinutes=30)
        hass.states.set('sensor.tank_temp', self.probe(RT - 0.4, age=20))
        await self.tick(hass, entry)
        self.assertEqual(self.state(hass), 'on')
        await self.tick(hass, entry, 11 * 60)
        self.assertEqual(self.state(hass), 'off')

    async def test_unfulfilled_safety_off_is_retried_and_never_claimed_success(self):
        hass, entry = self.setup_tank(heater='on')
        hass.states.set('sensor.tank_temp', 'unavailable')
        hass.services.responses[('switch', 'turn_off')] = None
        await self.tick(hass, entry)
        self.assertEqual(self.state(hass), 'on')
        self.assertTrue(any('not confirmed OFF' in m for m in self.runtime(hass)['issues'].values()))
        messages = ' '.join(c.data.get('message', '') for c in hass.services.calls)
        self.assertNotIn('were switched OFF', messages)
        del hass.services.responses[('switch', 'turn_off')]
        await self.tick(hass, entry, 60)
        self.assertEqual(self.state(hass), 'off')
        self.assertNotIn('temp_output_switch.heater', self.runtime(hass)['issues'])

    async def test_unfulfilled_heater_on_alerts_and_recovers(self):
        hass, entry = self.setup_tank()
        hass.services.responses[('switch', 'turn_on')] = None
        await self.tick(hass, entry)
        self.assertIn('temp_output_switch.heater', self.runtime(hass)['issues'])
        self.assertTrue(any(c.domain == 'persistent_notification' for c in hass.services.calls))
        del hass.services.responses[('switch', 'turn_on')]
        await self.tick(hass, entry, 60)
        self.assertEqual(self.state(hass), 'on')
        self.assertFalse(self.runtime(hass)['issues'])

    async def test_drift_alert_does_not_suppress_later_failed_safety_off(self):
        hass, entry = self.setup_tank(value=RT - 1.2)
        await self.tick(hass, entry)
        first = [c for c in hass.services.calls if c.domain == 'persistent_notification']
        self.assertEqual(len(first), 1)
        hass.states.set('sensor.tank_temp', 'unavailable')
        hass.services.responses[('switch', 'turn_off')] = None
        await self.tick(hass, entry, 60)
        notes = [c for c in hass.services.calls if c.domain == 'persistent_notification']
        self.assertEqual(len(notes), 2)
        self.assertIn('shutdown unconfirmed', notes[-1].data['title'])

    async def test_opposing_output_off_must_confirm_before_start(self):
        for warm, stuck in ((True, 'switch.heater'), (False, 'switch.fan')):
            hass, entry = self.setup_tank(value=RT + (0.4 if warm else -0.4),
                                          heater='on' if warm else 'off', cooler='off' if warm else 'on')
            hass.services.fail_on.add(('switch', 'turn_off', stuck))
            with self.assertLogs(i._LOGGER, level='WARNING'):
                await self.tick(hass, entry)
            self.assertFalse(any(c.service == 'turn_on' for c in hass.services.calls))
            self.assertIn('temp_interlock', self.runtime(hass)['issues'])
            hass.services.fail_on.clear()
            await self.tick(hass, entry, 60)
            self.assertEqual(self.state(hass, stuck), 'off')
            self.assertEqual(self.state(hass, 'switch.fan' if warm else 'switch.heater'), 'on')

    async def test_both_on_in_hold_band_are_stopped(self):
        hass, entry = self.setup_tank(value=RT, heater='on', cooler='on')
        await self.tick(hass, entry)
        self.assertEqual(self.state(hass), 'off')
        self.assertEqual(self.state(hass, 'switch.fan'), 'off')

    async def test_heating_only_and_cooling_only_need_no_phantom_opposing_output(self):
        for heating in (True, False):
            hass, entry = self.setup_tank(value=RT + (-0.4 if heating else 0.4),
                                          **({'coolEntity': None} if heating else {'heaterEntity': None}))
            await self.tick(hass, entry)
            self.assertEqual(self.state(hass, 'switch.heater' if heating else 'switch.fan'), 'on')
            self.assertFalse(self.runtime(hass)['issues'])

    async def test_bad_probe_arriving_during_opposing_off_prevents_start(self):
        hass, entry = self.setup_tank(cooler='on')
        original = hass.services.async_call
        async def lost_probe(domain, service, data=None, **kwargs):
            result = await original(domain, service, data, **kwargs)
            if service == 'turn_off':
                hass.states.set('sensor.tank_temp', 'unavailable')
            return result
        hass.services.async_call = lost_probe
        await self.tick(hass, entry)
        self.assertEqual(self.state(hass), 'off')
        self.assertFalse(any(c.service == 'turn_on' for c in hass.services.calls))

    async def test_concurrent_saves_cannot_drop_another_pending_release(self):
        hass, entry = self.setup_tank()
        await self.tick(hass, entry)
        temp = i._spawning_execution_cfg(i._config_from_entry(entry))['temp']
        self.change(hass, entry, temp={**temp, 'heaterEntity': 'switch.second'})
        hass.states.set('switch.second', 'on')
        original = hass.services.async_call
        async def change_again(domain, service, data=None, **kwargs):
            if service == 'turn_off' and data and 'switch.heater' in data.values():
                self.change(hass, entry, temp={**temp, 'heaterEntity': 'switch.third'})
            return await original(domain, service, data, **kwargs)
        hass.services.async_call = change_again
        await self.tick(hass, entry)
        self.assertIn('switch.second', i._spawning_owned_temp_outputs(entry))
        self.assertEqual(self.state(hass, 'switch.second'), 'on')
        hass.states.set('switch.third', 'off')
        await self.tick(hass, entry, 60)
        self.assertEqual(self.state(hass, 'switch.second'), 'off')
        self.assertEqual(self.state(hass, 'switch.third'), 'on')

    async def test_assumed_opposing_off_never_permits_heat(self):
        hass, entry = self.setup_tank()
        hass.states.set('switch.fan', FakeState('off', {'assumed_state': True}))
        hass.services.responses[('switch', 'turn_off')] = None
        await self.tick(hass, entry)
        self.assertEqual(self.state(hass), 'off')
        self.assertIn('temp_interlock', self.runtime(hass)['issues'])

    async def test_status_sees_new_probe_and_output_faults_between_ticks(self):
        hass, entry = self.setup_tank()
        await self.tick(hass, entry)
        config = i._config_from_entry(entry)
        self.assertEqual(i._spawning_health(hass, config, self.runtime(hass))['health'], 'ok')
        hass.states.set('sensor.tank_temp', 'unavailable')
        self.assertEqual(i._spawning_health(hass, config, self.runtime(hass))['health'], 'fault')
        hass.states.set('sensor.tank_temp', self.probe())
        hass.states.set('switch.fan', 'on')
        self.assertEqual(i._spawning_health(hass, config, self.runtime(hass))['health'], 'fault')

    async def test_disarm_and_failed_release_survive_runtime_restart(self):
        hass, entry = self.setup_tank()
        await self.tick(hass, entry)
        self.change(hass, entry, armed=False)
        cfg = i._config_from_entry(entry)
        cfg['spawningProgram']['enabled'] = False
        i._persist_entry_config(hass, entry, cfg)
        hass.services.responses[('switch', 'turn_off')] = None
        await self.tick(hass, entry)
        self.assertIn('switch.heater', i._spawning_owned_temp_outputs(entry))
        health = i._spawning_health(hass, i._config_from_entry(entry), self.runtime(hass))
        self.assertEqual(health['health'], 'fault')
        self.assertFalse(health['controlling'])
        await i._async_schedule_spawning_tick(hass, entry)
        self.assertIn(i.SPAWNING_TICK_UNSUB, hass.data[i.DOMAIN])
        restarted = f._exec_hass(entry, {'switch.heater': 'on', 'switch.fan': 'off'})
        await self.tick(restarted, entry, 60)
        self.assertEqual(self.state(restarted), 'off')
        self.assertFalse(i._spawning_owned_temp_outputs(entry))

    async def test_disarm_before_first_tick_still_releases_previous_bindings(self):
        hass, entry = self.setup_tank(heater='on')
        cfg = i._config_from_entry(entry)
        cfg['spawningProgram']['execution']['armed'] = False
        await i._async_save_config(hass, entry, cfg)
        await self.tick(hass, entry)
        self.assertEqual(self.state(hass), 'off')

    async def test_rebind_cannot_start_until_old_heater_is_off(self):
        hass, entry = self.setup_tank()
        await self.tick(hass, entry)
        new = dict(i._spawning_execution_cfg(i._config_from_entry(entry))['temp'], heaterEntity='switch.new_heater')
        self.change(hass, entry, temp=new)
        hass.states.set('switch.new_heater', 'off')
        hass.services.fail_on.add(('switch', 'turn_off', 'switch.heater'))
        with self.assertLogs(i._LOGGER, level='WARNING'):
            await self.tick(hass, entry)
        self.assertEqual(self.state(hass, 'switch.new_heater'), 'off')
        self.assertIn('switch.heater', entry.options[i.SPAWNING_TEMP_OUTPUTS])
        hass.services.fail_on.clear()
        await self.tick(hass, entry, 60)
        self.assertEqual(self.state(hass), 'off')
        self.assertEqual(self.state(hass, 'switch.new_heater'), 'on')

    async def test_disarm_during_inflight_on_compensates_with_off(self):
        hass, entry = self.setup_tank()
        entered, release = asyncio.Event(), asyncio.Event()
        original = hass.services.async_call
        async def delayed(domain, service, data=None, **kwargs):
            if service == 'turn_on':
                entered.set()
                await release.wait()
            return await original(domain, service, data, **kwargs)
        hass.services.async_call = delayed
        task = asyncio.create_task(self.tick(hass, entry))
        await entered.wait()
        self.change(hass, entry, armed=False)
        release.set()
        await task
        self.assertEqual(self.state(hass), 'off')
        self.assertFalse(i._spawning_execution_cfg(i._config_from_entry(entry))['armed'])

    async def test_probe_becoming_hot_during_on_is_stopped_on_return(self):
        hass, entry = self.setup_tank()
        original = hass.services.async_call
        async def heated(domain, service, data=None, **kwargs):
            result = await original(domain, service, data, **kwargs)
            if service == 'turn_on':
                hass.states.set('sensor.tank_temp', self.probe(30))
            return result
        hass.services.async_call = heated
        await self.tick(hass, entry)
        self.assertEqual(self.state(hass), 'off')
        self.assertIn('temp', self.runtime(hass)['issues'])

    async def test_timeout_does_not_prevent_other_safety_off(self):
        hass, entry = self.setup_tank(heater='on', cooler='on')
        hass.states.set('sensor.tank_temp', 'unavailable')
        original = hass.services.async_call
        async def hung(domain, service, data=None, **kwargs):
            if data and 'switch.heater' in data.values():
                await asyncio.Event().wait()
            return await original(domain, service, data, **kwargs)
        hass.services.async_call = hung
        with patch.object(i, 'SPAWNING_COMMAND_TIMEOUT_SECONDS', 0.02), self.assertLogs(i._LOGGER, level='WARNING'):
            await asyncio.wait_for(self.tick(hass, entry), 0.5)
        self.assertEqual(self.state(hass, 'switch.fan'), 'off')
        self.assertIn('temp_output_switch.heater', self.runtime(hass)['issues'])

    async def test_cooling_restart_delay_and_safety_stop(self):
        hass, entry = self.setup_tank(value=RT + 0.4, coolMinOffSeconds=180)
        await self.tick(hass, entry)
        self.assertEqual(self.state(hass, 'switch.fan'), 'off')
        await self.tick(hass, entry, 180)
        self.assertEqual(self.state(hass, 'switch.fan'), 'on')
        hass.states.set('sensor.tank_temp', 'unavailable')
        await self.tick(hass, entry, 1)
        self.assertEqual(self.state(hass, 'switch.fan'), 'off')
        hass.states.set('sensor.tank_temp', self.probe(RT + 0.4))
        restarted = f._exec_hass(entry, dict(hass.states._states))
        await self.tick(restarted, entry, 1)
        self.assertEqual(self.state(restarted, 'switch.fan'), 'off')

    async def test_unload_releases_thermal_outputs_and_retains_failed_release(self):
        for fail in (True, False):
            hass, entry = self.setup_tank()
            await self.tick(hass, entry)
            if fail:
                hass.services.responses[('switch', 'turn_off')] = None
            await i._async_spawning_stop(hass, entry)
            self.assertEqual(bool(i._spawning_owned_temp_outputs(entry)), fail)
            self.assertEqual(hass.states.get(i.SPAWNING_STATUS_ENTITY).state, 'fault' if fail else 'disarmed')
            self.assertEqual(self.state(hass), 'on' if fail else 'off')
            await self.tick(hass, entry)
            self.assertEqual(self.state(hass), 'on' if fail else 'off')

    async def test_profile_limits_block_arming_but_allow_disarm(self):
        for pid, preset in f.REEF_PRESETS.items():
            entry = f._temp_entry(maxC=27.5)
            hass = f._exec_hass(entry)
            cfg = i._config_from_entry(entry)
            cfg['spawningProgram']['reefPreset'] = pid
            before = deepcopy(cfg['spawningProgram']['execution']['temp'])
            conn = FakeConnection()
            await i.websocket_save_config(hass, conn, {'id': 1, 'config': cfg})
            compatible = min(preset['sstMonthlyC']) - 0.2 >= 22 and max(preset['sstMonthlyC']) + 0.2 <= 27.5
            self.assertEqual(bool(conn.errors), not compatible)
            self.assertEqual(cfg['spawningProgram']['execution']['temp'], before)
            cfg['spawningProgram']['execution']['armed'] = False
            conn = FakeConnection()
            await i.websocket_save_config(hass, conn, {'id': 2, 'config': cfg})
            self.assertFalse(conn.errors)

    async def test_legacy_invalid_curve_stops_outputs_without_raising_limits(self):
        hass, entry = self.setup_tank(heater='on', maxC=27.5)
        await self.tick(hass, entry)
        self.assertEqual(self.state(hass), 'off')
        self.assertIn('temp', self.runtime(hass)['issues'])
        self.assertEqual(i._spawning_execution_cfg(i._config_from_entry(entry))['temp']['maxC'], 27.5)

    def test_nonfinite_limits_never_expand_to_maximum(self):
        for invalid in ('nan', 'inf', '-inf'):
            entry = f._temp_entry(maxC=invalid, minC=invalid)
            temp = i._spawning_execution_cfg(i._config_from_entry(entry))['temp']
            self.assertEqual((temp['minC'], temp['maxC']), (22.0, 27.5))

    def test_seasonal_curve_is_continuous_for_all_presets_offsets_and_leap_year(self):
        for preset in f.REEF_PRESETS.values():
            for offset in range(12):
                day = datetime(2027, 1, 1).date()
                last = f.spawning.seasonal_temperature(preset, day - timedelta(days=1), offset)
                while day.year <= 2028:
                    value = f.spawning.seasonal_temperature(preset, day, offset)
                    self.assertLess(abs(value - last), 0.08)
                    self.assertGreaterEqual(value, min(preset['sstMonthlyC']))
                    self.assertLessEqual(value, max(preset['sstMonthlyC']))
                    if day.day == 15:
                        self.assertEqual(value, preset['sstMonthlyC'][(day.month - 1 - offset) % 12])
                    last = value
                    day += timedelta(days=1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
