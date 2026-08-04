/** Shared vocabulary. Kept in lockstep with the CHECK constraints in
 *  supabase/migrations/0001_beta_portal.sql and with KINDS/STATUSES in
 *  custom_components/openreef/beta.py — three copies of the same list, because
 *  they live in three languages and the database is the one that enforces it. */

export const KINDS = ["bug", "feature", "idea", "question", "praise", "unsafe"] as const;
export const SEVERITIES = ["low", "normal", "high", "blocker"] as const;
export const STATUSES = [
  "new",
  "triaged",
  "planned",
  "in_progress",
  "actioned",
  "wontfix",
  "duplicate",
] as const;
export const TESTER_STATUSES = ["invited", "active", "paused", "revoked"] as const;

export type Kind = (typeof KINDS)[number];
export type Severity = (typeof SEVERITIES)[number];
export type Status = (typeof STATUSES)[number];
export type TesterStatus = (typeof TESTER_STATUSES)[number];

/** Statuses that mean the item is finished and the tester should hear about it. */
export const CLOSED_STATUSES: Status[] = ["actioned", "wontfix", "duplicate"];

export const KIND_META: Record<Kind, { emoji: string; label: string }> = {
  bug: { emoji: "🐛", label: "Bug" },
  feature: { emoji: "✨", label: "Feature" },
  idea: { emoji: "💡", label: "Idea" },
  question: { emoji: "❓", label: "Question" },
  praise: { emoji: "🩵", label: "Nice thing" },
  unsafe: { emoji: "⚠️", label: "Unsafe" },
};

export const STATUS_META: Record<Status, { label: string; tone: string }> = {
  new: { label: "New", tone: "tone-new" },
  triaged: { label: "Seen", tone: "tone-seen" },
  planned: { label: "Planned", tone: "tone-seen" },
  in_progress: { label: "In progress", tone: "tone-work" },
  actioned: { label: "Actioned", tone: "tone-done" },
  wontfix: { label: "Won't do", tone: "tone-closed" },
  duplicate: { label: "Duplicate", tone: "tone-closed" },
};

export const SEVERITY_META: Record<Severity, { label: string; tone: string }> = {
  low: { label: "Minor", tone: "tone-seen" },
  normal: { label: "Normal", tone: "tone-seen" },
  high: { label: "Painful", tone: "tone-work" },
  blocker: { label: "Blocking", tone: "tone-danger" },
};

export type InboxRow = {
  id: string;
  ref: string;
  kind: Kind;
  severity: Severity;
  status: Status;
  body: string;
  intent: string | null;
  panel_tab: string | null;
  openreef_version: string | null;
  ha_version: string | null;
  owner_note: string | null;
  reply: string | null;
  replied_at: string | null;
  duplicate_of: string | null;
  created_at: string;
  updated_at: string;
  tester_id: string;
  tester_name: string;
  tester_status: TesterStatus;
  has_support: boolean;
  has_logs: boolean;
};

export type FeedbackDetail = InboxRow & {
  support_summary: string | null;
  log_tail: string | null;
  user_agent: string | null;
};

export type Tester = {
  id: string;
  code: string;
  name: string;
  email: string | null;
  status: TesterStatus;
  install_id: string | null;
  openreef_version: string | null;
  ha_version: string | null;
  notes: string | null;
  enrolled_at: string | null;
  last_seen_at: string | null;
  created_at: string;
};

export type Announcement = {
  id: string;
  title: string;
  body: string;
  published_at: string | null;
  created_at: string;
};
