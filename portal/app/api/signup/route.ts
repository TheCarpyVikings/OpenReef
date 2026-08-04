import { NextResponse } from "next/server";
import { clip, readJson } from "@/lib/api";
import { serviceClient } from "@/lib/supabase";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/*
 * POST /api/signup — the waiting list.
 *
 * This is what openreef.co.uk's currently-unwired FORM_ENDPOINT should point
 * at, so beta interest and the beta roster are one system instead of an inbox
 * and a spreadsheet. Promoting a signup into a tester is one click in /testers.
 *
 * Unlike the other routes this IS browser-called, hence the CORS headers.
 */

/*
 * SITE_ORIGIN is a comma-separated allowlist, because the marketing site is
 * reachable on both the apex and www — and a visitor who happens to land on
 * www would otherwise get a silent CORS failure on submit, which looks exactly
 * like the form being broken.
 *
 * The matching origin is echoed back rather than a wildcard, so the allowlist
 * stays meaningful. `Vary: Origin` is not optional here: without it a CDN can
 * cache one origin's response and serve it to another.
 */
function corsHeaders(request: Request): Record<string, string> {
  const allowed = (process.env.SITE_ORIGIN ?? "https://openreef.co.uk")
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
  const origin = request.headers.get("origin") ?? "";
  return {
    "Access-Control-Allow-Origin": allowed.includes(origin) ? origin : allowed[0],
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    Vary: "Origin",
  };
}

export function OPTIONS(request: Request) {
  return new NextResponse(null, { status: 204, headers: corsHeaders(request) });
}

export async function POST(request: Request) {
  const CORS = corsHeaders(request);
  const body = await readJson(request);
  const email = clip(body.email, 320).toLowerCase();

  // Length + shape only. Anything stricter rejects real addresses, and the
  // real validation is whether they ever reply to the invite.
  if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    return NextResponse.json({ error: "invalid_email" }, { status: 400, headers: CORS });
  }

  // Screening extras — present only when the site form's "beta seat" box was
  // ticked. Anything malformed is dropped rather than rejected: losing a
  // screening answer is fine, losing the signup over it is not.
  const haExperience = clip(body.haExperience, 16);
  const supabase = serviceClient();
  const { error } = await supabase.from("beta_signups").upsert(
    {
      email,
      source: clip(body.source, 64) || "site",
      note: clip(body.note, 2000) || null,
      tank: clip(body.tank, 200) || null,
      has_apex: typeof body.hasApex === "boolean" ? body.hasApex : null,
      ha_experience: ["new", "comfortable", "advanced"].includes(haExperience)
        ? haExperience
        : null,
    },
    { onConflict: "email", ignoreDuplicates: true },
  );

  // A duplicate signup is a success from the visitor's point of view — they
  // asked to be on the list and they are on the list.
  if (error) {
    return NextResponse.json({ error: "signup_failed" }, { status: 500, headers: CORS });
  }
  return NextResponse.json({ ok: true }, { headers: CORS });
}
