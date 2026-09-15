/**
 * The coral diary (0.7.192): the panel's LOCKSTEP mirror of livestock.py.
 *
 * The score, the confidence clock, the cadences and the due lists are
 * computed on both sides — the backend for the digest, the panel for the
 * tab, the rockwork glyph and the Pulse card. The fixtures here are the SAME
 * numbers tests/test_livestock.py pins; change one, change both. The rest
 * is the tab's judgement: the nav, the rockwork's 16-active cap, the NPS
 * tick-list living in the registry, the settings section.
 *
 * Run standalone:  node tests/test_panel_corals.mjs
 */

import { assert, assertEqual, freezeTime, makePanel, runTests, test } from "./_panel_harness.mjs";

const NOW = "2026-09-15T12:00:00Z";
const NOW_MS = Date.parse(NOW);
const daysAgo = (d) => new Date(NOW_MS - d * 86400000).toISOString();
const dateAgo = (d) => daysAgo(d).slice(0, 10);

function coral(species = "torch", addedDaysAgo = 100, extra = {}) {
  return { name: "Golden torch", species, colour: "gold", status: "active", addedAt: dateAgo(addedDaysAgo), ...extra };
}
function look(d, extra = {}) {
  return { at: daysAgo(d), extension: 3, tissue: "intact", colour: 4, fluor: "same", feeding: "", pests: "none", neighbours: [], ...extra };
}

async function panelWith(livestock, extra = {}) {
  const panel = await makePanel({ livestock, consumables: { products: {} }, display: {}, ...extra });
  panel._settingsSections = {};
  panel._isPhoneViewport = () => false;
  panel._nps = { summary: null };
  panel._livestock = { summary: null, at: 0, loading: false, error: "", loadError: "" };
  return panel;
}

// --- the score (mirror of test_livestock.py) ------------------------------------

test("score: a perfect look is 100 and losses/caps pin the Python numbers", async () => {
  const panel = await panelWith({});
  assertEqual(panel._coralScoreCheckin(look(0), {}, "euphyllia").score, 100);
  const out = panel._coralScoreCheckin(look(0, { extension: 1, tissue: "receding", colour: 2, pests: "suspected" }), {}, "euphyllia");
  assertEqual(out.losses.map((l) => l.points), [10, 20, 15, 12], "losses in row order");
  assertEqual(out.score, 40, "capped by active recession");
  assertEqual(out.caps.map((c) => c.limit), [40, 50]);
  const nb = panel._coralScoreCheckin(look(0, { extension: 0, fluor: "fading", neighbours: ["nipped", "shaded", "stung"] }), {}, "sps");
  assertEqual(nb.score, 100 - 25 - 8 - 8 - 8, "at most two neighbours count");
  assertEqual(panel._coralScoreCheckin(look(0, { pests: "confirmed" }), {}, "soft").score, 60);
  assertEqual(panel._coralScoreCheckin(look(0, { tissue: "rtn" }), {}, "sps").score, 10);
});

test("score: colour is judged against the colony's own baseline", async () => {
  const panel = await panelWith({});
  assertEqual(panel._coralScoreCheckin(look(0, { colour: 4 }), { colour: 6 }, "sps").score, 85);
  assertEqual(panel._coralScoreCheckin(look(0, { colour: 4 }), { colour: 5 }, "sps").score, 94);
  assertEqual(panel._coralScoreCheckin(look(0, { colour: 5 }), {}, "sps").score, 100);
  assertEqual(panel._coralScoreCheckin(look(0, { colour: 2 }), { colour: 2 }, "sps").score, 50);
});

test("score: ignored food only counts for animals that are fed", async () => {
  const panel = await panelWith({});
  assertEqual(panel._coralScoreCheckin(look(0, { feeding: "ignored" }), {}, "soft").score, 100);
  assertEqual(panel._coralScoreCheckin(look(0, { feeding: "ignored" }), {}, "lps_feeder").score, 92);
  assertEqual(panel._coralScoreCheckin(look(0, { feeding: "ignored" }), {}, "nps").score, 92);
});

// --- the colony state ------------------------------------------------------------

test("state: an unchecked colony has no score and is due", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await panelWith({ corals: { a: coral() } });
    const st = panel._coralState("a");
    assertEqual([st.score, st.grade, st.word, st.checkDue, st.checkOverdue], [null, "—", "unchecked", true, true]);
    assertEqual(st.insights[0].label, "No check-in yet");
  } finally { restore(); }
});

test("state: the confidence clock caps a forgotten colony at 70", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await panelWith({ corals: { a: coral() }, checkins: { a: [look(20)] } });
    const st = panel._coralState("a");
    assertEqual([st.stale, st.score, st.grade, st.word, st.checkDue, st.checkOverdue, st.trend], [true, 70, "C", "watch", true, true, null]);
    assert(st.caps.some((c) => c.limit === 70), "the cap names itself");
    panel._config.livestock.checkins.a = [look(9)];
    const due = panel._coralState("a");
    assertEqual([due.stale, due.score, due.checkDue, due.checkOverdue], [false, 100, true, false]);
  } finally { restore(); }
});

test("state: trend, words, tombstones and cadence reasons", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await panelWith({ corals: { a: coral() }, checkins: {
      a: [look(8, { extension: 1, tissue: "receding", colour: 2, pests: "suspected" }), look(1)] } });   // oldest first on purpose
    let st = panel._coralState("a");
    assertEqual([st.score, st.trend], [100, { delta: 60, word: "up" }], "rows sort by their stamps");
    assertEqual(st.nextCheckAt, NOW_MS + 6 * 86400000);
    panel._config.livestock.checkins.a = [look(1, { tissue: "receding" })];
    assertEqual([panel._coralState("a").word, panel._coralState("a").score], ["needs", 40]);
    panel._config.livestock.checkins.a = [look(1, { extension: 1, colour: 2 })];
    assertEqual([panel._coralState("a").word, panel._coralState("a").score], ["needs", 50], "the bleaching cap");
    panel._config.livestock.checkins.a = [look(1, { extension: 0, fluor: "fading" })];
    assertEqual([panel._coralState("a").word, panel._coralState("a").score], ["watch", 67]);
    panel._config.livestock.checkins.a = [look(1, { extension: 1 }), look(8, { colour: 3 })];
    assertEqual(panel._coralState("a").trend, { delta: -4, word: "down" });
    panel._config.livestock.checkins.a = [look(1, { colour: 3 }), look(8, { colour: 3 })];
    assertEqual(panel._coralState("a").trend, { delta: 0, word: "steady" });
    panel._config.livestock.checkins.a = [look(1, { tissue: "rtn", undoneAt: daysAgo(0) }), look(8)];
    st = panel._coralState("a");
    assertEqual([st.score, st.checkins, st.checkDue], [100, 1, true], "a tombstone never counts");
    // Cadences: own > arrival > group.
    panel._config.livestock.corals.n = coral("zoa", 5);
    assertEqual([panel._coralState("n").cadenceDays, panel._coralState("n").cadenceReason], [3, "arrival"]);
    panel._config.livestock.corals.n.checkCadenceDays = 10;
    assertEqual(panel._coralState("n").cadenceReason, "own");
    panel._config.livestock.corals.z = coral("zoa", 100);
    assertEqual(panel._coralState("z").cadenceDays, 14);
  } finally { restore(); }
});

test("state: the feed clock anchors on the last feed, then arrival; off for NPS and the lost", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await panelWith({ corals: { b: coral("acan", 40) }, checkins: { b: [look(1)] }, feeds: {} });
    let st = panel._coralState("b");
    assertEqual([st.feedDays, st.feedDue], [3, true]);
    panel._config.livestock.feeds.b = [{ at: daysAgo(1) }];
    st = panel._coralState("b");
    assertEqual([st.feedDue, st.nextFeedAt], [false, NOW_MS + 2 * 86400000]);
    panel._config.livestock.feeds.b = [{ at: daysAgo(4) }];
    assert(panel._coralState("b").feedDue);
    panel._config.livestock.corals.b.feedCadenceDays = 0;
    assertEqual(panel._coralState("b").feedDays, 0, "0 switches the reminder off");
    panel._config.livestock.corals.s = coral("suncoral", 40, { npsId: "tubastraea" });
    assertEqual(panel._coralState("s").feedDue, false, "the NPS plan owns those feeds");
    panel._config.livestock.corals.l = coral("acan", 40, { status: "lost" });
    assertEqual(panel._coralState("l").feedDue, false);
  } finally { restore(); }
});

test("summary: counts and due lists match the backend fixture", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await panelWith({
      corals: {
        a: coral("torch", 100, { name: "A" }), b: coral("acan", 100, { name: "B" }),
        c: coral("zoa", 100, { name: "C", status: "lost" }), d: coral("scoly", 100, { name: "D", status: "fragged" }),
      },
      checkins: { a: [look(1)], b: [look(20)] }, feeds: {},
    });
    const s = panel._coralsSummary();
    assertEqual(s.counts, { active: 2, fine: 1, watch: 1, needs: 0, unchecked: 0, lost: 1, gone: 1 });
    assertEqual(s.dueChecks.map((d) => d.id), ["b"]);
    assert(s.dueChecks[0].overdue);
    assertEqual(s.dueFeeds.map((d) => d.id), ["a", "b"]);
  } finally { restore(); }
});

test("shelf: the mouth filter follows the NPS matcher's rule", async () => {
  const panel = await panelWith({ corals: { s: coral("scoly"), c: coral("clam"), z: coral("zoa") } }, { consumables: { products: {
    roids: { name: "Reef Roids", category: "zooPrepared", particleUmMin: 150, particleUmMax: 250 },
    mysis: { name: "Frozen mysis", category: "zooPrepared", particleUmMin: 3000, particleUmMax: 8000 },
    pellet: { name: "LPS pellets", category: "zooPrepared" },
    phyto: { name: "Phyto", category: "phyto" },
  } } });
  const corals = panel._config.livestock.corals;
  assertEqual(panel._coralFoodsOnShelf(corals.s).map((f) => [f.id, f.fits]), [["mysis", true], ["pellet", true], ["roids", false]]);
  assertEqual(panel._coralFoodsOnShelf(corals.c).map((f) => f.id), ["phyto"]);
  assertEqual(panel._coralFoodsOnShelf(corals.z), []);
});

// --- the tab, the rockwork, the NPS tick-list, the settings ----------------------

test("nav: Corals is a Home page and routes its own content", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await panelWith({ corals: { a: coral("torch", 100, { name: "Golden torch" }), b: coral("acan", 100, { name: "Acan garden" }) },
      checkins: { a: [look(1, { tissue: "receding" })] } });
    const home = panel._navGroups().find((g) => g.id === "home");
    assert(home.pages.some(([id]) => id === "corals"), "Corals sits in Home");
    panel._activeTab = "corals";
    const html = panel._activeContent();
    assert(html.includes("corals-tab") && html.includes("Golden torch") && html.includes("Acan garden"), "both colonies listed");
    assert(html.includes("needs you"), "the strip and the card say who needs you");
    assert(html.includes("check-in due") || html.includes("check-in overdue"), "the unchecked acan is due a look");
    assert(html.includes('data-action="coral-round-start"'), "the round is offered");
    panel._coralsFilter = "gone";
    assert(panel._activeContent().includes("Nothing in this view"), "no lost corals yet");
    const empty = await panelWith({ corals: {} });
    empty._activeTab = "corals";
    assert(empty._activeContent().includes("No corals yet"), "the empty state nudges");
  } finally { restore(); }
});

test("rockwork: draws only the first sixteen ACTIVE colonies; a lost coral leaves the rock", async () => {
  const corals = {};
  for (let i = 0; i < 20; i += 1) corals[`c${i}`] = coral("zoa", 100, { name: `Zoa ${i}` });
  corals.c0.status = "lost";
  const panel = await panelWith({ corals });
  const drawn = panel._diagramCorals();
  assertEqual(drawn.length, 16);
  assert(!drawn.some(([id]) => id === "c0"), "the lost colony is not drawn");
  assert(drawn.some(([id]) => id === "c16"), "the seventeenth registered takes the freed slot");
});

test("rockwork glyph carries the diary's word", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await panelWith({ corals: { a: coral("torch", 100, { name: "A" }), b: coral("acan", 100, { name: "B" }), n: coral("zoa", 1, { name: "N" }) },
      checkins: { a: [look(1, { tissue: "receding" })] } }, { equipment: {}, diagram: { layout: {} } });
    panel._hass = { states: {} };
    panel._diagramArranging = false;
    const svg = panel._diagCoralsMarkup("sump");
    assert(/data-diag-coral="a"/.test(svg) && /class="dg-coral dg-cneeds" data-diag-coral="a"/.test(svg), "a receding colony dims and pulses");
    assert(/class="dg-coral dg-cstale" data-diag-coral="b"/.test(svg), "a never-checked colony past its cadence wears the ring");
    assert(/class="dg-coral dg-cnew" data-diag-coral="n"/.test(svg), "a colony added yesterday is new, not stale");
  } finally { restore(); }
});

test("NPS tick-list lives in the registry: derived, added on tick, removed only without a diary", async () => {
  const panel = await panelWith({ corals: { s: coral("suncoral", 100, { name: "Sun", npsId: "tubastraea" }), l: coral("gorgonian", 100, { npsId: "gorgonian_easy", status: "lost" }) } });
  panel._nps = { summary: { speciesLibrary: [{ id: "dendrophyllia", name: "Dendrophyllia", group: "stony" }] } };
  panel._setDirty = () => {};
  panel._render = () => {};
  assertEqual(panel._npsSelectedSpecies(), ["tubastraea"], "a lost NPS coral is not a ticked species");
  panel._npsToggleSpecies("dendrophyllia", true);
  const added = Object.values(panel._config.livestock.corals).find((c) => c.npsId === "dendrophyllia");
  assert(added && added.species === "suncoral" && added.name === "Dendrophyllia", "ticking registers a colony drawn by family");
  panel._npsToggleSpecies("dendrophyllia", false);
  assert(!Object.values(panel._config.livestock.corals).some((c) => c.npsId === "dendrophyllia"), "unticking removes a colony with no diary");
  panel._config.livestock.checkins = { s: [look(1)] };
  panel._npsToggleSpecies("tubastraea", false);
  assert(panel._config.livestock.corals.s, "a colony with a diary stays");
  assert(panel._coralsMsg.includes("Sun has a diary"), "and the tab says why");
});

test("settings section, mission card and the check-in draft", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await panelWith({ corals: { a: coral("torch", 100, { name: "A" }) }, checkins: { a: [look(1, { extension: 1, colour: 3, pests: "suspected" })] } });
    const settings = panel._coralsSettings();
    assert(settings.includes('id="or-section-corals"') && settings.includes('data-coral-setting="photoCap"'), "the diary's knobs render");
    assert(panel._missionCoralsCard().includes("Corals"), "the mission card renders");
    panel._render = () => {};
    panel._coralCheckinStart("a", false);
    const d = panel._coralCheckinDraft;
    assertEqual([d.extension, d.colour, d.pests], [1, 3, "none"], "same as last time is pre-filled; a suspicion is not carried forward");
    const dialog = panel._coralCheckinDialog();
    assert(dialog.includes("coral-checkin-dialog") && dialog.includes('data-id="tissue=receding"'), "the tap rows render");
    panel._coralCheckinPick("neighbours", "stung");
    panel._coralCheckinPick("neighbours", "stung");
    assertEqual(panel._coralCheckinDraft.neighbours, [], "a neighbour tap toggles");
    panel._coralCheckinPick("colour", "6");
    assertEqual(panel._coralCheckinDraft.colour, 6);
  } finally { restore(); }
});

await runTests();
