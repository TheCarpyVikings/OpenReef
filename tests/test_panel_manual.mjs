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
  panel._manualHistorySource = {};
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

test("source and period choices are per parameter, survive closing history, and preserve form drafts", async () => {
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
  const sourceTarget = { dataset: { manualHistorySource: "phosphate" }, value: "source:Hanna", type: "select-one" };
  handlers.input({ target: sourceTarget, type: "input" });
  assertEqual(renders, 1, "source input waits for change too");
  handlers.change({ target: sourceTarget, type: "change" });
  assertEqual(renders, 2);
  assertEqual(panel._manualHistorySource, { phosphate: "source:Hanna" });
  assertEqual(panel._manualHistoryRange, { phosphate: "7d" }, "changing source preserves the period");
  const toggle = { dataset: { action: "toggle-manual-history", id: "phosphate" } };
  await handlers.click({ target: { closest: () => toggle } });
  assert(!panel._manualTestCard("phosphate").includes("manual-history-list"), "history closes");
  await handlers.click({ target: { closest: () => toggle } });
  assert(panel._manualTestCard("phosphate").includes('value="7d" selected'), "choice survives reopening");
  assert(panel._manualTestCard("phosphate").includes('value="source:Hanna" selected'), "source survives reopening");
  assertEqual(JSON.stringify(panel._config), before, "filters do not modify stored results or settings");
  assertEqual(JSON.stringify(panel._manualEntryDefaults), drafts, "unsaved test session is preserved");
});

test("live refresh keeps the history scroll position; changing either filter starts at the top", async () => {
  const panel = await manualPanel();
  const listNode = (scrollTop = 0) => ({
    dataset: { manualHistoryList: panel._manualTestCard("phosphate").match(/data-manual-history-list="([^"]+)"/)[1] }, scrollTop,
  });
  let list = listNode(780);
  panel.shadowRoot = { querySelector: () => null, querySelectorAll: () => [list] };
  const state = panel._captureScrollState();
  list = listNode();
  panel._restoreScrollState(state);
  assertEqual(list.scrollTop, 780, "live readings must not send someone back to the newest test");
  panel._manualHistoryRange.phosphate = "90d";
  list = listNode();
  panel._restoreScrollState(state);
  assertEqual(list.scrollTop, 0, "a different period starts at its newest result");
  panel._manualHistoryRange.phosphate = "all";
  panel._manualHistorySource.phosphate = "source:Hanna";
  list = listNode();
  panel._restoreScrollState(state);
  assertEqual(list.scrollTop, 0, "a different source starts at its newest result");
});

test("source and date filters combine, with source choices drawn from the entire history", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await manualPanel([
      reading("recent-hanna", DAY), reading("old-hanna", 120 * DAY),
      { ...reading("aquaticlog", 2 * DAY), source: "AquaticLog" },
      { ...reading("icp", 400 * DAY), source: "ICP:ATI" },
    ]);
    assertEqual(rowIds(panel._manualTestCard("phosphate")), ["recent-hanna", "aquaticlog", "old-hanna", "icp"]);
    panel._manualHistorySource.phosphate = "source:Hanna";
    assertEqual(rowIds(panel._manualTestCard("phosphate")), ["recent-hanna", "old-hanna"]);
    panel._manualHistoryRange.phosphate = "7d";
    let html = panel._manualTestCard("phosphate");
    assertEqual(rowIds(html), ["recent-hanna"]);
    assert(html.includes("Showing 1 of 4 saved results"));
    assert(html.includes('value="source:ICP:ATI"'), "sources outside the period stay available");
    panel._manualHistorySource.phosphate = "source:ICP:ATI";
    html = panel._manualTestCard("phosphate");
    assertEqual(rowIds(html), []);
    assert(html.includes("No results match this source and time period."));
    panel._manualHistoryRange.phosphate = "all";
    assertEqual(rowIds(panel._manualTestCard("phosphate")), ["icp"]);
    panel._manualHistorySource.phosphate = "";
    assertEqual(rowIds(panel._manualTestCard("phosphate")), ["recent-hanna", "aquaticlog", "old-hanna", "icp"]);
  } finally { restore(); }
});

test("sources support imports, blank sources, and whitespace without treating a source named all as a wildcard", async () => {
  const panel = await manualPanel([
    { ...reading("blank", DAY), source: "  " },
    { ...reading("missing", 2 * DAY), source: undefined },
    { ...reading("padded", 3 * DAY), source: " Hanna " },
    reading("hanna", 4 * DAY),
    { ...reading("literal-all", 5 * DAY), source: "all" },
    { ...reading("quoted", 6 * DAY), source: 'Custom "kit" <lab>' },
  ]);
  const sources = panel._manualHistorySources("phosphate");
  assertEqual(sources.filter(([key]) => key === "source:Hanna").length, 1, "trimmed duplicates form one option");
  assert(sources.some(([key, label]) => key === "source:" && label === "No source recorded"));
  panel._manualHistorySource.phosphate = "source:";
  assertEqual(rowIds(panel._manualTestCard("phosphate")), ["blank", "missing"]);
  panel._manualHistorySource.phosphate = "source:Hanna";
  assertEqual(rowIds(panel._manualTestCard("phosphate")), ["padded", "hanna"]);
  panel._manualHistorySource.phosphate = "source:all";
  assertEqual(rowIds(panel._manualTestCard("phosphate")), ["literal-all"]);
  panel._manualHistorySource.phosphate = 'source:Custom "kit" <lab>';
  const html = panel._manualTestCard("phosphate");
  assertEqual(rowIds(html), ["quoted"]);
  assert(html.includes('value="source:Custom &quot;kit&quot; &lt;lab&gt;" selected'), "imported source text is escaped");
  assert(!html.includes("<lab>"));
});

test("a selected source stays visible when its last result disappears", async () => {
  const panel = await manualPanel([{ ...reading("other", DAY), source: "AquaticLog" }]);
  panel._manualHistorySource.phosphate = "source:Hanna";
  const html = panel._manualTestCard("phosphate");
  assert(html.includes('value="source:Hanna" selected'), "the control still describes the active filter");
  assert(html.includes("Showing 0 of 1 saved result"));
  assert(html.includes("No results match this source and time period."));
});

await runTests();
