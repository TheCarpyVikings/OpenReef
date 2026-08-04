import Link from "next/link";
import { notFound } from "next/navigation";
import { Chrome } from "@/app/components/Chrome";
import { saveOwnerNote, setStatus } from "@/app/actions";
import { requireOwner } from "@/lib/auth";
import { ago } from "@/lib/format";
import { serviceClient } from "@/lib/supabase";
import {
  KIND_META,
  SEVERITY_META,
  STATUSES,
  STATUS_META,
  type FeedbackDetail,
} from "@/lib/types";

export const dynamic = "force-dynamic";

/*
 * One report, everything known about it, and the triage controls.
 *
 * The status move and the tester-facing reply are a single form: one submit,
 * one write, so "actioned" and "here's what I did" can never disagree. The
 * private note is a separate form because it is a different audience — that
 * one never leaves the portal.
 */
export default async function FeedbackDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  await requireOwner();
  const { id } = await params;
  const supabase = serviceClient();

  const [{ data, error }, events] = await Promise.all([
    supabase
      .from("beta_feedback")
      .select("*, beta_testers(id, name, email, status, install_id, notes)")
      .eq("id", id)
      .maybeSingle(),
    supabase
      .from("beta_feedback_events")
      .select("event, detail, created_at")
      .eq("feedback_id", id)
      .order("created_at", { ascending: false })
      .limit(20),
  ]);

  if (error || !data) notFound();

  const row = data as unknown as FeedbackDetail & {
    beta_testers: { id: string; name: string; email: string | null; status: string; install_id: string | null; notes: string | null };
  };
  const tester = row.beta_testers;

  // Sibling reports from the same tab: the fastest way to spot "these three
  // tickets are one bug" before writing three replies. Skipped entirely when
  // there's no tab recorded — matching on "" would group every context-less
  // report into one meaningless pile.
  const related = row.panel_tab
    ? (
        await supabase
          .from("beta_inbox")
          .select("id, ref, body, status, created_at")
          .eq("panel_tab", row.panel_tab)
          .neq("id", row.id)
          .order("created_at", { ascending: false })
          .limit(5)
      ).data
    : null;

  return (
    <Chrome active="inbox" title={row.ref} lede={`From ${tester.name} · ${ago(row.created_at)}`}>
      <p style={{ marginBottom: 14 }}>
        <Link href="/">← Back to inbox</Link>
      </p>

      <div className="panel">
        <div className="card-head">
          <span className="badge">
            {KIND_META[row.kind].emoji} {KIND_META[row.kind].label}
          </span>
          <span className={`badge ${STATUS_META[row.status].tone}`}>
            {STATUS_META[row.status].label}
          </span>
          <span className={`badge ${SEVERITY_META[row.severity].tone}`}>
            {SEVERITY_META[row.severity].label}
          </span>
          <span className="spacer" />
          <span className="when" title={row.created_at}>
            {new Date(row.created_at).toISOString().replace("T", " ").slice(0, 16)}
          </span>
        </div>

        <p className="card-body" style={{ fontSize: 15 }}>
          {row.body}
        </p>

        {row.intent ? (
          <div className="callout">
            <p className="eyebrow">They were trying to</p>
            {row.intent}
          </div>
        ) : null}

        <div className="meta">
          <span>
            Tester <Link href={`/?tester=${tester.id}`}>{tester.name}</Link>
            {tester.email ? ` · ${tester.email}` : ""}
          </span>
          {row.panel_tab ? (
            <span>
              Tab <code>{row.panel_tab}</code>
            </span>
          ) : null}
          <span>OpenReef {row.openreef_version ?? "unknown"}</span>
          <span>Home Assistant {row.ha_version ?? "unknown"}</span>
          {tester.install_id ? (
            <span>
              Install <code>{tester.install_id.slice(0, 12)}</code>
            </span>
          ) : null}
          {row.user_agent ? <span style={{ gridColumn: "1 / -1" }}>{row.user_agent}</span> : null}
        </div>
      </div>

      {/* --- triage --- */}
      <div className="panel">
        <h2>Triage</h2>
        <form action={setStatus} className="stack" style={{ marginTop: 14 }}>
          <input type="hidden" name="id" value={row.id} />

          <div>
            <label className="label" htmlFor="status">
              Status
            </label>
            <select id="status" name="status" className="field" defaultValue={row.status}>
              {STATUSES.map((status) => (
                <option key={status} value={status}>
                  {STATUS_META[status].label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="label" htmlFor="duplicate_of">
              Duplicate of <span style={{ textTransform: "none", letterSpacing: 0 }}>(only when status is Duplicate)</span>
            </label>
            <input
              id="duplicate_of"
              name="duplicate_of"
              className="field"
              placeholder="e.g. OR-0012"
              autoComplete="off"
            />
          </div>

          <div>
            <label className="label" htmlFor="reply">
              Reply to the tester
            </label>
            <textarea
              id="reply"
              name="reply"
              className="field"
              rows={3}
              defaultValue={row.reply ?? ""}
              placeholder="What you did, or why you're not doing it. They see this in their panel and get a Home Assistant notification."
            />
            <p style={{ color: "var(--fg-subtle)", fontSize: 12, marginTop: 6 }}>
              Leave blank to change status silently. Anything typed here is sent
              to the tester on their install&apos;s next sync (within 30 minutes).
            </p>
          </div>

          <div className="row">
            <button className="btn primary" type="submit">
              Save &amp; notify
            </button>
            {row.replied_at ? <span className="who">Last replied {ago(row.replied_at)}</span> : null}
          </div>
        </form>

        <div className="sep" />

        <form action={saveOwnerNote}>
          <input type="hidden" name="id" value={row.id} />
          <label className="label" htmlFor="owner_note">
            Private note — never sent
          </label>
          <textarea
            id="owner_note"
            name="owner_note"
            className="field"
            rows={2}
            defaultValue={row.owner_note ?? ""}
            placeholder="What you actually think, where the bug probably is, what to check…"
          />
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn small" type="submit">
              Save note
            </button>
          </div>
        </form>
      </div>

      {/* --- diagnostics --- */}
      {row.support_summary ? (
        <details className="panel">
          <summary style={{ cursor: "pointer", fontWeight: 700 }}>Support summary</summary>
          <pre className="dump">{row.support_summary}</pre>
        </details>
      ) : (
        <div className="panel">
          <p style={{ color: "var(--fg-muted)" }}>
            No support summary — this tester has that sharing toggle off, so
            versions and the tab above are all the context there is.
          </p>
        </div>
      )}

      {row.log_tail ? (
        <details className="panel">
          <summary style={{ cursor: "pointer", fontWeight: 700 }}>Home Assistant log (OpenReef lines)</summary>
          <pre className="dump">{row.log_tail}</pre>
        </details>
      ) : null}

      {related && related.length > 0 ? (
        <div className="panel">
          <h2>Others from the same tab</h2>
          <ul className="list" style={{ marginTop: 12 }}>
            {related.map((item) => (
              <li key={item.id} className="card" style={{ padding: "11px 13px" }}>
                <div className="card-head" style={{ marginBottom: 5 }}>
                  <Link href={`/feedback/${item.id}`} className="ref">
                    {item.ref}
                  </Link>
                  <span className="spacer" />
                  <span className="when">{ago(item.created_at)}</span>
                </div>
                <p className="card-body" style={{ fontSize: 13 }}>
                  {item.body.slice(0, 180)}
                  {item.body.length > 180 ? "…" : ""}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {events.data && events.data.length > 0 ? (
        <div className="panel">
          <h2>History</h2>
          <table style={{ marginTop: 10 }}>
            <tbody>
              {events.data.map((event, index) => (
                <tr key={index}>
                  <td style={{ width: 110 }} className="when">
                    {ago(event.created_at)}
                  </td>
                  <td style={{ width: 110 }}>
                    <span className="badge">{event.event}</span>
                  </td>
                  <td>{event.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </Chrome>
  );
}
