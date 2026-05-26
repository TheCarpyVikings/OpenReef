'use client';

import React, { useState, useMemo, useEffect } from 'react';
import styles from '@/app/dashboard.module.css';
import { useSettings } from '@/context/SettingsContext';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import { Line } from 'react-chartjs-2';
import type { ChartOptions, TooltipItem } from 'chart.js';
import { HelpCircle, Info, Check, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { historyResponseToPoints } from '@/lib/ha-history';
import type { DataPoint } from '@/types/reef';

const SENSOR_COLORS = ['#f43f5e', '#3b82f6', '#10b981', '#f59e0b'];
const MAX_SENSORS = 3;

/* ── Rate of change thresholds (units per hour) ── */
const ROC_THRESHOLDS: Record<string, { normal: number; warning: number; unit: string }> = {
    temp: { normal: 0.3, warning: 0.5, unit: '°C/hr' },
    ph: { normal: 0.03, warning: 0.06, unit: '/hr' },
    salinity: { normal: 0.2, warning: 0.5, unit: 'ppt/hr' },
    orp: { normal: 10, warning: 25, unit: 'mV/hr' },
    do: { normal: 0.3, warning: 0.5, unit: 'mg/L/hr' },
    co2: { normal: 50, warning: 100, unit: 'ppm/hr' },
    humidity: { normal: 3, warning: 6, unit: '%/hr' },
    room_temp: { normal: 0.5, warning: 1, unit: '°C/hr' },
};

interface SensorDef {
    id: string;
    label: string;
    entityId: string;
    unit: string;
}

export const RateOfChangeChart: React.FC = () => {
    const { settings, getLabel } = useSettings();
    const { fetchHistory } = useHomeAssistant();

    const [selectedIds, setSelectedIds] = useState<string[]>([]);
    const [sensorData, setSensorData] = useState<Record<string, DataPoint[]>>({});
    const [isLoading, setIsLoading] = useState(false);
    const [rangeHours, setRangeHours] = useState(24);

    /* ── Sensor list ── */
    const sensors = useMemo((): SensorDef[] => {
        const list: SensorDef[] = [];
        const tankKeys: { id: string; key: keyof typeof settings.entities.tank; unit: string }[] = [
            { id: 'temp', key: 'temp', unit: '°C' }, { id: 'ph', key: 'ph', unit: '' },
            { id: 'salinity', key: 'salinity', unit: 'ppt' }, { id: 'orp', key: 'orp', unit: 'mV' },
            { id: 'do', key: 'do', unit: 'mg/L' },
        ];
        tankKeys.forEach(s => {
            const eid = settings.entities.tank[s.key];
            if (eid) list.push({ id: s.id, label: getLabel(s.id, s.id), entityId: eid, unit: s.unit });
        });
        const roomKeys: { id: string; key: keyof typeof settings.entities.room; unit: string }[] = [
            { id: 'room_temp', key: 'temp', unit: '°C' }, { id: 'co2', key: 'co2', unit: 'ppm' },
            { id: 'humidity', key: 'humidity', unit: '%' },
        ];
        roomKeys.forEach(s => {
            const eid = settings.entities.room?.[s.key];
            if (eid) list.push({ id: s.id, label: getLabel(s.id, s.id), entityId: eid, unit: s.unit });
        });
        return list;
    }, [settings, getLabel]);

    /* ── Fetch ── */
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
                const sensor = sensors.find(s => s.id === sId);
                if (!sensor) continue;
                try {
                    const data = await fetchHistory(sensor.entityId, rangeHours);
                    if (data && !cancelled) {
                        result[sId] = historyResponseToPoints(data, sensor.entityId, {
                            rangeHours,
                            includeBounds: false,
                        });
                    }
                } catch (err) { console.error(`RoC: Failed ${sId}:`, err); }
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
    }, [selectedIds, rangeHours, sensors, fetchHistory]);

    /* ── Compute rate of change (derivative smoothed with SMA) ── */
    const derivativeData = useMemo(() => {
        const result: Record<string, { x: number; y: number }[]> = {};

        for (const sId of selectedIds) {
            const raw = sensorData[sId] || [];
            if (raw.length < 3) { result[sId] = []; continue; }

            // Compute raw derivative (units per hour)
            const rawDerivative: { x: number; y: number }[] = [];
            for (let i = 1; i < raw.length; i++) {
                const dt = (raw[i].x - raw[i - 1].x) / 3600000; // hours
                if (dt < 0.001) continue; // skip duplicates
                const dy = raw[i].y - raw[i - 1].y;
                rawDerivative.push({ x: (raw[i].x + raw[i - 1].x) / 2, y: dy / dt });
            }

            // SMA smoothing (window = ~10 points or 5% of data)
            const window = Math.max(5, Math.floor(rawDerivative.length * 0.05));
            const smoothed: { x: number; y: number }[] = [];
            for (let i = 0; i < rawDerivative.length; i++) {
                const start = Math.max(0, i - Math.floor(window / 2));
                const end = Math.min(rawDerivative.length, i + Math.floor(window / 2) + 1);
                let sum = 0;
                for (let j = start; j < end; j++) sum += rawDerivative[j].y;
                smoothed.push({ x: rawDerivative[i].x, y: sum / (end - start) });
            }

            result[sId] = smoothed;
        }

        return result;
    }, [selectedIds, sensorData]);

    /* ── Current status for each sensor ── */
    const currentStatus = useMemo(() => {
        return selectedIds.map(sId => {
            const data = derivativeData[sId] || [];
            const sensor = sensors.find(s => s.id === sId);
            if (data.length === 0) return { id: sId, label: sensor?.label || sId, rate: 0, status: 'stable' as const, statusColor: '#778da9' };

            const recent = data.slice(-5);
            const avgRate = recent.reduce((sum, p) => sum + p.y, 0) / recent.length;
            const absRate = Math.abs(avgRate);
            const threshold = ROC_THRESHOLDS[sId];

            let status: 'stable' | 'normal' | 'fast' | 'concerning';
            let statusColor: string;

            if (!threshold) {
                status = absRate < 0.01 ? 'stable' : 'normal';
                statusColor = '#778da9';
            } else if (absRate >= threshold.warning) {
                status = 'concerning';
                statusColor = '#ef4444';
            } else if (absRate >= threshold.normal) {
                status = 'fast';
                statusColor = '#fbbf24';
            } else if (absRate > threshold.normal * 0.1) {
                status = 'normal';
                statusColor = '#4ade80';
            } else {
                status = 'stable';
                statusColor = '#778da9';
            }

            return { id: sId, label: sensor?.label || sId, rate: avgRate, status, statusColor, unit: threshold?.unit || '/hr' };
        });
    }, [selectedIds, derivativeData, sensors]);

    const chartWindow = useMemo(() => {
        const timestamps = selectedIds.flatMap((sensorId) => derivativeData[sensorId]?.map((point) => point.x) ?? []);
        if (timestamps.length === 0) return {};
        const max = Math.max(...timestamps);
        return { min: max - rangeHours * 3600000, max };
    }, [selectedIds, derivativeData, rangeHours]);

    /* ── Chart data ── */
    const chartData = useMemo(() => ({
        datasets: selectedIds.map((sId, i) => {
            const sensor = sensors.find(s => s.id === sId);
            const color = SENSOR_COLORS[i];
            const roc = ROC_THRESHOLDS[sId];
            return {
                label: `${sensor?.label || sId} (${roc?.unit || '/hr'})`,
                data: derivativeData[sId] || [],
                borderColor: color,
                backgroundColor: `${color}15`,
                fill: true,
                tension: 0.4,
                pointRadius: 0,
                borderWidth: 2,
                yAxisID: `y${i}`,
            };
        }),
    }), [selectedIds, derivativeData, sensors]);

    const chartOptions = useMemo<ChartOptions<'line'>>(() => {
        const scales: NonNullable<ChartOptions<'line'>['scales']> = {
            x: {
                type: 'linear' as const,
                grid: { color: 'rgba(255,255,255,0.04)' },
                ticks: {
                    color: '#778da9', maxRotation: 0, autoSkip: true, maxTicksLimit: 7,
                    callback: (value: string | number) => {
                        const d = new Date(value);
                        return rangeHours > 48
                            ? d.toLocaleDateString([], { month: 'short', day: 'numeric' })
                            : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                    },
                },
                min: chartWindow.min,
                max: chartWindow.max,
            },
        };

        selectedIds.forEach((sId, i) => {
            const sensor = sensors.find(s => s.id === sId);
            const color = SENSOR_COLORS[i];
            scales[`y${i}`] = {
                type: 'linear' as const,
                position: i % 2 === 0 ? 'left' : 'right',
                grid: { color: i === 0 ? 'rgba(255,255,255,0.06)' : 'transparent', drawOnChartArea: i === 0 },
                ticks: { color, font: { size: 11 } },
                title: {
                    display: true,
                    text: `${sensor?.label || sId} (${ROC_THRESHOLDS[sId]?.unit || '/hr'})`,
                    color, font: { size: 11, weight: 600 as const },
                },
            };
        });

        return {
            responsive: true, maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' as const },
            plugins: {
                legend: {
                    display: selectedIds.length > 1,
                    position: 'top' as const,
                    labels: { color: '#e0e1dd', boxWidth: 12, font: { size: 12 }, usePointStyle: true },
                },
                tooltip: {
                    backgroundColor: 'rgba(13, 27, 42, 0.95)',
                    titleColor: '#e0e1dd', bodyColor: '#e0e1dd',
                    callbacks: {
                        label: (ctx: TooltipItem<'line'>) => {
                            const value = ctx.parsed.y ?? 0;
                            return `${ctx.dataset.label}: ${value >= 0 ? '+' : ''}${value.toFixed(4)}`;
                        },
                        title: (ctx: TooltipItem<'line'>[]) => new Date(ctx[0]?.parsed.x ?? 0).toLocaleString(),
                    },
                },
                annotation: undefined, // zero line handled by grid
            },
            scales,
        };
    }, [selectedIds, sensors, rangeHours, chartWindow]);

    const toggleSensor = (id: string) => {
        setSelectedIds(prev => {
            if (prev.includes(id)) return prev.filter(s => s !== id);
            if (prev.length >= MAX_SENSORS) return prev;
            return [...prev, id];
        });
    };

    return (
        <div>
            {/* Beginner explanation */}
            <div style={{ background: 'rgba(168, 85, 247, 0.06)', border: '1px solid rgba(168, 85, 247, 0.15)', borderRadius: '12px', padding: '1rem 1.25rem', marginBottom: '1rem', display: 'flex', gap: '0.75rem', alignItems: 'flex-start' }}>
                <HelpCircle size={20} style={{ color: '#a855f7', flexShrink: 0, marginTop: 2 }} />
                <div style={{ fontSize: '0.8rem', color: '#b0bec5', lineHeight: 1.6 }}>
                    <strong style={{ color: '#e0e1dd' }}>What is this?</strong> Instead of showing the actual values, this shows <strong>how fast</strong> each parameter is changing. The line above zero means it&apos;s rising; below zero means it&apos;s falling. A flat line near zero means the parameter is stable — which is usually what you want in a reef tank.
                </div>
            </div>

            {/* Sensor picker */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginBottom: '1rem' }}>
                {sensors.map(sensor => {
                    const selIndex = selectedIds.indexOf(sensor.id);
                    const isSelected = selIndex !== -1;
                    const color = isSelected ? SENSOR_COLORS[selIndex] : undefined;
                    const disabled = !isSelected && selectedIds.length >= MAX_SENSORS;

                    return (
                        <button key={sensor.id} onClick={() => !disabled && toggleSensor(sensor.id)} style={{
                            display: 'flex', alignItems: 'center', gap: '0.35rem',
                            padding: '0.35rem 0.75rem', borderRadius: '20px', cursor: disabled ? 'not-allowed' : 'pointer',
                            fontSize: '0.8rem', fontWeight: 500, transition: 'all 0.2s',
                            border: `1.5px solid ${isSelected ? color : 'rgba(255,255,255,0.08)'}`,
                            background: isSelected ? `${color}15` : 'rgba(255,255,255,0.03)',
                            color: isSelected ? color : disabled ? '#4a5568' : '#b0bec5',
                            opacity: disabled ? 0.4 : 1,
                        }}>
                            {isSelected && <Check size={13} strokeWidth={3} />}
                            {sensor.label}
                        </button>
                    );
                })}
            </div>

            {/* Time range */}
            {selectedIds.length > 0 && (
                <div className={styles.rangeSelector} style={{ marginBottom: '1rem' }}>
                    {[{ label: '1H', h: 1 }, { label: '6H', h: 6 }, { label: '24H', h: 24 }, { label: '7D', h: 168 }].map(opt => (
                        <button key={opt.label} className={`${styles.rangeButton} ${rangeHours === opt.h ? styles.rangeActive : ''}`} onClick={() => setRangeHours(opt.h)}>
                            {opt.label}
                        </button>
                    ))}
                </div>
            )}

            {/* Current rate status cards */}
            {currentStatus.length > 0 && (
                <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.min(3, currentStatus.length)}, 1fr)`, gap: '0.75rem', marginBottom: '1rem' }}>
                    {currentStatus.map(s => (
                        <div key={s.id} style={{
                            background: 'rgba(27, 38, 59, 0.5)', borderRadius: '12px', padding: '1rem',
                            border: `1px solid ${s.statusColor}25`, textAlign: 'center',
                        }}>
                            <div style={{ fontSize: '0.7rem', fontWeight: 700, color: '#778da9', textTransform: 'uppercase', marginBottom: '0.5rem' }}>{s.label}</div>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.35rem', marginBottom: '0.25rem' }}>
                                {s.rate > 0.001 ? <TrendingUp size={18} style={{ color: s.statusColor }} /> : s.rate < -0.001 ? <TrendingDown size={18} style={{ color: s.statusColor }} /> : <Minus size={18} style={{ color: s.statusColor }} />}
                                <span style={{ fontSize: '1.25rem', fontWeight: 700, fontFamily: 'monospace', color: s.statusColor }}>
                                    {s.rate >= 0 ? '+' : ''}{s.rate.toFixed(4)}
                                </span>
                            </div>
                            <div style={{ fontSize: '0.7rem', color: '#778da9' }}>{s.unit}</div>
                            <div style={{ fontSize: '0.7rem', fontWeight: 600, color: s.statusColor, marginTop: '0.35rem', textTransform: 'capitalize' }}>
                                {s.status === 'stable' ? '● Stable' : s.status === 'normal' ? '● Normal change' : s.status === 'fast' ? '⚠ Changing fast' : '⚠ Concerning rate'}
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Chart */}
            <div style={{ background: 'rgba(27, 38, 59, 0.4)', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.06)', padding: '1.25rem' }}>
                {selectedIds.length > 0 ? (
                    <>
                        {isLoading && <div style={{ fontSize: '0.75rem', color: '#a855f7', marginBottom: '0.5rem' }}>Loading...</div>}
                        <div style={{ height: 360 }}>
                            <Line data={chartData} options={chartOptions} />
                        </div>
                    </>
                ) : (
                    <div style={{ height: 300, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '0.75rem', color: '#778da9' }}>
                        <TrendingUp size={48} strokeWidth={1} style={{ opacity: 0.2 }} />
                        <p style={{ margin: 0, fontSize: '0.85rem', color: '#e0e1dd' }}>Select sensors to see their rate of change</p>
                        <p style={{ margin: 0, fontSize: '0.75rem' }}>This shows how fast values are rising or falling</p>
                    </div>
                )}
            </div>

            {/* Concerning rate alert */}
            {currentStatus.some(s => s.status === 'concerning') && (
                <div style={{ marginTop: '1rem', background: 'rgba(239, 68, 68, 0.06)', border: '1px solid rgba(239, 68, 68, 0.2)', borderRadius: '12px', padding: '1rem 1.25rem', display: 'flex', gap: '0.75rem', alignItems: 'flex-start' }}>
                    <Info size={18} style={{ color: '#ef4444', flexShrink: 0, marginTop: 2 }} />
                    <div style={{ fontSize: '0.8rem', color: '#b0bec5', lineHeight: 1.5 }}>
                        <strong style={{ color: '#ef4444' }}>Rapid change detected:</strong>{' '}
                        {currentStatus.filter(s => s.status === 'concerning').map(s => s.label).join(', ')} {currentStatus.filter(s => s.status === 'concerning').length === 1 ? 'is' : 'are'} changing faster than usual. This could indicate equipment issues (heater stuck, ATO malfunction) or environmental changes. Check your equipment is working correctly.
                    </div>
                </div>
            )}
        </div>
    );
};
