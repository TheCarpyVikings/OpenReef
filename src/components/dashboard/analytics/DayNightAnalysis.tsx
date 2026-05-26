'use client';

import React, { useState, useMemo, useEffect } from 'react';
import { useSettings } from '@/context/SettingsContext';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import { Line } from 'react-chartjs-2';
import { Sun, Moon, HelpCircle, Info, ArrowUpDown } from 'lucide-react';
import { historyResponseToPoints } from '@/lib/ha-history';
import type { DataPoint } from '@/types/reef';

/* ── Beginner explanations for diurnal patterns ── */
const DIURNAL_TIPS: Record<string, string> = {
    ph: 'pH is naturally higher during the day because corals and algae photosynthesize, consuming CO₂. At night, everything respires, producing CO₂ which lowers pH. A swing of 0.1–0.3 is normal. Swings over 0.4 may stress livestock.',
    temp: 'Temperature often rises slightly during the day due to lighting and room heat, then drops at night. A swing of 0.5–1°C is normal. Larger swings suggest your heater or room temperature needs attention.',
    do: 'Dissolved oxygen is higher during the day (photosynthesis produces O₂) and lower at night (everything consumes O₂). This is completely natural. Ensure good surface agitation for nighttime oxygen.',
    orp: 'ORP tends to be higher during the day and lower at night. This follows the same photosynthesis/respiration cycle as pH. Consistent patterns indicate a healthy, stable system.',
    co2: 'Room CO₂ tends to be higher at night (less ventilation, more human breathing) and lower during the day. This directly affects your tank pH — high CO₂ pushes pH down.',
    humidity: 'Humidity may vary with room ventilation patterns. Day vs night differences are usually driven by whether windows are open, HVAC running, or evaporation rates changing.',
    room_temp: 'Room temperature follows your home heating/cooling schedule. Stable room temperature helps maintain stable tank temperature.',
    salinity: 'Salinity shouldn\'t change much between day and night. If it does, check your ATO (auto top-off) — it may be running more during the day due to higher evaporation from lights.',
};

interface SensorOption {
    id: string;
    label: string;
    entityId: string;
}

export const DayNightAnalysis: React.FC = () => {
    const { settings, getLabel } = useSettings();
    const { fetchHistory } = useHomeAssistant();

    const [selectedSensor, setSelectedSensor] = useState<string>('');
    const [historyData, setHistoryData] = useState<DataPoint[]>([]);
    const [isLoading, setIsLoading] = useState(false);

    /* ── Sensor list ── */
    const sensors = useMemo((): SensorOption[] => {
        const list: SensorOption[] = [];
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
        return list;
    }, [settings, getLabel]);

    // Auto-select first sensor
    useEffect(() => {
        if (selectedSensor || sensors.length === 0) return;
        const timeout = window.setTimeout(() => setSelectedSensor(sensors[0].id), 0);
        return () => window.clearTimeout(timeout);
    }, [sensors, selectedSensor]);

    /* ── Fetch 7 days of data ── */
    useEffect(() => {
        const sensor = sensors.find(s => s.id === selectedSensor);
        if (!sensor) return;
        let cancelled = false;
        const doFetch = async () => {
            setIsLoading(true);
            try {
                const data = await fetchHistory(sensor.entityId, 168);
                if (data && !cancelled) {
                    setHistoryData(historyResponseToPoints(data, sensor.entityId, {
                        rangeHours: 168,
                        includeBounds: false,
                    }));
                }
            } catch (err) { console.error('DayNight fetch err:', err); }
            if (!cancelled) setIsLoading(false);
        };
        const timeout = window.setTimeout(() => {
            void doFetch();
        }, 0);
        return () => {
            cancelled = true;
            window.clearTimeout(timeout);
        };
    }, [selectedSensor, sensors, fetchHistory]);

    /* ── Light schedule (derived from lighting.schedule, defaults to 8am-8pm) ── */
    const lightSchedule = useMemo(() => {
        const schedule = settings.lighting?.schedule;
        if (!schedule || schedule.length === 0) return { onHour: 8, offHour: 20 };

        // Find first entry where any non-moonlight channel > 0
        let onHour = 8, offHour = 20;
        const lightsOnEntries = schedule.filter(entry => {
            return Object.entries(entry.values).some(([key, val]) => key !== 'moonlight' && val > 0);
        });

        if (lightsOnEntries.length > 0) {
            onHour = parseInt(lightsOnEntries[0].time.split(':')[0], 10);
            offHour = parseInt(lightsOnEntries[lightsOnEntries.length - 1].time.split(':')[0], 10);
        }

        return { onHour, offHour };
    }, [settings]);

    /* ── Compute day/night stats ── */
    const analysis = useMemo(() => {
        if (historyData.length === 0) return null;

        const dayValues: number[] = [];
        const nightValues: number[] = [];
        const hourlyBuckets: { sum: number; count: number }[] = Array.from({ length: 24 }, () => ({ sum: 0, count: 0 }));

        historyData.forEach(point => {
            const date = new Date(point.x);
            const hour = date.getHours();

            hourlyBuckets[hour].sum += point.y;
            hourlyBuckets[hour].count++;

            const isDay = lightSchedule.onHour < lightSchedule.offHour
                ? hour >= lightSchedule.onHour && hour < lightSchedule.offHour
                : hour >= lightSchedule.onHour || hour < lightSchedule.offHour;

            if (isDay) dayValues.push(point.y);
            else nightValues.push(point.y);
        });

        const avg = (arr: number[]) => arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0;
        const min = (arr: number[]) => arr.length ? Math.min(...arr) : 0;
        const max = (arr: number[]) => arr.length ? Math.max(...arr) : 0;

        const dayAvg = avg(dayValues);
        const nightAvg = avg(nightValues);

        return {
            day: { avg: dayAvg, min: min(dayValues), max: max(dayValues), count: dayValues.length },
            night: { avg: nightAvg, min: min(nightValues), max: max(nightValues), count: nightValues.length },
            swing: Math.abs(dayAvg - nightAvg),
            hourlyProfile: hourlyBuckets.map((b, h) => ({ hour: h, avg: b.count > 0 ? b.sum / b.count : null })),
        };
    }, [historyData, lightSchedule]);

    /* ── 24h profile chart data ── */
    const profileChartData = useMemo(() => {
        if (!analysis) return { datasets: [] };
        const { onHour, offHour } = lightSchedule;

        return {
            labels: analysis.hourlyProfile.map(h => `${h.hour.toString().padStart(2, '0')}:00`),
            datasets: [{
                label: sensors.find(s => s.id === selectedSensor)?.label || selectedSensor,
                data: analysis.hourlyProfile.map(h => h.avg),
                borderColor: '#a855f7',
                backgroundColor: analysis.hourlyProfile.map(h => {
                    const isDay = onHour < offHour
                        ? h.hour >= onHour && h.hour < offHour
                        : h.hour >= onHour || h.hour < offHour;
                    return isDay ? 'rgba(251, 191, 36, 0.15)' : 'rgba(96, 165, 250, 0.10)';
                }),
                fill: true,
                tension: 0.4,
                pointRadius: 4,
                pointBackgroundColor: '#a855f7',
                borderWidth: 2.5,
            }],
        };
    }, [analysis, lightSchedule, selectedSensor, sensors]);

    const profileChartOptions = useMemo(() => ({
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: 'rgba(13, 27, 42, 0.95)',
                titleColor: '#e0e1dd', bodyColor: '#e0e1dd',
            },
        },
        scales: {
            x: {
                grid: { color: 'rgba(255,255,255,0.04)' },
                ticks: { color: '#778da9', maxRotation: 45, font: { size: 10 } },
            },
            y: {
                grid: { color: 'rgba(255,255,255,0.06)' },
                ticks: { color: '#778da9', font: { size: 11 } },
            },
        },
    }), []);

    const tip = DIURNAL_TIPS[selectedSensor] || null;

    return (
        <div>
            {/* Beginner explanation */}
            <div style={{ background: 'rgba(168, 85, 247, 0.06)', border: '1px solid rgba(168, 85, 247, 0.15)', borderRadius: '12px', padding: '1rem 1.25rem', marginBottom: '1rem', display: 'flex', gap: '0.75rem', alignItems: 'flex-start' }}>
                <HelpCircle size={20} style={{ color: '#a855f7', flexShrink: 0, marginTop: 2 }} />
                <div style={{ fontSize: '0.8rem', color: '#b0bec5', lineHeight: 1.6 }}>
                    <strong style={{ color: '#e0e1dd' }}>What is this?</strong> Reef tanks have natural day/night cycles. This view splits your sensor data by your light schedule ({lightSchedule.onHour}:00–{lightSchedule.offHour}:00) to show how parameters change between <Sun size={12} style={{ display: 'inline', verticalAlign: 'middle', color: '#fbbf24' }} /> day and <Moon size={12} style={{ display: 'inline', verticalAlign: 'middle', color: '#60a5fa' }} /> night.
                </div>
            </div>

            {/* Sensor selector */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginBottom: '1rem' }}>
                {sensors.map(s => (
                    <button key={s.id} onClick={() => setSelectedSensor(s.id)} style={{
                        padding: '0.4rem 0.8rem', borderRadius: '20px', fontSize: '0.8rem', fontWeight: 500, cursor: 'pointer', transition: 'all 0.2s',
                        border: `1.5px solid ${selectedSensor === s.id ? '#a855f7' : 'rgba(255,255,255,0.08)'}`,
                        background: selectedSensor === s.id ? 'rgba(168, 85, 247, 0.15)' : 'rgba(255,255,255,0.03)',
                        color: selectedSensor === s.id ? '#a855f7' : '#b0bec5',
                    }}>
                        {s.label}
                    </button>
                ))}
            </div>

            {isLoading ? (
                <div style={{ textAlign: 'center', padding: '3rem', color: '#778da9', fontSize: '0.85rem' }}>Analysing day/night patterns...</div>
            ) : analysis ? (
                <>
                    {/* Day vs Night cards */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: '0.75rem', marginBottom: '1.25rem', alignItems: 'stretch' }}>
                        {/* Day card */}
                        <div style={{ background: 'rgba(251, 191, 36, 0.06)', border: '1px solid rgba(251, 191, 36, 0.15)', borderRadius: '12px', padding: '1.25rem', textAlign: 'center' }}>
                            <Sun size={28} style={{ color: '#fbbf24', marginBottom: '0.5rem' }} />
                            <div style={{ fontSize: '0.7rem', fontWeight: 700, color: '#fbbf24', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '0.75rem' }}>Daytime</div>
                            <div style={{ fontSize: '2rem', fontWeight: 700, color: '#e0e1dd', fontFamily: 'monospace' }}>{analysis.day.avg.toFixed(2)}</div>
                            <div style={{ fontSize: '0.7rem', color: '#778da9', marginTop: '0.25rem' }}>avg</div>
                            <div style={{ display: 'flex', justifyContent: 'center', gap: '1rem', marginTop: '0.75rem', fontSize: '0.7rem', color: '#778da9' }}>
                                <span>Min <strong style={{ color: '#b0bec5' }}>{analysis.day.min.toFixed(2)}</strong></span>
                                <span>Max <strong style={{ color: '#b0bec5' }}>{analysis.day.max.toFixed(2)}</strong></span>
                            </div>
                        </div>

                        {/* Swing indicator */}
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '0.25rem', padding: '0 0.5rem' }}>
                            <ArrowUpDown size={20} style={{ color: '#778da9' }} />
                            <div style={{ fontSize: '1.1rem', fontWeight: 700, fontFamily: 'monospace', color: '#e0e1dd' }}>{analysis.swing.toFixed(3)}</div>
                            <div style={{ fontSize: '0.65rem', color: '#778da9', textAlign: 'center' }}>swing</div>
                        </div>

                        {/* Night card */}
                        <div style={{ background: 'rgba(96, 165, 250, 0.06)', border: '1px solid rgba(96, 165, 250, 0.15)', borderRadius: '12px', padding: '1.25rem', textAlign: 'center' }}>
                            <Moon size={28} style={{ color: '#60a5fa', marginBottom: '0.5rem' }} />
                            <div style={{ fontSize: '0.7rem', fontWeight: 700, color: '#60a5fa', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '0.75rem' }}>Nighttime</div>
                            <div style={{ fontSize: '2rem', fontWeight: 700, color: '#e0e1dd', fontFamily: 'monospace' }}>{analysis.night.avg.toFixed(2)}</div>
                            <div style={{ fontSize: '0.7rem', color: '#778da9', marginTop: '0.25rem' }}>avg</div>
                            <div style={{ display: 'flex', justifyContent: 'center', gap: '1rem', marginTop: '0.75rem', fontSize: '0.7rem', color: '#778da9' }}>
                                <span>Min <strong style={{ color: '#b0bec5' }}>{analysis.night.min.toFixed(2)}</strong></span>
                                <span>Max <strong style={{ color: '#b0bec5' }}>{analysis.night.max.toFixed(2)}</strong></span>
                            </div>
                        </div>
                    </div>

                    {/* Sensor-specific insight */}
                    {tip && (
                        <div style={{ background: 'rgba(74, 222, 128, 0.06)', border: '1px solid rgba(74, 222, 128, 0.15)', borderRadius: '12px', padding: '1rem 1.25rem', marginBottom: '1.25rem', display: 'flex', gap: '0.75rem', alignItems: 'flex-start' }}>
                            <Info size={18} style={{ color: '#4ade80', flexShrink: 0, marginTop: 2 }} />
                            <span style={{ fontSize: '0.8rem', color: '#b0bec5', lineHeight: 1.5 }}>{tip}</span>
                        </div>
                    )}

                    {/* 24-hour profile chart */}
                    <div style={{ background: 'rgba(27, 38, 59, 0.4)', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.06)', padding: '1.25rem' }}>
                        <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#e0e1dd', marginBottom: '0.75rem' }}>
                            24-Hour Average Profile <span style={{ fontWeight: 400, color: '#778da9', fontSize: '0.75rem' }}>(last 7 days)</span>
                        </div>
                        <div style={{ height: 280 }}>
                            <Line data={profileChartData} options={profileChartOptions} />
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'center', gap: '1.5rem', marginTop: '0.75rem' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.7rem', color: '#778da9' }}>
                                <div style={{ width: 12, height: 12, borderRadius: 3, background: 'rgba(251, 191, 36, 0.2)' }} /> Lights on
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.7rem', color: '#778da9' }}>
                                <div style={{ width: 12, height: 12, borderRadius: 3, background: 'rgba(96, 165, 250, 0.15)' }} /> Lights off
                            </div>
                        </div>
                    </div>
                </>
            ) : (
                <div style={{ textAlign: 'center', padding: '3rem', color: '#778da9' }}>Select a sensor above to see day/night analysis</div>
            )}
        </div>
    );
};
