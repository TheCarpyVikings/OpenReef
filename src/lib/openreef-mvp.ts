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

const DEFAULT_PLACEHOLDER_ENTITY_IDS = new Set([
    'sensor.tank_temperature',
    'sensor.tank_ph',
    'sensor.tank_sg',
    'sensor.tank_salinity',
    'sensor.tank_orp',
    'sensor.tank_do',
    'sensor.room_temperature',
    'sensor.room_co2',
    'sensor.room_humidity',
    'switch.ato_plug',
    'sensor.ato_power',
    'sensor.ato_energy',
    'switch.inkbird_plug',
    'sensor.inkbird_power',
    'sensor.inkbird_energy',
    'switch.return_pump_plug',
    'sensor.return_pump_power',
    'sensor.return_pump_energy',
    'switch.dosing_pump_plug',
    'sensor.dosing_pump_power',
    'sensor.dosing_pump_energy',
    'switch.skimmer_plug',
    'sensor.skimmer_power',
    'sensor.skimmer_energy',
    'switch.wavemakers_plug',
    'sensor.wavemakers_power',
    'sensor.wavemakers_energy',
    'switch.hydra_edge_plug',
    'sensor.hydra_edge_power',
    'sensor.hydra_edge_energy',
    'switch.kessil_plug',
    'sensor.kessil_power',
    'sensor.kessil_energy',
    'switch.mag_stirrer_plug',
    'sensor.mag_stirrer_power',
    'sensor.mag_stirrer_energy',
    'switch.air_pump_eheim_plug',
    'sensor.air_pump_power',
    'sensor.air_pump_energy',
    'switch.rodi_plug',
    'sensor.rodi_power',
    'sensor.rodi_energy',
    'switch.heater_plug',
    'sensor.heater_power',
    'sensor.heater_energy',
]);

const isEntityId = (value: string | undefined) => Boolean(value && /^[a-z0-9_]+\.[a-z0-9_]+$/.test(value));

const isUserMappedEntityId = (value: string | undefined) => (
    isEntityId(value) && !DEFAULT_PLACEHOLDER_ENTITY_IDS.has(value!)
);

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
        if (isUserMappedEntityId(config.switch)) ids.add(config.switch);
        if (isUserMappedEntityId(config.power)) ids.add(config.power);
        if (isUserMappedEntityId(config.energy)) ids.add(config.energy);
    });

    Object.values(settings.entities.energy).forEach((entityId) => {
        if (isUserMappedEntityId(entityId)) ids.add(entityId);
    });

    if (isUserMappedEntityId(settings.entities.tankMain.power)) ids.add(settings.entities.tankMain.power);
    if (isUserMappedEntityId(settings.entities.tankMain.energy)) ids.add(settings.entities.tankMain.energy);

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
