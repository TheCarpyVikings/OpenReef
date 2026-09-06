/*
 * Region capture shared by tools/demo-shots.mjs (the showroom) and
 * tools/capture-demos.mjs (a real tank): given a puppeteer page with the
 * OpenReef panel mounted, screenshot every titled panel in the current page's
 * content stack into <dir>/<n>-<slug>.png plus <dir>/full.png, and write a
 * manifest. Both harnesses produce identical file names, so the site's feature
 * pages can reference /demos/<page>/<n>-<slug>.png whichever tank took them.
 */
import { mkdirSync, rmSync, writeFileSync } from "node:fs";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const slug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 32) || "panel";

// Region name: a stable class-based name for the layout grids, else the heading.
const nameFor = (cls, heading) => {
  if (/\bsummary-grid\b/.test(cls)) return "summary";
  if (/\bdosing-grid\b/.test(cls)) return "channels";
  if (/\bgrid\b.*\bfour\b/.test(cls)) return "tasks";
  return slug(heading);
};

/** The panel's shadow root, wherever the panel is mounted (HA or the demo). */
const ROOT = `(() => { const p = document.querySelector("openreef-panel"); return p && (p.shadowRoot || p); })()`;

export async function captureRegions(page, dir, { hideSelector = null } = {}) {
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  if (hideSelector) await page.evaluate((sel) => document.querySelectorAll(sel).forEach((el) => (el.style.visibility = "hidden")), hideSelector);

  const panel = await page.$("openreef-panel");
  await panel.screenshot({ path: `${dir}/full.png` });

  const list = await page.evaluate(`(() => {
    const root = ${ROOT}; if (!root) return [];
    const main = root.querySelector("main") || root;
    const stack = main.querySelector("section.stack") || main;
    return [...stack.children].map((el, i) => ({
      i, cls: String(el.className), h: el.getBoundingClientRect().height,
      heading: (el.querySelector("h1,h2,h3,h4,.eyebrow,strong")?.textContent || "").trim().slice(0, 60),
    })).filter((r) => r.h >= 120);
  })()`);

  const manifest = [];
  let n = 0;
  for (const r of list) {
    n += 1;
    const file = `${n}-${nameFor(r.cls, r.heading)}.png`;
    // Fresh handle per region, with one retry: the panel re-renders on its
    // live tick and a handle taken earlier can detach between lookup and shot.
    let ok = false;
    for (let attempt = 0; attempt < 2 && !ok; attempt++) {
      const handle = await page.evaluateHandle(`(() => {
        const root = ${ROOT}; const main = root.querySelector("main") || root;
        const stack = main.querySelector("section.stack") || main; return stack.children[${r.i}];
      })()`);
      const el = handle.asElement();
      try {
        if (el && (await el.boundingBox())) { await el.screenshot({ path: `${dir}/${file}` }); ok = true; }
      } catch { /* detached mid-shot — retry once */ }
      if (!ok) await sleep(300);
    }
    if (ok) manifest.push({ file, heading: r.heading, height: Math.round(r.h) });
  }
  if (hideSelector) await page.evaluate((sel) => document.querySelectorAll(sel).forEach((el) => (el.style.visibility = "")), hideSelector);
  writeFileSync(`${dir}/manifest.json`, JSON.stringify(manifest, null, 1));
  return manifest;
}

/** Navigate the Helm: open the group, then the page (a hub is its own page). */
export async function openPage(page, group, id, click) {
  await click(group); await sleep(500);
  if (id !== group) await click(id);
  await sleep(1400);
}
