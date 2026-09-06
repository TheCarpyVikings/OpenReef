#!/usr/bin/env node
/*
 * Region screenshots of the demo for the site's feature pages — every titled
 * panel in each page's content stack becomes its own image (the feeding
 * station diagram, the rack, the live mixing view…), named by heading, plus
 * a full-page shot and a manifest. Output: public/demos/<page>/…
 * The same routine runs against a real tank in tools/capture-demos.mjs, so a
 * real capture drops straight into the same file names.
 *
 * Usage:  node tools/demo-shots.mjs [--pages nps,cultures]   (needs a build)
 */
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { captureRegions, openPage } from "./lib/regions.mjs";

const SITE = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const PORT = 4184;
export const PAGES = [
  ["feeding", "nps"], ["feeding", "hatchery"], ["feeding", "cultures"], ["feeding", "spawning"],
  ["feeding", "feeding"], ["water", "mixing"], ["water", "dosing"], ["water", "maintenance"],
  ["water", "awc"], ["home", "mission"], ["home", "diagram"],
];
const only = process.argv.includes("--pages") ? process.argv[process.argv.indexOf("--pages") + 1].split(",") : null;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const server = spawn("npx", ["vite", "preview", "--port", String(PORT), "--strictPort"], { cwd: SITE, stdio: "ignore", detached: true });
await sleep(2500);
const browser = await puppeteer.launch({ executablePath: process.env.CHROME || "/usr/bin/google-chrome", headless: "new", args: ["--no-sandbox", "--enable-unsafe-swiftshader"] });
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1000, deviceScaleFactor: 1.5 });
  await page.evaluateOnNewDocument(() => localStorage.setItem("openreef:demo:opener", "1"));
  await page.goto(`http://localhost:${PORT}/demo/`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('.demo-host[data-ready="true"]', { timeout: 20000 });
  await sleep(1500);
  const click = (id) => page.evaluate((i) => {
    const root = document.querySelector("openreef-panel").shadowRoot;
    root.querySelector(`[data-action="tab"][data-id="${i}"]`)?.dispatchEvent(new MouseEvent("click", { bubbles: true, composed: true }));
  }, id);
  for (const [group, id] of PAGES) {
    if (only && !only.includes(id)) continue;
    await openPage(page, group, id, click);
    const manifest = await captureRegions(page, resolve(SITE, "public", "demos", id), { hideSelector: ".demo-banner" });
    console.log(`${id}: ${manifest.map((m) => m.file).join(", ")}`);
  }
  if (!only || only.includes("pulse")) {
    await click("mission"); await sleep(600);
    await page.evaluate(() => document.querySelector("openreef-panel").shadowRoot.querySelector('[data-action="open-pulse"]')?.dispatchEvent(new MouseEvent("click", { bubbles: true, composed: true })));
    await sleep(1800);
    mkdirSync(resolve(SITE, "public", "demos", "pulse"), { recursive: true });
    await page.screenshot({ path: resolve(SITE, "public", "demos", "pulse", "wall.png") });
    console.log("pulse: wall.png");
  }
} finally {
  await browser.close();
  try { process.kill(-server.pid); } catch { server.kill(); }
}
