import React from 'react';
import styles from '@/app/dashboard.module.css';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import { useSettings } from '@/context/SettingsContext';
import {
    Waves,
    Calendar,
    Thermometer,
    Moon,
    Zap,
    Info,
    ArrowRightLeft
} from 'lucide-react';

const REEF_PROFILES = [
    { id: 'gbr_cairns', name: 'Great Barrier Reef - Cairns', lat: -16.92, lon: 145.77, description: 'Classic GBR profiles with peak spawning in Nov/Dec.' },
    { id: 'caribbean_curacao', name: 'Caribbean - Curaçao', lat: 12.11, lon: -68.93, description: 'Caribbean spawning peaks typically in Aug/Sept.' },
    { id: 'red_sea_eilat', name: 'Red Sea - Eilat', lat: 29.55, lon: 34.95, description: 'Spring and summer spawning events common here.' },
    { id: 'indo_bali', name: 'Indo-Pacific - Bali', lat: -8.34, lon: 115.09, description: 'Year-round high biodiversity with specific local peaks.' },
];

export const SpawningScreen: React.FC = () => {
    const { settings, updateSpawningSetting } = useSettings();
    const { entities, updateInputSelect, updateInputNumber } = useHomeAssistant();

    const spawning = settings.spawning;

    // Get target state from HA if available
    const nextSpawnDate = entities?.[spawning.entities.nextSpawnDate]?.state || 'Oct 23, 2026';
    const moonPhase = entities?.[spawning.entities.moonPhase]?.state || 'Waxing Gibbous';
    const targetTemp = entities?.[spawning.entities.targetTemp]?.state || '--';

    const handleProfileChange = (profileId: string) => {
        updateSpawningSetting({ profileId });
        updateInputSelect(spawning.entities.profile, profileId);
    };

    const handleStrengthChange = (val: number) => {
        updateSpawningSetting({ spawnStrength: val });
        updateInputNumber(spawning.entities.strength, val);
    };

    const handlePhaseOffsetChange = (val: number) => {
        updateSpawningSetting({ phaseOffset: val });
        updateInputNumber(spawning.entities.phaseOffset, val);
    };

    const handleTempOffsetChange = (val: number) => {
        updateSpawningSetting({ tempOffset: val });
        updateInputNumber(spawning.entities.tempOffset, val);
    };

    return (
        <div className={styles.missionControl}>
            <div className={styles.statusBanner} style={{ backgroundColor: 'rgba(0, 180, 216, 0.1)', borderColor: '#00b4d8' }}>
                <Waves color="#00b4d8" size={24} />
                <h2 style={{ color: '#00b4d8', margin: 0, fontSize: '1.5rem', letterSpacing: '0.05em' }}>CORAL SPAWNING CONTROL</h2>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(350px, 1fr))', gap: '1.5rem', marginTop: '2rem' }}>
                {/* Active Status & Next Spawn */}
                <section className={styles.missionSection}>
                    <h3 className={styles.sectionSubtitle}>Spawning Status</h3>
                    <div className={styles.card} style={{ borderLeft: '4px solid #00b4d8', background: 'rgba(0, 180, 216, 0.05)' }}>
                        <div style={{ display: 'flex', gap: '1.5rem', alignItems: 'center' }}>
                            <div style={{
                                width: '60px',
                                height: '60px',
                                borderRadius: '50%',
                                background: 'rgba(0, 180, 216, 0.2)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                boxShadow: '0 0 20px rgba(0, 180, 216, 0.2)'
                            }}>
                                <Moon size={32} color="#00b4d8" />
                            </div>
                            <div>
                                <div style={{ fontSize: '0.8rem', color: '#778da9', textTransform: 'uppercase' }}>Next Predicted Spawn</div>
                                <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#fff' }}>{nextSpawnDate}</div>
                                <div style={{ fontSize: '0.9rem', color: '#4ade80', marginTop: '0.2rem' }}>{moonPhase} (84% Intensity)</div>
                            </div>
                        </div>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginTop: '1rem' }}>
                        <div className={styles.card}>
                            <div style={{ fontSize: '0.75rem', color: '#778da9', textTransform: 'uppercase' }}>Target Temp</div>
                            <div style={{ fontSize: '1.25rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                <Thermometer size={18} color="#f87171" />
                                {targetTemp}°C
                            </div>
                        </div>
                        <div className={styles.card}>
                            <div style={{ fontSize: '0.75rem', color: '#778da9', textTransform: 'uppercase' }}>Day Length</div>
                            <div style={{ fontSize: '1.25rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                <Calendar size={18} color="#fbbf24" />
                                13h 12m
                            </div>
                        </div>
                    </div>
                </section>

                {/* Profile Selection */}
                <section className={styles.missionSection}>
                    <h3 className={styles.sectionSubtitle}>Reef Profile</h3>
                    <div className={styles.card}>
                        <div style={{ marginBottom: '1.5rem' }}>
                            <label style={{ display: 'block', fontSize: '0.8rem', color: '#778da9', marginBottom: '0.5rem' }}>Location preset</label>
                            <select
                                className={styles.taskSelect}
                                style={{ width: '100%', padding: '0.75rem' }}
                                value={spawning.profileId}
                                onChange={(e) => handleProfileChange(e.target.value)}
                            >
                                {REEF_PROFILES.map(p => (
                                    <option key={p.id} value={p.id}>{p.name}</option>
                                ))}
                            </select>
                        </div>

                        <div style={{
                            padding: '1rem',
                            background: 'rgba(255,255,255,0.03)',
                            borderRadius: '8px',
                            display: 'flex',
                            gap: '1rem',
                            alignItems: 'flex-start'
                        }}>
                            <Info size={18} color="#00b4d8" style={{ marginTop: '2px' }} />
                            <p style={{ margin: 0, fontSize: '0.85rem', color: '#e0e1dd', lineHeight: '1.4' }}>
                                {REEF_PROFILES.find(p => p.id === spawning.profileId)?.description}
                            </p>
                        </div>
                    </div>
                </section>

                {/* Fine Tuning */}
                <section className={styles.missionSection} style={{ gridColumn: '1 / -1' }}>
                    <h3 className={styles.sectionSubtitle}>Advanced Parameters</h3>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1.5rem' }}>
                        <div className={styles.card}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1rem' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                    <Zap size={18} color="#fbbf24" />
                                    <span style={{ fontWeight: 600 }}>Spawn Strength</span>
                                </div>
                                <span style={{ color: '#fbbf24', fontWeight: 700 }}>{spawning.spawnStrength}%</span>
                            </div>
                            <input
                                type="range"
                                min="0"
                                max="200"
                                step="10"
                                value={spawning.spawnStrength}
                                onChange={(e) => handleStrengthChange(parseInt(e.target.value))}
                                style={{ width: '100%', accentColor: '#fbbf24' }}
                            />
                            <p style={{ fontSize: '0.75rem', color: '#778da9', marginTop: '0.5rem' }}>
                                Modulates light intensity and lunar peak brightness.
                            </p>
                        </div>

                        <div className={styles.card}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1rem' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                    <ArrowRightLeft size={18} color="#00b4d8" />
                                    <span style={{ fontWeight: 600 }}>Phase Offset</span>
                                </div>
                                <span style={{ color: '#00b4d8', fontWeight: 700 }}>{spawning.phaseOffset} Days</span>
                            </div>
                            <input
                                type="range"
                                min="-10"
                                max="10"
                                step="1"
                                value={spawning.phaseOffset}
                                onChange={(e) => handlePhaseOffsetChange(parseInt(e.target.value))}
                                style={{ width: '100%', accentColor: '#00b4d8' }}
                            />
                            <p style={{ fontSize: '0.75rem', color: '#778da9', marginTop: '0.5rem' }}>
                                Shifts the spawning window relative to the full moon.
                            </p>
                        </div>

                        <div className={styles.card}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1rem' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                    <Thermometer size={18} color="#f87171" />
                                    <span style={{ fontWeight: 600 }}>Temp Offset</span>
                                </div>
                                <span style={{ color: '#f87171', fontWeight: 700 }}>{spawning.tempOffset > 0 ? '+' : ''}{spawning.tempOffset}°C</span>
                            </div>
                            <input
                                type="range"
                                min="-2"
                                max="2"
                                step="0.1"
                                value={spawning.tempOffset}
                                onChange={(e) => handleTempOffsetChange(parseFloat(e.target.value))}
                                style={{ width: '100%', accentColor: '#f87171' }}
                            />
                            <p style={{ fontSize: '0.75rem', color: '#778da9', marginTop: '0.5rem' }}>
                                Global bias for the seasonal temperature curve.
                            </p>
                        </div>
                    </div>
                </section>

                {/* Season Shifting */}
                <section className={styles.missionSection} style={{ gridColumn: '1 / -1' }}>
                    <h3 className={styles.sectionSubtitle}>Seasonal Shifting</h3>
                    <div className={styles.card} style={{ border: '1px dashed rgba(255,255,255,0.1)', background: 'transparent' }}>
                        <div style={{ display: 'flex', gap: '1.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                            <div style={{ flex: 1, minWidth: '200px' }}>
                                <p style={{ margin: 0, fontSize: '0.9rem', color: '#778da9' }}>
                                    Spawning corals out of sync? Shift the historical data to match your current month.
                                </p>
                            </div>
                            <div style={{ display: 'flex', gap: '1rem' }}>
                                <button className={styles.syncButton} style={{ gap: '0.5rem' }}>
                                    <ArrowRightLeft size={16} />
                                    Match Current Month
                                </button>
                                <button className={styles.syncButton} style={{ background: 'rgba(255,255,255,0.05)', borderColor: 'rgba(255,255,255,0.1)', color: '#fff' }}>
                                    Custom Shift
                                </button>
                            </div>
                        </div>
                    </div>
                </section>
                {/* Tier 3 Integration Setup */}
                <section className={styles.missionSection} style={{ gridColumn: '1 / -1' }}>
                    <h3 className={styles.sectionSubtitle}>Tier 3 Home Assistant Integration Setup</h3>
                    <div className={styles.card} style={{ background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(0, 180, 216, 0.3)' }}>
                        <p style={{ fontSize: '0.9rem', color: '#e0e1dd', marginBottom: '1.5rem', lineHeight: '1.6' }}>
                            Copy the following code into your Home Assistant <code style={{ color: '#00b4d8' }}>configuration.yaml</code> and <code style={{ color: '#00b4d8' }}>automations.yaml</code> to enable the Tier 3 hybrid coral spawning system.
                            This connects your selected Tier 3 devices to the live sun, moon, and SST data for the <strong>{REEF_PROFILES.find(p => p.id === spawning.profileId)?.name}</strong> reef profile.
                        </p>

                        <div style={{ background: '#111827', padding: '1.5rem', borderRadius: '8px', overflowX: 'auto', fontFamily: 'monospace', fontSize: '0.85rem', color: '#a5b4fc', border: '1px solid rgba(255,255,255,0.1)' }}>
                            <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                                {`# ------------------------------------------------------------------------------------------------
# configuration.yaml
# ------------------------------------------------------------------------------------------------
rest:
  - resource: http://[YOUR_DASHBOARD_IP]:3000/api/spawning?lat=${REEF_PROFILES.find(p => p.id === spawning.profileId)?.lat}&lon=${REEF_PROFILES.find(p => p.id === spawning.profileId)?.lon}
    scan_interval: 21600 # Every 6 hours
    sensor:
      - name: "Coral Spawning Moon Phase"
        value_template: "{{ value_json.moon.fraction }}"
      - name: "Coral Spawning SST"
        value_template: "{{ value_json.seaSurfaceTemperature }}"
        unit_of_measurement: "°C"
      - name: "Coral Spawning Sunrise"
        value_template: "{{ value_json.sun.sunrise }}"
      - name: "Coral Spawning Sunset"
        value_template: "{{ value_json.sun.sunset }}"

# ------------------------------------------------------------------------------------------------
# automations.yaml
# ------------------------------------------------------------------------------------------------
- alias: "Tier 3: Sunrise Main Light"
  trigger:
    - platform: template
      value_template: "{{ now().strftime('%H:%M') == as_timestamp(states('sensor.coral_spawning_sunrise')) | timestamp_custom('%H:%M') }}"
  action:
    - service: switch.turn_on
      target:
        entity_id: ${spawning.entities.mainLightPlug || 'switch.YOUR_MAIN_LIGHT_PLUG'}

- alias: "Tier 3: Sunset Main Light"
  trigger:
    - platform: template
      value_template: "{{ now().strftime('%H:%M') == as_timestamp(states('sensor.coral_spawning_sunset')) | timestamp_custom('%H:%M') }}"
  action:
    - service: switch.turn_off
      target:
        entity_id: ${spawning.entities.mainLightPlug || 'switch.YOUR_MAIN_LIGHT_PLUG'}

- alias: "Tier 3: Moonlight Brightness"
  trigger:
    - platform: state
      entity_id: sensor.coral_spawning_moon_phase
  action:
    - service: light.turn_on
      target:
        entity_id: ${spawning.entities.moonlightBulb || 'light.YOUR_MOONLIGHT_BULB'}
      data:
        brightness_pct: "{{ (states('sensor.coral_spawning_moon_phase') | float * 100) | int }}"
        
- alias: "Tier 3: Set Reef Target Temp"
  trigger:
    - platform: state
      entity_id: sensor.coral_spawning_sst
  condition:
    - condition: template
      value_template: "{{ states('sensor.coral_spawning_sst') not in ['unknown', 'unavailable', 'None', ''] }}"
  action:
    - service: climate.set_temperature
      target:
        entity_id: ${spawning.entities.thermostatClimate || 'climate.YOUR_REEF_THERMOSTAT'}
      data:
        temperature: "{{ states('sensor.coral_spawning_sst') | float }}"`}
                            </pre>
                        </div>
                    </div>
                </section>
            </div>
        </div>
    );
};
