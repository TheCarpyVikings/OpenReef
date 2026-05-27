import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { HAApiError, haWebSocketCommand } from '@/lib/server/ha-api';
import { validateContentType } from '@/lib/validation';
import type { OpenReefToggleEquipmentResponse } from '@/types/reef';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const ToggleSchema = z.object({
    equipmentId: z.string().regex(/^[A-Z0-9_]+$/),
});

export async function POST(req: NextRequest) {
    const ctError = validateContentType(req);
    if (ctError) return ctError;

    try {
        const parsed = ToggleSchema.safeParse(await req.json());
        if (!parsed.success) {
            return NextResponse.json({ error: 'Invalid input', details: parsed.error.flatten() }, { status: 400 });
        }

        const result = await haWebSocketCommand<OpenReefToggleEquipmentResponse>({
            type: 'openreef/toggle_equipment',
            equipment_id: parsed.data.equipmentId,
        });

        return NextResponse.json(result);
    } catch (error) {
        const status = error instanceof HAApiError ? error.status : 500;
        const message = error instanceof Error ? error.message : 'Failed to toggle OpenReef equipment';
        return NextResponse.json({ error: message }, { status });
    }
}
