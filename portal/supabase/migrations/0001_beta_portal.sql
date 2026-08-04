-- =============================================================================
-- 0001 — OpenReef beta portal
-- =============================================================================
-- Structured capture and triage of beta feedback from self-hosted OpenReef
-- installs. Replaces ad-hoc messages with one searchable, triageable inbox.
--
-- ACCESS MODEL — deliberately different from UniquePath's.
--   UniquePath's testers are Supabase auth users, so `parent_id = auth.uid()`
--   does all the work. OpenReef's testers are Home Assistant installs behind
--   NAT with no account and no session, so there is no `auth.uid()` to key on.
--
--   Instead: every table is RLS-enabled with NO policies at all. That denies
--   anon and authenticated outright. Every read and write goes through the
--   Next.js server using the service-role key, which bypasses RLS — so the
--   anon key is never a capability, and it is never shipped to a tester.
--   Testers authenticate with a bearer token whose SHA-256 lives in
--   beta_testers.token_hash; the plaintext exists only in transit and in the
--   tester's own config entry.
--
--   That means application code is the gate. It is server-only code behind an
--   owner-email check, and the alternative (handing installs an anon key and
--   writing RLS around a fake identity) would be a worse gate wearing a
--   better costume.
--
-- Feedback bodies are append-only: triage may set status/notes/replies but
-- must never rewrite what a tester wrote. Enforced by trigger, not convention.
-- =============================================================================

create extension if not exists pgcrypto;


-- --- testers ----------------------------------------------------------------
-- One row per person in the beta. Created by the owner (status 'invited') with
-- a code; the row is claimed when their install redeems it.

create table public.beta_testers (
  id              uuid primary key default gen_random_uuid(),
  -- Short, human-typable, unambiguous. Uppercased on write so codes are
  -- case-insensitive to a tester squinting at a phone.
  code            text not null unique check (code = upper(code) and char_length(code) between 4 and 32),
  name            text not null check (char_length(name) between 1 and 120),
  email           text check (email is null or char_length(email) <= 320),
  status          text not null default 'invited'
                    check (status in ('invited', 'active', 'paused', 'revoked')),

  -- Set at enrolment. token_hash is sha256(plaintext) — the plaintext is
  -- returned exactly once and never stored here.
  token_hash      text unique,
  install_id      text check (install_id is null or char_length(install_id) <= 64),

  -- Environment, refreshed on every enrol/sync. Answers "who is even on the
  -- version that has the bug" without asking anyone.
  openreef_version text check (openreef_version is null or char_length(openreef_version) <= 64),
  ha_version       text check (ha_version is null or char_length(ha_version) <= 64),

  -- Owner-private. Never returned by any tester-facing route.
  notes           text check (notes is null or char_length(notes) <= 4000),

  enrolled_at     timestamptz,
  last_seen_at    timestamptz,
  created_at      timestamptz not null default now()
);

create index on public.beta_testers (status, created_at desc);


-- --- feedback ---------------------------------------------------------------

-- Human-quotable references. "OR-0042" is something a tester can read out;
-- a uuid is not.
create sequence public.beta_feedback_ref_seq;

create table public.beta_feedback (
  id              uuid primary key default gen_random_uuid(),
  ref             text not null unique
                    default ('OR-' || lpad(nextval('public.beta_feedback_ref_seq')::text, 4, '0')),
  tester_id       uuid not null references public.beta_testers(id) on delete cascade,

  kind            text not null
                    check (kind in ('bug', 'feature', 'idea', 'question', 'praise', 'unsafe')),
  severity        text not null default 'normal'
                    check (severity in ('low', 'normal', 'high', 'blocker')),
  body            text not null check (char_length(body) between 1 and 4000),
  intent          text check (intent is null or char_length(intent) <= 500),

  -- Auto-captured context. None of this is typed by the tester; it describes
  -- the environment the report came from.
  panel_tab       text check (panel_tab is null or char_length(panel_tab) <= 64),
  openreef_version text check (openreef_version is null or char_length(openreef_version) <= 64),
  ha_version      text check (ha_version is null or char_length(ha_version) <= 64),
  user_agent      text check (user_agent is null or char_length(user_agent) <= 512),
  -- Opt-in attachments (see the Sharing toggles in the panel).
  support_summary text check (support_summary is null or char_length(support_summary) <= 24000),
  log_tail        text check (log_tail is null or char_length(log_tail) <= 8000),

  status          text not null default 'new'
                    check (status in ('new', 'triaged', 'planned', 'in_progress',
                                      'actioned', 'wontfix', 'duplicate')),
  -- Set when status = 'duplicate'. Lets five reports of one bug collapse into
  -- one thread while every reporter still gets told when it's fixed.
  duplicate_of    uuid references public.beta_feedback(id) on delete set null,

  owner_note      text check (owner_note is null or char_length(owner_note) <= 4000),
  -- Tester-visible. Synced down to their panel; owner_note never is.
  reply           text check (reply is null or char_length(reply) <= 2000),
  replied_at      timestamptz,

  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index on public.beta_feedback (status, created_at desc);
create index on public.beta_feedback (tester_id, created_at desc);
create index on public.beta_feedback (kind, created_at desc);
create index on public.beta_feedback (severity, created_at desc);
create index on public.beta_feedback (duplicate_of) where duplicate_of is not null;


-- --- audit trail ------------------------------------------------------------
-- Append-only record of triage. Cheap, and it means "when did I action this,
-- and what did I say" survives a change of mind.

create table public.beta_feedback_events (
  id          uuid primary key default gen_random_uuid(),
  feedback_id uuid not null references public.beta_feedback(id) on delete cascade,
  event       text not null check (char_length(event) <= 64),
  detail      text check (detail is null or char_length(detail) <= 2000),
  created_at  timestamptz not null default now()
);

create index on public.beta_feedback_events (feedback_id, created_at desc);


-- --- announcements ----------------------------------------------------------
-- Broadcast to every active tester. The point is to stop the same message
-- being typed eight times: "0.7.0 is out, please hammer the dosing tab."

create table public.beta_announcements (
  id           uuid primary key default gen_random_uuid(),
  title        text not null check (char_length(title) between 1 and 200),
  body         text not null check (char_length(body) between 1 and 2000),
  published_at timestamptz,
  created_at   timestamptz not null default now()
);

create index on public.beta_announcements (published_at desc nulls last);


-- --- signups ----------------------------------------------------------------
-- The waiting list. This is what the marketing site's currently-unwired
-- FORM_ENDPOINT should post into, so the beta funnel and the beta roster are
-- the same system rather than an inbox and a spreadsheet.

create table public.beta_signups (
  id         uuid primary key default gen_random_uuid(),
  email      text not null unique check (char_length(email) between 3 and 320),
  source     text check (source is null or char_length(source) <= 64),
  note       text check (note is null or char_length(note) <= 2000),
  -- Set when this signup is promoted into a tester, so the funnel is legible.
  tester_id  uuid references public.beta_testers(id) on delete set null,
  created_at timestamptz not null default now()
);


-- --- triggers ---------------------------------------------------------------

create or replace function public.beta_set_updated_at()
returns trigger language plpgsql as $$
begin
  NEW.updated_at = now();
  return NEW;
end;
$$;

create trigger beta_feedback_set_updated_at before update on public.beta_feedback
  for each row execute procedure public.beta_set_updated_at();

-- What a tester wrote is evidence, not a draft. Triage may move status and add
-- notes/replies; it may never edit the body, the captured context, or move a
-- report to a different tester. Postgres has no column-level RLS, so the
-- immutability is a trigger.
create or replace function public.beta_feedback_protect_immutable()
returns trigger language plpgsql as $$
begin
  if NEW.tester_id  is distinct from OLD.tester_id
     or NEW.ref     is distinct from OLD.ref
     or NEW.kind    is distinct from OLD.kind
     or NEW.body    is distinct from OLD.body
     or NEW.intent  is distinct from OLD.intent
     or NEW.panel_tab is distinct from OLD.panel_tab
     or NEW.openreef_version is distinct from OLD.openreef_version
     or NEW.ha_version is distinct from OLD.ha_version
     or NEW.user_agent is distinct from OLD.user_agent
     or NEW.support_summary is distinct from OLD.support_summary
     or NEW.log_tail is distinct from OLD.log_tail
     or NEW.created_at is distinct from OLD.created_at then
    raise exception 'beta_feedback: only triage fields are mutable';
  end if;
  return NEW;
end;
$$;

create trigger beta_feedback_protect_immutable_trigger
  before update on public.beta_feedback
  for each row execute procedure public.beta_feedback_protect_immutable();

-- A duplicate must point at something, and never at itself.
create or replace function public.beta_feedback_check_duplicate()
returns trigger language plpgsql as $$
begin
  if NEW.duplicate_of = NEW.id then
    raise exception 'beta_feedback: an item cannot duplicate itself';
  end if;
  if NEW.status = 'duplicate' and NEW.duplicate_of is null then
    raise exception 'beta_feedback: status duplicate requires duplicate_of';
  end if;
  return NEW;
end;
$$;

create trigger beta_feedback_check_duplicate_trigger
  before insert or update on public.beta_feedback
  for each row execute procedure public.beta_feedback_check_duplicate();


-- --- RLS: deny everything to anon + authenticated ---------------------------
-- No policies by design; see the header. Only service_role reaches these.

alter table public.beta_testers          enable row level security;
alter table public.beta_feedback         enable row level security;
alter table public.beta_feedback_events  enable row level security;
alter table public.beta_announcements    enable row level security;
alter table public.beta_signups          enable row level security;

revoke all on public.beta_testers, public.beta_feedback, public.beta_feedback_events,
              public.beta_announcements, public.beta_signups
  from anon, authenticated;


-- --- inbox view -------------------------------------------------------------
-- The list the portal reads. Deliberately excludes support_summary and
-- log_tail: they are large, and rendering an inbox should not ship a megabyte
-- of diagnostics to a browser that is only showing forty preview lines.

create or replace view public.beta_inbox
with (security_invoker = true) as
select
  f.id, f.ref, f.kind, f.severity, f.status, f.body, f.intent,
  f.panel_tab, f.openreef_version, f.ha_version,
  f.owner_note, f.reply, f.replied_at, f.duplicate_of,
  f.created_at, f.updated_at,
  t.id   as tester_id,
  t.name as tester_name,
  t.status as tester_status,
  (f.support_summary is not null and f.support_summary <> '') as has_support,
  (f.log_tail is not null and f.log_tail <> '')               as has_logs
from public.beta_feedback f
join public.beta_testers t on t.id = f.tester_id;

-- Supabase grants the API roles on objects in `public` by default, and a view
-- is an object. Without this the deny-all above would have a hole shaped
-- exactly like the inbox.
revoke all on public.beta_inbox from anon, authenticated;
