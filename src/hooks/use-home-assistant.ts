import { useState, useEffect, useCallback } from 'react';
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

export function useHomeAssistant() {
    const [entities, setEntities] = useState<HassEntities | null>(null);
    const [isConnected, setIsConnected] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [reconnectTrigger, setReconnectTrigger] = useState(0);

    const reconnect = useCallback(() => {
        setReconnectTrigger(prev => prev + 1);
    }, []);

    useEffect(() => {
        let isMounted = true;

        const fetchEntities = async () => {
            setIsConnected(false);
            try {
                const nextEntities = await getHAEntities();
                if (!isMounted) return;

                setEntities(nextEntities);
                setIsConnected(true);
                setError(null);
            } catch (err: unknown) {
                if (!isMounted) return;
                console.error('[HA] Hook Connection Error:', err);

                setError(getErrorMessage(err));
                setIsConnected(false);
            }
        };

        fetchEntities();
        const interval = setInterval(fetchEntities, 5000);

        return () => {
            isMounted = false;
            clearInterval(interval);
        };
    }, [reconnectTrigger]);

    const callService = useCallback(async (domain: string, service: string, serviceData?: object) => {
        try {
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
