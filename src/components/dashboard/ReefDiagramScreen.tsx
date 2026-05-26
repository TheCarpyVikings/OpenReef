'use client';

import React, { useMemo } from 'react';
import styles from '@/app/dashboard.module.css';
import { useSettings } from '@/context/SettingsContext';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import { RefreshCw, Zap } from 'lucide-react';

type EquipmentIconProps = React.SVGProps<SVGSVGElement> & {
    type: string;
    size?: number;
};

const EquipmentIcon = ({ type, size = 20, ...props }: EquipmentIconProps) => {
    const label = type.toLowerCase();

    // Custom SVG paths for better hardware representation
    if (label.includes('skimmer')) {
        return (
            <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
                <rect x="7" y="2" width="10" height="4" rx="1" /> {/* Collection Cup */}
                <path d="M6 6h12v12a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V6z" /> {/* Body */}
                <circle cx="12" cy="12" r="1" fill="currentColor" opacity="0.5" />
                <circle cx="10" cy="15" r="0.8" fill="currentColor" opacity="0.4" />
                <circle cx="14" cy="9" r="0.6" fill="currentColor" opacity="0.6" />
            </svg>
        );
    }

    if (label.includes('return') || (label.includes('pump') && !label.includes('wave') && !label.includes('dosing'))) {
        return (
            <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
                <rect x="4" y="10" width="12" height="10" rx="1" /> {/* Pump base */}
                <circle cx="10" cy="15" r="4" /> {/* Volute */}
                <path d="M14 15h6v-5h-2" /> {/* Outlet pipe */}
                <line x1="8" x2="12" y1="15" y2="15" opacity="0.5" />
                <line x1="10" x2="10" y1="13" y2="17" opacity="0.5" />
            </svg>
        );
    }

    if (label.includes('wave') || label.includes('mp40') || label.includes('nero')) {
        return (
            <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
                <circle cx="12" cy="12" r="9" /> {/* Housing */}
                <path d="M12 7v10M7 12h10" opacity="0.2" /> {/* Support */}
                <path d="M12 12l4-4M12 12l-4 4M12 12l4 4M12 12l-4-4" strokeWidth="2" /> {/* Propeller */}
            </svg>
        );
    }

    if (label.includes('kessil')) {
        return (
            <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
                <path d="M6 4h12l1 4H5l1-4z" /> {/* Top cap */}
                <path d="M5 8h14v2c0 4-3 7-7 7s-7-3-7-7V8z" /> {/* Pendent body */}
                <circle cx="12" cy="12" r="3" opacity="0.3" fill="currentColor" />
            </svg>
        );
    }

    if (label.includes('light') || label.includes('edge') || label.includes('hydra') || label.includes('radion')) {
        return (
            <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
                <rect x="4" y="8" width="16" height="8" rx="2" /> {/* Sleek light body */}
                <circle cx="8" cy="12" r="1.5" fill="currentColor" />
                <circle cx="12" cy="12" r="1.5" fill="currentColor" />
                <circle cx="16" cy="12" r="1.5" fill="currentColor" />
            </svg>
        );
    }

    if (label.includes('heater') || label.includes('inkbird')) {
        return (
            <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
                <rect x="9" y="2" width="6" height="20" rx="3" /> {/* Tube */}
                <path d="M11 6h2M11 9h2M11 12h2M11 15h2" opacity="0.5" /> {/* Element */}
                <rect x="10" y="3" width="4" height="2" fill="currentColor" opacity="0.3" />
            </svg>
        );
    }

    if (label.includes('dosing')) {
        return (
            <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
                <circle cx="12" cy="12" r="8" /> {/* Head */}
                <circle cx="12" cy="8" r="1.5" fill="currentColor" /> {/* Rollers */}
                <circle cx="12" cy="16" r="1.5" fill="currentColor" />
                <path d="M6 12h2M16 12h2" opacity="0.5" />
            </svg>
        );
    }

    if (label.includes('fan')) {
        return (
            <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
                <rect x="4" y="4" width="16" height="16" rx="2" /> {/* Frame */}
                <path d="M12 12 L16 8 M12 12 L16 16 M12 12 L8 16 M12 12 L8 8" strokeWidth="2.5" /> {/* Blades */}
                <circle cx="12" cy="12" r="2" fill="currentColor" />
            </svg>
        );
    }

    if (label.includes('ato')) {
        return (
            <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
                <rect x="6" y="10" width="12" height="10" rx="1" /> {/* Small pump */}
                <path d="M12 10V4h4" /> {/* Tubing */}
                <circle cx="12" cy="15" r="2" opacity="0.5" />
            </svg>
        );
    }

    return <Zap size={size} {...props} />;
};

export const ReefDiagramScreen: React.FC = () => {
    const { settings, getEquipmentName } = useSettings();
    const { entities, isConnected, toggleSwitch } = useHomeAssistant();

    const diagramEquipment = useMemo(() => {
        if (!entities) return [];
        return Object.entries(settings.entities.equipment)
            .filter(([, config]) => config.showInDiagram)
            .map(([key, config]) => ({
                key,
                name: getEquipmentName(key, key),
                state: entities[config.switch]?.state || 'unknown',
                position: config.diagramPosition || 'room',
                config
            }));
    }, [settings.entities.equipment, entities, getEquipmentName]);

    const isReturnRunning = entities && entities[settings.entities.equipment['RETURN_PUMP']?.switch]?.state === 'on';
    const areWavemakersRunning = entities && entities[settings.entities.equipment['WAVEMAKERS']?.switch]?.state === 'on';
    const isATORunning = entities && entities[settings.entities.equipment['ATO']?.switch]?.state === 'on';
    const hasTankAgitation = isReturnRunning || areWavemakersRunning;

    return (
        <div className={styles.settingsSection}>
            <div className={styles.card} style={{ minHeight: '600px', display: 'flex', flexDirection: 'column', background: 'rgba(13, 27, 42, 0.4)', padding: '2rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
                    <h2 className={styles.sectionTitle} style={{ margin: 0 }}>Interactive Reef System</h2>
                    <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.8rem', color: '#778da9' }}>
                            <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#4ade80', boxShadow: '0 0 5px #4ade80' }} />
                            <span>Running</span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.8rem', color: '#778da9' }}>
                            <div style={{ width: 10, height: 10, borderRadius: '50%', background: 'rgba(255,255,255,0.1)' }} />
                            <span>Standby</span>
                        </div>
                    </div>
                </div>

                {!isConnected ? (
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#778da9' }}>
                        <RefreshCw size={48} className={styles.spinning} style={{ marginBottom: '1rem' }} />
                        <p>Connecting to system...</p>
                    </div>
                ) : (
                    <svg viewBox="0 -60 850 660" style={{ width: '100%', height: 'auto', filter: 'drop-shadow(0 0 15px rgba(0,0,0,0.4))' }}>
                        <defs>
                            <linearGradient id="tankWater" x1="0%" y1="0%" x2="0%" y2="100%">
                                <stop offset="0%" stopColor="#00b4d8" stopOpacity="0.4" />
                                <stop offset="100%" stopColor="#0077b6" stopOpacity="0.6" />
                            </linearGradient>
                            <linearGradient id="sumpWater" x1="0%" y1="0%" x2="0%" y2="100%">
                                <stop offset="0%" stopColor="#00b4d8" stopOpacity="0.3" />
                                <stop offset="100%" stopColor="#0077b6" stopOpacity="0.5" />
                            </linearGradient>
                            <linearGradient id="freshWater" x1="0%" y1="0%" x2="0%" y2="100%">
                                <stop offset="0%" stopColor="#90e0ef" stopOpacity="0.5" />
                                <stop offset="100%" stopColor="#00b4d8" stopOpacity="0.7" />
                            </linearGradient>
                            <linearGradient id="dosingLiquid" x1="0%" y1="0%" x2="0%" y2="100%">
                                <stop offset="0%" stopColor="#fbbf24" stopOpacity="0.4" />
                                <stop offset="100%" stopColor="#d97706" stopOpacity="0.6" />
                            </linearGradient>
                            <pattern id="wavePattern" x="0" y="0" width="40" height="10" patternUnits="userSpaceOnUse">
                                <path d="M 0 5 Q 10 0 20 5 T 40 5" fill="none" stroke="white" strokeWidth="1" opacity="0.2" />
                            </pattern>
                            <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
                                <feGaussianBlur stdDeviation="3" result="blur" />
                                <feComposite in="SourceGraphic" in2="blur" operator="over" />
                            </filter>
                            <clipPath id="tankWaterClip">
                                <rect x="5" y="15" width="410" height="200" rx="10" />
                            </clipPath>
                            <clipPath id="sumpWaterClip">
                                <rect x="5" y="30" width="370" height="115" rx="8" />
                            </clipPath>
                        </defs>



                        {/* Main Tank */}
                        <g transform="translate(250, 0)">
                            <rect width="420" height="220" rx="15" fill="rgba(255,255,255,0.02)" stroke="rgba(255,255,255,0.1)" strokeWidth="3" />
                            <rect x="5" y="15" width="410" height="200" rx="10" fill="url(#tankWater)" />
                            <g clipPath="url(#tankWaterClip)">
                                <rect x="-15" y="15" width="450" height="200" fill="url(#wavePattern)" className={hasTankAgitation ? styles.waterWave : ''} opacity={hasTankAgitation ? 1 : 0.3} />
                            </g>

                            {/* Corals/Rockwork placeholder */}
                            <path d="M 50 205 Q 100 120 150 205 M 150 205 Q 200 140 250 205 M 250 205 Q 320 110 380 205" fill="rgba(255,255,255,0.05)" stroke="rgba(255,255,255,0.1)" strokeWidth="2" />

                            <text x="210" y="110" textAnchor="middle" fill="rgba(255,255,255,0.2)" fontSize="24" fontWeight="900" style={{ letterSpacing: '8px' }}>DISPLAY TANK</text>

                            {/* Equipment Positioning: Light (Above Tank) */}
                            {diagramEquipment.filter(e => e.position === 'light').map((e, i) => {
                                const lightCount = diagramEquipment.filter(e => e.position === 'light').length;
                                const spacing = 420 / (lightCount + 1);
                                const x = spacing * (i + 1);
                                const y = -25;
                                const isOn = e.state === 'on';
                                return (
                                    <g
                                        key={e.key}
                                        transform={`translate(${x}, ${y})`}
                                        onClick={() => toggleSwitch(e.config.switch)}
                                        style={{ cursor: 'pointer' }}
                                    >
                                        <g className={styles.clickableIcon}>
                                            {/* Hit Area */}
                                            <circle r="22" fill="transparent" />

                                            {/* Light Beam Effect */}
                                            {isOn && (
                                                <path
                                                    d={`M -20 20 L -60 200 L 60 200 L 20 20 Z`}
                                                    fill="url(#tankWater)"
                                                    opacity="0.15"
                                                    filter="url(#glow)"
                                                >
                                                    <animate attributeName="opacity" values="0.1;0.2;0.1" dur="4s" repeatCount="indefinite" />
                                                </path>
                                            )}
                                            {/* Light Unit */}
                                            <rect x="-25" y="-5" width="50" height="15" rx="4" fill="rgba(255,255,255,0.05)" stroke={isOn ? "#4ade80" : "rgba(255,255,255,0.1)"} strokeWidth="1" />
                                            <foreignObject x="-18" y="-18" width="36" height="36" style={{ pointerEvents: 'none' }}>
                                                <div style={{ color: isOn ? '#4ade80' : '#778da9', display: 'flex', justifyContent: 'center', alignItems: 'center', width: '100%', height: '100%' }}>
                                                    <EquipmentIcon type={e.name} size={36} />
                                                </div>
                                            </foreignObject>
                                        </g>
                                        <text y="-25" textAnchor="middle" fill="#778da9" fontSize="7" fontWeight="700">{e.name.toUpperCase()}</text>
                                    </g>
                                );
                            })}

                            {/* Equipment in Tank */}
                            {diagramEquipment.filter(e => e.position === 'tank').map((e, i) => {
                                const x = 50 + (i * 70);
                                const y = 50;
                                const isOn = e.state === 'on';
                                return (
                                    <g
                                        key={e.key}
                                        transform={`translate(${x}, ${y})`}
                                        onClick={() => toggleSwitch(e.config.switch)}
                                        style={{ cursor: 'pointer' }}
                                    >
                                        <g className={styles.clickableIcon}>
                                            <circle r="25" fill="transparent" />
                                            <foreignObject x="-20" y="-20" width="40" height="40" style={{ pointerEvents: 'none' }}>
                                                <div style={{ color: isOn ? '#4ade80' : '#778da9', display: 'flex', justifyContent: 'center', alignItems: 'center', width: '100%', height: '100%' }}>
                                                    <EquipmentIcon type={e.name} size={40} />
                                                </div>
                                            </foreignObject>
                                        </g>
                                        <text y="30" textAnchor="middle" fill="#778da9" fontSize="7" fontWeight="700">{e.name.toUpperCase()}</text>
                                    </g>
                                );
                            })}
                        </g>

                        {/* Dosing Container */}
                        {(() => {
                            const dosingPumps = diagramEquipment.filter(e => e.position === 'dosing_container');
                            const visiblePumps = dosingPumps.filter(e => e.config.showInDiagram !== false);
                            if (visiblePumps.length === 0) return null;

                            return (
                                <g transform="translate(65, 380)">
                                    <rect width="80" height="150" rx="4" fill="rgba(255,255,255,0.03)" stroke="rgba(255,255,255,0.1)" strokeWidth="2" />
                                    <rect x="5" y="60" width="70" height="85" rx="2" fill="url(#dosingLiquid)" />
                                    <text x="40" y="25" textAnchor="middle" fill="rgba(255,255,255,0.2)" fontSize="10" fontWeight="900">DOSING</text>

                                    {visiblePumps.map((e, i) => {
                                        const isDosingPump = e.name.toLowerCase().includes('dose') || e.name.toLowerCase().includes('dosing') || e.key.toLowerCase().includes('pump');
                                        const x = 40;
                                        // Put dosing pumps ABOVE the container (y is relative to translate(65, 380))
                                        const y = isDosingPump ? -50 : 65 + (i * 35);
                                        const isOn = e.state === 'on';
                                        return (
                                            <g
                                                key={e.key}
                                                transform={`translate(${x}, ${y})`}
                                                onClick={() => toggleSwitch(e.config.switch)}
                                                style={{ cursor: 'pointer' }}
                                            >
                                                <g className={styles.clickableIcon}>
                                                    <circle r="20" fill="transparent" />
                                                    <foreignObject x="-15" y="-15" width="30" height="30" style={{ pointerEvents: 'none' }}>
                                                        <div style={{ color: isOn ? '#fbbf24' : '#778da9', display: 'flex', justifyContent: 'center', alignItems: 'center', width: '100%', height: '100%' }}>
                                                            <EquipmentIcon type={e.name} size={30} />
                                                        </div>
                                                    </foreignObject>
                                                </g>
                                                <text y={isDosingPump ? -20 : 22} textAnchor="middle" fill="#778da9" fontSize="7" fontWeight="700">{e.name.toUpperCase()}</text>
                                            </g>
                                        );
                                    })}
                                </g>
                            );
                        })()}

                        {/* ATO Reservoir */}
                        <g transform="translate(155, 380)">
                            <rect width="80" height="150" rx="4" fill="rgba(255,255,255,0.03)" stroke="rgba(255,255,255,0.1)" strokeWidth="2" />
                            <rect x="5" y="40" width="70" height="105" rx="2" fill="url(#freshWater)" />
                            <text x="40" y="25" textAnchor="middle" fill="rgba(255,255,255,0.2)" fontSize="10" fontWeight="900">ATO</text>

                            {/* Freshwater Patterns/Glow */}
                            <rect x="5" y="40" width="70" height="105" rx="2" fill="url(#wavePattern)" opacity="0.1" />

                            {/* Equipment in ATO Reservoir */}
                            {diagramEquipment.filter(e => e.position === 'ato_reservoir' && e.config.showInDiagram !== false).map((e, i) => {
                                const isAtoPump = e.name.toLowerCase().includes('ato') || e.key.toLowerCase().includes('pump');
                                // If it's the ATO pump, put it at the bottom. Otherwise space them out.
                                const x = 40;
                                const y = isAtoPump ? 115 : 65 + (i * 35);
                                const isOn = e.state === 'on';
                                return (
                                    <g
                                        key={e.key}
                                        transform={`translate(${x}, ${y})`}
                                        onClick={() => toggleSwitch(e.config.switch)}
                                        style={{ cursor: 'pointer' }}
                                    >
                                        <foreignObject x="-15" y="-15" width="30" height="30" style={{ pointerEvents: 'none' }}>
                                            <div style={{ color: isOn ? '#4ade80' : '#778da9', display: 'flex', justifyContent: 'center', alignItems: 'center', width: '100%', height: '100%' }}>
                                                <EquipmentIcon type={e.name} size={30} />
                                            </div>
                                        </foreignObject>
                                        <text y="22" textAnchor="middle" fill="#778da9" fontSize="7" fontWeight="700">{e.name.toUpperCase()}</text>
                                    </g>
                                );
                            })}
                        </g>

                        {/* AWC Waste Container - Swapped to be next to Sump */}
                        {settings.waterChange.entities.pumpWasteShowInDiagram && (
                            <g transform="translate(640, 380)">
                                <rect width="80" height="150" rx="4" fill="rgba(255,255,255,0.03)" stroke="rgba(255,255,255,0.1)" strokeWidth="2" />
                                <rect x="5" y="60" width="70" height="85" rx="2" fill="url(#dosingLiquid)" opacity="0.6" />
                                <text x="40" y="25" textAnchor="middle" fill="rgba(255,255,255,0.2)" fontSize="10" fontWeight="900">WASTE</text>

                                {/* Waste Pump (Inline) */}
                                {(() => {
                                    const isOn = entities?.[settings.waterChange.entities.pumpWaste]?.state === 'on';
                                    return (
                                        <g transform="translate(40, -50)"
                                            onClick={() => toggleSwitch(settings.waterChange.entities.pumpWaste)}
                                            style={{ cursor: 'pointer' }}>
                                            <g className={styles.clickableIcon}>
                                                <circle r="20" fill="transparent" />
                                                <foreignObject x="-15" y="-15" width="30" height="30" style={{ pointerEvents: 'none' }}>
                                                    <div style={{ color: isOn ? '#f87171' : '#778da9', display: 'flex', justifyContent: 'center', alignItems: 'center', width: '100%', height: '100%' }}>
                                                        <EquipmentIcon type="dosing" size={30} />
                                                    </div>
                                                </foreignObject>
                                            </g>
                                            <text y="-20" textAnchor="middle" fill="#778da9" fontSize="7" fontWeight="700">AWC WASTE</text>
                                        </g>
                                    );
                                })()}
                            </g>
                        )}

                        {/* AWC Fresh Reservoir - Swapped to Far Right */}
                        {settings.waterChange.entities.pumpFreshShowInDiagram && (
                            <g transform="translate(730, 380)">
                                <rect width="80" height="150" rx="4" fill="rgba(255,255,255,0.03)" stroke="rgba(255,255,255,0.1)" strokeWidth="2" />
                                <rect x="5" y="40" width="70" height="105" rx="2" fill="url(#freshWater)" />
                                <text x="40" y="25" textAnchor="middle" fill="rgba(255,255,255,0.2)" fontSize="10" fontWeight="900">FRESH SW</text>

                                {/* Fresh Pump (Inline) */}
                                {(() => {
                                    const isOn = entities?.[settings.waterChange.entities.pumpFresh]?.state === 'on';
                                    return (
                                        <g transform="translate(40, -80)"
                                            onClick={() => toggleSwitch(settings.waterChange.entities.pumpFresh)}
                                            style={{ cursor: 'pointer' }}>
                                            <g className={styles.clickableIcon}>
                                                <circle r="20" fill="transparent" />
                                                <foreignObject x="-15" y="-15" width="30" height="30" style={{ pointerEvents: 'none' }}>
                                                    <div style={{ color: isOn ? '#4ade80' : '#778da9', display: 'flex', justifyContent: 'center', alignItems: 'center', width: '100%', height: '100%' }}>
                                                        <EquipmentIcon type="dosing" size={30} />
                                                    </div>
                                                </foreignObject>
                                            </g>
                                            <text y="-20" textAnchor="middle" fill="#778da9" fontSize="7" fontWeight="700">AWC FRESH</text>
                                        </g>
                                    );
                                })()}
                            </g>
                        )}

                        {/* Sump */}
                        <g transform="translate(250, 380)">
                            <rect width="380" height="150" rx="10" fill="rgba(255,255,255,0.02)" stroke="rgba(255,255,255,0.1)" strokeWidth="2" />
                            <rect x="5" y="30" width="370" height="115" rx="8" fill="url(#sumpWater)" />
                            <g clipPath="url(#sumpWaterClip)">
                                <rect x="-15" y="30" width="410" height="115" fill="url(#wavePattern)" className={isReturnRunning ? styles.waterWave : ''} opacity={isReturnRunning ? 1 : 0.3} />
                            </g>

                            {/* Baffles */}
                            <line x1="120" y1="30" x2="120" y2="145" stroke="rgba(255,255,255,0.1)" strokeWidth="2" />
                            <line x1="135" y1="5" x2="135" y2="120" stroke="rgba(255,255,255,0.1)" strokeWidth="2" />
                            <line x1="260" y1="30" x2="260" y2="145" stroke="rgba(255,255,255,0.1)" strokeWidth="2" />

                            <text x="190" y="90" textAnchor="middle" fill="rgba(255,255,255,0.1)" fontSize="18" fontWeight="900" style={{ letterSpacing: '4px' }}>SUMP</text>

                            {/* Specifically Placed Return Pump & Inkbird (Return Chamber) */}
                            {(() => {
                                const rp = diagramEquipment.find(e => e.key.toUpperCase() === 'RETURN_PUMP');
                                const inkbird = diagramEquipment.find(e => e.key.toUpperCase() === 'INKBIRD' || e.name.toLowerCase().includes('inkbird'));
                                return (
                                    <>
                                        {rp && (
                                            <g
                                                transform="translate(40, 115)"
                                                onClick={() => toggleSwitch(rp.config.switch)}
                                                style={{ cursor: 'pointer' }}
                                            >
                                                <g className={styles.clickableIcon}>
                                                    <circle r="25" fill="transparent" />
                                                    <foreignObject x="-20" y="-20" width="40" height="40" style={{ pointerEvents: 'none' }}>
                                                        <div style={{ color: rp.state === 'on' ? '#4ade80' : '#778da9', display: 'flex', justifyContent: 'center', alignItems: 'center', width: '100%', height: '100%' }}>
                                                            <EquipmentIcon type={rp.name} size={40} />
                                                        </div>
                                                    </foreignObject>
                                                </g>
                                                <text y="30" textAnchor="middle" fill="#778da9" fontSize="7" fontWeight="700">{rp.name.toUpperCase()}</text>
                                            </g>
                                        )}
                                        {inkbird && (
                                            <g
                                                transform="translate(85, 115)"
                                                onClick={() => toggleSwitch(inkbird.config.switch)}
                                                style={{ cursor: 'pointer' }}
                                            >
                                                <g className={styles.clickableIcon}>
                                                    <circle r="25" fill="transparent" />
                                                    <foreignObject x="-20" y="-20" width="40" height="40" style={{ pointerEvents: 'none' }}>
                                                        <div style={{ color: inkbird.state === 'on' ? '#4ade80' : '#778da9', display: 'flex', justifyContent: 'center', alignItems: 'center', width: '100%', height: '100%' }}>
                                                            <EquipmentIcon type={inkbird.name} size={40} />
                                                        </div>
                                                    </foreignObject>
                                                </g>
                                                <text y="30" textAnchor="middle" fill="#778da9" fontSize="7" fontWeight="700">{inkbird.name.toUpperCase()}</text>
                                            </g>
                                        )}
                                    </>
                                );
                            })()}

                            {/* Specifically Placed Skimmer (Middle Chamber) */}
                            {(() => {
                                const skimmer = diagramEquipment.find(e => e.key.toUpperCase() === 'SKIMMER' || e.name.toLowerCase().includes('skimmer'));
                                if (!skimmer) return null;
                                const isOn = skimmer.state === 'on';
                                return (
                                    <g
                                        transform="translate(200, 75)"
                                        onClick={() => toggleSwitch(skimmer.config.switch)}
                                        style={{ cursor: 'pointer' }}
                                    >
                                        <foreignObject x="-20" y="-20" width="40" height="40" style={{ pointerEvents: 'none' }}>
                                            <div style={{ color: isOn ? '#4ade80' : '#778da9', display: 'flex', justifyContent: 'center', alignItems: 'center', width: '100%', height: '100%' }}>
                                                <EquipmentIcon type={skimmer.name} size={40} />
                                            </div>
                                        </foreignObject>
                                        <text y="30" textAnchor="middle" fill="#778da9" fontSize="7" fontWeight="700">{skimmer.name.toUpperCase()}</text>
                                    </g>
                                );
                            })()}

                            {/* Other Equipment in Sump */}
                            {diagramEquipment.filter(e => {
                                if (e.position !== 'sump') return false;
                                const key = e.key.toUpperCase();
                                const name = e.name.toLowerCase();
                                const isSpecial = key === 'RETURN_PUMP' ||
                                    key === 'SKIMMER' || name.includes('skimmer') ||
                                    key === 'INKBIRD' || name.includes('inkbird');
                                return !isSpecial;
                            }).map((e, i) => {
                                const x = 320 + (i * 60);
                                const y = 55;
                                const isOn = e.state === 'on';
                                return (
                                    <g
                                        key={e.key}
                                        transform={`translate(${x}, ${y})`}
                                        onClick={() => toggleSwitch(e.config.switch)}
                                        style={{ cursor: 'pointer' }}
                                    >
                                        <g className={styles.clickableIcon}>
                                            <circle r="25" fill="transparent" />
                                            <foreignObject x="-20" y="-20" width="40" height="40" style={{ pointerEvents: 'none' }}>
                                                <div style={{ color: isOn ? '#4ade80' : '#778da9', display: 'flex', justifyContent: 'center', alignItems: 'center', width: '100%', height: '100%' }}>
                                                    <EquipmentIcon type={e.name} size={40} />
                                                </div>
                                            </foreignObject>
                                        </g>
                                        <text y="30" textAnchor="middle" fill="#778da9" fontSize="7" fontWeight="700">{e.name.toUpperCase()}</text>
                                    </g>
                                );
                            })}
                        </g>

                        {/* Room/Other Equipment */}
                        <g transform="translate(30, 120)">
                            <text x="0" y="-40" fill="rgba(255,255,255,0.3)" fontSize="12" fontWeight="800">EXTERNAL</text>
                            {diagramEquipment.filter(e => e.position === 'room').map((e, i) => {
                                const x = 0;
                                const y = i * 70;
                                const isOn = e.state === 'on';
                                return (
                                    <g
                                        key={e.key}
                                        transform={`translate(${x}, ${y})`}
                                        onClick={() => toggleSwitch(e.config.switch)}
                                        style={{ cursor: 'pointer' }}
                                    >
                                        <g className={styles.clickableIcon}>
                                            <circle r="25" fill="transparent" />
                                            <foreignObject x="-20" y="-20" width="40" height="40" style={{ pointerEvents: 'none' }}>
                                                <div style={{ color: isOn ? '#4ade80' : '#778da9', display: 'flex', justifyContent: 'center', alignItems: 'center', width: '100%', height: '100%' }}>
                                                    <EquipmentIcon type={e.name} size={40} />
                                                </div>
                                            </foreignObject>
                                        </g>
                                        <text y="30" textAnchor="middle" fill="#778da9" fontSize="7" fontWeight="700">{e.name.toUpperCase()}</text>
                                    </g>
                                );
                            })}
                        </g>

                        {/* Pipes (Moved to end to render on top of containers/liquid) */}
                        {/* Overflow Pipe */}
                        <path d="M 600 220 L 600 410" fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="16" strokeLinecap="round" />
                        {isReturnRunning && (
                            <path d="M 600 220 L 600 410" fill="none" stroke="#00b4d8" strokeWidth="6" strokeDasharray="10,10" className={styles.awcFlow} opacity="0.4" />
                        )}

                        {/* Return Pipe */}
                        <path d="M 290 495 L 242 495 L 242 90 L 280 90" fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="12" strokeLinecap="round" />
                        {isReturnRunning && (
                            <path d="M 290 495 L 242 495 L 242 90 L 280 90" fill="none" stroke="#4ade80" strokeWidth="6" strokeDasharray="10,10" className={styles.awcFlow} opacity="0.6" />
                        )}

                        {/* ATO Tubing - Staggered Bus at y=365 -> Drops to Return Chamber */}
                        {(() => {
                            const path = `M 195 515 L 195 365 L 290 365 L 290 410`;

                            return (
                                <>
                                    <path d={path} fill="none" stroke="rgba(255,255,255,0.15)" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
                                    {isATORunning && (
                                        <path d={path} fill="none" stroke="#90e0ef" strokeWidth="3" strokeDasharray="8,8" className={styles.awcFlow} opacity="0.8" strokeLinecap="round" strokeLinejoin="round" />
                                    )}
                                </>
                            );
                        })()}

                        {/* Dosing Tubing - Perfect Arc Over Pump & Bus at y=340 */}
                        {(() => {
                            const dosingPumps = diagramEquipment.filter(e => e.position === 'dosing_container' && (e.name.toLowerCase().includes('dose') || e.name.toLowerCase().includes('dosing') || e.key.toLowerCase().includes('pump')));
                            const visibleDosingPumps = dosingPumps.filter(e => e.config.showInDiagram !== false);
                            if (visibleDosingPumps.length === 0) return null;

                            const isDosing = visibleDosingPumps.some(e => e.state === 'on');
                            // Symmetric Arc peaking at y=315, Horizontal at y=340
                            const path = `M 90 515 L 90 340 Q 90 315 105 315 Q 120 315 120 340 L 270 340 L 270 410`;

                            return (
                                <>
                                    <path d={path} fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
                                    {isDosing && (
                                        <path d={path} fill="none" stroke="#fbbf24" strokeWidth="3" strokeDasharray="5,10" className={styles.awcFlow} opacity="0.8" strokeLinecap="round" strokeLinejoin="round" />
                                    )}
                                </>
                            );
                        })()}

                        {/* AWC Tubing - Swapped & Nested (No crossover) */}
                        {(() => {
                            const showFresh = settings.waterChange.entities.pumpFreshShowInDiagram;
                            const showWaste = settings.waterChange.entities.pumpWasteShowInDiagram;

                            const wastePumpActive = entities?.[settings.waterChange.entities.pumpWaste]?.state === 'on';
                            const freshPumpActive = entities?.[settings.waterChange.entities.pumpFresh]?.state === 'on';

                            // Waste: Sump far right (610, 480) -> Up to y=340 -> Arc peaking at y=315 -> Waste (695, 515)
                            const wastePath = `M 610 480 L 610 340 L 665 340 Q 665 315 680 315 Q 695 315 695 340 L 695 515`;

                            // Fresh SW: Fresh Bottom (785, 515) -> Up to y=310 -> Arc peaking at y=285 -> Horizontal left at y=310 -> Sump middle
                            const freshPath = `M 785 515 L 785 310 Q 785 285 770 285 Q 755 285 755 310 L 330 310 L 330 410`;

                            return (
                                <>
                                    {showWaste && (
                                        <>
                                            <path d={wastePath} fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
                                            {wastePumpActive && (
                                                <path d={wastePath} fill="none" stroke="#f87171" strokeWidth="3" strokeDasharray="5,10" className={styles.awcFlow} opacity="0.8" strokeLinecap="round" strokeLinejoin="round" />
                                            )}
                                        </>
                                    )}
                                    {showFresh && (
                                        <>
                                            <path d={freshPath} fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
                                            {freshPumpActive && (
                                                <path d={freshPath} fill="none" stroke="#4ade80" strokeWidth="3" strokeDasharray="5,10" className={styles.awcFlow} opacity="0.8" strokeLinecap="round" strokeLinejoin="round" />
                                            )}
                                        </>
                                    )}
                                </>
                            );
                        })()}
                    </svg>
                )}
            </div>
        </div>
    );
};
