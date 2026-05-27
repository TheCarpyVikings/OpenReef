import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { HAApiError, haRestJson, type HAState } from '@/lib/server/ha-api';
import { validateContentType } from '@/lib/validation';
import type { OpenReefRuntimeStateResponse } from '@/types/reef';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const RuntimeStateSchema = z.object({
    entityIds: z.array(z.string().regex(/^[a-z0-9_]+\.[a-z0-9_]+$/)).max(50).optional(),
});

const toRuntimeState = (entityId: string, state?: HAState) => ({
    entity_id: entityId,
    state: state?.state ?? null,
    unit: typeof state?.attributes?.unit_of_measurement === 'string'
        ? state.attributes.unit_of_measurement
        : null,
    last_changed: state?.last_changed ?? null,
    available: Boolean(state && !['unknown', 'unavailable'].includes(state.state)),
});

const readSingleEntityState = async (entityId: string) => {
    try {
        const state = await haRestJson<HAState>(`/api/states/${encodeURIComponent(entityId)}`);
        return toRuntimeState(entityId, state);
    } catch (error) {
        if (error instanceof HAApiError && error.status === 404) {
            return toRuntimeState(entityId);
        }
        throw error;
    }
};

export async function POST(req: NextRequest) {
    const ctError = validateContentType(req);
    if (ctError) return ctError;

    try {
        const parsed = RuntimeStateSchema.safeParse(await req.json());
        if (!parsed.success) {
            return NextResponse.json({ error: 'Invalid input', details: parsed.error.flatten() }, { status: 400 });
        }

        const entityIds = parsed.data.entityIds || [];
        const states = [];

        // Keep this intentionally sequential and targeted. It must never open
        // HA Core websocket state subscriptions or request the full state list.
        for (const entityId of entityIds) {
            states.push(await readSingleEntityState(entityId));
        }

        const result: OpenReefRuntimeStateResponse = {
            states,
            entity_count: states.length,
        };

        return NextResponse.json(result);
    } catch (error) {
        const status = error instanceof HAApiError ? error.status : 500;
        const message = error instanceof Error ? error.message : 'Failed to fetch OpenReef runtime state';
        return NextResponse.json({ error: message }, { status });
    }
}
