#!/usr/bin/env node
/*
 * Demo smoke test — the verification gate of `pnpm demo:refresh`.
 *
 * Serves the built site, opens /demo/ headless, waits for the real panel to
 * mount against the shim, then clicks through EVERY tab the panel currently
 * renders. Fails (exit 1) on any of:
 *
 *   - the demo never reaches ready state
 *   - a page error / console error during mount or the tab sweep
 *   - any openreef/* command the shim couldn't answer (window.__demoUnrouted)
 *     — the tab sweep presses nothing but tabs, so anything unrouted is a read
 *     the panel now performs that the fixtures don't carry: demo drift.
 *
 * The tab list is discovered from the live DOM, not hard-coded, so a new tab
 * in the panel is automatically part of the sweep.
 *
 * Usage:  node tools/demo-smoke.mjs [--shots <dir>]
 * Requires a prior `vite build` (serves dist/ via `vite preview`).
 */
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const SITE = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const PORT = 4181;
const shotsIdx = process.argv.indexOf("--shots");
const SHOTS = shotsIdx > -1 ? resolve(process.argv[shotsIdx + 1]) : null;
if (SHOTS) mkdirSync(SHOTS, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// --- serve dist/ ---------------------------------------------------------- //
// detached, so the whole process GROUP can be killed at the end. Killing the
// npx wrapper alone leaves vite running, squatting the port and making the next
// local run fail silently against --strictPort.
const server = spawn("npx", ["vite", "preview", "--port", String(PORT), "--strictPort"], {
  cwd: SITE,
  stdio: "ignore",
  detached: true,
});
const stopServer = () => {
  try { process.kill(-server.pid); } catch { server.kill(); }
};
let up = false;
for (let i = 0; i < 40 && !up; i++) {
  await sleep(250);
  up = await fetch(`http://localhost:${PORT}/demo/`).then((r) => r.ok).catch(() => false);
}
if (!up) {
  stopServer();
  console.error("FAIL: preview server never came up (did you run `vite build`?)");
  process.exit(1);
}

// --- drive the demo ------------------------------------------------------- //
const browser = await puppeteer.launch({
  executablePath: process.env.CHROME || "/usr/bin/google-chrome",
  headless: "new",
  args: ["--no-sandbox", "--enable-unsafe-swiftshader", "--window-size=1440,900"],
});
const failures = [];
const consoleErrors = [];
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  // Suppress the scripted opener so the sweep exercises the panel directly;
  // the opener gets its own check at the end.
  await page.evaluateOnNewDocument(() => localStorage.setItem("openreef:demo:opener", "1"));
  page.on("pageerror", (err) => consoleErrors.push(`pageerror: ${err.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(`console: ${msg.text()}`);
  });

  await page.goto(`http://localhost:${PORT}/demo/`, { waitUntil: "domcontentloaded" });
  const ready = await page
    .waitForSelector('.demo-host[data-ready="true"]', { timeout: 20000 })
    .then(() => true)
    .catch(() => false);
  if (!ready) failures.push("demo never reached ready state");

  if (ready) {
    await sleep(1500); // let the default tab finish its reads

    // Tab discovery is a breadth-first crawl: the Helm nav groups (Home /
    // Water / Feeding / Watch / System) only render their pages' tab buttons
    // once the group is open, so a single scan of the initial DOM would miss
    // every page behind a hub. Click each discovered tab, rescan, repeat
    // until no new ids appear.
    const scanTabs = () =>
      page.evaluate(() => {
        const panel = document.querySelector("openreef-panel");
        const root = panel?.shadowRoot ?? panel;
        return [
          ...new Set(
            [...(root?.querySelectorAll('[data-action="tab"][data-id]') ?? [])].map((el) =>
              el.getAttribute("data-id"),
            ),
          ),
        ];
      });
    // A page's tab button only exists while its nav group is open, so a
    // click can silently no-op once the crawl has wandered into another
    // group. clickTab therefore falls back to opening each top-level group
    // (the ids present on the landing page) until the button appears, and
    // the caller asserts the panel really switched — a discovered tab that
    // cannot be reached is a failure, not a free pass.
    const tryClick = (tabId) =>
      page.evaluate((id) => {
        const panel = document.querySelector("openreef-panel");
        const root = panel?.shadowRoot ?? panel;
        const el = root?.querySelector(`[data-action="tab"][data-id="${id}"]`);
        if (!el) return false;
        // Dispatch rather than .click(): some tab links live in SVG (the
        // diagram's hub links), and SVGElement has no click() method.
        el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, composed: true }));
        return true;
      }, tabId);
    const activeTab = () =>
      page.evaluate(() => document.querySelector("openreef-panel")?._activeTab ?? null);
    const landingIds = await scanTabs();
    const clickTab = async (tabId) => {
      if (await tryClick(tabId)) return true;
      for (const group of landingIds) {
        await tryClick(group);
        await sleep(400);
        if (await tryClick(tabId)) return true;
      }
      return false;
    };

    const tabIds = [];
    const queue = [...landingIds];
    const seen = new Set(queue);
    while (queue.length) {
      const id = queue.shift();
      tabIds.push(id);
      const before = consoleErrors.length;
      const clicked = await clickTab(id);
      await sleep(900);
      const active = await activeTab();
      if (!clicked || (active !== null && active !== id)) {
        failures.push(`tab "${id}" could not be reached (active tab: ${active})`);
      }
      if (consoleErrors.length > before) {
        failures.push(`tab "${id}": ${consoleErrors.slice(before).join(" | ")}`);
      }
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/demo-${id}.png` });
      for (const found of await scanTabs()) {
        if (!seen.has(found)) {
          seen.add(found);
          queue.push(found);
        }
      }
    }
    if (tabIds.length < 5) failures.push(`only ${tabIds.length} tabs found — panel chrome missing?`);
    console.log(`tabs swept (${tabIds.length}): ${tabIds.join(", ")}`);

    // Reef Pulse is a present-mode takeover, not a tab — enter and leave it.
    // The ✨ Present button only exists on some views, so go home first.
    await clickTab(tabIds[0]);
    await sleep(900);
    const pulseBefore = consoleErrors.length;
    const pulseOk = await page.evaluate(async () => {
      const panel = document.querySelector("openreef-panel");
      const root = panel?.shadowRoot ?? panel;
      root?.querySelector('[data-action="open-pulse"]')?.click();
      await new Promise((r) => setTimeout(r, 1200));
      const active = Boolean(panel?._pulseActive);
      root?.querySelector('[data-action="close-pulse"]')?.click();
      return active;
    });
    if (!pulseOk) failures.push("Reef Pulse present mode did not open (open-pulse)");
    else if (SHOTS) {
      await page.evaluate(() => {
        const panel = document.querySelector("openreef-panel");
        (panel?.shadowRoot ?? panel)?.querySelector('[data-action="open-pulse"]')?.click();
      });
      await sleep(1200);
      await page.screenshot({ path: `${SHOTS}/demo-pulse.png` });
      await page.evaluate(() => {
        const panel = document.querySelector("openreef-panel");
        (panel?.shadowRoot ?? panel)?.querySelector('[data-action="close-pulse"]')?.click();
      });
      await sleep(400);
    }
    if (consoleErrors.length > pulseBefore) {
      failures.push(`pulse mode: ${consoleErrors.slice(pulseBefore).join(" | ")}`);
    }

    const unrouted = await page.evaluate(() => [...new Set(window.__demoUnrouted ?? [])]);
    if (unrouted.length) {
      failures.push(
        `shim could not answer: ${unrouted.join(", ")} — the panel drifted ahead of the fixtures/shim`,
      );
    }

    // The opener must still appear for a first-time visitor and be dismissable.
    // Fresh incognito context: the sweep page carries an init script that
    // suppresses the opener, and evaluateOnNewDocument survives reloads.
    const fresh = await browser.createBrowserContext();
    const fpage = await fresh.newPage();
    await fpage.setViewport({ width: 1440, height: 900 });
    await fpage.goto(`http://localhost:${PORT}/demo/`, { waitUntil: "domcontentloaded" });
    const openerOk = await fpage
      .waitForSelector(".opener", { timeout: 20000 })
      .then(() => true)
      .catch(() => false);
    if (!openerOk) failures.push("scripted opener did not appear for a fresh visitor");
    if (SHOTS && openerOk) await fpage.screenshot({ path: `${SHOTS}/demo-opener.png` });
    await fresh.close();
  }
} finally {
  await browser.close();
  stopServer();
}

if (failures.length) {
  console.error(`\nDEMO SMOKE: FAIL (${failures.length})`);
  for (const f of failures) console.error(`  ✗ ${f}`);
  process.exit(1);
}
console.log("\nDEMO SMOKE: PASS — every tab rendered, every command answered.");
