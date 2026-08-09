#!/usr/bin/env node
/*
 * Panel mobile audit — renders the REAL Home Assistant panel at phone, tablet
 * and desktop sizes and measures what a screenshot cannot tell you.
 *
 * Sibling of tools/mobile-audit.mjs, which audits THIS SITE's own sections.
 * This one audits the integration's panel through the /demo/ shim.
 *
 * The /demo/ shim mounts the actual openreef-panel.js against fixtures, so this
 * is a full-panel layout lab, not a per-component stub. It sweeps every tab the
 * panel currently renders (discovered from the DOM, never hard-coded) and per
 * tab reports:
 *
 *   - HORIZONTAL OVERFLOW — anything poking past the viewport, ignoring content
 *     inside a deliberate horizontal scroller like the phone nav rail
 *   - CLIPPED — scrollWidth > clientWidth with overflow visible, i.e. text a
 *     grid column is too narrow to show (how the "Salinity" squeeze was found)
 *   - TINY — sub-32px tap targets, which are below a fingertip
 *   - nav height and where content actually starts, because a menu that pushes
 *     the first card off-screen is the single worst mobile failure
 *
 * Exit code is 1 if anything overflows the viewport horizontally — that is
 * unambiguously a bug. Tap targets and page heights are reported, not enforced:
 * they need judgement.
 *
 * Prereq: a built site, same as demo-smoke.
 *
 *   python3 tools/demo-fixtures.py   # pin the CURRENT panel into public/demo/
 *   pnpm build
 *   pnpm panel:mobile-audit -- --shots /tmp/shots
 *
 * Flags:  --shots <dir>   write <viewport>-<tab>.png and report.json
 *         --only <id>     one viewport (phone | small | tablet | desktop)
 */
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const SITE = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const PORT = 4187;
const arg = (name) => {
  const i = process.argv.indexOf(name);
  return i > -1 ? process.argv[i + 1] : null;
};
const SHOTS = arg("--shots") ? resolve(arg("--shots")) : null;
const ONLY = arg("--only");
if (SHOTS) mkdirSync(SHOTS, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Real devices, not round numbers: these are the sizes the panel is used at.
const VIEWPORTS = [
  { id: "phone", width: 430, height: 932, mobile: true, label: "iPhone 15 Pro Max" },
  { id: "small", width: 390, height: 844, mobile: true, label: "iPhone 14/15" },
  { id: "tablet", width: 1024, height: 1366, mobile: true, label: "iPad Pro 12.9 portrait" },
  { id: "desktop", width: 1440, height: 900, mobile: false, label: "Desktop" },
].filter((v) => !ONLY || v.id === ONLY);

// --- serve dist/ ---------------------------------------------------------- //
// detached, so the whole process GROUP can be killed at the end. Killing the
// npx wrapper alone orphans vite, which then squats the port and makes the next
// run fail silently against --strictPort.
const server = spawn("npx", ["vite", "preview", "--port", String(PORT), "--strictPort"], {
  cwd: SITE,
  stdio: "ignore",
  detached: true,
});
const stopServer = () => {
  try { process.kill(-server.pid); } catch { server.kill(); }
};
let up = false;
for (let i = 0; i < 60 && !up; i++) {
  await sleep(250);
  up = await fetch(`http://localhost:${PORT}/demo/`).then((r) => r.ok).catch(() => false);
}
if (!up) {
  stopServer();
  console.error(`FAIL: preview server never came up on ${PORT} (did you run \`pnpm build\`?)`);
  process.exit(1);
}

// --- the measurement, run inside the page --------------------------------- //
const MEASURE = () => {
  const root = document.querySelector("openreef-panel")?.shadowRoot;
  if (!root) return { error: "panel has no shadow root" };
  const vw = window.innerWidth;
  const label = (el) => {
    const cls = (el.getAttribute("class") || "").split(/\s+/).filter(Boolean).slice(0, 3).join(".");
    return `${el.tagName.toLowerCase()}${cls ? "." + cls : ""}`;
  };
  const visible = [...root.querySelectorAll("*")].filter((el) => {
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden" || Number(cs.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  });
  // Content parked off-screen inside a horizontal scroller is the design, not a bug.
  const inScroller = (el) => {
    for (let p = el.parentElement; p && p !== root; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === "auto" || ox === "scroll") return true;
    }
    return false;
  };
  const overflow = [];
  const clipped = [];
  const tiny = [];
  for (const el of visible) {
    const r = el.getBoundingClientRect();
    if ((r.right > vw + 1 || r.left < -1) && !inScroller(el)) {
      // Outermost offender only — a wide parent drags all its children along.
      if (!overflow.some((o) => o.el.contains(el))) {
        overflow.push({ el, sel: label(el), left: Math.round(r.left), right: Math.round(r.right) });
      }
    }
    if (el.scrollWidth > el.clientWidth + 2 && getComputedStyle(el).overflowX === "visible") {
      clipped.push({ sel: label(el), scroll: el.scrollWidth, client: el.clientWidth });
    }
    if ((el.tagName === "BUTTON" || el.getAttribute("data-action")) && (r.height < 32 || r.width < 32)) {
      tiny.push({ sel: label(el), w: Math.round(r.width), h: Math.round(r.height) });
    }
  }
  const nav = root.querySelector(".tabs")?.getBoundingClientRect();
  return {
    vw,
    docScrollWidth: document.documentElement.scrollWidth,
    pageScrollHeight: root.querySelector(".page")?.scrollHeight ?? 0,
    navHeight: nav ? Math.round(nav.height) : 0,
    contentStartsAt: nav ? Math.round(nav.bottom) : 0,
    overflow: overflow.map(({ sel, left, right }) => ({ sel, left, right })).slice(0, 12),
    clipped: clipped.slice(0, 12),
    tiny: tiny.slice(0, 12),
  };
};

// --- sweep ---------------------------------------------------------------- //
const report = {};
const failures = [];
const browser = await puppeteer.launch({
  executablePath: process.env.CHROME || "/usr/bin/google-chrome",
  headless: "new",
  args: ["--no-sandbox", "--enable-unsafe-swiftshader"],
});
try {
  for (const vp of VIEWPORTS) {
    const page = await browser.newPage();
    await page.setViewport({
      width: vp.width, height: vp.height, deviceScaleFactor: 1,
      isMobile: vp.mobile, hasTouch: vp.mobile,
    });
    await page.evaluateOnNewDocument(() => localStorage.setItem("openreef:demo:opener", "1"));
    const pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(String(e.message)));
    await page.goto(`http://localhost:${PORT}/demo/`, { waitUntil: "domcontentloaded" });
    const ready = await page.waitForSelector('.demo-host[data-ready="true"]', { timeout: 25000 })
      .then(() => true).catch(() => false);
    if (!ready) {
      failures.push(`${vp.id}: demo never reached ready state`);
      await page.close();
      continue;
    }
    await sleep(1600);

    const tabIds = await page.evaluate(() => [...new Set(
      [...(document.querySelector("openreef-panel")?.shadowRoot
        ?.querySelectorAll('[data-action="tab"][data-id]') ?? [])]
        .map((el) => el.getAttribute("data-id")))]);

    report[vp.id] = { label: vp.label, size: `${vp.width}x${vp.height}`, tabs: {} };
    for (const id of tabIds) {
      await page.evaluate((t) => {
        const root = document.querySelector("openreef-panel")?.shadowRoot;
        root?.querySelector(`[data-action="tab"][data-id="${t}"]`)?.click();
      }, id);
      await sleep(750);
      const m = await page.evaluate(MEASURE);
      report[vp.id].tabs[id] = m;
      if (m.overflow?.length) {
        failures.push(`${vp.id}/${id}: ${m.overflow.map((o) => `${o.sel} spans ${o.left}..${o.right} past ${m.vw}`).join("; ")}`);
      }
      if (m.docScrollWidth > m.vw + 1) {
        failures.push(`${vp.id}/${id}: page scrolls horizontally (${m.docScrollWidth} > ${m.vw})`);
      }
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/${vp.id}-${id}.png` });
    }
    if (pageErrors.length) failures.push(`${vp.id}: ${pageErrors.join(" | ")}`);
    await page.close();
  }
} finally {
  await browser.close();
  stopServer();
}
if (SHOTS) writeFileSync(`${SHOTS}/report.json`, JSON.stringify(report, null, 2));

// --- report --------------------------------------------------------------- //
for (const [vid, v] of Object.entries(report)) {
  console.log(`\n=== ${vid}  ${v.label} (${v.size}) ===`);
  for (const [tab, m] of Object.entries(v.tabs)) {
    const notes = [];
    if (m.overflow?.length) notes.push(`OVERFLOW ${m.overflow.map((o) => o.sel).join(", ")}`);
    if (m.clipped?.length) notes.push(`CLIPPED ${m.clipped.map((c) => `${c.sel}(${c.scroll}>${c.client})`).join(", ")}`);
    if (m.tiny?.length) notes.push(`TINY ${m.tiny.map((t) => `${t.sel}(${t.w}x${t.h})`).join(", ")}`);
    console.log(
      `  ${tab.padEnd(12)} nav=${String(m.navHeight).padStart(4)}px` +
      `  content@${String(m.contentStartsAt).padStart(4)}` +
      `  height=${m.pageScrollHeight}` +
      (notes.length ? `  ${notes.join(" | ")}` : ""),
    );
  }
}

if (failures.length) {
  console.error(`\nMOBILE AUDIT: FAIL (${failures.length})`);
  for (const f of failures) console.error(`  ✗ ${f}`);
  process.exit(1);
}
console.log("\nMOBILE AUDIT: PASS — nothing overflows the viewport at any size.");
console.log("Tap targets and page heights above are advisory: read them, do not gate on them.");
