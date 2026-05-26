import React, { useMemo } from 'react';
import { Activity } from 'lucide-react';
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
import type { ChartData, ChartOptions, TooltipItem } from 'chart.js';
import { Line } from 'react-chartjs-2';
import styles from '@/app/dashboard.module.css';
import { calculateSMA, calculateEMA, calculateSavitzkyGolay } from '@/lib/filters';
import type { DataPoint } from '@/types/reef';

ChartJS.register(
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    Title,
    Tooltip,
    Legend,
    Filler
);

interface HistoryGraphProps {
    title: string;
    data: DataPoint[];
    rangeHours: number;
    borderColor: string;
    backgroundColor: string;
    yMin?: number | null;
    yMax?: number | null;
    trendLine?: {
        type: 'sma' | 'ema' | 'savitzky-golay' | 'none';
        windowSize: number;
        polynomialOrder?: number;
    };
}

export const HistoryGraph: React.FC<HistoryGraphProps> = ({
    title,
    data,
    rangeHours,
    borderColor,
    backgroundColor,
    yMin,
    yMax,
    trendLine
}) => {
    const chartData = useMemo<ChartData<'line', DataPoint[]>>(() => {
        const isTrendActive = trendLine && trendLine.type !== 'none' && data.length > 0;

        const datasets: ChartData<'line', DataPoint[]>['datasets'] = [
            {
                label: title,
                data,
                borderColor: isTrendActive ? '#4b5563' : borderColor, // Grey if trend active, theme color otherwise
                backgroundColor: isTrendActive ? 'rgba(75, 85, 99, 0.1)' : backgroundColor,
                fill: !isTrendActive, // Only fill the raw data if it's the primary line
                tension: 0.4,
                pointRadius: 0,
                borderWidth: isTrendActive ? 1.5 : 2, // Thinner line for greyed out raw data
                order: 2, // Drawn behind trend line
            },
        ];

        if (isTrendActive) {
            let thresholdData: { x: number; y: number }[] = [];
            let label = 'Trend';

            if (trendLine.type === 'sma') {
                thresholdData = calculateSMA(data, trendLine.windowSize);
                label = `SMA (${trendLine.windowSize})`;
            } else if (trendLine.type === 'ema') {
                thresholdData = calculateEMA(data, trendLine.windowSize);
                label = `EMA (${trendLine.windowSize})`;
            } else if (trendLine.type === 'savitzky-golay') {
                thresholdData = calculateSavitzkyGolay(data, trendLine.windowSize, trendLine.polynomialOrder || 2);
                label = `SG Filter (${trendLine.windowSize})`;
            }

            if (thresholdData.length > 0) {
                datasets.push({
                    label,
                    data: thresholdData,
                    borderColor: borderColor, // Trend line gets the theme color
                    backgroundColor: 'transparent',
                    fill: false,
                    tension: 0.3,
                    pointRadius: 0,
                    borderWidth: 3, // Thicker for visibility
                    order: 1, // Drawn on top of raw data
                });
            }
        }

        return { datasets };
    }, [title, data, borderColor, backgroundColor, trendLine]);

    const chartWindow = useMemo(() => {
        if (rangeHours === 0 || data.length === 0) return {};
        const max = Math.max(...data.map((point) => point.x));
        return {
            min: max - (rangeHours * 60 * 60 * 1000),
            max,
        };
    }, [data, rangeHours]);

    const options: ChartOptions<'line'> = {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
            intersect: false,
            mode: 'index' as const,
        },
        plugins: {
            legend: {
                display: !!(trendLine && trendLine.type !== 'none'),
                position: 'top' as const,
                labels: {
                    color: '#778da9',
                    boxWidth: 12,
                    font: { size: 10 }
                }
            },
            title: {
                display: true,
                text: title,
                color: '#90e0ef',
                font: { size: 16 },
            },
            tooltip: {
                callbacks: {
                    label: (context: TooltipItem<'line'>) => {
                        const value = context.parsed.y ?? 0;
                        return `${context.dataset.label}: ${value.toFixed(2)}`;
                    },
                    title: (context: TooltipItem<'line'>[]) => {
                        const date = new Date(context[0]?.parsed.x ?? 0);
                        return date.toLocaleString();
                    }
                }
            }
        },
        scales: {
            y: {
                grid: { color: 'rgba(255, 255, 255, 0.1)' },
                ticks: { color: '#778da9' },
                ...(yMin !== null && yMin !== undefined ? { min: yMin } : {}),
                ...(yMax !== null && yMax !== undefined ? { max: yMax } : {}),
            },
            x: {
                type: 'linear' as const,
                grid: { display: false },
                ticks: {
                    color: '#778da9',
                    maxRotation: 0,
                    autoSkip: true,
                    maxTicksLimit: 6,
                    callback: function (value: string | number) {
                        const date = new Date(value);
                        if (rangeHours > 48) {
                            return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
                        }
                        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                    }
                },
                min: chartWindow.min,
                max: chartWindow.max,
            },
        },
    };

    return (
        <div className={styles.chartContainer}>
            {data.length > 0 ? (
                <Line data={chartData} options={options} />
            ) : (
                <div className={styles.noData}>
                    <Activity size={48} strokeWidth={1} />
                    <p>No History Data Available</p>
                    <span style={{ fontSize: '0.8rem' }}>Map your Home Assistant entities to enable trend tracking</span>
                </div>
            )}
        </div>
    );
};
