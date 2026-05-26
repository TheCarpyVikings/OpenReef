import { NextRequest, NextResponse } from 'next/server';
import WebSocket from 'ws';
import { getHAConfig } from '../ha-config';

export const dynamic = 'force-dynamic';

/**
 * Start an HLS camera stream via HA's WebSocket `camera/stream` command.
 * Returns the HLS token so the client can construct the playlist URL:
 *   /api/camera/hls/{token}/master_playlist.m3u8
 *
 * This is the same mechanism HA Lovelace uses — full framerate, through HA.
 */
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

    try {
        const hlsPath = await requestCameraStream(ha.url, ha.token, entityId);
        // hlsPath looks like: /api/hls/TOKEN/master_playlist.m3u8
        // Extract just the token.
        const match = hlsPath.match(/\/api\/hls\/([^/]+)\//);
        if (!match) {
            return NextResponse.json(
                { error: `Unexpected HLS path: ${hlsPath}` },
                { status: 502 },
            );
        }
        return NextResponse.json({ token: match[1] });
    } catch (err) {
        return NextResponse.json(
            { error: `camera/stream failed: ${err}` },
            { status: 502 },
        );
    }
}

/** One-shot WebSocket call to HA to start a camera HLS stream. */
function requestCameraStream(
    haUrl: string,
    haToken: string,
    entityId: string,
): Promise<string> {
    return new Promise((resolve, reject) => {
        const wsUrl = haUrl.replace(/^http/, 'ws') + '/api/websocket';
        const ws = new WebSocket(wsUrl);
        const timeout = setTimeout(() => {
            ws.close();
            reject(new Error('Timeout waiting for camera/stream'));
        }, 10_000);

        ws.on('message', (raw) => {
            const msg = JSON.parse(raw.toString());

            if (msg.type === 'auth_required') {
                ws.send(JSON.stringify({ type: 'auth', access_token: haToken }));
            } else if (msg.type === 'auth_ok') {
                ws.send(
                    JSON.stringify({
                        id: 1,
                        type: 'camera/stream',
                        entity_id: entityId,
                    }),
                );
            } else if (msg.type === 'auth_invalid') {
                clearTimeout(timeout);
                ws.close();
                reject(new Error('HA auth invalid'));
            } else if (msg.id === 1) {
                clearTimeout(timeout);
                ws.close();
                if (msg.success) {
                    resolve(msg.result.url);
                } else {
                    reject(new Error(msg.error?.message || 'camera/stream failed'));
                }
            }
        });

        ws.on('error', (err) => {
            clearTimeout(timeout);
            reject(err);
        });
    });
}
