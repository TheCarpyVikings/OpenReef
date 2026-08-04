import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

/*
 * Session refresh + the outer gate on the admin UI.
 *
 * This runs on every admin route and does two jobs: keep the Supabase session
 * cookie fresh, and bounce anyone who isn't signed in to /login. It is NOT the
 * authorisation check — the owner-email allowlist in lib/auth.ts is, and every
 * page and server action calls requireOwner() independently.
 *
 * Two gates on purpose. Middleware is easy to mis-scope with a matcher typo;
 * requireOwner() sits at the point of use where it cannot be routed around.
 */

const PUBLIC_PREFIXES = ["/login", "/auth", "/api"];

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const response = NextResponse.next({ request });

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  // Unconfigured deploy: let the request through so the page can render a
  // useful "you haven't set your env vars" error instead of a redirect loop.
  if (!url || !anon) return response;

  const supabase = createServerClient(url, anon, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (list) => {
        list.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
      },
    },
  });

  const { data } = await supabase.auth.getUser();

  if (!data.user && !PUBLIC_PREFIXES.some((prefix) => pathname.startsWith(prefix))) {
    const target = request.nextUrl.clone();
    target.pathname = "/login";
    target.searchParams.set("next", pathname);
    return NextResponse.redirect(target);
  }

  return response;
}

export const config = {
  matcher: [
    // Everything except Next internals and static files. The tester-facing API
    // is excluded via PUBLIC_PREFIXES above rather than here, so its requests
    // still get a session refresh pass and cost nothing extra.
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
