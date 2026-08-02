/**
 * Panel-side alert thresholds: the contract shared with the backend's
 * _sensor_alert_items (tests/test_alerts.py runs the same cases).
 *
 * These two are the pair where drift hurts most — the panel paints the pills, the
 * backend fires the notifications, and disagreeing means a green tile while a
 * critical push goes out, or a red tile with silence behind it. Light-gating was
 * exactly that: the backend suppressed low readings in the dark, the panel didn't.
 *
 * Run standalone:  node tests/test_panel_alerts.mjs
 */

import { assert, assertEqual, fixture, makePanel, runTests, test } from "./_panel_harness.mjs";

const CONTRACT = fixture("sensor_alert_cases.json");

// The panel has more statuses than the backend has severities (ok/unknown/muted/
// disabled all mean "nothing is being said"). Compare what the user is told.
function nagLevel(status) {
  return status === "critical" || status === "warning" ? status : "none";
}

function panelForCase(testCase) {
  const sensor = { ...CONTRACT.sensorDefaults, ...(testCase.sensor || {}), entity_id: "sensor.subject", label: "Subject" };
  const config = {
    sensors: { subject: sensor },
    alerts: {
      hysteresisPercent: CONTRACT.hysteresisPercent,
      lastStates: testCase.previousState ? { subject: testCase.previousState } : {},
    },
    lightingSchedule: testCase.lightsOn === undefined || testCase.lightsOn === null
      ? { mode: "off" }
      : { mode: "simple", onTime: "08:00", offTime: "20:00" },
  };
  return { sensor, config };
}

async function statusFor(testCase) {
  const { sensor, config } = panelForCase(testCase);
  const panel = await makePanel(config);
  // The live reading the panel would pull off hass.
  panel._state = (entityId) => (entityId === "sensor.subject" ? { state: String(testCase.value) } : null);
  panel._number = (entityId) => (entityId === "sensor.subject" ? testCase.value : null);
  // The backend owns the solar maths; the panel reads its fetched window. Pre-loaded
  // and fresh here so nothing schedules a fetch during the test.
  panel._lightingWindow = {
    data: testCase.lightsOn === undefined || testCase.lightsOn === null
      ? null
      : { configured: true, lightsOnNow: testCase.lightsOn },
    loading: false,
    at: Date.now(),
  };
  return nagLevel(panel._sensorStatus(sensor, "subject"));
}

test("test_thresholds_match_the_shared_contract", async () => {
  const mismatches = [];
  for (const testCase of CONTRACT.cases) {
    const actual = await statusFor(testCase);
    if (actual !== testCase.expect) {
      mismatches.push(`${testCase.name}: panel says ${actual}, contract says ${testCase.expect}`);
    }
  }
  assert(!mismatches.length, `panel drifted from the shared threshold contract:\n    ${mismatches.join("\n    ")}`);
});

test("test_contract_covers_gating_and_hysteresis", async () => {
  const names = CONTRACT.cases.map((entry) => entry.name);
  assertEqual(new Set(names).size, names.length, "duplicate case names in the contract fixture");
  assert(CONTRACT.cases.some((entry) => entry.sensor?.lightGated && entry.lightsOn === false),
    "the contract must pin the light-gated dark case");
  assert(CONTRACT.cases.some((entry) => entry.previousState === "warning"),
    "the contract must pin the sticky-hysteresis case");
});

test("test_an_unknown_lighting_window_never_hides_a_low_reading", async () => {
  // Fail-safe direction: if the window hasn't loaded, a low PAR reading still shows.
  const panel = await makePanel({
    sensors: { subject: { min: 100, max: 400, entity_id: "sensor.subject", enabled: true, alertsEnabled: true, lightGated: true } },
    alerts: {},
    lightingSchedule: { mode: "simple", onTime: "08:00", offTime: "20:00" },
  });
  panel._number = () => 0;
  panel._lightingWindow = { data: null, loading: true, at: 0 };  // loading: no fetch scheduled
  assertEqual(panel._sensorStatus(panel._config.sensors.subject, "subject"), "critical",
    "an unknown window must not suppress a real low reading");
});

test("test_gating_is_off_unless_the_schedule_is_on", async () => {
  const panel = await makePanel({
    sensors: { subject: { min: 100, max: 400, entity_id: "sensor.subject", enabled: true, alertsEnabled: true, lightGated: true } },
    alerts: {},
    lightingSchedule: { mode: "off" },
  });
  panel._number = () => 0;
  panel._lightingWindow = { data: { configured: true, lightsOnNow: false }, loading: false, at: Date.now() };
  assertEqual(panel._sensorStatus(panel._config.sensors.subject, "subject"), "critical",
    "with no lighting schedule there is nothing to gate on");
});

await runTests();
