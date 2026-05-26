import React, { useState, useCallback } from 'react';
import styles from '@/app/dashboard.module.css';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import { useSettings } from '@/context/SettingsContext';
import { Waves, Power, Zap, Moon, Wind, Lock } from 'lucide-react';

// ─── SVG Arc Visualisation ────────────────────────────────────────────────────

interface ArcVizProps {
    angle: number; // 0–180
    isOn: boolean;
}

const ArcViz: React.FC<ArcVizProps> = ({ angle, isOn }) => {
    const CX = 80;
    const CY = 80;
    const R = 60;

    // Convert angle (0=left, 90=top, 180=right) to SVG coords on upper semicircle
    const toPoint = (deg: number) => {
        const rad = (Math.PI * (180 - deg)) / 180; // flip so 0 is left, 180 is right
        return {
            x: CX + R * Math.cos(rad),
            y: CY - R * Math.sin(rad),
        };
    };

    // Semicircle arc path (left → right, upper half)
    const arcPath = `M ${CX - R} ${CY} A ${R} ${R} 0 0 1 ${CX + R} ${CY}`;

    // Pointer end point
    const pointer = toPoint(angle);

    // Sweep fill — arc from 0 to current angle
    const sweepEnd = toPoint(angle);
    const largeArc = angle > 90 ? 1 : 0;
    const fillPath =
        angle <= 0
            ? ''
            : `M ${CX - R} ${CY} A ${R} ${R} 0 ${largeArc} 1 ${sweepEnd.x} ${sweepEnd.y} L ${CX} ${CY} Z`;

    const accentColor = isOn ? '#00b4d8' : '#444';
    const fillColor = isOn ? 'rgba(0,180,216,0.15)' : 'rgba(100,100,100,0.08)';

    return (
        <svg width="160" height="90" viewBox="0 20 160 80" style={{ display: 'block', margin: '0 auto' }}>
            {/* Sweep fill */}
            {fillPath && <path d={fillPath} fill={fillColor} />}

            {/* Semicircle track */}
            <path d={arcPath} fill="none" stroke="#27272a" strokeWidth="4" strokeLinecap="round" />

            {/* Coloured arc up to pointer */}
            {angle > 0 && (
                <path
                    d={`M ${CX - R} ${CY} A ${R} ${R} 0 ${largeArc} 1 ${sweepEnd.x} ${sweepEnd.y}`}
                    fill="none"
                    stroke={accentColor}
                    strokeWidth="4"
                    strokeLinecap="round"
                    style={{ transition: 'stroke 0.3s' }}
                />
            )}

            {/* Pointer line */}
            <line
                x1={CX}
                y1={CY}
                x2={pointer.x}
                y2={pointer.y}
                stroke={accentColor}
                strokeWidth="2.5"
                strokeLinecap="round"
                style={{ transition: 'd 0.1s, stroke 0.3s' }}
            />

            {/* Centre dot */}
            <circle cx={CX} cy={CY} r={4} fill={accentColor} style={{ transition: 'fill 0.3s' }} />

            {/* Angle label */}
            <text
                x={CX}
                y={CY + 22}
                textAnchor="middle"
                fontSize="11"
                fill={accentColor}
                fontWeight="700"
                style={{ transition: 'fill 0.3s' }}
            >
                {angle}°
            </text>
        </svg>
    );
};

// ─── Unit Card ────────────────────────────────────────────────────────────────

interface UnitState {
    angle: number;  // 0–180
    speed: number;  // 0–100
    isOn: boolean;
}

interface UnitCardProps {
    unitKey: 'OSW_UNIT_1' | 'OSW_UNIT_2';
    label: string;
    state: UnitState;
    onAngleChange: (val: number) => void;
    onSpeedChange: (val: number) => void;
    onToggle: () => void;
}

const UnitCard: React.FC<UnitCardProps> = ({ label, state, onAngleChange, onSpeedChange, onToggle }) => {
    const isOn = state.isOn;
    const accent = isOn ? '#00b4d8' : '#555';

    return (
        <div
            className={styles.card}
            style={{
                borderLeft: `4px solid ${accent}`,
                transition: 'border-color 0.3s',
                background: isOn ? 'rgba(0,180,216,0.05)' : 'rgba(255,255,255,0.02)',
            }}
        >
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <span style={{ fontWeight: 700, fontSize: '1rem', color: '#e0e1dd' }}>{label}</span>
                <button
                    onClick={onToggle}
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.4rem',
                        padding: '0.4rem 0.9rem',
                        borderRadius: '6px',
                        border: `1px solid ${accent}`,
                        background: isOn ? `rgba(0,180,216,0.15)` : 'rgba(255,255,255,0.05)',
                        color: accent,
                        cursor: 'pointer',
                        fontSize: '0.8rem',
                        fontWeight: 600,
                        transition: 'all 0.3s',
                    }}
                >
                    <Power size={14} />
                    {isOn ? 'ON' : 'OFF'}
                </button>
            </div>

            {/* SVG Arc */}
            <ArcViz angle={state.angle} isOn={isOn} />

            {/* Angle Slider */}
            <div style={{ marginTop: '1.2rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.4rem' }}>
                    <span style={{ fontSize: '0.75rem', color: '#778da9', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                        Angle
                    </span>
                    <span style={{ fontSize: '0.85rem', fontWeight: 700, color: accent }}>{state.angle}°</span>
                </div>
                <input
                    type="range"
                    min={0}
                    max={180}
                    step={1}
                    value={state.angle}
                    onChange={(e) => onAngleChange(parseInt(e.target.value))}
                    disabled={!isOn}
                    style={{ width: '100%', accentColor: '#00b4d8', opacity: isOn ? 1 : 0.4, cursor: isOn ? 'pointer' : 'not-allowed' }}
                />
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: '#555', marginTop: '0.2rem' }}>
                    <span>0°</span>
                    <span>90°</span>
                    <span>180°</span>
                </div>
            </div>

            {/* Speed Slider */}
            <div style={{ marginTop: '1rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.4rem' }}>
                    <span style={{ fontSize: '0.75rem', color: '#778da9', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                        Speed
                    </span>
                    <span style={{ fontSize: '0.85rem', fontWeight: 700, color: accent }}>{state.speed}%</span>
                </div>
                <input
                    type="range"
                    min={0}
                    max={100}
                    step={1}
                    value={state.speed}
                    onChange={(e) => onSpeedChange(parseInt(e.target.value))}
                    disabled={!isOn}
                    style={{ width: '100%', accentColor: '#00b4d8', opacity: isOn ? 1 : 0.4, cursor: isOn ? 'pointer' : 'not-allowed' }}
                />
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: '#555', marginTop: '0.2rem' }}>
                    <span>Slow</span>
                    <span>Fast</span>
                </div>
            </div>
        </div>
    );
};

// ─── Quick Mode Button ────────────────────────────────────────────────────────

interface QuickModeButtonProps {
    label: string;
    icon: React.ReactNode;
    active: boolean;
    color: string;
    onClick: () => void;
}

const QuickModeButton: React.FC<QuickModeButtonProps> = ({ label, icon, active, color, onClick }) => (
    <button
        onClick={onClick}
        style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '0.5rem',
            padding: '1rem 1.5rem',
            borderRadius: '10px',
            border: `1.5px solid ${active ? color : '#27272a'}`,
            background: active ? `rgba(${hexToRgb(color)}, 0.12)` : 'rgba(255,255,255,0.03)',
            color: active ? color : '#778da9',
            cursor: 'pointer',
            fontSize: '0.85rem',
            fontWeight: 600,
            transition: 'all 0.25s',
            minWidth: '90px',
        }}
    >
        {icon}
        {label}
    </button>
);

function hexToRgb(hex: string): string {
    const clean = hex.replace('#', '');
    const r = parseInt(clean.substring(0, 2), 16);
    const g = parseInt(clean.substring(2, 4), 16);
    const b = parseInt(clean.substring(4, 6), 16);
    return `${r},${g},${b}`;
}

// ─── Roadmap Card ─────────────────────────────────────────────────────────────

interface RoadmapCardProps {
    title: string;
    description: string;
}

const RoadmapCard: React.FC<RoadmapCardProps> = ({ title, description }) => (
    <div
        style={{
            padding: '1.2rem',
            borderRadius: '10px',
            border: '1px dashed rgba(255,255,255,0.1)',
            background: 'rgba(255,255,255,0.02)',
            opacity: 0.65,
            position: 'relative',
        }}
    >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.4rem' }}>
            <Lock size={13} color="#778da9" />
            <span style={{ fontSize: '0.85rem', fontWeight: 700, color: '#e0e1dd' }}>{title}</span>
            <span style={{
                marginLeft: 'auto',
                fontSize: '0.65rem',
                padding: '2px 8px',
                borderRadius: '4px',
                background: 'rgba(120,120,120,0.15)',
                color: '#778da9',
                fontWeight: 700,
                letterSpacing: '0.05em',
            }}>
                COMING SOON
            </span>
        </div>
        <p style={{ margin: 0, fontSize: '0.78rem', color: '#778da9', lineHeight: '1.4' }}>{description}</p>
    </div>
);

// ─── Main Screen ──────────────────────────────────────────────────────────────

type QuickMode = 'feed' | 'night' | 'storm' | null;

const DEFAULT_UNIT: UnitState = { angle: 90, speed: 50, isOn: true };

export const OceanSeaWavesScreen: React.FC = () => {
    const { settings } = useSettings();
    const { entities, toggleSwitch, updateInputNumber } = useHomeAssistant();

    const [unit1, setUnit1] = useState<UnitState>({ ...DEFAULT_UNIT });
    const [unit2, setUnit2] = useState<UnitState>({ ...DEFAULT_UNIT, angle: 60, speed: 40 });
    const [quickMode, setQuickMode] = useState<QuickMode>(null);

    // Helper: get angle/speed input_number entity (conventional naming)
    const getAngleEntity = (key: 'OSW_UNIT_1' | 'OSW_UNIT_2'): string =>
        key === 'OSW_UNIT_1' ? 'input_number.osw_unit_1_angle' : 'input_number.osw_unit_2_angle';

    const getSpeedEntity = (key: 'OSW_UNIT_1' | 'OSW_UNIT_2'): string =>
        key === 'OSW_UNIT_1' ? 'input_number.osw_unit_1_speed' : 'input_number.osw_unit_2_speed';

    // Toggle on/off for a unit
    const handleToggle = useCallback((key: 'OSW_UNIT_1' | 'OSW_UNIT_2', setter: React.Dispatch<React.SetStateAction<UnitState>>) => {
        const sw = settings.entities.equipment[key]?.switch;
        if (sw) toggleSwitch(sw);
        setter(prev => ({ ...prev, isOn: !prev.isOn }));
    }, [settings.entities.equipment, toggleSwitch]);

    // Angle change
    const handleAngleChange = useCallback((key: 'OSW_UNIT_1' | 'OSW_UNIT_2', setter: React.Dispatch<React.SetStateAction<UnitState>>, val: number) => {
        setter(prev => ({ ...prev, angle: val }));
        const entity = getAngleEntity(key);
        if (entities?.[entity]) updateInputNumber(entity, val);
    }, [entities, updateInputNumber]);

    // Speed change
    const handleSpeedChange = useCallback((key: 'OSW_UNIT_1' | 'OSW_UNIT_2', setter: React.Dispatch<React.SetStateAction<UnitState>>, val: number) => {
        setter(prev => ({ ...prev, speed: val }));
        const entity = getSpeedEntity(key);
        if (entities?.[entity]) updateInputNumber(entity, val);
    }, [entities, updateInputNumber]);

    // Quick modes
    const applyQuickMode = (mode: QuickMode) => {
        if (quickMode === mode) {
            setQuickMode(null);
            return;
        }
        setQuickMode(mode);

        if (mode === 'feed') {
            // Pause: speed → 0
            setUnit1(prev => ({ ...prev, speed: 0 }));
            setUnit2(prev => ({ ...prev, speed: 0 }));
        } else if (mode === 'night') {
            // Gentle: speed → 10%
            setUnit1(prev => ({ ...prev, speed: 10 }));
            setUnit2(prev => ({ ...prev, speed: 10 }));
        } else if (mode === 'storm') {
            // Max: speed → 100%
            setUnit1(prev => ({ ...prev, speed: 100 }));
            setUnit2(prev => ({ ...prev, speed: 100 }));
        }
    };

    return (
        <div className={styles.missionControl}>
            {/* Status Banner */}
            <div className={styles.statusBanner} style={{ backgroundColor: 'rgba(0,180,216,0.08)', borderColor: '#00b4d8' }}>
                <Waves color="#00b4d8" size={26} />
                <h2 style={{ color: '#00b4d8', margin: 0, fontSize: '1.5rem', letterSpacing: '0.06em' }}>
                    OCEAN SEA WAVES
                </h2>
                <span style={{ marginLeft: 'auto', fontSize: '0.75rem', color: '#00b4d8', opacity: 0.7, fontWeight: 600, letterSpacing: '0.1em' }}>
                    MVP
                </span>
            </div>

            {/* Unit Cards */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1.5rem', marginTop: '2rem' }}>
                <UnitCard
                    unitKey="OSW_UNIT_1"
                    label="Unit 1"
                    state={unit1}
                    onToggle={() => handleToggle('OSW_UNIT_1', setUnit1)}
                    onAngleChange={(v) => handleAngleChange('OSW_UNIT_1', setUnit1, v)}
                    onSpeedChange={(v) => handleSpeedChange('OSW_UNIT_1', setUnit1, v)}
                />
                <UnitCard
                    unitKey="OSW_UNIT_2"
                    label="Unit 2"
                    state={unit2}
                    onToggle={() => handleToggle('OSW_UNIT_2', setUnit2)}
                    onAngleChange={(v) => handleAngleChange('OSW_UNIT_2', setUnit2, v)}
                    onSpeedChange={(v) => handleSpeedChange('OSW_UNIT_2', setUnit2, v)}
                />
            </div>

            {/* Quick Modes */}
            <section style={{ marginTop: '2rem' }}>
                <h3 className={styles.sectionSubtitle}>Quick Modes</h3>
                <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
                    <QuickModeButton
                        label="Feed"
                        icon={<Zap size={20} />}
                        active={quickMode === 'feed'}
                        color="#fbbf24"
                        onClick={() => applyQuickMode('feed')}
                    />
                    <QuickModeButton
                        label="Night"
                        icon={<Moon size={20} />}
                        active={quickMode === 'night'}
                        color="#818cf8"
                        onClick={() => applyQuickMode('night')}
                    />
                    <QuickModeButton
                        label="Storm"
                        icon={<Wind size={20} />}
                        active={quickMode === 'storm'}
                        color="#f87171"
                        onClick={() => applyQuickMode('storm')}
                    />
                </div>
            </section>

            {/* Roadmap */}
            <section style={{ marginTop: '2.5rem' }}>
                <h3 className={styles.sectionSubtitle}>Roadmap — Competing with Tunze Orca Mk2</h3>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '1rem' }}>
                    <RoadmapCard
                        title="Flow Sculpting"
                        description="Angle-dependent speed curves — vary pump power based on where the head is pointing."
                    />
                    <RoadmapCard
                        title="Custom Wave Patterns"
                        description="Sine, Random, Surge, Pulse, and Tidal Schedule modes for natural reef simulation."
                    />
                    <RoadmapCard
                        title="Multi-Unit Sync & Anti-Sync"
                        description="Coordinate multiple units in phase or counter-phase for complex flow dynamics."
                    />
                    <RoadmapCard
                        title="Scheduled Tidal Rhythms"
                        description="Program 24-hour tidal schedules mimicking natural reef water movement cycles."
                    />
                </div>
            </section>
        </div>
    );
};
