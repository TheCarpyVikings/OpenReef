import { NextRequest, NextResponse } from 'next/server';
import { getHAConfig } from '../ha-config';

// Server-side proxy that fetches a single JPEG frame from HA's camera proxy.
// Used by the snapshot/download feature in CameraScreen.
export async function GET(request: NextRequest) {
    const entityId = request.nextUrl.searchParams.get('entity');
    if (!entityId || !/^[a-z0-9_.]+$/.test(entityId)) {
        return NextResponse.json(
            { error: 'Missing or invalid entity parameter' },
            { status: 400 },
        );
    }

    const ha = await getHAConfig();
    if (!ha) {
        return NextResponse.json({ error: 'HA not configured' }, { status: 503 });
    }

    let haRes: Response;
    try {
        haRes = await fetch(`${ha.url}/api/camera_proxy/${entityId}`, {
            headers: { Authorization: `Bearer ${ha.token}` },
        });
    } catch (err) {
        return NextResponse.json(
            { error: `Could not reach HA: ${err}` },
            { status: 502 },
        );
    }

    if (!haRes.ok) {
        const body = await haRes.text().catch(() => '');
        return NextResponse.json(
            { error: `HA returned ${haRes.status}: ${body}` },
            { status: haRes.status },
        );
    }

    if (!haRes.body) {
        return NextResponse.json(
            { error: 'HA returned empty response' },
            { status: 502 },
        );
    }

    const contentType = haRes.headers.get('Content-Type') || 'image/jpeg';

    return new Response(haRes.body, {
        status: 200,
        headers: {
            'Content-Type': contentType,
            'Cache-Control': 'no-store',
        },
    });
}
