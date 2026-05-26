'use client';

import React, { useState, useMemo, useEffect } from 'react';
import styles from '@/app/dashboard.module.css';
import { useSettings } from '@/context/SettingsContext';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import { Line } from 'react-chartjs-2';
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    Title,
    Tooltip,
    Legend,
    Filler,
} from 'chart.js';
import type { ChartOptions, TooltipItem } from 'chart.js';
import { TrendingUp, RotateCcw, Check, Grid3X3, AlertTriangle, Sun, Activity } from 'lucide-react';
import { CorrelationHeatmap } from './analytics/CorrelationHeatmap';
import { AnomalyTimeline } from './analytics/AnomalyTimeline';
import { DayNightAnalysis } from './analytics/DayNightAnalysis';
import { RateOfChangeChart } from './analytics/RateOfChangeChart';
import { historyResponseToPoints } from '@/lib/ha-history';
import type { DataPoint } from '@/types/reef';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler);

/* ── Constants ─────────────────────────────────────────────── */

const SENSOR_COLORS = ['#f43f5e', '#3b82f6', '#10b981', '#f59e0b'];
const MAX_SENSORS = 4;

/* ── Types ─────────────────────────────────────────────────── */

interface SensorDef {
    id: string;
    label: string;
    entityId: string;
    isManual: boolean;
    group: 'tank' | 'room' | 'manual' | 'custom';
    unit: string;
    manualKey?: string;
}

/* ── Helpers ────────────────────────────────────────────────── */

function parseManualDate(dateStr: string): number {
    if (!dateStr) return 0;
    let d = dateStr;
    if (d.includes('/')) {
        const parts = d.split('/');
        if (parts.length === 3) {
            const [p1, p2, p3] = parts;
            if (p3.length === 4) d = `${p3}-${p2.padStart(2, '0')}-${p1.padStart(2, '0')}`;
            else if (p1.length === 4) d = `${p1}-${p2.padStart(2, '0')}-${p3.padStart(2, '0')}`;
        }
    }
    return new Date(d.includes('T') ? d : d + 'T12:00:00').getTime();
}

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

function computeCorrelation(
    dataA: { x: number; y: number }[],
    dataB: { x: number; y: number }[]
): number {
    if (dataA.length < 3 || dataB.length < 3) return NaN;
    const startTime = Math.max(dataA[0].x, dataB[0].x);
    const endTime = Math.min(dataA[dataA.length - 1].x, dataB[dataB.length - 1].x);
    if (endTime <= startTime) return NaN;

    // Use the sparser dataset's timestamps for sampling
    const sparser = dataA.length < dataB.length ? dataA : dataB;
    const samplePoints: number[] = [];

    if (sparser.length < 30) {
        sparser.forEach(p => { if (p.x >= startTime && p.x <= endTime) samplePoints.push(p.x); });
    } else {
        const numSamples = Math.min(200, Math.max(20, Math.min(dataA.length, dataB.length)));
        const step = (endTime - startTime) / numSamples;
        for (let t = startTime; t <= endTime; t += step) samplePoints.push(t);
    }

    if (samplePoints.length < 3) return NaN;

    const vA: number[] = [];
    const vB: number[] = [];
    for (const t of samplePoints) {
        const a = interpolateAt(dataA, t);
        const b = interpolateAt(dataB, t);
        if (a !== null && b !== null) { vA.push(a); vB.push(b); }
    }
    return pearsonR(vA, vB);
}

function correlationInfo(r: number) {
    if (isNaN(r)) return { label: 'N/A', color: '#778da9', desc: 'Not enough overlapping data' };
    const abs = Math.abs(r);
    const dir = r >= 0 ? 'positive' : 'negative';
    if (abs >= 0.8) return { label: `Strong ${dir}`, color: '#4ade80', desc: r >= 0 ? 'These rise and fall together' : 'When one rises, the other falls' };
    if (abs >= 0.5) return { label: `Moderate ${dir}`, color: '#fbbf24', desc: 'A noticeable relationship exists' };
    if (abs >= 0.3) return { label: `Weak ${dir}`, color: '#f97316', desc: 'A slight relationship may exist' };
    return { label: 'No correlation', color: '#6b7280', desc: 'These appear to be independent' };
}

/* ── Component ──────────────────────────────────────────────── */

export const AnalyticsScreen: React.FC = () => {
    const { settings, getLabel, manualReadings } = useSettings();
    const { fetchHistory } = useHomeAssistant();

    const [activeView, setActiveView] = useState<'compare' | 'heatmap' | 'anomalies' | 'daynight' | 'roc'>('compare');
    const [selectedIds, setSelectedIds] = useState<string[]>([]);
    const [historyRange, setHistoryRange] = useState(24);
    const [sensorData, setSensorData] = useState<Record<string, DataPoint[]>>({});
    const [isLoading, setIsLoading] = useState(false);

    /* ── Build available sensors list ── */

    const availableSensors = useMemo((): SensorDef[] => {
        const sensors: SensorDef[] = [];

        // Tank
        const tankKeys: { id: string; key: keyof typeof settings.entities.tank; unit: string }[] = [
            { id: 'temp', key: 'temp', unit: '°C' },
            { id: 'ph', key: 'ph', unit: '' },
            { id: 'salinity', key: 'salinity', unit: 'ppt' },
            { id: 'orp', key: 'orp', unit: 'mV' },
            { id: 'do', key: 'do', unit: 'mg/L' },
        ];
        tankKeys.forEach(s => {
            const eid = settings.entities.tank[s.key];
            if (eid) sensors.push({ id: s.id, label: getLabel(s.id, s.id), entityId: eid, isManual: false, group: 'tank', unit: s.unit });
        });

        // Room
        const roomKeys: { id: string; key: keyof typeof settings.entities.room; unit: string }[] = [
            { id: 'room_temp', key: 'temp', unit: '°C' },
            { id: 'co2', key: 'co2', unit: 'ppm' },
            { id: 'humidity', key: 'humidity', unit: '%' },
        ];
        roomKeys.forEach(s => {
            const eid = settings.entities.room?.[s.key];
            if (eid) sensors.push({ id: s.id, label: getLabel(s.id, s.id), entityId: eid, isManual: false, group: 'room', unit: s.unit });
        });

        // Manual
        const manualKeys = [
            { id: 'alk', unit: 'dKH' }, { id: 'calc', unit: 'ppm' }, { id: 'mag', unit: 'ppm' },
            { id: 'salinity', unit: 'sg' }, { id: 'nitrate', unit: 'ppm' }, { id: 'phosphate', unit: 'ppm' },
        ];
        manualKeys.forEach(s => {
            sensors.push({ id: `manual_${s.id}`, label: getLabel(s.id, s.id), entityId: '', isManual: true, group: 'manual', unit: s.unit, manualKey: s.id });
        });

        // Custom
        settings.customSensors?.forEach(s => {
            sensors.push({
                id: s.id, label: getLabel(s.id, s.label),
                entityId: s.group !== 'manual' ? s.haKey : '',
                isManual: s.group === 'manual', group: s.group === 'manual' ? 'manual' : 'custom',
                unit: '', manualKey: s.group === 'manual' ? s.id : undefined,
            });
        });

        return sensors;
    }, [settings, getLabel]);

    /* ── Derived state ── */

    const hasManual = selectedIds.some(id => availableSensors.find(s => s.id === id)?.isManual);

    const rangeOptions = hasManual
        ? [{ label: '7D', hours: 168 }, { label: '30D', hours: 720 }, { label: '3M', hours: 2160 }, { label: '6M', hours: 4320 }, { label: '1Y', hours: 8760 }, { label: 'All', hours: 0 }]
        : [{ label: '1H', hours: 1 }, { label: '6H', hours: 6 }, { label: '24H', hours: 24 }, { label: '7D', hours: 168 }, { label: '30D', hours: 720 }];

    // Auto-adjust range when switching between manual/live
    useEffect(() => {
        const nextRange = hasManual && historyRange < 168
            ? 720
            : !hasManual && (historyRange === 0 || historyRange > 720)
                ? 24
                : null;
        if (nextRange === null) return;

        const timeout = window.setTimeout(() => setHistoryRange(nextRange), 0);
        return () => window.clearTimeout(timeout);
    }, [hasManual, historyRange]);

    /* ── Fetch data ── */

    useEffect(() => {
        let cancelled = false;
        const fetchAll = async () => {
            if (selectedIds.length === 0) {
                setSensorData({});
                return;
            }

            setIsLoading(true);
            const result: Record<string, DataPoint[]> = {};

            for (const sId of selectedIds) {
                const sensor = availableSensors.find(s => s.id === sId);
                if (!sensor) continue;

                if (sensor.isManual) {
                    const key = sensor.manualKey || sensor.id;
                    const readings = manualReadings[key] || [];
                    const now = Date.now();
                    const start = historyRange === 0 ? 0 : now - historyRange * 3600000;
                    result[sId] = readings
                        .map((reading) => ({ x: parseManualDate(reading.date), y: reading.value }))
                        .filter((point) => Number.isFinite(point.y) && point.x > 0 && (historyRange === 0 || point.x >= start))
                        .sort((a, b) => a.x - b.x);
                } else {
                    try {
                        const fetchHours = historyRange === 0 ? 8760 : historyRange;
                        const data = await fetchHistory(sensor.entityId, fetchHours);
                        if (data && !cancelled) {
                            result[sId] = historyResponseToPoints(data, sensor.entityId, {
                                rangeHours: fetchHours,
                                includeBounds: false,
                            });
                        }
                    } catch (err) {
                        console.error(`Analytics: Failed to fetch ${sId}:`, err);
                        result[sId] = [];
                    }
                }
            }

            if (!cancelled) { setSensorData(result); setIsLoading(false); }
        };

        const timeout = window.setTimeout(() => {
            void fetchAll();
        }, 0);
        return () => {
            cancelled = true;
            window.clearTimeout(timeout);
        };
    }, [selectedIds, historyRange, availableSensors, fetchHistory, manualReadings]);

    /* ── Chart data ── */

    const chartData = useMemo(() => ({
        datasets: selectedIds.map((sId, i) => {
            const sensor = availableSensors.find(s => s.id === sId);
            const color = SENSOR_COLORS[i];
            return {
                label: sensor ? (sensor.unit ? `${sensor.label} (${sensor.unit})` : sensor.label) : sId,
                data: sensorData[sId] || [],
                borderColor: color,
                backgroundColor: `${color}20`,
                fill: false,
                tension: sensor?.isManual ? 0 : 0.4,
                pointRadius: sensor?.isManual ? 5 : 0,
                pointBackgroundColor: color,
                pointBorderColor: color,
                borderWidth: 2.5,
                yAxisID: `y${i}`,
            };
        }),
    }), [selectedIds, sensorData, availableSensors]);

    /* ── Chart options ── */

    const chartWindow = useMemo(() => {
        if (historyRange === 0) return {};
        const timestamps = selectedIds.flatMap((sensorId) => sensorData[sensorId]?.map((point) => point.x) ?? []);
        if (timestamps.length === 0) return {};
        const max = Math.max(...timestamps);
        return { min: max - historyRange * 3600000, max };
    }, [historyRange, selectedIds, sensorData]);

    const chartOptions = useMemo<ChartOptions<'line'>>(() => {
        const scales: NonNullable<ChartOptions<'line'>['scales']> = {
            x: {
                type: 'linear' as const,
                grid: { color: 'rgba(255,255,255,0.04)' },
                ticks: {
                    color: '#778da9', maxRotation: 0, autoSkip: true, maxTicksLimit: 7,
                    callback: (value: string | number) => {
                        const d = new Date(value);
                        return historyRange > 48
                            ? d.toLocaleDateString([], { month: 'short', day: 'numeric' })
                            : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                    },
                },
                min: chartWindow.min,
                max: chartWindow.max,
            },
        };

        selectedIds.forEach((sId, i) => {
            const sensor = availableSensors.find(s => s.id === sId);
            const color = SENSOR_COLORS[i];
            scales[`y${i}`] = {
                type: 'linear' as const,
                position: i % 2 === 0 ? 'left' : 'right',
                display: true,
                grid: { color: i === 0 ? 'rgba(255,255,255,0.06)' : 'transparent', drawOnChartArea: i === 0 },
                ticks: { color, font: { size: 11 }, count: 6 },
                title: {
                    display: true,
                    text: sensor ? (sensor.unit ? `${sensor.label} (${sensor.unit})` : sensor.label) : '',
                    color, font: { size: 11, weight: 600 as const },
                },
            };
        });

        return {
            responsive: true, maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' as const },
            plugins: {
                legend: {
                    display: true, position: 'top' as const,
                    labels: { color: '#e0e1dd', boxWidth: 12, font: { size: 12 }, usePointStyle: true },
                },
                tooltip: {
                    backgroundColor: 'rgba(13, 27, 42, 0.95)',
                    borderColor: 'rgba(255,255,255,0.1)',
                    borderWidth: 1,
                    titleColor: '#e0e1dd',
                    bodyColor: '#e0e1dd',
                    callbacks: {
                        label: (ctx: TooltipItem<'line'>) => {
                            const value = ctx.parsed.y ?? 0;
                            return `${ctx.dataset.label}: ${value.toFixed(2)}`;
                        },
                        title: (ctx: TooltipItem<'line'>[]) => new Date(ctx[0]?.parsed.x ?? 0).toLocaleString(),
                    },
                },
            },
            scales,
        };
    }, [selectedIds, availableSensors, historyRange, chartWindow]);

    /* ── Correlation ── */

    const correlations = useMemo(() => {
        if (selectedIds.length < 2) return [];
        const pairs: { labelA: string; labelB: string; r: number }[] = [];
        for (let i = 0; i < selectedIds.length; i++) {
            for (let j = i + 1; j < selectedIds.length; j++) {
                const a = availableSensors.find(s => s.id === selectedIds[i]);
                const b = availableSensors.find(s => s.id === selectedIds[j]);
                const r = computeCorrelation(sensorData[selectedIds[i]] || [], sensorData[selectedIds[j]] || []);
                pairs.push({ labelA: a?.label || selectedIds[i], labelB: b?.label || selectedIds[j], r });
            }
        }
        return pairs;
    }, [selectedIds, sensorData, availableSensors]);

    /* ── Handlers ── */

    const toggleSensor = (id: string) => {
        setSelectedIds(prev => {
            if (prev.includes(id)) return prev.filter(s => s !== id);
            if (prev.length >= MAX_SENSORS) return prev;
            return [...prev, id];
        });
    };

    /* ── Render helpers ── */

    const renderGroup = (groupLabel: string, groupKey: string) => {
        const sensors = availableSensors.filter(s => s.group === groupKey);
        if (sensors.length === 0) return null;
        return (
            <div key={groupKey} style={{ marginBottom: '0.75rem' }}>
                <span style={{ fontSize: '0.65rem', fontWeight: 700, color: '#778da9', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.4rem', display: 'block' }}>
                    {groupLabel}
                </span>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
                    {sensors.map(sensor => {
                        const selIndex = selectedIds.indexOf(sensor.id);
                        const isSelected = selIndex !== -1;
                        const color = isSelected ? SENSOR_COLORS[selIndex] : undefined;
                        const disabled = !isSelected && selectedIds.length >= MAX_SENSORS;

                        return (
                            <button
                                key={sensor.id}
                                onClick={() => !disabled && toggleSensor(sensor.id)}
                                style={{
                                    display: 'flex', alignItems: 'center', gap: '0.35rem',
                                    padding: '0.35rem 0.75rem', borderRadius: '20px', cursor: disabled ? 'not-allowed' : 'pointer',
                                    fontSize: '0.8rem', fontWeight: 500, transition: 'all 0.2s',
                                    border: `1.5px solid ${isSelected ? color : 'rgba(255,255,255,0.08)'}`,
                                    background: isSelected ? `${color}15` : 'rgba(255,255,255,0.03)',
                                    color: isSelected ? color : disabled ? '#4a5568' : '#b0bec5',
                                    opacity: disabled ? 0.4 : 1,
                                }}
                            >
                                {isSelected && <Check size={13} strokeWidth={3} />}
                                {sensor.label}
                                {sensor.unit && <span style={{ fontSize: '0.7rem', opacity: 0.6 }}>{sensor.unit}</span>}
                            </button>
                        );
                    })}
                </div>
            </div>
        );
    };

    /* ── Render ── */

    const SUB_VIEWS = [
        { id: 'compare' as const, label: 'Compare', icon: <TrendingUp size={15} /> },
        { id: 'heatmap' as const, label: 'Heatmap', icon: <Grid3X3 size={15} /> },
        { id: 'anomalies' as const, label: 'Anomalies', icon: <AlertTriangle size={15} /> },
        { id: 'daynight' as const, label: 'Day/Night', icon: <Sun size={15} /> },
        { id: 'roc' as const, label: 'Rate of Change', icon: <Activity size={15} /> },
    ];

    return (
        <div className={styles.missionControl}>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <div style={{ width: 44, height: 44, borderRadius: '12px', background: 'rgba(168, 85, 247, 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <TrendingUp size={24} style={{ color: '#a855f7' }} />
                    </div>
                    <div>
                        <h2 style={{ margin: 0, fontSize: '1.5rem', color: '#e0e1dd' }}>Analytics</h2>
                        <p style={{ margin: 0, fontSize: '0.8rem', color: '#778da9' }}>Compare sensors and discover correlations</p>
                    </div>
                </div>
                {activeView === 'compare' && selectedIds.length > 0 && (
                    <button
                        onClick={() => setSelectedIds([])}
                        style={{
                            display: 'flex', alignItems: 'center', gap: '0.4rem', padding: '0.4rem 0.8rem',
                            borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(255,255,255,0.03)',
                            color: '#778da9', fontSize: '0.8rem', cursor: 'pointer', fontWeight: 500, transition: 'all 0.2s',
                        }}
                    >
                        <RotateCcw size={14} /> Clear
                    </button>
                )}
            </div>

            {/* Sub-view navigation */}
            <div style={{ display: 'flex', gap: '0.35rem', marginTop: '1rem', overflowX: 'auto', paddingBottom: '0.25rem' }}>
                {SUB_VIEWS.map(view => (
                    <button
                        key={view.id}
                        onClick={() => setActiveView(view.id)}
                        style={{
                            display: 'flex', alignItems: 'center', gap: '0.4rem',
                            padding: '0.5rem 0.9rem', borderRadius: '10px', cursor: 'pointer',
                            fontSize: '0.78rem', fontWeight: 600, transition: 'all 0.2s', whiteSpace: 'nowrap',
                            border: `1.5px solid ${activeView === view.id ? '#a855f7' : 'rgba(255,255,255,0.06)'}`,
                            background: activeView === view.id ? 'rgba(168, 85, 247, 0.12)' : 'rgba(255,255,255,0.02)',
                            color: activeView === view.id ? '#c084fc' : '#778da9',
                        }}
                    >
                        {view.icon}
                        {view.label}
                    </button>
                ))}
            </div>

            {/* ── Compare View ── */}
            {activeView === 'compare' && (
                <>
                    {/* Sensor Picker */}
                    <section style={{ background: 'rgba(27, 38, 59, 0.4)', borderRadius: '1rem', padding: '1.25rem', border: '1px solid rgba(255,255,255,0.06)', marginTop: '1rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                            <span style={{ fontSize: '0.85rem', fontWeight: 600, color: '#e0e1dd' }}>
                                Select Sensors <span style={{ color: '#778da9', fontWeight: 400 }}>({selectedIds.length}/{MAX_SENSORS})</span>
                            </span>
                        </div>
                        {renderGroup('Tank Parameters', 'tank')}
                        {renderGroup('Room Environment', 'room')}
                        {renderGroup('Manual Tests', 'manual')}
                        {renderGroup('Custom Sensors', 'custom')}
                    </section>

                    {/* Time Range */}
                    {selectedIds.length > 0 && (
                        <div className={styles.rangeSelector} style={{ marginTop: '1rem' }}>
                            {rangeOptions.map(opt => (
                                <button
                                    key={opt.label}
                                    className={`${styles.rangeButton} ${historyRange === opt.hours ? styles.rangeActive : ''}`}
                                    onClick={() => setHistoryRange(opt.hours)}
                                >
                                    {opt.label}
                                </button>
                            ))}
                        </div>
                    )}

                    {/* Chart */}
                    <div style={{
                        marginTop: '1rem', background: 'rgba(27, 38, 59, 0.4)', borderRadius: '1rem',
                        border: '1px solid rgba(255,255,255,0.06)', padding: '1.25rem', position: 'relative',
                    }}>
                        {isLoading && (
                            <div style={{ position: 'absolute', top: 12, right: 16, fontSize: '0.7rem', color: '#a855f7', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.4rem', zIndex: 2 }}>
                                <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#a855f7', animation: 'pulse 1.5s infinite' }} />
                                Loading...
                            </div>
                        )}
                        {selectedIds.length > 0 ? (
                            <div style={{ height: 420 }}>
                                <Line data={chartData} options={chartOptions} />
                            </div>
                        ) : (
                            <div style={{ height: 350, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '0.75rem', color: '#778da9' }}>
                                <TrendingUp size={56} strokeWidth={1} style={{ opacity: 0.2 }} />
                                <h3 style={{ margin: 0, fontSize: '1.1rem', color: '#e0e1dd', fontWeight: 500 }}>Select sensors to compare</h3>
                                <p style={{ margin: 0, fontSize: '0.8rem', maxWidth: 360, textAlign: 'center', lineHeight: 1.5 }}>
                                    Choose 2–4 sensors from the picker above to overlay their data on a single chart and see correlation coefficients.
                                </p>
                            </div>
                        )}
                    </div>

                    {/* Correlation Panel */}
                    {correlations.length > 0 && (
                        <section style={{ marginTop: '1rem' }}>
                            <h3 style={{ fontSize: '1rem', fontWeight: 600, color: '#e0e1dd', margin: '0 0 0.75rem 0' }}>
                                Correlations
                            </h3>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '0.75rem' }}>
                                {correlations.map((pair, i) => {
                                    const info = correlationInfo(pair.r);
                                    const rDisplay = isNaN(pair.r) ? '—' : (pair.r >= 0 ? '+' : '') + pair.r.toFixed(3);
                                    const barWidth = isNaN(pair.r) ? 0 : Math.abs(pair.r) * 100;

                                    return (
                                        <div key={i} style={{
                                            background: 'rgba(27, 38, 59, 0.6)', borderRadius: '1rem', padding: '1.25rem',
                                            border: `1px solid ${info.color}25`, display: 'flex', flexDirection: 'column', gap: '0.6rem',
                                        }}>
                                            <div style={{ fontSize: '0.75rem', color: '#778da9', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                                                {pair.labelA} <span style={{ color: '#4a5568' }}>↔</span> {pair.labelB}
                                            </div>
                                            <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.5rem' }}>
                                                <span style={{ fontSize: '1.75rem', fontWeight: 700, color: info.color, fontFamily: 'monospace' }}>
                                                    {rDisplay}
                                                </span>
                                                <span style={{ fontSize: '0.7rem', color: '#778da9' }}>Pearson R</span>
                                            </div>
                                            <div style={{ height: 4, borderRadius: 4, background: 'rgba(255,255,255,0.06)', overflow: 'hidden' }}>
                                                <div style={{ height: '100%', width: `${barWidth}%`, borderRadius: 4, background: info.color, transition: 'width 0.5s ease' }} />
                                            </div>
                                            <div>
                                                <span style={{ fontSize: '0.8rem', fontWeight: 600, color: info.color }}>{info.label}</span>
                                                <span style={{ fontSize: '0.7rem', color: '#778da9', marginLeft: '0.5rem' }}>{info.desc}</span>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </section>
                    )}
                </>
            )}

            {/* ── Heatmap View ── */}
            {activeView === 'heatmap' && (
                <div style={{ marginTop: '1rem' }}>
                    <CorrelationHeatmap />
                </div>
            )}

            {/* ── Anomalies View ── */}
            {activeView === 'anomalies' && (
                <div style={{ marginTop: '1rem' }}>
                    <AnomalyTimeline />
                </div>
            )}

            {/* ── Day/Night View ── */}
            {activeView === 'daynight' && (
                <div style={{ marginTop: '1rem' }}>
                    <DayNightAnalysis />
                </div>
            )}

            {/* ── Rate of Change View ── */}
            {activeView === 'roc' && (
                <div style={{ marginTop: '1rem' }}>
                    <RateOfChangeChart />
                </div>
            )}
        </div>
    );
};
