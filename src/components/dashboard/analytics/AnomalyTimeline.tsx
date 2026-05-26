'use client';

import React, { useState, useMemo, useEffect } from 'react';
import styles from '@/app/dashboard.module.css';
import { useSettings } from '@/context/SettingsContext';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import { AlertTriangle, CheckCircle, HelpCircle, Info, Clock } from 'lucide-react';
import { historyResponseToPoints } from '@/lib/ha-history';
import type { DataPoint } from '@/types/reef';

interface SensorTimeline {
    id: string;
    label: string;
    segments: { start: number; end: number; inRange: boolean; avgVal?: number }[];
    anomalyCount: number;
    anomalyDuration: number; // ms
    totalDuration: number; // ms
}

// Beginner-friendly cause/action tips
const ANOMALY_TIPS: Record<string, { high: string; low: string }> = {
    temp: {
        high: 'Tank too warm. Common causes: room heat, faulty heater stuck on, lights too close. Action: check heater, increase airflow, consider a small fan on the sump.',
        low: 'Tank too cold. Common causes: cold room, heater off/broken, water change with cold water. Action: check heater is working and set correctly.',
    },
    ph: {
        high: 'pH too high. Common causes: excessive kalkwasser dosing, high alkalinity. Action: check your dosing schedule and test alkalinity.',
        low: 'pH too low. Common causes: high CO₂ in the room (poor ventilation), low alkalinity. Action: open a window, check your alkalinity levels, consider a CO₂ scrubber on your skimmer.',
    },
    salinity: {
        high: 'Salinity too high. Common causes: excessive evaporation without ATO running, salt creep. Action: check ATO is working, top off with fresh RODI water.',
        low: 'Salinity too low. Common causes: ATO overfilling, too much freshwater added. Action: check ATO float switch, add salt slowly.',
    },
    orp: {
        high: 'ORP very high. This is rare — could indicate oxidiser contamination. Action: do a water change and check for chemical contamination.',
        low: 'ORP low. Common causes: organic waste buildup, overfeeding, skimmer off. Action: check skimmer is running, reduce feeding, do a water change.',
    },
    do: {
        high: 'Dissolved oxygen high — this is generally fine and not a concern for reef tanks.',
        low: 'Dissolved oxygen low. Common causes: high temperature, overstocking, poor surface agitation. Action: increase flow at the surface, check wavemaker is running.',
    },
    co2: {
        high: 'Room CO₂ high. This will lower your tank pH. Common causes: poor room ventilation, people in the room. Action: open a window or add ventilation.',
        low: 'Room CO₂ low — this is good! Your pH will benefit from low ambient CO₂.',
    },
    humidity: {
        high: 'Room humidity high. Common causes: open-top tank evaporation, poor ventilation. Action: use a dehumidifier or improve room airflow.',
        low: 'Room humidity low — generally not an issue for aquariums.',
    },
    room_temp: {
        high: 'Room too warm — this will heat your tank. Action: use air conditioning or fans.',
        low: 'Room too cold — your heater has to work harder. Action: warm the room or insulate the tank.',
    },
};

export const AnomalyTimeline: React.FC = () => {
    const { settings, getLabel } = useSettings();
    const { fetchHistory } = useHomeAssistant();

    const [historyData, setHistoryData] = useState<Record<string, DataPoint[]>>({});
    const [isLoading, setIsLoading] = useState(false);
    const [rangeHours, setRangeHours] = useState(24);
    const [expandedSensor, setExpandedSensor] = useState<string | null>(null);

    /* ── Sensor list ── */
    const sensors = useMemo(() => {
        const list: { id: string; label: string; entityId: string }[] = [];
        const tankKeys: { id: string; key: keyof typeof settings.entities.tank }[] = [
            { id: 'temp', key: 'temp' }, { id: 'ph', key: 'ph' }, { id: 'salinity', key: 'salinity' },
            { id: 'orp', key: 'orp' }, { id: 'do', key: 'do' },
        ];
        tankKeys.forEach(s => {
            const eid = settings.entities.tank[s.key];
            if (eid && settings.thresholds[s.id]) list.push({ id: s.id, label: getLabel(s.id, s.id), entityId: eid });
        });
        const roomKeys: { id: string; key: keyof typeof settings.entities.room }[] = [
            { id: 'room_temp', key: 'temp' }, { id: 'co2', key: 'co2' }, { id: 'humidity', key: 'humidity' },
        ];
        roomKeys.forEach(s => {
            const eid = settings.entities.room?.[s.key];
            if (eid && settings.thresholds[s.id]) list.push({ id: s.id, label: getLabel(s.id, s.id), entityId: eid });
        });
        return list;
    }, [settings, getLabel]);

    /* ── Fetch ── */
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
                } catch (err) { console.error(`Anomaly: Failed ${sensor.id}:`, err); }
            }
            if (!cancelled) { setHistoryData(result); setIsLoading(false); }
        };
        fetchAll();
        return () => { cancelled = true; };
    }, [sensors, rangeHours, fetchHistory]);

    /* ── Build timelines ── */
    const timelines = useMemo((): SensorTimeline[] => {
        const timestamps = Object.values(historyData).flatMap((points) => points.map((point) => point.x));
        const now = timestamps.length > 0 ? Math.max(...timestamps) : 0;
        const start = now - rangeHours * 3600000;

        return sensors.map(sensor => {
            const data = historyData[sensor.id] || [];
            const threshold = settings.thresholds[sensor.id];
            if (!threshold || data.length === 0) {
                return { id: sensor.id, label: sensor.label, segments: [], anomalyCount: 0, anomalyDuration: 0, totalDuration: rangeHours * 3600000 };
            }

            const segments: SensorTimeline['segments'] = [];
            let currentInRange = data[0].y >= threshold.min && data[0].y <= threshold.max;
            let segStart = Math.max(data[0].x, start);
            let segValues: number[] = [data[0].y];

            for (let i = 1; i < data.length; i++) {
                const inRange = data[i].y >= threshold.min && data[i].y <= threshold.max;
                if (inRange !== currentInRange) {
                    segments.push({
                        start: segStart, end: data[i].x, inRange: currentInRange,
                        avgVal: segValues.reduce((a, b) => a + b, 0) / segValues.length,
                    });
                    segStart = data[i].x;
                    currentInRange = inRange;
                    segValues = [data[i].y];
                } else {
                    segValues.push(data[i].y);
                }
            }
            // Close final segment
            segments.push({
                start: segStart, end: now, inRange: currentInRange,
                avgVal: segValues.reduce((a, b) => a + b, 0) / segValues.length,
            });

            const anomalySegments = segments.filter(s => !s.inRange);
            const anomalyDuration = anomalySegments.reduce((sum, s) => sum + (s.end - s.start), 0);

            return {
                id: sensor.id, label: sensor.label, segments,
                anomalyCount: anomalySegments.length,
                anomalyDuration,
                totalDuration: now - start,
            };
        });
    }, [sensors, historyData, settings.thresholds, rangeHours]);

    const totalAnomalies = timelines.reduce((sum, t) => sum + t.anomalyCount, 0);
    const sensorsWithIssues = timelines.filter(t => t.anomalyCount > 0).length;

    const formatDuration = (ms: number): string => {
        const mins = Math.floor(ms / 60000);
        if (mins < 60) return `${mins}m`;
        const hrs = Math.floor(mins / 60);
        const remMins = mins % 60;
        if (hrs < 24) return remMins > 0 ? `${hrs}h ${remMins}m` : `${hrs}h`;
        const days = Math.floor(hrs / 24);
        return `${days}d ${hrs % 24}h`;
    };

    const getTip = (sensorId: string, avgVal: number): string | undefined => {
        const threshold = settings.thresholds[sensorId];
        if (!threshold) return undefined;
        const tips = ANOMALY_TIPS[sensorId];
        if (!tips) return undefined;
        return avgVal > threshold.max ? tips.high : tips.low;
    };

    return (
        <div>
            {/* Beginner explanation */}
            <div style={{ background: 'rgba(168, 85, 247, 0.06)', border: '1px solid rgba(168, 85, 247, 0.15)', borderRadius: '12px', padding: '1rem 1.25rem', marginBottom: '1rem', display: 'flex', gap: '0.75rem', alignItems: 'flex-start' }}>
                <HelpCircle size={20} style={{ color: '#a855f7', flexShrink: 0, marginTop: 2 }} />
                <div style={{ fontSize: '0.8rem', color: '#b0bec5', lineHeight: 1.6 }}>
                    <strong style={{ color: '#e0e1dd' }}>What is this?</strong> This timeline shows when your tank parameters went outside their safe range. <span style={{ color: '#4ade80' }}>Green = in range</span>, <span style={{ color: '#ef4444' }}>Red = out of range</span>. Tap any red zone to see what happened and what to do about it.
                </div>
            </div>

            {/* Time range + summary */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.75rem' }}>
                <div className={styles.rangeSelector}>
                    {[{ label: '6H', h: 6 }, { label: '24H', h: 24 }, { label: '7D', h: 168 }].map(opt => (
                        <button key={opt.label} className={`${styles.rangeButton} ${rangeHours === opt.h ? styles.rangeActive : ''}`} onClick={() => setRangeHours(opt.h)}>
                            {opt.label}
                        </button>
                    ))}
                </div>
                {!isLoading && timelines.length > 0 && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.4rem 0.8rem', borderRadius: '8px', background: totalAnomalies === 0 ? 'rgba(74, 222, 128, 0.08)' : 'rgba(239, 68, 68, 0.08)', border: `1px solid ${totalAnomalies === 0 ? 'rgba(74, 222, 128, 0.2)' : 'rgba(239, 68, 68, 0.2)'}` }}>
                        {totalAnomalies === 0
                            ? <><CheckCircle size={14} style={{ color: '#4ade80' }} /><span style={{ fontSize: '0.75rem', color: '#4ade80', fontWeight: 600 }}>All parameters in range ✓</span></>
                            : <><AlertTriangle size={14} style={{ color: '#ef4444' }} /><span style={{ fontSize: '0.75rem', color: '#ef4444', fontWeight: 600 }}>{totalAnomalies} anomal{totalAnomalies === 1 ? 'y' : 'ies'} across {sensorsWithIssues} sensor{sensorsWithIssues !== 1 ? 's' : ''}</span></>
                        }
                    </div>
                )}
            </div>

            {isLoading ? (
                <div style={{ textAlign: 'center', padding: '3rem', color: '#778da9', fontSize: '0.85rem' }}>Scanning sensor history...</div>
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    {timelines.map(timeline => {
                        const isExpanded = expandedSensor === timeline.id;
                        const uptimePct = timeline.totalDuration > 0 ? ((timeline.totalDuration - timeline.anomalyDuration) / timeline.totalDuration * 100) : 100;

                        return (
                            <div key={timeline.id} style={{ background: 'rgba(27, 38, 59, 0.4)', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.06)', overflow: 'hidden' }}>
                                {/* Sensor header */}
                                <div
                                    onClick={() => setExpandedSensor(isExpanded ? null : timeline.id)}
                                    style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '0.75rem 1rem', cursor: 'pointer' }}
                                >
                                    <div style={{ width: 8, height: 8, borderRadius: '50%', background: timeline.anomalyCount === 0 ? '#4ade80' : '#ef4444', flexShrink: 0 }} />
                                    <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#e0e1dd', flex: '0 0 120px' }}>{timeline.label}</span>

                                    {/* Timeline bar */}
                                    <div style={{ flex: 1, height: 20, borderRadius: 6, background: 'rgba(0,0,0,0.3)', overflow: 'hidden', display: 'flex' }}>
                                        {timeline.segments.map((seg, i) => {
                                            const width = timeline.totalDuration > 0 ? ((seg.end - seg.start) / timeline.totalDuration * 100) : 0;
                                            return (
                                                <div key={i} style={{
                                                    width: `${width}%`, height: '100%',
                                                    background: seg.inRange
                                                        ? 'rgba(74, 222, 128, 0.3)'
                                                        : 'rgba(239, 68, 68, 0.5)',
                                                    borderRight: i < timeline.segments.length - 1 ? '1px solid rgba(0,0,0,0.3)' : 'none',
                                                    transition: 'background 0.2s',
                                                }} />
                                            );
                                        })}
                                    </div>

                                    <span style={{ fontSize: '0.7rem', color: uptimePct >= 95 ? '#4ade80' : uptimePct >= 80 ? '#fbbf24' : '#ef4444', fontWeight: 700, fontFamily: 'monospace', flex: '0 0 45px', textAlign: 'right' }}>
                                        {uptimePct.toFixed(0)}%
                                    </span>
                                </div>

                                {/* Expanded details */}
                                {isExpanded && (
                                    <div style={{ padding: '0 1rem 1rem', borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                                        {timeline.anomalyCount === 0 ? (
                                            <div style={{ padding: '0.75rem 0', fontSize: '0.8rem', color: '#4ade80', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                <CheckCircle size={16} /> No out-of-range events. This sensor has been stable. Great job!
                                            </div>
                                        ) : (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', paddingTop: '0.75rem' }}>
                                                <div style={{ fontSize: '0.75rem', color: '#778da9' }}>
                                                    <Clock size={12} style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4 }} />
                                                    Total out-of-range time: <strong style={{ color: '#ef4444' }}>{formatDuration(timeline.anomalyDuration)}</strong> out of {formatDuration(timeline.totalDuration)}
                                                </div>
                                                {timeline.segments.filter(s => !s.inRange).map((seg, i) => {
                                                    const tip = getTip(timeline.id, seg.avgVal || 0);
                                                    return (
                                                        <div key={i} style={{ background: 'rgba(239, 68, 68, 0.06)', border: '1px solid rgba(239, 68, 68, 0.15)', borderRadius: '8px', padding: '0.75rem' }}>
                                                            <div style={{ fontSize: '0.75rem', color: '#ef4444', fontWeight: 600, marginBottom: '0.25rem' }}>
                                                                {new Date(seg.start).toLocaleString()} → {new Date(seg.end).toLocaleString()}
                                                                <span style={{ color: '#778da9', fontWeight: 400, marginLeft: '0.5rem' }}>({formatDuration(seg.end - seg.start)})</span>
                                                            </div>
                                                            <div style={{ fontSize: '0.75rem', color: '#b0bec5', marginBottom: tip ? '0.5rem' : 0 }}>
                                                                Average value: <strong>{seg.avgVal?.toFixed(2)}</strong>
                                                                {' '}(range: {settings.thresholds[timeline.id]?.min} – {settings.thresholds[timeline.id]?.max})
                                                            </div>
                                                            {tip && (
                                                                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start' }}>
                                                                    <Info size={14} style={{ color: '#fbbf24', flexShrink: 0, marginTop: 2 }} />
                                                                    <span style={{ fontSize: '0.75rem', color: '#b0bec5', lineHeight: 1.5 }}>{tip}</span>
                                                                </div>
                                                            )}
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
};
