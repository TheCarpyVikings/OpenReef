/**
 * Wrapper around fetch for /api/* routes.
 * Authentication is now handled via the `api_session` httpOnly cookie,
 * which is automatically included by the browser. No need to manually
 * attach auth headers — this eliminates the NEXT_PUBLIC_API_SECRET leak.
 */
export async function apiFetch(url: string, options: RequestInit = {}): Promise<Response> {
    return fetch(url, { ...options, credentials: 'same-origin' });
}

/**
 * Initializes the API session by setting the auth cookie.
 * Call this once when the app boots (e.g. in a top-level useEffect).
 * The secret is passed as a one-time POST body, NOT stored in the JS bundle.
 */
export async function initApiSession(secret: string): Promise<boolean> {
    try {
        const res = await fetch('/api/auth/session', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ secret }),
            credentials: 'same-origin',
        });
        return res.ok;
    } catch {
        return false;
    }
}

