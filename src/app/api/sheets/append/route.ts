import { NextRequest, NextResponse } from 'next/server';
import { oauth2Client, TOKEN_PATH, type GoogleCredentials } from '@/lib/google-tasks';
import { appendToSheet } from '@/lib/google-sheets';
import fs from 'fs';
import { z } from 'zod';
import { validateContentType, safeErrorResponse, isValidSheetRange, getErrorMessage } from '@/lib/validation';
import { rateLimit } from '@/lib/rate-limit';

// Cell values can only be strings, numbers, booleans, or null — no objects/arrays
const CellValueSchema = z.union([
    z.string().max(1000),
    z.number(),
    z.boolean(),
    z.null(),
]);

const AppendSchema = z.object({
    spreadsheetId: z.string().min(1).regex(/^[a-zA-Z0-9_-]+$/, 'Invalid spreadsheet ID format'),
    range: z.string().min(1).max(200).refine(isValidSheetRange, 'Invalid sheet range format'),
    values: z.array(z.array(CellValueSchema).max(50)).min(1).max(100), // Max 100 rows, 50 columns
});

export async function POST(req: NextRequest) {
    // Rate limit: 30 requests per minute for sheet writes
    const rateLimitError = rateLimit('sheets-append', 30);
    if (rateLimitError) return rateLimitError;

    // Validate Content-Type
    const ctError = validateContentType(req);
    if (ctError) return ctError;

    try {
        const body = await req.json();
        const parsed = AppendSchema.safeParse(body);
        if (!parsed.success) {
            return NextResponse.json({ error: 'Invalid input', details: parsed.error.flatten() }, { status: 400 });
        }

        const { spreadsheetId, range, values } = parsed.data;

        if (!fs.existsSync(TOKEN_PATH)) {
            return NextResponse.json({ error: 'Not authenticated with Google' }, { status: 401 });
        }

        const tokens = JSON.parse(fs.readFileSync(TOKEN_PATH, 'utf8')) as GoogleCredentials;
        oauth2Client.setCredentials(tokens);

        const result = await appendToSheet(spreadsheetId, range, values);

        return NextResponse.json({ success: true, result });
    } catch (error: unknown) {
        if (getErrorMessage(error).includes('invalid_grant')) {
            if (fs.existsSync(TOKEN_PATH)) fs.unlinkSync(TOKEN_PATH);
            return NextResponse.json({ authenticated: false, error: 'Google authentication expired' }, { status: 401 });
        }
        return safeErrorResponse(error, 'Failed to sync with Google Sheets');
    }
}
