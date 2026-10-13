/** Typical-day history must load wherever a sensor trend is opened. */
import { assert, assertEqual, freezeTime, makePanel, runTests, test } from "./_panel_harness.mjs";

const NOW = "2026-10-13T12:00:00Z";
const hourly = (days = 7, hours = 24) => Array.from({ length: days * hours }, (_, i) => ({
  start: Date.parse(NOW) - (Math.floor(i / hours) * 24 + i % hours + 1) * 3600000,
  mean: 8 + Math.sin((i % hours) * Math.PI / 12) / 10,
}));

async function panelFixture() {
  const panel = await makePanel({ sensors: {
    ph: { label: "pH", enabled: true, entity_id: "sensor.tank_ph", group: "tank", kind: "numeric", unit: "" },
    co2: { label: "CO₂ Level", enabled: true, entity_id: "sensor.room_co2", group: "room", kind: "numeric", unit: "ppm" },
  } });
  panel._activeTab = "mission";
  panel._hass = { states: {} };
  panel._liveSparks = {};
  panel._liveGhosts = {};
  panel._render = () => {};
  panel._fetchTrendPoints = async () => [{ time: Date.parse(NOW) - 3600000, value: 8 }, { time: Date.parse(NOW), value: 8.1 }];
  return panel;
}

test("opening pH from Mission Control loads its typical day and CO2 without visiting Live Stats", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await panelFixture();
    const requests = [];
    panel._callWS = async (msg) => { requests.push(msg); return { [msg.statistic_ids[0]]: hourly() }; };
    await panel._loadTrend("ph", "24h");
    assertEqual(requests.map((r) => r.statistic_ids[0]).sort(), ["sensor.room_co2", "sensor.tank_ph"]);
    assert(requests.every((r) => r.type === "recorder/statistics_during_period" && r.period === "hour"), "request hourly statistics, independently of the chart range");
    assertEqual(panel._liveGhost("ph")?.length, 24);
    assertEqual(panel._liveGhost("co2")?.length, 24);
    assert(!panel._trend.loading && panel._trend.points.length === 2, "the existing chart still loads");
  } finally { restore(); }
});

test("unavailable statistics and failed requests do not masquerade as gathering more days", async () => {
  const panel = await panelFixture();
  panel._callWS = async () => ({});
  await panel._loadTrend("ph", "24h");
  let html = panel._liveDriversMarkup("ph", panel._config.sensors.ph);
  assert(html.includes("no hourly statistics") && html.includes("Recorder"), "empty statistics have an actionable explanation");
  assert(!html.includes("gathering a typical day"), "waiting longer is not presented as the cure for absent statistics");
  panel._callWS = async () => { throw new Error("not permitted"); };
  await panel._loadTrend("ph", "24h", true);
  html = panel._liveDriversMarkup("ph", panel._config.sensors.ph);
  assert(html.includes("could not load hourly statistics") && html.includes("Refresh"), "request errors stay distinct from empty data");
  assert(panel._trend.points.length === 2 && !panel._trend.error, "a statistics failure does not break the working chart");
});

test("opening a trend while Live Stats is still fetching updates the open modal when statistics arrive", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await panelFixture();
    panel._activeTab = "live";
    let releasePh;
    let startedPh;
    const phStarted = new Promise((resolve) => { startedPh = resolve; });
    const phData = new Promise((resolve) => { releasePh = resolve; });
    const requests = [];
    const paints = [];
    panel._render = () => { paints.push({ chartReady: !panel._trend?.loading, typicalReady: !!panel._liveGhost("ph") }); };
    panel._callWS = async (msg) => {
      const entity = msg.statistic_ids[0];
      requests.push(entity);
      if (entity === "sensor.tank_ph") { startedPh(); return phData; }
      return { [entity]: hourly() };
    };
    const pageLoad = panel._loadLiveSparklines();
    await phStarted;
    const modalLoad = panel._loadTrend("ph");
    await Promise.resolve();
    assert(paints.some((p) => p.chartReady && !p.typicalReady), "the chart can paint while the typical day is loading");
    releasePh({ "sensor.tank_ph": hourly() });
    await Promise.all([pageLoad, modalLoad]);
    assertEqual(requests.filter((id) => id === "sensor.tank_ph").length, 1, "page and modal share the pending pH request");
    assertEqual(requests.filter((id) => id === "sensor.room_co2").length, 1, "comparison request is also shared");
    assert(paints.at(-1).typicalReady, "the open modal repaints after history arrives without needing to close it");
  } finally { restore(); }
});

test("Refresh bypasses the hourly cache and can recover from a statistics failure", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await panelFixture();
    let calls = 0;
    let fails = true;
    panel._callWS = async (msg) => { calls++; if (fails) throw new Error("disconnected"); return { [msg.statistic_ids[0]]: hourly() }; };
    await panel._loadTrend("ph");
    assertEqual(panel._liveGhost("ph"), null);
    fails = false;
    await panel._loadTrend("ph", "6h");
    assertEqual(calls, 2, "range changes reuse a recent result instead of fetching every time");
    await panel._loadTrend("ph", "6h", true);
    assertEqual(calls, 4, "explicit refresh retries both sensors immediately");
    assertEqual(panel._liveGhost("ph")?.length, 24);
    assertEqual(panel._liveGhost("co2")?.length, 24);
  } finally { restore(); }
});

test("coverage messages distinguish genuinely short history from sparse hours across many days", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await panelFixture();
    let data = hourly(3);
    panel._callWS = async (msg) => ({ [msg.statistic_ids[0]]: data });
    await panel._loadLiveGhost("ph");
    assertEqual(panel._liveGhost("ph"), null);
    // The rolling 72 h window touches four dates, but no hour has four observations.
    assert(panel._liveGhostMessage("ph").includes("0 of 24 clock hours"), "calendar dates alone do not establish four days per hour");
    data = hourly(7, 6);
    await panel._loadLiveGhost("ph", true);
    assertEqual(panel._liveGhost("ph"), null);
    assert(panel._liveGhostMessage("ph").includes("6 of 24 clock hours"), "seven days with only six matching hours still lack coverage");
    data = hourly(2);
    await panel._loadLiveGhost("ph", true);
    assert(panel._liveGhostMessage("ph").includes("only 3 days"), "report the actual returned dates");
  } finally { restore(); }
});

test("missing CO2 statistics are not described as evidence of no relationship", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await panelFixture();
    panel._callWS = async (msg) => ({ [msg.statistic_ids[0]]: msg.statistic_ids[0] === "sensor.tank_ph" ? hourly() : [] });
    await panel._loadTrend("ph");
    const html = panel._liveDriversMarkup("ph", panel._config.sensors.ph);
    assert(html.includes("typically") && html.includes("CO₂ Level</b> · no hourly statistics"), "name the unavailable comparison source");
    assert(!html.includes("no convincing link"), "missing history cannot establish a negative result");
  } finally { restore(); }
});

test("changing the mapped entity discards an old in-flight statistics result", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await panelFixture();
    let finishOld;
    const oldData = new Promise((resolve) => { finishOld = resolve; });
    panel._callWS = async (msg) => msg.statistic_ids[0] === "sensor.tank_ph" ? oldData : { [msg.statistic_ids[0]]: hourly().map((p) => ({ ...p, mean: 9 })) };
    const oldRequest = panel._loadLiveGhost("ph");
    panel._config.sensors.ph.entity_id = "sensor.replacement_ph";
    await panel._loadLiveGhost("ph");
    finishOld({ "sensor.tank_ph": hourly() });
    await oldRequest;
    assertEqual(panel._liveGhosts.ph.entityId, "sensor.replacement_ph");
    assert(panel._liveGhost("ph").every((v) => v === 9), "old sensor must not overwrite the new baseline");
    panel._config.sensors.ph.entity_id = "sensor.third_ph";
    assertEqual(panel._liveGhost("ph"), null, "a previous entity's cached model is never reused");
  } finally { restore(); }
});

test("closing the modal during a request does not reopen it or repaint over another view", async () => {
  const panel = await panelFixture();
  let finish;
  const pending = new Promise((resolve) => { finish = resolve; });
  panel._callWS = async () => pending;
  let paints = 0;
  panel._render = () => { paints++; };
  const load = panel._loadTrend("ph");
  await Promise.resolve();
  panel._trend = null;
  panel._trendRequest = "";
  const before = paints;
  finish({});
  await load;
  assertEqual(panel._trend, null);
  assertEqual(paints, before);
});

await runTests();
