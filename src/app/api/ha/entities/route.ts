import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() {
    return NextResponse.json(
        {
            error: 'Full Home Assistant entity export is disabled in OpenReef. Use targeted entity search or runtime-state instead.',
        },
        { status: 410 },
    );
}
