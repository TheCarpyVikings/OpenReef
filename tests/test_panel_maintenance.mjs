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

test("test_hour_clock_tasks_speak_hours", async () => {
  const restore = freezeTime(CASES.now);
  try {
    const panel = await makePanel(configForCase({
      task: { cadenceHours: 36, criticalAfterHours: 48 },
      completions: [{ timestamp: "2026-06-03T03:00:00+00:00" }], // 30 h ago
    }));
    const state = panel._maintenanceDueState("subject");
    assertEqual(state.status, "ok", state.detail);
    assert(state.detail.includes("30 h ago") && state.detail.includes("every 36 h"),
      `hour tasks must report in hours, not days: ${state.detail}`);
    // The next-due clock runs on hours too: due 36 h after the completion.
    const nextMs = panel._maintenanceNextDueMs("subject");
    const expected = Date.parse("2026-06-03T03:00:00+00:00") + 36 * 3600000;
    assertEqual(nextMs, expected, "next-due should be completion + cadenceHours");
  } finally {
    restore();
  }
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

// --- V3 slice (2026-09-05): notes on the card, the push-target copy, the streak ---

test("test_task_notes_are_the_how_line_on_the_card", async () => {
  const restore = freezeTime(CASES.now);
  try {
    const panel = await makePanel(configForCase({
      task: { notes: "Rinse in tank water, never tap." },
      completions: [{ timestamp: new Date(Date.parse(CASES.now) - 2 * 86400000).toISOString() }],
    }));
    const card = panel._maintenanceTaskCard("subject");
    assert(card.includes('<p class="hint maintenance-notes">Rinse in tank water, never tap.</p>'), `the notes must show on the card: ${card.slice(0, 900)}`);
    const bare = await makePanel(configForCase({}));
    assert(!bare._maintenanceTaskCard("subject").includes("maintenance-notes"), "no notes, no line");
    // The push target says what it accepts.
    const settings = panel._maintenanceSettings(true);
    assert(settings.includes("Push target — any notify service") && settings.includes('placeholder="mobile_app_pixel, or a notify group"'), "the target field must say any notify service works");
    assert(settings.includes("a phone, a notify group, Telegram"), "and name the kinds of target");
  } finally {
    restore();
  }
});

test("test_the_streak_counts_consecutive_on_schedule_intervals", async () => {
  const restore = freezeTime(CASES.now);
  try {
    const day = (n) => new Date(Date.parse(CASES.now) - n * 86400000).toISOString();
    const stamps = (days) => days.map((n) => ({ timestamp: day(n) }));
    // Oldest→newest gaps: 7, 7, 7 (on time), 9 (late), 7, 7 (on time) → run 2, best 3.
    const panel = await makePanel(configForCase({ completions: stamps([44, 37, 30, 23, 14, 7, 0]) }));
    const streak = panel._maintenanceStreak("subject", panel._maintenanceTask("subject"));
    assertEqual(streak.current, 2, "the current run stops at the late gap");
    assertEqual(streak.best, 3, "the best run is remembered");
    assertEqual(streak.total, 6, "six intervals between seven completions");
    const html = panel._maintenanceCadenceCard();
    assert(html.includes('<small class="maint-streak">On schedule 2 in a row · best run 3</small>'), `the cadence card carries the streak: ${html.slice(html.indexOf("maint-streak") - 40, html.indexOf("maint-streak") + 120)}`);
    // A late latest interval resets the run and says so, keeping the best.
    const late = await makePanel(configForCase({ completions: stamps([30, 23, 16, 0]) }));   // gaps 7, 7, 16
    assert(late._maintenanceCadenceCard().includes("Last one ran late — the streak restarts with the next on-time completion · best run 2"), late._maintenanceCadenceCard());
    // The whole record on schedule is "your best run" from three up, and one interval says so plainly.
    const perfect = await makePanel(configForCase({ completions: stamps([21, 14, 7, 0]) }));
    assert(perfect._maintenanceCadenceCard().includes("On schedule 3 in a row — your best run"));
    const one = await makePanel(configForCase({ completions: stamps([7, 0]) }));
    assert(one._maintenanceCadenceCard().includes(">On schedule 1 in a row</small>"));
    // Half a day of grace on a day clock: 7.3 days is on schedule, 7.6 is not.
    const grace = await makePanel(configForCase({ completions: stamps([7.3, 0]) }));
    assertEqual(grace._maintenanceStreak("subject", grace._maintenanceTask("subject")).current, 1);
    const over = await makePanel(configForCase({ completions: stamps([7.6, 0]) }));
    assertEqual(over._maintenanceStreak("subject", over._maintenanceTask("subject")).current, 0);
    // Skipped entries make no interval: they neither extend nor break the run.
    const skipped = await makePanel(configForCase({ completions: [...stamps([14, 7]), { timestamp: day(3), skipped: true }, ...stamps([0])] }));
    assertEqual(skipped._maintenanceStreak("subject", skipped._maintenanceTask("subject")).current, 2);
    // Nothing logged twice: no streak line at all.
    const none = await makePanel(configForCase({ completions: stamps([0]) }));
    assertEqual(none._maintenanceStreakLabel(none._maintenanceStreak("subject", none._maintenanceTask("subject"))), "");
  } finally {
    restore();
  }
});

// --- V3 (2026-09-05): the checklist and the new-water record ------------------------

test("test_the_checklist_ticks_for_the_visit_and_the_usual_steps_are_one_tap_away", async () => {
  const restore = freezeTime(CASES.now);
  try {
    const panel = await makePanel(configForCase({ task: { steps: ["Return pump off", "Siphon", "Refill"] } }));
    panel._render = () => {};
    panel._setDirty = () => {};
    const card = panel._maintenanceTaskCard("subject");
    assert(card.includes('<ul class="maintenance-steps"') && (card.match(/data-action="maintenance-step"/g) || []).length === 3, "three steps, three boxes");
    assert(card.includes("0 of 3 ticked"), "the tally starts at nothing");
    panel._toggleMaintenanceStep("subject", 1);
    const ticked = panel._maintenanceTaskCard("subject");
    assert(ticked.includes('data-index="1" checked') && ticked.includes('<span class="done">Siphon</span>') && ticked.includes("1 of 3 ticked"), ticked);
    panel._toggleMaintenanceStep("subject", 1);
    assert(panel._maintenanceTaskCard("subject").includes("0 of 3 ticked"), "a second tap unticks");
    // No steps: no list, no tally.
    const bare = await makePanel(configForCase({}));
    assert(!bare._maintenanceTaskCard("subject").includes("maintenance-steps"));
    // Settings: one step per line, and the usual steps for a suggested chore.
    const settings = panel._maintenanceSettings(true);
    assert(settings.includes('data-field="stepsText"') && settings.includes("Return pump off\nSiphon\nRefill</textarea>"), "the textarea round-trips the lines");
    const wc = await makePanel({ maintenance: { enabled: true, tasks: { water_change: { label: "Water change", enabled: true, cadenceDays: 7, criticalAfterDays: 14, scheduleMode: "interval", builtin: true } }, completions: {} } });
    wc._render = () => {};
    wc._setDirty = () => {};
    assert(wc._maintenanceSettings(true).includes('data-action="maintenance-usual-steps" data-id="water_change"'), "a suggested chore without steps offers the usual ones");
    wc._maintenanceUsualSteps("water_change");
    const steps = wc._config.maintenance.tasks.water_change.steps;
    assert(Array.isArray(steps) && steps.length === 5 && steps[0] === "Return pump and skimmer off", JSON.stringify(steps));
    assert(!wc._maintenanceSettings(true).includes('data-action="maintenance-usual-steps"'), "once taken, the offer goes");
    wc._maintenanceUsualSteps("no_such_task");
  } finally {
    restore();
  }
});

test("test_the_new_water_record_has_its_inputs_and_shows_in_history", async () => {
  const restore = freezeTime(CASES.now);
  try {
    const stamp = new Date(Date.parse(CASES.now) - 86400000).toISOString();
    const panel = await makePanel(configForCase({
      task: { logsVolume: true },
      completions: [{ id: "a", timestamp: stamp, volume: 20, volumeUnit: "L", newWater: { ppt: 35.2, tempC: 25.3, brand: "NYOS Pure" } },
                    { id: "b", timestamp: new Date(Date.parse(stamp) - 86400000).toISOString(), volume: 10, volumeUnit: "L" }],
    }));
    const card = panel._maintenanceTaskCard("subject");
    assert(card.includes('data-maint-draft="ppt"') && card.includes('data-maint-draft="tempC"'), "a volume-logging task takes the new water's ppt and °C");
    const plain = await makePanel(configForCase({}));
    assert(!plain._maintenanceTaskCard("subject").includes('data-maint-draft="ppt"'), "other tasks do not");
    const history = panel._renderCompletionWeeks("subject", panel._maintenanceCompletions("subject"));
    assert(history.includes("New water: 35.2 ppt · 25.3 °C · NYOS Pure"), history);
    assert((history.match(/New water:/g) || []).length === 1, "only the stamped row says so");
    assertEqual(panel._maintenanceNewWaterText({ ppt: 35 }), "35 ppt");
    assertEqual(panel._maintenanceNewWaterText(null), "");
  } finally {
    restore();
  }
});

await runTests();
