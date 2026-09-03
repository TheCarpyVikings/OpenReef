/**
 * Cooling headroom (Layer 1) panel logic: the one digest every surface reads
 * (Overview row, Pulse card, Settings readout) from the backend's status
 * payload. The panel never recomputes the index — what is pinned here is
 * that it renders the backend's verdict faithfully, that a humid-but-cool
 * day never becomes a warning card, and that a missing reading degrades to
 * "not reporting" rather than a number.
 *
 * Run standalone:  node tests/test_panel_cooling.mjs
 */

import { assert, assertEqual, makePanel, runTests, test } from "./_panel_harness.mjs";

function status(over = {}) {
  return {
    enabled: true, targetC: 25.5, targetSource: "fixed", waterSource: "sensor", waterC: 26,
    roomC: 30.1, rh: 78, fanNeeded: true, warn: true, issues: {},
    result: { waterC: 26, roomC: 30.1, rh: 78, dewC: 25.9, marginC: 0.1, vpdKpa: 0.04, index: 0.02,
      band: "dead", status: "warning", title: "Evaporative cooling has stopped", netFan: "marginal" },
    whatIf: { humidities: [50, 70, 80], rows: [
      { roomC: 22, cells: [{ rh: 50, index: 1.1, band: "good" }, { rh: 70, index: 0.82, band: "good" }, { rh: 80, index: 0.67, band: "thin" }] },
      { roomC: 30, cells: [{ rh: 50, index: 0.67, band: "thin" }, { rh: 70, index: 0.21, band: "weak" }, { rh: 80, index: 0, band: "reversed" }] },
    ] },
    ...over,
  };
}

async function prep(cfg = { enabled: true }, st = status()) {
  const panel = await makePanel({ coolingHeadroom: cfg, spawningProgram: { enabled: false } });
  panel._cooling = { status: st, at: Date.now(), loading: false, error: "" };
  panel._callWS = async () => { throw new Error("no network in tests"); };
  panel._render = () => {};
  return panel;
}

test("disabled: no row, no card, summary null", async () => {
  const panel = await prep({ enabled: false });
  assertEqual(panel._coolingMissionRow(), "");
  assertEqual(panel._coolingInsightCard(), null);
});

test("summary renders the backend verdict: percent, band pill, dew-point detail", async () => {
  const panel = await prep();
  const sum = panel._coolingSummary();
  assertEqual(sum.pct, 2);
  assertEqual(sum.pill, "warning");
  assertEqual(sum.label, "Evaporative cooling has stopped");
  assert(sum.detail.includes("dew point 25.9 °C vs tank 26.0 °C"), sum.detail);
  assert(panel._coolingMissionRow().includes("2 % fan effect"));
});

test("warning card carries the backend status; reversed is critical", async () => {
  const panel = await prep();
  assertEqual(panel._coolingInsightCard().status, "warning");
  const rev = status({ result: { ...status().result, band: "reversed", status: "critical", title: "Room air is condensing on the tank — the fan is heating it" } });
  const panel2 = await prep({ enabled: true }, rev);
  assertEqual(panel2._coolingInsightCard().status, "critical");
  assertEqual(panel2._coolingSummary().pill, "critical");
});

test("humid but cool: the same bad band is an ok card, not a warning", async () => {
  const st = status({ fanNeeded: false, warn: false });
  const panel = await prep({ enabled: true }, st);
  const card = panel._coolingInsightCard();
  assertEqual(card.status, "ok");
  assert(card.title.includes("aren't needed"), card.title);
  assert(panel._coolingMissionRow().includes("fans not needed right now"));
});

test("good day: ok card with the percent in the title", async () => {
  const st = status({ warn: false, result: { ...status().result, index: 0.96, band: "good", status: "ok", title: "Fans have full headroom" } });
  const panel = await prep({ enabled: true }, st);
  const card = panel._coolingInsightCard();
  assertEqual(card.status, "ok");
  assert(card.title.includes("96 %"), card.title);
  assertEqual(panel._coolingSummary().pill, "ok");
});

test("no reading: not reporting with the first issue, and no insight card", async () => {
  const st = status({ result: null, warn: false, fanNeeded: false, issues: { humidity: "humidity sensor (sensor.hum) is unavailable" } });
  const panel = await prep({ enabled: true }, st);
  const sum = panel._coolingSummary();
  assertEqual(sum.pct, null);
  assertEqual(sum.pill, "unknown");
  assert(sum.detail.includes("unavailable"));
  assertEqual(panel._coolingInsightCard(), null);
  assert(panel._coolingMissionRow().includes("Not reporting"));
});

test("what-if table renders the backend grid with band classes", async () => {
  const panel = await prep();
  const html = panel._coolingWhatIfTable(status());
  assert(html.includes("50 % RH") && html.includes("Room 30 °C"));
  assert(html.includes('cooling-cell reversed">0 %'));
  assert(html.includes('cooling-cell good">110 %'));
  assertEqual(panel._coolingWhatIfTable({}), "");
});

test("settings section renders fields, readout and the spawning option gated on the program", async () => {
  const panel = await prep();
  panel._settingsSectionOpen = () => true;
  panel._awcEntitySelect = (scope, _id, field, value) => `<input data-scope="${scope}" data-field="${field}" value="${value}">`;
  const html = panel._coolingSettings();
  assert(html.includes('data-field="enabled"') && html.includes('data-field="targetTempC"'));
  assert(html.includes('data-field="humidityEntity"'));
  assert(html.includes("2 % fan effect"));
  assert(html.includes("(program off)"), "spawning target disabled while the program is off");
  assert(html.includes("cooling-grid"));
});

test("status load is cached and never runs while disabled", async () => {
  const panel = await prep({ enabled: false });
  let calls = 0;
  panel._callWS = async () => { calls += 1; return status(); };
  await panel._loadCoolingStatus(true);
  assertEqual(calls, 0);
  panel._config.coolingHeadroom.enabled = true;
  await panel._loadCoolingStatus();          // fresh cache: skipped
  assertEqual(calls, 0);
  await panel._loadCoolingStatus(true);
  assertEqual(calls, 1);
});

await runTests();
