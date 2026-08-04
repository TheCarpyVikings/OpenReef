import { createRoot } from "react-dom/client";
import { FEATURES, GITHUB_URL } from "../copy";
import "../styles.css";
import "./deepdive.css";

/*
 * /features/ — the deep-dive hub. One canonical page that lists every feature
 * deep dive, so nobody has to swim the whole 3D journey to find the reading.
 */

const DIVES = FEATURES.filter((f) => f.href);

function Hub() {
  return (
    <>
      <div className="static-bg" />
      <nav className="topnav">
        <a className="topnav-brand" href="/">
          <img src="/logo.png" alt="" /> OpenReef
        </a>
        <div className="topnav-links">
          <a className="dd-back" href="/">
            ← The dive
          </a>
          <a href="/demo/">Live demo</a>
          <a href={GITHUB_URL}>GitHub</a>
          <a className="btn btn-primary btn-small" href="/#cta">
            Join the beta
          </a>
        </div>
      </nav>
      <main className="dd dd-hub">
        <article>
          <h1>The deep dives</h1>
          <p className="dd-lede">
            Every big OpenReef feature, explained properly: how it works, what it costs elsewhere,
            and the honest limits. All screenshots are the current Home Assistant integration.
          </p>

          <a className="hub-demo-callout" href="/demo/">
            <strong>Prefer to click things?</strong>
            <span>
              The live demo runs the real panel on a simulated tank — every feature below, in your
              browser, nothing to install. →
            </span>
          </a>

          <div className="features-grid hub-grid">
            {DIVES.map((f) => (
              <a key={f.title} className="feature hub-card" href={f.href}>
                {f.img && <img src={f.img} alt={`${f.title} screenshot`} loading="lazy" />}
                <h3>{f.title}</h3>
                <p>{f.body}</p>
                <span className="feature-more">Deep dive →</span>
              </a>
            ))}
          </div>

          <section className="dd-cta">
            <h2>Try it on your tank.</h2>
            <p>
              OpenReef is free, open source, and in private beta. Keep your Apex — give it a brain.
            </p>
            <a className="btn btn-primary" href="/#cta">
              Join the beta
            </a>
            <a className="btn btn-ghost" href="/demo/">
              Play with the demo
            </a>
          </section>

          <footer className="dd-footer">
            <p>
              Built in the open by one reefer and a soldering iron. © 2026 OpenReef ·{" "}
              <a href="/">Back to the dive</a>
            </p>
          </footer>
        </article>
      </main>
    </>
  );
}

createRoot(document.getElementById("root")!).render(<Hub />);
