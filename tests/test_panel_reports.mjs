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

await runTests();
