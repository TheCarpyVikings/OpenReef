'use client';

import React, { useState, useMemo, useEffect } from 'react';
import styles from '@/app/dashboard.module.css';
import { useSettings } from '@/context/SettingsContext';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import { Grid3X3, HelpCircle, Loader, Info } from 'lucide-react';
import { historyResponseToPoints } from '@/lib/ha-history';
import type { DataPoint } from '@/types/reef';

/* ── Helpers ── */

function interpolateAt(data: { x: number; y: number }[], t: number): number | null {
    if (data.length === 0) return null;
    if (t <= data[0].x) return data[0].y;
    if (t >= data[data.length - 1].x) return data[data.length - 1].y;
    for (let i = 0; i < data.length - 1; i++) {
        if (t >= data[i].x && t <= data[i + 1].x) {
            const ratio = (t - data[i].x) / (data[i + 1].x - data[i].x);
            return data[i].y + ratio * (data[i + 1].y - data[i].y);
        }
    }
    return null;
}

function pearsonR(xs: number[], ys: number[]): number {
    const n = xs.length;
    if (n < 3) return NaN;
    const sumX = xs.reduce((a, b) => a + b, 0);
    const sumY = ys.reduce((a, b) => a + b, 0);
    const sumXY = xs.reduce((a, b, i) => a + b * ys[i], 0);
    const sumX2 = xs.reduce((a, b) => a + b * b, 0);
    const sumY2 = ys.reduce((a, b) => a + b * b, 0);
    const denom = Math.sqrt((n * sumX2 - sumX * sumX) * (n * sumY2 - sumY * sumY));
    if (denom === 0) return 0;
    return (n * sumXY - sumX * sumY) / denom;
}

function computeCorrelation(dataA: { x: number; y: number }[], dataB: { x: number; y: number }[]): number {
    if (dataA.length < 3 || dataB.length < 3) return NaN;
    const startTime = Math.max(dataA[0].x, dataB[0].x);
    const endTime = Math.min(dataA[dataA.length - 1].x, dataB[dataB.length - 1].x);
    if (endTime <= startTime) return NaN;
    const numSamples = Math.min(200, Math.max(20, Math.min(dataA.length, dataB.length)));
    const step = (endTime - startTime) / numSamples;
    const vA: number[] = [], vB: number[] = [];
    for (let t = startTime; t <= endTime; t += step) {
        const a = interpolateAt(dataA, t), b = interpolateAt(dataB, t);
        if (a !== null && b !== null) { vA.push(a); vB.push(b); }
    }
    return pearsonR(vA, vB);
}

function rToColor(r: number): string {
    if (isNaN(r)) return 'rgba(255,255,255,0.03)';
    const abs = Math.abs(r);
    if (r >= 0) {
        if (abs >= 0.7) return 'rgba(74, 222, 128, 0.6)';
        if (abs >= 0.4) return 'rgba(74, 222, 128, 0.3)';
        if (abs >= 0.2) return 'rgba(74, 222, 128, 0.12)';
        return 'rgba(255,255,255,0.03)';
    } else {
        if (abs >= 0.7) return 'rgba(96, 165, 250, 0.6)';
        if (abs >= 0.4) return 'rgba(96, 165, 250, 0.3)';
        if (abs >= 0.2) return 'rgba(96, 165, 250, 0.12)';
        return 'rgba(255,255,255,0.03)';
    }
}

function rLabel(r: number): string {
    if (isNaN(r)) return 'No data';
    const abs = Math.abs(r);
    const dir = r >= 0 ? 'positive' : 'negative';
    if (abs >= 0.7) return `Strong ${dir}`;
    if (abs >= 0.4) return `Moderate ${dir}`;
    if (abs >= 0.2) return `Weak ${dir}`;
    return 'No link';
}

/* ── Beginner-friendly insight generator ── */
const INSIGHTS: Record<string, string> = {
    'ph_co2': 'CO₂ dissolves in water to form carbonic acid, lowering pH. When people are in the room, CO₂ rises and pH drops. This is completely normal.',
    'co2_ph': 'CO₂ dissolves in water to form carbonic acid, lowering pH. When people are in the room, CO₂ rises and pH drops. This is completely normal.',
    'temp_ph': 'Higher temperatures can slightly increase pH readings. Temperature also affects biological activity in the tank.',
    'ph_temp': 'Higher temperatures can slightly increase pH readings. Temperature also affects biological activity in the tank.',
    'temp_do': 'Warmer water holds less dissolved oxygen. If your tank is hot, oxygen levels will naturally drop.',
    'do_temp': 'Warmer water holds less dissolved oxygen. If your tank is hot, oxygen levels will naturally drop.',
    'temp_room_temp': 'Your room temperature directly affects tank temperature. Good insulation and a reliable heater/chiller help maintain stability.',
    'room_temp_temp': 'Your room temperature directly affects tank temperature. Good insulation and a reliable heater/chiller help maintain stability.',
    'co2_humidity': 'Both are affected by room ventilation. Opening windows will lower both CO₂ and humidity.',
    'humidity_co2': 'Both are affected by room ventilation. Opening windows will lower both CO₂ and humidity.',
    'ph_orp': 'pH and ORP often correlate because both are affected by the redox chemistry of your tank water.',
    'orp_ph': 'pH and ORP often correlate because both are affected by the redox chemistry of your tank water.',
};

interface SensorInfo {
    id: string;
    label: string;
    entityId: string;
}

export const CorrelationHeatmap: React.FC = () => {
    const { settings, getLabel } = useSettings();
    const { fetchHistory } = useHomeAssistant();

    const [historyData, setHistoryData] = useState<Record<string, { x: number; y: number }[]>>({});
    const [isLoading, setIsLoading] = useState(false);
    const [selectedCell, setSelectedCell] = useState<{ a: string; b: string } | null>(null);
    const [rangeHours, setRangeHours] = useState(24);

    /* ── Build sensor list ── */
    const sensors = useMemo((): SensorInfo[] => {
        const list: SensorInfo[] = [];
        const tankKeys: { id: string; key: keyof typeof settings.entities.tank }[] = [
            { id: 'temp', key: 'temp' }, { id: 'ph', key: 'ph' }, { id: 'salinity', key: 'salinity' },
            { id: 'orp', key: 'orp' }, { id: 'do', key: 'do' },
        ];
        tankKeys.forEach(s => {
            const eid = settings.entities.tank[s.key];
            if (eid) list.push({ id: s.id, label: getLabel(s.id, s.id), entityId: eid });
        });
        const roomKeys: { id: string; key: keyof typeof settings.entities.room }[] = [
            { id: 'room_temp', key: 'temp' }, { id: 'co2', key: 'co2' }, { id: 'humidity', key: 'humidity' },
        ];
        roomKeys.forEach(s => {
            const eid = settings.entities.room?.[s.key];
            if (eid) list.push({ id: s.id, label: getLabel(s.id, s.id), entityId: eid });
        });
        settings.customSensors?.filter(s => s.group !== 'manual').forEach(s => {
            if (s.haKey) list.push({ id: s.id, label: getLabel(s.id, s.label), entityId: s.haKey });
        });
        return list;
    }, [settings, getLabel]);

    /* ── Fetch all sensor history ── */
    useEffect(() => {
        if (sensors.length === 0) return;
        let cancelled = false;
        const fetchAll = async () => {
            setIsLoading(true);
            const result: Record<string, DataPoint[]> = {};
            for (const sensor of sensors) {
                try {
                    const data = await fetchHistory(sensor.entityId, rangeHours);
                    if (data && !cancelled) {
                        result[sensor.id] = historyResponseToPoints(data, sensor.entityId, {
                            rangeHours,
                            includeBounds: false,
                        });
                    }
                } catch (err) {
                    console.error(`Heatmap: Failed to fetch ${sensor.id}:`, err);
                }
            }
            if (!cancelled) { setHistoryData(result); setIsLoading(false); }
        };
        const timeout = window.setTimeout(() => {
            void fetchAll();
        }, 0);
        return () => {
            cancelled = true;
            window.clearTimeout(timeout);
        };
    }, [sensors, rangeHours, fetchHistory]);

    /* ── Compute correlation matrix ── */
    const matrix = useMemo(() => {
        const m: Record<string, Record<string, number>> = {};
        for (const a of sensors) {
            m[a.id] = {};
            for (const b of sensors) {
                if (a.id === b.id) { m[a.id][b.id] = 1; continue; }
                const dataA = historyData[a.id] || [];
                const dataB = historyData[b.id] || [];
                m[a.id][b.id] = computeCorrelation(dataA, dataB);
            }
        }
        return m;
    }, [sensors, historyData]);

    /* ── Find the most interesting insight to highlight ── */
    const topInsight = useMemo(() => {
        let best: { a: string; b: string; r: number; absR: number } | null = null;
        for (let i = 0; i < sensors.length; i++) {
            for (let j = i + 1; j < sensors.length; j++) {
                const r = matrix[sensors[i].id]?.[sensors[j].id] ?? NaN;
                if (isNaN(r)) continue;
                const absR = Math.abs(r);
                if (!best || absR > best.absR) {
                    best = { a: sensors[i].id, b: sensors[j].id, r, absR };
                }
            }
        }
        return best;
    }, [matrix, sensors]);

    const getInsight = (aId: string, bId: string): string | undefined => {
        return INSIGHTS[`${aId}_${bId}`] || INSIGHTS[`${bId}_${aId}`];
    };

    const selected = selectedCell
        ? { r: matrix[selectedCell.a]?.[selectedCell.b] ?? NaN, a: sensors.find(s => s.id === selectedCell.a), b: sensors.find(s => s.id === selectedCell.b) }
        : null;

    return (
        <div>
            {/* Beginner explanation */}
            <div style={{ background: 'rgba(168, 85, 247, 0.06)', border: '1px solid rgba(168, 85, 247, 0.15)', borderRadius: '12px', padding: '1rem 1.25rem', marginBottom: '1rem', display: 'flex', gap: '0.75rem', alignItems: 'flex-start' }}>
                <HelpCircle size={20} style={{ color: '#a855f7', flexShrink: 0, marginTop: 2 }} />
                <div style={{ fontSize: '0.8rem', color: '#b0bec5', lineHeight: 1.6 }}>
                    <strong style={{ color: '#e0e1dd' }}>What is this?</strong> This heatmap shows how your sensors relate to each other. <strong style={{ color: '#4ade80' }}>Green</strong> means they move together (when one goes up, so does the other). <strong style={{ color: '#60a5fa' }}>Blue</strong> means they move oppositely. Grey means no relationship. Click any cell to learn more.
                </div>
            </div>

            {/* Time range */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                <div className={styles.rangeSelector}>
                    {[{ label: '6H', h: 6 }, { label: '24H', h: 24 }, { label: '7D', h: 168 }].map(opt => (
                        <button key={opt.label} className={`${styles.rangeButton} ${rangeHours === opt.h ? styles.rangeActive : ''}`} onClick={() => setRangeHours(opt.h)}>
                            {opt.label}
                        </button>
                    ))}
                </div>
                {isLoading && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', color: '#a855f7' }}>
                        <Loader size={14} className={styles.spinning || ''} /> Analysing...
                    </div>
                )}
            </div>

            {sensors.length < 2 ? (
                <div style={{ textAlign: 'center', padding: '3rem 1rem', color: '#778da9' }}>
                    <Grid3X3 size={48} strokeWidth={1} style={{ opacity: 0.3, marginBottom: '0.5rem' }} />
                    <p>Connect at least 2 sensors in Settings to see correlations</p>
                </div>
            ) : (
                <>
                    {/* Matrix grid */}
                    <div style={{ overflowX: 'auto', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.06)' }}>
                        <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: sensors.length * 80 }}>
                            <thead>
                                <tr>
                                    <th style={{ padding: '0.5rem', background: 'rgba(0,0,0,0.3)', borderBottom: '1px solid rgba(255,255,255,0.06)' }} />
                                    {sensors.map(s => (
                                        <th key={s.id} style={{ padding: '0.5rem 0.4rem', fontSize: '0.65rem', fontWeight: 700, color: '#778da9', textTransform: 'uppercase', letterSpacing: '0.03em', background: 'rgba(0,0,0,0.3)', borderBottom: '1px solid rgba(255,255,255,0.06)', whiteSpace: 'nowrap' }}>
                                            {s.label}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {sensors.map(row => (
                                    <tr key={row.id}>
                                        <td style={{ padding: '0.5rem 0.6rem', fontSize: '0.7rem', fontWeight: 600, color: '#e0e1dd', whiteSpace: 'nowrap', background: 'rgba(0,0,0,0.2)', borderRight: '1px solid rgba(255,255,255,0.06)' }}>
                                            {row.label}
                                        </td>
                                        {sensors.map(col => {
                                            const r = matrix[row.id]?.[col.id] ?? NaN;
                                            const isIdentity = row.id === col.id;
                                            const isActive = selectedCell?.a === row.id && selectedCell?.b === col.id;
                                            return (
                                                <td
                                                    key={col.id}
                                                    onClick={() => !isIdentity && setSelectedCell({ a: row.id, b: col.id })}
                                                    style={{
                                                        padding: '0.5rem', textAlign: 'center', cursor: isIdentity ? 'default' : 'pointer',
                                                        background: isIdentity ? 'rgba(255,255,255,0.08)' : rToColor(r),
                                                        borderBottom: '1px solid rgba(255,255,255,0.03)',
                                                        borderRight: '1px solid rgba(255,255,255,0.03)',
                                                        outline: isActive ? '2px solid #a855f7' : 'none',
                                                        transition: 'all 0.15s',
                                                        position: 'relative',
                                                    }}
                                                >
                                                    <span style={{ fontSize: '0.75rem', fontWeight: 700, fontFamily: 'monospace', color: isIdentity ? '#4a5568' : '#e0e1dd' }}>
                                                        {isIdentity ? '—' : isNaN(r) ? '·' : r.toFixed(2)}
                                                    </span>
                                                </td>
                                            );
                                        })}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>

                    {/* Selected cell detail */}
                    {selected && !isNaN(selected.r) && (
                        <div style={{ marginTop: '1rem', background: 'rgba(27, 38, 59, 0.6)', borderRadius: '12px', padding: '1.25rem', border: '1px solid rgba(255,255,255,0.08)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                                <span style={{ fontSize: '0.85rem', fontWeight: 600, color: '#e0e1dd' }}>
                                    {selected.a?.label} ↔ {selected.b?.label}
                                </span>
                                <span style={{ fontSize: '1.25rem', fontWeight: 700, fontFamily: 'monospace', color: rToColor(selected.r).replace(/[\d.]+\)$/, '1)') }}>
                                    {(selected.r >= 0 ? '+' : '') + selected.r.toFixed(3)}
                                </span>
                            </div>
                            <div style={{ fontSize: '0.8rem', color: '#778da9', marginBottom: '0.5rem' }}>{rLabel(selected.r)}</div>
                            {/* Strength bar */}
                            <div style={{ height: 4, borderRadius: 4, background: 'rgba(255,255,255,0.06)', marginBottom: '0.75rem', overflow: 'hidden' }}>
                                <div style={{ height: '100%', width: `${Math.abs(selected.r) * 100}%`, borderRadius: 4, background: selected.r >= 0 ? '#4ade80' : '#60a5fa', transition: 'width 0.3s' }} />
                            </div>
                            {/* Insight */}
                            {selectedCell && getInsight(selectedCell.a, selectedCell.b) && (
                                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', padding: '0.75rem' }}>
                                    <Info size={16} style={{ color: '#fbbf24', flexShrink: 0, marginTop: 2 }} />
                                    <span style={{ fontSize: '0.78rem', color: '#b0bec5', lineHeight: 1.5 }}>
                                        {getInsight(selectedCell.a, selectedCell.b)}
                                    </span>
                                </div>
                            )}
                        </div>
                    )}

                    {/* Auto-highlighted top insight */}
                    {topInsight && Math.abs(topInsight.r) >= 0.5 && !selectedCell && (
                        <div style={{ marginTop: '1rem', background: 'rgba(74, 222, 128, 0.06)', border: '1px solid rgba(74, 222, 128, 0.15)', borderRadius: '12px', padding: '1rem 1.25rem', display: 'flex', gap: '0.75rem', alignItems: 'flex-start' }}>
                            <Info size={18} style={{ color: '#4ade80', flexShrink: 0, marginTop: 2 }} />
                            <div style={{ fontSize: '0.8rem', color: '#b0bec5', lineHeight: 1.5 }}>
                                <strong style={{ color: '#4ade80' }}>Key finding:</strong>{' '}
                                {sensors.find(s => s.id === topInsight.a)?.label} and {sensors.find(s => s.id === topInsight.b)?.label} have a{' '}
                                <strong>{rLabel(topInsight.r).toLowerCase()}</strong> correlation (R = {topInsight.r.toFixed(2)}).
                                {getInsight(topInsight.a, topInsight.b) && ` ${getInsight(topInsight.a, topInsight.b)}`}
                            </div>
                        </div>
                    )}

                    {/* Legend */}
                    <div style={{ marginTop: '1rem', display: 'flex', gap: '1rem', justifyContent: 'center', flexWrap: 'wrap' }}>
                        {[
                            { color: 'rgba(74, 222, 128, 0.6)', label: 'Strong positive' },
                            { color: 'rgba(74, 222, 128, 0.25)', label: 'Moderate positive' },
                            { color: 'rgba(255,255,255,0.05)', label: 'No link' },
                            { color: 'rgba(96, 165, 250, 0.25)', label: 'Moderate negative' },
                            { color: 'rgba(96, 165, 250, 0.6)', label: 'Strong negative' },
                        ].map(item => (
                            <div key={item.label} style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                <div style={{ width: 14, height: 14, borderRadius: 3, background: item.color, border: '1px solid rgba(255,255,255,0.1)' }} />
                                <span style={{ fontSize: '0.65rem', color: '#778da9' }}>{item.label}</span>
                            </div>
                        ))}
                    </div>
                </>
            )}
        </div>
    );
};
