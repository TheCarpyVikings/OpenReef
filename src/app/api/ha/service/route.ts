import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { callHAService, HAApiError } from '@/lib/server/ha-api';
import { isEntityControlArmed } from '@/lib/server/openreef-config';
import { readJsonBody, validateContentType } from '@/lib/validation';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const ServiceSchema = z.object({
    domain: z.string().regex(/^[a-z0-9_]+$/),
    service: z.string().regex(/^[a-z0-9_]+$/),
    serviceData: z.record(z.string(), z.unknown()).optional(),
});

const EntityId = z.string().max(200).regex(/^[a-z0-9_]+\.[a-z0-9_]+$/);
const targeted = (fields: z.ZodRawShape = {}) => z.object({
    entity_id: z.union([EntityId, z.array(EntityId).min(1).max(20)]), ...fields,
}).strict();
// Deny unknown domains/services and implicit HA targets (areas, devices, "all").
// Every supported command must pass the same explicit per-entity arming gate.
const SAFE_SERVICES: Record<string, z.ZodType> = {
    'button.press': targeted(),
    'switch.turn_on': targeted(), 'switch.turn_off': targeted(), 'switch.toggle': targeted(),
    'input_boolean.turn_on': targeted(), 'input_boolean.turn_off': targeted(), 'input_boolean.toggle': targeted(),
    'number.set_value': targeted({ value: z.number().finite() }),
    'input_number.set_value': targeted({ value: z.number().finite() }),
    'select.select_option': targeted({ option: z.string().min(1).max(255) }),
    'input_select.select_option': targeted({ option: z.string().min(1).max(255) }),
    'input_datetime.set_datetime': targeted({ datetime: z.string().max(30).regex(/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?$/) }),
    'light.turn_on': targeted({ brightness: z.number().int().min(0).max(255).optional() }),
    'light.turn_off': targeted(), 'light.toggle': targeted(),
};

export async function POST(req: NextRequest) {
    const ctError = validateContentType(req);
    if (ctError) return ctError;

    try {
        const body = await readJsonBody(req);
        if (body.error) return body.error;
        const parsed = ServiceSchema.safeParse(body.data);
        if (!parsed.success) {
            return NextResponse.json({ error: 'Invalid input', details: parsed.error.flatten() }, { status: 400 });
        }

        const { domain, service, serviceData = {} } = parsed.data;
        const allowedSchema = SAFE_SERVICES[`${domain}.${service}`];
        if (!allowedSchema) {
            return NextResponse.json({ error: 'This Home Assistant service is not allowed' }, { status: 403 });
        }
        const target = allowedSchema.safeParse(serviceData);
        if (!target.success) {
            return NextResponse.json({ error: 'Invalid explicit service target or data' }, { status: 400 });
        }
        const validatedData = target.data as Record<string, unknown> & { entity_id: string | string[] };
        const entityIds = Array.isArray(validatedData.entity_id) ? validatedData.entity_id : [validatedData.entity_id];
        if (entityIds.some((id) => !id.startsWith(`${domain}.`))) {
            return NextResponse.json({ error: 'Entity domain does not match service' }, { status: 403 });
        }
        const lockedEntity = await firstLockedEntity(entityIds);
        if (lockedEntity) {
            return NextResponse.json({ error: `OpenReef control is not armed for ${lockedEntity}` }, { status: 403 });
        }

        return NextResponse.json({ result: await callHAService(domain, service, validatedData) });
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
