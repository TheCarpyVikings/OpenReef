import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { validateContentType } from '@/lib/validation';

const SessionSchema = z.object({
    secret: z.string().min(1).max(256),
});

/**
 * POST /api/auth/session
 *
 * Sets the API secret as an httpOnly session cookie.
 * This replaces the NEXT_PUBLIC_API_SECRET approach — the secret
 * is sent once from the client and stored as a secure cookie,
 * keeping it out of the JS bundle.
 */
export async function POST(req: NextRequest) {
    const ctError = validateContentType(req);
    if (ctError) return ctError;

    try {
        const body = await req.json();
        const parsed = SessionSchema.safeParse(body);
        if (!parsed.success) {
            return NextResponse.json(
                { error: 'Invalid input' },
                { status: 400 }
            );
        }

        const { secret } = parsed.data;

        // Verify the secret matches the configured API_SECRET
        const apiSecret = process.env.API_SECRET;
        if (!apiSecret) {
            // No API_SECRET configured — development mode, no cookie needed
            return NextResponse.json({ success: true, mode: 'development' });
        }

        // Timing-safe comparison
        if (secret.length !== apiSecret.length) {
            return NextResponse.json({ error: 'Invalid secret' }, { status: 401 });
        }
        const bufA = new TextEncoder().encode(secret);
        const bufB = new TextEncoder().encode(apiSecret);
        let mismatch = 0;
        for (let i = 0; i < bufA.length; i++) {
            mismatch |= bufA[i] ^ bufB[i];
        }
        if (mismatch !== 0) {
            return NextResponse.json({ error: 'Invalid secret' }, { status: 401 });
        }

        const response = NextResponse.json({ success: true });
        response.cookies.set('api_session', secret, {
            httpOnly: true,
            secure: process.env.NODE_ENV === 'production',
            sameSite: 'strict',
            path: '/',
            maxAge: 60 * 60 * 24 * 30, // 30 days
        });

        return response;
    } catch {
        return NextResponse.json({ error: 'Session initialization failed' }, { status: 500 });
    }
}
