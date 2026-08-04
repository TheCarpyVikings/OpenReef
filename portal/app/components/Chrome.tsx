import Link from "next/link";
import { signOut } from "@/app/actions";

/** Shared page frame. Server component — the nav has no state beyond which
 *  route is active, so there is nothing here worth shipping to the browser. */
export function Chrome({
  active,
  title,
  lede,
  children,
}: {
  active: "inbox" | "testers" | "announcements";
  title: string;
  lede?: string;
  children: React.ReactNode;
}) {
  const tabs = [
    { id: "inbox", href: "/", label: "Inbox" },
    { id: "testers", href: "/testers", label: "Testers" },
    { id: "announcements", href: "/announcements", label: "Announcements" },
  ] as const;

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">OpenReef beta portal</p>
          <h1>{title}</h1>
          {lede ? <p style={{ color: "var(--fg-muted)", marginTop: 4 }}>{lede}</p> : null}
        </div>
        <div className="row">
          <nav className="nav">
            {tabs.map((tab) => (
              <Link key={tab.id} href={tab.href} className={active === tab.id ? "active" : ""}>
                {tab.label}
              </Link>
            ))}
          </nav>
          <form action={signOut}>
            <button className="btn small" type="submit">
              Sign out
            </button>
          </form>
        </div>
      </header>
      {children}
    </div>
  );
}
