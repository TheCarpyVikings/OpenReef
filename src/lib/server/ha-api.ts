import 'server-only';

import WebSocket from 'ws';
import type { HassEntities } from 'home-assistant-js-websocket';
import type { HAHistoryResponse } from '@/types/reef';

export type HAState = {
    entity_id: string;
    state: string;
    attributes?: Record<string, unknown>;
    last_changed?: string;
    last_updated?: string;
    context?: {
        id: string;
        parent_id: string | null;
        user_id: string | null;
    };
};

export class HAApiError extends Error {
    status: number;

    constructor(message: string, status = 502) {
        super(message);
        this.name = 'HAApiError';
        this.status = status;
    }
}

const trimTrailingSlash = (value: string) => value.replace(/\/$/, '');

export const getHABaseUrl = () => {
    if (process.env.HA_ADDON_MODE === 'true') {
        return 'http://supervisor/core';
    }

    const configuredUrl = process.env.HA_URL || process.env.NEXT_PUBLIC_HA_URL || '';
    return configuredUrl ? trimTrailingSlash(configuredUrl) : '';
};

export const getHAToken = () => process.env.SUPERVISOR_TOKEN || process.env.HA_TOKEN || '';

const requireHAConfig = () => {
    const baseUrl = getHABaseUrl();
    const token = getHAToken();

    if (!baseUrl || !token) {
        throw new HAApiError('Home Assistant is not configured', 503);
    }

    return { baseUrl, token };
};

export async function haRestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
    const { baseUrl, token } = requireHAConfig();
    const response = await fetch(`${baseUrl}${path}`, {
        ...init,
        cache: 'no-store',
        headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
            ...(init.headers || {}),
        },
    });

    if (!response.ok) {
        const body = await response.text().catch(() => '');
        throw new HAApiError(`Home Assistant returned ${response.status}: ${body}`, response.status);
    }

    return response.json() as Promise<T>;
}

export async function callHAService(
    domain: string,
    service: string,
    serviceData: Record<string, unknown>,
) {
    return haRestJson<unknown>(`/api/services/${domain}/${service}`, {
        method: 'POST',
        body: JSON.stringify(serviceData),
    });
}

export function statesToEntities(states: HAState[]): HassEntities {
    const entities: Record<string, HAState> = {};
    states.forEach((state) => {
        entities[state.entity_id] = {
            ...state,
            attributes: state.attributes || {},
            context: state.context || { id: '', parent_id: null, user_id: null },
        };
    });
    return entities as unknown as HassEntities;
}

export async function getHAEntities(): Promise<HassEntities> {
    const states = await haRestJson<HAState[]>('/api/states');
    return statesToEntities(states);
}

type HAWebSocketResult<T> = {
    id: number;
    type: 'result';
    success: boolean;
    result?: T;
    error?: { code?: string; message?: string };
};

export async function haWebSocketCommand<T>(
    payload: Record<string, unknown>,
    timeoutMs = 15000,
): Promise<T> {
    const { baseUrl, token } = requireHAConfig();
    const wsUrl = `${baseUrl.replace(/^http/, 'ws')}/api/websocket`;
    const messageId = 1;

    return new Promise<T>((resolve, reject) => {
        const ws = new WebSocket(wsUrl);
        let settled = false;

        const settle = (fn: () => void) => {
            if (settled) return;
            settled = true;
            clearTimeout(timeout);
            ws.close();
            fn();
        };

        const timeout = setTimeout(() => {
            settle(() => reject(new HAApiError('Timed out waiting for Home Assistant', 504)));
        }, timeoutMs);

        ws.on('message', (raw) => {
            let message: Record<string, unknown>;
            try {
                message = JSON.parse(raw.toString()) as Record<string, unknown>;
            } catch (error) {
                settle(() => reject(error));
                return;
            }

            if (message.type === 'auth_required') {
                ws.send(JSON.stringify({ type: 'auth', access_token: token }));
                return;
            }

            if (message.type === 'auth_invalid') {
                settle(() => reject(new HAApiError('Home Assistant rejected the token', 401)));
                return;
            }

            if (message.type === 'auth_ok') {
                ws.send(JSON.stringify({ ...payload, id: messageId }));
                return;
            }

            if (message.type === 'result' && message.id === messageId) {
                const resultMessage = message as HAWebSocketResult<T>;
                if (resultMessage.success) {
                    settle(() => resolve(resultMessage.result as T));
                } else {
                    settle(() =>
                        reject(
                            new HAApiError(
                                resultMessage.error?.message || 'Home Assistant websocket command failed',
                                502,
                            ),
                        ),
                    );
                }
            }
        });

        ws.on('error', (error) => {
            settle(() => reject(error));
        });
    });
}

export async function getHAHistory(
    entityId: string | string[],
    startTime: string,
    endTime: string,
): Promise<HAHistoryResponse> {
    return haWebSocketCommand<HAHistoryResponse>({
        type: 'history/history_during_period',
        start_time: startTime,
        end_time: endTime,
        entity_ids: Array.isArray(entityId) ? entityId : [entityId],
        no_attributes: true,
    });
}
