import type { EntitySuggestionTarget } from './entity-suggestions';
import type { OpenReefEntityCandidate } from '@/types/reef';

const normalizeStem = (value: string) => value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .replace(/_+/g, '_');

const titleFromEntityId = (entityId: string) => entityId
    .split('.', 2)[1]
    ?.replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase()) || entityId;

const add = (
    candidates: Map<string, OpenReefEntityCandidate>,
    entityId: string,
    score: number,
) => {
    const domain = entityId.split('.', 1)[0] || '';
    candidates.set(entityId, {
        entity_id: entityId,
        name: titleFromEntityId(entityId),
        domain,
        device_class: null,
        unit: null,
        area: null,
        score,
    });
};

const addSensor = (candidates: Map<string, OpenReefEntityCandidate>, stem: string, score: number) => {
    add(candidates, `sensor.${stem}`, score);
};

const addSwitch = (candidates: Map<string, OpenReefEntityCandidate>, stem: string, score: number) => {
    add(candidates, `switch.${stem}`, score);
};

const sensorSuggestions = (
    target: EntitySuggestionTarget,
    candidates: Map<string, OpenReefEntityCandidate>,
) => {
    const id = normalizeStem(target.id);
    const label = normalizeStem(target.label);
    const keywords = target.keywords.map(normalizeStem).filter(Boolean);
    const hasDeviceClass = (deviceClass: string) => target.deviceClasses?.includes(deviceClass);
    const hasKeyword = (keyword: string) => keywords.some((term) => term.includes(keyword));

    if (id === 'temp') {
        ['tank_temperature', 'tank_temp', 'reef_temperature', 'aquarium_temperature', 'temperature'].forEach((stem, index) => addSensor(candidates, stem, 100 - index));
        return;
    }

    if (id === 'room_temp') {
        ['room_temperature', 'room_temp', 'ambient_temperature', 'air_temperature', 'temperature'].forEach((stem, index) => addSensor(candidates, stem, 100 - index));
        return;
    }

    if (id === 'ph') {
        ['tank_ph', 'reef_ph', 'aquarium_ph', 'ph'].forEach((stem, index) => addSensor(candidates, stem, 100 - index));
        return;
    }

    if (id === 'salinity') {
        ['tank_salinity', 'tank_sg', 'reef_salinity', 'specific_gravity', 'salinity'].forEach((stem, index) => addSensor(candidates, stem, 100 - index));
        return;
    }

    if (id === 'co2') {
        ['room_co2', 'co2', 'carbon_dioxide', 'air_co2'].forEach((stem, index) => addSensor(candidates, stem, 100 - index));
        return;
    }

    if (id === 'humidity') {
        ['room_humidity', 'humidity', 'air_humidity'].forEach((stem, index) => addSensor(candidates, stem, 100 - index));
        return;
    }

    if (hasDeviceClass('power') || hasKeyword('power')) {
        const stem = id.replace(/_power$/, '') || label;
        [stem, label].filter(Boolean).forEach((base, index) => {
            addSensor(candidates, `${base}_power`, 100 - index);
            addSensor(candidates, `${base}_watts`, 90 - index);
        });
        return;
    }

    if (hasDeviceClass('energy') || hasKeyword('energy')) {
        const stem = id.replace(/_energy$/, '') || label;
        [stem, label].filter(Boolean).forEach((base, index) => {
            addSensor(candidates, `${base}_energy`, 100 - index);
            addSensor(candidates, `${base}_daily_energy`, 90 - index);
        });
        return;
    }

    [id, label, ...keywords].filter(Boolean).forEach((stem, index) => {
        addSensor(candidates, stem, 80 - index);
        addSensor(candidates, `reef_${stem}`, 70 - index);
    });
};

const switchSuggestions = (
    target: EntitySuggestionTarget,
    candidates: Map<string, OpenReefEntityCandidate>,
) => {
    const id = normalizeStem(target.id);
    const label = normalizeStem(target.label);
    const bases = Array.from(new Set([id, label, ...target.keywords.map(normalizeStem)].filter(Boolean)));

    bases.slice(0, 4).forEach((base, index) => {
        addSwitch(candidates, `${base}_plug`, 100 - index);
        addSwitch(candidates, base, 90 - index);
        addSwitch(candidates, `${base}_switch`, 80 - index);
        addSwitch(candidates, `${base}_socket`, 70 - index);
    });
};

export const getLocalEntitySuggestions = (
    target: EntitySuggestionTarget,
    currentValue?: string,
    placeholder?: string,
): OpenReefEntityCandidate[] => {
    const candidates = new Map<string, OpenReefEntityCandidate>();

    if (currentValue?.includes('.')) add(candidates, currentValue, 120);
    if (placeholder?.includes('.')) add(candidates, placeholder, 115);

    if (target.domains.includes('switch')) {
        switchSuggestions(target, candidates);
    } else {
        sensorSuggestions(target, candidates);
    }

    return Array.from(candidates.values())
        .sort((a, b) => b.score - a.score || a.entity_id.localeCompare(b.entity_id))
        .slice(0, 10);
};
