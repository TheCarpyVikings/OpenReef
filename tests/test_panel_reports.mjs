/**
 * Reef Report, Stage A (0.7.197): the panel stamps the day's Reef Health into
 * the backend's score log — once per local day, refreshed every six hours,
 * never from a demo, retried after a failed call.
 *
 * Run standalone:  node tests/test_panel_reports.mjs
 */

import { assert, assertEqual, freezeTime, makePanel, runTests, test } from "./_panel_harness.mjs";

function health(score = 78) {
  return { score, categories: { chemistry: { score: 90 }, life: { score: 100 }, confidence: { score: "n/a" } } };
}

async function stampingPanel(calls, fail = false) {
  const panel = await makePanel({ reports: { weekStart: 0, scoreLog: [], events: [] } });
  panel._hass = { callWS: async (payload) => { calls.push(payload); if (fail) throw new Error("no"); return {}; } };
  panel._reportStampedDate = "";
  panel._reportStampedAt = 0;
  return panel;
}

test("test_stamps_once_per_local_day_with_rounded_parts", async () => {
  const restore = freezeTime(new Date(2026, 8, 16, 9, 0, 0).toISOString());
  try {
    const calls = [];
    const panel = await stampingPanel(calls);
    assert(panel._reportMaybeStamp(health(77.6)));
    assert(!panel._reportMaybeStamp(health(77.6)), "the second render of the day does not stamp again");
    assertEqual(calls.length, 1);
    assertEqual(calls[0].type, "openreef/report_score_stamp");
    assertEqual(calls[0].date, "2026-09-16");
    assertEqual(calls[0].total, 78);
    assertEqual(JSON.stringify(calls[0].parts), JSON.stringify({ chemistry: 90, life: 100 }), "unscored categories are left out");
  } finally {
    restore();
  }
});

test("test_refreshes_after_six_hours_and_on_a_new_day", async () => {
  const calls = [];
  let restore = freezeTime(new Date(2026, 8, 16, 9, 0, 0).toISOString());
  const panel = await stampingPanel(calls);
  panel._reportMaybeStamp(health());
  restore();
  restore = freezeTime(new Date(2026, 8, 16, 14, 0, 0).toISOString());
  assert(!panel._reportMaybeStamp(health()), "five hours on: still today's stamp");
  restore();
  restore = freezeTime(new Date(2026, 8, 16, 15, 30, 0).toISOString());
  assert(panel._reportMaybeStamp(health()), "past six hours the day's row is refreshed");
  restore();
  restore = freezeTime(new Date(2026, 8, 17, 0, 10, 0).toISOString());
  assert(panel._reportMaybeStamp(health()), "a new local day stamps again");
  assertEqual(calls.map((c) => c.date).join(","), "2026-09-16,2026-09-16,2026-09-17");
  restore();
});

test("test_a_fresh_stamp_already_on_the_ledger_counts_and_a_failed_call_retries", async () => {
  const restore = freezeTime(new Date(2026, 8, 16, 9, 0, 0).toISOString());
  try {
    const calls = [];
    const panel = await stampingPanel(calls);
    panel._config.reports.scoreLog = [{ date: "2026-09-16", at: new Date(Date.now() - 3600000).toISOString(), total: 70, parts: {} }];
    assert(!panel._reportMaybeStamp(health()), "another device stamped an hour ago");
    assertEqual(calls.length, 0);
    const failing = await stampingPanel(calls, true);
    assert(failing._reportMaybeStamp(health()));
    await new Promise((resolve) => setTimeout(resolve, 0));
    assertEqual(failing._reportStampedAt, 0, "a refused stamp is forgotten so the next render tries again");
    assert(failing._reportMaybeStamp(health()));
    assertEqual(calls.length, 2);
  } finally {
    restore();
  }
});

test("test_never_stamps_without_hass_or_from_a_demo", async () => {
  const restore = freezeTime(new Date(2026, 8, 16, 9, 0, 0).toISOString());
  try {
    const calls = [];
    const panel = await stampingPanel(calls);
    panel._nps = { demo: true };
    assert(!panel._reportMaybeStamp(health()), "a demo's score is staged, not the tank's");
    panel._nps = { demo: false };
    panel._hass = null;
    assert(!panel._reportMaybeStamp(health()));
    assert(!(await stampingPanel(calls))._reportMaybeStamp({ score: NaN }));
    assertEqual(calls.length, 0);
  } finally {
    restore();
  }
});

// --- Stage C (0.7.199): the viewer ------------------------------------------

function fixtureReport() {
  const day = (d, h = 9) => new Date(2026, 8, 7 + d, h).toISOString();
  return {
    version: 1, generatedAt: day(9), readingsSource: "recorder",
    period: { kind: "week", which: "previous", start: day(0, 0), end: day(7, 0), label: "7–13 September 2026", partial: false, days: 7, weekStart: 0 },
    headline: { score: { latest: 82, average: 80, previousAverage: 71, delta: 9, stamps: 3, gaps: 4, parts: { chemistry: 85 },
      series: [{ date: "2026-09-07", total: 78 }, { date: "2026-09-08", total: 80 }, { date: "2026-09-11", total: 82 }] },
      verdict: "6 chores ticked off, 80 % on time, water steady." },
    did: { maintenance: { done: 6, skipped: 1, onSchedule: 80, timed: 5, waterChangedL: 15.4, waterChangedPct: 30, handL: 5, autoL: 10.4, bySource: { hand: 5, awc: 1 },
      tasks: [{ id: "water", label: "Water change", done: 2, skipped: 0, late: 0, litres: 15.4, tracked: true }, { id: "sock", label: "Filter sock", done: 1, skipped: 0, late: 1, litres: null, tracked: true }, { id: "old", label: "Old chore", done: 1, skipped: 1, late: 0, litres: null, tracked: false }] },
      awc: { runs: 1, partial: 0, drainedL: 2.5, filledL: 2.5 }, tests: { count: 2, parameters: ["Alkalinity", "Calcium"] },
      feeds: { count: 14, hand: 12, pump: 2, undone: 1, available: true }, hatches: 2, cultureFeeds: 3, coralCheckins: 2 },
    water: { parameters: [
      { id: "alkalinity", label: "Alkalinity", unit: "dKH", tests: 2, sensorSamples: 0, latest: 8.0, latestAt: day(5), latestSource: "test", daysSince: 1.6, range: { min: 7.5, max: 9.5 }, inRange: true, band: "drifting", change: -0.6, low: 8.0, high: 8.7, latestIsFromPeriod: true,
        points: [{ t: day(-20), v: 8.6 }, { t: day(-13), v: 8.2 }, { t: day(-6), v: 8.7 }, { t: day(1), v: 8.3 }, { t: day(5), v: 8.0 }], consumption: { perDay: 0.08, pairs: 3 } },
      { id: "calcium", label: "Calcium", unit: "ppm", tests: 1, sensorSamples: 0, latest: 430, daysSince: 4.6, range: { min: 400, max: 450 }, inRange: true, band: "single", change: null, latestIsFromPeriod: true, points: [{ t: day(2), v: 430 }], consumption: { perDay: null, pairs: 0 } },
      { id: "salinity", label: "Salinity", unit: "ppt", tests: 0, sensorSamples: 0, latest: 35, daysSince: 47, latestSource: "sensor", disagree: { delta: -0.9, test: 35.9, sensor: 35 }, range: { min: 33, max: 36 }, inRange: true, band: "untested", change: null, latestIsFromPeriod: false, points: [] },
    ], untested: ["Salinity"], tested: ["Alkalinity", "Calcium"] },
    living: { hatches: { started: 3, harvested: 2, avgActualHours: 26, avgLateHours: 2, enriched: 1, byVessel: [{ id: "v1", name: "Hatchery 1", harvests: 1 }, { id: "v2", name: "Hatchery 2", harvests: 1 }] },
      cultures: { jars: [{ id: "j1", name: "Rotifers", feeds: 3, looks: 4, harvests: 1, skips: 0, signs: 1, restarts: 0, crashed: 0, harvestMl: 300, signList: ["foam"] }], feeds: 3, looks: 4, harvests: 1, skips: 0, signs: 1, restarts: 0, crashed: 0 },
      corals: { colonies: 2, checkins: 2, feeds: 1, grades: { A: 1, C: 1 }, moved: [{ id: "c1", name: "Acro", from: 80, to: 62 }] } },
    happened: { count: 2, byType: { warning: 1, control: 1 }, rows: [{ at: day(2), message: "Return pump off", type: "control" }, { at: day(1), message: "Alk drifting", type: "warning" }] },
    next: { count: 2, days: [{ day: "now", label: "Already due", items: [{ id: "kalk", label: "Refill kalk", dueAt: day(6, 22), status: "warning", source: null }] },
      { day: "2026-09-15", label: "Tuesday", items: [{ id: "brine_hatch_start", label: "Start hatch", dueAt: day(8, 22), status: "ok", source: "hatchery" }] }] },
    notes: ["Not tested this period: Salinity.", "Reef Health was stamped on 3 of 7 days — the panel was closed on the rest."],
  };
}

test("test_hero_card_reads_last_week_from_the_score_log", async () => {
  const restore = freezeTime(new Date(2026, 8, 16, 9, 0, 0).toISOString());   // Wednesday; last week = 7–13
  try {
    const row = (d, total) => ({ date: `2026-09-${String(d).padStart(2, "0")}`, at: "", total, parts: {} });
    const panel = await makePanel({ reports: { weekStart: 0, scoreLog: [row(12, 84), row(9, 76), row(3, 70), row(1, 74)], events: [] } });
    const card = panel._reportHeroCard();
    assert(card.includes("80/100") && card.includes("up 8 on the week before"), card);
    assert(card.includes('data-action="report-open"'));
    panel._config.reports.scoreLog = [];
    assert(panel._reportHeroCard().includes("Ready"), "no stamps yet: the card still opens the report");
    panel._config.reports.weekStart = 6;   // Sunday start: last week = 6–12, the 12th is in, the 3rd is out
    panel._config.reports.scoreLog = [row(12, 84), row(13, 60), row(5, 70)];
    assert(panel._reportHeroCard().includes("84/100") && panel._reportHeroCard().includes("up 14"), panel._reportHeroCard());
  } finally {
    restore();
  }
});

test("test_dialog_renders_every_section_and_links_rows_to_tasks", async () => {
  const panel = await makePanel({ reports: { weekStart: 0, scoreLog: [], events: [] }, captures: [
    { id: "x", timestamp: new Date(2026, 8, 9, 12).toISOString(), label: "Feed watch", cameraLabel: "Display", thumbnail: "thumbs/x.jpg" },
    { id: "y", timestamp: new Date(2026, 8, 20, 12).toISOString(), label: "Later", thumbnail: "thumbs/y.jpg" },
  ] });
  panel._report = { open: true, loading: false, error: "", data: fixtureReport(), at: Date.now(), period: "week", which: "previous" };
  const html = panel._reportDialog();
  assert(html.includes('class="wizard trend-dialog report-dialog"'), "a distinctive dialog class (scroll restore)");
  assert(html.includes("7–13 September 2026") && html.includes("80<span>/100</span>") && html.includes("up 9 on the period before"));
  assert(html.includes("6 chores ticked off, 80 % on time, water steady."));
  assert(html.includes("Stamped on 3 of 7 days — 4 days the panel stayed closed."));
  assert(html.includes('src="/openreef_captures/thumbs/x.jpg"') && !html.includes("thumbs/y.jpg"), "the photo of the week is from the week");
  for (const heading of ["What you did", "Water", "Living reef", "What happened", "Next week", "Notes"]) assert(html.includes(heading), heading);
  assert(html.includes('data-action="report-task" data-id="water"') && html.includes('data-action="report-task" data-id="brine_hatch_start"'));
  assert(html.includes("(no longer tracked)"));
  assert(html.includes("0.08 dKH/day") && html.includes("needs 2 more falling pairs"), "consumption estimate and its honesty");
  assert(html.includes(">drifting<") && html.includes(">one reading<") && html.includes(">not tested<") && html.includes(">in range<"));
  assert(html.includes("Not tested this period: Salinity."));
  assert(html.includes("your test · 2 d before the end") && html.includes("the sensor · 47 d old — not this period"), "every latest figure names where it came from");
  assert(html.includes("sensor -0.90 ppt off your test"), "the probe against the kit");
  assert((html.match(/<polyline class="report-spark-line"/g) || []).length === 2, "score line + alkalinity line; one point draws no line");
  assert(html.includes("Rotifers") && html.includes("1 sign") && html.includes("Acro: 80 → 62"));
  assert(html.includes("Return pump off") && html.includes("Already due") && html.includes("Tuesday"));
  assert(html.includes("readings from the recorder"));
  assert(html.includes('data-action="report-period" data-id="month"') && html.includes('data-action="report-which" data-id="current"'));
  panel._report.data.period.partial = true;
  assert(panel._reportDialog().includes(">in progress<"));
  panel._report = { open: true, loading: true, error: "", data: null, at: 0, period: "week", which: "previous" };
  assert(panel._reportDialog().includes("Reading the ledgers"));
  panel._report = { open: true, loading: false, error: "Could not compile the report.", data: null, at: 0, period: "week", which: "previous" };
  assert(panel._reportDialog().includes("Could not compile the report."));
});

test("test_load_hands_the_recorder_back_in_when_the_backend_read_tests_only", async () => {
  const calls = [];
  const panel = await makePanel({ reports: { weekStart: 0, scoreLog: [], events: [] },
    sensors: { alkalinity: { entity_id: "sensor.trident_alk", enabled: true }, calcium: { entity_id: "", enabled: true } } });
  panel._render = () => {};
  panel._hass = { callWS: async (payload) => { calls.push(payload); if (payload.type === "openreef/report_list") return { items: [{ id: "week:2026-09-07", kind: "week", start: "2026-09-07", label: "7–13 September 2026", weekScore: { total: 70 } }] }; return { ...fixtureReport(), readingsSource: payload.readings ? "panel" : "tests" }; } };
  panel._fetchHistoryTrendPoints = async (entityId) => [{ time: Date.parse("2026-09-10T09:00:00Z"), value: 8.3 }];
  panel._report = { open: true, loading: false, error: "", data: null, at: 0, period: "week", which: "previous" };
  await panel._reportLoad(true);
  const compiles = calls.filter((c) => c.type === "openreef/report_compile");
  assertEqual(compiles.length, 2, "compile, then compile again with the panel's readings");
  assertEqual(compiles[1].readings.alkalinity[0].v, 8.3);
  assert(!compiles[1].readings.calcium, "an unmapped sensor sends nothing");
  assertEqual(panel._report.data.readingsSource, "panel");
  assertEqual(panel._report.items.length, 1, "the stored snapshots ride along");
  assert(!panel._report.loading && !panel._report.error);
  panel._hass = { callWS: async () => { throw new Error("no backend"); } };
  await panel._reportLoad(true);
  assertEqual(panel._report.error, "no backend");
  assert(panel._report.data, "the last good report stays on screen");
});

test("test_score_card_explains_its_parts_and_recommendations_render_with_snooze", async () => {
  const panel = await makePanel({ reports: { weekStart: 0, scoreLog: [], events: [] }, captures: [] });
  const data = fixtureReport();
  data.score = { total: 66, condition: 58, consistency: 74, neutral: ["Livestock wellbeing"], parts: [
    { id: "chemistry", label: "Chemistry stability", weight: 30, side: "condition", score: 58, available: true, why: "2 parameters with a trend; Nitrate swinging.", raise: "Test Salinity." },
    { id: "care", label: "Care consistency", weight: 25, side: "consistency", score: 80, available: true, why: "80 % of chores on time.", raise: "Tick chores on their day." },
    { id: "nutrition", label: "Nutrition", weight: 15, side: "consistency", score: 70, available: true, why: "14 feeds logged; 1 culture sign.", raise: "Look at the jars daily." },
    { id: "livestock", label: "Livestock wellbeing", weight: 15, side: "condition", score: null, available: false, why: "No colonies graded yet.", raise: "Look at every colony." },
    { id: "reliability", label: "System reliability", weight: 15, side: "consistency", score: 100, available: true, why: "Nothing on the log.", raise: "Clear the warnings." },
  ] };
  data.recommendations = { calm: false, snoozed: ["late_sock"], items: [
    { id: "test_alkalinity", size: "small", title: "Test alkalinity this week", evidence: "Last test 9 days before the period's end.", effort: "5 min", effect: "A trend to read.", actions: [{ action: "tab", id: "manual", label: "Log a test" }] },
    { id: "late_kalk", size: "small", title: "Do Refill kalk on its day", evidence: "2 of 3 ticks came after the cadence.", effort: "no extra time", effect: "The on-time rate.", actions: [{ action: "report-task", id: "kalk", label: "Open the task" }] },
  ] };
  panel._report = { open: true, loading: false, error: "", data, at: Date.now(), period: "week", which: "previous", whyOpen: false };
  let html = panel._reportDialog();
  assert(html.includes("Reef Week Score") && html.includes("66<span>/100</span>") && html.includes("condition 58 · consistency 74"));
  assert(html.includes("No data for livestock wellbeing — left out, not zero."));
  assert(html.includes('data-action="report-why"') && !html.includes("2 parameters with a trend"), "the why list is folded by default");
  panel._report.whyOpen = true;
  html = panel._reportDialog();
  assert(html.includes("2 parameters with a trend; Nitrate swinging.") && html.includes("Raise it: Test Salinity.") && html.includes(">neutral<small>"));
  assert(!html.includes("Raise it: Clear the warnings."), "a full-marks part needs no raise line");
  assert(html.includes("Recommendations · small") && html.includes("1 snoozed"));
  assert(html.includes("Test alkalinity this week") && html.includes("Because:</small> Last test 9 days"));
  assert(html.includes('data-action="tab" data-id="manual"') && html.includes('data-action="report-task" data-id="kalk"'));
  assert(html.includes('data-action="report-rec-snooze" data-id="test_alkalinity" data-days="30"'));
  data.recommendations = { calm: true, snoozed: [], items: [{ id: "keep_rhythm", size: "small", title: "Keep the rhythm", evidence: "Nothing in this period asked for a change.", effort: "none", effect: "The reef likes it this way.", actions: [] }] };
  html = panel._reportDialog();
  assert(html.includes("This week") && html.includes("Keep the rhythm") && !html.includes("report-rec-snooze"), "a calm week has nothing to snooze");
  const calls = [];
  panel._hass = { callWS: async (payload) => { calls.push(payload); return payload.type === "openreef/report_compile" ? data : { snoozedRecs: {} }; } };
  panel._render = () => {};
  await panel._reportSnoozeRec("test_alkalinity", 30);
  assertEqual(calls[0].type, "openreef/report_rec_snooze");
  assertEqual(calls[0].rec_id, "test_alkalinity");
  assertEqual(calls[1].type, "openreef/report_compile", "and the report reloads");
});

test("test_settings_card_timeline_anchor_and_store", async () => {
  const panel = await makePanel({ reports: { weekStart: 6, scoreLog: [], events: [], schedule: { enabled: true, time: "06:30", push: false }, items: [] }, captures: [] });
  const card = panel._reportSettingsCard();
  assert(card.includes('data-scope="reports" data-field="weekStart"') && card.includes('<option value="6" selected>Sunday'));
  assert(card.includes('data-scope="reports-schedule" data-field="time" value="06:30"'));
  assert(card.includes('data-field="push" >') || card.includes('data-field="push" checked') === false, "push off renders unchecked");
  const data = fixtureReport();
  panel._report = { open: true, loading: false, error: "", data, at: Date.now(), period: "week", which: "previous", anchor: "", items: [
    { id: "week:2026-09-07", kind: "week", start: "2026-09-07", label: "7–13 September 2026", generatedAt: "2026-09-14T07:00:00Z", verdict: "A steady week.", weekScore: { total: 70 } },
    { id: "week:2026-08-31", kind: "week", start: "2026-08-31", label: "31 Aug – 6 Sep 2026", generatedAt: "2026-09-07T07:00:00Z", verdict: "Slipping.", weekScore: { total: 55 } },
    { id: "month:2026-08-01", kind: "month", start: "2026-08-01", label: "August 2026", generatedAt: "2026-09-01T07:00:00Z", verdict: "", weekScore: { total: 61 } },
  ] };
  let html = panel._reportDialog();
  assert(html.includes("Past weeks") && html.includes("2 stored"), "only this kind's snapshots");
  assert(html.includes('data-action="report-anchor" data-id="2026-08-31" data-kind="week"') && html.includes(">55<"));
  assert(html.includes('class="maint-row open"'), "the viewed week is highlighted");
  assert(html.includes("this week stored") && !html.includes('data-action="report-store"'), "a stored week needs no store button");
  assert((html.match(/report-spark-line/g) || []).length >= 3, "the scores across weeks draw a line");
  data.period.start = "2026-09-14T00:00:00Z"; data.stored = null;
  html = panel._reportDialog();
  assert(html.includes('data-action="report-store"'), "an unstored complete week offers Store");
  data.period.partial = true;
  assert(!panel._reportDialog().includes('data-action="report-store"'), "never store a period in progress");
  data.happened.rows[0].count = 397;
  assert(panel._reportDialog().includes("×397"));
  const calls = [];
  panel._render = () => {};
  panel._hass = { callWS: async (payload) => { calls.push(payload); return payload.type === "openreef/report_list" ? { items: [] } : data; } };
  await panel._reportStoreNow();
  assertEqual(calls[0].type, "openreef/report_generate");
  assertEqual(calls[0].which, "previous");
});

test("test_month_dialog_renders_the_monthly_sections", async () => {
  const panel = await makePanel({ reports: { weekStart: 0, scoreLog: [], events: [], items: [] }, captures: [
    { id: "a", timestamp: new Date(2026, 7, 2, 12).toISOString(), label: "Early", thumbnail: "thumbs/a.jpg" },
    { id: "b", timestamp: new Date(2026, 7, 16, 12).toISOString(), label: "Mid", thumbnail: "thumbs/b.jpg" },
    { id: "c", timestamp: new Date(2026, 7, 30, 12).toISOString(), label: "Late", thumbnail: "thumbs/c.jpg" },
  ] });
  const data = fixtureReport();
  data.period = { kind: "month", which: "previous", start: "2026-08-01T00:00:00+00:00", end: "2026-09-01T00:00:00+00:00", label: "August 2026", partial: false, days: 31, weekStart: 0 };
  data.living.corals.added = [{ id: "c3", name: "Goniopora" }];
  data.recommendations = { size: "big", calm: false, snoozed: [], raised: ["salt_stock", "water_plan"], items: [
    { id: "salt_stock", size: "big", title: "Order salt", evidence: "About 5.5 weeks of salt left. Third month running.", effort: "5 min", effect: "No batch waits.", promoted: true, actions: [{ action: "tab", id: "mixing", label: "Open the mixing station" }] },
    { id: "water_plan", size: "big", title: "Raise the AWC volume or lower its plan — pick one", evidence: "40 L changed against 62 L planned.", effort: "5 min", effect: "A plan the tank actually gets.", actions: [{ action: "tab", id: "awc", label: "Open AWC" }] },
  ] };
  data.month = {
    trend: { previous: "July 2026", deltas: { total: 6, condition: 3, consistency: 8, health: null },
      months: [{ id: "month:2026-06-01", label: "June 2026", start: "2026-06-01", total: 58, condition: 50, consistency: 64, health: 80 }, { id: "month:2026-07-01", label: "July 2026", start: "2026-07-01", total: 60, condition: 55, consistency: 66, health: 82 }, { id: "month:2026-08-01", label: "August 2026", start: "2026-08-01", total: 66, condition: 58, consistency: 74, health: null, current: true }],
      weeks: [{ start: "2026-08-03", label: "3–9 August 2026", total: 70 }, { start: "2026-08-10", label: "10–16 August 2026", total: 72 }] },
    drift: { late: [{ id: "sock", label: "Filter sock", done: 4, timed: 3, late: 2, skipped: 0, lateShare: 67, slipDays: 3 }], held: [{ id: "water", label: "Water change", done: 4 }] },
    consumption: { parameters: [{ id: "alkalinity", label: "Alkalinity", unit: "dKH", months: [{ label: "Jun", perDay: 0.1, pairs: 2, readings: 4 }, { label: "Jul", perDay: 0.15, pairs: 2, readings: 4 }, { label: "Aug", perDay: 0.2, pairs: 2, readings: 4 }], changePct: 100, direction: "rising" },
      { id: "calcium", label: "Calcium", unit: "ppm", months: [{ label: "Jun", perDay: null, pairs: 0, readings: 0 }, { label: "Jul", perDay: null, pairs: 1, readings: 2 }, { label: "Aug", perDay: null, pairs: 0, readings: 0 }], changePct: null, direction: "unknown" }] },
    water: { changedL: 40, handL: 40, autoL: 0, pctOfTank: 77, awcRuns: 0, plannedL: 62, met: false, shortfallL: 22, usualL: 44.3, salt: { tracked: true, usedKg: 2.5, onHandKg: 3.2, weeksLeft: 5.5, low: false } },
    testing: { scheduled: 2, overallRatio: 50, tests: 5, expected: 6, bestDay: "Saturday", bestDayShare: 40, parameters: [{ id: "calcium", label: "Calcium", cadenceDays: 14, expected: 2, tests: 0, ratio: 0, longestGapDays: 31, onCadence: false }, { id: "alkalinity", label: "Alkalinity", cadenceDays: 7, expected: 4, tests: 4, ratio: 100, longestGapDays: 24, onCadence: false }] },
    icp: { any: true, inPeriod: true, daysSinceLast: 20, latest: { id: "b", lab: "Triton", date: "2026-08-12", elements: 3, flaggedCount: 1, flagged: [{ symbol: "Ca", name: "Calcium", value: 450, unit: "ppm", status: "high" }] }, previous: { id: "a", lab: "Triton", date: "2026-07-10", elements: 3, flaggedCount: 0, flagged: [] },
      movers: [{ symbol: "I", name: "Iodine", from: 60, to: 40, unit: "ppb", pct: -33, statusFrom: "ok", statusTo: "ok" }, { symbol: "Ca", name: "Calcium", from: 420, to: 450, unit: "ppm", pct: 7, statusFrom: "ok", statusTo: "high" }] },
    ageing: { items: [{ id: "replace_carbon", label: "Replace carbon", kind: "consumable", cadenceDays: 30, lastAt: "2026-06-20T09:00:00+00:00", ageDays: 73, ratio: 2.43, status: "overdue" }, { id: "calibrate_ph", label: "Calibrate pH probe", kind: "calibration", cadenceDays: 30, lastAt: null, ageDays: null, ratio: null, status: "never" }],
      filters: [{ id: "sed", label: "Sediment", usedPct: 105, litres: 2100, ageDays: 184, status: "overdue" }] },
    goals: { from: "July 2026", cleared: 1, open: 2, items: [{ id: "water_plan", title: "Raise the AWC volume or lower its plan — pick one", status: "open" }, { id: "test_alkalinity", title: "Test alkalinity this week", status: "cleared" }] },
  };
  panel._report = { open: true, loading: false, error: "", data, at: Date.now(), period: "month", which: "previous", items: [] };
  const html = panel._reportDialog();
  for (const heading of ["Last month's plan", "Score over months", "Cadence drift", "Consumption trend", "Water ledger", "Testing discipline", ">ICP<", "Equipment ageing", "The next two weeks", "Recommendations · big"]) assert(html.includes(heading), heading);
  assert(html.includes("third month running") && html.includes('class="report-card report-rec promoted"'), "the promoted recommendation says so");
  assert(html.includes("July 2026 recommended 2") && html.includes(">still open<") && html.includes(">cleared<"));
  assert(html.includes("up 6 on July 2026") && html.includes("up 8 on July 2026") && html.includes("2 stored months before this one"));
  assert((html.match(/report-spark-line/g) || []).length >= 3, "score by month, the weeks inside it, and alkalinity");
  assert(html.includes('data-action="report-task" data-id="sock"') && html.includes("2 of 3") && html.includes("3.0 d on average") && html.includes("Water change · 4"));
  assert(html.includes(">rising<") && html.includes("+100 %") && html.includes("1 falling pair") && html.includes(">not enough tests<"));
  assert(html.includes("62.0 L planned · 22.0 L short") && html.includes("2.50 kg") && html.includes("≈6 weeks at your rate"));
  assert(html.includes("0 of 2") && html.includes(">slipped<") && html.includes("Your tests land on a Saturday (40 % of them)"));
  assert(html.includes("Triton") && html.includes("1 flagged") && html.includes("against Triton · 2026-07-10") && html.includes("Iodine") && html.includes("-33 %") && html.includes("+7 %"));
  assert(html.includes('data-action="report-task" data-id="replace_carbon"') && html.includes("73 d") && html.includes(">overdue<") && html.includes(">never logged<") && html.includes("Sediment · 105 %"));
  assert(html.includes("New this period: Goniopora"));
  assert(html.includes("First of the month") && html.includes("Last of the month") && html.includes("thumbs/a.jpg") && html.includes("thumbs/c.jpg") && !html.includes("thumbs/b.jpg"), "first and last capture of the month");
  data.month.icp = { any: true, inPeriod: false, daysSinceLast: 140, latest: { lab: "ATI", date: "2026-04-14" }, previous: null, movers: [] };
  data.month.goals = { from: null, items: [], cleared: 0, open: 0 };
  data.recommendations = { size: "big", calm: true, snoozed: [], raised: [], items: [{ id: "keep_rhythm", size: "big", title: "Keep the rhythm", evidence: "Nothing in this month asked for a change.", effort: "none", effect: "The reef likes it this way.", actions: [] }] };
  const calm = panel._reportDialog();
  assert(calm.includes("No ICP this month — the last (ATI, 2026-04-14) was 140 days before the month's end."));
  assert(calm.includes("The first stored month gives the next one something to check against.") && calm.includes(">This month<"));
  // The panel's own recorder read reaches back three months for a month.
  const spans = [];
  panel._config.sensors = { alkalinity: { entity_id: "sensor.alk", enabled: true } };
  panel._fetchHistoryTrendPoints = async (entityId, start, end) => { spans.push(Math.round((end - start) / 86400000)); return [{ time: Date.parse("2026-08-10T09:00:00Z"), value: 8.3 }]; };
  await panel._reportPanelReadings({ period: { kind: "month", end: "2026-09-01T00:00:00Z" } });
  await panel._reportPanelReadings({ period: { kind: "week", end: "2026-09-01T00:00:00Z" } });
  assertEqual(spans.join(","), "92,28");
});

await runTests();
