import "server-only";

import { createServerClient } from "@supabase/ssr";
import { createClient } from "@supabase/supabase-js";
import { cookies } from "next/headers";

/*
 * Two clients, two very different privileges.
 *
 *   serviceClient() — bypasses RLS. Every table in this schema denies anon and
 *   authenticated outright (see the migration header), so this is the ONLY way
 *   data is read or written. It must never be constructed outside server code,
 *   which `import "server-only"` enforces at build time.
 *
 *   sessionClient() — the owner's Supabase Auth session, used for exactly one
 *   thing: finding out who is logged in. It has no table privileges at all,
 *   which is deliberate — authorisation is a single explicit check in
 *   lib/auth.ts rather than something smeared across RLS policies.
 */

function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `${name} is not set. See portal/.env.example — the portal cannot start without it.`,
    );
  }
  return value;
}

export function serviceClient() {
  return createClient(
    required("NEXT_PUBLIC_SUPABASE_URL"),
    required("SUPABASE_SERVICE_ROLE_KEY"),
    { auth: { persistSession: false, autoRefreshToken: false } },
  );
}

export async function sessionClient() {
  const store = await cookies();
  return createServerClient(
    required("NEXT_PUBLIC_SUPABASE_URL"),
    required("NEXT_PUBLIC_SUPABASE_ANON_KEY"),
    {
      cookies: {
        getAll: () => store.getAll(),
        setAll: (list) => {
          try {
            list.forEach(({ name, value, options }) => store.set(name, value, options));
          } catch {
            // Called from a Server Component, where cookies are read-only.
            // Middleware refreshes the session, so this is safe to swallow.
          }
        },
      },
    },
  );
}
