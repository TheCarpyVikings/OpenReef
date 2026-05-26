import { NextResponse } from 'next/server';
import { getAuthUrl } from '@/lib/google-tasks';
import crypto from 'crypto';

export async function GET() {
    try {
        const state = crypto.randomBytes(32).toString('hex');
        const url = getAuthUrl(state);

        const response = NextResponse.redirect(url);
        response.cookies.set('oauth_state', state, {
            httpOnly: true,
            secure: process.env.NODE_ENV === 'production',
            sameSite: 'lax',
            maxAge: 600, // 10 minutes
            path: '/',
        });

        return response;
    } catch (error) {
        console.error('Error getting auth URL:', error);
        return NextResponse.json({ error: 'Failed to initiate authentication' }, { status: 500 });
    }
}

