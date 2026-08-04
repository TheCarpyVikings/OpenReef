import Link from "next/link";
import { Chrome } from "@/app/components/Chrome";
import { requireOwner } from "@/lib/auth";
import { ago } from "@/lib/format";
import { serviceClient } from "@/lib/supabase";
import {
  KIND_META,
  SEVERITY_META,
  STATUS_META,
  STATUSES,
  type InboxRow,
  type Status,
} from "@/lib/types";

export const dynamic = "force-dynamic";

/*
 * The inbox.
 *
 * Ordering is severity-then-recency rather than pure recency: with one tester
 * those are the same list, but at twenty testers a blocker filed on Tuesday
 * must not sink under Thursday's typo reports. That is the single ranking
 * decision that keeps this readable as the beta grows.
 */

const FILTERS: Array<{ value: Status | "all" | "open"; label: string }> = [
  { value: "open", label: "Open" },
  { value: "all", label: "All" },
  ...STATUSES.map((status) => ({ value: status, label: STATUS_META[status].label })),
];

const OPEN_STATUSES: Status[] = ["new", "triaged", "planned", "in_progress"];

const SEVERITY_RANK: Record<string, number> = { blocker: 0, high: 1, normal: 2, low: 3 };

export default async function InboxPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; tester?: string }>;
}) {
  await requireOwner();
  const params = await searchParams;
  const filter = (params.status ?? "open") as Status | "all" | "open";
  const supabase = serviceClient();

  let query = supabase.from("beta_inbox").select("*").limit(300);
  if (filter === "open") query = query.in("status", OPEN_STATUSES);
  else if (filter !== "all") query = query.eq("status", filter);
  if (params.tester) query = query.eq("tester_id", params.tester);

  const [{ data, error }, counts, testers] = await Promise.all([
    query.order("created_at", { ascending: false }),
    supabase.from("beta_inbox").select("status, severity, kind, created_at"),
    supabase.from("beta_testers").select("id, name").eq("status", "active"),
  ]);

  const rows = ((data ?? []) as InboxRow[]).sort(
    (a, b) =>
      (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9) ||
      b.created_at.localeCompare(a.created_at),
  );

  const all = counts.data ?? [];
  const weekAgo = new Date(Date.now() - 7 * 86_400_000).toISOString();
  const stats = {
    open: all.filter((row) => OPEN_STATUSES.includes(row.status as Status)).length,
    urgent: all.filter(
      (row) => OPEN_STATUSES.includes(row.status as Status) && (row.severity === "blocker" || row.kind === "unsafe"),
    ).length,
    week: all.filter((row) => row.created_at >= weekAgo).length,
    actioned: all.filter((row) => row.status === "actioned").length,
    testers: (testers.data ?? []).length,
  };

  return (
    <Chrome
      active="inbox"
      title="Inbox"
      lede="Everything from the Ask Reece button, newest and nastiest first."
    >
      <div className="stats">
        <div className="stat">
          <b>{stats.open}</b>
          <span>open</span>
        </div>
        <div className={`stat${stats.urgent ? " danger" : ""}`}>
          <b>{stats.urgent}</b>
          <span>blocking / unsafe</span>
        </div>
        <div className="stat">
          <b>{stats.week}</b>
          <span>this week</span>
        </div>
        <div className="stat">
          <b>{stats.actioned}</b>
          <span>actioned</span>
        </div>
        <div className="stat">
          <b>{stats.testers}</b>
          <span>active testers</span>
        </div>
      </div>

      <div className="filters">
        {FILTERS.map((option) => {
          const href = option.value === "open" ? "/" : `/?status=${option.value}`;
          return (
            <Link key={option.value} href={href} className={filter === option.value ? "active" : ""}>
              {option.label}
            </Link>
          );
        })}
      </div>

      {error ? <p className="notice error">Could not load the inbox: {error.message}</p> : null}

      {rows.length === 0 ? (
        <p className="empty">
          Nothing here. When a tester presses <strong>Ask Reece</strong>, it lands in this list
          with their versions, the tab they were on, and their support summary attached.
        </p>
      ) : (
        <ul className="list">
          {rows.map((row) => (
            <li
              key={row.id}
              className={`card${row.severity === "blocker" || row.kind === "unsafe" ? " is-blocker" : ""}`}
            >
              <div className="card-head">
                <span className="badge">
                  {KIND_META[row.kind].emoji} {KIND_META[row.kind].label}
                </span>
                <span className={`badge ${STATUS_META[row.status].tone}`}>
                  {STATUS_META[row.status].label}
                </span>
                {row.severity !== "normal" ? (
                  <span className={`badge ${SEVERITY_META[row.severity].tone}`}>
                    {SEVERITY_META[row.severity].label}
                  </span>
                ) : null}
                <Link href={`/feedback/${row.id}`} className="ref">
                  {row.ref}
                </Link>
                <span className="spacer" />
                <span className="who">{row.tester_name}</span>
                <span className="when" title={row.created_at}>
                  {ago(row.created_at)}
                </span>
              </div>

              <p className="card-body">{row.body}</p>

              {row.intent ? (
                <div className="callout">
                  <p className="eyebrow">They were trying to</p>
                  {row.intent}
                </div>
              ) : null}

              <div className="meta">
                {row.panel_tab ? (
                  <span>
                    Tab <code>{row.panel_tab}</code>
                  </span>
                ) : null}
                {row.openreef_version ? <span>OpenReef {row.openreef_version}</span> : null}
                {row.ha_version ? <span>HA {row.ha_version}</span> : null}
                <span>
                  {row.has_support ? "Support summary ✓" : "No support summary"}
                  {row.has_logs ? " · logs ✓" : ""}
                </span>
              </div>

              <div className="row" style={{ marginTop: 12 }}>
                <Link className="btn small" href={`/feedback/${row.id}`}>
                  Open &amp; triage
                </Link>
                {row.reply ? <span className="who">Replied {ago(row.replied_at)}</span> : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Chrome>
  );
}
