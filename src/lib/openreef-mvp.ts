import type { HassEntities } from 'home-assistant-js-websocket';
import type { AppSettings } from '@/context/SettingsContext';

export const MVP_SENSOR_IDS = ['temp', 'ph', 'salinity', 'room_temp', 'co2', 'humidity'] as const;

export type MvpSensorId = typeof MVP_SENSOR_IDS[number];

export const MVP_SENSOR_META: Record<MvpSensorId, {
    label: string;
    unit: string;
    group: 'tank' | 'room';
    key: 'temp' | 'ph' | 'salinity' | 'co2' | 'humidity';
}> = {
    temp: { label: 'Temperature', unit: '°C', group: 'tank', key: 'temp' },
    ph: { label: 'pH Level', unit: '', group: 'tank', key: 'ph' },
    salinity: { label: 'Salinity', unit: 'ppt', group: 'tank', key: 'salinity' },
    room_temp: { label: 'Room Temp', unit: '°C', group: 'room', key: 'temp' },
    co2: { label: 'CO2 Level', unit: 'ppm', group: 'room', key: 'co2' },
    humidity: { label: 'Humidity', unit: '%', group: 'room', key: 'humidity' },
};

const isEntityId = (value: string | undefined) => Boolean(value && /^[a-z0-9_]+\.[a-z0-9_]+$/.test(value));

export const getMvpSensorEntityId = (settings: AppSettings, sensorId: MvpSensorId) => {
    const meta = MVP_SENSOR_META[sensorId];
    return meta.group === 'tank'
        ? settings.entities.tank[meta.key as keyof typeof settings.entities.tank]
        : settings.entities.room[meta.key as keyof typeof settings.entities.room];
};

export const getMvpEntityIds = (settings: AppSettings) => {
    const ids = new Set<string>();

    MVP_SENSOR_IDS.forEach((sensorId) => {
        const entityId = getMvpSensorEntityId(settings, sensorId);
        if (isEntityId(entityId)) ids.add(entityId);
    });

    Object.values(settings.entities.equipment).forEach((config) => {
        if (isEntityId(config.switch)) ids.add(config.switch);
        if (isEntityId(config.power)) ids.add(config.power);
        if (isEntityId(config.energy)) ids.add(config.energy);
    });

    Object.values(settings.entities.energy).forEach((entityId) => {
        if (isEntityId(entityId)) ids.add(entityId);
    });

    if (isEntityId(settings.entities.tankMain.power)) ids.add(settings.entities.tankMain.power);
    if (isEntityId(settings.entities.tankMain.energy)) ids.add(settings.entities.tankMain.energy);

    return Array.from(ids);
};

export const getEntityState = (entities: HassEntities | null, entityId: string | undefined) => (
    entityId ? entities?.[entityId]?.state : undefined
);

export const parseEntityNumber = (entities: HassEntities | null, entityId: string | undefined) => {
    const state = getEntityState(entities, entityId);
    if (state === undefined) return NaN;
    const value = parseFloat(state);
    return Number.isFinite(value) ? value : NaN;
};

export const formatNumber = (value: number, decimals = 1) => (
    Number.isFinite(value) ? value.toFixed(decimals) : '--'
);

export const sensorStatus = (value: number, threshold?: { min: number; max: number }) => {
    if (!Number.isFinite(value) || !threshold) return 'unknown' as const;
    if (value < threshold.min || value > threshold.max) return 'critical' as const;
    const buffer = (threshold.max - threshold.min) * 0.1;
    if (value < threshold.min + buffer || value > threshold.max - buffer) return 'warning' as const;
    return 'ok' as const;
};
