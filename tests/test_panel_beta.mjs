/**
 * Beta feedback FAB — custom element behaviour.
 *
 * Detachable with the feature: delete this file alongside
 * custom_components/openreef/frontend/openreef-beta.js.
 *
 * The element ships its own shadow root and builds HTML with template strings,
 * so what matters here is what the strings contain. Specifically:
 *
 *   * it stays completely invisible when the backend module isn't there, so
 *     removing beta.py after the beta cannot leave a dead button behind;
 *   * reply text arrives from the portal and goes through innerHTML, so it
 *     must be escaped — this is the one genuine XSS surface in the feature;
 *   * the delegated listeners bind exactly once, because the panel re-appends
 *     this element on every render and a stacking listener would fire a
 *     submission N times;
 *   * a half-typed message survives clicking a different kind chip.
 *
 * Run standalone:  node tests/test_panel_beta.mjs
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { assert, assertEqual, runTests, test } from "./_panel_harness.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BETA_PATH = path.join(
  HERE, "..", "custom_components", "openreef", "frontend", "openreef-beta.js",
);

/* --- loader ---------------------------------------------------------------
 * Its own loader rather than the shared panel one: the harness caches the FIRST
 * class handed to customElements.define, which is the panel's. */

let cachedClass = null;

async function loadBetaClass() {
  if (cachedClass) return cachedClass;
  let captured = null;
  globalThis.HTMLElement = class {};
  globalThis.customElements = {
    define: (_name, cls) => { captured = cls; },
    get: () => undefined,
  };
  globalThis.window = globalThis;
  // Node already provides `navigator` (getter-only, so it cannot be assigned);
  // the element only reads navigator.userAgent, which Node's satisfies.
  globalThis.document = globalThis.document || { addEventListener() {}, removeEventListener() {} };
  const source = fs.readFileSync(BETA_PATH, "utf8");
  await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
  if (!captured) throw new Error("openreef-beta.js did not define a custom element");
  cachedClass = captured;
  return captured;
}

/** Minimal shadow-root stub: records what was written, serves elements by id. */
function fakeShadowRoot(elements = {}) {
  return {
    innerHTML: "",
    listeners: [],
    addEventListener(type, fn) { this.listeners.push([type, fn]); },
    getElementById: (id) => elements[id] ?? null,
    querySelector: () => null,
    get firstChild() { return this.innerHTML ? {} : null; },
  };
}

/** An instance without running the constructor (it wants a real shadow root). */
async function makeFab(overrides = {}) {
  const BetaClass = await loadBetaClass();
  const fab = Object.create(BetaClass.prototype);
  Object.assign(fab, {
    _hass: { user: { is_admin: true } },
    _context: { tab: "mission", version: "0.6.9" },
    _support: () => "OpenReef support summary\nVersion: 0.6.9",
    _state: null,
    _open: false,
    _view: "send",
    _draft: { kind: "bug", severity: "normal", body: "", intent: "" },
    _showsPayload: false,
    _busy: false,
    _error: "",
    _sentRef: "",
    _code: "",
    _loaded: true,
    _bound: false,
  });
  Object.assign(fab, overrides);
  fab.shadowRoot = overrides.shadowRoot ?? fakeShadowRoot();
  return fab;
}

const ENROLLED = {
  enabled: true, enrolled: true, testerName: "Ada", version: "0.6.9",
  shareSupport: true, shareLogs: true, items: [], announcements: [],
  queued: 0, unread: 0, lastSyncAt: "", lastError: "",
};

/* --- visibility ---------------------------------------------------------- */

test("invisible until status has loaded", async () => {
  const fab = await makeFab({ _loaded: false });
  assert(fab._visible() === false, "should be hidden before load");
});

test("invisible when the backend module is gone", async () => {
  // beta.py deleted after the beta: openreef/beta_status errors, _state stays
  // null, and the button must simply never appear.
  const fab = await makeFab({ _loaded: true, _state: null });
  assert(fab._visible() === false, "no backend means no button");
  fab._render();
  assertEqual(fab.shadowRoot.innerHTML, "", "must render nothing at all");
});

test("invisible to non-admin users", async () => {
  const fab = await makeFab({ _state: ENROLLED, _hass: { user: { is_admin: false } } });
  assert(fab._visible() === false, "non-admins cannot submit, so must not be offered");
});

test("visible once enrolled", async () => {
  const fab = await makeFab({ _state: ENROLLED });
  assert(fab._visible() === true, "should show for an admin with state");
  fab._render();
  assert(fab.shadowRoot.innerHTML.includes("Ask Reece"), "FAB label missing");
});

/* --- badge --------------------------------------------------------------- */

test("badge is hidden at zero and shown when unread", async () => {
  // Matched against the badge's own attribute — the FAB icon carries
  // aria-hidden, so a bare includes("hidden") passes no matter what.
  const badgeHidden = /class="orb-badge"\s+hidden/;

  const quiet = await makeFab({ _state: { ...ENROLLED, unread: 0 } });
  assert(badgeHidden.test(quiet._fab()), "zero unread should hide the badge");

  const busy = await makeFab({ _state: { ...ENROLLED, unread: 3 } });
  const markup = busy._fab();
  assert(!badgeHidden.test(markup), "unread should show the badge");
  assert(markup.includes(">3<"), "badge count missing");
});

test("badge clamps at 9+", async () => {
  const fab = await makeFab({ _state: { ...ENROLLED, unread: 42 } });
  assert(fab._fab().includes("9+"), "large counts should clamp");
});

/* --- escaping ------------------------------------------------------------ */

test("a reply from the portal is escaped", async () => {
  const hostile = '<img src=x onerror="alert(1)">';
  const fab = await makeFab({
    _state: {
      ...ENROLLED,
      items: [{
        ref: "OR-0001", kind: "bug", status: "actioned",
        body: hostile, reply: hostile, createdAt: "", repliedAt: "", unread: false,
      }],
    },
    _view: "list",
  });
  const markup = fab._listView();
  assert(!markup.includes("<img"), "hostile markup reached the DOM string");
  assert(markup.includes("&lt;img"), "expected escaped output");
});

test("an announcement from the portal is escaped", async () => {
  const fab = await makeFab({
    _state: {
      ...ENROLLED,
      announcements: [{ id: "a", title: "<script>x</script>", body: "<b>y</b>", publishedAt: "", unread: true }],
    },
  });
  const markup = fab._newsView();
  assert(!markup.includes("<script>"), "script tag survived escaping");
  assert(!markup.includes("<b>"), "raw markup survived escaping");
});

test("the tester's own draft is escaped when re-rendered", async () => {
  const fab = await makeFab({
    _state: ENROLLED,
    _draft: { kind: "bug", severity: "normal", body: '</textarea><script>x</script>', intent: '" onmouseover="x' },
  });
  const markup = fab._sendView();
  assert(!markup.includes("</textarea><script>"), "draft body broke out of the textarea");
  assert(!markup.includes('" onmouseover="x'), "draft intent broke out of the attribute");
});

/* --- draft handling ------------------------------------------------------ */

test("switching kind keeps what is already typed", async () => {
  const shadowRoot = fakeShadowRoot({
    "orb-body": { value: "the ATO ran twice overnight" },
    "orb-intent": { value: "topping off" },
  });
  const fab = await makeFab({ _state: ENROLLED, shadowRoot });
  fab._captureDraft();
  assertEqual(fab._draft.body, "the ATO ran twice overnight", "body lost");
  assertEqual(fab._draft.intent, "topping off", "intent lost");
});

test("severity chips only appear for bugs", async () => {
  const bug = await makeFab({ _state: ENROLLED, _draft: { kind: "bug", severity: "normal", body: "", intent: "" } });
  assert(bug._sendView().includes("Blocking me"), "bugs should offer severity");

  const idea = await makeFab({ _state: ENROLLED, _draft: { kind: "idea", severity: "normal", body: "", intent: "" } });
  assert(!idea._sendView().includes("Blocking me"), "ideas should not ask for severity");
});

test("the unsafe kind leads with a safety warning, not a form", async () => {
  const fab = await makeFab({ _state: ENROLLED, _draft: { kind: "unsafe", severity: "normal", body: "", intent: "" } });
  const markup = fab._sendView();
  assert(markup.includes("deal with the"), "expected the tank-first warning");
});

/* --- consent preview ----------------------------------------------------- */

test("the payload preview shows the real support summary", async () => {
  const fab = await makeFab({ _state: ENROLLED, _showsPayload: true });
  const markup = fab._payloadPreview();
  assert(markup.includes("OpenReef support summary"), "preview should show what is actually sent");
  assert(markup.includes("mission"), "preview should name the current tab");
});

test("the preview says so when sharing is off", async () => {
  const fab = await makeFab({ _state: { ...ENROLLED, shareSupport: false, shareLogs: false } });
  const markup = fab._payloadPreview();
  assert(markup.includes("<strong>off</strong>"), "an off toggle should be stated plainly");
  assert(!markup.includes("OpenReef support summary"), "must not preview what it will not send");
});

test("a panel that cannot build a summary still allows a report", async () => {
  const fab = await makeFab({
    _state: ENROLLED,
    _support: () => { throw new Error("half-configured install"); },
  });
  assertEqual(fab._supportText(), "", "a throwing summary must degrade to empty");
});

/* --- custom element upgrade ----------------------------------------------
 * The panel createElement()s this and sets hass/context/support synchronously,
 * while the dynamic import that DEFINES it is still in flight. Properties set
 * on a not-yet-upgraded element land as own data properties, which shadow the
 * prototype accessors forever once it upgrades — so the setters never fire and
 * the button never appears. This shipped broken in 0.7.0; these are the tests
 * that would have caught it.
 *
 * Note these deliberately do NOT use makeFab's plain assignment: that goes
 * through the setters and so cannot reproduce the defect. */

function shadowProperty(target, name, value) {
  Object.defineProperty(target, name, {
    value, writable: true, configurable: true, enumerable: true,
  });
}

test("pre-upgrade properties are re-applied through their setters", async () => {
  const fab = await makeFab({ _hass: null, _loaded: false, _state: null });
  const hass = { user: { is_admin: true }, callWS: async () => ENROLLED };

  shadowProperty(fab, "hass", hass);
  assert(fab._hass === null, "precondition: the shadowed setter must not have run");

  fab.connectedCallback();
  assert(fab._hass === hass, "connectedCallback must route hass back through its setter");
});

test("context and support survive the upgrade too", async () => {
  const fab = await makeFab({ _hass: null, _loaded: false, _state: null });
  shadowProperty(fab, "context", { tab: "dosing", version: "0.7.0" });
  shadowProperty(fab, "support", () => "summary text");
  shadowProperty(fab, "hass", { user: { is_admin: true }, callWS: async () => ENROLLED });

  fab.connectedCallback();
  assertEqual(fab._context.tab, "dosing", "context lost across upgrade");
  assertEqual(fab._supportText(), "summary text", "support callback lost across upgrade");
});

test("context and support are upgraded before hass", async () => {
  // hass is what kicks off the status load and first render, so if it were
  // re-applied first the very first paint would have no support callback.
  const fab = await makeFab({ _hass: null, _loaded: false, _state: null });
  let supportAtLoadTime = "unset";
  shadowProperty(fab, "support", () => "summary text");
  shadowProperty(fab, "hass", {
    user: { is_admin: true },
    callWS: async () => { supportAtLoadTime = fab._supportText(); return ENROLLED; },
  });

  fab.connectedCallback();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assertEqual(supportAtLoadTime, "summary text", "hass was applied before support");
});

test("upgrading is a no-op when the panel set nothing", async () => {
  const fab = await makeFab({ _state: ENROLLED });
  fab.connectedCallback();  // must not throw
  assert(fab._visible() === true, "a normally-constructed element still works");
});

/* --- binding ------------------------------------------------------------- */

test("listeners bind exactly once across re-renders", async () => {
  const fab = await makeFab({ _state: ENROLLED });
  fab._render();
  fab._render();
  fab._render();
  const clicks = fab.shadowRoot.listeners.filter(([type]) => type === "click");
  assertEqual(clicks.length, 1, "click listener stacked across renders");
});

/* --- enrolment ----------------------------------------------------------- */

test("an unenrolled install is asked for a code, not a message", async () => {
  const fab = await makeFab({ _state: { ...ENROLLED, enrolled: false }, _open: true, _view: "enrol" });
  const markup = fab._modal();
  assert(markup.includes("Invite code"), "should ask for the code");
  assert(!markup.includes("orb-nav"), "no tabs before enrolment");
});

test("a rejected code stays in the box", async () => {
  const fab = await makeFab({ _state: { ...ENROLLED, enrolled: false }, _code: "REEF-TYPO", _error: "nope" });
  assert(fab._enrolView().includes('value="REEF-TYPO"'), "the typed code should survive a rejection");
});

await runTests();
