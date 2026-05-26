'use client';

import React, { useState } from 'react';
import styles from '@/app/dashboard.module.css';
import { useSettings } from '@/context/SettingsContext';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import { FileText, Download, TrendingUp, Activity, Clock, CheckCircle, AlertTriangle } from 'lucide-react';
import { ReefHealthScore, calculateHealthScore } from './ReefHealthScore';
import type { HealthScoreInput } from './ReefHealthScore';
import { useNow } from '@/hooks/use-now';
import type { ReefTask } from '@/types/reef';

interface ReportsScreenProps {
    tasks: ReefTask[];
}

const StatBox = ({ icon, label, value, color, subtitle }: {
    icon: React.ReactNode; label: string; value: string; color: string; subtitle?: string;
}) => (
    <div style={{
        background: 'rgba(27, 38, 59, 0.6)',
        border: '1px solid rgba(255,255,255,0.1)',
        borderRadius: '1rem',
        padding: '1.25rem',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        textAlign: 'center',
        gap: '0.5rem',
    }}>
        <div style={{
            width: 40, height: 40, borderRadius: '10px',
            background: `${color}15`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color,
        }}>
            {icon}
        </div>
        <div style={{ fontSize: '0.75rem', color: '#778da9', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {label}
        </div>
        <div style={{ fontSize: '1.75rem', fontWeight: 700, color }}>{value}</div>
        {subtitle && <div style={{ fontSize: '0.7rem', color: '#778da9' }}>{subtitle}</div>}
    </div>
);

export const ReportsScreen: React.FC<ReportsScreenProps> = ({ tasks }) => {
    const { settings, getEquipmentName, getLabel, manualReadings } = useSettings();
    const { entities } = useHomeAssistant();
    const [reportPeriod, setReportPeriod] = useState<'week' | 'month'>('week');
    const now = useNow(60 * 60 * 1000);

    const getEntityState = (entityId: string | undefined) => entityId ? entities?.[entityId]?.state : undefined;

    const getLatestManualValue = (id: string) => {
        const readings = manualReadings[id];
        if (!readings || readings.length === 0) return NaN;
        return parseFloat(readings[readings.length - 1].value.toString());
    };

    const getManualReadingAge = (id: string): number => {
        const readings = manualReadings[id];
        if (!readings || readings.length === 0 || now === 0) return Infinity;
        const lastDate = new Date(readings[readings.length - 1].date);
        return (now - lastDate.getTime()) / (1000 * 60 * 60); // hours
    };

    // Build health score input
    const healthInput: HealthScoreInput = (() => {
        const sensorReadings = settings.missionControl.environmentalStats.map(id => {
            let entityId = '';
            if (settings.entities.tank[id as keyof typeof settings.entities.tank]) {
                entityId = settings.entities.tank[id as keyof typeof settings.entities.tank];
            } else if (settings.entities.room[id as keyof typeof settings.entities.room]) {
                entityId = settings.entities.room[id as keyof typeof settings.entities.room];
            }
            const state = entityId ? getEntityState(entityId) : undefined;
            const threshold = settings.thresholds[id];
            return {
                id,
                value: state ? parseFloat(state) : NaN,
                min: threshold?.min ?? 0,
                max: threshold?.max ?? 100,
            };
        }).filter(s => !isNaN(s.value));

        const manualParams = ['alk', 'calc', 'mag', 'salinity', 'nitrate', 'phosphate'];
        const manualData = manualParams.map(id => {
            const threshold = settings.thresholds[id];
            return {
                id,
                value: getLatestManualValue(id),
                min: threshold?.min ?? 0,
                max: threshold?.max ?? 100,
                ageHours: getManualReadingAge(id),
            };
        }).filter(m => !isNaN(m.value));

        const customAlarms = Object.entries(settings.alarms || {}).map(([, alarm]) => {
            const state = getEntityState(alarm.entityId);
            const isOk = state === alarm.okValue || (alarm.okValue.toLowerCase() === 'off' && state === 'off') || (alarm.okValue.toLowerCase() === 'on' && state === 'on');
            return { severity: alarm.severity as 'critical' | 'warning', isOk };
        });

        const criticalEquip = settings.missionControl.criticalEquipment.map(key => ({
            key,
            isOn: getEntityState(settings.entities.equipment[key]?.switch) === 'on',
            isCritical: true,
        }));

        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const todayStr = today.toISOString().split('T')[0];
        const activeTasks = tasks.filter(t => !t.completed && t.due);
        const overdue = activeTasks.filter(t => { const d = new Date(t.due!); d.setHours(0, 0, 0, 0); return d < today; }).length;
        const dueToday = activeTasks.filter(t => t.due === todayStr).length;

        return {
            sensorReadings,
            manualReadings: manualData,
            alarms: customAlarms,
            equipment: criticalEquip,
            tasks: { overdue, dueToday, totalActive: activeTasks.length },
        };
    })();

    const { score, grade, breakdown } = calculateHealthScore(healthInput);

    // Report stats
    const completedTasks = tasks.filter(t => t.completed).length;
    const totalTasks = tasks.length;
    const completionRate = totalTasks > 0 ? Math.round((completedTasks / totalTasks) * 100) : 100;

    const equipmentEntries = Object.entries(settings.entities.equipment);
    const onlineEquipment = equipmentEntries.filter(([, config]) => getEntityState(config.switch) === 'on').length;
    const uptimeRate = equipmentEntries.length > 0 ? Math.round((onlineEquipment / equipmentEntries.length) * 100) : 100;

    // Parameter stability analysis
    const stabilityData = settings.missionControl.environmentalStats.map(id => {
        let entityId = '';
        if (settings.entities.tank[id as keyof typeof settings.entities.tank]) {
            entityId = settings.entities.tank[id as keyof typeof settings.entities.tank];
        } else if (settings.entities.room[id as keyof typeof settings.entities.room]) {
            entityId = settings.entities.room[id as keyof typeof settings.entities.room];
        }
        const state = entityId ? getEntityState(entityId) : undefined;
        const val = state ? parseFloat(state) : NaN;
        const threshold = settings.thresholds[id];
        const isInRange = threshold && !isNaN(val) && val >= threshold.min && val <= threshold.max;

        return { id, label: getLabel(id), value: val, isInRange, threshold };
    }).filter(s => !isNaN(s.value));

    const inRangeCount = stabilityData.filter(s => s.isInRange).length;
    const stabilityPct = stabilityData.length > 0 ? Math.round((inRangeCount / stabilityData.length) * 100) : 100;

    const handleExportReport = () => {
        const reportDate = new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
        const reportLines = [
            `OPENREEF — ${reportPeriod === 'week' ? 'WEEKLY' : 'MONTHLY'} TANK HEALTH REPORT`,
            `Generated: ${reportDate}`,
            `Tank: ${settings.general.tankName}`,
            `Owner: ${settings.general.userName}`,
            '',
            '═══════════════════════════════════════',
            `REEF HEALTH SCORE: ${score}/100 (${grade})`,
            '═══════════════════════════════════════',
            '',
            'SCORE BREAKDOWN:',
            ...breakdown.map(b => `  ${b.label}: ${b.score}/${b.maxScore} — ${b.detail}`),
            '',
            'PARAMETER STATUS:',
            ...stabilityData.map(s => {
                const status = s.isInRange ? '✓ IN RANGE' : '✗ OUT OF RANGE';
                return `  ${s.label}: ${s.value.toFixed(2)} [${s.threshold?.min}-${s.threshold?.max}] ${status}`;
            }),
            '',
            'MANUAL TEST READINGS:',
            ...['alk', 'calc', 'mag', 'salinity', 'nitrate', 'phosphate'].map(id => {
                const val = getLatestManualValue(id);
                const age = getManualReadingAge(id);
                const ageStr = age === Infinity ? 'Never tested' : `${Math.round(age / 24)} days ago`;
                return `  ${getLabel(id)}: ${isNaN(val) ? 'No data' : val.toFixed(2)} (${ageStr})`;
            }),
            '',
            'EQUIPMENT STATUS:',
            ...equipmentEntries.map(([key, config]) => {
                const state = getEntityState(config.switch) || 'unknown';
                const power = parseFloat(getEntityState(config.power) || '0');
                return `  ${getEquipmentName(key, key)}: ${state.toUpperCase()} (${power.toFixed(1)}W)`;
            }),
            '',
            `MAINTENANCE: ${completedTasks}/${totalTasks} tasks completed (${completionRate}%)`,
            `EQUIPMENT UPTIME: ${onlineEquipment}/${equipmentEntries.length} devices online (${uptimeRate}%)`,
            `PARAMETER STABILITY: ${inRangeCount}/${stabilityData.length} parameters in range (${stabilityPct}%)`,
            '',
            '═══════════════════════════════════════',
            'Generated by Open Reef Controller',
        ];

        const text = reportLines.join('\n');
        const blob = new Blob([text], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `reef-report-${reportPeriod}-${new Date().toISOString().split('T')[0]}.txt`;
        a.click();
        URL.revokeObjectURL(url);
    };

    return (
        <div className={styles.missionControl}>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <FileText size={24} style={{ color: '#06b6d4' }} />
                    <div>
                        <h2 style={{ margin: 0, fontSize: '1.5rem', color: '#e0e1dd' }}>Tank Health Reports</h2>
                        <p style={{ margin: 0, fontSize: '0.8rem', color: '#778da9' }}>AI-generated health analysis and statistics</p>
                    </div>
                </div>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    <div className={styles.rangeSelector}>
                        <button
                            className={`${styles.rangeButton} ${reportPeriod === 'week' ? styles.activeRange : ''}`}
                            onClick={() => setReportPeriod('week')}
                        >
                            Weekly
                        </button>
                        <button
                            className={`${styles.rangeButton} ${reportPeriod === 'month' ? styles.activeRange : ''}`}
                            onClick={() => setReportPeriod('month')}
                        >
                            Monthly
                        </button>
                    </div>
                    <button
                        onClick={handleExportReport}
                        style={{
                            display: 'flex', alignItems: 'center', gap: '0.5rem',
                            background: 'rgba(6, 182, 212, 0.1)',
                            color: '#06b6d4',
                            border: '1px solid rgba(6, 182, 212, 0.2)',
                            padding: '0.5rem 1rem',
                            borderRadius: '8px',
                            cursor: 'pointer',
                            fontSize: '0.85rem',
                            fontWeight: 600,
                            transition: 'all 0.2s',
                        }}
                    >
                        <Download size={16} />
                        Export Report
                    </button>
                </div>
            </div>

            {/* Health Score (Full) */}
            <ReefHealthScore input={healthInput} />

            {/* Quick Stats Grid */}
            <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                gap: '1rem',
            }}>
                <StatBox
                    icon={<Activity size={20} />}
                    label="Param Stability"
                    value={`${stabilityPct}%`}
                    color={stabilityPct >= 80 ? '#4ade80' : stabilityPct >= 60 ? '#fbbf24' : '#ef4444'}
                    subtitle={`${inRangeCount}/${stabilityData.length} in range`}
                />
                <StatBox
                    icon={<CheckCircle size={20} />}
                    label="Task Completion"
                    value={`${completionRate}%`}
                    color={completionRate >= 80 ? '#4ade80' : completionRate >= 50 ? '#fbbf24' : '#ef4444'}
                    subtitle={`${completedTasks}/${totalTasks} completed`}
                />
                <StatBox
                    icon={<TrendingUp size={20} />}
                    label="Equipment Uptime"
                    value={`${uptimeRate}%`}
                    color={uptimeRate >= 80 ? '#4ade80' : uptimeRate >= 60 ? '#fbbf24' : '#ef4444'}
                    subtitle={`${onlineEquipment}/${equipmentEntries.length} online`}
                />
                <StatBox
                    icon={<AlertTriangle size={20} />}
                    label="Active Alerts"
                    value={`${healthInput.alarms.filter(a => !a.isOk).length}`}
                    color={healthInput.alarms.some(a => !a.isOk && a.severity === 'critical') ? '#ef4444' : healthInput.alarms.some(a => !a.isOk) ? '#fbbf24' : '#4ade80'}
                    subtitle={healthInput.alarms.every(a => a.isOk) ? 'All clear' : 'Needs attention'}
                />
            </div>

            {/* Parameter Detail Table */}
            <section className={styles.missionSection}>
                <h3 className={styles.sectionSubtitle}>Parameter Details</h3>
                <div style={{
                    background: 'rgba(27, 38, 59, 0.4)',
                    borderRadius: '1rem',
                    overflow: 'hidden',
                    border: '1px solid rgba(255,255,255,0.08)',
                }}>
                    {/* Table header */}
                    <div style={{
                        display: 'grid', gridTemplateColumns: '1fr 100px 120px 80px',
                        padding: '0.75rem 1rem',
                        background: 'rgba(0,0,0,0.2)',
                        borderBottom: '1px solid rgba(255,255,255,0.06)',
                        fontSize: '0.7rem', fontWeight: 700, color: '#778da9', textTransform: 'uppercase', letterSpacing: '0.05em',
                    }}>
                        <span>Parameter</span>
                        <span style={{ textAlign: 'center' }}>Current</span>
                        <span style={{ textAlign: 'center' }}>Range</span>
                        <span style={{ textAlign: 'center' }}>Status</span>
                    </div>
                    {/* Live params */}
                    {stabilityData.map((s, i) => (
                        <div key={i} style={{
                            display: 'grid', gridTemplateColumns: '1fr 100px 120px 80px',
                            padding: '0.65rem 1rem',
                            borderBottom: '1px solid rgba(255,255,255,0.03)',
                            fontSize: '0.85rem',
                            alignItems: 'center',
                        }}>
                            <span style={{ color: '#e0e1dd', fontWeight: 500 }}>{s.label}</span>
                            <span style={{ textAlign: 'center', color: s.isInRange ? '#4ade80' : '#ef4444', fontWeight: 700 }}>
                                {s.value.toFixed(2)}
                            </span>
                            <span style={{ textAlign: 'center', color: '#778da9', fontSize: '0.75rem' }}>
                                {s.threshold?.min} — {s.threshold?.max}
                            </span>
                            <span style={{ textAlign: 'center' }}>
                                {s.isInRange
                                    ? <CheckCircle size={16} style={{ color: '#4ade80' }} />
                                    : <AlertTriangle size={16} style={{ color: '#ef4444' }} />}
                            </span>
                        </div>
                    ))}
                    {/* Manual params */}
                    {['alk', 'calc', 'mag', 'salinity', 'nitrate', 'phosphate'].map((id, i) => {
                        const val = getLatestManualValue(id);
                        const threshold = settings.thresholds[id];
                        const isInRange = threshold && !isNaN(val) && val >= threshold.min && val <= threshold.max;
                        const age = getManualReadingAge(id);
                        const isStale = age > 168;

                        return (
                            <div key={`manual-${i}`} style={{
                                display: 'grid', gridTemplateColumns: '1fr 100px 120px 80px',
                                padding: '0.65rem 1rem',
                                borderBottom: '1px solid rgba(255,255,255,0.03)',
                                fontSize: '0.85rem',
                                alignItems: 'center',
                                opacity: isStale ? 0.5 : 1,
                            }}>
                                <span style={{ color: '#e0e1dd', fontWeight: 500 }}>
                                    {getLabel(id)}
                                    {isStale && <span style={{ fontSize: '0.65rem', color: '#fbbf24', marginLeft: '0.5rem' }}>STALE</span>}
                                </span>
                                <span style={{
                                    textAlign: 'center',
                                    color: isNaN(val) ? '#778da9' : isInRange ? '#4ade80' : '#ef4444',
                                    fontWeight: 700,
                                }}>
                                    {isNaN(val) ? '--' : val.toFixed(2)}
                                </span>
                                <span style={{ textAlign: 'center', color: '#778da9', fontSize: '0.75rem' }}>
                                    {threshold?.min} — {threshold?.max}
                                </span>
                                <span style={{ textAlign: 'center' }}>
                                    {isNaN(val)
                                        ? <Clock size={16} style={{ color: '#778da9' }} />
                                        : isInRange
                                            ? <CheckCircle size={16} style={{ color: '#4ade80' }} />
                                            : <AlertTriangle size={16} style={{ color: '#ef4444' }} />}
                                </span>
                            </div>
                        );
                    })}
                </div>
            </section>

            {/* Equipment Status Table */}
            <section className={styles.missionSection}>
                <h3 className={styles.sectionSubtitle}>Equipment Status</h3>
                <div style={{
                    background: 'rgba(27, 38, 59, 0.4)',
                    borderRadius: '1rem',
                    overflow: 'hidden',
                    border: '1px solid rgba(255,255,255,0.08)',
                }}>
                    <div style={{
                        display: 'grid', gridTemplateColumns: '1fr 80px 100px 80px',
                        padding: '0.75rem 1rem',
                        background: 'rgba(0,0,0,0.2)',
                        borderBottom: '1px solid rgba(255,255,255,0.06)',
                        fontSize: '0.7rem', fontWeight: 700, color: '#778da9', textTransform: 'uppercase', letterSpacing: '0.05em',
                    }}>
                        <span>Device</span>
                        <span style={{ textAlign: 'center' }}>Status</span>
                        <span style={{ textAlign: 'center' }}>Power</span>
                        <span style={{ textAlign: 'center' }}>Critical</span>
                    </div>
                    {equipmentEntries.map(([key, config], i) => {
                        const state = getEntityState(config.switch) || 'unknown';
                        const power = parseFloat(getEntityState(config.power) || '0');
                        const isCritical = settings.missionControl.criticalEquipment.includes(key);
                        return (
                            <div key={i} style={{
                                display: 'grid', gridTemplateColumns: '1fr 80px 100px 80px',
                                padding: '0.65rem 1rem',
                                borderBottom: '1px solid rgba(255,255,255,0.03)',
                                fontSize: '0.85rem',
                                alignItems: 'center',
                            }}>
                                <span style={{ color: '#e0e1dd', fontWeight: 500 }}>{getEquipmentName(key, key)}</span>
                                <span style={{
                                    textAlign: 'center',
                                    color: state === 'on' ? '#4ade80' : '#fbbf24',
                                    fontWeight: 700,
                                    fontSize: '0.75rem',
                                }}>
                                    {state.toUpperCase()}
                                </span>
                                <span style={{ textAlign: 'center', color: '#778da9' }}>
                                    {power.toFixed(1)}W
                                </span>
                                <span style={{ textAlign: 'center' }}>
                                    {isCritical && (
                                        <span style={{
                                            fontSize: '0.65rem', fontWeight: 700,
                                            background: state === 'on' ? '#4ade8015' : '#ef444415',
                                            color: state === 'on' ? '#4ade80' : '#ef4444',
                                            padding: '2px 6px', borderRadius: '4px',
                                        }}>
                                            CRITICAL
                                        </span>
                                    )}
                                </span>
                            </div>
                        );
                    })}
                </div>
            </section>
        </div>
    );
};
