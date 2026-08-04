import Link from "next/link";
import { Chrome } from "@/app/components/Chrome";
import { createTester, saveTesterNotes, setTesterStatus } from "@/app/actions";
import { requireOwner } from "@/lib/auth";
import { ago } from "@/lib/format";
import { serviceClient } from "@/lib/supabase";
import { attentionFor, byUrgency, LEVEL_TONE, type Attention } from "@/lib/attention";
import type { Tester } from "@/lib/types";

export const dynamic = "force-dynamic";

const STATUS_TONE: Record<string, string> = {
  invited: "tone-new",
  active: "tone-done",
  paused: "tone-work",
  revoked: "tone-closed",
};

/*
 * The roster.
 *
 * Adding someone mints an invite code. That code is the whole onboarding
 * story — you send it, they paste it into OpenReef Settings, done. No account,
 * no password, nothing for them to lose.
 */
export default async function TestersPage() {
  await requireOwner();
  const supabase = serviceClient();

  const [testers, feedback, signups] = await Promise.all([
    supabase.from("beta_testers").select("*").order("created_at", { ascending: false }),
    supabase.from("beta_feedback").select("tester_id"),
    supabase
      .from("beta_signups")
      .select("id, email, source, note, created_at, tester_id")
      .is("tester_id", null)
      .order("created_at", { ascending: false })
      .limit(50),
  ]);

  const counts = new Map<string, number>();
  for (const row of feedback.data ?? []) {
    counts.set(row.tester_id, (counts.get(row.tester_id) ?? 0) + 1);
  }
  const rows = (testers.data ?? []) as Tester[];

  // One clock for the whole render, so two rows can never disagree about how
  // long ago something was.
  const now = Date.now();
  const needsAttention = rows
    .map((tester) => ({ tester, attention: attentionFor(tester, counts.get(tester.id) ?? 0, now) }))
    .filter((entry): entry is { tester: Tester; attention: Attention } => entry.attention !== null)
    .sort((a, b) => byUrgency(a.attention, b.attention));

  return (
    <Chrome
      active="testers"
      title="Testers"
      lede="Issue a code, send it, they paste it into OpenReef Settings. That's the whole onboarding."
    >
      {needsAttention.length > 0 ? (
        <div className="panel" style={{ borderColor: "var(--border-2)" }}>
          <h2>Needs a nudge</h2>
          <p style={{ color: "var(--fg-muted)", marginTop: 4, fontSize: 13.5 }}>
            The install checks in every 30 minutes on its own, so silence here isn&apos;t
            someone being busy — it&apos;s something being wrong.
          </p>
          <ul className="list" style={{ marginTop: 12 }}>
            {needsAttention.map(({ tester, attention }) => (
              <li key={tester.id} className="card" style={{ padding: "12px 14px" }}>
                <div className="card-head" style={{ marginBottom: 4 }}>
                  <span className={`badge ${LEVEL_TONE[attention.level]}`}>{attention.label}</span>
                  <strong>{tester.name}</strong>
                  {tester.email ? <span className="who">{tester.email}</span> : null}
                  <span className="spacer" />
                  <span className="when">last check-in {ago(tester.last_seen_at)}</span>
                </div>
                <p style={{ margin: 0, fontSize: 13.5, color: "var(--fg-muted)" }}>{attention.why}</p>
              </li>
            ))}
          </ul>
        </div>
      ) : rows.length > 0 ? (
        <div className="panel">
          <h2>Everyone&apos;s fine</h2>
          <p style={{ color: "var(--fg-muted)", marginTop: 4, fontSize: 13.5 }}>
            Every active tester is checked in, set up, and nothing is flagged.
          </p>
        </div>
      ) : null}

      <div className="panel">
        <h2>Invite someone</h2>
        <form action={createTester} className="row" style={{ marginTop: 12, alignItems: "flex-end" }}>
          <div style={{ flex: "1 1 200px" }}>
            <label className="label" htmlFor="name">
              Name
            </label>
            <input id="name" name="name" className="field" required autoComplete="off" />
          </div>
          <div style={{ flex: "1 1 220px" }}>
            <label className="label" htmlFor="email">
              Email (optional)
            </label>
            <input id="email" name="email" className="field" type="email" autoComplete="off" />
          </div>
          <button className="btn primary" type="submit">
            Generate code
          </button>
        </form>
      </div>

      {rows.length === 0 ? (
        <p className="empty">No testers yet. Invite the first one above.</p>
      ) : (
        <div className="panel">
          <h2>Roster</h2>
          <div style={{ overflowX: "auto" }}>
            <table style={{ marginTop: 12 }}>
              <thead>
                <tr>
                  <th>Tester</th>
                  <th>Code</th>
                  <th>Status</th>
                  <th>Setup</th>
                  <th>Trust</th>
                  <th>Versions</th>
                  <th>Last seen</th>
                  <th>Feedback</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((tester) => (
                  <tr key={tester.id}>
                    <td>
                      <strong>{tester.name}</strong>
                      {tester.email ? (
                        <div className="who" style={{ fontSize: 12 }}>
                          {tester.email}
                        </div>
                      ) : null}
                    </td>
                    <td>
                      <code>{tester.code}</code>
                    </td>
                    <td>
                      <span className={`badge ${STATUS_TONE[tester.status] ?? "tone-seen"}`}>
                        {tester.status}
                      </span>
                    </td>
                    <td>
                      {tester.setup_complete === null ? (
                        <span className="who">—</span>
                      ) : tester.setup_complete ? (
                        <>
                          <span className="badge tone-done">done</span>
                          {typeof tester.equipment_armed === "number" ? (
                            <div className="who" style={{ fontSize: 12, marginTop: 3 }}>
                              {tester.equipment_armed} armed
                            </div>
                          ) : null}
                        </>
                      ) : (
                        <>
                          <span className="badge tone-work">unfinished</span>
                          {typeof tester.sensors_mapped === "number" &&
                          typeof tester.sensors_enabled === "number" ? (
                            <div className="who" style={{ fontSize: 12, marginTop: 3 }}>
                              {tester.sensors_mapped}/{tester.sensors_enabled} probes
                            </div>
                          ) : null}
                        </>
                      )}
                    </td>
                    <td>
                      {tester.trust_status && tester.trust_status !== "unknown" ? (
                        <>
                          <span
                            className={`badge ${
                              tester.trust_status === "ok"
                                ? "tone-done"
                                : tester.trust_status === "warning"
                                  ? "tone-work"
                                  : "tone-danger"
                            }`}
                          >
                            {tester.trust_status}
                          </span>
                          {/* Core only recomputes Trust Check when the panel is
                              opened, so say how old the reading is rather than
                              implying it's live. */}
                          <div className="who" style={{ fontSize: 12, marginTop: 3 }}>
                            {ago(tester.trust_checked_at)}
                          </div>
                        </>
                      ) : (
                        <span className="who">—</span>
                      )}
                    </td>
                    <td className="who">
                      {tester.openreef_version ? `OR ${tester.openreef_version}` : "—"}
                      {tester.ha_version ? (
                        <div style={{ fontSize: 12 }}>HA {tester.ha_version}</div>
                      ) : null}
                    </td>
                    <td className="when">{ago(tester.last_seen_at)}</td>
                    <td>
                      {counts.get(tester.id) ? (
                        <Link href={`/?status=all&tester=${tester.id}`}>{counts.get(tester.id)}</Link>
                      ) : (
                        <span className="who">0</span>
                      )}
                    </td>
                    <td>
                      <div className="row" style={{ gap: 6 }}>
                        {tester.status !== "revoked" ? (
                          <form action={setTesterStatus}>
                            <input type="hidden" name="id" value={tester.id} />
                            <input
                              type="hidden"
                              name="status"
                              value={tester.status === "paused" ? "active" : "paused"}
                            />
                            <button className="btn small" type="submit">
                              {tester.status === "paused" ? "Resume" : "Pause"}
                            </button>
                          </form>
                        ) : null}
                        <form action={setTesterStatus}>
                          <input type="hidden" name="id" value={tester.id} />
                          <input
                            type="hidden"
                            name="status"
                            value={tester.status === "revoked" ? "invited" : "revoked"}
                          />
                          <button className="btn small danger" type="submit">
                            {tester.status === "revoked" ? "Restore" : "Revoke"}
                          </button>
                        </form>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p style={{ color: "var(--fg-subtle)", fontSize: 12, marginTop: 12 }}>
            Revoking clears the install&apos;s token, so it stops talking to the portal on its
            very next request — not at some later cleanup. Restoring issues a fresh code
            redemption; they&apos;ll need to paste the code again.
          </p>
        </div>
      )}

      {rows.length > 0 ? (
        <div className="panel">
          <h2>Private notes</h2>
          <div className="grid-2" style={{ marginTop: 12 }}>
            {rows.map((tester) => (
              <form action={saveTesterNotes} key={tester.id}>
                <input type="hidden" name="id" value={tester.id} />
                <label className="label" htmlFor={`notes-${tester.id}`}>
                  {tester.name}
                </label>
                <textarea
                  id={`notes-${tester.id}`}
                  name="notes"
                  className="field"
                  rows={2}
                  defaultValue={tester.notes ?? ""}
                  placeholder="Tank, hardware, what they're good at breaking…"
                />
                <button className="btn small" type="submit" style={{ marginTop: 8 }}>
                  Save
                </button>
              </form>
            ))}
          </div>
        </div>
      ) : null}

      <div className="panel">
        <h2>Waiting list</h2>
        <p style={{ color: "var(--fg-muted)", marginTop: 4, fontSize: 13.5 }}>
          Signups from openreef.co.uk that haven&apos;t been invited yet. Point the site&apos;s
          form at <code>/api/signup</code> to fill this.
        </p>
        {(signups.data ?? []).length === 0 ? (
          <p className="empty" style={{ marginTop: 12 }}>
            Nobody waiting.
          </p>
        ) : (
          <table style={{ marginTop: 12 }}>
            <tbody>
              {(signups.data ?? []).map((signup) => (
                <tr key={signup.id}>
                  <td>{signup.email}</td>
                  <td>
                    {/* What they ticked on the site. Someone who asked for a beta
                        seat is a candidate; someone who only wants the manual is
                        not, and inviting them is a favour neither of you wanted. */}
                    {(signup.note ?? "")
                      .split(",")
                      .map((part: string) => part.trim())
                      .filter(Boolean)
                      .map((interest: string) => (
                        <span
                          key={interest}
                          className={`badge ${interest === "beta" ? "tone-new" : "tone-seen"}`}
                          style={{ marginRight: 4 }}
                        >
                          {interest}
                        </span>
                      ))}
                  </td>
                  <td className="who">{signup.source}</td>
                  <td className="when">{ago(signup.created_at)}</td>
                  <td>
                    <form action={createTester} className="row" style={{ gap: 6 }}>
                      <input type="hidden" name="signup_id" value={signup.id} />
                      <input type="hidden" name="email" value={signup.email} />
                      <input
                        name="name"
                        className="field"
                        style={{ width: 150 }}
                        placeholder="Their name"
                        required
                        autoComplete="off"
                      />
                      <button className="btn small primary" type="submit">
                        Invite
                      </button>
                    </form>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Chrome>
  );
}
