import { Chrome } from "@/app/components/Chrome";
import { createAnnouncement, deleteAnnouncement, publishAnnouncement } from "@/app/actions";
import { requireOwner } from "@/lib/auth";
import { ago } from "@/lib/format";
import { serviceClient } from "@/lib/supabase";
import type { Announcement } from "@/lib/types";

export const dynamic = "force-dynamic";

/*
 * Broadcast.
 *
 * The single highest-leverage thing here for a solo maintainer: one message
 * that reaches every active tester's panel, instead of the same message typed
 * eight times into eight different chat threads.
 *
 * Publishing is a separate action from writing on purpose — this goes to
 * everyone at once and there is no unsend.
 */
export default async function AnnouncementsPage() {
  await requireOwner();
  const supabase = serviceClient();
  const { data } = await supabase
    .from("beta_announcements")
    .select("*")
    .order("created_at", { ascending: false });
  const rows = (data ?? []) as Announcement[];

  return (
    <Chrome
      active="announcements"
      title="Announcements"
      lede="One message to every active tester's panel. Say it once."
    >
      <div className="panel">
        <h2>New announcement</h2>
        <form action={createAnnouncement} className="stack" style={{ marginTop: 12 }}>
          <div>
            <label className="label" htmlFor="title">
              Title
            </label>
            <input
              id="title"
              name="title"
              className="field"
              required
              maxLength={200}
              placeholder="e.g. 0.7.0 is out — please hammer the Dosing tab"
              autoComplete="off"
            />
          </div>
          <div>
            <label className="label" htmlFor="body">
              Message
            </label>
            <textarea
              id="body"
              name="body"
              className="field"
              rows={4}
              required
              maxLength={2000}
              placeholder="What changed, what you want them to try, what to watch out for."
            />
          </div>
          <div className="row">
            <button className="btn primary" type="submit">
              Save as draft
            </button>
            <span style={{ color: "var(--fg-subtle)", fontSize: 12 }}>
              Nothing is sent until you publish it.
            </span>
          </div>
        </form>
      </div>

      {rows.length === 0 ? (
        <p className="empty">No announcements yet.</p>
      ) : (
        <ul className="list">
          {rows.map((row) => (
            <li key={row.id} className="card">
              <div className="card-head">
                <span className={`badge ${row.published_at ? "tone-done" : "tone-seen"}`}>
                  {row.published_at ? "Published" : "Draft"}
                </span>
                <strong>{row.title}</strong>
                <span className="spacer" />
                <span className="when">
                  {row.published_at ? ago(row.published_at) : `written ${ago(row.created_at)}`}
                </span>
              </div>
              <p className="card-body">{row.body}</p>
              <div className="row" style={{ marginTop: 12 }}>
                {row.published_at ? null : (
                  <form action={publishAnnouncement}>
                    <input type="hidden" name="id" value={row.id} />
                    <button className="btn small primary" type="submit">
                      Publish to all testers
                    </button>
                  </form>
                )}
                <form action={deleteAnnouncement}>
                  <input type="hidden" name="id" value={row.id} />
                  <button className="btn small danger" type="submit">
                    Delete
                  </button>
                </form>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Chrome>
  );
}
