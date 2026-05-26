'use client';

import React, { useState, useEffect } from 'react';
import styles from '@/app/dashboard.module.css';
import { useSettings } from '@/context/SettingsContext';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import { Droplets, AlertCircle, CheckCircle2, RefreshCw, Play, Square, Beaker } from 'lucide-react';

export const WaterChangeScreen: React.FC = () => {
    const { settings } = useSettings();
    const { entities, isConnected, pressButton, turnOffSwitch } = useHomeAssistant();

    const [isTestMode, setIsTestMode] = useState(false);
    const [simulatedWasteLevel, setSimulatedWasteLevel] = useState(0);
    const [simulatedFreshLevel, setSimulatedFreshLevel] = useState(settings.waterChange.containers.freshCapacity || 25);
    const [simulatedTodayVolume, setSimulatedTodayVolume] = useState(0);
    const [isActivatingPreset, setIsActivatingPreset] = useState<string | null>(null);

    const config = settings.waterChange;

    const getEntityState = (entityId: string) => entities?.[entityId]?.state;

    // Actual States from HA
    const actualWasteLevel = parseFloat(getEntityState(config.entities.wasteLevel) || '0');
    const actualFreshLevel = parseFloat(getEntityState(config.entities.freshLevel) || '0');
    const actualWastePump = getEntityState(config.entities.pumpWaste) === 'on';
    const actualFreshPump = getEntityState(config.entities.pumpFresh) === 'on';

    // Simulation logic
    useEffect(() => {
        let interval: ReturnType<typeof setInterval> | undefined;
        let timeout: ReturnType<typeof setTimeout> | undefined;
        if (isTestMode) {
            timeout = setTimeout(() => {
                setSimulatedWasteLevel(0);
                setSimulatedFreshLevel(config.containers.freshCapacity);
            }, 0);

            interval = setInterval(() => {
                setSimulatedWasteLevel(prev => {
                    const next = Math.min(config.containers.wasteCapacity, prev + 0.8);
                    return next;
                });
                setSimulatedFreshLevel(prev => {
                    const next = Math.max(0, prev - 0.8);
                    return next;
                });
                setSimulatedTodayVolume(prev => prev + 0.8);
            }, 1000);
        }
        return () => {
            if (timeout) clearTimeout(timeout);
            if (interval) clearInterval(interval);
        };
    }, [isTestMode, config.containers.freshCapacity, config.containers.wasteCapacity]);

    const wasteLevel = isTestMode ? simulatedWasteLevel : actualWasteLevel;
    const freshLevel = isTestMode ? simulatedFreshLevel : actualFreshLevel;

    const todayTotal = isTestMode ? simulatedTodayVolume : parseFloat(getEntityState(config.entities.todayTotal) || '0');
    const weekTotal = isTestMode ? (simulatedTodayVolume + 15.5) : parseFloat(getEntityState(config.entities.weekTotal) || '0');
    const monthTotal = isTestMode ? (simulatedTodayVolume + 65.2) : parseFloat(getEntityState(config.entities.monthTotal) || '0');

    const wastePercent = Math.min(100, Math.max(0, (wasteLevel / (config.containers.wasteCapacity || 1)) * 100));
    const freshPercent = Math.min(100, Math.max(0, (freshLevel / (config.containers.freshCapacity || 1)) * 100));

    // Derived States (preferred simulated if in test mode, but stop if sensors are critical)
    const isWastePumpRunning = isTestMode ? (wastePercent < 100) : actualWastePump;
    const isFreshPumpRunning = isTestMode ? (freshPercent > 0) : actualFreshPump;

    // Sensor States
    const isWasteFull = isTestMode
        ? wastePercent >= 100
        : getEntityState(config.entities.wasteFull) === 'on' || getEntityState(config.entities.wasteFull) === 'true';
    const isFreshEmpty = isTestMode
        ? freshPercent <= 0
        : getEntityState(config.entities.freshEmpty) === 'on' || getEntityState(config.entities.freshEmpty) === 'true';
    const isTankHigh = getEntityState(config.entities.tankHigh) === 'on' || getEntityState(config.entities.tankHigh) === 'true';

    // Automatic Safety Cutoff Logic
    useEffect(() => {
        const isCritical = isWasteFull || isFreshEmpty || isTankHigh;

        if (isCritical && !isTestMode) {
            // If either pump is running, turn them off
            if (actualWastePump || actualFreshPump) {
                console.log('[AWC Safety] Sensor critical! Emergency pump shutdown triggered.');
                if (actualWastePump) turnOffSwitch(config.entities.pumpWaste);
                if (actualFreshPump) turnOffSwitch(config.entities.pumpFresh);
            }
        }
    }, [isWasteFull, isFreshEmpty, isTankHigh, isTestMode, actualWastePump, actualFreshPump, config.entities.pumpWaste, config.entities.pumpFresh, turnOffSwitch]);

    // Animation classes from dashboard.module.css
    const wastePipeClass = isWastePumpRunning ? styles.awcFlow : '';
    const freshPipeClass = isFreshPumpRunning ? styles.awcFlow : '';

    return (
        <div className={styles.missionControl}>
            <div className={styles.grid}>
                {/* Header Stats */}
                <div className={styles.card} style={{ gridColumn: 'span 1' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <h3 className={styles.sectionSubtitle}>Simulation Controls</h3>
                        <Beaker size={20} color={isTestMode ? "var(--primary-color)" : "#778da9"} />
                    </div>
                    <div style={{ marginTop: '1rem' }}>
                        <button
                            onClick={() => setIsTestMode(!isTestMode)}
                            style={{
                                width: '100%',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                gap: '0.5rem',
                                padding: '0.75rem',
                                borderRadius: '8px',
                                border: 'none',
                                background: isTestMode ? '#ef4444' : 'var(--primary-color)',
                                color: 'white',
                                fontWeight: 700,
                                cursor: 'pointer',
                                transition: 'all 0.2s'
                            }}
                        >
                            {isTestMode ? (
                                <><Square size={16} /> STOP SIMULATION</>
                            ) : (
                                <><Play size={16} /> START SIMULATION</>
                            )}
                        </button>
                    </div>
                </div>

                <div className={styles.card} style={{ gridColumn: 'span 1' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <h3 className={styles.sectionSubtitle}>AWC Configuration</h3>
                        <Droplets size={20} color="var(--primary-color)" />
                    </div>
                    <div style={{ display: 'grid', gap: '1rem', marginTop: '1rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <span style={{ color: '#778da9' }}>Waste Capacity</span>
                            <span style={{ fontWeight: 600 }}>{config.containers.wasteCapacity} L</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <span style={{ color: '#778da9' }}>Fresh Capacity</span>
                            <span style={{ fontWeight: 600 }}>{config.containers.freshCapacity} L</span>
                        </div>
                    </div>
                </div>

                <div className={styles.card} style={{ gridColumn: 'span 1' }}>
                    <h3 className={styles.sectionSubtitle}>Safety Sensors</h3>
                    <div style={{ display: 'grid', gap: '1rem', marginTop: '1rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ color: '#778da9' }}>Waste Tank Full</span>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: isWasteFull ? '#ef4444' : '#4ade80' }}>
                                {isWasteFull ? <AlertCircle size={16} /> : <CheckCircle2 size={16} />}
                                <span style={{ fontWeight: 700, fontSize: '0.85rem' }}>{isWasteFull ? 'CRITICAL (FULL)' : 'GOOD'}</span>
                            </div>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ color: '#778da9' }}>Fresh Tank Empty</span>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: isFreshEmpty ? '#ef4444' : '#4ade80' }}>
                                {isFreshEmpty ? <AlertCircle size={16} /> : <CheckCircle2 size={16} />}
                                <span style={{ fontWeight: 700, fontSize: '0.85rem' }}>{isFreshEmpty ? 'CRITICAL (EMPTY)' : 'GOOD'}</span>
                            </div>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ color: '#778da9' }}>Tank Level High</span>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: isTankHigh ? '#ef4444' : '#4ade80' }}>
                                {isTankHigh ? <AlertCircle size={16} /> : <CheckCircle2 size={16} />}
                                <span style={{ fontWeight: 700, fontSize: '0.85rem' }}>{isTankHigh ? 'CRITICAL (HIGH)' : 'GOOD'}</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div className={styles.card} style={{ gridColumn: 'span 1' }}>
                    <h3 className={styles.sectionSubtitle}>Change Volumes</h3>
                    <div style={{ display: 'grid', gap: '1rem', marginTop: '1rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ color: '#778da9' }}>Changed Today</span>
                            <span style={{ fontWeight: 600, color: 'var(--primary-color)' }}>{todayTotal.toFixed(1)} L</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ color: '#778da9' }}>Changed This Week</span>
                            <span style={{ fontWeight: 600 }}>{weekTotal.toFixed(1)} L</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ color: '#778da9' }}>Changed This Month</span>
                            <span style={{ fontWeight: 600 }}>{monthTotal.toFixed(1)} L</span>
                        </div>
                    </div>
                </div>

                <div className={styles.card} style={{ gridColumn: 'span 2' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                        <h3 className={styles.sectionSubtitle}>Daily Schedule Selection</h3>
                        <Beaker size={20} color="var(--primary-color)" />
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(100px, 1fr))', gap: '1rem' }}>
                        {(config.percentagePresets || []).map(preset => (
                            <button
                                key={preset.id}
                                onClick={async () => {
                                    setIsActivatingPreset(preset.id);
                                    if (isTestMode) {
                                        // Mock activation in simulation: increment based on percentage (assume 250L tank for mockup)
                                        const changeAmount = (preset.percentage / 100) * 250;
                                        setSimulatedTodayVolume(prev => prev + changeAmount);
                                    } else {
                                        await pressButton(preset.entityId);
                                    }
                                    setTimeout(() => setIsActivatingPreset(null), 2000);
                                }}
                                disabled={isActivatingPreset !== null}
                                className={styles.tabItem}
                                style={{
                                    height: '60px',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    justifyContent: 'center',
                                    alignItems: 'center',
                                    gap: '0.25rem',
                                    opacity: isActivatingPreset === preset.id ? 0.7 : 1,
                                    border: isActivatingPreset === preset.id ? '2px solid var(--primary-color)' : '1px solid rgba(255,255,255,0.1)',
                                    background: isActivatingPreset === preset.id ? 'rgba(var(--primary-rgb), 0.1)' : 'rgba(255,255,255,0.03)',
                                    position: 'relative',
                                    overflow: 'hidden'
                                }}
                            >
                                <span style={{ fontSize: '1.2rem', fontWeight: 800, color: 'var(--primary-color)' }}>{preset.label}</span>
                                <span style={{ fontSize: '0.65rem', color: '#778da9', textTransform: 'uppercase', letterSpacing: '1px' }}>Water Change</span>
                                {isActivatingPreset === preset.id && (
                                    <div style={{ position: 'absolute', bottom: 0, left: 0, height: '3px', background: 'var(--primary-color)', animation: 'progress 2s linear forwards' }} />
                                )}
                            </button>
                        ))}
                    </div>
                </div>
            </div>

            {/* Interactive Diagram */}
            <div className={styles.card} style={{ marginTop: '2rem', minHeight: '450px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: 'rgba(13, 27, 42, 0.4)' }}>
                {!isConnected ? (
                    <div style={{ textAlign: 'center', color: '#778da9' }}>
                        <RefreshCw size={48} className={styles.spin} style={{ marginBottom: '1rem' }} />
                        <p>Waiting for Home Assistant connection...</p>
                    </div>
                ) : (
                    <>
                        <svg viewBox="0 0 800 450" style={{ width: '100%', maxWidth: '800px', filter: 'drop-shadow(0 0 10px rgba(0,0,0,0.3))' }}>
                            {/* Definitions for animations */}
                            <defs>
                                <linearGradient id="waterGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                                    <stop offset="0%" stopColor="#00b4d8" stopOpacity="0.8" />
                                    <stop offset="100%" stopColor="#0077b6" stopOpacity="0.9" />
                                </linearGradient>
                                <linearGradient id="wasteGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                                    <stop offset="0%" stopColor="#00b4d8" stopOpacity="0.8" />
                                    <stop offset="100%" stopColor="#0077b6" stopOpacity="0.9" />
                                </linearGradient>
                                <pattern id="wavePattern" x="0" y="0" width="40" height="10" patternUnits="userSpaceOnUse">
                                    <path d="M 0 5 Q 10 0 20 5 T 40 5" fill="none" stroke="white" strokeWidth="1" opacity="0.3" />
                                </pattern>

                                <clipPath id="tankWaterClipMini">
                                    <rect x="5" y="15" width="190" height="130" rx="10" />
                                </clipPath>
                                <clipPath id="wasteClip">
                                    <rect x="2" y={98 - (wastePercent / 100) * 96} width="96" height={(wastePercent / 100) * 96} rx="2" style={{ transition: 'all 0.5s ease' }} />
                                </clipPath>
                                <clipPath id="freshClip">
                                    <rect x="2" y={98 - (freshPercent / 100) * 96} width="96" height={(freshPercent / 100) * 96} rx="2" style={{ transition: 'all 0.5s ease' }} />
                                </clipPath>
                            </defs>

                            {/* Main Pipes (Background) */}
                            <path d="M 300 125 L 150 125 L 150 280" fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="14" strokeLinecap="round" />
                            <path d="M 650 280 L 650 125 L 500 125" fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="14" strokeLinecap="round" />

                            {/* Reef Tank (Main) */}
                            <g transform="translate(300, 50)">
                                <rect x="0" y="0" width="200" height="150" rx="15" fill="rgba(255,255,255,0.02)" stroke="rgba(255,255,255,0.15)" strokeWidth="3" />
                                <rect x="5" y="15" width="190" height="130" fill="url(#waterGradient)" opacity="0.4" rx="10" />
                                <g clipPath="url(#tankWaterClipMini)">
                                    <rect x="-15" y="15" width="230" height="130" fill="url(#wavePattern)" opacity="0.2" className={styles.waterWave} />
                                </g>
                                <text x="100" y="75" textAnchor="middle" fill="rgba(255,255,255,0.6)" fontSize="14" fontWeight="800" style={{ letterSpacing: '2px' }}>REEF TANK</text>

                                {/* Coral shapes */}
                                <path d="M 40 140 Q 50 110 60 140" fill="none" stroke="#ff758c" strokeWidth="6" strokeLinecap="round" opacity="0.6" />
                                <path d="M 140 140 Q 150 120 160 140" fill="none" stroke="#4ade80" strokeWidth="6" strokeLinecap="round" opacity="0.6" />
                            </g>

                            {/* Waste Container */}
                            <g transform="translate(100, 280)">
                                <rect x="0" y="0" width="100" height="100" rx="8" fill="rgba(255,255,255,0.03)" stroke="rgba(255,255,255,0.15)" strokeWidth="2" />
                                {/* Water level */}
                                <rect x="2" y={98 - Math.max(2, (wastePercent / 100) * 96)} width="96" height={Math.max(2, (wastePercent / 100) * 96)} fill="url(#wasteGradient)" opacity="0.8" rx="4" style={{ transition: 'all 0.5s ease' }} />
                                {/* Wave surface effect */}
                                {wastePercent > 2 && (
                                    <g clipPath="url(#wasteClip)">
                                        <rect x="-50" y={95 - (wastePercent / 100) * 96} width="200" height="10" fill="url(#wavePattern)" className={styles.waterWave} />
                                    </g>
                                )}

                                <text x="50" y="-25" textAnchor="middle" fill={isWastePumpRunning ? "#ef4444" : "#778da9"} fontSize="11" fontWeight="900" style={{ transition: 'all 0.3s' }}>
                                    {isWastePumpRunning ? "• EMPTYING TANK" : "WASTE RESERVOIR"}
                                </text>
                                <text x="50" y="45" textAnchor="middle" fill="#fff" fontSize="18" fontWeight="900">{wasteLevel.toFixed(1)}L</text>
                                <text x="50" y="68" textAnchor="middle" fill={isWasteFull ? "#ef4444" : "#00b4d8"} fontSize="14" fontWeight="800">{wastePercent.toFixed(1)}%</text>
                            </g>

                            {/* Fresh Container */}
                            <g transform="translate(600, 280)">
                                <rect x="0" y="0" width="100" height="100" rx="8" fill="rgba(255,255,255,0.03)" stroke="rgba(255,255,255,0.15)" strokeWidth="2" />
                                {/* Water level */}
                                <rect x="2" y={98 - Math.max(2, (freshPercent / 100) * 96)} width="96" height={Math.max(2, (freshPercent / 100) * 96)} fill="url(#waterGradient)" opacity="0.8" rx="4" style={{ transition: 'all 0.5s ease' }} />
                                {/* Wave surface effect */}
                                {freshPercent > 2 && (
                                    <g clipPath="url(#freshClip)">
                                        <rect x="-50" y={95 - (freshPercent / 100) * 96} width="200" height="10" fill="url(#wavePattern)" className={styles.waterWave} />
                                    </g>
                                )}

                                <text x="50" y="-25" textAnchor="middle" fill={isFreshPumpRunning ? "#4ade80" : "#778da9"} fontSize="11" fontWeight="900" style={{ transition: 'all 0.3s' }}>
                                    {isFreshPumpRunning ? "• FILLING TANK" : "FRESH RESERVOIR"}
                                </text>
                                <text x="50" y="45" textAnchor="middle" fill="#fff" fontSize="18" fontWeight="900">{freshLevel.toFixed(1)}L</text>
                                <text x="50" y="68" textAnchor="middle" fill={isFreshEmpty ? "#ef4444" : "#00b4d8"} fontSize="14" fontWeight="800">{freshPercent.toFixed(1)}%</text>
                            </g>

                            {/* Active Flow Pipes */}
                            {isWastePumpRunning && (
                                <path d="M 300 125 L 150 125 L 150 280" className={wastePipeClass} fill="none" stroke="#ef4444" strokeWidth="8" strokeDasharray="14,14" opacity="0.9" />
                            )}
                            {isFreshPumpRunning && (
                                <path d="M 650 280 L 650 125 L 500 125" className={freshPipeClass} fill="none" stroke="#4ade80" strokeWidth="8" strokeDasharray="14,14" opacity="0.9" />
                            )}

                            {/* Pumps visual indicators */}
                            <g transform="translate(210, 110)">
                                <filter id="pumpGlowWaste" x="-50%" y="-50%" width="200%" height="200%">
                                    <feGaussianBlur stdDeviation="3" result="blur" />
                                    <feComposite in="SourceGraphic" in2="blur" operator="over" />
                                </filter>
                                <circle cx="15" cy="15" r="22" fill={isWastePumpRunning ? "rgba(239, 68, 68, 0.2)" : "rgba(255,255,255,0.05)"} stroke={isWastePumpRunning ? "#ef4444" : "rgba(255,255,255,0.1)"} strokeWidth="3" filter={isWastePumpRunning ? "url(#pumpGlowWaste)" : ""} />
                                <RefreshCw size={18} x="6" y="6" className={isWastePumpRunning ? styles.spin : ''} color={isWastePumpRunning ? "#ef4444" : "#778da9"} />
                                <text x="15" y="-12" textAnchor="middle" fill={isWastePumpRunning ? "#ef4444" : "#778da9"} fontSize="10" fontWeight="900">WASTE PUMP</text>
                            </g>

                            <g transform="translate(560, 110)">
                                <filter id="pumpGlowFresh" x="-50%" y="-50%" width="200%" height="200%">
                                    <feGaussianBlur stdDeviation="3" result="blur" />
                                    <feComposite in="SourceGraphic" in2="blur" operator="over" />
                                </filter>
                                <circle cx="15" cy="15" r="22" fill={isFreshPumpRunning ? "rgba(74, 222, 128, 0.2)" : "rgba(255,255,255,0.05)"} stroke={isFreshPumpRunning ? "#4ade80" : "rgba(255,255,255,0.1)"} strokeWidth="3" filter={isFreshPumpRunning ? "url(#pumpGlowFresh)" : ""} />
                                <RefreshCw size={18} x="6" y="6" className={isFreshPumpRunning ? styles.spin : ''} color={isFreshPumpRunning ? "#4ade80" : "#778da9"} />
                                <text x="15" y="-12" textAnchor="middle" fill={isFreshPumpRunning ? "#4ade80" : "#778da9"} fontSize="10" fontWeight="900">FRESH PUMP</text>
                            </g>
                        </svg>

                        <div style={{ display: 'flex', gap: '3rem', marginTop: '2rem', padding: '1rem', background: 'rgba(255,255,255,0.02)', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.05)' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                                <div style={{
                                    width: '12px',
                                    height: '12px',
                                    borderRadius: '50%',
                                    background: isWastePumpRunning ? '#ef4444' : '#1b263b',
                                    boxShadow: isWastePumpRunning ? '0 0 10px #ef4444' : 'none'
                                }} />
                                <span style={{ fontSize: '0.85rem', fontWeight: 600, color: isWastePumpRunning ? '#ef4444' : '#778da9' }}>WASTE: {isWastePumpRunning ? 'RUNNING' : 'STANDBY'}</span>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                                <div style={{
                                    width: '12px',
                                    height: '12px',
                                    borderRadius: '50%',
                                    background: isFreshPumpRunning ? '#4ade80' : '#1b263b',
                                    boxShadow: isFreshPumpRunning ? '0 0 10px #4ade80' : 'none'
                                }} />
                                <span style={{ fontSize: '0.85rem', fontWeight: 600, color: isFreshPumpRunning ? '#4ade80' : '#778da9' }}>FRESH: {isFreshPumpRunning ? 'RUNNING' : 'STANDBY'}</span>
                            </div>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
};
