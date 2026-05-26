import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { getHAHistory, HAApiError } from '@/lib/server/ha-api';
import { validateContentType } from '@/lib/validation';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const HistorySchema = z.object({
    entityId: z.union([z.string().min(1), z.array(z.string().min(1)).min(1)]),
    startTime: z.string().datetime(),
    endTime: z.string().datetime(),
});

export async function POST(req: NextRequest) {
    const ctError = validateContentType(req);
    if (ctError) return ctError;

    try {
        const parsed = HistorySchema.safeParse(await req.json());
        if (!parsed.success) {
            return NextResponse.json({ error: 'Invalid input', details: parsed.error.flatten() }, { status: 400 });
        }

        const { entityId, startTime, endTime } = parsed.data;
        return NextResponse.json({ history: await getHAHistory(entityId, startTime, endTime) });
    } catch (error) {
        const status = error instanceof HAApiError ? error.status : 500;
        const message = error instanceof Error ? error.message : 'Failed to fetch Home Assistant history';
        return NextResponse.json({ error: message }, { status });
    }
}
