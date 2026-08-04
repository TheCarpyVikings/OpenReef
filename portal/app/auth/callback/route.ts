import { NextResponse } from "next/server";
import { sessionClient } from "@/lib/supabase";
import { isOwnerEmail } from "@/lib/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Exchanges the magic-link code for a session cookie, then hands off to the
 *  requested page. A non-owner who completes sign-in gets bounced straight
 *  back out — they hold a valid session, which is not the same as access. */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const next = url.searchParams.get("next") ?? "/";

  if (!code) return NextResponse.redirect(new URL("/login", url.origin));

  const supabase = await sessionClient();
  const { data, error } = await supabase.auth.exchangeCodeForSession(code);

  if (error || !isOwnerEmail(data.user?.email)) {
    await supabase.auth.signOut();
    return NextResponse.redirect(new URL("/login?denied=1", url.origin));
  }

  // Relative paths only — an open redirect on a login callback would let an
  // attacker land the owner's freshly-authenticated browser anywhere.
  const target = next.startsWith("/") && !next.startsWith("//") ? next : "/";
  return NextResponse.redirect(new URL(target, url.origin));
}
