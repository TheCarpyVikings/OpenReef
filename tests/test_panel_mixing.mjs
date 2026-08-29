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
  assert(found.length >= 6 && found.includes("idle") && found.includes("salting"),
    `could not read MIXING_STATUSES from const.py: got ${JSON.stringify(found)}`);
  return found;
}

function mixConfig(over = {}) {
  return {
    enabled: true,
    layout: "dual",
    vessels: {
      rodi: { volumeLitres: 50, estimatedLitres: 40, levelSensorEntity: "" },
      mix: { volumeLitres: 50, estimatedLitres: 0, contents: "empty", levelSensorEntity: "" },
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
      status: "idle", contents: "empty", litres: 0, remainingLitres: 0,
      stages: ["heating", "salting", "ready", "storing"],
      mix: { percent: null, hoursLeft: null, testUnlocked: false },
      ageDays: null, retestDue: false, loggedPpt: 0,
      ...over.batch,
    },
    levels: over.levels || {
      rodi: { litres: 40, volumeLitres: 50, percent: 80, estimated: true },
      mix: { litres: 0, volumeLitres: 50, percent: 0, contents: "empty", estimated: true },
    },
    dose: over.dose || { available: true, grams: 1950, gPerL: 39.0 },
    mixHours: 2.0,
    brand: { id: "nyos_pure", label: "NYOS Pure", useWithinH: 0 },
    brands: [{ id: "nyos_pure", label: "NYOS Pure" }, { id: "custom", label: "Custom / other" }],
    targetPpt: 35,
    salinityUnit: over.salinityUnit || "ppt",
    targetSg: 1.0264,
    rodi: over.rodi || {
      rateLph: 0, calibratedAt: "", litresProcessed: 0, filterRatedL: 0,
      filterChangedAt: "", filterDue: false, draw: null, calibration: null,
    },
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
  assert(html.includes("Salt &amp; mix") || html.includes("Salt & mix"),
    "progress rail lost the mix stage");
  assert(html.includes("nothing here forces the next step"),
    "an empty idle vessel lost its each-process-on-its-own line");
  noPlaceholders(html, "mixing tab");
});

test("the independent processes surface as their own controls", async () => {
  // Empty vessel, dual: the transfer row is there, Start mixing is not yet.
  const empty = await mixingPanel();
  empty._activeTab = "mixing";
  let html = empty._mixingTab();
  assert(html.includes('data-action="mixing-transfer"'), "idle lost its transfer row");
  assert(!html.includes('data-action="mixing-start"'),
    "an empty vessel offered Start mixing with nothing to mix");
  // RODI water on hand: Start mixing appears with the litres named.
  const rodiWater = await mixingPanel(
    { vessels: { rodi: { volumeLitres: 50, estimatedLitres: 10, levelSensorEntity: "" },
                 mix: { volumeLitres: 50, estimatedLitres: 40, contents: "rodi", levelSensorEntity: "" } } },
    summaryBlob({ batch: { contents: "rodi", remainingLitres: 40 },
                  levels: { rodi: { litres: 10, volumeLitres: 50, percent: 20, estimated: true },
                            mix: { litres: 40, volumeLitres: 50, percent: 80, contents: "rodi", estimated: true } } }));
  rodiWater._activeTab = "mixing";
  html = rodiWater._mixingTab();
  assert(html.includes('data-action="mixing-start"'), "RODI water on hand lost Start mixing");
  assert(html.includes("Start mixing 40"), "Start mixing lost the vessel's litres");
  assert(html.includes("RODI water on hand"), "the card head lost the water-on-hand line");
  // Single layout: no transfer row — the vessel fills from the RODI unit.
  const single = await mixingPanel({ layout: "single" },
    summaryBlob({ levels: { mix: { litres: 0, volumeLitres: 50, percent: 0, contents: "empty", estimated: true } } }));
  single._activeTab = "mixing";
  assert(!single._mixingTab().includes('data-action="mixing-transfer"'),
    "single layout offered a transfer with no store");
});

test("salting offers the dilution transfer; a stored batch does not", async () => {
  const salting = await mixingPanel({ batch: { state: "salting", litres: 40 } },
    summaryBlob({ batch: { status: "salting", contents: "salt", litres: 40, remainingLitres: 40,
                           mix: { percent: 50, hoursLeft: 1.0, testUnlocked: false } } }));
  salting._activeTab = "mixing";
  const html = salting._mixingTab();
  assert(html.includes("dilute"), "salting lost its dilution hint");
  assert(html.includes('data-action="mixing-transfer"'), "salting lost the dilution transfer row");
  const stored = await mixingPanel({ batch: { state: "storing", litres: 40 } },
    summaryBlob({ batch: { status: "storing", contents: "salt", litres: 40, remainingLitres: 40 } }));
  stored._activeTab = "mixing";
  assert(!stored._mixingTab().includes('data-action="mixing-transfer"'),
    "a stored batch offered a transfer over standing saltwater");
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
  assert(html.includes("salinity"), "an unlocked window did not ask for the test");
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

test("each run stage offers exactly its one next action", async () => {
  const expectations = [
    ["heating", "mixing-advance", null],
    ["salting", "mixing-log", "data-mixing-ppt"],
  ];
  for (const [status, action, input] of expectations) {
    const panel = await mixingPanel({ batch: { state: status, litres: 40 } },
      summaryBlob({ batch: { status, contents: "salt", litres: 40, remainingLitres: 40 } }));
    panel._activeTab = "mixing";
    const html = panel._mixingTab();
    assert(html.includes(`data-action="${action}"`), `${status} lost its ${action} button`);
    if (input) assert(html.includes(input), `${status} lost its ${input} input`);
    assert(html.includes('data-action="mixing-abort"'), `${status} lost its stop/discard`);
    noPlaceholders(html, `controls ${status}`);
  }
});

test("stopping heat keeps its own label; discard names the loss; idle empty offers neither", async () => {
  const heating = await mixingPanel({ batch: { state: "heating", litres: 40 } },
    summaryBlob({ batch: { status: "heating", contents: "rodi", litres: 40, remainingLitres: 40 } }));
  heating._activeTab = "mixing";
  assert(heating._mixingTab().includes("Stop heating"),
    "heating's stop must say heating — the water survives it");
  const ready = await mixingPanel({ batch: { state: "ready", litres: 40 } },
    summaryBlob({ batch: { status: "ready", contents: "salt", litres: 40, remainingLitres: 40, loggedPpt: 35.1 } }));
  ready._activeTab = "mixing";
  assert(ready._mixingTab().includes("Discard batch"), "ready batch lost its Discard");
  const idle = await mixingPanel();
  idle._activeTab = "mixing";
  assert(!idle._mixingTab().includes("mixing-abort"), "an empty idle vessel offered a discard");
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

test("a stored batch offers usage, retest and the reminder seed", async () => {
  const panel = await mixingPanel({ batch: { state: "storing", litres: 40 } },
    summaryBlob({ batch: { status: "storing", contents: "salt", litres: 40, remainingLitres: 25 } }));
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

test("level corrections follow the layout — both vessels own a ledger now", async () => {
  const dual = await mixingPanel({ batch: { state: "storing", litres: 40 } },
    summaryBlob({ batch: { status: "storing", contents: "salt", litres: 40, remainingLitres: 40 } }));
  dual._activeTab = "mixing";
  const html = dual._mixingTab();
  assert(html.includes('data-mixing-level="rodi"'), "dual layout lost the RODI correction");
  assert(html.includes('data-mixing-level="mix"'), "the mix vessel lost its correction");
  const idleSingle = await mixingPanel({ layout: "single" },
    summaryBlob({ levels: { mix: { litres: 0, volumeLitres: 50, percent: 0, contents: "empty", estimated: true } } }));
  idleSingle._activeTab = "mixing";
  const idleHtml = idleSingle._mixingTab();
  assert(!idleHtml.includes('data-mixing-level="rodi"'), "single layout offered a phantom RODI correction");
  assert(idleHtml.includes('data-mixing-level="mix"'),
    "an idle vessel can still hold water — its correction must stay");
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

test("settings carries the AWC guard with the stored mode selected", async () => {
  const panel = await mixingPanel();
  const body = panel._mixingSettingsBody(mixConfig({ integrations: { awcGuard: "block", atoFromRodi: false } }));
  assert(body.includes('data-field="awcGuard"'), "settings lost the AWC guard select");
  assert(/value="block"\s+selected/.test(body), "the stored guard mode was not selected");
  noPlaceholders(body, "guard settings");
});

test("the Water hub card reads the vessel ledger", async () => {
  const panel = await mixingPanel({
    batch: { state: "storing", litres: 40 },
    vessels: { rodi: { volumeLitres: 50, estimatedLitres: 40, levelSensorEntity: "" },
               mix: { volumeLitres: 50, estimatedLitres: 25, contents: "salt", levelSensorEntity: "" } },
  });
  const hub = panel._hubTab("water");
  assert(hub.includes("25") && hub.includes("L ready"), "hub card lost the remaining litres");
  assert(hub.includes("tested saltwater on hand"), "hub card lost its vouching line");
  // Plain RODI water on hand tells its own story.
  const rodi = await mixingPanel({
    vessels: { rodi: { volumeLitres: 50, estimatedLitres: 40, levelSensorEntity: "" },
               mix: { volumeLitres: 50, estimatedLitres: 30, contents: "rodi", levelSensorEntity: "" } },
  });
  const rodiHub = rodi._hubTab("water");
  assert(rodiHub.includes("30") && rodiHub.includes("L RODI"), "hub card lost the RODI-on-hand line");
});

test("no mixing action button ever renders classless — the invisible-button regression", async () => {
  // A bare <button> has no panel styling (browser white + inherited light
  // text = unreadable). Every mixing button must carry a class.
  const states = ["idle", "filling", "transferring", "heating", "salting", "ready", "storing"];
  for (const status of states) {
    const panel = await mixingPanel({ batch: { state: status, type: "salt", litres: 40 } },
      summaryBlob({ batch: { status, litres: 40, remainingLitres: 40 } }));
    panel._activeTab = "mixing";
    const html = panel._mixingTab();
    assert(!/<button\s+data-action=/.test(html),
      `${status} rendered a classless (invisible) button`);
  }
});

test("the RODI card offers a draw and a calibration when the unit is quiet", async () => {
  const panel = await mixingPanel();
  panel._activeTab = "mixing";
  const html = panel._mixingTab();
  assert(html.includes("RODI on demand"), "the RODI card lost its title");
  assert(html.includes('data-action="mixing-rodi-draw"'), "the draw button is missing");
  assert(html.includes('data-action="mixing-cal-start"'), "the calibrate button is missing");
  assert(html.includes('value="store"'), "dual layout lost the store destination");
  assert(html.includes('value="external"'), "the T-off destination is missing");
  assert(html.includes("Flow rate unknown"), "an unknown rate must say so, not guess");
  noPlaceholders(html, "rodi card idle");
  // Single vessel: external is the only destination — the vessel fills via a batch.
  const single = await mixingPanel({ layout: "single" },
    summaryBlob({ levels: { mix: { litres: 0, volumeLitres: 50, percent: 0, estimated: true } } }));
  single._activeTab = "mixing";
  const singleHtml = single._mixingTab();
  assert(!singleHtml.includes('value="store"'), "single layout offered a phantom store destination");
  assert(singleHtml.includes('value="external"'), "single layout lost its T-off destination");
});

test("a live draw shows its progress and a Stop — and the diagram runs the right line", async () => {
  const drawSummary = summaryBlob({ rodi: {
    rateLph: 120, calibratedAt: "", litresProcessed: 200, filterRatedL: 0,
    filterChangedAt: "", filterDue: false, calibration: null,
    draw: { litres: 10, destination: "external", litresDone: 5, percent: 50, minutesLeft: 3 },
  } });
  const panel = await mixingPanel({}, drawSummary);
  panel._activeTab = "mixing";
  const html = panel._mixingTab();
  assert(html.includes('data-action="mixing-rodi-stop"'), "a live draw lost its Stop");
  assert(html.includes("5") && html.includes("10"), "the draw progress lost its litres");
  noPlaceholders(html, "rodi card drawing");
  // External run: the T-off flows, the vessel feed does not.
  const extSvg = panel._mixingDiagramSvg(mixConfig(), { status: "idle" },
    summaryBlob().levels, drawSummary.rodi);
  assert(extSvg.includes("T-off"), "an external draw did not draw the T-off");
  assert(extSvg.includes('class="mix-flow"'), "an external draw did not flow");
  // Store draw: flows down the feed line, no T-off.
  const storeSvg = panel._mixingDiagramSvg(mixConfig(), { status: "idle" },
    summaryBlob().levels, { ...drawSummary.rodi, draw: { ...drawSummary.rodi.draw, destination: "store" } });
  assert(!storeSvg.includes("T-off"), "a store draw drew a phantom T-off");
  assert(storeSvg.includes('class="mix-flow"'), "a store draw did not flow the feed line");
  // Quiet unit: nothing flows.
  const quiet = panel._mixingDiagramSvg(mixConfig(), { status: "idle" },
    summaryBlob().levels, summaryBlob().rodi);
  assert(!quiet.includes('class="mix-flow"'), "a quiet RODI unit animated a flow");
});

test("a calibration run asks for the measured litres and jugs the diagram", async () => {
  const calSummary = summaryBlob({ rodi: {
    rateLph: 0, calibratedAt: "", litresProcessed: 0, filterRatedL: 0,
    filterChangedAt: "", filterDue: false, draw: null,
    calibration: { startedAt: "2026-08-28T12:00:00+00:00", elapsedMin: 4.2 },
  } });
  const panel = await mixingPanel({}, calSummary);
  panel._activeTab = "mixing";
  const html = panel._mixingTab();
  assert(html.includes("data-mixing-cal-litres"), "calibration lost its litres input");
  assert(html.includes('data-action="mixing-cal-finish"'), "calibration lost its finish");
  assert(html.includes('data-action="mixing-cal-cancel"'), "calibration lost its cancel");
  noPlaceholders(html, "rodi card calibrating");
  const svg = panel._mixingDiagramSvg(mixConfig(), { status: "idle" },
    summaryBlob().levels, calSummary.rodi);
  assert(svg.includes("measuring jug"), "a calibration run did not label the jug");
});

test("the filter ledger tells its count and shouts only when due", async () => {
  const fine = await mixingPanel({}, summaryBlob({ rodi: {
    rateLph: 100, calibratedAt: "", litresProcessed: 800, filterRatedL: 1500,
    filterChangedAt: "", filterDue: false, draw: null, calibration: null,
  } }));
  fine._activeTab = "mixing";
  let html = fine._mixingTab();
  assert(html.includes("800") && html.includes("1,500") || html.includes("1500"),
    "the ledger lost its litres");
  assert(html.includes('data-action="mixing-filters-changed"'), "the reset button is missing");
  assert(!html.includes("Filter service due"), "an in-life filter must not shout");
  const due = await mixingPanel({}, summaryBlob({ rodi: {
    rateLph: 100, calibratedAt: "", litresProcessed: 1600, filterRatedL: 1500,
    filterChangedAt: "", filterDue: true, draw: null, calibration: null,
  } }));
  due._activeTab = "mixing";
  html = due._mixingTab();
  assert(html.includes("Filter service due"), "a spent filter went unannounced");
});

test("settings carries the filter rating and near-full alert fields", async () => {
  const panel = await mixingPanel();
  const body = panel._mixingSettingsBody(mixConfig({ rodi: {
    rateLph: 0, fillCapMin: 240, filterRatedL: 1500, alertPct: 80, externalVolumeL: 20,
  } }));
  assert(body.includes('data-field="filterRatedL"'), "settings lost the filter rating");
  assert(body.includes('value="1500"'), "the stored rating did not render");
  assert(body.includes('data-field="alertPct"'), "settings lost the near-full alert threshold");
  assert(body.includes('data-field="externalVolumeL"'), "settings lost the T-off container volume");
  assert(body.includes('value="80"') && body.includes('value="20"'),
    "the stored alert settings did not render");
  noPlaceholders(body, "rodi settings");
});

test("an idle tab refetches a stale summary — a settings save elsewhere must reach the dose guide", async () => {
  const panel = await mixingPanel();
  let called = 0;
  panel._mixingLoadSummary = () => { called += 1; };
  panel._mixingSummaryLoading = false;
  panel._mixingSummaryAt = Date.now() - 9000;          // stale cache, idle batch
  panel._activeTab = "mixing";
  panel._mixingTab();
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert(called >= 1, "a stale idle summary was never refetched — vessel edits go unseen");
  called = 0;
  panel._mixingSummaryAt = Date.now();                 // fresh cache: stay quiet
  panel._mixingTab();
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert(called === 0, "a fresh summary was refetched needlessly");
});

const SG_SALT = { brand: "nyos_pure", targetPpt: 35, unit: "sg", mixHours: 0, customGPerL: 0 };

test("the panel's SG anchor cannot drift from mixing.py", async () => {
  const py = fs.readFileSync(path.join(ROOT, "custom_components", "openreef", "mixing.py"), "utf8");
  const anchor = Number(py.match(/REFERENCE_SG\s*=\s*([\d.]+)/)?.[1]);
  assert(anchor > 1.02 && anchor < 1.03, `could not read REFERENCE_SG from mixing.py: ${anchor}`);
  const panel = await mixingPanel({ salt: SG_SALT });
  assert(Math.abs(panel._mixingPptToSg(35) - anchor) < 0.0002,
    "the panel's ppt→SG anchor drifted from the Python");
  assert(Math.abs(panel._mixingSgToPpt(anchor) - 35) < 0.05,
    "the panel's SG→ppt anchor drifted from the Python");
});

test("an SG keeper reads and types SG everywhere on the tab", async () => {
  const panel = await mixingPanel({ salt: SG_SALT },
    summaryBlob({ batch: { status: "salting", litres: 40, remainingLitres: 40,
                           mix: { percent: 50, hoursLeft: 1.0, testUnlocked: false } } }));
  panel._activeTab = "mixing";
  let html = panel._mixingTab();
  assert(html.includes("Measured salinity (SG)"), "the salting input did not speak SG");
  assert(html.includes('step="0.001"'), "the SG input lost its 0.001 step");
  assert(html.includes("1.0264"), "the SG placeholder lost the converted target");
  assert(html.includes("1.0264 SG"), "the dose header did not convert to SG");
  const stored = await mixingPanel({ salt: SG_SALT, batch: { state: "storing", type: "salt", litres: 40 } },
    summaryBlob({ batch: { status: "storing", type: "salt", litres: 40, remainingLitres: 40,
                           loggedPpt: 35.1, loggedSg: 1.0265 } }));
  stored._activeTab = "mixing";
  html = stored._mixingTab();
  assert(html.includes("1.0265 SG"), "a stored batch's tested line did not speak SG");
  noPlaceholders(html, "sg tab");
  const badge = stored._mixingDiagramSvg(mixConfig({ salt: SG_SALT }),
    { status: "ready", type: "salt", loggedPpt: 35.1, loggedSg: 1.0265 }, summaryBlob().levels);
  assert(badge.includes("1.0265"), "the diagram badge did not convert to SG");
});

test("a ppt keeper sees exactly what they always saw", async () => {
  const panel = await mixingPanel({},
    summaryBlob({ batch: { status: "salting", litres: 40, remainingLitres: 40,
                           mix: { percent: 50, hoursLeft: 1.0, testUnlocked: false } } }));
  panel._activeTab = "mixing";
  const html = panel._mixingTab();
  assert(html.includes("Measured salinity (ppt)"), "ppt keepers lost their ppt input");
  assert(html.includes("35.0 ppt"), "the dose header stopped speaking ppt");
});

test("settings offers the unit picker and converts the target box for SG", async () => {
  const panel = await mixingPanel();
  const ppt = panel._mixingSettingsBody(mixConfig());
  assert(ppt.includes('data-field="unit"'), "settings lost the salinity unit picker");
  assert(ppt.includes("Target salinity (ppt)"), "ppt settings lost the ppt target box");
  const sg = panel._mixingSettingsBody(mixConfig({ salt: SG_SALT }));
  assert(sg.includes("Target salinity (SG)"), "sg settings did not convert the target box");
  assert(sg.includes('value="1.0264"'), "the stored 35 ppt did not render as 1.0264 SG");
  noPlaceholders(sg, "sg settings");
});

runTests();
