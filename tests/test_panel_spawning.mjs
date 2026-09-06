/**
 * Coral Spawning tab — the reef-picker regression (0.7.75) and the execution strip.
 *
 * The field bug this pins down: the compiler form's selects used to live only in
 * the DOM, so any background re-render (hass pushes arrive every few seconds, and
 * the execution card's status polling re-renders on top) silently snapped the
 * reef picker back to the saved preset BEFORE Generate could read it — Generate
 * then honestly compiled the old reef. The fix binds those fields into config on
 * change; these tests keep that true.
 *
 * Run standalone:  node tests/test_panel_spawning.mjs
 */

import fs from "node:fs";
import { PANEL_PATH, assert, makePanel, runTests, test } from "./_panel_harness.mjs";

const PRESETS = [
  { id: "gbr_central", label: "Great Barrier Reef (Central)", region: "Coral Sea, Australia" },
  { id: "red_sea_aqaba", label: "Red Sea (Gulf of Aqaba)", region: "Northern Red Sea" },
];

const EXEC_STATUS = {
  execution: { mode: "openreef", armed: true, temp: {} },
  state: {
    valid: true, sunrise: "06:30", sunset: "19:30", dayLengthHours: 13,
    moonIlluminationPct: 91, moonPhase: "Waxing gibbous", targetTempC: 27,
    reefDate: "2026-08-24",
    nextTransition: { kind: "sunset", at: "19:30", inMinutes: 60, tomorrow: false },
  },
  entities: {},
  runtime: { controlling: true, health: "ok", lastCompletedAt: "2026-08-24T12:00:00Z", overrides: {}, issues: [] },
};

async function spawningPanel(configOver = {}, spawningOver = {}) {
  const panel = await makePanel({
    spawningProgram: {
      enabled: true, reefPreset: "red_sea_aqaba", offsetMonths: 0, solarNoonHour: 13,
      tempUnit: "C", tempProbe: "Tmp",
      execution: { mode: "openreef", armed: true, temp: {} },
    },
    lightingSchedule: { mode: "off" },
    ...configOver,
  });
  panel._spawning = {
    presets: PRESETS, program: null, loading: false, generating: false, error: "",
    copied: "", execStatus: EXEC_STATUS, execAt: Date.now(), execLoading: false,
    ...spawningOver,
  };
  panel._configDirty = false;
  panel._loadSpawnExecStatus = () => {};  // no network in the harness
  return panel;
}

test("the reef picker renders from SAVED config — config is the source of truth a re-render restores", async () => {
  const panel = await spawningPanel();
  const html = panel._spawningTab();
  assert(/value="red_sea_aqaba" selected/.test(html), "saved reef must render selected");
  assert(!/value="gbr_central" selected/.test(html), "only the saved reef may be selected");
  // The other half of the fix: a changed pick must land in config immediately,
  // so the next render preserves it instead of wiping it.
  panel._config.spawningProgram.reefPreset = "gbr_central";
  const rerender = panel._spawningTab();
  assert(/value="gbr_central" selected/.test(rerender), "a config change must survive a re-render");
});

test("the form fields are BOUND — the input pipeline writes spawn-field edits into config and marks dirty", () => {
  // The regression itself: pre-0.7.75 there was no dataset.spawnField branch, so
  // DOM-only picks were lost to background re-renders before Generate read them.
  const source = fs.readFileSync(PANEL_PATH, "utf8");
  assert(
    /dataset\.spawnField[\s\S]{0,500}spawningProgram[\s\S]{0,300}_setDirty\(true\)/.test(source),
    "handleFieldInput must write data-spawn-field edits into config.spawningProgram and mark dirty"
  );
});

test("unsaved edits flag the execution strip as a stale preview WITH a Save button in reach", async () => {
  const panel = await spawningPanel();
  panel._configDirty = true;
  const html = panel._spawningTab();
  assert(html.includes("Save to refresh this preview"),
    "dirty settings must announce the strip previews older values");
  // Reece's field catch #2: the hint told users to Save, but the tab had no Save
  // button (the app's only one lives on the Settings tab). Dirty must render one.
  assert((html.match(/data-action="save"/g) || []).length >= 1,
    "a dirty spawning tab must offer a Save button");
  panel._configDirty = false;
  const clean = panel._spawningTab();
  assert(!clean.includes("Save to refresh this preview"), "the hint must clear once saved");
  assert(!clean.includes('data-action="save"'), "no Save button when nothing is dirty");
});

test("the execution strip renders the backend status — sunrise, sunset, moon, target", async () => {
  const panel = await spawningPanel();
  const html = panel._spawningTab();
  for (const chip of ["06:30", "19:30", "13 h day", "91%", "target 27°C"]) {
    assert(html.includes(chip), `strip must show ${chip}`);
  }
  assert(html.includes("plug states confirmed"), "confirmed status must show");
  assert(html.includes("Last check:"), "last completed check must show");
});

test("armed alone never appears as confirmed, and faults stay visible", async () => {
  for (const [health, label] of [[undefined, "waiting for first check"], ["stalled", "lighting checks overdue"], ["fault", "check the plugs"], ["override", "manual override"]]) {
    const panel = await spawningPanel({}, { execStatus: {
      ...EXEC_STATUS, runtime: { controlling: true, health, overrides: {}, issues: [] },
    } });
    const html = panel._spawningTab();
    assert(html.includes(label), `must show ${label}`);
    assert(!html.includes("plug states confirmed"), "must not claim confirmation");
  }
});

test("the hybrid setup and deliberate HA override policy are explained", async () => {
  const panel = await spawningPanel();
  const html = panel._spawningTab();
  assert(html.includes("Using Apex for temperature and moonlight?"));
  assert(html.includes("Hold direct HA user changes until the next transition"));
  assert(html.includes("disarm for maintenance"));
});

test("export shows local lunar dates and double-new-moon warnings", async () => {
  const panel = await spawningPanel();
  const html = panel._spawningProgramView({
    params: { year: 2027, timeZone: "Europe/London" },
    spawnPrediction: { fullMoonUtc: "2027-01-01T23:30:00Z", fullMoonLocalDate: "2027-01-02" },
    lunarWarnings: ["2027-08 contains two new moons."],
  });
  assert(html.includes("2027-01-02"));
  assert(html.includes("2027-08 contains two new moons."));
  assert(html.includes("Dates use Europe/London"));
});

test("temperature settings support different sensors and cooling equipment", async () => {
  const panel = await spawningPanel();
  const html = panel._spawningTab();
  assert(html.includes('data-field="staleMinutes"'));
  assert(html.includes('data-field="coolMinOffSeconds"'));
  assert(html.includes("Minimum cooling OFF time"));
  assert(html.includes("independent temperature protection"));
  assert(!html.includes("zero risk"));
  assert(!html.includes("never through the guard's cool socket"));
});

test("pending thermal shutdown remains visible when switching to Apex", async () => {
  const panel = await spawningPanel({}, { execStatus: {
    ...EXEC_STATUS,
    runtime: { controlling: false, health: "fault", tempPendingRelease: ["switch.old_heater"], overrides: {}, issues: ["OFF unconfirmed"] },
  } });
  panel._config.spawningProgram.execution.mode = "apex";
  const html = panel._spawningTab();
  assert(html.includes("temperature shutdown unconfirmed"));
  assert(html.includes("switch.old_heater"));
  assert(!html.includes('class="pill unknown">Apex executes'));
});

await runTests();
