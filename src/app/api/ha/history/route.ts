import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { getHAHistory, HAApiError } from '@/lib/server/ha-api';
import { readJsonBody, validateContentType } from '@/lib/validation';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const HistorySchema = z.object({
    entityId: z.union([
        z.string().max(200).regex(/^[a-z0-9_]+\.[a-z0-9_]+$/),
        z.array(z.string().max(200).regex(/^[a-z0-9_]+\.[a-z0-9_]+$/)).min(1).max(50),
    ]),
    startTime: z.string().datetime(),
    endTime: z.string().datetime(),
});

export async function POST(req: NextRequest) {
    const ctError = validateContentType(req);
    if (ctError) return ctError;

    try {
        const body = await readJsonBody(req);
        if (body.error) return body.error;
        const parsed = HistorySchema.safeParse(body.data);
        if (!parsed.success) {
            return NextResponse.json({ error: 'Invalid input', details: parsed.error.flatten() }, { status: 400 });
        }

        const { entityId, startTime, endTime } = parsed.data;
        const duration = Date.parse(endTime) - Date.parse(startTime);
        if (duration <= 0 || duration > 90 * 86400000) {
            return NextResponse.json({ error: 'History range must be between 0 and 90 days' }, { status: 400 });
        }
        return NextResponse.json({ history: await getHAHistory(entityId, startTime, endTime) });
    } catch (error) {
        const status = error instanceof HAApiError ? error.status : 500;
        const message = error instanceof Error ? error.message : 'Failed to fetch Home Assistant history';
        return NextResponse.json({ error: message }, { status });
    }
}
