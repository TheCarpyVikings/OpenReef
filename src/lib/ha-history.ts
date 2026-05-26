import type { DataPoint, HAHistoryEntry, HAHistoryResponse } from '@/types/reef';

const UNAVAILABLE_STATES = new Set(['unavailable', 'unknown']);

const timestampFromEntry = (entry: HAHistoryEntry): number => {
    let rawTime = entry.last_changed ?? entry.lc ?? entry.last_updated ?? entry.lu;
    if (typeof rawTime === 'number') {
        rawTime *= 1000;
    }
    return new Date(rawTime ?? 0).getTime();
};

const valueFromEntry = (entry: HAHistoryEntry): number => {
    const rawValue = entry.state ?? entry.s;
    return Number.parseFloat(rawValue ?? '');
};

export const getEntityHistory = (
    response: HAHistoryResponse | null | undefined,
    entityId: string,
): HAHistoryEntry[] => {
    if (!response) return [];
    if (Array.isArray(response)) return response[0] ?? [];
    return response[entityId] ?? [];
};

export const historyEntriesToPoints = (
    entries: HAHistoryEntry[],
    options: {
        rangeHours: number;
        now?: number;
        currentState?: string;
        includeBounds?: boolean;
    },
): DataPoint[] => {
    const now = options.now ?? Date.now();
    const start = now - options.rangeHours * 60 * 60 * 1000;

    const points = entries
        .filter((entry) => !UNAVAILABLE_STATES.has(entry.state ?? entry.s ?? ''))
        .map((entry) => ({
            x: timestampFromEntry(entry),
            y: valueFromEntry(entry),
        }))
        .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y) && point.x >= start && point.x <= now)
        .sort((a, b) => a.x - b.x);

    if (options.includeBounds === false) {
        return points;
    }

    if (points.length > 0 && points[0].x > start) {
        points.unshift({ x: start, y: points[0].y });
    } else if (points.length === 0 && options.currentState !== undefined) {
        const currentValue = Number.parseFloat(options.currentState);
        if (Number.isFinite(currentValue)) {
            points.push({ x: start, y: currentValue });
        }
    }

    if (points.length > 0) {
        points.push({ x: now, y: points[points.length - 1].y });
    }

    return points;
};

export const historyResponseToPoints = (
    response: HAHistoryResponse | null | undefined,
    entityId: string,
    options: Parameters<typeof historyEntriesToPoints>[1],
): DataPoint[] => historyEntriesToPoints(getEntityHistory(response, entityId), options);

export const findMidnightValue = (
    response: HAHistoryResponse | null | undefined,
    entityId: string,
    midnight: number,
): number => {
    const sorted = getEntityHistory(response, entityId)
        .filter((entry) => !UNAVAILABLE_STATES.has(entry.state ?? entry.s ?? ''))
        .sort((a, b) => timestampFromEntry(a) - timestampFromEntry(b));

    let midnightValue = 0;
    for (const point of sorted) {
        const timestamp = timestampFromEntry(point);
        if (timestamp <= midnight) {
            midnightValue = valueFromEntry(point) || 0;
        } else {
            break;
        }
    }

    if (midnightValue === 0 && sorted.length > 0) {
        midnightValue = valueFromEntry(sorted[0]) || 0;
    }

    return midnightValue;
};
