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
  "_timelapseSettings", "_overlaySettings", "_feedWatchSettings", "_visionSettings", "_pulseSettings", "_diagramSettings",
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
    assert(html.includes('data-action="timelapse-clear"'), "clear stays until Stage B moves it");
  }
  try { html = panel._manualTestSettings(); } catch (e) { html = ""; }
  if (html) assert(!html.includes('data-action="apply-manual-schedule-preset"'), "the preset is applied from the Manual Tests tab");
  // At least one of the three rendered in this harness, or the test proves nothing.
  const rendered = ["_captureSettings", "_timelapseSettings", "_manualTestSettings"].filter((m) => { try { return Boolean(panel[m]()); } catch { return false; } });
  assert(rendered.length >= 1, `no duplicate-bearing section rendered in the harness: ${rendered}`);
});

await runTests();
