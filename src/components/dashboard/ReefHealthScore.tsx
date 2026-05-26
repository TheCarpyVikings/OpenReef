'use client';

import React, { useMemo } from 'react';

interface HealthScoreInput {
    // Live sensor data: array of { id, value, min, max }
    sensorReadings: { id: string; value: number; min: number; max: number }[];
    // Manual test readings: array of { id, value, min, max, ageHours }
    manualReadings: { id: string; value: number; min: number; max: number; ageHours: number }[];
    // Alarm states: array of { severity, isOk }
    alarms: { severity: 'critical' | 'warning'; isOk: boolean }[];
    // Equipment: array of { key, isOn, isCritical }
    equipment: { key: string; isOn: boolean; isCritical: boolean }[];
    // Tasks: { overdue, dueToday, totalActive }
    tasks: { overdue: number; dueToday: number; totalActive: number };
}

interface BreakdownItem {
    label: string;
    score: number;
    maxScore: number;
    status: 'good' | 'warning' | 'critical';
    detail: string;
}

function calculateHealthScore(input: HealthScoreInput): { score: number; grade: string; breakdown: BreakdownItem[] } {
    const breakdown: BreakdownItem[] = [];

    // --- 1. Live Sensors (30 points max) ---
    let sensorScore = 30;
    let sensorIssues = 0;
    const totalSensors = input.sensorReadings.length;

    for (const s of input.sensorReadings) {
        if (isNaN(s.value)) continue;
        const range = s.max - s.min;
        if (range <= 0) continue;

        if (s.value < s.min || s.value > s.max) {
            // Out of range — calculate how far off
            const deviation = s.value < s.min ? s.min - s.value : s.value - s.max;
            const percentOff = Math.min(deviation / (range * 0.5), 1);
            sensorScore -= (30 / Math.max(totalSensors, 1)) * percentOff;
            sensorIssues++;
        }
    }
    sensorScore = Math.max(0, Math.round(sensorScore));
    breakdown.push({
        label: 'Live Parameters',
        score: sensorScore,
        maxScore: 30,
        status: sensorScore >= 25 ? 'good' : sensorScore >= 15 ? 'warning' : 'critical',
        detail: sensorIssues === 0
            ? `All ${totalSensors} live parameters in range`
            : `${sensorIssues} of ${totalSensors} parameters out of range`
    });

    // --- 2. Manual Test Readings (25 points max) ---
    let manualScore = 25;
    let manualIssues = 0;
    const totalManual = input.manualReadings.length;
    let staleCount = 0;

    for (const m of input.manualReadings) {
        // Penalise stale readings (older than 7 days)
        if (m.ageHours > 168) {
            staleCount++;
            manualScore -= 3;
            continue;
        }

        if (isNaN(m.value)) continue;
        const range = m.max - m.min;
        if (range <= 0) continue;

        if (m.value < m.min || m.value > m.max) {
            const deviation = m.value < m.min ? m.min - m.value : m.value - m.max;
            const percentOff = Math.min(deviation / (range * 0.5), 1);
            manualScore -= (25 / Math.max(totalManual, 1)) * percentOff;
            manualIssues++;
        }
    }

    if (totalManual === 0) {
        manualScore = 15; // No manual readings = partial penalty
    }
    manualScore = Math.max(0, Math.round(manualScore));
    breakdown.push({
        label: 'Water Chemistry',
        score: manualScore,
        maxScore: 25,
        status: manualScore >= 20 ? 'good' : manualScore >= 12 ? 'warning' : 'critical',
        detail: totalManual === 0
            ? 'No manual test data available'
            : staleCount > 0
                ? `${staleCount} readings are stale (>7 days old)`
                : manualIssues === 0
                    ? `All ${totalManual} chemistry parameters in range`
                    : `${manualIssues} chemistry parameters out of range`
    });

    // --- 3. Alarms (20 points max) ---
    let alarmScore = 20;
    const criticalAlarms = input.alarms.filter(a => !a.isOk && a.severity === 'critical').length;
    const warningAlarms = input.alarms.filter(a => !a.isOk && a.severity === 'warning').length;

    alarmScore -= criticalAlarms * 10; // -10 per critical alarm
    alarmScore -= warningAlarms * 4; // -4 per warning

    alarmScore = Math.max(0, Math.round(alarmScore));
    breakdown.push({
        label: 'Health Monitors',
        score: alarmScore,
        maxScore: 20,
        status: alarmScore >= 18 ? 'good' : alarmScore >= 10 ? 'warning' : 'critical',
        detail: criticalAlarms === 0 && warningAlarms === 0
            ? 'All health monitors OK'
            : criticalAlarms > 0
                ? `${criticalAlarms} critical alert${criticalAlarms > 1 ? 's' : ''} active!`
                : `${warningAlarms} warning${warningAlarms > 1 ? 's' : ''} active`
    });

    // --- 4. Equipment (15 points max) ---
    let equipmentScore = 15;
    const criticalOff = input.equipment.filter(e => e.isCritical && !e.isOn).length;
    const totalCritical = input.equipment.filter(e => e.isCritical).length;

    equipmentScore -= criticalOff * 5;
    equipmentScore = Math.max(0, Math.round(equipmentScore));
    breakdown.push({
        label: 'Equipment Status',
        score: equipmentScore,
        maxScore: 15,
        status: equipmentScore >= 13 ? 'good' : equipmentScore >= 8 ? 'warning' : 'critical',
        detail: criticalOff === 0
            ? `All ${totalCritical} critical devices online`
            : `${criticalOff} critical device${criticalOff > 1 ? 's' : ''} offline`
    });

    // --- 5. Maintenance (10 points max) ---
    let taskScore = 10;
    taskScore -= input.tasks.overdue * 3; // -3 per overdue task
    taskScore -= input.tasks.dueToday * 1; // -1 per due-today task

    taskScore = Math.max(0, Math.round(taskScore));
    breakdown.push({
        label: 'Maintenance',
        score: taskScore,
        maxScore: 10,
        status: taskScore >= 8 ? 'good' : taskScore >= 5 ? 'warning' : 'critical',
        detail: input.tasks.overdue === 0 && input.tasks.dueToday === 0
            ? 'All maintenance tasks up to date'
            : input.tasks.overdue > 0
                ? `${input.tasks.overdue} overdue task${input.tasks.overdue > 1 ? 's' : ''}`
                : `${input.tasks.dueToday} task${input.tasks.dueToday > 1 ? 's' : ''} due today`
    });

    const totalScore = sensorScore + manualScore + alarmScore + equipmentScore + taskScore;

    // Grade letter
    let grade = 'F';
    if (totalScore >= 95) grade = 'A+';
    else if (totalScore >= 90) grade = 'A';
    else if (totalScore >= 85) grade = 'A-';
    else if (totalScore >= 80) grade = 'B+';
    else if (totalScore >= 75) grade = 'B';
    else if (totalScore >= 70) grade = 'B-';
    else if (totalScore >= 65) grade = 'C+';
    else if (totalScore >= 60) grade = 'C';
    else if (totalScore >= 50) grade = 'D';

    return { score: totalScore, grade, breakdown };
}

function getGradeColor(score: number): string {
    if (score >= 85) return '#4ade80';
    if (score >= 70) return '#a3e635';
    if (score >= 55) return '#fbbf24';
    if (score >= 40) return '#fb923c';
    return '#ef4444';
}

interface ReefHealthScoreProps {
    input: HealthScoreInput;
    compact?: boolean;
}

export const ReefHealthScore: React.FC<ReefHealthScoreProps> = ({ input, compact = false }) => {
    const { score, grade, breakdown } = useMemo(() => calculateHealthScore(input), [input]);
    const color = getGradeColor(score);
    const circumference = 2 * Math.PI * 54;
    const strokeDash = (score / 100) * circumference;

    if (compact) {
        return (
            <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '1rem',
                padding: '0.75rem 1rem',
                background: `${color}10`,
                borderRadius: '12px',
                border: `1px solid ${color}30`,
            }}>
                <div style={{ position: 'relative', width: 44, height: 44, flexShrink: 0 }}>
                    <svg width="44" height="44" viewBox="0 0 44 44">
                        <circle cx="22" cy="22" r="18" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="4" />
                        <circle
                            cx="22" cy="22" r="18" fill="none" stroke={color} strokeWidth="4"
                            strokeDasharray={`${(score / 100) * 2 * Math.PI * 18} ${2 * Math.PI * 18}`}
                            strokeLinecap="round"
                            transform="rotate(-90 22 22)"
                            style={{ transition: 'stroke-dasharray 1s ease' }}
                        />
                    </svg>
                    <div style={{
                        position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: '0.7rem', fontWeight: 800, color
                    }}>
                        {score}
                    </div>
                </div>
                <div>
                    <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#e0e1dd' }}>Reef Health: {grade}</div>
                    <div style={{ fontSize: '0.7rem', color: '#778da9' }}>
                        {score >= 85 ? 'Excellent condition' : score >= 70 ? 'Needs attention' : score >= 50 ? 'Issues detected' : 'Critical attention needed'}
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div style={{
            background: 'rgba(27, 38, 59, 0.6)',
            backdropFilter: 'blur(10px)',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            borderRadius: '1rem',
            padding: '1.5rem',
            animation: 'fadeIn 0.4s ease-out',
        }}>
            {/* Header with gauge */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem', marginBottom: '1.5rem' }}>
                {/* Circular gauge */}
                <div style={{ position: 'relative', width: 130, height: 130, flexShrink: 0 }}>
                    <svg width="130" height="130" viewBox="0 0 130 130">
                        {/* Background track */}
                        <circle cx="65" cy="65" r="54" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="8" />
                        {/* Score arc */}
                        <circle
                            cx="65" cy="65" r="54" fill="none" stroke={color} strokeWidth="8"
                            strokeDasharray={`${strokeDash} ${circumference}`}
                            strokeLinecap="round"
                            transform="rotate(-90 65 65)"
                            style={{
                                transition: 'stroke-dasharray 1.5s cubic-bezier(0.4, 0, 0.2, 1)',
                                filter: `drop-shadow(0 0 6px ${color}80)`,
                            }}
                        />
                        {/* Glow ring */}
                        <circle
                            cx="65" cy="65" r="54" fill="none" stroke={color} strokeWidth="2" opacity="0.15"
                            strokeDasharray={`${strokeDash} ${circumference}`}
                            strokeLinecap="round"
                            transform="rotate(-90 65 65)"
                        />
                    </svg>
                    <div style={{
                        position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
                        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                    }}>
                        <span style={{ fontSize: '2.2rem', fontWeight: 800, color, lineHeight: 1 }}>
                            {score}
                        </span>
                        <span style={{ fontSize: '0.65rem', color: '#778da9', letterSpacing: '0.1em', marginTop: '4px' }}>
                            / 100
                        </span>
                    </div>
                </div>

                {/* Grade and summary */}
                <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.75rem', marginBottom: '0.5rem' }}>
                        <span style={{
                            fontSize: '1.5rem', fontWeight: 800, color,
                            background: `${color}15`, padding: '0.2rem 0.6rem', borderRadius: '8px',
                        }}>
                            {grade}
                        </span>
                        <span style={{ fontSize: '1.1rem', fontWeight: 700, color: '#e0e1dd' }}>
                            Reef Health Score
                        </span>
                    </div>
                    <p style={{ fontSize: '0.85rem', color: '#778da9', margin: 0, lineHeight: 1.5 }}>
                        {score >= 90
                            ? '🌊 Your reef is thriving! All systems performing optimally.'
                            : score >= 75
                                ? '⚡ Your reef is healthy but has areas that need attention.'
                                : score >= 55
                                    ? '⚠️ Several issues detected. Review the breakdown below.'
                                    : '🚨 Critical attention needed! Multiple systems require immediate action.'}
                    </p>
                </div>
            </div>

            {/* Breakdown bars */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                {breakdown.map((item, i) => {
                    const pct = (item.score / item.maxScore) * 100;
                    const barColor = item.status === 'good' ? '#4ade80' : item.status === 'warning' ? '#fbbf24' : '#ef4444';
                    return (
                        <div key={i}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                                <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#e0e1dd' }}>
                                    {item.label}
                                </span>
                                <span style={{ fontSize: '0.75rem', fontWeight: 700, color: barColor }}>
                                    {item.score}/{item.maxScore}
                                </span>
                            </div>
                            <div style={{
                                height: '6px', borderRadius: '3px',
                                background: 'rgba(255,255,255,0.06)', overflow: 'hidden',
                            }}>
                                <div style={{
                                    height: '100%', borderRadius: '3px',
                                    width: `${pct}%`,
                                    background: `linear-gradient(90deg, ${barColor}cc, ${barColor})`,
                                    transition: 'width 1s cubic-bezier(0.4, 0, 0.2, 1)',
                                    boxShadow: `0 0 8px ${barColor}40`,
                                }} />
                            </div>
                            <div style={{ fontSize: '0.7rem', color: '#778da9', marginTop: '2px' }}>
                                {item.detail}
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

export { calculateHealthScore };
export type { HealthScoreInput, BreakdownItem };
