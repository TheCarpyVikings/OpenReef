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


// --- Layer 2: the projection, the plan, the dehumidifier controls -----------

function l2(over = {}) {
  const at = (h) => new Date(Date.UTC(2026, 6, 14, 12 + h)).toISOString();
  const hours = [0, 1, 2, 3, 4, 5].map((h) => ({
    at: at(h), outC: h < 4 ? 20 : 27, outDewC: h < 4 ? 12 : 21, roomC: h < 4 ? 23 : 30, rh: h < 4 ? 55 : 74,
    dewC: h < 4 ? 14 : 25, index: h < 4 ? 0.9 : 0.12, band: h < 4 ? "good" : "dead",
    fanNeeded: h >= 2, affected: h >= 4, unrescuable: false,
  }));
  return status({
    warn: false, fanNeeded: false,
    result: { ...status().result, index: 0.9, band: "good", status: "ok", title: "Fans have full headroom" },
    weather: { entity: "weather.home", outC: 20, outRh: 60, outDewC: 12, available: true },
    offsets: { offsetT: 3, offsetDew: 2 },
    projection: { hours, worst: { at: at(4), index: 0.12, band: "dead" }, firstAffectedAt: at(4), lastAffectedAt: at(5),
      affectedHours: 2, neededHours: 4, dayKind: "humid-heat", dayKindLabel: "Humid-heat day — dehumidify ahead of the afternoon",
      purgeWindow: { from: at(0), to: at(1), outC: 20 }, offsets: { offsetT: 3, offsetDew: 2 } },
    vent: { advised: true, known: true, reason: "outdoor dew point 12.0 °C is 5.6 °C below indoors — vent (intake fan + window) instead of dehumidifying", outdoorC: 20, outdoorDewC: 12, gapC: 5.6 },
    plan: { shouldRun: false, kind: "scheduled", startAt: at(1), until: at(6), reason: "start by 13:00 — headroom drops to 12 % from 16:00" },
    dehumidifier: { mode: "advise", armed: false, switchEntity: "switch.dehum", controlling: false, state: "off" },
    ...over,
  });
}

test("scheduled plan: ok card names the start time; row carries the drop", async () => {
  const panel = await prep({ enabled: true, weatherEntity: "weather.home", dehumidifier: { mode: "advise", switchEntity: "switch.dehum" } }, l2());
  const sum = panel._coolingSummary();
  assertEqual(sum.dayKind, "humid-heat");
  assertEqual(sum.worstPct, 12);
  assertEqual(sum.planActive, false);
  const card = panel._coolingInsightCard();
  assertEqual(card.status, "ok");
  assert(card.title.startsWith("Humid-heat day — dehumidifier by "), card.title);
  assert(panel._coolingMissionRow().includes("drops to 12 % from"));
});

test("active plan: warning card; vent advice takes the title when outdoor air is drier", async () => {
  const st = l2({ plan: { shouldRun: true, kind: "ahead", startAt: "x", until: "y", reason: "fan headroom drops to 12 % from 16:00" } });
  const panel = await prep({ enabled: true, weatherEntity: "weather.home" }, st);
  const card = panel._coolingInsightCard();
  assertEqual(card.status, "warning");
  assertEqual(card.title, "Vent the room now");
  const noVent = l2({ plan: st.plan, vent: { advised: false, known: true, reason: "outdoor air is as wet as indoors" } });
  const panel2 = await prep({ enabled: true, weatherEntity: "weather.home" }, noVent);
  assertEqual(panel2._coolingInsightCard().title, "Dehumidify now");
  assert(panel2._coolingMissionRow().includes("Dehumidify now"));
});

test("chiller day is a critical card", async () => {
  const st = l2({ plan: { shouldRun: false, kind: "unrescuable", startAt: null, until: null, reason: "room 31.0 °C at 85 % — a dehumidifier cannot rescue this afternoon; this is a chiller day" } });
  const panel = await prep({ enabled: true, weatherEntity: "weather.home" }, st);
  const card = panel._coolingInsightCard();
  assertEqual(card.status, "critical");
  assertEqual(card.title, "Chiller day");
});

test("forecast strip renders every hour with band, idle and affected markers", async () => {
  const panel = await prep({ enabled: true, weatherEntity: "weather.home" }, l2());
  const html = panel._coolingForecastStrip(l2());
  assertEqual((html.match(/class="cooling-hour /g) || []).length, 6);
  assertEqual((html.match(/affected/g) || []).length, 2);
  assertEqual((html.match(/ idle/g) || []).length, 2);
  assert(html.includes("Humid-heat day"));
  assert(html.includes("night-purge window"));
  assertEqual(panel._coolingForecastStrip(status()), "");
});

test("layer 2 settings render the weather/dehumidifier fields, the plan, vent and controls", async () => {
  const cfg = { enabled: true, weatherEntity: "weather.home", dehumidifier: { mode: "auto", armed: true, switchEntity: "switch.dehum" } };
  const st = l2({ dehumidifier: { mode: "auto", armed: true, switchEntity: "switch.dehum", controlling: true, state: "on", override: { state: "off", since: "2026-07-14T12:00:00Z" } } });
  const panel = await prep(cfg, st);
  panel._settingsSectionOpen = () => true;
  panel._awcEntitySelect = (scope, _id, field, value) => `<input data-scope="${scope}" data-field="${field}" value="${value}">`;
  const html = panel._coolingSettings();
  assert(html.includes('data-field="weatherEntity"') && html.includes('data-scope="cooling-dehum" data-field="mode"'));
  assert(html.includes('data-field="armed"'), "armed toggle appears in auto mode");
  assert(html.includes("OpenReef is driving the plug"));
  assert(html.includes("Give it back to the plan"), "resume button while held");
  assert(html.includes("<strong>Vent:</strong>") && html.includes("<strong>Plan:</strong>"));
  assert(html.includes("cooling-strip"));
  const advise = await prep({ enabled: true, dehumidifier: { mode: "advise" } }, l2());
  advise._settingsSectionOpen = () => true;
  advise._awcEntitySelect = () => "";
  assert(!advise._coolingSettings().includes('data-field="armed"'), "no armed toggle outside auto");
});


// --- Layer 3: the intake fan ------------------------------------------------

function l3(decision, over = {}) {
  return l2({
    ventDecision: decision,
    ventFan: { mode: "auto", armed: true, switchEntity: "switch.vent", controlling: true, state: "off" },
    window: { entity: "binary_sensor.window", open: true },
    ventActive: false,
    ...over,
  });
}

test("blocked by a closed window: warning card and row say open the window", async () => {
  const st = l3({ shouldRun: false, kind: "blocked", wants: "cool", reason: "the room needs cooling and outdoor air is drier — but the window is closed" },
    { window: { entity: "binary_sensor.window", open: false } });
  const panel = await prep({ enabled: true }, st);
  const card = panel._coolingInsightCard();
  assertEqual(card.status, "warning");
  assert(card.title.startsWith("Open the window"), card.title);
  assert(panel._coolingMissionRow().includes("Open the window"));
});

test("night purge: running vs advised wording follows who is driving the fan", async () => {
  const purge = { shouldRun: true, kind: "purge", wants: "purge", reason: "night purge — the coolest outdoor air (12.0 °C) until 06:00, ahead of a dry-heat day" };
  const running = await prep({ enabled: true }, l3(purge, { ventFan: { mode: "auto", armed: true, switchEntity: "switch.vent", controlling: true, state: "on" } }));
  assertEqual(running._coolingInsightCard().title, "Night purge running");
  assertEqual(running._coolingInsightCard().status, "ok");
  const advised = await prep({ enabled: true }, l3(purge, { ventFan: { mode: "advise", armed: false, switchEntity: "", controlling: false, state: null } }));
  assertEqual(advised._coolingInsightCard().title, "Night purge — run the intake fan");
  assert(advised._coolingMissionRow().includes("Night purge — run the intake fan"));
});

test("vent wins over the dehumidifier plan on every surface", async () => {
  const cool = { shouldRun: true, kind: "cool", wants: "cool", reason: "the room needs cooling and outdoor air is drier (18.0 °C, dew point 10.0 °C, 8.0 °C below indoors)" };
  const st = l3(cool, { fanNeeded: true, plan: { shouldRun: false, kind: "vented", startAt: null, until: null, reason: "venting instead — outdoor air is drier than indoors, so the dehumidifier stays off" } });
  const panel = await prep({ enabled: true }, st);
  const sum = panel._coolingSummary();
  assertEqual(sum.ventRunning, true);
  assertEqual(sum.planActive, false);
  assertEqual(panel._coolingInsightCard().title, "Vent the room now");
  assertEqual(panel._coolingInsightCard().status, "warning");
  assert(panel._coolingPlanLine(sum).startsWith("Dehumidifier off — venting instead"));
  assert(panel._coolingMissionRow().includes("Vent the room:"));
});

test("layer 3 settings render the vent fields, window state and controls", async () => {
  const cfg = { enabled: true, weatherEntity: "weather.home", vent: { mode: "auto", armed: true, switchEntity: "switch.vent", windowEntity: "binary_sensor.window", nightPurge: true } };
  const st = l3({ shouldRun: false, kind: "none", wants: null, reason: "outdoor air is as wet as indoors (dew point 19.0 °C) — keep the windows shut" },
    { ventFan: { mode: "auto", armed: true, switchEntity: "switch.vent", controlling: true, state: "off", override: { state: "on", since: "2026-07-14T12:00:00Z" } }, window: { entity: "binary_sensor.window", open: false } });
  const panel = await prep(cfg, st);
  panel._settingsSectionOpen = () => true;
  panel._awcEntitySelect = (scope, _id, field, value) => `<input data-scope="${scope}" data-field="${field}" value="${value}">`;
  const html = panel._coolingSettings();
  assert(html.includes('data-scope="cooling-vent" data-field="mode"') && html.includes('data-field="windowEntity"'));
  assert(html.includes('data-field="nightPurge"') && html.includes('data-scope="cooling-vent" data-field="armed"'));
  assert(html.includes("window closed"));
  assert(html.includes("keep the windows shut"));
  assert(html.includes('data-action="cooling-vent" data-id="resume"'), "resume while held");
  const off = await prep({ enabled: true, vent: { mode: "off" } }, l3({ shouldRun: false, kind: "none", reason: "" }));
  off._settingsSectionOpen = () => true;
  off._awcEntitySelect = () => "";
  assert(!off._coolingSettings().includes('data-scope="cooling-vent" data-field="armed"'));
});

await runTests();
