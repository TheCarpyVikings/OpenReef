/**
 * Mission Control aggregation: the Attention list and the counters above it.
 *
 * This is the screen a reefer looks at first, so the contracts that matter are not
 * the arithmetic but the accounting. One real problem must produce one row. A muted
 * or disabled sensor must produce none. A quiet tank must read quiet — and a loud
 * one must not bury the loud part under noise.
 *
 * Everything here is driven through `_missionIssueList` / `_mission`, which are pure
 * given `_config`, `_hass.states` and `_validation`. No shadow root is touched.
 *
 * Run standalone:  node tests/test_panel_attention.mjs
 */

import { assert, assertEqual, freezeTime, makePanel, runTests, test } from "./_panel_harness.mjs";

const NOW = "2026-06-04T09:00:00.000Z";
const iso = (daysAgo) => new Date(Date.parse(NOW) - daysAgo * 86400000).toISOString();

// A tank with nothing wrong with it: one live in-range probe, one armed heater that
// is on and reporting, one maintenance task done yesterday. Each test takes exactly
// one thing away, so any row that appears is attributable to that one thing.
function greenTank(over = {}) {
  return {
    sensors: {
      temp: { label: "Temperature", enabled: true, alertsEnabled: true, entity_id: "sensor.temp", min: 24, max: 27, unit: "°C" },
    },
    equipment: {
      heater: { label: "Heater", armed: true, switch_entity_id: "switch.heater", type: "heater" },
    },
    maintenance: {
      enabled: true,
      tasks: { glass: { label: "Glass clean", enabled: true, cadenceDays: 7, criticalAfterDays: 14, scheduleMode: "interval" } },
      completions: { glass: [{ id: "g", timestamp: iso(1) }] },
    },
    interlocks: {},
    alerts: {},
    display: {},
    activity: [],
    energy: {},
    tank: {},
    ...over,
  };
}

const GREEN_STATES = { "sensor.temp": { state: "25.5" }, "switch.heater": { state: "on" } };

async function mission(config, states = GREEN_STATES, validation = {}) {
  const panel = await makePanel(config);
  // _state/_number read hass directly, so real states beat stubbing the readers.
  panel._hass = { states };
  panel._validation = { missing_entities: [], armed_unavailable: [], ...validation };
  panel._healthSections = {};       // no stored collapse state: defaults apply
  panel._settingsSections = {};
  panel._healthTrends = {};
  // Pre-loaded and not stale, so nothing schedules a lighting fetch mid-test.
  panel._lightingWindow = { data: null, loading: true, at: 0 };
  return panel;
}

const ROW = /<button class="issue-item (\w+)" data-action="tab" data-id="([^"]*)">\s*<span class="pill (\w+)">[^<]*<\/span>\s*<strong>([^<]*)<\/strong>\s*<small>([^<]*)<\/small>/g;
const CARD = /<button class="summary-card (\w+)" data-action="tab" data-id="([^"]*)"[^>]*>\s*<span>([^<]*)<\/span>\s*<strong>([^<]*)<\/strong>\s*<small>([^<]*)<\/small>/g;

function parseRows(html) {
  return [...html.matchAll(ROW)].map(([, severity, tab, pillClass, title, detail]) => ({
    severity, tab, pillClass, title, detail,
  }));
}

/** The Attention list as data: one entry per rendered issue row. */
function rows(panel) {
  const html = issueHtml(panel);
  assertClean(html, "issue list");
  return parseRows(html);
}

function issueHtml(panel) {
  const sensors = panel._enabledSensors();
  return panel._missionIssueList(
    sensors,
    Object.entries(panel._config.equipment || {}),
    panel._sensorAlerts(sensors),
    panel._validation.missing_entities,
    panel._validation.armed_unavailable,
    panel._interlockWarnings(),
  );
}

/**
 * The rendered Attention section of a full `_mission()`, sliced out by id. Reading
 * the pill and the rows from the SAME slice is the point: it proves the counter the
 * user sees and the list underneath it were produced by one screen, not two calls.
 */
function attentionSection(html) {
  const start = html.indexOf('id="or-msection-mission-attention"');
  assert(start > -1, "Mission Control must render an Attention section");
  const end = html.indexOf("</article>", start);
  assert(end > start, "the Attention section must be closed");
  return html.slice(start, end);
}

/**
 * "3 to check" / "all clear" — the pill the user reads without expanding anything,
 * with the colour it is painted in and the number it claims.
 */
function attention(html) {
  const section = attentionSection(html);
  const match = section.match(/<span class="pill (ok|warning|critical)">((\d+) to check|all clear)<\/span>/);
  assert(match, `the Attention section must carry a summary pill: ${section.slice(0, 400)}`);
  return {
    tone: match[1],
    text: match[2],
    count: match[3] === undefined ? 0 : Number(match[3]),
    rows: parseRows(section),
  };
}

/** Back-compat alias for the pill text alone. */
const attentionPill = (html) => attention(html).text;

/** The summary cards above the list, keyed by their label. */
function cards(html) {
  const out = {};
  for (const [, status, tab, label, value, detail] of html.matchAll(CARD)) {
    out[label] = { status, tab, value, detail };
  }
  return out;
}

function card(html, label) {
  const found = cards(html)[label];
  assert(found, `Mission Control must render a "${label}" summary card: got ${Object.keys(cards(html)).join(", ")}`);
  return found;
}

function hero(html) {
  return {
    headline: (html.match(/<h2>([^<]*)<\/h2>/) || [])[1] || "",
    border: (html.match(/<div class="hero ([^"]*)"/) || [])[1] || "",
  };
}

function assertClean(html, where) {
  const leak = (html.match(/undefined|NaN|Infinity|\[object/) || [])[0];
  assert(!leak, `${where} leaked "${leak}" into user-visible markup`);
}

const titled = (list, fragment) => list.filter((row) => row.title.includes(fragment));

// --- one problem, one row -------------------------------------------------------

test("test_a_reading_out_of_range_is_one_critical_row_and_is_counted_once", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await mission(greenTank(), { ...GREEN_STATES, "sensor.temp": { state: "31" } });
    const list = rows(panel);
    assertEqual(list.length, 1, `one overheating probe must not fan out into several rows: ${JSON.stringify(list)}`);
    assertEqual(list[0].severity, "critical", "outside the configured range is critical, not a nudge");
    assertEqual(list[0].tab, "live", "the row must land the user where the reading is");
    assert(list[0].detail.includes("31.0") && list[0].detail.includes("24 - 27"),
      `the row must show the reading and the range it broke: "${list[0].detail}"`);

    const html = panel._mission();
    assertClean(html, "mission");
    const shown = attention(html);
    assertEqual(shown.text, "1 to check", "the counter above the list must agree with the list");
    assertEqual(shown.tone, "critical", "the pill above a critical row must be red, not amber");
    assertEqual(shown.rows.length, shown.count,
      `the rendered rows must match the number the pill claims: ${JSON.stringify(shown.rows)}`);
    assertEqual(shown.rows[0].severity, "critical", "and the rendered row must carry the same severity as the pill");
    assertEqual(hero(html).headline, "Action needed");
    assertEqual(hero(html).border, "danger-border", "a critical reading must colour the hero, not just the row");

    // The Sensors card is the same tally in card form. 1 of 1 sensor mapped, 1 critical.
    assertEqual(card(html, "Sensors").status, "critical", "the Sensors card must go red when a probe is out of range");
    assertEqual(card(html, "Sensors").value, "1/1", "the card reports mapped/enabled sensors");
    assertEqual(card(html, "Sensors").detail, "1 critical · 0 warning", "and spells out the same split as the list");
  } finally {
    restore();
  }
});

test("test_an_unavailable_armed_switch_is_one_critical_row_and_is_counted_once", async () => {
  const restore = freezeTime(NOW);
  try {
    // Present in Home Assistant but offline: this is the everyday failure (smart plug
    // dropped off wifi), and it is the backend's armed_unavailable that reports it.
    const panel = await mission(greenTank(), { ...GREEN_STATES, "switch.heater": { state: "unavailable" } },
      { armed_unavailable: ["switch.heater"] });
    const list = rows(panel);
    assertEqual(list.length, 1, `one dead switch must be one row: ${JSON.stringify(list)}`);
    assertEqual(list[0].severity, "critical", "OpenReef believing it can drive a dead switch is a safety issue");
    assertEqual(list[0].tab, "controls");
    assert(list[0].detail.includes("switch.heater"), `the row must name the entity: "${list[0].detail}"`);

    const html = panel._mission();
    const shown = attention(html);
    assertEqual(shown.text, "1 to check", "counted once, shown once");
    assertEqual(shown.rows.length, 1, "counted once, rendered once");
    assertEqual(shown.tone, "critical", "a dead armed switch is red, not amber");
    // A switch OpenReef thinks it can drive but cannot is exactly as loud as a bad
    // reading: it must reach the hero and the Equipment card, not only the row.
    assertEqual(hero(html).headline, "Action needed", "a dead armed device must escalate the whole screen");
    assertEqual(hero(html).border, "danger-border");
    assertEqual(card(html, "Equipment").status, "critical", "the Equipment card must go red while a device is unreachable");
    assertEqual(card(html, "Equipment").value, "1/1", "the card counts armed of total equipment");
  } finally {
    restore();
  }
});

test("test_maintenance_rows_and_maintenance_counters_agree", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await mission(greenTank({
      maintenance: {
        enabled: true,
        tasks: {
          glass: { label: "Glass clean", enabled: true, cadenceDays: 7, criticalAfterDays: 14, scheduleMode: "interval" },
          socks: { label: "Filter sock", enabled: true, cadenceDays: 3, criticalAfterDays: 6, scheduleMode: "interval" },
          carbon: { label: "Replace carbon", enabled: true, cadenceDays: 30, criticalAfterDays: 60, scheduleMode: "interval" },
          rodi: { label: "RODI filters", enabled: false, cadenceDays: 180, criticalAfterDays: 360, scheduleMode: "interval" },
        },
        completions: {
          glass: [{ id: "g", timestamp: iso(30) }],   // past criticalAfterDays -> overdue
          socks: [{ id: "s", timestamp: iso(4) }],    // past cadence, inside critical -> due
          carbon: [{ id: "c", timestamp: iso(2) }],   // fresh
          rodi: [{ id: "r", timestamp: iso(900) }],   // ancient, but the task is off
        },
      },
    }));
    assertEqual(panel._maintenanceDueCount(), 2, "due counts warning + critical tasks");
    assertEqual(panel._maintenanceOverdueCount(), 1, "overdue counts only the critical ones");

    const maintenanceRows = rows(panel).filter((row) => row.tab === "maintenance");
    assertEqual(maintenanceRows.length, 2, `the list must show the same two tasks the counters counted: ${JSON.stringify(maintenanceRows)}`);
    assertEqual(titled(maintenanceRows, "Glass clean")[0].severity, "critical", "overdue is critical");
    assert(titled(maintenanceRows, "Glass clean")[0].title.endsWith("overdue"), "an overdue task must say overdue");
    assertEqual(titled(maintenanceRows, "Filter sock")[0].severity, "warning", "due-but-not-overdue is a warning");
    assertEqual(titled(maintenanceRows, "Replace carbon").length, 0, "a task inside its cadence is not attention");
    assertEqual(titled(maintenanceRows, "RODI").length, 0, "a disabled task is not tracked at all, however old");
    // The list and the counters both filter on task.enabled, so the absence above is
    // double-guarded and would survive either filter breaking. The guard that actually
    // decides is in _maintenanceDueState, so assert it where it lives: 900 days stale
    // and still "not tracked", because the user said they don't do this job.
    assertEqual(panel._maintenanceDueState("rodi").status, "unknown", "a switched-off chore has no due state");
    assertEqual(panel._maintenanceDueState("rodi").label, "not tracked");
    assertEqual(panel._maintenanceDueState("glass").label, "overdue");
    assertEqual(panel._maintenanceDueState("socks").label, "due");
    assertEqual(panel._maintenanceDueState("carbon").label, "done");

    // The Maintenance summary card is the counter the user sees; it reads from the
    // same two numbers, so a drift here means the card and the list disagree.
    const cardHtml = panel._missionMaintenanceCard();
    assertClean(cardHtml, "maintenance card");
    assert(cardHtml.includes("2 due") && cardHtml.includes("1 overdue"), `the card must report 2 due / 1 overdue: ${cardHtml}`);
    assert(cardHtml.includes('class="summary-card critical"'), "any overdue task makes the card critical");

    const html = panel._mission();
    const shown = attention(html);
    assertEqual(shown.text, "2 to check",
      "chores are part of Attention: the pill must count them like anything else");
    assertEqual(shown.rows.length, 2, "and the rendered list must be those same two chores");
    assertEqual(shown.tone, "critical", "an overdue chore turns the Attention pill red");
    // The card the user actually sees in Mission Control, not just the fragment.
    assertEqual(card(html, "Maintenance").value, "2 due");
    assertEqual(card(html, "Maintenance").detail, "1 overdue");
    assertEqual(card(html, "Maintenance").status, "critical");
  } finally {
    restore();
  }
});

// --- silenced means silent ------------------------------------------------------

test("test_a_muted_sensor_stays_out_of_attention_until_the_mute_expires", async () => {
  const restore = freezeTime(NOW);
  try {
    const overheating = { ...GREEN_STATES, "sensor.temp": { state: "31" } };
    const muted = await mission(greenTank({ alerts: { muteUntil: { temp: "2026-06-04T12:00:00.000Z" } } }), overheating);
    assertEqual(rows(muted).length, 0, "a muted sensor must not keep nagging from Mission Control");
    const html = muted._mission();
    assertEqual(attentionPill(html), "all clear", "muting hides the row, so it must also clear the counter");
    assertEqual(attention(html).tone, "ok", "and the pill goes green, not amber");
    assertEqual(attention(html).rows.length, 0, "nothing is rendered beneath an all-clear pill");
    assertEqual(hero(html).headline, "All systems nominal");
    assertEqual(card(html, "Sensors").status, "ok", "a muted probe leaves no residue on the Sensors card");
    assertEqual(card(html, "Sensors").detail, "0 critical · 0 warning");

    // The mute is a snooze, not a delete: once it lapses the alert comes straight back.
    const expired = await mission(greenTank({ alerts: { muteUntil: { temp: "2026-06-04T08:00:00.000Z" } } }), overheating);
    assertEqual(rows(expired).length, 1, "an expired mute must not keep suppressing a live problem");
    assertEqual(rows(expired)[0].severity, "critical");
  } finally {
    restore();
  }
});

test("test_alerts_off_and_disabled_are_different_switches_and_both_stay_quiet", async () => {
  const restore = freezeTime(NOW);
  try {
    const overheating = { ...GREEN_STATES, "sensor.temp": { state: "31" } };

    // Alerts off: still a configured sensor, still readable live, just not shouting.
    const quiet = greenTank();
    quiet.sensors.temp.alertsEnabled = false;
    const quietPanel = await mission(quiet, overheating);
    assertEqual(rows(quietPanel).length, 0, "alertsEnabled:false must remove the sensor from Attention");

    // Disabled: gone from Mission Control entirely — no reading row, and no nag to
    // map it either. "You don't own an ORP probe" must not read as "set up your ORP
    // probe". A second sensor keeps "No sensor types enabled" out of the way.
    const off = greenTank();
    off.sensors.temp.enabled = false;
    off.sensors.orp = { label: "ORP", enabled: false, alertsEnabled: true, entity_id: "", min: 300, max: 450, unit: "mV", group: "chemistry" };
    off.sensors.ph = { label: "pH", enabled: true, alertsEnabled: true, entity_id: "sensor.ph", min: 7.9, max: 8.4, unit: "pH", group: "chemistry" };
    const offPanel = await mission(off, { ...overheating, "sensor.ph": { state: "8.1" } });
    const list = rows(offPanel);
    assertEqual(titled(list, "Temperature").length, 0, `a disabled sensor must never contribute a row: ${JSON.stringify(list)}`);
    assertEqual(titled(list, "need mapping").length, 0,
      `a disabled, unmapped sensor is not an unmapped sensor: ${JSON.stringify(list)}`);
    assertEqual(titled(list, "ORP").length, 0, "an unowned probe must not be advertised as a gap");
    // The one thing turning tank temperature off DOES earn: an armed heater now has
    // nothing to check itself against, which is a real interlock warning.
    assertEqual(list.length, 1, `only the heater interlock should remain: ${JSON.stringify(list)}`);
    assert(list[0].title.includes("Heater interlock"), `unexpected leftover row: ${JSON.stringify(list[0])}`);
    // An interlock is a "your setup can't protect itself" note, not a live fault.
    // Painting it red would put it level with a heater that is actually cooking the
    // tank, and the user would stop believing red.
    assertEqual(list[0].severity, "warning", "an interlock gap is a warning, not a critical");
    assertEqual(list[0].pillClass, "warning");
    assertEqual(list[0].tab, "controls", "the fix is arming/mapping, so send the user to Controls");
    const html = offPanel._mission();
    assertEqual(hero(html).headline, "Watch closely", "an interlock warning must not read as an emergency");
    assertEqual(hero(html).border, "warning-border");
    assertEqual(attention(html).tone, "warning", "and the Attention pill stays amber");
    assertEqual(attention(html).count, 1, "the interlock is counted exactly once");
  } finally {
    restore();
  }
});

test("test_a_snoozed_or_switched_off_chore_is_hidden_from_the_list_and_the_counter", async () => {
  const restore = freezeTime(NOW);
  try {
    const stale = { glass: [{ id: "g", timestamp: iso(40) }] };
    const snoozed = await mission(greenTank({
      maintenance: {
        enabled: true,
        tasks: { glass: { label: "Glass clean", enabled: true, cadenceDays: 7, criticalAfterDays: 14, scheduleMode: "interval", snoozedUntil: "2026-06-10T00:00:00.000Z" } },
        completions: stale,
      },
    }));
    assertEqual(rows(snoozed).length, 0, "snoozing a chore must silence it, not just re-label it");
    assertEqual(snoozed._maintenanceDueCount(), 0, "a snoozed chore must not be counted either");

    // Turning the whole feature off is the bigger hammer and must be respected too:
    // the panel and the backend both gate on maintenance.enabled.
    const disabled = await mission(greenTank({
      maintenance: {
        enabled: false,
        tasks: { glass: { label: "Glass clean", enabled: true, cadenceDays: 7, criticalAfterDays: 14, scheduleMode: "interval" } },
        completions: stale,
      },
    }));
    assertEqual(rows(disabled).length, 0, "maintenance disabled means no chore ever reaches Mission Control");
    assertEqual(attentionPill(disabled._mission()), "all clear");
  } finally {
    restore();
  }
});

// --- a quiet tank must read quiet ------------------------------------------------

test("test_an_all_clear_tank_gets_a_calm_summary_not_a_zeroed_alarm", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await mission(greenTank());
    const list = issueHtml(panel);
    assertClean(list, "empty attention list");
    assert(!/issue-item/.test(list), "nothing is wrong, so nothing should be listed");
    assert(!/pill (critical|warning)/.test(list), "an all-clear tank must not paint a red or amber pill");
    assert(list.includes("Nothing needs attention"), `the empty state should reassure, not just be blank: ${list}`);

    const html = panel._mission();
    assertClean(html, "mission");
    assertEqual(hero(html).headline, "All systems nominal");
    assertEqual(hero(html).border, "ok-border");
    assertEqual(attentionPill(html), "all clear");
    assertEqual(attention(html).tone, "ok", "the all-clear pill must be green");
    assertEqual(attention(html).count, 0);
    assert(!html.includes("danger-border"), "no danger styling anywhere on a healthy tank");
    // Every card that speaks for the tank must agree it is fine — a single red card
    // above an "all clear" list is the contradiction that erodes trust in the screen.
    assertEqual(card(html, "Sensors").status, "ok");
    assertEqual(card(html, "Sensors").detail, "0 critical · 0 warning");
    assertEqual(card(html, "Equipment").status, "ok");
    assertEqual(card(html, "Maintenance").status, "ok");
    assertEqual(card(html, "Maintenance").value, "All done");
  } finally {
    restore();
  }
});

test("test_informational_rows_never_escalate_a_healthy_tank", async () => {
  const restore = freezeTime(NOW);
  try {
    // A mapped-but-disarmed device is a setup note, not a fault. It gets a row so the
    // user can find it, but it must not turn the tank red or claim to need action.
    const config = greenTank();
    config.equipment.skimmer = { label: "Skimmer", armed: false, switch_entity_id: "switch.skimmer", type: "skimmer" };
    const panel = await mission(config, { ...GREEN_STATES, "switch.skimmer": { state: "on" } });
    const list = rows(panel);
    assertEqual(list.length, 1, `only the disarmed note should appear: ${JSON.stringify(list)}`);
    assertEqual(list[0].severity, "info");
    assertEqual(list[0].pillClass, "unknown", "info rows must be visually muted, not amber");

    const html = panel._mission();
    assertEqual(hero(html).headline, "All systems nominal", "a disarmed device is not a reason to alarm anyone");
    assertEqual(hero(html).border, "ok-border");
  } finally {
    restore();
  }
});

// --- bucketing: every alert counted once, in one place ---------------------------

test("test_every_sensor_alert_lands_in_exactly_one_summary_bucket", async () => {
  const restore = freezeTime(NOW);
  try {
    const config = greenTank({
      sensors: {
        temp: { label: "Temperature", enabled: true, alertsEnabled: true, entity_id: "sensor.temp", min: 24, max: 27, unit: "°C" },
        alkalinity: { label: "Alkalinity", enabled: true, alertsEnabled: true, entity_id: "sensor.alk", min: 7.5, max: 9.5, unit: "dKH", group: "chemistry" },
        calcium: { label: "Calcium", enabled: true, alertsEnabled: true, entity_id: "sensor.ca", min: 400, max: 450, unit: "ppm", group: "chemistry" },
        room_temp: { label: "Room temp", enabled: true, alertsEnabled: true, entity_id: "sensor.room", min: 18, max: 26, unit: "°C", group: "room" },
      },
    });
    const panel = await mission(config, {
      ...GREEN_STATES,
      "sensor.temp": { state: "31" },        // scoring critical
      "sensor.alk": { state: "7.6" },        // scoring warning (inside the buffer)
      "sensor.ca": { state: "unavailable" }, // unknown
      "sensor.room": { state: "30" },        // context only, however far out
    });
    const alerts = panel._sensorAlerts(panel._enabledSensors());
    const summary = panel._sensorSummaryState(alerts, false);

    assertEqual(alerts.length, 4, "each alerting sensor produces exactly one alert");
    const bucketed = [...summary.scoringCritical, ...summary.scoringWarning, ...summary.unknown, ...summary.context];
    assertEqual(bucketed.length, alerts.length, "buckets must partition the alerts — nothing dropped, nothing duplicated");
    assertEqual(new Set(bucketed.map((alert) => alert.id)).size, alerts.length, "a sensor must not appear in two buckets");
    assertEqual(summary.criticalCount + summary.warningCount + summary.contextCount, alerts.length,
      "the three headline counts must add up to the alerts they describe");
    assertEqual(summary.detail, "1 critical · 2 warning · 1 context warning",
      "the Sensors card detail is the same tally, spelled out");
    assertEqual(summary.status, "critical",
      "one scoring critical outranks every warning: the card colour follows the worst thing in it");
    assertEqual(summary.scoringCritical.map((a) => a.id), ["temp"]);
    assertEqual(summary.scoringWarning.map((a) => a.id), ["alkalinity"]);
    assertEqual(summary.unknown.map((a) => a.id), ["calcium"], "an unreadable probe is 'unknown', counted with the warnings");
    assertEqual(summary.context.map((a) => a.id), ["room_temp"]);

    const missionHtml = panel._mission();
    assertEqual(card(missionHtml, "Sensors").status, "critical", "the card on screen carries that same status");
    assertEqual(card(missionHtml, "Sensors").detail, summary.detail);
    assertEqual(card(missionHtml, "Sensors").value, "4/4", "all four are mapped");

    // The list beneath shows one row per sensor, with the same critical/not split.
    const sensorRows = rows(panel).filter((row) => ["live", "settings"].includes(row.tab));
    assertEqual(sensorRows.filter((row) => row.severity === "critical").length, summary.criticalCount,
      "the number of red rows must equal the critical count on the card");
    assertEqual(titled(sensorRows, "Temperature").length, 1);
    assertEqual(titled(sensorRows, "Alkalinity").length, 1);
    assertEqual(titled(sensorRows, "Calcium").length, 1);
    assertEqual(titled(sensorRows, "Room temp").length, 1);
  } finally {
    restore();
  }
});

test("test_a_context_sensor_never_escalates_the_tank_to_critical", async () => {
  const restore = freezeTime(NOW);
  try {
    // Room temperature is measured, not controlled. It is worth telling the user about,
    // but it must not read as "your reef is in danger" or drive the score.
    const config = greenTank();
    config.sensors.room_temp = { label: "Room temp", enabled: true, alertsEnabled: true, entity_id: "sensor.room", min: 18, max: 26, unit: "°C", group: "room" };
    const panel = await mission(config, { ...GREEN_STATES, "sensor.room": { state: "35" } });

    const alerts = panel._sensorAlerts(panel._enabledSensors());
    assertEqual(alerts.find((alert) => alert.id === "room_temp").status, "critical", "the reading itself really is out of range");
    const summary = panel._sensorSummaryState(alerts, false);
    assertEqual(summary.criticalCount, 0, "a context sensor must not fill the critical bucket");
    assertEqual(summary.status, "warning", "context is worth a warning, never a red tank");

    const row = titled(rows(panel), "Room temp")[0];
    assertEqual(row.severity, "warning", "the row is downgraded to match the bucket");
    assertEqual(row.tab, "live", "context rows still link to the reading");
    assert(row.title.includes("(context)") && row.detail.includes("context only"),
      `the row must say why it is not urgent: ${JSON.stringify(row)}`);

    const html = panel._mission();
    assertClean(html, "mission");
    assertEqual(hero(html).headline, "Watch closely");
    assertEqual(hero(html).border, "warning-border", "amber, never red");
    assertEqual(card(html, "Sensors").status, "warning", "the card reports it");
    assertEqual(card(html, "Sensors").detail, "0 critical · 0 warning · 1 context warning",
      "context is tallied separately from the warnings that drive the score");

    // The asymmetry this used to pin (an amber row nobody counted, so the pill read
    // "all clear" above it) was resolved in 0.6.6 the way the rest of the screen
    // already leaned: the Sensors card goes amber for context, so the counter counts
    // it too. One thing on screen, one thing counted — never a row without a number.
    assertEqual(attention(html).text, "1 to check", "a context row is a row, so it is counted");
    assertEqual(attention(html).rows.length, 1, "and the section opens to show it");
    assertEqual(attention(html).rows[0].severity, "warning", "amber, never red — it is still context");

    panel._healthSections = { "mission-attention": true };
    const expanded = attention(panel._mission());
    assertEqual(expanded.count, 1, "expanding does not change the counter");
    assertEqual(expanded.rows.length, 1, "and the context row is the one being counted");
    assertEqual(expanded.rows[0].severity, "warning");
  } finally {
    restore();
  }
});

test("test_a_sensor_that_stops_reporting_is_a_warning_not_a_critical", async () => {
  const restore = freezeTime(NOW);
  try {
    // No data is not the same as bad data. Claiming critical here would train the user
    // to ignore red, and the true reading is unknown in both directions.
    const panel = await mission(greenTank(), { ...GREEN_STATES, "sensor.temp": { state: "unavailable" } });
    const list = rows(panel);
    const row = titled(list, "Temperature")[0];
    assertEqual(row.severity, "warning", "a silent probe is a confidence problem, not a range breach");
    assertEqual(row.tab, "settings", "the fix is in the mapping, so send the user there");
    assert(row.title.includes("not reporting"), `the row must say what is wrong: "${row.title}"`);
    assertEqual(titled(list, "Temperature is not reporting").length, 1, "the probe is named once, not once per consequence");
    assertEqual(titled(list, "need mapping").length, 0, "a mapped-but-silent probe is not an unmapped probe");
    // The second row is not a duplicate: the armed heater has just lost the reading it
    // interlocks against, which is a separate thing the user can act on.
    assertEqual(list.length, 2, `expected the probe row plus the heater interlock: ${JSON.stringify(list)}`);
    assertEqual(titled(list, "Heater interlock")[0].detail, "sensor.temp is unavailable.",
      "the interlock row must say which entity went dark");

    const html = panel._mission();
    assertEqual(hero(html).headline, "Watch closely");
    assertEqual(hero(html).border, "warning-border", "amber, not red — nothing is confirmed bad");
    assertEqual(attention(html).tone, "warning", "the pill must stay amber when nothing is critical");
    assertEqual(attention(html).count, 2, "both consequences are counted, and counted once each");
    assertEqual(attention(html).rows.length, 2);
    assertEqual(card(html, "Sensors").detail, "0 critical · 1 warning",
      "an unknown reading is counted as a warning on the card, matching the row");
  } finally {
    restore();
  }
});

test("test_display_wavemaker_left_off_is_reported_as_critical_flow_loss", async () => {
  const restore = freezeTime(NOW);
  try {
    // Display flow is the one "off" state OpenReef refuses to shrug at: a stopped gyre
    // in Running mode is dead flow over corals, so it is a critical row that names the
    // device. (It is deliberately never auto-restarted — a person must look first.)
    const config = greenTank({ mode: { active: "running" } });
    config.equipment.gyre = { label: "Gyre XF330", armed: true, switch_entity_id: "switch.gyre", type: "display_wavemaker" };
    const panel = await mission(config, { ...GREEN_STATES, "switch.gyre": { state: "off" } });
    const row = titled(rows(panel), "wavemaker")[0];
    assert(row, "a display wavemaker left off in Running mode must be reported");
    assertEqual(row.severity, "critical");
    assertEqual(row.tab, "controls");
    assert(row.detail.includes("Gyre XF330"), `the row must name the pump: "${row.detail}"`);
    assert(/flow/i.test(row.detail), "the row must explain why an off pump matters");

    // Feed/Maintenance modes turn pumps off on purpose, so the same state is silent.
    const feeding = await mission(
      greenTank({ mode: { active: "feed" }, equipment: config.equipment }),
      { ...GREEN_STATES, "switch.gyre": { state: "off" } },
    );
    assertEqual(titled(rows(feeding), "wavemaker").length, 0,
      "a pump you deliberately stopped for feeding must not be reported as a fault");
  } finally {
    restore();
  }
});

// --- the backend's own findings must survive the trip to the screen ----------------

test("test_backend_reported_missing_entities_are_shown_and_named", async () => {
  const restore = freezeTime(NOW);
  try {
    // `missing_entities` is the backend telling the panel "you have a mapping pointing
    // at an entity Home Assistant does not have". If the panel drops it the user is
    // looking at a dashboard wired to nothing and being told everything is fine.
    const panel = await mission(greenTank(), GREEN_STATES, { missing_entities: ["sensor.ghost"] });
    const list = rows(panel);
    assertEqual(list.length, 1, `one broken mapping is one row: ${JSON.stringify(list)}`);
    assertEqual(list[0].severity, "critical", "a mapping pointing at nothing is a broken instrument");
    assertEqual(list[0].tab, "settings", "the fix is re-mapping, so send the user to Settings");
    assert(list[0].detail.includes("sensor.ghost"), `the row must name the entity: "${list[0].detail}"`);
    assertEqual(attention(panel._mission()).count, 1, "counted once");

    // Long lists are truncated so one bad integration cannot swamp the screen, but
    // the entities that ARE shown must be real ones, not a placeholder.
    const many = ["sensor.a", "sensor.b", "sensor.c", "sensor.d", "sensor.e", "sensor.f", "sensor.g", "sensor.h"];
    const flood = await mission(greenTank(), GREEN_STATES, { missing_entities: many });
    const floodRows = rows(flood);
    assertEqual(floodRows.length, 1, "eight broken mappings still collapse into one row");
    for (const entity of many.slice(0, 6)) {
      assert(floodRows[0].detail.includes(entity), `the row must list ${entity}: "${floodRows[0].detail}"`);
    }
    assert(!floodRows[0].detail.includes("sensor.g"), `the row must stop at six: "${floodRows[0].detail}"`);
  } finally {
    restore();
  }
});

test("test_a_tank_with_no_sensors_enabled_is_told_so_exactly_once", async () => {
  const restore = freezeTime(NOW);
  try {
    // A fresh install with every sensor type switched off must not render as a healthy
    // tank — there is simply nothing being watched, and that is worth saying out loud.
    const panel = await mission({
      sensors: { temp: { label: "Temperature", enabled: false, alertsEnabled: true, entity_id: "sensor.temp", min: 24, max: 27, unit: "°C" } },
      equipment: {},
      maintenance: { enabled: false, tasks: {}, completions: {} },
      interlocks: {}, alerts: {}, display: {}, activity: [], energy: {}, tank: {},
    }, {});

    assertEqual(panel._enabledSensors().length, 0);
    const list = rows(panel);
    assertEqual(titled(list, "No sensor types enabled").length, 1,
      `an unwatched tank must be told once: ${JSON.stringify(list)}`);
    assertEqual(titled(list, "No sensor types enabled")[0].severity, "warning");
    assertEqual(titled(list, "need mapping").length, 0, "disabled sensors are not unmapped sensors");

    // The empty-sensor flag is what stops the Sensors card claiming "ok" with nothing in it.
    assertEqual(panel._sensorSummaryState([], true).status, "warning", "nothing watched is not the same as nothing wrong");
    assertEqual(panel._sensorSummaryState([], false).status, "ok");

    const html = panel._mission();
    assertClean(html, "mission");
    assertEqual(hero(html).headline, "Watch closely", "an unwatched tank is not 'All systems nominal'");
    assertEqual(hero(html).border, "warning-border");
    assertEqual(card(html, "Sensors").status, "warning");
    assertEqual(card(html, "Sensors").value, "0/0");
  } finally {
    restore();
  }
});

test("test_three_unrelated_faults_produce_three_rows_and_a_count_of_three", async () => {
  const restore = freezeTime(NOW);
  try {
    // The no-double-counting contract, checked where it can actually break: one
    // overdue chore, one dead armed switch and one out-of-range probe, together.
    // Each source pushes independently, so a shared bug shows up as 4+ rows or as a
    // pill that disagrees with what is rendered under it.
    const panel = await mission(greenTank({
      maintenance: {
        enabled: true,
        tasks: { glass: { label: "Glass clean", enabled: true, cadenceDays: 7, criticalAfterDays: 14, scheduleMode: "interval" } },
        completions: { glass: [{ id: "g", timestamp: iso(30) }] },
      },
    }), { ...GREEN_STATES, "sensor.temp": { state: "31" }, "switch.heater": { state: "unavailable" } },
    { armed_unavailable: ["switch.heater"] });

    const html = panel._mission();
    assertClean(html, "mission");
    const shown = attention(html);
    assertEqual(shown.count, 3, "three problems, three to check");
    assertEqual(shown.rows.length, 3, `three problems, three rows: ${JSON.stringify(shown.rows)}`);
    assertEqual(shown.rows.length, shown.count, "the pill and the list beneath it must never disagree");
    assertEqual(titled(shown.rows, "Temperature").length, 1, "the probe is listed once");
    assertEqual(titled(shown.rows, "Armed equipment unavailable").length, 1, "the dead switch is listed once");
    assertEqual(titled(shown.rows, "Glass clean").length, 1, "the chore is listed once");
    assertEqual(shown.rows.filter((row) => row.severity === "critical").length, 3, "all three are critical");
    assertEqual(shown.tone, "critical");
    assertEqual(hero(html).headline, "Action needed");
    assertEqual(hero(html).border, "danger-border");
  } finally {
    restore();
  }
});

test("test_setup_notes_sink_below_real_faults_in_the_list", async () => {
  const restore = freezeTime(NOW);
  try {
    // Ordering the user relies on: actionable rows first, "you still have to configure
    // this" notes last. NOTE: the list is built by source, then severity is stamped on
    // each row — it is NOT re-sorted by severity, so a warning from an earlier source
    // (a sensor alert) still renders above a later critical (a dead switch). That is
    // pinned here deliberately; if severity sorting is ever added this test is the
    // one that should be updated to say so.
    const config = greenTank();
    config.equipment.skimmer = { label: "Skimmer", armed: false, switch_entity_id: "switch.skimmer", type: "skimmer" };
    const panel = await mission(config, {
      ...GREEN_STATES,
      "sensor.temp": { state: "26.8" },   // inside range, past the 10% warning buffer
      "switch.skimmer": { state: "on" },
    }, { armed_unavailable: ["switch.heater"] });

    const list = rows(panel);
    assertEqual(list.map((row) => row.severity), ["warning", "critical", "info"],
      `sources render in order (sensors, validation, setup notes): ${JSON.stringify(list)}`);
    assertEqual(list[2].pillClass, "unknown", "the trailing note stays grey");
    assert(list[2].title.includes("disarmed"), `the last row must be the setup note: ${JSON.stringify(list[2])}`);
    // Whatever the order, the loud thing must still be countable and still be red.
    assertEqual(attention(panel._mission()).tone, "critical", "a critical anywhere in the list paints the pill red");
  } finally {
    restore();
  }
});

// --- robustness -------------------------------------------------------------------

test("test_a_half_configured_tank_never_renders_undefined_or_nan", async () => {
  const restore = freezeTime(NOW);
  try {
    // Everything a part-finished setup can throw at the list: no thresholds, no unit,
    // a binary sensor, an unmapped probe, a chore with no cadence and an unparseable
    // completion timestamp. The user sees this screen mid-setup more than any other.
    const panel = await mission({
      sensors: {
        temp: { label: "Temperature", enabled: true, alertsEnabled: true, entity_id: "sensor.temp" },
        salinity: { label: "Salinity", enabled: true, alertsEnabled: true, entity_id: "", group: "chemistry" },
        leak: { label: "Leak", enabled: true, alertsEnabled: true, entity_id: "binary_sensor.leak", kind: "binary" },
      },
      equipment: { mystery: { label: "", armed: true, switch_entity_id: "switch.mystery" } },
      maintenance: {
        enabled: true,
        tasks: { never: { label: "Never logged", enabled: true }, broken: { label: "Broken log", enabled: true, cadenceDays: 1, criticalAfterDays: 2 } },
        completions: { broken: [{ id: "b", timestamp: "not-a-date" }] },
      },
      interlocks: {}, alerts: {}, display: {}, activity: [], energy: {}, tank: {},
    }, {
      "sensor.temp": { state: "25" },
      "binary_sensor.leak": { state: "wet" },
      "switch.mystery": { state: "on" },
    });

    const list = rows(panel);              // rows() asserts the markup is clean
    assert(list.length > 0, "a half-configured tank should still be telling the user something");
    for (const row of list) {
      assert(row.title.trim().length > 2, `every row needs a readable title: ${JSON.stringify(row)}`);
      assert(row.detail.trim().length > 2, `every row needs a readable detail: ${JSON.stringify(row)}`);
    }

    // An enabled-but-unmapped probe is the single most common half-finished state,
    // and silently dropping it is how a user ends up thinking a sensor is watched
    // when nothing is reading it. One row, naming the sensor, pointing at Settings.
    const mapping = titled(list, "need mapping");
    assertEqual(mapping.length, 1, `an unmapped sensor must produce exactly one nag: ${JSON.stringify(list)}`);
    assertEqual(mapping[0].severity, "warning");
    assertEqual(mapping[0].tab, "settings", "the fix is in Settings, so the row must go there");
    assert(mapping[0].detail.includes("Salinity"), `the nag must name the unmapped sensor: "${mapping[0].detail}"`);
    // A wet leak sensor is the one binary probe that must shout.
    const leak = titled(list, "Leak");
    assertEqual(leak.length, 1, `one wet leak probe is one row: ${JSON.stringify(list)}`);
    assertEqual(leak[0].severity, "critical", "a leak sensor reporting wet is not a nudge");

    const html = panel._mission();
    assertClean(html, "mission");
    assertEqual(card(html, "Sensors").value, "2/3",
      "the Sensors card counts mapped over enabled — an unmapped probe must not be counted as mapped");
  } finally {
    restore();
  }
});

test("test_user_supplied_labels_are_escaped_before_they_reach_the_list", async () => {
  const restore = freezeTime(NOW);
  try {
    // Task and equipment labels are free text the user types. The Attention list is
    // built by string concatenation, so escaping is the only thing between a typed
    // angle bracket and injected markup in the panel.
    const evil = '<img src=x onerror="alert(1)"> & "quoted"';
    const panel = await mission(greenTank({
      maintenance: {
        enabled: true,
        tasks: { glass: { label: evil, enabled: true, cadenceDays: 1, criticalAfterDays: 2, scheduleMode: "interval" } },
        completions: { glass: [{ id: "g", timestamp: iso(30) }] },
      },
    }));
    const html = issueHtml(panel);
    assertClean(html, "issue list");
    assert(!html.includes("<img"), "a label must never be able to open a tag");
    assert(!html.includes('onerror="'), "a label must never be able to add an attribute");
    assert(html.includes("&lt;img") && html.includes("&amp;") && html.includes("&quot;"),
      "the label should still be shown, escaped");
  } finally {
    restore();
  }
});

test("test_the_headline_and_the_counter_are_read_off_the_same_list", async () => {
  const restore = freezeTime(NOW);
  try {
    // The hero, the "N to check" pill and the rows used to be computed in parallel
    // from the raw inputs, and drifted: a display wavemaker left off is a critical
    // ROW but was in none of the counted buckets, so Mission Control read "All
    // systems nominal · all clear" directly above a red "Display wavemaker still
    // off". One list, one count, one headline.
    const config = greenTank({ mode: { active: "running" } });
    config.equipment.gyre = { label: "Gyre XF330", armed: true, switch_entity_id: "switch.gyre", type: "display_wavemaker" };
    const panel = await mission(config, { ...GREEN_STATES, "switch.gyre": { state: "off" } });

    const html = panel._mission();
    assertClean(html, "mission");
    const shown = attention(html);
    assertEqual(shown.rows.length, 1, "one stopped gyre is one row");
    assertEqual(shown.rows[0].severity, "critical");
    assertEqual(shown.text, "1 to check", "the pill must count the row the user can see");
    assertEqual(shown.tone, "critical", "and be painted the colour of the worst thing in it");
    assertEqual(hero(html).headline, "Action needed",
      "the headline cannot say nominal while a critical row sits under it");

    // The same wiring in the other direction: a genuinely quiet tank still reads quiet.
    const calm = (await mission(greenTank())) ._mission();
    assertEqual(attention(calm).text, "all clear");
    assertEqual(hero(calm).headline, "All systems nominal");
  } finally {
    restore();
  }
});

await runTests();
