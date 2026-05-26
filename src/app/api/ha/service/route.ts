import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { callHAService, HAApiError } from '@/lib/server/ha-api';
import { isEntityControlArmed } from '@/lib/server/openreef-config';
import { validateContentType } from '@/lib/validation';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const ServiceSchema = z.object({
    domain: z.string().regex(/^[a-z0-9_]+$/),
    service: z.string().regex(/^[a-z0-9_]+$/),
    serviceData: z.record(z.string(), z.unknown()).optional(),
});

const CONTROL_DOMAINS = new Set([
    'button',
    'climate',
    'input_boolean',
    'input_datetime',
    'input_number',
    'input_select',
    'light',
    'number',
    'select',
    'switch',
]);

const extractEntityIds = (serviceData: Record<string, unknown>) => {
    const rawEntityId = serviceData.entity_id;
    if (typeof rawEntityId === 'string') return [rawEntityId];
    if (Array.isArray(rawEntityId)) {
        return rawEntityId.filter((value): value is string => typeof value === 'string');
    }
    return [];
};

export async function POST(req: NextRequest) {
    const ctError = validateContentType(req);
    if (ctError) return ctError;

    try {
        const parsed = ServiceSchema.safeParse(await req.json());
        if (!parsed.success) {
            return NextResponse.json({ error: 'Invalid input', details: parsed.error.flatten() }, { status: 400 });
        }

        const { domain, service, serviceData = {} } = parsed.data;
        const entityIds = extractEntityIds(serviceData);

        if (CONTROL_DOMAINS.has(domain)) {
            if (entityIds.length === 0) {
                return NextResponse.json(
                    { error: 'OpenReef blocks control service calls without an explicit entity_id target' },
                    { status: 403 },
                );
            }

            const lockedEntity = await firstLockedEntity(entityIds);
            if (lockedEntity) {
                return NextResponse.json(
                    { error: `OpenReef control is not armed for ${lockedEntity}` },
                    { status: 403 },
                );
            }
        }

        return NextResponse.json({ result: await callHAService(domain, service, serviceData) });
    } catch (error) {
        const status = error instanceof HAApiError ? error.status : 500;
        const message = error instanceof Error ? error.message : 'Failed to call Home Assistant service';
        return NextResponse.json({ error: message }, { status });
    }
}

async function firstLockedEntity(entityIds: string[]) {
    for (const entityId of entityIds) {
        if (!(await isEntityControlArmed(entityId))) return entityId;
    }
    return null;
}
