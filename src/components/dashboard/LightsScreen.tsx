'use client';

import React, { useState, useMemo } from 'react';
import styles from '@/app/dashboard.module.css';
import { useSettings } from '@/context/SettingsContext';
import type { AppSettings } from '@/context/SettingsContext';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import {
    Sun,
    Moon,
    Wind,
    Lightbulb,
    Camera,
    Zap,
    Clock,
    Settings,
    RefreshCw,
    Sparkles,
    Waves
} from 'lucide-react';

type LightingChannel = keyof AppSettings['lighting']['channels'];

export const LightsScreen = () => {
    const { settings } = useSettings();
    const { entities, callService } = useHomeAssistant();
    const [previewTime, setPreviewTime] = useState('14:00');
    const [isPreviewActive, setIsPreviewActive] = useState(false);
    const [localChannels, setLocalChannels] = useState<Partial<Record<LightingChannel, number>>>({});

    // Get current light states from HA or default to local
    const haChannels = useMemo<Record<LightingChannel, number>>(() => {
        const values = Object.keys(settings.lighting.channels).reduce((acc, key) => ({ ...acc, [key]: 0 }), {} as Record<LightingChannel, number>);
        if (!entities) return values;

        Object.entries(settings.lighting.channels).forEach(([key, entityId]) => {
            const state = entities[entityId]?.state;
            if (state && !isNaN(parseFloat(state))) {
                values[key as LightingChannel] = parseFloat(state);
            }
        });
        return values;
    }, [entities, settings.lighting.channels]);

    const channelValues = useMemo(
        () => ({ ...haChannels, ...localChannels }),
        [haChannels, localChannels],
    );

    const handleChannelChange = (channel: LightingChannel, value: number) => {
        setLocalChannels(prev => ({ ...prev, [channel]: value }));
        const entityId = settings.lighting.channels[channel];
        if (entityId) {
            callService('number', 'set_value', { entity_id: entityId, value });
        }
    };

    const applyPreset = (presetId: string) => {
        const preset = settings.lighting.presets.find(p => p.id === presetId);
        if (preset) {
            setLocalChannels(preset.values as Partial<Record<LightingChannel, number>>);
            Object.entries(preset.values).forEach(([key, value]) => {
                const entityId = settings.lighting.channels[key as LightingChannel];
                if (entityId) {
                    callService('number', 'set_value', { entity_id: entityId, value });
                }
            });
        }
    };

    const channelsConfig: Array<{ key: LightingChannel; label: string; color: string; icon: React.ReactNode }> = [
        { key: 'white', label: 'White', color: '#ffffff', icon: <Sun size={18} /> },
        { key: 'blue', label: 'Blue', color: '#00b4d8', icon: <Waves size={18} /> },
        { key: 'royalBlue', label: 'Royal', color: '#0077b6', icon: <Waves size={18} /> },
        { key: 'violet', label: 'Violet', color: '#7b2cbf', icon: <Sparkles size={18} /> },
        { key: 'uv', label: 'UV', color: '#3c096c', icon: <Sparkles size={18} /> },
        { key: 'red', label: 'Red', color: '#e63946', icon: <Zap size={18} /> },
        { key: 'green', label: 'Green', color: '#2a9d8f', icon: <Wind size={18} /> },
        { key: 'moonlight', label: 'Moon', color: '#edf2f4', icon: <Moon size={18} /> },
    ];

    // SVG Spectrum Visualization
    const spectrumGradient = useMemo(() => {
        const totalIntensity = Object.values(channelValues).reduce((a, b) => a + b, 0);
        if (totalIntensity === 0) return 'rgba(0,0,0,0.2)';

        // Simple blend for visual effect
        let r = 0, g = 0, b = 0, v = 0;
        r += channelValues.white * 0.5 + channelValues.red + channelValues.violet * 0.2;
        g += channelValues.white * 0.5 + channelValues.green;
        b += channelValues.blue + channelValues.royalBlue + channelValues.violet * 0.5 + channelValues.uv * 0.3;
        v += channelValues.violet + channelValues.uv;

        const max = Math.max(r, g, b, v, 1);
        return `rgba(${Math.min(255, (r / max) * 255)}, ${Math.min(255, (g / max) * 255)}, ${Math.min(255, (b / max) * 255)}, 0.6)`;
    }, [channelValues]);

    return (
        <div className={styles.lightsContainer}>
            <div className={styles.lightsHeader}>
                <div className={styles.lightStatus}>
                    <div className={styles.spectrumPreview} style={{
                        boxShadow: `0 0 40px ${spectrumGradient}`,
                        background: `radial-gradient(circle at center, ${spectrumGradient}, transparent)`
                    }}>
                        <Lightbulb size={40} color={spectrumGradient === 'rgba(0,0,0,0.2)' ? '#444' : '#fff'} />
                    </div>
                    <div>
                        <h2 className={styles.sectionTitle}>Light Control</h2>
                        <p className={styles.sectionSubtitle}>Spectrum & Schedule Management</p>
                    </div>
                </div>

                <div className={styles.presetsBar}>
                    {settings.lighting.presets.map(preset => (
                        <button
                            key={preset.id}
                            className={styles.presetButton}
                            onClick={() => applyPreset(preset.id)}
                        >
                            {preset.id === 'photo' ? <Camera size={14} /> : <Sparkles size={14} />}
                            {preset.name}
                        </button>
                    ))}
                    <button className={styles.presetButton} style={{ borderColor: '#ef4444', color: '#ef4444' }}>
                        <Zap size={14} />
                        Full Spectrum
                    </button>
                </div>
            </div>

            <div className={styles.lightsGrid}>
                {/* Spectrum Mixer */}
                <section className={styles.mixerSection}>
                    <h3 className={styles.cardTitle}>Spectrum Mixer</h3>
                    <div className={styles.mixerGrid}>
                        {channelsConfig.map(ch => (
                            <div key={ch.key} className={styles.sliderContainer}>
                                <div className={styles.sliderLabel}>
                                    {ch.icon}
                                    <span>{ch.label}</span>
                                </div>
                                <div className={styles.verticalSliderWrapper}>
                                    <input
                                        type="range"
                                        min="0"
                                        max="100"
                                        value={channelValues[ch.key] || 0}
                                        onChange={(e) => handleChannelChange(ch.key, parseInt(e.target.value))}
                                        className={styles.verticalSlider}
                                        style={{ '--track-color': ch.color } as React.CSSProperties}
                                    />
                                    <div className={styles.sliderValue}>{Math.round(channelValues[ch.key] || 0)}%</div>
                                </div>
                            </div>
                        ))}
                    </div>
                </section>

                {/* Daylight Cycle */}
                <section className={styles.cycleSection}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
                        <h3 className={styles.cardTitle}>Daylight Cycle</h3>
                        <div className={styles.cycleActions}>
                            <button className={styles.iconButton} title="Cloud Simulation"><Wind size={16} /></button>
                            <button className={styles.iconButton} title="Lunar Cycle"><Moon size={16} /></button>
                            <button className={styles.iconButton} title="Sync All"><RefreshCw size={16} /></button>
                        </div>
                    </div>

                    <div className={styles.cycleVisualizer}>
                        <svg viewBox="0 0 800 200" className={styles.cycleSvg}>
                            <defs>
                                <linearGradient id="curveGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                                    <stop offset="0%" stopColor="var(--primary-color)" stopOpacity="0.4" />
                                    <stop offset="100%" stopColor="var(--primary-color)" stopOpacity="0" />
                                </linearGradient>
                            </defs>

                            {/* Grid Lines */}
                            <line x1="0" y1="180" x2="800" y2="180" stroke="#27272a" strokeWidth="1" />
                            {[0, 4, 8, 12, 16, 20, 24].map(h => (
                                <text key={h} x={(h / 24) * 800} y="195" fontSize="10" fill="#778da9" textAnchor="middle">{h}:00</text>
                            ))}

                            {/* Intensity Curve */}
                            <path
                                d="M 0 180 Q 200 180 333 100 T 466 50 T 600 150 T 800 180"
                                fill="url(#curveGradient)"
                                stroke="var(--primary-color)"
                                strokeWidth="3"
                                strokeLinecap="round"
                            />

                            {/* Preview Marker */}
                            <line
                                x1={(parseInt(previewTime.split(':')[0]) / 24) * 800}
                                y1="0"
                                x2={(parseInt(previewTime.split(':')[0]) / 24) * 800}
                                y2="180"
                                stroke="#fff"
                                strokeWidth="2"
                                strokeDasharray="4 2"
                            />
                        </svg>
                    </div>

                    <div className={styles.previewControls}>
                        <div className={styles.previewLabel}>
                            <Clock size={16} />
                            <span>Preview Time: {previewTime}</span>
                        </div>
                        <input
                            type="range"
                            min="0"
                            max="1439"
                            value={parseInt(previewTime.split(':')[0]) * 60 + parseInt(previewTime.split(':')[1])}
                            onChange={(e) => {
                                const totalMinutes = parseInt(e.target.value);
                                const h = Math.floor(totalMinutes / 60);
                                const m = totalMinutes % 60;
                                setPreviewTime(`${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`);
                            }}
                            className={styles.horizontalSlider}
                        />
                        <button
                            className={`${styles.previewToggle} ${isPreviewActive ? styles.active : ''}`}
                            onClick={() => setIsPreviewActive(!isPreviewActive)}
                        >
                            {isPreviewActive ? 'Stop Preview' : 'Run Preview Cycle'}
                        </button>
                    </div>

                    <div className={styles.scheduleList}>
                        {settings.lighting.schedule.map((slot, idx) => (
                            <div key={idx} className={styles.scheduleItem}>
                                <div className={styles.slotTime}>{slot.time}</div>
                                <div className={styles.slotValues}>
                                    <div className={styles.miniBar} style={{ height: `${slot.values.white}%`, background: '#fff' }} />
                                    <div className={styles.miniBar} style={{ height: `${slot.values.blue}%`, background: '#00b4d8' }} />
                                    <div className={styles.miniBar} style={{ height: `${slot.values.royalBlue}%`, background: '#0077b6' }} />
                                </div>
                                <button className={styles.smallIconButton}><Settings size={12} /></button>
                            </div>
                        ))}
                    </div>
                </section>
            </div>
        </div>
    );
};
