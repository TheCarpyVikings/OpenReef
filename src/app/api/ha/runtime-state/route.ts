import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { HAApiError, haWebSocketCommand } from '@/lib/server/ha-api';
import { validateContentType } from '@/lib/validation';
import type { OpenReefRuntimeStateResponse } from '@/types/reef';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const RuntimeStateSchema = z.object({
    entityIds: z.array(z.string().regex(/^[a-z0-9_]+\.[a-z0-9_]+$/)).max(100).optional(),
});

export async function POST(req: NextRequest) {
    const ctError = validateContentType(req);
    if (ctError) return ctError;

    try {
        const parsed = RuntimeStateSchema.safeParse(await req.json());
        if (!parsed.success) {
            return NextResponse.json({ error: 'Invalid input', details: parsed.error.flatten() }, { status: 400 });
        }

        const payload: Record<string, unknown> = {
            type: 'openreef/get_runtime_state',
        };

        if (parsed.data.entityIds) {
            payload.entity_ids = parsed.data.entityIds;
        }

        const result = await haWebSocketCommand<OpenReefRuntimeStateResponse>(payload);
        return NextResponse.json(result);
    } catch (error) {
        const status = error instanceof HAApiError ? error.status : 500;
        const message = error instanceof Error ? error.message : 'Failed to fetch OpenReef runtime state';
        return NextResponse.json({ error: message }, { status });
    }
}
