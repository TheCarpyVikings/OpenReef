import { useState } from "react";
import { FEATURES, GITHUB_URL } from "../copy";

export interface DeepDiveContent {
  slug: string;
  h1: string;
  lede: string;
  buddyLine: string;
  buddyPose: string;
  img: string;
  imgAlt: string;
  /** When the feature is playable in /demo/, a third CTA button appears. */
  demoLabel?: string;
  sections: Array<{ heading: string; paragraphs: string[]; list?: string[]; snippet?: string }>;
  limits: string[];
  faq: Array<{ q: string; a: string }>;
}

export default function DeepDive({ c }: { c: DeepDiveContent }) {
  const [artOk, setArtOk] = useState(true);
  const [zoom, setZoom] = useState(false);
  const [imgOk, setImgOk] = useState(true);
  const faqLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: c.faq.map((f) => ({
      "@type": "Question",
      name: f.q,
      acceptedAnswer: { "@type": "Answer", text: f.a },
    })),
  };
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
          <a href="/features/">Deep dives</a>
          <a href="/demo/">Live demo</a>
          <a href={GITHUB_URL}>GitHub</a>
          <a className="btn btn-primary btn-small" href="/#cta">
            Join the beta
          </a>
        </div>
      </nav>
      <main className="dd">
        <article>
          <h1>{c.h1}</h1>
          <p className="dd-lede">{c.lede}</p>

          <aside className="buddy-inline">
            <span className="buddy-inline-face">
              {artOk ? (
                <img src={`/avatar/${c.buddyPose}.png`} alt="" onError={() => setArtOk(false)} />
              ) : (
                "🪸"
              )}
            </span>
            <p>{c.buddyLine}</p>
          </aside>

          {imgOk && (
            <button className="dd-shot" onClick={() => setZoom(true)} aria-label="Enlarge screenshot">
              <img src={c.img} alt={c.imgAlt} onError={() => setImgOk(false)} />
            </button>
          )}

          {c.sections.map((s) => (
            <section key={s.heading}>
              <h2>{s.heading}</h2>
              {s.paragraphs.map((p, i) => (
                <p key={i}>{p}</p>
              ))}
              {s.list && (
                <ul>
                  {s.list.map((li, i) => (
                    <li key={i}>{li}</li>
                  ))}
                </ul>
              )}
              {s.snippet && <pre className="code-snippet">{s.snippet}</pre>}
            </section>
          ))}

          <section className="dd-limits">
            <h2>The honest bit</h2>
            <ul>
              {c.limits.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
          </section>

          <section>
            <h2>Questions reefers actually ask</h2>
            {c.faq.map((f) => (
              <details key={f.q} className="dd-faq">
                <summary>{f.q}</summary>
                <p>{f.a}</p>
              </details>
            ))}
          </section>

          <section className="dd-siblings">
            <h2>More deep dives</h2>
            <nav>
              {FEATURES.filter((f) => f.href && f.href !== `/features/${c.slug}/`).map((f) => (
                <a key={f.href} href={f.href}>
                  {f.title} →
                </a>
              ))}
              <a href="/demo/">Or just play with the live demo →</a>
            </nav>
          </section>

          <section className="dd-cta">
            <h2>Try it on your tank.</h2>
            <p>
              OpenReef is free, open source, and in private beta. Keep your Apex — give it a brain.
            </p>
            <a className="btn btn-primary" href="/#cta">
              Join the beta
            </a>
            {c.demoLabel && (
              <a className="btn btn-ghost" href="/demo/">
                {c.demoLabel}
              </a>
            )}
            <a className="btn btn-ghost" href={GITHUB_URL}>
              Read the source
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
      {zoom && (
        <div className="lightbox" role="dialog" aria-modal="true" onClick={() => setZoom(false)}>
          <figure onClick={(e) => e.stopPropagation()}>
            <img src={c.img} alt={c.imgAlt} />
            <figcaption>
              {c.imgAlt}
              <button onClick={() => setZoom(false)} aria-label="Close">
                ×
              </button>
            </figcaption>
          </figure>
        </div>
      )}
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(faqLd) }} />
    </>
  );
}
