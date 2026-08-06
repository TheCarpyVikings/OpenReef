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
  assert(!aioSvg.includes(">refugium<") && !aioSvg.includes(">sock<"), "AiO draws back chambers, not a sump");
  // Chamber labels were retired in 0.7.20 — the gear says what each section is.
  assert(!aioSvg.includes(">media<"), "no static chamber captions");
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
    querySelector: () => null,
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

// --- spatial alerts ---------------------------------------------------------

const num = (state, unit = "") => ({ state: String(state), attributes: { unit_of_measurement: unit } });

function alertRig(sensors, states) {
  const cfg = structuredClone(RIG);
  cfg.sensors = sensors;
  return prepAsync(cfg, states);
}
async function prepAsync(cfg, states) {
  const panel = prep(await makePanel(cfg), { ...ALL_ON, ...states });
  panel._sensorMeta = {};
  panel._validation = null;
  panel._lightingWindow = { data: null, loading: false, at: 0 };
  return panel;
}

test("alerts mark only warning/critical sensors, at their physical anchor", async () => {
  const panel = await alertRig({
    temp: { label: "Tank Temp", entity_id: "sensor.t", group: "tank", unit: "°C", min: 24, max: 26, enabled: true },
    leak: { label: "Leak", entity_id: "binary_sensor.leak", group: "safety", kind: "binary", enabled: true },
  }, {
    "sensor.t": num(25.1, "°C"), // in range -> no marker
    "binary_sensor.leak": { state: "on", attributes: { device_class: "moisture" } }, // tripped
  });
  const alerts = panel._diagramAlerts("sump");
  assertEqual(alerts.length, 1, "healthy sensors never get a marker");
  assertEqual(alerts[0].id, "leak");
  assertEqual([alerts[0].x, alerts[0].y], [700, 926], "leak pulses at the cabinet base");
  const svg = panel._pulseDiagramSvg();
  assert(svg.includes("dg-alert critical"), "marker rendered");
  assert(svg.includes('data-diag-alert-key="leak:critical"'), "layer keyed by the alert set");
});

test("alerts sort worst-first, cap at three, and stack shared anchors", async () => {
  const chem = (id, label) => [id, { label, entity_id: `sensor.${id}`, group: "chemistry", min: 100, max: 200, enabled: true }];
  const panel = await alertRig(Object.fromEntries([
    chem("alkalinity", "Alk"), chem("calcium", "Ca"), chem("magnesium", "Mg"),
    ["leak", { label: "Leak", entity_id: "binary_sensor.leak", group: "safety", kind: "binary", enabled: true }],
  ]), {
    "sensor.alkalinity": num(999), "sensor.calcium": num(999), "sensor.magnesium": num(999),
    "binary_sensor.leak": { state: "on", attributes: { device_class: "moisture" } },
  });
  // Pure marker behaviour: chips off, so chip dedupe doesn't absorb these.
  panel._config.diagram.showReadings = false;
  const alerts = panel._diagramAlerts("sump");
  assertEqual(alerts.length, 3, "capped at three");
  const ys = alerts.filter((a) => a.x === 420).map((a) => a.y);
  assertEqual(new Set(ys).size, ys.length, "shared chemistry anchor stacks instead of overlapping");
});

test("a sensor already on a chip pulses there — no duplicate marker on top", async () => {
  const sensors = {
    ph: { label: "pH Level", entity_id: "sensor.ph", group: "chemistry", min: 7.9, max: 8.4, enabled: true },
    leak: { label: "Leak", entity_id: "binary_sensor.leak", group: "safety", kind: "binary", enabled: true },
  };
  const states = {
    "sensor.ph": num(7.2),
    "binary_sensor.leak": { state: "on", attributes: { device_class: "moisture" } },
  };
  const chipped = await alertRig(sensors, states);
  const ids = chipped._diagramAlerts("sump").map((a) => a.id);
  assert(!ids.includes("ph"), "chip'd pH raises no marker — the chip tints instead");
  assert(ids.includes("leak"), "leak still gets its spatial marker");
  const noChips = await alertRig(sensors, states);
  noChips._config.diagram.showReadings = false;
  assert(noChips._diagramAlerts("sump").map((a) => a.id).includes("ph"), "chips off -> the marker returns");
});

test("AiO doser drop is a slot: media chamber default, high-flow return by choice", async () => {
  const cfg = structuredClone(RIG);
  cfg.diagram.systemType = "aio";
  const def = prep(await makePanel(cfg), ALL_ON);
  assertEqual(def._diagramResolvedLayout("aio", def._diagramNodes()).doser, "doseMedia");
  assert(def._pulseDiagramSvg().includes("dripping into the media chamber"), "default described");
  cfg.diagram.layout = { doser: "doseReturn" };
  const highFlow = prep(await makePanel(cfg), ALL_ON);
  assertEqual(highFlow._diagramResolvedLayout("aio", highFlow._diagramNodes()).doser, "doseReturn");
  assert(highFlow._pulseDiagramSvg().includes("dripping into the high-flow return chamber"), "kalk-friendly drop described");
  const sump = prep(await makePanel(structuredClone(RIG)), ALL_ON);
  assertEqual(sump._diagramResolvedLayout("sump", sump._diagramNodes()).doser, "rightShelf", "sump keeps its shelf slots");
});

test("room-air readings and the showAlerts gate keep markers off the tank", async () => {
  const roomy = await alertRig({
    room_temp: { label: "Fish Room", entity_id: "sensor.room", group: "room", min: 18, max: 24, enabled: true },
  }, { "sensor.room": num(99) });
  assertEqual(roomy._diagramAlerts("sump").length, 0, "room air has no home on the tank");
  const gatedCfg = structuredClone(RIG);
  gatedCfg.diagram.showAlerts = false;
  gatedCfg.sensors = { leak: { label: "Leak", entity_id: "binary_sensor.leak", group: "safety", kind: "binary", enabled: true } };
  const gated = await prepAsync(gatedCfg, { "binary_sensor.leak": { state: "on", attributes: { device_class: "moisture" } } });
  assertEqual(gated._diagramAlerts("sump").length, 0, "toggle off means no markers at all");
});

// --- probe reading chips ----------------------------------------------------

test("reading chips: probe values only, priority order, capped at four", async () => {
  const mk = (id, label, group, extra = {}) => [id, { label, entity_id: `sensor.${id}`, group, min: 0, max: 100, enabled: true, ...extra }];
  const panel = await prepAsync({ ...structuredClone(RIG), sensors: Object.fromEntries([
    mk("calcium", "Calcium", "chemistry"), mk("temp", "Tank Temp", "tank"),
    mk("ph", "pH", "chemistry"), mk("salinity", "Salinity", "chemistry"),
    mk("alkalinity", "Alkalinity", "chemistry"),
    mk("par", "PAR", "lighting"), mk("room_temp", "Room", "room"),
    ["leak", { label: "Leak", entity_id: "binary_sensor.l", group: "safety", kind: "binary", enabled: true }],
  ]) }, {
    "sensor.calcium": num(50), "sensor.temp": num(25), "sensor.ph": num(8.1),
    "sensor.salinity": num(35), "sensor.alkalinity": num(9),
    "sensor.par": num(200), "sensor.room_temp": num(21),
    "binary_sensor.l": { state: "off", attributes: { device_class: "moisture" } },
  });
  const readings = panel._diagramReadings();
  assertEqual(readings.map((r) => r.id), ["temp", "ph", "salinity", "alkalinity"], "priority order wins; calcium bumped by the cap");
  const svg = panel._pulseDiagramSvg();
  assert(svg.includes('data-diag-chip="temp"'), "chip carries its patch hook");
  assert(!svg.includes('data-diag-chip="par"') && !svg.includes('data-diag-chip="room_temp"'), "PAR and room air stay off the water");
  assert(!svg.includes('data-diag-chip="leak"'), "binary sensors are not readings");
});

test("showReadings off means no chips at all", async () => {
  const cfg = structuredClone(RIG);
  cfg.diagram.showReadings = false;
  cfg.sensors = { temp: { label: "Tank Temp", entity_id: "sensor.t", group: "tank", min: 0, max: 100, enabled: true } };
  const panel = await prepAsync(cfg, { "sensor.t": num(25) });
  assertEqual(panel._diagramReadings().length, 0);
});

// --- living details ---------------------------------------------------------

test("label inference: chiller, UV, reactor, air stone and fuge light get their own art", async () => {
  const cfg = structuredClone(RIG);
  Object.assign(cfg.equipment, {
    chilly: { label: "Hailea Chiller", type: "heater", switch_entity_id: "switch.chill" },
    uv: { label: "UV Steriliser", type: "filtration", switch_entity_id: "switch.uv" },
    gfo: { label: "GFO Reactor", type: "filtration", switch_entity_id: "switch.gfo" },
    bubbler: { label: "Air Pump", type: "air_pump", switch_entity_id: "switch.air" },
    fuge: { label: "Refugium Light", type: "lighting", switch_entity_id: "switch.fuge" },
  });
  const states = { ...ALL_ON, "switch.chill": sw("on"), "switch.uv": sw("on"), "switch.gfo": sw("on"), "switch.air": sw("on"), "switch.fuge": sw("on") };
  const panel = prep(await makePanel(cfg), states);
  const nodes = panel._diagramNodes();
  assertEqual(nodes.chiller[0], "chilly", "chiller split off the heater profile by label");
  assertEqual(nodes.heater[0], "heat", "the real heater keeps its slot");
  assertEqual(nodes.uv[0], "uv");
  assertEqual(nodes.reactor[0], "gfo");
  assertEqual(nodes.air[0], "bubbler");
  assertEqual(nodes.fugelight[0], "fuge", "fuge light split off lighting by label");
  assertEqual(nodes.light[0], "light", "display light unaffected");
  const svg = panel._pulseDiagramSvg();
  for (const kind of ["dg-chiller", "dg-uv", "dg-reactor", "dg-air", "dg-fugelight"]) {
    assert(svg.includes(kind), `${kind} drawn`);
  }
  assert(rootClass(svg).includes("dg-fuge-on"), "fuge glow baked from its switch");
});

test("ATO trickle class follows the ATO switch", async () => {
  const on = prep(await makePanel(structuredClone(RIG)), ALL_ON);
  assert(rootClass(on._pulseDiagramSvg()).includes("dg-ato-on"), "topping-off shows the trickle");
  const off = prep(await makePanel(structuredClone(RIG)), { ...ALL_ON, "switch.ato": sw("off") });
  assert(!rootClass(off._pulseDiagramSvg()).includes("dg-ato-on"), "idle ATO keeps the tube still");
});

test("a dose is only a dose when the counter goes UP", async () => {
  const cfg = structuredClone(RIG);
  cfg.dosing.channels.ch1.driver = { type: "openreef_esphome_stepper", entities: { dosedTodaySensor: "sensor.alk_today" } };
  const classes = new Map();
  const fakeSvg = {
    classList: { toggle: (cls, val) => classes.set(cls, val) },
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  const panel = prep(await makePanel(cfg), { ...ALL_ON, "sensor.alk_today": num(12) });
  panel._updatePulseDiagram(fakeSvg);
  assertEqual(classes.get("dg-dosing"), false, "first sighting seeds the watch, no drip");
  panel._hass = { states: { ...ALL_ON, "sensor.alk_today": num(12) } };
  panel._updatePulseDiagram(fakeSvg);
  assertEqual(classes.get("dg-dosing"), false, "same value, still no drip");
  panel._hass = { states: { ...ALL_ON, "sensor.alk_today": num(16) } };
  panel._updatePulseDiagram(fakeSvg);
  assertEqual(classes.get("dg-dosing"), true, "counter up -> drip burst");
});

test("the return chamber visibly rises while the loop is stopped", async () => {
  const panel = prep(await makePanel(structuredClone(RIG)), ALL_ON);
  const svg = panel._pulseDiagramSvg();
  assert(svg.includes("dg-c4rise"), "level-rise cap present in the sump scene");
});

// --- arrange slots for real-world AiO layouts (0.7.18) ----------------------

test("AiO heater can live in any back chamber, including the last one", async () => {
  const cfg = structuredClone(RIG);
  cfg.diagram.systemType = "aio";
  cfg.diagram.layout = { heater: "ch3" };
  const panel = prep(await makePanel(cfg), ALL_ON);
  const layout = panel._diagramResolvedLayout("aio", panel._diagramNodes());
  assertEqual(layout.heater, "ch3", "return-chamber heater honoured");
  assert(panel._pulseDiagramSvg().length > 1000, "scene renders with the heater in ch3");
});

test("AiO ATO fill point is a slot: middle chamber default, last chamber by choice", async () => {
  const cfg = structuredClone(RIG);
  cfg.diagram.systemType = "aio";
  const def = prep(await makePanel(cfg), ALL_ON);
  assertEqual(def._diagramResolvedLayout("aio", def._diagramNodes()).ato, "atoMid", "default fills the middle chamber");
  assert(def._pulseDiagramSvg().includes("filling the middle chamber"), "tooltip says where it fills");
  cfg.diagram.layout = { ato: "atoEnd" };
  const end = prep(await makePanel(cfg), ALL_ON);
  assertEqual(end._diagramResolvedLayout("aio", end._diagramNodes()).ato, "atoEnd");
  assert(end._pulseDiagramSvg().includes("filling the return chamber"), "re-routed tube described");
  const sump = prep(await makePanel(structuredClone(RIG)), ALL_ON);
  assert(!("ato" in sump._diagramResolvedLayout("sump", sump._diagramNodes())), "sump ATO is not slotted");
});

test("air stone slots per scene: sump return/display, AiO display/beside-the-return", async () => {
  const cfg = structuredClone(RIG);
  cfg.equipment.bubbler = { label: "Air Pump", type: "air_pump", switch_entity_id: "switch.air" };
  const states = { ...ALL_ON, "switch.air": sw("on") };
  const sump = prep(await makePanel(cfg), states);
  assertEqual(sump._diagramResolvedLayout("sump", sump._diagramNodes()).air, "airReturn", "sump default");
  const aioCfg = structuredClone(cfg);
  aioCfg.diagram.systemType = "aio";
  aioCfg.diagram.layout = { air: "airCh3" };
  const aio = prep(await makePanel(aioCfg), states);
  assertEqual(aio._diagramResolvedLayout("aio", aio._diagramNodes()).air, "airCh3");
  assert(aio._pulseDiagramSvg().includes("scrubbing beside the return"), "bubble-scrubbing placement drawn");
  aioCfg.diagram.layout = { air: "sumpReturn" }; // wrong-scene slot id
  const junk = prep(await makePanel(aioCfg), states);
  assertEqual(junk._diagramResolvedLayout("aio", junk._diagramNodes()).air, "airDisplay", "wrong-scene slot falls back");
});

// --- wavemaker sides & bubble scrubbing (0.7.23) ----------------------------

test("wavemakers slot to either wall or the middle, two heights per side", async () => {
  const cfg = structuredClone(RIG);
  cfg.diagram.layout = { "wm:wave_l": "glassL", "wm:wave_r": "glassL2" };
  const both = prep(await makePanel(cfg), ALL_ON);
  const layout = both._diagramResolvedLayout("sump", both._diagramNodes());
  assertEqual(layout["wm:wave_l"], "glassL");
  assertEqual(layout["wm:wave_r"], "glassL2", "same wall, second height");
  const aioCfg = structuredClone(RIG);
  aioCfg.diagram.systemType = "aio";
  aioCfg.diagram.layout = { "wm:wave_l": "glassR" };
  const aio = prep(await makePanel(aioCfg), ALL_ON);
  assertEqual(aio._diagramResolvedLayout("aio", aio._diagramNodes())["wm:wave_l"], "glassR", "AiO right wall exists now");
  assert(aio._pulseDiagramSvg().length > 1000, "scene renders a left-facing unit");
});

test("an AiO tank draws up to three wavemakers", async () => {
  const cfg = structuredClone(RIG);
  cfg.diagram.systemType = "aio";
  cfg.equipment.wave_c = { label: "Wave Mid", type: "display_wavemaker", switch_entity_id: "switch.wc" };
  const panel = prep(await makePanel(cfg), { ...ALL_ON, "switch.wc": sw("on") });
  const svg = panel._pulseDiagramSvg();
  assertEqual((svg.match(/dg-node dg-wm/g) || []).length, 3, "all three drawn");
});

test("bubble scrubbing needs the stone beside the return AND both pumps running", async () => {
  const cfg = structuredClone(RIG);
  cfg.diagram.systemType = "aio";
  cfg.diagram.layout = { air: "airCh3" };
  cfg.equipment.bubbler = { label: "Air Pump", type: "air_pump", switch_entity_id: "switch.air" };
  const on = prep(await makePanel(cfg), { ...ALL_ON, "switch.air": sw("on") });
  assert(rootClass(on._pulseDiagramSvg()).includes("dg-scrub"), "scrubbing rig fogs the display");
  const retOff = prep(await makePanel(structuredClone(cfg)), { ...ALL_ON, "switch.air": sw("on"), "switch.ret": sw("off") });
  assert(!rootClass(retOff._pulseDiagramSvg()).includes("dg-scrub"), "no return, no bubbles in the display");
  const airOff = prep(await makePanel(structuredClone(cfg)), { ...ALL_ON, "switch.air": sw("off") });
  assert(!rootClass(airOff._pulseDiagramSvg()).includes("dg-scrub"), "air pump off, water stays clear");
  const moved = structuredClone(cfg);
  moved.diagram.layout = { air: "airDisplay" };
  const display = prep(await makePanel(moved), { ...ALL_ON, "switch.air": sw("on") });
  assert(!rootClass(display._pulseDiagramSvg()).includes("dg-scrub"), "a display air stone does not fog via the return");
});

test("sump scrubbing: the default return-chamber stone fogs while both run", async () => {
  const cfg = structuredClone(RIG);
  cfg.equipment.bubbler = { label: "Air Pump", type: "air_pump", switch_entity_id: "switch.air" };
  const panel = prep(await makePanel(cfg), { ...ALL_ON, "switch.air": sw("on") });
  const svg = panel._pulseDiagramSvg();
  assert(rootClass(svg).includes("dg-scrub"));
  assert(svg.includes("dg-scrubcloud") && svg.includes("dg-scrubjet"), "mist and cloud layers present");
});

test("live patching flips dg-scrub with the pumps", async () => {
  const cfg = structuredClone(RIG);
  cfg.diagram.systemType = "aio";
  cfg.diagram.layout = { air: "airCh3" };
  cfg.equipment.bubbler = { label: "Air Pump", type: "air_pump", switch_entity_id: "switch.air" };
  const classes = new Map();
  const fakeSvg = {
    classList: { toggle: (cls, val) => classes.set(cls, val) },
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  const panel = prep(await makePanel(cfg), { ...ALL_ON, "switch.air": sw("on") });
  panel._updatePulseDiagram(fakeSvg);
  assertEqual(classes.get("dg-scrub"), true, "scrub follows live state");
  panel._hass = { states: { ...ALL_ON, "switch.air": sw("off") } };
  panel._updatePulseDiagram(fakeSvg);
  assertEqual(classes.get("dg-scrub"), false, "air off clears the fog");
});

// --- Reef Layer: corals on the rockwork (0.7.25) ---------------------------

test("bare rock until corals are registered; registered corals render by zone", async () => {
  const bare = prep(await makePanel(structuredClone(RIG)), ALL_ON);
  assert(!bare._pulseDiagramSvg().includes('class="dg-coral"'), "no corals invented");
  const cfg = structuredClone(RIG);
  cfg.livestock = { corals: {
    stag: { name: "Green Slimer", species: "staghorn", colour: "green", addedAt: "2026-06-01" },
    torchy: { name: "Golden torch", species: "torch", colour: "gold", addedAt: "2026-07-01" },
  } };
  const panel = prep(await makePanel(cfg), ALL_ON);
  const svg = panel._pulseDiagramSvg();
  assertEqual((svg.match(/class="dg-coral"/g) || []).length, 2, "both corals drawn");
  const layout = panel._diagramCoralLayout("sump", panel._diagramCorals());
  assertEqual(layout["coral:stag"], "spsPeak", "SPS takes the crest");
  assertEqual(layout["coral:torchy"], "lpsL", "LPS takes mid-rock");
});

test("coral placement honours stored slots, rejects wrong zones, never stacks", async () => {
  const cfg = structuredClone(RIG);
  cfg.livestock = { corals: {
    a: { species: "zoa", colour: "orange" },
    b: { species: "zoa", colour: "pink" },
  } };
  cfg.diagram.layout = { "coral:a": "softR", "coral:b": "spsPeak" };
  const panel = prep(await makePanel(cfg), ALL_ON);
  const layout = panel._diagramCoralLayout("sump", panel._diagramCorals());
  assertEqual(layout["coral:a"], "softR", "stored slot honoured");
  assertEqual(layout["coral:b"], "softL", "wrong-zone slot falls back to the zone default");
  assert(layout["coral:a"] !== layout["coral:b"], "no stacking");
});

test("a full rock queues corals instead of stacking them", async () => {
  const corals = {};
  for (let i = 0; i < 14; i++) corals[`c${i}`] = { species: "zoa", colour: "purple" };
  const cfg = structuredClone(RIG);
  cfg.livestock = { corals };
  const panel = prep(await makePanel(cfg), ALL_ON);
  const layout = panel._diagramCoralLayout("sump", panel._diagramCorals());
  const placed = Object.values(layout).filter(Boolean);
  assertEqual(new Set(placed).size, placed.length, "every placed coral has its own spot");
  assertEqual(placed.length, 12, "twelve slots filled; the rest wait rather than stack");
  assertEqual((panel._pulseDiagramSvg().match(/class="dg-coral/g) || []).length, 12);
});

test("tapping a coral opens its card; the card knows its story", async () => {
  const cfg = structuredClone(RIG);
  cfg.livestock = { corals: { t: { name: "Golden torch", species: "torch", colour: "gold", addedAt: "2026-07-06" } } };
  const panel = prep(await makePanel(cfg), ALL_ON);
  panel._coralFocus = "t";
  const html = panel._coralModalMarkup();
  assert(html.includes("Golden torch") && html.includes("Torch coral"), "name + species in the tab modal");
  assert(html.includes("in your tank"), "age line present");
  assert(panel._pulseFocusCoralMarkup("t").includes("Golden torch"), "wall card renders too");
});

test("arrange mode offers coral drop zones only for zones in use", async () => {
  const cfg = structuredClone(RIG);
  cfg.livestock = { corals: { z: { species: "zoa", colour: "pink" } } };
  const panel = prep(await makePanel(cfg), ALL_ON);
  panel._diagramArranging = true;
  const svg = panel._pulseDiagramSvg();
  assert(svg.includes('data-diag-slot="softL"'), "soft zone slots offered");
  assert(!svg.includes('data-diag-slot="spsPeak"'), "no SPS slots for a zoa-only reef");
});

// --- Reef Layer slice 2: moonlight, spawning nights, arrivals (0.7.27) ------

test("moonlight follows the display light — and only a mapped one", async () => {
  const lightOff = { ...ALL_ON, "switch.light": sw("off") };
  const off = prep(await makePanel(structuredClone(RIG)), lightOff);
  assert(rootClass(off._pulseDiagramSvg()).includes("dg-night"), "light off -> moonlight");
  const on = prep(await makePanel(structuredClone(RIG)), ALL_ON);
  assert(!rootClass(on._pulseDiagramSvg()).includes("dg-night"), "light on -> full colour");
  const unmapped = structuredClone(RIG);
  delete unmapped.equipment.light;
  const none = prep(await makePanel(unmapped), lightOff);
  assert(!rootClass(none._pulseDiagramSvg()).includes("dg-night"), "no mapped light -> never guesses night");
});

test("spawning night needs the window, the corals, and the dark", async () => {
  const day = 86400000;
  const inWindow = {
    program: { spawnPrediction: {
      windowStart: new Date(Date.now() - day).toISOString().slice(0, 10),
      windowEnd: new Date(Date.now() + day).toISOString().slice(0, 10),
    } },
    at: Date.now(), loading: false,
  };
  const cfg = structuredClone(RIG);
  cfg.spawningProgram = { enabled: true };
  cfg.livestock = { corals: { z: { species: "zoa", colour: "pink" } } };
  const lightOff = { ...ALL_ON, "switch.light": sw("off") };
  const go = prep(await makePanel(cfg), lightOff, { _pulseSpawn: inWindow });
  assert(rootClass(go._pulseDiagramSvg()).includes("dg-spawn"), "window + corals + dark -> bundles");
  const lit = prep(await makePanel(structuredClone(cfg)), ALL_ON, { _pulseSpawn: inWindow });
  assert(!rootClass(lit._pulseDiagramSvg()).includes("dg-spawn"), "lights blazing -> no release");
  const bare = structuredClone(cfg);
  bare.livestock = { corals: {} };
  const empty = prep(await makePanel(bare), lightOff, { _pulseSpawn: inWindow });
  assert(!rootClass(empty._pulseDiagramSvg()).includes("dg-spawn"), "no corals -> nothing to spawn");
  const past = structuredClone(inWindow);
  past.program.spawnPrediction.windowStart = "2026-01-01";
  past.program.spawnPrediction.windowEnd = "2026-01-04";
  const stale = prep(await makePanel(structuredClone(cfg)), lightOff, { _pulseSpawn: past });
  assert(!rootClass(stale._pulseDiagramSvg()).includes("dg-spawn"), "outside the window -> quiet reef");
});

test("a coral added this week shimmers; an old one doesn't", async () => {
  const cfg = structuredClone(RIG);
  cfg.livestock = { corals: {
    fresh: { species: "zoa", colour: "pink", addedAt: new Date().toISOString().slice(0, 10) },
    old: { species: "torch", colour: "gold", addedAt: "2026-01-01" },
  } };
  const panel = prep(await makePanel(cfg), ALL_ON);
  const svg = panel._pulseDiagramSvg();
  assertEqual((svg.match(/dg-coral dg-cnew/g) || []).length, 1, "exactly the newcomer shimmers");
});

test("the starter reef is six real, removable registry entries", async () => {
  const panel = prep(await makePanel(structuredClone(RIG)), ALL_ON, { _setDirty: () => {}, _render: () => {} });
  panel._addStarterReef();
  const corals = panel._config.livestock.corals;
  assertEqual(Object.keys(corals).length, 6);
  assert(Object.values(corals).every((c) => c.name && c.species && c.colour && c.addedAt), "fully-formed entries");
  panel._removeCoral(Object.keys(corals)[0]);
  assertEqual(Object.keys(panel._config.livestock.corals).length, 5, "and they remove like any other");
});

// --- Reef Layer slice 3: species, scapes, colour spacing (0.7.28) -----------

test("the new species know their zones and all sixteen render", async () => {
  const cfg = structuredClone(RIG);
  cfg.livestock = { corals: {
    ham: { species: "hammer", colour: "green" },   // lps
    tab: { species: "table", colour: "purple" },   // sps
    xen: { species: "xenia", colour: "pink" },     // soft
    bird: { species: "birdsnest", colour: "teal" },// sps
  } };
  const panel = prep(await makePanel(cfg), ALL_ON);
  const layout = panel._diagramCoralLayout("sump", panel._diagramCorals());
  const slots = panel._diagramCoralSlots("sump");
  assert(slots[layout["coral:ham"]].kinds.includes("lps"), "hammer lives mid-rock");
  assert(slots[layout["coral:tab"]].kinds.includes("sps"), "table acro takes the crest");
  assert(slots[layout["coral:xen"]].kinds.includes("soft"), "xenia stays low");
  assertEqual((panel._pulseDiagramSvg().match(/class="dg-coral/g) || []).length, 4, "all four drawn");
});

test("scapes move the rock and the slots, but placements survive the switch", async () => {
  const cfg = structuredClone(RIG);
  cfg.livestock = { corals: { s: { species: "staghorn", colour: "green" } } };
  cfg.diagram.layout = { "coral:s": "spsPeak" };
  const island = prep(await makePanel(cfg), ALL_ON);
  const islandSlots = island._diagramCoralSlots("sump");
  const twin = structuredClone(cfg);
  twin.diagram.scape = "twinpeaks";
  const twinPanel = prep(await makePanel(twin), ALL_ON);
  const twinSlots = twinPanel._diagramCoralSlots("sump");
  assert(islandSlots.spsPeak.x !== twinSlots.spsPeak.x, "same id, different rock");
  assertEqual(twinPanel._diagramCoralLayout("sump", twinPanel._diagramCorals())["coral:s"], "spsPeak", "stored slot survives the scape change");
  const slope = structuredClone(cfg);
  slope.diagram.scape = "slope";
  const slopePanel = prep(await makePanel(slope), ALL_ON);
  assert(slopePanel._pulseDiagramSvg().length > 1000, "slope scene renders");
  assert(prep(await makePanel(twin), ALL_ON)._pulseDiagramSvg().length > 1000, "twin peaks scene renders");
  const junk = structuredClone(cfg);
  junk.diagram.scape = "atlantis";
  assertEqual(prep(await makePanel(junk), ALL_ON)._diagramScape(), "island", "unknown scape falls back");
});

test("colour spacing: same-coloured colonies spread across the rock", async () => {
  const cfg = structuredClone(RIG);
  cfg.livestock = { corals: {
    a: { species: "zoa", colour: "pink" },
    b: { species: "zoa", colour: "pink" },
    c: { species: "zoa", colour: "pink" },
  } };
  const panel = prep(await makePanel(cfg), ALL_ON);
  const layout = panel._diagramCoralLayout("sump", panel._diagramCorals());
  const slots = panel._diagramCoralSlots("sump");
  const spots = ["a", "b", "c"].map((k) => slots[layout[`coral:${k}`]]);
  for (let i = 0; i < spots.length; i++) {
    for (let j = i + 1; j < spots.length; j++) {
      assert(Math.hypot(spots[i].x - spots[j].x, spots[i].y - spots[j].y) >= 170,
        "no two pink colonies within neighbour range while free slots remain");
    }
  }
});

test("notes and photo ride the coral card; the wall shows notes read-only", async () => {
  const cfg = structuredClone(RIG);
  cfg.livestock = { corals: { t: { name: "Torchy", species: "torch", colour: "gold", notes: "Frag from Dave", photoUrl: "/local/t.jpg" } } };
  const panel = prep(await makePanel(cfg), ALL_ON);
  panel._coralFocus = "t";
  const modal = panel._coralModalMarkup();
  assert(modal.includes("Frag from Dave") && modal.includes('src="/local/t.jpg"'), "notes + photo in the tab modal");
  assert(modal.includes("data-coral-notes"), "notes editable in place");
  assert(panel._pulseFocusCoralMarkup("t").includes("Frag from Dave"), "wall card carries the notes");
});

test("removing a coral clears its slot from the layout", async () => {
  const cfg = structuredClone(RIG);
  cfg.livestock = { corals: { z: { species: "zoa", colour: "pink" } } };
  cfg.diagram.layout = { "coral:z": "softR" };
  const panel = prep(await makePanel(cfg), ALL_ON, { _setDirty: () => {}, _render: () => {} });
  panel._removeCoral("z");
  assert(!panel._config.livestock.corals.z, "registry entry gone");
  assert(!panel._config.diagram.layout["coral:z"], "layout slot vacated");
});

test("chip labels break at a word, never mid-word", async () => {
  const panel = prep(await makePanel(structuredClone(RIG)), ALL_ON);
  assertEqual(panel._diagChipLabel("Tank Temperature"), "TANK");
  assertEqual(panel._diagChipLabel("pH Level"), "PH LEVEL");
  assertEqual(panel._diagChipLabel("Alkalinity"), "ALKALINITY");
  assertEqual(panel._diagChipLabel("Supercalifragilistic"), "SUPERCALIFRA", "single long word hard-cuts");
  assertEqual(panel._diagChipLabel(""), "");
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
