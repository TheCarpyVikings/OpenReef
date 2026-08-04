-- =============================================================================
-- 0002 — activation signals
-- =============================================================================
-- Feedback volume only ever measures testers who are already succeeding.
-- Someone who installed OpenReef, couldn't map their probes and quietly gave up
-- is indistinguishable from someone perfectly happy — both send nothing.
--
-- These columns are pushed by the integration on every 30-minute sync, so an
-- install reports whether it actually works even from a tester who never types
-- a word. That turns the roster from a list of names into a picture of who got
-- there and who is stuck.
--
-- All nullable with no defaults beyond the counts: a tester enrolled before
-- this migration simply has nulls until their next sync, and the portal reads
-- that as "not reported yet" rather than as zero.
-- =============================================================================

alter table public.beta_testers
  -- Did they finish the setup wizard? The single clearest activation gate.
  add column setup_complete boolean,

  -- Worst-of trust check status: ok / warning / critical / unknown.
  -- NOTE: core only recomputes this when the panel is opened, so it can be
  -- stale. trust_checked_at travels with it precisely so the UI can say
  -- "as of 3 days ago" instead of implying the reading is live.
  add column trust_status text
    check (trust_status is null or trust_status in ('ok', 'warning', 'critical', 'unknown')),
  add column trust_checked_at timestamptz,

  -- How far they got with the fiddly part. sensors_mapped < sensors_enabled is
  -- the classic stuck-in-setup shape.
  add column sensors_enabled  integer check (sensors_enabled  is null or sensors_enabled  >= 0),
  add column sensors_mapped   integer check (sensors_mapped   is null or sensors_mapped   >= 0),
  add column equipment_mapped integer check (equipment_mapped is null or equipment_mapped >= 0),
  -- Armed equipment means they trust it enough to let it touch a socket. That
  -- is the real "this person is actually using it" signal.
  add column equipment_armed  integer check (equipment_armed  is null or equipment_armed  >= 0);

-- The roster's default sort is "who needs attention", which is last_seen_at
-- ascending over active testers.
create index on public.beta_testers (status, last_seen_at asc nulls first);
