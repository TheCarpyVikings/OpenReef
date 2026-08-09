/**
 * The mobile pass: phone layout contracts that regress silently.
 *
 * Every case here pins something that WAS broken on a real iPhone 15 Pro Max
 * and that no other suite would notice, because the failures are layout, not
 * logic — the panel renders "fine", it is just unusable:
 *
 *   - the tab list was fourteen full-width buttons, 787px of chrome on a 932px
 *     screen, so no card was reachable without scrolling past the whole menu;
 *   - every settings section defaulted open, making that page a 25,000px scroll;
 *   - a two-class selector (.manual-batch-row.has-unit) quietly outranked the
 *     phone tier's single-class reset and kept its desktop three-column grid,
 *     squeezing a label into 50px.
 *
 * The stylesheet lives in a JS template literal, so these read it as text. That
 * is deliberate: the point is to catch a future edit that drops the phone
 * override or reintroduces the specificity trap, and only the source shows that.
 *
 * Run standalone:  node tests/test_panel_mobile.mjs
 */

import { assert, assertEqual, makePanel, runTests, test } from "./_panel_harness.mjs";

// --- stylesheet helpers ----------------------------------------------------

/** Split the sheet into its @media blocks by brace matching (regex cannot). */
function mediaBlocks(css) {
  const blocks = [];
  let i = 0;
  while ((i = css.indexOf("@media", i)) !== -1) {
    const open = css.indexOf("{", i);
    if (open === -1) break;
    const query = css.slice(i + 6, open).trim();
    let depth = 1;
    let j = open + 1;
    for (; j < css.length && depth > 0; j++) {
      if (css[j] === "{") depth++;
      else if (css[j] === "}") depth--;
    }
    blocks.push({ query, body: css.slice(open + 1, j - 1) });
    i = j;
  }
  return blocks;
}

/** Media blocks that apply at or below `px` wide — i.e. the phone/tablet tiers. */
function tiersUpTo(css, px) {
  return mediaBlocks(css).filter((b) => {
    const m = /max-width:\s*(\d+)px/.exec(b.query);
    return m && Number(m[1]) <= px;
  });
}

async function sheet() {
  const panel = await makePanel({});
  return panel._styles();
}

// --- the nav rail ----------------------------------------------------------

test("phones get a scrolling nav rail, not a wall of stacked buttons", async () => {
  const css = await sheet();
  const rail = tiersUpTo(css, 1024).find((b) => /\.tabs\s*\{[^}]*overflow-x:\s*auto/.test(b.body));
  assert(rail, "no phone/tablet tier turns .tabs into a horizontal scroller");
  const rule = /\.tabs\s*\{([^}]*)\}/.exec(rail.body)[1];
  assert(/display:\s*flex/.test(rule), "the rail must be a flex row, not the desktop grid");
  assert(/flex-wrap:\s*nowrap/.test(rule), "wrapping would rebuild the wall it replaces");
  assert(/position:\s*sticky/.test(rule), "the rail stays reachable down a long page");
  // A grid template surviving here would fight the flex layout.
  const chip = /\.tabs button\s*\{([^}]*)\}/.exec(rail.body);
  assert(chip && /flex:\s*0 0 auto/.test(chip[1]), "chips must not shrink to fit — that is the wall again");
  assert(chip && /min-height:\s*4\dpx/.test(chip[1]), "chips need a finger-sized target");
});

test("the active chip is scrolled back into view after a re-render", async () => {
  const panel = await makePanel({});
  const active = { offsetLeft: 900, offsetWidth: 100 };
  const rail = {
    scrollWidth: 1500, clientWidth: 400, scrollLeft: 0,
    querySelector: (sel) => (sel === "button.active" ? active : null),
  };
  panel.shadowRoot = { querySelector: (sel) => (sel === ".tabs" ? rail : null) };
  panel._keepActiveTabInView();
  // Centred: 900 - (400 - 100) / 2
  assertEqual(rail.scrollLeft, 750, "active chip should be centred in the rail");

  // A chip near the left edge must not scroll to a negative offset.
  rail.scrollLeft = 0;
  active.offsetLeft = 10;
  panel._keepActiveTabInView();
  assertEqual(rail.scrollLeft, 0, "no negative scroll for the first chip");
});

test("the desktop grid is left alone — nothing to scroll, nothing to move", async () => {
  const panel = await makePanel({});
  const rail = {
    scrollWidth: 1200, clientWidth: 1200, scrollLeft: 42,
    querySelector: () => ({ offsetLeft: 800, offsetWidth: 100 }),
  };
  panel.shadowRoot = { querySelector: () => rail };
  panel._keepActiveTabInView();
  assertEqual(rail.scrollLeft, 42, "an unscrollable grid must not be touched");
});

test("a missing tab strip never throws", async () => {
  const panel = await makePanel({});
  panel.shadowRoot = { querySelector: () => null };
  panel._keepActiveTabInView();  // must not throw
  panel.shadowRoot = { querySelector: () => ({ scrollWidth: 900, clientWidth: 400, querySelector: () => null }) };
  panel._keepActiveTabInView();  // no active chip yet
});

// --- settings sections -----------------------------------------------------

function withViewport(matches, fn) {
  const real = globalThis.matchMedia;
  globalThis.matchMedia = () => ({ matches });
  try { return fn(); } finally { globalThis.matchMedia = real; }
}

test("settings sections default closed on a phone, open on a desktop", async () => {
  const panel = await makePanel({});
  panel._settingsSections = {};
  assertEqual(withViewport(true, () => panel._settingsSectionOpen("profile")), false,
    "an untouched section must start closed on a phone");
  assertEqual(withViewport(false, () => panel._settingsSectionOpen("profile")), true,
    "desktop behaviour is unchanged");
});

test("an explicit choice beats the viewport default in both directions", async () => {
  const panel = await makePanel({});
  panel._settingsSections = { profile: true, dosing: false };
  // A deep-link writes true before rendering; it must survive the phone default.
  assertEqual(withViewport(true, () => panel._settingsSectionOpen("profile")), true,
    "a deep-linked section stays open on a phone");
  assertEqual(withViewport(false, () => panel._settingsSectionOpen("dosing")), false,
    "a section the user closed stays closed");
});

test("no matchMedia (server-side or an old webview) falls back to open", async () => {
  const panel = await makePanel({});
  panel._settingsSections = {};
  const real = globalThis.matchMedia;
  globalThis.matchMedia = undefined;
  try {
    assertEqual(panel._settingsSectionOpen("profile"), true, "unknown viewport must not hide settings");
  } finally { globalThis.matchMedia = real; }
});

// --- the specificity trap --------------------------------------------------

test("the phone tier resets .manual-batch-row.has-unit by name, not by hope", async () => {
  const css = await sheet();
  const tiers = tiersUpTo(css, 700);
  const reset = tiers.some((b) =>
    /\.manual-batch-row\s*,\s*\.manual-batch-row\.has-unit\s*\{[^}]*grid-template-columns:\s*1fr/.test(b.body));
  assert(reset,
    "a bare .manual-batch-row reset loses to the two-class .has-unit rule above it; name both");
});

test("phone touch targets clear the finger threshold", async () => {
  const css = await sheet();
  const tiers = tiersUpTo(css, 700);
  const sized = (selector, min) => tiers.some((b) => {
    const m = new RegExp(`${selector}\\s*\\{([^}]*)\\}`).exec(b.body);
    if (!m) return false;
    const px = /(?:min-height|height|width):\s*(\d+)px/.exec(m[1]);
    return px && Number(px[1]) >= min;
  });
  assert(sized("\\.coral-swatch", 32), "coral swatches rendered at 26px — below a fingertip");
  assert(sized("\\.inline-btn", 32), "inline Go buttons rendered 104x22");
  assert(sized("\\.or-buddy-close", 32), "the buddy's dismiss was a 22px target");
});

// --- the full-screen diagram ----------------------------------------------

test("full screen is a portrait-phone rotation, and only there", async () => {
  const css = await sheet();
  const rotate = mediaBlocks(css).find((b) =>
    /orientation:\s*portrait/.test(b.query) && /rotate\(90deg\)/.test(b.body));
  assert(rotate, "no portrait rule rotates the full-screen scene onto the long axis");
  assert(/max-width:\s*(\d{3})px/.test(rotate.query),
    "rotation must stay bounded to phones — a sideways iPad is not the fix");
  // Rotating a box sized to the OTHER axis is what makes it fill the screen.
  assert(/width:\s*100dvh/.test(rotate.body) && /height:\s*100dvw/.test(rotate.body),
    "the rotated svg must be sized against the swapped axes");
});

test("the full-screen stage outranks the panel chrome but never Reef Pulse", async () => {
  const css = await sheet();
  const rule = /\.panel\.diagram-stage\.is-full\s*\{([^}]*)\}/.exec(css);
  assert(rule, "no .is-full stage rule");
  assert(/position:\s*fixed/.test(rule[1]) && /inset:\s*0/.test(rule[1]), "full screen must cover the viewport");
  assert(/aspect-ratio:\s*auto/.test(rule[1]), "the 16/10 stage ratio has to be released to fill the screen");
  const z = Number(/z-index:\s*(\d+)/.exec(rule[1])[1]);
  const pulseZ = Number(/\.pulse-root\s*\{[^}]*z-index:\s*(\d+)/.exec(css)[1]);
  assert(z < pulseZ, `full screen (${z}) must sit below Reef Pulse (${pulseZ})`);
  assert(z > 100, "z-index must clear Home Assistant's own chrome, like the Pulse root does");
});

test("the Diagram tab offers full screen, and the overlay carries its own exit", async () => {
  const panel = await makePanel({
    equipment: { ret: { label: "Return", type: "return_pump", switch_entity_id: "switch.ret", armed: true } },
    diagram: { systemType: "sump", allowControls: true, layout: {} },
  });
  panel._hass = { states: { "switch.ret": { state: "on", attributes: {} } } };
  panel._diagramArranging = false;
  panel._pulseFocus = null;
  panel._coralFocus = null;

  panel._diagramFull = false;
  const normal = panel._diagramTab();
  assert(normal.includes('data-action="diagram-full"'), "no way into full screen from the tab");
  assert(!/class="panel diagram-stage\s+is-full/.test(normal), "stage must not start full screen");
  assert(!normal.includes("diag-full-close"), "no exit button while not full screen");

  panel._diagramFull = true;
  const full = panel._diagramTab();
  assert(/diagram-stage\s+is-full/.test(full), "full screen must mark the stage");
  assert(full.includes("diag-full-close"), "a full-screen overlay with no exit is a trap");
  assert(full.includes("diag-full-hint"), "the rotated view needs to explain itself");
});

test("Show all / Hide all reach every section that rendered, not just the stored ones", async () => {
  const panel = await makePanel({});
  panel._settingsSections = { profile: false };
  // Sections register themselves as they render.
  panel._settingsPanel("diagram", "Diagram", "", "");
  panel._settingsPanel("dosing", "Dosing", "", "");
  const ids = panel._allSettingsSectionIds().sort();
  assertEqual(ids, ["diagram", "dosing", "profile"],
    "an id with no stored default must still be reachable by Show all");
});

await runTests();
