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

const rotationSummary = (rotation = {}) => {
  const data = summary();
  for (const [id, name] of [["marine-flake", "Vitalis - Marine Flakes"], ["marine-pellet", "Vitalis - Marine Pellets"],
    ["platinum-flake", "Vitalis - Platinum Marine Flakes"], ["platinum-pellet", "Vitalis - Platinum Marine Pellets"]]) {
    data.foods.push({ id: `manual:${id}`, name, unit: "pinch", portion: 1, tankFeed: true, loggable: true,
      sources: [{ id: `manual:${id}`, label: "By hand", loggable: true, available: true }] });
  }
  data.rotation = { enabled: true, startDate: "2026-10-25", startPhase: "marine", notify: false,
    marineFoodIds: ["manual:marine-flake", "manual:marine-pellet"], platinumFoodIds: ["manual:platinum-flake", "manual:platinum-pellet"],
    status: "active", phase: "marine", cycleWeek: 2, nextPhase: "platinum", nextSwitchDate: "2026-11-22",
    suggestedFoodIds: ["manual:marine-flake", "manual:marine-pellet"], invalidFoodIds: [], ...rotation };
  return data;
};

test("rotation setup previews matching food names without enabling, saving or changing portions", async () => {
  const data = rotationSummary({ enabled: false, startDate: "", marineFoodIds: [], platinumFoodIds: [], status: "disabled", phase: null, suggestedFoodIds: [] });
  data.foods.push({ id: "culture-only", name: "Vitalis Marine culture mix", sources: [{ id: "culture:mix", loggable: true, tankFeed: false }] });
  // The tank has reached tomorrow, while this browser's frozen clock is still Nov 1.
  data.date = "2026-11-02"; data.nowLocal = "2026-11-02T07:30:00+13:00";
  const before = JSON.stringify(data), p = await panel(data); let writes = 0;
  p._callWS = async () => { writes++; };
  assert(p._feedingRotationCard().includes("Set up rotation"), "optional feature has a setup entry point");
  p._feedingOverviewAction("rotation");
  const draft = p._feedingState().draft;
  assert(!draft.enabled && !draft.notify, "guidance and notification need explicit opt in");
  assert(draft.startDate === "2026-11-02", "date comes from Home Assistant, never browser today");
  assertEqual(draft.marineFoodIds, ["manual:marine-flake", "manual:marine-pellet"]);
  assertEqual(draft.platinumFoodIds, ["manual:platinum-flake", "manual:platinum-pellet"]);
  assert(p._feedingEditor().includes("Review both groups before saving"), "name matches require review");
  assert(!p._feedingEditor().includes('data-feeding-draft="marineFood:phyto:nanno"'), "culture-only sources cannot be selected");
  assert(!p._feedingEditor().includes('data-feeding-draft="marineFood:culture-only"'), "source-level tank-use exclusion is respected too");
  assert(writes === 0 && JSON.stringify(data) === before, "opening settings changes no records or config");
  p._feedingDraftChanged("startPhase", "platinum"); p._feedingDraftChanged("startDate", "2026-10-01");
  p._feedingOverviewAction("rotation-today");
  assert(draft.startDate === "2026-11-02" && draft.startPhase === "platinum", "Start today changes the selected phase's first day only");
});

test("rotation highlights both current-phase forms while other foods still log their own portions", async () => {
  const data = rotationSummary(), p = await panel(data), before = JSON.stringify(data);
  const html = p._feedingOverview();
  assert(html.indexOf("Vitalis rotation") < html.indexOf("Your usual portions"), "guide is directly above usual portions");
  assert(html.includes("Marine · week 2 of 6") && html.includes("Switch to Platinum Marine on"), "shared phase and next switch are visible");
  const buttons = html.match(/<button[^>]*data-action="feeding-overview-quick"[\s\S]*?<\/button>/g) || [];
  for (const id of ["manual:marine-flake", "manual:marine-pellet", "manual:platinum-flake", "manual:platinum-pellet"]) {
    const button = buttons.find((item) => item.includes(`data-id="${id}"`));
    assert(button && button.includes("+ 1 pinch"), "all usual quantities remain available");
    assert(button.includes("Suggested today") === id.startsWith("manual:marine-"), "only this phase is suggested");
  }
  let sent; p._feedingCommand = (message) => { sent = message; };
  p._feedingQuick("manual:platinum-pellet");
  assertEqual(sent, { type: "openreef/feeding_log", food_id: "manual:platinum-pellet", source_id: "manual:platinum-pellet", amount: 1, extra: true }, "guidance never substitutes the tapped food");
  assert(JSON.stringify(data) === before, "rendering guidance does not rewrite history, totals or slots");
  data.rotation.phase = "platinum"; data.rotation.cycleWeek = 5; data.rotation.nextPhase = "marine";
  data.rotation.suggestedFoodIds = data.rotation.platinumFoodIds;
  const platinum = p._feedingOverview().match(/<button[^>]*data-action="feeding-overview-quick"[\s\S]*?<\/button>/g) || [];
  assert(platinum.filter((item) => item.includes("Suggested today")).every((item) => item.includes('data-id="manual:platinum-')), "phase change follows backend suggestions");
});

test("rotation save sends one shared configuration and never logs or schedules food", async () => {
  const p = await panel(rotationSummary()), calls = [];
  p._feedingLoad = async () => {};
  p._callWS = async (message) => { calls.push(message); return { ok: true }; };
  p._feedingOpenRotation();
  p._feedingDraftChanged("startPhase", "platinum"); p._feedingDraftChanged("startDate", "2026-11-01");
  p._feedingDraftChanged("notify", true);
  await p._feedingSaveDraft();
  assertEqual(calls, [{ type: "openreef/feeding_rotation_save", enabled: true, start_date: "2026-11-01", start_phase: "platinum",
    marine_food_ids: ["manual:marine-flake", "manual:marine-pellet"], platinum_food_ids: ["manual:platinum-flake", "manual:platinum-pellet"], notify: true }]);
  assert(p._feedingState().draft === null && !p._feedingState().noticeEntry, "success closes settings without inventing a feed or undo entry");
});

test("rotation clock refreshes stale visible guidance without interrupting drafts or inactive pages", async () => {
  const p = await panel(rotationSummary()), st = p._feedingState(); let loads = 0;
  p._hass = {}; p._activeTab = "feeding";
  p._feedingLoad = async () => { loads++; };
  st.at = Date.now() - 59999;
  await p._feedingRefreshRotationIfDue();
  assert(loads === 0, "fresh snapshot is retained");
  st.at = Date.now() - 60000;
  const blocked = [
    [() => { st.draft = { kind: "rotation" }; }, () => { st.draft = null; }],
    [() => { st.busy = true; }, () => { st.busy = false; }],
    [() => { st.loading = true; }, () => { st.loading = false; }],
    [() => { st.data.rotation.enabled = false; }, () => { st.data.rotation.enabled = true; }],
    [() => { p._activeTab = "water"; }, () => { p._activeTab = "feeding"; }],
    [() => { p._hass = null; }, () => { p._hass = {}; }],
    [() => { p._nps.demo = true; }, () => { p._nps.demo = false; }],
    [() => { p._setupOpen = true; }, () => { p._setupOpen = false; }],
    [() => { p.shadowRoot = {}; p._isEditingFormControl = () => true; }, () => { p.shadowRoot = null; }],
  ];
  for (const [set, restore] of blocked) { set(); await p._feedingRefreshRotationIfDue(); restore(); }
  const visibility = document.visibilityState;
  try { document.visibilityState = "hidden"; await p._feedingRefreshRotationIfDue(); }
  finally { document.visibilityState = visibility; }
  assert(loads === 0, "draft, busy, hidden, editing and unrelated pages do not fetch or redraw");
  await p._feedingRefreshRotationIfDue();
  assert(loads === 1, "visible Feeding refreshes the backend calendar after sixty seconds");
  p._activeTab = "nps"; await p._feedingRefreshRotationIfDue();
  assert(loads === 2, "NPS overview uses the same refresh path");
});

test("rotation validation catches missing groups, overlap, invalid dates and removed foods", async () => {
  const p = await panel(rotationSummary()); let writes = 0;
  p._feedingCommand = () => { writes++; };
  const check = (change, text) => {
    p._feedingOpenRotation(); change(p._feedingState().draft); p._feedingSaveDraft();
    assert(p._feedingState().error.includes(text), text);
  };
  check((d) => { d.marineFoodIds = []; }, "at least one food");
  check((d) => { d.platinumFoodIds.push(d.marineFoodIds[0]); }, "different foods");
  check((d) => { d.startDate = "2026-02-30"; }, "valid date");
  check((d) => { d.startDate = ""; }, "valid date");
  check((d) => { d.startPhase = "unknown"; }, "Choose a phase");
  check((d) => { d.marineFoodIds = ["deleted-food"]; }, "Remove unavailable");
  check((d) => { d.marineFoodIds = ["phyto:nanno"]; }, "Remove unavailable");
  assert(writes === 0, "invalid drafts never reach a write command");
  p._feedingOpenRotation(); p._feedingDraftChanged("marineFood:phyto:nanno", true);
  assert(!p._feedingState().draft.marineFoodIds.includes("phyto:nanno"), "event path also rejects excluded culture supplies");
});

test("rotation missing selections remain repairable, and disabling does not require replacing them", async () => {
  const data = rotationSummary({ status: "needs_foods", marineFoodIds: ["manual:deleted"], invalidFoodIds: ["manual:deleted"], suggestedFoodIds: [] });
  const p = await panel(data); let sent;
  p._feedingCommand = (message) => { sent = message; };
  p._feedingOpenRotation();
  const html = p._feedingEditor();
  assert(html.includes('data-feeding-draft="marineFood:manual:deleted" checked') && html.includes("untick to remove"), "removed IDs are visible and removable");
  assert(p._feedingRotationCard().includes("Some selected foods need review"), "card explains why mapping needs attention");
  p._feedingDraftChanged("enabled", false); p._feedingSaveDraft();
  assert(sent.enabled === false && sent.marine_food_ids[0] === "manual:deleted", "can turn guidance off without repairing a removed food");
  p._feedingDraftChanged("startDate", "old-invalid-date");
  p._feedingState().draft.platinumFoodIds.push("manual:deleted");
  p._feedingSaveDraft();
  assert(sent.start_date === "old-invalid-date" && sent.enabled === false, "turning off is also allowed with stale date or overlapping mappings");
  p._feedingDraftChanged("startDate", "2026-10-25"); p._feedingDraftChanged("platinumFood:manual:deleted", false);
  p._feedingDraftChanged("marineFood:manual:deleted", false); p._feedingDraftChanged("marineFood:manual:marine-pellet", true);
  p._feedingDraftChanged("enabled", true); p._feedingSaveDraft();
  assertEqual(sent.marine_food_ids, ["manual:marine-pellet"], "an explicit replacement can re-enable guidance");
});

test("rotation busy state prevents duplicate saves and lost drafts, and failures stay beside the form", async () => {
  const p = await panel(rotationSummary()); let reject, writes = 0;
  p._callWS = () => { writes++; return new Promise((resolve, rejectSave) => { reject = rejectSave; }); };
  p._feedingOpenRotation(); const draft = p._feedingState().draft;
  const pending = p._feedingSaveDraft();
  p._feedingSaveDraft(); p._feedingDraftChanged("notify", true); p._feedingOverviewAction("days", { id: 7 }); p._feedingOverviewAction("cancel");
  assert(writes === 1 && p._feedingState().draft === draft && !draft.notify && p._feedingState().days === 1, "busy save retains original draft and prevents repeated work");
  assert(p._feedingEditor().includes('aria-busy="true"') && p._feedingEditor().includes('class="feed-rotation-controls stack" disabled'), "all form controls are disabled accessibly");
  reject(new Error("Connection lost <retry>")); await pending;
  const html = p._feedingEditor();
  assert(p._feedingState().draft === draft && !p._feedingState().busy, "failed save can be retried with the same selections");
  assert(html.includes('role="alert"') && html.includes("Connection lost &lt;retry&gt;"), "escaped error is next to Save rotation");
});

test("rotation upcoming, simple, history and out-of-stock states remain neutral", async () => {
  const data = rotationSummary({ status: "upcoming", phase: null, cycleWeek: null, startPhase: "platinum", startDate: "2026-11-04", suggestedFoodIds: [] });
  const p = await panel(data);
  assert(p._feedingRotationCard().includes("Starts") && p._feedingRotationCard().includes("Platinum Marine comes first"), "future start has no fake current phase");
  assert(!p._feedingOverview().includes("Suggested today"), "no premature suggestion");
  data.rotation.status = "needs_foods"; data.rotation.invalidFoodIds = ["missing"];
  assert(!p._feedingRotationCard().includes("week —") && p._feedingRotationCard().includes("Platinum Marine comes first"), "future start stays upcoming when a mapping needs repair");
  p._feedingState().simple = true;
  assert(p._feedingOverview().includes("Vitalis rotation") && !p._feedingOverview().includes("Set your Vitalis rotation"), "simple mode retains compact status without opening settings");
  data.days = 7; p._feedingState().days = 7;
  assert(p._feedingOverview().includes("Vitalis rotation"), "history still shows today's rotation guidance");
  const active = rotationSummary(); active.foods.find((f) => f.id === "manual:marine-flake").sources[0].available = false;
  const stock = await panel(active);
  assert(stock._feedingRotationCard().includes("no available source") && stock._feedingRotationCard().includes("week 2 of 6"), "stock shortage does not reset or block the calendar");
});

test("rotation form has native keyboard submission, labelled groups and escaped selectable food IDs", async () => {
  const data = rotationSummary(), evilId = 'manual:x" autofocus onfocus="bad()';
  data.foods.push({ id: evilId, name: "<img src=x onerror=bad()>", unit: "pinch", portion: 1, sources: [{ id: evilId, loggable: true }] });
  const p = await panel(data); p._feedingOpenRotation();
  p._feedingState().draft.startDate = '"><script>bad()</script>';
  const html = p._feedingEditor();
  assert(html.includes('data-feeding-rotation-form') && html.includes('type="submit"') && html.includes('<legend>Marine foods'), "native form supports Enter, checkbox Space and fieldset navigation");
  assert(html.includes('aria-describedby="feeding-rotation-date-help"') && html.includes("Home Assistant notification"), "date semantics and reminder channel are explicit");
  assert(!html.includes("<img") && !html.includes("<script>") && html.includes("&quot; autofocus"), "food names, IDs and dates cannot create HTML");
  const card = p._feedingRotationCard();
  assert(card.includes('href="https://www.vitalisaquatic.uk/feeding-guides"') && card.includes('rel="noopener noreferrer"'), "official guide is a safe external link");
  const handlers = {};
  p.shadowRoot = { addEventListener: (type, handler) => { handlers[type] = handler; } };
  p.addEventListener = () => {};
  p._attachEvents(); let submitted = 0, prevented = 0;
  p._feedingSaveDraft = () => { submitted++; };
  handlers.submit({ target: { matches: () => true }, preventDefault: () => { prevented++; } });
  handlers.submit({ target: { matches: () => false }, preventDefault: () => { prevented++; } });
  assert(submitted === 1 && prevented === 1, "keyboard submit uses the same guarded save path, unrelated forms remain untouched");
  // Opening focus callbacks are deferred, so retain the optional DOM interface for them.
  p.shadowRoot.querySelector = () => null;
});

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

test("culture supplies stay out of usual portions and the new tank-feed chooser", async () => {
  const data = summary();
  data.foods.unshift({ id: "product:f2", name: "Guillard's f/2", unit: "ml", portion: 1,
    tankFeed: false, tankFeedLocked: true, tankFeedReason: "Culture fertiliser: record it in Cultures.", loggable: false,
    sources: [{ id: "shelf:f2", label: "Culture fertiliser", loggable: false, available: false }] });
  data.foods.push({ id: "product:rotifer_feed", name: "Rotifer feed", unit: "ml", portion: 1,
    tankFeed: false, tankFeedReason: "Used for live cultures.",
    sources: [{ id: "shelf:rotifer_feed", loggable: true, available: true }] });
  const p = await panel(data); let writes = 0;
  p._feedingCommand = () => { writes++; };
  const html = p._feedingOverview();
  for (const id of ["product:f2", "product:rotifer_feed"]) {
    assert(!html.includes(`data-action="feeding-overview-quick" data-id="${id}"`), "non-tank supply has no quick button");
    p._feedingQuick(id);
  }
  assert(writes === 0, "stale quick taps cannot log excluded supplies even if a source looks available");
  p._feedingOpenEditor();
  const editor = p._feedingEditor();
  assert(p._feedingState().draft.foodId === "brine", "new feed defaults to eligible tank food");
  assert(!editor.includes('value="product:f2"') && !editor.includes('value="product:rotifer_feed"'), "supplies are absent from the new-feed choices");
  assert(editor.includes('value="manual:flake"'), "ordinary tank foods remain available");
  p._feedingState().manage = true;
  const managed = p._feedingOverview();
  assert(managed.includes("Culture fertiliser: record it in Cultures.") && managed.includes("Review use"), "excluded supplies retain an explained management route");
});

test("excluding a supply does not prevent correcting or undoing its historical tank entry", async () => {
  const data = summary();
  data.foods.push({ id: "product:f2", name: "Guillard's f/2", unit: "ml", portion: 1,
    tankFeed: false, tankFeedLocked: true, loggable: false,
    sources: [{ id: "shelf:f2", label: "Culture fertiliser", loggable: false, available: false }] });
  data.rows.push({ id: "old-f2", foodId: "product:f2", name: "Guillard's f/2", unit: "ml", amount: 1,
    sourceId: "shelf:f2", sourceLabel: "Culture fertiliser", at: "2026-11-01T11:25:00Z", date: data.date,
    time: "11:25", editable: true, undoable: true });
  const p = await panel(data); let sent;
  p._feedingCommand = (message) => { sent = message; };
  const before = JSON.stringify(data.rows);
  p._feedingOpenEditor("", "old-f2");
  assert(p._feedingEditor().includes('value="product:f2" selected'), "historical editor retains the excluded food");
  p._feedingDraftChanged("amount", "0.5", "input"); p._feedingSaveDraft();
  assertEqual(sent, { type: "openreef/feeding_edit", entry_id: "old-f2", amount: .5, at: "2026-11-01T11:25:00.000Z" });
  assert(p._feedingOverviewLog().includes('data-action="feeding-overview-undo" data-id="old-f2"'), "old entry still offers undo");
  p._feedingOverviewAction("undo", { id: "old-f2" });
  assertEqual(sent, { type: "openreef/feeding_undo", entry_id: "old-f2" });
  assert(JSON.stringify(data.rows) === before, "eligibility changes never rewrite historical records locally");
});

test("tank-use preference is explicit while culture fertiliser stays locked", async () => {
  const data = summary();
  data.foods.push({ id: "product:shared", name: "Shared phyto", unit: "ml", portion: 10,
    tankFeed: false, tankFeedReason: "Used for live cultures.", sources: [] });
  data.foods.push({ id: "product:f2", name: "Guillard's f/2", unit: "ml", portion: 1,
    tankFeed: false, tankFeedLocked: true, tankFeedReason: "Culture fertiliser: record it in Cultures.", sources: [] });
  const p = await panel(data); let sent;
  p._feedingCommand = (message) => { sent = message; };
  p._feedingNewFood("product:shared");
  assert(p._feedingEditor().includes("Used for tank feeding"), "purpose is separate from live-food type");
  p._feedingDraftChanged("tankFeed", true); p._feedingSaveDraft();
  assert(sent.food_id === "product:shared" && sent.tank_feed === true, "an intentional shared food may be enabled for tank use");
  assert(!Object.hasOwn(sent, "live"), "changing tank use does not reclassify historical live food");
  p._feedingNewFood("product:f2");
  assert(/data-feeding-draft="tankFeed"[^>]*disabled/.test(p._feedingEditor()), "fertiliser cannot be enabled from the tank-food editor");
  p._feedingDraftChanged("tankFeed", true); p._feedingSaveDraft();
  assert(sent.tank_feed === false, "locked purpose cannot be overwritten by a stale change event");
  p._feedingNewFood();
  assert(p._feedingState().draft.tankFeed === true, "new custom foods default to tank feeding");
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
  assertEqual(sent, { type: "openreef/feeding_food_save", food_id: "manual:flake", name: "Vitalis flake", unit: "pinch", portion: .5, tank_feed: true });
  p._feedingNewFood("brine");
  assert(p._feedingState().draft.native, "native identity is not renamed by preference editor");
  p._feedingDraftChanged("live", true); p._feedingSaveDraft();
  assert(sent.food_id === "brine" && sent.live === true, "native classification is an explicit saved preference");
  p._feedingNewFood(); p._feedingDraftChanged("name", "New flake"); p._feedingSaveDraft();
  assert(sent.live === false, "new foods still send an initial classification");
});

test("renamed shelf presets retain validated culture use before their first save", async () => {
  const p = await panel();
  p._nps.summary.library = [
    { name: "Guillard's f/2", category: "other", feedingUse: "culture_nutrient" },
    { name: "Rotifer feed", category: "phyto", feedingUse: "culture_feed" },
    { name: "Unknown role", feedingUse: "anything_else" },
  ];
  p._npsSyncDoseReminder = p._setDirty = p._recordActivity = () => {};
  for (const key of ["0", "1", "2"]) p._npsAddProduct(key);
  const products = Object.values(p._config.consumables.products);
  products[0].name = "Culture fertiliser bottle A";
  assert(products[0].feedingUse === "culture_nutrient", "renaming cannot lose nutrient purpose");
  assert(products[1].feedingUse === "culture_feed", "culture feed purpose reaches the settings save");
  assert(!Object.hasOwn(products[2], "feedingUse"), "unrecognised preset roles are not copied");
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
