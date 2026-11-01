/** Whole-tank feeding UI contracts. Run: node tests/test_panel_feeding.mjs */
import { assert, assertEqual, freezeTime, makePanel, runTests, test } from "./_panel_harness.mjs";

const NOW = "2026-11-01T18:30:00Z";
const restoreClock = freezeTime(NOW);
const summary = () => ({
  date: "2026-11-01", since: "2026-11-01", days: 1, nowLocal: NOW, timeZone: "UTC",
  foods: [
    { id: "brine", name: "Live brine", unit: "ml", portion: 250, live: true, sources: [
      { id: "brine:container", label: "Container", available: true, loggable: true },
      { id: "brine:bottle", label: "Fridge bottle", available: true, loggable: true },
    ] },
    { id: "manual:flake", name: "Vitalis flake", unit: "pinch", portion: 1, live: false,
      sources: [{ id: "manual:flake", label: "Food shelf", loggable: true, available: true }] },
    { id: "phyto:nanno", name: "Live phyto · Nanno", unit: "ml", portion: 100, live: true,
      sources: [{ id: "culture:nanno", label: "Culture jar", loggable: false, available: true }] },
  ],
  totals: [
    { foodId: "brine", name: "Live brine", unit: "ml", amount: 5000, feeds: 20, live: true, tankVolumePct: 1,
      sources: [{ id: "brine:container", label: "Container", amount: 3000, unit: "ml" }, { id: "brine:bottle", label: "Fridge bottle", amount: 2000, unit: "ml" }] },
    { foodId: "manual:flake", name: "Vitalis flake", unit: "pinch", amount: 3, feeds: 2, live: false, tankVolumePct: null, sources: [] },
  ],
  rows: [{ id: "brine@one", foodId: "brine", name: "Live brine", unit: "ml", amount: 250, source: "brine", sourceId: "brine:bottle", sourceLabel: "Fridge bottle", at: "2026-11-01T11:25:00Z", date: "2026-11-01", time: "11:25", slot: "11:00", plannedAmount: 250, editable: true, undoable: true }],
  planned: [{ id: "brine:21", foodId: "brine", name: "Live brine", unit: "ml", amount: 250, at: "21:00", source: "brine:container", status: "planned" }],
  perDay: [{ date: "2026-11-01", foods: [{ foodId: "brine", unit: "ml", amount: 5000, feeds: 20 }], hasRecords: true }],
  tankLitres: 500, liveLiquidMl: 32500, liveVolumePct: 6.5, coverage: { notes: ["Available records only."] },
});

async function panel(data = summary()) {
  const p = await makePanel({ manualReadings: { nitrate: [{ value: 12, timestamp: "2026-10-11T12:00:00Z" }] } });
  p._render = () => {};
  p._nps = { demo: false, loading: false, summary: {} };
  p._npsLoadSummary = () => {};
  p._feedingState().data = data;
  p._feedingState().days = data.days;
  p._feedingState().at = Date.now();
  return p;
}

test("summary uses backend volume estimates and mixed units, even with a capped displayed log", async () => {
  const data = summary(); data.truncated = true;
  const p = await panel(data), html = p._feedingOverview();
  assert(html.includes("5,000 ml") && html.includes("3 pinches"), "food amounts retain their units");
  assert(html.includes("≈ 1% of tank volume added"), "per-food percentage is visible");
  assert(html.includes("32,500 ml · ≈ 6.5% of tank volume"), "overall live addition is independent of displayed row cap");
  assert(html.includes("500 L configured water volume") && html.includes("including carrier water"), "denominator and interpretation are explicit");
  assert(html.includes("totals include all retained records"), "capped list does not imply capped totals");
  assert(!html.includes("biomass"), "no claim that liquid equals organism mass");
});

test("missing tank volume does not become zero percent or silently assume display name volume", async () => {
  const data = summary(); data.tankLitres = null; data.liveVolumePct = null; data.totals[0].tankVolumePct = null;
  const p = await panel(data), html = p._feedingOverview();
  assert(html.includes("Set your tank water volume"), "configuration prompt");
  assert(!html.includes("≈ 0%") && !html.includes("of tank volume added"), "no fabricated denominator");
  assertEqual(p._feedingPercent(.004), "≈ <0.01%", "very small positive values remain distinguishable from zero");
});

test("quick dry food logs once as extra with no device command or schedule", async () => {
  const p = await panel(), calls = [];
  p._feedingLoad = async () => {};
  p._callWS = async (message) => { calls.push(message); return { entry_id: "new-flake" }; };
  await p._feedingQuick("manual:flake");
  assertEqual(calls, [{ type: "openreef/feeding_log", food_id: "manual:flake", source_id: "manual:flake", amount: 1, extra: true }]);
  assert(p._feedingState().noticeEntry === "new-flake", "immediate undo names exact entry");
});

test("quick live food offers source and nearest open slot before writing", async () => {
  const p = await panel(); let calls = 0;
  p._callWS = async () => { calls++; };
  p._feedingQuick("brine");
  assert(calls === 0, "no record written until chooser confirmed");
  const d = p._feedingState().draft;
  assert(d.sourceId === "brine:container" && d.slot === "21:00", "correct suggested source and slot");
  const html = p._feedingEditor();
  assert(html.includes("Extra feed") && html.includes("Fridge bottle"), "both intent and source can change");
});

test("partial planned feed sends actual amount and chosen slot, without an invented remainder", async () => {
  const p = await panel(); let sent;
  p._feedingCommand = (message) => { sent = message; };
  p._feedingOpenEditor("brine", "", "brine:21");
  p._feedingDraftChanged("amount", "100", "input");
  p._feedingSaveDraft();
  assertEqual(sent, { type: "openreef/feeding_log", food_id: "brine", source_id: "brine:container", amount: 100, at: "2026-11-01T18:30:00.000Z", slot: "21:00" });
  assert(p._feedingEditor().includes("including if you fed less"), "completion behavior is visible");
});

test("explicit extra remains extra despite a nearby planned feed", async () => {
  const p = await panel(); let sent;
  p._feedingCommand = (message) => { sent = message; };
  p._feedingOpenEditor("brine", "", "brine:21");
  p._feedingDraftChanged("slot", "extra");
  p._feedingSaveDraft();
  assert(sent.extra === true && !Object.hasOwn(sent, "slot"), "extra is explicit, never nearest-matched on the client");
});

test("any-time planned feeds retain planned intent and remain distinct from extras", async () => {
  const data = summary(); data.planned[0].at = null;
  const p = await panel(data); let sent;
  p._feedingCommand = (message) => { sent = message; };
  p._feedingQuick("brine");
  assert(p._feedingState().draft.slot === "anytime", "any-time slot is offered when no timed slot exists");
  assert(p._feedingEditor().includes("Any time feed"), "human label is not a fake clock");
  p._feedingSaveDraft();
  assert(sent.slot === "anytime" && sent.extra === false, "explicit planned intent reaches backend");
  p._feedingDraftChanged("slot", "extra"); p._feedingSaveDraft();
  assert(sent.extra === true && !Object.hasOwn(sent, "slot"), "extra remains a separate choice");
});

test("brine plans accept either container, while moving the actual day removes today's slot", async () => {
  const p = await panel();
  p._feedingOpenEditor("brine", "", "brine:21");
  p._feedingDraftChanged("sourceId", "brine:bottle");
  assert(p._feedingState().draft.slot === "21:00", "the same brine plan may be fed from either container");
  p._feedingOpenEditor("brine", "", "brine:21");
  p._feedingDraftChanged("at", "2026-10-31T20:00");
  assert(p._feedingState().draft.slot === "extra", "yesterday cannot fill today's slot");
});

test("editing opens the original actual time and source, then updates the same entry", async () => {
  const p = await panel(); let sent;
  p._feedingCommand = (message) => { sent = message; };
  p._feedingOpenEditor("", "brine@one");
  assert(p._feedingState().draft.at === "2026-11-01T11:25", "actual timestamp is preserved, not replaced by now");
  assert(p._feedingState().draft.sourceId === "brine:bottle", "canonical sourceId wins over legacy source kind");
  p._feedingDraftChanged("amount", "100", "input");
  p._feedingSaveDraft();
  assertEqual(sent, { type: "openreef/feeding_edit", entry_id: "brine@one", amount: 100, at: "2026-11-01T11:25:00.000Z" });
});

test("source capability and availability prevent shortcutting harvest or inventory guards", async () => {
  const p = await panel(); let writes = 0;
  p._feedingCommand = () => { writes++; };
  p._feedingQuick("phyto:nanno");
  assert(writes === 0 && p._feedingState().error.includes("No available source"), "culture harvest stays on specialist control");
  p._feedingState().data.foods[0].sources.forEach((source) => { source.available = false; });
  p._feedingQuick("brine");
  assert(writes === 0, "empty/unavailable food is not blindly logged");
});

test("save errors preserve draft and repeat taps are blocked while saving", async () => {
  const p = await panel(); let reject, calls = 0;
  p._feedingOpenEditor("manual:flake");
  p._callWS = () => { calls++; return new Promise((_, no) => { reject = no; }); };
  const first = p._feedingSaveDraft();
  p._feedingSaveDraft();
  assert(calls === 1 && p._feedingState().busy, "one mutation in flight");
  reject(new Error("Inventory changed; check the source."));
  await first;
  assert(p._feedingState().draft && !p._feedingState().busy, "failed write keeps form");
  assert(p._feedingState().error.includes("Inventory changed"), "backend refusal stays visible");
});

test("future times and nonpositive amounts are rejected before writing", async () => {
  const p = await panel(); let writes = 0;
  p._feedingCommand = () => { writes++; };
  p._feedingOpenEditor("manual:flake");
  p._feedingDraftChanged("at", "2026-11-01T19:00"); p._feedingSaveDraft();
  assert(writes === 0 && p._feedingState().error.includes("up to now"), "future log rejected");
  p._feedingDraftChanged("at", "2026-11-01T18:30"); p._feedingDraftChanged("amount", "-1", "input"); p._feedingSaveDraft();
  assert(writes === 0, "negative portion rejected");
});

test("simple view changes presentation only and leaves current errors, due feeds and volume totals", async () => {
  const p = await panel(), before = JSON.stringify(p._feedingState().data);
  p._feedingState().error = "Pump connection unavailable.";
  p._feedingOverviewAction("simple");
  const html = p._feedingOverview();
  assert(!html.includes("<h3>Feeding log</h3>") && !html.includes("<h3>Today’s timeline</h3>"), "details hidden");
  assert(html.includes("Still planned today") && html.includes("32,500 ml") && html.includes("Pump connection unavailable"), "important state stays visible");
  assert(JSON.stringify(p._feedingState().data) === before, "presentation does not mutate records");
});

test("historical chart preserves missing food amounts and identifies incomplete live volume", async () => {
  const data = summary(); data.days = 7; data.perDay.unshift({ date: "2026-10-31", hasRecords: true, foods: [{ foodId: "brine", unit: "ml", amount: null }] });
  data.unknownLiveFeeds = 2; data.unclassifiedLiquidMl = 300;
  const p = await panel(data), html = p._feedingOverview();
  assert(html.includes('class="feed-overview-bar gap"'), "missing amount has a visible gap");
  assert(html.includes("No amount recorded") && html.includes("2 live feeds have no recorded volume"), "unknown is not zero");
  assert(html.includes("300 ml of unclassified liquid is excluded"), "classification limits are explicit");
});

test("manual testing card reuses real results with their dates and routes to existing tests", async () => {
  const p = await panel(), html = p._feedingNutrientCard();
  assert(html.includes("Nitrate: 12 ppm") && html.includes("Phosphate: no recorded test"), "existing actual results only");
  assert(html.includes('data-action="tab" data-id="manual"'), "one canonical logging destination");
  assert(!html.includes("critical") && !html.includes("overdue"), "neutral freshness, no inferred current chemistry issue");
});

test("log intent labels distinguish explicit extras, automatic delivery and unspecified legacy records", async () => {
  const cases = [
    [{ slot: "", how: "hand", extra: true }, "Extra feed"],
    [{ slot: "", how: "hand" }, "Recorded feed"],
    [{ slot: "extra", how: "hand" }, "Recorded feed"],
    [{ slot: "", how: "pump" }, "Automatic feed"],
    [{ slot: "", how: "hand", drip: true }, "Automatic feed"],
    [{ slot: "11:00", how: "pump" }, "11:00 slot"],
    [{ slot: "anytime", how: "hand", extra: false }, "Any-time slot"],
  ];
  for (const [fields, expected] of cases) {
    const data = summary(); data.rows[0] = { ...data.rows[0], ...fields };
    const p = await panel(data), html = p._feedingOverviewLog();
    assert(html.includes(expected), `${JSON.stringify(fields)} should display ${expected}`);
    if (expected !== "Extra feed") assert(!html.includes("Extra feed"), "only explicit extra intent is labelled extra");
  }
});

test("food preferences save custom portions and explicitly classify native live liquid", async () => {
  const p = await panel(); let sent;
  p._feedingCommand = (message) => { sent = message; };
  p._feedingNewFood("manual:flake");
  p._feedingDraftChanged("portion", "0.5", "input"); p._feedingSaveDraft();
  assertEqual(sent, { type: "openreef/feeding_food_save", food_id: "manual:flake", name: "Vitalis flake", unit: "pinch", portion: .5, live: false });
  p._feedingNewFood("brine");
  assert(p._feedingState().draft.native, "native identity is not renamed by preference editor");
  p._feedingDraftChanged("live", true); p._feedingSaveDraft();
  assert(sent.food_id === "brine" && sent.live === true, "native classification is an explicit saved preference");
});

test("demo never writes real feeding records", async () => {
  const p = await panel(); let writes = 0;
  p._nps.demo = true; p._callWS = async () => { writes++; };
  await p._feedingQuick("manual:flake");
  assert(writes === 0 && p._feedingState().error.includes("Exit demo"), "demo write blocked");
});

test("backend names, sources and errors are escaped before entering markup", async () => {
  const data = summary(); data.totals[0].name = '<img src=x onerror="bad()">'; data.rows[0].sourceLabel = "<script>bad()</script>";
  const p = await panel(data); p._feedingState().error = "<svg onload=bad()>";
  const html = p._feedingOverview();
  assert(!html.includes("<img") && !html.includes("<script>bad") && !html.includes("<svg onload"), "untrusted text cannot create markup");
  assert(html.includes("&lt;img") && html.includes("&lt;svg"), "text remains readable");
});

await runTests();
restoreClock();
