'use client';

import React from 'react';
import styles from '@/app/dashboard.module.css';
import { useSettings } from '@/context/SettingsContext';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import { StatusCard } from './StatusCard';
import { Thermometer, Droplets, Activity, Wind } from 'lucide-react';

interface LiveStatsScreenProps {
    onCardClick: (id: string, label: string, color: string, isManual?: boolean) => void;
    dashboardHistory: Record<string, { x: number; y: number }[]>;
}

export const LiveStatsScreen: React.FC<LiveStatsScreenProps> = ({ onCardClick, dashboardHistory }) => {
    const { settings, getLabel } = useSettings();
    const { entities } = useHomeAssistant();

    const getEntityState = (entityId: string | undefined) => entityId ? entities?.[entityId]?.state : undefined;

    const formatRoomValue = (value: string | undefined, decimals: number): string | undefined => {
        if (!value) return value;
        const num = parseFloat(value);
        if (isNaN(num)) return value;
        return num.toFixed(decimals);
    };

    return (
        <>
            <section className={styles.grid}>
                <h2 className={styles.sectionTitle}>Tank Parameters</h2>
                {settings.dashboard.visibleCards.includes('temp') && (
                    <StatusCard
                        label={getLabel('temp', 'Temperature')}
                        value={getEntityState(settings.entities.tank.temp)}
                        unit="°C"
                        min={settings.thresholds.temp?.min}
                        max={settings.thresholds.temp?.max}
                        icon={<Thermometer size={18} style={{ verticalAlign: 'middle', marginRight: 4 }} />}
                        onClick={() => onCardClick('temp', getLabel('temp', 'Temperature'), '#f43f5e')}
                        variant={settings.dashboard.liveStatsView}
                        history={dashboardHistory[settings.entities.tank.temp || '']}
                    />
                )}
                {settings.dashboard.visibleCards.includes('ph') && (
                    <StatusCard
                        label={getLabel('ph', 'pH Level')}
                        value={getEntityState(settings.entities.tank.ph)}
                        unit=""
                        min={settings.thresholds.ph?.min}
                        max={settings.thresholds.ph?.max}
                        icon={<Droplets size={18} style={{ verticalAlign: 'middle', marginRight: 4 }} />}
                        onClick={() => onCardClick('ph', getLabel('ph', 'pH Level'), '#a855f7')}
                        variant={settings.dashboard.liveStatsView}
                        history={dashboardHistory[settings.entities.tank.ph || '']}
                    />
                )}
                {settings.dashboard.visibleCards.includes('salinity') && (
                    <StatusCard
                        label={getLabel('salinity', 'Salinity')}
                        value={getEntityState(settings.entities.tank.salinity)}
                        unit="ppt"
                        min={settings.thresholds.salinity?.min}
                        max={settings.thresholds.salinity?.max}
                        icon={<Activity size={18} style={{ verticalAlign: 'middle', marginRight: 4 }} />}
                        onClick={() => onCardClick('salinity', getLabel('salinity', 'Salinity'), '#3b82f6')}
                        variant={settings.dashboard.liveStatsView}
                        history={dashboardHistory[settings.entities.tank.salinity || '']}
                    />
                )}
                {settings.dashboard.visibleCards.includes('orp') && (
                    <StatusCard
                        label={getLabel('orp', 'ORP')}
                        value={getEntityState(settings.entities.tank.orp)}
                        unit="mV"
                        min={settings.thresholds.orp?.min}
                        max={settings.thresholds.orp?.max}
                        icon={<Activity size={18} style={{ verticalAlign: 'middle', marginRight: 4 }} />}
                        onClick={() => onCardClick('orp', getLabel('orp', 'ORP'), '#eab308')}
                        variant={settings.dashboard.liveStatsView}
                        history={dashboardHistory[settings.entities.tank.orp || '']}
                    />
                )}
                {settings.dashboard.visibleCards.includes('do') && (
                    <StatusCard
                        label={getLabel('do', 'Dissolved O₂')}
                        value={getEntityState(settings.entities.tank.do)}
                        unit="mg/L"
                        min={settings.thresholds.do?.min}
                        max={settings.thresholds.do?.max}
                        icon={<Wind size={18} style={{ verticalAlign: 'middle', marginRight: 4 }} />}
                        onClick={() => onCardClick('do', getLabel('do', 'Dissolved O₂'), '#06b6d4')}
                        variant={settings.dashboard.liveStatsView}
                        history={dashboardHistory[settings.entities.tank.do || '']}
                    />
                )}
                {settings.customSensors.filter(s => s.group === 'tank').map(s => (
                    <StatusCard
                        key={s.id}
                        label={getLabel(s.id, s.label)}
                        value={getEntityState(s.haKey)}
                        unit=""
                        min={settings.thresholds[s.id]?.min}
                        max={settings.thresholds[s.id]?.max}
                        icon={<Activity size={18} style={{ verticalAlign: 'middle', marginRight: 4 }} />}
                        onClick={() => onCardClick(s.id, getLabel(s.id, s.label), '#10b981')}
                        variant={settings.dashboard.liveStatsView}
                        history={dashboardHistory[s.haKey]}
                        isCustom={true}
                    />
                ))}
            </section>

            <section className={styles.grid}>
                <h2 className={styles.sectionTitle}>Room Environment</h2>
                {settings.dashboard.visibleCards.includes('room_temp') && (
                    <StatusCard
                        label={getLabel('room_temp', 'Room Temp')}
                        value={formatRoomValue(getEntityState(settings.entities.room?.temp), 2)}
                        unit="°C"
                        min={settings.thresholds.room_temp?.min}
                        max={settings.thresholds.room_temp?.max}
                        icon={<Thermometer size={18} style={{ verticalAlign: 'middle', marginRight: 4 }} />}
                        onClick={() => onCardClick('room_temp', getLabel('room_temp', 'Room Temp'), '#f97316')}
                        variant={settings.dashboard.liveStatsView}
                        history={dashboardHistory[settings.entities.room?.temp || '']}
                    />
                )}
                {settings.dashboard.visibleCards.includes('co2') && (
                    <StatusCard
                        label={getLabel('co2', 'CO2 Level')}
                        value={formatRoomValue(getEntityState(settings.entities.room?.co2), 2)}
                        unit="ppm"
                        min={settings.thresholds.co2?.min}
                        max={settings.thresholds.co2?.max}
                        icon={<Wind size={18} style={{ verticalAlign: 'middle', marginRight: 4 }} />}
                        onClick={() => onCardClick('co2', getLabel('co2', 'CO2 Level'), '#10b981')}
                        variant={settings.dashboard.liveStatsView}
                        history={dashboardHistory[settings.entities.room?.co2 || '']}
                    />
                )}
                {settings.dashboard.visibleCards.includes('humidity') && (
                    <StatusCard
                        label={getLabel('humidity', 'Humidity')}
                        value={formatRoomValue(getEntityState(settings.entities.room?.humidity), 2)}
                        unit="%"
                        min={settings.thresholds.humidity?.min}
                        max={settings.thresholds.humidity?.max}
                        icon={<Droplets size={18} style={{ verticalAlign: 'middle', marginRight: 4 }} />}
                        onClick={() => onCardClick('humidity', getLabel('humidity', 'Humidity'), '#06b6d4')}
                        variant={settings.dashboard.liveStatsView}
                        history={dashboardHistory[settings.entities.room?.humidity || '']}
                    />
                )}
                {settings.customSensors.filter(s => s.group === 'room').map(s => (
                    <StatusCard
                        key={s.id}
                        label={getLabel(s.id, s.label)}
                        value={getEntityState(s.haKey)}
                        unit=""
                        min={settings.thresholds[s.id]?.min}
                        max={settings.thresholds[s.id]?.max}
                        icon={<Wind size={18} style={{ verticalAlign: 'middle', marginRight: 4 }} />}
                        onClick={() => onCardClick(s.id, getLabel(s.id, s.label), '#10b981')}
                        variant={settings.dashboard.liveStatsView}
                        history={dashboardHistory[s.haKey]}
                        isCustom={true}
                    />
                ))}
            </section>
        </>
    );
};
