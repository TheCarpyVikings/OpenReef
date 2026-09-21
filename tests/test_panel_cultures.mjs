/**
 * Cultures tab presentation (live cultures v1): the jar strip, the rotifer
 * bottle, the mission row, the settings section, the reminder seeding and
 * the Helm's nav/hub — plus the "Brine hatchery" rename. The engine is
 * Python and covered in test_cultures.py; this pins what the keeper looks at.
 *
 * All renderers are exercised with pre-seeded summaries so no test can reach
 * for the network.
 *
 * Run standalone:  node tests/test_panel_cultures.mjs
 */

import { assert, freezeTime, makePanel, runTests, test } from "./_panel_harness.mjs";

const NOW = "2026-09-03T12:00:00Z";
const iso = (hoursAgo) => new Date(Date.parse(NOW) - hoursAgo * 3600000).toISOString();

function baseConfig(overrides = {}) {
  return {
    nps: {
      enabled: false,
      cultures: {
        enabled: true, tempEntity: "",
        jars: {
          c1: { name: "Rotifers A", species: "rotifer_L", volumeL: 2.5, salinityPpt: 35,
                feed: { productId: "phyto", doseMl: 5 }, cadence: {},
                state: { startedAt: iso(12 * 24), lastRestartAt: iso(12 * 24), lastFedAt: iso(20),
                         lastHarvestAt: iso(30), lastTint: "clearing", crashedAt: "" }, history: [] },
          c2: { name: "Pods", species: "tigriopus", volumeL: 4, salinityPpt: 35,
                feed: { productId: "", doseMl: 10 }, cadence: {}, state: {}, history: [] },
        },
        bottle: { volumeMl: 1000, remainingMl: 400, filledAt: iso(10), doseMl: 20 },
      },
      hatchery: { enabled: true, eggType: "standard", hatchHours: 24, vessels: {}, reservoir: {} },
    },
    consumables: { products: { phyto: { name: "Live phyto", bottleMl: 500, remainingMl: 300, history: [] } } },
    maintenance: { tasks: {}, completions: {} },
    ...overrides,
  };
}

const clock = (due, hoursUntil, available = true) => ({
  available, due, at: available ? NOW : null, hoursUntil: due ? 0 : hoursUntil, hoursOverdue: due ? 2 : 0 });

function jarSummary(over = {}) {
  return {
    id: "c1", name: "Rotifers A", species: "rotifer_L", speciesName: "Rotifers (L-type)", kind: "rotifer",
    latin: "Brachionus plicatilis", volumeL: 2.5, salinityPpt: 35, vesselKind: "cone", purgeMl: 50, sieveUm: 50, adultSieveUm: 0,
    tintTarget: "leafy green — spinach, not pea soup", firstHarvestDays: 6, note: "Keep the water lightly green.",
    feed: { productId: "phyto", productName: "Live phyto", doseMl: 5 },
    cadence: { feedIntervalH: 12, harvestIntervalDays: 1, harvestPct: 25, restartIntervalDays: 14, waterChangeIntervalDays: 0, waterChangePct: 0 },
    state: { status: "producing", ageDays: 12, daysSinceRestart: 12, percent: 86, splitEligible: true,
             feed: clock(true, 0), harvest: clock(true, 0), restart: clock(false, 48), waterChange: clock(false, 0, false),
             nextChore: { key: "feed", at: NOW, due: true, hoursUntil: 0 },
             cadence: { restartIntervalDays: 14 } },
    tint: "clearing", due: ["feed", "harvest"],
    feedAdvice: { action: "feed_now", reason: "clearing — feed on schedule" },
    temp: { available: true, status: "ok", tempC: 23.5, minC: 18, maxC: 26, hardMaxC: 30 },
    harvestGuide: { totalMl: 625, mixMl: 625, rodiMl: 0, targetPpt: 35 },
    restartGuide: { totalMl: 2500, mixMl: 2500, rodiMl: 0, targetPpt: 35, mixPpt: 35, sg: 1.0264 },
    fillGuide: { totalMl: 2500, mixMl: 2500, rodiMl: 0, targetPpt: 35, mixPpt: 35, sg: 1.0264 },
    waterChangeGuide: { totalMl: 0, mixMl: 0, rodiMl: 0, targetPpt: 35 },
    hasBottle: true, seededFrom: "", reseedFrom: [],
    learned: { clearingH: { available: false, hours: null, samples: 0 }, firstHarvestDays: { available: false, days: null, samples: 0 },
               runLengthDays: { available: false, days: null, samples: 0 }, yieldMlDay: null, suggest: { feedIntervalH: null, restartIntervalDays: null } },
    risk: { level: "ok", reason: "steady — nothing to worry about" }, lastSign: "",
    lineage: { generation: 1, fromName: "", line: "gen 1 · from the starter" },
    tintStrip: ["", "", "", "", "", "", "", "", "green", "green", "clearing", "green", "clearing", "clearing"],
    stagger: { available: false, days: null, idealDays: null, advice: "" },
    guard: { available: false, status: "unknown", peakC: null, peakAt: null, crossAt: null, hoursUntil: null, line: "" },
    history: [{ event: "harvest", at: iso(30), ml: 625, tint: "green", from: "", sign: "", eggRatio: 0, tempC: 23.4 },
              { event: "seeded", at: iso(12 * 24), ml: 0, tint: "", from: "", sign: "", eggRatio: 0, tempC: null }],
    ...over,
  };
}

// What the backend's cultures.rig_state would say for these jars (the panel
// only draws it; test_cultures.py pins the maths).
function rigFixture(list) {
  const vessel = (j) => {
    const st = j.state || {};
    const running = st.status === "producing" || st.status === "establishing";
    const due = new Set(j.due || []);
    return { id: j.id, name: j.name, kind: j.vesselKind || "jar", status: st.status || "none",
      tint: running ? (j.tint || "") : "", pct: st.percent ?? (st.status === "producing" ? 100 : 0),
      airOn: running, purgeHot: due.has("harvest") || due.has("restart"), harvestHot: due.has("harvest"),
      refillHot: due.has("harvest") || due.has("restart"), feedHot: running && j.feedAdvice?.action === "feed_now",
      restartHot: due.has("restart"), tempStatus: j.temp?.status || "unknown",
      establishDays: st.status === "establishing" ? Math.round(st.ageDays || 0) : null, firstHarvestDays: j.firstHarvestDays || 6 };
  };
  const cones = list.filter((j) => (j.vesselKind || "jar") !== "tub").map(vessel);
  const tub = list.filter((j) => j.vesselKind === "tub").map(vessel)[0] || null;
  const lead = list.find((j) => (j.vesselKind || "jar") !== "tub") || {};
  const g = lead.harvestGuide || {};
  const harvest = cones.some((c) => c.harvestHot);
  return {
    stage: harvest ? "harvest" : cones.some((c) => c.status === "producing") ? "steady" : "idle",
    caption: harvest ? `HARVEST — air off, settle 20 min, bleed ~${lead.purgeMl || 0} ml off the tip, then ${g.totalMl || 0} ml through the ${lead.sieveUm || 50} µm net · refill ${g.mixMl || 0} ml fresh`
      : cones.some((c) => c.status === "producing") ? "STEADY — nothing due · look at the water" : "IDLE — seed the cone and the rig comes alive",
    cones, tub,
    jug: { harvestMl: g.totalMl || 0, mixMl: g.mixMl || 0, rodiMl: g.rodiMl || 0, ppt: g.targetPpt || 35, purgeMl: lead.purgeMl || 0, sieveUm: lead.sieveUm || 50 },
    bottle: { ml: 400, pct: 40, status: "fresh" },
  };
}

function summaryFixture(jars) {
  const list = jars || [jarSummary(), jarSummary({
    id: "c2", name: "Pods", species: "tigriopus", speciesName: "Tigriopus copepods", kind: "copepod",
    latin: "Tigriopus californicus", volumeL: 4, vesselKind: "tub", purgeMl: 0, sieveUm: 50, adultSieveUm: 300,
    tintTarget: "Granny Smith apple skin", firstHarvestDays: 28, note: "Patience beats fiddling.",
    feed: { productId: "", productName: null, doseMl: 10 },
    cadence: { feedIntervalH: 24, harvestIntervalDays: 10, harvestPct: 25, restartIntervalDays: 0, waterChangeIntervalDays: 0, waterChangePct: 50 },
    state: { status: "none", ageDays: null, daysSinceRestart: null, percent: null, splitEligible: false, waterChangeOnDemand: true,
             feed: clock(false, 0, false), harvest: clock(false, 0, false), restart: clock(false, 0, false), waterChange: clock(false, 0, false),
             nextChore: null, cadence: {} },
    tint: "", due: [], feedAdvice: { action: "wait", reason: "no tint logged yet" },
    temp: { available: true, status: "ok", tempC: 23.5, minC: 18, maxC: 26, hardMaxC: 28, actC: 30, criticalC: 32, act: false },
    waterChangeGuide: { totalMl: 2000, mixMl: 2000, rodiMl: 0, targetPpt: 35 },
    hasBottle: false, history: [],
  })];
  return {
    enabled: true, jars: list, dueCount: list.reduce((n, j) => n + (j.due || []).length, 0),
    idleJars: list.filter((j) => j.state.status === "none" || j.state.status === "crashed").map((j) => j.id),
    canAddJar: list.length < 4,
    bottle: { status: "fresh", remainingMl: 400, hoursLeft: 62, filledAt: iso(10), volumeMl: 1000, doseMl: 20, shelfDays: 5,
              enriched: false, boost: { status: "none", hoursLeft: null }, usageMlDay: null, history: [] },
    enrichment: { productId: "", productName: "Rotifer & Artemia Enrichment", drops: 3, soakH: 6, boostWarmH: 8, boostColdH: 24,
                  soak: { status: "none", percent: null, hoursLeft: null, hoursElapsed: null }, portionMl: 0, jarId: "", jarName: null },
    nextHarvest: { status: "wait", hoursUntil: 14, driver: "depletion" },
    tempC: 23.5,
    backup: list.filter((j) => j.state.status === "producing" || j.state.status === "establishing").length
      ? [{ species: "rotifer_L", speciesName: "Rotifers (L-type)", running: list.filter((j) => j.species === "rotifer_L" && (j.state.status === "producing" || j.state.status === "establishing")).length,
           backedUp: list.filter((j) => j.species === "rotifer_L" && (j.state.status === "producing" || j.state.status === "establishing")).length >= 2,
           continuityDays: 12, guard: { available: false, status: "unknown", line: "" } }] : [],
    guardAvailable: false,
    rig: rigFixture(list),
    species: [
      { id: "rotifer_L", name: "Rotifers (L-type)", kind: "rotifer", vesselKind: "cone", salinityPpt: 27, feedIntervalH: 12, harvestIntervalDays: 1, harvestPct: 25, restartIntervalDays: 14, waterChangeIntervalDays: 0, waterChangePct: 0, sieveUm: 50, adultSieveUm: 0, purgeMl: 50, firstHarvestDays: 6, tintTarget: "leafy green — spinach, not pea soup" },
      { id: "tigriopus", name: "Tigriopus copepods", kind: "copepod", vesselKind: "tub", salinityPpt: 35, feedIntervalH: 24, harvestIntervalDays: 10, harvestPct: 25, restartIntervalDays: 0, waterChangeIntervalDays: 0, waterChangePct: 50, sieveUm: 50, adultSieveUm: 300, purgeMl: 0, firstHarvestDays: 28, tintTarget: "Granny Smith apple skin" },
    ],
    tints: ["green", "clearing", "clear"],
    signs: [{ id: "foam", label: "foam on the surface" }, { id: "milky", label: "milky water" }, { id: "smell", label: "a smell" }, { id: "surface", label: "clustering at the surface" }],
    maxJars: 4,
  };
}

async function culturesPanel(configOverrides = {}, summary) {
  const panel = await makePanel(baseConfig(configOverrides));
  panel._cultures = { summary: summary === undefined ? summaryFixture() : summary, at: Date.now(), loading: false, error: "", message: "" };
  panel._nps = { summary: null, at: Date.now(), loading: false, error: "", message: "", addOpen: false, confirmDelete: "", demo: false };
  panel._configDirty = false;
  panel._activity = [];
  panel._settingsSectionIds = new Set();
  panel._settingsSections = {};
  panel._isPhoneViewport = () => false;
  panel._render = () => {};                    // taps and seeders re-render; no DOM here
  panel._setDirty = () => { panel._configDirty = true; };
  panel._recordActivity = () => {};
  return panel;
}

const noPlaceholders = (html, where) =>
  assert(!/undefined|NaN|\[object/.test(html), `${where} leaked a placeholder value`);

test("the Feeding hub carries Brine hatchery + Cultures, and the hub card counts running jars", async () => {
  const panel = await culturesPanel();
  const feeding = panel._navGroups().find((g) => g.id === "feeding");
  const labels = feeding.pages.map(([, label]) => label);
  assert(labels.includes("Brine hatchery"), `hatchery pill must read "Brine hatchery": ${labels}`);
  assert(!labels.includes("Hatchery"), "the bare Hatchery label is retired");
  assert(labels.includes("Cultures"), "the Cultures pill is missing");
  panel._config.nps.cultures.enabled = false;
  assert(!panel._navGroups().find((g) => g.id === "feeding").pages.some(([id]) => id === "cultures"),
    "Cultures must hide when the feature is off");
  panel._config.nps.cultures.enabled = true;
  const hub = panel._hubTab("feeding");
  assert(hub.includes("1 jar running"), "the hub card must count the running jar");
});

test("the Cultures tab renders the rack: a producing jar with its taps, an empty jar, the bottle", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await culturesPanel();
    const html = panel._culturesTab();
    noPlaceholders(html, "Cultures tab");
    assert(html.includes("Rotifers A") && html.includes("Pods"), "both jars must be on the rack");
    assert(html.includes("feed due") && html.includes("harvest due"), "due chips missing");
    assert(html.includes('data-action="cultures-harvested"'), "the daily tap is missing");
    assert(html.includes('data-action="cultures-fed"'), "the Fed tap is missing");
    assert(html.includes('data-action="cultures-restart"'), "a rotifer jar must offer Restarted");
    assert(!html.includes('data-action="cultures-water-change"'), "rotifers have no water-change chore");
    assert(html.includes('data-action="cultures-split"'), "a dense producing jar must offer Split into B");
    assert(html.includes('data-cultures-tint="c1"'), "the tint select is missing");
    assert(html.includes("harvest 625 ml"), "the measured jug is missing");
    assert(html.includes('data-action="cultures-seed" data-id="c2"'), "the empty pod jar must offer Seed");
    assert(html.includes("Rotifer bottle") && html.includes("Fed 20 ml"), "the bottle tile with its dose button is missing");
    assert(html.includes("2 chores"), "the mission row must count due chores");
    assert(html.includes("Sync culture reminders"), "the reminders button is missing");
    assert(html.includes("Culture journal") && html.includes("harvested"), "the journal is missing");
    assert(html.includes("Brachionus plicatilis"), "the species notes are missing");
    assert(html.includes("23.5 °C"), "the room card must show the temperature");
  } finally { restore(); }
});

test("a crashed jar offers a reseed from its producing sibling, and the heat line is a real warning", async () => {
  const restore = freezeTime(NOW);
  try {
    const crashed = jarSummary({
      id: "c2", name: "Rotifers B", reseedFrom: ["c1"], due: [], hasBottle: true,
      state: { ...jarSummary().state, status: "crashed", ageDays: 9, splitEligible: false },
      temp: { available: true, status: "hot", tempC: 30.2, minC: 18, maxC: 26, hardMaxC: 30 },
    });
    const panel = await culturesPanel({}, summaryFixture([jarSummary({ temp: { available: true, status: "hot", tempC: 30.2, minC: 18, maxC: 26, hardMaxC: 30 } }), crashed]));
    const html = panel._culturesTab();
    assert(html.includes('data-action="cultures-seed" data-id="c2" data-from="c1"'), "reseed-from-sibling button missing");
    assert(html.includes("Seed from Rotifers A"), "the reseed button must name the sibling");
    assert(!html.includes('data-action="cultures-harvested" data-id="c2"'), "a crashed jar has nothing to harvest");
    assert(html.includes("hard line"), "the heat warning must say it is over the hard line");
    assert(html.includes("over the hard line — extra air"), "the room card must escalate");
    assert(html.includes("1 crashed"), "the jars card must count the crash");
  } finally { restore(); }
});

test("with no jars the tab explains itself, with no summary it does not leak", async () => {
  const restore = freezeTime(NOW);
  try {
    let panel = await culturesPanel({}, { enabled: true, jars: [], dueCount: 0, idleJars: [], canAddJar: true, bottle: { status: "empty" }, tempC: null, species: [], tints: [] });
    let html = panel._culturesTab();
    noPlaceholders(html, "empty Cultures tab");
    assert(html.includes("No jars yet") && html.includes('data-action="cultures-add-jar"'), "the empty state must offer a jar");
    panel = await culturesPanel({}, null);
    html = panel._culturesTab();
    noPlaceholders(html, "Cultures tab before the summary lands");
  } finally { restore(); }
});

test("Culture settings: species picker, cadence from the preset, jar add/remove rules", async () => {
  const panel = await culturesPanel();
  let html = panel._culturesSettings();
  noPlaceholders(html, "Culture settings");
  assert(html.includes('data-scope="nps-cultures" data-field="enabled"'), "the on toggle is missing");
  assert(html.includes("Tigriopus copepods") && html.includes("Rotifers (L-type)"), "the species picker is missing");
  // The pod jar shows its own preset cadence (weekly harvest, 21-day change).
  assert(html.includes('data-id="c2" data-field="harvestIntervalDays" value="10"'), "pod harvest cadence must come from the preset");
  assert(html.includes('data-id="c2" data-field="waterChangeIntervalDays" value="0"') && html.includes('data-id="c2" data-field="waterChangePct" value="50"'), "pod water change: on a sign (no clock), 50 %");
  assert(html.includes('data-id="c1" data-field="restartIntervalDays" value="14"'), "rotifer restart cadence must come from the preset");
  // A running jar cannot change species, and cannot be removed.
  assert(/data-id="c1" data-field="species" disabled/.test(html), "a running jar's species is locked");
  panel._culturesRemoveJar("c1");
  assert(panel._config.nps.cultures.jars.c1, "a running jar must not be removed");
  assert(panel._cultures.error.includes("running"), "the refusal must say why");
  panel._culturesRemoveJar("c2");
  assert(!panel._config.nps.cultures.jars.c2, "an idle jar is removable");
  panel._culturesAddJar();
  panel._culturesAddJar();
  panel._culturesAddJar();
  panel._culturesAddJar();
  assert(Object.keys(panel._config.nps.cultures.jars).length === 4, "the rack caps at 4 jars");
});

test("syncing reminders seeds per-jar tasks on the right clocks, anchored on the jar's stamps", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await culturesPanel();
    panel._culturesSeedReminders();
    const tasks = panel._config.maintenance.tasks;
    const comps = panel._config.maintenance.completions;
    assert(tasks.culture_c1_feed && tasks.culture_c1_feed.cadenceHours === 12, "rotifer feed rides the 12 h clock");
    assert(tasks.culture_c1_harvest && tasks.culture_c1_harvest.cadenceDays === 1, "rotifer harvest is daily");
    assert(tasks.culture_c1_restart && tasks.culture_c1_restart.cadenceDays === 14, "rotifer restart is fortnightly");
    assert(!tasks.culture_c1_water_change, "rotifers get no water-change task");
    assert(tasks.culture_c2_feed && tasks.culture_c2_feed.cadenceHours === 24, "pod feed rides the daily clock");
    assert(tasks.culture_c2_harvest.cadenceDays === 10 && !tasks.culture_c2_water_change, "pods harvest every 10 days; a water change on a sign has no reminder");
    assert(!tasks.culture_c2_restart, "pods never sieve-restart");
    // Anchors: the feed logged 20 h ago, the harvest 30 h ago, the restart 12 d ago.
    assert(comps.culture_c1_feed?.[0]?.timestamp === iso(20) && comps.culture_c1_feed[0].source === "cultures", "feed anchor missing");
    assert(comps.culture_c1_harvest?.[0]?.timestamp === iso(30), "harvest anchor missing");
    assert(comps.culture_c1_restart?.[0]?.timestamp === iso(12 * 24), "restart anchor missing");
    assert(!comps.culture_c2_feed?.length, "an unseeded jar has no stamps to anchor on");
    assert(panel._configDirty === true, "seeding reminders must dirty the config");
    // Re-running never duplicates the anchor.
    panel._culturesSeedReminders();
    assert(comps.culture_c1_feed.length === 1, "re-sync duplicated the anchor completion");
  } finally { restore(); }
});

test("the Pulse insight rotator surfaces due jars, the heat line and a stale bottle", async () => {
  const restore = freezeTime(NOW);
  try {
    const summary = summaryFixture([jarSummary({ temp: { available: true, status: "hot", tempC: 31, minC: 18, maxC: 26, hardMaxC: 30 } })]);
    summary.bottle = { ...summary.bottle, status: "stale", hoursLeft: 0 };
    const panel = await culturesPanel({}, summary);
    panel._culturesLoadSummary = async () => {};
    const cards = panel._pulseInsightCards();
    assert(Array.isArray(cards) && cards.length, "the rotator returned nothing");
    const titles = cards.map((c) => `${c.kicker}: ${c.title}`).join(" | ");
    assert(titles.includes("Cultures: Rotifers A: feed + harvest"), `due jar card missing: ${titles}`);
    assert(titles.includes("over the hard line"), `heat card missing: ${titles}`);
    assert(titles.includes("Rotifer bottle is stale"), `stale bottle card missing: ${titles}`);
  } finally { restore(); }
});


test("the live rig draws the cones, the net, the bottle and the tub, and follows the stage", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await culturesPanel();
    const html = panel._culturesTab();
    assert(html.includes("The rig — live"), "the rig panel is missing from the tab");
    assert(html.includes("ROTIFERS A") && html.includes("PODS · TUB"), "the cone and the tub must be labelled");
    assert(html.includes("50 µm net") && html.includes("FRIDGE BOTTLE"), "net or bottle copy missing");
    assert(html.includes("HARVEST — air off, settle 20 min"), "the caption must name the stage");
    assert(html.includes("purge 50 ml · harvest 625 ml"), "the jar guide must lead with the purge for a cone");
    assert(html.includes('data-action="cultures-rig-play"'), "the walkthrough button is missing");
    // A due harvest lights the tip run and the arc to the bottle; a quiet rig does not.
    const hotSvg = panel._culturesRigSvg(rigFixture([jarSummary()]));
    assert((hotSvg.match(/awc-flow/g) || []).length >= 3, "a due harvest must animate the tip run, the waste drop and the bottle arc");
    const quietSvg = panel._culturesRigSvg(rigFixture([jarSummary({ due: [], feedAdvice: { action: "wait", reason: "" } })]));
    assert(!quietSvg.includes('stroke="#66bb6a" stroke-width="2" class="awc-flow"'), "a quiet rig must not animate the harvest run");
    assert(quietSvg.includes("air ON"), "a producing cone bubbles");
    // No tub → no tub drawing; four cones cap the band.
    const noTub = panel._culturesRigSvg(rigFixture([jarSummary()]));
    assert(!noTub.includes("· TUB"), "a rack without pods draws no tub");
    const four = panel._culturesRigSvg(rigFixture([1, 2, 3, 4, 5].map((n) => jarSummary({ id: `c${n}`, name: `Cone ${n}` }))));
    assert(four.includes("CONE 4") && !four.includes("CONE 5"), "the drawing caps at four cones like the hatchery");
    noPlaceholders(html, "cultures tab with the rig");
  } finally { restore(); }
});

test("play the day walks the cone through its stages and a second tap stops it", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await culturesPanel();
    const stages = panel._culturesRigPreviewStages();
    assert(stages.length >= 8 && stages[0].caption.startsWith("1 · LOOK") && stages[2].cones[0].purgeHot, "the stage list lost its shape");
    assert(stages.some((s) => s.stage === "restart" && s.cones[0].restartHot) && stages.some((s) => s.stage === "tub" && s.tub.harvestHot), "restart and tub stages missing");
    panel._culturesRigPlay();
    assert(panel._culturesRigPreview && panel._culturesRigPreview.stage === "look", "play must start at LOOK");
    assert(panel._culturesRigState().caption.startsWith("1 · LOOK"), "the drawing must read the preview while playing");
    assert(panel._culturesRigPanel().includes("■ Stop"), "the button flips to Stop while playing");
    panel._culturesRigPlay();
    assert(panel._culturesRigPreview === null && panel._culturesRigTimer === null, "a second tap must stop the walkthrough");
  } finally { restore(); }
});

test("removing a jar takes its reminders with it", async () => {
  const restore = freezeTime(NOW);
  try {
    const maintenance = {
      tasks: { culture_c2_feed: { label: "Pods: feed" }, culture_c2_harvest: { label: "Pods: harvest" }, culture_c1_feed: { label: "A: feed" }, water_change: { label: "tank" } },
      completions: { culture_c2_feed: [{ id: "x", timestamp: NOW }], culture_c1_feed: [{ id: "y", timestamp: NOW }] },
    };
    const panel = await culturesPanel({ maintenance });
    panel._culturesRemoveJar("c2");
    const cfg = panel._config;
    assert(!cfg.nps.cultures.jars.c2, "the jar must go");
    assert(!cfg.maintenance.tasks.culture_c2_feed && !cfg.maintenance.tasks.culture_c2_harvest, "the jar's tasks must go with it");
    assert(!cfg.maintenance.completions.culture_c2_feed, "the jar's completions must go with it");
    assert(cfg.maintenance.tasks.culture_c1_feed && cfg.maintenance.tasks.water_change && cfg.maintenance.completions.culture_c1_feed, "other tasks must survive");
    assert(panel._configDirty, "removal must dirty the config");
    // A running jar still refuses.
    panel._culturesRemoveJar("c1");
    assert(panel._config.nps.cultures.jars.c1 && panel._cultures.error.includes("running"), "a running jar must refuse removal");
  } finally { restore(); }
});

test("settings carry the vessel, the purge and the salinity recommendation", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await culturesPanel();
    const html = panel._culturesSettings();
    assert(html.includes('data-field="vesselKind"') && html.includes("Cone — the hatchery"), "the vessel select is missing");
    assert(html.includes('data-field="purgeMl"'), "the cone's purge field is missing");
    assert(html.includes("SG 1.019–1.021 (about 27 ppt)") && !html.includes("2.5×"), "the salinity recommendation must be on the page");
    assert(html.includes("never a cone"), "the pods' vessel hint is missing");
    // Changing species resets vessel + purge with the salinity (the scope handler).
    const jar = panel._config.nps.cultures.jars.c2;
    jar.vesselKind = "cone"; jar.purgeMl = 80;
    panel._applyField?.("nps-culture-jar", "c2", "species", "rotifer_L");
    if (panel._applyField) {
      assert(jar.vesselKind === "cone" && jar.salinityPpt === 27, "species change must reseed the vessel and salinity from the preset");
    }
  } finally { restore(); }
});

test("a producing tub offers Water changed on a sign, with no clock", async () => {
  const restore = freezeTime(NOW);
  try {
    const pod = summaryFixture()[ "jars" ][1];
    const producing = { ...pod, state: { ...pod.state, status: "producing", ageDays: 40, waterChangeOnDemand: true }, tint: "green", due: [] };
    const panel = await culturesPanel({}, summaryFixture([jarSummary(), producing]));
    const html = panel._culturesTab();
    const tile = html.slice(html.indexOf('data-culture="c2"'));
    assert(tile.includes('data-action="cultures-water-change"') && tile.includes("On a sign"), "the on-demand water change button is missing");
    assert(!tile.includes("Restarted"), "pods never sieve-restart");
    noPlaceholders(html, "producing tub");
  } finally { restore(); }
});

test("the heat copy explains oxygen and ammonia and escalates at the critical line", async () => {
  const restore = freezeTime(NOW);
  try {
    const warn = jarSummary({ temp: { available: true, status: "hot", tempC: 28.6, minC: 18, maxC: 26, hardMaxC: 28, actC: 30, criticalC: 32, act: false } });
    let panel = await culturesPanel({}, summaryFixture([warn]));
    let html = panel._culturesTab();
    assert(html.includes("over the 28 °C hard line") && html.includes("oxygen and ammonia"), "the warn tier must say why");
    assert(html.includes("over the hard line — extra air"), `room card missing the warn copy`);
    const act = jarSummary({ temp: { available: true, status: "hot", tempC: 30.4, minC: 18, maxC: 26, hardMaxC: 28, actC: 30, criticalC: 32, act: true } });
    panel = await culturesPanel({}, summaryFixture([act]));
    html = panel._culturesTab();
    assert(html.includes("over the 30 °C act line") && html.includes("act now"), "the act tier is missing");
    const critical = jarSummary({ temp: { available: true, status: "critical", tempC: 32.5, minC: 18, maxC: 26, hardMaxC: 28, actC: 30, criticalC: 32, act: true } });
    panel = await culturesPanel({}, summaryFixture([critical]));
    html = panel._culturesTab();
    assert(html.includes("32 °C critical line") && html.includes("move the cultures NOW"), "the critical tier is missing");
    panel._culturesLoadSummary = async () => {};
    const cards = panel._pulseInsightCards();
    const heat = cards.find((c) => c.title.includes("over the hard line"));
    assert(heat && (heat.body || heat.detail || JSON.stringify(heat)).includes("NOW"), "the Pulse line must escalate at the critical line");
  } finally { restore(); }
});

test("the arrival walkthrough shows only while nothing has ever been seeded", async () => {
  const restore = freezeTime(NOW);
  try {
    const fresh = summaryFixture([
      jarSummary({ state: { ...jarSummary().state, status: "none", percent: null }, tint: "", due: [], history: [] }),
      summaryFixture().jars[1],
    ]);
    let panel = await culturesPanel({}, fresh);
    let html = panel._culturesTab();
    assert(html.includes("The day the parcel lands") && html.includes("first harvest unlocks at day 6") && html.includes("waits until day 28"), "the walkthrough must quote the presets");
    assert(html.includes("Reef Juice is a tank dose, nothing to do with the jars") && html.includes("it lives on the NPS food shelf with its own dose and reminder"), "the shelf step must send Reef Juice to the shelf");
    panel = await culturesPanel();
    html = panel._culturesTab();
    assert(!html.includes("The day the parcel lands"), "a seeded rack must not show the walkthrough");
  } finally { restore(); }
});


test("the tile carries the risk line, the sign taps and the egg-ratio check; the taps call the right WS", async () => {
  const restore = freezeTime(NOW);
  try {
    const risky = jarSummary({
      risk: { level: "act", reason: "two harvests missed — the ammonia is climbing, harvest before you feed" },
      feedAdvice: { action: "harvest_first", reason: "two harvests missed — harvest before you feed, the ammonia is climbing" },
      lastSign: "foam",
      state: { ...jarSummary().state, restart: { ...clock(true, 0), reason: "sign" } }, due: ["feed", "harvest", "restart"],
    });
    const panel = await culturesPanel({}, summaryFixture([risky]));
    const html = panel._culturesTab();
    assert(html.includes('data-culture-risk="act"') && html.includes("⚠ two harvests missed"), "the risk line is missing");
    assert(html.includes("→ harvest"), "harvest debt must turn the feed advice into harvest first");
    assert(html.includes("restart due · a crash sign"), "the restart chip must say why it came forward");
    ["foam", "milky", "smell", "surface"].forEach((sg) => assert(html.includes(`data-action="cultures-sign" data-id="c1" data-sign="${sg}"`), `${sg} tap missing`));
    assert(html.includes('data-cultures-egg="c1"'), "the egg-ratio input is missing");
    assert(html.includes("Rotifers A: two harvests missed"), "the Due-now card must carry the act reason");
    const calls = [];
    panel._callWS = async (msg) => { calls.push(msg); return {}; };
    panel._culturesLoadSummary = async () => {};
    panel._culturesSign("c1", "milky");
    panel._culturesApplyLearned("c1", "feedIntervalH");
    await new Promise((r) => setTimeout(r, 0));
    assert(calls[0].type === "openreef/cultures_log" && calls[0].sign === "milky" && calls[0].jar_id === "c1", "the sign tap must log the sign");
    assert(calls[1].type === "openreef/cultures_apply_learned" && calls[1].field === "feedIntervalH", "Apply must call cultures_apply_learned");
    noPlaceholders(html, "risky tile");
  } finally { restore(); }
});

test("the learned chips appear only when the journal has taught something", async () => {
  const restore = freezeTime(NOW);
  try {
    const taught = jarSummary({ learned: {
      clearingH: { available: true, hours: 9.3, samples: 3 }, firstHarvestDays: { available: true, days: 5.5, samples: 2 },
      runLengthDays: { available: true, days: 11, samples: 3 }, yieldMlDay: 610,
      suggest: { feedIntervalH: 8, restartIntervalDays: 10 } } });
    let panel = await culturesPanel({}, summaryFixture([taught]));
    let html = panel._culturesTab();
    assert(html.includes("clears in ~9.3 h (3 feeds) — feed every 8 h?") && html.includes('data-field="feedIntervalH">Apply'), "the feed chip is missing");
    assert(html.includes("Recorded crashes averaged ~11 days (3 failures) — restart at 10?") && html.includes('data-field="restartIntervalDays">Apply'), "the restart chip is missing");
    assert(html.includes("~610 ml a day harvested lately"), "the yield line is missing");
    assert(!html.includes("seeds took"), "a producing jar does not show the first-harvest line");
    panel = await culturesPanel();
    html = panel._culturesTab();
    assert(!html.includes("Apply</button>"), "nothing learned, no chips");
    const establishing = jarSummary({ state: { ...jarSummary().state, status: "establishing", ageDays: 2, percent: 14 }, due: [],
      learned: { ...taught.learned, suggest: { feedIntervalH: null, restartIntervalDays: null } } });
    html = (await culturesPanel({}, summaryFixture([establishing])))._culturesTab();
    assert(html.includes("Your last 2 seeds took ~5.5 days"), "an establishing jar shows what earlier seeds took");
  } finally { restore(); }
});

test("the journal shows signs, egg counts and the room, and the Pulse carries the risk line", async () => {
  const restore = freezeTime(NOW);
  try {
    const jar = jarSummary({ risk: { level: "act", reason: "foam on the surface since the last restart" },
      history: [{ event: "sign", at: iso(2), ml: 0, tint: "", from: "", sign: "foam", eggRatio: 18, tempC: 24.1 },
                { event: "harvest", at: iso(30), ml: 625, tint: "green", from: "", sign: "", eggRatio: 0, tempC: 23.4 }] });
    const panel = await culturesPanel({}, summaryFixture([jar]));
    const html = panel._culturesTab();
    assert(html.includes(">Sign<") && html.includes(">Eggs<") && html.includes(">°C<"), "journal columns missing");
    assert(html.includes("foam on the surface") && html.includes("18 %") && html.includes(">24.1<"), "journal row values missing");
    panel._culturesLoadSummary = async () => {};
    const cards = panel._pulseInsightCards();
    const titles = cards.map((c) => `${c.kicker}: ${c.title}`).join(" | ");
    assert(titles.includes("Cultures: Rotifers A: foam on the surface since the last restart"), `risk card missing: ${titles}`);
  } finally { restore(); }
});


test("the DHA step: the enrich tick, the soak tile, the boost line and the next-harvest line", async () => {
  const restore = freezeTime(NOW);
  try {
    let panel = await culturesPanel();
    let html = panel._culturesTab();
    assert(html.includes('data-cultures-enrich="c1"') && html.includes("enrich this crop"), "the enrich tick is missing on a producing rotifer jar");
    assert(html.includes("harvest in ~14 h — before the bottle runs dry"), "the bottle card must carry the next-harvest line");
    assert(!html.includes("data-culture-soak"), "no soak, no soak tile");
    const soaking = summaryFixture();
    soaking.enrichment = { ...soaking.enrichment, soak: { status: "soaking", percent: 40, hoursLeft: 3.6, hoursElapsed: 2.4 }, portionMl: 625, jarId: "c1", jarName: "Rotifers A" };
    panel = await culturesPanel({}, soaking);
    html = panel._culturesTab();
    assert(html.includes("data-culture-soak") && html.includes("3 drops in · ~3.6 h to go") && html.includes("40%"), "the soaking tile is wrong");
    assert(html.includes('data-cultures-enrich="c1" disabled'), "a second crop cannot join a running soak");
    assert(html.includes('data-action="cultures-enrich-done"') && html.includes('data-action="cultures-enrich-plain"'), "soak buttons missing");
    const done = summaryFixture();
    done.enrichment = { ...done.enrichment, soak: { status: "done", percent: 100, hoursLeft: 6.5, hoursElapsed: 7.5 }, portionMl: 625, jarId: "c1", jarName: "Rotifers A" };
    done.bottle = { ...done.bottle, enriched: true, boost: { status: "gutloaded", hoursLeft: 19.2 } };
    done.nextHarvest = { status: "now", hoursUntil: 0, driver: "freshness" };
    panel = await culturesPanel({}, done);
    html = panel._culturesTab();
    assert(html.includes("done — rinse on the net and bottle") && html.includes('class="primary compact-button" data-action="cultures-enrich-done"'), "a finished soak must lead with Rinsed & bottled");
    assert(html.includes("enrichment estimate · ~19.2 h remaining") && html.includes("fridge · enriched"), "the boost line is missing on the bottle");
    assert(html.includes("harvest now — before the bottle goes stale"), "the next-harvest line must escalate");
    panel._culturesLoadSummary = async () => {};
    const titles = panel._pulseInsightCards().map((c) => `${c.kicker}: ${c.title}`).join(" | ");
    assert(titles.includes("Soak done — rinse and bottle the rotifers") && titles.includes("Harvest the cone now"), `Pulse lines missing: ${titles}`);
    noPlaceholders(html, "soak done");
  } finally { restore(); }
});

test("the tank's phyto is the shelf's business — nothing of it on the Cultures tab", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await culturesPanel();
    const html = panel._culturesTab();
    assert(!html.includes("The tank's phyto") && !html.includes("cultures-phyto-dosed"), "the phyto panel must be gone");
    const settings = panel._culturesSettings();
    assert(!settings.includes('data-scope="nps-culture-phyto"') && settings.includes('data-scope="nps-culture-enrich" data-field="drops"'),
      "phyto settings gone, enrichment settings stay");
    panel._culturesSeedReminders();
    assert(!panel._config.maintenance.tasks.culture_phyto_dose, "the cultures seeding must not conjure the phyto task");
    panel._culturesLoadSummary = async () => {};
    const titles = panel._pulseInsightCards().map((c) => `${c.kicker}: ${c.title}`).join(" | ");
    assert(!titles.includes("Phyto dose due"), `the cultures Pulse line must be gone: ${titles}`);
  } finally { restore(); }
});

test("the journal merges the bottle's rows, the hub card reads the bottle, the hatchery stamps the cysts", async () => {
  const restore = freezeTime(NOW);
  try {
    const summary = summaryFixture();
    summary.bottle = { ...summary.bottle, history: [{ event: "fed_tank", at: iso(1), ml: 20 }, { event: "enriched", at: iso(5), ml: 625 }] };
    const panel = await culturesPanel({}, summary);
    const html = panel._culturesTab();
    assert(html.includes("fed to the tank") && html.includes("enriched &amp; bottled") && html.includes(">Bottle<"), "the bottle's rows must show in the journal");
    const hub = panel._hubCards ? panel._hubCards() : panel._feedingHub?.() || "";
    const card = typeof hub === "string" ? hub : "";
    if (card) assert(card.includes("bottle 400 ml") && card.includes("harvest in ~14 h"), "the hub card must read the bottle and the next harvest");
    panel._nps.summary = { hatchery: { cysts: { available: true, openedAt: iso(22 * 24), days: 22, status: "aging" } } };
    const hs = panel._hatcherySettings();
    assert(hs.includes("opened 22 days ago") && !hs.includes('data-action="nps-cysts-opened"'), "settings shows the pouch age; the stamp moved to the tile (0.7.177)");
    const tile = panel._npsPouchLine({ id: "v1", cysts: { available: true, days: 22, status: "aging" } });
    assert(tile.includes("pouch opened 22 d ago") && tile.includes('data-action="nps-cysts-opened" data-id="v1"'), "the tile stamps the cysts");
    panel._culturesLoadSummary = async () => {};
    const titles = panel._pulseInsightCards().map((c) => `${c.kicker}: ${c.title}`).join(" | ");
    assert(titles.includes("Brine hatchery: Cysts pouch opened 22 days ago"), `cysts Pulse line missing: ${titles}`);
  } finally { restore(); }
});


test("never zero: the Jars card says backup or not, and the restart seeds B by default when there is none", async () => {
  const restore = freezeTime(NOW);
  try {
    let panel = await culturesPanel();
    let html = panel._culturesTab();
    assert(html.includes("no backup") && html.includes("split only a healthy, mature culture") && html.includes("12 days without a gap"), "the Jars card must say there is no backup and count continuity");
    assert(html.includes('data-cultures-split="c1" checked'), "with no backup the restart ticks 'seed B' by default");
    assert(html.includes("gen 1 · from the starter"), "the lineage line is missing");
    assert(html.includes('data-action="cultures-share-card" data-id="c1"'), "the share-card button is missing");
    const calls = [];
    panel._callWS = async (msg) => { calls.push(msg); return {}; };
    panel._culturesLoadSummary = async () => {};
    panel._culturesRestart("c1");
    await new Promise((r) => setTimeout(r, 0));
    assert(calls[0].type === "openreef/cultures_restart" && calls[0].split === false, "no DOM tick in the harness → split false, never a silent split");
    // Two running rotifer jars: backed up, stagger advice on the tile, no default split tick.
    const b = jarSummary({ id: "c2", name: "Rotifers B", lineage: { generation: 2, fromName: "Rotifers A", line: "gen 2 · from Rotifers A" },
      stagger: { available: true, days: 1, idealDays: 7, advice: "restart cycles only 1 days apart (ideal 7) — hold one restart 6 days to spread them" } });
    const two = summaryFixture([jarSummary({ stagger: { available: true, days: 1, idealDays: 7, advice: "restart cycles only 1 days apart (ideal 7) — hold one restart 6 days to spread them" } }), b]);
    panel = await culturesPanel({}, two);
    html = panel._culturesTab();
    assert(html.includes("backed up") && html.includes("rotifers (l-type): 2 running"), "two running jars are a backup");
    assert(html.includes("gen 2 · from Rotifers A · restart cycles only 1 days apart"), "the stagger advice rides the lineage line");
    assert(html.includes('data-cultures-split="c1" >') || html.includes('data-cultures-split="c1">'), "with a backup the split tick is off by default");
    noPlaceholders(html, "backup rack");
  } finally { restore(); }
});

test("the heat guard reads the day ahead onto the tile, the Room card and the Pulse", async () => {
  const restore = freezeTime(NOW);
  try {
    const warn = { available: true, status: "warn", peakC: 30.1, peakAt: iso(-15), crossAt: iso(-9), hoursUntil: 9,
      line: "room passes 28 °C in ~9 h (peak 30.1 °C) — extra air, shade, feed lightly, a 50 % change ready" };
    const pod = { ...summaryFixture().jars[1], state: { ...summaryFixture().jars[1].state, status: "producing", ageDays: 40 }, tint: "green", guard: warn };
    const summary = summaryFixture([jarSummary(), pod]);
    summary.backup = [
      { species: "rotifer_L", speciesName: "Rotifers (L-type)", running: 1, backedUp: false, continuityDays: 12, guard: { available: true, status: "watch", line: "room peaks at 28.4 °C — above the 26 °C band, keep an eye on it" } },
      { species: "tigriopus", speciesName: "Tigriopus copepods", running: 1, backedUp: false, continuityDays: 40, guard: warn },
    ];
    summary.guardAvailable = true;
    const panel = await culturesPanel({}, summary);
    const html = panel._culturesTab();
    assert(html.includes('data-culture-guard="warn"') && html.includes("🌡️ tomorrow: room passes 28 °C in ~9 h"), "the pods' tile must carry the day-ahead warning");
    assert(html.includes("tomorrow: room passes 28 °C"), "the Room card must escalate to the guard when the room is fine today");
    panel._culturesLoadSummary = async () => {};
    const titles = panel._pulseInsightCards().map((c) => `${c.kicker}: ${c.title}`).join(" | ");
    assert(titles.includes("Cultures: Heat ahead for the tigriopus copepods"), `guard Pulse line missing: ${titles}`);
    noPlaceholders(html, "guard");
  } finally { restore(); }
});

test("the culture card draws the story: name, species, day, generation, the ring and the tint strip", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await culturesPanel();
    const sum = panel._cultures.summary;
    const svg = panel._culturesCardSvg(sum.jars[0], sum);
    assert(svg.startsWith("\n      <svg xmlns=") && svg.includes("Rotifers A") && svg.includes("Brachionus plicatilis"), "the card header is wrong");
    assert(svg.includes("day 12 · producing · gen 1 · from the starter") && svg.includes("12 days without a gap"), "the story lines are missing");
    assert(svg.includes(">86%<") && svg.includes("restart cycle"), "the restart ring is missing");
    assert((svg.match(/<rect x="\d+" y="160"/g) || []).length === 14, "the strip must be 14 days");
    assert(svg.includes('fill="#43a047"') && svg.includes('fill="#9ccc65"') && svg.includes('fill="#1c262e"'), "the strip colours must follow the tints and blanks");
    assert(svg.includes("built with OpenReef"), "the card is unsigned");
    const crashed = panel._culturesCardSvg({ ...sum.jars[0], state: { ...sum.jars[0].state, status: "crashed", percent: null } }, sum);
    assert(crashed.includes(">crashed · gen 1") && crashed.includes(">—<"), "a crashed jar's card says so");
  } finally { restore(); }
});


// --------------------------------------------------------------------------- //
// 0.7.140 — the §8.12 gaps: the ghost cone B, the bleed in the journal, the
// arrival maths, the demo view.
// --------------------------------------------------------------------------- //
test("one running cone pencils B in: dashed, faint, named, and not counted as a cone", async () => {
  const restore = freezeTime(NOW);
  try {
    const one = summaryFixture([jarSummary()]);
    one.rig.cones.push({ id: "", name: "Rotifers B", kind: "cone", status: "ghost", tint: "", pct: 0, airOn: false, purgeHot: false,
      harvestHot: false, refillHot: false, feedHot: false, restartHot: false, tempStatus: "unknown", establishDays: null, firstHarvestDays: 6,
      note: "comes with the first restart" });
    const panel = await culturesPanel({}, one);
    const svg = panel._culturesRigSvg(one.rig);
    assert(svg.includes("ROTIFERS B") && svg.includes("comes with the first restart"), "the ghost must be labelled and explained");
    assert(svg.includes('data-cultures-ghost="1"') && svg.includes('opacity="0.45"'), "the ghost is drawn faint");
    assert((svg.match(/stroke-dasharray="6 4"/g) || []).length >= 3, "the ghost's body and its drop are dashed");
    assert(!svg.includes("CONE 2"), "no fallback name for the ghost");
    const html = panel._culturesTab();
    assert(html.includes("One cone on the hatchery") && html.includes("B is pencilled in beside A"), "the shape line counts real cones and explains B");
    noPlaceholders(html, "cultures tab with a ghost cone");
    const two = summaryFixture([jarSummary(), jarSummary({ id: "c2", name: "Rotifers B" })]);
    const twoSvg = panel._culturesRigSvg(two.rig);
    assert(!twoSvg.includes('data-cultures-ghost="1"'), "the fixture without a ghost draws none");
  } finally { restore(); }
});

test("the journal shows the bleed and the learned purge line", async () => {
  const restore = freezeTime(NOW);
  try {
    const jar = jarSummary({
      history: [{ event: "harvest", at: iso(2), ml: 625, tint: "clearing", from: "", sign: "", eggRatio: 0, tempC: 24.1, purgeMl: 50 },
                { event: "restart", at: iso(9 * 24), ml: 2500, tint: "green", from: "", sign: "", eggRatio: 0, tempC: 24.0, purgeMl: 100 },
                { event: "feed", at: iso(14), ml: 0, tint: "green", from: "", sign: "", eggRatio: 0, tempC: null, purgeMl: 0 }],
      learned: { ...jarSummary().learned, purge: { available: true, byPurge: { "50": { days: 11, runs: 2 }, "100": { days: 13, runs: 2 } },
        line: "runs bled ~100 ml lasted ~13 d, ~50 ml lasted ~11 d (2 + 2 runs) — the bigger purge buys ~2 more days" } },
    });
    const panel = await culturesPanel({}, summaryFixture([jar]));
    const html = panel._culturesTab();
    assert(html.includes("harvested · bled 50 ml") && html.includes("restarted · bled 100 ml"), "the bleed rides the What column");
    assert(!html.includes("fed · bled"), "a feed has no bleed");
    assert(html.includes("Purge: runs bled ~100 ml lasted ~13 d") && html.includes("the bigger purge buys ~2 more days."), "the learned purge line is on the tile");
    const quiet = await culturesPanel({}, summaryFixture([jarSummary()]));
    assert(!quiet._culturesTab().includes("Purge: runs bled"), "no comparison, no line");
    noPlaceholders(html, "cultures tab with purge rows");
  } finally { restore(); }
});

test("the arrival walkthrough carries the acclimation maths, and a plain rule without them", async () => {
  const restore = freezeTime(NOW);
  try {
    const virgin = () => summaryFixture([
      jarSummary({ state: { ...jarSummary().state, status: "none", percent: null }, tint: "", due: [], history: [] }),
      summaryFixture().jars[1],
    ]);
    const withPlan = virgin();
    withPlan.arrival = { rotifer: { fromPpt: 27, toPpt: 35, pouchMl: 500, steps: [{ addMl: 500, ppt: 31, waitMin: 15 }], finalStepPpt: 4, withinRule: true,
      line: "the starter is at ~27 ppt and the cone at 35: float the pouch 15 min, then add 500 ml of cone water, wait 15 min (~31 ppt); then net them into the cone — the last step is 4 ppt" } };
    let panel = await culturesPanel({}, withPlan);
    let html = panel._culturesTab();
    assert(html.includes("the starter is at ~27 ppt and the cone at 35") && html.includes("add 500 ml of cone water, wait 15 min (~31 ppt)"), "the measured plan must be quoted");
    assert(html.includes("the last step is 4 ppt."), "the sentence ends with the final step");
    assert(!html.includes("add cone water to it in steps"), "the plain rule gives way to the maths");
    panel = await culturesPanel({}, virgin());
    html = panel._culturesTab();
    assert(html.includes("Measure starter salinity and volume"), "without a measured salinity the page requests a measurement");
    noPlaceholders(html, "walkthrough");
  } finally { restore(); }
});

test("the demo view stages a rack, refuses every tap, and hands the real rack back on exit", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await culturesPanel();
    const calls = [];
    panel._callWS = async (msg) => { calls.push(msg); return {}; };
    const real = panel._cultures.summary;
    panel._culturesToggleDemo();
    assert(panel._cultures.demo === true && panel._cultures.summary !== real, "the demo swaps the summary");
    const sum = panel._cultures.summary;
    assert(sum.jars.length === 4 && sum.jars.map((j) => j.name).join(",") === "Rotifers A,Rotifers B,Pods,Nanno A", "two cones, the tub and the phyto vessel");
    assert(sum.enrichment.soak.status === "soaking" && sum.backup[1].guard.status === "warn" && sum.jars[0].learned.purge.available, "a soak, a warning, a journal that learned");
    const html = panel._culturesTab();
    assert(html.includes("Demo view — a staged rack") && html.includes("Exit demo"), "the banner and the exit button");
    assert(html.includes("ROTIFERS A") && html.includes("ROTIFERS B") && html.includes("PODS · TUB"), "the rig draws the staged rack");
    assert(html.includes("tomorrow") && html.includes("enrichment estimate") && html.includes("Purge: runs bled"), "the guard, the boost and the learned purge show");
    assert(html.includes("harvested · bled 50 ml"), "the journal carries the bleed");
    noPlaceholders(html, "cultures demo view");
    // Every tap is refused; nothing reaches the backend; nothing is saved.
    await panel._culturesCall({ type: "openreef/cultures_log", jar_id: "a", fed: true });
    assert(calls.length === 0 && panel._cultures.message.startsWith("Demo view — the buttons are for show"), "a tap in the demo is for show");
    panel._culturesLog("a", true, true);
    panel._culturesRestart("a");
    await panel._culturesLoadSummary(true);
    assert(calls.length === 0, "no refresh, no WS in the demo");
    panel._culturesSeedReminders();
    assert(!Object.keys(panel._config.maintenance.tasks || {}).length && panel._configDirty === false, "the staged jars never seed reminders on the real rack");
    // Exit: the stash comes back and the real summary is asked for again.
    panel._culturesToggleDemo();
    assert(panel._cultures.demo === false && panel._cultures.summary === real, "exit restores the real summary");
    await new Promise((r) => setTimeout(r, 0));
    assert(calls.length === 1 && calls[0].type === "openreef/cultures_summary", "exit refreshes from the backend");
    assert(panel._cultures.message.startsWith("Demo view closed"), "and says so");
  } finally { restore(); }
});

test("day 0 shows the fill split from the station's water, the harvest tap sends what went into the bottle", async () => {
  const restore = freezeTime(NOW);
  try {
    const fill = { totalMl: 2000, mixMl: 1543, rodiMl: 457, targetPpt: 27, mixPpt: 35, sg: 1.0204 };
    const fresh = summaryFixture([
      jarSummary({ name: "Rotifers A", volumeL: 2, salinityPpt: 27, state: { ...jarSummary().state, status: "none", percent: null }, tint: "", due: [], history: [],
        fillGuide: fill, restartGuide: fill, harvestGuide: { totalMl: 500, mixMl: 386, rodiMl: 114, targetPpt: 27, mixPpt: 35, sg: 1.0204 },
        arrivalFillGuide: { totalMl: 2000, mixMl: 1543, rodiMl: 457, targetPpt: 27, mixPpt: 35, sg: 1.0204 }, pouchMl: 500 }),
      summaryFixture().jars[1],
    ]);
    fresh.rig = { ...fresh.rig, jug: { mode: "fill", harvestMl: 2000, mixMl: 1543, rodiMl: 457, ppt: 27, mixPpt: 35, purgeMl: 50, sieveUm: 50 } };
    let panel = await culturesPanel({}, fresh);
    let html = panel._culturesTab();
    assert(html.includes("fill 2000 ml: <strong>1543 ml of 35 ppt mix + 457 ml RODI</strong> → 27 ppt (SG 1.0204)"), `the tile must carry the fill split: ${html.match(/fill [^<]*<strong>[^<]*<\/strong>[^<]*/)?.[0]}`);
    assert(html.includes("↳ <strong>Rotifers A</strong>: prepare 2000 ml — 1543 ml of 35 ppt mix + 457 ml RODI → 27 ppt."), `the arrival panel must fill the working volume for a sieved starter: ${html.match(/↳ [^.]*\./)?.[0]}`);
    assert(!html.includes("the jug says how much RODI"), "the old hand-wave is gone");
    const rig = panel._culturesRigSvg(panel._culturesRigState());
    assert(rig.includes("fill 2000 ml: 1543 ml of 35 ppt mix") && rig.includes("+ 457 ml RODI · @ 27 ppt") && !rig.includes("purge ~"), "the rig's jug reads fill on day 0");
    noPlaceholders(html, "day-0 tab");
    // A 35 ppt jar: straight mix, no RODI, no dangling plus.
    const matched = summaryFixture([jarSummary({ state: { ...jarSummary().state, status: "none", percent: null }, tint: "", due: [], history: [] })]);
    html = (await culturesPanel({}, matched))._culturesTab();
    assert(html.includes("fill 2500 ml: <strong>2500 ml of 35 ppt mix</strong> → 35 ppt (SG 1.0264)"), "a matched jar shows straight mix");
    // Producing: the bottle input rides the harvest tap and the tap sends it.
    panel = await culturesPanel();
    html = panel._culturesTab();
    assert(html.includes('data-cultures-bottle-ml="c1"') && html.includes("Blank = the whole harvest volume (625 ml)"), "the bottle input is missing");
    const c1Tile = html.slice(html.indexOf('data-culture="c1"'), html.indexOf('data-culture="c2"'));
    assert(c1Tile.length > 0 && !c1Tile.includes("fill 2500 ml"), "a running jar shows no fill line");
    const c2Tile = html.slice(html.indexOf('data-culture="c2"'));
    assert(c2Tile.includes("fill 2500 ml"), "the unseeded tub still shows its fill");
    const calls = [];
    panel._callWS = async (msg) => { calls.push(msg); return {}; };
    panel._culturesLoadSummary = async () => {};
    const box = panel.shadowRoot?.querySelector('[data-cultures-bottle-ml="c1"]');
    if (box) {
      box.value = "150";
      panel._culturesLog("c1", true, true);
      await new Promise((r) => setTimeout(r, 0));
      assert(calls[0]?.bottle_ml === 150 && calls[0]?.harvested === true, `the tap must send bottle_ml: ${JSON.stringify(calls[0])}`);
    }
  } finally { restore(); }
});

test("audit: new jars use the species salinity and zero egg observations are sent", async () => {
  const panel = await culturesPanel();
  panel._culturesAddJar();
  assert(panel._config.nps.cultures.jars.c3.salinityPpt === 27, "new rotifers use 27 ppt");
  let sent;
  panel._culturesCall = (msg) => { sent = msg; };
  panel.shadowRoot = { querySelector: (selector) => selector.includes("data-cultures-egg") ? { value: "0" } : null };
  panel._culturesLog("c1", false, false);
  assert(sent.egg_ratio === 0, "a measured zero is not missing");
});

test("audit: the refill labels the stock salinity and includes purge water", async () => {
  const jar = jarSummary({ salinityPpt: 27, harvestGuide: { totalMl: 625, refillMl: 675, mixMl: 521, rodiMl: 154, mixPpt: 35, targetPpt: 27 } });
  const panel = await culturesPanel({}, summaryFixture([jar]));
  const html = panel._culturesTab();
  assert(html.includes("refill 521 ml @ 35 ppt + 154 ml RODI → 27 ppt"), "stock and final salinity must be distinct");
  assert(html.includes("harvest + purge replaced"), "both withdrawals are replaced");
  panel._cultures.summary.jars[0].harvestGuide = { available: false, reason: "Cannot make 40 ppt by diluting 35 ppt water" };
  assert(panel._culturesTab().includes("Cannot make 40 ppt"), "an impossible recipe must be explained");
});

test("audit: maintenance waits for the backend first-harvest clock and preserves half days", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await culturesPanel();
    panel._culturesLoadSummary = async () => {};
    panel._config.maintenance.enabled = true;
    panel._config.nps.cultures.jars.c1.cadence.harvestIntervalDays = 0.5;
    panel._culturesSeedReminders();
    assert(panel._config.maintenance.tasks.culture_c1_harvest.cadenceHours === 12, "half a day is twelve hours");
    panel._config.maintenance.tasks.culture_c1_restart.cadenceHours = 90 * 24;
    assert(panel._maintenanceTask("culture_c1_restart").cadenceHours === 2160, "a 90-day culture interval must not clamp to fourteen days");
    panel._cultures.summary.jars[0].state.harvest = { available: true, due: false, at: iso(-48), hoursUntil: 48 };
    assert(panel._maintenanceDueState("culture_c1_harvest").status === "ok", "generic cadence must not override establishment");
    assert(panel._maintenanceNextDueMs("culture_c1_harvest") === Date.parse(iso(-48)), "upcoming uses the same due instant");
    panel._cultures.summary.jars[0].state.harvest = { available: false, due: false };
    assert(panel._maintenanceDueState("culture_c1_harvest").status === "unknown", "crashed and idle jars have no harvest clock");
  } finally { restore(); }
});

test("audit: enrichment completion is disabled before the soak is done", async () => {
  const summary = summaryFixture();
  summary.enrichment.soak = { status: "soaking", percent: 20, hoursLeft: 4 };
  const panel = await culturesPanel({}, summary);
  const html = panel._culturesTab();
  assert(/data-action="cultures-enrich-done"[^>]*disabled/.test(html), "cannot claim enrichment early");
  assert(html.includes('data-action="cultures-enrich-plain"'), "an abandoned soak can still be logged plain");
});

test("a harvest names where it went: the tile's select, the settings default, the tap's word", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await culturesPanel();
    let html = panel._culturesTab();
    assert(html.includes('data-cultures-harvest-to="c1"') && html.includes('<option value="bottle" selected>the fridge bottle</option>'), "the producing rotifer tile must carry the destination select, bottle by default");
    assert(html.includes('>Rinsed in<span class="unit"><input type="number" min="1" max="5000" step="10" placeholder="625" data-cultures-bottle-ml="c1"'), "the rinse box lost its label — blank means the whole harvest, so the box shows it");
    const c2Tile = html.slice(html.indexOf('data-culture="c2"'));
    assert(!c2Tile.includes("data-cultures-harvest-to"), "the pods have nowhere else than the tank — no select");
    const settings = panel._culturesSettings();
    assert(settings.includes('data-scope="nps-culture-jar" data-id="c1" data-field="harvestTo"') && settings.includes("straight into the tank (no bottle)"), "the rotifer jar must offer its default destination");
    assert(!settings.includes('data-id="c2" data-field="harvestTo"'), "the pods offer no destination");
    const calls = [];
    panel._callWS = async (msg) => { calls.push(msg); return {}; };
    panel._culturesLoadSummary = async () => {};
    panel._npsLoadSummary = async () => {};
    panel._culturesLog("c1", false, true, "tank");
    await new Promise((r) => setTimeout(r, 0));
    assert(calls[0]?.harvested === true && calls[0]?.destination === "tank" && !calls[0]?.fed, `the tap must send its destination: ${JSON.stringify(calls[0])}`);
    assert(panel._cultures.message.includes("straight into the tank"), "the message must say where it went");
    panel._culturesLog("c1", true, true);
    await new Promise((r) => setTimeout(r, 0));
    const select = panel.shadowRoot?.querySelector('[data-cultures-harvest-to="c1"]');
    if (select) {
      assert(calls[1]?.destination === "bottle", `the tile's select is the default word: ${JSON.stringify(calls[1])}`);
      select.value = "tank";
      panel._culturesLog("c1", true, true);
      await new Promise((r) => setTimeout(r, 0));
      assert(calls[2]?.destination === "tank", "the select's choice rides the tap");
    }
    // A tank-default jar renders the select on tank.
    const fixture = summaryFixture([jarSummary({ harvestTo: "tank" }), summaryFixture().jars[1]]);
    html = (await culturesPanel({}, fixture))._culturesTab();
    assert(html.includes('<option value="tank" selected>straight into the tank</option>'), "the jar's default must lead the select");
  } finally { restore(); }
});

test("the rack tile is a tidy form: compact ticks, a labelled egg check, aligned rows (0.7.163)", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await culturesPanel();
    const html = panel._culturesTab();
    noPlaceholders(html, "rack tiles");
    assert(html.includes('<div class="culture-tile" data-culture="c1">'), "the tile carries the rack class");
    const c1 = html.slice(html.indexOf('data-culture="c1"'), html.indexOf('data-culture="c2"'));
    // Every control sits on a labelled row; the ticks are ticks, not 42 px boxes.
    assert(c1.includes('<label class="culture-field" title="Aim for leafy green — spinach, not pea soup">Water<select data-cultures-tint="c1">'), "the Water row");
    assert(c1.includes('>Harvest to<select data-cultures-harvest-to="c1">'), "the destination row");
    assert(c1.includes('<label class="culture-tick" title="The DHA step') && c1.includes('data-cultures-enrich="c1"'), "the enrich tick is a compact tick");
    assert(c1.includes('<span>Signs</span>') && c1.includes('<div class="culture-signs">'), "the signs row");
    assert(c1.includes('>Egg ratio<span class="unit">') && c1.includes('placeholder="%" data-cultures-egg="c1"') && c1.includes("observe the trend") && !c1.includes("≥ 30 % is healthy"), "the egg check is labelled");
    assert(c1.includes('<span>Restart</span><label class="culture-tick"') && c1.includes('data-cultures-split="c1"'), "the split tick is a compact tick");
    assert(!c1.includes("width:64px") && !c1.includes("% eggs") && !c1.includes("Sign:"), "the clipped placeholder and the bare row are gone");
    // Head, form, notes, observations, actions — in that order.
    const order = ['class="culture-jar"', 'class="culture-head"', 'class="culture-form"', 'class="culture-notes"', "<span>Signs</span>", 'class="button-row"'];
    let last = -1;
    for (const needle of order) { const idx = c1.indexOf(needle); assert(idx > last, `tile out of order at ${needle}`); last = idx; }
    // The stylesheet sizes the ticks and the compact controls.
    const css = panel._styles();
    assert(css.includes('.culture-tick input[type="checkbox"] { width: 15px; height: 15px; min-height: 0;'), "tick sizing rule missing");
    assert(css.includes('.culture-field select, .culture-field input[type="number"] { min-height: 30px;'), "compact control rule missing");
  } finally { restore(); }
});


// --- 0.7.184: the look that decided not to feed, and the timeline ----------
test("rack tile: Looked logs the water alone; Skip feed only when the feed is due; a held clock says so", async () => {
  const restore = freezeTime(NOW);
  try {
    const held = jarSummary({ id: "c2", name: "Rotifers B", due: [], tint: "green",
      state: { ...jarSummary().state, feed: { ...clock(false, 9), skipped: true } },
      feedAdvice: { action: "wait", reason: "still green — check before adding more food" } });
    const panel = await culturesPanel({}, summaryFixture([jarSummary(), held]));
    const html = panel._culturesTab();
    noPlaceholders(html, "skip/looked tile");
    const c1 = html.slice(html.indexOf('data-culture="c1"'), html.indexOf('data-culture="c2"'));
    const c2 = html.slice(html.indexOf('data-culture="c2"'));
    assert(c1.includes('data-action="cultures-looked" data-id="c1"'), "Looked is on the tile");
    assert(c1.includes('data-action="cultures-skip-feed" data-id="c1"') && c1.includes("holds until the next slot"), "Skip feed sits beside Fed when the feed is due");
    assert(c1.indexOf('cultures-looked') < c1.indexOf('cultures-fed"') && c1.indexOf('cultures-fed"') < c1.indexOf('cultures-skip-feed'), "Looked · Fed · Skip feed, in that order");
    assert(!c1.includes('data-culture-skipped="c1"'), "a due feed is not 'held'");
    assert(c2.includes('data-action="cultures-looked" data-id="c2"') && !c2.includes("cultures-skip-feed"), "nothing to skip when the feed is not due");
    assert(c2.includes('data-culture-skipped="c2">feed skipped · next look in ~9 h</small>'), "the held clock is said plainly");
  } finally { restore(); }
});

test("the taps: Skip feed sends the tint and skip_feed, Looked sends the tint alone, and neither goes out empty", async () => {
  const panel = await culturesPanel();
  const calls = [];
  panel._callWS = async (msg) => { calls.push(msg); return {}; };
  panel._culturesLoadSummary = async () => {};
  let tint = "green";
  panel.shadowRoot = { querySelector: (selector) => selector.includes("data-cultures-tint") ? { value: tint } : null };
  panel._culturesLog("c1", false, false, "", true);
  await new Promise((r) => setTimeout(r, 0));
  assert(calls.length === 1 && calls[0].type === "openreef/cultures_log" && calls[0].jar_id === "c1", `one cultures_log call: ${JSON.stringify(calls)}`);
  assert(calls[0].tint === "green" && calls[0].skip_feed === true && !("fed" in calls[0]) && !("harvested" in calls[0]), `the skip: ${JSON.stringify(calls[0])}`);
  assert(panel._cultures.message.includes("Feed skipped") && panel._cultures.message.includes("holds until the next slot"), panel._cultures.message);
  panel._culturesLog("c1", false, false);
  await new Promise((r) => setTimeout(r, 0));
  assert(calls.length === 2 && calls[1].tint === "green" && !("skip_feed" in calls[1]) && !("fed" in calls[1]), `the look: ${JSON.stringify(calls[1])}`);
  assert(panel._cultures.message.startsWith("Tint logged — nothing else moved."), panel._cultures.message);
  // Fed wins over skip if both were somehow asked for.
  panel._culturesLog("c1", true, false, "", true);
  await new Promise((r) => setTimeout(r, 0));
  assert(calls[2].fed === true && !("skip_feed" in calls[2]), `fed, not skipped: ${JSON.stringify(calls[2])}`);
  // No tint picked, nothing else typed: no call, a nudge instead.
  tint = "";
  panel._culturesLog("c1", false, false);
  await new Promise((r) => setTimeout(r, 0));
  assert(calls.length === 3 && panel._cultures.message.startsWith("Pick the water you saw first"), `an empty look stays home: ${panel._cultures.message}`);
  // A skip with no tint still goes — the skip is the fact.
  panel._culturesLog("c1", false, false, "", true);
  await new Promise((r) => setTimeout(r, 0));
  assert(calls.length === 4 && calls[3].skip_feed === true && !("tint" in calls[3]), `a bare skip: ${JSON.stringify(calls[3])}`);
});

test("timeline: a lane per jar — the tint band, the taps, the clearing spans, the open span, the range toggle", async () => {
  const restore = freezeTime(NOW);
  try {
    const timeline = { days: 30, since: iso(30 * 24), tintBefore: "clear",
      marks: [
        { at: iso(20 * 24), event: "feed", tint: "green", fed: true, skipped: false, ml: 0, sign: "", tempC: 24.1 },   // outside a 14-day view
        { at: iso(5 * 24 + 6), event: "feed", tint: "green", fed: true, skipped: false, ml: 0, sign: "", tempC: 24.0 },
        { at: iso(5 * 24 - 3), event: "tint", tint: "clear", fed: false, skipped: false, ml: 0, sign: "", tempC: null },
        { at: iso(4 * 24), event: "tint", tint: "green", fed: false, skipped: true, ml: 0, sign: "", tempC: 24.4 },
        { at: iso(3 * 24), event: "harvest", tint: "clearing", fed: true, skipped: false, ml: 625, sign: "", tempC: 24.2 },
        { at: iso(2 * 24), event: "sign", tint: "", fed: false, skipped: false, ml: 0, sign: "foam", tempC: null },
        { at: iso(30), event: "feed", tint: "green", fed: true, skipped: false, ml: 0, sign: "", tempC: 24.6 },
      ],
      spans: [
        { fedAt: iso(20 * 24), clearAt: iso(19 * 24), hours: 24, open: false },     // outside a 14-day view
        { fedAt: iso(5 * 24 + 6), clearAt: iso(5 * 24 - 3), hours: 9, open: false },
        { fedAt: iso(30), clearAt: null, hours: 30, open: true },
      ] };
    const jar = jarSummary({ timeline, learned: { ...jarSummary().learned, clearingH: { available: true, hours: 9.2, samples: 3 } } });
    const bare = jarSummary({ id: "c2", name: "Rotifers B", timeline: { days: 30, since: iso(30 * 24), tintBefore: "", marks: [], spans: [] } });
    const panel = await culturesPanel({}, summaryFixture([jar, bare]));
    let html = panel._culturesTab();
    noPlaceholders(html, "timeline");
    assert(html.includes('data-culture-timeline="14"'), "14 days by default");
    assert(html.indexOf('data-culture-timeline="14"') < html.indexOf("The rig") || !html.includes("The rig"), "the timeline sits above the rig, under the rack");
    const tl = html.slice(html.indexOf('data-culture-timeline="14"'), html.indexOf("culture-tl-legend"));
    const lane = tl.slice(tl.indexOf('data-tl-jar="c1"'), tl.indexOf('data-tl-jar="c2"'));
    assert((lane.match(/data-tl-mark="feed"/g) || []).length === 2, "two feeds inside the fortnight (the 20-day-old one is out)");
    assert(lane.includes('data-tl-mark="skip"') && lane.includes("stroke-dasharray") && lane.includes("looked (green) — feed skipped"), "the skipped look is a hollow, dotted triangle with its story");
    assert(lane.includes('data-tl-mark="harvest"') && lane.includes("harvested 625 ml + fed"), "the harvest diamond");
    assert(lane.includes('data-tl-mark="sign"') && lane.includes("a crash sign: foam"), "the sign");
    assert(lane.includes('data-tl-band="clear"') && lane.includes("as last reported before this window"), "the band starts from the tint in force before the window");
    assert((lane.match(/data-tl-tint=/g) || []).length === 5, "one dot per tint tap in view (two feeds, a look, a skipped look, a harvest)");
    assert(lane.includes('data-tl-span="closed"') && lane.includes(">9 h</text>") && !lane.includes(">24 h<"), "the 9 h clearing span is drawn and labelled; the old one is out of view");
    assert(lane.includes('data-tl-span="open"') && lane.includes("still clearing, 30 h so far") && lane.includes(">30 h</text>"), "the open span is measured to now");
    assert(tl.includes("clears in ~9.2 h · 3 feeds") && tl.includes("clearing for 30 h"), "the lane's name carries the learned time and the open wait");
    assert(tl.includes('data-tl-jar="c2"') && tl.includes("no looks in this window"), "an empty lane says so");
    assert(tl.includes('data-action="cultures-timeline-days" data-days="7"') && tl.includes('class="primary compact-button" data-action="cultures-timeline-days" data-days="14"'), "the range toggle");
    assert(html.includes("▽ looked, feed skipped") && html.includes("dashed = still clearing"), "the legend");
    // The 30-day view lets the old feed and its span back in.
    panel._cultures.timelineDays = 30;
    html = panel._culturesTab();
    const lane30 = html.slice(html.indexOf('data-tl-jar="c1"'), html.indexOf('data-tl-jar="c2"'));
    assert((lane30.match(/data-tl-mark="feed"/g) || []).length === 3 && lane30.includes(">24 h</text>"), "30 days shows all three feeds and the 24 h span");
    assert(html.includes('data-culture-timeline="30"'), "the toggle is reflected");
    // The demo view carries a timeline per jar.
    const demo = panel._culturesDemoData().summary;
    assert(demo.jars.every((j) => Array.isArray(j.timeline?.marks) && j.timeline.marks.length && Array.isArray(j.timeline.spans)), "demo jars have timelines");
    assert(demo.jars[0].timeline.marks.some((m) => m.skipped) && demo.jars[0].timeline.spans.some((sp) => sp.open), "the demo shows a skip and an open span");
    for (let i = 1; i < demo.jars[0].timeline.marks.length; i += 1) {
      assert(Date.parse(demo.jars[0].timeline.marks[i - 1].at) <= Date.parse(demo.jars[0].timeline.marks[i].at), "demo marks are oldest first");
    }
  } finally { restore(); }
});

test("journal: a skipped look and a bare skip are named", async () => {
  const restore = freezeTime(NOW);
  try {
    const jar = jarSummary({ history: [
      { event: "tint", at: iso(2), ml: 0, tint: "green", from: "", sign: "", eggRatio: null, tempC: 24.1, skipped: true },
      { event: "skip", at: iso(26), ml: 0, tint: "", from: "", sign: "", eggRatio: null, tempC: null, skipped: true },
      { event: "tint", at: iso(50), ml: 0, tint: "clear", from: "", sign: "", eggRatio: null, tempC: null, skipped: false },
    ] });
    const panel = await culturesPanel({}, summaryFixture([jar]));
    const html = panel._culturesTab();
    const journal = html.slice(html.indexOf("Culture journal"));
    assert(journal.includes(">looked · feed skipped<"), "the look that skipped");
    assert(journal.includes(">feed skipped<"), "the bare skip");
    assert(journal.includes(">looked<"), "a plain look stays a look");
  } finally { restore(); }
});

test("a refused cultures tap outlives the summary reload (0.7.186)", async () => {
  // Same defect as the hatchery's dead "Harvest now": every rack button
  // stores the backend's refusal and then reloads, and the reload wiped it.
  const panel = await culturesPanel();
  panel._cultures = { ...(panel._cultures || {}), loading: false, demo: false, error: "", loadError: "", message: "" };
  const REFUSAL = "That bottle is empty — harvest before you feed from it.";
  const renders = [];
  panel._render = () => renders.push(panel._cultures.error);
  panel._callWS = async (call) => {
    if (call.type === "openreef/cultures_summary") return panel._cultures.summary || {};
    throw new Error(REFUSAL);
  };
  await panel._culturesCall({ type: "openreef/cultures_feed_skip", id: "cone-a" }, "Fed.");
  for (let i = 0; i < 5; i += 1) await new Promise((r) => setTimeout(r, 0));
  assert(renders.length >= 1, "the tap must paint");
  assert(renders.every((e) => e === REFUSAL), `every paint after the tap must carry the refusal: ${JSON.stringify(renders)}`);
  assert(panel._cultures.error === REFUSAL, "the refusal must still be on state after the reload");
  panel._callWS = async () => { throw new Error("Could not load the cultures."); };
  await panel._culturesLoadSummary(true);
  assert(panel._cultures.error === "Could not load the cultures.", "a failed load reports itself");
  panel._callWS = async () => ({});
  await panel._culturesLoadSummary(true);
  assert(panel._cultures.error === "", "a good load clears the loader's own failure");
});

test("journal: a daily tap inside the day carries Undo, a ceremony and an old row do not, a taken-back row is struck", async () => {
  const restore = freezeTime(NOW);
  try {
    const row = (f) => ({ event: "tint", at: iso(2), ml: 0, tint: "", from: "", sign: "", eggRatio: null, tempC: null, skipped: false, fed: false, ...f });
    const jar = jarSummary({ history: [
      row({ event: "feed", at: iso(1), tint: "green", fed: true }),
      row({ event: "tint", at: iso(3), tint: "clearing", undoneAt: iso(0.5) }),
      row({ event: "harvest", at: iso(5), ml: 500 }),
      row({ event: "feed", at: iso(30), tint: "clear", fed: true }),
    ] });
    const panel = await culturesPanel({}, summaryFixture([jar]));
    const html = panel._culturesTab();
    const journal = html.slice(html.indexOf("Culture journal"));
    const undos = journal.match(/data-action="cultures-undo"/g) || [];
    assert(undos.length === 1, `one Undo — the feed from an hour ago: ${undos.length}`);
    assert(journal.includes(`data-action="cultures-undo" data-id="${jar.id}" data-at="${iso(1)}"`), "the button names the jar and the row");
    assert(journal.includes("culture-journal-undone") && journal.includes("looked · taken back"), "the taken-back look is struck and named");
    // The tap sends the row's stamp; the reply message tells the keeper to log it again.
    const calls = [];
    panel._callWS = async (call) => { calls.push(call); return {}; };
    await panel._culturesUndo(jar.id, iso(1));
    assert(calls[0].type === "openreef/cultures_undo" && calls[0].jar_id === jar.id && calls[0].at === iso(1), JSON.stringify(calls[0]));
    assert(panel._cultures.message.includes("Taken back"), panel._cultures.message);
    calls.length = 0;
    await panel._culturesUndo(jar.id, "");
    assert(calls.length === 0, "no stamp, no call");
  } finally { restore(); }
});


// ---------------------------------------------------------------------------
// 0.7.207 — the phyto vessel, Stage A (docs/phyto-culture-brainstorm.md §5.9)
// ---------------------------------------------------------------------------
function phytoJar(over = {}) {
  return {
    id: "n1", name: "Nanno A", species: "nanno", speciesName: "Nannochloropsis (phyto)", kind: "phyto",
    latin: "Nannochloropsis oculata", volumeL: 4, salinityPpt: 35, vesselKind: "bottle", purgeMl: 0, sieveUm: 0, adultSieveUm: 0,
    tintTarget: "dense, dark green", firstHarvestDays: 7, note: "The culture IS the colour.",
    feed: { productId: "", productName: null, doseMl: 5 },
    cadence: { feedIntervalH: 24, harvestIntervalDays: 8, harvestPct: 60, restartIntervalDays: 0, waterChangeIntervalDays: 0, waterChangePct: 0, splitPct: 60, splitIntervalDays: 8, restartCycles: 4, lightHours: 16 },
    mode: "batch", workingL: 1.25, harvestTo: "bottle", hasBottle: false, hasHomeBottle: true, seededFrom: "", reseedFrom: [], reseedFromBottle: false, lastSign: "",
    tints: ["pale", "green", "dark", "off"],
    signs: [{ id: "yellow", label: "yellowing" }, { id: "brown", label: "browning" }, { id: "cloudy", label: "cloudy water" }, { id: "smell", label: "a smell" }],
    state: { status: "producing", ageDays: 9, daysSinceRestart: 9, percent: 25, splitEligible: true, workingL: 1.25, mode: "batch",
             cycle: { day: 8, ofDays: 8, percent: 100 }, daysSinceSplit: 8, darkDays: 1, peakHeld: false, cyclesSinceFresh: 1, restartCycles: 4, harvestBlocked: false,
             feed: clock(false, 0, false), look: clock(true, 0), harvest: { ...clock(true, 0), reason: "dark" }, restart: clock(false, 3 * 8 * 24), waterChange: clock(false, 0, false),
             nextChore: { key: "harvest", at: NOW, due: true, hoursUntil: 0 }, cadence: {} },
    tint: "dark", due: ["look", "harvest"],
    densityAdvice: { action: "split_now", reason: "dark — split now: the bottle, the tank, the drip" },
    feedAdvice: { action: "split_now", reason: "dark — split now: the bottle, the tank, the drip" },
    temp: { available: true, status: "ok", tempC: 23.5, minC: 20, maxC: 27, hardMaxC: 29, actC: 30, criticalC: 32, act: false },
    guard: { available: false, status: "unknown", line: "" },
    learned: { clearingH: { available: false }, firstHarvestDays: { available: false }, runLengthDays: { available: false }, yieldMlDay: null, suggest: {}, daysToDark: { available: true, days: 6, samples: 2 } },
    risk: { level: "ok", reason: "no warning from the recorded observations" },
    lineage: { generation: 1, fromName: "", line: "gen 1 · from the starter" },
    tintStrip: ["", "", "", "", "", "pale", "pale", "green", "green", "green", "green", "dark", "dark", "dark"],
    stagger: { available: false, days: null, idealDays: null, advice: "" },
    splitGuide: { available: true, totalMl: 750, outMl: 750, freshMl: 750, refillMl: 750, mixMl: 750, rodiMl: 0, targetPpt: 35, mixPpt: 35, sg: 1.0264,
                  nutrientMl: 1.1, nutrientMlPerL: 1.5, workingMlBefore: 1250, workingMlAfter: 1250, containerMl: 4000, scaleUp: false, removalPct: 60, seedPct: 40, warning: "", purgeMl: 0 },
    seedGuides: { starter: { starterMl: 250, freshMl: 1000, workingL: 1.25, workingMl: 1250, nutrientMl: 1.5, mixMl: 1000, rodiMl: 0, targetPpt: 35, kitWorkingL: 3.5, ratio: 4 },
                  kit: { starterMl: 250, freshMl: 3250, workingL: 3.5, workingMl: 3500, nutrientMl: 4.9, mixMl: 3250, rodiMl: 0, targetPpt: 35, kitWorkingL: 3.5, ratio: 13 } },
    homeBottle: { productId: "home_phyto_n1", exists: true, name: "Home phyto (Nanno A)", remainingMl: 600, bottleMl: 1000, percent: 60, expiry: { status: "fresh", daysLeft: 15.2, ageDays: 5.8 },
                  handDose: { planned: true, ml: 35, everyDays: 1, cadenceText: "every day", clock: clock(false, 6) }, shake: { applies: true, due: true, hoursSince: 50 }, daysUntilEmpty: 17, usageMlPerDay: 35 },
    nutrient: { productId: "f2", productName: "Phytoplankton Nutrient (Guillard's f/2)", mlPerL: 1.5, remainingMl: 236.5, splitsLeft: 215, linked: true },
    sizing: { available: true, yieldMlDay: 94, demandMlDay: 35, ratio: 2.7, idealL: 0.47, line: "the rack drinks ~35 ml a day (the tank's hand dose); this vessel makes ~94 at a 60 % split every 8 days — 3× more than it needs" },
    starter: { available: true, status: "fresh", daysLeft: 19, ageDays: 9, openedAt: iso(9 * 24), arrivalTint: "green" },
    drips: [{ id: "drip", name: "Phyto drip", linked: true }], hygiene: "Its own airline — never the rotifer kit.", nutrientNote: "f/2 with NEW water only.",
    harvestGuide: { totalMl: 750, mixMl: 750, rodiMl: 0, targetPpt: 35 }, restartGuide: { totalMl: 1250, mixMl: 1250, rodiMl: 0, targetPpt: 35 },
    fillGuide: { totalMl: 1250, mixMl: 1250, rodiMl: 0, targetPpt: 35 }, waterChangeGuide: { totalMl: 0, mixMl: 0, rodiMl: 0, targetPpt: 35 },
    history: [{ event: "tint", at: iso(2), ml: 0, tint: "dark", from: "", sign: "", eggRatio: null, tempC: 23.4, secchiCm: 7 },
              { event: "harvest", at: iso(8 * 24), ml: 750, tint: "dark", from: "", sign: "", eggRatio: null, tempC: 23.1, dests: [{ to: "bottle", ml: 600 }, { to: "tank", ml: 150 }], freshMl: 750, nutrientMl: 1.1 },
              { event: "seeded", at: iso(17 * 24), ml: 1250, tint: "pale", from: "", sign: "", eggRatio: null, tempC: null, freshMl: 1000, nutrientMl: 1.5, arrivalTint: "green" }],
    timeline: { days: 30, since: iso(30 * 24), tintBefore: "", marks: [], spans: [] },
    ...over,
  };
}

function phytoSummary(jar = phytoJar()) {
  const base = summaryFixture([jar]);
  return { ...base, backup: [{ species: "nanno", speciesName: "Nannochloropsis (phyto)", running: 1, backedUp: false, continuityDays: 9, guard: { available: false, status: "unknown", line: "" } }],
    nextHarvest: { status: "none", hoursUntil: null, driver: null }, maxJars: 6,
    rig: { stage: "split", caption: "SPLIT — Nanno A: 750 ml out → the bottle / the tank / the drip · 750 ml fresh @ 35 ppt + 1.1 ml f/2", cones: [], tub: null,
           jug: { mode: "fill", harvestMl: 0, mixMl: 0, rodiMl: 0, ppt: 35, purgeMl: 0, sieveUm: 50 }, bottle: { ml: 0, pct: 0, status: "empty" },
           phyto: [{ id: "n1", name: "Nanno A", kind: "bottle", status: "producing", tint: "dark", pct: 100, airOn: true, lightOn: true, splitHot: true, freshHot: false, lookHot: true,
                     offColour: false, peakHeld: false, advice: "split_now", tempStatus: "ok", establishDays: null, firstHarvestDays: 7, cycleDay: 8, cycleOf: 8, workingL: 1.25, bottleMl: 600, bottleStatus: "fresh", scaleUp: false }],
           phytoJug: { jarName: "Nanno A", outMl: 750, freshMl: 750, mixMl: 750, rodiMl: 0, ppt: 35, nutrientMl: 1.1, scaleUp: false, workingLAfter: 1.25, available: true, reason: "" } },
    species: [...base.species, { id: "nanno", name: "Nannochloropsis (phyto)", kind: "phyto", vesselKind: "bottle", salinityPpt: 35, splitPct: 60, splitIntervalDays: 8, restartCycles: 4, lightHours: 16, nutrientMlPerL: 1.5, starterMl: 250, volumeL: 4, firstHarvestDays: 7 }],
    phytoTints: ["pale", "green", "dark", "off"], phytoSigns: jar.signs };
}

function phytoConfig() {
  return baseConfig({
    nps: { enabled: false, cultures: { enabled: true, tempEntity: "", jars: {
      n1: { name: "Nanno A", species: "nanno", vesselKind: "bottle", volumeL: 4, salinityPpt: 35, starterMl: 250, harvestTo: "bottle", mode: "batch",
            nutrient: { productId: "f2", mlPerL: 1.5 }, bottleMl: 1000, feed: { productId: "", doseMl: 5 }, cadence: {},
            state: { startedAt: iso(9 * 24), lastRestartAt: iso(9 * 24), lastHarvestAt: iso(8 * 24), lastLookedAt: iso(2), lastTint: "dark", workingL: 1.25, cyclesSinceFresh: 1 }, history: [] },
    }, bottle: { volumeMl: 1000, remainingMl: 0, filledAt: "", doseMl: 20 } }, hatchery: { enabled: false, vessels: {}, reservoir: {} } },
    consumables: { products: {
      f2: { name: "Phytoplankton Nutrient (Guillard's f/2)", bottleMl: 250, remainingMl: 236.5, history: [] },
      home_phyto_n1: { name: "Home phyto (Nanno A)", brand: "Home culture", category: "phyto", bottleMl: 1000, remainingMl: 600, refrigerated: true, stirDaily: true, shelfLifeDaysOpened: 21, openedAt: iso(6 * 24), history: [], doseMl: 35, doseEveryDays: 1 },
    } },
    dosing: { channels: { drip: { name: "Phyto drip", chemical: "food", enabled: true, schedule: { enabled: true, mlPerDay: 40, standing: { enabled: true } }, reservoir: { productId: "home_phyto_n1", productIsBottle: false, volumeMl: 500, remainingMl: 100 } } } },
  });
}

test("the phyto tile: the lit vessel, the colour + Secchi row, the split form with its shares, the notes and the taps", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await culturesPanel(phytoConfig(), phytoSummary());
    const html = panel._culturesTab();
    noPlaceholders(html, "phyto tile");
    assert(html.includes('data-culture-kind="phyto"') && html.includes('data-culture-phyto-svg="n1"'), "the tile and its lit vessel");
    assert(html.includes("Phyto, on its own clock"), "a phyto-only rack changes the headline");
    assert(html.includes("cycle day 8 of ~8") && html.includes("1.25 L working"), "the cycle ring and the working volume");
    assert(html.includes("split due · it reads dark") && html.includes("look due"), `the chips speak phyto: ${html.match(/<span class="pill warning"[^>]*>[^<]*/g)}`);
    assert(html.includes('data-cultures-tint="n1"') && html.includes('<option value="pale"') && html.includes('<option value="dark"'), "the colour select on the phyto scale");
    assert(!html.includes('<option value="clearing"'), "the rotifer scale must not leak onto the vessel");
    assert(html.includes('data-cultures-secchi="n1"'), "the Secchi box");
    assert(html.includes('data-cultures-split-ml="n1"') && html.includes('value="750"'), "the split's out box defaults to the jug");
    assert(html.includes('data-cultures-dest-bottle="n1"') && html.includes('data-cultures-dest-tank="n1"') && html.includes('data-cultures-dest-drip="n1"') && html.includes('data-cultures-dest-vessel="n1"'), "every destination");
    assert(html.includes('data-cultures-dest-tank-ml="n1"') && html.includes('value="35"'), "the tank share defaults to the bottle's dose");
    assert(html.includes('data-cultures-working-after="n1"') && html.includes('data-cultures-f2="n1"') && html.includes("1.1 ml off Phytoplankton Nutrient"), "the scale-up box and the f/2 tick");
    assert(html.includes('data-culture-density="split_now"') && html.includes("dark — split now"), "the density advice");
    assert(html.includes("jug: 750 ml out · 750 ml fresh @ 35 ppt + 1.1 ml f/2 · 40 % stays as seed"), "the jug line");
    assert(html.includes("data-culture-sizing") && html.includes("this vessel makes ~94"), "the sizing line");
    assert(html.includes("fridge bottle: 600 of 1000 ml · 15.2 d left · ~17 d at the tank's rate · <span") && html.includes("shake it") && html.includes("tank dose 35 ml every day — the shelf's Dosed tap"), "the home bottle line");
    assert(html.includes("data-culture-nutrient") && html.includes("236.5 ml ≈ 215 splits"), "the f/2 budget");
    assert(html.includes("starter bottle: 19 d of its four weeks left · arrived green"), "the starter's clock");
    assert(html.includes("darkens in ~6 days (2 cycles)"), "the learned days-to-dark");
    assert(html.includes('data-action="cultures-looked" data-id="n1"') && html.includes('data-action="cultures-split-phyto" data-id="n1"') && html.includes('data-action="cultures-fresh-vessel" data-id="n1"'), "Looked / Split / Fresh vessel");
    assert(!html.includes('data-action="cultures-fed" data-id="n1"') && !html.includes('data-action="cultures-harvested" data-id="n1"') && !html.includes('data-action="cultures-restart" data-id="n1"'), "a vessel is never fed, harvested or restarted");
    assert(html.includes('data-sign="yellow"') && !html.includes('data-sign="milky"'), "the phyto signs");
    assert(html.includes("SPLIT — Nanno A") && html.includes('data-cultures-phyto="n1"'), "the rig draws the lit vessel and names the split");
    assert(html.includes("split") && html.includes("→ 600 ml bottle + 150 ml tank · 750 ml fresh + 1.1 ml f/2") && html.includes("looked · Secchi 7 cm"), "the journal speaks phyto");
    assert(!html.includes("Rotifer bottle"), "no rotifer bottle tile on a phyto-only rack");
    assert(html.includes("1 chore") || html.includes("2 chores"), "the mission row counts the chores");
  } finally { restore(); }
});

test("the seed card: the arrival check gates the tap, both recipes, the fridge-bottle reseed after a crash", async () => {
  const restore = freezeTime(NOW);
  try {
    const empty = phytoJar({ tint: "", due: [], state: { ...phytoJar().state, status: "none", ageDays: null, workingL: 0, cycle: {}, harvest: clock(false, 0, false), look: clock(false, 0, false), restart: clock(false, 0, false) },
      homeBottle: { productId: "home_phyto_n1", exists: false, remainingMl: 0, bottleMl: 1000, expiry: { status: "empty" }, handDose: {}, shake: { applies: false, due: false } }, densityAdvice: { action: "none", reason: "" }, risk: { level: "ok", reason: "" }, history: [] });
    const panel = await culturesPanel(phytoConfig(), phytoSummary(empty));
    const html = panel._culturesTab();
    noPlaceholders(html, "phyto seed card");
    assert(html.includes('data-cultures-arrival="n1"') && html.includes("off — grey, brown, cloudy, a smell"), "the arrival check");
    assert(html.includes('data-cultures-starter-ml="n1"') && html.includes('data-cultures-working-l="n1"') && html.includes('data-cultures-starter-opened="n1"'), "the recipe's boxes");
    assert(html.includes("recipe: 250 ml starter + 1000 ml of 35 ppt water + 1.5 ml f/2 → 1.25 L · the kit's 3.5 L wants 3250 ml + 4.9 ml f/2"), "the recipe line");
    assert(html.includes('data-action="cultures-seed-phyto" data-id="n1"') && html.includes('data-recipe="kit"') && html.includes("Seed at 3.5 L"), "both recipes");
    assert(html.includes("The day the parcel lands") && html.includes("Phyto into the vessel.") && html.includes("Hygiene, said once") && !html.includes("Rotifers into the cone"), "the walkthrough speaks to the vessel only");
    assert(html.includes("the home fridge bottle joins the food shelf when you seed"), "the bottle is promised");
    // The tap refuses without the arrival check; with it, the recipe rides the call.
    const calls = [];
    panel._callWS = async (call) => { calls.push(call); return {}; };
    panel._culturesLoadSummary = async () => {};
    panel.shadowRoot = { querySelector: (sel) => {
      if (sel.includes("data-cultures-arrival")) return { value: panel._arrivalValue || "" };
      if (sel.includes("data-cultures-starter-ml")) return { value: "250" };
      if (sel.includes("data-cultures-working-l")) return { value: "1.25" };
      if (sel.includes("data-cultures-starter-opened")) return { value: "2026-09-01" };
      return null;
    } };
    panel._culturesPhytoSeed("n1");
    assert(calls.length === 0 && /Look at the starter/.test(panel._cultures.message), "no arrival check, no call");
    panel._arrivalValue = "green";
    await panel._culturesPhytoSeed("n1");
    assert(calls[0].type === "openreef/cultures_seed" && calls[0].arrival_tint === "green" && calls[0].starter_ml === 250 && calls[0].working_l === 1.25 && calls[0].starter_opened_at.startsWith("2026-09-01"), JSON.stringify(calls[0]));
    calls.length = 0;
    await panel._culturesPhytoSeed("n1", "kit");
    assert(calls[0].working_l === 3.5, "the kit button seeds at 3.5 L");
    // A crashed vessel with a young bottle offers the fridge reseed.
    const crashed = phytoJar({ reseedFromBottle: true, tint: "", due: [], state: { ...phytoJar().state, status: "crashed" }, densityAdvice: { action: "none", reason: "" }, risk: { level: "ok", reason: "" } });
    const html2 = (await culturesPanel(phytoConfig(), phytoSummary(crashed)))._culturesTab();
    assert(html2.includes('data-action="cultures-seed-bottle" data-id="n1"') && html2.includes("Seed from the fridge bottle"), "the young bottle is a starter");
  } finally { restore(); }
});

test("the split tap sends the shares, the scale-up and the f/2; the fresh vessel is the same form; a blocked vessel disables Split", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await culturesPanel(phytoConfig(), phytoSummary());
    const calls = [];
    panel._callWS = async (call) => { calls.push(call); return {}; };
    panel._culturesLoadSummary = async () => {};
    const values = { "data-cultures-split-ml": "750", "data-cultures-dest-bottle": true, "data-cultures-dest-bottle-ml": "", "data-cultures-dest-tank": true, "data-cultures-dest-tank-ml": "150",
                     "data-cultures-dest-drip": false, "data-cultures-dest-vessel": false, "data-cultures-working-after": "1.25", "data-cultures-f2": true, "data-cultures-tint": "dark", "data-cultures-secchi": "7" };
    panel.shadowRoot = { querySelector: (sel) => {
      const key = Object.keys(values).find((k) => sel.includes(`[${k}=`));
      if (!key) return null;
      const v = values[key];
      return typeof v === "boolean" ? { checked: v, value: "" } : { value: v, checked: false };
    } };
    await panel._culturesPhytoSplit("n1");
    const call = calls[0];
    assert(call.type === "openreef/cultures_split" && call.ml === 750 && call.nutrient === true && call.tint === "dark" && call.secchi_cm === 7, JSON.stringify(call));
    assert(JSON.stringify(call.to) === JSON.stringify([{ to: "bottle", ml: 600 }, { to: "tank", ml: 150 }]), `a blank bottle share takes the rest: ${JSON.stringify(call.to)}`);
    assert(!("fresh_ml" in call), "like for like — no fresh_ml");
    // The scale-up: the working volume after moves, the fresh water follows.
    values["data-cultures-working-after"] = "3.5";
    values["data-cultures-dest-drip"] = true;
    values["data-cultures-f2"] = false;
    calls.length = 0;
    await panel._culturesPhytoSplit("n1");
    assert(calls[0].fresh_ml === 3000 && calls[0].nutrient === false, `750 out, 3.5 L after → 3000 ml fresh: ${JSON.stringify(calls[0])}`);
    assert(calls[0].to.some((s) => s.to === "drip" && s.ml === 0), "the drip share rides without a number — the jar takes what fits");
    calls.length = 0;
    await panel._culturesPhytoSplit("n1", true);
    assert(calls[0].type === "openreef/cultures_fresh_vessel" && calls[0].ml === 750, "the fresh vessel is the same form");
    // Blocked: the Split button is disabled, the advice says hold, the rig says off-colour.
    const blocked = phytoJar({ tint: "off", due: ["restart"], state: { ...phytoJar().state, harvestBlocked: true, splitEligible: false, restart: { ...clock(true, 0), reason: "sign" } },
      densityAdvice: { action: "hold", reason: "off-colour — do not harvest into anything" }, lastSign: "brown", risk: { level: "act", reason: "off-colour — harvest into nothing" } });
    const sum = phytoSummary(blocked);
    sum.rig = { ...sum.rig, stage: "off_colour", caption: "OFF-COLOUR — Nanno A: harvest into nothing", phyto: [{ ...sum.rig.phyto[0], tint: "off", offColour: true, splitHot: false, freshHot: true }] };
    const html = (await culturesPanel(phytoConfig(), sum))._culturesTab();
    assert(/data-action="cultures-split-phyto" data-id="n1"[^>]*disabled/.test(html), "Split is disabled while blocked");
    assert(html.includes('data-culture-density="hold"') && html.includes("fresh vessel due · a sign") && html.includes("OFF-COLOUR — Nanno A"), "the hold, the chip, the rig");
    assert(!html.includes('data-cultures-split-ml="n1"'), "no split form while blocked");
  } finally { restore(); }
});

test("settings: the phyto row, its cadences and the add button; reminders seed look / split / fresh vessel and no feed", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await culturesPanel(phytoConfig(), phytoSummary());
    const html = panel._culturesSettings();
    noPlaceholders(html, "phyto settings");
    assert(html.includes('data-culture-settings-kind="phyto"'), "the phyto row");
    assert(html.includes('data-field="harvestTo"') && html.includes('value="source"') && html.includes("the home fridge bottle (the default)"), "split goes to");
    assert(html.includes('data-field="nutrientProductId"') && html.includes('data-field="nutrientMlPerL"') && html.includes('data-field="bottleMl"') && html.includes('data-field="mode"'), "the f/2 link, the bottle size, the mode");
    assert(html.includes('data-field="splitPct"') && html.includes('data-field="splitIntervalDays"') && html.includes('data-field="restartCycles"') && html.includes('data-field="lightHours"'), "the four cadences");
    assert(!html.includes('data-id="n1" data-field="feedIntervalH"') && !html.includes('data-id="n1" data-field="purgeMl"'), "no feed, no purge on a vessel");
    assert(html.includes("Hygiene, said once") && html.includes('data-action="cultures-add-phyto"') && html.includes("up to 6"), "the hint, the add button, the cap");
    assert(html.includes('<option value="nanno"'), "the species picker offers the vessel");
    // Add a phyto vessel from the button: the defaults land in the config.
    panel._culturesAddJar("nanno");
    const added = Object.values(panel._config.nps.cultures.jars).find((j) => j.name === "Nanno 2" || (j.species === "nanno" && j.name !== "Nanno A"));
    assert(added && added.vesselKind === "bottle" && added.volumeL === 4 && added.bottleMl === 1000 && added.mode === "batch", `the added vessel: ${JSON.stringify(added)}`);
    delete panel._config.nps.cultures.jars[Object.keys(panel._config.nps.cultures.jars).find((k) => panel._config.nps.cultures.jars[k] === added)];
    // Reminders for the vessel.
    panel._culturesSeedReminders();
    const tasks = panel._config.maintenance.tasks;
    assert(tasks.culture_n1_look && tasks.culture_n1_look.cadenceDays === 1 && tasks.culture_n1_look.label === "Look at Nanno A", "the daily look");
    assert(tasks.culture_n1_harvest && tasks.culture_n1_harvest.cadenceDays === 8 && tasks.culture_n1_harvest.label === "Split Nanno A", "the split on the split clock");
    assert(tasks.culture_n1_restart && tasks.culture_n1_restart.cadenceDays === 32 && /Fresh vessel/.test(tasks.culture_n1_restart.label), "the fresh vessel every four splits");
    assert(!tasks.culture_n1_feed && !tasks.culture_n1_water_change, "no feed, no water change");
    const comps = panel._config.maintenance.completions;
    assert(comps.culture_n1_look?.length === 1 && comps.culture_n1_harvest?.length === 1, "anchored on the look and the split stamps");
    // The maintenance state reads the vessel's look clock through the summary.
    panel._config.maintenance.enabled = true;
    const state = panel._maintenanceDueState("culture_n1_look");
    assert(state.status === "warning" && state.label === "due", `the look is due on the vessel's clock: ${JSON.stringify(state)}`);
  } finally { restore(); }
});

test("the shelf: the home bottle's Shaken tap and chip; the drip's Loaded debits a home bottle; the hub names the vessel", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await culturesPanel(phytoConfig(), phytoSummary());
    const product = panel._config.consumables.products.home_phyto_n1;
    const state = { bottleMl: 1000, remainingMl: 600, percent: 60, usageMlPerDay: 35, daysUntilEmpty: 17, low: false, empty: false,
      expiry: { status: "fresh", daysLeft: 15 }, stirDaily: true, refrigerated: true, categoryLabel: "Phytoplankton",
      handDose: { planned: true, ml: 35, everyDays: 1, cadenceText: "every day", clock: clock(false, 6), guide: { available: false }, lastAt: "", note: "" },
      shake: { applies: true, due: true, hoursSince: 50, lastAt: "" } };
    const card = panel._npsProductCard("home_phyto_n1", product, state);
    noPlaceholders(card, "home bottle card");
    assert(card.includes('data-action="nps-product-shaken" data-id="home_phyto_n1"') && card.includes("Shake it") && card.includes("Dosed 35 ml"), "Shaken beside Dosed");
    const dry = panel._npsProductCard("f2", panel._config.consumables.products.f2, { ...state, shake: { applies: false, due: false }, stirDaily: false, refrigerated: false });
    assert(!dry.includes("nps-product-shaken"), "a still bottle has no Shaken");
    assert(panel._doserLoadsFromHomeBottle("drip") === true, "the drip draws from the home bottle");
    panel._config.dosing.channels.drip.reservoir.productId = "rj";
    assert(panel._doserLoadsFromHomeBottle("drip") === false, "a shop bottle keeps the old Loaded");
    const hub = panel._hubTab("feeding");
    assert(hub.includes("Nanno A · day 8 · dark") && hub.includes("split now") && hub.includes("bottle 600 ml, 15 d left"), `the hub line: ${hub.match(/Nanno A[^<]*/)}`);
  } finally { restore(); }
});

test("the demo rack carries the phyto vessel and renders without placeholders", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await culturesPanel();
    const demo = panel._culturesDemoData().summary;
    assert(demo.jars.some((j) => j.kind === "phyto") && demo.rig.phyto.length === 1 && demo.maxJars === 6, "the staged rack has a vessel");
    panel._cultures.summary = demo;
    panel._cultures.demo = true;
    const html = panel._culturesTab();
    noPlaceholders(html, "demo tab with the vessel");
    assert(html.includes("Nanno A") && html.includes('data-culture-kind="phyto"') && html.includes('data-cultures-phyto="n"'), "the vessel on the demo rack and rig");
  } finally { restore(); }
});

// --- 0.7.208 — Stage B: light, heat, backup, learning (doc §5.6, §5.8, §5.10, §11) ---
function stageBLight(over = {}) {
  return { mode: "sun+lamp", switchEntity: "switch.phyto_lamp", tempEntity: "", targetH: 16, daylightH: 12.4, sunAvailable: true, isDay: false,
    sunsetAt: iso(2), sunriseAt: iso(-10), lampH: 1.5, deliveredH: 13.9, plannedLampH: 3.6,
    window: { onAt: iso(2), offAt: iso(-1.6), active: true, over: false, rule: "sunset", hoursIn: 1.9 },
    plugState: "on", plugOn: true, lit: true, shortDay: false, status: "ok",
    line: "daylight 12.4 h (astronomical — the window gives less) · lamp 3.6 h from sunset 19:09 → 22:45 · 1.5 h lamp so far", nudge: "",
    aerationNote: "Air is never switched — a still culture settles and dies; only the lamp rides the plug.", ...over };
}

test("Stage B tile: the light line, the vessel-sensor words, the Apply chips, the learned lines and the refresh label on the B share", async () => {
  const restore = freezeTime(NOW);
  try {
    const jar = phytoJar({
      light: stageBLight(),
      temp: { available: true, status: "hot", tempC: 29.6, minC: 20, maxC: 27, hardMaxC: 29, actC: 30, criticalC: 32, act: false, source: "vessel" },
      learned: { clearingH: { available: false }, firstHarvestDays: { available: false }, runLengthDays: { available: false }, yieldMlDay: 94, yieldLWeek: 0.66,
        suggest: { splitIntervalDays: 6, mode: "daily" }, daysToDark: { available: true, days: 6, samples: 2 },
        depth: { available: true, line: "> 65 % splits took ~5 d to darken, ≤ 50 % splits took ~3 d to darken — this does not establish the cause" },
        light: { weekH: 11, days: 7, line: "a week under 14 h of light (~11 h a day) beside a slow cycle — the light is the first thing to check; nothing here proves it" } },
      dailyOffer: { available: true, pct: 20 },
      refresh: { isBackup: false, fromId: "", fromName: "", available: false, due: false, backupId: "n2", backupName: "Nanno B", everyDays: 32 },
    });
    const panel = await culturesPanel(phytoConfig(), phytoSummary(jar));
    const html = panel._culturesTab();
    noPlaceholders(html, "stage B tile");
    assert(html.includes('data-culture-light="ok"') && html.includes("☀+💡 daylight 12.4 h (astronomical — the window gives less) · lamp 3.6 h from sunset 19:09 → 22:45 · 1.5 h lamp so far"), "the light line");
    assert(html.includes('data-culture-lamp="on"'), "the tile's lamp glyph is lit");
    assert(html.includes('data-culture-temp-source="vessel"') && html.includes("29.6 °C") && html.includes("(the vessel's own sensor)"), "the vessel sensor names itself");
    assert(html.includes("split every 6? <button") && html.includes('data-action="cultures-apply-learned" data-id="n1" data-field="splitIntervalDays"'), "Apply on days-to-dark");
    assert(html.includes("Two cycles learned — run it daily? A 20 % draw every day") && html.includes('data-field="mode">Switch to daily'), "the daily offer");
    assert(html.includes("&gt; 65 % splits took ~5 d to darken") && html.includes("a week under 14 h of light"), "recovery by depth and the light line");
    assert(html.includes("→ Nanno B</span>") && html.includes("to refresh Nanno B"), "the B share refreshes the running backup");
    // The lamp that should be on and is not: a watch, a red lamp, the risk line's words.
    const dark = phytoJar({ light: stageBLight({ status: "watch", plugOn: false, plugState: "off", lit: false, line: "daylight 12.4 h … · lamp 3.6 h from sunset 19:09 → 22:45 · 0.0 h lamp so far — lamp off 1.9 h into its window" }),
      risk: { level: "watch", reason: "lamp off 1.9 h into its window" } });
    const html2 = panel._culturesPhytoTile(dark, phytoSummary(dark), [dark]);
    assert(html2.includes('data-culture-light="watch"') && html2.includes("lamp off 1.9 h into its window") && html2.includes('data-culture-lamp="off"') && html2.includes('fill="#e5484d"'), "the lamp-off watch");
    // Sun mode with a short day: the nudge rides the line.
    const sunOnly = phytoJar({ light: stageBLight({ mode: "sun", switchEntity: "", status: "watch", shortDay: true, daylightH: 11.6, deliveredH: 11.6, plugOn: false, isDay: true, lit: true,
      line: "daylight 11.6 h (astronomical — the window gives less)", nudge: "the days are under 12 h — put the LED on the plug" }) });
    const html3 = panel._culturesPhytoTile(sunOnly, phytoSummary(sunOnly), [sunOnly]);
    assert(html3.includes("☀ daylight 11.6 h (astronomical — the window gives less) — the days are under 12 h — put the LED on the plug"), "the short-day nudge");
    // The rack's air, when no vessel sensor is bound.
    const rack = phytoJar({ temp: { available: true, status: "warm", tempC: 27.5, minC: 20, maxC: 27, hardMaxC: 29, actC: 30, criticalC: 32, act: false, source: "rack" } });
    assert(panel._culturesPhytoTile(rack, phytoSummary(rack), [rack]).includes("(this is the rack's air, not the culture — a vessel sensor in Culture settings reads the water)"), "the rack's words");
  } finally { restore(); }
});

test("Stage B: the backup's tile — its parent, the refresh clock, the Refresh tap and the chore word; the refresh tap sends its WS", async () => {
  const restore = freezeTime(NOW);
  try {
    const a = phytoJar({ refresh: { isBackup: false, backupId: "n2", backupName: "Nanno B" }, light: stageBLight() });
    const b = phytoJar({ id: "n2", name: "Nanno B", volumeL: 1, workingL: 1, tint: "green", due: ["look", "refresh"], backupOf: "n1",
      light: stageBLight({ mode: "sun", switchEntity: "", status: "ok", line: "daylight 12.4 h (astronomical — the window gives less)" }),
      densityAdvice: { action: "wait", reason: "growing — dark in ~2 d" },
      refresh: { isBackup: true, fromId: "n1", fromName: "Nanno A", available: true, due: true, hoursUntil: 0, everyDays: 32, starterMl: 250, freshMl: 750, nutrientMl: 1.1, workingL: 1, backupId: "", backupName: "" },
      state: { ...phytoJar().state, ageDays: 33, workingL: 1, splitEligible: false, harvest: clock(false, 0, false),
        refresh: { available: true, due: true, at: NOW, hoursUntil: 0, hoursOverdue: 24, reason: "backup", everyDays: 32 }, backupOf: "n1" },
      risk: { level: "watch", reason: "the backup is 33 days old — refresh it from the main vessel" } });
    const summary = { ...phytoSummary(a), jars: [a, b], dueCount: 3,
      rig: { ...phytoSummary(a).rig, phyto: [...phytoSummary(a).rig.phyto, { id: "n2", name: "Nanno B", kind: "bottle", status: "producing", tint: "green", pct: 40, airOn: true, lightOn: true, lightWatch: false, backup: true, refreshHot: true,
        splitHot: false, freshHot: false, lookHot: true, offColour: false, peakHeld: false, advice: "wait", tempStatus: "ok", establishDays: null, firstHarvestDays: 7, cycleDay: 33, cycleOf: 8, workingL: 1, bottleMl: 0, bottleStatus: "empty", scaleUp: false }] } };
    const config = phytoConfig();
    config.nps.cultures.jars.n2 = { ...config.nps.cultures.jars.n1, name: "Nanno B", volumeL: 1, state: { ...config.nps.cultures.jars.n1.state, backupOf: "n1", workingL: 1, startedAt: iso(33 * 24) } };
    config.maintenance = { enabled: true, tasks: {}, completions: {} };
    const panel = await culturesPanel(config, summary);
    panel._culturesSeedReminders();
    const html = panel._culturesTab();
    noPlaceholders(html, "backup tile");
    assert(html.includes('data-culture-backup="n1"') && html.includes("backup of Nanno A · <span") && html.includes("refresh due") && html.includes("(every ~32 d) · 250 ml from Nanno A + 750 ml fresh + 1.1 ml f/2"), `the backup line: ${html.match(/backup of[^<]*<span[^<]*<\/span>[^<]*/)}`);
    assert(html.includes('class="primary compact-button" data-action="cultures-refresh-backup" data-id="n2"') && html.includes("Refresh from Nanno A</button>"), "the Refresh tap, primary when due");
    assert(html.includes("refresh the backup due · 33 days on the sill"), `the chore chip: ${html.match(/<span class="pill warning"[^>]*>[^<]*/g)}`);
    assert(!html.includes('data-action="cultures-refresh-backup" data-id="n1"'), "the main vessel has no Refresh tap");
    assert(html.includes("backup — refresh it"), "the rig names the backup's chore");
    assert(html.includes("3 chores"), "the mission row counts the refresh");
    let sent = null;
    panel._culturesCall = (msg) => { sent = msg; };
    panel._culturesRefreshBackup("n2");
    assert(sent && sent.type === "openreef/cultures_refresh_backup" && sent.jar_id === "n2", `the refresh tap: ${JSON.stringify(sent)}`);
    panel._culturesApplyLearned("n1", "mode");
    assert(sent.type === "openreef/cultures_apply_learned" && sent.field === "mode", "the daily offer's Apply");
    assert(panel._culturesChoreWord(b, "refresh") === "refresh the backup", "the chore word");
    const due = panel._maintenanceDueState("culture_n2_refresh");
    assert(due.status === "warning" && due.label === "due", `the refresh reminder reads B's clock: ${JSON.stringify(due)}`);
    assert(panel._maintenanceDueState("culture_n1_look").label === "due", "the look reminder still reads the jar");
  } finally { restore(); }
});

test("Stage B settings: the Light group in the vessel's row, the refresh reminder for a backup, the add-jar default and the demo rack", async () => {
  const restore = freezeTime(NOW);
  try {
    const config = phytoConfig();
    config.nps.cultures.jars.n1.light = { mode: "sun+lamp", switchEntity: "switch.phyto_lamp", onAt: "07:00", latestOff: "23:30", tempEntity: "sensor.nanno_water" };
    config.nps.cultures.jars.n2 = { ...config.nps.cultures.jars.n1, name: "Nanno B", volumeL: 1, light: { mode: "sun" }, state: { ...config.nps.cultures.jars.n1.state, backupOf: "n1", workingL: 1 } };
    config.maintenance = { enabled: true, tasks: {}, completions: {} };
    const panel = await culturesPanel(config, phytoSummary());
    const settings = panel._culturesSettings();
    noPlaceholders(settings, "phyto settings with light");
    assert(settings.includes('data-culture-light="n1"') && settings.includes('data-field="light.mode"') && settings.includes('<option value="sun+lamp" selected>'), "the Light select");
    assert(settings.includes('data-field="light.switchEntity" value="switch.phyto_lamp"') && settings.includes('data-field="light.latestOff" value="23:30"') && settings.includes('data-field="light.tempEntity" value="sensor.nanno_water"'), "the plug, the cap and the vessel sensor");
    assert(settings.includes('type="time" data-scope="nps-culture-jar" data-id="n1" data-field="light.onAt" value="07:00"'), "the on-at clock");
    assert(!settings.includes("Stage B"), "no promise of a later stage in the hints");
    panel._culturesSeedReminders();
    const tasks = panel._config.maintenance.tasks;
    assert(tasks.culture_n2_refresh && tasks.culture_n2_refresh.cadenceDays === 32 && tasks.culture_n2_refresh.label === "Refresh Nanno B from Nanno A", `the backup's refresh chore: ${JSON.stringify(tasks.culture_n2_refresh)}`);
    assert(!tasks.culture_n1_refresh, "the main vessel carries no refresh chore");
    assert(tasks.culture_n1_look && tasks.culture_n1_harvest && tasks.culture_n1_restart, "the Stage A chores stay");
    delete panel._config.nps.cultures.jars.n2.state.backupOf;
    panel._culturesSeedReminders();
    assert(!panel._config.maintenance.tasks.culture_n2_refresh, "no longer a backup: the chore goes");
    panel._culturesAddJar("nanno");
    const added = Object.values(panel._config.nps.cultures.jars).find((j) => j.name === "Nanno 3" || j.name.startsWith("Nanno") && !["Nanno A", "Nanno B"].includes(j.name));
    assert(added && added.light && added.light.mode === "sun" && added.light.onAt === "07:00" && added.light.latestOff === "00:00", `a new vessel starts on the sun: ${JSON.stringify(added?.light)}`);
    const shelf = panel._npsProductCard("home_phyto_n1", panel._config.consumables.products.home_phyto_n1,
      { bottleMl: 1000, remainingMl: 0, percent: 0, empty: true, low: true, expiry: { status: "empty" }, handDose: { planned: true, ml: 35, everyDays: 1, clock: {} },
        shake: { applies: true, due: false }, splitNudge: "empty — Nanno A reads dark: split into this bottle" });
    assert(shelf.includes('data-shelf-nudge="home_phyto_n1"') && shelf.includes("empty — Nanno A reads dark: split into this bottle"), "the shelf's split nudge");
    const demo = panel._culturesDemoData().summary;
    const vessel = demo.jars.find((j) => j.kind === "phyto");
    assert(vessel.light && vessel.light.mode === "sun+lamp" && vessel.refresh && vessel.dailyOffer, "the demo vessel carries the Stage B fields");
    panel._cultures.summary = demo; panel._cultures.demo = true;
    const html = panel._culturesTab();
    noPlaceholders(html, "demo tab with the light");
    assert(html.includes("☀+💡 daylight 12.3 h"), "the demo shows the light line");
  } finally { restore(); }
});

// --- 0.7.209 — Stage C: the rotifer coupling and the stick (doc §4.2, §5.5, §6, §12) ---
test("Stage C animal tile: the phyto refill row, the three-way jug line, the still-green word, and the harvest and restart taps carry the source", async () => {
  const restore = freezeTime(NOW);
  try {
    const summary = summaryFixture();
    const cone = summary.jars[0];
    const cid = cone.id;
    cone.phytoSources = [{ id: "bottle:home_phyto_n1", kind: "bottle", name: "Home phyto (Nanno A)", ml: 600, ppt: 35, ready: true, tint: "" },
      { id: "vessel:n1", kind: "vessel", name: "Nanno A", ml: 1250, ppt: 35, ready: true, tint: "dark" },
      { id: "vessel:n2", kind: "vessel", name: "Nanno B", ml: 1000, ppt: 35, ready: false, tint: "pale" }];
    cone.coneDoseMl = 170;
    cone.phytoRefill = { totalMl: 625, refillMl: 675, phytoMl: 170, phytoPpt: 35, mixMl: 351, rodiMl: 154, targetPpt: 27, mixPpt: 35, resultPpt: 27, available: true, sourceId: "bottle:home_phyto_n1", sourceName: "Home phyto (Nanno A)", stillGreen: false };
    const panel = await culturesPanel({}, summary);
    const html = panel._culturesTab();
    noPlaceholders(html, "animal tile with phyto sources");
    assert(html.includes(`data-cultures-phyto-from="${cid}"`) && html.includes('<option value="bottle:home_phyto_n1" >Home phyto (Nanno A) · 600 ml</option>') && html.includes('<option value="vessel:n1" >Nanno A · dark</option>'), `the source select: ${html.match(/<select data-cultures-phyto-from[\s\S]*?<\/select>/)}`);
    assert(html.includes('<option value="vessel:n2" disabled>Nanno B · pale (not ready)</option>'), "a pale vessel is offered greyed");
    assert(html.includes(`data-cultures-phyto-ml="${cid}"`) && html.includes('placeholder="170"'), "the ml box shows one tint as its placeholder");
    assert(html.includes("refill with phyto: 170 ml of 35 ppt phyto + 351 ml mix + 154 ml RODI → 27 ppt"), "the three-way jug line");
    cone.phytoRefill.stillGreen = true;
    const html2 = panel._culturesTab();
    assert(html2.includes("still green — plain water this time"), "the still-green word");
    // The senders: a picked source rides the harvest and the restart; blank ml lets the backend size one tint.
    const picked = { value: "vessel:n1" }, box = { value: "" };
    panel.shadowRoot = { querySelector: (sel) => sel.includes("phyto-from") ? picked : sel.includes("phyto-ml") ? box : null };
    let sent = null;
    panel._culturesCall = (msg) => { sent = msg; };
    panel._culturesLog(cid, true, true);
    assert(sent.type === "openreef/cultures_log" && sent.harvested === true && sent.phyto_from === "vessel:n1" && !("phyto_ml" in sent), `the harvest carries the source: ${JSON.stringify(sent)}`);
    box.value = "200";
    panel._culturesRestart(cid);
    assert(sent.type === "openreef/cultures_restart" && sent.phyto_from === "vessel:n1" && sent.phyto_ml === 200, `the restart carries it too: ${JSON.stringify(sent)}`);
    picked.value = "";
    panel._culturesLog(cid, true, true);
    assert(!("phyto_from" in sent), "no source, no phyto fields");
    // A jar with no sources on the rack shows no row.
    const bare = await culturesPanel({}, summaryFixture());
    assert(!bare._culturesTab().includes("data-cultures-phyto-from"), "no phyto on the rack, no row");
  } finally { restore(); }
});

test("Stage C phyto tile: the cone share, the Secchi line and the printable stick", async () => {
  const restore = freezeTime(NOW);
  try {
    const jar = phytoJar({
      cones: [{ id: "a", name: "Rotifers A", doseMl: 170, tint: "clearing", stillGreen: false, feedDue: true }],
      secchi: { available: true, readings: 8, bands: { pale: 14, green: 8, dark: 4.2 }, counts: { pale: 3, green: 3, dark: 2 }, stick: { darkMaxCm: 6.1, greenMaxCm: 11 },
        fit: { available: true, points: 8, slopePerDay: -0.233, halvingDays: 3, r2: 0.78 }, daysToDark: 3.3, lastCm: 9,
        line: "Secchi: on your stick: dark ~4.2 cm, green ~8 cm, pale ~14 cm (8 readings) · the depth halves every ~3 d (8 readings, your fit) · today's 9 cm is ~3.3 d from dark" },
    });
    const panel = await culturesPanel(phytoConfig(), phytoSummary(jar));
    const html = panel._culturesTab();
    noPlaceholders(html, "phyto tile with a cone and a stick");
    assert(html.includes('data-cultures-dest-cone="n1"') && html.includes("→ Rotifers A</span>") && html.includes('data-cultures-dest-cone-ml="n1"') && html.includes('value="170"'), "the cone share with one tint as its default");
    assert(!html.includes("data-cultures-dest-cone-jar"), "one cone needs no picker");
    assert(html.includes('data-culture-secchi="8"') && html.includes("the depth halves every ~3 d") && html.includes("9 cm is ~3.3 d from dark"), "the Secchi line");
    assert(html.includes('data-action="cultures-print-secchi" data-id="n1"'), "the print button");
    const svg = panel._culturesSecchiStickSvg(jar);
    assert(svg.includes('width="40mm"') && svg.includes('data-cultures-secchi-stick="n1"') && (svg.match(/<line /g) || []).length === 41, "true-size stick with 5 mm ticks over 20 cm");
    assert(svg.includes(">20</text>") && svg.includes(">0</text>"), "the cm numbers");
    assert(svg.includes('fill="#1b5e20"') && svg.includes('fill="#43a047"') && svg.includes("your bands: dark ≤ 6.1 cm · green ≤ 11 cm (8 readings)"), "the keeper's bands drawn");
    const blank = panel._culturesSecchiStickSvg(phytoJar({ secchi: { available: false, readings: 0, bands: {}, stick: null, fit: { available: false }, line: "" } }));
    assert(!blank.includes('fill="#1b5e20"') && blank.includes("no bands yet — the readings draw them"), "no readings, no bands");
    noPlaceholders(svg, "stick"); noPlaceholders(blank, "blank stick");
    // Two cones: a picker, and the split sender names the jar.
    const two = phytoJar({ cones: [{ id: "a", name: "Rotifers A", doseMl: 170, tint: "clear", stillGreen: false, feedDue: true }, { id: "b", name: "Rotifers B", doseMl: 170, tint: "green", stillGreen: true, feedDue: false }] });
    const html2 = panel._culturesPhytoTile(two, phytoSummary(two), [two]);
    assert(html2.includes('data-cultures-dest-cone-jar="n1"') && html2.includes(">Rotifers B · green</option>"), "the picker when two stand");
    panel._cultures.summary = phytoSummary(two);
    const boxes = { "data-cultures-split-ml": { value: "400" }, "data-cultures-dest-cone": { checked: true }, "data-cultures-dest-cone-ml": { value: "" }, "data-cultures-dest-cone-jar": { value: "b" }, "data-cultures-dest-bottle": { checked: true }, "data-cultures-dest-bottle-ml": { value: "" } };
    panel.shadowRoot = { querySelector: (sel) => { const key = Object.keys(boxes).find((k) => sel.startsWith(`[${k}=`)); return key ? boxes[key] : null; } };
    let sent = null;
    panel._culturesCall = (msg) => { sent = msg; };
    panel._culturesPhytoSplit("n1");
    assert(sent && sent.ml === 400 && JSON.stringify(sent.to) === JSON.stringify([{ to: "bottle", ml: 400 }, { to: "cone", ml: 0, jarId: "b" }]), `the cone share names its jar and leaves the ml to the backend: ${JSON.stringify(sent.to)}`);
    const empty = phytoJar({ secchi: { available: false, readings: 0, bands: {}, stick: null, fit: { available: false }, line: "" } });
    assert(panel._culturesPhytoTile(empty, phytoSummary(empty), [empty]).includes('data-culture-secchi="0"'), "no readings: the tile says how to start");
  } finally { restore(); }
});

test("Stage C report viewer: a vessel's splits and litres, an animal's home phyto", async () => {
  const panel = await culturesPanel();
  const c = { jars: [{ id: "n1", name: "Nanno A", kind: "phyto", feeds: 0, looks: 4, harvests: 2, skips: 0, signs: 0, restarts: 0, crashed: 0, harvestMl: 1500, yieldL: 1.5, dests: { bottle: 1100, tank: 230, cone: 170 }, signList: [] },
                     { id: "r1", name: "Rotifers A", kind: "animal", feeds: 3, looks: 4, harvests: 1, skips: 0, signs: 0, restarts: 0, crashed: 0, harvestMl: 625, phytoFedMl: 340, signList: [] }], feeds: 3, looks: 8, harvests: 3, skips: 0, signs: 0, restarts: 0, crashed: 0, phytoYieldL: 1.5 };
  const section = panel._reportLiving({ living: { cultures: c, hatches: {}, corals: {} } });
  noPlaceholders(section, "report living section");
  assert(section.includes("Nanno A") && section.includes("2 splits — 1.5 L (1100 ml bottle, 230 ml tank, 170 ml cone)"), `the vessel's line: ${section.match(/Nanno A[^<]*<\/strong>[^<]*/)}`);
  assert(section.includes("1 harvest (625 ml) · 340 ml of home phyto"), `the animal's home phyto: ${section.match(/Rotifers A[^<]*<\/strong>[^<]*/)}`);
});

// Keep this LAST: a test defined below the runner is a test that never runs.
runTests();
