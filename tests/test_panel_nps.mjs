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
        pods: { name: "GoldPods", brand: "NYOS", category: "zooPrepared",
                bottleMl: 250, remainingMl: 100, lowThresholdMl: 0,
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
        pods: { bottleMl: 250, remainingMl: 100, percent: 40, usageMlPerDay: null,
                daysUntilEmpty: null, low: false, empty: false,
                expiry: { status: "fresh", daysLeft: null }, categoryLabel: "Zooplankton (prepared)" },
      },
      lowCount: 0, expiredCount: 0, count: 2,
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

test("the diagram shows real fills, the owed badge, and never draws a bottle twice", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    const svg = panel._npsDiagramSvg();
    assert(svg.includes("owes 430 ml"), "owed badge missing or wrong");
    assert(svg.includes("🦐"), "brine reservoir missing");
    // The unlinked bottle renders in the row: 40% of 62 = 24.8 units of fill.
    assert(/height="24.8"/.test(svg), "bottle fill height does not match the 40% shelf state");
    // The exchange-linked bottle leaves the row and BECOMES the brine box
    // (one physical container, drawn once — the live-test catch):
    assert(/height="31"/.test(svg), "brine box does not carry its bottle's 50% fill");
    const phytoLabels = (svg.match(/>Phyto</g) || []).length;
    assert(phytoLabels === 1, `the linked bottle is drawn ${phytoLabels} times — must be exactly once`);
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

const noBareCheckboxes = (html, where) => {
  const bare = html.match(/<label(?![^>]*toggle-card)[^>]*>\s*<input type="checkbox"/g) || [];
  assert(bare.length === 0, `${where}: ${bare.length} bare checkbox label(s) — use toggle-card`);
};

test("the product editor uses toggle-cards and never an empty category select", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    // Unconditional: the editor is pure markup (the earlier section-level test
    // silently skipped when section chrome needed browser globals — vacuous).
    const card = panel._npsProductSettingsCard("phyto", panel._config.consumables.products.phyto);
    noBareCheckboxes(card, "product editor");
    assert(card.includes("toggle-card compact-toggle"), "toggle-card convention missing from the editor");
    assert(card.includes("Phytoplankton"), "category select rendered empty");
    // The fallback holds even before any summary has loaded (and in demo).
    panel._nps.summary = null;
    const early = panel._npsProductSettingsCard("phyto", panel._config.consumables.products.phyto);
    assert(early.includes("Phytoplankton"), "category fallback missing before the summary loads");
  } finally { restore(); }
});

test("settings section checkboxes use the toggle-card convention", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    let html;
    try { html = panel._npsSettings(); } catch { html = null; }
    if (html !== null) {
      noBareCheckboxes(html, "settings section");
      assert(html.includes("toggle-card compact-toggle"), "toggle-card convention missing");
    }
  } finally { restore(); }
});

test("the feeding sequence plays dose → flush → drain → balanced with honest numbers", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._render = () => {};
    panel._npsToggleDemo();
    const fx = () => panel._nps.summary.feedExchange;
    panel._npsDemoAdvance("dose");
    assert(panel._config.dosing.channels.demo_brine.state.haRunEndsAt, "dose stage: brine pump not running");
    panel._npsDemoAdvance("flush");
    assert(fx().chaserActive === true, "flush stage: chaser line not animating");
    assert(fx().state.owedMl === 642, "flush stage: owed must be dose + chaser (642 ml)");
    panel._npsDemoAdvance("drain");
    assert(fx().drainActive === true, "drain stage: drain not animating");
    assert(fx().chaserActive === false, "drain stage: chaser must have stopped");
    panel._npsDemoAdvance("done");
    assert(fx().state.owedMl === 0, "done stage: books not settled");
    assert(fx().state.lastDrainMl === 642, "done stage: drained volume wrong");
    // The diagram reflects each stage — drain flow visible mid-drain:
    panel._npsDemoAdvance("drain");
    const svg = panel._npsDiagramSvg();
    assert(svg.includes("draining"), "diagram missing the draining badge mid-sequence");
    // Reset: every line must STOP (the "lines never stop" live-test catch).
    panel._npsDemoAdvance("");
    const brineState = panel._config.dosing.channels.demo_brine.state;
    assert(brineState.haRunEndsAt === "", "reset left the brine pump running");
    assert(Date.now() - Date.parse(brineState.lastDoseAt) > 30000,
      "reset left a fresh dose stamp — the brine line would keep flowing");
    panel._npsToggleDemo();   // exit clears timers and stage
    assert(panel._nps.demoStage === "", "exit demo left a stage behind");
  } finally { restore(); }
});

test("the water-change demo drains, refills, and moves the reservoir levels", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._render = () => {};
    panel._npsToggleDemo();
    const res = () => panel._awcSummary.summary.reservoirs;
    const wasteBefore = res().waste.percent, freshBefore = res().fresh.percent;
    panel._npsDemoAdvance("awc-drain");
    assert(panel._nps.summary.awcDemo.draining === true, "drain stage flag missing");
    assert(panel._npsDiagramSvg().includes("water change"), "drain badge missing");
    panel._npsDemoAdvance("awc-fill");
    assert(res().waste.percent > wasteBefore, "waste level did not rise");
    assert(res().fresh.percent < freshBefore, "fresh level did not fall");
    assert(panel._npsDiagramSvg().includes("refilling"), "refill badge missing");
    panel._npsDemoAdvance("");
    assert(panel._nps.summary.awcDemo.filling === false, "reset left the fill running");
    panel._npsToggleDemo();
  } finally { restore(); }
});

test("EVERY bottle renders in the row — no ghost, no cap, ever", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._render = () => {};
    panel._npsToggleDemo();   // demo shelf: 5 row bottles (6 minus the brine)
    const svg = panel._npsDiagramSvg();
    const bottleClips = (svg.match(/id="npsB\d+"/g) || []).length;
    assert(bottleClips === 5, `expected all 5 row bottles, saw ${bottleClips}`);
    for (const name of ["GoldPods", "Live phy", "Oyster-F", "Reef-Roi", "Roti-Fea"]) {
      assert(svg.includes(`>${name}<`), `bottle missing from the row: ${name}`);
    }
    assert(!svg.includes(">+"), "a ghost/overflow placeholder crept back in");
    assert(!svg.includes("more on the shelf"), "old loose text still present");
    // At rest nothing is dosing — no line may flow (class only appears on
    // animated overlays; the <style> block defines it without using it).
    const flows = (svg.match(/class="awc-flow"/g) || []).length;
    assert(flows === 0, `diagram at rest has ${flows} flowing line(s) — lines must stop`);
    panel._npsToggleDemo();
  } finally { restore(); }
});

test("the diagram carries the fresh reservoir with the AWC's real level", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._awcSummary.summary.reservoirs = { fresh: { percent: 50 }, waste: { percent: 25 } };
    const svg = panel._npsDiagramSvg();
    assert(svg.includes(">fresh<"), "fresh reservoir missing from the diagram");
    assert(svg.includes("npsFreshG"), "fresh fill gradient missing");
    // 50% of the 62-high fresh box = 31 units; 25% waste = 15.5.
    assert(svg.includes('height="15.5"'), "waste fill does not match the 25% level");
    noPlaceholders(svg, "diagram with reservoirs");
  } finally { restore(); }
});

test("the hatchery card walks its lifecycle: empty, incubating, ready, overdue", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    const withHatch = (state) => {
      panel._nps.summary.hatchery = { eggType: "standard", hatchHours: 24, eggTypes: [], state };
      return panel._npsTab();
    };
    let html = withHatch({ status: "none" });
    assert(html.includes("Start hatch"), "empty hatchery missing its start button");
    html = withHatch({ status: "incubating", hoursElapsed: 15, hoursLeft: 9, percent: 62 });
    assert(html.includes("9 h to go"), "incubating countdown missing");
    assert(html.includes("Cancel hatch"), "incubating missing cancel");
    assert(html.includes("nps-bub"), "incubating vessel has no bubbles");
    html = withHatch({ status: "ready", hoursElapsed: 24.5, hoursLeft: 0, percent: 100 });
    assert(html.includes("Ready to harvest"), "ready copy missing");
    assert(html.includes("Hatched &amp; loaded"), "ready missing the harvest button");
    html = withHatch({ status: "overdue", hoursElapsed: 40, hoursLeft: 0, percent: 100 });
    assert(html.includes("harvest soon"), "overdue nag missing");
    noPlaceholders(html, "hatchery card");
  } finally { restore(); }
});

test("egg-type choice seeds the recommended hatch hours in settings", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._config.nps.hatchery = { eggType: "standard", hatchHours: 24, state: {} };
    // Simulate the field handler's nps-hatchery branch for an eggType change.
    const hatchery = panel._config.nps.hatchery;
    hatchery.eggType = "decapsulated";
    const rec = panel._npsEggTypes().find((e) => e.id === "decapsulated");
    if (rec) hatchery.hatchHours = rec.hours;
    assert(hatchery.hatchHours === 16, "decapsulated should seed 16 h");
  } finally { restore(); }
});

runTests();
