'use client';

import React from 'react';
import styles from '@/app/dashboard.module.css';
import { useSettings } from '@/context/SettingsContext';
import { StatusCard } from './StatusCard';
import { FlaskRound, Beaker, Activity } from 'lucide-react';
import { RefreshCw } from 'lucide-react';
import { useNow } from '@/hooks/use-now';

interface ManualStatsScreenProps {
    onCardClick: (id: string, label: string, color: string, isManual?: boolean) => void;
}

export const ManualStatsScreen: React.FC<ManualStatsScreenProps> = ({ onCardClick }) => {
    const { settings, getLabel, manualReadings, syncManualReadingsWithSheets, isSyncing } = useSettings();
    const now = useNow(60 * 60 * 1000);

    const getLatestManualValue = (id: string) => {
        const readings = manualReadings[id];
        if (!readings || readings.length === 0) return '--';
        return readings[readings.length - 1].value.toString();
    };

    const getLatestManualDateObj = (id: string) => {
        const readings = manualReadings[id];
        if (!readings || readings.length === 0) return null;
        return new Date(readings[readings.length - 1].date);
    };

    const getLatestManualDateDisplay = (id: string) => {
        const d = getLatestManualDateObj(id);
        if (!d) return undefined;
        try {
            return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
        } catch {
            return undefined;
        }
    };

    const isTestStale = (id: string) => {
        const d = getLatestManualDateObj(id);
        if (!d || now === 0) return false;
        const daysSince = (now - d.getTime()) / (1000 * 60 * 60 * 24);
        if (id === 'alk') return daysSince > 7;
        if (id === 'calc' || id === 'mag') return daysSince > 14;
        if (id === 'salinity') return daysSince > 14;
        return daysSince > 14; // Default to 14 days for other tests
    };

    return (
        <section className={styles.grid}>
            <div style={{ gridColumn: '1 / -1', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h2 className={styles.sectionTitle} style={{ margin: 0 }}>Manual Parameters</h2>
                {settings.general.googleSheetId && (
                    <button
                        className={styles.actionButton}
                        onClick={() => syncManualReadingsWithSheets()}
                        disabled={isSyncing}
                        style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', opacity: isSyncing ? 0.6 : 1 }}
                    >
                        <RefreshCw size={14} className={isSyncing ? styles.spinning : ''} />
                        {isSyncing ? 'Syncing...' : 'Sync with Sheets'}
                    </button>
                )}
            </div>
            <StatusCard
                label={getLabel('alk', 'Alkalinity')}
                value={getLatestManualValue('alk')}
                unit="dKH"
                min={settings.thresholds.alk?.min}
                max={settings.thresholds.alk?.max}
                icon={<FlaskRound size={18} style={{ verticalAlign: 'middle', marginRight: 4 }} />}
                onClick={() => onCardClick('alk', getLabel('alk', 'Alkalinity'), '#f43f5e', true)}
                variant={settings.dashboard.manualStatsView}
                lastTested={getLatestManualDateDisplay('alk')}
                isStale={isTestStale('alk')}
            />
            <StatusCard
                label={getLabel('calc', 'Calcium')}
                value={getLatestManualValue('calc')}
                unit="ppm"
                min={settings.thresholds.calc?.min}
                max={settings.thresholds.calc?.max}
                icon={<Beaker size={18} style={{ verticalAlign: 'middle', marginRight: 4 }} />}
                onClick={() => onCardClick('calc', getLabel('calc', 'Calcium'), '#f59e0b', true)}
                variant={settings.dashboard.manualStatsView}
                lastTested={getLatestManualDateDisplay('calc')}
                isStale={isTestStale('calc')}
            />
            <StatusCard
                label={getLabel('mag', 'Magnesium')}
                value={getLatestManualValue('mag')}
                unit="ppm"
                min={settings.thresholds.mag?.min}
                max={settings.thresholds.mag?.max}
                icon={<Activity size={18} style={{ verticalAlign: 'middle', marginRight: 4 }} />}
                onClick={() => onCardClick('mag', getLabel('mag', 'Magnesium'), '#10b981', true)}
                variant={settings.dashboard.manualStatsView}
                lastTested={getLatestManualDateDisplay('mag')}
                isStale={isTestStale('mag')}
            />
            <StatusCard
                label={getLabel('salinity', 'Salinity')}
                value={getLatestManualValue('salinity')}
                unit="sg"
                min={settings.thresholds.salinity?.min}
                max={settings.thresholds.salinity?.max}
                icon={<Activity size={18} style={{ verticalAlign: 'middle', marginRight: 4 }} />}
                onClick={() => onCardClick('salinity', getLabel('salinity', 'Salinity'), '#0284c7', true)}
                variant={settings.dashboard.manualStatsView}
                lastTested={getLatestManualDateDisplay('salinity')}
                isStale={isTestStale('salinity')}
            />
            <StatusCard
                label={getLabel('nitrate', 'Nitrate')}
                value={getLatestManualValue('nitrate')}
                unit="ppm"
                min={settings.thresholds.nitrate?.min}
                max={settings.thresholds.nitrate?.max}
                icon={<Activity size={18} style={{ verticalAlign: 'middle', marginRight: 4 }} />}
                onClick={() => onCardClick('nitrate', getLabel('nitrate', 'Nitrate'), '#eab308', true)}
                variant={settings.dashboard.manualStatsView}
                lastTested={getLatestManualDateDisplay('nitrate')}
                isStale={isTestStale('nitrate')}
            />
            <StatusCard
                label={getLabel('phosphate', 'Phosphate')}
                value={getLatestManualValue('phosphate')}
                unit="ppm"
                min={settings.thresholds.phosphate?.min}
                max={settings.thresholds.phosphate?.max}
                icon={<Activity size={18} style={{ verticalAlign: 'middle', marginRight: 4 }} />}
                onClick={() => onCardClick('phosphate', getLabel('phosphate', 'Phosphate'), '#f97316', true)}
                variant={settings.dashboard.manualStatsView}
                lastTested={getLatestManualDateDisplay('phosphate')}
                isStale={isTestStale('phosphate')}
            />
            {settings.customSensors.filter(s => s.group === 'manual').map(s => (
                <StatusCard
                    key={s.id}
                    label={getLabel(s.id, s.label)}
                    value={getLatestManualValue(s.id)}
                    unit=""
                    min={settings.thresholds[s.id]?.min}
                    max={settings.thresholds[s.id]?.max}
                    icon={<Activity size={18} style={{ verticalAlign: 'middle', marginRight: 4 }} />}
                    onClick={() => onCardClick(s.id, getLabel(s.id, s.label), '#a855f7', true)}
                    variant={settings.dashboard.manualStatsView}
                    isCustom={true}
                    lastTested={getLatestManualDateDisplay(s.id)}
                    isStale={isTestStale(s.id)}
                />
            ))}
        </section>
    );
};
