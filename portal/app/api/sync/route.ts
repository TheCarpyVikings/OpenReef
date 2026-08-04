import { NextResponse } from "next/server";
import { authenticate, clip, readJson } from "@/lib/api";
import { serviceClient } from "@/lib/supabase";

/** Non-negative integer or null. Anything else the client sends is discarded
 *  rather than trusted — these feed a dashboard, not a decision. */
function count(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? Math.floor(value)
    : null;
}

const TRUST = ["ok", "warning", "critical", "unknown"];

/**
 * Fold the install's activation report into the tester row.
 *
 * Absent or malformed fields become null, which the roster reads as "not
 * reported yet" — deliberately distinct from zero, because "0 sensors mapped"
 * and "hasn't told us yet" mean completely different things when you are
 * deciding whether to check on someone.
 */
function activationPatch(raw: unknown): Record<string, unknown> {
  const patch: Record<string, unknown> = { last_seen_at: new Date().toISOString() };
  if (!raw || typeof raw !== "object") return patch;
  const a = raw as Record<string, unknown>;

  if (typeof a.setupComplete === "boolean") patch.setup_complete = a.setupComplete;
  if (typeof a.trustStatus === "string" && TRUST.includes(a.trustStatus)) {
    patch.trust_status = a.trustStatus;
  }
  const checkedAt = clip(a.trustCheckedAt, 40);
  // Guard the timestamp: a malformed string would fail the whole update and
  // silently cost us the last_seen_at refresh too.
  if (checkedAt && !Number.isNaN(Date.parse(checkedAt))) patch.trust_checked_at = checkedAt;

  for (const [from, to] of [
    ["sensorsEnabled", "sensors_enabled"],
    ["sensorsMapped", "sensors_mapped"],
    ["equipmentMapped", "equipment_mapped"],
    ["equipmentArmed", "equipment_armed"],
  ] as const) {
    const value = count(a[from]);
    if (value !== null) patch[to] = value;
  }
  return patch;
}

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/*
 * POST /api/sync — what an install polls every 30 minutes.
 *
 * Returns the tester's own items with current status and any reply, plus every
 * published announcement. Deliberately NOT incremental despite the client
 * sending `since`: the whole set is a few dozen small rows, and returning all
 * of it means a tester who was offline for a fortnight, or whose stored
 * `lastSyncAt` got mangled, still converges to the truth. Cheap idempotence
 * beats a clever delta that can drift.
 *
 * Note what is absent: owner_note never appears here. It is the private
 * scratchpad, and the only thing keeping it private is that this query does
 * not select it.
 */
export async function POST(request: Request) {
  const auth = await authenticate(request);
  if ("error" in auth) return auth.error;

  const body = await readJson(request);
  const supabase = serviceClient();

  const [items, announcements] = await Promise.all([
    supabase
      .from("beta_feedback")
      .select("ref, kind, status, reply, replied_at, created_at, body")
      .eq("tester_id", auth.tester.id)
      .order("created_at", { ascending: false })
      .limit(50),
    supabase
      .from("beta_announcements")
      .select("id, title, body, published_at")
      .not("published_at", "is", null)
      .order("published_at", { ascending: false })
      .limit(10),
  ]);

  if (items.error) return NextResponse.json({ error: "lookup_failed" }, { status: 500 });

  // Best effort: the tester's own data has already been assembled, and losing
  // a dashboard refresh is not worth failing their sync over.
  void supabase
    .from("beta_testers")
    .update({
      ...activationPatch(body.activation),
      ...(clip(body.openreefVersion, 64) ? { openreef_version: clip(body.openreefVersion, 64) } : {}),
      ...(clip(body.haVersion, 64) ? { ha_version: clip(body.haVersion, 64) } : {}),
    })
    .eq("id", auth.tester.id)
    .then(() => undefined);

  return NextResponse.json({
    items: (items.data ?? []).map((row) => ({
      ref: row.ref,
      kind: row.kind,
      status: row.status,
      reply: row.reply ?? "",
      repliedAt: row.replied_at ?? "",
      createdAt: row.created_at,
      // Excerpt only — the install already has its own full copy, and this is
      // just enough for it to render an item it has somehow lost track of.
      bodyExcerpt: (row.body ?? "").slice(0, 400),
    })),
    announcements: (announcements.data ?? []).map((row) => ({
      id: row.id,
      title: row.title,
      body: row.body,
      publishedAt: row.published_at,
    })),
    serverTime: new Date().toISOString(),
  });
}
