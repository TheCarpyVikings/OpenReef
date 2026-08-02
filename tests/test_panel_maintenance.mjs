/**
 * Panel-side maintenance tests: the due/overdue contract shared with the backend,
 * plus the water-change chart aggregation that lives only in the panel.
 *
 * The lockstep half is the point. _maintenanceDueState (panel) and
 * _maintenance_task_state (backend) are separate implementations of one schedule;
 * the backend drives reminders with the panel closed, the panel drives the pills.
 * Both read tests/fixtures/maintenance_due_cases.json, so drifting either one fails.
 *
 * Run standalone:  node tests/test_panel_maintenance.mjs
 */

import { assert, assertEqual, fixture, freezeTime, makePanel, runTests, test } from "./_panel_harness.mjs";

const CASES = fixture("maintenance_due_cases.json");

// The panel says "not due" in three different ways (ok / unknown / snoozed); the
// backend says it by omitting the task. Compare what actually nags the user.
function nagLevel(status) {
  return status === "critical" || status === "warning" ? status : "none";
}

function configForCase(testCase) {
  return {
    maintenance: {
      enabled: testCase.maintenanceEnabled !== false,
      tasks: {
        subject: {
          label: "Subject",
          enabled: true,
          cadenceDays: 7,
          criticalAfterDays: 14,
          scheduleMode: "interval",
          ...testCase.task,
        },
      },
      completions: { subject: testCase.completions || [] },
    },
  };
}

test("test_due_state_matches_the_shared_contract", async () => {
  const restore = freezeTime(CASES.now);
  try {
    const mismatches = [];
    for (const testCase of CASES.cases) {
      const panel = await makePanel(configForCase(testCase));
      const actual = nagLevel(panel._maintenanceDueState("subject").status);
      if (actual !== testCase.expect) {
        mismatches.push(`${testCase.name}: panel says ${actual}, contract says ${testCase.expect}`);
      }
    }
    assert(!mismatches.length, `panel drifted from the shared due contract:\n    ${mismatches.join("\n    ")}`);
  } finally {
    restore();
  }
});

test("test_every_contract_case_is_exercised", async () => {
  assert(CASES.cases.length >= 15, "the shared contract should cover interval, fixed, snooze and skip cases");
  const names = new Set(CASES.cases.map((entry) => entry.name));
  assertEqual(names.size, CASES.cases.length, "duplicate case names in the contract fixture");
});

// --- chart aggregation (panel-only; no backend counterpart to drift from) ----

const TANK = 52;

function chartConfig(completions) {
  return {
    tank: { volumeLitres: TANK },
    maintenance: {
      enabled: true,
      tasks: { water_change: { label: "Water change", enabled: true, cadenceDays: 7, logsVolume: true } },
      completions: { water_change: completions },
    },
  };
}

const AT = "2026-06-04T09:00:00+00:00";   // Thursday
const iso = (daysAgo, hour = 9) =>
  new Date(Date.parse(AT) - daysAgo * 86400000).toISOString().replace(/T\d\d/, `T${String(hour).padStart(2, "0")}`);

test("test_weeks_are_zero_filled_across_the_window", async () => {
  const restore = freezeTime(AT);
  try {
    const panel = await makePanel(chartConfig([{ id: "a", timestamp: iso(1), volume: 10, volumeUnit: "L" }]));
    const weeks = panel._maintenanceWaterChangeWeeks(12);
    assertEqual(weeks.length, 12, "every week in the window must be present");
    assertEqual(weeks.filter((week) => week.count > 0).length, 1, "only the logged week has data");
    assert(weeks[weeks.length - 1].count === 1, "the newest bucket is the current week");
  } finally {
    restore();
  }
});

test("test_percent_and_litres_are_derived_from_each_other", async () => {
  const restore = freezeTime(AT);
  try {
    const panel = await makePanel(chartConfig([
      { id: "l", timestamp: iso(1), volume: 13, volumeUnit: "L" },     // 25% of 52 L
      { id: "p", timestamp: iso(2), volume: 25, volumeUnit: "pct" },   // 13 L of 52 L
    ]));
    const week = panel._maintenanceWaterChangeWeeks(12).at(-1);
    assertEqual(week.litres, 26, "both entries contribute 13 L");
    assertEqual(week.pct, 50, "both entries contribute 25%");
  } finally {
    restore();
  }
});

test("test_skipped_entries_never_reach_the_chart", async () => {
  const restore = freezeTime(AT);
  try {
    const panel = await makePanel(chartConfig([
      { id: "done", timestamp: iso(1), volume: 10, volumeUnit: "L" },
      { id: "skip", timestamp: iso(2), volume: 99, volumeUnit: "L", skipped: true },
    ]));
    const week = panel._maintenanceWaterChangeWeeks(12).at(-1);
    assertEqual(week.litres, 10, "a skip is history, not water changed");
    assertEqual(week.count, 1);
  } finally {
    restore();
  }
});

test("test_automatic_share_is_split_out_of_the_total", async () => {
  const restore = freezeTime(AT);
  try {
    const panel = await makePanel(chartConfig([
      { id: "auto", timestamp: iso(1), volume: 4, volumeUnit: "L", source: "awc" },
      { id: "hand", timestamp: iso(2), volume: 16, volumeUnit: "L" },
    ]));
    const week = panel._maintenanceWaterChangeWeeks(12).at(-1);
    assertEqual(week.litres, 20, "the total covers both sources");
    assertEqual(week.autoLitres, 4, "the automatic share is tracked separately");
    assertEqual(week.autoCount, 1);
    assertEqual(week.litres - week.autoLitres, 16, "the rest is what was logged by hand");
  } finally {
    restore();
  }
});

test("test_entries_outside_the_window_are_excluded", async () => {
  const restore = freezeTime(AT);
  try {
    const panel = await makePanel(chartConfig([
      { id: "inside", timestamp: iso(20), volume: 5, volumeUnit: "L" },
      { id: "outside", timestamp: iso(200), volume: 99, volumeUnit: "L" },
    ]));
    const weeks = panel._maintenanceWaterChangeWeeks(12);
    assertEqual(weeks.reduce((sum, week) => sum + week.litres, 0), 5, "a 12-week window must not reach back 200 days");
  } finally {
    restore();
  }
});

test("test_auto_logged_today_only_counts_todays_automatic_water", async () => {
  const restore = freezeTime(AT);
  try {
    const panel = await makePanel(chartConfig([
      { id: "auto-today", timestamp: iso(0, 2), volume: 2.5, volumeUnit: "L", source: "awc" },
      { id: "auto-today-2", timestamp: iso(0, 7), volume: 1, volumeUnit: "L", source: "awc" },
      { id: "auto-yesterday", timestamp: iso(1), volume: 9, volumeUnit: "L", source: "awc" },
      { id: "hand-today", timestamp: iso(0, 8), volume: 20, volumeUnit: "L" },
    ]));
    assertEqual(panel._maintenanceAutoLoggedToday("water_change"), 3.5,
      "the double-log hint counts only today's automatic litres");
  } finally {
    restore();
  }
});

test("test_intervals_measure_gaps_between_real_completions", async () => {
  const restore = freezeTime(AT);
  try {
    const panel = await makePanel(chartConfig([
      { id: "c", timestamp: iso(0) },
      { id: "b", timestamp: iso(7) },
      { id: "skip", timestamp: iso(10), skipped: true },
      { id: "a", timestamp: iso(15) },
    ]));
    const gaps = panel._maintenanceIntervals("water_change").map((gap) => Math.round(gap.days));
    assertEqual(gaps, [8, 7], "gaps run oldest-first and ignore skips");
  } finally {
    restore();
  }
});

test("test_chart_renders_without_holes_for_an_empty_history", async () => {
  const restore = freezeTime(AT);
  try {
    const panel = await makePanel(chartConfig([]));
    assertEqual(panel._maintenanceVolumeTasks().length, 0, "a task with no logged volume summons no chart");
    const html = panel._maintenanceTrendsSection();
    assert(!/undefined|NaN|Infinity/.test(html), "empty history must not leak placeholder values");
  } finally {
    restore();
  }
});

test("test_chart_markup_stays_well_formed_with_data", async () => {
  const restore = freezeTime(AT);
  try {
    const panel = await makePanel(chartConfig([
      { id: "auto", timestamp: iso(1), volume: 4, volumeUnit: "L", source: "awc" },
      { id: "hand", timestamp: iso(9), volume: 16, volumeUnit: "L" },
    ]));
    const html = panel._maintenanceWaterChangeCard();
    assert(!/undefined|NaN|Infinity/.test(html), "no placeholder values in the rendered chart");
    assert(html.includes("maint-bar auto"), "the automatic share is drawn in its own segment");
    assert(html.includes("maint-legend"), "a mixed window shows the legend");
    const open = (html.match(/<svg/g) || []).length;
    const close = (html.match(/<\/svg>/g) || []).length;
    assertEqual(open, close, "unbalanced <svg> tags");
  } finally {
    restore();
  }
});

test("test_history_says_so_when_the_row_cap_bites", async () => {
  const restore = freezeTime(AT);
  try {
    const many = Array.from({ length: 143 }, (_, index) => ({
      id: `e${index}`, timestamp: iso(index), volume: 1, volumeUnit: "L",
    }));
    const panel = await makePanel(chartConfig(many));
    const html = panel._renderCompletionWeeks("water_change", many);
    assert(html.includes("Showing the newest 100 of 143"),
      "a truncated history must say it is truncated, not just stop");
    assertEqual((html.match(/manual-history-row/g) || []).length, 100, "the cap is a DOM limit, not a data limit");

    const few = many.slice(0, 12);
    const short = panel._renderCompletionWeeks("water_change", few);
    assert(!short.includes("Showing the newest"), "no truncation note when nothing is truncated");
  } finally {
    restore();
  }
});

await runTests();
