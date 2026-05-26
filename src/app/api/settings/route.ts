import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { validateContentType, validateBodySize, safeErrorResponse, hasPrototypePollutionKeys } from '@/lib/validation';
import { readOpenReefSettings, writeOpenReefSettings } from '@/lib/server/openreef-config';
import type { AppSettings } from '@/context/SettingsContext';

// Settings can be deeply nested but we enforce overall structure safety
const SettingsSchema = z.object({
    settings: z.record(z.string(), z.any()),
});

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() {
    try {
        return NextResponse.json({ settings: await readOpenReefSettings() });
    } catch (error) {
        return safeErrorResponse(error, 'Failed to read settings');
    }
}

export async function POST(req: NextRequest) {
    // Validate Content-Type
    const ctError = validateContentType(req);
    if (ctError) return ctError;

    // Validate body size (100KB max for settings)
    const sizeError = validateBodySize(req, 102400);
    if (sizeError) return sizeError;

    try {
        const body = await req.json();
        const parsed = SettingsSchema.safeParse(body);
        if (!parsed.success) {
            return NextResponse.json({ error: 'Invalid input', details: parsed.error.flatten() }, { status: 400 });
        }

        const { settings } = parsed.data;

        // Check for prototype pollution attempts
        if (hasPrototypePollutionKeys(settings)) {
            return NextResponse.json(
                { error: 'Invalid input: forbidden key detected' },
                { status: 400 }
            );
        }

        const result = await writeOpenReefSettings(settings as unknown as AppSettings);
        return NextResponse.json({ success: true, source: result.source });
    } catch (error) {
        return safeErrorResponse(error, 'Failed to save settings');
    }
}
