/**
 * The Log tab (0.7.109): date-range bucketing, type folding/grouping, the
 * paged view state, and the rendered tab's filter + show-more behaviour.
 *
 * Run standalone:  node tests/test_panel_log.mjs
 */

import {
  makePanel, freezeTime, assert, assertEqual, test, runTests,
} from "./_panel_harness.mjs";

// Frozen mid-afternoon so "today/yesterday" boundaries are unambiguous in UTC.
const NOW = "2026-09-01T15:00:00Z";

const entry = (iso, message, type) => ({ timestamp: iso, message, type });

function feed() {
  return [
    entry("2026-09-01T14:00:00Z", "Hand-fed brine", "control"),
    entry("2026-09-01T00:30:00Z", "Heartbeat OK", "info"),
    entry("2026-08-31T23:50:00Z", "ATO turned off", "control"),
    entry("2026-08-28T10:00:00Z", "Leak warning", "warning"),
    entry("2026-08-10T10:00:00Z", "AWC finished", "control"),
    entry("2026-07-01T10:00:00Z", "Ancient event", "info"),
  ];
}

test("date buckets are calendar-local, not 24h windows", async () => {
  const panel = await makePanel({});
  const restore = freezeTime(NOW);
  try {
    assertEqual(panel._logDateBucket("2026-09-01T00:30:00Z"), "Today");
    // 15h ago but across midnight — must NOT read as Today.
    assertEqual(panel._logDateBucket("2026-08-31T23:50:00Z"), "Yesterday");
    assertEqual(panel._logDateBucket("2026-08-28T10:00:00Z"), "This week");
    assertEqual(panel._logDateBucket("2026-08-10T10:00:00Z"), "This month");
    assertEqual(panel._logDateBucket("2026-07-01T10:00:00Z"), "Older");
    assertEqual(panel._logDateBucket("garbage"), "Undated");
  } finally {
    restore();
  }
});

test("unknown entry types fold to info so nothing vanishes", async () => {
  const panel = await makePanel({});
  assertEqual(panel._logEntryType({ type: "control" }), "control");
  assertEqual(panel._logEntryType({ type: "warning" }), "warning");
  assertEqual(panel._logEntryType({ type: "critical-junk" }), "info");
  assertEqual(panel._logEntryType({}), "info");
});

test("date grouping keeps newest-first order inside ordered buckets", async () => {
  const panel = await makePanel({});
  const restore = freezeTime(NOW);
  try {
    const groups = panel._logGroups(feed(), "date");
    assertEqual(groups.map((g) => g.label),
      ["Today", "Yesterday", "This week", "This month", "Older"]);
    assertEqual(groups[0].items.map((i) => i.message),
      ["Hand-fed brine", "Heartbeat OK"]);
  } finally {
    restore();
  }
});

test("type grouping puts warnings first and folds junk into System", async () => {
  const panel = await makePanel({});
  const groups = panel._logGroups(feed(), "type");
  assertEqual(groups.map((g) => g.label), ["Warnings", "Actions", "System"]);
  assertEqual(groups[0].items.map((i) => i.message), ["Leak warning"]);
  assertEqual(groups[1].items.length, 3);
});

test("the rendered tab filters by type and offers show-more when the feed is deep", async () => {
  const many = [];
  for (let i = 0; i < 40; i += 1) {
    many.push(entry(`2026-09-01T0${i % 10}:0${i % 6}:00Z`, `Event ${i}`, i % 2 ? "control" : "info"));
  }
  const panel = await makePanel({ activity: many });
  const restore = freezeTime(NOW);
  try {
    let html = panel._logTab();
    assert(html.includes("log-show-more"), "40 entries at a 30-row page must offer Show more");
    assert(html.includes("All (40)") && html.includes("Actions (20)"),
      "the type chips carry live counts");

    panel._logViewState().type = "warning";
    html = panel._logTab();
    assert(!html.includes("Event 1<"), "a warning filter hides control/info rows");
    assert(html.includes("Nothing matches this filter"),
      "an empty filter result says so instead of rendering nothing");

    panel._logViewState().type = "all";
    panel._logViewState().limit = 100;
    html = panel._logTab();
    assert(!html.includes("log-show-more"), "a fully-extended view drops Show more");
    assert(html.includes("That's the whole feed."), "the end of the feed is announced");
  } finally {
    restore();
  }
});

test("the empty feed renders the quiet state, not controls", async () => {
  const panel = await makePanel({ activity: [] });
  const html = panel._logTab();
  assert(html.includes("No OpenReef activity has been recorded yet"), "quiet copy expected");
  assert(!html.includes("log-group"), "no grouping controls over an empty feed");
});

await runTests();
