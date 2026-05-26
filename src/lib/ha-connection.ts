import type { HassEntities } from 'home-assistant-js-websocket';
import { apiFetch } from '@/lib/api-fetch';
import type { HAHistoryResponse } from '@/types/reef';

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

export const getHAEntities = async (signal?: AbortSignal): Promise<HassEntities> => {
    const response = await apiFetch('/api/ha/entities', { signal });
    if (!response.ok) {
        const body = await response.json().catch(() => ({})) as { error?: string };
        throw new Error(body.error || 'Failed to fetch Home Assistant entities');
    }

    const data = await response.json() as { entities: HassEntities };
    return data.entities;
};

export const subscribeToEntities = (callback: (entities: HassEntities) => void) => {
    void callback;
    // The browser now polls the server-side gateway instead of holding an HA websocket token.
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
