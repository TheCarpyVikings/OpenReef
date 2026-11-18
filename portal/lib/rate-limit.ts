import "server-only";

import { isIP } from "node:net";
import { NextResponse } from "next/server";
import { hashToken, jsonError } from "./api";
import { serviceClient } from "./supabase";

const LIMITS = {
  enrol: { global: 120, ip: 20 },
  signup: { global: 300, ip: 10 },
  sync: { global: 6000, ip: 300 },
  feedback: { global: 1200, ip: 120 },
} as const;

/** Vercel overwrites this header at its edge. Never trust a caller-supplied
 * forwarding header on other hosts: use a conservative shared bucket there.
 * https://vercel.com/docs/headers/request-headers#x-vercel-forwarded-for */
export function clientAddress(request: Request): string {
  if (process.env.VERCEL !== "1") return "shared";
  const address = request.headers.get("x-vercel-forwarded-for")?.trim() ?? "";
  return isIP(address) ? address : "shared";
}

/** Atomic, shared across serverless instances. A missing migration or database
 * failure fails closed; it never silently disables throttling. */
export async function takeRateLimit(key: string, limit: number): Promise<NextResponse | null> {
  try {
    const { data, error } = await serviceClient().rpc("beta_take_rate_limit", {
      p_key: await hashToken(key), p_limit: limit, p_window_seconds: 3600,
    });
    if (error || typeof data !== "boolean") return jsonError("temporarily_unavailable", 503);
    if (!data) {
      return NextResponse.json({ error: "rate_limited" }, {
        status: 429, headers: { "Retry-After": "3600", "Cache-Control": "no-store" },
      });
    }
    return null;
  } catch {
    return jsonError("temporarily_unavailable", 503);
  }
}

export async function limitRequest(request: Request, endpoint: keyof typeof LIMITS) {
  const limits = LIMITS[endpoint];
  // Bound total work and the number of per-address rows before creating one.
  return await takeRateLimit(`${endpoint}:global`, limits.global)
    ?? await takeRateLimit(`${endpoint}:ip:${clientAddress(request)}`, limits.ip);
}
