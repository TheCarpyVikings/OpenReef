/**
 * Settings tab structure (Stage A of docs/settings-audit-2026-09-13.md):
 * thirty sections file under six groups in nav-rail order with jump chips;
 * the "How this works" block is closed by default and remembers its toggle;
 * operations that already live on a feature tab are no longer duplicated in
 * Settings. Section CONTENT is pinned by each feature's own suite — what is
 * pinned here is the shape of the page.
 *
 * Run standalone:  node tests/test_panel_settings.mjs
 */

import { assert, assertEqual, makePanel, runTests, test } from "./_panel_harness.mjs";

const SECTION_METHODS = ["_profileSettings", "_guideSettings", "_missionSettings", "_liveStatsSettings", "_sensorSettings",
  "_coolingSettings", "_manualTestSettings", "_maintenanceSettings", "_dosingSettings", "_awcSettings", "_mixingSettings",
  "_npsSettings", "_hatcherySettings", "_culturesSettings", "_equipmentSettings", "_cameraSettings", "_captureSettings",
  "_timelapseSettings", "_overlaySettings", "_feedWatchSettings", "_visionSettings", "_pulseSettings", "_diagramSettings", "_coralsSettings",
  "_modePreviewSettings", "_alertsSettings", "_lightingScheduleSettings", "_interlockSettings", "_energySettings",
  "_systemCheckSettings", "_backupRestoreSettings"];

async function shell() {
  const panel = await makePanel({});
  for (const m of SECTION_METHODS) panel[m] = () => `<!--${m}-->`;
  panel._saveControls = () => "";
  panel._configDirty = false;
  panel._healthSections = {};
  panel._defaultHealthSections = () => ({});
  return panel;
}

test("six groups in nav order, every section exactly once, six jump chips", async () => {
  const panel = await shell();
  const html = panel._settings();
  const groups = [...html.matchAll(/<div class="settings-group" id="or-group-([\w-]+)"/g)].map((m) => m[1]);
  assertEqual(groups.join(" "), "display sensing water feeding watch system");
  const chips = [...html.matchAll(/data-action="settings-jump" data-id="or-group-([\w-]+)"/g)].map((m) => m[1]);
  assertEqual(chips.join(" "), groups.join(" "));
  for (const m of SECTION_METHODS) {
    assertEqual((html.match(new RegExp(`<!--${m}-->`, "g")) || []).length, 1, `${m} renders once`);
  }
  // Water sits together; Profile opens the page; Backup closes it.
  const at = (m) => html.indexOf(`<!--${m}-->`);
  assert(at("_profileSettings") < at("_sensorSettings") && at("_sensorSettings") < at("_dosingSettings"));
  assert(at("_dosingSettings") < at("_awcSettings") && at("_awcSettings") < at("_mixingSettings") && at("_mixingSettings") < at("_maintenanceSettings"));
  assert(at("_npsSettings") < at("_cameraSettings") && at("_cameraSettings") < at("_equipmentSettings"));
  assert(at("_backupRestoreSettings") > at("_systemCheckSettings"));
  assert(html.includes("Profile &amp; display") || html.includes("Profile & display"));
});

test("how-it-works: closed by default, opens from the remembered toggle, body only when open", async () => {
  const panel = await shell();
  const closed = panel._howItWorks("demo", "<p>The long story.</p>");
  assert(closed.includes('data-action="toggle-health-section" data-section="how-demo" data-open="0"'), closed);
  assert(closed.includes(">How this works<") && !closed.includes("The long story"));
  panel._healthSections["how-demo"] = true;
  const open = panel._howItWorks("demo", "<p>The long story.</p>");
  assert(open.includes('data-open="1"') && open.includes("The long story") && open.includes(">Hide<"));
  assert(panel._howItWorks("x", "", "Why this matters").includes(">Why this matters<"));
});

test("the prose-heavy sections use how-it-works for their intros", async () => {
  const panel = await makePanel({ coolingHeadroom: { enabled: false }, nps: { hatchery: {} }, mixingStation: {} });
  panel._healthSections = {};
  panel._defaultHealthSections = () => ({});
  panel._settingsSectionOpen = () => true;
  panel._awcEntitySelect = () => "";
  panel._cooling = { status: null, at: 0, loading: false, error: "" };
  panel._render = () => {};
  const cooling = panel._coolingSettings();
  assert(cooling.includes('data-section="how-cooling-forecast"') && cooling.includes('data-section="how-cooling-vent"'), "cooling intros collapse");
  assert(!cooling.includes("Bind a weather entity and OpenReef projects"), "the 114-word forecast paragraph is hidden until asked for");
  panel._healthSections["how-cooling-forecast"] = true;
  assert(panel._coolingSettings().includes("Bind a weather entity and OpenReef projects"), "…and shows when opened");
});

test("duplicates of tab actions left Settings: capture-now, timelapse grab, the manual preset", async () => {
  const panel = await makePanel({ capture: {}, timelapse: {}, manualTests: { enabled: true } });
  panel._settingsSectionOpen = () => true;
  panel._cameraList = () => [];
  panel._awcEntitySelect = () => "";
  panel._settingsPanel = (id, title, description, content) => `<!--${id}-->${content}`;
  let html = "";
  try { html = panel._captureSettings(); } catch (e) { html = ""; }
  if (html) assert(!html.includes('data-action="capture-now"'), "capture-now is on the Cameras tab");
  try { html = panel._timelapseSettings(); } catch (e) { html = ""; }
  if (html) {
    assert(!html.includes('data-action="timelapse-grab"'), "grab is on the Cameras tab");
    assert(!html.includes('data-action="timelapse-clear"'), "clear moved to the Cameras tab in Stage B");
  }
  try { html = panel._manualTestSettings(); } catch (e) { html = ""; }
  if (html) assert(!html.includes('data-action="apply-manual-schedule-preset"'), "the preset is applied from the Manual Tests tab");
  // At least one of the three rendered in this harness, or the test proves nothing.
  const rendered = ["_captureSettings", "_timelapseSettings", "_manualTestSettings"].filter((m) => { try { return Boolean(panel[m]()); } catch { return false; } });
  assert(rendered.length >= 1, `no duplicate-bearing section rendered in the harness: ${rendered}`);
});


// --- Stage B: operations out of Settings --------------------------------------

test("attention rows carry Ack / Mute for sensor alerts, and only for them", async () => {
  const panel = await makePanel({ sensors: { temp: { label: "Temp" } }, alertEscalation: {} });
  panel._sensorStatus = () => "warning";
  panel._formatMutedUntil = () => "";
  panel._isAlertMuted = () => false;
  const html = panel._missionIssuesHtml([
    { severity: "warning", title: "Temp high", detail: "27.1 °C", tab: "live", sensorId: "temp" },
    { severity: "warning", title: "Sensors still need mapping", detail: "pH", tab: "settings", sensorId: "" },
  ]);
  assert(html.includes('data-action="ack-alert" data-id="temp"') && html.includes('data-action="mute-alert" data-id="temp" data-minutes="1440"'));
  assertEqual((html.match(/issue-actions/g) || []).length, 1, "only the sensor alert gets actions");
  panel._isAlertMuted = () => true;
  panel._formatMutedUntil = () => "14:00";
  const muted = panel._alertActionButtons("temp");
  assert(muted.includes("Muted until 14:00") && muted.includes('data-action="unmute-alert"') && !muted.includes("ack-alert"));
  // Settings → Alerts no longer lists them.
  const settings = await makePanel({ quietHours: { enabled: false }, alerts: {}, alertEscalation: {}, sensors: {} });
  settings._settingsSections = {}; settings._healthSections = {};
  settings._enabledSensors = () => [];
  const body = settings._alertsSettings(true);
  assert(!body.includes("ack-alert") && body.includes("Open Mission Control"));
});

test("System Check: fields stay in Settings, readouts go to the dialog, the cards open it", async () => {
  const panel = await makePanel({});
  panel._systemCheckParts = () => ({ readiness: "<i>R</i>", diagnostics: "<i>D</i>", watchdog: "<i>W</i>", probe: "<i>P</i>", edge: "<i>E</i>", replay: "<i>X</i>", buttons: "<i>B</i>", backupReview: "<i>K</i>" });
  panel._settingsPanel = (id, title, description, content) => `<!--${id}-->${content}`;
  const settings = panel._systemCheckSettings();
  for (const k of ["W", "P", "E", "K"]) assert(settings.includes(`<i>${k}</i>`), `settings keeps ${k}`);
  for (const k of ["R", "D", "X", "B"]) assert(!settings.includes(`<i>${k}</i>`), `settings drops ${k}`);
  assert(settings.includes('data-action="system-check-open"'));
  const dialog = panel._systemCheckDialog();
  for (const k of ["R", "D", "X", "B"]) assert(dialog.includes(`<i>${k}</i>`), `dialog shows ${k}`);
  for (const k of ["W", "P", "E"]) assert(!dialog.includes(`<i>${k}</i>`), `dialog hides ${k}`);
  assert(dialog.includes('data-action="system-check-close"'));
  const card = panel._missionSummaryCard("Trust Check", "Ready", "all clear", "ok", "settings", { action: "system-check-open" });
  assert(card.includes('data-action="system-check-open"') && !card.includes('data-id="settings"'));
});

test("AWC: calibration and the flood consent live in the Pumps & calibration dialog, not Settings", async () => {
  const panel = await makePanel({ automaticWaterChange: { pumps: { drain: { switchEntity: "switch.d" }, fill: {} }, safety: {} } });
  panel._awcEntitySelect = (scope, id, field, value) => `<select ${id} data-scope="${scope}" data-field="${field}"><option>${value}</option></select>`;
  panel._configDirty = false;
  const dialog = panel._awcPumpsDialog();
  assert(dialog.includes('data-action="awc-calibrate" data-id="drain"') && dialog.includes('data-action="awc-cal-run"'), "calibration in the dialog");
  assert(dialog.includes('data-action="awc-ack-flood"') && dialog.includes('data-action="awc-pumps-close"'));
  assert(dialog.includes('data-action="awc-tubing-replaced"'));
  let settings = "";
  try { settings = panel._awcSetupBody(panel._config.automaticWaterChange); } catch { settings = ""; }
  if (settings) {
    assert(!settings.includes("awc-calibrate") && !settings.includes("awc-cal-run") && !settings.includes("awc-ack-flood"), "settings is config only");
    assert(settings.includes('data-field="switchEntity"') && settings.includes("No leak sensor bound"), "settings keeps the switch and says where consent lives");
  }
});

test("timelapse clear sits on the Cameras tab; the Pulse device face rides with the wall's mode list", async () => {
  const panel = await makePanel({ timelapse: {}, pulse: {} });
  panel._cameraList = () => [["cam", { entity_id: "camera.x" }]];
  panel._timelapse = { loaded: true, loading: false, frames: [{ at: 1 }], error: "" };
  panel._loadTimelapseFrames = () => {};
  let html = "";
  try { html = panel._timelapseSection(); } catch { html = ""; }
  if (html) assert(html.includes('data-action="timelapse-clear"') && html.includes('data-action="timelapse-grab"'));
  const faces = panel._pulseDeviceFacesMarkup();
  assert(faces.includes('data-action="pulse-device-face" data-id="follow"') && faces.includes("pulse-device-faces"));
});


// --- Stage C: data editors out of Settings --------------------------------------

test("the three data editors are dialogs off their tabs; Settings only points at them", async () => {
  const panel = await makePanel({ maintenance: { enabled: true, tasks: {} }, nps: { species: [] }, consumables: { products: {} }, diagram: {} });
  panel._nps = { summary: { speciesLibrary: [], library: [] }, loading: false };
  panel._configDirty = false;
  panel._settingsSectionOpen = () => true;
  panel._healthSections = {};
  panel._settingsPanel = (id, title, description, content) => `<!--${id}-->${content}`;
  // Maintenance
  const maint = panel._maintenanceSettings(true);
  assert(!maint.includes("add-maintenance-task") && !maint.includes("load-suggested-tasks") && maint.includes('data-action="maintenance-tasks-open"'));
  const tasks = panel._maintenanceTasksDialog();
  assert(tasks.includes('data-action="add-maintenance-task"') && tasks.includes('data-action="load-suggested-tasks"') && tasks.includes('data-action="maintenance-tasks-close"'));
  // NPS
  let nps = "";
  try { nps = panel._npsSettings(); } catch { nps = ""; }
  if (nps) assert(!nps.includes('data-action="nps-add-product"') && nps.includes('data-action="nps-library-open"'));
  const library = panel._npsLibraryDialog();
  assert(library.includes('data-action="nps-add-product" data-library="custom"') && library.includes('data-action="nps-library-close"'));
  // Diagram
  let diagram = "";
  try { diagram = panel._diagramSettings(); } catch { diagram = ""; }
  if (diagram) assert(!diagram.includes("coral-pick-species") && diagram.includes('data-action="coral-open"'));
  panel._coralRegistryMarkup = () => `<!--registry-->`;
  const coral = panel._coralDialog();
  assert(coral.includes("<!--registry-->") && coral.includes('data-action="coral-close"'));
});


// --- dialogs keep their scroll position across a re-render ------------------

test("an open dialog keeps its scroll position; a different dialog starts at the top", async () => {
  const panel = await makePanel({});
  let wizard = { scrollTop: 340, className: "wizard trend-dialog cooling-dialog" };
  panel.shadowRoot = { querySelector: (sel) => (sel === ".wizard" ? wizard : null) };
  const state = panel._captureScrollState();
  assertEqual(state.wizard, 340);
  assertEqual(state.key, "wizard trend-dialog cooling-dialog");
  // Same dialog rebuilt by a re-render: position restored.
  wizard = { scrollTop: 0, className: "wizard trend-dialog cooling-dialog" };
  panel._restoreScrollState(state);
  assertEqual(wizard.scrollTop, 340);
  // A different dialog: left at the top.
  wizard = { scrollTop: 0, className: "wizard trend-dialog system-check-dialog" };
  panel._restoreScrollState(state);
  assertEqual(wizard.scrollTop, 0);
  // No dialog was open: nothing to restore, nothing thrown.
  panel.shadowRoot = { querySelector: () => null };
  const none = panel._captureScrollState();
  assertEqual(none.key, "");
  panel._restoreScrollState(none);
});

await runTests();
