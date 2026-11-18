import { NextResponse } from "next/server";
import { clip, readJson } from "@/lib/api";
import { limitRequest } from "@/lib/rate-limit";
import { serviceClient } from "@/lib/supabase";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function allowedOrigin(request: Request): string | null {
  const allowed = (process.env.SITE_ORIGIN ?? "https://openreef.co.uk,https://www.openreef.co.uk")
    .split(",").map((entry) => entry.trim()).filter(Boolean);
  const origin = request.headers.get("origin");
  return origin && allowed.includes(origin) ? origin : null;
}

function corsHeaders(origin: string): Record<string, string> {
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Cache-Control": "no-store",
    Vary: "Origin",
  };
}

export function OPTIONS(request: Request) {
  const origin = allowedOrigin(request);
  return new NextResponse(null, {
    status: origin ? 204 : 403,
    headers: origin ? corsHeaders(origin) : { Vary: "Origin" },
  });
}

/** Browser-only public waiting list. Origin validation blocks drive-by browser
 * posts; shared rate limits also cover scripts that can forge that header. */
export async function POST(request: Request) {
  const origin = allowedOrigin(request);
  if (!origin) return NextResponse.json({ error: "origin_not_allowed" }, {
    status: 403, headers: { Vary: "Origin", "Cache-Control": "no-store" },
  });
  const CORS = corsHeaders(origin);
  const withCors = (response: Response) => {
    for (const [name, value] of Object.entries(CORS)) response.headers.set(name, value);
    return response;
  };
  const limited = await limitRequest(request, "signup");
  if (limited) return withCors(limited);
  const parsed = await readJson(request, 32 * 1024);
  if ("error" in parsed) return withCors(parsed.error);
  const body = parsed.body;
  // Hidden site-form field. Older clients omit it. It is an extra signal, not
  // an authentication or complete bot defense; never store suspected bot data.
  if (body.website !== undefined && body.website !== "") {
    return NextResponse.json({ ok: true }, { headers: CORS });
  }
  const email = clip(body.email, 320).toLowerCase();
  if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    return NextResponse.json({ error: "invalid_email" }, { status: 400, headers: CORS });
  }

  const haExperience = clip(body.haExperience, 16);
  const { error } = await serviceClient().from("beta_signups").upsert({
    email,
    source: clip(body.source, 64) || "site",
    note: clip(body.note, 2000) || null,
    tank: clip(body.tank, 200) || null,
    has_apex: typeof body.hasApex === "boolean" ? body.hasApex : null,
    ha_experience: ["new", "comfortable", "advanced"].includes(haExperience) ? haExperience : null,
  }, { onConflict: "email", ignoreDuplicates: true });
  if (error) return NextResponse.json({ error: "signup_failed" }, { status: 500, headers: CORS });
  return NextResponse.json({ ok: true }, { headers: CORS });
}
