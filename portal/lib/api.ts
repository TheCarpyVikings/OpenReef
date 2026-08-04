import "server-only";

import { NextResponse } from "next/server";
import { serviceClient } from "./supabase";
import type { Tester } from "./types";

/*
 * Shared plumbing for the three tester-facing routes.
 *
 * Callers are Home Assistant integrations on domestic broadband: they drop
 * mid-request, retry, run months-old builds, and occasionally send nonsense.
 * Every helper here assumes that and returns a typed error rather than
 * throwing, so a malformed request is a 400 and never a 500.
 */

export function jsonError(error: string, status: number) {
  return NextResponse.json({ error }, { status });
}

/** Tokens are 32 random bytes, hex. Stored only as a SHA-256 digest. */
export function newToken(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function hashToken(token: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** Invite codes: uppercase, no vowels and no 0/1/I/O — unambiguous read aloud
 *  and impossible to accidentally spell a word with. */
export function newInviteCode(): string {
  const alphabet = "BCDFGHJKLMNPQRSTVWXYZ23456789";
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  const pick = (index: number) => alphabet[bytes[index] % alphabet.length];
  return `REEF-${pick(0)}${pick(1)}${pick(2)}${pick(3)}`;
}

export function bearer(request: Request): string {
  const header = request.headers.get("authorization") ?? "";
  const match = /^Bearer\s+(.+)$/i.exec(header.trim());
  return match ? match[1].trim() : "";
}

export function clip(value: unknown, max: number): string {
  return typeof value === "string" ? value.trim().slice(0, max) : "";
}

/** Body parse that never throws — an empty or non-JSON body becomes {}. */
export async function readJson(request: Request): Promise<Record<string, unknown>> {
  try {
    const parsed = await request.json();
    return parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

export type AuthedTester = Pick<Tester, "id" | "name" | "status">;

/**
 * Resolve the bearer token to an active tester.
 *
 * Paused and revoked testers are rejected here rather than filtered later, so
 * there is exactly one place that decides whether an install may still talk to
 * the portal — and revoking someone genuinely stops them mid-beta.
 */
export async function authenticate(
  request: Request,
): Promise<{ tester: AuthedTester } | { error: NextResponse }> {
  const token = bearer(request);
  if (!token) return { error: jsonError("missing_token", 401) };

  const supabase = serviceClient();
  const { data, error } = await supabase
    .from("beta_testers")
    .select("id, name, status")
    .eq("token_hash", await hashToken(token))
    .maybeSingle();

  if (error) return { error: jsonError("lookup_failed", 500) };
  if (!data) return { error: jsonError("invalid_token", 401) };
  if (data.status === "revoked") return { error: jsonError("revoked", 403) };
  if (data.status !== "active") return { error: jsonError("inactive", 403) };
  return { tester: data as AuthedTester };
}

/**
 * Crude per-tester submission cap.
 *
 * Not a security control — it exists so a broken install stuck in a retry loop
 * cannot bury a day's real feedback under ten thousand identical rows. A
 * genuine tester will never come close to it, and it counts rows rather than
 * keeping state, so it survives serverless cold starts.
 */
export async function overRateLimit(testerId: string): Promise<boolean> {
  const since = new Date(Date.now() - 60 * 60 * 1000).toISOString();
  const supabase = serviceClient();
  const { count, error } = await supabase
    .from("beta_feedback")
    .select("id", { count: "exact", head: true })
    .eq("tester_id", testerId)
    .gte("created_at", since);
  if (error) return false; // a failed check must not block real feedback
  return (count ?? 0) >= 30;
}
