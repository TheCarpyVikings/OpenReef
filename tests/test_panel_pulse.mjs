/**
 * Reef Pulse kiosk logic: night-dim window maths and the tap-to-expand
 * detail cards.
 *
 * Pulse runs unattended on a wall tablet, so the failure modes are quiet ones
 * nobody is watching for: a dim window that inverts overnight and blacks the
 * screen out all day, a detail card that renders for a sensor that no longer
 * exists, an equipment wattage total that silently absorbs NaN. What is pinned
 * here is the JUDGEMENT, not the styling: when the screen is allowed to dim,
 * which keys produce a card at all, and that the numbers shown are the numbers
 * configured.
 *
 * Run standalone:  node tests/test_panel_pulse.mjs
 */

import { assert, assertEqual, freezeTime, makePanel, runTests, test } from "./_panel_harness.mjs";

function prep(panel, states = {}, patch = {}) {
  panel._hass = { states };
  panel._sensorMeta = {};
  panel._validation = null;
  panel._lightingWindow = { data: null, loading: false, at: 0 };
  panel._healthTrends = { checkedAt: "", items: {}, error: "" };
  panel._pulseFocus = null;
  panel._pulseFocusTrend = { key: "", range: "", points: null, loading: false };
  panel._pulseInsight = { idx: 0 };
  panel._pulseSpawn = { program: null, at: 0, loading: false };
  panel._pulseIcpCards = { cards: null, at: 0, loading: false };
  panel._consumption = null;
  panel._vision = null;
  panel._trustCheck = null;
  panel._awcSummary = null;
  return Object.assign(panel, patch);
}

const num = (state, unit = "") => ({ state: String(state), attributes: { unit_of_measurement: unit } });

// --- night-dim window maths ------------------------------------------------

test("parse time accepts HH:MM and rejects junk", async () => {
  const panel = prep(await makePanel({}));
  assertEqual(panel._pulseParseTime("22:00"), 22 * 60);
  assertEqual(panel._pulseParseTime("07:30"), 7 * 60 + 30);
  assertEqual(panel._pulseParseTime("7:05"), 7 * 60 + 5);
  assertEqual(panel._pulseParseTime("24:00"), null);
  assertEqual(panel._pulseParseTime("12:60"), null);
  assertEqual(panel._pulseParseTime("noon"), null);
  assertEqual(panel._pulseParseTime(""), null);
});

test("night dim is opt-in: default config never dims", async () => {
  const panel = prep(await makePanel({ pulse: {} }));
  assertEqual(panel._pulseNightDimActive(new Date("2026-06-04T03:00:00")), false);
});

test("night dim window crossing midnight covers both sides of it", async () => {
  const panel = prep(await makePanel({ pulse: { nightDim: true, nightDimFrom: "22:00", nightDimTo: "07:00" } }));
  assertEqual(panel._pulseNightDimActive(new Date("2026-06-04T23:30:00")), true, "late evening");
  assertEqual(panel._pulseNightDimActive(new Date("2026-06-04T03:00:00")), true, "small hours");
  assertEqual(panel._pulseNightDimActive(new Date("2026-06-04T06:59:00")), true, "just before end");
  assertEqual(panel._pulseNightDimActive(new Date("2026-06-04T07:00:00")), false, "at end");
  assertEqual(panel._pulseNightDimActive(new Date("2026-06-04T12:00:00")), false, "midday");
  assertEqual(panel._pulseNightDimActive(new Date("2026-06-04T21:59:00")), false, "just before start");
});

test("night dim same-day window works and from==to means never", async () => {
  const sameDay = prep(await makePanel({ pulse: { nightDim: true, nightDimFrom: "13:00", nightDimTo: "15:00" } }));
  assertEqual(sameDay._pulseNightDimActive(new Date("2026-06-04T14:00:00")), true);
  assertEqual(sameDay._pulseNightDimActive(new Date("2026-06-04T16:00:00")), false);
  // A zero-length window is a typo, not a request for a permanently dark wall.
  const zero = prep(await makePanel({ pulse: { nightDim: true, nightDimFrom: "10:00", nightDimTo: "10:00" } }));
  assertEqual(zero._pulseNightDimActive(new Date("2026-06-04T10:00:00")), false);
});

test("night dim with a malformed time falls back to not dimming", async () => {
  const panel = prep(await makePanel({ pulse: { nightDim: true, nightDimFrom: "banana", nightDimTo: "07:00" } }));
  assertEqual(panel._pulseNightDimActive(new Date("2026-06-04T03:00:00")), false);
});

// --- health ring animation tiers ------------------------------------------

test("ring animation tier: elite only for a calm >=95, never for warning or unmeasured", async () => {
  const panel = prep(await makePanel({}));
  assertEqual(panel._pulseRingClass({ status: "ok", score: 96 }), "pulse-ring is-ok is-elite");
  assertEqual(panel._pulseRingClass({ status: "ok", score: 94 }), "pulse-ring is-ok");
  // A capped-but-high score must not shimmer: the cap is the story.
  assertEqual(panel._pulseRingClass({ status: "warning", score: 97 }), "pulse-ring is-warning");
  assertEqual(panel._pulseRingClass({ status: "critical", score: 40 }), "pulse-ring is-critical");
  assertEqual(panel._pulseRingClass({ status: "unknown", score: 100 }), "pulse-ring is-unknown");
});

test("the ring itself never carries a bare status class", async () => {
  // Regression: a bare `warning` on the ring matched the global .warning
  // BUTTON rule, painting an orange rounded rectangle behind the gauge.
  const panel = prep(await makePanel({}));
  for (const status of ["ok", "warning", "critical", "unknown"]) {
    const cls = panel._pulseRingClass({ status, score: 80 });
    assert(!/(?<!-)\b(?:warning|critical|ok|unknown|elite)\b/.test(cls), `ring leaked a bare status class: ${cls}`);
  }
  const markup = panel._pulseRingMarkup({ status: "warning", score: 80, grade: "B" });
  assert(markup.includes("is-warning"), "ring markup carries the prefixed class");
  assert(!/class="pulse-ring warning/.test(markup), "ring markup leaked a bare class");
});

// --- status classes on Pulse's small shapes --------------------------------

test("status classes are prefixed so the global .warning button rule can't inflate a dot", async () => {
  const panel = prep(await makePanel({}));
  assertEqual(panel._pulseStatusClass("ok"), "is-ok");
  assertEqual(panel._pulseStatusClass("warning"), "is-warning");
  assertEqual(panel._pulseStatusClass("critical"), "is-critical");
  assertEqual(panel._pulseStatusClass("muted"), "is-unknown");
  assertEqual(panel._pulseStatusClass(undefined), "is-unknown");
});

test("dots and markers never emit a bare warning/critical class", async () => {
  // Regression: the global `.warning` button class (padding + border, declared
  // after the Pulse block) turned any bare-classed 8px dot into a lozenge.
  const restore = freezeTime("2026-06-04T09:00:00Z");
  try {
    const sensor = { label: "Room Temp", entity_id: "sensor.room", unit: "°C", min: 18, max: 28, enabled: true };
    const panel = prep(await makePanel({ sensors: { room: sensor } }), { "sensor.room": num(35, "°C") });
    // The lookbehind is load-bearing: \b treats the hyphen in "is-critical" as
    // a boundary, so without it the guard flags the very fix it is protecting.
    const bare = /class="[^"]*(?<!-)\b(?:warning|critical|ok|unknown)\b[^"]*"/;

    const marker = panel._pulseRangeBarMarkup("room", sensor);
    assert(marker.includes("is-critical"), "marker carries the prefixed status class");
    assert(!bare.test(marker), `range marker leaked a bare status class: ${marker}`);

    const cats = panel._pulseCategoryBarsMarkup(panel._reefHealthScore());
    assert(cats.includes("is-"), "category bars carry prefixed classes");
    assert(!bare.test(cats), "category bars leaked a bare status class");

    panel._pulseFocus = "insights";
    const deck = panel._pulseFocusInsightsMarkup();
    if (deck) assert(!/<span class="(?:on )?(?:warning|critical|ok|unknown)"/.test(deck), "pager dots leaked a bare status class");

    // Event ticker: a `warning` activity entry used to get the same orange box.
    panel._config.activity = [
      { timestamp: "2026-06-04T08:00:00Z", message: "Skimmer paused", type: "warning" },
      { timestamp: "2026-06-04T07:00:00Z", message: "Feed mode ended", type: "info" },
    ];
    const ticker = panel._pulseTickerMarkup();
    assert(ticker.includes("is-warning"), "ticker carries the prefixed status class");
    assert(!bare.test(ticker), `ticker leaked a bare status class: ${ticker}`);
  } finally {
    restore();
  }
});

// --- share the wall --------------------------------------------------------

test("share model mirrors the wall: ring, up to five tiles with status, insight", async () => {
  const restore = freezeTime("2026-06-04T09:00:00Z");
  try {
    const sensors = {};
    "abcdefg".split("").forEach((k, i) => {
      sensors[`s${k}`] = { label: `Sensor ${k}`, entity_id: `sensor.${k}`, unit: "°C", min: 20, max: 30, enabled: true };
    });
    const states = Object.fromEntries("abcdefg".split("").map((k) => [`sensor.${k}`, num(25, "°C")]));
    // One reading outside its range must carry its status into the card.
    states["sensor.c"] = num(99, "°C");
    const panel = prep(await makePanel({ tank: { name: "Fluval Evo 52L" }, sensors }), states);
    const model = panel._pulseShareModel();
    assertEqual(model.tankName, "Fluval Evo 52L");
    assertEqual(model.tiles.length, 5, "tiles capped at five — the card has five slots");
    assert(model.tiles.every((t) => t.label && t.value), "each tile carries label and value");
    assertEqual(model.tiles[2].status, "critical", "out-of-range reading keeps its status colour");
    assert(Number.isFinite(model.score) && model.score >= 0 && model.score <= 100, "score is a real 0-100");
    assert(model.insight && model.insight.title, "insight strip included by default");
    assert(model.dateText.length > 0, "card is stamped with when it was taken");
  } finally {
    restore();
  }
});

test("share model honours the display toggles it inherits from Pulse", async () => {
  const restore = freezeTime("2026-06-04T09:00:00Z");
  try {
    const panel = prep(await makePanel({
      tank: {},
      pulse: { showInsights: false, showBuddy: false, showMode: false },
    }));
    const model = panel._pulseShareModel();
    assertEqual(model.insight, null, "insights off -> no strip on the card");
    assertEqual(model.showBuddy, false, "buddy off -> no avatar on the card");
    assertEqual(model.modeLabel, "", "mode off -> no mode in the stamp");
    assertEqual(model.tankName, "OpenReef", "unnamed tank still gets a title");
  } finally {
    restore();
  }
});

test("share card status colours are the wall's palette, unknown falls back to grey", async () => {
  const panel = prep(await makePanel({}));
  assertEqual(panel._pulseShareStatusColor("ok"), "#22c55e");
  assertEqual(panel._pulseShareStatusColor("warning"), "#f59e0b");
  assertEqual(panel._pulseShareStatusColor("critical"), "#ef4444");
  assertEqual(panel._pulseShareStatusColor("unknown"), "#64748b");
  assertEqual(panel._pulseShareStatusColor(undefined), "#64748b");
});

test("card text is ellipsized to its box so a long label can never bleed out", async () => {
  const panel = prep(await makePanel({}));
  // Stand-in for a canvas context: one unit of width per character.
  const ctx = { measureText: (t) => ({ width: String(t).length }) };
  assertEqual(panel._fitText(ctx, "short", 40), "short", "text that fits is untouched");
  const clipped = panel._fitText(ctx, "an extremely long sensor label that will not fit", 12);
  assert(clipped.endsWith("…"), "long text gets an ellipsis");
  assert(clipped.length <= 12, `clipped text must fit the box, got ${clipped.length}`);
  assertEqual(panel._fitText(ctx, null, 10), "", "null renders as empty, not 'null'");
});

// --- named faces -----------------------------------------------------------

// Lockstep with _normalise_core_config's pulse section: a face writing a field
// the backend doesn't validate would be silently dropped or ride unvalidated.
const NORMALISED_PULSE_FIELDS = new Set([
  "enabled", "showHealthRing", "showStats", "showTicker", "showMode", "showBuddy",
  "showClock", "kioskAutoStart", "showSparklines", "showCategories", "showEquipment",
  "showToday", "showInsights", "showShare", "keepAwake", "nightDim", "cameraId",
  "backdrop", "graphRange", "timelapseStyle", "sizePreset",
  "nightDimFrom", "nightDimTo", "nightDimLuxEntity", "nightDimLuxThreshold",
]);
// Faces are layout presets, not preference resets — these stay untouched.
const USER_PREFS_FACES_MUST_NOT_TOUCH = [
  "kioskAutoStart", "keepAwake", "nightDim", "nightDimFrom", "nightDimTo",
  "nightDimLuxEntity", "nightDimLuxThreshold", "cameraId", "graphRange",
  "sizePreset", "showShare", "enabled",
];

test("faces only write backend-validated fields and never touch user prefs", async () => {
  const panel = prep(await makePanel({}));
  const faces = panel._pulseFaces();
  assertEqual(Object.keys(faces).sort(), ["datawall", "diagram", "minimal", "photoframe"]);
  for (const [id, face] of Object.entries(faces)) {
    for (const key of Object.keys(face.patch)) {
      assert(NORMALISED_PULSE_FIELDS.has(key), `${id} writes unvalidated field ${key}`);
      assert(!USER_PREFS_FACES_MUST_NOT_TOUCH.includes(key), `${id} must not touch user pref ${key}`);
    }
    assert(["auto", "camera", "wall", "timelapse", "diagram"].includes(face.patch.backdrop), `${id} backdrop must be whitelisted`);
  }
});

test("faces express their intent: full wall, quiet photo frame, minimal night", async () => {
  const panel = prep(await makePanel({}));
  const faces = panel._pulseFaces();
  assert(Object.values(faces.datawall.patch).filter((v) => v === true).length >= 10, "data wall turns everything on");
  assertEqual(faces.photoframe.patch.showStats, false);
  assertEqual(faces.photoframe.patch.showHealthRing, true, "photo frame keeps the ring");
  assertEqual(faces.photoframe.patch.showInsights, true, "photo frame keeps one ambient story");
  assertEqual(faces.minimal.patch.showInsights, false, "minimal is genuinely minimal");
  assertEqual(faces.minimal.patch.showClock, true, "minimal keeps the clock");
});

test("applying a face patches config, marks dirty, and preserves user prefs", async () => {
  let dirty = null;
  let rendered = 0;
  const panel = prep(await makePanel({
    pulse: { kioskAutoStart: true, nightDim: true, sizePreset: "far", showStats: true, backdrop: "camera" },
  }), {}, {
    _setDirty: (v) => { dirty = v; },
    _render: () => { rendered += 1; },
  });
  panel._applyPulseFace("minimal");
  const pulse = panel._config.pulse;
  assertEqual(pulse.showStats, false, "face applied");
  assertEqual(pulse.backdrop, "wall");
  assertEqual(pulse.kioskAutoStart, true, "kiosk autostart preserved");
  assertEqual(pulse.nightDim, true, "night dim preserved");
  assertEqual(pulse.sizePreset, "far", "viewing distance preserved");
  assertEqual(dirty, true, "settings marked dirty for the Save flow");
  assertEqual(rendered, 1);
  panel._applyPulseFace("nonsense");
  assertEqual(rendered, 1, "unknown face is a no-op");
});

// --- tap-to-expand focus cards --------------------------------------------

test("focus markup is empty for no focus and for unknown keys", async () => {
  const panel = prep(await makePanel({ sensors: {}, equipment: {} }));
  panel._pulseFocus = null;
  assertEqual(panel._pulseFocusMarkup(), "");
  panel._pulseFocus = "nonsense";
  assertEqual(panel._pulseFocusMarkup(), "");
  panel._pulseFocus = "sensor:ghost"; // sensor removed while the card was up
  assertEqual(panel._pulseFocusMarkup(), "");
});

test("sensor focus card shows live value, badge and range controls", async () => {
  const panel = prep(await makePanel({
    sensors: { temp: { label: "Tank Temperature", entity_id: "sensor.tank_temp", unit: "°C", min: 24, max: 26, enabled: true } },
  }), { "sensor.tank_temp": num(25.2, "°C") });
  panel._pulseFocus = "sensor:temp";
  panel._pulseFocusTrend = { key: "sensor:temp", range: "24h", points: null, loading: true };
  const html = panel._pulseFocusMarkup();
  assert(html.includes("Tank Temperature"), "label shown");
  assert(html.includes("25.2"), "current value shown");
  assert(html.includes("in range"), "badge label shown");
  assert(html.includes("Loading history…"), "loading state while trend fetch is in flight");
  assert(html.includes('data-action="pulse-focus-range"'), "range buttons offered");
  assert(html.includes('data-action="pulse-unfocus"'), "card can be closed");
});

test("sensor focus card computes low/average/high from fetched points", async () => {
  const panel = prep(await makePanel({
    sensors: { ph: { label: "pH Level", entity_id: "sensor.ph", min: 7.8, max: 8.4, enabled: true } },
  }), { "sensor.ph": num(8.06) });
  panel._pulseFocus = "sensor:ph";
  panel._pulseFocusTrend = {
    key: "sensor:ph", range: "24h", loading: false,
    points: [{ time: 0, value: 8.0 }, { time: 1, value: 8.2 }, { time: 2, value: 8.1 }],
  };
  const html = panel._pulseFocusMarkup();
  assert(html.includes("8.00"), "low uses pH digits");
  assert(html.includes("8.20"), "high uses pH digits");
  assert(html.includes("8.10"), "average of the points");
  assert(html.includes("7.80–8.40"), "configured target band shown");
  assert(html.includes("pulse-focus-svg"), "chart rendered from points");
});

test("binary sensor focus card shows state only — no chart, no range buttons", async () => {
  const panel = prep(await makePanel({
    sensors: { leak: { label: "Leak Sensor", entity_id: "binary_sensor.leak", kind: "binary", enabled: true } },
  }), { "binary_sensor.leak": { state: "off", attributes: { device_class: "moisture" } } });
  panel._pulseFocus = "sensor:leak";
  const html = panel._pulseFocusMarkup();
  assert(html.includes("Leak Sensor"), "label shown");
  assert(!html.includes("pulse-focus-svg"), "no numeric chart for a binary state");
  assert(!html.includes('data-action="pulse-focus-range"'), "no history range buttons");
});

test("focus chart draws the target band only when the sensor has a real range", async () => {
  const panel = prep(await makePanel({}));
  const points = [{ time: 0, value: 10 }, { time: 60000, value: 12 }];
  assert(panel._pulseFocusChartSvg(points, { min: 9, max: 13 }).includes('class="band"'), "band for a valid range");
  assert(!panel._pulseFocusChartSvg(points, {}).includes('class="band"'), "no band without a range");
  assert(!panel._pulseFocusChartSvg(points, { min: 13, max: 9 }).includes('class="band"'), "no band for an inverted range");
});

test("equipment focus card lists switch-mapped gear and totals real watts only", async () => {
  const panel = prep(await makePanel({
    equipment: {
      return_pump: { label: "Return Pump", switch_entity_id: "switch.return", power_entity_id: "sensor.return_w" },
      skimmer: { label: "Skimmer", switch_entity_id: "switch.skimmer", power_entity_id: "sensor.skimmer_w" },
      probe: { label: "No Switch" }, // not switch-mapped -> not a row
    },
  }), {
    "switch.return": { state: "on" },
    "switch.skimmer": { state: "off" },
    "sensor.return_w": num(23.4, "W"),
    // skimmer power entity missing -> reads as null and must stay out of the total
  });
  panel._pulseFocus = "equipment";
  const html = panel._pulseFocusMarkup();
  assert(html.includes("Return Pump") && html.includes("Skimmer"), "both mapped rows present");
  assert(!html.includes("No Switch"), "unmapped gear excluded");
  assert(html.includes("Running") && html.includes("Off"), "state labels shown");
  assert(html.includes("2 tracked · 23 W now"), "wattage total sums only finite readings");
});

// --- night dim: lux sensor beats the clock ---------------------------------

test("lux sensor decides dimming when mapped; clock is the fallback", async () => {
  const cfg = { nightDim: true, nightDimFrom: "22:00", nightDimTo: "07:00", nightDimLuxEntity: "sensor.room_lux", nightDimLuxThreshold: 10 };
  const midday = new Date("2026-06-04T12:00:00");
  const midnight = new Date("2026-06-04T00:30:00");
  // Dark room at midday -> dims even outside the clock window.
  const dark = prep(await makePanel({ pulse: cfg }), { "sensor.room_lux": num(4, "lx") });
  assertEqual(dark._pulseNightDimActive(midday), true, "dark room dims regardless of clock");
  // Bright room at midnight -> the lux sensor overrides the clock window.
  const bright = prep(await makePanel({ pulse: cfg }), { "sensor.room_lux": num(120, "lx") });
  assertEqual(bright._pulseNightDimActive(midnight), false, "lit room stays awake inside the window");
  // Sensor unavailable -> honest fallback to the clock window.
  const gone = prep(await makePanel({ pulse: cfg }), { "sensor.room_lux": { state: "unavailable", attributes: {} } });
  assertEqual(gone._pulseNightDimActive(midnight), true, "clock window applies when the sensor is gone");
  assertEqual(gone._pulseNightDimActive(midday), false);
});

// --- tonight's moon --------------------------------------------------------

test("moon math: new at the epoch, full a half-cycle later, matches a real full moon", async () => {
  const panel = prep(await makePanel({}));
  const epoch = new Date(Date.UTC(2000, 0, 6, 18, 14));
  const atEpoch = panel._pulseMoonInfo(epoch);
  assertEqual(atEpoch.phaseName, "New moon");
  assert(atEpoch.illumination < 0.01, "dark at the epoch");
  const half = new Date(epoch.getTime() + 14.765 * 86400000);
  const atHalf = panel._pulseMoonInfo(half);
  assertEqual(atHalf.phaseName, "Full moon");
  assert(atHalf.illumination > 0.99, "fully lit at the half-cycle");
  // Real-world spot check: 13 Jan 2025 was a full moon.
  const spot = panel._pulseMoonInfo(new Date(Date.UTC(2025, 0, 13, 22, 0)));
  assert(spot.illumination > 0.94, `13 Jan 2025 should read nearly full, got ${spot.illumination.toFixed(3)}`);
});

// --- insight cards ---------------------------------------------------------

test("insight cards: moon always present, subsystem cards only when their data exists", async () => {
  const restore = freezeTime("2026-06-04T09:00:00Z");
  try {
    const panel = prep(await makePanel({ sensors: {}, equipment: {}, alerts: {} }));
    const keys = panel._pulseInsightCards().map((c) => c.key);
    assert(keys.includes("moon"), "moon card is always available");
    assert(!keys.some((k) => k.startsWith("consumption-")), "no consumption cards without advisor data");
    assert(!keys.some((k) => k.startsWith("icp-")), "no ICP cards without a fetched dashboard");
    assert(!keys.includes("lighting"), "no lighting card without a configured window");
    assert(!keys.includes("vision-seen"), "no vision card when the engine is off");
  } finally {
    restore();
  }
});

test("insight cards: consumption projections surface worst-first and skip learning", async () => {
  const restore = freezeTime("2026-06-04T09:00:00Z");
  try {
    const sensors = {
      alkalinity: { label: "Alkalinity", entity_id: "sensor.alk", min: 7, max: 11, enabled: true },
      calcium: { label: "Calcium", entity_id: "sensor.ca", min: 380, max: 460, enabled: true },
    };
    const panel = prep(await makePanel({ sensors, dosing: { enabled: true } }), {}, {
      _dosingEnabled: () => true,
      _dosingActiveParameters: () => Object.entries(sensors),
      _consumption: {
        checkedAt: "2026-06-04T08:00:00Z",
        items: {
          alkalinity: { status: "warning", trendText: "Falling ~0.12 dKH/day", projectionText: "Reaches your low limit in about 9 days" },
          calcium: { status: "learning", trendText: "Learning", projectionText: "" },
        },
        error: "",
      },
    });
    const cards = panel._pulseInsightCards();
    const consumption = cards.filter((c) => c.key.startsWith("consumption-"));
    assertEqual(consumption.length, 1, "learning parameter contributes no card");
    assertEqual(consumption[0].title, "Falling ~0.12 dKH/day");
    assertEqual(consumption[0].status, "warning");
  } finally {
    restore();
  }
});

test("insight cards: quiet-reef streak counts days since the last critical alert", async () => {
  const restore = freezeTime("2026-06-10T09:00:00Z");
  try {
    const withCritical = prep(await makePanel({
      alerts: { history: [
        { timestamp: "2026-06-09T12:00:00Z", state: "warning", label: "pH near limit" },
        { timestamp: "2026-06-05T09:00:00Z", state: "critical", label: "Tank temp high" },
      ] },
    }));
    const streak = withCritical._pulseInsightCards().find((c) => c.key === "streak");
    assert(streak, "streak card present");
    assert(streak.title.includes("5 days since the last critical alert"), streak.title);
    const clean = prep(await makePanel({
      alerts: { history: Array.from({ length: 6 }, (_, i) => ({ timestamp: `2026-06-0${i + 1}T09:00:00Z`, state: "warning", label: "w" })) },
    }));
    const cleanCard = clean._pulseInsightCards().find((c) => c.key === "streak");
    assertEqual(cleanCard.title, "No critical alerts in the log");
  } finally {
    restore();
  }
});

test("insight cards: spawn countdown rides the moon card when the program is cached", async () => {
  const restore = freezeTime("2026-06-04T09:00:00Z");
  try {
    const panel = prep(await makePanel({}), {}, {
      _pulseSpawn: { at: Date.now(), loading: false, program: {
        preset: { label: "Great Barrier Reef" },
        spawnPrediction: { nightsUntilWindowStart: 23, nightsUntilWindowEnd: 27 },
      } },
    });
    const moon = panel._pulseInsightCards().find((c) => c.key === "moon");
    assert(moon.detail.includes("23 nights until the Great Barrier Reef window"), moon.detail);
  } finally {
    restore();
  }
});

test("insight deck: opens on the tapped card, arrows wrap, swipe direction maps to step", async () => {
  const restore = freezeTime("2026-06-04T09:00:00Z");
  try {
    const panel = prep(await makePanel({
      alerts: { history: [{ timestamp: "2026-06-01T09:00:00Z", state: "critical", label: "Old scare" }] },
    }), {}, { _pulseActive: true });
    const deck = panel._pulseInsightCards();
    assert(deck.length >= 2, "need a deck to page through");
    // Ambient rotator is showing card 1; tapping must open the deck there.
    panel._pulseInsight.idx = 1;
    panel._openPulseFocus("insights");
    assertEqual(panel._pulseFocus, "insights");
    assertEqual(panel._pulseFocusInsightIdx, 1, "deck opens on the tapped card");
    // Next wraps forward past the end; prev wraps back.
    panel._pulseFocusInsightIdx = deck.length - 1;
    panel._pulseFocusInsightNav(1);
    assertEqual(panel._pulseFocusInsightIdx, 0, "next wraps to the first card");
    panel._pulseFocusInsightNav(-1);
    assertEqual(panel._pulseFocusInsightIdx, deck.length - 1, "prev wraps to the last card");
    const html = panel._pulseFocusInsightsMarkup();
    assert(html.includes("data-pulse-insight-deck"), "deck is swipe-targetable");
    assert((html.match(/pulse-insight-dots/g) || []).length === 1 && html.includes(`1/${deck.length}`) === false, "pager present");
    assert(html.includes(`${deck.length}/${deck.length}`), "position indicator shows current page");
  } finally {
    restore();
  }
});

test("insight deck markup shows the expanded `more` lines the strip hides", async () => {
  const restore = freezeTime("2026-06-04T09:00:00Z");
  try {
    const panel = prep(await makePanel({}), {}, {
      _pulseActive: true,
      _pulseSpawn: { at: Date.now(), loading: false, program: {
        preset: { label: "Great Barrier Reef" },
        spawnPrediction: { nightsUntilWindowStart: 23, nightsUntilWindowEnd: 27, fullMoonUtc: "2026-06-29T12:00:00Z", windowStart: "2026-07-02", windowEnd: "2026-07-05" },
      } },
    });
    const moon = panel._pulseInsightCards().find((c) => c.key === "moon");
    assert(moon.more.some((l) => l.includes("Full moon: 2026-06-29")), "full moon date in more lines");
    assert(moon.more.some((l) => l.includes("2026-07-02 → 2026-07-05")), "window range in more lines");
    const deck = panel._pulseInsightCards();
    panel._pulseFocus = "insights";
    panel._pulseFocusInsightIdx = deck.findIndex((c) => c.key === "moon");
    const html = panel._pulseFocusInsightsMarkup();
    assert(html.includes("Full moon: 2026-06-29"), "expanded view renders the more lines");
  } finally {
    restore();
  }
});

test("insight rotation cycles cards and the markup carries the current key", async () => {
  const restore = freezeTime("2026-06-04T09:00:00Z");
  try {
    const panel = prep(await makePanel({
      alerts: { history: [{ timestamp: "2026-06-01T09:00:00Z", state: "critical", label: "Old scare" }] },
    }));
    const cards = panel._pulseInsightCards();
    assert(cards.length >= 2, "need at least two cards to rotate");
    panel._pulseInsight.idx = 0;
    const first = panel._pulseInsightKey();
    panel._pulseInsight.idx = 1;
    const second = panel._pulseInsightKey();
    assert(first !== second, "advancing the index changes the card");
    panel._pulseInsight.idx = cards.length;
    assertEqual(panel._pulseInsightKey(), first, "rotation wraps modulo the deck");
    assert(panel._pulseInsightMarkup().includes(`data-insight-key="${first}"`), "markup stamps the key for swap detection");
  } finally {
    restore();
  }
});

test("today focus card with nothing configured stays honest, not empty", async () => {
  const restore = freezeTime("2026-06-04T09:00:00Z");
  try {
    const panel = prep(await makePanel({ maintenance: {}, energy: {} }));
    panel._pulseFocus = "today";
    const html = panel._pulseFocusMarkup();
    assert(html.includes("All caught up"), "headline for an empty fortnight");
    assert(html.includes("Nothing due in the next 14 days."), "explicit empty state");
  } finally {
    restore();
  }
});

// --- changing mode from the wall -------------------------------------------

const MODE_RIG = {
  equipment: {
    ret: { label: "Return Pump", type: "return_pump", switch_entity_id: "switch.ret", armed: true },
    skim: { label: "Skimmer", type: "skimmer", switch_entity_id: "switch.skim", armed: true },
    heat: { label: "Heater", type: "heater", switch_entity_id: "switch.heat", armed: false },
  },
  modePreviews: { feed: { ret: "off", skim: "off", heat: "off" } },
  mode: { active: "running", startedAt: "" },
};
const MODE_STATES = {
  "switch.ret": { state: "on", attributes: {} },
  "switch.skim": { state: "on", attributes: {} },
  "switch.heat": { state: "on", attributes: {} },
};
const modePanel = async (pulse = {}, cfg = {}) => prep(
  await makePanel({ ...structuredClone(MODE_RIG), ...cfg, pulse: { enabled: true, ...pulse } }),
  MODE_STATES,
);

test("the mode chip is a control only when the wall is allowed to change mode", async () => {
  const on = await modePanel();
  assertEqual(on._pulseModeAllowed(), true, "allowed by default, like diagram controls");
  const off = await modePanel({ allowModes: false });
  assertEqual(off._pulseModeAllowed(), false);
  // The card itself refuses too — the gate cannot be walked round by deep-linking
  // straight to the focus key.
  off._pulseFocus = "modes";
  assertEqual(off._pulseFocusMarkup(), "", "a disallowed wall renders no mode card at all");
});

test("the mode list shows every mode, marks the active one, and leads with the way back", async () => {
  const panel = await modePanel();
  panel._pulseFocus = "modes";
  panel._pulseModePick = "";
  const running = panel._pulseFocusMarkup();
  assert(running.includes('data-id="feed"'), "Feed is offered");
  assert(/data-id="running"[^>]*disabled/.test(running), "the active mode is not tappable");

  // Mid-Feed, getting back to Running is the urgent one, so it comes first.
  panel._config.mode.active = "feed";
  const inFeed = panel._pulseFocusMarkup();
  const order = [...inFeed.matchAll(/pulse-mode-row[^>]*data-id="([a-z]+)"/g)].map((m) => m[1]);
  assertEqual(order[0], "running", "Return to Running leads while a mode is active");
  assert(inFeed.includes("Return to Running"), "and says so in words");
});

test("picking a mode shows the real plan before anything can be applied", async () => {
  const panel = await modePanel();
  panel._pulseFocus = "modes";
  panel._pulseModePick = "feed";
  const html = panel._pulseFocusMarkup();
  assert(html.includes("Return Pump") && html.includes("Skimmer"), "armed gear is listed");
  assert(html.includes("turn off"), "and what will happen to it");
  // The disarmed heater must be shown as skipped, not silently dropped: the
  // wall has to match what actually happens.
  assert(html.includes("Heater") && html.includes("locked"), "disarmed gear shows as locked");
  assert(html.includes('data-action="pulse-mode-apply"'), "apply is offered once the plan is visible");
  assert(!/pulse-mode-apply[^>]*disabled/.test(html), "two ready actions -> apply is live");
});

test("a mode with nothing configured cannot be applied", async () => {
  const panel = await modePanel({}, { modePreviews: {} });
  panel._pulseFocus = "modes";
  panel._pulseModePick = "feed";
  const html = panel._pulseFocusMarkup();
  assert(/pulse-mode-apply[^>]*disabled/.test(html), "nothing ready -> apply stays disabled");
  assert(html.includes("No equipment actions are configured"), "and says why");
});

test("apply re-checks the gate and the mode id rather than trusting the markup", async () => {
  const applied = [];
  const panel = await modePanel();
  panel._pulseActive = true;
  panel._applyMode = (id) => applied.push(id);

  panel._pulseApplyMode("nonsense-mode");
  assertEqual(applied.length, 0, "an unknown mode id is refused");

  panel._config.pulse.allowModes = false;
  panel._pulseApplyMode("feed");
  assertEqual(applied.length, 0, "a wall that may not change mode is refused");

  panel._config.pulse.allowModes = true;
  panel._busy = true;
  panel._pulseApplyMode("feed");
  assertEqual(applied.length, 0, "no double-fire while one apply is in flight");

  panel._busy = false;
  panel._pulseApplyMode("feed");
  assertEqual(applied, ["feed"], "a real request goes through");
  assertEqual(panel._pulseModePick, "", "and the plan step closes behind it");
});

// --- the fullscreen trap ---------------------------------------------------

test("Pulse's own re-render must not read as the user leaving fullscreen", async () => {
  const panel = await modePanel();
  const realDoc = globalThis.document;
  let closed = 0;
  globalThis.document = { fullscreenElement: null, addEventListener() {}, removeEventListener() {} };
  try {
    panel._pulseActive = true;
    panel._pulseEnteredFs = true;
    panel._closePulse = () => { closed += 1; };
    // No .pulse-root to re-request against: the fallback must still not close.
    panel.shadowRoot = { querySelector: () => null };

    // Fullscreen ended right after one of our DOM swaps — that is us, not Esc.
    // Applying a mode used to land here and dump the wall back to the panel.
    panel._pulseFsSwapAt = Date.now();
    panel._onPulseFullscreenChange();
    assertEqual(closed, 0, "a self-inflicted fullscreen exit must never close Pulse");

    // A genuine exit, long after any swap, still closes Pulse.
    panel._pulseEnteredFs = true;
    panel._pulseFsSwapAt = Date.now() - 10000;
    panel._onPulseFullscreenChange();
    assertEqual(closed, 1, "pressing Esc out of fullscreen still leaves present mode");

    // Never entered fullscreen in the first place: nothing to react to.
    panel._pulseEnteredFs = false;
    panel._pulseFsSwapAt = 0;
    panel._onPulseFullscreenChange();
    assertEqual(closed, 1, "a windowed Pulse ignores fullscreen events entirely");
  } finally {
    globalThis.document = realDoc;
  }
});

test("regaining fullscreen after a swap is best-effort, never fatal", async () => {
  const panel = await modePanel();
  const realDoc = globalThis.document;
  let closed = 0;
  let requested = 0;
  globalThis.document = { fullscreenElement: null, addEventListener() {}, removeEventListener() {} };
  try {
    panel._pulseActive = true;
    panel._pulseEnteredFs = true;
    panel._closePulse = () => { closed += 1; };
    panel.shadowRoot = {
      querySelector: () => ({
        requestFullscreen: () => { requested += 1; return Promise.reject(new Error("gesture expired")); },
      }),
    };
    panel._pulseFsSwapAt = Date.now();
    panel._onPulseFullscreenChange();
    assertEqual(requested, 1, "it tries to take fullscreen back");
    assertEqual(closed, 0, "and a refusal leaves Pulse open, just windowed");
    assertEqual(panel._pulseFsSwapAt, 0, "the swap stamp is consumed, so the next Esc is honoured");
  } finally {
    globalThis.document = realDoc;
  }
});

// --- how long left ---------------------------------------------------------

const NOW = "2026-08-09T12:00:00Z";
const inMs = (ms) => new Date(Date.parse(NOW) + ms).toISOString();

const timerPanel = async (mode, extra = {}) => prep(
  await makePanel({
    ...structuredClone(MODE_RIG),
    mode: { active: "running", startedAt: "", expiresAt: "", autoReturn: false, ...mode },
    pulse: { enabled: true },
    ...extra,
  }),
  MODE_STATES,
);

test("countdowns are clock-shaped, so they look like they are counting", async () => {
  const panel = prep(await makePanel({}));
  assertEqual(panel._formatCountdown(7 * 60000 + 32000), "7:32");
  assertEqual(panel._formatCountdown(62000), "1:02", "seconds are zero-padded");
  assertEqual(panel._formatCountdown(9000), "0:09", "under a minute still reads as a clock");
  assertEqual(panel._formatCountdown(3 * 3600000 + 4 * 60000 + 5000), "3:04:05");
  assertEqual(panel._formatCountdown(-5000), "0:00", "never counts past zero into negatives");
});

test("the countdown reports the RUN, not the mode's configuration", async () => {
  const restore = freezeTime(NOW);
  try {
    // A mode carrying a 20 minute timer, but applied before that timer existed:
    // the backend only stamps expiresAt at apply time, so this run has none.
    const panel = await timerPanel(
      { active: "feed", startedAt: inMs(-900000), expiresAt: "", autoReturn: false },
      { modeTimers: { feed: { durationMinutes: 20, autoReturn: true } } },
    );
    const timer = panel._modeCountdown();
    assertEqual(timer.hasTimer, false, "no expiry stamped means no timer on this run");
    assertEqual(timer.autoReturn, false, "and nothing will bring it back on its own");
    const card = panel._pulseModeCountdownMarkup();
    assert(card.includes("No timer on this run"), "the wall says which it means");
    assert(card.includes("20 minute timer"), "and does not contradict the duration shown per mode");
    assert(card.includes("applies next time"), "explaining why the two differ");
  } finally {
    restore();
  }
});

test("a mode with no timer at all says so plainly rather than showing nothing", async () => {
  const restore = freezeTime(NOW);
  try {
    // Feed carries a built-in 10 minute default, so "no timer at all" needs a
    // mode configured to zero — which is what every custom mode starts as.
    const panel = await timerPanel(
      { active: "feed", startedAt: inMs(-600000) },
      { modeTimers: { feed: { durationMinutes: 0, autoReturn: false } } },
    );
    assertEqual(panel._activeModeCountdownText(), "No timer — stays on until you return to Running");
    const card = panel._pulseModeCountdownMarkup();
    assert(card.includes("will not end by itself"), "the wall must not imply it sorts itself out");
    assert(card.includes("Settings → Modes"), "and says where to give it one");
  } finally {
    restore();
  }
});

test("a timed run counts down, and says whether anything will act on it", async () => {
  const restore = freezeTime(NOW);
  try {
    const auto = await timerPanel({ active: "feed", startedAt: inMs(-150000), expiresAt: inMs(452000), autoReturn: true });
    const timer = auto._modeCountdown();
    assertEqual(timer.hasTimer, true);
    assertEqual(timer.clock, "7:32");
    assert(auto._activeModeCountdownText().startsWith("7:32 left"), "the number leads");
    assert(auto._activeModeCountdownText().includes("returns on its own"), "auto-return is stated");

    const manual = await timerPanel({ active: "feed", startedAt: inMs(-150000), expiresAt: inMs(452000), autoReturn: false });
    assert(manual._activeModeCountdownText().includes("waits for you"),
      "without auto-return the timer only expires — it must not read as a promise to return");
  } finally {
    restore();
  }
});

test("an expired run is distinguishable from one still counting", async () => {
  const restore = freezeTime(NOW);
  try {
    const due = await timerPanel({ active: "feed", startedAt: inMs(-900000), expiresAt: inMs(-1000), autoReturn: true });
    assertEqual(due._modeCountdown().expired, true);
    assertEqual(due._activeModeCountdownText(), "Auto-return due");
    assertEqual(due._pulseModeChipText(), "Feed · returning");

    const stuck = await timerPanel({ active: "feed", startedAt: inMs(-900000), expiresAt: inMs(-1000), autoReturn: false });
    assertEqual(stuck._activeModeCountdownText(), "Timer expired");
    assertEqual(stuck._pulseModeChipText(), "Feed · timer up");
  } finally {
    restore();
  }
});

test("the wall chip carries the countdown, and Running stays a plain label", async () => {
  const restore = freezeTime(NOW);
  try {
    const running = await timerPanel({ active: "running", startedAt: inMs(-60000) });
    assertEqual(running._pulseModeChipText(), "Running", "no countdown clutter when nothing is timed");
    const feed = await timerPanel({ active: "feed", startedAt: inMs(-60000), expiresAt: inMs(452000), autoReturn: true });
    assertEqual(feed._pulseModeChipText(), "Feed · 7:32");
    const untimed = await timerPanel({ active: "feed", startedAt: inMs(-60000) });
    assertEqual(untimed._pulseModeChipText(), "Feed", "an untimed run shows no invented clock");
  } finally {
    restore();
  }
});

test("the one-second timer repaints the chip, so the Pulse tick cannot wipe it", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await timerPanel(
      { active: "feed", startedAt: inMs(-60000), expiresAt: inMs(452000), autoReturn: true },
      { energy: {}, maintenance: {}, sensors: {} },
    );
    const countdownEl = { textContent: "" };
    const chipEl = { textContent: "" };
    panel.shadowRoot = {
      querySelectorAll: (sel) => (sel === "[data-mode-countdown]" ? [countdownEl] : []),
      querySelector: (sel) => (sel === "[data-pulse-mode]" ? chipEl : null),
    };
    panel._updateModeCountdownElements();
    assert(countdownEl.textContent.startsWith("7:32 left"), "panel countdowns tick");
    assertEqual(chipEl.textContent, "Feed · 7:32", "and so does the wall chip");
    // Pulse's own 10s repaint writes the chip too. If it writes the bare label
    // the countdown visibly stalls for ten seconds at a time, so drive the real
    // update path and assert the clock survives it.
    chipEl.textContent = "";
    // _updatePulse touches a lot of the wall; anything that is not the chip can
    // be an inert stand-in.
    const stub = () => ({
      textContent: "", offsetWidth: 0, style: {},
      classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
      setAttribute() {}, getAttribute: () => null,
      querySelector: () => stub(), querySelectorAll: () => [],
    });
    const pulseRoot = {
      ...stub(),
      querySelector: (sel) => (sel === "[data-pulse-mode]" ? chipEl : stub()),
      querySelectorAll: () => [],
    };
    panel.shadowRoot = {
      querySelectorAll: () => [],
      querySelector: (sel) => (sel === "[data-pulse-root]" ? pulseRoot : sel === "[data-pulse-mode]" ? chipEl : stub()),
    };
    panel._pulseTick = 1;
    panel._updatePulse();
    assertEqual(chipEl.textContent, "Feed · 7:32", "the Pulse repaint must not drop back to the bare label");
  } finally {
    restore();
  }
});

test("each mode says up front how long it would run for", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await timerPanel({ active: "running" }, {
      modeTimers: { feed: { durationMinutes: 10, autoReturn: true }, maintenance: { durationMinutes: 0, autoReturn: false } },
    });
    panel._pulseFocus = "modes";
    panel._pulseModePick = "";
    const html = panel._pulseFocusMarkup();
    assert(html.includes("10 min, returns on its own"), "a timed mode advertises its timer");
    assert(html.includes("no timer — stays until you end it"), "and an untimed one is called out");
  } finally {
    restore();
  }
});

await runTests();
