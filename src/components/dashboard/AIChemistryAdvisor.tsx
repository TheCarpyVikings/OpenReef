'use client';

import React, { useMemo } from 'react';
import { TrendingUp, TrendingDown, Minus, AlertTriangle, CheckCircle, Beaker, ArrowRight } from 'lucide-react';

interface ChemistryInsight {
    param: string;
    label: string;
    value: number | string;
    trend: 'rising' | 'falling' | 'stable' | 'unknown';
    status: 'good' | 'warning' | 'critical';
    advice: string;
    priority: number; // 1 = highest
}

interface AIChemistryAdvisorProps {
    // Live sensor data
    sensorReadings: { id: string; label: string; value: number; min: number; max: number; unit?: string }[];
    // Manual test readings with history
    manualReadings: { id: string; label: string; values: { value: number; date: string }[]; min: number; max: number; unit?: string }[];
    // Show expanded view
    expanded?: boolean;
    onToggleExpanded?: () => void;
}

function analyzeParameter(
    id: string,
    label: string,
    currentValue: number,
    min: number,
    max: number,
    history?: { value: number; date: string }[],
): ChemistryInsight {
    // Determine trend from history
    let trend: 'rising' | 'falling' | 'stable' | 'unknown' = 'unknown';
    if (history && history.length >= 2) {
        const recent = history.slice(-3);
        if (recent.length >= 2) {
            const diff = recent[recent.length - 1].value - recent[0].value;
            const range = max - min;
            const pctChange = Math.abs(diff) / range;
            if (pctChange > 0.05) {
                trend = diff > 0 ? 'rising' : 'falling';
            } else {
                trend = 'stable';
            }
        }
    }

    // Determine status
    let status: 'good' | 'warning' | 'critical' = 'good';
    const range = max - min;
    const margin = range * 0.1; // 10% buffer for warnings

    if (currentValue < min || currentValue > max) {
        status = 'critical';
    } else if (currentValue < min + margin || currentValue > max - margin) {
        status = 'warning';
    }

    // Generate advice
    let advice = '';
    let priority = 3;

    // Specific parameter advice
    const paramAdvice: Record<string, { low: string; high: string; trendUp: string; trendDown: string }> = {
        alk: {
            low: 'Alkalinity is low. Consider increasing dosing or performing a water change with higher alk salt mix.',
            high: 'Alkalinity is elevated. Reduce alk dosing and monitor consumption rate.',
            trendUp: 'Alkalinity is trending upward — verify dosing amounts match consumption.',
            trendDown: 'Alkalinity is declining — coral may be consuming more. Consider increasing dosing.'
        },
        calc: {
            low: 'Calcium is depleted. Increase calcium dosing. Check that alk dosing hasn\'t displaced calcium.',
            high: 'Calcium is high. Reduce dosing to prevent precipitation and monitor alkalinity.',
            trendUp: 'Calcium trending up — may cause precipitation with high alkalinity.',
            trendDown: 'Calcium trending down — corals are consuming more, adjust dosing upward.'
        },
        mag: {
            low: 'Magnesium is low which makes it harder to maintain calcium and alkalinity. Dose magnesium.',
            high: 'Magnesium is slightly high. No action needed unless significantly elevated.',
            trendUp: 'Magnesium rising — reduce mag dosing if above optimal range.',
            trendDown: 'Magnesium declining — may impact Ca/Alk stability. Top up magnesium.'
        },
        nitrate: {
            low: 'Nitrate is very low. Corals need some nitrate (5-10ppm). Consider reducing filtration or supplementing.',
            high: 'Nitrate is elevated. Increase water changes, reduce feeding, or add more filtration.',
            trendUp: 'Nitrate rising — check for overfeeding, decaying matter, or insufficient export.',
            trendDown: 'Nitrate declining — good if approaching target, concerning if reaching zero.'
        },
        phosphate: {
            low: 'Phosphate is very low. Ultra-low phosphate can stress corals. Reduce GFO or dose phosphate.',
            high: 'Phosphate is elevated. Increase GFO, water changes, or reduce feeding.',
            trendUp: 'Phosphate rising — check filtration, feeding amounts, and detritus buildup.',
            trendDown: 'Phosphate declining toward target — maintain current approach.'
        },
        temp: {
            low: 'Temperature is too low. Check heater is functioning and properly sized for your tank.',
            high: 'Temperature is too high! Ensure cooling fans or chiller are operating. Open canopy.',
            trendUp: 'Temperature rising — prepare cooling measures. Check ambient room temp.',
            trendDown: 'Temperature dropping — verify heater operation and room heating.'
        },
        ph: {
            low: 'pH is low. Increase aeration, consider CO2 scrubber, or dose Kalkwasser.',
            high: 'pH is high. Reduce aeration if using CO2 scrubber. Check dosing.',
            trendUp: 'pH trending up — monitor alkalinity dosing schedule.',
            trendDown: 'pH declining — often caused by high CO2 in the room. Improve ventilation.'
        },
        salinity: {
            low: 'Salinity is low. Top-off water may be overfilling. Verify ATO operation.',
            high: 'Salinity is high. Check for evaporation issues or ATO malfunction.',
            trendUp: 'Salinity creeping up — verify ATO is maintaining water level correctly.',
            trendDown: 'Salinity declining — check for leaks or excessive top-off.'
        }
    };

    const pa = paramAdvice[id];

    if (status === 'critical') {
        priority = 1;
        advice = currentValue < min ? (pa?.low || `${label} is below safe range. Immediate attention needed.`) : (pa?.high || `${label} is above safe range. Immediate attention needed.`);
    } else if (status === 'warning') {
        priority = 2;
        advice = currentValue < min + (max - min) * 0.1
            ? (pa?.low || `${label} is approaching lower limit. Monitor closely.`)
            : (pa?.high || `${label} is approaching upper limit. Monitor closely.`);
    } else if (trend === 'rising' || trend === 'falling') {
        priority = 2;
        advice = trend === 'rising'
            ? (pa?.trendUp || `${label} is trending upward. Keep monitoring.`)
            : (pa?.trendDown || `${label} is trending downward. Keep monitoring.`);
    } else {
        advice = `${label} is stable and within optimal range. ✓`;
    }

    return {
        param: id,
        label,
        value: isNaN(currentValue) ? '--' : currentValue,
        trend,
        status,
        advice,
        priority,
    };
}

export const AIChemistryAdvisor: React.FC<AIChemistryAdvisorProps> = ({
    sensorReadings,
    manualReadings,
    expanded = false,
    onToggleExpanded,
}) => {
    const insights = useMemo(() => {
        const all: ChemistryInsight[] = [];

        // Analyze live sensor readings
        for (const s of sensorReadings) {
            if (isNaN(s.value)) continue;
            all.push(analyzeParameter(s.id, s.label, s.value, s.min, s.max));
        }

        // Analyze manual readings (with history)
        for (const m of manualReadings) {
            if (!m.values || m.values.length === 0) continue;
            const latest = m.values[m.values.length - 1];
            all.push(analyzeParameter(m.id, m.label, latest.value, m.min, m.max, m.values));
        }

        // Sort by priority (critical first, then warnings, then stable)
        return all.sort((a, b) => a.priority - b.priority);
    }, [sensorReadings, manualReadings]);

    const issues = insights.filter(i => i.status !== 'good' || (i.trend !== 'stable' && i.trend !== 'unknown'));
    const criticalCount = insights.filter(i => i.status === 'critical').length;
    const warningCount = insights.filter(i => i.status === 'warning').length;
    const goodCount = insights.filter(i => i.status === 'good').length;

    // Generate daily briefing
    const briefing = useMemo(() => {
        if (criticalCount > 0) {
            return `🚨 ${criticalCount} critical issue${criticalCount > 1 ? 's' : ''} require${criticalCount === 1 ? 's' : ''} immediate attention.`;
        }
        if (warningCount > 0) {
            return `⚠️ ${warningCount} parameter${warningCount > 1 ? 's' : ''} approaching limit${warningCount > 1 ? 's' : ''}.`;
        }
        if (issues.length > 0) {
            return `📊 ${issues.length} parameter${issues.length > 1 ? 's' : ''} trending — keep monitoring.`;
        }
        return `🌊 Looking great! All ${goodCount} monitored parameters are stable and in range.`;
    }, [criticalCount, warningCount, issues.length, goodCount]);

    const TrendIcon = ({ trend }: { trend: string }) => {
        if (trend === 'rising') return <TrendingUp size={14} style={{ color: '#fbbf24' }} />;
        if (trend === 'falling') return <TrendingDown size={14} style={{ color: '#60a5fa' }} />;
        if (trend === 'stable') return <Minus size={14} style={{ color: '#4ade80' }} />;
        return <Minus size={14} style={{ color: '#778da9', opacity: 0.5 }} />;
    };

    const StatusIcon = ({ status }: { status: string }) => {
        if (status === 'critical') return <AlertTriangle size={14} style={{ color: '#ef4444' }} />;
        if (status === 'warning') return <AlertTriangle size={14} style={{ color: '#fbbf24' }} />;
        return <CheckCircle size={14} style={{ color: '#4ade80' }} />;
    };

    const now = new Date();
    const timeOfDay = now.getHours() < 12 ? 'Good Morning' : now.getHours() < 17 ? 'Good Afternoon' : 'Good Evening';

    return (
        <div style={{
            background: 'rgba(27, 38, 59, 0.6)',
            backdropFilter: 'blur(10px)',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            borderRadius: '1rem',
            padding: '1.5rem',
            borderLeft: `4px solid ${criticalCount > 0 ? '#ef4444' : warningCount > 0 ? '#fbbf24' : '#4ade80'}`,
        }}>
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
                <div style={{
                    width: 36, height: 36, borderRadius: '10px',
                    background: 'linear-gradient(135deg, #06b6d4, #8b5cf6)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                    <Beaker size={18} color="#fff" />
                </div>
                <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '1rem', fontWeight: 700, color: '#e0e1dd' }}>
                        {timeOfDay} — Your Tank Today
                    </div>
                    <div style={{ fontSize: '0.8rem', color: '#778da9' }}>
                        AI Chemistry Advisor
                    </div>
                </div>
                <div style={{
                    display: 'flex', gap: '0.4rem', fontSize: '0.7rem', fontWeight: 600,
                }}>
                    {criticalCount > 0 && (
                        <span style={{ background: '#ef444420', color: '#ef4444', padding: '2px 8px', borderRadius: '6px' }}>
                            {criticalCount} Critical
                        </span>
                    )}
                    {warningCount > 0 && (
                        <span style={{ background: '#fbbf2420', color: '#fbbf24', padding: '2px 8px', borderRadius: '6px' }}>
                            {warningCount} Warning
                        </span>
                    )}
                    {criticalCount === 0 && warningCount === 0 && (
                        <span style={{ background: '#4ade8020', color: '#4ade80', padding: '2px 8px', borderRadius: '6px' }}>
                            All Clear
                        </span>
                    )}
                </div>
            </div>

            {/* Briefing */}
            <div style={{
                fontSize: '0.9rem', color: '#e0e1dd', lineHeight: 1.6,
                padding: '0.75rem 1rem',
                background: 'rgba(0,0,0,0.2)',
                borderRadius: '8px',
                marginBottom: '1rem',
            }}>
                {briefing}
            </div>

            {/* Insights list */}
            {(expanded ? insights : insights.filter(i => i.status !== 'good' || i.trend !== 'stable').slice(0, 5)).map((insight, i) => (
                <div key={i} style={{
                    display: 'flex', alignItems: 'center', gap: '0.75rem',
                    padding: '0.6rem 0',
                    borderBottom: i < (expanded ? insights.length : Math.min(issues.length, 5)) - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none',
                }}>
                    <StatusIcon status={insight.status} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <span style={{ fontSize: '0.85rem', fontWeight: 600, color: '#e0e1dd' }}>
                                {insight.label}
                            </span>
                            <span style={{
                                fontSize: '0.8rem', fontWeight: 700,
                                color: insight.status === 'critical' ? '#ef4444' : insight.status === 'warning' ? '#fbbf24' : '#4ade80',
                            }}>
                                {typeof insight.value === 'number' ? insight.value.toFixed(2) : insight.value}
                            </span>
                            <TrendIcon trend={insight.trend} />
                        </div>
                        <div style={{ fontSize: '0.75rem', color: '#778da9', lineHeight: 1.4, marginTop: '2px' }}>
                            {insight.advice}
                        </div>
                    </div>
                </div>
            ))}

            {/* Expand/Collapse */}
            {insights.length > 5 && onToggleExpanded && (
                <button
                    onClick={onToggleExpanded}
                    style={{
                        display: 'flex', alignItems: 'center', gap: '0.4rem',
                        width: '100%', justifyContent: 'center',
                        padding: '0.6rem',
                        marginTop: '0.5rem',
                        background: 'rgba(255,255,255,0.03)',
                        border: '1px solid rgba(255,255,255,0.08)',
                        borderRadius: '8px',
                        color: '#778da9',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        cursor: 'pointer',
                        transition: 'all 0.2s',
                    }}
                >
                    {expanded ? 'Show Less' : `Show All ${insights.length} Parameters`}
                    <ArrowRight size={12} style={{ transform: expanded ? 'rotate(-90deg)' : 'rotate(90deg)', transition: 'transform 0.2s' }} />
                </button>
            )}
        </div>
    );
};
