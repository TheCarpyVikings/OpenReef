/**
 * The Helm (0.7.72): five task groups over sixteen pages — the group bar, the
 * hubs of live cards, and the second deck of sibling pills. Deep links keep
 * page ids, so nothing else in the app changes.
 *
 * Run standalone:  node tests/test_panel_nav.mjs
 */

import { assert, freezeTime, makePanel, runTests, test } from "./_panel_harness.mjs";

const NOW = "2026-08-13T12:00:00Z";

const FULL = {
  nps: { enabled: true, hatchery: { enabled: true } },
  dosing: { enabled: true, channels: {} },
  vision: { enabled: true },
  guardian: { enabled: true },
  equipment: {},
  maintenance: { enabled: true, tasks: {}, completions: {} },
};

test("the group bar carries five groups and highlights the active page's group", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await makePanel(structuredClone(FULL));
    panel._activeTab = "awc";
    const bar = panel._tabs();
    for (const label of ["Home", "Water", "Feeding", "Watch", "System"]) {
      assert(bar.includes(label), `group ${label} missing from the bar`);
    }
    assert(!bar.includes('data-id="maintenance"'), "pages must not sit in the top bar any more");
    // Active page's group is highlighted; Home routes straight to Mission.
    assert(/class="active"[^>]*data-id="water"/.test(bar.replace(/\n\s*/g, " ")) || bar.includes('class="active" data-action="tab"\n            data-id="water"') || bar.match(/button class="active"[\s\S]{0,80}data-id="water"/), "Water should be highlighted while on Water Change");
    assert(bar.match(/data-id="mission"/), "Home must route straight to Mission Control");
  } finally { restore(); }
});

test("groups reflect the gates — features join and leave their group", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await makePanel(structuredClone(FULL));
    const pages = (gid) => panel._navGroups().find((g) => g.id === gid).pages.map(([id]) => id);
    assert(pages("feeding").join() === "nps,hatchery,spawning", "Feeding should hold nps, hatchery, spawning");
    assert(pages("watch").includes("vision"), "Vision belongs to Watch when enabled");
    panel._config.vision.enabled = false;
    panel._config.dosing.enabled = false;
    assert(!pages("watch").includes("vision"), "Vision must leave Watch when disabled");
    assert(!pages("water").includes("dosing"), "Dosing must leave Water when disabled");
    assert(pages("water").includes("awc"), "Water Change is always in Water");
  } finally { restore(); }
});

test("hubs render one live card per page and route through data-action tab", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await makePanel(structuredClone(FULL));
    const water = panel._hubTab("water");
    for (const id of ["awc", "dosing", "maintenance", "icp", "manual"]) {
      assert(water.includes(`data-id="${id}"`), `Water hub missing the ${id} card`);
    }
    assert(water.includes("hub-grid"), "hub grid class missing");
    assert(!/undefined|NaN|\[object/.test(water), "Water hub leaked a placeholder");
    const feeding = panel._hubTab("feeding");
    assert(feeding.includes('data-id="hatchery"'), "Feeding hub missing the hatchery card");
    assert(!/undefined|NaN|\[object/.test(feeding), "Feeding hub leaked a placeholder");
    // Dispatcher: a group id renders its hub; home renders Mission directly.
    panel._activeTab = "water";
    assert(panel._activeContent().includes("hub-grid"), "active group id must render its hub");
  } finally { restore(); }
});

test("the second deck shows siblings on a page and hides on hubs", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await makePanel(structuredClone(FULL));
    panel._activeTab = "maintenance";
    const deck = panel._subNav();
    assert(deck.includes('data-id="awc"') && deck.includes('data-id="icp"'), "siblings missing from the second deck");
    assert(/class="active"[\s\S]{0,60}data-id="maintenance"/.test(deck), "current page must be highlighted");
    assert(deck.includes('data-id="water"'), "the crumb back to the hub is missing");
    panel._activeTab = "water";
    assert(panel._subNav() === "", "no second deck on a hub");
  } finally { restore(); }
});

runTests();
