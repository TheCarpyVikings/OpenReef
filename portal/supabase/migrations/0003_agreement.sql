-- =============================================================================
-- 0003 — agreement acceptance
-- =============================================================================
-- "Who agreed to what, and when" has to survive future rewording of the
-- agreement, so acceptance is recorded as a version string + timestamp on the
-- tester row rather than as a boolean. The version comes from
-- portal/lib/terms.ts (AGREEMENT_VERSION), kept in lockstep with the Version:
-- line in content/beta-agreement.md and content/privacy-notice.md.
--
-- Nullable on purpose: testers enrolled before this shipped have nulls, which
-- reads as "accepted nothing yet". Re-enrolling (same code, new token — the
-- reinstall path) re-records acceptance at the then-current version.
-- =============================================================================

alter table public.beta_testers
  add column agreement_version text
    check (agreement_version is null or char_length(agreement_version) <= 32),
  add column agreement_accepted_at timestamptz;
