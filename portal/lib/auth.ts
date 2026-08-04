import "server-only";

import { redirect } from "next/navigation";
import { sessionClient } from "./supabase";

/*
 * Owner authorisation.
 *
 * Anyone can hold a Supabase Auth session (sign-up is a magic link). Being
 * signed in is therefore NOT authorisation — only an address on OWNER_EMAILS
 * is. That allowlist is an env var rather than a database row on purpose: a
 * SQL injection or a bad service-role query cannot grant someone admin, because
 * the grant does not live in the database at all.
 */

function ownerEmails(): string[] {
  return (process.env.OWNER_EMAILS ?? "")
    .split(",")
    .map((entry) => entry.trim().toLowerCase())
    .filter(Boolean);
}

export function isOwnerEmail(email: string | null | undefined): boolean {
  if (!email) return false;
  const allowed = ownerEmails();
  // Fail closed. An unset OWNER_EMAILS is a misconfiguration, and the safe
  // reading of "nobody is listed" is "nobody gets in", not "everybody does".
  if (allowed.length === 0) return false;
  return allowed.includes(email.toLowerCase());
}

/** Current owner session, or null. Never throws. */
export async function currentOwner(): Promise<{ id: string; email: string } | null> {
  try {
    const supabase = await sessionClient();
    const { data } = await supabase.auth.getUser();
    const user = data.user;
    if (!user?.email || !isOwnerEmail(user.email)) return null;
    return { id: user.id, email: user.email };
  } catch {
    return null;
  }
}

/** Guard for pages and server actions. Redirects to /login when not the owner. */
export async function requireOwner(): Promise<{ id: string; email: string }> {
  const owner = await currentOwner();
  if (!owner) redirect("/login");
  return owner;
}
