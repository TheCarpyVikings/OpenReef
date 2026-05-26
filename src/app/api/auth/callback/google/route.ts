import { NextRequest, NextResponse } from 'next/server';
import { oauth2Client, TOKEN_PATH } from '@/lib/google-tasks';
import fs from 'fs';
import { safeErrorResponse } from '@/lib/validation';

export async function GET(req: NextRequest) {
    const searchParams = req.nextUrl.searchParams;
    const code = searchParams.get('code');
    const state = searchParams.get('state');

    if (!code) {
        return NextResponse.json({ error: 'No code provided' }, { status: 400 });
    }

    // Validate state parameter to prevent CSRF
    const storedState = req.cookies.get('oauth_state')?.value;
    if (!state || !storedState || state !== storedState) {
        return NextResponse.json({ error: 'Invalid state parameter — possible CSRF attack' }, { status: 403 });
    }

    try {
        const { tokens } = await oauth2Client.getToken(code);

        // Persist tokens locally for this dashboard
        fs.writeFileSync(TOKEN_PATH, JSON.stringify(tokens));

        // Clear the state cookie and redirect back to the dashboard tasks tab
        const response = NextResponse.redirect(new URL('/?tab=tasks', req.url));
        response.cookies.delete('oauth_state');
        return response;
    } catch (error) {
        return safeErrorResponse(error, 'Failed to exchange code for tokens');
    }
}
