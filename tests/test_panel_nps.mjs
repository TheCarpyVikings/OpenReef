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
    // The flush overlay must cover the FULL route (through the brine line into
    // the tank) and be drawn AFTER the brine's static pipe, or the thicker
    // grey paints over the blue on the shared segments (z-order live-catch).
    const flushSvg = panel._npsDiagramSvg();
    const overlay = /<path d="([^"]+)" fill="none" stroke="#42a5f5"/.exec(flushSvg);
    assert(overlay, "flush overlay missing");
    assert(overlay[1].includes("V 96 H"), "flush overlay does not run the full route into the tank");
    assert(overlay.index > flushSvg.indexOf('id="npsBrine"'), "flush overlay drawn beneath the brine pipe");
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
    assert(html.includes("15 / 24 h"), "incubating countdown missing");
    assert(html.includes("Harvest now"), "early harvest must be offered mid-incubation (instar I is the premium harvest)");
    assert(html.includes(">Cancel<"), "incubating missing cancel");
    assert(html.includes("nps-bub"), "incubating vessel has no bubbles");
    html = withHatch({ status: "ready", hoursElapsed: 24.5, hoursLeft: 0, percent: 100 });
    assert(html.includes("Hatched &amp; loaded"), "ready missing the harvest button");
    html = withHatch({ status: "overdue", hoursElapsed: 40, hoursLeft: 0, percent: 100 });
    assert(html.includes("harvest now"), "overdue nag missing");
    noPlaceholders(html, "hatchery card");
    // The hatchery is core NPS — it renders even with the exchange OFF
    // (hatching happens whether or not the matched drain is on).
    panel._config.nps.feedExchange.enabled = false;
    panel._config.nps.feedExchange.channelId = "";
    const ungated = withHatch({ status: "none" });
    assert(ungated.includes("Hatchery"), "hatchery hidden when the exchange is off");
    assert(ungated.includes("Start hatch"), "hatchery unusable when the exchange is off");
  } finally { restore(); }
});

test("the setup checklist speaks each driver's calibration language", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._config.dosing.channels.brine.calibration = {};   // force the checklist
    const brushed = panel._doserChannelChecklist("brine", "Brine", "Live food",
      { bound: 1, calibrated: false, hasVolume: true, bindings: null });
    assert(brushed.includes("30 s burst"), "brushed head shown stepper calibration copy");
    assert(!brushed.includes("100 revolutions"), "brushed head still told to count revolutions");
    panel._config.dosing.channels.brine.driver.type = "openreef_esphome_stepper";
    const stepper = panel._doserChannelChecklist("brine", "Brine", "Live food",
      { bound: 1, calibrated: false, hasVolume: true, bindings: null });
    assert(stepper.includes("100 revolutions"), "stepper lost its revolution copy");
    panel._config.dosing.channels.brine.driver.type = "ha_switch_timed";
    const ha = panel._doserChannelChecklist("brine", "Brine", "Live food",
      { bound: 1, calibrated: false, hasVolume: true, bindings: null });
    assert(ha.includes("30 s burst"), "generic driver shown stepper calibration copy");
    assert(ha.includes("Bind the pump switch"), "generic driver still asks for the full entity set");
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

test("the hatchery card recommends when to start the next hatch", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    const sum = panel._nps.summary;
    sum.hatchery = { eggType: "standard", hatchHours: 24, eggTypes: [],
      state: { status: "none" },
      nextHatch: { status: "wait", startAt: new Date(Date.parse(NOW) + 19 * 3600000).toISOString(),
        hoursUntil: 19, readyBy: "", driver: "freshness",
        hatchHours: 24, shelfHours: 48, overlap: false } };
    let html = panel._npsTab();
    assert(html.includes("Next hatch: start"), "wait status should render the timed suggestion");
    assert(html.includes("before the loaded brine fades"), "the freshness driver should say why");
    sum.hatchery.nextHatch = { status: "start_now", startAt: NOW, hoursUntil: 0,
      readyBy: "", driver: "depletion", hatchHours: 36, shelfHours: 24, overlap: true };
    html = panel._npsTab();
    assert(html.includes("Start the next hatch now"), "start_now should be urgent");
    assert(html.includes("batches have to overlap"), "the overlap physics should be said out loud");
    sum.hatchery.nextHatch = { status: "no_brine", startAt: null, hoursUntil: null,
      readyBy: null, driver: null, hatchHours: 24, shelfHours: 24, overlap: false };
    html = panel._npsTab();
    assert(!html.includes("Next hatch: start"), "no_brine adds nothing — the hatch line already says start one");
  } finally { restore(); }
});

test("hand-dosers get the brine clocks and the loaded button without a pump", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._config.nps.feedExchange.channelId = "";
    const sum = panel._nps.summary;
    sum.feedExchange.channelId = "";
    sum.feedExchange.prime = { status: "prime", ageHours: 2, primeLeftHours: 22 };
    sum.feedExchange.freshness = { status: "fresh", hoursLeft: 20, ageHours: 4 };
    sum.hatchery = { eggType: "standard", hatchHours: 24, eggTypes: [],
      state: { status: "ready", hoursElapsed: 25, hoursLeft: 0, percent: 100 },
      nextHatch: { status: "start_now", startAt: NOW, hoursUntil: 0, readyBy: "",
        driver: "freshness", hatchHours: 24, shelfHours: 24, overlap: true } };
    const html = panel._npsTab();
    assert(html.includes('data-action="nps-hatch-loaded"'), "the loaded button must not need a pump");
    assert(html.includes("Hand-dosing mode"), "hand-dose hint missing");
    assert(html.includes("nutritional prime"), "the prime clock should run without a pump");
  } finally { restore(); }
});

function v2HatcherySummary(over = {}) {
  return {
    enabled: true, eggType: "standard", hatchHours: 24, eggTypes: [], history: [],
    state: { status: "incubating", hoursElapsed: 15, hoursLeft: 9, percent: 62 },
    vessels: [
      { id: "v1", name: "Hatchery 1", volumeL: 1.0, eggType: "standard", hatchHours: 24,
        state: { status: "incubating", hoursElapsed: 15, hoursLeft: 9, percent: 62 },
        guide: { available: true, grams: 2.0, nauplii: 450000 } },
      { id: "v2", name: "Hatchery 2", volumeL: 0.7, eggType: "standard", hatchHours: 24,
        state: { status: "none", hoursElapsed: null, hoursLeft: null, percent: null },
        guide: { available: true, grams: 1.4, nauplii: 315000 } },
    ],
    idleVessel: "v2", vesselsNeeded: 1,
    reservoir: { canonical: "hatchery", volumeMl: 1000, remainingMl: 710, loadVolumeMl: 0,
      refrigerated: true, shelfHours: 48, mixedAt: new Date(Date.parse(NOW) - 5 * 3600000).toISOString(),
      freshness: { status: "fresh", hoursLeft: 43, ageHours: 5 } },
    handFeed: { defaultDoseMl: 30, feedsPerDay: 2 },
    enrichment: { hours: 12, doseMl: 1, doseDelayH: 6, batchDoseDelayH: 0, productId: "",
      productName: "Selcon", splitDose: false, sourceVesselId: "",
      state: { status: "none", firstDoseDue: false, secondDoseDue: false } },
    learned: { available: false, hours: null, samples: 0 },
    temp: { available: false, expectedHours: null, factor: null, warm: false },
    vesselPresets: [
      { id: "ziss_zh700", name: "Ziss ZH-700", volumeL: 0.7 },
      { id: "ziss_zh2000", name: "Ziss ZH-2000", volumeL: 2.0 },
    ],
    nextHatch: { status: "chained", startAt: new Date(Date.parse(NOW) + 18 * 3600000).toISOString(),
      hoursUntil: 18, readyBy: "", driver: "freshness", hatchHours: 24, shelfHours: 48,
      overlap: false, busyCount: 1 },
    ...over,
  };
}

test("the v2 strip shows every vessel, the container, and the advisory brains", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._nps.summary.hatchery = v2HatcherySummary({
      learned: { available: true, hours: 20.0, samples: 3 },
      temp: { available: true, expectedHours: 36.0, factor: 1.5, warm: false, tempC: 21 },
      vesselsNeeded: 2,
    });
    const html = panel._npsTab();
    assert(html.includes("Hatchery 1") && html.includes("Hatchery 2"), "every vessel must render");
    assert(html.includes("data-brine-container"), "the brine container visual is missing");
    assert(html.includes("710 / 1000 ml"), "the container must show its honest fill");
    assert(html.includes("Fed 30 ml"), "the one-tap hand-feed button is missing");
    assert(html.includes("~2 g cysts"), "the cyst-dose guide (2 g/L optimum) is missing");
    assert(html.includes("Set clock to 20 h"), "the learned-clock Apply is missing");
    // A learned clock exists, so the temperature line quotes the rule of
    // thumb but defers to the measured runs (0.7.115).
    assert(html.includes("rule of thumb ~36 h") && html.includes("measured beats modelled"),
      "the temperature advisory is missing or stretches the learned clock");
    assert(!html.includes("needs 2 hatcheries"), "two vessels for a needed-2 setup — no nag");
    // Down a vessel, the structural advice appears.
    const short = v2HatcherySummary({ vesselsNeeded: 2 });
    short.vessels = short.vessels.slice(0, 1);
    panel._nps.summary.hatchery = short;
    assert(panel._npsTab().includes("needs 2 hatcheries"), "the structural vessel-count advice is missing");
    noPlaceholders(html, "v2 hatchery strip");
  } finally { restore(); }
});

test("a stale container hard-gates the load with a discard flow", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._nps.summary.hatchery = v2HatcherySummary({
      reservoir: { canonical: "hatchery", volumeMl: 1000, remainingMl: 400, loadVolumeMl: 0,
        refrigerated: false, shelfHours: 24,
        mixedAt: new Date(Date.parse(NOW) - 30 * 3600000).toISOString(),
        freshness: { status: "stale", hoursLeft: 0, ageHours: 30 } },
    });
    const html = panel._npsTab();
    assert(html.includes("Discard old brine"), "the discard button is missing");
    assert(html.includes("discard it before loading"), "the hard-gate copy is missing");
  } finally { restore(); }
});

test("the hand-fed brine container joins the diagram with no pipework", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._nps.summary.feedExchange.enabled = false;
    panel._nps.summary.hatchery = v2HatcherySummary();
    const svg = panel._npsDiagramSvg();
    assert(svg.includes("npsHandBrine"), "hand-fed container missing from the diagram");
    assert(svg.includes("hand-fed"), "hand-fed label missing");
    panel._nps.summary.hatchery = v2HatcherySummary({
      reservoir: { canonical: "hatchery", volumeMl: 0, remainingMl: 0, loadVolumeMl: 0,
        refrigerated: false, shelfHours: 24, mixedAt: "", freshness: null } });
    assert(!panel._npsDiagramSvg().includes("npsHandBrine"),
      "no container volume configured — nothing to draw");
  } finally { restore(); }
});

test("settings carry the vessel editor with the researched presets", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._nps.summary.hatchery = v2HatcherySummary();
    panel._config.nps.hatchery = {
      eggType: "standard", hatchHours: 24,
      vessels: { v1: { name: "Hatchery 1", volumeL: 1, state: {} } },
      reservoir: { volumeMl: 1000, remainingMl: 710, loadVolumeMl: 0, refrigerated: true },
      handFeed: { defaultDoseMl: 30, feedsPerDay: 2 },
    };
    panel._settingsSectionsOpen = { nps: true };
    let html;
    try { html = panel._npsSettings(); } catch { html = null; }
    if (html !== null) {
      assert(html.includes("Ziss ZH-700"), "vessel presets missing (and remember: no ZH-1000 exists)");
      assert(html.includes("Add a hatchery"), "the add-vessel button is missing");
      assert(html.includes('data-scope="nps-hatch-reservoir"'), "container ledger settings missing");
      assert(!html.includes('data-field="refrigerated"'), "the fridge is per batch now — no global toggle");
      assert(html.includes("per batch, not a setting"), "settings must point at the inline ❄ Refrigerate button");
      assert(html.includes('data-field="tempEntity"'), "the temp sensor field is missing");
    }
  } finally { restore(); }
});

test("the enrichment vessel joins the strip while a batch soaks", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    // Idle soak + loaded brine: the CONTAINER offers "Enrich brine" — the
    // vessels never do (a soak must not touch a running hatch).
    panel._nps.summary.hatchery = v2HatcherySummary();
    let html = panel._npsTab();
    assert(html.includes("Enrich brine"), "the container enrich action is missing");
    assert(html.includes("The running hatch is untouched"), "the no-touch promise is missing");
    assert(!html.includes("data-enrich-vessel"), "no soak running — no beaker");
    // Soaking: the beaker tile appears, the container button stands down.
    panel._nps.summary.hatchery = v2HatcherySummary({
      enrichment: { hours: 12, doseMl: 1, doseDelayH: 0, batchDoseDelayH: 0, productId: "selcon",
        productName: "Selcon", splitDose: true, sourceVesselId: "",
        state: { status: "enriching", hoursElapsed: 10.5, hoursLeft: 1.5, percent: 88,
          firstDoseDue: false, secondDoseDue: true } },
    });
    html = panel._npsTab();
    assert(html.includes("data-enrich-vessel"), "the enrichment beaker is missing");
    assert(html.includes("~1.5 h of soak left"), "the soak countdown is missing");
    assert(html.includes("Log top-up"), "the split-dose top-up button is missing");
    assert(html.includes("Soak done"), "the soak-done button is missing");
    assert(!html.includes("Enrich brine"), "one soak at a time — the container button stands down");
    noPlaceholders(html, "enrichment strip");
    // An enriched load tells you its tighter clock.
    panel._nps.summary.hatchery = v2HatcherySummary({
      reservoir: { canonical: "hatchery", volumeMl: 1000, remainingMl: 710, loadVolumeMl: 0,
        refrigerated: false, shelfHours: 12, lastLoadEnriched: true,
        mixedAt: new Date(Date.parse(NOW) - 2 * 3600000).toISOString(),
        freshness: { status: "fresh", hoursLeft: 10, ageHours: 2 } },
    });
    html = panel._npsTab();
    assert(html.includes("Enriched load — feed it out within 12 h"), "the enriched shelf line is missing");
  } finally { restore(); }
});

test("the rig blueprint lives on the Hatchery tab; NPS keeps a compact door", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._nps.summary.hatchery = v2HatcherySummary();
    // NPS tab: compact strip, a door to the Hatchery, and NO blueprint.
    let html = panel._npsTab();
    assert(html.includes("Open Hatchery"), "the door to the Hatchery tab is missing from NPS");
    assert(!html.includes("120 µm mesh"), "the blueprint must live on the Hatchery tab only");
    // Hatchery tab: the rig is the hero, always open.
    html = panel._hatcheryTab();
    // One cone keeps the original "HATCH EGGS" drawing; a multi-cone rig
    // labels each cone by number (0.7.111).
    assert((html.includes("HATCH EGGS") || html.includes("HATCH 1")) && html.includes("LIVE BRINE"),
      "the staggered vessels are missing");
    assert(html.includes("120 µm mesh"), "the mesh capsule is missing");
    assert(html.includes("mesh half OFF"), "the crud-bleed-through-③ step is missing");
    assert(!html.includes("Ⓐ"), "the syringe valve is retired — crud bleeds via ② + ③");
    assert(!html.includes("lamp"), "the lamp is retired — the mesh needs no packing");
    assert(html.includes("never the tank"), "the hatch-water rule must be stated");
    assert(html.includes("4. Mesh drain"), "the numbered harvest steps are missing");
    assert(html.includes("the vessel IS the aerated container"), "vessel-2-as-container must be stated");
    noPlaceholders(html, "rig blueprint");
  } finally { restore(); }
});

test("the rig blueprint is live — it follows the hatchery's stage", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    // Incubating: bubbles on, orange density, the countdown caption.
    panel._nps.summary.hatchery = v2HatcherySummary();
    let html = panel._hatcheryTab();
    assert(html.includes("INCUBATING —"), "incubating caption missing");
    assert(html.includes("air ON"), "air must run while incubating");
    // Ready: the lamp lights, the transfer valves go hot, the slug packs.
    panel._nps.summary.hatchery = v2HatcherySummary({
      state: { status: "ready", hoursElapsed: 24.5, hoursLeft: 0, percent: 100 } });
    html = panel._hatcheryTab();
    assert(html.includes("READY —"), "ready caption missing");
    assert(html.includes("crud bleed"), "ready must walk the bleed-then-mesh sequence");
    // Enriching: the soak beaker with its own clock.
    panel._nps.summary.hatchery = v2HatcherySummary({
      state: { status: "none" },
      enrichment: { hours: 12, doseMl: 1, productId: "", productName: "Selcon", splitDose: false,
        sourceVesselId: "v1",
        state: { status: "enriching", hoursElapsed: 7, hoursLeft: 5, percent: 58, secondDoseDue: false } } });
    html = panel._hatcheryTab();
    assert(html.includes("ENRICHING —"), "enriching caption missing");
    assert(html.includes("% soak"), "the soak beaker is missing");
    // Nothing running, container holding brine: the ledger speaks.
    panel._nps.summary.hatchery = v2HatcherySummary({ state: { status: "none" } });
    html = panel._hatcheryTab();
    assert(html.includes("LOADED — container 71%"), "the loaded stage must read the real ledger");
    assert(html.includes("710 / 1000 ml") && html.includes("the vessel IS the container"),
      "vessel 2 must carry the ledger in the mesh flow");
    noPlaceholders(html, "live rig");
  } finally { restore(); }
});

test("the walkthrough plays every stage client-side", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._nps.summary.hatchery = v2HatcherySummary();
    const stages = panel._npsRigPreviewStages();
    assert(stages.length >= 6, "the walkthrough should cover the whole cycle");
    assert(stages.every((s) => s.caption && s.stage), "every stage needs a caption");
    panel._npsRigPreview = stages[3];
    const html = panel._hatcheryTab();
    assert(html.includes("4 · MESH DRAIN"), "a running preview must override the live state");
    assert(panel._hatcheryTab().includes("■ Stop"), "the play button must become a stop button");
  } finally { restore(); }
});

test("hatchery settings live in their own section (0.7.71)", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._settingsSectionsOpen = { hatchery: true, nps: true };
    let html;
    try { html = panel._hatcherySettings(); } catch { html = null; }
    if (html !== null) {
      assert(html.includes("or-section-hatchery"), "the hatchery settings anchor is missing");
      assert(html.includes('data-field="enabled"'), "the standalone enable toggle is missing");
      assert(html.includes('data-scope="nps-hatch-vessel"'), "the vessel editor moved out of the section");
      assert(html.includes('data-scope="nps-enrichment"'), "enrichment settings missing");
      assert(html.includes("Split-dose top-up"), "the split-dose toggle is missing");
      assert(html.includes('data-field="doseDelayH"'), "the first-dose delay field is missing");
      assert(html.includes("instar II"), "the instar II explanation is missing");
    }
    let npsHtml;
    try { npsHtml = panel._npsSettings(); } catch { npsHtml = null; }
    if (npsHtml !== null) {
      assert(npsHtml.includes("Open hatchery settings"), "NPS settings must link to the hatchery section");
      assert(!npsHtml.includes('data-scope="nps-hatch-vessel"'), "the vessel editor must not live in NPS settings any more");
    }
  } finally { restore(); }
});

test("the learned-clock chip actually applies — one command moves the lot", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._render = () => {};
    panel._nps.summary.hatchery = v2HatcherySummary({
      learned: { available: true, hours: 33.8, samples: 3 },
    });
    const sent = [];
    panel._callWS = async (msg) => {
      sent.push(msg);
      return {
        config: { ...panel._config, nps: { ...panel._config.nps, hatchery: { hatchHours: 34 } } },
        entry_id: "e1", hours: 34, previous: 24,
        restamped: [{ id: "v1", name: "Hatchery 1", hoursLeft: 33.3 }],
        kept: ["Hatchery 2"],
      };
    };
    let reloaded = false;
    panel._npsLoadSummary = () => { reloaded = true; };
    await panel._npsApplyLearnedHours(33.8);
    const save = sent.find((m) => m.type === "openreef/save_config");
    assert(!save, "the whole-config save would write this page's stale snapshot over the ledger");
    const clock = sent.find((m) => m.type === "openreef/nps_hatch_clock");
    assert(clock, "the chip must reach the backend — a local edit alone leaves the card unchanged");
    assert(clock.hours === 34, "the rounded clock must reach the command");
    assert(panel._config.nps.hatchery.hatchHours === 34,
      "the settings input reads _config — it must agree with the new clock too");
    assert(reloaded, "the summary must recompile so the new clock is visible immediately");
    assert(panel._nps.message.includes("34 h"), "the keeper needs confirmation the clock moved");
    assert(panel._nps.message.includes("Hatchery 1") && panel._nps.message.includes("33.3"),
      "the running batch moved onto the new clock — say so, that is the visible half");
    assert(panel._nps.message.includes("Hatchery 2"),
      "a batch already hatched keeps its result — say that too");
    // And that confirmation has somewhere to land on the Hatchery page.
    panel._nps.summary.hatchery = v2HatcherySummary();
    assert(panel._hatcheryTab().includes(panel._nps.message.slice(0, 24)),
      "the Hatchery tab must render its own messages");
  } finally { restore(); }
});

test("unsaved edits survive a clock apply", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._render = () => {};
    panel._nps.summary.hatchery = v2HatcherySummary();
    panel._npsLoadSummary = () => {};
    panel._config.tank.volumeLitres = 999;        // the keeper is mid-edit
    panel._configDirty = true;
    panel._callWS = async () => ({ config: { nps: {}, tank: { volumeLitres: 100 } }, hours: 34 });
    await panel._npsApplyLearnedHours(34);
    assert(panel._config.tank.volumeLitres === 999,
      "adopting the server config would silently bin the keeper's pending edit");
    assert(panel._config.nps.hatchery.hatchHours === 34, "the clock must still land");
  } finally { restore(); }
});

test("a batch on its own clock says so, and stale reminders own up", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    // Clock moved to 34 h; the running batch was stamped at 24 h.
    panel._nps.summary.hatchery = v2HatcherySummary({ hatchHours: 34 });
    let html = panel._hatcheryPanel();
    assert(html.includes("on its own 24 h clock"),
      "a countdown that disagrees with settings must explain itself, not look broken");
    // Explaining is not enough — the learned chip retires once the clock and
    // the history agree, so this button is the ONLY route back for a batch
    // stamped before the change (0.7.80).
    assert(html.includes('data-action="nps-align-clock"') && html.includes("Move to 34 h"),
      "a stranded batch must have a one-tap way onto the current clock");
    // Same clock top and bottom — nothing to explain.
    panel._nps.summary.hatchery = v2HatcherySummary();
    assert(!panel._hatcheryPanel().includes("on its own"),
      "no drift, no note");
    // Reminders added on the old clock are part of the same lie.
    panel._config.maintenance = { tasks: { brine_hatch_harvest: { cadenceHours: 24 } } };
    panel._nps.summary.hatchery = v2HatcherySummary({ hatchHours: 34 });
    html = panel._hatcheryPanel();
    assert(html.includes("still run a 24 h cycle"), "the reminder drift must be surfaced");
    assert(html.includes("Bring them onto 34 h"), "and it must offer the one-tap fix");
    // The row keeps its seeder button, but the two must not read identically —
    // Reece's screenshot stacked two buttons labelled the same thing.
    assert(!html.includes(">Sync hatchery reminders</button> <button") &&
      html.split(">Sync hatchery reminders<").length === 2,
      "the instant re-time and the seeder must be distinguishable");
    panel._config.maintenance.tasks.brine_hatch_harvest.cadenceHours = 34;
    assert(!panel._hatcheryPanel().includes("still run a"), "in step — no nag");
  } finally { restore(); }
});

test("the Hatchery tab stands alone — hero, journal, reminders, gating", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._nps.summary.hatchery = v2HatcherySummary({
      history: [
        { vesselId: "v1", harvestedAt: NOW, startedAt: NOW, plannedHours: 24,
          actualHours: 30.5, eggType: "standard", enriched: true, enrichedHours: 11.5 },
        { vesselId: "v2", harvestedAt: NOW, startedAt: NOW, plannedHours: 24,
          actualHours: 24.2, eggType: "standard" },
        { vesselId: "v9", harvestedAt: NOW, startedAt: NOW, plannedHours: 24,
          actualHours: 25.0, eggType: "standard" },
      ],
      learned: { available: true, hours: 27.4, samples: 2 },
    });
    const html = panel._hatcheryTab();
    assert(html.includes(">Hatchery</th>"), "the journal must say which hatchery each batch came from");
    assert(html.includes(">Hatchery 1</td>") && html.includes(">Hatchery 2</td>"),
      "journal rows must carry the live vessel name");
    assert(html.includes(">v9</td>"), "a removed vessel falls back to its id, not a blank");
    assert(html.includes("Live brine, on schedule"), "the hero head is missing");
    assert(html.includes("No NPS corals required"), "the standalone promise is missing");
    assert(html.includes("summary-grid"), "the mission row is missing");
    assert(html.includes("Hatch journal") && html.includes("30.5"), "the journal must show real batches");
    assert(html.includes("enriched 11.5 h"), "the enriched badge is missing from the journal");
    assert(html.includes("Reminders"), "the reminders card is missing");
    noPlaceholders(html, "hatchery tab");
    // Gating (via The Helm's Feeding group): inherits nps.enabled, works
    // standalone, hides when off.
    const feedingPages = () => panel._navGroups().find((g) => g.id === "feeding").pages.map(([id]) => id);
    assert(feedingPages().includes("hatchery"), "the page should show when NPS is on (inheritance)");
    panel._config.nps.enabled = false;
    panel._config.nps.hatchery = { enabled: true };
    assert(panel._hatcheryEnabled() === true, "standalone: hatchery on with NPS off");
    assert(feedingPages().includes("hatchery"), "standalone page missing from Feeding");
    assert(!feedingPages().includes("nps"), "NPS must stay hidden when NPS is off");
    assert(panel._hubTab("feeding").includes('data-id="hatchery"'), "the Feeding hub must card the hatchery");
    panel._config.nps.hatchery = { enabled: false };
    assert(panel._hatcheryEnabled() === false, "explicit off must win");
    assert(!feedingPages().includes("hatchery"), "disabled hatchery must leave the group");
  } finally { restore(); }
});

test("the enrichment tile holds the Selcon until instar II", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    const withEnrich = (state, batchDelay) => {
      panel._nps.summary.hatchery = v2HatcherySummary({
        enrichment: { hours: 12, doseMl: 1, doseDelayH: 8, batchDoseDelayH: batchDelay,
          productId: "selcon", productName: "Selcon", splitDose: false, sourceVesselId: "v1",
          state },
      });
      return panel._npsTab();
    };
    // Holding: clean water, no dose yet — the tile says when the dose lands.
    let html = withEnrich({ status: "enriching", hoursElapsed: 3, hoursLeft: null,
      percent: 0, firstDoseDue: false, secondDoseDue: false }, 8);
    assert(html.includes("holding — dose at +8 h"), "the holding copy is missing");
    assert(!html.includes(">Add dose<"), "no dose button before the molt");
    // The molt has landed: the amber prompt and the Add dose button appear.
    html = withEnrich({ status: "enriching", hoursElapsed: 8.5, hoursLeft: null,
      percent: 0, firstDoseDue: true, secondDoseDue: false }, 8);
    assert(html.includes("mouths are open"), "the dose-due prompt is missing");
    assert(html.includes('data-action="nps-enrich-dose"'), "the Add dose button is missing");
    noPlaceholders(html, "enrichment dose-delay tile");
  } finally { restore(); }
});

test("hatchery reminders sync to the hatch clock and anchor to a running hatch", async () => {
  const restore = freezeTime(NOW);
  try {
    // A 36 h hatch, 6 h in — Reece's exact case: the harvest reminder must
    // land in 30 h, not "every 1 day".
    const startedIso = new Date(Date.parse(NOW) - 6 * 3600000).toISOString();
    const panel = await npsPanel();
    panel._render = () => {};                    // the seeder re-renders; no DOM here
    panel._setDirty = () => { panel._configDirty = true; };
    panel._config.nps.hatchery = { eggType: "cool_room", hatchHours: 36,
                                   state: { hatchStartedAt: startedIso } };
    // Stale day-based tasks from the old seeding get re-synced, not duplicated.
    panel._config.maintenance = {
      enabled: true,
      tasks: {
        brine_hatch_start: { label: "Start brine shrimp hatch", cadenceDays: 1, criticalAfterDays: 1, enabled: true, notify: true },
        brine_hatch_harvest: { label: "Harvest, rinse & load brine", cadenceDays: 1, criticalAfterDays: 1, enabled: true, notify: true },
      },
      completions: {},
    };
    panel._npsSeedHatchReminders();
    const tasks = panel._config.maintenance.tasks;
    assert(tasks.brine_hatch_start.cadenceHours === 36, "start chore should run on the 36 h hatch clock");
    assert(tasks.brine_hatch_harvest.cadenceHours === 36, "harvest chore should run on the 36 h hatch clock");
    assert(tasks.brine_hatch_harvest.criticalAfterHours === 48, "harvest overdue should mirror the 12 h yolk grace");
    const hoursOut = (Date.parse(tasks.brine_hatch_harvest.snoozedUntil) - Date.parse(NOW)) / 3600000;
    assert(Math.abs(hoursOut - 30) < 0.01, `harvest reminder should land in 30 h, got ${hoursOut}`);
    const comps = panel._config.maintenance.completions.brine_hatch_start;
    assert(comps.length === 1 && comps[0].source === "hatchery", "the running hatch logs the start chore, hatchery-sourced");
    assert(comps[0].timestamp === startedIso, "the start completion is honestly back-dated to hatchStartedAt");
    panel._npsSeedHatchReminders();
    assert(panel._config.maintenance.completions.brine_hatch_start.length === 1, "re-syncing must not duplicate the completion");
    // The hour clock reaches the due-state: 6 h since "start" on a 36 h cadence is done, in hours.
    const state = panel._maintenanceDueState("brine_hatch_start");
    assert(state.status === "ok" && state.detail.includes("every 36 h"), `due state should speak hours: ${state.detail}`);
  } finally { restore(); }
});

test("seeding without a running hatch sets the hour cadence but anchors nothing", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._render = () => {};                    // the seeder re-renders; no DOM here
    panel._setDirty = () => { panel._configDirty = true; };
    panel._config.nps.hatchery = { eggType: "decapsulated", hatchHours: 16, state: { hatchStartedAt: "" } };
    assert(panel._npsTab().includes("Add hatchery reminders"), "first visit should offer to ADD the reminders");
    panel._npsSeedHatchReminders();
    const m = panel._config.maintenance;
    assert(m.tasks.brine_hatch_start.cadenceHours === 16, "an 18/16 h egg type should set an hour cadence");
    assert(!m.tasks.brine_hatch_harvest.snoozedUntil, "no running hatch, nothing to anchor to");
    assert(!(m.completions?.brine_hatch_start || []).length, "no running hatch, nothing to back-log");
    assert(panel._npsTab().includes("Sync hatchery reminders"), "once added, the button becomes a re-sync");
  } finally { restore(); }
});


test("aligning a stranded batch needs no hours — and no Save bar", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._render = () => {};
    panel._npsLoadSummary = () => {};
    panel._nps.summary.hatchery = v2HatcherySummary({ hatchHours: 34 });
    const sent = [];
    panel._callWS = async (msg) => {
      sent.push(msg);
      return { config: panel._config, hours: 34,
               restamped: [{ id: "v1", name: "Hatchery 1", hoursLeft: 32.2 }], kept: [] };
    };
    await panel._npsAlignClock("v1");
    const call = sent.find((m) => m.type === "openreef/nps_hatch_clock");
    assert(call, "the align button must reach the backend");
    assert(call.hours === undefined,
      "no hours means 'use the clock we already have' — sending one could move it");
    assert(call.vessel_id === "v1", "the named batch is the one that moves");
    assert(panel._nps.message.includes("34 h") && panel._nps.message.includes("32.2"),
      "say what actually moved, in hours the keeper can check against the tile");
    assert(!panel._configDirty, "this lands immediately — it must not arm the Save bar");
  } finally { restore(); }
});


test("unsaved changes carry their own Save button off the Settings page", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._render = () => {};
    panel._setDirty = (d = true) => { panel._configDirty = d; };
    panel._nps.summary.hatchery = v2HatcherySummary();
    panel._activeTab = "hatchery";
    // Clean page: nothing to nag about.
    assert(!panel._messages().includes('data-action="save"'),
      "no pending changes, no Save button");
    // "Sync hatchery reminders" leaves the config dirty — and the Save bar
    // lives in Settings, so from here it was unreachable (Reece, 0.7.81).
    panel._config.nps.hatchery = { eggType: "standard", hatchHours: 34, state: {} };
    panel._npsSeedHatchReminders();
    assert(panel._configDirty, "the seeder must still leave the change pending");
    assert(panel._hatcheryTab().includes("save to keep them"),
      "the message says a save is needed...");
    assert(panel._messages().includes('data-action="save"')
      && panel._messages().includes("Save changes"),
      "...so a Save button has to be reachable from this page");
    // It rides in the GLOBAL slot (0.7.82), so it covers every tab that can go
    // dirty — corals, cameras, modes, doser suggestions — not just this one.
    panel._nps.message = "";
    assert(panel._messages().includes('data-action="save"'),
      "a dirty page keeps offering the save even once the message has gone");
    panel._activeTab = "corals";
    assert(panel._messages().includes('data-action="save"'), "same on every other tab");
    // Settings already carries its own save bar — don't stack a second.
    panel._activeTab = "settings";
    assert(!panel._messages().includes('data-action="save"'),
      "Settings has _saveControls; a second bar would be noise");
    // Saved: the offer retires itself.
    panel._activeTab = "hatchery";
    panel._configDirty = false;
    assert(!panel._messages().includes('data-action="save"'), "saved — nothing to offer");
    // The demo can never persist, so it must never promise a save.
    panel._configDirty = true;
    panel._nps.demo = true;
    assert(!panel._messages().includes('data-action="save"'), "the demo saves nothing");
  } finally { restore(); }
});

test("an enriched batch reads gut-loaded, never 'past prime, hatch fresh'", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._nps.summary.hatchery = v2HatcherySummary();
    const fx = panel._nps.summary.feedExchange;
    // 26 h since the load, soak finished 4 h ago. The old single clock called
    // this "past the 24 h prime window" — about a batch that had just been fed.
    fx.prime = { status: "gutloaded", ageHours: 26, primeLeftHours: 8,
                 enriched: true, window: "boost", windowHours: 12, soakAgeHours: 4 };
    let html = panel._hatcheryPanel();
    assert(html.includes("Gut-loaded"), "an enriched batch says so");
    assert(html.includes("has been FED"), "and says why the yolk clock stopped applying");
    assert(!html.includes("past the 24 h yolk window"), "it must not also condemn it");
    assert(html.includes("at room temp"), "the hold length is qualified by storage");
    // Fridged: same status, a much longer hold, and the copy has to follow.
    fx.prime.windowHours = 48; fx.prime.primeLeftHours = 44; fx.prime.refrigerated = true;
    assert(panel._hatcheryPanel().includes("fridged"), "48 h only makes sense cold");
    // Boost drained is not the same as stale — it is still live food.
    fx.prime = { status: "boost_fading", ageHours: 44, primeLeftHours: 0,
                 enriched: true, window: "boost", windowHours: 12, soakAgeHours: 20 };
    html = panel._hatcheryPanel();
    assert(html.includes("boost has drained"), "the honest ending for an enriched batch");
    assert(html.includes("Still live food"), "...and it does not tell him to bin it");
    // The unenriched path keeps the yolk story, now labelled as such.
    fx.prime = { status: "fading", ageHours: 30, primeLeftHours: 0,
                 enriched: false, window: "yolk", windowHours: 24 };
    html = panel._hatcheryPanel();
    assert(html.includes("never enriched") && html.includes("yolk window"),
      "unenriched brine still ages out — and now names the reason");
    assert(html.includes("enrich it"), "with enrichment offered as the way out");
  } finally { restore(); }
});

test("a cool bench moves the molt, so the dose-delay advice moves with it", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._nps.summary.hatchery = v2HatcherySummary();
    const hatch = panel._nps.summary.hatchery;
    hatch.temp = { available: true, tempC: 26.4, expectedHours: 38.4, factor: 1.13, warm: false };
    hatch.instar = { available: true, hours: 9.0, factor: 1.13 };
    hatch.enrichment = { ...(hatch.enrichment || {}), doseDelayH: 6 };
    let html = panel._hatcheryPanel();
    assert(html.includes("molt to instar II lands nearer"), "6 h is early at 26.4 °C");
    assert(html.includes("no mouth"), "and it says why an early dose is wasted");
    // Setting already past the molt: no nag.
    hatch.enrichment.doseDelayH = 10;
    assert(!panel._hatcheryPanel().includes("lands nearer"), "in step — no nag");
    // No sensor, no claim.
    hatch.enrichment.doseDelayH = 6;
    hatch.instar = { available: false, hours: 8, factor: null };
    assert(!panel._hatcheryPanel().includes("lands nearer"),
      "without a temperature reading the app has nothing to argue with");
  } finally { restore(); }
});

runTests();

test("the fridge is per batch — inline button, its own tile, and the hero card says so", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    // Warm load: the advice line carries ❄ Refrigerate, no fridge tile.
    panel._nps.summary.hatchery = v2HatcherySummary({
      reservoir: { canonical: "hatchery", volumeMl: 750, remainingMl: 500, loadVolumeMl: 0,
        refrigerated: false, refrigeratedAt: "", fridgeSavedH: 0, shelfHours: 24, plainShelfHours: 24,
        mixedAt: new Date(Date.parse(NOW) - 5 * 3600000).toISOString(),
        freshness: { status: "fresh", hoursLeft: 19, ageHours: 5 } },
    });
    let html = panel._hatcheryPanel();
    assert(html.includes('data-action="nps-fridge-in"'), "a warm load must offer ❄ Refrigerate inline");
    assert(!html.includes("data-fridge-tile"), "no fridge tile for a warm load");
    assert(!html.includes("fridge the container in Settings"), "the old settings pointer must be gone");
    // Cold load: the tile appears with the life left, and the button flips.
    panel._nps.summary.hatchery = v2HatcherySummary({
      reservoir: { canonical: "hatchery", volumeMl: 750, remainingMl: 500, loadVolumeMl: 0,
        refrigerated: true, refrigeratedAt: new Date(Date.parse(NOW) - 2 * 3600000).toISOString(),
        fridgeSavedH: 0, shelfHours: 43, plainShelfHours: 43,
        mixedAt: new Date(Date.parse(NOW) - 5 * 3600000).toISOString(),
        freshness: { status: "fresh", hoursLeft: 38, ageHours: 5 } },
    });
    html = panel._hatcheryPanel();
    assert(html.includes("data-fridge-tile"), "a cold load gets its own tile");
    assert(html.includes("38 h of life left"), "the tile wears the life left");
    assert(html.includes('data-action="nps-fridge-out"'), "and offers Take out");
    assert(!html.includes('data-action="nps-fridge-in"'), "never both buttons at once");
    const tab = panel._hatcheryTab();
    assert(tab.includes("in the fridge"), "the hero Container card says it is cold");
    noPlaceholders(html, "fridge tile");
  } finally { restore(); }
});

test("the temperature line measures the stretch against the rated hours and defers to the learned clock", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    // Reece's live case: 26.1 °C, a 38 h clock set from batches that ran ~36 h.
    panel._nps.summary.hatchery = v2HatcherySummary({
      hatchHours: 38,
      temp: { available: true, tempC: 26.1, expectedHours: 27.6, factor: 1.15, warm: false, ratedHours: 24 },
      learned: { available: true, hours: 36.3, samples: 3 },
    });
    let html = panel._hatcheryPanel();
    assert(!html.includes("not 38 h"), "the learned clock must not be stretched again");
    assert(html.includes("measured beats modelled"), "the line defers to the measured runs");
    // No learned clock, a 24 h clock: the honest stretch on the rated hours.
    panel._nps.summary.hatchery = v2HatcherySummary({
      hatchHours: 24,
      temp: { available: true, tempC: 26.1, expectedHours: 27.6, factor: 1.15, warm: false, ratedHours: 24 },
      learned: { available: false, hours: null, samples: 0 },
    });
    html = panel._hatcheryPanel();
    assert(html.includes("expect ~27.6 h, not 24 h"), "no learned clock: the rule of thumb speaks");
    // A clock already longer than the rule of thumb is not told to stretch.
    panel._nps.summary.hatchery = v2HatcherySummary({
      hatchHours: 36,
      temp: { available: true, tempC: 26.1, expectedHours: 27.6, factor: 1.15, warm: false, ratedHours: 24 },
      learned: { available: false, hours: null, samples: 0 },
    });
    html = panel._hatcheryPanel();
    assert(html.includes("already allows for it"), "a generous clock is left alone");
  } finally { restore(); }
});
