#!/usr/bin/env node
/**
 * Captures fresh feature screenshots from the OpenReef Home Assistant panel
 * into site/public/demos/ with the filenames the feature cards expect.
 *
 * Usage:
 *   HA_URL=http://homeassistant.local:8123 HA_TOKEN=<long-lived-access-token> pnpm capture
 *
 * Optional env:
 *   CHROME       path to Chrome/Chromium (default /usr/bin/google-chrome)
 *   PANEL_PATH   panel URL path (default "openreef")
 *   TABS         comma-separated tab ids to capture (default: all below)
 *   VIEWPORT     WxH (default 1280x800; captured at 2x for crisp cards)
 *
 * Auth note: the script injects the long-lived token as `hassTokens` in
 * localStorage before the frontend boots — the standard headless-HA trick.
 * If your HA lands on the login screen instead, generate a fresh long-lived
 * token (profile → security) and check HA_URL matches the URL you browse on.
 */
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { captureRegions, openPage } from "./lib/regions.mjs";

const HA_URL = process.env.HA_URL?.replace(/\/$/, "");
const HA_TOKEN = process.env.HA_TOKEN;
if (!HA_URL || !HA_TOKEN) {
  console.error("Set HA_URL and HA_TOKEN. See the header of this script.");
  process.exit(1);
}
const CHROME = process.env.CHROME || "/usr/bin/google-chrome";
const PANEL_PATH = process.env.PANEL_PATH || "openreef";
const [W, H] = (process.env.VIEWPORT || "1280x800").split("x").map(Number);

// Pages to capture (group → page, since the Helm). Each page's titled panels
// land in public/demos/<page>/<n>-<slug>.png — the same names the showroom
// harness (tools/demo-shots.mjs) produces, so the site swaps tanks for free.
// Pages whose feature is disabled in your config are skipped.
const ALL_TABS = [
  { group: "home", id: "mission" }, { group: "home", id: "diagram" },
  { group: "water", id: "awc" }, { group: "water", id: "mixing" }, { group: "water", id: "dosing" },
  { group: "water", id: "maintenance" }, { group: "water", id: "icp" },
  { group: "feeding", id: "feeding" }, { group: "feeding", id: "nps" }, { group: "feeding", id: "hatchery" },
  { group: "feeding", id: "cultures" }, { group: "feeding", id: "spawning" },
  { group: "watch", id: "cameras" }, { group: "watch", id: "live" }, { group: "watch", id: "energy" },
  { group: "system", id: "controls" },
];
const wanted = process.env.TABS?.split(",").map((s) => s.trim());
const TABS = wanted ? ALL_TABS.filter((t) => wanted.includes(t.id)) : ALL_TABS;

const outDir = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "demos");
mkdirSync(outDir, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--enable-unsafe-swiftshader"],
});
try {
  const page = await browser.newPage();
  await page.setViewport({ width: W, height: H, deviceScaleFactor: 2 });

  // Log the frontend in before it boots, and mark the panel as "already
  // toured" — a fresh profile otherwise auto-starts the guided tour and the
  // buddy toast, which then photobomb every screenshot.
  await page.evaluateOnNewDocument(
    (haUrl, token) => {
      try {
        localStorage.setItem(
          "hassTokens",
          JSON.stringify({
            access_token: token,
            token_type: "Bearer",
            expires_in: 1800,
            expires: Date.now() + 3600e3,
            hassUrl: haUrl,
            clientId: haUrl + "/",
            refresh_token: "",
          })
        );
        localStorage.setItem("openreef:onboarding:v1:done", "1");
        localStorage.setItem("openreef:buddy", "off");
      } catch {
        /* ignore */
      }
    },
    HA_URL,
    HA_TOKEN
  );

  await page.goto(`${HA_URL}/${PANEL_PATH}`, { waitUntil: "domcontentloaded", timeout: 60000 });
  // Wait for the panel's tab bar through the shadow DOM.
  await page.waitForSelector('pierce/[data-action="tab"]', { timeout: 45000 }).catch(() => {
    console.error(
      "Panel tab bar never appeared — check PANEL_PATH, the token, and that the integration is loaded."
    );
    process.exit(1);
  });
  await sleep(2500);

  // Belt and braces: if the tour or buddy toast still appeared (e.g. the
  // panel changes its storage keys), dismiss them through the shadow DOM.
  for (const sel of ['pierce/[data-action="onboarding-skip"]', 'pierce/[data-action="buddy-dismiss"]']) {
    const btn = await page.$(sel);
    if (btn) {
      await btn.click().catch(() => {});
      await sleep(600);
    }
  }

  const click = (tabId) => page.evaluate((i) => {
    const root = document.querySelector("openreef-panel")?.shadowRoot;
    root?.querySelector(`[data-action="tab"][data-id="${i}"]`)?.dispatchEvent(new MouseEvent("click", { bubbles: true, composed: true }));
  }, tabId);
  for (const { group, id } of TABS) {
    const present = await page.evaluate((i) => {
      const root = document.querySelector("openreef-panel")?.shadowRoot;
      return Boolean(root?.querySelector(`[data-action="tab"][data-id="${i}"]`));
    }, group);
    if (!present) { console.warn(`- group "${group}" not found — skipped ${id}`); continue; }
    await openPage(page, group, id, click);
    const manifest = await captureRegions(page, join(outDir, id));
    if (!manifest.length) console.warn(`- ${id}: no regions captured (feature disabled?)`);
    else console.log(`✓ ${id} → public/demos/${id}/ (${manifest.map((m) => m.file).join(", ")})`);
  }

  // Reef Pulse isn't a tab — it's the ✨ Present takeover. Capture it last,
  // from the mission tab, unless a TABS filter excluded it.
  if (!wanted || wanted.includes("pulse")) {
    await openPage(page, "home", "mission", click);
    const present = await page.$('pierce/[data-action="open-pulse"]');
    if (!present) {
      console.warn('- pulse: no "open-pulse" button found (Pulse disabled?) — skipped');
    } else {
      await present.click();
      await sleep(4000); // let the wall settle (sparklines, backdrop)
      mkdirSync(join(outDir, "pulse"), { recursive: true });
      await page.screenshot({ path: join(outDir, "pulse", "wall.png") });
      console.log("✓ pulse → public/demos/pulse/wall.png");
      const close = await page.$('pierce/[data-action="close-pulse"]');
      if (close) await close.click().catch(() => {});
    }
  }
} finally {
  await browser.close();
}
console.log("Done. Rebuild the site and the feature cards will pick these up.");
