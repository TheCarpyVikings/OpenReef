/** Manual history must expose every saved result and filter without changing data. */
import { makePanel, freezeTime, assert, assertEqual, test, runTests } from "./_panel_harness.mjs";

const NOW = "2026-11-02T12:00:00Z";
const DAY = 86400000;
const reading = (id, ageMs) => ({
  id, timestamp: new Date(Date.parse(NOW) - ageMs).toISOString(), value: 0.08, source: "Hanna",
});
const rowIds = (html) => [...html.matchAll(/data-reading="([^"]+)"/g)].map((match) => match[1]);

async function manualPanel(readings = []) {
  const panel = await makePanel({ manualReadings: { phosphate: readings } });
  panel._manualHistoryOpen = { phosphate: true };
  panel._manualHistoryRange = {};
  return panel;
}

test("All history shows every saved result newest first, including entries beyond twelve and a year", async () => {
  const readings = Array.from({ length: 29 }, (_, i) => reading(`test-${i}`, i * 30 * DAY)).reverse();
  const panel = await manualPanel(readings);
  const before = JSON.stringify(readings);
  const html = panel._manualTestCard("phosphate");
  assertEqual(rowIds(html), Array.from({ length: 29 }, (_, i) => `test-${i}`));
  assert(html.includes('value="all" selected'), "All history is the default");
  assert(html.includes("Showing 29 of 29 saved results"), "count matches the rows");
  assertEqual(JSON.stringify(readings), before, "viewing does not reorder stored history");
});

test("each period includes its exact cutoff and excludes older and future results", async () => {
  const restore = freezeTime(NOW);
  try {
    for (const [range, days] of [["7d", 7], ["30d", 30], ["90d", 90], ["180d", 180], ["365d", 365]]) {
      const panel = await manualPanel([
        reading("older", days * DAY + 1), reading("boundary", days * DAY),
        reading("now", 0), reading("future", -1),
      ]);
      panel._manualHistoryRange.phosphate = range;
      const html = panel._manualTestCard("phosphate");
      assertEqual(rowIds(html), ["now", "boundary"], `${range} cutoff`);
      assert(html.includes("Showing 2 of 4 saved results"), `${range} filtered count`);
    }
  } finally { restore(); }
});

test("empty periods distinguish old history from a test with no saved results", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await manualPanel([reading("old", 400 * DAY)]);
    panel._manualHistoryRange.phosphate = "7d";
    const html = panel._manualTestCard("phosphate");
    assert(html.includes("No results in this period. Choose All history"), "older results remain discoverable");
    assert(html.includes("Showing 0 of 1 saved result"), "zero matches is explicit");
    assert((await manualPanel())._manualTestCard("phosphate").includes("No history yet."), "empty store message");
  } finally { restore(); }
});

test("changing a period is per parameter, survives closing history, and preserves form drafts", async () => {
  const panel = await manualPanel([reading("old", 400 * DAY)]);
  panel._manualEntryDefaults = { values: { alkalinity: "8.2" }, notes: "Before water change" };
  // Populate normal schedule defaults before checking for data mutations.
  panel._manualTestCard("phosphate");
  const before = JSON.stringify(panel._config);
  const drafts = JSON.stringify(panel._manualEntryDefaults);
  const handlers = {};
  panel.shadowRoot = { addEventListener: (type, handler) => { handlers[type] = handler; } };
  panel.addEventListener = () => {};
  let renders = 0;
  panel._render = () => { renders += 1; };
  panel._attachEvents();
  const target = { dataset: { manualHistoryRange: "phosphate" }, value: "7d", type: "select-one" };
  handlers.input({ target, type: "input" });
  assertEqual(renders, 0, "wait for change before replacing the select");
  handlers.change({ target, type: "change" });
  assertEqual(renders, 1);
  assertEqual(panel._manualHistoryRange, { phosphate: "7d" });
  const toggle = { dataset: { action: "toggle-manual-history", id: "phosphate" } };
  await handlers.click({ target: { closest: () => toggle } });
  assert(!panel._manualTestCard("phosphate").includes("manual-history-list"), "history closes");
  await handlers.click({ target: { closest: () => toggle } });
  assert(panel._manualTestCard("phosphate").includes('value="7d" selected'), "choice survives reopening");
  assertEqual(JSON.stringify(panel._config), before, "filters do not modify stored results or settings");
  assertEqual(JSON.stringify(panel._manualEntryDefaults), drafts, "unsaved test session is preserved");
});

test("live refresh keeps the history scroll position; changing period starts at the top", async () => {
  const panel = await manualPanel();
  let list = { dataset: { manualHistoryList: "phosphate:all" }, scrollTop: 780 };
  panel.shadowRoot = { querySelector: () => null, querySelectorAll: () => [list] };
  const state = panel._captureScrollState();
  list = { dataset: { manualHistoryList: "phosphate:all" }, scrollTop: 0 };
  panel._restoreScrollState(state);
  assertEqual(list.scrollTop, 780, "live readings must not send someone back to the newest test");
  list = { dataset: { manualHistoryList: "phosphate:90d" }, scrollTop: 0 };
  panel._restoreScrollState(state);
  assertEqual(list.scrollTop, 0, "a different period starts at its newest result");
});

await runTests();
