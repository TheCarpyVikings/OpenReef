# OpenReef beta portal

Owner-only inbox for the **Ask Reece** button in the OpenReef Home Assistant
panel, plus the tester roster and the broadcast channel.

Next.js 16 + Supabase Postgres. Standalone Vercel project — deliberately
separate from the root Next dashboard app so it never entangles with the auth
and secrets work in `VERCEL_READINESS_TODO.md`, exactly as `site/` is.

Feature docs and the wire contract: [`docs/beta-feedback.md`](../docs/beta-feedback.md).

---

## Deploy

### 1. Supabase

Create a project, then run the migration:

```bash
supabase link --project-ref <ref>
supabase db push          # applies supabase/migrations/0001_beta_portal.sql
```

Or paste `supabase/migrations/0001_beta_portal.sql` into the SQL editor.

Then **Authentication → Providers → Email**: enable magic links. Built-in SMTP
is fine — this sends a handful of emails to one address.

### 2. Vercel

New project, **Root Directory = `portal`**, framework Next.js. Set the
environment variables from [`.env.example`](.env.example):

| Variable | Notes |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Project Settings → API |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Project Settings → API |
| `SUPABASE_SERVICE_ROLE_KEY` | **Server-only.** Full access to every tester's feedback — rotate immediately if it leaks. |
| `OWNER_EMAILS` | Comma-separated allowlist. Empty fails closed. |
| `SITE_ORIGIN` | Origin allowed to POST `/api/signup` |

Point `beta.openreef.co.uk` at it.

### 3. Tell the integration where it lives

`DEFAULT_ENDPOINT` in `custom_components/openreef/beta.py` is
`https://beta.openreef.co.uk`. If you deploy elsewhere, change that constant —
it is overridable per-install, but the default is what every tester gets.

### 4. First tester

Sign in → **Testers** → generate a code → send it. They paste it into
OpenReef → Ask Reece.

---

## Local development

```bash
cd portal
pnpm install
cp .env.example .env.local     # fill in your Supabase values
pnpm dev
```

To point a local Home Assistant at it, set the install's endpoint to
`http://<your-machine>:3000` when enrolling (the `beta_enrol` websocket command
takes an optional `endpoint`).

---

## Access model

Worth understanding before changing anything here, because it is deliberately
**not** the RLS-policy model UniquePath uses.

UniquePath's testers are Supabase auth users, so `parent_id = auth.uid()` does
all the work. OpenReef's testers are Home Assistant installs behind NAT with no
account and no session — there is no `auth.uid()` to key on.

So instead:

- **Every table denies `anon` and `authenticated` outright.** RLS is enabled
  with no policies at all, and privileges are revoked (including on the
  `beta_inbox` view — Supabase grants the API roles on objects in `public` by
  default, and without that revoke the deny-all would have a hole shaped
  exactly like the inbox).
- **All access is server-side via the service-role key**, which bypasses RLS.
  `import "server-only"` makes shipping it to a browser a build error.
- **Testers authenticate with a bearer token** whose SHA-256 is stored in
  `beta_testers.token_hash`. The plaintext exists only in transit and in the
  tester's own config entry. Revoking clears the hash, so it bites on the next
  request.
- **The owner is an env allowlist, not a database row.** A SQL injection or a
  bad service-role query cannot grant someone admin, because the grant does not
  live in the database.
- **Two independent gates**: `middleware.ts` bounces anonymous requests, and
  every page and server action calls `requireOwner()` at the point of use where
  it cannot be routed around by a matcher typo.

Feedback bodies are **append-only**. Triage may set status, notes and replies;
a database trigger rejects any update that touches the body or the captured
context. What a tester wrote is evidence, not a draft.

---

## Layout

```
app/
  page.tsx                 inbox — severity-then-recency
  feedback/[id]/page.tsx   detail + triage + diagnostics
  testers/page.tsx         roster, invite codes, waiting list
  announcements/page.tsx   broadcast
  actions.ts               every mutation (all call requireOwner)
  api/enrol|feedback|sync  tester-facing, bearer auth
  api/signup               browser-called, for the marketing site form
lib/
  supabase.ts   service + session clients
  auth.ts       owner allowlist
  api.ts        tokens, codes, rate limit
  types.ts      shared vocabulary (mirrors the SQL CHECKs and beta.py)
supabase/migrations/
```
