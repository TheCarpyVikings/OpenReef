'use client';

import React, { useState, useMemo, useEffect } from 'react';
import styles from '@/app/dashboard.module.css';
import { useSettings } from '@/context/SettingsContext';
import type { AppSettings } from '@/context/SettingsContext';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import { HistoryGraph } from './HistoryGraph';
import { X, Activity, Calendar, Plus } from 'lucide-react';
import { apiFetch } from '@/lib/api-fetch';
import { historyResponseToPoints } from '@/lib/ha-history';
import type { DataPoint } from '@/types/reef';

type TrendLineConfig = AppSettings['visuals']['trendLines'][string];
type TrendLineType = TrendLineConfig['type'];
type DashboardTrendLineType = NonNullable<AppSettings['dashboard']['trendLineType']>;

interface SelectedParam {
    id: string;
    label: string;
    color: string;
    isManual: boolean;
}

interface ParamHistoryModalProps {
    selectedParam: SelectedParam;
    onClose: () => void;
}

export const ParamHistoryModal: React.FC<ParamHistoryModalProps> = ({ selectedParam, onClose }) => {
    const { settings, manualReadings, saveManualReadings, updateNestedSetting, syncManualReadingsWithSheets } = useSettings();
    const { fetchHistory, entities } = useHomeAssistant();

    const [historyRange, setHistoryRange] = useState(selectedParam.isManual ? 720 : 24);
    const [newValue, setNewValue] = useState('');
    const [newDate, setNewDate] = useState(new Date().toISOString().split('T')[0]);
    const [realHistoryData, setRealHistoryData] = useState<DataPoint[] | null>(null);

    const updateParamTrendLine = (updates: Partial<TrendLineConfig>) => {
        const existing = settings.visuals.trendLines?.[selectedParam.id];
        const defaultTrendLine: TrendLineConfig = {
            enabled: true,
            type: 'none',
            windowSize: 12,
            polynomialOrder: 2,
        };
        const nextTrendLine = Object.assign({}, defaultTrendLine, existing, updates);
        updateNestedSetting('visuals', {
            trendLines: {
                ...settings.visuals.trendLines,
                [selectedParam.id]: nextTrendLine,
            },
        });
    };

    // Fetch HA history when a live param is selected
    useEffect(() => {
        if (selectedParam.isManual) return;

        let entityId = '';
        if (settings.entities.tank[selectedParam.id as keyof typeof settings.entities.tank]) {
            entityId = settings.entities.tank[selectedParam.id as keyof typeof settings.entities.tank];
        } else if (settings.entities.room?.[selectedParam.id as keyof typeof settings.entities.room]) {
            entityId = settings.entities.room[selectedParam.id as keyof typeof settings.entities.room];
        } else if (selectedParam.id === 'room_temp') {
            entityId = settings.entities.room?.temp;
        } else {
            const customSensor = settings.customSensors?.find(s => s.id === selectedParam.id);
            if (customSensor) entityId = customSensor.haKey;
        }

        if (!entityId) {
            console.log('ParamHistoryModal: No entityId found for', selectedParam.id);
            return;
        }

        let cancelled = false;
        const timeout = window.setTimeout(async () => {
            try {
                const data = await fetchHistory(entityId, historyRange);
                if (data && !cancelled) {
                    setRealHistoryData(historyResponseToPoints(data, entityId, {
                        rangeHours: historyRange,
                        currentState: entities?.[entityId]?.state,
                    }));
                }
            } catch (err) {
                console.error('Failed to fetch history:', err);
            }
        }, 0);

        return () => {
            cancelled = true;
            window.clearTimeout(timeout);
        };
    }, [selectedParam, historyRange, settings, entities, fetchHistory]);

    // Prepare history data
    const activeHistory = useMemo(() => {
        if (selectedParam.isManual) {
            const readings = manualReadings[selectedParam.id] || [];
            return readings.map(r => {
                let dateStr = r.date;
                if (dateStr && typeof dateStr === 'string' && dateStr.includes('/')) {
                    const parts = dateStr.split('/');
                    if (parts.length === 3) {
                        const [p1, p2, p3] = parts;
                        if (p3.length === 4) dateStr = `${p3}-${p2.padStart(2, '0')}-${p1.padStart(2, '0')}`;
                        else if (p1.length === 4) dateStr = `${p1}-${p2.padStart(2, '0')}-${p3.padStart(2, '0')}`;
                    }
                }
                return {
                    x: new Date(dateStr.includes('T') ? dateStr : dateStr + 'T00:00:00').getTime(),
                    y: r.value
                };
            });
        }

        return realHistoryData || [];
    }, [selectedParam, manualReadings, realHistoryData]);

    // Handle adding new manual reading
    const handleAddReading = async () => {
        if (!newValue) return;

        const id = selectedParam.id;
        const readings = [...(manualReadings[id] || [])];
        const val = parseFloat(newValue);

        readings.push({ value: val, date: newDate });
        readings.sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());

        const newData = { ...manualReadings, [id]: readings };
        saveManualReadings(newData);
        setNewValue('');

        if (settings.general.googleSheetId) {
            try {
                const response = await apiFetch('/api/sheets/append', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        spreadsheetId: settings.general.googleSheetId,
                        range: 'Sheet1!A:C',
                        values: [[newDate, selectedParam.label, val]]
                    })
                });
                if (!response.ok) {
                    const errorData = await response.json();
                    console.error('Failed to sync with Google Sheets:', errorData.error);
                }
            } catch (err) {
                console.error('Error syncing with Google Sheets:', err);
            }
            syncManualReadingsWithSheets();
        }
    };



    return (
        <div className={styles.modalOverlay} onClick={onClose}>
            <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
                <div className={styles.modalHeader}>
                    <h3 className={styles.modalTitle}>{selectedParam.label} {selectedParam.isManual ? 'Logs' : 'History'}</h3>
                    <button className={styles.closeButton} onClick={onClose}>
                        <X size={24} />
                    </button>
                </div>
                <div className={styles.modalBody}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '1rem' }}>
                        <div className={styles.rangeSelector}>
                            {(selectedParam.isManual
                                ? [
                                    { label: '1M', hours: 720 },
                                    { label: '3M', hours: 2160 },
                                    { label: '6M', hours: 4320 },
                                    { label: '1Y', hours: 8760 },
                                    { label: 'All', hours: 87600 },
                                ]
                                : [
                                    { label: '1H', hours: 1 },
                                    { label: '6H', hours: 6 },
                                    { label: '24H', hours: 24 },
                                    { label: '7D', hours: 168 },
                                    { label: '30D', hours: 720 },
                                ]
                            ).map(opt => (
                                <button
                                    key={opt.label}
                                    className={`${styles.rangeButton} ${historyRange === opt.hours ? styles.rangeActive : ''}`}
                                    onClick={() => setHistoryRange(opt.hours)}
                                >
                                    {opt.label}
                                </button>
                            ))}
                        </div>
                        {!selectedParam.isManual && (
                            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', background: 'rgba(255,255,255,0.03)', padding: '4px 12px', borderRadius: '8px' }}>
                                <Activity size={14} style={{ color: '#00b4d8' }} />
                                <span style={{ fontSize: '0.75rem', color: '#778da9', fontWeight: 600, textTransform: 'uppercase' }}>Trend Line:</span>
                                <select
                                    className={styles.input}
                                    style={{
                                        padding: '2px 8px',
                                        fontSize: '0.75rem',
                                        width: 'auto',
                                        height: 'auto',
                                        border: 'none',
                                        background: 'transparent'
                                    }}
                                    value={settings.dashboard.trendLineType || 'none'}
                                    onChange={(e) => updateNestedSetting('dashboard', { trendLineType: e.target.value as DashboardTrendLineType })}
                                >
                                    <option value="none">None</option>
                                    <option value="sma">Simple Moving Avg</option>
                                    <option value="ema">Exponential Moving Avg</option>
                                    <option value="savitzky-golay">Savitzky-Golay (Smooth)</option>
                                </select>
                            </div>
                        )}
                    </div>

                    {selectedParam.isManual && (
                        <>
                            <div className={styles.entryForm}>
                                <div className={styles.inputGroup}>
                                    <div className={styles.inputWrapper}>
                                        <Activity size={18} className={styles.inputIcon} />
                                        <input
                                            type="number"
                                            placeholder="New Value"
                                            className={styles.input}
                                            value={newValue}
                                            onChange={(e) => setNewValue(e.target.value)}
                                        />
                                    </div>
                                    <div className={styles.inputWrapper}>
                                        <Calendar size={18} className={styles.inputIcon} />
                                        <input
                                            type="date"
                                            className={styles.input}
                                            value={newDate}
                                            onChange={(e) => setNewDate(e.target.value)}
                                        />
                                    </div>
                                    <button className={styles.addButton} onClick={handleAddReading}>
                                        <Plus size={18} />
                                        <span>Add</span>
                                    </button>
                                </div>
                            </div>

                            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', background: 'rgba(255,255,255,0.03)', padding: '4px 12px', borderRadius: '8px', marginBottom: '1rem' }}>
                                <Activity size={14} style={{ color: '#00b4d8' }} />
                                <span style={{ fontSize: '0.75rem', color: '#778da9', fontWeight: 600, textTransform: 'uppercase' }}>Trend Line:</span>
                                <select
                                    className={styles.input}
                                    style={{
                                        padding: '2px 8px',
                                        fontSize: '0.8rem',
                                        width: 'auto',
                                        height: 'auto',
                                        background: 'transparent',
                                        border: 'none',
                                        color: '#e0e1dd',
                                        cursor: 'pointer'
                                    }}
                                    value={settings.visuals.trendLines?.[selectedParam.id]?.type || 'none'}
                                    onChange={(e) => {
                                        const type = e.target.value as TrendLineType;
                                        updateParamTrendLine({
                                            type,
                                            enabled: type !== 'none',
                                        });
                                    }}
                                >
                                    <option value="none">Off</option>
                                    <option value="sma">SMA</option>
                                    <option value="ema">EMA</option>
                                    <option value="savitzky-golay">SG Filter</option>
                                </select>
                                {settings.visuals.trendLines?.[selectedParam.id]?.type && settings.visuals.trendLines?.[selectedParam.id]?.type !== 'none' && (
                                    <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                                        <input
                                            type="number"
                                            className={styles.input}
                                            style={{ width: '40px', height: '24px', padding: '0 4px', fontSize: '0.75rem', borderBottom: '1px solid rgba(255,255,255,0.1)' }}
                                            value={settings.visuals.trendLines?.[selectedParam.id]?.windowSize || 12}
                                            onChange={(e) => {
                                                const windowSize = parseInt(e.target.value) || 1;
                                                updateParamTrendLine({ windowSize });
                                            }}
                                            title="Smoothing Window Size"
                                        />
                                        {settings.visuals.trendLines?.[selectedParam.id]?.type === 'savitzky-golay' && (
                                            <input
                                                type="number"
                                                className={styles.input}
                                                style={{ width: '30px', height: '24px', padding: '0 4px', fontSize: '0.75rem', borderBottom: '1px solid rgba(255,255,255,0.1)', color: '#fbbf24' }}
                                                value={settings.visuals.trendLines?.[selectedParam.id]?.polynomialOrder || 2}
                                                onChange={(e) => {
                                                    const polynomialOrder = parseInt(e.target.value) || 1;
                                                    updateParamTrendLine({ polynomialOrder });
                                                }}
                                                title="Polynomial Order"
                                                min="1"
                                                max="5"
                                            />
                                        )}
                                    </div>
                                )}
                            </div>
                        </>
                    )}

                    <HistoryGraph
                        title={`${selectedParam.label} (Trend)`}
                        data={activeHistory}
                        rangeHours={historyRange}
                        borderColor={selectedParam.color}
                        backgroundColor={`${selectedParam.color}1a`}
                        yMin={settings.visuals?.yAxisRanges?.[selectedParam.id]?.min ?? null}
                        yMax={settings.visuals?.yAxisRanges?.[selectedParam.id]?.max ?? null}
                        trendLine={
                            selectedParam?.isManual
                                ? settings.visuals.trendLines?.[selectedParam.id]
                                : (settings.visuals.trendLines?.[selectedParam.id]?.type && settings.visuals.trendLines?.[selectedParam.id]?.type !== 'none'
                                    ? settings.visuals.trendLines?.[selectedParam.id]
                                    : {
                                        type: settings.dashboard.trendLineType || 'none',
                                        windowSize: 12
                                    })
                        }
                    />
                </div>
            </div>
        </div>
    );
};
