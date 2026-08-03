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
  panel._pulseFocus = null;
  panel._pulseFocusTrend = { key: "", range: "", points: null, loading: false };
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
