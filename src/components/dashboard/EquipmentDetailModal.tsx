'use client';

import React, { useState, useEffect } from 'react';
import styles from '@/app/dashboard.module.css';
import { useSettings } from '@/context/SettingsContext';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import { HistoryGraph } from './HistoryGraph';
import { X, Power } from 'lucide-react';
import { historyResponseToPoints } from '@/lib/ha-history';
import type { DataPoint } from '@/types/reef';

interface SelectedEquipment {
    label: string;
    entityId: string;
    icon: React.ReactNode;
}

interface EquipmentDetailModalProps {
    selectedEquipment: SelectedEquipment;
    onClose: () => void;
}

export const EquipmentDetailModal: React.FC<EquipmentDetailModalProps> = ({ selectedEquipment, onClose }) => {
    const { settings } = useSettings();
    const { entities, toggleSwitch, fetchHistory } = useHomeAssistant();

    const getEntityState = (entityId: string | undefined) => entityId ? entities?.[entityId]?.state : undefined;

    const [historyRange, setHistoryRange] = useState(24);
    const [realHistoryData, setRealHistoryData] = useState<DataPoint[] | null>(null);

    // Find equipment config
    const equipConfig = Object.values(settings.entities.equipment).find(
        (config) => config.switch === selectedEquipment.entityId
    );

    const powerVal = equipConfig ? getEntityState(equipConfig.power) : null;
    const energyVal = equipConfig ? getEntityState(equipConfig.energy) : null;

    useEffect(() => {
        if (!equipConfig?.power) return;

        let cancelled = false;
        const timeout = window.setTimeout(async () => {
            try {
                const data = await fetchHistory(equipConfig.power, historyRange);
                if (data && !cancelled) {
                    setRealHistoryData(historyResponseToPoints(data, equipConfig.power, {
                        rangeHours: historyRange,
                        currentState: entities?.[equipConfig.power]?.state,
                    }));
                }
            } catch (err) {
                console.error('Failed to fetch equipment history:', err);
            }
        }, 0);

        return () => {
            cancelled = true;
            window.clearTimeout(timeout);
        };
    }, [equipConfig?.power, historyRange, fetchHistory, entities]);

    return (
        <div className={styles.modalOverlay} onClick={onClose}>
            <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
                <div className={styles.modalHeader}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                        <div className={styles.iconWrapper} style={{ width: 48, height: 48 }}>
                            {selectedEquipment.icon}
                        </div>
                        <h3 className={styles.modalTitle}>{selectedEquipment.label} Monitor</h3>
                    </div>
                    <button className={styles.closeButton} onClick={onClose}>
                        <X size={24} />
                    </button>
                </div>
                <div className={styles.modalBody}>
                    <div className={styles.energyStats}>
                        <div className={styles.statCard}>
                            <div className={styles.statLabel}>Current Power</div>
                            <div className={styles.statValue}>
                                {powerVal || '0'} <span className={styles.statUnit}>W</span>
                            </div>
                        </div>
                        <div className={styles.statCard}>
                            <div className={styles.statLabel}>Daily Energy</div>
                            <div className={styles.statValue}>
                                {energyVal || '0'} <span className={styles.statUnit}>kWh</span>
                            </div>
                        </div>
                        <div className={styles.statCard}>
                            <div className={styles.statLabel}>Status</div>
                            <div className={`${styles.statValue} ${getEntityState(selectedEquipment.entityId) === 'on' ? styles.statusActive : ''}`} style={{ fontSize: '1.2rem', textTransform: 'uppercase' }}>
                                {getEntityState(selectedEquipment.entityId) === 'on' ? 'Active' : 'Inactive'}
                            </div>
                        </div>
                    </div>

                    <div style={{ marginTop: '2rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                            <h4 className={styles.sectionSubtitle}>Power Consumption</h4>
                            <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                                <div className={styles.rangeSelector}>
                                    {[
                                        { label: '1H', hours: 1 },
                                        { label: '6H', hours: 6 },
                                        { label: '24H', hours: 24 },
                                        { label: '7D', hours: 168 },
                                        { label: '30D', hours: 720 },
                                    ].map(opt => (
                                        <button
                                            key={opt.label}
                                            className={`${styles.rangeButton} ${historyRange === opt.hours ? styles.rangeActive : ''}`}
                                            onClick={() => setHistoryRange(opt.hours)}
                                        >
                                            {opt.label}
                                        </button>
                                    ))}
                                </div>
                                <button
                                    className={`${styles.toggleButton} ${getEntityState(selectedEquipment.entityId) === 'on' ? styles.toggleOn : ''}`}
                                    style={{ width: 'auto', padding: '0.5rem 1rem', borderRadius: '8px', gap: '0.5rem' }}
                                    onClick={() => toggleSwitch(selectedEquipment.entityId)}
                                >
                                    <Power size={18} />
                                    <span>{getEntityState(selectedEquipment.entityId) === 'on' ? 'Power OFF' : 'Power ON'}</span>
                                </button>
                            </div>
                        </div>
                        <HistoryGraph
                            title="Power Usage (Watts)"
                            data={realHistoryData || []}
                            rangeHours={historyRange}
                            borderColor="#00b4d8"
                            backgroundColor="rgba(0, 180, 216, 0.1)"
                        />
                    </div>
                </div>
            </div>
        </div>
    );
};
