#!/usr/bin/env node
/**
 * Emulated mobile audit: loads the site at real phone metrics and reports
 * layout problems (horizontal overflow, offscreen elements, tiny tap targets,
 * content hidden behind the fixed buddy bubble) plus per-section screenshots.
 *
 * Usage: node tools/mobile-audit.mjs [url]
 */
import { mkdirSync } from "node:fs";
import puppeteer from "puppeteer-core";

const URL = process.argv[2] || "http://localhost:4173/";
const OUT = process.env.SHOT_DIR || "/tmp/mobile-audit";
mkdirSync(OUT, { recursive: true });

const IOS_UA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
const AND_UA =
  "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/536.36";

const DEVICES = [
  { name: "iPhone-SE", w: 375, h: 667, dsf: 2, ua: IOS_UA },
  { name: "iPhone-15", w: 393, h: 852, dsf: 3, ua: IOS_UA },
  { name: "iPhone-15-Pro-Max", w: 430, h: 932, dsf: 3, ua: IOS_UA },
  { name: "Pixel-8", w: 412, h: 915, dsf: 2.6, ua: AND_UA },
  { name: "iPad-mini", w: 768, h: 1024, dsf: 2, ua: IOS_UA },
];

const SECTIONS = ["hero", "meet", "sandbox", "lights", "spawning", "features", "diy", "compare", "cta"];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME || "/usr/bin/google-chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--enable-unsafe-swiftshader"],
});

const report = [];

for (const d of DEVICES) {
  const page = await browser.newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(e.message));
  await page.setUserAgent(d.ua);
  await page.setViewport({
    width: d.w,
    height: d.h,
    deviceScaleFactor: d.dsf,
    isMobile: true,
    hasTouch: true,
  });
  await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 90000 });
  await sleep(7000);

  const findings = await page.evaluate(() => {
    const vw = window.innerWidth;
    const out = { vw, overflow: null, offenders: [], tinyTargets: [], canvas: false };
    out.canvas = !!document.querySelector(".canvas-wrap canvas");
    const de = document.documentElement;
    if (de.scrollWidth > vw + 1) out.overflow = { scrollWidth: de.scrollWidth, viewport: vw };
    // any element sticking out horizontally
    document.querySelectorAll("body *").forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return;
      const cs = getComputedStyle(el);
      if (cs.position === "fixed") return;
      if (r.right > vw + 2 || r.left < -2) {
        // ignore things inside an intentional horizontal scroller
        let p = el.parentElement, scroller = false;
        while (p) {
          if (getComputedStyle(p).overflowX === "auto" || getComputedStyle(p).overflowX === "scroll") { scroller = true; break; }
          p = p.parentElement;
        }
        if (!scroller) {
          out.offenders.push({
            tag: el.tagName.toLowerCase(),
            cls: (el.className || "").toString().slice(0, 40),
            left: Math.round(r.left), right: Math.round(r.right),
          });
        }
      }
    });
    // interactive elements smaller than the 44px touch guideline
    document.querySelectorAll("button, a, input[type=range], input[type=email]").forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return;
      if (r.height < 32 || r.width < 32) {
        out.tinyTargets.push({
          tag: el.tagName.toLowerCase(),
          cls: (el.className || "").toString().slice(0, 30),
          text: (el.textContent || "").trim().slice(0, 22),
          w: Math.round(r.width), h: Math.round(r.height),
        });
      }
    });
    return out;
  });

  // how much of the screen the fixed buddy bubble eats
  const buddy = await page.evaluate(() => {
    const b = document.querySelector(".buddy");
    if (!b) return null;
    const r = b.getBoundingClientRect();
    return {
      pctHeight: Math.round((r.height / window.innerHeight) * 100),
      pctWidth: Math.round((r.width / window.innerWidth) * 100),
      top: Math.round(r.top),
    };
  });

  report.push({ device: d.name, ...findings, buddy, errs: errs.slice(0, 3) });

  for (const s of SECTIONS) {
    await page.evaluate((sec) => {
      const el = document.querySelector(`section[data-sec="${sec}"]`);
      if (el) window.scrollTo({ top: el.offsetTop + 40, behavior: "instant" });
    }, s);
    await sleep(1600);
    await page.screenshot({ path: `${OUT}/${d.name}-${s}.png` });
  }
  await page.close();
}

await browser.close();

console.log("\n================ MOBILE AUDIT ================");
for (const r of report) {
  console.log(`\n### ${r.device}  (${r.vw}px CSS width)`);
  console.log(`  3D canvas      : ${r.canvas ? "mounted" : "MISSING"}`);
  console.log(`  H-overflow     : ${r.overflow ? `YES — page ${r.overflow.scrollWidth}px vs ${r.overflow.viewport}px viewport` : "none"}`);
  console.log(`  Offending els  : ${r.offenders.length ? JSON.stringify(r.offenders.slice(0, 5)) : "none"}`);
  console.log(`  Small targets  : ${r.tinyTargets.length ? JSON.stringify(r.tinyTargets.slice(0, 5)) : "none"}`);
  console.log(`  Buddy bubble   : ${r.buddy ? `${r.buddy.pctHeight}% of screen height, ${r.buddy.pctWidth}% width, top ${r.buddy.top}px` : "n/a"}`);
  console.log(`  JS errors      : ${r.errs.length ? r.errs.join(" | ") : "none"}`);
}
console.log("\nScreenshots →", OUT);
