import Link from "next/link";
import { Chrome } from "@/app/components/Chrome";
import { createTester, saveTesterNotes, setTesterStatus } from "@/app/actions";
import { requireOwner } from "@/lib/auth";
import { ago } from "@/lib/format";
import { serviceClient } from "@/lib/supabase";
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
      .select("id, email, source, created_at, tester_id")
      .is("tester_id", null)
      .order("created_at", { ascending: false })
      .limit(50),
  ]);

  const counts = new Map<string, number>();
  for (const row of feedback.data ?? []) {
    counts.set(row.tester_id, (counts.get(row.tester_id) ?? 0) + 1);
  }
  const rows = (testers.data ?? []) as Tester[];

  return (
    <Chrome
      active="testers"
      title="Testers"
      lede="Issue a code, send it, they paste it into OpenReef Settings. That's the whole onboarding."
    >
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
