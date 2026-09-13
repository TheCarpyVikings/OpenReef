/**
 * Live Stats: direction, rate and projection; stale; the marked moment; the
 * page's Needs-a-look move and the truth strip.
 *
 * The contracts here are the ones a keeper would notice if they broke: a room
 * cooling after a window opened must read as "falling, back toward the middle"
 * (green), not as a warning; a slope on dead readings must never be shown; a
 * card that moves to Needs a look must not also stay in its group.
 *
 * Decisions: docs/live-stats-brainstorm.md §8.
 *
 * Run standalone:  node tests/test_panel_live.mjs
 */

import { assert, assertEqual, freezeTime, makePanel, runTests, test } from "./_panel_harness.mjs";

const NOW = "2026-09-13T14:50:00.000Z";
const NOW_MS = Date.parse(NOW);
const minsAgo = (m) => NOW_MS - m * 60000;
const isoMinsAgo = (m) => new Date(minsAgo(m)).toISOString();

function config(over = {}) {
  return {
    sensors: {
      tank_temp: { label: "Tank temperature", enabled: true, alertsEnabled: true, entity_id: "sensor.tank_temp", group: "tank", min: 24, max: 26, unit: "°C", kind: "numeric" },
      ph: { label: "pH", enabled: true, alertsEnabled: true, entity_id: "sensor.ph", group: "tank", min: 7.8, max: 8.4, unit: "", kind: "numeric" },
      room_temp: { label: "Room temperature", enabled: true, alertsEnabled: true, entity_id: "sensor.room_temp", group: "room", min: 18, max: 28, unit: "°C", kind: "numeric" },
      humidity: { label: "Humidity", enabled: true, alertsEnabled: true, entity_id: "sensor.humidity", group: "room", min: 40, max: 60, unit: "%", kind: "numeric" },
      leak: { label: "Leak", enabled: true, alertsEnabled: true, entity_id: "binary_sensor.leak", group: "safety", kind: "binary", unit: "" },
    },
    alerts: {},
    display: {},
    lightingSchedule: { mode: "off" },
    ...over,
  };
}

const state = (value, minutesAgo = 1) => ({ state: String(value), last_reported: isoMinsAgo(minutesAgo), last_updated: isoMinsAgo(minutesAgo) });

function states(over = {}) {
  return {
    "sensor.tank_temp": state(25.3),
    "sensor.ph": state(8.05),
    "sensor.room_temp": state(26.0),
    "sensor.humidity": state(55.0),
    "binary_sensor.leak": state("off"),
    ...over,
  };
}

// Readings evenly spaced over the last `minutes`, going linearly from `from` to `to`.
function ramp(from, to, minutes, steps = 6) {
  const out = [];
  for (let i = 0; i <= steps; i += 1) {
    out.push({ time: minsAgo(minutes - (minutes * i) / steps), value: from + ((to - from) * i) / steps });
  }
  return out;
}

async function live(cfg = config(), st = states(), readings = {}, sparks = {}) {
  const panel = await makePanel(cfg);
  panel._hass = { states: st };
  panel._validation = { missing_entities: [], armed_unavailable: [] };
  panel._lightingWindow = { data: null, loading: true, at: 0 };
  panel._liveReadings = readings;
  panel._liveSparks = sparks;
  panel._liveMarkOpen = false;
  panel._settingsSections = {};
  panel._activeTab = "live";
  return panel;
}

// ── Rate windows ────────────────────────────────────────────────────────────

test("rate windows: water groups use 30 min, air groups 15 min (§8.3)", async () => {
  const panel = await live();
  assertEqual(panel._liveRateWindows("tank"), { now: 30, context: 120 });
  assertEqual(panel._liveRateWindows("chemistry"), { now: 30, context: 120 });
  assertEqual(panel._liveRateWindows("room"), { now: 15, context: 60 });
  assertEqual(panel._liveRateWindows(undefined), { now: 30, context: 120 });
});

// ── Direction ───────────────────────────────────────────────────────────────

test("a warm room cooling fast after the window opened reads falling and AWAY, no projection past 3 h", async () => {
  const restore = freezeTime(NOW);
  try {
    // 26.3 → 26.0 over 15 min = −1.2 °C/h = 12 % of the 18–28 band per hour: fast.
    const panel = await live(config(), states(), { room_temp: ramp(26.3, 26.0, 15) });
    const d = panel._liveDirection("room_temp", panel._config.sensors.room_temp);
    assert(d, "direction expected");
    assertEqual(d.speed, "fast");
    assertEqual(d.arrow, "↓");
    assertEqual(d.rising, false);
    assertEqual(d.away, true);
    assertEqual(d.toward, false);
    assertEqual(d.projection, "", "18.0 is 6.7 h away — not worth a clock");
    assertEqual(d.windowMinutes, 15);
    const html = panel._liveDirectionMarkup("room_temp", panel._config.sensors.room_temp, d, { stale: false });
    assert(html.includes("−1.20 °C/h"), `rate text: ${html}`);
    assert(html.includes("back toward the middle"), html);
    assert(html.includes('live-arrow away'), "green arrow");
  } finally { restore(); }
});

test("tank rising toward max projects the clock it hits the limit", async () => {
  const restore = freezeTime(NOW);
  try {
    // 25.55 → 25.7 over 30 min = +0.3 °C/h; 26.0 is 1 h away.
    const st = states({ "sensor.tank_temp": state(25.7) });
    const panel = await live(config(), st, { tank_temp: ramp(25.55, 25.7, 30) });
    const d = panel._liveDirection("tank_temp", panel._config.sensors.tank_temp);
    assert(d, "direction expected");
    assertEqual(d.speed, "fast");
    assertEqual(d.arrow, "↑");
    assertEqual(d.toward, true);
    assert(d.projection.startsWith("hits 26.0 ≈ "), d.projection);
    assert(d.projection.endsWith(" at this pace"), d.projection);
    const html = panel._liveDirectionMarkup("tank_temp", panel._config.sensors.tank_temp, d, { stale: false });
    assert(html.includes("+0.30 °C/h"), html);
    assert(html.includes('live-arrow toward'), "amber arrow");
  } finally { restore(); }
});

test("a flat sensor is steady: no rate, no projection", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await live(config(), states(), { ph: ramp(8.05, 8.052, 30) });
    const d = panel._liveDirection("ph", panel._config.sensors.ph);
    assertEqual(d.speed, "steady");
    assertEqual(d.arrow, "→");
    assertEqual(d.projection, "");
    const html = panel._liveDirectionMarkup("ph", panel._config.sensors.ph, d, { stale: false });
    assert(html.includes("steady last 30 min"), html);
  } finally { restore(); }
});

test("out of range and heading back says when it is back in range; still moving away says so", async () => {
  const restore = freezeTime(NOW);
  try {
    const st = states({ "sensor.humidity": state(63.0) });
    const back = await live(config(), st, { humidity: ramp(63.4, 63.0, 15) });   // −1.6 %/h → 60 in ~1.9 h
    const d1 = back._liveDirection("humidity", back._config.sensors.humidity);
    assertEqual(d1.away, true);
    assert(d1.projection.startsWith("back in range ≈ "), d1.projection);
    const away = await live(config(), st, { humidity: ramp(62.6, 63.0, 15) });   // +1.6 %/h, already above max
    const d2 = away._liveDirection("humidity", away._config.sensors.humidity);
    assertEqual(d2.toward, true);
    assertEqual(d2.projection, "still moving away");
  } finally { restore(); }
});

test("fewer than three readings and no history: the card watches, it does not guess", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await live(config(), states(), { tank_temp: [{ time: minsAgo(1), value: 25.3 }] });
    assertEqual(panel._liveDirection("tank_temp", panel._config.sensors.tank_temp), null);
    const card = panel._liveStatCard("tank_temp", panel._config.sensors.tank_temp);
    assert(card.includes("watching for a trend"), card);
    assert(card.includes("gathering the last 24 h"), card);
  } finally { restore(); }
});

test("history stands in for the ring before it has filled", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await live(config(), states(), {}, { tank_temp: ramp(25.0, 25.3, 30) });
    const d = panel._liveDirection("tank_temp", panel._config.sensors.tank_temp);
    assert(d && d.rising, "direction from history");
  } finally { restore(); }
});

test("binary and unmapped sensors have no direction", async () => {
  const restore = freezeTime(NOW);
  try {
    const cfg = config();
    cfg.sensors.ph.entity_id = "";
    const panel = await live(cfg, states(), { leak: ramp(0, 1, 15) });
    assertEqual(panel._liveDirection("leak", cfg.sensors.leak), null);
    assertEqual(panel._liveDirection("ph", cfg.sensors.ph), null);
  } finally { restore(); }
});

// ── Stale ───────────────────────────────────────────────────────────────────

test("stale: 38 min silent on a fresh reload (15 min fallback) — pill, hollow dot, no direction", async () => {
  const restore = freezeTime(NOW);
  try {
    const st = states({ "sensor.ph": state(8.05, 38) });
    const panel = await live(config(), st, {}, { ph: ramp(8.0, 8.05, 24 * 60, 40) });
    assertEqual(panel._liveStaleAfterMinutes("ph"), 15);
    assertEqual(panel._liveStale("ph", panel._config.sensors.ph).stale, true);
    assertEqual(panel._liveDirection("ph", panel._config.sensors.ph), null);
    const card = panel._liveStatCard("ph", panel._config.sensors.ph);
    assert(card.includes('pill stale">stale 38 min'), card);
    assert(card.includes('live-spark-now stale'), "hollow endpoint");
    assert(card.includes("no fresh readings"), card);
    assert(card.includes('class="live-card stale'), "card status is stale, not the range badge");
  } finally { restore(); }
});

test("stale threshold = 3 × the observed cadence, floored at 10 min and capped at 60 (§8.7)", async () => {
  const restore = freezeTime(NOW);
  try {
    const gaps = (minutes, n = 5) => Array.from({ length: n }, (_, i) => ({ time: minsAgo(minutes * (n - i)), value: 25 }));
    const panel = await live(config(), states(), { tank_temp: gaps(1), ph: gaps(30), room_temp: gaps(5) });
    assertEqual(panel._liveStaleAfterMinutes("tank_temp"), 10);
    assertEqual(panel._liveStaleAfterMinutes("ph"), 60);
    assertEqual(panel._liveStaleAfterMinutes("room_temp"), 15);
    // A sensor two minutes quiet on a one-minute cadence is fine; twelve minutes is stale.
    const fine = await live(config(), states({ "sensor.tank_temp": state(25.3, 2) }), { tank_temp: gaps(1) });
    assertEqual(fine._liveStale("tank_temp", fine._config.sensors.tank_temp).stale, false);
    const gone = await live(config(), states({ "sensor.tank_temp": state(25.3, 12) }), { tank_temp: gaps(1) });
    assertEqual(gone._liveStale("tank_temp", gone._config.sensors.tank_temp).stale, true);
  } finally { restore(); }
});

// ── The ring ────────────────────────────────────────────────────────────────

test("recording readings dedupes by stamp, keeps two hours, skips binary and unmapped", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await live(config(), states(), { tank_temp: [{ time: minsAgo(130), value: 25.0 }, { time: minsAgo(50), value: 25.1 }] });
    panel._recordLiveReadings();
    assertEqual(panel._liveReadings.tank_temp.map((p) => p.value), [25.1, 25.3], "old reading trimmed, new one appended");
    panel._recordLiveReadings();
    assertEqual(panel._liveReadings.tank_temp.length, 2, "same stamp is not recorded twice");
    assertEqual(panel._liveReadings.leak, undefined);
    panel._hass.states["sensor.tank_temp"] = state(25.3, 0);
    panel._recordLiveReadings();
    assertEqual(panel._liveReadings.tank_temp.length, 3, "a fresh report of the same value still counts — that is the cadence");
  } finally { restore(); }
});

test("the series is the history plus only the live readings newer than it", async () => {
  const restore = freezeTime(NOW);
  try {
    const history = ramp(25.0, 25.2, 120, 4);          // ends at now-0? no: ends at NOW
    const panel = await live(config(), states(), { tank_temp: [{ time: minsAgo(10), value: 25.25 }, { time: minsAgo(0), value: 25.3 }] }, { tank_temp: history.slice(0, 3) });
    const series = panel._liveSeries("tank_temp");
    assertEqual(series.length, 5);
    assert(series.every((p, i) => i === 0 || p.time >= series[i - 1].time), "oldest first");
  } finally { restore(); }
});

// ── The marked moment ───────────────────────────────────────────────────────

test("the mark's Δ is now minus the reading nearest the mark; older than the history is —", async () => {
  const restore = freezeTime(NOW);
  try {
    const cfg = config({ display: { liveMarker: { at: isoMinsAgo(48), label: "Opened window" } } });
    const panel = await live(cfg, states(), {}, { room_temp: ramp(26.9, 26.0, 60, 12) });  // a point every 5 min, 26.9 at −60
    const m = panel._liveMarker();
    assertEqual(m.label, "Opened window");
    const delta = panel._liveMarkerDelta("room_temp", cfg.sensors.room_temp, m);
    // Nearest point to −48 min is −50 min: 26.9 − 0.9·(10/60) = 26.75 → Δ = −0.75.
    assert(Math.abs(delta - (-0.75)) < 1e-9, `delta ${delta}`);
    const card = panel._liveStatCard("room_temp", cfg.sensors.room_temp);
    assert(card.includes("−0.8</b> since "), card);
    assert(card.includes("live-spark-mark"), "tick on the sparkline");
    // Tank temp holds no history near the mark: no number, no lie.
    assertEqual(panel._liveMarkerDelta("tank_temp", cfg.sensors.tank_temp, m), null);
    assert(panel._liveStatCard("tank_temp", cfg.sensors.tank_temp).includes("— since "), "dash when unknown");
    const row = panel._liveMarkerRow(m);
    assert(row.includes("Opened window") && row.includes("48 min ago") && row.includes('data-action="live-mark-clear"'), row);
  } finally { restore(); }
});

test("no mark: the row offers one; open: a labelled box with Mark now", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await live();
    assertEqual(panel._liveMarker(), null);
    assert(panel._liveMarkerRow(null).includes('data-action="live-mark-open"'));
    panel._liveMarkOpen = true;
    const row = panel._liveMarkerRow(null);
    assert(row.includes("data-field=\"live-mark-label\"") && row.includes('data-action="live-mark-save"'), row);
  } finally { restore(); }
});

// ── The page ────────────────────────────────────────────────────────────────

test("a reading out of range MOVES to Needs a look; its group counts it as gone (§8.2); the modes are gone", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await live(config(), states({ "sensor.humidity": state(63.5) }));
    const html = panel._liveStats();
    assertEqual(html.split('data-live-card="humidity"').length - 1, 1, "one humidity card on the page");
    const needs = html.indexOf("Needs a look");
    const env = html.indexOf(">Environment<");
    assert(needs > -1 && env > needs, "Needs a look sits above Environment");
    assert(html.indexOf('data-live-card="humidity"') < env, "the humidity card is in Needs a look, not Environment");
    assert(html.includes("1 sensor · 1 needs a look"), html.match(/\d sensors? · \d needs a look/)?.[0] || "no moved count");
    assert(html.includes("2 sensors</span>"), "tank group intact");
    assert(!html.includes("live-mode") && !html.includes("Gauges") && !html.includes("live-gauge"), "modes removed");
    assert(html.includes("live-legend"), "legend");
  } finally { restore(); }
});

test("truth strip names the thing that matters, with its direction; calm state is one line", async () => {
  const restore = freezeTime(NOW);
  try {
    const loud = await live(config(), states({ "sensor.humidity": state(63.0), "sensor.ph": state(8.05, 38) }), { humidity: ramp(63.4, 63.0, 15) });
    const strip = loud._liveTruthMarkup(loud._liveRows());
    assert(strip.includes("<b>3 of 5 in range.</b>"), strip);
    assert(strip.includes("Humidity is high</span> but falling 1.60 %/h — back in range ≈ "), strip);
    assert(strip.includes("pH has not reported for 38 min."), strip);
    assert(strip.includes('<div class="warn"><strong>1</strong><small>attention</small>'), strip);
    assert(strip.includes('<div class="warn"><strong>1</strong><small>stale</small>'), strip);

    const calm = await live();
    const calmStrip = calm._liveTruthMarkup(calm._liveRows());
    assert(calmStrip.includes("<b>All 5 in range.</b>"), calmStrip);
    assert(!calmStrip.includes("warn"), "nothing amber on a calm strip");
    calm._tone = () => "professional";
    assert(calm._liveTruthMarkup(calm._liveRows()).includes("Everything is where it should be."), "professional voice");
    calm._tone = () => "cheeky";
    assert(!calm._liveTruthMarkup(calm._liveRows()).includes("Everything is where it should be."), "cheeky voice differs");
  } finally { restore(); }
});

test("the sparkline draws the safe band with its edges labelled, the last hour bright, and a dot for now", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await live(config(), states(), {}, { tank_temp: ramp(25.0, 25.3, 24 * 60, 48) });
    const svg = panel._liveSparkSvg("tank_temp", panel._config.sensors.tank_temp, panel._liveSeries("tank_temp"), null);
    assert(svg.includes('class="live-spark-band"'), "band");
    assert(svg.includes(">26.0</text>") && svg.includes(">24.0</text>"), "edge labels");
    assert(svg.includes('class="live-spark-history"') && svg.includes('class="live-spark-recent"'), "two segments");
    assert(svg.includes('class="live-spark-now"'), "endpoint");
    assert(!svg.includes("live-spark-mark"), "no tick without a mark");
    const empty = panel._liveSparkSvg("ph", panel._config.sensors.ph, [], null);
    assert(empty.includes("gathering the last 24 h"), empty);
  } finally { restore(); }
});

test("binary and unmapped cards are plain articles with no trend", async () => {
  const restore = freezeTime(NOW);
  try {
    const cfg = config();
    cfg.sensors.ph.entity_id = "";
    const panel = await live(cfg);
    const leak = panel._liveStatCard("leak", cfg.sensors.leak);
    assert(leak.startsWith("\n        <article") && leak.includes("no-trend") && !leak.includes("live-spark"), leak);
    const ph = panel._liveStatCard("ph", cfg.sensors.ph);
    assert(ph.includes("Not mapped") && !ph.includes("show-trend"), ph);
  } finally { restore(); }
});


// ── v2: pace ────────────────────────────────────────────────────────────────

test("pace: a steep last quarter-hour against a mild hour is picking up; a mild one against a steep hour is easing", async () => {
  const restore = freezeTime(NOW);
  try {
    // Ring covers 15 min at −1.2 °C/h; history covers the hour at −0.3 °C/h.
    const up = await live(config(), states(), { room_temp: ramp(26.3, 26.0, 15) }, { room_temp: ramp(26.3, 26.0, 60, 12).filter((p) => p.time < minsAgo(15)) });
    const d1 = up._liveDirection("room_temp", up._config.sensors.room_temp);
    assertEqual(d1.pace, "picking up");
    assert(up._liveDirectionMarkup("room_temp", up._config.sensors.room_temp, d1, { stale: false }).includes('live-pace">· picking up'), "pace shown");
    // Ring: −0.4 °C/h over 15 min; history before it: −2.4 °C/h.
    const ease = await live(config(), states(), { room_temp: ramp(26.1, 26.0, 15) }, { room_temp: ramp(28.0, 26.2, 60, 12).filter((p) => p.time < minsAgo(15)) });
    const d2 = ease._liveDirection("room_temp", ease._config.sensors.room_temp);
    assertEqual(d2.pace, "easing");
  } finally { restore(); }
});

test("pace: a reversal against an hour that was itself moving has just turned — 'now falling' in the strip", async () => {
  const restore = freezeTime(NOW);
  try {
    const st = states({ "sensor.humidity": state(63.0) });
    // Hour was rising +1.6 %/h; the last 15 min fall at −1.6 %/h.
    const panel = await live(config(), st, { humidity: ramp(63.4, 63.0, 15) }, { humidity: ramp(62.2, 63.4, 60, 12).filter((p) => p.time < minsAgo(15)) });
    const d = panel._liveDirection("humidity", panel._config.sensors.humidity);
    assertEqual(d.pace, "just turned");
    const strip = panel._liveTruthMarkup(panel._liveRows());
    assert(strip.includes("but now falling 1.60 %/h — back in range ≈ "), strip);
    const steady = await live(config(), states(), { ph: ramp(8.05, 8.052, 30) }, { ph: ramp(7.9, 8.05, 120, 24) });
    assertEqual(steady._liveDirection("ph", steady._config.sensors.ph).pace, "", "steady never has a pace");
  } finally { restore(); }
});

// ── v2: ledger event ticks ──────────────────────────────────────────────────

function ledger() {
  return [
    { timestamp: isoMinsAgo(20), message: "Water change complete: 20.0 L exchanged", type: "control" },
    { timestamp: isoMinsAgo(35), message: "Hand-fed 5 ml of live brine", type: "control" },
    { timestamp: isoMinsAgo(47), message: "Window fan switched on — room 26.8 °C, dew-point margin 9.1 °C", type: "info" },
    { timestamp: isoMinsAgo(60 * 30), message: "Water change started: 20.0 L (drain_fill)", type: "control" },
    { timestamp: isoMinsAgo(5), message: "OpenReef heartbeat OK", type: "info" },
    { timestamp: "not a date", message: "Hand-fed 2 ml of live brine", type: "control" },
  ];
}

test("event kinds read off the message; unknown messages are not events", async () => {
  const panel = await live();
  assertEqual(panel._liveEventKind("Water change started: 20.0 L (drain_fill)").id, "water");
  assertEqual(panel._liveEventKind("Scheduled water change blocked: source empty").id, "water");
  assertEqual(panel._liveEventKind("Hand-fed 5 ml of live brine (the 11:00 feed)").id, "feed");
  assertEqual(panel._liveEventKind("Reef Roids dosed by hand — 2 ml").id, "feed");
  assertEqual(panel._liveEventKind("Dehumidifier switched off — margin recovered").id, "equipment");
  assertEqual(panel._liveEventKind("Heater switched on by hand from the panel").id, "equipment");
  assertEqual(panel._liveEventKind("OpenReef heartbeat OK"), null);
  assertEqual(panel._liveEventKind("Mixing station: RODI run done — 20 L"), null);
});

test("ticks land only on the groups a kind can move, only within 24 h, only when the kind is on", async () => {
  const restore = freezeTime(NOW);
  try {
    const cfg = config({ activity: ledger() });
    const panel = await live(cfg, states());
    const tank = panel._liveEvents("tank_temp", cfg.sensors.tank_temp);
    assertEqual(tank.map((e) => e.kind), ["water", "feed", "equipment"], "tank sees all three; the 30 h old one and the undated one are dropped");
    const room = panel._liveEvents("room_temp", cfg.sensors.room_temp);
    assertEqual(room.map((e) => e.kind), ["equipment"], "a water change does not move the room");
    assertEqual(panel._liveEvents("leak", cfg.sensors.leak), []);
    const svg = panel._liveSparkSvg("tank_temp", cfg.sensors.tank_temp, ramp(25.0, 25.3, 24 * 60, 48), null, { events: tank });
    assertEqual((svg.match(/live-spark-event/g) || []).length, 3, "three ticks");
    assert(svg.includes("<title>") && svg.includes("· Water change complete: 20.0 L exchanged</title>"), "each tick carries its message");
    // Switch feeds off in Settings.
    cfg.display.liveEventTicks = { feed: false };
    assertEqual(panel._liveEventTicksEnabled(), { water: true, feed: false, equipment: true });
    assertEqual(panel._liveEvents("tank_temp", cfg.sensors.tank_temp).map((e) => e.kind), ["water", "equipment"]);
    const settings = panel._liveStatsSettings();
    assert(settings.includes('data-scope="live-event" data-id="feed" ') && !settings.includes('data-id="feed" checked'), "feed unticked in Settings");
    assert(settings.includes('data-id="water" checked'), "water ticked");
  } finally { restore(); }
});

// ── v2: list density ────────────────────────────────────────────────────────

test("list density: one row per sensor, Needs a look first, mini sparkline without labels", async () => {
  const restore = freezeTime(NOW);
  try {
    const cfg = config({ activity: ledger() });
    cfg.sensors.ph.entity_id = "";
    const panel = await live(cfg, states({ "sensor.humidity": state(63.5) }), { humidity: ramp(63.9, 63.5, 15) }, { tank_temp: ramp(25.0, 25.3, 24 * 60, 48) });
    assertEqual(panel._liveDensity(), "cards", "default");
    panel._liveDensity = () => "list";
    const html = panel._liveStats();
    assert(html.includes('class="live-list"') && !html.includes('class="live-grid"'), "rows, not cards");
    assert(html.includes('data-action="live-density" data-id="list"'), "density switch");
    const rows = [...html.matchAll(/data-live-card="([a-z_]+)"/g)].map((m) => m[1]);
    assertEqual(rows, ["humidity", "tank_temp", "ph", "leak", "room_temp"], "Needs a look first, then the group order");
    assert(html.includes("Environment · needs a look"), "the moved row says so");
    const tankRow = html.slice(html.indexOf('data-live-card="tank_temp"'), html.indexOf('data-live-card="ph"'));
    assert(tankRow.includes('live-spark-svg mini') && !tankRow.includes(">26.0</text>"), "mini sparkline carries no edge labels");
    assert(tankRow.includes('data-live-geom="200,2,4"'), "hover geometry for the mini");
    assert(tankRow.includes("live-spark-event"), "ticks on the mini too");
    const phRow = html.slice(html.indexOf('data-live-card="ph"'), html.indexOf('data-live-card="leak"'));
    assert(phRow.startsWith('data-live-card="ph">') && phRow.includes("Not mapped") && !phRow.includes("show-trend"), "unmapped row is plain");
    assert(html.includes("live-legend") && html.includes("OpenReef events"), "legend explains the ticks");
  } finally { restore(); }
});


// ── 0.7.173: the trend modal in the card's language ────────────────────────

test("trend modal for a live sensor carries the pill, the direction line, the band, the mark, the events and a stats row", async () => {
  const restore = freezeTime(NOW);
  try {
    const cfg = config({ activity: ledger(), display: { liveMarker: { at: isoMinsAgo(48), label: "Opened window" } } });
    const points = ramp(25.0, 25.3, 24 * 60, 48);
    const panel = await live(cfg, states(), { tank_temp: ramp(25.2, 25.3, 30) }, { tank_temp: points });
    panel._trend = { sensorId: "tank_temp", entityId: "sensor.tank_temp", range: "24h", loading: false, points, error: "" };
    const html = panel._trendModal();
    assert(html.includes('class="pill ok">in range'), "pill in the title");
    assert(html.includes('class="live-dir"'), "direction line");
    assert(html.includes('class="live-spark-band"') && html.includes(">26.0</text>") && html.includes(">24.0</text>"), "band with labelled edges");
    assert(html.includes("live-spark-mark") && html.includes("live-spark-event"), "mark and ledger ticks reach a 24 h chart");
    assert(html.includes('data-live-source="trend"') && html.includes('data-live-geom="640,8,48"') && html.includes('data-live-domain="'), "hover geometry and domain");
    assert(html.includes("<small>Average</small>") && html.includes("<small>Since "), "stats row");
    assert(!html.includes("range-picker") && html.includes('data-action="trend-range" data-id="tank_temp" data-range="7d"'), "ranges as the compact switch");
    assert(html.includes('class="live-spark-history"') && html.includes('class="live-spark-recent"'), "dimmed range, bright last hour");
    assert(html.includes("sensor.tank_temp"), "entity id kept, small, at the foot");
  } finally { restore(); }
});

test("trend modal for a hand-logged parameter: the band and the chart, no ring, no mark, no ledger", async () => {
  const restore = freezeTime(NOW);
  try {
    const cfg = config({ activity: ledger(), display: { liveMarker: { at: isoMinsAgo(48), label: "Opened window" } } });
    const panel = await live(cfg, states());
    const points = [10, 5, 1].map((d, i) => ({ time: minsAgo(d * 1440), value: 8 + i * 0.4 }));
    panel._trend = { source: "manual", sensorId: "alkalinity", entityId: "", range: "30d", loading: false, error: "", points, manualMeta: { label: "Alkalinity", unit: "dKH", min: 7, max: 11 }, digits: 2 };
    const html = panel._trendModal();
    assert(html.includes("Hand-logged results") && !html.includes('class="live-dir"'), "no direction line");
    assert(html.includes('class="live-spark-band"') && html.includes(">11.00</text>"), "band from the manual range");
    assert(!html.includes("live-spark-mark") && !html.includes("live-spark-event") && !html.includes("<small>Since "), "nothing from the ring or the ledger");
    assert(html.includes('data-live-range="30d"'), "hover formats dates beyond a day");
    assertEqual(panel._liveTrendWhen(minsAgo(0), "24h").length, 5);
    assert(panel._liveTrendWhen(minsAgo(0), "30d").length > 5, "date + clock");
  } finally { restore(); }
});

// Keep this LAST: tests registered below the runner never run.
await runTests();
