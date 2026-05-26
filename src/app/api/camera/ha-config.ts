import { getHABaseUrl, getHAToken } from '@/lib/server/ha-api';

/**
 * Resolve the server-side HA URL and token.
 * These credentials must never be sent to the browser.
 */
export async function getHAConfig(): Promise<{ url: string; token: string } | null> {
    const url = getHABaseUrl();
    const token = getHAToken();

    if (!url || !token) return null;
    return { url: url.replace(/\/$/, ''), token };
}
