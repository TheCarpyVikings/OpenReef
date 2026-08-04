"use client";

import { createBrowserClient } from "@supabase/ssr";
import { useState, type FormEvent } from "react";

/*
 * Magic-link sign-in.
 *
 * Note what this page does NOT do: check whether the address is the owner's.
 * Anyone can request a link and anyone can hold a session — authorisation is
 * the OWNER_EMAILS allowlist checked server-side on every page and action.
 * Telling a stranger at this screen whether an address is the admin's would be
 * handing out exactly the piece of information they came for.
 */
export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const supabase = createBrowserClient(
        process.env.NEXT_PUBLIC_SUPABASE_URL!,
        process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      );
      const { error: authError } = await supabase.auth.signInWithOtp({
        email: email.trim(),
        options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
      });
      if (authError) throw new Error(authError.message);
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send the link.");
    }
    setBusy(false);
  }

  return (
    <div className="shell" style={{ maxWidth: 420, paddingTop: 80 }}>
      <div className="panel">
        <p className="eyebrow">OpenReef</p>
        <h1 style={{ fontSize: 26 }}>Beta portal</h1>

        {sent ? (
          <p style={{ color: "var(--fg-muted)", marginTop: 14 }}>
            If that address has access, a sign-in link is on its way. It expires
            shortly, so use it soon.
          </p>
        ) : (
          <form onSubmit={onSubmit} style={{ marginTop: 18 }}>
            <label className="label" htmlFor="email">
              Email
            </label>
            <input
              id="email"
              className="field"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
            {error ? (
              <p className="notice error" style={{ marginTop: 12 }} role="alert">
                {error}
              </p>
            ) : null}
            <button className="btn primary" type="submit" disabled={busy} style={{ marginTop: 14, width: "100%" }}>
              {busy ? "Sending…" : "Email me a link"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
