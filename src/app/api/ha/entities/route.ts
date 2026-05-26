import { NextResponse } from 'next/server';
import { getHAEntities, HAApiError } from '@/lib/server/ha-api';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() {
    try {
        return NextResponse.json({ entities: await getHAEntities() });
    } catch (error) {
        const status = error instanceof HAApiError ? error.status : 500;
        const message = error instanceof Error ? error.message : 'Failed to fetch Home Assistant entities';
        return NextResponse.json({ error: message }, { status });
    }
}
