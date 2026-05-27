import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { HAApiError, haWebSocketCommand } from '@/lib/server/ha-api';
import { validateContentType } from '@/lib/validation';
import type { OpenReefEntitySearchResponse } from '@/types/reef';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const SearchTargetSchema = z.object({
    id: z.string().max(80),
    label: z.string().max(120),
    domains: z.array(z.string().regex(/^[a-z0-9_]+$/)).min(1).max(6),
    keywords: z.array(z.string().max(80)).max(24),
    prefer: z.array(z.string().max(80)).max(24).optional(),
    avoid: z.array(z.string().max(80)).max(24).optional(),
    deviceClasses: z.array(z.string().max(60)).max(12).optional(),
    units: z.array(z.string().max(20)).max(12).optional(),
    stateClasses: z.array(z.string().max(60)).max(12).optional(),
});

const SearchSchema = z.object({
    target: SearchTargetSchema,
    limit: z.number().int().min(1).max(10).optional(),
});

export async function POST(req: NextRequest) {
    const ctError = validateContentType(req);
    if (ctError) return ctError;

    try {
        const parsed = SearchSchema.safeParse(await req.json());
        if (!parsed.success) {
            return NextResponse.json({ error: 'Invalid input', details: parsed.error.flatten() }, { status: 400 });
        }

        const target = parsed.data.target;
        const result = await haWebSocketCommand<OpenReefEntitySearchResponse>({
            type: 'openreef/search_entities',
            limit: parsed.data.limit ?? 10,
            target: {
                id: target.id,
                label: target.label,
                domains: target.domains,
                keywords: target.keywords,
                prefer: target.prefer ?? [],
                avoid: target.avoid ?? [],
                device_classes: target.deviceClasses ?? [],
                units: target.units ?? [],
                state_classes: target.stateClasses ?? [],
            },
        });

        return NextResponse.json(result);
    } catch (error) {
        const status = error instanceof HAApiError ? error.status : 500;
        const message = error instanceof Error ? error.message : 'Failed to search Home Assistant entities';
        return NextResponse.json({ error: message }, { status });
    }
}
