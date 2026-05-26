import React from 'react';
import styles from '@/app/dashboard.module.css';

interface StatusCardProps {
    label: string;
    value: number | string | undefined;
    unit: string;
    min?: number;
    max?: number;
    icon?: React.ReactNode;
    onClick?: () => void;
    variant?: 'numbers' | 'gauges' | 'graphs';
    history?: { x: number; y: number }[];
    isCustom?: boolean;
    lastTested?: string;
    isStale?: boolean;
}

export const StatusCard: React.FC<StatusCardProps> = ({
    label,
    value,
    unit,
    min,
    max,
    icon,
    onClick,
    variant,
    history,
    isCustom,
    lastTested,
    isStale
}) => {
    const numericValue = typeof value === 'string' ? parseFloat(value) : value;
    const displayValue = typeof numericValue === 'number' && !isNaN(numericValue)
        ? numericValue.toFixed(2)
        : (value !== undefined ? value : '--');

    const getStatusClass = () => {
        if (numericValue === undefined || isNaN(numericValue) || min === undefined || max === undefined) return '';
        if (numericValue < min || numericValue > max) return styles.danger;
        const buffer = (max - min) * 0.1;
        if (numericValue < min + buffer || numericValue > max - buffer) return styles.warning;
        return styles.safe;
    };

    const statusClass = getStatusClass();

    const getActiveColor = () => {
        if (statusClass === styles.danger) return '#ef4444';
        if (statusClass === styles.warning) return '#f59e0b';
        return '#10b981';
    };

    const activeColor = getActiveColor();

    // Calculate Gauge props
    const renderGauge = () => {
        if (min === undefined || max === undefined || typeof numericValue !== 'number') return null;

        const range = max - min;
        const buffer = range * 0.15; // warning zone width
        const totalMin = min - range * 0.5;
        const totalMax = max + range * 0.5;
        const totalRange = totalMax - totalMin;

        const getPercent = (val: number) => Math.min(Math.max((val - totalMin) / totalRange, 0), 1);
        const currentPercent = getPercent(numericValue);

        // Zone boundaries as percentages
        const dangerLowEnd = getPercent(min);
        const warnLowEnd = getPercent(min + buffer);
        const warnHighStart = getPercent(max - buffer);
        const dangerHighStart = getPercent(max);

        const radius = 44;
        const centerX = 55;
        const centerY = 55;
        const strokeW = 7;
        const needleLen = radius - 8;

        const polarToCartesian = (percent: number) => {
            const angle = (percent * 180 - 180) * Math.PI / 180.0;
            return {
                x: centerX + (radius * Math.cos(angle)),
                y: centerY + (radius * Math.sin(angle))
            };
        };

        const describeArc = (startP: number, endP: number) => {
            const s = polarToCartesian(startP);
            const e = polarToCartesian(endP);
            const sweep = (endP - startP) * 180;
            const large = sweep > 180 ? "1" : "0";
            return `M ${s.x} ${s.y} A ${radius} ${radius} 0 ${large} 1 ${e.x} ${e.y}`;
        };

        // Needle position
        const needleAngle = (currentPercent * 180 - 180) * Math.PI / 180.0;
        const needleTipX = centerX + needleLen * Math.cos(needleAngle);
        const needleTipY = centerY + needleLen * Math.sin(needleAngle);
        // Needle base (small circle at center)
        const needleBaseR = 3;

        const uid = `gauge-${label.replace(/\s/g, '')}-${min}-${max}`;

        return (
            <div style={{ position: 'relative', width: '100%', height: '100px', display: 'flex', justifyContent: 'center', alignItems: 'center', marginTop: '0.25rem' }}>
                <svg width="140" height="95" viewBox="0 0 110 70">
                    <defs>
                        <filter id={`glow-${uid}`} x="-50%" y="-50%" width="200%" height="200%">
                            <feGaussianBlur stdDeviation="2.5" result="blur" />
                            <feMerge>
                                <feMergeNode in="blur" />
                                <feMergeNode in="SourceGraphic" />
                            </feMerge>
                        </filter>
                        <linearGradient id={`needleGrad-${uid}`} x1="0%" y1="0%" x2="100%" y2="0%">
                            <stop offset="0%" stopColor={activeColor} stopOpacity="0" />
                            <stop offset="100%" stopColor={activeColor} stopOpacity="1" />
                        </linearGradient>
                    </defs>

                    {/* Background track */}
                    <path d={describeArc(0, 1)} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={strokeW} strokeLinecap="round" />

                    {/* Zone arcs: danger-low, warning-low, safe, warning-high, danger-high */}
                    <path d={describeArc(0, dangerLowEnd)} fill="none" stroke="#ef4444" strokeWidth={strokeW} strokeLinecap="round" opacity="0.35" />
                    <path d={describeArc(dangerLowEnd, warnLowEnd)} fill="none" stroke="#f59e0b" strokeWidth={strokeW} opacity="0.35" />
                    <path d={describeArc(warnLowEnd, warnHighStart)} fill="none" stroke="#10b981" strokeWidth={strokeW} opacity="0.35" />
                    <path d={describeArc(warnHighStart, dangerHighStart)} fill="none" stroke="#f59e0b" strokeWidth={strokeW} opacity="0.35" />
                    <path d={describeArc(dangerHighStart, 1)} fill="none" stroke="#ef4444" strokeWidth={strokeW} strokeLinecap="round" opacity="0.35" />

                    {/* Active fill arc (up to current value) */}
                    <path
                        d={describeArc(0, currentPercent)}
                        fill="none"
                        stroke={activeColor}
                        strokeWidth={strokeW + 1}
                        strokeLinecap="round"
                        filter={`url(#glow-${uid})`}
                        style={{ transition: 'all 0.6s cubic-bezier(0.4, 0, 0.2, 1)' }}
                    />

                    {/* Tick marks for min and max */}
                    {[dangerLowEnd, dangerHighStart].map((p, i) => {
                        const pos = polarToCartesian(p);
                        const innerR = radius - strokeW / 2 - 3;
                        const innerAngle = (p * 180 - 180) * Math.PI / 180.0;
                        const ix = centerX + innerR * Math.cos(innerAngle);
                        const iy = centerY + innerR * Math.sin(innerAngle);
                        return <line key={i} x1={pos.x} y1={pos.y} x2={ix} y2={iy} stroke="rgba(255,255,255,0.25)" strokeWidth="1" />;
                    })}

                    {/* Needle */}
                    <line
                        x1={centerX}
                        y1={centerY}
                        x2={needleTipX}
                        y2={needleTipY}
                        stroke={activeColor}
                        strokeWidth="2"
                        strokeLinecap="round"
                        filter={`url(#glow-${uid})`}
                        style={{ transition: 'all 0.6s cubic-bezier(0.4, 0, 0.2, 1)' }}
                    />
                    {/* Needle center dot */}
                    <circle cx={centerX} cy={centerY} r={needleBaseR} fill={activeColor} opacity="0.8" />
                    <circle cx={centerX} cy={centerY} r={needleBaseR - 1} fill="#0d1b2a" />

                    {/* Value text */}
                    <text x={centerX} y={centerY - 10} textAnchor="middle" fill="#fff" fontSize="15" fontWeight="700" fontFamily="Inter, sans-serif">{displayValue}</text>
                    <text x={centerX} y={centerY - 1} textAnchor="middle" fill="#778da9" fontSize="7" fontFamily="Inter, sans-serif">{unit}</text>

                    {/* Min / Max labels */}
                    <text x="8" y="62" textAnchor="start" fill="#778da9" fontSize="5.5" fontFamily="Inter, sans-serif">{min}</text>
                    <text x="102" y="62" textAnchor="end" fill="#778da9" fontSize="5.5" fontFamily="Inter, sans-serif">{max}</text>
                </svg>
            </div>
        );
    };

    const renderMiniSparkline = () => {
        if (!history || history.length < 2) {
            return (
                <div style={{ height: '75px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#778da9', fontSize: '0.7rem' }}>
                    Loading data...
                </div>
            );
        }

        const width = 200;
        const height = 60;
        const padding = 5;

        // Auto-scale Y based on min/max of history or threshold range if provided
        const yValues = history.map(p => p.y);
        const dataMin = Math.min(...yValues);
        const dataMax = Math.max(...yValues);

        // Use threshold range if available to keep scales consistent, otherwise use data range
        const viewMin = (min !== undefined && max !== undefined) ? Math.min(min, dataMin) : dataMin;
        const viewMax = (min !== undefined && max !== undefined) ? Math.max(max, dataMax) : dataMax;
        const yRange = (viewMax - viewMin) || 1;

        const xMin = Math.min(...history.map(p => p.x));
        const xMax = Math.max(...history.map(p => p.x));
        const xRange = xMax - xMin;

        const getX = (x: number) => padding + ((x - xMin) / xRange) * (width - padding * 2);
        const getY = (y: number) => (height - padding) - ((y - viewMin) / yRange) * (height - padding * 2);

        const points = history.map(p => `${getX(p.x)},${getY(p.y)}`).join(' ');
        const pathData = `M ${points}`;
        const areaData = `${pathData} L ${getX(xMax)},${height} L ${getX(xMin)},${height} Z`;

        return (
            <div style={{ position: 'relative', width: '100%', height: '75px', marginTop: '0.5rem', overflow: 'hidden' }}>
                <div style={{ position: 'absolute', top: 0, left: 0, right: 0, textAlign: 'center' }}>
                    <span style={{ fontSize: '1.2rem', fontWeight: 700, color: '#fff' }}>{displayValue}</span>
                    <span style={{ fontSize: '0.7rem', color: '#778da9', marginLeft: '4px' }}>{unit}</span>
                </div>
                <svg width="100%" height="100%" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ marginTop: '15px' }}>
                    <defs>
                        <linearGradient id={`grad-${label.replace(/\s/g, '')}`} x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stopColor={activeColor} stopOpacity="0.2" />
                            <stop offset="100%" stopColor={activeColor} stopOpacity="0" />
                        </linearGradient>
                    </defs>
                    <path d={areaData} fill={`url(#grad-${label.replace(/\s/g, '')})`} />
                    <path d={pathData} fill="none" stroke={activeColor} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
            </div>
        );
    };

    return (
        <div
            className={`${styles.card} ${onClick ? styles.clickable : ''}`}
            onClick={onClick}
        >
            <div className={styles.sensorLabel}>
                {icon} {label}
                {isCustom && (
                    <span style={{
                        marginLeft: 'auto',
                        fontSize: '0.6rem',
                        background: 'rgba(0, 180, 216, 0.1)',
                        color: '#00b4d8',
                        padding: '2px 6px',
                        borderRadius: '4px',
                        border: '1px solid rgba(0, 180, 216, 0.2)',
                        fontWeight: 600,
                        textTransform: 'uppercase'
                    }}>
                        Custom
                    </span>
                )}
            </div>

            {variant === 'gauges' && min !== undefined && max !== undefined ? (
                renderGauge()
            ) : variant === 'graphs' ? (
                renderMiniSparkline()
            ) : (
                <div className={`${styles.sensorValue} ${statusClass}`}>
                    {displayValue}
                    <span className={styles.sensorUnit}>{unit}</span>
                </div>
            )}

            <div className={styles.sensorLabel} style={lastTested ? { display: 'flex', justifyContent: 'space-between', width: '100%' } : {}}>
                <span>{min !== undefined && max !== undefined ? `${min} - ${max} Range` : 'Monitoring'}</span>
                {lastTested && (
                    <span style={{ color: isStale ? '#ef4444' : '#778da9', fontWeight: isStale ? 600 : 400, fontSize: '0.65rem' }}>
                        {lastTested}
                    </span>
                )}
            </div>
        </div>
    );
};
