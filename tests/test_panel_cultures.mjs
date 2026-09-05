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
    restartGuide: { totalMl: 2500, mixMl: 2500, rodiMl: 0, targetPpt: 35 },
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
    assert(html.includes("1.020 (27 ppt)") && html.includes("2.5×"), "the salinity recommendation must be on the page");
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
    assert(html.includes("runs ~11 days before it turns (3 runs) — restart at 10?") && html.includes('data-field="restartIntervalDays">Apply'), "the restart chip is missing");
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
    assert(html.includes("gut-loaded · ~19.2 h of boost left") && html.includes("fridge · enriched"), "the boost line is missing on the bottle");
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
    assert(hs.includes("opened 22 days ago") && hs.includes('data-action="nps-cysts-opened"'), "the cysts line is missing from hatchery settings");
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
    assert(html.includes("no backup") && html.includes("split at the next restart") && html.includes("12 days without a gap"), "the Jars card must say there is no backup and count continuity");
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
    assert(html.includes("The starter is at ~27 ppt and the cone at 35") && html.includes("add 500 ml of cone water, wait 15 min (~31 ppt)"), "the plan must be quoted, capitalised");
    assert(html.includes("the last step is 4 ppt."), "the sentence ends with the final step");
    assert(!html.includes("add cone water to it in steps"), "the plain rule gives way to the maths");
    panel = await culturesPanel({}, virgin());
    html = panel._culturesTab();
    assert(html.includes("in steps of no more than 5 ppt"), "without a plan the rule itself is stated");
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
    assert(sum.jars.length === 3 && sum.jars.map((j) => j.name).join(",") === "Rotifers A,Rotifers B,Pods", "two cones and the tub");
    assert(sum.enrichment.soak.status === "soaking" && sum.backup[1].guard.status === "warn" && sum.jars[0].learned.purge.available, "a soak, a warning, a journal that learned");
    const html = panel._culturesTab();
    assert(html.includes("Demo view — a staged rack") && html.includes("Exit demo"), "the banner and the exit button");
    assert(html.includes("ROTIFERS A") && html.includes("ROTIFERS B") && html.includes("PODS · TUB"), "the rig draws the staged rack");
    assert(html.includes("tomorrow") && html.includes("gut-loaded") && html.includes("Purge: runs bled"), "the guard, the boost and the learned purge show");
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

// Keep this LAST: a test defined below the runner is a test that never runs.
runTests();
