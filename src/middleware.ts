import { NextRequest, NextResponse } from 'next/server';
import { constantTimeEqual, sameOriginRequest, SESSION_COOKIE, validApiSecret, validSession } from '@/lib/session';

export async function middleware(req: NextRequest) {
    const pathname = req.nextUrl.pathname;
    if (pathname === '/login') return NextResponse.next();

    const apiSecret = process.env.API_SECRET;
    if (!validApiSecret(apiSecret)) {
        return NextResponse.json({ error: 'Dashboard authentication is not configured' }, { status: 503 });
    }

    // The sole public API validates the supplied secret and rate-limits attempts.
    if (pathname === '/api/auth/session') return NextResponse.next();

    const authorization = req.headers.get('authorization') || '';
    const bearer = authorization.startsWith('Bearer ') ? authorization.slice(7) : '';
    const bearerAuthenticated = Boolean(bearer && constantTimeEqual(bearer, apiSecret));
    const cookieAuthenticated = !bearerAuthenticated && await validSession(
        req.cookies.get(SESSION_COOKIE)?.value || '', apiSecret,
    );

    if (!bearerAuthenticated && !cookieAuthenticated) {
        if (!pathname.startsWith('/api/')) return NextResponse.redirect(new URL('/login', req.url));
        return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    // Lax cookies allow the authenticated Google OAuth callback. Mutations must
    // originate in this app; API clients can instead authenticate with Bearer.
    if (!bearerAuthenticated && !['GET', 'HEAD', 'OPTIONS'].includes(req.method) && !sameOriginRequest(req)) {
        return NextResponse.json({ error: 'Cross-origin request denied' }, { status: 403 });
    }
    return NextResponse.next();
}

export const config = {
    matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
