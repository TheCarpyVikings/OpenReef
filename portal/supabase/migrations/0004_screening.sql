-- =============================================================================
-- 0004 — signup screening
-- =============================================================================
-- The waiting list currently captures an email and three checkboxes, which
-- makes inviting first-come-first-served the only possible policy. Three more
-- questions — asked on the site form only when "beta seat" is ticked — let
-- invitations be deliberate: an Apex owner with a mature tank and Home
-- Assistant experience is a different (and for the current cohort, better)
-- tester than someone brand new to both.
--
-- All nullable: old rows predate the questions, and manual-only signups are
-- never asked them.
-- =============================================================================

alter table public.beta_signups
  -- Free text, e.g. "450L mixed reef, 3 years". Enough to judge, small enough
  -- to skim in the waiting-list table.
  add column tank text check (tank is null or char_length(tank) <= 200),

  -- The differentiation north-star is beating Fusion for Apex owners, so this
  -- is the single highest-value screening bit we can ask for.
  add column has_apex boolean,

  -- Self-assessed, which is fine — it predicts how much hand-holding install
  -- will take, not skill.
  add column ha_experience text
    check (ha_experience is null or ha_experience in ('new', 'comfortable', 'advanced'));
