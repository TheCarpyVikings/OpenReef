import { NextRequest, NextResponse } from 'next/server';

/**
 * Sanitizes a string input: trims whitespace, strips null bytes, and enforces max length.
 */
export function sanitizeString(input: string, maxLength: number = 1000): string {
    return input
        .replace(/\0/g, '')   // Strip null bytes
        .trim()
        .slice(0, maxLength);
}

/**
 * Validates that the request Content-Type header matches the expected type.
 * Returns a 415 response if mismatched, or null if valid.
 */
export function validateContentType(
    req: NextRequest,
    expected: string = 'application/json'
): NextResponse | null {
    const contentType = req.headers.get('content-type');
    if (!contentType || !contentType.includes(expected)) {
        return NextResponse.json(
            { error: `Unsupported Content-Type. Expected ${expected}` },
            { status: 415 }
        );
    }
    return null;
}

/**
 * Creates a safe error response that never leaks internal error details to the client.
 * Logs the real error server-side for debugging.
 */
export function safeErrorResponse(
    error: unknown,
    fallbackMessage: string,
    status: number = 500
): NextResponse {
    // Log the real error server-side
    console.error(`[API Error] ${fallbackMessage}:`, error);

    return NextResponse.json(
        { error: fallbackMessage },
        { status }
    );
}

export function getErrorMessage(error: unknown): string {
    if (error instanceof Error) return error.message;
    if (typeof error === 'object' && error !== null && 'message' in error) {
        return String((error as { message: unknown }).message);
    }
    return String(error);
}

/**
 * Validates that a Google Sheets range string only contains safe characters.
 * Valid examples: "Sheet1!A1:C10", "'My Sheet'!A:Z", "Sheet1"
 */
export function isValidSheetRange(range: string): boolean {
    // Allow alphanumeric, spaces, underscores, exclamation marks, colons, apostrophes, and dollar signs
    return /^[A-Za-z0-9_ !':$]+$/.test(range) && range.length <= 200;
}

/**
 * Checks if an object's keys contain prototype pollution attempts.
 */
export function hasPrototypePollutionKeys(obj: unknown): boolean {
    if (typeof obj !== 'object' || obj === null) return false;

    const dangerousKeys = ['__proto__', 'constructor', 'prototype'];

    for (const key of Object.keys(obj as Record<string, unknown>)) {
        if (dangerousKeys.includes(key)) return true;

        // Recursively check nested objects
        const value = (obj as Record<string, unknown>)[key];
        if (typeof value === 'object' && value !== null) {
            if (hasPrototypePollutionKeys(value)) return true;
        }
    }

    return false;
}

/**
 * Validates request body size. Returns a 413 response if too large, or null if OK.
 * Note: This is a best-effort check using Content-Length header.
 */
export function validateBodySize(
    req: NextRequest,
    maxBytes: number = 102400 // 100KB default
): NextResponse | null {
    const contentLength = req.headers.get('content-length');
    if (contentLength && parseInt(contentLength, 10) > maxBytes) {
        return NextResponse.json(
            { error: 'Request body too large' },
            { status: 413 }
        );
    }
    return null;
}
