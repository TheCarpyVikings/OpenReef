-- =============================================================================
-- 0005 — prompted micro-feedback kinds
-- =============================================================================
-- Two new feedback kinds for the panel's prompt mechanism:
--
--   'pulse' — the one-tap "how's it going?" the panel offers after a week of
--             silence. Body is a short human-readable answer ("Going well").
--   'nps'   — the once-ever 0–10 question at day 30. Body is "NPS <n>".
--
-- Same table as everything else on purpose: with a cohort this size a pulse is
-- just a very small feedback item, and giving it its own table would buy
-- nothing but joins. Postgres CHECK constraints can't be altered in place, so
-- drop-and-recreate with the widened list.
-- =============================================================================

alter table public.beta_feedback
  drop constraint if exists beta_feedback_kind_check;

alter table public.beta_feedback
  add constraint beta_feedback_kind_check
    check (kind in ('bug', 'feature', 'idea', 'question', 'praise', 'unsafe',
                    'pulse', 'nps'));
