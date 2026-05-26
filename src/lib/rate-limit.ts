import { NextResponse } from 'next/server';

interface RateLimitEntry {
    timestamps: number[];
}

const rateLimitStore = new Map<string, RateLimitEntry>();

// Clean up expired entries every 5 minutes
const CLEANUP_INTERVAL = 5 * 60 * 1000;
let lastCleanup = Date.now();

function cleanup(windowMs: number) {
    const now = Date.now();
    if (now - lastCleanup < CLEANUP_INTERVAL) return;
    lastCleanup = now;

    for (const [key, entry] of rateLimitStore.entries()) {
        entry.timestamps = entry.timestamps.filter(t => now - t < windowMs);
        if (entry.timestamps.length === 0) {
            rateLimitStore.delete(key);
        }
    }
}

/**
 * Simple in-memory sliding window rate limiter.
 * Returns a NextResponse with 429 status if the limit is exceeded, or null if OK.
 *
 * @param key - Unique identifier for the rate limit bucket (e.g. endpoint path)
 * @param maxRequests - Maximum requests allowed within the window
 * @param windowMs - Time window in milliseconds (default: 60 seconds)
 */
export function rateLimit(
    key: string,
    maxRequests: number,
    windowMs: number = 60_000
): NextResponse | null {
    const now = Date.now();

    cleanup(windowMs);

    let entry = rateLimitStore.get(key);
    if (!entry) {
        entry = { timestamps: [] };
        rateLimitStore.set(key, entry);
    }

    // Remove timestamps outside the window
    entry.timestamps = entry.timestamps.filter(t => now - t < windowMs);

    if (entry.timestamps.length >= maxRequests) {
        const retryAfterMs = entry.timestamps[0] + windowMs - now;
        const retryAfterSec = Math.ceil(retryAfterMs / 1000);

        const response = NextResponse.json(
            { error: 'Too many requests. Please try again later.' },
            { status: 429 }
        );
        response.headers.set('Retry-After', String(retryAfterSec));
        return response;
    }

    entry.timestamps.push(now);
    return null;
}
