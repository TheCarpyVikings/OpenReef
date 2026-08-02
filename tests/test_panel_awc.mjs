/**
 * AWC presentation: how the panel paints the backend's water-change state.
 *
 * The state machine itself is Python and heavily covered (test_awc,
 * test_awc_safety). What had no tests was the half the keeper actually looks at:
 * the banner, the live diagram, the metric cards. That layer has its own failure
 * mode — the engine is right and the screen still lies. R18 (a drain leg stuck at
 * "0%" for its whole duration), R29 ("Calibration OK" while every run was blocked
 * on no_calibration) and R30 (a drain-only abort reading "0.0 L") were all bugs of
 * exactly this kind, so these pin the promises rather than the markup.
 *
 * Everything here is pure given a state/summary blob. The renderers schedule a
 * summary refetch when their cache is stale, so `_awcSummaryLoading` is pinned
 * true — no test may reach for the network.
 *
 * Run standalone:  node tests/test_panel_awc.mjs
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { assert, assertEqual, freezeTime, makePanel, runTests, test } from "./_panel_harness.mjs";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const NOW = "2026-06-04T09:00:00Z";

/** The statuses the backend is allowed to hand the panel, read from its own tuple. */
function backendStatuses() {
  const source = fs.readFileSync(path.join(ROOT, "custom_components", "openreef", "const.py"), "utf8");
  const block = source.match(/AWC_STATUSES\s*=\s*\(([\s\S]*?)\)/);
  const found = block ? [...block[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]) : [];
  // A silently-empty parse would make the loop below vacuous, so prove it read something.
  assert(found.length >= 8 && found.includes("idle") && found.includes("fault"),
    `could not read AWC_STATUSES from const.py: got ${JSON.stringify(found)}`);
  return found;
}

async function awcPanel(config = {}) {
  const panel = await makePanel({ automaticWaterChange: config });
  panel._awcSummaryLoading = true;   // never let a renderer schedule a fetch
  return panel;
}

/**
 * What the banner tells the user at a glance. The AWC banner carries its severity
 * as a border colour (plus the calm subtle-card), so that is the thing to read.
 */
function severityOf(html) {
  const hits = [
    /--error-color/.test(html) && "critical",
    /--warning-color/.test(html) && "warning",
    /--info-color/.test(html) && "info",
    /subtle-card/.test(html) && "calm",
  ].filter(Boolean);
  return hits.length === 1 ? hits[0] : `ambiguous(${hits.join("+") || "none"})`;
}

function noPlaceholders(html, where) {
  assert(!/undefined|NaN|Infinity|\[object/.test(html), `${where} leaked a placeholder value`);
}

const headingOf = (html) => html.match(/<strong>[^<]*/)[0];

/** A fully-derived summary; individual tests take pieces away or break them. */
function summary(overrides = {}) {
  return {
    reservoirs: {
      fresh: { remainingL: 18.5, capacityL: 25, percent: 74, saltPpt: 35.1, dispensedSinceFullL: 6.5, driftPct: null, driftStatus: "" },
      waste: { filledL: 6.5, capacityL: 25, percent: 26, remainingCapacityL: 18.5 },
    },
    sourcePolicy: { mode: "single", lastSourceUsed: "" },
    scheduleText: "5% of the tank every Sunday at 02:00",
    dailyChangeL: 1.5, weeklyChangeL: 10.5, weeklyPercentOfTank: 10.2,
    daysOfFreshRemaining: 12.4, changesRemaining: 3,
    netImbalance: { drainedL: 40, filledL: 40, netL: 0, status: "ok", suggestedTrimL: 0 },
    projectedRemovalPct30d: 35.1,
    pumps: {
      drain: { mlPerS: 20, calibrated: true, recalibrationDue: false },
      fill: { mlPerS: 18, calibrated: true, recalibrationDue: false },
    },
    ...overrides,
  };
}

// --- status → label → severity ------------------------------------------------

test("test_every_declared_backend_status_maps_to_a_label_and_a_severity", async () => {
  // The label rides the live-view heading, the Reef Pulse kiosk title and the
  // diagram's aria-label, so a status with no entry blanks all three at once.
  // Driven off const.py's own tuple rather than a copy of it here.
  //
  // Second half: the states that need attention must also be WORDED differently
  // from idle and carry a non-calm severity. "Idle" on screen during a fault or a
  // running change is the one direction that talks a keeper out of looking.
  const panel = await awcPanel();
  const restore = freezeTime(NOW);
  try {
    for (const status of [...backendStatuses(), "", undefined, "something_new"]) {
      const label = panel._awcStatusLabel(status);
      assert(typeof label === "string" && label.trim().length > 0,
        `status ${JSON.stringify(status)} produced no label`);
      noPlaceholders(label, `label for ${JSON.stringify(status)}`);
      const severity = severityOf(panel._awcStatusBanner({ status }));
      assert(!severity.startsWith("ambiguous"),
        `status ${JSON.stringify(status)} banner is ${severity} — every state must read as exactly one severity`);
    }

    const idle = panel._awcStatusLabel("idle");
    const attention = { draining: "info", filling: "info", exchanging: "info", paused: "warning", fault: "critical" };
    for (const [status, severity] of Object.entries(attention)) {
      assert(panel._awcStatusLabel(status) !== idle,
        `${status} must not share a label with idle ("${idle}")`);
      assertEqual(severityOf(panel._awcStatusBanner({ status })), severity, `${status} banner severity`);
    }

    // A label that does not NAME its own state is as useless as a blank one:
    // "Filling…" over a running drain leg sends the keeper to the wrong pump, and
    // two states sharing one label makes the live view unreadable.
    const names = {
      idle: /idle/i, draining: /drain/i, filling: /fill/i, exchanging: /exchang/i,
      paused: /paus/i, fault: /fault/i, complete: /complete/i,
    };
    const seen = new Map();
    for (const [status, wants] of Object.entries(names)) {
      const label = panel._awcStatusLabel(status);
      assert(wants.test(label), `${status} is labelled "${label}" — a label must name its state`);
      assert(!seen.has(label), `"${label}" labels both ${seen.get(label)} and ${status}`);
      seen.set(label, status);
    }
    assert(!/fill/i.test(panel._awcStatusLabel("draining")) && !/drain/i.test(panel._awcStatusLabel("filling")),
      "draining and filling must not be described with each other's verb — that is a wrong-pump report");

    // That label is the diagram's entire accessible name, so it has to travel.
    assert(panel._awcDiagramSvg({}, { status: "draining" }, null)
      .includes(`aria-label="Automatic water change diagram — ${panel._awcStatusLabel("draining")}"`),
      "the diagram's accessible name must carry the status label");

    // Every live run needs its emergency exit on the banner itself — the Stop
    // button is the only thing between a runaway pump and the settings tab — and
    // the banner heading has to name the state it is reporting, not a fixed word.
    for (const status of ["draining", "filling", "exchanging"]) {
      const running = panel._awcStatusBanner({ status, targetLitres: 10, movedMl: { drain: 1000 } });
      assert(running.includes('data-action="awc-abort"'),
        `${status} must offer Stop — a running change the keeper cannot halt is the hazard`);
      assert(new RegExp(status, "i").test(headingOf(running)),
        `the ${status} banner heading must name ${status}: ${headingOf(running)}`);
    }
  } finally {
    restore();
  }
});

// --- faults and pauses ---------------------------------------------------------

test("test_a_fault_reads_as_critical_and_names_the_reason", async () => {
  const panel = await awcPanel();
  const named = panel._awcStatusBanner({ status: "fault", fault: "Leak detected — all pumps stopped" });
  assertEqual(severityOf(named), "critical", "a latched fault is the loudest thing on the tab");
  assert(named.includes("Leak detected — all pumps stopped"),
    "the backend's latched reason must be shown, not just 'faulted'");
  assert(named.includes('data-action="awc-ack"'), "a latched fault needs its manual re-arm");

  // A fault with no stored reason still has to say something — an empty <p> would
  // read as a fault with no cause, which is worse than a generic sentence.
  const bare = panel._awcStatusBanner({ status: "fault" });
  assertEqual(severityOf(bare), "critical");
  assert(/<p>\s*\S[^<]*<\/p>/.test(bare), "a reasonless fault must still explain itself");
  noPlaceholders(bare, "reasonless fault banner");

  // Fault text is free-form prose composed backend-side (it can carry an entity id
  // or an exception string) and renders as HTML, so it must be escaped.
  const hostile = panel._awcStatusBanner({ status: "fault", fault: '<img src=x onerror="boom">' });
  assert(!hostile.includes("<img"), "fault text must be escaped, not injected");
  assert(hostile.includes("&lt;img"), "the reason should still be readable once escaped");
});

test("test_paused_offers_both_ways_out", async () => {
  const panel = await awcPanel();
  const html = panel._awcStatusBanner({ status: "paused", pausedReason: "Return flow is not confirmed" });
  assertEqual(severityOf(html), "warning", "a pause is recoverable — warning, not critical");
  assert(html.includes("Return flow is not confirmed"), "the pause must name what it is waiting on");
  assert(html.includes('data-action="awc-resume"') && html.includes('data-action="awc-abort"'),
    "a paused change must offer both resume and stop — a pause with only one exit strands the run");
  noPlaceholders(panel._awcStatusBanner({ status: "paused" }), "reasonless pause banner");

  // Pause reasons are composed backend-side from the same free-form material as
  // fault text (entity ids, sensor names), so they need the same escaping.
  const hostile = panel._awcStatusBanner({ status: "paused", pausedReason: '<img src=x onerror="boom">' });
  assert(!hostile.includes("<img"), "the pause reason must be escaped, not injected");
  assert(hostile.includes("&lt;img"), "and still readable once escaped");
});

// --- progress maths ------------------------------------------------------------

test("test_progress_clamps_to_0_100_and_never_divides_by_a_zero_target", async () => {
  // targetLitres is 0 in the default state blob and a run can be observed before
  // the target lands, so the divide has to be guarded — NaN% on a live tank is
  // indistinguishable from a crash. At the other end, dead reckoning plus a
  // resumed run can credit more than the target; "137%" reads as a runaway pump.
  const panel = await awcPanel();
  const restore = freezeTime(NOW);
  try {
    for (const target of [0, undefined, "not a number"]) {
      const html = panel._awcStatusBanner({ status: "draining", targetLitres: target, movedMl: { drain: 1200 } });
      noPlaceholders(html, `draining with target ${JSON.stringify(target)}`);
      assert(html.includes("— 0%"), `target ${JSON.stringify(target)} must read 0%, got ${headingOf(html)}`);
      assert(/of [\d.]+ L target/.test(html), "the target line still renders with its unit");
    }

    const over = panel._awcStatusBanner({ status: "exchanging", targetLitres: 10, movedMl: { drain: 25000, fill: 24000 } });
    assert(headingOf(over).includes("— 100%"), `overshoot must clamp: ${headingOf(over)}`);
    assert(over.includes("Drained 25.00 L") && over.includes("filled 24.00 L"),
      "clamping the percentage must not hide the real litres moved");

    // Simultaneous runs dead-reckon both counters at once, so the header follows
    // the LEADING leg: pacing the headline off the slower pump stalls the display
    // at a low number while most of the tank's water has already gone.
    const mid = panel._awcStatusBanner({ status: "exchanging", targetLitres: 10, movedMl: { drain: 6000, fill: 4000 } });
    assert(headingOf(mid).includes("— 60%"), `the leading leg sets the percentage: ${headingOf(mid)}`);
    assert(mid.includes("Drained 6.00 L") && mid.includes("filled 4.00 L"),
      "and both legs are still reported separately underneath");
  } finally {
    restore();
  }
});

test("test_progress_counts_both_legs_and_follows_the_active_source", async () => {
  // Sequential legs only credit volume when the leg completes, so the header %
  // spans BOTH halves: a finished drain is half the change, not all of it. And
  // the filled figure has to follow activeSourceRole — reading movedMl.fill for a
  // run drawing on source 2 would report a live fill as zero litres.
  const panel = await awcPanel();
  const restore = freezeTime(NOW);
  try {
    const half = panel._awcStatusBanner({ status: "filling", targetLitres: 10, movedMl: { drain: 10000 } });
    assert(half.includes("— 50%"), `drain done, fill not started is halfway: ${headingOf(half)}`);

    const source2 = panel._awcStatusBanner({
      status: "filling", targetLitres: 10, activeSourceRole: "fill2",
      movedMl: { drain: 10000, fill2: 5000 },
    });
    assert(source2.includes("— 75%"), `source-2 litres must count: ${headingOf(source2)}`);
    assert(source2.includes("filled 5.00 L"), "the filled figure must come from the source actually in use");
  } finally {
    restore();
  }
});

test("test_an_in_flight_leg_is_interpolated_but_a_broken_timer_is_not", async () => {
  // R18: without interpolation the flagship live view sat at "Draining — 0%" for
  // the whole drain leg and then jumped. The interpolation is driven by the leg's
  // own timer, so a missing or back-to-front timer must degrade to "no progress
  // yet" rather than inventing a fraction.
  const panel = await awcPanel();
  const restore = freezeTime(NOW);
  try {
    const midLeg = panel._awcStatusBanner({
      status: "draining", targetLitres: 10, movedMl: {},
      legStartedAt: "2026-06-04T08:59:00Z", legEndsAt: "2026-06-04T09:01:00Z",
    });
    assert(midLeg.includes("— 25%"), `half of the drain leg is a quarter of the change: ${headingOf(midLeg)}`);
    assert(midLeg.includes("Drained 5.00 L"), "the interpolated litres are shown, not just the percentage");

    for (const timer of [
      {},
      { legStartedAt: "2026-06-04T09:05:00Z", legEndsAt: "2026-06-04T09:01:00Z" },
      { legStartedAt: "nonsense", legEndsAt: "also nonsense" },
    ]) {
      const html = panel._awcStatusBanner({ status: "draining", targetLitres: 10, movedMl: {}, ...timer });
      noPlaceholders(html, `draining with timer ${JSON.stringify(timer)}`);
      assert(html.includes("— 0%"), `a broken leg timer must not invent progress: ${JSON.stringify(timer)}`);
    }

    // The other end of the same interpolation: a leg still running past its own
    // ETA (a slow pump, a partly blocked line) must stop crediting litres at the
    // leg's target rather than extrapolating — otherwise the banner reports more
    // water moved than the whole change was ever going to move.
    const overrun = panel._awcStatusBanner({
      status: "draining", targetLitres: 10, movedMl: {},
      legStartedAt: "2026-06-04T08:00:00Z", legEndsAt: "2026-06-04T08:30:00Z",
    });
    assert(overrun.includes("— 50%"), `an overrunning drain leg caps at its own target: ${headingOf(overrun)}`);
    assert(overrun.includes("Drained 10.00 L"), "credited litres stop at the leg target, they do not run away");
  } finally {
    restore();
  }
});

// --- the diagram ---------------------------------------------------------------

test("test_the_diagram_reports_levels_flow_and_hazards_honestly", async () => {
  // Levels come off the backend's derived summary; a stale capacity or a
  // hand-edited reservoir can put a percentage outside 0-100, and the fill rect is
  // drawn straight from it. Flow arrows and spinning pumps are the fastest read on
  // the tab — two flows means both pumps are energised, so painting them on an
  // idle system is a direct misreport of what the hardware is doing.
  const panel = await awcPanel();
  const rect = (html, clip) => html.match(new RegExp(`${clip}\\)"><rect[^>]*>`))[0];
  const heightOf = (frag) => Number(frag.match(/height="([\d.]+)"/)[1]);

  const over = panel._awcDiagramSvg({}, { status: "idle" }, {
    reservoirs: { fresh: { percent: 740, remainingL: 18.5 }, waste: { percent: -20, filledL: 0 } },
  });
  assertEqual(heightOf(rect(over, "awcFreshClip")), 108, "over 100% must draw a full container, not spill past it");
  assertEqual(heightOf(rect(over, "awcWasteClip")), 0, "a negative level must draw empty");
  noPlaceholders(over, "diagram with out-of-range levels");

  const junk = panel._awcDiagramSvg({}, { status: "idle" }, {
    reservoirs: { fresh: { percent: "abc" }, waste: { percent: null } },
  });
  assertEqual(heightOf(rect(junk, "awcFreshClip")), 0, "an unreadable level must draw empty, not NaN");
  noPlaceholders(junk, "diagram with unreadable levels");

  const flows = (html) => (html.match(/class="awc-flow"/g) || []).length;
  const sum = summary();
  assertEqual(flows(panel._awcDiagramSvg({}, { status: "idle" }, sum)), 0, "an idle system moves no water");
  assertEqual(flows(panel._awcDiagramSvg({}, { status: "draining" }, sum)), 1, "draining runs one pipe");
  assertEqual(flows(panel._awcDiagramSvg({}, { status: "filling" }, sum)), 1, "filling runs one pipe");
  assertEqual(flows(panel._awcDiagramSvg({}, { status: "exchanging" }, sum)), 2, "an exchange runs both pumps at once");

  // Counting animations is not enough — the animation has to be on the right
  // pump. A spinning fill impeller during a drain is a hardware report, and it is
  // the one the keeper trusts before reaching for the sump.
  const spinning = (html) => ["Fill", "Drain"].filter((name) => {
    const group = html.split('<g data-action="tab"').find((part) => part.includes(`${name} pump — tap to calibrate`));
    assert(group, `${name} pump is missing from the diagram entirely`);
    return group.includes('class="awc-spin"');
  });
  assertEqual(spinning(panel._awcDiagramSvg({}, { status: "idle" }, sum)), [], "nothing spins on an idle system");
  assertEqual(spinning(panel._awcDiagramSvg({}, { status: "draining" }, sum)), ["Drain"], "draining spins the drain pump alone");
  assertEqual(spinning(panel._awcDiagramSvg({}, { status: "filling" }, sum)), ["Fill"], "filling spins the fill pump alone");
  assertEqual(spinning(panel._awcDiagramSvg({}, { status: "exchanging" }, sum)), ["Fill", "Drain"], "an exchange spins both");

  // Levels grow from the bottom of the container, at a height proportional to the
  // percentage: a rect pinned to the top reads as full when the drum is nearly dry.
  const yOf = (frag) => Number(frag.match(/y="([-\d.]+)"/)[1]);
  const BOTTOM = 258, FULL = 108;
  for (const [clip, pct] of [["awcFreshClip", 74], ["awcWasteClip", 26]]) {
    const frag = rect(panel._awcDiagramSvg({}, { status: "idle" }, sum), clip);
    assert(Math.abs(heightOf(frag) - FULL * pct / 100) < 0.01,
      `${clip} must be drawn at ${pct}% of the container: ${frag}`);
    assert(Math.abs(yOf(frag) + heightOf(frag) - BOTTOM) < 0.01,
      `${clip} must sit on the bottom of the container, not hang from the top: ${frag}`);
  }

  // The container captions are LITRES, not the percentage that drives the fill
  // rect right above them: "Fresh 74.0L" off a 74%-full 25 L drum is the same
  // class of lie as an unlabelled number, and it reads as plenty when it is not.
  const real = panel._awcDiagramSvg({}, { status: "idle" }, sum);
  assert(real.includes("Fresh 18.5L"), `fresh caption is litres remaining: ${(real.match(/Fresh [^<]*/) || ["missing"])[0]}`);
  assert(real.includes("Waste 6.5L"), `waste caption is litres held: ${(real.match(/Waste [^<]*/) || ["missing"])[0]}`);

  // Mid-run the diagram carries its own readout, and its filled figure follows the
  // source actually in use — a run drawing on source 2 is not a zero-litre fill.
  const readout = panel._awcDiagramSvg({}, {
    status: "filling", targetLitres: 10, activeSourceRole: "fill2", movedMl: { drain: 10000, fill2: 4500 },
  }, sum);
  assert(readout.includes("drained 10.00 · filled 4.50 / 10.0 L"),
    `the live readout must show both legs against the target: ${(readout.match(/drained[^<]*/) || ["missing"])[0]}`);

  assert(!/drained/.test(panel._awcDiagramSvg({}, { status: "idle", targetLitres: 10, movedMl: { drain: 5000 } }, sum)),
    "an idle system is not mid-change, whatever the last run left behind in the state blob");

  // Hazard badges come off the live sensor snapshot, not the status. Each one is
  // raised ONE AT A TIME: a badge wired to the wrong float ("waste full" driven by
  // the fresh-empty switch) sends the keeper to the wrong drum, and testing all
  // four together cannot tell the two apart.
  const hazards = { leak: "LEAK", highLevel: "HIGH", freshEmpty: "EMPTY", wasteFull: "FULL" };
  for (const [flag, badge] of Object.entries(hazards)) {
    panel._awcSummary = { live: { [flag]: true } };
    const html = panel._awcDiagramSvg({}, { status: "fault" }, sum);
    assert(html.includes(badge), `${flag} must raise the ${badge} badge`);
    for (const [other, otherBadge] of Object.entries(hazards)) {
      if (other === flag) continue;
      assert(!html.includes(otherBadge),
        `${flag} alone must not raise ${otherBadge} — that badge belongs to ${other}`);
    }
  }

  panel._awcSummary = { live: { leak: true, highLevel: true, freshEmpty: true, wasteFull: true } };
  const hazard = panel._awcDiagramSvg({}, { status: "fault" }, sum);
  for (const badge of Object.values(hazards)) {
    assert(hazard.includes(badge), `the ${badge} hazard must be visible alongside the others`);
  }

  panel._awcSummary = { live: {} };
  const clear = panel._awcDiagramSvg({}, { status: "fault" }, sum);
  for (const badge of Object.values(hazards)) {
    assert(!clear.includes(badge), `no sensor is tripped — ${badge} must not be painted`);
  }
  panel._awcSummary = null;
});

// --- the metric cards ----------------------------------------------------------

test("test_the_calibration_card_tells_the_truth_about_blocked_runs", async () => {
  // R29: "OK — within window" for a never-calibrated pump was a lie while the
  // engine blocked every run on no_calibration. Never-calibrated is critical and
  // says runs are blocked; merely stale is a warning; both healthy is ok.
  const panel = await awcPanel();
  const cardOf = (html) => html.match(/aria-label="Calibration[^"]*"/)[0];
  const statusOf = (html) => html.match(/class="summary-card (\w+)"[^>]*data-id="settings"/)[1];

  const never = panel._awcMetrics(summary({
    pumps: { drain: { calibrated: false, recalibrationDue: false }, fill: { calibrated: true, recalibrationDue: false } },
  }));
  assertEqual(statusOf(never), "critical", "an uncalibrated pump blocks every run — that is not a warning");
  assert(cardOf(never).includes("runs blocked until calibrated"), `must say why: ${cardOf(never)}`);
  // R29 was the HEADLINE, not the colour: the card said "OK" in the one place a
  // keeper glances, with the truth in the small print underneath.
  assert(/Calibration — Needed —/.test(cardOf(never)), `the headline must call it out: ${cardOf(never)}`);
  assert(!/Calibration — OK/.test(cardOf(never)), "and must never read OK while every run is blocked");

  // Either pump blocks the run, so both roles have to be checked — a fill pump
  // that was never calibrated is exactly as blocking as the drain.
  const neverFill = panel._awcMetrics(summary({
    pumps: { drain: { calibrated: true, recalibrationDue: false }, fill: { calibrated: false, recalibrationDue: false } },
  }));
  assertEqual(statusOf(neverFill), "critical", "an uncalibrated FILL pump blocks runs just as hard as the drain");
  assert(/Calibration — Needed —/.test(cardOf(neverFill)), `and says so: ${cardOf(neverFill)}`);

  const stale = panel._awcMetrics(summary({
    pumps: { drain: { calibrated: true, recalibrationDue: true }, fill: { calibrated: true, recalibrationDue: false } },
  }));
  assertEqual(statusOf(stale), "warning", "a stale calibration still runs — nag, do not alarm");
  assert(cardOf(stale).includes("recalibrate"), `must say what to do: ${cardOf(stale)}`);
  assert(/Calibration — Due —/.test(cardOf(stale)), `a nag reads as due, not needed: ${cardOf(stale)}`);

  const healthy = panel._awcMetrics(summary());
  assertEqual(statusOf(healthy), "ok", "two fresh calibrations are simply fine");
  assert(/Calibration — OK — within window/.test(cardOf(healthy)), `and say so plainly: ${cardOf(healthy)}`);
});

test("test_supply_and_drift_cards_say_what_to_do", async () => {
  const panel = await awcPanel();
  const cardOf = (html, label) => html.match(new RegExp(`aria-label="${label}[^"]*"`))[0];
  const statusOf = (html, label) => {
    const at = html.indexOf(`aria-label="${label}`);
    return html.slice(0, at).match(/class="summary-card (\w+)"[^>]*$/)[1];
  };

  // No schedule yet means no consumption rate, so "days of fresh remaining" is
  // genuinely unknown. Unknown is a dash and stays calm — an idle new system is
  // not a system in trouble.
  const unknown = panel._awcMetrics(summary({ daysOfFreshRemaining: null }));
  assert(cardOf(unknown, "Fresh remaining").includes("—"), "unknown supply reads as a dash");
  assertEqual(statusOf(unknown, "Fresh remaining"), "ok", "unknown must not masquerade as a shortage");
  noPlaceholders(unknown, "metrics with an unknown supply");

  assertEqual(statusOf(panel._awcMetrics(summary({ daysOfFreshRemaining: 2.4 })), "Fresh remaining"), "warning",
    "under three days of saltwater left is worth mixing more");

  // T9: the drift card is actionable — direction and litres, plus the ledger reset.
  const over = panel._awcMetrics(summary({
    netImbalance: { drainedL: 40, filledL: 36.5, netL: 3.5, status: "warning", suggestedTrimL: 3.5 },
  }));
  assert(cardOf(over, "Net drift").includes("add 3.50 L"), `drained more than filled → add: ${cardOf(over, "Net drift")}`);
  assert(over.includes('data-action="awc-reset-ledger"'), "correcting drift needs the ledger reset alongside it");
  assertEqual(statusOf(over, "Net drift"), "warning",
    "a drifted ledger has to LOOK wrong — advice in a card that stays green is advice nobody reads");

  const under = panel._awcMetrics(summary({
    netImbalance: { drainedL: 36.5, filledL: 40, netL: -3.5, status: "warning", suggestedTrimL: -3.5 },
  }));
  assert(cardOf(under, "Net drift").includes("remove 3.50 L"),
    `filled more than drained → remove, and the litres stay positive: ${cardOf(under, "Net drift")}`);

  const balanced = panel._awcMetrics(summary());
  assert(cardOf(balanced, "Net drift").includes("in balance"), "a balanced ledger says so");
  assert(!balanced.includes("awc-reset-ledger"), "nothing to reset when nothing has drifted");
  assertEqual(statusOf(balanced, "Net drift"), "ok", "and stays calm while it is balanced");

  // Each card reads the field it is labelled with, and its headline value carries
  // the unit. A bare "3.50" on a tab dealing in litres, days and percent at once
  // is three different readings; "10.5%" sourced from the weekly LITRES is a
  // fourth. Pinned as whole values, so a wrong field cannot hide behind a unit.
  const values = {
    "Fresh remaining": "Fresh remaining — 12.4 d — days at current rate",
    "Weekly change": "Weekly change — 10.2% — of tank volume",
    "Net drift": "Net drift — 0.00 L — in balance",
    "30-day dilution": "30-day dilution — 35% — old water removed",
  };
  for (const [label, wants] of Object.entries(values)) {
    assertEqual(cardOf(balanced, label), `aria-label="${wants}"`, `${label} card`);
  }

  // A fill pump quietly over-dispensing shows up nowhere else in the UI: the
  // reservoir hit empty while the model still claimed litres in hand.
  const drifting = summary();
  drifting.reservoirs.fresh = { ...drifting.reservoirs.fresh, driftStatus: "warning", driftPct: 14 };
  const driftHtml = panel._awcMetrics(drifting);
  assert(driftHtml.includes("Fill-pump calibration drift 14%"), "calibration drift is named with its size");
  assert(driftHtml.includes("6.5 L dispensed"), "and with the litres the model thought it had dispensed");
  assert(!balanced.includes("Fill-pump calibration drift"), "a pump that is tracking gets no nag");
});

test("test_a_second_source_reports_its_own_level_in_litres", async () => {
  // Stage B: two fresh reservoirs. The strip only appears when a second source
  // exists, and each tile must carry litres, capacity and percent — an unlabelled
  // number here is the difference between "18 L left" and "18% left".
  const panel = await awcPanel();
  assertEqual(panel._awcSourceStrip(summary()), "", "one source needs no comparison strip");

  const sum = summary();
  sum.reservoirs.fresh2 = { remainingL: 4.2, capacityL: 25, percent: 16.8, saltPpt: 34.2, dispensedSinceFullL: 20.8, driftPct: 12, driftStatus: "warning" };
  sum.sourcePolicy = { mode: "alternate", lastSourceUsed: "fill2" };
  sum.netImbalance.perSource = { fill: 30.5, fill2: 12.4 };
  const html = panel._awcSourceStrip(sum);
  noPlaceholders(html, "two-source strip");
  assert(html.includes("18.5 / 25 L"), "source 1 shows litres remaining against capacity");
  assert(html.includes("4.2 / 25 L"), "source 2 shows litres remaining against capacity");
  assert(/\(74%\)/.test(html) && /\(17%\)/.test(html), "each tile carries its own percentage");
  assert(html.includes("drift 12%"), "a drifting source is called out on its own tile");
  assert(html.includes("source 2"), "the internal role fill2 must be spoken as 'source 2'");
  assert(!html.includes("fill2"), "the raw pump role should not leak into the copy");

  // Both tiles carrying the right NUMBERS is only half of it — each number has to
  // be on the right tile. Swapped tiles read as "top up source 2" while it is
  // source 1 that is nearly full, and hang the drift warning on the wrong drum.
  const tileOf = (name) => {
    const tile = html.split('<div class="setting-card subtle-card">').find((part) => part.includes(name));
    assert(tile, `no tile for ${name}`);
    return tile.split("</div>")[0];
  };
  const one = tileOf("Source 1"), two = tileOf("Source 2");
  assert(one.includes("18.5 / 25 L") && one.includes("(74%)") && one.includes("35.1 ppt"),
    `source 1's own figures must sit on source 1's tile: ${one}`);
  assert(two.includes("4.2 / 25 L") && two.includes("(17%)") && two.includes("34.2 ppt"),
    `source 2's own figures must sit on source 2's tile: ${two}`);
  assert(two.includes("drift 12%") && !one.includes("drift"),
    "the drift warning belongs to the drum that drifted, and to no other");
  assert(html.includes("delivered 30.5 L / 12.4 L"),
    `the per-source ledger reads source 1 then source 2, in litres: ${(html.match(/delivered[^<]*/) || ["missing"])[0]}`);
  assert(html.includes("Last source used: source 2"), "and names which drum fed the last change");
});

// --- history and the calm path -------------------------------------------------

test("test_history_shows_both_sides_of_a_partial_change", async () => {
  // R30: a drain-only abort read "0.0 L · partial", hiding the litres that had
  // already LEFT the tank — the number you need to decide whether to top up by hand.
  const panel = await awcPanel();
  const restore = freezeTime(NOW);
  try {
    assertEqual(panel._awcHistory({}), "", "no history, no section");

    const html = panel._awcHistory({
      history: [
        { completedAt: "2026-06-03T02:00:00Z", drainedL: 5.2, filledL: 5.2, method: "batch_sequential" },
        { completedAt: "2026-06-02T02:00:00Z", drainedL: 5.2, filledL: 0, partial: true, method: "batch_simultaneous" },
        { completedAt: "", drainedL: 0, filledL: 0 },
      ],
    });
    noPlaceholders(html, "history rows");
    assert(html.includes("drained 5.2 / filled 0.0 L"), "an unbalanced change must show both sides");
    assert(html.includes("· partial"), "and say it did not finish");
    assert(/<small>5\.2 L/.test(html), "a balanced change is one figure, not two");

    // "partial" has to land on the row that WAS partial. A completed change
    // wearing that tag sends the keeper hunting for litres nothing lost.
    const rowFor = (needle) => {
      const row = html.split('class="manual-history-row"').find((part) => part.includes(needle));
      assert(row, `no history row containing ${needle}`);
      return row;
    };
    assert(rowFor("drained 5.2 / filled 0.0 L").includes("· partial"),
      "the aborted change is the one tagged partial");
    assert(!rowFor("<small>5.2 L").includes("partial"),
      "and the completed change is not — the tag must follow the flag, not decorate every row");
    assert(html.includes("batch sequential") && !html.includes("batch_sequential"),
      "the method is spoken, not printed as an enum");
    assert(html.includes("Unknown time"), "an unparseable timestamp reads as unknown, never as an invalid date");
  } finally {
    restore();
  }
});

test("test_an_idle_system_with_no_history_reads_calm", async () => {
  // A brand-new install has an empty state blob and no summary. Every one of these
  // surfaces has to be quiet and complete rather than a wall of dashes and zeros.
  //
  // The one thing an idle banner IS allowed to flag is the post-change ATO
  // hold-off: T10, where the stabilisation window looked like a failed ATO — the
  // exact moment a keeper watching the sump drop would override the safety.
  const panel = await awcPanel();
  const restore = freezeTime(NOW);
  try {
    const banner = panel._awcStatusBanner({});
    assertEqual(severityOf(banner), "calm", "nothing has happened yet — that is not a problem");
    assert(banner.includes("Last change: never"), "never run is stated plainly");
    assert(banner.includes("Next scheduled: —"), "no schedule is a dash, not a blank");
    noPlaceholders(banner, "first-run idle banner");

    // …and once the system HAS run, both stamps must actually render. An idle
    // banner permanently reading "never · —" is the same screen a broken schedule
    // produces, so the calm path has to prove it can show real times. (Formatting
    // is the browser's locale; assert the shape, not the punctuation.)
    const ran = panel._awcStatusBanner({
      status: "idle", lastRun: "2026-06-03T02:00:00Z", nextRun: "2026-06-10T03:15:00Z",
    });
    noPlaceholders(ran, "idle banner with a run behind it");
    assert(!ran.includes("never") && !ran.includes("Next scheduled: —"),
      `a system that has run must not read as never-run: ${ran.match(/<p>[^<]*/)[0]}`);
    // Compared against the panel's own formatter rather than a literal: the stamp
    // is rendered in the viewer's locale (a 2-digit year in de-DE, a 4-digit one
    // in en-GB), so pinning the text would pin the test machine's LANG.
    const lastTxt = ran.match(/Last change: ([^·]*)/)[1].trim();
    const nextTxt = ran.match(/Next scheduled: ([^<]*)/)[1].trim();
    assertEqual(lastTxt, panel._formatActivityTime("2026-06-03T02:00:00Z"), "last change is the last run, formatted");
    assertEqual(nextTxt, panel._formatActivityTime("2026-06-10T03:15:00Z"), "next scheduled is the next run, formatted");
    assert(/\d{1,2}:\d{2}/.test(lastTxt), `and carries a real clock time: "${lastTxt}"`);
    assert(lastTxt !== nextTxt, "last and next are different instants and must not print the same stamp");

    assertEqual(panel._awcMetrics(null), "", "no summary yet means no metric cards, not empty ones");

    const svg = panel._awcDiagramSvg({}, {}, null);
    noPlaceholders(svg, "diagram with no summary");
    assert(/Fresh --\s*L/.test(svg) && /Waste --\s*L/.test(svg),
      "unknown volumes read as -- with their unit attached");
    assert(!/drained/.test(svg), "an idle diagram carries no progress readout");

    const held = panel._awcStatusBanner({ status: "idle", atoSuspendedUntil: "2026-06-04T09:30:00Z" });
    assert(held.includes("ATO paused"), "a suspended ATO must be named on the idle banner");
    assert(/class="pill warning"/.test(held), "and carry a warning pill, since it is a temporary override");
    assert(/\d{1,2}:\d{2}/.test(held.match(/ATO paused[^<]*/)[0]), "the chip must say when it resumes");
    for (const clear of ["2026-06-04T08:30:00Z", "", "not a date"]) {
      assert(!panel._awcStatusBanner({ status: "idle", atoSuspendedUntil: clear }).includes("ATO paused"),
        `an expired or unset hold-off (${JSON.stringify(clear)}) must not claim the ATO is paused`);
    }
  } finally {
    restore();
  }
});

// --- the tab as a whole --------------------------------------------------------

test("test_running_states_lock_the_manual_change_form", async () => {
  // The only defence against a double-start from the UI. Backend-blocked is a
  // toast; a disabled button is the thing that stops the click.
  const panel = await awcPanel({ schedule: { amount: 5, amountUnit: "percent" } });
  for (const status of ["draining", "filling", "exchanging", "paused"]) {
    const html = panel._awcControls({ status });
    assert(/data-action="awc-run" disabled/.test(html), `${status} must disable "Change now"`);
    assert(/data-awc-run-amount[^>]*disabled/.test(html), `${status} must disable the amount input`);
  }
  const idle = panel._awcControls({ status: "idle" });
  assert(!/data-action="awc-run" disabled/.test(idle), "an idle system can start a change");
  assert(idle.includes('value="5"'), "the form is seeded from the saved schedule amount");
  assert(/<input type="number" min="0"[^>]*data-awc-run-amount/.test(idle),
    "and cannot be pointed at a negative volume — there is no such water change");

  // The amount is meaningless without its unit: 5 litres and 5% of the tank differ
  // by an order of magnitude on most systems, and this form starts a real run.
  assert(/<option value="percent" selected>/.test(idle), "a percent schedule pre-selects percent");

  const litres = await awcPanel({ schedule: { amount: 12, amountUnit: "litres" } });
  const litresHtml = litres._awcControls({ status: "idle" });
  assert(/<option value="litres" selected>/.test(litresHtml), "a litres schedule pre-selects litres");
  assert(!/<option value="percent" selected>/.test(litresHtml), "and only one unit may be selected");

  // No saved unit at all must land on percent — the safer default, since the
  // seeded amount was authored as a percentage everywhere else in the feature.
  const unset = await awcPanel({ schedule: { amount: 5 } });
  assert(/<option value="percent" selected>/.test(unset._awcControls({ status: "idle" })),
    "an unset unit defaults to % of tank, not litres");
});

test("test_an_unconfigured_system_gets_a_checklist_but_still_shows_a_fault", async () => {
  // A first-run tab is a setup checklist, not an all-zero diagram. The one thing
  // that must survive that early return is a non-idle state: a fault latched
  // before setup finished (or after a pump binding was removed) still has to be
  // visible and re-armable, or the feature is stuck with no way back.
  const restore = freezeTime(NOW);
  try {
    const fresh = await awcPanel({ enabled: true, pumps: {} });
    const html = fresh._automaticWaterChange();
    assert(html.includes("Open setup"), "an unconfigured system is walked through setup");
    assert(!html.includes("<svg"), "no diagram of hardware that does not exist yet");
    assert(!html.includes("summary-card"), "and no metrics derived from nothing");
    noPlaceholders(html, "first-run AWC tab");

    const faulted = await awcPanel({ enabled: true, pumps: {}, state: { status: "fault", fault: "Leak detected" } });
    const faultHtml = faulted._automaticWaterChange();
    assert(faultHtml.includes("Leak detected"), "a fault must survive the empty-state shortcut");
    assert(faultHtml.includes('data-action="awc-ack"'), "and stay re-armable from the checklist screen");
  } finally {
    restore();
  }
});

test("test_a_configured_system_gets_the_whole_tab_not_the_checklist", async () => {
  // The mirror image of the first-run test, and the only place the tab is
  // assembled end to end. Once pumps are bound the checklist must get out of the
  // way: a working system shown a "set up your hardware" screen has no diagram,
  // no Change-now button and no metrics — the feature simply disappears.
  const restore = freezeTime(NOW);
  try {
    const panel = await awcPanel({
      enabled: true,
      pumps: { drain: { switchEntity: "switch.drain" }, fill: { switchEntity: "switch.fill" } },
      schedule: { amount: 5, amountUnit: "percent" },
      state: { status: "idle", lastRun: "2026-06-03T02:00:00Z" },
      history: [{ completedAt: "2026-06-03T02:00:00Z", drainedL: 5.2, filledL: 5.2, method: "batch_sequential" }],
    });
    panel._awcSummary = { summary: summary() };
    const html = panel._automaticWaterChange();

    assert(!html.includes("Open setup"), "a bound system is past the setup checklist");
    for (const [what, needle] of [
      ["the live diagram", "<svg"],
      ["the manual-change form", 'data-action="awc-run"'],
      ["the metric cards", "summary-card"],
      ["the history section", "Recent changes"],
      ["the plain-language schedule line", "5% of the tank every Sunday at 02:00"],
      ["the idle banner", "Last change:"],
    ]) {
      assert(html.includes(needle), `a configured tab is missing ${what}`);
    }
    noPlaceholders(html, "configured AWC tab");
    assert(!html.includes("DEMO MODE"), "a real system is not labelled a sandbox");

    // Demo mode is the other way past the checklist: no hardware, but a live
    // sandbox that must render the real tab or the demo shows nothing at all.
    const demo = await awcPanel({ enabled: true, pumps: {}, simulation: { enabled: true } });
    const demoHtml = demo._automaticWaterChange();
    assert(demoHtml.includes("DEMO MODE"), "the sandbox says so, loudly");
    assert(demoHtml.includes("<svg") && demoHtml.includes('data-action="awc-run"'),
      "and still renders the real tab, not the setup checklist");
    assert(!demoHtml.includes("Open setup"), "demo mode is not an unconfigured system");
  } finally {
    restore();
  }
});

test("test_the_live_snapshot_wins_over_the_stored_config_state", async () => {
  // R19: config event refreshes are suppressed while the settings form is dirty or
  // Pulse is open, so banners froze mid-run — "Draining" with a Stop button after
  // the change had finished, faults invisible on the kiosk. The summary snapshot
  // is the live truth; config is only the fallback.
  const panel = await awcPanel();
  const stored = { state: { status: "draining" } };
  assertEqual(panel._awcLiveState(stored).status, "draining", "with no snapshot the stored state is all there is");

  panel._awcSummary = { state: { status: "fault", fault: "Leak detected" } };
  assertEqual(panel._awcLiveState(stored).status, "fault", "a fresh snapshot must override a stale stored state");

  for (const bad of [null, "fault", 7]) {
    panel._awcSummary = { state: bad };
    assertEqual(panel._awcLiveState(stored).status, "draining",
      `a malformed snapshot state (${JSON.stringify(bad)}) must fall back, not blank the banner`);
  }
  panel._awcSummary = null;
  assertEqual(JSON.stringify(panel._awcLiveState({})), "{}", "no state anywhere is an empty object, not a throw");
});

await runTests();
