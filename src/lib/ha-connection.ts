import type { HassEntities } from 'home-assistant-js-websocket';
import { apiFetch } from '@/lib/api-fetch';
import type {
    HAHistoryResponse,
    OpenReefEntitySearchResponse,
    OpenReefRuntimeEntity,
    OpenReefRuntimeStateResponse,
    OpenReefToggleEquipmentResponse,
} from '@/types/reef';
import type { EntitySuggestionTarget } from './entity-suggestions';

export const setHAConfig = (url: string, token: string) => {
    void url;
    void token;
    // HA credentials are intentionally server-side in OpenReef add-on mode.
};

export const disconnectHA = () => {
    // Server-side gateway connections are short lived per API request.
};

export const getCurrentHAConfig = () => ({
    baseUrl: 'server-side',
    token: '',
    isConnected: false,
});

export const getHAConnection = async () => true;

const runtimeStatesToEntities = (states: OpenReefRuntimeEntity[]): HassEntities => {
    const entities = states.reduce<Record<string, unknown>>((acc, state) => {
        acc[state.entity_id] = {
            entity_id: state.entity_id,
            state: state.state ?? 'unavailable',
            attributes: {
                unit_of_measurement: state.unit ?? undefined,
            },
            last_changed: state.last_changed ?? '',
            last_updated: state.last_changed ?? '',
            context: { id: '', parent_id: null, user_id: null },
        };
        return acc;
    }, {});

    return entities as HassEntities;
};

export const getHARuntimeState = async (
    entityIds?: string[],
    signal?: AbortSignal,
): Promise<HassEntities> => {
    const response = await apiFetch('/api/ha/runtime-state', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entityIds }),
        signal,
    });

    if (!response.ok) {
        const body = await response.json().catch(() => ({})) as { error?: string };
        throw new Error(body.error || 'Failed to fetch OpenReef runtime state');
    }

    const data = await response.json() as OpenReefRuntimeStateResponse;
    return runtimeStatesToEntities(data.states || []);
};

export const getHAEntities = async (signal?: AbortSignal): Promise<HassEntities> => (
    getHARuntimeState(undefined, signal)
);

export const searchHAEntities = async (
    target: EntitySuggestionTarget,
    signal?: AbortSignal,
) => {
    const response = await apiFetch('/api/ha/search-entities', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target, limit: 10 }),
        signal,
    });

    if (!response.ok) {
        const body = await response.json().catch(() => ({})) as { error?: string };
        throw new Error(body.error || 'Failed to search Home Assistant entities');
    }

    return response.json() as Promise<OpenReefEntitySearchResponse>;
};

export const subscribeToEntities = (callback: (entities: HassEntities) => void) => {
    void callback;
    // The browser now requests small OpenReef runtime snapshots instead of holding an HA websocket token.
    return undefined;
};

export const haCallService = async (
    domain: string,
    service: string,
    serviceData?: object,
) => {
    const response = await apiFetch('/api/ha/service', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain, service, serviceData: serviceData || {} }),
    });

    if (!response.ok) {
        const body = await response.json().catch(() => ({})) as { error?: string };
        throw new Error(body.error || 'Failed to call Home Assistant service');
    }

    return response.json();
};

export const toggleOpenReefEquipment = async (equipmentId: string) => {
    const response = await apiFetch('/api/ha/toggle-equipment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ equipmentId }),
    });

    if (!response.ok) {
        const body = await response.json().catch(() => ({})) as { error?: string };
        throw new Error(body.error || 'Failed to toggle OpenReef equipment');
    }

    return response.json() as Promise<OpenReefToggleEquipmentResponse>;
};

export const getHAHistory = async (
    entityId: string | string[],
    startTime: Date,
    endTime: Date,
): Promise<HAHistoryResponse> => {
    const response = await apiFetch('/api/ha/history', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            entityId,
            startTime: startTime.toISOString(),
            endTime: endTime.toISOString(),
        }),
    });

    if (!response.ok) {
        const body = await response.json().catch(() => ({})) as { error?: string };
        throw new Error(body.error || 'Failed to fetch Home Assistant history');
    }

    const data = await response.json() as { history: HAHistoryResponse };
    return data.history;
};
