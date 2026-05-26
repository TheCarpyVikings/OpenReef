import React, { useState, useEffect } from 'react';
import { useSettings } from '@/context/SettingsContext';
import styles from '@/app/dashboard.module.css';
import { ArrowRight, ArrowLeft, Check, Smartphone, Activity, Zap, Lightbulb, AlertTriangle, RefreshCw, Database, X } from 'lucide-react';
import { useHomeAssistant } from '@/hooks/use-home-assistant';

const WIZARD_STEPS = [
    { id: 'welcome', title: 'Welcome', icon: <Smartphone size={24} /> },
    { id: 'ha_connection', title: 'Home Assistant', icon: <Database size={24} /> },
    { id: 'general', title: 'General Setup', icon: <Smartphone size={24} /> }, // Reusing Smartphone as placeholder if needed, or maybe Settings icon
    { id: 'sensors', title: 'Sensors', icon: <Activity size={24} /> },
    { id: 'equipment', title: 'Equipment', icon: <Zap size={24} /> },
    { id: 'lighting', title: 'Lighting', icon: <Lightbulb size={24} /> },
    { id: 'completion', title: 'All Done!', icon: <Check size={24} /> },
];

export const SetupWizard: React.FC<{ onComplete: () => void }> = ({ onComplete }) => {
    const { settings, updateNestedSetting, updateSettings } = useSettings();
    const { isConnected, reconnect } = useHomeAssistant();
    const [currentStep, setCurrentStep] = useState(0);
    const [isTesting, setIsTesting] = useState(false);
    const [testResult, setTestResult] = useState<'success' | 'error' | null>(null);

    // Local state for form inputs to avoid constant context updates during typing
    // We'll initialize this with current settings when the step changes
    const [localGeneral, setLocalGeneral] = useState(settings.general);
    const [localEntities, setLocalEntities] = useState(settings.entities);
    const isAddonMode = process.env.NEXT_PUBLIC_HA_ADDON_MODE === 'true';

    useEffect(() => {
        const timeout = window.setTimeout(() => {
            setLocalGeneral(settings.general);
            setLocalEntities(settings.entities);
        }, 0);
        return () => window.clearTimeout(timeout);
    }, [settings, currentStep]);


    const handleNext = () => {
        // Save current step data to context if needed
        if (currentStep === 2) { // General
            updateNestedSetting('general', localGeneral);
        } else if (currentStep === 3 || currentStep === 4) { // Sensors or Equipment
            updateSettings({ entities: localEntities });
        }

        if (currentStep < WIZARD_STEPS.length - 1) {
            setCurrentStep(currentStep + 1);
        } else {
            onComplete();
        }
    };

    const handleBack = () => {
        if (currentStep > 0) {
            setCurrentStep(currentStep - 1);
        }
    };

    const handleTestConnection = async () => {
        setIsTesting(true);
        setTestResult(null);
        updateNestedSetting('general', { haUrl: localGeneral.haUrl, haToken: '' });

        // Give it a moment to update context/local storage if needed, then try reconnect
        setTimeout(async () => {
            try {
                await reconnect();
                // Wait for connection status
                setTimeout(() => {
                    if (isConnected) {
                        setTestResult('success');
                    } else {
                        setTestResult('error');
                    }
                    setIsTesting(false);
                }, 2000);
            } catch {
                setTestResult('error');
                setIsTesting(false);
            }
        }, 500);
    };

    const renderStepContent = () => {
        switch (WIZARD_STEPS[currentStep].id) {
            case 'welcome':
                return (
                    <div className={styles.wizardStepContainer}>
                        <div className={styles.wizardWelcomeGraphics}>
                            {/* Placeholder for a nice image or graphic */}
                            <div style={{ fontSize: '4rem', marginBottom: '1rem' }}>🐠</div>
                        </div>
                        <h2>Welcome to OpenReef!</h2>
                        <p>
                            This wizard will guide you through the initial setup of your OpenReef.
                            We&apos;ll connect to Home Assistant, configure your sensors, set up your equipment,
                            and get your lighting schedule ready.
                        </p>
                        <p>It typically takes about 5 minutes.</p>
                    </div>
                );

            case 'ha_connection':
                return (
                    <div className={styles.wizardStepContainer}>
                        <h3>Connect to Home Assistant</h3>
                        <p className={styles.wizardDescription}>
                            {isAddonMode
                                ? 'OpenReef is connected through the Home Assistant Supervisor and Ingress.'
                                : 'OpenReef connects through the server-side Home Assistant gateway configured for this deployment.'}
                        </p>

                        {!isAddonMode && (
                            <div className={styles.settingGroup}>
                                <label className={styles.label}>Home Assistant URL</label>
                                <input
                                    type="text"
                                    className={styles.input}
                                    value={localGeneral.haUrl}
                                    onChange={(e) => setLocalGeneral({ ...localGeneral, haUrl: e.target.value })}
                                    placeholder="Configured on the server"
                                />
                            </div>
                        )}

                        <div className={styles.wizardActionRow}>
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
                                    opacity: isTesting ? 0.7 : 1,
                                    margin: '0 auto'
                                }}
                            >
                                {isTesting ? <RefreshCw size={18} className={styles.spin} /> : testResult === 'success' ? <Check size={18} /> : <RefreshCw size={18} />}
                                {isTesting ? 'Testing...' : testResult === 'success' ? 'Connected!' : 'Test Connection'}
                            </button>
                        </div>
                        {testResult === 'error' && (
                            <div className={styles.errorMessage}>
                                <AlertTriangle size={16} /> Could not connect to the server-side Home Assistant gateway.
                            </div>
                        )}
                    </div>
                );

            case 'general':
                return (
                    <div className={styles.wizardStepContainer}>
                        <h3>General Settings</h3>
                        <div className={styles.settingGroup}>
                            <label className={styles.label}>Tank Name</label>
                            <input
                                type="text"
                                className={styles.input}
                                value={localGeneral.tankName}
                                onChange={(e) => setLocalGeneral({ ...localGeneral, tankName: e.target.value })}
                            />
                        </div>
                        <div className={styles.settingGroup}>
                            <label className={styles.label}>Your Name</label>
                            <input
                                type="text"
                                className={styles.input}
                                value={localGeneral.userName}
                                onChange={(e) => setLocalGeneral({ ...localGeneral, userName: e.target.value })}
                            />
                        </div>
                        <div className={styles.settingGroup}>
                            <label className={styles.label}>Theme Color</label>
                            <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.5rem', justifyContent: 'center' }}>
                                {['#00b4d8', '#4ade80', '#fbbf24', '#f87171', '#a855f7', '#ec4899'].map(color => (
                                    <button
                                        key={color}
                                        onClick={() => setLocalGeneral({ ...localGeneral, themeColor: color })}
                                        style={{
                                            width: '40px',
                                            height: '40px',
                                            borderRadius: '50%',
                                            backgroundColor: color,
                                            border: localGeneral.themeColor === color ? '3px solid #fff' : '2px solid transparent',
                                            cursor: 'pointer',
                                            boxShadow: localGeneral.themeColor === color ? '0 0 10px rgba(255,255,255,0.5)' : 'none',
                                            transition: 'all 0.2s'
                                        }}
                                    />
                                ))}
                            </div>
                        </div>
                    </div>
                );

            case 'sensors':
                const coreSensors: Array<{ id: string; label: string; key: keyof typeof localEntities.tank }> = [
                    { id: 'temp', label: 'Temperature', key: 'temp' },
                    { id: 'ph', label: 'pH', key: 'ph' },
                    { id: 'salinity', label: 'Salinity', key: 'salinity' },
                    { id: 'orp', label: 'ORP', key: 'orp' },
                ];
                return (
                    <div className={styles.wizardStepContainer}>
                        <h3>Map Your Sensors</h3>
                        <p className={styles.wizardDescription}>Enter the Entity ID from Home Assistant for each sensor.</p>
                        <div className={styles.wizardGrid}>
                            {coreSensors.map(sensor => (
                                <div key={sensor.id} className={styles.settingGroup}>
                                    <label className={styles.label}>{sensor.label}</label>
                                    <input
                                        type="text"
                                        className={styles.input}
                                        placeholder={`sensor.tank_${sensor.id}`}
                                        value={localEntities.tank[sensor.key]}
                                        onChange={(e) => {
                                            setLocalEntities({
                                                ...localEntities,
                                                tank: {
                                                    ...localEntities.tank,
                                                    [sensor.key]: e.target.value,
                                                },
                                            });
                                        }}
                                    />
                                </div>
                            ))}
                        </div>
                    </div>
                );

            case 'equipment':
                const coreEquipment = [
                    { id: 'RETURN_PUMP', label: 'Return Pump' },
                    { id: 'HEATER', label: 'Heater' },
                    { id: 'SKIMMER', label: 'Skimmer' },
                    { id: 'ATO', label: 'ATO' },
                ];
                return (
                    <div className={styles.wizardStepContainer}>
                        <h3>Map Your Equipment</h3>
                        <p className={styles.wizardDescription}>
                            Control switches and monitor power usage.
                        </p>
                        <div className={styles.wizardGrid}>
                            {coreEquipment.map(eq => (
                                <div key={eq.id} className={styles.card} style={{ padding: '1rem' }}>
                                    <h4 style={{ marginBottom: '0.5rem', color: '#e0e1dd' }}>{eq.label}</h4>
                                    <div className={styles.settingGroup}>
                                        <label className={styles.subLabel}>Switch Entity</label>
                                        <input
                                            type="text"
                                            className={styles.input}
                                            placeholder="switch.device_name"
                                            value={localEntities.equipment[eq.id]?.switch || ''}
                                            onChange={(e) => {
                                                const newEntities = JSON.parse(JSON.stringify(localEntities));
                                                if (!newEntities.equipment[eq.id]) newEntities.equipment[eq.id] = {};
                                                newEntities.equipment[eq.id].switch = e.target.value;
                                                setLocalEntities(newEntities);
                                            }}
                                        />
                                    </div>
                                    <div className={styles.settingGroup}>
                                        <label className={styles.subLabel}>Power Sensor (Optional)</label>
                                        <input
                                            type="text"
                                            className={styles.input}
                                            placeholder="sensor.device_power"
                                            value={localEntities.equipment[eq.id]?.power || ''}
                                            onChange={(e) => {
                                                const newEntities = JSON.parse(JSON.stringify(localEntities));
                                                if (!newEntities.equipment[eq.id]) newEntities.equipment[eq.id] = {};
                                                newEntities.equipment[eq.id].power = e.target.value;
                                                setLocalEntities(newEntities);
                                            }}
                                        />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                );

            case 'lighting':
                return (
                    <div className={styles.wizardStepContainer}>
                        <h3>Lighting Setup</h3>
                        <p className={styles.wizardDescription}>
                            We&apos;ve pre-configured a standard AB+ spectrum schedule for you.
                            You can customize channels and detailed schedules in the full settings menu later.
                        </p>
                        <div className={styles.card} style={{ padding: '2rem', textAlign: 'center' }}>
                            <Lightbulb size={48} color="#fbbf24" style={{ marginBottom: '1rem' }} />
                            <p>Default Schedule: <strong>11 hours</strong> (10:00 - 21:00)</p>
                            <p>Ramp Up/Down: <strong>1 hour</strong></p>
                            <p>Moonlight: <strong>Enabled</strong> (5%)</p>
                        </div>
                        <p className={styles.helperText} style={{ marginTop: '2rem' }}>
                            Note: Ensure your light entities are named correctly in Home Assistant (e.g. number.reef_light_blue) or map them in Settings &gt; Lighting later.
                        </p>
                    </div>
                );

            case 'completion':
                return (
                    <div className={styles.wizardStepContainer}>
                        <div style={{ fontSize: '4rem', marginBottom: '1rem', color: '#4ade80' }}>
                            <Check size={64} />
                        </div>
                        <h2>You&apos;re All Set!</h2>
                        <p>
                            Your controller is now configured and ready to go.
                            Explore the dashboard, check your live stats, and fine-tune your alerts in the settings.
                        </p>
                        <div className={styles.card} style={{ marginTop: '2rem', padding: '1.5rem', background: 'rgba(255,255,255,0.05)' }}>
                            <h4>Next Steps:</h4>
                            <ul style={{ textAlign: 'left', marginTop: '1rem', paddingLeft: '1.5rem', color: '#aabbc9' }}>
                                <li>Verify sensor readings on the Dashboard.</li>
                                <li>Test equipment switches manually.</li>
                                <li>Set up critical alarms in Mission Control.</li>
                            </ul>
                        </div>
                    </div>
                );

            default:
                return null;
        }
    };

    return (
        <div className={styles.wizardOverlay}>
            <div className={styles.wizardContent} style={{ position: 'relative' }}>
                <button
                    onClick={onComplete}
                    style={{ position: 'absolute', top: '1.5rem', right: '1.5rem', background: 'none', border: 'none', color: '#778da9', cursor: 'pointer', zIndex: 10 }}
                    title="Close / Skip Wizard"
                >
                    <X size={24} />
                </button>

                {/* Progress Bar */}
                <div className={styles.wizardProgress}>
                    {WIZARD_STEPS.map((step, index) => (
                        <React.Fragment key={step.id}>
                            <div className={`${styles.wizardStepDot} ${index <= currentStep ? styles.activeDot : ''}`} title={step.title}>
                                {index < currentStep ? <Check size={12} /> : index + 1}
                            </div>
                            {index < WIZARD_STEPS.length - 1 && (
                                <div className={`${styles.wizardStepLine} ${index < currentStep ? styles.activeLine : ''}`} />
                            )}
                        </React.Fragment>
                    ))}
                </div>

                <div className={styles.wizardBody}>
                    {renderStepContent()}
                </div>

                <div className={styles.wizardFooter}>
                    {currentStep > 0 && (
                        <button onClick={handleBack} className={styles.secondaryButton}>
                            <ArrowLeft size={18} /> Back
                        </button>
                    )}

                    {/* Spacer if no back button */}
                    {currentStep === 0 && <div />}

                    <button onClick={handleNext} className={styles.primaryButton}>
                        {currentStep === WIZARD_STEPS.length - 1 ? (
                            <>Finish <Check size={18} /></>
                        ) : (
                            <>Next <ArrowRight size={18} /></>
                        )}
                    </button>
                </div>
            </div>
        </div>
    );
};
