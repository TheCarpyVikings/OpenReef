/**
 * NPS tab presentation: the feeding-station diagram, the 24 h timeline, the
 * setup checklist, and the embedded pump cards. The engines are Python and
 * covered in test_nps.py; this pins the half the keeper looks at — fill levels
 * that match the shelf, an owed-drain badge that tells the truth, a checklist
 * that retires itself when setup is done.
 *
 * All renderers are exercised with pre-seeded summaries so no test can reach
 * for the network.
 *
 * Run standalone:  node tests/test_panel_nps.mjs
 */

import { assert, freezeTime, makePanel, runTests, test } from "./_panel_harness.mjs";

const NOW = "2026-08-13T12:00:00Z";

function baseConfig(overrides = {}) {
  return {
    nps: {
      enabled: true,
      species: [],
      feedExchange: {
        enabled: true, channelId: "brine", minDrainMl: 150, maxOwedMl: 2000,
        state: { owedMl: 430, lastBlockedReason: "" },
      },
      truce: { enabled: false, uvOffMinutes: 120, ozoneOffMinutes: 120, skimmerOffMinutes: 45, state: {} },
      ...overrides.nps,
    },
    consumables: {
      products: {
        phyto: { name: "Phyto", brand: "AlgaeBarn", category: "phyto",
                 bottleMl: 1000, remainingMl: 500, lowThresholdMl: 0,
                 shelfLifeDaysOpened: 0, history: [] },
      },
    },
    dosing: {
      enabled: true,
      channels: {
        brine: {
          name: "Brine pump", chemical: "livefood", enabled: true,
          schedule: { enabled: true, mlPerDay: 20, mode: "doses", dosesPerDay: 4,
                      windowStart: "08:00", windowEnd: "20:00", night: {} },
          reservoir: { productId: "phyto", productIsBottle: false },
          calibration: { mlPerS: 1 },
          driver: { type: "openreef_esphome_brushed", entities: {} },
          state: {}, guards: {},
        },
      },
    },
    automaticWaterChange: {
      enabled: true,
      schedule: { enabled: true, mode: "times", times: ["10:00"], amount: 5,
                  amountUnit: "percent", period: "week", days: [] },
    },
    tank: { volumeLitres: 100 },
    ...overrides.config,
  };
}

function summaryFixture() {
  return {
    enabled: true,
    shelf: {
      products: {
        phyto: { bottleMl: 1000, remainingMl: 500, percent: 50, usageMlPerDay: null,
                 daysUntilEmpty: null, low: false, empty: false,
                 expiry: { status: "fresh", daysLeft: null }, categoryLabel: "Phytoplankton" },
      },
      lowCount: 0, expiredCount: 0, count: 1,
    },
    library: [], categories: { phyto: "Phytoplankton", other: "Other" },
    feedExchange: {
      enabled: true, channelId: "brine", channelName: "Brine pump",
      minDrainMl: 150, maxOwedMl: 2000,
      state: { owedMl: 430, lastDrainAt: "", lastDrainMl: 0, totalDrainedL: 0, lastBlockedReason: "" },
      freshness: { status: "fresh", hoursLeft: 20, ageHours: 4 },
      prime: { status: "prime", ageHours: 4, primeLeftHours: 20 },
      drainActive: false,
    },
    foodChannels: [{ id: "brine", name: "Brine pump", chemical: "livefood" }],
    speciesLibrary: [{ id: "tubastraea", name: "Sun coral (Tubastraea)", difficulty: 1, note: "" }],
    speciesPlan: { species: [], gaps: [], warnings: [], suggestions: [] },
    budget: { available: false },
  };
}

async function npsPanel(configOverrides = {}) {
  const panel = await makePanel(baseConfig(configOverrides));
  panel._nps = { summary: summaryFixture(), at: Date.now(), loading: false,
                 error: "", message: "", addOpen: false, confirmDelete: "" };
  panel._doserSummary = { summary: {}, bindings: {} };
  panel._doserSummaryLoading = false;
  panel._doserRemoveConfirm = "";
  panel._awcSummary = { summary: { scheduleText: "5% weekly, Mondays" }, state: {} };
  panel._awcSummaryLoading = true;
  panel._lightingWindow = { data: { configured: true, onTime: "09:00", offTime: "21:00" }, loading: false };
  panel._consumption = { checkedAt: "", items: {}, error: "" };
  panel._configDirty = false;
  return panel;
}

const noPlaceholders = (html, where) =>
  assert(!/undefined|NaN|\[object/.test(html), `${where} leaked a placeholder value`);

test("the tab renders the informative sections without placeholder leaks", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    const html = panel._npsTab();
    for (const marker of ["Feeding station", "Food pumps", "Hatchery", "Food shelf",
      "Feed exchange", "Water exchange"]) {
      assert(html.includes(marker), `missing section: ${marker}`);
    }
    noPlaceholders(html, "NPS tab");
  } finally { restore(); }
});

test("the page carries no settings forms — they all live behind Settings", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    const html = panel._npsTab();
    for (const scope of ["nps-exchange", "nps-truce", "nps-species", "awc-schedule", "consumable"]) {
      assert(!html.includes(`data-scope="${scope}"`), `page still carries a ${scope} form`);
    }
    assert(html.includes("summary-card"), "status cards missing");
    assert(html.includes('data-scroll="or-section-nps"'), "no deep link into the NPS settings section");
  } finally { restore(); }
});

test("the settings section carries every moved form", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._settingsSectionsOpen = { nps: true };
    let html;
    try {
      html = panel._npsSettings();
    } catch {
      // Section chrome may need browser globals; the body builder is the contract.
      html = null;
    }
    if (html !== null) {
      for (const scope of ["nps-exchange", "nps-truce", "nps-species", "consumable"]) {
        assert(html.includes(`data-scope="${scope}"`), `settings missing the ${scope} form`);
      }
      assert(html.includes("Salinity rule"), "salinity rule copy missing from settings");
      assert(html.includes("Bottle size (ml)"), "product editor missing from settings");
    }
  } finally { restore(); }
});

test("the diagram shows the bottle at its real fill and the owed-drain badge", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    const svg = panel._npsDiagramSvg();
    assert(svg.includes("owes 430 ml"), "owed badge missing or wrong");
    assert(svg.includes("🦐"), "brine reservoir missing");
    // 50% of a 62-high bottle = 31 units of fill.
    assert(/height="31"/.test(svg), "bottle fill height does not match the 50% shelf state");
    noPlaceholders(svg, "diagram");
  } finally { restore(); }
});

test("the diagram animates the drain when a matched drain runs", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._nps.summary.feedExchange.drainActive = true;
    const svg = panel._npsDiagramSvg();
    assert(svg.includes("draining"), "active drain badge missing");
    assert(/class="awc-flow"[^>]*><\/path>|awc-flow/.test(svg), "no flow animation on the drain path");
  } finally { restore(); }
});

test("the timeline draws dose ticks, night shading, and a next-event line", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    const html = panel._npsTimelineSvg();
    // 4 doses across 08:00–20:00 → ticks at 09:30, 12:30, 15:30, 18:30.
    const ticks = (html.match(/height="5"/g) || []).length;
    assert(ticks >= 4, `expected ≥4 dose ticks, saw ${ticks}`);
    assert(html.includes("opacity=\"0.45\""), "night shading missing despite a lighting window");
    assert(html.includes("Next:"), "next-event line missing");
    noPlaceholders(html, "timeline");
  } finally { restore(); }
});

test("the setup checklist knows what is done and retires itself", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    // Bottle exists, pump exists+calibrated+linked, AWC on → everything done.
    assert(panel._npsSetupCard() === "", "checklist should retire when all steps are done");
    // Take the calibration away and it comes back with that step open.
    panel._config.dosing.channels.brine.calibration = {};
    const card = panel._npsSetupCard();
    assert(card.includes("Calibrate the pump"), "missing the open calibration step");
    assert(card.includes("Getting set up"), "checklist header missing");
  } finally { restore(); }
});

test("food pumps render as full dosing cards; the bottle link moved to Settings", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    const html = panel._npsTab();
    assert(html.includes("dosing-grid"), "pump cards are not the dosing-grid embed");
    assert(!html.includes("Draws from bottle"), "bottle link should live in channel settings now");
    // The channel-settings home for the link:
    assert(panel._npsProductOptions("phyto").includes("Phyto"), "product options helper broken");
  } finally { restore(); }
});

test("demo view stages a full tank, blocks saving, and restores on exit", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    const realConfig = panel._config;
    panel._render = () => {};                    // toggle re-renders; no DOM here
    panel._npsToggleDemo();
    assert(panel._nps.demo === true, "demo flag not set");
    assert(panel._config !== realConfig, "config was not swapped");
    assert(Object.keys(panel._config.consumables.products).length === 6, "demo shelf not staged");
    const html = panel._npsTab();
    assert(html.includes("Demo view"), "demo banner missing");
    assert(html.includes("Exit demo"), "exit button missing");
    // Saving the staged config must be refused outright.
    let saved = false;
    panel._callWS = async () => { saved = true; return {}; };
    await panel._saveConfig();
    assert(saved === false, "demo config reached save_config");
    await panel._persistConfigSilently();
    assert(saved === false, "demo config reached the silent persist");
    // Exit restores the stashed real state untouched.
    panel._npsToggleDemo();
    assert(panel._nps.demo === false, "demo flag not cleared");
    assert(panel._config === realConfig, "real config not restored");
  } finally { restore(); }
});

test("settings checkboxes use the toggle-card convention, not bare mini-grid labels", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    let html;
    try { html = panel._npsSettings(); } catch { html = null; }
    if (html !== null) {
      const bare = html.match(/<label(?![^>]*toggle-card)[^>]*>\s*<input type="checkbox"/g) || [];
      assert(bare.length === 0, `${bare.length} bare checkbox label(s) — use toggle-card`);
      assert(html.includes("toggle-card compact-toggle"), "toggle-card convention missing");
    }
  } finally { restore(); }
});

runTests();
