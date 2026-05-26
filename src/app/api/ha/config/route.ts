import { NextResponse } from 'next/server';
import { getHABaseUrl } from '@/lib/server/ha-api';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() {
    const response = NextResponse.json({
        addonMode: process.env.HA_ADDON_MODE === 'true',
        token: '',
        url: getHABaseUrl(),
    });

    response.headers.set('Cache-Control', 'no-store, no-cache, must-revalidate');
    response.headers.set('Pragma', 'no-cache');
    response.headers.set('Expires', '0');

    return response;
}
