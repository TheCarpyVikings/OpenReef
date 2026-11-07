import { assert, makePanel, runTests, test } from "./_panel_harness.mjs";

async function panelFixture() {
  const panel = await makePanel();
  panel._nps = {summary: {hatchery: {
    history: [{vesselId: "v1", startedAt: "2026-11-05T19:50:00Z", harvestedAt: "2026-11-07T07:50:00Z"}],
    vessels: [{id: "v1", name: "Hatchery 1"}],
    harvestRepair: {canUndo: true, canCorrectEmpty: true, mixedAt: "2026-11-06T10:00:00Z"},
  }}};
  panel._render = () => {};
  panel._npsLoadSummary = async () => {};
  return panel;
}

test("existing harvest offers missed-discard correction with inline confirmation", async () => {
  const panel = await panelFixture();
  const hatch = panel._nps.summary.hatchery;
  hatch.harvestRepair.canUndo = false;
  hatch.harvestRepair.undoReason = "No undo checkpoint is available for this harvest.";
  let html = panel._npsHarvestRepairForm(hatch);
  assert(html.includes("I emptied the container before this harvest"), "repair legacy harvest");
  assert(!html.includes('data-id="undo"'), "do not offer unsupported undo");
  panel._feedingDetailsOpen = {"hatchery-harvest-repair": true};
  panel._npsHarvestRepairBegin("emptied");
  html = panel._npsHarvestRepairForm(hatch);
  assert(html.includes("physically emptied") && html.includes("when that harvest was logged"), "explain truthful clock");
  assert(html.includes("Recorded volume and water use stay unchanged"), "explain correction scope");
  assert(html.includes("Yes, I emptied it") && html.includes("Cancel"), "explicit inline confirmation");
  assert(/<details[^>]* open>/.test(html), "survive live refresh");
});

test("undo explains restored stock and sends the reviewed harvest only once", async () => {
  const panel = await panelFixture();
  const calls = [];
  let release;
  panel._callWS = async (msg) => {
    calls.push(msg);
    await new Promise((resolve) => { release = resolve; });
    return {config: {restored: true}};
  };
  panel._npsHarvestRepairBegin("undo");
  const html = panel._npsHarvestRepairForm(panel._nps.summary.hatchery);
  assert(html.includes("previous batch, container contents and water accounting"), "explain undo");
  const first = panel._npsHarvestRepair("undo");
  await panel._npsHarvestRepair("undo");
  assert(calls.length === 1, "block repeated click while saving");
  assert(calls[0].type === "openreef/nps_harvest_repair" && calls[0].action === "undo", "use repair API");
  assert(calls[0].harvested_at === "2026-11-07T07:50:00Z" && calls[0].vessel_id === "v1", "protect reviewed harvest");
  release();
  await first;
  assert(panel._config.restored && !panel._npsHarvestRepairPending && !panel._npsHarvestRepairReview, "complete once");
});

test("demo unsaved settings cancellation and changed harvest cannot submit", async () => {
  for (const reason of ["demo", "dirty", "cancel", "changed", "clock", "unavailable"]) {
    const panel = await panelFixture();
    panel._npsHarvestRepairBegin("emptied");
    if (reason === "demo") panel._nps.demo = true;
    if (reason === "dirty") panel._configDirty = true;
    if (reason === "cancel") panel._npsHarvestRepairReview = "";
    if (reason === "changed") panel._nps.summary.hatchery.history[0].harvestedAt = "changed";
    if (reason === "clock") panel._nps.summary.hatchery.harvestRepair.mixedAt = "changed";
    if (reason === "unavailable") panel._nps.summary.hatchery.harvestRepair.canCorrectEmpty = false;
    let submitted = false;
    panel._callWS = async () => { submitted = true; };
    await panel._npsHarvestRepair("emptied");
    assert(!submitted, reason);
    assert(panel._npsHarvestRepairForm(panel._nps.summary.hatchery).includes("Correct or undo latest harvest"), "form still renders");
  }
});

test("backend refusal stays visible and does not report success", async () => {
  const panel = await panelFixture();
  panel._npsHarvestRepairBegin("undo");
  panel._callWS = async () => { throw new Error("Stock changed; refresh first."); };
  await panel._npsHarvestRepair("undo");
  assert(panel._nps.error === "Stock changed; refresh first." && !panel._nps.message, "show refusal");
  assert(!panel._npsHarvestRepairPending, "allow recovery");
});

test("linked pump harvest never overwrites the server's retained container clock", async () => {
  const panel = await panelFixture();
  panel._config = {nps: {feedExchange: {channelId: "brine"}}};
  const calls = [];
  panel._callWS = async (msg) => { calls.push(msg); return {}; };
  await panel._npsHatchLoaded("v1");
  assert(calls.length === 1 && calls[0].type === "openreef/nps_hatch_cancel", "one atomic harvest; no separate refresh stamp");
});

await runTests();
