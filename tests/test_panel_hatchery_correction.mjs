import { assert, makePanel, runTests, test } from "./_panel_harness.mjs";

function hatchery() {
  return {
    history: [{ vesselId: "v1", startedAt: "2026-11-02T09:53:00Z", harvestedAt: "2026-11-04T21:41:00Z" }],
    vessels: [
      { id: "v1", name: "Hatchery 1", startedAt: "2026-11-04T09:42:00Z" },
      { id: "v2", name: "Hatchery 2", startedAt: "2026-11-02T22:54:00Z" },
    ],
  };
}

test("correction explains both batch changes and offers the other running hatchery", async () => {
  const panel = await makePanel();
  const html = panel._npsHatchCorrectionForm(hatchery());
  assert(html.includes('value="v2"') && !html.includes('value="v1"'), "only the other hatchery is eligible");
  assert(html.includes("restores Hatchery 1") && html.includes("replacement hatch"), "explain clock restoration");
  assert(html.includes("Food volumes and water use stay unchanged"), "explain ledger preservation");
  assert(!panel._npsHatchCorrectionForm({history: [], vessels: []}), "no history means no correction");
});

test("confirmed correction sends exact observed timestamps and refreshes saved records", async () => {
  const panel = await makePanel();
  const hatch = hatchery();
  panel._nps = {summary: {hatchery: hatch}};
  panel.shadowRoot = {querySelector: () => ({value: "v2"})};
  panel._render = () => {};
  let calls = [], refreshes = 0, confirmation = "";
  panel._callWS = async (msg) => { calls.push(msg); return {config: {corrected: true}}; };
  panel._npsLoadSummary = async () => { refreshes++; };
  const oldConfirm = globalThis.confirm;
  globalThis.confirm = (text) => { confirmation = text; return true; };
  try { await panel._npsHatchCorrectVessel(); } finally { globalThis.confirm = oldConfirm; }
  assert(calls.length === 1 && calls[0].type === "openreef/nps_hatch_correct_vessel", "one correction command");
  assert(calls[0].harvest_started_at === hatch.history[0].startedAt, "protect the journal row");
  assert(calls[0].source_started_at === hatch.vessels[0].startedAt && calls[0].target_started_at === hatch.vessels[1].startedAt, "protect both active batches");
  assert(confirmation.includes("Restore Hatchery 1") && confirmation.includes("Move the replacement start"), "review both effects");
  assert(panel._config.corrected && refreshes === 1 && !panel._npsHatchCorrectionPending, "saved state and fresh forecast");
});

test("cancel, demo, unsaved edits and duplicate clicks cannot send a correction", async () => {
  for (const reason of ["cancel", "demo", "dirty", "pending"]) {
    const panel = await makePanel();
    panel._nps = {summary: {hatchery: hatchery()}, demo: reason === "demo"};
    panel._configDirty = reason === "dirty";
    panel._npsHatchCorrectionPending = reason === "pending";
    panel.shadowRoot = {querySelector: () => ({value: "v2"})};
    panel._render = () => {};
    panel._callWS = () => { throw new Error("must not send"); };
    panel._npsLoadSummary = () => { throw new Error("must not refresh"); };
    const oldConfirm = globalThis.confirm;
    globalThis.confirm = () => false;
    try { await panel._npsHatchCorrectVessel(); } finally { globalThis.confirm = oldConfirm; }
  }
});

await runTests();
