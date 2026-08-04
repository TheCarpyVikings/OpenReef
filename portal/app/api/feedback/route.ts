import { NextResponse } from "next/server";
import { authenticate, clip, jsonError, overRateLimit, readJson } from "@/lib/api";
import { serviceClient } from "@/lib/supabase";
import { KINDS, SEVERITIES, type Kind, type Severity } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function asKind(value: unknown): Kind {
  return KINDS.includes(value as Kind) ? (value as Kind) : "bug";
}

function asSeverity(value: unknown, kind: Kind): Severity {
  // "Something unsafe" is a blocker regardless of what the client said. The
  // panel already enforces this; enforcing it again here means an older build,
  // or a hand-rolled request, cannot file a life-support incident as "minor".
  if (kind === "unsafe") return "blocker";
  return SEVERITIES.includes(value as Severity) ? (value as Severity) : "normal";
}

/*
 * POST /api/feedback — one submission from an enrolled install.
 *
 * The response carries the ref (OR-0042) so the tester's panel can show it
 * immediately and quote it later.
 */
export async function POST(request: Request) {
  const auth = await authenticate(request);
  if ("error" in auth) return auth.error;

  const body = await readJson(request);
  const text = clip(body.body, 4000);
  if (!text) return jsonError("empty_body", 400);

  if (await overRateLimit(auth.tester.id)) return jsonError("rate_limited", 429);

  const kind = asKind(body.kind);
  const supabase = serviceClient();
  const { data, error } = await supabase
    .from("beta_feedback")
    .insert({
      tester_id: auth.tester.id,
      kind,
      severity: asSeverity(body.severity, kind),
      body: text,
      intent: clip(body.intent, 500) || null,
      panel_tab: clip(body.panelTab, 64) || null,
      openreef_version: clip(body.openreefVersion, 64) || null,
      ha_version: clip(body.haVersion, 64) || null,
      user_agent: clip(body.userAgent, 512) || null,
      support_summary: clip(body.supportSummary, 24000) || null,
      log_tail: clip(body.logTail, 8000) || null,
    })
    .select("id, ref")
    .single();

  if (error || !data) return jsonError("insert_failed", 500);

  // Best-effort housekeeping. Neither failing is worth losing the submission
  // that already landed, so nothing below is awaited into the response path.
  void supabase
    .from("beta_testers")
    .update({
      last_seen_at: new Date().toISOString(),
      openreef_version: clip(body.openreefVersion, 64) || null,
      ha_version: clip(body.haVersion, 64) || null,
    })
    .eq("id", auth.tester.id)
    .then(() => undefined);

  void supabase
    .from("beta_feedback_events")
    .insert({ feedback_id: data.id, event: "submitted", detail: kind })
    .then(() => undefined);

  return NextResponse.json({ id: data.id, ref: data.ref });
}
