import { NextResponse } from "next/server";
import { authenticate } from "@/lib/api";
import { serviceClient } from "@/lib/supabase";

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

  void supabase
    .from("beta_testers")
    .update({ last_seen_at: new Date().toISOString() })
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
