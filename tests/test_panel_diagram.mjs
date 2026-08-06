/**
 * Living tank diagram: node resolution, flow gating, slot layout and the
 * wall-side control funnel.
 *
 * The diagram is a wall display of the user's REAL plumbing, so the failure
 * modes worth pinning are truth failures: a loop that keeps "flowing" after the
 * return pump stopped, gear appearing that the user never mapped, a stored
 * layout slot that no longer exists crashing the scene, or the two-step wall
 * toggle firing for unarmed equipment. Styling is not asserted — judgement is.
 *
 * Run standalone:  node tests/test_panel_diagram.mjs
 */

import { assert, assertEqual, makePanel, runTests, test } from "./_panel_harness.mjs";

function prep(panel, states = {}, patch = {}) {
  panel._hass = { states };
  panel._diagramArranging = false;
  panel._pulseDiagArm = null;
  panel._pulseFocus = null;
  panel._pulseFocusTrend = { key: "", range: "", points: null, loading: false };
  return Object.assign(panel, patch);
}

const sw = (state) => ({ state, attributes: {} });

const RIG = {
  equipment: {
    ret: { label: "Return Pump", type: "return_pump", switch_entity_id: "switch.ret", armed: true },
    wave_l: { label: "Wave Left", type: "display_wavemaker", switch_entity_id: "switch.wl" },
    wave_r: { label: "Wave Right", type: "display_wavemaker", switch_entity_id: "switch.wr" },
    heat: { label: "Heater", type: "heater", switch_entity_id: "switch.heat" },
    skim: { label: "Skimmer", type: "skimmer", switch_entity_id: "switch.skim" },
    topoff: { label: "ATO", type: "ato", switch_entity_id: "switch.ato" },
    light: { label: "AI Prime", type: "lighting", switch_entity_id: "switch.light" },
    ghost: { label: "Unmapped Probe" }, // no switch -> must not render
  },
  dosing: { enabled: true, channels: {
    ch1: { name: "Alk", chemical: "alk", enabled: true },
    ch2: { name: "Ca", chemical: "ca", enabled: true },
  } },
  diagram: { systemType: "sump", allowControls: true, layout: {} },
};

const ALL_ON = {
  "switch.ret": sw("on"), "switch.wl": sw("on"), "switch.wr": sw("on"),
  "switch.heat": sw("on"), "switch.skim": sw("on"), "switch.ato": sw("on"), "switch.light": sw("on"),
};

// --- node resolution -------------------------------------------------------

test("nodes come from the equipment mapping; unmapped gear never renders", async () => {
  const panel = prep(await makePanel(structuredClone(RIG)), ALL_ON);
  const nodes = panel._diagramNodes();
  assertEqual(nodes.ret[0], "ret");
  assertEqual(nodes.wavemakers.map(([id]) => id), ["wave_l", "wave_r"]);
  assertEqual(nodes.heater[0], "heat");
  assertEqual(nodes.skimmer[0], "skim");
  assertEqual(nodes.ato[0], "topoff");
  assertEqual(nodes.light[0], "light");
  assertEqual(nodes.doser.length, 2, "dosing channels become the station heads");
  const svg = panel._pulseDiagramSvg();
  assert(!svg.includes("Unmapped Probe"), "switchless gear stays off the diagram");
});

test("dosing disabled or empty -> no dosing station node", async () => {
  const noDose = prep(await makePanel({ ...structuredClone(RIG), dosing: { enabled: false, channels: { ch1: { name: "Alk" } } } }), ALL_ON);
  assertEqual(noDose._diagramNodes().doser, null);
  const empty = prep(await makePanel({ ...structuredClone(RIG), dosing: { enabled: true, channels: {} } }), ALL_ON);
  assertEqual(empty._diagramNodes().doser, null);
});

// --- the core promise: flow follows the pumps ------------------------------

// The stylesheet inside the SVG always mentions dg-loop-off in its selectors,
// so the honest probe is the ROOT element's class attribute, not the string.
const rootClass = (svg) => (svg.match(/<svg[^>]*class="([^"]*)"/) || [])[1] || "";

test("return pump ON -> loop flows; OFF or unavailable -> loop stops", async () => {
  const on = prep(await makePanel(structuredClone(RIG)), ALL_ON);
  assert(!rootClass(on._pulseDiagramSvg()).includes("dg-loop-off"), "loop animates while the return runs");
  const off = prep(await makePanel(structuredClone(RIG)), { ...ALL_ON, "switch.ret": sw("off") });
  assert(rootClass(off._pulseDiagramSvg()).includes("dg-loop-off"), "loop halts when the return stops");
  const gone = prep(await makePanel(structuredClone(RIG)), { ...ALL_ON, "switch.ret": sw("unavailable") });
  assert(rootClass(gone._pulseDiagramSvg()).includes("dg-loop-off"), "an unavailable pump is not claimed to be pumping");
});

test("no return pump mapped -> the diagram never pretends water is moving", async () => {
  const cfg = structuredClone(RIG);
  delete cfg.equipment.ret;
  const panel = prep(await makePanel(cfg), ALL_ON);
  assert(rootClass(panel._pulseDiagramSvg()).includes("dg-loop-off"), "unmeasured loop reads as stopped, not flowing");
});

test("a stopped wavemaker only dims its own node — the loop keeps running", async () => {
  const panel = prep(await makePanel(structuredClone(RIG)), { ...ALL_ON, "switch.wl": sw("off") });
  const svg = panel._pulseDiagramSvg();
  assert(!rootClass(svg).includes("dg-loop-off"), "loop unaffected by a wavemaker");
  assert(/dg-node dg-wm off/.test(svg), "the stopped wavemaker carries the off state");
  assert(/dg-node dg-wm on/.test(svg), "the running wavemaker stays on");
});

// --- both system types render ---------------------------------------------

test("sump scene shows sump chambers; AiO shows back chambers instead", async () => {
  const sump = prep(await makePanel(structuredClone(RIG)), ALL_ON);
  const sumpSvg = sump._pulseDiagramSvg();
  assert(sumpSvg.includes(">refugium<") && sumpSvg.includes(">sock<"), "sump chamber labels present");
  const cfg = structuredClone(RIG);
  cfg.diagram.systemType = "aio";
  const aio = prep(await makePanel(cfg), ALL_ON);
  const aioSvg = aio._pulseDiagramSvg();
  assert(aioSvg.includes(">media<") && !aioSvg.includes(">refugium<"), "AiO draws back chambers, not a sump");
  assert(aioSvg.includes("all-in-one"), "aria label says what it is");
});

// --- layout slots ----------------------------------------------------------

test("stored layout moves gear; junk slot ids fall back without crashing", async () => {
  const cfg = structuredClone(RIG);
  cfg.diagram.layout = { heater: "weir", "wm:wave_l": "glassC", doser: "leftShelf" };
  const panel = prep(await makePanel(cfg), ALL_ON);
  const layout = panel._diagramResolvedLayout("sump", panel._diagramNodes());
  assertEqual(layout.heater, "weir");
  assertEqual(layout["wm:wave_l"], "glassC");
  assertEqual(layout.doser, "leftShelf");
  const junk = structuredClone(RIG);
  junk.diagram.layout = { heater: "the-moon", "wm:wave_l": "weir" }; // wrong kind too
  const fallback = prep(await makePanel(junk), ALL_ON);
  const resolved = fallback._diagramResolvedLayout("sump", fallback._diagramNodes());
  assertEqual(resolved.heater, "sumpReturn", "unknown slot falls back to the default");
  assertEqual(resolved["wm:wave_l"], "glassL", "wrong-kind slot falls back too");
  assert(fallback._pulseDiagramSvg().length > 1000, "scene still renders");
});

test("two wavemakers can never stack on one slot", async () => {
  const cfg = structuredClone(RIG);
  cfg.diagram.layout = { "wm:wave_l": "glassR", "wm:wave_r": "glassR" };
  const panel = prep(await makePanel(cfg), ALL_ON);
  const layout = panel._diagramResolvedLayout("sump", panel._diagramNodes());
  assert(layout["wm:wave_l"] !== layout["wm:wave_r"], "collision resolved to distinct slots");
});

test("arrange mode draws drop zones; normal mode draws none", async () => {
  const panel = prep(await makePanel(structuredClone(RIG)), ALL_ON);
  assert(!panel._pulseDiagramSvg().includes("data-diag-slot"), "no slots while viewing");
  panel._diagramArranging = true;
  const editing = panel._pulseDiagramSvg();
  assert(editing.includes('data-diag-slot="weir"') && editing.includes('data-diag-slot="leftShelf"'), "slots visible while arranging");
});

// --- wall-side control funnel ----------------------------------------------

test("wall toggle is two-step and only ever calls the safety funnel once", async () => {
  const calls = [];
  const panel = prep(await makePanel(structuredClone(RIG)), ALL_ON, {
    _toggleEquipment: (id) => calls.push(id),
    _renderPulseFocus: () => {},
  });
  panel._pulseDiagramToggle("ret");
  assertEqual(calls, [], "first tap only arms the confirm");
  assert(panel._pulseDiagArm && panel._pulseDiagArm.id === "ret");
  panel._pulseDiagramToggle("ret");
  assertEqual(calls, ["ret"], "second tap fires exactly one toggle");
  assertEqual(panel._pulseDiagArm, null, "confirm state cleared after firing");
});

test("unarmed equipment and controls-off walls never reach the toggle", async () => {
  const calls = [];
  const cfg = structuredClone(RIG);
  cfg.equipment.heat.armed = false;
  const panel = prep(await makePanel(cfg), ALL_ON, { _toggleEquipment: (id) => calls.push(id), _renderPulseFocus: () => {} });
  panel._pulseDiagramToggle("heat");
  panel._pulseDiagramToggle("heat");
  assertEqual(calls, [], "unarmed gear cannot be toggled from the wall");
  const lockedCfg = structuredClone(RIG);
  lockedCfg.diagram.allowControls = false;
  const locked = prep(await makePanel(lockedCfg), ALL_ON, { _toggleEquipment: (id) => calls.push(id), _renderPulseFocus: () => {} });
  locked._pulseDiagramToggle("ret");
  locked._pulseDiagramToggle("ret");
  assertEqual(calls, [], "controls-off wall is genuinely look-but-don't-touch");
});

test("equipment focus card: armed gear offers the safety-checked toggle, unarmed explains itself", async () => {
  const panel = prep(await makePanel(structuredClone(RIG)), ALL_ON);
  panel._pulseFocus = "equip:ret";
  const armedHtml = panel._pulseFocusMarkup();
  assert(armedHtml.includes("Return Pump"), "label shown");
  assert(armedHtml.includes('data-action="diagram-toggle"'), "armed gear gets the control");
  assert(armedHtml.includes("halts all flow"), "return pump card explains the consequence");
  panel._pulseFocus = "equip:heat"; // not armed in RIG
  const unarmedHtml = panel._pulseFocusMarkup();
  assert(!unarmedHtml.includes('data-action="diagram-toggle"'), "unarmed gear is read-only");
  assert(unarmedHtml.includes("Not armed"), "and says why");
  panel._pulseFocus = "equip:ghost-no-such";
  assertEqual(panel._pulseFocusMarkup(), "", "removed equipment renders no card");
});

test("doser focus card lists every channel with its chemical", async () => {
  const panel = prep(await makePanel(structuredClone(RIG)), ALL_ON);
  panel._pulseFocus = "doser-station";
  const html = panel._pulseFocusMarkup();
  assert(html.includes("Alk") && html.includes("Ca"), "channels listed");
  assert(html.includes("2 channels"), "count in the header");
});

// --- live patching ---------------------------------------------------------

test("state patching toggles classes in place — flow animations never restart", async () => {
  const panel = prep(await makePanel(structuredClone(RIG)), ALL_ON);
  const classes = new Map();
  const fakeNode = (key) => ({
    getAttribute: () => key,
    classList: { toggle: (cls, on) => classes.set(`${key}:${cls}`, on) },
  });
  const svg = {
    classList: { toggle: (cls, on) => classes.set(`svg:${cls}`, on) },
    querySelectorAll: () => [fakeNode("equip:ret"), fakeNode("equip:wave_l"), fakeNode("doser-station")],
  };
  panel._hass = { states: { ...ALL_ON, "switch.ret": sw("off") } };
  panel._updatePulseDiagram(svg);
  assertEqual(classes.get("svg:dg-loop-off"), true, "loop gate follows the live return state");
  assertEqual(classes.get("equip:ret:off"), true);
  assertEqual(classes.get("equip:wave_l:on"), true);
  assertEqual(classes.get("doser-station:on"), true);
});

// --- AWC on the wall --------------------------------------------------------

// Preps for AWC cases pin the summary and mark it "loading" so the diagram's
// keep-warm kick can never fire a real websocket call inside a test.
function awcRig(status = "idle", summaryPatch = {}, live = {}) {
  const cfg = structuredClone(RIG);
  cfg.automaticWaterChange = { enabled: true, sumpEnabled: true, pumps: { drain: {}, fill: {} }, reservoirs: { fresh: {}, waste: {} } };
  return [cfg, {
    _awcSummaryLoading: true,
    _awcSummaryAt: Date.now(),
    _awcSummary: {
      state: { status, targetLitres: 10, movedMl: { drain: 4200, fill: 2600 } },
      summary: { reservoirs: { fresh: { percent: 55, remainingL: 11 }, waste: { percent: 30, filledL: 6.2 }, ...summaryPatch } },
      live,
    },
  }];
}

test("AWC nodes render only when the feature is enabled", async () => {
  const off = prep(await makePanel(structuredClone(RIG)), ALL_ON);
  assert(!off._pulseDiagramSvg().includes('data-diag-node="awc-station"'), "no AWC gear without the feature");
  const [cfg, patch] = awcRig();
  const on = prep(await makePanel(cfg), ALL_ON, patch);
  const svg = on._pulseDiagramSvg();
  assert(svg.includes('data-diag-node="awc-station"'), "AWC station present");
  assert(svg.includes(">fresh<") && svg.includes(">waste<"), "both reservoirs labelled");
  cfg.automaticWaterChange.reservoirs.fresh2 = {};
  const multi = prep(await makePanel(cfg), ALL_ON, patch);
  assert(multi._pulseDiagramSvg().includes("fresh ×2"), "second source shows as fresh ×2");
});

test("change status drives the drain/fill animation classes", async () => {
  for (const [status, drain, fill] of [["draining", true, false], ["filling", false, true], ["exchanging", true, true], ["idle", false, false]]) {
    const [cfg, patch] = awcRig(status);
    const panel = prep(await makePanel(cfg), ALL_ON, patch);
    const cls = rootClass(panel._pulseDiagramSvg());
    assertEqual(cls.includes("dg-awc-draining"), drain, `${status}: drain class`);
    assertEqual(cls.includes("dg-awc-filling"), fill, `${status}: fill class`);
  }
});

test("reservoir levels come from the summary and clamp to 0-100", async () => {
  const [cfg, patch] = awcRig();
  const panel = prep(await makePanel(cfg), ALL_ON, patch);
  // sump fresh canister: h 204 -> inner 196; 55% -> 108 tall
  assert(/height="108"[^>]*data-diag-awc-level="fresh"/.test(panel._pulseDiagramSvg()), "fresh level scales with percent");
  const [cfg2, patch2] = awcRig("idle", { fresh: { percent: 250, remainingL: 99 } });
  const over = prep(await makePanel(cfg2), ALL_ON, patch2);
  assert(/height="196"[^>]*data-diag-awc-level="fresh"/.test(over._pulseDiagramSvg()), "over-100 clamps to full");
});

test("awc focus card: Stop only while water moves; faults name themselves", async () => {
  const [cfg, patch] = awcRig("draining");
  const running = prep(await makePanel(cfg), ALL_ON, patch);
  running._pulseFocus = "awc-station";
  const html = running._pulseFocusMarkup();
  assert(html.includes('data-action="awc-abort"'), "running change offers Stop");
  assert(html.includes("4.20 out"), "progress shows drained litres");
  const [cfg2, patch2] = awcRig("idle");
  const idle = prep(await makePanel(cfg2), ALL_ON, patch2);
  idle._pulseFocus = "awc-station";
  assert(!idle._pulseFocusMarkup().includes('data-action="awc-abort"'), "idle card has no Stop");
  const [cfg3, patch3] = awcRig("idle", {}, { leak: true });
  const leak = prep(await makePanel(cfg3), ALL_ON, patch3);
  leak._pulseFocus = "awc-station";
  assert(leak._pulseFocusMarkup().includes("Leak detected"), "fault carries into the pill");
});

// --- the Diagram tab --------------------------------------------------------

test("diagram is a first-class tab that routes its own content", async () => {
  const panel = prep(await makePanel(structuredClone(RIG)), ALL_ON, { _activeTab: "diagram" });
  assert(panel._tabs().includes('data-id="diagram"'), "tab button present");
  const content = panel._activeContent();
  assert(content.includes("data-pulse-diagram-svg"), "tab renders the living schematic");
  assert(content.includes('data-action="diagram-arrange"'), "arrange control offered in the tab");
  assert(content.includes('data-action="open-pulse"'), "present hand-off to Reef Pulse offered");
});

test("diagram tab shows the empty-state nudge when nothing is mapped", async () => {
  const panel = prep(await makePanel({ equipment: {}, dosing: { enabled: true, channels: {} }, diagram: {} }), {}, { _activeTab: "diagram" });
  const content = panel._activeContent();
  assert(content.includes("Nothing mapped yet"), "empty state explains where gear comes from");
});

test("hass updates on the diagram tab patch in place, never re-render", async () => {
  const panel = prep(await makePanel(structuredClone(RIG)), ALL_ON, { _activeTab: "diagram", _pulseActive: false });
  assertEqual(panel._shouldRenderForHassUpdate(), false, "diagram tab suppresses the render path");
});

// --- backdrop plumbing -----------------------------------------------------

test("pulse backdrop resolves 'diagram' and the screen mounts the schematic", async () => {
  const cfg = structuredClone(RIG);
  cfg.pulse = { backdrop: "diagram" };
  const panel = prep(await makePanel(cfg), ALL_ON);
  assertEqual(panel._pulseBackdrop(), "diagram");
  const markup = panel._pulseDiagramMarkup();
  assert(markup.includes("data-pulse-diagram") && markup.includes("data-pulse-diagram-svg"), "wrapper + svg present");
});

await runTests();
