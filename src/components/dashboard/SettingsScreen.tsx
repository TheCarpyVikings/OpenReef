/* eslint-disable @typescript-eslint/no-explicit-any -- Legacy settings form has schema-dynamic update paths that need a dedicated typed split. */
import React, { useState, useEffect } from 'react';
import { useSettings } from '@/context/SettingsContext';
import { withIngressPath } from '@/lib/api-fetch';
import styles from '@/app/dashboard.module.css';
import { Settings, Layout, Thermometer, PenTool, CheckSquare, Save, Activity, Plus, Trash2, Tag, Database, Zap, Power, Shield, Cpu, FlaskConical as Flask, RefreshCw, RotateCcw, Check, AlertTriangle, Waves, Lightbulb, Droplets, Sparkles, Video } from 'lucide-react';
import { SetupWizard } from './SetupWizard';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import { EntityPicker } from './EntityPicker';
import { getEquipmentSuggestionTarget, getSensorSuggestionTarget } from '@/lib/entity-suggestions';

const sections = [
    { id: 'setup', label: 'Setup Wizard', icon: <Sparkles size={18} /> },
    { id: 'general', label: 'General', icon: <Settings size={18} /> },
    { id: 'dashboard', label: 'Dashboard', icon: <Layout size={18} /> },
    { id: 'mission', label: 'Mission Control', icon: <Shield size={18} /> },
    { id: 'sensors', label: 'Sensors', icon: <Activity size={18} /> },
    { id: 'equipment', label: 'Equipment', icon: <Zap size={18} /> },
    { id: 'water-change', label: 'Water Change', icon: <Droplets size={18} /> },
    { id: 'tasks', label: 'Schedule', icon: <CheckSquare size={18} /> },
    { id: 'modes', label: 'Modes', icon: <Cpu size={18} /> },
    { id: 'calibration', label: 'Calibration', icon: <Flask size={18} /> },
    { id: 'spawning', label: 'Coral Spawning', icon: <Waves size={18} /> },
    { id: 'camera', label: 'Camera', icon: <Video size={18} /> },
    { id: 'lighting', label: 'Lighting', icon: <Lightbulb size={18} /> },
    { id: 'ai', label: 'AI Guardian', icon: <Shield size={18} /> },
    { id: 'data', label: 'Data', icon: <Database size={18} /> },
];

interface SettingsScreenProps {
    initialSection?: string;
    initialEditingAlarmId?: string;
}

export const SettingsScreen: React.FC<SettingsScreenProps> = ({ initialSection, initialEditingAlarmId }) => {
    const { settings, updateSettings, updateNestedSetting, updateSpawningSetting, clearManualReadings, updateMode, getEquipmentName, addEquipment, removeEquipment, getLabel, addAlarm, updateAlarm, removeAlarm, addCalibrationSensor, removeCalibrationSensor, updateCalibrationSensor, resetHAConfig, haError, setHaError, addRecurringTask, removeRecurringTask, addCustomSensor, removeCustomSensor, addAwcPreset, removeAwcPreset } = useSettings();
    const { pressButton, entities, reconnect, error: currentHaError } = useHomeAssistant();
    const [activeSection, setActiveSection] = useState(initialSection || 'general');
    const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
    const [newEquipmentName, setNewEquipmentName] = useState('');
    const [newAlarm, setNewAlarm] = useState({ label: '', entityId: '', okValue: '', severity: 'critical' as 'critical' | 'warning', description: '' });
    const [newCal, setNewCal] = useState({ sensorKey: 'salinity', numPoints: 3, v1: 0, v2: 0, v3: 0 });
    const [editingCal, setEditingCal] = useState<string | null>(null);
    const [editingAlarmId, setEditingAlarmId] = useState<string | null>(initialEditingAlarmId || null);
    const [editingSensorId, setEditingSensorId] = useState<string | null>(null);
    const [editingEquipmentId, setEditingEquipmentId] = useState<string | null>(null);
    const [newSensor, setNewSensor] = useState({ label: '', haKey: '', group: 'tank' as 'tank' | 'room' | 'manual' });
    const [isTesting, setIsTesting] = useState(false);
    const [testResult, setTestResult] = useState<'success' | 'error' | null>(null);
    const [recurTitle, setRecurTitle] = useState('');
    const [recurInterval, setRecurInterval] = useState(7);
    const [recurCategory, setRecurCategory] = useState('Maintenance');
    const [newAwcPreset, setNewAwcPreset] = useState({ label: '', percentage: 1, entityId: '' });

    const CATEGORIES = ['General', 'Feeding', 'Maintenance', 'Cleaning', 'Water Change', 'Dosing', 'Testing'];

    // Sync hook error to context error for persistent display
    useEffect(() => {
        if (currentHaError) setHaError(currentHaError);
    }, [currentHaError, setHaError]);

    const handleTestConnection = async () => {
        setIsTesting(true);
        setTestResult(null);
        setHaError(null);

        try {
            const connected = await reconnect();
            setTestResult(connected ? 'success' : 'error');
        } catch {
            setTestResult('error');
        } finally {
            setIsTesting(false);
        }
    };

    const handleColorChange = (color: string) => {
        updateNestedSetting('general', { themeColor: color });
    };

    const handleAddRecurringTask = () => {
        if (!recurTitle.trim()) return;
        addRecurringTask({
            title: recurTitle,
            intervalDays: recurInterval,
            category: recurCategory
        });
        setRecurTitle('');
    };

    const handleDeleteRecurringTask = (id: string) => {
        removeRecurringTask(id);
    };

    return (
        <div className={styles.settingsContainer}>
            <aside className={styles.settingsSidebar}>
                <h3 className={styles.sidebarTitle}>Settings</h3>
                <nav className={styles.sidebarNav}>
                    {sections.map((section) => (
                        <button
                            key={section.id}
                            className={`${styles.sidebarButton} ${activeSection === section.id ? styles.activeSidebar : ''}`}
                            onClick={() => setActiveSection(section.id)}
                        >
                            {section.icon}
                            <span>{section.label}</span>
                        </button>
                    ))}
                </nav>
            </aside>

            <main className={styles.settingsContent}>
                {activeSection === 'setup' && <SetupWizard onComplete={() => setActiveSection('general')} />}

                {/* General Settings */}
                {activeSection === 'general' && (
                    <div className={styles.settingsSection}>
                        <h4 className={styles.sectionHeader}>General Configuration</h4>
                        <div className={styles.card} style={{ padding: '1.5rem', marginBottom: '2rem' }}>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1.5rem' }}>
                                <div className={styles.settingGroup}>
                                    <label className={styles.label}>Tank Name</label>
                                    <input
                                        type="text"
                                        className={styles.input}
                                        value={settings.general.tankName}
                                        onChange={(e) => updateNestedSetting('general', { tankName: e.target.value })}
                                    />
                                </div>
                                <div className={styles.settingGroup}>
                                    <label className={styles.label}>User Name</label>
                                    <input
                                        type="text"
                                        className={styles.input}
                                        value={settings.general.userName}
                                        onChange={(e) => updateNestedSetting('general', { userName: e.target.value })}
                                    />
                                </div>
                                <div className={styles.settingGroup}>
                                    <label className={styles.label}>Theme Color</label>
                                    <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.5rem' }}>
                                        {['#00b4d8', '#4ade80', '#fbbf24', '#f87171', '#a855f7', '#ec4899'].map(color => (
                                            <button
                                                key={color}
                                                onClick={() => handleColorChange(color)}
                                                style={{
                                                    width: '32px',
                                                    height: '32px',
                                                    borderRadius: '50%',
                                                    backgroundColor: color,
                                                    border: settings.general.themeColor === color ? '3px solid #fff' : 'none',
                                                    cursor: 'pointer',
                                                    boxShadow: settings.general.themeColor === color ? '0 0 10px rgba(255,255,255,0.5)' : 'none'
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
                                        onChange={(e) => updateNestedSetting('general', { energyTariff: parseFloat(e.target.value) || 0 })}
                                    />
                                </div>
                            </div>
                        </div>

                        {process.env.NEXT_PUBLIC_HA_ADDON_MODE !== 'true' && (<>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', marginTop: '2rem' }}>
                                <h5 style={{ color: '#e0e1dd', margin: 0 }}>Home Assistant Connection</h5>
                                <button
                                    onClick={resetHAConfig}
                                    className={styles.tabItem}
                                    style={{ padding: '4px 12px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'rgba(255,255,255,0.05)' }}
                                    title="Restore values from .env.local"
                                >
                                    <RotateCcw size={14} /> Reset to Defaults
                                </button>
                            </div>
                            <div className={styles.card} style={{ padding: '1.5rem' }}>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '1.5rem' }}>
                                    <div className={styles.settingGroup}>
                                        <label className={styles.label}>Home Assistant URL</label>
                                        <input
                                            type="text"
                                            className={styles.input}
                                            placeholder="http://192.168.1.100:8123"
                                            value={settings.general.haUrl}
                                            onChange={(e) => updateNestedSetting('general', { haUrl: e.target.value.trim() })}
                                        />
                                        <p style={{ fontSize: '0.75rem', color: '#778da9', marginTop: '0.5rem' }}>
                                            The URL of your Home Assistant instance (e.g. http://192.168.1.100:8123).
                                        </p>
                                    </div>
                                    <div className={styles.settingGroup}>
                                        <label className={styles.label}>Credential Handling</label>
                                        <div className={styles.input} style={{ minHeight: '42px', display: 'flex', alignItems: 'center', color: '#778da9' }}>
                                            Home Assistant credentials are held by the OpenReef server gateway, not this browser.
                                        </div>
                                    </div>

                                    <div className={styles.settingGroup}>
                                        <label className={styles.label}>Google Sheet ID (for Manual Tests)</label>
                                        <input
                                            type="text"
                                            className={styles.input}
                                            placeholder="e.g. 1aBCdEfGhIjKlMnOpQrStUvWxYz1234567890"
                                            value={settings.general.googleSheetId || ''}
                                            onChange={(e) => updateNestedSetting('general', { googleSheetId: e.target.value.trim() })}
                                        />
                                        <p style={{ fontSize: '0.75rem', color: '#778da9', marginTop: '0.5rem' }}>
                                            The ID of the Google Sheet where test results will be appended. You can find this in the sheet&apos;s URL.
                                        </p>
                                        <div style={{ marginTop: '1rem' }}>
                                            <button
                                                onClick={() => window.location.href = withIngressPath('/api/auth/google')}
                                                className={styles.tabItem}
                                                style={{
                                                    padding: '8px 16px',
                                                    background: '#4285F4',
                                                    color: '#fff',
                                                    border: 'none',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: '0.5rem',
                                                }}
                                            >
                                                <Database size={18} /> Connect Google Account
                                            </button>
                                            <p style={{ fontSize: '0.7rem', color: '#778da9', marginTop: '0.5rem' }}>
                                                Required for syncing with Google Sheets. Note: This will request spreadsheet permissions.
                                            </p>
                                        </div>
                                    </div>

                                    {haError && (
                                        <div style={{
                                            padding: '0.75rem',
                                            background: 'rgba(239, 68, 68, 0.1)',
                                            borderRadius: '6px',
                                            border: '1px solid rgba(239, 68, 68, 0.2)',
                                            color: '#ef4444',
                                            fontSize: '0.85rem',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.75rem'
                                        }}>
                                            <AlertTriangle size={18} />
                                            <span>{haError}</span>
                                        </div>
                                    )}

                                    <div style={{ display: 'flex', gap: '1rem' }}>
                                        <button
                                            onClick={handleTestConnection}
                                            className={styles.tabItem}
                                            disabled={isTesting}
                                            style={{
                                                padding: '8px 16px',
                                                background: testResult === 'success' ? '#10b981' : isTesting ? 'rgba(255,255,255,0.05)' : 'var(--primary-color)',
                                                color: '#fff',
                                                border: 'none',
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '0.5rem',
                                                opacity: isTesting ? 0.7 : 1
                                            }}
                                        >
                                            {isTesting ? <RefreshCw size={18} className={styles.spin} /> : testResult === 'success' ? <Check size={18} /> : <RefreshCw size={18} />}
                                            {isTesting ? 'Testing...' : testResult === 'success' ? 'Connected!' : 'Test & Save Connection'}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </>)}

                        <div style={{ marginTop: '3rem' }}>
                            <h5 style={{ color: '#ef4444', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                <Shield size={18} /> Danger Zone
                            </h5>
                            <div className={styles.card} style={{ padding: '1.5rem', borderColor: 'rgba(239, 68, 68, 0.2)', backgroundColor: 'rgba(239, 68, 68, 0.05)' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <div>
                                        <div style={{ color: '#e0e1dd', fontWeight: 600, marginBottom: '0.25rem' }}>Reset All Settings</div>
                                        <div style={{ color: '#778da9', fontSize: '0.85rem' }}>Wipe all local configuration and restore defaults. This cannot be undone.</div>
                                    </div>
                                    <button
                                        className={styles.resetButton}
                                        onClick={() => setShowDeleteConfirm(true)}
                                        style={{ backgroundColor: '#ef4444' }}
                                    >
                                        Reset Settings
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* Dashboard Settings */}
                {activeSection === 'dashboard' && (
                    <div className={styles.settingsSection}>
                        <h4 className={styles.sectionHeader}>Dashboard Display & Layout</h4>

                        <div style={{ display: 'grid', gap: '2rem' }}>
                            <div className={styles.card} style={{ padding: '1.5rem' }}>
                                <h5 style={{ color: '#e0e1dd', marginBottom: '1.5rem', fontSize: '1rem' }}>View Modes</h5>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem' }}>
                                    {[
                                        { id: 'liveStatsView', label: 'Live Stats View' },
                                        { id: 'manualStatsView', label: 'Manual Stats View' }
                                    ].map(setting => (
                                        <div key={setting.id} className={styles.settingGroup}>
                                            <label className={styles.label}>{setting.label}</label>
                                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem', marginTop: '0.5rem' }}>
                                                {['numbers', 'gauges', 'graphs'].map(mode => (
                                                    <button
                                                        key={mode}
                                                        onClick={() => updateNestedSetting('dashboard', { [setting.id]: mode } as any)}
                                                        className={`${styles.tabItem} ${settings.dashboard[setting.id as 'liveStatsView' | 'manualStatsView'] === mode ? styles.activeTab : ''}`}
                                                        style={{ padding: '0.5rem', fontSize: '0.8rem', justifyContent: 'center' }}
                                                    >
                                                        {mode.charAt(0).toUpperCase() + mode.slice(1)}
                                                    </button>
                                                ))}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>

                            <div className={styles.card} style={{ padding: '1.5rem' }}>
                                <h5 style={{ color: '#e0e1dd', marginBottom: '1.5rem', fontSize: '1rem' }}>Visible Modules</h5>
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: '1rem' }}>
                                    {[
                                        { id: 'temp', label: 'Temperature' },
                                        { id: 'ph', label: 'pH Level' },
                                        { id: 'salinity', label: 'Salinity' },
                                        { id: 'orp', label: 'ORP' },
                                        { id: 'do', label: 'Dissolved Oxygen' },
                                        { id: 'room_temp', label: 'Room Temp' },
                                        { id: 'co2', label: 'CO2 level' },
                                        { id: 'humidity', label: 'Humidity' },
                                        { id: 'alk', label: 'Alkalinity' },
                                        { id: 'calc', label: 'Calcium' },
                                        { id: 'mag', label: 'Magnesium' },
                                        { id: 'nitrate', label: 'Nitrate' },
                                        { id: 'phosphate', label: 'Phosphate' },
                                        ...(settings.customSensors || []).map(s => ({ id: s.id, label: s.label }))
                                    ].map(item => (
                                        <label key={item.id} style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', cursor: 'pointer', padding: '0.5rem', background: 'rgba(255,255,255,0.02)', borderRadius: '6px' }}>
                                            <input
                                                type="checkbox"
                                                checked={settings.dashboard.visibleCards.includes(item.id)}
                                                onChange={(e) => {
                                                    const current = settings.dashboard.visibleCards;
                                                    const updated = e.target.checked
                                                        ? [...current, item.id]
                                                        : current.filter(id => id !== item.id);
                                                    updateNestedSetting('dashboard', { visibleCards: updated });
                                                }}
                                            />
                                            <span style={{ fontSize: '0.9rem', color: '#e0e1dd' }}>{getLabel(item.id, item.label)}</span>
                                        </label>
                                    ))}
                                </div>
                            </div>

                            <div className={styles.card} style={{ padding: '1.5rem' }}>
                                <h5 style={{ color: '#e0e1dd', marginBottom: '1.5rem', fontSize: '1rem' }}>Graph Y-Axis Ranges</h5>
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: '1.5rem' }}>
                                    {['temp', 'ph', 'salinity', 'orp', 'do', 'room_temp', 'co2', 'humidity', 'alk', 'calc', 'mag', 'nitrate', 'phosphate'].map(key => (
                                        <div key={key} className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                            <label className={styles.label}>{getLabel(key)} Range</label>
                                            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                                <input
                                                    type="number"
                                                    className={styles.input}
                                                    placeholder="Min"
                                                    value={settings.visuals.yAxisRanges[key]?.min ?? ''}
                                                    onChange={(e) => {
                                                        const min = e.target.value === '' ? null : parseFloat(e.target.value);
                                                        updateNestedSetting('visuals', {
                                                            yAxisRanges: { ...settings.visuals.yAxisRanges, [key]: { ...settings.visuals.yAxisRanges[key], min } }
                                                        } as any);
                                                    }}
                                                />
                                                <span style={{ color: '#778da9' }}>-</span>
                                                <input
                                                    type="number"
                                                    className={styles.input}
                                                    placeholder="Max"
                                                    value={settings.visuals.yAxisRanges[key]?.max ?? ''}
                                                    onChange={(e) => {
                                                        const max = e.target.value === '' ? null : parseFloat(e.target.value);
                                                        updateNestedSetting('visuals', {
                                                            yAxisRanges: { ...settings.visuals.yAxisRanges, [key]: { ...settings.visuals.yAxisRanges[key], max } }
                                                        } as any);
                                                    }}
                                                />
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>

                            <div className={styles.card} style={{ padding: '1.5rem' }}>
                                <h5 style={{ color: '#e0e1dd', marginBottom: '1.5rem', fontSize: '1rem' }}>Trend Lines</h5>
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '1rem' }}>
                                    {[
                                        { id: 'temp', label: 'Temperature' },
                                        { id: 'ph', label: 'pH Level' },
                                        { id: 'salinity', label: 'Salinity' },
                                        { id: 'orp', label: 'ORP' },
                                        { id: 'do', label: 'Dissolved Oxygen' },
                                        { id: 'room_temp', label: 'Room Temp' },
                                        { id: 'co2', label: 'CO2 level' },
                                        { id: 'humidity', label: 'Humidity' },
                                        { id: 'alk', label: 'Alkalinity' },
                                        { id: 'calc', label: 'Calcium' },
                                        { id: 'mag', label: 'Magnesium' },
                                        { id: 'nitrate', label: 'Nitrate' },
                                        { id: 'phosphate', label: 'Phosphate' },
                                    ].map(item => (
                                        <div key={item.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.75rem', background: 'rgba(255,255,255,0.02)', borderRadius: '8px' }}>
                                            <span style={{ fontSize: '0.9rem', color: '#e0e1dd' }}>{getLabel(item.id, item.label)}</span>
                                            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                                <select
                                                    className={styles.input}
                                                    value={settings.visuals.trendLines?.[item.id]?.type || 'none'}
                                                    onChange={(e) => {
                                                        const type = e.target.value as any;
                                                        updateNestedSetting('visuals', {
                                                            trendLines: {
                                                                ...(settings.visuals.trendLines || {}),
                                                                [item.id]: {
                                                                    ...(settings.visuals.trendLines?.[item.id] || { windowSize: 12, polynomialOrder: 2, enabled: true }),
                                                                    type,
                                                                    enabled: type !== 'none'
                                                                }
                                                            }
                                                        } as any);
                                                    }}
                                                    style={{ appearance: 'none', background: 'rgba(255,255,255,0.05)', color: '#e0e1dd', padding: '4px 8px', fontSize: '0.8rem', width: '100px' }}
                                                >
                                                    <option value="none">None</option>
                                                    <option value="sma">SMA</option>
                                                    <option value="ema">EMA</option>
                                                    <option value="savitzky-golay">SG Filter</option>
                                                </select>
                                                {settings.visuals.trendLines?.[item.id]?.type && settings.visuals.trendLines?.[item.id]?.type !== 'none' && (
                                                    <div style={{ display: 'flex', gap: '4px' }}>
                                                        <input
                                                            type="number"
                                                            className={styles.input}
                                                            style={{ width: '45px', padding: '4px', fontSize: '0.8rem' }}
                                                            placeholder="Win"
                                                            title="Smoothing Window Size"
                                                            value={settings.visuals.trendLines?.[item.id]?.windowSize || 12}
                                                            onChange={(e) => {
                                                                const windowSize = parseInt(e.target.value) || 1;
                                                                updateNestedSetting('visuals', {
                                                                    trendLines: {
                                                                        ...settings.visuals.trendLines,
                                                                        [item.id]: { ...settings.visuals.trendLines?.[item.id], windowSize }
                                                                    }
                                                                } as any);
                                                            }}
                                                        />
                                                        {settings.visuals.trendLines?.[item.id]?.type === 'savitzky-golay' && (
                                                            <input
                                                                type="number"
                                                                className={styles.input}
                                                                style={{ width: '35px', padding: '4px', fontSize: '0.8rem', color: '#fbbf24' }}
                                                                placeholder="Poly"
                                                                title="Polynomial Order (1-5)"
                                                                value={settings.visuals.trendLines?.[item.id]?.polynomialOrder || 2}
                                                                onChange={(e) => {
                                                                    const polynomialOrder = parseInt(e.target.value) || 1;
                                                                    updateNestedSetting('visuals', {
                                                                        trendLines: {
                                                                            ...settings.visuals.trendLines,
                                                                            [item.id]: { ...settings.visuals.trendLines?.[item.id], polynomialOrder }
                                                                        }
                                                                    } as any);
                                                                }}
                                                                min="1"
                                                                max="5"
                                                            />
                                                        )}
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* Mission Control Settings */}
                {activeSection === 'mission' && (
                    <div className={styles.settingsSection}>
                        <h4 className={styles.sectionHeader}>Mission Control & Alarms</h4>

                        <div style={{ marginBottom: '2rem' }}>
                            <div className={styles.card} style={{ padding: '1.5rem' }}>
                                <h5 style={{ color: '#e0e1dd', marginBottom: '1.5rem', fontSize: '1rem' }}>Display Configuration</h5>
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '2rem' }}>
                                    <div>
                                        <label className={styles.label} style={{ marginBottom: '1rem', display: 'block' }}>Environmental Health Stats</label>
                                        <div className={styles.checkboxGrid}>
                                            {[
                                                'temp', 'ph', 'salinity', 'orp', 'do', 'room_temp', 'co2', 'humidity', 'alk', 'calc', 'mag', 'nitrate', 'phosphate',
                                                ...(settings.customSensors || []).map(s => s.id)
                                            ].map(key => (
                                                <label key={key} className={styles.checkboxLabel}>
                                                    <input
                                                        type="checkbox"
                                                        checked={settings.missionControl.environmentalStats.includes(key)}
                                                        onChange={(e) => {
                                                            const current = settings.missionControl.environmentalStats;
                                                            const updated = e.target.checked
                                                                ? [...current, key]
                                                                : current.filter(k => k !== key);
                                                            updateNestedSetting('missionControl', { environmentalStats: updated });
                                                        }}
                                                        style={{ marginRight: '0.5rem' }}
                                                    />
                                                    {getLabel(key)}
                                                </label>
                                            ))}
                                        </div>
                                    </div>
                                    <div>
                                        <label className={styles.label} style={{ marginBottom: '1rem', display: 'block' }}>Critical Equipment</label>
                                        <div className={styles.checkboxGrid}>
                                            {Object.keys(settings.entities.equipment).map(key => (
                                                <label key={key} className={styles.checkboxLabel}>
                                                    <input
                                                        type="checkbox"
                                                        checked={settings.missionControl.criticalEquipment.includes(key)}
                                                        onChange={(e) => {
                                                            const current = settings.missionControl.criticalEquipment;
                                                            const updated = e.target.checked
                                                                ? [...current, key]
                                                                : current.filter(k => k !== key);
                                                            updateNestedSetting('missionControl', { criticalEquipment: updated });
                                                        }}
                                                        style={{ marginRight: '0.5rem' }}
                                                    />
                                                    {getEquipmentName(key, key)}
                                                </label>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div style={{ marginBottom: '2rem' }}>
                            <div className={styles.card} style={{ padding: '1.5rem' }}>
                                <h5 style={{ color: '#e0e1dd', marginBottom: '1.25rem', fontSize: '1rem' }}>Add New Health Monitor / Alarm</h5>
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', alignItems: 'end' }}>
                                    <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                        <label className={styles.label}>Label</label>
                                        <input
                                            type="text"
                                            className={styles.input}
                                            placeholder="e.g. Critical Temp"
                                            value={newAlarm.label}
                                            onChange={(e) => setNewAlarm({ ...newAlarm, label: e.target.value })}
                                        />
                                    </div>
                                    <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                        <label className={styles.label}>HA Entity ID</label>
                                        <input
                                            type="text"
                                            className={styles.input}
                                            placeholder="binary_sensor.reef_alert"
                                            value={newAlarm.entityId}
                                            onChange={(e) => setNewAlarm({ ...newAlarm, entityId: e.target.value })}
                                        />
                                    </div>
                                    <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                        <label className={styles.label}>&quot;Good&quot; Value</label>
                                        <input
                                            type="text"
                                            className={styles.input}
                                            placeholder="e.g. OK or off"
                                            value={newAlarm.okValue}
                                            onChange={(e) => setNewAlarm({ ...newAlarm, okValue: e.target.value })}
                                        />
                                    </div>
                                    <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                        <label className={styles.label}>Severity</label>
                                        <select
                                            className={styles.input}
                                            value={newAlarm.severity}
                                            onChange={(e) => setNewAlarm({ ...newAlarm, severity: e.target.value as any })}
                                            style={{ appearance: 'none', background: 'rgba(255,255,255,0.05)' }}
                                        >
                                            <option value="critical">Critical (Red)</option>
                                            <option value="warning">Warning (Yellow)</option>
                                        </select>
                                    </div>
                                    <div className={styles.settingGroup} style={{ marginBottom: 0, gridColumn: 'span 2' }}>
                                        <label className={styles.label}>Warning Message (Optional)</label>
                                        <input
                                            type="text"
                                            className={styles.input}
                                            placeholder="e.g. Heater efficiency drop - Consider replacing soon"
                                            value={newAlarm.description}
                                            onChange={(e) => setNewAlarm({ ...newAlarm, description: e.target.value })}
                                        />
                                    </div>
                                    <button
                                        className={styles.addButton}
                                        onClick={() => {
                                            if (newAlarm.label && newAlarm.entityId) {
                                                addAlarm(newAlarm);
                                                setNewAlarm({ label: '', entityId: '', okValue: '', severity: 'critical', description: '' });
                                            }
                                        }}
                                        disabled={!newAlarm.label || !newAlarm.entityId}
                                    >
                                        <Plus size={18} />
                                    </button>
                                </div>
                            </div>
                        </div>

                        <div style={{ display: 'grid', gap: '1rem' }}>
                            {Object.entries(settings.alarms || {}).map(([id, alarm]) => (
                                <div key={id} className={styles.card} style={{ padding: '1.25rem' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1.5rem', width: '100%', marginBottom: editingAlarmId === id ? '1.5rem' : 0 }}>
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', flex: 1, minWidth: 0 }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                                                <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: alarm.severity === 'critical' ? '#ef4444' : '#fbbf24' }} />
                                                <span style={{ fontWeight: 600, fontSize: '1rem', color: '#e0e1dd' }}>{alarm.label}</span>
                                                <span style={{
                                                    fontSize: '0.65rem',
                                                    textTransform: 'uppercase',
                                                    color: alarm.severity === 'critical' ? '#ef4444' : '#fbbf24',
                                                    fontWeight: 700,
                                                    background: alarm.severity === 'critical' ? 'rgba(239,68,68,0.1)' : 'rgba(251,191,36,0.1)',
                                                    padding: '2px 6px',
                                                    borderRadius: '4px',
                                                    border: `1px solid ${alarm.severity === 'critical' ? 'rgba(239,68,68,0.2)' : 'rgba(251,191,36,0.2)'}`
                                                }}>
                                                    {alarm.severity}
                                                </span>
                                            </div>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem', flexWrap: 'wrap' }}>
                                                <span style={{
                                                    color: '#778da9',
                                                    fontSize: '0.8rem',
                                                    fontFamily: 'monospace',
                                                    overflow: 'hidden',
                                                    textOverflow: 'ellipsis',
                                                    whiteSpace: 'nowrap',
                                                    maxWidth: '100%'
                                                }} title={alarm.entityId}>
                                                    {alarm.entityId}
                                                </span>
                                                <div style={{ fontSize: '0.85rem', color: '#778da9', whiteSpace: 'nowrap' }}>
                                                    EXPECTED: <span style={{ color: '#00b4d8', fontWeight: 600 }}>{alarm.okValue}</span>
                                                </div>
                                            </div>
                                            {alarm.description && (
                                                <div style={{ fontSize: '0.8rem', color: '#778da9', fontStyle: 'italic', marginTop: '0.25rem' }}>
                                                    &quot;{alarm.description}&quot;
                                                </div>
                                            )}
                                        </div>
                                        <div style={{ display: 'flex', gap: '0.5rem' }}>
                                            <button
                                                onClick={() => setEditingAlarmId(editingAlarmId === id ? null : id)}
                                                style={{ color: editingAlarmId === id ? 'var(--primary-color)' : '#778da9', background: editingAlarmId === id ? 'rgba(var(--primary-rgb), 0.1)' : 'none', border: 'none', cursor: 'pointer', padding: '0.5rem', borderRadius: '6px' }}
                                            >
                                                <Settings size={18} />
                                            </button>
                                            <button
                                                className={styles.deleteButton}
                                                onClick={() => removeAlarm(id)}
                                                style={{ color: '#ef4444', background: 'none', border: 'none', cursor: 'pointer', padding: '0.5rem' }}
                                            >
                                                <Trash2 size={18} />
                                            </button>
                                        </div>
                                    </div>

                                    {editingAlarmId === id && (
                                        <div className={styles.card} style={{ padding: '1.25rem', background: 'rgba(0,0,0,0.2)', animation: 'slideDown 0.2s ease-out' }}>
                                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', alignItems: 'end' }}>
                                                <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                    <label className={styles.label}>Label</label>
                                                    <input
                                                        type="text"
                                                        className={styles.input}
                                                        value={alarm.label}
                                                        onChange={(e) => updateAlarm(id, { label: e.target.value })}
                                                    />
                                                </div>
                                                <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                    <label className={styles.label}>HA Entity ID</label>
                                                    <input
                                                        type="text"
                                                        className={styles.input}
                                                        value={alarm.entityId}
                                                        onChange={(e) => updateAlarm(id, { entityId: e.target.value })}
                                                    />
                                                </div>
                                                <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                    <label className={styles.label}>&quot;Good&quot; Value</label>
                                                    <input
                                                        type="text"
                                                        className={styles.input}
                                                        value={alarm.okValue}
                                                        onChange={(e) => updateAlarm(id, { okValue: e.target.value })}
                                                    />
                                                </div>
                                                <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                    <label className={styles.label}>Severity</label>
                                                    <select
                                                        className={styles.input}
                                                        value={alarm.severity}
                                                        onChange={(e) => updateAlarm(id, { severity: e.target.value as any })}
                                                        style={{ appearance: 'none', background: 'rgba(255,255,255,0.05)' }}
                                                    >
                                                        <option value="critical">Critical (Red)</option>
                                                        <option value="warning">Warning (Yellow)</option>
                                                    </select>
                                                </div>
                                                <div className={styles.settingGroup} style={{ marginBottom: 0, gridColumn: 'span 2' }}>
                                                    <label className={styles.label}>Warning Message (Optional)</label>
                                                    <input
                                                        type="text"
                                                        className={styles.input}
                                                        value={alarm.description || ''}
                                                        onChange={(e) => updateAlarm(id, { description: e.target.value })}
                                                    />
                                                </div>
                                                <button
                                                    className={styles.addButton}
                                                    onClick={() => setEditingAlarmId(null)}
                                                    style={{ background: 'var(--primary-color)', color: 'white' }}
                                                >
                                                    <Save size={18} />
                                                </button>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Sensors Settings */}
                {activeSection === 'sensors' && (
                    <div className={styles.settingsSection}>
                        <h4 className={styles.sectionHeader}>Sensor Management</h4>
                        <div style={{ display: 'grid', gap: '2rem' }}>
                            {[
                                {
                                    group: 'Tank Sensors', items: [
                                        { id: 'temp', label: 'Temperature', haKey: 'temp' },
                                        { id: 'ph', label: 'pH Level', haKey: 'ph' },
                                        { id: 'salinity', label: 'Salinity', haKey: 'salinity' },
                                        { id: 'orp', label: 'ORP', haKey: 'orp' },
                                        { id: 'do', label: 'Dissolved Oxygen', haKey: 'do' },
                                        ...(settings.customSensors || []).filter(s => s.group === 'tank').map(s => ({
                                            id: s.id, label: s.label, haKey: s.haKey, isCustom: true
                                        }))
                                    ], parent: 'tank'
                                },
                                {
                                    group: 'Room Environment', items: [
                                        { id: 'room_temp', label: 'Room Temp', haKey: 'temp' },
                                        { id: 'co2', label: 'CO2 level', haKey: 'co2' },
                                        { id: 'humidity', label: 'Humidity', haKey: 'humidity' },
                                        ...(settings.customSensors || []).filter(s => s.group === 'room').map(s => ({
                                            id: s.id, label: s.label, haKey: s.haKey, isCustom: true
                                        }))
                                    ], parent: 'room'
                                },
                                {
                                    group: 'Manual Test Parameters', items: [
                                        { id: 'alk', label: 'Alkalinity' },
                                        { id: 'calc', label: 'Calcium' },
                                        { id: 'mag', label: 'Magnesium' },
                                        { id: 'salinity', label: 'Salinity' },
                                        { id: 'nitrate', label: 'Nitrate' },
                                        { id: 'phosphate', label: 'Phosphate' },
                                        ...(settings.customSensors || []).filter(s => s.group === 'manual').map(s => ({
                                            id: s.id, label: s.label, haKey: s.haKey, isCustom: true
                                        }))
                                    ]
                                }
                            ].map(section => (
                                <div key={section.group}>
                                    <h5 style={{ color: '#e0e1dd', marginBottom: '1rem', borderLeft: '3px solid #00b4d8', paddingLeft: '0.75rem' }}>{section.group}</h5>
                                    <div style={{ display: 'grid', gap: '1rem' }}>
                                        {section.items.map(sensor => (
                                            <div key={sensor.id} className={styles.card} style={{ padding: '1.25rem', position: 'relative' }}>
                                                {editingSensorId === sensor.id ? (
                                                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '1.5rem', alignItems: 'end' }}>
                                                        <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                            <label className={styles.label}>Display Label</label>
                                                            <input
                                                                type="text"
                                                                className={styles.input}
                                                                placeholder={sensor.label}
                                                                value={settings.labels[sensor.id] || ''}
                                                                onChange={(e) => updateNestedSetting('labels', { ...settings.labels, [sensor.id]: e.target.value })}
                                                            />
                                                        </div>
                                                        {(sensor as any).haKey && (
                                                            <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                                <label className={styles.label}>HA Entity ID</label>
                                                                <EntityPicker
                                                                    entities={entities}
                                                                    target={getSensorSuggestionTarget(
                                                                        sensor.id,
                                                                        settings.labels[sensor.id] || sensor.label,
                                                                        (section as any).parent === 'room' ? 'room' : (section as any).parent === 'tank' ? 'tank' : 'manual',
                                                                    )}
                                                                    value={(sensor as any).isCustom ? (sensor as any).haKey : (settings.entities as any)[(section as any).parent][(sensor as any).haKey]}
                                                                    placeholder={`sensor.${sensor.id}`}
                                                                    onRequestEntities={reconnect}
                                                                    onChange={(entityId) => {
                                                                        if ((sensor as any).isCustom) {
                                                                            const updated = settings.customSensors.map(s => s.id === sensor.id ? { ...s, haKey: entityId } : s);
                                                                            updateSettings({ customSensors: updated });
                                                                        } else {
                                                                            const parentEntities = (settings.entities as any)[(section as any).parent];
                                                                            updateNestedSetting('entities', {
                                                                                ...settings.entities,
                                                                                [(section as any).parent]: { ...parentEntities, [(sensor as any).haKey!]: entityId }
                                                                            } as any);
                                                                        }
                                                                    }}
                                                                />
                                                            </div>
                                                        )}
                                                        {!(sensor as any).haKey && <div />}
                                                        <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                            <label className={styles.label}>Alert Thresholds (Min - Max)</label>
                                                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                                                <input
                                                                    type="number"
                                                                    className={styles.input}
                                                                    placeholder="Min"
                                                                    value={settings.thresholds[sensor.id]?.min ?? ''}
                                                                    onChange={(e) => {
                                                                        const val = e.target.value === '' ? null : parseFloat(e.target.value);
                                                                        updateNestedSetting('thresholds', {
                                                                            ...settings.thresholds,
                                                                            [sensor.id]: { ...settings.thresholds[sensor.id], min: val }
                                                                        } as any);
                                                                    }}
                                                                />
                                                                <input
                                                                    type="number"
                                                                    className={styles.input}
                                                                    placeholder="Max"
                                                                    value={settings.thresholds[sensor.id]?.max ?? ''}
                                                                    onChange={(e) => {
                                                                        const val = e.target.value === '' ? null : parseFloat(e.target.value);
                                                                        updateNestedSetting('thresholds', {
                                                                            ...settings.thresholds,
                                                                            [sensor.id]: { ...settings.thresholds[sensor.id], max: val }
                                                                        } as any);
                                                                    }}
                                                                />
                                                            </div>
                                                        </div>
                                                        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                                                            {(sensor as any).isCustom && (
                                                                <button
                                                                    className={styles.deleteButton}
                                                                    onClick={() => removeCustomSensor(sensor.id)}
                                                                    style={{ color: '#ef4444', background: 'rgba(239,68,68,0.1)', border: 'none', padding: '0.5rem', borderRadius: '6px' }}
                                                                >
                                                                    <Trash2 size={18} />
                                                                </button>
                                                            )}
                                                            <button
                                                                className={styles.addButton}
                                                                onClick={() => setEditingSensorId(null)}
                                                                style={{ background: 'var(--primary-color)', color: 'white' }}
                                                            >
                                                                <Save size={18} />
                                                            </button>
                                                        </div>
                                                    </div>
                                                ) : (
                                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr 1fr', gap: '2rem', flex: 1 }}>
                                                            <div>
                                                                <label className={styles.label}>Sensor</label>
                                                                <div style={{ color: '#e0e1dd', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                                    {settings.labels[sensor.id] || sensor.label}
                                                                    {(sensor as any).isCustom && (
                                                                        <span style={{
                                                                            fontSize: '0.6rem',
                                                                            background: 'rgba(0, 180, 216, 0.1)',
                                                                            color: '#00b4d8',
                                                                            padding: '1px 6px',
                                                                            borderRadius: '4px',
                                                                            border: '1px solid rgba(0, 180, 216, 0.2)',
                                                                            textTransform: 'uppercase',
                                                                            fontWeight: 700
                                                                        }}>Custom</span>
                                                                    )}
                                                                </div>
                                                            </div>
                                                            {(sensor as any).haKey && (
                                                                <div>
                                                                    <label className={styles.label}>HA Entity ID</label>
                                                                    <div style={{ color: '#778da9', fontSize: '0.9rem', fontFamily: 'monospace' }}>
                                                                        {(sensor as any).isCustom ? (sensor as any).haKey : (settings.entities as any)[(section as any).parent]?.[(sensor as any).haKey]}
                                                                    </div>
                                                                </div>
                                                            )}
                                                            <div>
                                                                <label className={styles.label}>Alert Range</label>
                                                                <div style={{ color: '#00b4d8', fontSize: '0.9rem' }}>
                                                                    {settings.thresholds[sensor.id] ? `${settings.thresholds[sensor.id].min} - ${settings.thresholds[sensor.id].max}` : 'Not set'}
                                                                </div>
                                                            </div>
                                                        </div>
                                                        <button
                                                            className={styles.editButton}
                                                            onClick={() => setEditingSensorId(sensor.id)}
                                                            style={{ border: 'none', background: 'rgba(119,141,169,0.1)', color: '#778da9', padding: '0.5rem', borderRadius: '6px', cursor: 'pointer' }}
                                                        >
                                                            <PenTool size={18} />
                                                        </button>
                                                    </div>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            ))}

                            <div style={{ marginTop: '2rem' }}>
                                <h5 style={{ color: '#e0e1dd', marginBottom: '1rem', borderLeft: '3px solid #fbbf24', paddingLeft: '0.75rem' }}>Energy Monitoring</h5>
                                <div className={styles.card} style={{ padding: '1.5rem' }}>
                                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1.5rem' }}>
                                        {[
                                            { key: 'dailyEnergy', label: 'Daily Energy (kWh)', icon: <Zap size={16} /> },
                                            { key: 'weeklyEnergy', label: 'Weekly Energy (kWh)', icon: <Zap size={16} /> },
                                            { key: 'monthlyEnergy', label: 'Monthly Energy (kWh)', icon: <Zap size={16} /> },
                                            { key: 'dailyCost', label: 'Daily Cost (£)', icon: <Database size={16} /> },
                                            { key: 'weeklyCost', label: 'Weekly Cost (£)', icon: <Database size={16} /> },
                                            { key: 'monthlyCost', label: 'Monthly Cost (£)', icon: <Database size={16} /> },
                                        ].map(item => (
                                            <div key={item.key} className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                <label className={styles.label} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                    {item.icon} {item.label}
                                                </label>
                                                <input
                                                    type="text"
                                                    className={styles.input}
                                                    placeholder="sensor.energy_stats"
                                                    value={settings.entities.energy?.[item.key as keyof typeof settings.entities.energy] || ''}
                                                    onChange={(e) => {
                                                        const energyEntities = { ...settings.entities.energy, [item.key]: e.target.value };
                                                        updateNestedSetting('entities', { ...settings.entities, energy: energyEntities });
                                                    }}
                                                />
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>

                            <div className={styles.card} style={{ padding: '1.5rem', background: 'rgba(0,180,216,0.02)', border: '1px dashed rgba(0,180,216,0.2)' }}>
                                <h5 style={{ color: '#00b4d8', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                    <Plus size={18} /> Add Custom Sensor
                                </h5>
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', alignItems: 'end' }}>
                                    <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                        <label className={styles.label}>Label</label>
                                        <input
                                            type="text"
                                            className={styles.input}
                                            placeholder="e.g., Magnesium"
                                            value={newSensor.label}
                                            onChange={(e) => setNewSensor({ ...newSensor, label: e.target.value })}
                                        />
                                    </div>
                                    <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                        <label className={styles.label}>HA Entity (Optional)</label>
                                        <EntityPicker
                                            entities={entities}
                                            target={getSensorSuggestionTarget(
                                                newSensor.label || 'custom_sensor',
                                                newSensor.label || 'Custom Sensor',
                                                newSensor.group,
                                            )}
                                            placeholder="sensor.magnesium"
                                            value={newSensor.haKey}
                                            onRequestEntities={reconnect}
                                            onChange={(entityId) => setNewSensor({ ...newSensor, haKey: entityId })}
                                        />
                                    </div>
                                    <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                        <label className={styles.label}>Group</label>
                                        <select
                                            className={styles.input}
                                            value={newSensor.group}
                                            onChange={(e) => setNewSensor({ ...newSensor, group: e.target.value as any })}
                                            style={{ color: '#e0e1dd', background: '#1b263b' }}
                                        >
                                            <option value="tank">Tank Sensors</option>
                                            <option value="room">Room Environment</option>
                                            <option value="manual">Manual Tests</option>
                                        </select>
                                    </div>
                                    <button
                                        className={styles.addButton}
                                        onClick={() => {
                                            if (newSensor.label) {
                                                addCustomSensor(newSensor);
                                                setNewSensor({ label: '', haKey: '', group: 'tank' });
                                            }
                                        }}
                                        disabled={!newSensor.label}
                                        style={{ height: '42px' }}
                                    >
                                        <Plus size={18} /> Add Sensor
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* Equipment Settings */}
                {activeSection === 'equipment' && (
                    <div className={styles.settingsSection}>
                        <h4 className={styles.sectionHeader}>Equipment Management</h4>

                        <div style={{ marginBottom: '2rem' }}>
                            <div className={styles.card} style={{ padding: '1.25rem' }}>
                                <label className={styles.label}>Add New Equipment</label>
                                <div style={{ display: 'flex', gap: '1rem', marginTop: '0.5rem' }}>
                                    <input
                                        type="text"
                                        className={styles.input}
                                        placeholder="Equipment Name (e.g., Return Pump)"
                                        value={newEquipmentName}
                                        onChange={(e) => setNewEquipmentName(e.target.value)}
                                    />
                                    <button
                                        className={styles.addButton}
                                        onClick={() => {
                                            if (newEquipmentName) {
                                                addEquipment(newEquipmentName);
                                                setNewEquipmentName('');
                                            }
                                        }}
                                        disabled={!newEquipmentName}
                                    >
                                        <Plus size={18} /> Add
                                    </button>
                                </div>
                            </div>
                        </div>

                        <div style={{ display: 'grid', gap: '1.5rem' }}>
                            {Object.entries(settings.entities.equipment).map(([key, config]) => (
                                <div key={key} className={styles.card} style={{ padding: '1.5rem' }}>
                                    {editingEquipmentId === key ? (
                                        <>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: '1.5rem' }}>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                                                    <div style={{ padding: '0.75rem', background: 'rgba(0,180,216,0.1)', borderRadius: '10px', color: '#00b4d8' }}>
                                                        <Power size={20} />
                                                    </div>
                                                    <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                        <label className={styles.label}>Display Name</label>
                                                        <input
                                                            type="text"
                                                            className={styles.input}
                                                            style={{ fontSize: '1.1rem', fontWeight: 600, width: '250px' }}
                                                            value={settings.equipment.aliases[key] || key}
                                                            onChange={(e) => {
                                                                const aliases = { ...settings.equipment.aliases, [key]: e.target.value };
                                                                updateNestedSetting('equipment', { ...settings.equipment, aliases });
                                                            }}
                                                        />
                                                    </div>
                                                </div>
                                                <div style={{ display: 'flex', gap: '0.5rem' }}>
                                                    <button
                                                        className={styles.deleteButton}
                                                        onClick={() => removeEquipment(key)}
                                                        style={{ color: '#ef4444', background: 'rgba(239,68,68,0.1)', border: 'none', padding: '0.5rem', borderRadius: '6px' }}
                                                    >
                                                        <Trash2 size={18} />
                                                    </button>
                                                    <button
                                                        className={styles.addButton}
                                                        onClick={() => setEditingEquipmentId(null)}
                                                        style={{ background: 'var(--primary-color)', color: 'white' }}
                                                    >
                                                        <Save size={18} />
                                                    </button>
                                                </div>
                                            </div>

                                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1.5rem' }}>
                                                <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                    <label className={styles.label}>Switch Entity</label>
                                                    <EntityPicker
                                                        entities={entities}
                                                        target={getEquipmentSuggestionTarget(key, getEquipmentName(key, key), 'switch')}
                                                        placeholder="switch.device_name"
                                                        value={config.switch}
                                                        onRequestEntities={reconnect}
                                                        onChange={(entityId) => {
                                                            const equip = { ...settings.entities.equipment, [key]: { ...config, switch: entityId } };
                                                            updateNestedSetting('entities', { ...settings.entities, equipment: equip } as any);
                                                        }}
                                                    />
                                                </div>
                                                <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                    <label className={styles.label}>Power Entity (W)</label>
                                                    <EntityPicker
                                                        entities={entities}
                                                        target={getEquipmentSuggestionTarget(key, getEquipmentName(key, key), 'power')}
                                                        placeholder="sensor.device_power"
                                                        value={config.power}
                                                        onRequestEntities={reconnect}
                                                        onChange={(entityId) => {
                                                            const equip = { ...settings.entities.equipment, [key]: { ...config, power: entityId } };
                                                            updateNestedSetting('entities', { ...settings.entities, equipment: equip } as any);
                                                        }}
                                                    />
                                                </div>
                                                <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                    <label className={styles.label}>Energy Entity (Wh)</label>
                                                    <EntityPicker
                                                        entities={entities}
                                                        target={getEquipmentSuggestionTarget(key, getEquipmentName(key, key), 'energy')}
                                                        placeholder="sensor.device_energy"
                                                        value={config.energy}
                                                        onRequestEntities={reconnect}
                                                        onChange={(entityId) => {
                                                            const equip = { ...settings.entities.equipment, [key]: { ...config, energy: entityId } };
                                                            updateNestedSetting('entities', { ...settings.entities, equipment: equip } as any);
                                                        }}
                                                    />
                                                </div>
                                            </div>

                                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1.5rem', marginTop: '1.5rem' }}>
                                                <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                    <label className={styles.label} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                        <Shield size={14} /> Control Armed
                                                    </label>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginTop: '0.5rem' }}>
                                                        <button
                                                            onClick={() => {
                                                                const equip = { ...settings.entities.equipment, [key]: { ...config, controlEnabled: !config.controlEnabled } };
                                                                updateNestedSetting('entities', { ...settings.entities, equipment: equip } as any);
                                                            }}
                                                            className={`${styles.tabItem} ${config.controlEnabled ? styles.activeTab : ''}`}
                                                            style={{ padding: '0.4rem 0.8rem', fontSize: '0.75rem', minWidth: '80px', justifyContent: 'center' }}
                                                        >
                                                            {config.controlEnabled ? 'ARMED' : 'LOCKED'}
                                                        </button>
                                                    </div>
                                                </div>
                                                <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                    <label className={styles.label} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                        <Layout size={14} /> Show in Diagram
                                                    </label>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginTop: '0.5rem' }}>
                                                        <button
                                                            onClick={() => {
                                                                const equip = { ...settings.entities.equipment, [key]: { ...config, showInDiagram: !config.showInDiagram } };
                                                                updateNestedSetting('entities', { ...settings.entities, equipment: equip } as any);
                                                            }}
                                                            className={`${styles.tabItem} ${config.showInDiagram ? styles.activeTab : ''}`}
                                                            style={{ padding: '0.4rem 0.8rem', fontSize: '0.75rem', minWidth: '80px', justifyContent: 'center' }}
                                                        >
                                                            {config.showInDiagram ? 'VISIBLE' : 'HIDDEN'}
                                                        </button>
                                                    </div>
                                                </div>
                                                <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                    <label className={styles.label}>Diagram Position</label>
                                                    <select
                                                        className={styles.input}
                                                        style={{ height: '38px', padding: '0 0.5rem' }}
                                                        value={config.diagramPosition || 'room'}
                                                        onChange={(e) => {
                                                            const equip = { ...settings.entities.equipment, [key]: { ...config, diagramPosition: e.target.value as any } };
                                                            updateNestedSetting('entities', { ...settings.entities, equipment: equip } as any);
                                                        }}
                                                    >
                                                        <option value="tank">Tank</option>
                                                        <option value="sump">Sump</option>
                                                        <option value="ato_reservoir">ATO Reservoir</option>
                                                        <option value="dosing_container">Dosing Container</option>
                                                        <option value="awc_fresh">AWC Fresh Reservoir</option>
                                                        <option value="awc_waste">AWC Waste Container</option>
                                                        <option value="light">Light (Above Tank)</option>
                                                        <option value="room">Other/Room</option>
                                                    </select>
                                                </div>
                                            </div>
                                        </>
                                    ) : (
                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                                                <div style={{ padding: '0.75rem', background: 'rgba(0,180,216,0.1)', borderRadius: '10px', color: '#00b4d8' }}>
                                                    <Power size={20} />
                                                </div>
                                                <div>
                                                    <div style={{ color: '#e0e1dd', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                        {settings.equipment.aliases[key] || key}
                                                        {config.showInDiagram && (
                                                            <span style={{ fontSize: '0.65rem', background: 'rgba(0,180,216,0.1)', color: '#00b4d8', padding: '2px 6px', borderRadius: '4px', textTransform: 'uppercase' }}>
                                                                Diagram ({config.diagramPosition || 'Room'})
                                                            </span>
                                                        )}
                                                        {config.controlEnabled && (
                                                            <span style={{ fontSize: '0.65rem', background: 'rgba(16,185,129,0.12)', color: '#34d399', padding: '2px 6px', borderRadius: '4px', textTransform: 'uppercase' }}>
                                                                Armed
                                                            </span>
                                                        )}
                                                    </div>
                                                    <div style={{ color: '#778da9', fontSize: '0.8rem' }}>{config.switch || 'No switch entity'}</div>
                                                </div>
                                            </div>
                                            <button
                                                className={styles.editButton}
                                                onClick={() => setEditingEquipmentId(key)}
                                                style={{ border: 'none', background: 'rgba(119,141,169,0.1)', color: '#778da9', padding: '0.5rem', borderRadius: '6px', cursor: 'pointer' }}
                                            >
                                                <PenTool size={18} />
                                            </button>
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                )}


                {activeSection === 'tasks' && (
                    <div className={styles.settingsSection}>
                        <h4 className={styles.sectionHeader}>Maintenance Schedule</h4>

                        <div className={styles.card} style={{ padding: '1.5rem', marginBottom: '2rem' }}>
                            <h5 style={{ color: '#e0e1dd', marginBottom: '1.25rem', fontSize: '1rem' }}>Manage Recurring Tasks</h5>
                            <p style={{ fontSize: '0.85rem', color: '#778da9', marginBottom: '1.5rem' }}>
                                Recurring tasks are automatically added to your list based on the interval.
                            </p>

                            <div className={styles.addTaskForm} style={{ flexWrap: 'wrap', marginBottom: '2rem', display: 'flex', gap: '0.75rem' }}>
                                <input
                                    type="text"
                                    placeholder="Task name (e.g., Check Salt Level)"
                                    className={styles.taskInput}
                                    value={recurTitle}
                                    onChange={(e) => setRecurTitle(e.target.value)}
                                    style={{ flex: '2 1 300px' }}
                                />
                                <div style={{ display: 'flex', gap: '0.5rem', flex: '1 1 200px' }}>
                                    <span style={{ alignSelf: 'center', fontSize: '0.8rem', color: '#778da9' }}>Every</span>
                                    <input
                                        type="number"
                                        className={styles.taskInput}
                                        value={recurInterval}
                                        onChange={(e) => setRecurInterval(parseInt(e.target.value) || 1)}
                                        style={{ width: '60px', padding: '0.5rem' }}
                                        min="1"
                                    />
                                    <span style={{ alignSelf: 'center', fontSize: '0.8rem', color: '#778da9' }}>days</span>
                                </div>
                                <select
                                    className={styles.taskSelect}
                                    value={recurCategory}
                                    onChange={(e) => setRecurCategory(e.target.value)}
                                    style={{ flex: '1 1 150px' }}
                                >
                                    {CATEGORIES.map(cat => <option key={cat} value={cat}>{cat}</option>)}
                                </select>
                                <button className={styles.addButton} onClick={handleAddRecurringTask} style={{ height: '42px', padding: '0 1.5rem' }}>
                                    <Plus size={18} /> Add
                                </button>
                            </div>

                            <div style={{ display: 'grid', gap: '1rem' }}>
                                {settings.tasks.recurring.map((rt) => (
                                    <div key={rt.id} className={styles.card} style={{ padding: '1rem', background: 'rgba(255,255,255,0.02)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                        <div>
                                            <div style={{ fontWeight: 600, color: '#e0e1dd', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                <RefreshCw size={14} color="#00b4d8" />
                                                {rt.title}
                                            </div>
                                            <div style={{ fontSize: '0.8rem', color: '#778da9', marginTop: '0.25rem', display: 'flex', gap: '1rem' }}>
                                                <span style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}><Tag size={12} /> {rt.category}</span>
                                                <span style={{ color: '#00b4d8' }}>Every {rt.intervalDays} days</span>
                                            </div>
                                        </div>
                                        <button
                                            onClick={() => handleDeleteRecurringTask(rt.id)}
                                            style={{ color: '#ef4444', background: 'rgba(239,68,68,0.1)', border: 'none', padding: '0.5rem', borderRadius: '6px', cursor: 'pointer' }}
                                        >
                                            <Trash2 size={18} />
                                        </button>
                                    </div>
                                ))}
                                {settings.tasks.recurring.length === 0 && (
                                    <div style={{ textAlign: 'center', padding: '2rem', color: '#778da9', background: 'rgba(255,255,255,0.01)', borderRadius: '8px', border: '1px dashed rgba(255,255,255,0.05)' }}>
                                        <p>No recurring tasks defined yet.</p>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                )}

                {/* Modes Settings */}
                {activeSection === 'modes' && (
                    <div className={styles.settingsSection}>
                        <h4 className={styles.sectionHeader}>Behavior Modes</h4>
                        <div style={{ display: 'grid', gap: '2rem' }}>
                            {settings.modes.map((mode) => (
                                <div key={mode.id} className={styles.card} style={{ padding: '1.5rem' }}>
                                    <h5 style={{ color: '#00b4d8', marginBottom: '1.25rem', fontSize: '1.1rem' }}>{mode.label} Mode</h5>
                                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '1rem' }}>
                                        {Object.entries(settings.entities.equipment).map(([equipKey]) => {
                                            const currentStatus = mode.equipmentConfig?.[equipKey] || 'off';
                                            return (
                                                <div key={equipKey} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.75rem', background: 'rgba(255,255,255,0.02)', borderRadius: '8px' }}>
                                                    <span style={{ fontSize: '0.9rem' }}>{getEquipmentName(equipKey, equipKey)}</span>
                                                    <button
                                                        onClick={() => {
                                                            const next = currentStatus === 'on' ? 'off' : 'on';
                                                            updateMode(mode.id, { equipmentConfig: { ...mode.equipmentConfig, [equipKey]: next } });
                                                        }}
                                                        className={`${styles.tabItem} ${currentStatus === 'on' ? styles.activeTab : ''}`}
                                                        style={{ padding: '0.4rem 0.8rem', fontSize: '0.75rem', minWidth: '60px', justifyContent: 'center' }}
                                                    >
                                                        {currentStatus.toUpperCase()}
                                                    </button>
                                                </div>
                                            );
                                        })}
                                    </div>
                                    {mode.id !== 'running' && (
                                        <div style={{ marginTop: '1.5rem', paddingTop: '1.5rem', borderTop: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', gap: '1rem' }}>
                                            <div className={styles.settingGroup} style={{ marginBottom: 0, flex: 1 }}>
                                                <label className={styles.label} style={{ fontSize: '0.8rem', marginBottom: '0.5rem' }}>Auto-Revert Duration (minutes)</label>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                                                    <input
                                                        type="number"
                                                        className={styles.input}
                                                        placeholder="No Timer"
                                                        value={mode.duration || ''}
                                                        onChange={(e) => {
                                                            const val = e.target.value === '' ? undefined : parseInt(e.target.value);
                                                            updateMode(mode.id, { duration: val });
                                                        }}
                                                        style={{ width: '120px' }}
                                                    />
                                                    <span style={{ fontSize: '0.75rem', color: '#778da9' }}>
                                                        {mode.duration ? `Will automatically switch back to Running mode after ${mode.duration} minutes.` : 'No timer set. Switch back manually.'}
                                                    </span>
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                )}
                {/* Calibration Settings */}
                {activeSection === 'calibration' && (
                    <div className={styles.settingsSection}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
                            <h4 className={styles.sectionHeader} style={{ marginBottom: 0 }}>Sensor Calibration</h4>
                        </div>

                        <div className={styles.card} style={{ padding: '1.5rem', marginBottom: '2rem' }}>
                            <h5 style={{ color: '#e0e1dd', marginBottom: '1.25rem', fontSize: '1rem' }}>Add New Calibration Card</h5>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', alignItems: 'end' }}>
                                <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                    <label className={styles.label}>Select Sensor</label>
                                    <select
                                        className={styles.input}
                                        value={newCal.sensorKey}
                                        onChange={(e) => {
                                            const key = e.target.value;
                                            let defaults = { v1: 0, v2: 0, v3: 0 };
                                            if (key === 'ph') defaults = { v1: 4.00, v2: 7.00, v3: 10.00 };
                                            if (key === 'salinity') defaults = { v1: 0, v2: 35.0, v3: 50.0 };
                                            setNewCal({ ...newCal, sensorKey: key, ...defaults });
                                        }}
                                        style={{ appearance: 'none', background: 'rgba(255,255,255,0.05)' }}
                                    >
                                        <option value="salinity">Salinity</option>
                                        <option value="orp">ORP</option>
                                        <option value="do">Dissolved Oxygen</option>
                                        <option value="temp">Temperature</option>
                                        <option value="ph">pH</option>
                                    </select>
                                </div>
                                <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                    <label className={styles.label}>Calibration Type</label>
                                    <select
                                        className={styles.input}
                                        value={newCal.numPoints}
                                        onChange={(e) => setNewCal({ ...newCal, numPoints: parseInt(e.target.value) })}
                                        style={{ appearance: 'none', background: 'rgba(255,255,255,0.05)' }}
                                    >
                                        <option value={1}>1-Point Calibration</option>
                                        <option value={2}>2-Point Calibration</option>
                                        <option value={3}>3-Point Calibration</option>
                                    </select>
                                </div>
                                <button
                                    className={styles.addButton}
                                    onClick={() => {
                                        addCalibrationSensor(newCal.sensorKey, newCal.numPoints, { v1: newCal.v1, v2: newCal.v2, v3: newCal.v3 });
                                    }}
                                    style={{ height: '42px' }}
                                >
                                    <Plus size={18} /> Add Card
                                </button>
                            </div>

                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '1rem', marginTop: '1.5rem' }}>
                                {newCal.numPoints >= 1 && (
                                    <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                        <label className={styles.label} style={{ fontSize: '0.7rem' }}>
                                            {newCal.numPoints === 1 ? 'Mid Value' : 'Low Value'}
                                        </label>
                                        <input
                                            type="number"
                                            step="0.01"
                                            className={styles.input}
                                            value={newCal.v1}
                                            onChange={(e) => setNewCal({ ...newCal, v1: parseFloat(e.target.value) || 0 })}
                                        />
                                    </div>
                                )}
                                {newCal.numPoints >= 2 && (
                                    <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                        <label className={styles.label} style={{ fontSize: '0.7rem' }}>
                                            {newCal.numPoints === 2 ? 'High Value' : 'Mid Value'}
                                        </label>
                                        <input
                                            type="number"
                                            step="0.01"
                                            className={styles.input}
                                            value={newCal.v2}
                                            onChange={(e) => setNewCal({ ...newCal, v2: parseFloat(e.target.value) || 0 })}
                                        />
                                    </div>
                                )}
                                {newCal.numPoints >= 3 && (
                                    <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                        <label className={styles.label} style={{ fontSize: '0.7rem' }}>High Value</label>
                                        <input
                                            type="number"
                                            step="0.01"
                                            className={styles.input}
                                            value={newCal.v3}
                                            onChange={(e) => setNewCal({ ...newCal, v3: parseFloat(e.target.value) || 0 })}
                                        />
                                    </div>
                                )}
                            </div>
                        </div>

                        <div style={{ display: 'grid', gap: '2rem' }}>
                            {Object.entries(settings.calibration).map(([sensorKey, config]) => (
                                <div key={sensorKey} className={styles.card} style={{ padding: '1.5rem', border: '1px solid rgba(var(--primary-rgb), 0.2)' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                                            <div className={styles.iconWrapper} style={{ background: 'rgba(var(--primary-rgb), 0.1)', color: 'var(--primary-color)' }}>
                                                <Flask size={20} />
                                            </div>
                                            <h5 style={{ color: '#e0e1dd', fontSize: '1.1rem', margin: 0 }}>
                                                {getLabel(sensorKey)} Calibration
                                            </h5>
                                        </div>

                                        <div style={{ display: 'flex', alignItems: 'center', gap: '2rem' }}>
                                            {(() => {
                                                const entityId = config.calibrationLiveEntity || (settings.entities.tank as any)[sensorKey] || (settings.entities.room as any)[sensorKey];
                                                const state = entities?.[entityId]?.state || '--';
                                                return (
                                                    <div style={{ textAlign: 'right' }}>
                                                        <div style={{ fontSize: '0.65rem', color: '#778da9', textTransform: 'uppercase', marginBottom: '4px' }}>Live Reading</div>
                                                        <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--primary-color)' }}>{state}</div>
                                                    </div>
                                                );
                                            })()}
                                            <button
                                                className={styles.sidebarButton}
                                                onClick={() => setEditingCal(editingCal === sensorKey ? null : sensorKey)}
                                                style={{
                                                    background: editingCal === sensorKey ? 'rgba(var(--primary-rgb), 0.2)' : 'transparent',
                                                    color: editingCal === sensorKey ? 'var(--primary-color)' : '#778da9',
                                                    border: 'none',
                                                    padding: '0.5rem',
                                                    borderRadius: '6px',
                                                    minWidth: 'auto',
                                                    height: 'auto'
                                                }}
                                            >
                                                {editingCal === sensorKey ? <Plus size={18} style={{ transform: 'rotate(45deg)' }} /> : <Settings size={18} />}
                                            </button>
                                            <button
                                                className={styles.deleteButton}
                                                onClick={() => removeCalibrationSensor(sensorKey)}
                                                style={{ color: '#ef4444', background: 'rgba(239,68,68,0.1)', border: 'none', padding: '0.5rem', borderRadius: '6px' }}
                                            >
                                                <Trash2 size={18} />
                                            </button>
                                        </div>
                                    </div>

                                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
                                        <button
                                            className={styles.sidebarButton}
                                            style={{ background: 'rgba(119, 141, 169, 0.1)', justifyContent: 'center' }}
                                            onClick={() => pressButton(config.clear)}
                                            disabled={!config.clear}
                                        >
                                            <Trash2 size={16} />
                                            <span>Clear</span>
                                        </button>

                                        {config.numPoints >= 1 && (
                                            <button
                                                className={styles.sidebarButton}
                                                style={{ background: 'rgba(74, 222, 128, 0.1)', color: '#4ade80', justifyContent: 'center' }}
                                                onClick={() => pressButton(config.p1)}
                                                disabled={!config.p1}
                                            >
                                                <Thermometer size={16} />
                                                <span>{config.numPoints === 1 ? 'Mid' : 'Low'} ({config.v1 || '?'})</span>
                                            </button>
                                        )}

                                        {config.numPoints >= 2 && (
                                            <button
                                                className={styles.sidebarButton}
                                                style={{ background: 'rgba(0, 180, 216, 0.1)', color: '#00b4d8', justifyContent: 'center' }}
                                                onClick={() => pressButton(config.p2)}
                                                disabled={!config.p2}
                                            >
                                                <Thermometer size={16} />
                                                <span>{config.numPoints === 2 ? 'High' : 'Mid'} ({config.v2 || '?'})</span>
                                            </button>
                                        )}

                                        {config.numPoints >= 3 && (
                                            <button
                                                className={styles.sidebarButton}
                                                style={{ background: 'rgba(248, 113, 113, 0.1)', color: '#f87171', justifyContent: 'center' }}
                                                onClick={() => pressButton(config.p3)}
                                                disabled={!config.p3}
                                            >
                                                <Thermometer size={16} />
                                                <span>High ({config.v3 || '?'})</span>
                                            </button>
                                        )}
                                    </div>

                                    {editingCal === sensorKey && (
                                        <div className={styles.card} style={{ padding: '1.25rem', background: 'rgba(0,0,0,0.2)', animation: 'slideDown 0.2s ease-out' }}>
                                            <h6 style={{ color: '#778da9', fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                <Settings size={14} /> Configuration
                                            </h6>

                                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1.5rem' }}>
                                                <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                    <label className={styles.label} style={{ fontSize: '0.7rem' }}>Live Reading Entity (Override)</label>
                                                    <input
                                                        type="text"
                                                        className={styles.input}
                                                        style={{ height: '32px', fontSize: '0.8rem' }}
                                                        placeholder="sensor.ph_raw"
                                                        value={config.calibrationLiveEntity || ''}
                                                        onChange={(e) => updateCalibrationSensor(sensorKey, { calibrationLiveEntity: e.target.value })}
                                                    />
                                                </div>

                                                <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                    <label className={styles.label} style={{ fontSize: '0.7rem' }}>Clear Entity ID</label>
                                                    <input
                                                        type="text"
                                                        className={styles.input}
                                                        style={{ height: '32px', fontSize: '0.8rem' }}
                                                        value={config.clear}
                                                        onChange={(e) => updateCalibrationSensor(sensorKey, { clear: e.target.value })}
                                                    />
                                                </div>

                                                {config.numPoints >= 1 && (
                                                    <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '0.75rem' }}>
                                                        <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                            <label className={styles.label} style={{ fontSize: '0.7rem' }}>{config.numPoints === 1 ? 'Mid' : 'Low'} Entity ID</label>
                                                            <input
                                                                type="text"
                                                                className={styles.input}
                                                                style={{ height: '32px', fontSize: '0.8rem' }}
                                                                value={config.p1}
                                                                onChange={(e) => updateCalibrationSensor(sensorKey, { p1: e.target.value })}
                                                            />
                                                        </div>
                                                        <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                            <label className={styles.label} style={{ fontSize: '0.7rem' }}>Value</label>
                                                            <input
                                                                type="number"
                                                                step="0.01"
                                                                className={styles.input}
                                                                style={{ height: '32px', fontSize: '0.8rem' }}
                                                                value={config.v1}
                                                                onChange={(e) => updateCalibrationSensor(sensorKey, { v1: parseFloat(e.target.value) || 0 })}
                                                            />
                                                        </div>
                                                    </div>
                                                )}

                                                {config.numPoints >= 2 && (
                                                    <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '0.75rem' }}>
                                                        <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                            <label className={styles.label} style={{ fontSize: '0.7rem' }}>{config.numPoints === 2 ? 'High' : 'Mid'} Entity ID</label>
                                                            <input
                                                                type="text"
                                                                className={styles.input}
                                                                style={{ height: '32px', fontSize: '0.8rem' }}
                                                                value={config.p2}
                                                                onChange={(e) => updateCalibrationSensor(sensorKey, { p2: e.target.value })}
                                                            />
                                                        </div>
                                                        <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                            <label className={styles.label} style={{ fontSize: '0.7rem' }}>Value</label>
                                                            <input
                                                                type="number"
                                                                step="0.01"
                                                                className={styles.input}
                                                                style={{ height: '32px', fontSize: '0.8rem' }}
                                                                value={config.v2}
                                                                onChange={(e) => updateCalibrationSensor(sensorKey, { v2: parseFloat(e.target.value) || 0 })}
                                                            />
                                                        </div>
                                                    </div>
                                                )}

                                                {config.numPoints >= 3 && (
                                                    <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '0.75rem' }}>
                                                        <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                            <label className={styles.label} style={{ fontSize: '0.7rem' }}>High Entity ID</label>
                                                            <input
                                                                type="text"
                                                                className={styles.input}
                                                                style={{ height: '32px', fontSize: '0.8rem' }}
                                                                value={config.p3}
                                                                onChange={(e) => updateCalibrationSensor(sensorKey, { p3: e.target.value })}
                                                            />
                                                        </div>
                                                        <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                                            <label className={styles.label} style={{ fontSize: '0.7rem' }}>Value</label>
                                                            <input
                                                                type="number"
                                                                step="0.01"
                                                                className={styles.input}
                                                                style={{ height: '32px', fontSize: '0.8rem' }}
                                                                value={config.v3}
                                                                onChange={(e) => updateCalibrationSensor(sensorKey, { v3: parseFloat(e.target.value) || 0 })}
                                                            />
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Coral Spawning Settings */}
                {activeSection === 'spawning' && (
                    <div className={styles.settingsSection}>
                        <h4 className={styles.sectionHeader}>Coral Spawning Configuration</h4>
                        <p className={styles.description} style={{ marginBottom: '2rem' }}>
                            Configure the Home Assistant entities used to synchronize coral spawning parameters.
                        </p>

                        <div className={styles.card} style={{ padding: '1.5rem' }}>
                            <h5 style={{ color: '#e0e1dd', marginBottom: '1.5rem', fontSize: '1rem' }}>Home Assistant Entities</h5>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1.5rem' }}>
                                {[
                                    { key: 'profile', label: 'Profile (Input Select)', helper: 'Used to select the reef location preset.' },
                                    { key: 'startDate', label: 'Start Date (Input Datetime)', helper: 'The historical start date reference.' },
                                    { key: 'strength', label: 'Spawn Strength (Input Number)', helper: 'Intensity multiplier for light/moon.' },
                                    { key: 'phaseOffset', label: 'Phase Offset (Input Number)', helper: 'Days offset from full moon.' },
                                    { key: 'tempOffset', label: 'Temp Offset (Input Number)', helper: 'Global seasonal temperature bias.' },
                                    { key: 'nextSpawnDate', label: 'Next Spawn (Sensor)', helper: 'State displays the next predicted date.' },
                                    { key: 'moonPhase', label: 'Moon Phase (Sensor)', helper: 'Current phase of the moon.' },
                                    { key: 'targetTemp', label: 'Target Temp (Sensor)', helper: 'Calculated today\'s ideal temperature.' },
                                    { key: 'mainLightPlug', label: 'Main Light Plug (Switch)', helper: 'Tier 3: The smart plug to turn on/off with sunrise.' },
                                    { key: 'moonlightBulb', label: 'Moonlight Bulb (Light)', helper: 'Tier 3: The smart bulb matched to moon brightness.' },
                                    { key: 'thermostatClimate', label: 'Thermostat (Climate)', helper: 'Tier 3: Home Assistant generic thermostat target.' },
                                ].map((item) => (
                                    <div key={item.key} className={styles.settingGroup}>
                                        <label className={styles.label}>{item.label}</label>
                                        <input
                                            type="text"
                                            className={styles.input}
                                            value={settings.spawning.entities[item.key as keyof typeof settings.spawning.entities] || ''}
                                            onChange={(e) => {
                                                const newEntities = { ...settings.spawning.entities, [item.key]: e.target.value };
                                                updateSpawningSetting({ entities: newEntities });
                                            }}
                                            placeholder={`e.g. sensor.coral_${item.key}`}
                                        />
                                        <p style={{ fontSize: '0.7rem', color: '#778da9', marginTop: '0.4rem' }}>{item.helper}</p>
                                    </div>
                                ))}
                            </div>
                        </div>

                        <div style={{ marginTop: '2rem' }}>
                            <div className={styles.card} style={{ padding: '1.5rem', background: 'rgba(0, 180, 216, 0.05)', borderLeft: '4px solid #00b4d8' }}>
                                <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-start' }}>
                                    <Activity size={20} color="#00b4d8" style={{ marginTop: '2px' }} />
                                    <div>
                                        <div style={{ color: '#e0e1dd', fontWeight: 600, marginBottom: '0.25rem' }}>Active Syncing</div>
                                        <div style={{ color: '#778da9', fontSize: '0.85rem', lineHeight: '1.4' }}>
                                            The Coral Spawning tab in the dashboard will automatically write to these entities when you adjust sliders or change profiles. Ensure these entities are correctly defined in your Home Assistant configuration.
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* AI Guardian Settings */}
                {activeSection === 'ai' && (
                    <div className={styles.settingsSection}>
                        <h4 className={styles.sectionHeader}>AI Guardian Configuration</h4>
                        <div className={styles.card} style={{ padding: '1.5rem', marginBottom: '2rem' }}>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1.5rem' }}>
                                <div className={styles.settingGroup}>
                                    <label className={styles.label}>Enable AI Guardian</label>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginTop: '0.5rem' }}>
                                        <button
                                            className={`${styles.tabItem} ${settings.ai.enabled ? styles.activeTab : ''}`}
                                            onClick={() => updateNestedSetting('ai', { enabled: true })}
                                            style={{ padding: '4px 12px', fontSize: '0.8rem' }}
                                        >
                                            Enabled
                                        </button>
                                        <button
                                            className={`${styles.tabItem} ${!settings.ai.enabled ? styles.activeTab : ''}`}
                                            onClick={() => updateNestedSetting('ai', { enabled: false })}
                                            style={{ padding: '4px 12px', fontSize: '0.8rem' }}
                                        >
                                            Disabled
                                        </button>
                                    </div>
                                </div>
                                <div className={styles.settingGroup}>
                                    <label className={styles.label}>Simli API Key</label>
                                    <input
                                        type="password"
                                        className={styles.input}
                                        placeholder="Enter Simli API Key"
                                        value={settings.ai.simliApiKey}
                                        onChange={(e) => updateNestedSetting('ai', { simliApiKey: e.target.value.trim() })}
                                    />
                                </div>
                                <div className={styles.settingGroup}>
                                    <label className={styles.label}>Gemini API Key</label>
                                    <input
                                        type="password"
                                        className={styles.input}
                                        placeholder="Enter Gemini API Key"
                                        value={settings.ai.geminiApiKey}
                                        onChange={(e) => updateNestedSetting('ai', { geminiApiKey: e.target.value.trim() })}
                                    />
                                </div>
                                <div className={styles.settingGroup}>
                                    <label className={styles.label}>OpenAI API Key (Required for Lip-Sync)</label>
                                    <input
                                        type="password"
                                        className={styles.input}
                                        placeholder="Enter OpenAI API Key"
                                        value={settings.ai.openaiApiKey}
                                        onChange={(e) => updateNestedSetting('ai', { openaiApiKey: e.target.value.trim() })}
                                    />
                                </div>
                                <div className={styles.settingGroup}>
                                    <label className={styles.label}>Simli Face ID</label>
                                    <input
                                        type="text"
                                        className={styles.input}
                                        placeholder="Face ID (e.g. e6fcd...)"
                                        value={settings.ai.faceId}
                                        onChange={(e) => updateNestedSetting('ai', { faceId: e.target.value.trim() })}
                                    />
                                </div>
                            </div>
                            <p style={{ fontSize: '0.75rem', color: '#778da9', marginTop: '1rem' }}>
                                The AI Guardian uses Simli for the talking avatar and Gemini for the brain.
                                Lagertha will monitor your reef and respond based on live data.
                            </p>
                        </div>
                    </div>
                )}

                {/* Water Change Settings */}
                {activeSection === 'water-change' && (
                    <div className={styles.settingsSection}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
                            <h2 className={styles.sectionTitle}>Water Change Configuration</h2>
                            <Droplets size={24} color="var(--primary-color)" />
                        </div>

                        <div className={styles.card} style={{ marginBottom: '1.5rem' }}>
                            <h3 className={styles.sectionSubtitle}>Pumps & Sensors</h3>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '1.5rem', marginTop: '1rem' }}>
                                <div>
                                    <label className={styles.inputLabel}>Waste Pump Switch</label>
                                    <input
                                        type="text"
                                        className={styles.input}
                                        value={settings.waterChange.entities.pumpWaste}
                                        onChange={(e) => updateNestedSetting('waterChange', {
                                            entities: { ...settings.waterChange.entities, pumpWaste: e.target.value }
                                        } as any)}
                                        placeholder="switch.awc_waste_pump"
                                    />
                                    <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
                                        <button
                                            onClick={() => updateNestedSetting('waterChange', {
                                                entities: { ...settings.waterChange.entities, pumpWasteShowInDiagram: !settings.waterChange.entities.pumpWasteShowInDiagram }
                                            } as any)}
                                            className={`${styles.tabItem} ${settings.waterChange.entities.pumpWasteShowInDiagram ? styles.activeTab : ''}`}
                                            style={{ padding: '0.2rem 0.5rem', fontSize: '0.65rem', flex: 1, justifyContent: 'center' }}
                                        >
                                            {settings.waterChange.entities.pumpWasteShowInDiagram ? 'VISIBLE' : 'HIDDEN'}
                                        </button>
                                        <select
                                            className={styles.input}
                                            style={{ height: '24px', padding: '0 0.2rem', fontSize: '0.65rem', flex: 1.5 }}
                                            value={settings.waterChange.entities.pumpWastePosition || 'awc_waste'}
                                            onChange={(e) => updateNestedSetting('waterChange', {
                                                entities: { ...settings.waterChange.entities, pumpWastePosition: e.target.value as any }
                                            } as any)}
                                        >
                                            <option value="awc_waste">AWC Waste</option>
                                            <option value="sump">Sump</option>
                                            <option value="room">Room</option>
                                        </select>
                                    </div>
                                </div>
                                <div>
                                    <label className={styles.inputLabel}>Fresh Pump Switch</label>
                                    <input
                                        type="text"
                                        className={styles.input}
                                        value={settings.waterChange.entities.pumpFresh}
                                        onChange={(e) => updateNestedSetting('waterChange', {
                                            entities: { ...settings.waterChange.entities, pumpFresh: e.target.value }
                                        } as any)}
                                        placeholder="switch.awc_fresh_pump"
                                    />
                                    <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
                                        <button
                                            onClick={() => updateNestedSetting('waterChange', {
                                                entities: { ...settings.waterChange.entities, pumpFreshShowInDiagram: !settings.waterChange.entities.pumpFreshShowInDiagram }
                                            } as any)}
                                            className={`${styles.tabItem} ${settings.waterChange.entities.pumpFreshShowInDiagram ? styles.activeTab : ''}`}
                                            style={{ padding: '0.2rem 0.5rem', fontSize: '0.65rem', flex: 1, justifyContent: 'center' }}
                                        >
                                            {settings.waterChange.entities.pumpFreshShowInDiagram ? 'VISIBLE' : 'HIDDEN'}
                                        </button>
                                        <select
                                            className={styles.input}
                                            style={{ height: '24px', padding: '0 0.2rem', fontSize: '0.65rem', flex: 1.5 }}
                                            value={settings.waterChange.entities.pumpFreshPosition || 'awc_fresh'}
                                            onChange={(e) => updateNestedSetting('waterChange', {
                                                entities: { ...settings.waterChange.entities, pumpFreshPosition: e.target.value as any }
                                            } as any)}
                                        >
                                            <option value="awc_fresh">AWC Fresh</option>
                                            <option value="sump">Sump</option>
                                            <option value="room">Room</option>
                                        </select>
                                    </div>
                                </div>
                                <div>
                                    <label className={styles.inputLabel}>Waste Tank Full Sensor</label>
                                    <input
                                        type="text"
                                        className={styles.input}
                                        value={settings.waterChange.entities.wasteFull}
                                        onChange={(e) => updateNestedSetting('waterChange', {
                                            entities: { ...settings.waterChange.entities, wasteFull: e.target.value }
                                        } as any)}
                                        placeholder="binary_sensor.awc_waste_full"
                                    />
                                </div>
                                <div>
                                    <label className={styles.inputLabel}>Fresh Tank Empty Sensor</label>
                                    <input
                                        type="text"
                                        className={styles.input}
                                        value={settings.waterChange.entities.freshEmpty}
                                        onChange={(e) => updateNestedSetting('waterChange', {
                                            entities: { ...settings.waterChange.entities, freshEmpty: e.target.value }
                                        } as any)}
                                        placeholder="binary_sensor.awc_fresh_empty"
                                    />
                                </div>
                                <div>
                                    <label className={styles.inputLabel}>Tank High Level Sensor</label>
                                    <input
                                        type="text"
                                        className={styles.input}
                                        value={settings.waterChange.entities.tankHigh}
                                        onChange={(e) => updateNestedSetting('waterChange', {
                                            entities: { ...settings.waterChange.entities, tankHigh: e.target.value }
                                        } as any)}
                                        placeholder="binary_sensor.awc_tank_high"
                                    />
                                </div>
                                <div>
                                    <label className={styles.inputLabel}>Waste Level Sensor (Estimated/Volume)</label>
                                    <input
                                        type="text"
                                        className={styles.input}
                                        value={settings.waterChange.entities.wasteLevel}
                                        onChange={(e) => updateNestedSetting('waterChange', {
                                            entities: { ...settings.waterChange.entities, wasteLevel: e.target.value }
                                        } as any)}
                                        placeholder="sensor.waste_water_volume"
                                    />
                                </div>
                                <div>
                                    <label className={styles.inputLabel}>Fresh Level Sensor (Estimated/Volume)</label>
                                    <input
                                        type="text"
                                        className={styles.input}
                                        value={settings.waterChange.entities.freshLevel}
                                        onChange={(e) => updateNestedSetting('waterChange', {
                                            entities: { ...settings.waterChange.entities, freshLevel: e.target.value }
                                        } as any)}
                                        placeholder="sensor.fresh_saltwater_volume"
                                    />
                                </div>
                                <div>
                                    <label className={styles.inputLabel}>Water Changed Today (Volume)</label>
                                    <input
                                        type="text"
                                        className={styles.input}
                                        value={settings.waterChange.entities.todayTotal}
                                        onChange={(e) => updateNestedSetting('waterChange', {
                                            entities: { ...settings.waterChange.entities, todayTotal: e.target.value }
                                        } as any)}
                                        placeholder="sensor.awc_today_volume"
                                    />
                                </div>
                                <div>
                                    <label className={styles.inputLabel}>Water Changed This Week (Volume)</label>
                                    <input
                                        type="text"
                                        className={styles.input}
                                        value={settings.waterChange.entities.weekTotal}
                                        onChange={(e) => updateNestedSetting('waterChange', {
                                            entities: { ...settings.waterChange.entities, weekTotal: e.target.value }
                                        } as any)}
                                        placeholder="sensor.awc_week_volume"
                                    />
                                </div>
                                <div>
                                    <label className={styles.inputLabel}>Water Changed This Month (Volume)</label>
                                    <input
                                        type="text"
                                        className={styles.input}
                                        value={settings.waterChange.entities.monthTotal}
                                        onChange={(e) => updateNestedSetting('waterChange', {
                                            entities: { ...settings.waterChange.entities, monthTotal: e.target.value }
                                        } as any)}
                                        placeholder="sensor.awc_month_volume"
                                    />
                                </div>
                            </div>
                        </div>

                        <div className={styles.card}>
                            <h3 className={styles.sectionSubtitle}>Container Capacities</h3>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1.5rem', marginTop: '1rem' }}>
                                <div>
                                    <label className={styles.inputLabel}>Waste Tank Capacity (Liters)</label>
                                    <input
                                        type="number"
                                        className={styles.input}
                                        value={settings.waterChange.containers.wasteCapacity}
                                        onChange={(e) => updateNestedSetting('waterChange', {
                                            containers: { ...settings.waterChange.containers, wasteCapacity: parseFloat(e.target.value) }
                                        } as any)}
                                    />
                                </div>
                                <div>
                                    <label className={styles.inputLabel}>Fresh Tank Capacity (Liters)</label>
                                    <input
                                        type="number"
                                        className={styles.input}
                                        value={settings.waterChange.containers.freshCapacity}
                                        onChange={(e) => updateNestedSetting('waterChange', {
                                            containers: { ...settings.waterChange.containers, freshCapacity: parseFloat(e.target.value) }
                                        } as any)}
                                    />
                                </div>
                            </div>
                        </div>

                        <div className={styles.card}>
                            <h3 className={styles.sectionSubtitle}>Daily Change Presets</h3>
                            <div style={{ marginBottom: '1.5rem', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '1.5rem' }}>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr auto', gap: '1rem', alignItems: 'end' }}>
                                    <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                        <label className={styles.label}>Label (e.g. 5%)</label>
                                        <input
                                            type="text"
                                            className={styles.input}
                                            value={newAwcPreset.label}
                                            onChange={(e) => setNewAwcPreset({ ...newAwcPreset, label: e.target.value })}
                                            placeholder="5%"
                                        />
                                    </div>
                                    <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                        <label className={styles.label}>Percentage (%)</label>
                                        <input
                                            type="number"
                                            className={styles.input}
                                            value={newAwcPreset.percentage}
                                            onChange={(e) => setNewAwcPreset({ ...newAwcPreset, percentage: parseFloat(e.target.value) })}
                                        />
                                    </div>
                                    <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                        <label className={styles.label}>HA Button Entity</label>
                                        <input
                                            type="text"
                                            className={styles.input}
                                            value={newAwcPreset.entityId}
                                            onChange={(e) => setNewAwcPreset({ ...newAwcPreset, entityId: e.target.value })}
                                            placeholder="button.awc_5_percent"
                                        />
                                    </div>
                                    <button
                                        onClick={() => {
                                            if (newAwcPreset.label && newAwcPreset.entityId) {
                                                addAwcPreset(newAwcPreset);
                                                setNewAwcPreset({ label: '', percentage: 1, entityId: '' });
                                            }
                                        }}
                                        className={styles.saveButton}
                                        style={{ width: 'auto', padding: '0.6rem 1rem' }}
                                    >
                                        <Plus size={18} /> Add
                                    </button>
                                </div>
                            </div>

                            <div style={{ display: 'grid', gap: '1rem' }}>
                                {settings.waterChange.percentagePresets.map(preset => (
                                    <div key={preset.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'rgba(255,255,255,0.03)', padding: '0.75rem 1rem', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.05)' }}>
                                        <div>
                                            <div style={{ fontWeight: 600, color: 'var(--primary-color)' }}>{preset.label} ({preset.percentage}%)</div>
                                            <div style={{ fontSize: '0.75rem', color: '#778da9' }}>Entity: {preset.entityId}</div>
                                        </div>
                                        <button
                                            onClick={() => removeAwcPreset(preset.id)}
                                            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#ef4444' }}
                                        >
                                            <Trash2 size={16} />
                                        </button>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                )}

                {/* Lighting Settings */}
                {activeSection === 'lighting' && (
                    <div className={styles.settingsSection}>
                        <h4 className={styles.sectionHeader}>Lighting Configuration</h4>
                        <div className={styles.card} style={{ padding: '1.5rem' }}>
                            <h5 style={{ color: '#e0e1dd', marginBottom: '1.5rem', fontSize: '1rem' }}>Spectrum Channel Entities</h5>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1.5rem' }}>
                                {[
                                    { key: 'white', label: 'White Channel' },
                                    { key: 'blue', label: 'Blue Channel' },
                                    { key: 'royalBlue', label: 'Royal Blue Channel' },
                                    { key: 'violet', label: 'Violet Channel' },
                                    { key: 'uv', label: 'UV Channel' },
                                    { key: 'red', label: 'Red Channel' },
                                    { key: 'green', label: 'Green Channel' },
                                    { key: 'moonlight', label: 'Moonlight Channel' },
                                ].map(ch => (
                                    <div key={ch.key} className={styles.settingGroup}>
                                        <label className={styles.label}>{ch.label}</label>
                                        <input
                                            type="text"
                                            className={styles.input}
                                            placeholder={`number.reef_light_${ch.key}`}
                                            value={(settings.lighting.channels as any)[ch.key]}
                                            onChange={(e) => {
                                                const currentChannels = { ...settings.lighting.channels };
                                                (currentChannels as any)[ch.key] = e.target.value.trim();
                                                updateNestedSetting('lighting', { channels: currentChannels });
                                            }}
                                        />
                                    </div>
                                ))}
                            </div>
                            <p style={{ fontSize: '0.75rem', color: '#778da9', marginTop: '1rem' }}>
                                Map these to your Home Assistant <code>number</code> entities to control each channel&apos;s intensity (0-100).
                            </p>
                        </div>
                    </div>
                )}

                {/* Data Management */}
                {activeSection === 'data' && (
                    <div className={styles.settingsSection}>
                        <h4 className={styles.sectionHeader}>Data Management</h4>
                        <div className={styles.card} style={{ padding: '1.5rem' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <div>
                                    <h5 style={{ color: '#e0e1dd' }}>Manual History</h5>
                                    <p className={styles.description}>Wipe all manual water test results.</p>
                                </div>
                                <button
                                    onClick={() => confirm('Clear history?') && clearManualReadings()}
                                    className={styles.deleteButton}
                                >
                                    Clear History
                                </button>
                            </div>
                        </div>
                    </div>
                )}

                {/* Camera Settings */}
                {activeSection === 'camera' && (
                    <div className={styles.settingsSection}>
                        <h4 className={styles.sectionHeader}>Camera Configuration</h4>

                        {/* Enable/Disable */}
                        <div className={styles.card} style={{ padding: '1.5rem', marginBottom: '2rem' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <div>
                                    <div style={{ color: '#e0e1dd', fontWeight: 600, marginBottom: '0.25rem' }}>Enable Camera</div>
                                    <div style={{ color: '#778da9', fontSize: '0.85rem' }}>Show the Camera tab in the dashboard navigation</div>
                                </div>
                                <label style={{ position: 'relative', display: 'inline-block', width: '48px', height: '26px', cursor: 'pointer' }}>
                                    <input
                                        type="checkbox"
                                        checked={settings.camera.enabled}
                                        onChange={(e) => updateNestedSetting('camera', { enabled: e.target.checked } as any)}
                                        style={{ opacity: 0, width: 0, height: 0 }}
                                    />
                                    <span style={{
                                        position: 'absolute', inset: 0, borderRadius: '26px', transition: 'all 0.3s',
                                        background: settings.camera.enabled ? 'var(--primary-color)' : 'rgba(255,255,255,0.1)',
                                    }}>
                                        <span style={{
                                            position: 'absolute', width: '20px', height: '20px', borderRadius: '50%',
                                            background: '#fff', top: '3px', transition: 'all 0.3s',
                                            left: settings.camera.enabled ? '25px' : '3px',
                                        }} />
                                    </span>
                                </label>
                            </div>
                        </div>

                        {/* Configured Cameras */}
                        <h5 style={{ color: '#e0e1dd', marginBottom: '1rem' }}>Configured Cameras</h5>
                        <div style={{ display: 'grid', gap: '1rem', marginBottom: '2rem' }}>
                            {(settings.camera.cameras || []).map((cam) => (
                                <div key={cam.id} className={styles.card} style={{ padding: '1.25rem' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem' }}>
                                        <div style={{ flex: 1, minWidth: 0 }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                                                <Video size={18} style={{ color: 'var(--primary-color)', flexShrink: 0 }} />
                                                <span style={{ fontWeight: 600, color: '#e0e1dd', fontSize: '1rem' }}>{cam.label}</span>
                                                <span style={{
                                                    fontSize: '0.65rem', textTransform: 'uppercase', fontWeight: 700,
                                                    background: 'rgba(var(--primary-rgb), 0.1)', color: 'var(--primary-color)',
                                                    padding: '2px 6px', borderRadius: '4px',
                                                    border: '1px solid rgba(var(--primary-rgb), 0.2)',
                                                }}>{cam.streamType}</span>
                                            </div>
                                            <span style={{ color: '#778da9', fontSize: '0.8rem', fontFamily: 'monospace' }}>{cam.entityId}</span>
                                        </div>
                                        <button
                                            onClick={() => {
                                                if (confirm(`Remove camera "${cam.label}"?`)) {
                                                    const updated = settings.camera.cameras.filter(c => c.id !== cam.id);
                                                    updateNestedSetting('camera', { cameras: updated } as any);
                                                }
                                            }}
                                            style={{ color: '#ef4444', background: 'none', border: 'none', cursor: 'pointer', padding: '0.5rem' }}
                                        >
                                            <Trash2 size={18} />
                                        </button>
                                    </div>
                                </div>
                            ))}
                            {(settings.camera.cameras || []).length === 0 && (
                                <div className={styles.card} style={{
                                    backgroundColor: 'transparent', border: '1px dashed #27272a',
                                    textAlign: 'center', padding: '2rem',
                                }}>
                                    <p style={{ color: '#778da9', margin: 0 }}>No cameras configured yet.</p>
                                </div>
                            )}
                        </div>

                        {/* Add Camera Form */}
                        <h5 style={{ color: '#e0e1dd', marginBottom: '1rem' }}>Add Camera</h5>
                        <div className={styles.card} style={{ padding: '1.5rem' }}>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', alignItems: 'end' }}>
                                <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                    <label className={styles.label}>Label</label>
                                    <input
                                        type="text"
                                        className={styles.input}
                                        placeholder="e.g. Reef Tank"
                                        id="cam-label"
                                    />
                                </div>
                                <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                    <label className={styles.label}>HA Entity ID</label>
                                    <input
                                        type="text"
                                        className={styles.input}
                                        placeholder="camera.reef_tank"
                                        id="cam-entity"
                                    />
                                </div>
                                <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                    <label className={styles.label}>Stream Type</label>
                                    <select
                                        className={styles.input}
                                        id="cam-stream"
                                        defaultValue="mjpeg"
                                        style={{ appearance: 'none', background: 'rgba(255,255,255,0.05)' }}
                                    >
                                        <option value="mjpeg">MJPEG</option>
                                        <option value="webrtc">WebRTC</option>
                                    </select>
                                </div>
                                <div className={styles.settingGroup} style={{ marginBottom: 0 }}>
                                    <label className={styles.label}>Direct Stream URL <span style={{ color: '#778da9', fontWeight: 400 }}>(optional)</span></label>
                                    <input
                                        type="text"
                                        className={styles.input}
                                        placeholder="e.g. http://192.168.0.162:1984/api/stream.mjpeg?src=reef_tank"
                                        id="cam-direct-url"
                                    />
                                </div>
                                <button
                                    className={styles.addButton}
                                    onClick={() => {
                                        const label = (document.getElementById('cam-label') as HTMLInputElement)?.value?.trim();
                                        const entityId = (document.getElementById('cam-entity') as HTMLInputElement)?.value?.trim();
                                        const streamType = (document.getElementById('cam-stream') as HTMLSelectElement)?.value as 'mjpeg' | 'webrtc';
                                        const directStreamUrl = (document.getElementById('cam-direct-url') as HTMLInputElement)?.value?.trim() || undefined;
                                        if (!label || !entityId) return;
                                        const id = entityId.replace(/[^a-z0-9]/g, '_') + '_' + Date.now();
                                        const updated = [...(settings.camera.cameras || []), { id, label, entityId, streamType, directStreamUrl }];
                                        updateNestedSetting('camera', { cameras: updated } as any);
                                        (document.getElementById('cam-label') as HTMLInputElement).value = '';
                                        (document.getElementById('cam-entity') as HTMLInputElement).value = '';
                                        (document.getElementById('cam-direct-url') as HTMLInputElement).value = '';
                                    }}
                                >
                                    <Plus size={18} />
                                </button>
                            </div>
                        </div>

                        {/* Setup Guide */}
                        <div className={styles.card} style={{ padding: '1.5rem', marginTop: '2rem', borderColor: 'rgba(var(--primary-rgb), 0.2)', background: 'rgba(var(--primary-rgb), 0.03)' }}>
                            <h5 style={{ color: '#e0e1dd', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                <Settings size={16} /> Camera Setup Guide
                            </h5>
                            <div style={{ color: '#778da9', fontSize: '0.85rem', lineHeight: 1.7 }}>
                                <p style={{ margin: '0 0 0.75rem 0' }}><strong style={{ color: '#e0e1dd' }}>USB Camera</strong> (e.g. ELP 4K IMX317):</p>
                                <ol style={{ margin: '0 0 1rem 1.25rem', padding: 0 }}>
                                    <li>Pass USB device through to HA VM (Proxmox: <code style={{ color: '#00b4d8' }}>qm set &lt;vmid&gt; -usb0 host=&lt;vid:pid&gt;</code>)</li>
                                    <li>In HA, add the <strong>Generic Camera</strong> or <strong>FFmpeg</strong> integration</li>
                                    <li>Set the stream source to your USB device (e.g. <code style={{ color: '#00b4d8' }}>/dev/video0</code>)</li>
                                    <li>Enter the resulting <code style={{ color: '#00b4d8' }}>camera.*</code> entity ID above</li>
                                </ol>
                                <p style={{ margin: '0 0 0.75rem 0' }}><strong style={{ color: '#e0e1dd' }}>Wireless / IP Camera</strong>:</p>
                                <ol style={{ margin: '0 0 0 1.25rem', padding: 0 }}>
                                    <li>Add via HA&apos;s <strong>ONVIF</strong>, <strong>Generic Camera</strong>, or the camera&apos;s native integration</li>
                                    <li>Enter the resulting <code style={{ color: '#00b4d8' }}>camera.*</code> entity ID above</li>
                                </ol>
                            </div>
                        </div>
                    </div>
                )}
            </main>

            {showDeleteConfirm && (
                <div className={styles.modalOverlay}>
                    <div className={styles.modal}>
                        <h3>Reset All Settings?</h3>
                        <p>This will wipe all configurations and refresh the app.</p>
                        <div className={styles.modalActions}>
                            <button className={styles.cancelButton} onClick={() => setShowDeleteConfirm(false)}>Cancel</button>
                            <button className={styles.deleteButton} onClick={() => {
                                localStorage.removeItem('reefSettings');
                                window.location.reload();
                            }}>Reset</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};
