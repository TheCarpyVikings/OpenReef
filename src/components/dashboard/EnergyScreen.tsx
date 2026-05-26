'use client';

import React from 'react';
import styles from '@/app/dashboard.module.css';
import { useSettings } from '@/context/SettingsContext';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import { Zap, Power } from 'lucide-react';

interface EnergyScreenProps {
    midnightEnergies: Record<string, number>;
    onEquipmentClick: (label: string, entityId: string, icon: React.ReactNode) => void;
}

export const EnergyScreen: React.FC<EnergyScreenProps> = ({ midnightEnergies, onEquipmentClick }) => {
    const { settings, getEquipmentName } = useSettings();
    const { entities } = useHomeAssistant();

    const getEntityState = (entityId: string | undefined) => entityId ? entities?.[entityId]?.state : undefined;

    const getDailyEnergy = (entityId: string | undefined, currentValue: string | undefined) => {
        if (!entityId) return 0;
        const total = currentValue ? parseFloat(currentValue) : NaN;
        const midnight = midnightEnergies[entityId] || 0;

        if (!isNaN(total) && total > 0) {
            const delta = total < midnight ? total : total - midnight;
            return Math.max(0, delta);
        }

        return 0;
    };

    const dailyEnergy = parseFloat(getEntityState(settings.entities.energy.dailyEnergy) || '0');
    const weeklyEnergy = parseFloat(getEntityState(settings.entities.energy.weeklyEnergy) || '0');
    const monthlyEnergy = parseFloat(getEntityState(settings.entities.energy.monthlyEnergy) || '0');
    const currentPower = settings.entities.tankMain?.power ?
        parseFloat(getEntityState(settings.entities.tankMain.power) || '0') :
        Object.values(settings.entities.equipment).reduce((acc, config) => {
            const val = parseFloat(getEntityState(config.power) || '0');
            return acc + (isNaN(val) ? 0 : val);
        }, 0);

    const dailyCost = parseFloat(getEntityState(settings.entities.energy.dailyCost) || '0');
    const weeklyCost = parseFloat(getEntityState(settings.entities.energy.weeklyCost) || '0');
    const monthlyCost = parseFloat(getEntityState(settings.entities.energy.monthlyCost) || '0');
    const annualEstimate = (weeklyCost / 7) * 365;

    return (
        <section className={styles.grid}>
            <h2 className={styles.sectionTitle}>Energy & Cost Tracking</h2>

            {/* Consumption Overview */}
            <div style={{ gridColumn: '1 / -1', marginBottom: '2rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
                    <div className={styles.iconWrapper} style={{ backgroundColor: 'rgba(0, 180, 216, 0.1)', color: '#00b4d8' }}>
                        <Zap size={20} />
                    </div>
                    <h3 className={styles.sectionSubtitle} style={{ margin: 0 }}>Consumption Overview</h3>
                </div>
                <div className={styles.energyStats} style={{ marginTop: 0 }}>
                    <div className={styles.statCard} style={{ borderLeft: '4px solid #00b4d8' }}>
                        <div className={styles.statLabel}>Current Load</div>
                        <div className={styles.statValue}>
                            {currentPower.toFixed(1)} <span className={styles.statUnit}>W</span>
                        </div>
                    </div>
                    <div className={styles.statCard}>
                        <div className={styles.statLabel}>Daily Usage</div>
                        <div className={styles.statValue}>
                            {dailyEnergy.toFixed(0)} <span className={styles.statUnit}>Wh</span>
                        </div>
                    </div>
                    <div className={styles.statCard}>
                        <div className={styles.statLabel}>Weekly Usage</div>
                        <div className={styles.statValue}>
                            {weeklyEnergy.toFixed(0)} <span className={styles.statUnit}>Wh</span>
                        </div>
                    </div>
                    <div className={styles.statCard}>
                        <div className={styles.statLabel}>Monthly Usage</div>
                        <div className={styles.statValue}>
                            {monthlyEnergy.toFixed(0)} <span className={styles.statUnit}>Wh</span>
                        </div>
                    </div>
                </div>
            </div>

            {/* Financial Overview */}
            <div style={{ gridColumn: '1 / -1', marginBottom: '2rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
                    <div className={styles.iconWrapper} style={{ backgroundColor: 'rgba(74, 222, 128, 0.1)', color: '#4ade80' }}>
                        <Power size={20} />
                    </div>
                    <h3 className={styles.sectionSubtitle} style={{ margin: 0 }}>Financial Analysis</h3>
                </div>
                <div className={styles.energyStats} style={{ marginTop: 0 }}>
                    <div className={styles.statCard} style={{ borderLeft: '4px solid #4ade80', background: 'rgba(74, 222, 128, 0.05)' }}>
                        <div className={styles.statLabel}>Daily Cost</div>
                        <div className={styles.statValue}>
                            <span className={styles.statUnit} style={{ marginRight: '2px' }}>£</span>
                            {dailyCost.toFixed(2)}
                        </div>
                    </div>
                    <div className={styles.statCard}>
                        <div className={styles.statLabel}>Weekly Cost</div>
                        <div className={styles.statValue}>
                            <span className={styles.statUnit} style={{ marginRight: '2px' }}>£</span>
                            {weeklyCost.toFixed(2)}
                        </div>
                    </div>
                    <div className={styles.statCard}>
                        <div className={styles.statLabel}>Monthly Cost</div>
                        <div className={styles.statValue}>
                            <span className={styles.statUnit} style={{ marginRight: '2px' }}>£</span>
                            {monthlyCost.toFixed(2)}
                        </div>
                    </div>
                    <div className={styles.statCard} style={{ background: 'rgba(255, 255, 255, 0.02)', borderColor: 'rgba(255, 255, 255, 0.05)' }}>
                        <div className={styles.statLabel}>Estimated Annual</div>
                        <div className={styles.statValue} style={{ opacity: 0.8 }}>
                            <span className={styles.statUnit} style={{ marginRight: '2px' }}>£</span>
                            {annualEstimate.toFixed(0)}
                        </div>
                        <div className={styles.statLabel} style={{ fontSize: '0.7rem', opacity: 0.4, marginTop: '4px' }}>(based on weekly avg)</div>
                    </div>
                </div>
            </div>

            {/* Per-device energy cards */}
            <div style={{ gridColumn: '1 / -1', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '1rem' }}>
                {Object.entries(settings.entities.equipment).map(([key, config]) => {
                    const powerState = getEntityState(config.power);
                    const energyState = getEntityState(config.energy);
                    const powerNum = parseFloat(powerState || '0');
                    const dailyEnergyNum = getDailyEnergy(config.energy, energyState);

                    const label = getEquipmentName(key, key);
                    const isActive = getEntityState(config.switch) === 'on';

                    return (
                        <div key={key} className={`${styles.card} ${styles.clickable}`} onClick={() => onEquipmentClick(label, config.switch, <Zap size={24} />)}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                                    <div className={styles.iconWrapper} style={{ width: 32, height: 32, borderRadius: 8 }}>
                                        <Zap size={16} />
                                    </div>
                                    <span style={{ fontWeight: 600, color: '#e0e1dd' }}>{label}</span>
                                </div>
                                <div style={{
                                    padding: '0.25rem 0.6rem',
                                    background: isActive ? 'rgba(74, 222, 128, 0.1)' : 'rgba(255, 255, 255, 0.05)',
                                    borderRadius: '6px',
                                    fontSize: '0.7rem',
                                    fontWeight: 700,
                                    color: isActive ? '#4ade80' : '#778da9'
                                }}>
                                    {isActive ? 'ACTIVE' : 'IDLE'}
                                </div>
                            </div>

                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                                <div>
                                    <div style={{ fontSize: '0.65rem', color: '#778da9', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.25rem' }}>Current Draw</div>
                                    <div style={{ fontSize: '1.35rem', fontWeight: 700, color: '#fff' }}>
                                        {isNaN(powerNum) ? '0' : powerNum.toFixed(1)} <span style={{ fontSize: '0.8rem', fontWeight: 400, color: '#778da9' }}>W</span>
                                    </div>
                                </div>
                                <div>
                                    <div style={{ fontSize: '0.65rem', color: '#778da9', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.25rem' }}>Daily Consumption</div>
                                    <div style={{ fontSize: '1.35rem', fontWeight: 700, color: '#00b4d8' }}>
                                        {dailyEnergyNum.toFixed(1)} <span style={{ fontSize: '0.8rem', fontWeight: 400, color: '#778da9' }}>Wh</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>
        </section>
    );
};
