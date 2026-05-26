/**
 * Wrapper around fetch for /api/* routes.
 * Authentication is now handled via the `api_session` httpOnly cookie,
 * which is automatically included by the browser. No need to manually
 * attach auth headers — this eliminates the NEXT_PUBLIC_API_SECRET leak.
 */
const INGRESS_SEGMENT_PATTERN = /^\/([^/?#]+_openreef)(?:[/?#]|$)/i;
const HASSIO_INGRESS_PATTERN = /^\/api\/hassio_ingress\/([^/?#]+)(?:[/?#]|$)/i;

export function withIngressPath(path: string): string {
    if (typeof window === 'undefined' || !path.startsWith('/')) {
        return path;
    }

    const pathname = window.location.pathname;
    const hassioMatch = pathname.match(HASSIO_INGRESS_PATTERN);
    const openreefMatch = pathname.match(INGRESS_SEGMENT_PATTERN);

    const ingressBase = hassioMatch
        ? `/api/hassio_ingress/${hassioMatch[1]}`
        : openreefMatch
            ? `/${openreefMatch[1]}`
            : '';

    if (!ingressBase) {
        return path;
    }

    if (path === ingressBase || path.startsWith(`${ingressBase}/`)) {
        return path;
    }

    return `${ingressBase}${path}`;
}

export async function apiFetch(url: string, options: RequestInit = {}): Promise<Response> {
    return fetch(withIngressPath(url), { ...options, credentials: 'same-origin' });
}

/**
 * Initializes the API session by setting the auth cookie.
 * Call this once when the app boots (e.g. in a top-level useEffect).
 * The secret is passed as a one-time POST body, NOT stored in the JS bundle.
 */
export async function initApiSession(secret: string): Promise<boolean> {
    try {
        const res = await fetch(withIngressPath('/api/auth/session'), {
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
