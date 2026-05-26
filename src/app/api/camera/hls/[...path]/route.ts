import { NextRequest, NextResponse } from 'next/server';
import { getHAConfig } from '../../ha-config';

export const dynamic = 'force-dynamic';

/**
 * Catch-all proxy for HLS requests.
 * Forwards /api/camera/hls/TOKEN/playlist.m3u8  →  HA/api/hls/TOKEN/playlist.m3u8
 *          /api/camera/hls/TOKEN/segment/1.m4s  →  HA/api/hls/TOKEN/segment/1.m4s
 *          etc.
 *
 * The HLS token in the URL path authenticates with HA — no Bearer header needed.
 * This proxy exists solely to bypass browser CORS restrictions.
 */
export async function GET(
    _request: NextRequest,
    { params }: { params: Promise<{ path: string[] }> },
) {
    const { path } = await params;
    const haPath = path.join('/');

    const ha = await getHAConfig();
    if (!ha) {
        return NextResponse.json({ error: 'HA not configured' }, { status: 503 });
    }

    let haRes: Response;
    try {
        haRes = await fetch(`${ha.url}/api/hls/${haPath}`, {
            cache: 'no-store',
        });
    } catch (err) {
        return NextResponse.json(
            { error: `Could not reach HA: ${err}` },
            { status: 502 },
        );
    }

    if (!haRes.ok) {
        return new Response(haRes.body, { status: haRes.status });
    }

    const contentType = haRes.headers.get('Content-Type') || 'application/octet-stream';

    return new Response(haRes.body, {
        status: 200,
        headers: {
            'Content-Type': contentType,
            'Cache-Control': 'no-store',
        },
    });
}
