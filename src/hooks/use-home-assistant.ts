import { useCallback, useEffect, useSyncExternalStore } from 'react';
import { HassEntities } from 'home-assistant-js-websocket';
import { getHAEntities, haCallService } from '@/lib/ha-connection';
import type { HAHistoryResponse } from '@/types/reef';

const getErrorMessage = (err: unknown) => {
    if (err === 1) return 'Network Error: Could not reach the server. Check your URL and network connection.';
    if (err === 2) return 'Authentication Error: Invalid token.';
    if (err === 3) return 'Connection Lost: Check your network.';
    if (err instanceof Error) return err.message;
    return 'Failed to connect to Home Assistant';
};

type HAStoreState = {
    entities: HassEntities | null;
    isConnected: boolean;
    error: string | null;
};

const PAUSED_MESSAGE = 'HA paused - click to connect';

let haStoreState: HAStoreState = {
    entities: null,
    isConnected: false,
    error: PAUSED_MESSAGE,
};

const haStoreListeners = new Set<() => void>();
let activeEntityRequest: Promise<void> | null = null;
let activeEntityController: AbortController | null = null;
let unloadHandlerRegistered = false;

const emitHAStore = () => {
    haStoreListeners.forEach(listener => listener());
};

const setHAStoreState = (nextState: Partial<HAStoreState>) => {
    haStoreState = { ...haStoreState, ...nextState };
    emitHAStore();
};

const subscribeToHAStore = (listener: () => void) => {
    haStoreListeners.add(listener);
    return () => {
        haStoreListeners.delete(listener);
    };
};

const getHAStoreSnapshot = () => haStoreState;

const abortActiveEntityRequest = () => {
    activeEntityController?.abort();
    activeEntityController = null;
    activeEntityRequest = null;
    if (!haStoreState.isConnected) {
        setHAStoreState({ error: PAUSED_MESSAGE });
    }
};

const registerUnloadAbortHandler = () => {
    if (unloadHandlerRegistered || typeof window === 'undefined') return;
    unloadHandlerRegistered = true;
    window.addEventListener('pagehide', abortActiveEntityRequest);
};

const requestEntitiesOnce = async () => {
    if (activeEntityRequest) return activeEntityRequest;

    const controller = new AbortController();
    activeEntityController = controller;
    setHAStoreState({ isConnected: false, error: 'Connecting to HA...' });

    activeEntityRequest = (async () => {
        try {
            const nextEntities = await getHAEntities(controller.signal);
            if (controller.signal.aborted) return;

            setHAStoreState({
                entities: nextEntities,
                isConnected: true,
                error: null,
            });
        } catch (err: unknown) {
            if (controller.signal.aborted) return;
            console.error('[HA] Hook Connection Error:', err);

            setHAStoreState({
                isConnected: false,
                error: getErrorMessage(err),
            });
        } finally {
            if (activeEntityController === controller) {
                activeEntityController = null;
            }
            activeEntityRequest = null;
        }
    })();

    return activeEntityRequest;
};

const requireConnected = () => {
    if (!haStoreState.isConnected) {
        throw new Error(`${PAUSED_MESSAGE}.`);
    }
};

export function useHomeAssistant() {
    const { entities, isConnected, error } = useSyncExternalStore(
        subscribeToHAStore,
        getHAStoreSnapshot,
        getHAStoreSnapshot,
    );

    useEffect(() => {
        registerUnloadAbortHandler();
    }, []);

    const reconnect = useCallback(() => {
        void requestEntitiesOnce();
    }, []);

    const callService = useCallback(async (domain: string, service: string, serviceData?: object) => {
        try {
            requireConnected();
            await haCallService(domain, service, serviceData);
        } catch (err) {
            console.error('HA Service Call Error:', err);
            throw err;
        }
    }, []);

    const toggleSwitch = useCallback(async (entityId: string) => {
        return callService('switch', 'toggle', { entity_id: entityId });
    }, [callService]);

    const turnOffSwitch = useCallback(async (entityId: string) => {
        return callService('switch', 'turn_off', { entity_id: entityId });
    }, [callService]);

    const turnOnSwitch = useCallback(async (entityId: string) => {
        return callService('switch', 'turn_on', { entity_id: entityId });
    }, [callService]);

    const turnOnInputBoolean = useCallback(async (entityId: string) => {
        return callService('input_boolean', 'turn_on', { entity_id: entityId });
    }, [callService]);

    const turnOffInputBoolean = useCallback(async (entityId: string) => {
        return callService('input_boolean', 'turn_off', { entity_id: entityId });
    }, [callService]);

    const pressButton = useCallback(async (entityId: string) => {
        return callService('button', 'press', { entity_id: entityId });
    }, [callService]);

    const updateInputSelect = useCallback(async (entityId: string, option: string) => {
        return callService('input_select', 'select_option', { entity_id: entityId, option });
    }, [callService]);

    const updateInputNumber = useCallback(async (entityId: string, value: number) => {
        return callService('input_number', 'set_value', { entity_id: entityId, value });
    }, [callService]);

    const updateInputDateTime = useCallback(async (entityId: string, timestamp: string) => {
        return callService('input_datetime', 'set_datetime', { entity_id: entityId, datetime: timestamp });
    }, [callService]);

    const fetchHistory = useCallback(async (entityId: string | string[], hours: number = 24): Promise<HAHistoryResponse> => {
        requireConnected();
        const endTime = new Date();
        const startTime = new Date(endTime.getTime() - hours * 60 * 60 * 1000);
        const { getHAHistory } = await import('@/lib/ha-connection');
        return getHAHistory(entityId, startTime, endTime);
    }, []);

    return {
        entities,
        isConnected,
        error,
        callService,
        toggleSwitch,
        turnOffInputBoolean,
        turnOffSwitch,
        turnOnInputBoolean,
        turnOnSwitch,
        pressButton,
        updateInputSelect,
        updateInputNumber,
        updateInputDateTime,
        fetchHistory,
        reconnect,
    };
}
