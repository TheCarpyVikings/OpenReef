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
  assertEqual(panel._pulseRingClass({ status: "ok", score: 96 }), "pulse-ring ok elite");
  assertEqual(panel._pulseRingClass({ status: "ok", score: 94 }), "pulse-ring ok");
  // A capped-but-high score must not shimmer: the cap is the story.
  assertEqual(panel._pulseRingClass({ status: "warning", score: 97 }), "pulse-ring warning");
  assertEqual(panel._pulseRingClass({ status: "critical", score: 40 }), "pulse-ring critical");
  assertEqual(panel._pulseRingClass({ status: "unknown", score: 100 }), "pulse-ring unknown");
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

await runTests();
