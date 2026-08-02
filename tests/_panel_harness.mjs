/**
 * Test harness for the panel web component (custom_components/openreef/frontend).
 *
 * The panel is one ~19k-line vanilla custom element with no build step, so there is
 * nothing to import normally. This loads the file as a module behind minimal browser
 * stubs, captures the class handed to customElements.define, and builds instances
 * WITHOUT running the constructor (Object.create) — the constructor wants a shadow
 * root, hass and a network. Every method is on the prototype, so pure logic
 * (due states, chart aggregation, formatting) is directly callable.
 *
 * Deliberately dependency-free, like the Python suites: no jsdom, no test runner.
 *
 * Run standalone:  node tests/test_panel_maintenance.mjs
 */

// Pinned before anything constructs a Date: the fixed-day schedule maths is
// calendar-local on both sides of the lockstep, so the suites need one calendar.
process.env.TZ = "UTC";

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
// OPENREEF_PANEL_PATH points the harness at a COPY of the panel. That is how a suite
// is checked for teeth: mutate the copy, re-run, confirm the suite fails — without
// touching the working tree, so several suites can be verified at once.
export const PANEL_PATH = process.env.OPENREEF_PANEL_PATH
  || path.join(ROOT, "custom_components", "openreef", "frontend", "openreef-panel.js");

let cachedClass = null;

/** Load the panel module once behind browser stubs and return its element class. */
export async function loadPanelClass() {
  if (cachedClass) return cachedClass;
  let captured = null;
  globalThis.HTMLElement = class {};
  globalThis.customElements = {
    define: (_name, cls) => { captured = captured || cls; },
    get: () => undefined,
  };
  globalThis.window = globalThis;
  globalThis.document = {
    createElement: () => ({ style: {}, classList: { add() {}, remove() {} } }),
    addEventListener() {},
  };
  const source = fs.readFileSync(PANEL_PATH, "utf8");
  // data: URL rather than a file import — the panel is not a module on disk and
  // must not be resolved relative to the repo (it has no exports).
  await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
  if (!captured) throw new Error("openreef-panel.js did not define a custom element");
  cachedClass = captured;
  return captured;
}

/**
 * A panel instance with `config` installed and the small amount of view state the
 * render paths read. No constructor, no DOM, no hass.
 */
export async function makePanel(config = {}) {
  const PanelClass = await loadPanelClass();
  const panel = Object.create(PanelClass.prototype);
  panel._config = config;
  panel._maintenanceHistoryOpen = {};
  panel._maintenanceDrafts = {};
  panel._maintChart = { weeks: 12, unit: "pct" };
  return panel;
}

/**
 * Freeze the clock. The panel reads "now" through both `Date.now()` and
 * `new Date()`, so both are replaced. Returns the restore function.
 */
export function freezeTime(iso) {
  const RealDate = globalThis.Date;
  const fixed = new RealDate(iso).getTime();
  if (!Number.isFinite(fixed)) throw new Error(`freezeTime: bad instant ${iso}`);
  class FrozenDate extends RealDate {
    constructor(...args) {
      super(...(args.length ? args : [fixed]));
    }
    static now() {
      return fixed;
    }
  }
  globalThis.Date = FrozenDate;
  return () => { globalThis.Date = RealDate; };
}

/** Read a JSON fixture from tests/fixtures. */
export function fixture(name) {
  return JSON.parse(fs.readFileSync(path.join(HERE, "fixtures", name), "utf8"));
}

export function assert(condition, message) {
  if (!condition) throw new Error(message || "assertion failed");
}

export function assertEqual(actual, expected, message) {
  const a = JSON.stringify(actual);
  const b = JSON.stringify(expected);
  if (a !== b) throw new Error(`${message || "not equal"}: got ${a}, expected ${b}`);
}

/**
 * Tiny runner mirroring the Python suites. Register with `test(name, fn)`, then
 * `await runTests()` at the end of the file: each case prints PASS/FAIL and the
 * process exits non-zero if any failed. (Registration rather than reading the
 * module's own exports — a module cannot import itself while still evaluating.)
 */
const registered = [];

export function test(name, fn) {
  registered.push([name, fn]);
}

export async function runTests() {
  const tests = [...registered].sort(([a], [b]) => a.localeCompare(b));
  let passed = 0;
  const failed = [];
  for (const [name, fn] of tests) {
    try {
      await fn();
      passed += 1;
      console.log(`  PASS  ${name}`);
    } catch (error) {
      failed.push(name);
      console.log(`  FAIL  ${name}: ${error.message}`);
    }
  }
  console.log(`\n${passed}/${tests.length} passed${failed.length ? ` — FAILED: ${failed.join(", ")}` : " "}`);
  process.exitCode = failed.length ? 1 : 0;
}
