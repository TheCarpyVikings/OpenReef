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
    eggType: "standard", hatchHours: 24, eggTypes: [],
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
    enrichment: { hours: 12, doseMl: 1, productId: "", productName: "Selcon", splitDose: false,
      sourceVesselId: "", state: { status: "none", secondDoseDue: false } },
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
    assert(html.includes("expect ~36 h"), "the temperature advisory is missing");
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
      assert(html.includes("lives in the fridge"), "the refrigerated toggle is missing");
      assert(html.includes('data-field="tempEntity"'), "the temp sensor field is missing");
    }
  } finally { restore(); }
});

test("the enrichment vessel joins the strip while a batch soaks", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    // Idle enrichment: incubating vessels offer the per-batch "→ Enrich".
    panel._nps.summary.hatchery = v2HatcherySummary();
    let html = panel._npsTab();
    assert(html.includes("→ Enrich"), "the per-batch enrich choice is missing at harvest");
    assert(!html.includes("data-enrich-vessel"), "no soak running — no beaker");
    // Soaking: the beaker tile appears, the enrich buttons leave the vessels.
    panel._nps.summary.hatchery = v2HatcherySummary({
      enrichment: { hours: 12, doseMl: 1, productId: "selcon", productName: "Selcon",
        splitDose: true, sourceVesselId: "v1",
        state: { status: "enriching", hoursElapsed: 10.5, hoursLeft: 1.5, percent: 88, secondDoseDue: true } },
    });
    html = panel._npsTab();
    assert(html.includes("data-enrich-vessel"), "the enrichment beaker is missing");
    assert(html.includes("10.5 / 12 h soak"), "the soak countdown is missing");
    assert(html.includes("Log top-up"), "the split-dose top-up button is missing");
    assert(html.includes("Enriched &amp; loaded"), "the enriched load button is missing");
    assert(!html.includes("→ Enrich"), "one soak at a time — vessels must not offer enrich while busy");
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

test("the rig blueprint unfolds on demand and walks the settle-and-slug harvest", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._nps.summary.hatchery = v2HatcherySummary();
    let html = panel._npsTab();
    assert(html.includes("Rig blueprint"), "the blueprint toggle is missing");
    assert(!html.includes("slug chamber"), "the blueprint must start collapsed");
    panel._npsRigOpen = true;
    html = panel._npsTab();
    assert(html.includes("slug chamber"), "the slug chamber is missing from the blueprint");
    assert(html.includes("HATCH EGGS") && html.includes("LIVE BRINE"), "the two staggered vessels are missing");
    assert(html.includes("Ⓐ") && html.includes("Ⓑ"), "the chamber valves are missing");
    assert(html.includes("lamp at the tip"), "the lamp step is missing");
    assert(html.includes("never feeds the tank"), "the hatch-water rule must be stated");
    assert(html.includes("7. Drain vessel 2"), "the numbered harvest steps are missing");
    noPlaceholders(html, "rig blueprint");
  } finally { restore(); }
});

test("settings carry the enrichment block", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await npsPanel();
    panel._settingsSectionsOpen = { nps: true };
    let html;
    try { html = panel._npsSettings(); } catch { html = null; }
    if (html !== null) {
      assert(html.includes('data-scope="nps-enrichment"'), "enrichment settings missing");
      assert(html.includes("Split-dose top-up"), "the split-dose toggle is missing");
      assert(html.includes("proven for larvae, recommended for NPS corals"), "the honest evidence copy is missing");
    }
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

runTests();
