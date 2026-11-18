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
  return NextResponse.json({ error }, { status, headers: { "Cache-Control": "no-store" } });
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

/** 128 random bits; 37 characters fits the existing HA client's 64-char limit.
 * Only a digest is stored. Copy/paste is preferable to reading this aloud. */
export function newInviteCode(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return `REEF-${Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("").toUpperCase()}`;
}

export function bearer(request: Request): string {
  const header = request.headers.get("authorization") ?? "";
  const match = /^Bearer\s+(.+)$/i.exec(header.trim());
  return match ? match[1].trim() : "";
}

export function clip(value: unknown, max: number): string {
  return typeof value === "string" ? value.trim().slice(0, max) : "";
}

/** Bound bytes while reading, including chunked bodies without Content-Length.
 * Field clipping alone happens too late to protect JSON parsing/memory. */
export async function readJson(
  request: Request,
  maxBytes = 8192,
): Promise<{ body: Record<string, unknown> } | { error: NextResponse }> {
  if (request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") {
    return { error: jsonError("json_required", 415) };
  }
  const length = request.headers.get("content-length");
  if (length && Number(length) > maxBytes) return { error: jsonError("body_too_large", 413) };
  const reader = request.body?.getReader();
  if (!reader) return { error: jsonError("invalid_json", 400) };
  let size = 0;
  const chunks: Uint8Array[] = [];
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) {
        void reader.cancel().catch(() => undefined);
        return { error: jsonError("body_too_large", 413) };
      }
      chunks.push(value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    const parsed: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { error: jsonError("invalid_json", 400) };
    }
    return { body: parsed as Record<string, unknown> };
  } catch {
    return { error: jsonError("invalid_json", 400) };
  } finally {
    reader.releaseLock();
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
  if (!/^[a-f0-9]{64}$/.test(token)) return { error: jsonError("invalid_token", 401) };

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
