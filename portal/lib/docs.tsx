import fs from "node:fs";
import path from "node:path";
import { marked } from "marked";

/*
 * Renders a markdown document from content/ as a public page.
 *
 * These two pages (/agreement, /privacy) are the only public HTML the portal
 * serves — everything else is the owner's. The markdown is repo-controlled and
 * written by us, so rendering it with marked and no sanitizer is fine: the
 * threat model for sanitization is *user*-supplied markdown, and none of this
 * is.
 *
 * Read with a literal-ish path via process.cwd() so Vercel's file tracing
 * includes content/ in the serverless bundle (belt-and-braces: next.config.ts
 * also lists it in outputFileTracingIncludes).
 */

export function readDoc(name: "beta-agreement" | "privacy-notice"): string {
  const raw = fs.readFileSync(path.join(process.cwd(), "content", `${name}.md`), "utf8");
  return marked.parse(raw, { async: false });
}

export function DocPage({ name }: { name: "beta-agreement" | "privacy-notice" }) {
  return (
    <div className="shell" style={{ maxWidth: 780 }}>
      <div className="panel doc">
        {/* eslint-disable-next-line react/no-danger -- repo-controlled markdown, no user input */}
        <div dangerouslySetInnerHTML={{ __html: readDoc(name) }} />
      </div>
      <p style={{ color: "var(--fg-subtle)", fontSize: 12.5, marginTop: 10 }}>
        Part of the OpenReef beta ·{" "}
        <a href="https://openreef.co.uk">openreef.co.uk</a> ·{" "}
        <a href="https://github.com/TheCarpyVikings/OpenReef">source</a>
      </p>
    </div>
  );
}
