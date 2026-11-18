// Web Crypto keeps this usable in both Next middleware and Node route handlers.
export const SESSION_COOKIE = 'api_session';
export const SESSION_MAX_AGE = 60 * 60 * 12;

/** Configuration gate shared by cookie and Bearer authentication. Generate a
 * random secret; this length check cannot measure a human password's entropy. */
export function validApiSecret(value: unknown): value is string {
    return typeof value === 'string' && value.length >= 32 && value.length <= 256
        && value.trim() === value;
}

const encode = (value: string) => new TextEncoder().encode(value);
const hex = (bytes: ArrayBuffer | Uint8Array) => Array.from(new Uint8Array(bytes))
    .map((byte) => byte.toString(16).padStart(2, '0')).join('');

export function constantTimeEqual(left: string, right: string): boolean {
    const a = encode(left);
    const b = encode(right);
    if (a.length !== b.length) return false;
    let different = 0;
    for (let index = 0; index < a.length; index++) different |= a[index] ^ b[index];
    return different === 0;
}

async function signature(value: string, secret: string): Promise<string> {
    const key = await crypto.subtle.importKey('raw', encode(secret),
        { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
    return hex(await crypto.subtle.sign('HMAC', key, encode(`openreef-session:${value}`)));
}

export async function createSession(secret: string): Promise<string> {
    if (!validApiSecret(secret)) throw new Error('Dashboard authentication configuration is invalid');
    const expires = Math.floor(Date.now() / 1000) + SESSION_MAX_AGE;
    const nonce = hex(crypto.getRandomValues(new Uint8Array(24)));
    const value = `${expires}.${nonce}`;
    return `${value}.${await signature(value, secret)}`;
}

export async function validSession(value: string, secret: string): Promise<boolean> {
    const match = /^(\d{10})\.([a-f0-9]{48})\.([a-f0-9]{64})$/.exec(value);
    if (!match || !validApiSecret(secret)) return false;
    const now = Math.floor(Date.now() / 1000);
    const expires = Number(match[1]);
    if (expires <= now || expires > now + SESSION_MAX_AGE) return false;
    return constantTimeEqual(match[3], await signature(`${match[1]}.${match[2]}`, secret));
}

export function sameOriginRequest(request: Request): boolean {
    try {
        // Reverse proxies must set this explicitly if their internal URL differs.
        // Forwarded headers are not trusted as a source of authentication policy.
        const expected = new URL(process.env.OPENREEF_PUBLIC_ORIGIN || request.url).origin;
        return request.headers.get('origin') === expected;
    } catch {
        return false;
    }
}
