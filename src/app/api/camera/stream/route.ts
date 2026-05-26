import { NextRequest, NextResponse } from 'next/server';
import http from 'http';
import https from 'https';
import { getHAConfig } from '../ha-config';

// Never cache this route.
export const dynamic = 'force-dynamic';

// Server-side proxy that streams the MJPEG feed from HA to the browser using
// Node.js native http/https — bypasses fetch() buffering and Next.js response
// compression so frames are forwarded to the browser as they arrive from HA.
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

    const target = new URL(`${ha.url}/api/camera_proxy_stream/${entityId}`);
    const transport = target.protocol === 'https:' ? https : http;
    const port = target.port
        ? parseInt(target.port)
        : target.protocol === 'https:' ? 443 : 80;

    return new Promise<Response>((resolve) => {
        const req = transport.request(
            {
                hostname: target.hostname,
                port,
                path: target.pathname + target.search,
                method: 'GET',
                headers: { Authorization: `Bearer ${ha.token}` },
            },
            (res) => {
                if (!res.statusCode || res.statusCode >= 400) {
                    resolve(
                        NextResponse.json(
                            { error: `HA returned ${res.statusCode}` },
                            { status: res.statusCode ?? 502 },
                        ),
                    );
                    res.resume(); // drain and discard
                    return;
                }

                const contentType =
                    res.headers['content-type'] || 'multipart/x-mixed-replace';

                // Pipe HA bytes directly to the browser as a ReadableStream.
                // Node.js emits chunks as they arrive from the TCP socket —
                // no buffering, no compression.
                const stream = new ReadableStream<Uint8Array>({
                    start(controller) {
                        res.on('data', (chunk: Buffer) =>
                            controller.enqueue(new Uint8Array(chunk)),
                        );
                        res.on('end', () => controller.close());
                        res.on('error', (err) => controller.error(err));
                    },
                    cancel() {
                        req.destroy();
                    },
                });

                resolve(
                    new Response(stream, {
                        status: 200,
                        headers: {
                            'Content-Type': contentType,
                            'Cache-Control': 'no-store',
                            'X-Accel-Buffering': 'no', // disable nginx buffering if present
                        },
                    }),
                );
            },
        );

        req.on('error', (err) => {
            resolve(
                NextResponse.json(
                    { error: `Could not reach HA: ${err}` },
                    { status: 502 },
                ),
            );
        });

        // Cancel the HA request when the browser disconnects.
        request.signal.addEventListener('abort', () => req.destroy());

        req.end();
    });
}
