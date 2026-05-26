import { NextResponse } from 'next/server';
import { getHAEntities, HAApiError } from '@/lib/server/ha-api';
import type { HassEntities } from 'home-assistant-js-websocket';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const FRESH_CACHE_MS = 15_000;
const STALE_CACHE_MS = 5 * 60_000;

let entityCache: {
    timestamp: number;
    entities: HassEntities;
} | null = null;

export async function GET(request: Request) {
    const now = Date.now();

    if (entityCache && now - entityCache.timestamp < FRESH_CACHE_MS) {
        return NextResponse.json({ entities: entityCache.entities, cached: true });
    }

    try {
        const entities = await getHAEntities(request.signal);
        entityCache = { timestamp: now, entities };
        return NextResponse.json({ entities });
    } catch (error) {
        const status = error instanceof HAApiError ? error.status : 500;
        const message = error instanceof Error ? error.message : 'Failed to fetch Home Assistant entities';

        if (entityCache && now - entityCache.timestamp < STALE_CACHE_MS) {
            return NextResponse.json({
                entities: entityCache.entities,
                stale: true,
                warning: message,
            });
        }

        return NextResponse.json({ error: message }, { status });
    }
}
