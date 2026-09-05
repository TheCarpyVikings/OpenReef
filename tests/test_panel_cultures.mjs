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
    history: [{ event: "harvest", at: iso(30), ml: 625, tint: "green", from: "" },
              { event: "seeded", at: iso(12 * 24), ml: 0, tint: "", from: "" }],
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
    bottle: { status: "fresh", remainingMl: 400, hoursLeft: 62, filledAt: iso(10), volumeMl: 1000, doseMl: 20, shelfDays: 5 },
    tempC: 23.5,
    rig: rigFixture(list),
    species: [
      { id: "rotifer_L", name: "Rotifers (L-type)", kind: "rotifer", vesselKind: "cone", salinityPpt: 27, feedIntervalH: 12, harvestIntervalDays: 1, harvestPct: 25, restartIntervalDays: 14, waterChangeIntervalDays: 0, waterChangePct: 0, sieveUm: 50, adultSieveUm: 0, purgeMl: 50, firstHarvestDays: 6, tintTarget: "leafy green — spinach, not pea soup" },
      { id: "tigriopus", name: "Tigriopus copepods", kind: "copepod", vesselKind: "tub", salinityPpt: 35, feedIntervalH: 24, harvestIntervalDays: 10, harvestPct: 25, restartIntervalDays: 0, waterChangeIntervalDays: 0, waterChangePct: 50, sieveUm: 50, adultSieveUm: 300, purgeMl: 0, firstHarvestDays: 28, tintTarget: "Granny Smith apple skin" },
    ],
    tints: ["green", "clearing", "clear"], maxJars: 4,
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
    assert(html.includes("Reef Juice is for the tank, not the jars"), "the shelf step must keep Reef Juice out of the jars");
    panel = await culturesPanel();
    html = panel._culturesTab();
    assert(!html.includes("The day the parcel lands"), "a seeded rack must not show the walkthrough");
  } finally { restore(); }
});

// Keep this LAST: a test defined below the runner is a test that never runs.
runTests();
