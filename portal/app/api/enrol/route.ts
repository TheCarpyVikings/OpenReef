import { NextResponse } from "next/server";
import { clip, hashToken, jsonError, newToken, readJson } from "@/lib/api";
import { limitRequest, takeRateLimit } from "@/lib/rate-limit";
import { serviceClient } from "@/lib/supabase";
import { AGREEMENT_VERSION } from "@/lib/terms";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** An invitation is an expiring, single-use credential. Recovery/reinstallation
 * needs a fresh owner-issued invitation; a used code never rotates a token. */
export async function POST(request: Request) {
  const limited = await limitRequest(request, "enrol");
  if (limited) return limited;
  const parsed = await readJson(request, 4096);
  if ("error" in parsed) return parsed.error;
  const body = parsed.body;
  const code = typeof body.code === "string" ? body.code.trim().toUpperCase() : "";
  if (!/^REEF-[A-F0-9]{32}$/.test(code)) return jsonError("invalid_code", 403);
  if (body.agreementAccepted !== true) return jsonError("agreement_required", 403);

  const codeLimit = await takeRateLimit(`enrol:code:${code}`, 5);
  if (codeLimit) return codeLimit;
  const token = newToken();
  const { data, error } = await serviceClient().rpc("beta_redeem_invite", {
    p_invite_hash: await hashToken(code),
    p_token_hash: await hashToken(token),
    p_install_id: clip(body.installId, 64) || null,
    p_openreef_version: clip(body.openreefVersion, 64) || null,
    p_ha_version: clip(body.haVersion, 64) || null,
    p_agreement_version: AGREEMENT_VERSION,
  });
  if (error) return jsonError("enrol_failed", 503);
  const tester = data?.[0];
  // Expired, used, paused, revoked and unknown invitations are indistinguishable.
  if (!tester) return jsonError("invalid_code", 403);
  return NextResponse.json({ token, testerName: tester.tester_name }, {
    headers: { "Cache-Control": "no-store" },
  });
}
