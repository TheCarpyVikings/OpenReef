import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { readJsonBody, validateContentType } from '@/lib/validation';
import { rateLimit } from '@/lib/rate-limit';
import { constantTimeEqual, createSession, sameOriginRequest, SESSION_COOKIE, SESSION_MAX_AGE, validApiSecret } from '@/lib/session';

const SessionSchema = z.object({ secret: z.string().min(1).max(256) });

export async function POST(req: NextRequest) {
    if (!sameOriginRequest(req)) {
        return NextResponse.json({ error: 'Cross-origin request denied' }, { status: 403 });
    }
    const ctError = validateContentType(req);
    if (ctError) return ctError;
    const limitError = rateLimit('session-login', 10);
    if (limitError) return limitError;
    const apiSecret = process.env.API_SECRET;
    if (!validApiSecret(apiSecret)) {
        return NextResponse.json({ error: 'Dashboard authentication is not configured' }, { status: 503 });
    }
    const body = await readJsonBody(req, 2048);
    if (body.error) return body.error;
    const parsed = SessionSchema.safeParse(body.data);
    if (!parsed.success) return NextResponse.json({ error: 'Invalid input' }, { status: 400 });
    if (!constantTimeEqual(parsed.data.secret, apiSecret)) {
        return NextResponse.json({ error: 'Invalid secret' }, { status: 401 });
    }

    const response = NextResponse.json({ success: true });
    response.headers.set('Cache-Control', 'no-store');
    response.cookies.set(SESSION_COOKIE, await createSession(apiSecret), {
        httpOnly: true,
        secure: process.env.NODE_ENV === 'production',
        sameSite: 'lax',
        path: '/',
        maxAge: SESSION_MAX_AGE,
    });
    return response;
}

export async function DELETE(req: NextRequest) {
    if (!sameOriginRequest(req)) {
        return NextResponse.json({ error: 'Cross-origin request denied' }, { status: 403 });
    }
    const response = NextResponse.json({ success: true });
    response.cookies.delete(SESSION_COOKIE);
    return response;
}
