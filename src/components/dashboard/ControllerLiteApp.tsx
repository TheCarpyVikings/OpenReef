'use client';

import React, { useEffect, useMemo, useState } from 'react';
import {
    Activity,
    ArrowLeft,
    ArrowRight,
    Check,
    Leaf,
    Power,
    Search,
    Settings,
    Shield,
    Thermometer,
    Wind,
    Zap,
} from 'lucide-react';
import type { HassEntities } from 'home-assistant-js-websocket';
import styles from '@/app/dashboard.module.css';
import { SettingsProvider, useSettings, type AppSettings } from '@/context/SettingsContext';
import { apiFetch, withIngressPath } from '@/lib/api-fetch';
import {
    formatNumber,
    getEntityState,
    getMvpEntityIds,
    getMvpSensorEntityId,
    MVP_SENSOR_IDS,
    MVP_SENSOR_META,
    parseEntityNumber,
    sensorStatus,
    type MvpSensorId,
} from '@/lib/openreef-mvp';
import { getEquipmentSuggestionTarget, getSensorSuggestionTarget, type EntitySuggestionTarget } from '@/lib/entity-suggestions';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import { SafeEntityPicker } from './SafeEntityPicker';
import { StatusCard } from './StatusCard';

type ControllerLiteAppProps = {
    initialView?: 'dashboard' | 'setup';
    onExit?: () => void;
};

type MvpTab = 'mission' | 'live' | 'controls' | 'energy' | 'settings';

const TAB_CONFIG: Array<{ id: MvpTab; label: string; icon: React.ReactNode }> = [
    { id: 'mission', label: 'Mission Control', icon: <Shield size={20} /> },
    { id: 'live', label: 'Live Stats', icon: <Activity size={20} /> },
    { id: 'controls', label: 'Controls', icon: <Power size={20} /> },
    { id: 'energy', label: 'Energy', icon: <Zap size={20} /> },
    { id: 'settings', label: 'Settings', icon: <Settings size={20} /> },
];

const energyTarget = (
    id: string,
    label: string,
    keywords: string[],
    deviceClasses: string[],
    units: string[],
): EntitySuggestionTarget => ({
    id,
    label,
    domains: ['sensor'],
    keywords,
    prefer: ['reef', 'tank', 'aquarium', 'energy', 'power', 'cost'],
    avoid: [],
    deviceClasses,
    units,
});

function ControllerLiteContent({ initialView = 'dashboard', onExit }: ControllerLiteAppProps) {
    const { settings } = useSettings();
    const { entities, isConnected, error, reconnect } = useHomeAssistant();
    const [activeTab, setActiveTab] = useState<MvpTab>('mission');
    const [setupOpen, setSetupOpen] = useState(initialView === 'setup');
    const logoSrc = withIngressPath('/openreef-logo.png');

    const entityIds = useMemo(() => getMvpEntityIds(settings), [settings]);
    const entityKey = entityIds.join('|');

    useEffect(() => {
        if (setupOpen) return;
        const ids = entityKey ? entityKey.split('|') : [];
        void reconnect(ids);
        const interval = window.setInterval(() => {
            void reconnect(ids);
        }, 30_000);
        return () => window.clearInterval(interval);
    }, [entityKey, reconnect, setupOpen]);

    const handleStatusClick = () => {
        void reconnect(entityIds);
    };

    return (
        <div className={styles.dashboardContainer}>
            <header className={styles.header}>
                <div className={styles.mvpHeaderBrand}>
                    {/* eslint-disable-next-line @next/next/no-img-element -- Ingress path is only known in the browser. */}
                    <img suppressHydrationWarning src={logoSrc} alt="OpenReef Logo" width={56} height={56} />
                    <div>
                        <h1 className={styles.title}>{settings.general.tankName || 'OpenReef'}</h1>
                        <p className={styles.mvpMuted}>{settings.general.userName ? `${settings.general.userName}'s OpenReef` : 'Controller-lite MVP'}</p>
                    </div>
                </div>
                <div className={styles.mvpHeaderActions}>
                    <button type="button" className={styles.secondaryButton} onClick={() => setSetupOpen(true)}>
                        <Settings size={18} />
                        Setup
                    </button>
                    <button
                        type="button"
                        className={styles.statusIndicator}
                        title={isConnected ? 'HA Connected' : error || 'Click to check Home Assistant'}
                        onClick={handleStatusClick}
                    >
                        <div className={`${styles.statusDot} ${isConnected ? styles.connected : styles.disconnected}`} />
                        <span className={styles.statusText}>{isConnected ? 'HA Connected' : error || 'Check HA'}</span>
                    </button>
                </div>
            </header>

            <nav className={styles.navBar}>
                {TAB_CONFIG.map((tab) => (
                    <button
                        key={tab.id}
                        className={`${styles.tabButton} ${activeTab === tab.id ? styles.activeTab : ''}`}
                        onClick={() => setActiveTab(tab.id)}
                    >
                        {tab.icon}
                        <span>{tab.label}</span>
                    </button>
                ))}
            </nav>

            {activeTab === 'mission' && <MvpMissionControl entities={entities} />}
            {activeTab === 'live' && <MvpLiveStats entities={entities} />}
            {activeTab === 'controls' && <MvpControls entities={entities} />}
            {activeTab === 'energy' && <MvpEnergy entities={entities} />}
            {activeTab === 'settings' && <MvpSettings onOpenSetup={() => setSetupOpen(true)} />}

            {setupOpen && (
                <MvpSetupWizard
                    onClose={() => {
                        setSetupOpen(false);
                        onExit?.();
                    }}
                />
            )}
        </div>
    );
}

function MvpMissionControl({ entities }: { entities: HassEntities | null }) {
    const { settings, getEquipmentName, getLabel } = useSettings();
    const sensorRows = MVP_SENSOR_IDS.map((sensorId) => {
        const entityId = getMvpSensorEntityId(settings, sensorId);
        const value = parseEntityNumber(entities, entityId);
        const threshold = settings.thresholds[sensorId];
        return {
            id: sensorId,
            label: getLabel(sensorId, MVP_SENSOR_META[sensorId].label),
            value,
            unit: MVP_SENSOR_META[sensorId].unit,
            status: sensorStatus(value, threshold),
        };
    });
    const criticalSensors = sensorRows.filter((sensor) => sensor.status === 'critical');
    const warningSensors = sensorRows.filter((sensor) => sensor.status === 'warning');
    const equipmentRows = Object.entries(settings.entities.equipment).map(([key, config]) => ({
        key,
        label: getEquipmentName(key, key),
        state: getEntityState(entities, config.switch),
        armed: config.controlEnabled === true,
        entityId: config.switch,
    }));
    const offlineArmedEquipment = equipmentRows.filter((equipment) => equipment.armed && equipment.state !== 'on');

    const status = criticalSensors.length > 0 || offlineArmedEquipment.length > 0
        ? { label: 'Action needed', color: '#ef4444' }
        : warningSensors.length > 0
            ? { label: 'Watch closely', color: '#fbbf24' }
            : { label: 'All systems nominal', color: '#4ade80' };

    return (
        <section className={styles.grid}>
            <h2 className={styles.sectionTitle}>Mission Control</h2>
            <div className={styles.mvpStatusBanner} style={{ borderColor: `${status.color}80`, background: `${status.color}18` }}>
                <span className={styles.mvpPulse} style={{ backgroundColor: status.color }} />
                <strong>{status.label}</strong>
                <span>{criticalSensors.length} critical sensor issue(s), {offlineArmedEquipment.length} armed equipment issue(s)</span>
            </div>

            <div className={styles.card}>
                <h3 className={styles.mvpCardTitle}>Core Parameters</h3>
                <div className={styles.mvpList}>
                    {sensorRows.map((sensor) => (
                        <div key={sensor.id} className={styles.mvpListRow}>
                            <span>{sensor.label}</span>
                            <strong className={sensor.status === 'critical' ? styles.danger : sensor.status === 'warning' ? styles.warning : styles.safe}>
                                {formatNumber(sensor.value, sensor.id === 'ph' ? 2 : 1)} {sensor.unit}
                            </strong>
                        </div>
                    ))}
                </div>
            </div>

            <div className={styles.card}>
                <h3 className={styles.mvpCardTitle}>Armed Equipment</h3>
                <div className={styles.mvpList}>
                    {equipmentRows.filter((equipment) => equipment.armed).length === 0 && (
                        <p className={styles.mvpMuted}>No equipment controls armed yet.</p>
                    )}
                    {equipmentRows.filter((equipment) => equipment.armed).map((equipment) => (
                        <div key={equipment.key} className={styles.mvpListRow}>
                            <span>{equipment.label}</span>
                            <strong className={equipment.state === 'on' ? styles.safe : styles.warning}>
                                {equipment.state || 'unknown'}
                            </strong>
                        </div>
                    ))}
                </div>
            </div>
        </section>
    );
}

function MvpLiveStats({ entities }: { entities: HassEntities | null }) {
    const { settings, getLabel } = useSettings();

    return (
        <section className={styles.grid}>
            <h2 className={styles.sectionTitle}>Live Stats</h2>
            {MVP_SENSOR_IDS.map((sensorId) => {
                const meta = MVP_SENSOR_META[sensorId];
                const entityId = getMvpSensorEntityId(settings, sensorId);
                return (
                    <StatusCard
                        key={sensorId}
                        label={getLabel(sensorId, meta.label)}
                        value={getEntityState(entities, entityId)}
                        unit={meta.unit}
                        min={settings.thresholds[sensorId]?.min}
                        max={settings.thresholds[sensorId]?.max}
                        icon={sensorId === 'co2' ? <Wind size={18} /> : sensorId === 'temp' || sensorId === 'room_temp' ? <Thermometer size={18} /> : <Activity size={18} />}
                        variant="numbers"
                    />
                );
            })}
        </section>
    );
}

function MvpControls({ entities }: { entities: HassEntities | null }) {
    const { settings, getEquipmentName, updateSettings } = useSettings();
    const { toggleEquipment, reconnect } = useHomeAssistant();
    const [busyKey, setBusyKey] = useState<string | null>(null);
    const [message, setMessage] = useState<string | null>(null);

    const setArmed = (equipmentId: string, enabled: boolean) => {
        if (enabled && !window.confirm(`Arm OpenReef control for ${getEquipmentName(equipmentId, equipmentId)}?`)) {
            return;
        }

        updateSettings({
            entities: {
                ...settings.entities,
                equipment: {
                    ...settings.entities.equipment,
                    [equipmentId]: {
                        ...settings.entities.equipment[equipmentId],
                        controlEnabled: enabled,
                    },
                },
            },
        });
    };

    const handleToggle = async (equipmentId: string) => {
        setBusyKey(equipmentId);
        setMessage(null);
        try {
            await toggleEquipment(equipmentId);
            const switchEntity = settings.entities.equipment[equipmentId]?.switch;
            await reconnect(switchEntity ? [switchEntity] : []);
        } catch (err) {
            setMessage(err instanceof Error ? err.message : 'Could not toggle equipment');
        } finally {
            setBusyKey(null);
        }
    };

    return (
        <section className={styles.grid}>
            <h2 className={styles.sectionTitle}>Controls</h2>
            {message && <div className={styles.errorMessage}>{message}</div>}
            <div className={styles.mvpFullGrid}>
                {Object.entries(settings.entities.equipment).map(([key, config]) => {
                    const label = getEquipmentName(key, key);
                    const state = getEntityState(entities, config.switch);
                    const isArmed = config.controlEnabled === true;
                    const canToggle = Boolean(config.switch && isArmed && busyKey !== key);
                    return (
                        <div key={key} className={styles.card}>
                            <div className={styles.mvpControlHeader}>
                                <div>
                                    <div className={styles.sensorLabel}>Equipment</div>
                                    <h3 className={styles.mvpCardTitle}>{label}</h3>
                                    <p className={styles.mvpMuted}>{config.switch || 'No switch mapped'}</p>
                                </div>
                                <strong className={state === 'on' ? styles.safe : state ? styles.warning : styles.mvpMuted}>
                                    {state || 'unknown'}
                                </strong>
                            </div>
                            <div className={styles.mvpControlActions}>
                                <label className={styles.mvpArmToggle}>
                                    <input
                                        type="checkbox"
                                        checked={isArmed}
                                        onChange={(event) => setArmed(key, event.target.checked)}
                                    />
                                    <span>{isArmed ? 'Armed' : 'Locked'}</span>
                                </label>
                                <button
                                    type="button"
                                    className={styles.primaryButton}
                                    disabled={!canToggle}
                                    onClick={() => { void handleToggle(key); }}
                                >
                                    <Power size={18} />
                                    {busyKey === key ? 'Toggling...' : 'Toggle'}
                                </button>
                            </div>
                        </div>
                    );
                })}
            </div>
        </section>
    );
}

function MvpEnergy({ entities }: { entities: HassEntities | null }) {
    const { settings, getEquipmentName } = useSettings();
    const equipmentPower = Object.values(settings.entities.equipment).reduce((total, config) => {
        const power = parseEntityNumber(entities, config.power);
        return total + (Number.isFinite(power) ? power : 0);
    }, 0);
    const tankMainPower = parseEntityNumber(entities, settings.entities.tankMain.power);
    const currentPower = Number.isFinite(tankMainPower) ? tankMainPower : equipmentPower;
    const energy = settings.entities.energy;

    return (
        <section className={styles.grid}>
            <h2 className={styles.sectionTitle}>Energy</h2>
            <MetricCard label="Current Load" value={formatNumber(currentPower, 1)} unit="W" />
            <MetricCard label="Daily Usage" value={formatNumber(parseEntityNumber(entities, energy.dailyEnergy), 0)} unit="Wh" />
            <MetricCard label="Weekly Usage" value={formatNumber(parseEntityNumber(entities, energy.weeklyEnergy), 0)} unit="Wh" />
            <MetricCard label="Monthly Usage" value={formatNumber(parseEntityNumber(entities, energy.monthlyEnergy), 0)} unit="Wh" />
            <MetricCard label="Daily Cost" value={formatNumber(parseEntityNumber(entities, energy.dailyCost), 2)} unit="£" prefix />
            <MetricCard label="Weekly Cost" value={formatNumber(parseEntityNumber(entities, energy.weeklyCost), 2)} unit="£" prefix />
            <MetricCard label="Monthly Cost" value={formatNumber(parseEntityNumber(entities, energy.monthlyCost), 2)} unit="£" prefix />

            <div className={styles.mvpFullGrid}>
                {Object.entries(settings.entities.equipment).map(([key, config]) => (
                    <div key={key} className={styles.card}>
                        <h3 className={styles.mvpCardTitle}>{getEquipmentName(key, key)}</h3>
                        <div className={styles.mvpList}>
                            <div className={styles.mvpListRow}>
                                <span>Power</span>
                                <strong>{formatNumber(parseEntityNumber(entities, config.power), 1)} W</strong>
                            </div>
                            <div className={styles.mvpListRow}>
                                <span>Energy</span>
                                <strong>{formatNumber(parseEntityNumber(entities, config.energy), 1)} Wh</strong>
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </section>
    );
}

function MvpSettings({ onOpenSetup }: { onOpenSetup: () => void }) {
    const { settings, updateNestedSetting, updateSettings, getEquipmentName } = useSettings();
    const themeColors = ['#00b4d8', '#4ade80', '#fbbf24', '#f87171', '#a855f7', '#ec4899'];

    const updateThreshold = (sensorId: MvpSensorId, bound: 'min' | 'max', value: string) => {
        const parsed = parseFloat(value);
        if (!Number.isFinite(parsed)) return;
        updateSettings({
            thresholds: {
                ...settings.thresholds,
                [sensorId]: {
                    ...settings.thresholds[sensorId],
                    [bound]: parsed,
                },
            },
        });
    };

    const updateAlias = (equipmentId: string, alias: string) => {
        updateSettings({
            equipment: {
                ...settings.equipment,
                aliases: {
                    ...settings.equipment.aliases,
                    [equipmentId]: alias,
                },
            },
        });
    };

    const setArmed = (equipmentId: string, enabled: boolean) => {
        if (enabled && !window.confirm(`Arm OpenReef control for ${getEquipmentName(equipmentId, equipmentId)}?`)) {
            return;
        }

        updateSettings({
            entities: {
                ...settings.entities,
                equipment: {
                    ...settings.entities.equipment,
                    [equipmentId]: {
                        ...settings.entities.equipment[equipmentId],
                        controlEnabled: enabled,
                    },
                },
            },
        });
    };

    return (
        <section className={styles.grid}>
            <h2 className={styles.sectionTitle}>Settings</h2>

            <div className={styles.card}>
                <h3 className={styles.mvpCardTitle}>App Experience</h3>
                <div className={styles.settingGroup}>
                    <label className={styles.label}>Tank Name</label>
                    <input
                        className={styles.input}
                        value={settings.general.tankName}
                        onChange={(event) => updateNestedSetting('general', { tankName: event.target.value })}
                    />
                </div>
                <div className={styles.settingGroup}>
                    <label className={styles.label}>Your Name</label>
                    <input
                        className={styles.input}
                        value={settings.general.userName}
                        onChange={(event) => updateNestedSetting('general', { userName: event.target.value })}
                    />
                </div>
                <div className={styles.settingGroup}>
                    <label className={styles.label}>Theme Color</label>
                    <div className={styles.colorGrid}>
                        {themeColors.map((color) => (
                            <button
                                key={color}
                                type="button"
                                title={color}
                                onClick={() => updateNestedSetting('general', { themeColor: color })}
                                style={{
                                    width: 38,
                                    height: 38,
                                    borderRadius: 999,
                                    border: settings.general.themeColor === color ? '3px solid #fff' : '1px solid rgba(255,255,255,0.2)',
                                    background: color,
                                    cursor: 'pointer',
                                }}
                            />
                        ))}
                    </div>
                </div>
                <div className={styles.settingGroup}>
                    <label className={styles.label}>Energy Tariff (£/kWh)</label>
                    <input
                        type="number"
                        step="0.01"
                        className={styles.input}
                        value={settings.general.energyTariff}
                        onChange={(event) => updateNestedSetting('general', { energyTariff: parseFloat(event.target.value) || 0 })}
                    />
                </div>
                <button type="button" className={styles.primaryButton} onClick={onOpenSetup}>
                    <Settings size={18} />
                    Reopen Setup
                </button>
            </div>

            <div className={styles.card}>
                <h3 className={styles.mvpCardTitle}>Live Stat Thresholds</h3>
                <div className={styles.mvpList}>
                    {MVP_SENSOR_IDS.map((sensorId) => {
                        const meta = MVP_SENSOR_META[sensorId];
                        const threshold = settings.thresholds[sensorId];
                        return (
                            <div key={sensorId} className={styles.mvpThresholdRow}>
                                <span>{meta.label}</span>
                                <label>
                                    Min
                                    <input
                                        type="number"
                                        step="0.01"
                                        className={styles.input}
                                        value={threshold?.min ?? 0}
                                        onChange={(event) => updateThreshold(sensorId, 'min', event.target.value)}
                                    />
                                </label>
                                <label>
                                    Max
                                    <input
                                        type="number"
                                        step="0.01"
                                        className={styles.input}
                                        value={threshold?.max ?? 0}
                                        onChange={(event) => updateThreshold(sensorId, 'max', event.target.value)}
                                    />
                                </label>
                            </div>
                        );
                    })}
                </div>
            </div>

            <div className={styles.mvpFullGrid}>
                {Object.entries(settings.entities.equipment).map(([key, config]) => (
                    <div key={key} className={styles.card}>
                        <h3 className={styles.mvpCardTitle}>{getEquipmentName(key, key)}</h3>
                        <div className={styles.settingGroup}>
                            <label className={styles.label}>Display Name</label>
                            <input
                                className={styles.input}
                                value={settings.equipment.aliases[key] || ''}
                                placeholder={key.replace(/_/g, ' ')}
                                onChange={(event) => updateAlias(key, event.target.value)}
                            />
                        </div>
                        <div className={styles.mvpList}>
                            <div className={styles.mvpListRow}>
                                <span>Switch</span>
                                <code>{config.switch || 'Not mapped'}</code>
                            </div>
                            <div className={styles.mvpListRow}>
                                <span>Control</span>
                                <label className={styles.mvpArmToggle}>
                                    <input
                                        type="checkbox"
                                        checked={config.controlEnabled === true}
                                        onChange={(event) => setArmed(key, event.target.checked)}
                                    />
                                    <span>{config.controlEnabled ? 'Armed' : 'Locked'}</span>
                                </label>
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </section>
    );
}

function MetricCard({ label, value, unit, prefix = false }: { label: string; value: string; unit: string; prefix?: boolean }) {
    return (
        <div className={styles.statCard}>
            <div className={styles.statLabel}>{label}</div>
            <div className={styles.statValue}>
                {prefix && <span className={styles.statUnit}>{unit}</span>}
                {value}
                {!prefix && <span className={styles.statUnit}> {unit}</span>}
            </div>
        </div>
    );
}

function MvpSetupWizard({ onClose }: { onClose: () => void }) {
    const { settings, updateSettings, updateNestedSetting, getEquipmentName } = useSettings();
    const [step, setStep] = useState(0);
    const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'ok' | 'error'>('idle');
    const steps = ['Basics', 'Sensors', 'Equipment', 'Energy'];

    const updateEntities = (entities: AppSettings['entities']) => {
        updateSettings({ entities });
    };

    const updateSensor = (sensorId: MvpSensorId, entityId: string) => {
        const meta = MVP_SENSOR_META[sensorId];
        if (meta.group === 'tank') {
            updateEntities({
                ...settings.entities,
                tank: { ...settings.entities.tank, [meta.key]: entityId },
            });
            return;
        }

        updateEntities({
            ...settings.entities,
            room: { ...settings.entities.room, [meta.key]: entityId },
        });
    };

    const updateEquipment = (equipmentId: string, field: 'switch' | 'power' | 'energy', entityId: string) => {
        updateEntities({
            ...settings.entities,
            equipment: {
                ...settings.entities.equipment,
                [equipmentId]: {
                    ...settings.entities.equipment[equipmentId],
                    [field]: entityId,
                    controlEnabled: settings.entities.equipment[equipmentId]?.controlEnabled ?? false,
                },
            },
        });
    };

    const updateEnergyEntity = (field: keyof AppSettings['entities']['energy'], entityId: string) => {
        updateEntities({
            ...settings.entities,
            energy: { ...settings.entities.energy, [field]: entityId },
        });
    };

    const testConnection = async () => {
        setTestStatus('testing');
        try {
            const [healthResponse, configResponse] = await Promise.all([
                apiFetch('/api/health'),
                apiFetch('/api/ha/config'),
            ]);
            if (!healthResponse.ok || !configResponse.ok) {
                throw new Error('OpenReef add-on health check failed');
            }
            setTestStatus('ok');
        } catch {
            setTestStatus('error');
        }
    };

    return (
        <div className={styles.wizardOverlay}>
            <div className={styles.wizardContent}>
                <div className={styles.wizardProgress}>
                    {steps.map((label, index) => (
                        <React.Fragment key={label}>
                            <div className={`${styles.wizardStepDot} ${index <= step ? styles.activeDot : ''}`}>
                                {index < step ? <Check size={12} /> : index + 1}
                            </div>
                            {index < steps.length - 1 && (
                                <div className={`${styles.wizardStepLine} ${index < step ? styles.activeLine : ''}`} />
                            )}
                        </React.Fragment>
                    ))}
                </div>

                <div className={styles.wizardBody}>
                    {step === 0 && (
                        <div className={styles.wizardStepContainer}>
                            <Leaf size={54} color="#00b4d8" />
                            <h2>OpenReef setup</h2>
                            <p className={styles.wizardDescription}>Map only the entities the MVP needs. Entity search is targeted and capped, so Home Assistant is never asked for a full state dump.</p>
                            <div className={styles.wizardGrid}>
                                <div className={styles.settingGroup}>
                                    <label className={styles.label}>Tank Name</label>
                                    <input className={styles.input} value={settings.general.tankName} onChange={(event) => updateNestedSetting('general', { tankName: event.target.value })} />
                                </div>
                                <div className={styles.settingGroup}>
                                    <label className={styles.label}>Your Name</label>
                                    <input className={styles.input} value={settings.general.userName} onChange={(event) => updateNestedSetting('general', { userName: event.target.value })} />
                                </div>
                            </div>
                            <button type="button" className={styles.secondaryButton} onClick={() => { void testConnection(); }}>
                                <Search size={18} />
                                {testStatus === 'testing' ? 'Testing...' : testStatus === 'ok' ? 'Connection OK' : 'Test Connection'}
                            </button>
                            {testStatus === 'error' && <div className={styles.errorMessage}>Could not reach the OpenReef Home Assistant integration.</div>}
                        </div>
                    )}

                    {step === 1 && (
                        <div className={styles.wizardStepContainer}>
                            <h2>Map sensors</h2>
                            <p className={styles.wizardDescription}>Use existing Home Assistant entities for tank and room monitoring.</p>
                            <div className={styles.wizardGrid}>
                                {MVP_SENSOR_IDS.map((sensorId) => {
                                    const meta = MVP_SENSOR_META[sensorId];
                                    return (
                                        <SafeEntityPicker
                                            key={sensorId}
                                            label={meta.label}
                                            value={getMvpSensorEntityId(settings, sensorId)}
                                            placeholder={meta.group === 'tank' ? `sensor.tank_${sensorId}` : `sensor.room_${meta.key}`}
                                            target={getSensorSuggestionTarget(sensorId, meta.label, meta.group)}
                                            onChange={(entityId) => updateSensor(sensorId, entityId)}
                                        />
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {step === 2 && (
                        <div className={styles.wizardStepContainer}>
                            <h2>Map equipment</h2>
                            <p className={styles.wizardDescription}>Switches are required for Controls. Power and energy sensors are optional.</p>
                            <div className={styles.wizardGrid}>
                                {Object.entries(settings.entities.equipment).map(([key, config]) => (
                                    <div key={key} className={styles.card}>
                                        <h3 className={styles.mvpCardTitle}>{getEquipmentName(key, key)}</h3>
                                        <SafeEntityPicker
                                            label="Switch"
                                            value={config.switch}
                                            placeholder="switch.device_name"
                                            target={getEquipmentSuggestionTarget(key, getEquipmentName(key, key), 'switch')}
                                            onChange={(entityId) => updateEquipment(key, 'switch', entityId)}
                                        />
                                        <SafeEntityPicker
                                            label="Power"
                                            value={config.power}
                                            placeholder="sensor.device_power"
                                            target={getEquipmentSuggestionTarget(key, getEquipmentName(key, key), 'power')}
                                            onChange={(entityId) => updateEquipment(key, 'power', entityId)}
                                        />
                                        <SafeEntityPicker
                                            label="Energy"
                                            value={config.energy}
                                            placeholder="sensor.device_energy"
                                            target={getEquipmentSuggestionTarget(key, getEquipmentName(key, key), 'energy')}
                                            onChange={(entityId) => updateEquipment(key, 'energy', entityId)}
                                        />
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {step === 3 && (
                        <div className={styles.wizardStepContainer}>
                            <h2>Energy and cost</h2>
                            <p className={styles.wizardDescription}>These are optional. Leave fields blank if Home Assistant does not already expose them.</p>
                            <div className={styles.wizardGrid}>
                                <SafeEntityPicker label="Daily Energy" value={settings.entities.energy.dailyEnergy} placeholder="sensor.reef_daily_energy" target={energyTarget('daily_energy', 'Daily Energy', ['daily energy', 'today energy', 'energy'], ['energy'], ['Wh', 'kWh'])} onChange={(entityId) => updateEnergyEntity('dailyEnergy', entityId)} />
                                <SafeEntityPicker label="Weekly Energy" value={settings.entities.energy.weeklyEnergy} placeholder="sensor.reef_weekly_energy" target={energyTarget('weekly_energy', 'Weekly Energy', ['weekly energy', 'week energy', 'energy'], ['energy'], ['Wh', 'kWh'])} onChange={(entityId) => updateEnergyEntity('weeklyEnergy', entityId)} />
                                <SafeEntityPicker label="Monthly Energy" value={settings.entities.energy.monthlyEnergy} placeholder="sensor.reef_monthly_energy" target={energyTarget('monthly_energy', 'Monthly Energy', ['monthly energy', 'month energy', 'energy'], ['energy'], ['Wh', 'kWh'])} onChange={(entityId) => updateEnergyEntity('monthlyEnergy', entityId)} />
                                <SafeEntityPicker label="Daily Cost" value={settings.entities.energy.dailyCost} placeholder="sensor.reef_daily_cost" target={energyTarget('daily_cost', 'Daily Cost', ['daily cost', 'today cost', 'cost'], ['monetary'], ['£', 'GBP'])} onChange={(entityId) => updateEnergyEntity('dailyCost', entityId)} />
                                <SafeEntityPicker label="Weekly Cost" value={settings.entities.energy.weeklyCost} placeholder="sensor.reef_weekly_cost" target={energyTarget('weekly_cost', 'Weekly Cost', ['weekly cost', 'week cost', 'cost'], ['monetary'], ['£', 'GBP'])} onChange={(entityId) => updateEnergyEntity('weeklyCost', entityId)} />
                                <SafeEntityPicker label="Monthly Cost" value={settings.entities.energy.monthlyCost} placeholder="sensor.reef_monthly_cost" target={energyTarget('monthly_cost', 'Monthly Cost', ['monthly cost', 'month cost', 'cost'], ['monetary'], ['£', 'GBP'])} onChange={(entityId) => updateEnergyEntity('monthlyCost', entityId)} />
                            </div>
                        </div>
                    )}
                </div>

                <div className={styles.wizardFooter}>
                    {step > 0 ? (
                        <button type="button" className={styles.secondaryButton} onClick={() => setStep(step - 1)}>
                            <ArrowLeft size={18} />
                            Back
                        </button>
                    ) : (
                        <button type="button" className={styles.secondaryButton} onClick={onClose}>
                            Close
                        </button>
                    )}
                    <button
                        type="button"
                        className={styles.primaryButton}
                        onClick={() => {
                            if (step === steps.length - 1) {
                                updateSettings({
                                    missionControl: {
                                        ...settings.missionControl,
                                        environmentalStats: [...MVP_SENSOR_IDS],
                                    },
                                    dashboard: {
                                        ...settings.dashboard,
                                        visibleCards: [...MVP_SENSOR_IDS],
                                    },
                                });
                                onClose();
                                return;
                            }
                            setStep(step + 1);
                        }}
                    >
                        {step === steps.length - 1 ? 'Finish' : 'Next'}
                        {step === steps.length - 1 ? <Check size={18} /> : <ArrowRight size={18} />}
                    </button>
                </div>
            </div>
        </div>
    );
}

export default function ControllerLiteApp(props: ControllerLiteAppProps) {
    return (
        <SettingsProvider>
            <ControllerLiteContent {...props} />
        </SettingsProvider>
    );
}
