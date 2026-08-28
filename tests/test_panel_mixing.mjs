/**
 * Mixing Station presentation: how the panel paints the station's state.
 *
 * The batch clocks and dose maths are Python and covered by test_mixing.py.
 * This suite pins the screen's promises: every backend status has an explicit
 * label and a renderable diagram, the diagram draws the layout it was told
 * (dual shows the RODI store, single doesn't), the animations follow the
 * stage, and nothing ever leaks a placeholder. Statuses are read out of
 * const.py's own tuple so backend and panel cannot drift.
 *
 * Renderers schedule a summary refetch when their cache is stale, so
 * `_mixingSummaryLoading` is pinned true — no test may reach for the network.
 *
 * Run standalone:  node tests/test_panel_mixing.mjs
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { assert, makePanel, runTests, test } from "./_panel_harness.mjs";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

/** The statuses the backend is allowed to hand the panel, read from its own tuple. */
function backendStatuses() {
  const source = fs.readFileSync(path.join(ROOT, "custom_components", "openreef", "const.py"), "utf8");
  const block = source.match(/MIXING_STATUSES\s*=\s*\(([\s\S]*?)\)/);
  const found = block ? [...block[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]) : [];
  assert(found.length >= 8 && found.includes("idle") && found.includes("salting"),
    `could not read MIXING_STATUSES from const.py: got ${JSON.stringify(found)}`);
  return found;
}

function mixConfig(over = {}) {
  return {
    enabled: true,
    layout: "dual",
    vessels: {
      rodi: { volumeLitres: 50, estimatedLitres: 40, levelSensorEntity: "" },
      mix: { volumeLitres: 50, levelSensorEntity: "" },
    },
    switches: {
      rodiBooster: { switchEntity: "" }, mixPumpA: { switchEntity: "" },
      mixPumpB: { switchEntity: "" }, heater: { switchEntity: "" },
    },
    rodi: { rateLph: 0, fillCapMin: 240 },
    salt: { brand: "nyos_pure", targetPpt: 35, mixHours: 0, customGPerL: 0 },
    heat: { enabled: true, targetC: 25, tempSensorEntity: "" },
    storage: { circulateEveryH: 6, circulateForMin: 10, retestAfterDays: 7 },
    batch: { state: "idle", type: "salt", litres: 0, usedLitres: 0 },
    ...over,
  };
}

function summaryBlob(over = {}) {
  return {
    enabled: true,
    layout: "dual",
    batch: {
      status: "idle", type: "salt", litres: 0, remainingLitres: 0,
      stages: ["filling", "transferring", "heating", "salting", "ready", "storing"],
      mix: { percent: null, hoursLeft: null, testUnlocked: false },
      ageDays: null, retestDue: false, loggedPpt: 0,
      ...over.batch,
    },
    levels: over.levels || {
      rodi: { litres: 40, volumeLitres: 50, percent: 80, estimated: true },
      mix: { litres: 0, volumeLitres: 50, percent: 0, estimated: true },
    },
    dose: over.dose || { available: true, grams: 1950, gPerL: 39.0 },
    mixHours: 2.0,
    brand: { id: "nyos_pure", label: "NYOS Pure", useWithinH: 0 },
    brands: [{ id: "nyos_pure", label: "NYOS Pure" }, { id: "custom", label: "Custom / other" }],
    targetPpt: 35,
  };
}

async function mixingPanel(config = {}, summary = summaryBlob()) {
  const panel = await makePanel({ mixingStation: mixConfig(config) });
  panel._mixingSummaryLoading = true;  // never let a renderer schedule a fetch
  panel._mixingSummary = summary;
  panel._mixingSummaryAt = Date.now();
  panel._hass = { states: {} };
  return panel;
}

function noPlaceholders(html, where) {
  assert(!/undefined|NaN|Infinity|\[object/.test(html), `${where} leaked a placeholder value`);
}

test("every backend status has an explicit label — no silent fallthrough to Idle", async () => {
  const panel = await mixingPanel();
  for (const status of backendStatuses()) {
    const label = panel._mixingStatusLabel(status);
    assert(typeof label === "string" && label.length,
      `status ${status} produced no label`);
    if (status !== "idle") {
      assert(label !== "Idle", `status ${status} fell through to the Idle fallback`);
    }
  }
});

test("every backend status renders a diagram without placeholders", async () => {
  const panel = await mixingPanel();
  for (const status of backendStatuses()) {
    for (const layout of ["dual", "single"]) {
      const svg = panel._mixingDiagramSvg(
        mixConfig({ layout }), { status, type: "salt" }, summaryBlob().levels);
      assert(svg.includes("<svg"), `status ${status}/${layout} rendered no svg`);
      noPlaceholders(svg, `diagram ${status}/${layout}`);
    }
  }
});

test("dual layout draws the RODI store and the transfer valve; single does not", async () => {
  const panel = await mixingPanel();
  const dual = panel._mixingDiagramSvg(mixConfig(), { status: "idle" }, summaryBlob().levels);
  assert(dual.includes("RODI store"), "dual layout lost its RODI store");
  assert(dual.includes("manual ball valve"), "dual layout lost the transfer valve");
  const single = panel._mixingDiagramSvg(
    mixConfig({ layout: "single" }), { status: "idle" },
    { mix: { litres: 0, volumeLitres: 50, percent: 0, estimated: true } });
  assert(!single.includes("RODI store"), "single layout drew a phantom RODI store");
  assert(!single.includes("manual ball valve"), "single layout drew a phantom transfer valve");
});

test("animations follow the stage: fill flows, salting spins and snows", async () => {
  const panel = await mixingPanel();
  const levels = summaryBlob().levels;
  const filling = panel._mixingDiagramSvg(mixConfig(), { status: "filling" }, levels);
  assert(filling.includes("mix-flow"), "filling did not animate the feed line");
  const salting = panel._mixingDiagramSvg(mixConfig(), { status: "salting" }, levels);
  assert(salting.includes("mix-spin"), "salting did not spin the impellers");
  assert(salting.includes("mix-snow"), "salting lost its salt snow");
  const idle = panel._mixingDiagramSvg(mixConfig(), { status: "idle" }, levels);
  assert(!idle.includes('class="mix-flow"'), "idle animated a flow it should not");
});

test("heating glows only when a heater is configured and heating", async () => {
  const panel = await mixingPanel();
  const levels = summaryBlob().levels;
  const heating = panel._mixingDiagramSvg(mixConfig(), { status: "heating" }, levels);
  assert(heating.includes("mix-glow"), "heating did not glow the heater");
  const noHeater = panel._mixingDiagramSvg(
    mixConfig({ heat: { enabled: false } }), { status: "salting" }, levels);
  assert(!noHeater.includes("Heater"), "heat-disabled setup still drew a heater");
});

test("levels drive the fill rectangles; retest and ready badge honestly", async () => {
  const panel = await mixingPanel();
  const svg = panel._mixingDiagramSvg(mixConfig(),
    { status: "storing", type: "salt", retestDue: true },
    summaryBlob().levels);
  assert(svg.includes('height="96"'), "80% RODI level did not draw a 96-tall fill");
  assert(svg.includes("RETEST"), "an aged batch lost its RETEST badge");
  const ready = panel._mixingDiagramSvg(mixConfig(),
    { status: "ready", type: "salt", loggedPpt: 35.1 }, summaryBlob().levels);
  assert(ready.includes("35.1 ppt"), "a tested batch did not show its logged ppt");
});

test("the tab renders idle state with the dose guide and no placeholders", async () => {
  const panel = await mixingPanel();
  panel._activeTab = "mixing";
  const html = panel._mixingTab();
  assert(html.includes("Saltwater Mixing Station"), "tab lost its title");
  assert(html.includes("1,950") || html.includes("1950"), "dose guide lost its grams");
  assert(html.includes("Fill RODI"), "progress rail lost its first stage");
  noPlaceholders(html, "mixing tab");
});

test("salting tab shows the countdown; unlocked window asks for the test", async () => {
  const saltingSummary = summaryBlob({
    batch: { status: "salting", litres: 50, remainingLitres: 50,
             mix: { percent: 50, hoursLeft: 1.0, testUnlocked: false } },
  });
  const panel = await mixingPanel({ batch: { state: "salting", type: "salt", litres: 50 } }, saltingSummary);
  panel._activeTab = "mixing";
  let html = panel._mixingTab();
  assert(/1(\.0)? h left/.test(html), "salting tab lost its countdown");
  const done = summaryBlob({
    batch: { status: "salting", litres: 50, remainingLitres: 50,
             mix: { percent: 100, hoursLeft: 0, testUnlocked: true } },
  });
  panel._mixingSummary = done;
  html = panel._mixingTab();
  assert(html.includes("refractometer"), "an unlocked window did not ask for the test");
});

test("nav gates on the master switch; the Water hub card renders", async () => {
  const on = await mixingPanel();
  const water = on._navGroups().find((g) => g.id === "water");
  assert(water.pages.some(([id]) => id === "mixing"), "enabled station missing from Water group");
  const off = await makePanel({ mixingStation: mixConfig({ enabled: false }) });
  const waterOff = off._navGroups().find((g) => g.id === "water");
  assert(!waterOff.pages.some(([id]) => id === "mixing"), "disabled station still in Water group");
  const hub = on._hubTab("water");
  assert(hub.includes("Mixing Station"), "Water hub lost the mixing card");
  noPlaceholders(hub, "water hub");
});

test("settings body offers the four plugs and keeps the stored brand before the summary lands", async () => {
  const panel = await mixingPanel();
  const body = panel._mixingSettingsBody(mixConfig());
  for (const role of ["rodiBooster", "mixPumpA", "mixPumpB", "heater"]) {
    assert(body.includes(`data-id="${role}"`), `settings lost the ${role} picker`);
  }
  assert(body.includes("nyos_pure"), "settings lost the stored brand");
  noPlaceholders(body, "mixing settings");
  // Before any summary: the stored brand must still render as an option.
  const cold = await makePanel({ mixingStation: mixConfig() });
  cold._mixingSummaryLoading = true;
  cold._hass = { states: {} };
  const coldBody = cold._mixingSettingsBody(mixConfig());
  assert(coldBody.includes('value="nyos_pure"'), "cold settings dropped the stored brand");
});

test("each stage offers exactly its one next action", async () => {
  const expectations = [
    ["idle", "mixing-start", "data-mixing-litres"],
    ["filling", "mixing-advance", null],
    ["transferring", "mixing-advance", "data-mixing-transfer"],
    ["heating", "mixing-advance", null],
    ["salting", "mixing-log", "data-mixing-ppt"],
  ];
  for (const [status, action, input] of expectations) {
    const panel = await mixingPanel({ batch: { state: status, type: "salt", litres: 40 } },
      summaryBlob({ batch: { status, litres: 40, remainingLitres: 40 } }));
    panel._activeTab = "mixing";
    const html = panel._mixingTab();
    assert(html.includes(`data-action="${action}"`), `${status} lost its ${action} button`);
    if (input) assert(html.includes(input), `${status} lost its ${input} input`);
    if (status !== "idle") {
      assert(html.includes('data-action="mixing-abort"'), `${status} lost its abort`);
    }
    noPlaceholders(html, `controls ${status}`);
  }
});

test("a ready batch offers Discard, not Abort — and idle offers no abort at all", async () => {
  const ready = await mixingPanel({ batch: { state: "ready", type: "salt", litres: 40 } },
    summaryBlob({ batch: { status: "ready", litres: 40, remainingLitres: 40, loggedPpt: 35.1 } }));
  ready._activeTab = "mixing";
  assert(ready._mixingTab().includes("Discard batch"), "ready batch lost its Discard");
  const idle = await mixingPanel();
  idle._activeTab = "mixing";
  assert(!idle._mixingTab().includes("mixing-abort"), "idle offered an abort with nothing running");
});

test("the correction message renders where the keeper can read it", async () => {
  const panel = await mixingPanel({ batch: { state: "salting", type: "salt", litres: 40 } },
    summaryBlob({ batch: { status: "salting", litres: 40, remainingLitres: 40 } }));
  panel._activeTab = "mixing";
  panel._mixingMessage = "Low — add about 89 g of salt, let it dissolve, retest.";
  const html = panel._mixingTab();
  assert(html.includes("89 g of salt"), "the correction message did not render");
});

test("simulate mode announces itself on the batch card and in settings", async () => {
  const panel = await mixingPanel({ simulate: true });
  panel._activeTab = "mixing";
  assert(panel._mixingTab().includes("Simulate is on"), "sim mode was silent on the tab");
  const body = panel._mixingSettingsBody(mixConfig({ simulate: true }));
  assert(/data-field="simulate"[^>]*checked/.test(body), "settings lost the armed sim toggle");
});

test("a stored batch offers usage, retest and the reminder seed — RODI batches only usage", async () => {
  const panel = await mixingPanel({ batch: { state: "storing", type: "salt", litres: 40 } },
    summaryBlob({ batch: { status: "storing", type: "salt", litres: 40, remainingLitres: 25 } }));
  panel._activeTab = "mixing";
  let html = panel._mixingTab();
  assert(html.includes("data-mixing-used"), "storing lost its usage input");
  assert(html.includes('data-action="mixing-mark-used"'), "storing lost Log usage");
  assert(html.includes('data-action="mixing-log"'), "storing lost Log retest");
  assert(html.includes('data-action="mixing-add-retest-reminder"'),
    "no reminder task yet — the seed button should offer itself");
  panel._config.maintenance = { tasks: { mixing_retest: { label: "Retest" } } };
  html = panel._mixingTab();
  assert(!html.includes('data-action="mixing-add-retest-reminder"'),
    "task exists — the seed button must stand down");
  const rodi = await mixingPanel({ batch: { state: "ready", type: "rodi", litres: 30 } },
    summaryBlob({ batch: { status: "ready", type: "rodi", litres: 30, remainingLitres: 30 } }));
  rodi._activeTab = "mixing";
  const rodiHtml = rodi._mixingTab();
  assert(rodiHtml.includes("data-mixing-used"), "rodi batch lost its usage input");
  assert(!rodiHtml.includes('data-action="mixing-log"'), "a top-off batch has nothing to retest");
});

test("the storing card tells the circulation rhythm honestly", async () => {
  const still = await mixingPanel({ batch: { state: "storing", type: "salt", litres: 40 } },
    summaryBlob({ batch: { status: "storing", type: "salt", litres: 40, remainingLitres: 40, circulating: false } }));
  still._activeTab = "mixing";
  assert(/stir 10 min every 6 h/.test(still._mixingTab()), "quiet storage lost its cadence line");
  const stirring = await mixingPanel({ batch: { state: "storing", type: "salt", litres: 40 } },
    summaryBlob({ batch: { status: "storing", type: "salt", litres: 40, remainingLitres: 40, circulating: true } }));
  stirring._activeTab = "mixing";
  assert(stirring._mixingTab().includes("Stirring now"), "a live burst went unannounced");
});

test("a circulation burst spins the impellers without salting's snow", async () => {
  const panel = await mixingPanel();
  const svg = panel._mixingDiagramSvg(mixConfig(),
    { status: "storing", type: "salt", circulating: true }, summaryBlob().levels);
  assert(svg.includes('class="mix-spin"'), "the burst did not spin the impellers");
  assert(!svg.includes('class="mix-snow"'), "a storage stir must not snow salt");
});

test("level corrections follow the layout and the batch", async () => {
  const dual = await mixingPanel({ batch: { state: "storing", type: "salt", litres: 40 } },
    summaryBlob({ batch: { status: "storing", litres: 40, remainingLitres: 40 } }));
  dual._activeTab = "mixing";
  const html = dual._mixingTab();
  assert(html.includes('data-mixing-level="rodi"'), "dual layout lost the RODI correction");
  assert(html.includes('data-mixing-level="mix"'), "an active batch lost the mix correction");
  const idleSingle = await mixingPanel({ layout: "single" },
    summaryBlob({ levels: { mix: { litres: 0, volumeLitres: 50, percent: 0, estimated: true } } }));
  idleSingle._activeTab = "mixing";
  const idleHtml = idleSingle._mixingTab();
  assert(!idleHtml.includes('data-mixing-level="rodi"'), "single layout offered a phantom RODI correction");
  assert(!idleHtml.includes('data-mixing-level="mix"'), "idle vessel offered a correction with nothing in it");
});

test("the seed button writes the keeper's retest chore from the storage setting", async () => {
  const panel = await mixingPanel({ storage: { circulateEveryH: 6, circulateForMin: 10, retestAfterDays: 5 } });
  panel._setDirty = () => { panel._dirtied = true; };
  panel._recordActivity = () => {};
  panel._render = () => {};
  panel._mixingSeedRetestReminder();
  const task = panel._config.maintenance.tasks.mixing_retest;
  assert(task && task.enabled === true, "seed did not create the chore");
  assert(task.cadenceDays === 5 && task.criticalAfterDays === 10,
    "cadence did not follow retestAfterDays");
  assert(panel._dirtied, "seeding must mark the config dirty");
});

runTests();
