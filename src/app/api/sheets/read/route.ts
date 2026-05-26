import { NextRequest, NextResponse } from 'next/server';
import { oauth2Client, TOKEN_PATH, type GoogleCredentials } from '@/lib/google-tasks';
import { readSheetData } from '@/lib/google-sheets';
import fs from 'fs';
import { z } from 'zod';
import { safeErrorResponse, isValidSheetRange, getErrorMessage } from '@/lib/validation';

const ReadQuerySchema = z.object({
    spreadsheetId: z.string().min(1).regex(/^[a-zA-Z0-9_-]+$/, 'Invalid spreadsheet ID format'),
    range: z.string().max(200).refine(
        (val) => !val || isValidSheetRange(val),
        'Invalid sheet range format'
    ).optional(),
});

export async function GET(req: NextRequest) {
    try {
        const searchParams = req.nextUrl.searchParams;
        const parsed = ReadQuerySchema.safeParse({
            spreadsheetId: searchParams.get('spreadsheetId'),
            range: searchParams.get('range') || undefined,
        });

        if (!parsed.success) {
            return NextResponse.json({ error: 'Invalid input', details: parsed.error.flatten() }, { status: 400 });
        }

        const { spreadsheetId, range } = parsed.data;

        if (!fs.existsSync(TOKEN_PATH)) {
            return NextResponse.json({ error: 'Not authenticated with Google' }, { status: 401 });
        }

        const tokens = JSON.parse(fs.readFileSync(TOKEN_PATH, 'utf8')) as GoogleCredentials;
        oauth2Client.setCredentials(tokens);

        const rows = await readSheetData(spreadsheetId, range || 'Sheet1!A:C');

        return NextResponse.json({ values: rows || [] });
    } catch (error: unknown) {
        if (getErrorMessage(error).includes('invalid_grant')) {
            if (fs.existsSync(TOKEN_PATH)) fs.unlinkSync(TOKEN_PATH);
            return NextResponse.json({ authenticated: false, error: 'Google authentication expired' }, { status: 401 });
        }
        return safeErrorResponse(error, 'Failed to fetch from Google Sheets');
    }
}
