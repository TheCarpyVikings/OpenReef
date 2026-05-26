import type { HassEntities } from 'home-assistant-js-websocket';

type HAEntity = HassEntities[string] & {
    entity_id?: string;
    attributes?: {
        friendly_name?: string;
        device_class?: string;
        unit_of_measurement?: string;
        state_class?: string;
    };
};

export type EntitySuggestionTarget = {
    id: string;
    label: string;
    domains: string[];
    keywords: string[];
    prefer?: string[];
    avoid?: string[];
    deviceClasses?: string[];
    units?: string[];
    stateClasses?: string[];
};

export type EntitySuggestion = {
    entityId: string;
    label: string;
    score: number;
    domain: string;
};

const DEFAULT_OPENREEF_ENTITY_IDS = new Set([
    'sensor.tank_temperature',
    'sensor.tank_ph',
    'sensor.tank_sg',
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

const normalize = (value: string) =>
    value
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();

const getDomain = (entityId: string) => entityId.split('.')[0] || '';

const getFriendlyName = (entityId: string, entity: HAEntity) =>
    entity.attributes?.friendly_name?.trim() || entityId;

const hasToken = (haystack: string, needle: string) => {
    const normalizedNeedle = normalize(needle);
    if (!normalizedNeedle) return false;
    return ` ${haystack} `.includes(` ${normalizedNeedle} `);
};

const hasPhrase = (haystack: string, phrase: string) => {
    const normalizedPhrase = normalize(phrase);
    if (!normalizedPhrase) return false;
    return haystack.includes(normalizedPhrase);
};

const scoreTerms = (haystack: string, terms: string[], points: number) =>
    terms.reduce((score, term) => {
        if (term.length <= 3) {
            return score + (hasToken(haystack, term) ? points : 0);
        }
        return score + (hasPhrase(haystack, term) ? points : 0);
    }, 0);

export const shouldReplaceEntitySuggestionValue = (value: string | undefined) => {
    if (!value?.trim()) return true;
    return DEFAULT_OPENREEF_ENTITY_IDS.has(value.trim());
};

export function getEntitySuggestions(
    entities: HassEntities | null,
    target: EntitySuggestionTarget,
    limit = 5,
): EntitySuggestion[] {
    if (!entities) return [];

    return Object.entries(entities)
        .map(([entityId, entity]) => {
            const typedEntity = entity as HAEntity;
            const domain = getDomain(entityId);
            if (!target.domains.includes(domain)) return null;

            const friendlyName = getFriendlyName(entityId, typedEntity);
            const deviceClass = typedEntity.attributes?.device_class || '';
            const unit = typedEntity.attributes?.unit_of_measurement || '';
            const stateClass = typedEntity.attributes?.state_class || '';
            const haystack = normalize([
                entityId,
                friendlyName,
                deviceClass,
                unit,
                stateClass,
            ].join(' '));

            let score = 30;
            score += scoreTerms(haystack, target.keywords, 18);
            score += scoreTerms(haystack, target.prefer || [], 10);
            score -= scoreTerms(haystack, target.avoid || [], 16);

            if (target.deviceClasses?.includes(deviceClass)) score += 35;
            if (target.units?.some(candidate => unit.toLowerCase() === candidate.toLowerCase())) score += 24;
            if (target.stateClasses?.includes(stateClass)) score += 16;
            if (hasPhrase(haystack, 'reef') || hasPhrase(haystack, 'tank') || hasPhrase(haystack, 'aquarium')) score += 5;
            if (entityId === target.id) score += 20;

            return {
                entityId,
                label: friendlyName,
                score,
                domain,
            };
        })
        .filter((suggestion): suggestion is EntitySuggestion => suggestion !== null && suggestion.score > 35)
        .sort((a, b) => b.score - a.score || a.entityId.localeCompare(b.entityId))
        .slice(0, limit);
}

export const getBestEntitySuggestion = (
    entities: HassEntities | null,
    target: EntitySuggestionTarget,
) => getEntitySuggestions(entities, target, 1)[0]?.entityId || '';

export const getSensorSuggestionTarget = (
    key: string,
    label: string,
    group: 'tank' | 'room' | 'manual' = 'tank',
): EntitySuggestionTarget => {
    const tankPrefer = ['reef', 'tank', 'aquarium', 'water', 'saltwater'];
    const roomPrefer = ['room', 'ambient', 'air'];
    const basePrefer = group === 'room' ? roomPrefer : tankPrefer;
    const baseAvoid = group === 'room' ? tankPrefer : roomPrefer;

    const targets: Record<string, Partial<EntitySuggestionTarget>> = {
        temp: {
            keywords: ['temperature', 'temp'],
            deviceClasses: ['temperature'],
            units: ['°C', '°F', 'C', 'F'],
        },
        room_temp: {
            keywords: ['temperature', 'temp', 'room'],
            prefer: roomPrefer,
            avoid: tankPrefer,
            deviceClasses: ['temperature'],
            units: ['°C', '°F', 'C', 'F'],
        },
        ph: {
            keywords: ['ph'],
            avoid: ['phone', 'phase'],
        },
        salinity: {
            keywords: ['salinity', 'specific gravity', 'sg', 'conductivity'],
            prefer: ['ppt', 'salt'],
            units: ['ppt', 'SG', 'sg', 'mS/cm'],
        },
        orp: {
            keywords: ['orp', 'redox'],
            units: ['mV', 'mv'],
        },
        do: {
            keywords: ['dissolved oxygen', 'oxygen', 'o2'],
            units: ['mg/L', 'mg/l', 'ppm'],
        },
        co2: {
            keywords: ['co2', 'carbon dioxide'],
            prefer: roomPrefer,
            avoid: tankPrefer,
            units: ['ppm'],
        },
        humidity: {
            keywords: ['humidity', 'humid'],
            prefer: roomPrefer,
            avoid: tankPrefer,
            deviceClasses: ['humidity'],
            units: ['%'],
        },
        alkalinity: { keywords: ['alkalinity', 'alk', 'dkh'], units: ['dKH', 'dkh'] },
        alk: { keywords: ['alkalinity', 'alk', 'dkh'], units: ['dKH', 'dkh'] },
        calcium: { keywords: ['calcium', 'calc', 'ca'], units: ['ppm', 'mg/L', 'mg/l'] },
        calc: { keywords: ['calcium', 'calc', 'ca'], units: ['ppm', 'mg/L', 'mg/l'] },
        magnesium: { keywords: ['magnesium', 'mag', 'mg'], units: ['ppm', 'mg/L', 'mg/l'] },
        mag: { keywords: ['magnesium', 'mag', 'mg'], units: ['ppm', 'mg/L', 'mg/l'] },
        nitrate: { keywords: ['nitrate', 'no3'], units: ['ppm', 'mg/L', 'mg/l'] },
        phosphate: { keywords: ['phosphate', 'po4'], units: ['ppm', 'mg/L', 'mg/l'] },
    };

    const target = targets[key] || {};

    return {
        id: key,
        label,
        domains: ['sensor'],
        keywords: target.keywords || [label, key],
        prefer: [...basePrefer, ...(target.prefer || [])],
        avoid: [...baseAvoid, ...(target.avoid || [])],
        deviceClasses: target.deviceClasses,
        units: target.units,
        stateClasses: target.stateClasses,
    };
};

const EQUIPMENT_KEYWORDS: Record<string, string[]> = {
    ATO: ['ato', 'auto top off', 'top off'],
    INKBIRD: ['inkbird', 'heater controller', 'temperature controller'],
    RETURN_PUMP: ['return pump', 'return', 'main pump'],
    DOSING_PUMP: ['dosing pump', 'doser', 'dosing'],
    SKIMMER: ['skimmer', 'protein skimmer'],
    WAVEMAKERS: ['wavemaker', 'wave maker', 'powerhead', 'flow pump', 'gyre'],
    HYDRA_EDGE: ['hydra', 'hydra edge', 'ai hydra', 'light'],
    KESSIL: ['kessil', 'light'],
    MAG_STIRRER: ['mag stirrer', 'stirrer', 'magnetic stirrer'],
    AIR_PUMP: ['air pump', 'aerator'],
    RODI: ['rodi', 'ro di', 'reverse osmosis'],
    HEATER: ['heater', 'heating'],
};

export const getEquipmentSuggestionTarget = (
    equipmentKey: string,
    label: string,
    kind: 'switch' | 'power' | 'energy',
): EntitySuggestionTarget => {
    const equipmentKeywords = [
        label,
        equipmentKey,
        ...(EQUIPMENT_KEYWORDS[equipmentKey] || []),
    ];

    if (kind === 'switch') {
        return {
            id: equipmentKey,
            label,
            domains: ['switch'],
            keywords: equipmentKeywords,
            prefer: ['plug', 'socket', 'outlet', 'power'],
            avoid: ['power sensor', 'energy', 'current', 'voltage'],
        };
    }

    if (kind === 'power') {
        return {
            id: `${equipmentKey}_power`,
            label: `${label} power`,
            domains: ['sensor'],
            keywords: equipmentKeywords,
            prefer: ['power', 'watt', 'watts', 'current consumption'],
            avoid: ['energy', 'today', 'daily', 'weekly', 'monthly'],
            deviceClasses: ['power'],
            units: ['W', 'w', 'kW', 'kw'],
        };
    }

    return {
        id: `${equipmentKey}_energy`,
        label: `${label} energy`,
        domains: ['sensor'],
        keywords: equipmentKeywords,
        prefer: ['energy', 'consumption', 'today', 'total'],
        avoid: ['power', 'watt', 'current'],
        deviceClasses: ['energy'],
        units: ['Wh', 'wh', 'kWh', 'kwh'],
        stateClasses: ['total', 'total_increasing'],
    };
};
