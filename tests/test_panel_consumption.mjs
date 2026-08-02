/**
 * Consumption learning and parameter projection: the advisory numbers behind
 * "you are losing X dKH/day, at this rate you hit Y on Z".
 *
 * This is the arithmetic a reefer acts on. It is also the easiest thing in the
 * panel to break silently — a slope is still a number when the readings behind it
 * are noise, and a projection is still a date when the sensor has been offline for
 * a week. So these tests pin the REFUSALS as hard as the maths: too little history
 * stays "collecting", noise never becomes a trend, a stale manual log says it is
 * stale instead of being extrapolated, and advice is clamped to a safe daily step.
 *
 * Everything here is pure given `_config` plus a stubbed `_number` (the live
 * reading the panel would pull off hass). The clock is frozen because the manual
 * path measures freshness in days.
 *
 * Run standalone:  node tests/test_panel_consumption.mjs
 */

import { assert, assertEqual, freezeTime, makePanel, runTests, test } from "./_panel_harness.mjs";

const NOW = "2026-06-10T12:00:00Z";
const DAY = 86400000;
const ALK = "alkalinity";

// Seachem Reef Fusion is the exact-strength preset: 1 mL raises 0.493 dKH in 25 L,
// so a 300 L tank gets 0.0410833 dKH per mL. Chosen because it unlocks every exact
// mL path, which is where a clamping bug would actually reach a doser.
const POTENCY = (0.493 * 25) / 300;

// A fully-satisfied advisor: acknowledged, real volume, known product, current dose.
function cfg(overrides = {}) {
  const { system = {}, parameters = {}, sensors = {}, ...rest } = overrides;
  return {
    tank: { volumeLitres: 300 },
    dosing: {
      enabled: true,
      system: {
        primaryProduct: "seachem_reef_fusion",
        safetyAcknowledged: true,
        tankVolumeLitres: 300,
        ...system,
      },
      parameters: { alkalinity: { doserMlPerDay: 40, target: 8.3 }, ...parameters },
    },
    sensors: {
      alkalinity: { label: "Alkalinity", unit: "dKH", enabled: true, entity_id: "sensor.alk", min: 7, max: 11 },
      ...sensors,
    },
    ...rest,
  };
}

// One reading per day at 12:00Z, newest last. The engine averages per UTC calendar
// day, so one point per day is the cleanest way to control the fitted slope.
function series(nDays, valueAt, endIso = NOW) {
  const end = Date.parse(endIso);
  return Array.from({ length: nDays }, (_, i) => ({ time: end - (nDays - 1 - i) * DAY, value: valueAt(i) }));
}

function mapped(points, range = "7d") {
  return { points, range, source: "statistics" };
}

async function analyse({ config = cfg(), trend, live = 8.1, health = { status: "ok" }, id = ALK } = {}) {
  const panel = await makePanel(config);
  panel._number = () => live;
  panel._state = () => null;
  return { panel, item: panel._analyseConsumption(id, config.sensors[id], trend, health) };
}

const iso = (daysAgo) => new Date(Date.parse(NOW) - daysAgo * DAY).toISOString();

// Manual history behaves differently from mapped history: it has its own freshness
// gate and its own minimum span, so it needs its own fixture.
function manualCase(readings, overrides = {}) {
  const config = cfg(overrides);
  config.manualReadings = { alkalinity: readings };
  config.manualTests = { enabled: true, schedules: { alkalinity: { enabled: true, cadenceDays: 7, criticalAfterDays: 14 } } };
  const points = readings
    .map((entry) => ({ time: Date.parse(entry.timestamp), value: entry.value }))
    .sort((a, b) => a.time - b.time);
  return { config, trend: { points, range: "7d", source: "manual" } };
}

// Every field a card or the doser Apply button could read. If a refusal path leaks
// one of these as a number, something downstream will happily act on it.
const ADVICE_NUMBERS = [
  "slopePerDay", "projectionDays", "projectionValue", "extraMlPerDay",
  "correctionMl", "suggestedDoseMlPerDay", "reviewDoseMlPerDay", "maxDailyAdjustmentUnits",
];
const TEXTS = ["doseText", "trendText", "projectionText", "confidenceText", "maintenanceText", "correctionText", "safetyText"];

function assertNoPlaceholders(item, context) {
  for (const key of TEXTS) {
    const text = item[key] ?? "";
    assert(!/NaN|Infinity|undefined|\[object/.test(text), `${context}: ${key} leaked a placeholder — "${text}"`);
  }
  for (const key of ADVICE_NUMBERS) {
    const value = item[key];
    assert(value === null || Number.isFinite(value),
      `${context}: ${key} must be null or a finite number, got ${value}`);
  }
  assert(item.current === null || Number.isFinite(item.current),
    `${context}: current reading must be null or finite, got ${item.current}`);
}

test("test_too_little_history_never_produces_a_rate", async () => {
  const restore = freezeTime(NOW);
  try {
    // Three days of readings, and a full week of readings the fetch layer could only
    // pull over a 24h window. Neither is a week of history, so neither gets a slope.
    const cases = [
      ["three days", mapped(series(3, () => 8.5))],
      ["24h window", mapped(series(7, (i) => 8.6 - 0.1 * i), "24h")],
      ["bare array (range unknown)", series(7, (i) => 8.6 - 0.1 * i)],
    ];
    for (const [name, trend] of cases) {
      const { item } = await analyse({ trend });
      assertEqual(item.group, "learning", `${name}: must stay in the learning group`);
      assertEqual(item.confident, false, `${name}: must not claim confidence`);
      assertEqual(item.slopePerDay, null, `${name}: no rate may be published`);
      assertEqual(item.projectionDays, null, `${name}: no projection without a rate`);
      assertEqual(item.reviewDoseMlPerDay, null, `${name}: no mL advice without a rate`);
      assert(/Collecting/.test(item.trendText) && /4 days/.test(item.trendText),
        `${name}: the user must be told it is still collecting, and how much it needs — "${item.trendText}"`);
      assertNoPlaceholders(item, name);
    }
  } finally {
    restore();
  }
});

test("test_a_clear_downward_trend_gives_a_negative_rate_of_the_right_size", async () => {
  const restore = freezeTime(NOW);
  try {
    // Seven daily readings falling exactly 0.1 dKH/day, live reading 8.1, low limit
    // 7.0 — so the honest answer is "-0.1 dKH/day, 11 days of headroom".
    const { item } = await analyse({ trend: mapped(series(7, (i) => 8.6 - 0.1 * i)) });
    assertEqual(item.confident, true, "a clean 7-day fall is exactly what the advisor exists for");
    assert(Math.abs(item.slopePerDay + 0.1) < 1e-6,
      `slope must be ~-0.1 dKH/day, got ${item.slopePerDay}`);
    assert(item.trendText.startsWith("Falling ~0.10 dKH/day"),
      `the direction and rate must be stated in the user's unit — "${item.trendText}"`);
    assertEqual(item.projectionEdge, "low");
    assertEqual(item.projectionValue, 7);
    assert(Math.abs(item.projectionDays - 11) < 1e-6,
      `(8.1 - 7.0) / 0.1 = 11 days, got ${item.projectionDays}`);
    assert(item.projectionText.includes("7.00 dKH") && item.projectionText.includes("11 days"),
      `the projection must name the limit and the date — "${item.projectionText}"`);
    assertEqual(item.status, "ok", "11 days out is worth watching, not an alarm");
    assertNoPlaceholders(item, "clean fall");
  } finally {
    restore();
  }
});

test("test_noise_never_becomes_a_confident_trend", async () => {
  const restore = freezeTime(NOW);
  try {
    // A +-0.4 dKH sawtooth. Least squares will still hand back a slope (-0.037/day
    // here); the residual check is what stops that slope being sold as consumption.
    const { item } = await analyse({
      trend: mapped(series(8, (i) => 8.3 + [0.4, -0.45, 0.35, -0.5, 0.42, -0.38, 0.3, -0.4][i])),
    });
    assertEqual(item.confident, false, "scatter this wide is not a consumption signal");
    assert(/too noisy/.test(item.trendText),
      `the user must be told WHY there is no rate — "${item.trendText}"`);
    assertEqual(item.projectionDays, null, "an untrustworthy rate must not get a date attached");
    assertEqual(item.projectionText, "", "no projection sentence at all when the trend is not trusted");
    assert(/No dosing change suggested/.test(item.maintenanceText),
      `noise must not move a doser — "${item.maintenanceText}"`);
    assertNoPlaceholders(item, "noise");
  } finally {
    restore();
  }
});

test("test_movement_below_the_useful_signal_is_reported_as_steady", async () => {
  const restore = freezeTime(NOW);
  try {
    // A test kit that resolves 0.1 dKH cannot tell you about 0.03 dKH of drift.
    // Below that floor the answer is "nothing to see", not a tiny dose change.
    for (const [name, valueAt] of [
      ["dead flat", () => 8.3],
      ["0.005 dKH/day", (i) => 8.3 - 0.005 * i],
    ]) {
      const { item } = await analyse({ trend: mapped(series(7, valueAt)), live: 8.3 });
      assertEqual(item.confident, false, `${name}: sub-signal movement is not a trend`);
      assertEqual(item.recommendationState, "steady", `${name}: the card should read Steady, not Learning`);
      assert(item.confidenceText.includes("0.10 dKH"),
        `${name}: the signal floor must be quoted in the user's unit — "${item.confidenceText}"`);
      assert(/below OpenReef's useful signal/.test(item.maintenanceText),
        `${name}: "${item.maintenanceText}"`);
      assertEqual(item.projectionDays, null, `${name}: nothing to project from`);
      assertNoPlaceholders(item, name);
    }
  } finally {
    restore();
  }
});

test("test_stale_manual_history_is_reported_stale_not_extrapolated", async () => {
  const restore = freezeTime(NOW);
  try {
    // Cadence 7 days, critical after 14. Four dated results is plenty of DATA — the
    // point is that old data must not be projected forward as if it were current.
    const stale = manualCase([20, 24, 28, 32].map((d) => ({ timestamp: iso(d), value: 8.6 - (36 - d) * 0.03 })));
    const { item: staleItem } = await analyse({ ...stale, live: 8.0 });
    assertEqual(staleItem.status, "critical", "a 20-day-old test is not a basis for dosing");
    assertEqual(staleItem.group, "learning");
    assertEqual(staleItem.slopePerDay, null, "no rate may be derived from stale results");
    assertEqual(staleItem.projectionDays, null, "and certainly no date");
    assert(/20 days ago/.test(staleItem.trendText) && /Retest/.test(staleItem.trendText),
      `the age and the fix must both be stated — "${staleItem.trendText}"`);

    // Past cadence but not yet critical: same refusal, softer status.
    const due = manualCase([9, 13, 17, 21].map((d) => ({ timestamp: iso(d), value: 8.6 - (21 - d) * 0.03 })));
    const { item: dueItem } = await analyse({ ...due, live: 8.0 });
    assertEqual(dueItem.status, "warning", "due-for-a-retest is a nudge, not an emergency");
    assertEqual(dueItem.slopePerDay, null);
    assert(/due for a fresh test/.test(dueItem.trendText), `"${dueItem.trendText}"`);

    // Nothing logged at all.
    const empty = manualCase([]);
    const { item: emptyItem } = await analyse({ ...empty, trend: { points: [], range: "manual", source: "manual" }, live: 8.0 });
    assertEqual(emptyItem.slopePerDay, null);
    assert(/Add a fresh Alkalinity result/.test(emptyItem.trendText), `"${emptyItem.trendText}"`);

    for (const [name, item] of [["stale", staleItem], ["due", dueItem], ["empty", emptyItem]]) {
      assertNoPlaceholders(item, `manual ${name}`);
    }
  } finally {
    restore();
  }
});

test("test_fresh_manual_history_still_needs_a_wide_enough_window", async () => {
  const restore = freezeTime(NOW);
  try {
    // Four results all logged inside five days are fresh but tell you nothing about
    // consumption: a single bad kit reading would dominate the fit.
    const tight = manualCase([0, 1, 2, 3, 4].map((d) => ({ timestamp: iso(d), value: 8.5 - d * 0.1 })));
    const { item: tightItem } = await analyse({ ...tight, live: 8.1 });
    assertEqual(tightItem.confident, false, "five days of manual results is not a consumption baseline");
    assert(/needs about 8 days of manual results/.test(tightItem.confidenceText),
      `the required window must be spelled out — "${tightItem.confidenceText}"`);
    assertEqual(tightItem.projectionDays, null);

    // Spread the same number of results over a real window and it becomes usable.
    const wide = manualCase([0, 4, 8, 12, 16].map((d) => ({ timestamp: iso(d), value: 8.0 + d * 0.03 })));
    const { item: wideItem } = await analyse({ ...wide, live: 8.0 });
    assertEqual(wideItem.confident, true, "16 days of dated results is a baseline");
    assert(Math.abs(wideItem.slopePerDay + 0.03) < 1e-6, `slope should be ~-0.03/day, got ${wideItem.slopePerDay}`);
    assert(wideItem.trendText.includes("from manual test history"),
      `manual advice must say where the number came from — "${wideItem.trendText}"`);
    assertNoPlaceholders(wideItem, "manual wide window");
  } finally {
    restore();
  }
});

test("test_a_crossing_further_than_sixty_days_out_is_not_projected", async () => {
  const restore = freezeTime(NOW);
  try {
    // 0.012 dKH/day off 8.5 towards a 7.0 floor is 125 days away. Nothing that far
    // out survives a water change, so quoting a date would be false precision.
    const { item } = await analyse({ trend: mapped(series(14, (i) => 8.6 - 0.012 * i)), live: 8.5 });
    assertEqual(item.confident, true, "the trend itself is real, it is just slow");
    assertEqual(item.projectionDays, null, "a 125-day projection must be dropped");
    assertEqual(item.projectionEdge, null);
    assertEqual(item.projectionValue, null);
    assertEqual(item.projectionText, "No threshold crossing projected within 60 days.",
      "and the user is told that, rather than shown a blank");
    assertEqual(item.status, "ok");
    assertNoPlaceholders(item, "slow fall");
  } finally {
    restore();
  }
});

test("test_projection_maths_never_divides_by_zero_or_leaks_a_placeholder", async () => {
  const restore = freezeTime(NOW);
  try {
    const cases = [
      // Zero slope: the projection divisor.
      ["identical readings", { trend: mapped(series(7, () => 8.3)), live: 8.3 }],
      // Live sensor offline — the engine has to fall back to the last daily average.
      ["no live reading", { trend: mapped(series(7, (i) => 8.6 - 0.1 * i)), live: null }],
      ["live reading NaN", { trend: mapped(series(7, (i) => 8.6 - 0.1 * i)), live: NaN }],
      // No thresholds configured: nothing to project towards.
      ["no min or max", {
        config: cfg({ sensors: { alkalinity: { label: "Alkalinity", unit: "dKH", enabled: true, entity_id: "sensor.alk" } } }),
        trend: mapped(series(7, (i) => 8.6 - 0.1 * i)),
      }],
      // min === max, so the derived adjustment limit would be a zero range.
      ["zero-width range on an unpreset parameter", {
        config: cfg({
          sensors: { nitrate: { label: "Nitrate", unit: "ppm", enabled: true, entity_id: "sensor.no3", min: 5, max: 5 } },
          parameters: { nitrate: { doserMlPerDay: 10, target: 5 } },
        }),
        trend: mapped(series(7, (i) => 12 - 0.5 * i)),
        live: 9,
        id: "nitrate",
      }],
      // Already past the low limit and still falling.
      ["already below the low limit", { trend: mapped(series(7, (i) => 7.4 - 0.15 * i)), live: 6.5 }],
      // No tank volume, so potency is 0 and every mL divisor is unavailable.
      ["no tank volume", {
        config: cfg({ system: { tankVolumeLitres: 0 }, tank: { volumeLitres: 0 } }),
        trend: mapped(series(7, (i) => 8.6 - 0.1 * i)),
      }],
    ];
    for (const [name, options] of cases) {
      const { item } = await analyse(options);
      assertNoPlaceholders(item, name);
      if (item.projectionDays !== null) {
        assert(item.projectionDays > 0 && item.projectionDays <= 60,
          `${name}: a published projection must be a real number of days ahead, got ${item.projectionDays}`);
      }
    }
  } finally {
    restore();
  }
});

test("test_advice_is_clamped_to_a_safe_daily_step", async () => {
  const restore = freezeTime(NOW);
  try {
    // 0.5 dKH/day of loss "needs" +12.2 mL/day to hold. OpenReef will not tell
    // anyone to make that change in one go: the review step is capped at the
    // per-parameter daily limit (0.3 dKH for alkalinity).
    const { item } = await analyse({ trend: mapped(series(7, (i) => 10.5 - 0.5 * i)), live: 7.5 });
    assertEqual(item.confident, true);
    assertEqual(item.maxDailyAdjustmentUnits, 0.3, "alkalinity moves 0.3 dKH/day at most");
    const step = item.reviewDoseMlPerDay - 40;
    assert(Math.abs(step - 0.3 / POTENCY) < 1e-6,
      `the review step must be the daily limit converted to mL (${(0.3 / POTENCY).toFixed(3)}), got ${step.toFixed(3)}`);
    assert(item.suggestedDoseMlPerDay > item.reviewDoseMlPerDay,
      "the uncapped holding dose is shown for context but is NOT the recommended next step");
    assert(item.maintenanceText.includes("above the product maximum"),
      `and the product ceiling is named when the holding dose clears it — "${item.maintenanceText}"`);

    // The clamp is a floor as well as a ceiling: the product's own daily maximum
    // (Reef Fusion, 4 mL per 25 L => 48 mL/day at 300 L) still wins.
    const nearMax = cfg({ parameters: { alkalinity: { doserMlPerDay: 46, target: 8.3 } } });
    const { item: capped } = await analyse({ config: nearMax, trend: mapped(series(7, (i) => 10.5 - 0.5 * i)), live: 7.5 });
    assertEqual(Number(capped.reviewDoseMlPerDay.toFixed(6)), 48,
      "46 + 7.3 mL/day would clear the product maximum, so the advice stops at 48");
    assertNoPlaceholders(capped, "near product max");
  } finally {
    restore();
  }
});

test("test_the_daily_limit_and_signal_floor_are_per_parameter", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await makePanel(cfg());
    // Hand-set for the three parameters people actually dose; anything else is
    // derived from the configured range so a custom parameter still gets a cap.
    const known = { alkalinity: [0.3, 0.1], calcium: [20, 8], magnesium: [50, 20] };
    for (const [id, [limit, signal]] of Object.entries(known)) {
      assertEqual(panel._dosingDailyAdjustmentLimit(id, { min: 0, max: 1 }), limit,
        `${id}: the hand-set daily limit must win over the sensor range`);
      assertEqual(panel._dosingMinimumSignal(id, { min: 0, max: 1 }), signal,
        `${id}: the hand-set signal floor must win over the sensor range`);
    }
    assertEqual(panel._dosingDailyAdjustmentLimit("nitrate", { min: 0, max: 20 }), 2, "10% of the range");
    assertEqual(panel._dosingMinimumSignal("nitrate", { min: 0, max: 20 }), 0.4, "2% of the range");
    // No range, or a zero-width one: fall back to a non-zero constant. These values
    // end up as divisors and comparison floors, so 0 would be a NaN factory.
    for (const sensor of [{}, { min: 5, max: 5 }, { min: "x", max: "y" }]) {
      assert(panel._dosingDailyAdjustmentLimit("nitrate", sensor) > 0,
        `no usable range must still yield a positive daily limit (${JSON.stringify(sensor)})`);
      assert(panel._dosingMinimumSignal("nitrate", sensor) > 0,
        `no usable range must still yield a positive signal floor (${JSON.stringify(sensor)})`);
    }
  } finally {
    restore();
  }
});

test("test_freshness_says_not_checked_until_a_check_has_run", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await makePanel(cfg());
    // The consumption tab is populated by an explicit "Refresh checks". Until that
    // has run, every number on it is absent — say so rather than implying "now".
    assertEqual(panel._consumptionFreshness(), "Not checked this session", "no consumption state at all");
    panel._consumption = {};
    assertEqual(panel._consumptionFreshness(), "Not checked this session", "state exists but was never checked");
    panel._consumption = { checkedAt: "whenever" };
    assertEqual(panel._consumptionFreshness(), "Not checked this session", "an unparseable stamp is not a time");
    panel._consumption = { checkedAt: NOW };
    const shown = panel._consumptionFreshness();
    assert(shown !== "Not checked this session", "a real stamp must be rendered as a time");
    // Locale formatting varies by machine; only the absence of junk is a contract.
    assert(/\d/.test(shown) && !/NaN|Invalid|undefined/.test(shown), `bad freshness stamp: "${shown}"`);
  } finally {
    restore();
  }
});

test("test_stability_is_borrowed_from_the_health_trend", async () => {
  const restore = freezeTime(NOW);
  try {
    // One source of truth: the Reef Health Score decides how steady a parameter is,
    // and the consumption card just re-renders that verdict. If these two ever
    // disagree the user sees "Steady" next to a critical drift pill.
    const panel = await makePanel(cfg());
    assertEqual(panel._consumptionStability({ status: "learning" }).status, "learning");
    assertEqual(panel._consumptionStability({ status: "critical" }).label, "Drifting");
    assertEqual(panel._consumptionStability({ status: "warning" }).label, "Some drift");
    assertEqual(panel._consumptionStability({ status: "ok" }).stars, "★★★★★");
    // A missing health item is learning, not five stars — absence of evidence is
    // not evidence of stability.
    for (const missing of [null, undefined]) {
      assertEqual(panel._consumptionStability(missing).status, "learning", `${missing} must not read as steady`);
      assertEqual(panel._consumptionStability(missing).stars, "", "learning shows no star rating");
    }
    // And it is carried through onto the item the card renders.
    const { item } = await analyse({ trend: mapped(series(7, (i) => 8.6 - 0.1 * i)), health: { status: "critical" } });
    assertEqual(item.stability.label, "Drifting", "the card must not re-derive stability of its own");
  } finally {
    restore();
  }
});

test("test_the_learning_placeholder_never_advertises_a_number", async () => {
  const restore = freezeTime(NOW);
  try {
    const panel = await makePanel(cfg());
    panel._number = () => 8.1;
    const item = panel._consumptionLearning(ALK, panel._config.sensors[ALK]);
    assertEqual(item.group, "learning");
    assertEqual(item.status, "learning");
    assertEqual(item.confident, false);
    for (const key of ADVICE_NUMBERS) {
      assertEqual(item[key], null, `${key} must be null while learning — a card that reads it must show "--"`);
    }
    assertEqual(item.current, 8.1, "the live reading is still shown; only the DERIVED numbers are withheld");
    assertEqual(item.projectionText, "", "no projection sentence while learning");
    assert(/Locked until/.test(item.correctionText), `correction must be explicitly locked — "${item.correctionText}"`);
    assertEqual(item.digits, 2, "alkalinity renders to 2 dp so a placeholder card matches a real one");

    // The detail and the status/source options are what the callers use to explain
    // WHICH kind of "not yet" this is; they must not be swallowed.
    const stale = panel._consumptionLearning(ALK, panel._config.sensors[ALK], "Retest alkalinity.", {
      status: "critical", source: "manual",
    });
    assertEqual(stale.status, "critical");
    assertEqual(stale.source, "manual");
    for (const key of ["doseText", "trendText", "confidenceText", "maintenanceText", "safetyText"]) {
      assertEqual(stale[key], "Retest alkalinity.", `${key} must carry the caller's reason`);
    }
  } finally {
    restore();
  }
});

test("test_the_mission_tile_leads_with_the_soonest_real_crossing", async () => {
  const restore = freezeTime(NOW);
  try {
    const config = cfg({
      sensors: { calcium: { label: "Calcium", unit: "ppm", enabled: true, entity_id: "sensor.ca", min: 380, max: 460 } },
      parameters: { alkalinity: { doserMlPerDay: 40, target: 8.3 }, calcium: { doserMlPerDay: 40, target: 430 } },
    });
    const panel = await makePanel(config);
    panel._number = () => 8.1;

    assertEqual(panel._dosingMissionState().status, "unknown", "nothing is claimed before a refresh has run");
    assert(/Refresh checks/.test(panel._dosingMissionState().detail), "and the user is told how to get numbers");

    panel._consumption = {
      checkedAt: NOW,
      items: {
        alkalinity: { label: "Alkalinity", status: "critical", projectionDays: 2.5, trendText: "Falling" },
        calcium: { label: "Calcium", status: "warning", projectionDays: 9, trendText: "Falling" },
      },
    };
    const lead = panel._dosingMissionState();
    assertEqual(lead.status, "critical", "one critical parameter makes the whole tile critical");
    assertEqual(lead.value, "2.5 days", "the tile leads with the SOONEST crossing, not the first parameter");
    assert(lead.detail.startsWith("Alkalinity"), `and names it — "${lead.detail}"`);

    // Non-finite projections are junk from a divide-by-zero somewhere upstream; they
    // must never be sorted to the front and rendered as a headline.
    panel._consumption.items = {
      alkalinity: { label: "Alkalinity", status: "critical", projectionDays: Infinity, trendText: "Falling fast" },
      calcium: { label: "Calcium", status: "ok", projectionDays: NaN },
    };
    const junk = panel._dosingMissionState();
    assert(!/NaN|Infinity|undefined|--/.test(`${junk.value} ${junk.detail}`),
      `junk projections leaked into the tile: ${JSON.stringify(junk)}`);
    assertEqual(junk.value, "1 to watch",
      "with no usable date the tile counts the parameters instead of headlining a broken one");
    assertEqual(junk.status, "critical", "the parameter is still critical even with no usable date");

    panel._consumption.items = {
      alkalinity: { label: "Alkalinity", status: "learning", projectionDays: null },
      calcium: { label: "Calcium", status: "learning", projectionDays: null },
    };
    assertEqual(panel._dosingMissionState().value, "Learning", "all-learning reads as learning, not as all-clear");
  } finally {
    restore();
  }
});

test("test_how_soon_the_crossing_is_drives_the_status_ladder", async () => {
  const restore = freezeTime(NOW);
  try {
    // The status a card renders is derived from projectionDays alone: <=3 days is an
    // emergency, <=10 is worth watching, beyond that is business as usual. Getting
    // this ladder wrong is how a tank hits its low limit overnight with a green pill.
    const ladder = [
      // 0.5 dKH/day off 7.5 towards 7.0 => 1 day.
      ["one day out", { trend: mapped(series(7, (i) => 10.5 - 0.5 * i)), live: 7.5 }, "critical", 1, "1.0 day"],
      // Same rate, 0.4 dKH of headroom => 0.8 days, which must read in hours.
      ["under a day", { trend: mapped(series(7, (i) => 10.5 - 0.5 * i)), live: 7.4 }, "critical", 0.8, "19 hours"],
      // 0.2 dKH/day off 8.1 => 5.5 days.
      ["mid week", { trend: mapped(series(7, (i) => 9.5 - 0.2 * i)), live: 8.1 }, "warning", 5.5, "5.5 days"],
      // 0.1 dKH/day off 8.1 => 11 days, just past the watch band.
      ["next fortnight", { trend: mapped(series(7, (i) => 8.6 - 0.1 * i)), live: 8.1 }, "ok", 11, "11 days"],
    ];
    for (const [name, options, status, days, phrase] of ladder) {
      const { item } = await analyse(options);
      assertEqual(item.confident, true, `${name}: the fixture is a clean trend`);
      assert(Math.abs(item.projectionDays - days) < 1e-6,
        `${name}: expected ~${days} days to the limit, got ${item.projectionDays}`);
      assertEqual(item.status, status, `${name}: ${days} days out must render as ${status}`);
      assert(item.projectionText.includes(`in about ${phrase}.`),
        `${name}: the wait must be spelled out as "${phrase}" — "${item.projectionText}"`);
      assertNoPlaceholders(item, name);
    }

    // _formatDays is the only thing between a raw float and the sentence above.
    const panel = await makePanel(cfg());
    assertEqual(panel._formatDays(0.5), "12 hours", "sub-day waits are hours, not '0.5 days'");
    assertEqual(panel._formatDays(1 / 48), "1 hour", "half an hour rounds to one, and reads singular");
    assertEqual(panel._formatDays(0.0001), "1 hour",
      "an imminent crossing must never round down to '0 hours' — that reads as 'already fine'");
    assertEqual(panel._formatDays(1), "1.0 day", "singular day");
    assertEqual(panel._formatDays(2.54), "2.5 days", "under ten days keeps a decimal");
    assertEqual(panel._formatDays(11.4), "11 days", "over ten days does not pretend to that precision");
    for (const junk of [Number.NaN, Infinity, -Infinity, null, undefined]) {
      assertEqual(panel._formatDays(junk), "--", `${junk} must render as "--", never as a duration`);
    }
  } finally {
    restore();
  }
});

test("test_an_offline_live_sensor_falls_back_to_the_last_daily_average", async () => {
  const restore = freezeTime(NOW);
  try {
    // History runs to 8.0 on the last day. If hass has nothing current for the entity
    // the projection must start from that 8.0 — not from 0, not from null, and not
    // from the oldest point. Starting from the wrong value moves the date.
    const trend = mapped(series(7, (i) => 8.6 - 0.1 * i));
    for (const [name, live] of [["no live reading", null], ["live reading NaN", Number.NaN], ["live reading a string state", "unavailable"]]) {
      const { item } = await analyse({ trend, live });
      assert(Math.abs(item.current - 8) < 1e-9,
        `${name}: must fall back to the last daily average 8.0, got ${item.current}`);
      assert(Math.abs(item.projectionDays - 10) < 1e-6,
        `${name}: (8.0 - 7.0) / 0.1 = 10 days, got ${item.projectionDays}`);
      assertEqual(item.status, "warning", `${name}: 10 days out is inside the watch band`);
      assertNoPlaceholders(item, name);
    }
    // And a live reading, when there is one, wins over the historical average.
    const { item: liveItem } = await analyse({ trend, live: 8.1 });
    assertEqual(liveItem.current, 8.1, "a current reading is what the projection starts from");
    assert(Math.abs(liveItem.projectionDays - 11) < 1e-6, `got ${liveItem.projectionDays}`);
  } finally {
    restore();
  }
});

test("test_a_rising_parameter_is_advised_down_and_never_below_zero_ml", async () => {
  const restore = freezeTime(NOW);
  try {
    // 2 dKH/day of RISE. Held literally, the "holding dose" is 40 - 48.7 = -8.7 mL/day.
    // A negative dose is not a thing; it is also the number an Apply button would send.
    const climbing = mapped(series(7, (i) => 8.3 + 2 * i));
    const { item } = await analyse({ trend: climbing, live: 20.3 });
    assertEqual(item.confident, true);
    assert(Math.abs(item.slopePerDay - 2) < 1e-6, `slope must be ~+2 dKH/day, got ${item.slopePerDay}`);
    assert(item.trendText.startsWith("Rising ~2.00 dKH/day"),
      `a rise must be named as a rise — "${item.trendText}"`);
    assertEqual(item.suggestedDoseMlPerDay, 0,
      "the uncapped holding dose is negative, so it floors at 0 mL/day rather than going below");
    assert(Math.abs(item.extraMlPerDay + 0.3 / POTENCY) < 1e-6,
      `the reduction is clamped to the 0.3 dKH/day limit, got ${item.extraMlPerDay}`);
    assert(Math.abs(item.reviewDoseMlPerDay - (40 - 0.3 / POTENCY)) < 1e-6,
      `the review step is one clamped stride down from 40 mL/day, got ${item.reviewDoseMlPerDay}`);
    assertEqual(item.projectionDays, null, "already above the high limit, so there is nothing to project to");
    assert(/above target/.test(item.doNotDoseText), `"${item.doNotDoseText}"`);
    assert(/do not use a one-off chemical correction downward/.test(item.correctionText),
      `you cannot dose a parameter down — "${item.correctionText}"`);
    assertNoPlaceholders(item, "steep rise");

    // Same rise on a tank already dosing only 5 mL/day: one clamped stride down is
    // -2.3 mL/day. The advice must stop at zero and say so.
    const lowDose = cfg({ parameters: { alkalinity: { doserMlPerDay: 5, target: 8.3 } } });
    const { item: floored } = await analyse({ config: lowDose, trend: climbing, live: 20.3 });
    assertEqual(floored.reviewDoseMlPerDay, 0, "a review step may reach 0 mL/day but never go under it");
    assertEqual(floored.suggestedDoseMlPerDay, 0);
    assert(/Suggested next dose is 0 mL\/day/.test(floored.maintenanceText),
      `stopping the doser must be stated, not implied — "${floored.maintenanceText}"`);
    assertNoPlaceholders(floored, "steep rise on a small dose");

    // A gentle rise still gets a projection — towards the HIGH limit this time.
    const { item: gentle } = await analyse({ trend: mapped(series(7, (i) => 8.3 + 0.15 * i)), live: 9.2 });
    assertEqual(gentle.projectionEdge, "high", "a rise runs at the high limit, not the low one");
    assertEqual(gentle.projectionValue, 11);
    assert(Math.abs(gentle.projectionDays - 12) < 1e-6,
      `(11.0 - 9.2) / 0.15 = 12 days, got ${gentle.projectionDays}`);
    assert(gentle.projectionText.includes("high limit of 11.00 dKH") && gentle.projectionText.includes("12 days"),
      `"${gentle.projectionText}"`);
    assertEqual(gentle.status, "ok");
    assertNoPlaceholders(gentle, "gentle rise");
  } finally {
    restore();
  }
});

test("test_several_readings_in_one_day_collapse_to_that_day_average", async () => {
  const restore = freezeTime(NOW);
  try {
    // Real mapped history is not one tidy reading a day: a probe writes constantly and
    // a doser makes a sawtooth. The engine averages per UTC day so the fit sees a
    // baseline. Each day below carries three readings straddling the true value by a
    // DIFFERENT amount, so anything other than a mean (a sum, the first, the newest)
    // moves the fitted slope.
    const clean = series(7, (i) => 8.6 - 0.1 * i);
    const spread = clean.flatMap((point, i) => {
      const swing = 0.2 + 0.05 * i;
      return [
        { time: point.time - 3 * 3600000, value: point.value - swing },
        { time: point.time, value: point.value },
        { time: point.time + 3 * 3600000, value: point.value + swing },
      ];
    });

    const panel = await makePanel(cfg());
    const days = panel._trendDays(spread);
    assertEqual(days.length, 7, "21 readings across 7 UTC days is 7 points, not 21");
    for (const [i, day] of days.entries()) {
      assertEqual(day.count, 3, `day ${day.day} should have collapsed 3 readings`);
      assert(Math.abs(day.avg - (8.6 - 0.1 * i)) < 1e-9,
        `day ${day.day} must average to ${8.6 - 0.1 * i}, got ${day.avg}`);
    }
    assert(days[0].day < days[days.length - 1].day, "days must come out oldest-first for the fit");

    const { item: baseline } = await analyse({ trend: mapped(clean) });
    const { item: busy } = await analyse({ trend: mapped(spread) });
    assert(Math.abs(busy.slopePerDay - baseline.slopePerDay) < 1e-9,
      `intra-day scatter changed the rate: ${baseline.slopePerDay} -> ${busy.slopePerDay}`);
    assertEqual(busy.confident, true, "scatter WITHIN a day is not a reason to distrust the day-to-day trend");
    assert(Math.abs(busy.projectionDays - baseline.projectionDays) < 1e-9);
    assertNoPlaceholders(busy, "busy history");
  } finally {
    restore();
  }
});

test("test_four_consecutive_days_is_the_shortest_usable_mapped_window", async () => {
  const restore = freezeTime(NOW);
  try {
    // The gate is 4 dated days spanning at least 3. Four consecutive days is exactly
    // that boundary and must be USABLE — a stricter window silently parks every new
    // install in "collecting" forever, which is the failure nobody reports.
    const { item: four } = await analyse({ trend: mapped(series(4, (i) => 8.6 - 0.15 * i)) });
    assertEqual(four.confident, true, "four consecutive days is enough to advise from");
    assertEqual(four.group, "advice");
    assert(Math.abs(four.slopePerDay + 0.15) < 1e-6, `got ${four.slopePerDay}`);
    assert(/strong enough for advisory dosing/.test(four.confidenceText),
      `the window must be accepted outright — "${four.confidenceText}"`);
    assertNoPlaceholders(four, "four days");

    // Three is not, and the refusal names the shortfall.
    const { item: three } = await analyse({ trend: mapped(series(3, (i) => 8.6 - 0.15 * i)) });
    assertEqual(three.confident, false);
    assertEqual(three.slopePerDay, null);
  } finally {
    restore();
  }
});

test("test_unreadable_points_are_dropped_rather_than_fitted", async () => {
  const restore = freezeTime(NOW);
  try {
    // History arrives from HA and can carry unavailable/unknown states and missing
    // timestamps. Those are absences, not readings, and must not bend the slope.
    const clean = series(7, (i) => 8.6 - 0.1 * i);
    const { item: baseline } = await analyse({ trend: mapped(clean) });
    const { item: dirty } = await analyse({
      trend: mapped([
        ...clean,
        { time: Date.parse(NOW), value: "unavailable" },
        { time: Date.parse(NOW) - DAY, value: "unknown" },
        { time: Number.NaN, value: 8.4 },
        { time: Date.parse(NOW) - 2 * DAY },
        null,
      ]),
    });
    assert(Math.abs(dirty.slopePerDay - baseline.slopePerDay) < 1e-9,
      `unreadable points changed the fitted rate: ${baseline.slopePerDay} -> ${dirty.slopePerDay}`);
    assertEqual(dirty.confident, baseline.confident);
    assertNoPlaceholders(dirty, "dirty history");
  } finally {
    restore();
  }
});

await runTests();
