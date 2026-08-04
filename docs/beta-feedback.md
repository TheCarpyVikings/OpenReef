# Beta feedback — "Ask Reece"

A floating button in every corner of the OpenReef panel that turns a tester's
half-formed "hey, this looks wrong" into a triageable report with the
diagnostics already attached — and tells them when it gets acted on.

Shipped in **0.7.0**.

> **This is scaffolding.** Every design decision below optimises for being
> removed cleanly when the beta ends. See [Removal](#removal) — it is four
> `git rm`s and six lines.

---

## Why it exists

Beta feedback currently arrives as messages, and every message costs a
round-trip: which version, which tab, what does Trust Check say, can you paste
your support summary. With one tester that is annoying. With ten it is the
whole evening.

So the button collects the round-trip up front, and the portal closes the loop
without a reply being typed.

---

## Shape

```
Tester's Home Assistant                     beta.openreef.co.uk (Vercel)
┌──────────────────────────┐                ┌─────────────────────────────┐
│ openreef-beta.js         │                │ /api/enrol    (code → token)│
│   the FAB + modal        │                │ /api/feedback (submit)      │
│        ↕ websocket       │   HTTPS out    │ /api/sync     (poll)        │
│ beta.py                  │ ─────────────► │ /api/signup   (waiting list)│
│   consent, redaction,    │                ├─────────────────────────────┤
│   offline queue, 30-min  │ ◄───────────── │ Inbox · Testers · Broadcast │
│   poll, notifications    │   replies      └──────────────┬──────────────┘
└──────────────────────────┘                               │ Supabase Postgres
```

Testers are self-hosted installs behind NAT, so **nothing can reach in**. The
integration pushes out and polls for replies every 30 minutes (and immediately
when a tester opens the modal). That is the constraint every other decision
falls out of.

---

## What a tester sees

**The button.** Bottom-right on every tab, including Reef Pulse. Shows an
unread dot when there's a reply waiting. Hidden entirely for non-admin Home
Assistant users, because the backend requires admin to submit and offering a
button that will refuse is worse than no button.

**The modal.** Six kinds — bug, feature request, idea, question, nice thing,
and *something unsafe*. Bugs also ask how much it hurts. There's a message box,
an optional "what were you trying to do", and a disclosure that shows the
**exact text** that will be sent, including the full support summary rendered
verbatim.

`Something unsafe` gets its own treatment: it is always filed as a blocker
regardless of what the client says, and the form leads with *deal with the tank
first, this can wait*.

**Yours.** Every report with its current status and Reece's reply.

**News.** Announcements broadcast from the portal.

**Sharing.** Two toggles — support summary, and OpenReef's lines from the HA
log. Both default on, both are genuinely optional, and turning them off empties
the field rather than merely hiding it. Leaving the beta drops the token
immediately.

---

## What gets attached

Always:

| Field | Source |
|---|---|
| Panel tab | which tab was open when they pressed the button |
| OpenReef version, schema | `INTEGRATION_VERSION` |
| Home Assistant version | `homeassistant.const.__version__` |
| Browser user-agent | the panel |
| Tester name, install id | assigned at enrolment |

Opt-in:

| Field | Source |
|---|---|
| Support summary | the panel's existing `_supportSummaryText()` — versions, mapped/armed equipment, Trust Check, heartbeat, health-score breakdown, recent activity |
| Log tail | last 80 lines of `home-assistant.log` mentioning openreef, and nothing else |

The support summary is the same text Settings → System Check has always let a
tester copy by hand. This just stops them having to.

### Redaction

Everything outbound passes `beta.redact()` first, which strips vendor-prefixed
keys (`sk-`, `ghp_`, `xox…`), bearer tokens, `api_key=`/`password:` pairs, and
**JWTs** — Home Assistant long-lived access tokens are JWTs, and are the single
most damaging thing a tester could paste into a bug report.

It is deliberately over-eager. A mangled log line costs a follow-up question; a
leaked token costs a tester their Home Assistant.

---

## Reliability

- **Offline queue.** A failed submit is stored locally (max 20) and flushed on
  the next sync. Losing a bug report because the portal was rebooting is the
  one failure a tester would never forgive.
- **Permanent failures are dropped.** A queued item rejected with
  `invalid_token`/`revoked` is discarded rather than retried every 30 minutes
  forever.
- **Unread is sticky.** An item stays flagged until the tester actually opens
  it, so a status change that lands while the panel is closed is never missed.
- **Sync is idempotent.** `/api/sync` returns the whole set, not a delta, so an
  install that was offline for a fortnight converges rather than drifting.
- **Everything fails soft.** A dead portal, a corrupt state blob, a revoked
  token — none of it raises into the panel, setup, or unload. Feedback plumbing
  must not be able to take a reef controller down.

---

## Wire contract

All tester-facing calls are `POST`, JSON in and out, `Authorization: Bearer
<token>` except enrol. Made by the HA *backend* (aiohttp), never a browser — so
there is no CORS anywhere except `/api/signup`.

```
POST /api/enrol
  { code, installId, openreefVersion, haVersion }
→ 200 { token, testerName }        403 { error: "invalid_code" | "revoked" }

POST /api/feedback
  { installId, kind, severity, body, intent, panelTab, userAgent,
    openreefVersion, haVersion, supportSummary, logTail, clientAt }
→ 200 { id, ref }                  401 invalid_token · 403 revoked · 429 rate_limited

POST /api/sync
  { installId, since }
→ 200 { items: [{ ref, kind, status, reply, repliedAt, createdAt, bodyExcerpt }],
        announcements: [{ id, title, body, publishedAt }],
        serverTime }
```

`owner_note` is never selected by `/api/sync`. That query is the only thing
keeping the private scratchpad private — do not add `*` to it.

---

## Portal

Lives in [`portal/`](../portal). Next.js on Vercel, Supabase Postgres, owner-only.
See [portal/README.md](../portal/README.md) to deploy.

- **Inbox** — sorted severity-then-recency, so a blocker filed on Tuesday
  doesn't sink under Thursday's typo report. Filters by status; stat tiles for
  open / blocking / this week / actioned / active testers.
- **Detail** — the report, all captured context, the support summary and log
  tail behind disclosures, sibling reports from the same tab (spot duplicates
  before writing three replies), and the triage form. Status and the
  tester-facing reply are **one write**, so "actioned" and "here's what I did"
  can never disagree.
- **Testers** — issue codes, pause, revoke (which clears the token, so it bites
  on the next request rather than at some later cleanup), private notes, and
  the waiting list.
- **Announcements** — one message to every active tester's panel. Draft, then
  publish as a separate deliberate act; there is no unsend.

---

## Adding a tester

1. Portal → **Testers** → name (+ email) → **Generate code**.
2. Send them the code (`REEF-XXXX`).
3. They open OpenReef → **Ask Reece** → paste → **Join the beta**.

No account, no password, nothing for them to lose. Re-enrolling with the same
code rotates the token, so a tester who restores a backup or moves hardware can
get themselves unstuck without messaging you — which is the exact failure this
system exists to prevent.

---

## Removal

The whole point. Four deletions and six lines:

```bash
git rm custom_components/openreef/beta.py
git rm custom_components/openreef/frontend/openreef-beta.js
git rm tests/test_beta.py tests/test_panel_beta.mjs
grep -rn "BETA-FEEDBACK" custom_components/     # delete every line it finds
```

That grep currently returns six lines in `__init__.py` and
`openreef-panel.js`, plus `_mountBetaFab()`.

Then either archive or drop the `portal/` directory and the Supabase project.

**Why there is nothing else to unwind:**

- Beta state lives in its own config-entry options key (`beta_feedback`),
  never in `CONF_SETTINGS`. So there is no `CORE_SCHEMA_VERSION` bump, no entry
  in `_normalise_core_config`, and no migration to write. Removal leaves one
  orphan dict that nothing reads.
- Nothing in the integration imports *from* `beta.py` except those tagged
  lines. It shares no helpers and no constants — the two it needs (`DOMAIN`,
  the options key) are duplicated on purpose.
- If `openreef-beta.js` is deleted but `_mountBetaFab()` survives, the dynamic
  import rejects, `<openreef-beta-fab>` stays an undefined element with no box
  and no content, and nothing breaks. Covered by a test.
- If `beta.py` is deleted but the JS survives, `openreef/beta_status` errors,
  the element stays invisible, and nothing breaks. Also covered by a test.

---

## Tests

`tests/test_beta.py` (29) and `tests/test_panel_beta.mjs` (18), both picked up
by CI's discovery loop. They pin the things that would be genuinely bad to get
wrong: redaction catches an HA long-lived token; consent toggles empty the
field rather than hiding it; `unsafe` cannot be filed as minor; a closed item
notifies exactly once; the token never reaches the panel; a down portal queues
rather than loses; replies from the portal are escaped before they hit
`innerHTML`; and the delegated listeners bind exactly once across re-renders.
