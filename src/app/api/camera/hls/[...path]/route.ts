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
    // Next decodes route segments: reject embedded slashes, dot segments and
    // query/fragment characters before constructing an upstream URL.
    if (!Array.isArray(path) || path.length < 2 || path.length > 6 ||
        path.some((part) => !/^[a-zA-Z0-9_-][a-zA-Z0-9_.-]{0,199}$/.test(part)) ||
        !/\.(m3u8|m4s|mp4|ts)$/.test(path[path.length - 1])) {
        return NextResponse.json({ error: 'Invalid HLS path' }, { status: 400 });
    }
    const haPath = path.join('/');

    const ha = await getHAConfig();
    if (!ha) {
        return NextResponse.json({ error: 'HA not configured' }, { status: 503 });
    }

    let haRes: Response;
    try {
        haRes = await fetch(`${ha.url}/api/hls/${haPath}`, {
            cache: 'no-store',
            redirect: 'error',
            signal: AbortSignal.timeout(15000),
        });
    } catch {
        return NextResponse.json(
            { error: 'Could not load camera stream' },
            { status: 502 },
        );
    }

    if (!haRes.ok) {
        return NextResponse.json({ error: 'Camera stream unavailable' }, { status: haRes.status });
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
