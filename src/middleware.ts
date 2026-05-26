import { NextRequest, NextResponse } from 'next/server';

function timingSafeCompare(a: string, b: string): boolean {
    if (a.length !== b.length) return false;
    const bufA = new TextEncoder().encode(a);
    const bufB = new TextEncoder().encode(b);
    let mismatch = 0;
    for (let i = 0; i < bufA.length; i++) {
        mismatch |= bufA[i] ^ bufB[i];
    }
    return mismatch === 0;
}

export function middleware(req: NextRequest) {
    // In addon mode, HA Ingress handles all authentication
    if (process.env.HA_ADDON_MODE === 'true') {
        return NextResponse.next();
    }

    const isApiRoute = req.nextUrl.pathname.startsWith('/api/');
    const apiSecret = process.env.API_SECRET;

    // ──────────────────────────────────────────────
    // PAGE ROUTES: auto-set the session cookie
    // ──────────────────────────────────────────────
    if (!isApiRoute) {
        // If API_SECRET is configured and the cookie isn't set yet, set it now.
        // This ensures the browser is authenticated before any client-side
        // API calls are made (replaces the old NEXT_PUBLIC_API_SECRET approach).
        if (apiSecret && !req.cookies.get('api_session')?.value) {
            const response = NextResponse.next();
            response.cookies.set('api_session', apiSecret, {
                httpOnly: true,
                secure: process.env.NODE_ENV === 'production',
                sameSite: 'strict',
                path: '/',
                maxAge: 60 * 60 * 24 * 30, // 30 days
            });
            return response;
        }
        return NextResponse.next();
    }

    // ──────────────────────────────────────────────
    // API ROUTES: enforce authentication
    // ──────────────────────────────────────────────

    // Skip auth for OAuth endpoints and public data endpoints
    if (
        req.nextUrl.pathname.startsWith('/api/auth/callback') ||
        req.nextUrl.pathname.startsWith('/api/auth/google') ||
        req.nextUrl.pathname.startsWith('/api/auth/session') ||
        req.nextUrl.pathname.startsWith('/api/spawning')
    ) {
        return NextResponse.next();
    }

    // If no API_SECRET is configured, allow all requests (development mode)
    if (!apiSecret) {
        return NextResponse.next();
    }

    // Check Authorization header (Bearer token)
    const authHeader = req.headers.get('Authorization');
    const token = authHeader?.replace('Bearer ', '');

    // Check session cookie as fallback
    const cookieToken = req.cookies.get('api_session')?.value;

    const providedToken = token || cookieToken || '';

    if (!providedToken || !timingSafeCompare(providedToken, apiSecret)) {
        return NextResponse.json(
            { error: 'Unauthorized' },
            { status: 401 }
        );
    }

    return NextResponse.next();
}

export const config = {
    matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
