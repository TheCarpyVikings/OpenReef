import { NextResponse } from "next/server";
import { clip, hashToken, jsonError, newToken, readJson } from "@/lib/api";
import { serviceClient } from "@/lib/supabase";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/*
 * POST /api/enrol — redeem an invite code.
 *
 * Called once per install, unauthenticated (the code IS the credential). On
 * success it mints a bearer token, returns the plaintext exactly once, and
 * stores only its hash.
 *
 * Re-enrolling with the same code is allowed and rotates the token. That is
 * deliberate: a tester who reinstalls Home Assistant, restores a backup, or
 * moves to new hardware would otherwise be locked out with no self-service
 * way back in — and "message Reece to get unstuck" is the exact failure this
 * whole system exists to prevent.
 */
export async function POST(request: Request) {
  const body = await readJson(request);
  const code = clip(body.code, 64).toUpperCase();
  const installId = clip(body.installId, 64);

  if (!code) return jsonError("invalid_code", 400);

  const supabase = serviceClient();
  const { data: tester, error } = await supabase
    .from("beta_testers")
    .select("id, name, status")
    .eq("code", code)
    .maybeSingle();

  if (error) return jsonError("lookup_failed", 500);
  // Same response for "no such code" and "revoked code" would be tidier, but
  // a revoked tester deserves to know they were removed rather than being
  // left to debug a typo that isn't there.
  if (!tester) return jsonError("invalid_code", 403);
  if (tester.status === "revoked") return jsonError("revoked", 403);

  const token = newToken();
  const { error: updateError } = await supabase
    .from("beta_testers")
    .update({
      token_hash: await hashToken(token),
      status: "active",
      install_id: installId || null,
      openreef_version: clip(body.openreefVersion, 64) || null,
      ha_version: clip(body.haVersion, 64) || null,
      enrolled_at: new Date().toISOString(),
      last_seen_at: new Date().toISOString(),
    })
    .eq("id", tester.id);

  if (updateError) return jsonError("enrol_failed", 500);

  return NextResponse.json({ token, testerName: tester.name });
}
