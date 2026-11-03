import { assert, assertEqual, makePanel, runTests, test } from "./_panel_harness.mjs";

const equipment = { heat: { label: "Inkbird", power_entity_id: "sensor.power", heaterMonitor: { mode: "shared_fan" } } };
function snapshot(over = {}) {
  return { label: "Inkbird", mode: "shared_fan", status: "learning", current: "heating", source: "confirmed",
    reason: "Learning during normal use. No action needed.", watts: 202, cycles: 3, cyclesNeeded: 12, minimumDays: 7,
    powerPercent: null, heatingLoadPercent: 44, coverageHours: 12.3, heatingWhEstimate: 400, coolingWhEstimate: 0,
    unassignedWhEstimate: 0, loads: [], coolingObserved: false, ...over };
}
async function prep(over = {}) {
  const panel = await makePanel({ equipment });
  panel._heaterHealth = { status: { equipment: { heat: snapshot(over) } }, at: Date.now(), error: "" };
  panel._render = () => {};
  return panel;
}

test("setup reuses power and temperature mappings and offers shared controller modes", async () => {
  const panel = await prep();
  const html = panel._heaterMonitorSettings("heat", equipment.heat);
  assert(html.includes('value="shared_fan" selected'));
  assert(html.includes('value="shared_chiller"'));
  assert(html.includes("Arming is not required"));
  assert(!html.includes("minWatts"));
});

test("learning never presents a fabricated efficiency or healthy score", async () => {
  const panel = await prep();
  const html = panel._heaterHealthCards();
  assert(html.includes("3 complete reference cycles"));
  assert(html.includes("12 across 7 days"));
  assert(html.includes("not efficiency or remaining life"));
  assert(!html.includes("100%"));
  assert(html.includes("waiting for normal use or identification"));
});

test("reported percentage and urgent alert render together without hiding urgency", async () => {
  const panel = await prep({ status: "critical", powerPercent: 100, baselineReady: true,
    issue: { title: "Temperature outside range", message: "Check the tank now", severity: "critical" } });
  const html = panel._heaterHealthCards();
  assert(html.includes("Urgent check") && html.includes("100%"));
  assert(html.includes("Check the tank now"));
});

test("ambiguous loads have one-tap identification and are escaped", async () => {
  const panel = await prep({ label: '<img src=x onerror="alert(1)">', loads: [{ id: 'p1"onclick="bad', watts: 12, role: null }] });
  const html = panel._heaterHealthCards();
  assert(!html.includes("<img src=x"));
  assert(html.includes('data-role="heating"') && html.includes('data-role="cooling"') && html.includes('data-role="idle"'));
  assert(!html.includes('data-load="p1"onclick='));
});

test("a failed refresh hides cached health rather than claiming it is current", async () => {
  const panel = await prep({ status: "monitoring", powerPercent: 100 });
  panel._heaterHealth.error = "Connection lost";
  const html = panel._heaterHealthCards();
  assert(html.includes("Connection lost"));
  assert(!html.includes("100%"));
});

test("identification sends only the monitoring action and refreshes displayed status", async () => {
  const panel = await prep();
  const calls = [];
  panel._callWS = async (request) => { calls.push(request); return { equipment: { heat: snapshot({ current: "cooling" }) } }; };
  await panel._heaterRespond("heat", "identify", "p2", "cooling");
  assertEqual(calls, [{ type: "openreef/heater_health_respond", equipmentId: "heat", action: "identify", loadId: "p2", role: "cooling" }]);
  assertEqual(panel._heaterHealth.status.equipment.heat.current, "cooling");
});

test("unsaved mapping edits block baseline responses", async () => {
  const panel = await prep();
  panel._configDirty = true;
  panel._callWS = async () => { throw new Error("must not send"); };
  await panel._heaterRespond("heat", "replaced");
  assert(panel._error.includes("Save your settings"));
});

test("reset preview states what will be relearned and permits cancellation", async () => {
  const panel = await prep();
  panel._heaterReset = { id: "heat", action: "replaced" };
  const html = panel._heaterHealthCards();
  assert(html.includes("identified cooling patterns remain"));
  assert(html.includes('data-action="heater-reset-confirm"'));
  assert(html.includes('data-action="heater-reset-cancel"'));
});

test("failed network fetch is throttled instead of looping on render", async () => {
  const panel = await prep();
  panel._hass = {};
  let calls = 0;
  panel._callWS = async () => { calls++; throw new Error("Offline"); };
  await panel._loadHeaterHealth(true);
  await panel._loadHeaterHealth();
  assertEqual(calls, 1);
  assertEqual(panel._heaterHealth.error, "Offline");
});

await runTests();
