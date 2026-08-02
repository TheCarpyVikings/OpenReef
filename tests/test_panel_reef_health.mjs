/**
 * Reef Health scoring: the 0-100 headline on Mission Control.
 *
 * This number is the whole promise of the "intelligence layer" — it is the one
 * thing a user reads before deciding whether the tank needs them. It is also
 * panel-only: there is no backend counterpart to drift from, so nothing else
 * catches it when the arithmetic changes.
 *
 * What is pinned here is the SHAPE of the judgement, not the exact tuning:
 * profile weights are a complete, normalised set; a critical reading costs more
 * than a warning; a hard cap is a ceiling that beats a flattering weighted
 * average; disabled and muted sensors are out of the score entirely; and the
 * category breakdown shown under the number actually adds up to the number.
 *
 * Run standalone:  node tests/test_panel_reef_health.mjs
 */

import { assert, assertEqual, freezeTime, makePanel, runTests, test } from "./_panel_harness.mjs";

const CLOCK = "2026-06-04T09:00:00Z";

/**
 * The scorer reads a handful of instance fields the constructor would normally
 * install (hass states, backend validation, fetched trends). Object.create skips
 * the constructor, so they are set here — explicitly empty unless a test says
 * otherwise, so no test inherits another's noise.
 */
function prep(panel, states = {}, patch = {}) {
  panel._hass = { states };
  panel._sensorMeta = {};
  panel._validation = null;
  panel._lightingWindow = { data: null, loading: false, at: 0 };
  panel._healthTrends = { checkedAt: "", items: {}, error: "" };
  return Object.assign(panel, patch);
}

async function scoreFor(config, states = {}, patch = {}) {
  const panel = prep(await makePanel(config), states, patch);
  return { panel, health: panel._reefHealthScore() };
}

/** Every test reads the clock through maintenance/mute freshness. */
async function atClock(fn) {
  const restore = freezeTime(CLOCK);
  try {
    return await fn();
  } finally {
    restore();
  }
}

const TEMP = { label: "Temperature", enabled: true, alertsEnabled: true, entity_id: "sensor.temp", min: 24, max: 27, unit: "C" };
const ALK = { label: "Alkalinity", enabled: true, alertsEnabled: true, entity_id: "sensor.alk", min: 7.5, max: 9, unit: "dKH", group: "chemistry" };

// A quiet, fully-mapped tank. Individual tests break one thing at a time.
function tank(overrides = {}) {
  const { sensors, ...rest } = overrides;
  return {
    tank: { profile: "mixed_reef" },
    sensors: {
      temp: { ...TEMP },
      alkalinity: { ...ALK },
      ...(sensors || {}),
    },
    equipment: {},
    manualTests: { enabled: false, schedules: {} },
    maintenance: { enabled: false, tasks: {}, completions: {} },
    ...rest,
  };
}

const CALM = { "sensor.temp": { state: "25.5" }, "sensor.alk": { state: "8.2" } };

/** The weighted average the breakdown claims, recomputed from what the UI shows. */
function weightedFromBreakdown(health) {
  return Object.values(health.categories).reduce((total, item) => total + item.score * item.weight, 0);
}

// --- weights ----------------------------------------------------------------

test("test_every_profile_weights_the_same_six_categories_and_sums_to_one", async () => {
  // The weighted average is only a 0-100 score if the weights are a complete,
  // normalised set. A profile missing a category silently zero-weights it (that
  // category's losses become free); weights summing to less than 1 mean a
  // perfect tank can never reach 100.
  const panel = await makePanel({});
  const categories = panel._healthCategoryChoices().map(([id]) => id);
  const profiles = panel._tankProfileChoices().map(([id]) => id);
  assert(profiles.length >= 6, "the profile list should still cover FOWLR through SPS");
  for (const profile of profiles) {
    const weights = panel._healthWeights(profile);
    assertEqual(Object.keys(weights).sort(), [...categories].sort(),
      `${profile} must weight exactly the categories the breakdown renders`);
    const sum = categories.reduce((total, id) => total + weights[id], 0);
    assert(Math.abs(sum - 1) < 1e-9, `${profile} weights sum to ${sum}, not 1`);
    for (const id of categories) {
      assert(weights[id] > 0, `${profile} zero-weights ${id}, which would make its losses free`);
    }
  }
  // Config can carry a profile from an older release. Falling back beats
  // returning undefined weights, which would score every tank 0.
  assertEqual(panel._healthWeights("reef_of_the_future"), panel._healthWeights("mixed_reef"));
  const { health } = await atClock(() => scoreFor(tank({ tank: { profile: "reef_of_the_future" } }), CALM));
  assertEqual(health.profile, "mixed_reef", "an unknown profile must not leak into the score");
});

test("test_the_profile_decides_how_much_a_chemistry_problem_hurts", async () => {
  // The point of profiles: the same alkalinity crash should dent an SPS tank
  // harder than a fish-only system. If these ever score the same, the profile
  // picker is decoration.
  const scores = {};
  await atClock(async () => {
    for (const profile of ["fish_only_fowlr", "sps"]) {
      const { health } = await scoreFor(
        tank({ tank: { profile } }),
        { ...CALM, "sensor.alk": { state: "20" } },
      );
      scores[profile] = health;
    }
  });
  assertEqual(scores.sps.categories.chemistry.score, scores.fish_only_fowlr.categories.chemistry.score,
    "the raw chemistry damage is the same; only its weight differs");
  assert(scores.sps.categories.chemistry.weight > scores.fish_only_fowlr.categories.chemistry.weight,
    "SPS must weight chemistry above FOWLR");
  assert(scores.sps.score < scores.fish_only_fowlr.score,
    `the same alk crash should cost an SPS tank more: sps ${scores.sps.score} vs fowlr ${scores.fish_only_fowlr.score}`);
});

// --- severity ---------------------------------------------------------------

test("test_a_critical_reading_always_costs_more_than_a_warning", async () => {
  const panel = await makePanel({});
  const families = [
    ["temp", {}, "life"],
    ["alkalinity", { group: "chemistry" }, "chemistry"],
    ["flow", { group: "flow" }, "stability"],
    ["salinity", { group: "water" }, "stability"],
  ];
  for (const [id, sensor, category] of families) {
    const critical = panel._sensorAlertImpact(id, sensor, "critical");
    const warning = panel._sensorAlertImpact(id, sensor, "warning");
    assertEqual(critical.category, category, `${id} critical must land in ${category}`);
    assertEqual(warning.category, category, `${id} warning must land in ${category}`);
    assert(critical.points > warning.points,
      `${id}: critical costs ${critical.points}, warning ${warning.points} — a critical must hurt more`);
    assertEqual(critical.group, "action", `${id} critical belongs in the action list`);
    assertEqual(warning.group, "watch", `${id} warning belongs in the watch list`);
  }
  // Life support is the most expensive thing a single sensor can report.
  const lifePoints = panel._sensorAlertImpact("temp", {}, "critical").points;
  for (const [id, sensor] of families.slice(1)) {
    assert(lifePoints > panel._sensorAlertImpact(id, sensor, "critical").points,
      `a life-support critical must outrank ${id}`);
  }

  // And the ordering has to survive the whole pipeline, not just the table.
  const { calm, warn, crit } = await atClock(async () => ({
    calm: (await scoreFor(tank(), CALM)).health,
    // 8.95 dKH sits inside the range but within the 10% warning buffer of max 9.
    warn: (await scoreFor(tank(), { ...CALM, "sensor.alk": { state: "8.95" } })).health,
    crit: (await scoreFor(tank(), { ...CALM, "sensor.alk": { state: "20" } })).health,
  }));
  assert(calm.score > warn.score && warn.score > crit.score,
    `score must fall with severity: calm ${calm.score}, warning ${warn.score}, critical ${crit.score}`);
  assertEqual([calm.warningCount, warn.warningCount, crit.warningCount], [0, 1, 0]);
  assertEqual([calm.criticalCount, warn.criticalCount, crit.criticalCount], [0, 0, 1]);
  assert(crit.categories.chemistry.lost > warn.categories.chemistry.lost,
    "the damage lands in the chemistry category either way, just harder");
  assertEqual(crit.losses[0].status, "critical", "the sorted loss list leads with the critical");

  // The card reads topReason and nextAction out verbatim. On a clean tank both
  // fall back to fixed copy, and an empty fallback is a blank line on the
  // dashboard where the explanation should be.
  assertEqual(calm.topReason, "All scoring checks look steady", "a calm tank still has to say something");
  assertEqual(calm.nextAction, "Keep monitoring and refresh health after the next meaningful tank change.");

  // Severity outranks size in the loss list: a 9-point warning must not push an
  // 8-point critical off the top, because losses[0] is the line the user reads.
  const { health: mixed } = await atClock(() => scoreFor(
    tank(),
    { ...CALM, "sensor.temp": { state: "26.8" } },
    { _validation: { missing_entities: ["sensor.gone"], armed_unavailable: [] } },
  ));
  assertEqual(mixed.losses.map((loss) => [loss.status, loss.points]), [["critical", 8], ["warning", 9]],
    "a critical sorts ahead of a warning even when the warning cost more points");
  const { health: twoCriticals } = await atClock(() => scoreFor(
    tank(),
    { ...CALM, "sensor.temp": { state: "40" } },
    { _validation: { missing_entities: ["sensor.gone"], armed_unavailable: [] } },
  ));
  assertEqual(twoCriticals.losses.map((loss) => loss.points), [22, 8],
    "within one severity the more expensive loss leads");
});

// --- caps -------------------------------------------------------------------

test("test_a_hard_cap_beats_a_flattering_weighted_average", async () => {
  // The whole reason caps exist. One leak detector should not be averaged away
  // by five categories that happen to be fine.
  const { health } = await atClock(() => scoreFor(
    tank({ sensors: { leak: { label: "Leak", enabled: true, alertsEnabled: true, entity_id: "binary_sensor.leak", kind: "binary", group: "safety" } } }),
    { ...CALM, "binary_sensor.leak": { state: "on" } },
  ));
  assert(weightedFromBreakdown(health) > 90,
    `the weighted average alone would read ${Math.round(weightedFromBreakdown(health))} — that is what the cap has to beat`);
  assertEqual(health.appliedCap?.limit, 35, "an active leak detector caps Reef Health at 35");
  assertEqual(health.score, 35, "the cap, not the average, is what the user sees");
  assertEqual(health.status, "critical");
  assertEqual(health.grade, "E");
  assertEqual(health.topReason, "Leak detector active", "the cap explains the number");

  // With two hazards live, the worst one sets the ceiling — and the other is
  // still recorded, because a leak does not make a high-water alarm go away.
  const { health: both } = await atClock(() => scoreFor(
    tank({
      sensors: {
        leak: { label: "Leak", enabled: true, alertsEnabled: true, entity_id: "binary_sensor.leak", kind: "binary", group: "safety" },
        high_water: { label: "High water", enabled: true, alertsEnabled: true, entity_id: "binary_sensor.hw", kind: "binary", group: "safety" },
      },
    }),
    { ...CALM, "binary_sensor.leak": { state: "on" }, "binary_sensor.hw": { state: "on" } },
  ));
  assertEqual(both.caps.map((cap) => cap.limit).sort((a, b) => a - b), [35, 45],
    "both hazards must be recorded, not just the one that wins");
  assertEqual(both.score, 35, "the lowest cap wins");
  assertEqual(both.appliedCap.limit, 35);

  // Caps are not only for binary hazards. A life-support READING out of range is
  // a hard ceiling too, however flattering the rest of the tank looks.
  const { health: hot } = await atClock(() => scoreFor(tank(), { ...CALM, "sensor.temp": { state: "40" } }));
  assert(weightedFromBreakdown(hot) > 90,
    `the average alone would read ${Math.round(weightedFromBreakdown(hot))} — a tank at 40 C is not a 90-something`);
  assertEqual(hot.appliedCap?.limit, 65, "a tank temperature outside range caps Reef Health at 65");
  assertEqual(hot.score, 65);
  assertEqual(hot.topReason, "Tank temperature outside range");
  assertEqual(hot.status, "critical");
});

test("test_a_cap_is_a_ceiling_and_never_a_floor", async () => {
  // A cap must never RESCUE a tank that scored worse on its own. Here every
  // chemistry sensor is out of range and ten mapped entities are missing, so the
  // weighted average lands below the display-flow cap of 75.
  const chem = (label, entity, min, max) => ({ label, enabled: true, alertsEnabled: true, entity_id: entity, min, max, group: "chemistry" });
  const { health } = await atClock(() => scoreFor(
    tank({
      sensors: {
        alkalinity: chem("Alkalinity", "sensor.alk", 7.5, 9),
        calcium: chem("Calcium", "sensor.ca", 400, 450),
        magnesium: chem("Magnesium", "sensor.mg", 1300, 1400),
        nitrate: chem("Nitrate", "sensor.no3", 2, 15),
        phosphate: chem("Phosphate", "sensor.po4", 0.02, 0.1),
        salinity: chem("Salinity", "sensor.sal", 34, 35.5),
      },
      equipment: { wm1: { label: "Wavemaker", type: "display_wavemaker", armed: true, switch_entity_id: "switch.wm1" } },
    }),
    {
      ...CALM,
      "sensor.alk": { state: "20" }, "sensor.ca": { state: "900" }, "sensor.mg": { state: "3000" },
      "sensor.no3": { state: "99" }, "sensor.po4": { state: "5" }, "sensor.sal": { state: "50" },
      "switch.wm1": { state: "off" },
    },
    { _validation: { missing_entities: ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"], armed_unavailable: [] } },
  ));
  assertEqual(health.appliedCap.limit, 75, "all display wavemakers off still caps at 75");
  assert(health.score < 75, `a cap must not lift a worse score: got ${health.score}`);
  assertEqual(health.score, Math.round(weightedFromBreakdown(health)),
    "with the average already below the cap, the average is the answer");
  // Stopped flow is serious but it is not a leak. The cap's own severity is what
  // colours the card, so it must stay a warning rather than a red alert.
  assertEqual(health.appliedCap.status, "warning");
  assertEqual(health.status, "warning", "the card's status follows the cap that applied");

  // The 75 cap means ALL display flow is down. With one of two pumps still
  // running there is no ceiling at all — the losses alone carry it.
  const wm = (label, entity) => ({ label, type: "display_wavemaker", armed: true, switch_entity_id: entity });
  const { health: partial } = await atClock(() => scoreFor(
    tank({ equipment: { wm1: wm("Wavemaker 1", "switch.wm1"), wm2: wm("Wavemaker 2", "switch.wm2") } }),
    { ...CALM, "switch.wm1": { state: "off" }, "switch.wm2": { state: "on" } },
  ));
  assertEqual(partial.caps, [], "one pump off out of two is not 'all display flow is off'");
  assertEqual(partial.categories.equipment.lost, 15, "the stopped pump is still charged as a loss");
  assertEqual(partial.categories.stability.lost, 10, "and reduced display flow still costs stability");
});

// --- the breakdown has to add up --------------------------------------------

test("test_the_category_breakdown_adds_up_to_the_headline_number", async () => {
  // The Reef Health card shows per-category scores and weights next to the
  // total. If those stop reconciling, the explanation is fiction.
  //
  // The damage is spread deliberately unevenly across an SPS profile — heavy in
  // the lightest category (confidence, 0.05) and light elsewhere — so a total
  // that ignored the weights would land nowhere near the weighted one.
  const { health } = await atClock(() => scoreFor(
    tank({
      tank: { profile: "sps" },
      sensors: { flow: { label: "Flow", enabled: true, alertsEnabled: true, entity_id: "sensor.flow", min: 500, max: 2000, group: "flow" } },
      maintenance: {
        enabled: true,
        tasks: { water_change: { label: "Water change", enabled: true, cadenceDays: 7, criticalAfterDays: 14, scheduleMode: "interval" } },
        completions: { water_change: [{ id: "old", timestamp: "2026-04-01T09:00:00Z" }] },
      },
    }),
    { ...CALM, "sensor.alk": { state: "20" }, "sensor.flow": { state: "600" } },
    { _validation: { missing_entities: ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"], armed_unavailable: [] } },
  ));
  assertEqual(health.appliedCap, null, "this case is deliberately cap-free so the arithmetic is visible");
  assertEqual(health.score, Math.round(weightedFromBreakdown(health)),
    "the total must be the weighted average of the categories shown beside it");
  const unweighted = Object.values(health.categories).reduce((sum, item) => sum + item.score, 0) / 6;
  assert(Math.abs(health.score - unweighted) > 5,
    "this fixture is meant to distinguish a weighted total from a flat average — it no longer does");
  for (const [id, item] of Object.entries(health.categories)) {
    assertEqual(item.score, Math.max(0, 100 - Math.min(item.lost, 100)),
      `${id}: the category score must be 100 minus the points it lost`);
    assert(item.score >= 0 && item.score <= 100, `${id} scored ${item.score}, outside 0-100`);
  }
  const totalLost = Object.values(health.categories).reduce((sum, item) => sum + item.lost, 0);
  const totalPoints = health.losses.reduce((sum, loss) => sum + loss.points, 0);
  assertEqual(totalLost, totalPoints, "every listed loss must be booked against a category, and vice versa");

  // Five simultaneous life-support criticals are 110 points against a category
  // worth 100. Without the clamp the weighted average goes negative and the
  // whole score becomes nonsense.
  const binary = (label, entity) => ({ label, enabled: true, alertsEnabled: true, entity_id: entity, kind: "binary", group: "safety" });
  const { health: flooded } = await atClock(() => scoreFor(
    tank({
      sensors: {
        leak: binary("Leak", "binary_sensor.leak"),
        high_water: binary("High water", "binary_sensor.hw"),
        low_water: binary("Low water", "binary_sensor.lw"),
        dissolved_oxygen: { label: "Dissolved oxygen", enabled: true, alertsEnabled: true, entity_id: "sensor.do", min: 6, max: 9 },
      },
    }),
    {
      ...CALM,
      "sensor.temp": { state: "40" }, "sensor.do": { state: "0.5" },
      "binary_sensor.leak": { state: "on" }, "binary_sensor.hw": { state: "on" }, "binary_sensor.lw": { state: "on" },
    },
  ));
  assertEqual(flooded.categories.life.score, 0, "life support floors at 0, it does not go negative");
  assert(flooded.score >= 0 && flooded.score <= 100, `score ${flooded.score} escaped 0-100`);
  assertEqual(flooded.status, "critical");
});

// --- what must never reach the score ----------------------------------------

test("test_a_disabled_sensor_never_contributes", async () => {
  // Turning a sensor off is how a user says "I do not own this". It must not
  // then be scored, counted, or asked to be mapped.
  const wild = { ...CALM, "sensor.alk": { state: "20" } };
  const { health: off } = await atClock(() => scoreFor(
    tank({ sensors: { alkalinity: { ...ALK, enabled: false } } }), wild));
  const { health: on } = await atClock(() => scoreFor(tank(), wild));

  assertEqual(off.score, 100, "a disabled sensor's reading is not the tank's problem");
  assertEqual(off.losses, [], "nothing about a disabled sensor may appear as a loss");
  assertEqual(off.categories.chemistry.lost, 0);
  assert(off.detail.includes("1/1 sensors mapped"), `a disabled sensor is not counted at all: "${off.detail}"`);
  assert(on.score < off.score, "the same reading on an ENABLED sensor must cost something");
});

test("test_muting_alerts_takes_a_sensor_out_of_the_score_until_the_mute_expires", async () => {
  // Two ways to mute: permanently (alertsEnabled) and until a timestamp. Both
  // mean "stop nagging me about this one", so neither may drag the score down —
  // and an EXPIRED mute must bring the penalty straight back.
  const wild = { ...CALM, "sensor.alk": { state: "20" } };
  const cases = {
    alertsOff: tank({ sensors: { alkalinity: { ...ALK, alertsEnabled: false } } }),
    mutedUntilTomorrow: tank({ alerts: { muteUntil: { alkalinity: "2026-06-05T09:00:00Z" } } }),
  };
  await atClock(async () => {
    for (const [name, config] of Object.entries(cases)) {
      const { health } = await scoreFor(config, wild);
      assertEqual(health.score, 100, `${name}: a muted sensor must not reduce Reef Health`);
      assertEqual(health.losses, [], `${name}: a muted sensor must not appear as a loss`);
      assertEqual(health.criticalCount, 0, `${name}: nor be counted as a critical`);
    }
    const { health: expired } = await scoreFor(
      tank({ alerts: { muteUntil: { alkalinity: "2026-06-03T09:00:00Z" } } }), wild);
    assert(expired.score < 100, "an expired mute must stop hiding the reading");
    assertEqual(expired.losses.map((loss) => loss.category), ["chemistry"]);
  });
});

test("test_muting_temperature_does_not_hide_an_unsupervised_heater", async () => {
  // The exception that has to hold: muting temp alerts is about notifications.
  // An armed heater with no trustworthy temperature is a safety fact, so it
  // still caps the score and still costs life-support points.
  const { health } = await atClock(() => scoreFor(
    tank({
      sensors: { temp: { ...TEMP, alertsEnabled: false } },
      equipment: { heater: { label: "Heater", type: "heater", armed: true, switch_entity_id: "switch.heater" } },
    }),
    { ...CALM, "switch.heater": { state: "on" } },
  ));
  assertEqual(health.appliedCap?.limit, 60, "an armed heater without a verified temperature caps at 60");
  assertEqual(health.score, 60);
  assert(health.losses.some((loss) => loss.category === "life" && loss.status === "critical"),
    `it must also cost life-support points: ${JSON.stringify(health.losses)}`);
});

test("test_context_only_readings_are_reported_but_do_not_move_the_score", async () => {
  // Room temperature, CO2, ORP and friends describe the room, not the water.
  // They are shown because they explain things — a hot room explains a hot tank —
  // but they must never be the reason the headline number dropped.
  const { health } = await atClock(() => scoreFor(
    tank({ sensors: { room_temp: { label: "Room temp", enabled: true, alertsEnabled: true, entity_id: "sensor.room", min: 18, max: 26, unit: "C", group: "room" } } }),
    { ...CALM, "sensor.room": { state: "40" } },
  ));
  assertEqual(health.score, 100, "a hot room is context, not a reef health problem");
  assertEqual(health.losses, []);
  assertEqual(health.contextCount, 1, "it is still surfaced — silently dropping it would be worse");
  assertEqual(health.criticalCount, 1, "and still counted honestly in the alert tally");
  const note = health.groups.context[0];
  assertEqual(note.affectsScore, false);
  assert(note.detail.includes("does not reduce Reef Health"),
    `the note must say why it is not scored: "${note.detail}"`);
});

test("test_an_enabled_but_unmapped_sensor_is_a_confidence_problem_not_a_water_problem", async () => {
  // "I own an alk probe but haven't mapped it" says nothing about alkalinity.
  // Charging it to chemistry would invent a chemistry problem out of a setup gap.
  const { health } = await atClock(() => scoreFor(
    tank({ sensors: { alkalinity: { ...ALK, entity_id: "" } } }), CALM));
  assertEqual(health.categories.chemistry.lost, 0, "an unmapped probe is not a chemistry reading");
  assert(health.categories.confidence.lost > 0, "it is a confidence gap and must be booked there");
  assertEqual(health.unknownCount, 1);
  assert(health.losses.every((loss) => loss.category === "confidence"),
    `every loss here should be confidence: ${JSON.stringify(health.losses.map((loss) => loss.category))}`);
  assert(health.losses.some((loss) => /unmapped/i.test(loss.label)),
    "the user has to be told which fact is missing");
  // Two distinct doubts, both real: the setup gap itself, and the reading the
  // probe therefore cannot give. Either one silently costing nothing would leave
  // a half-configured tank looking better than it is.
  assertEqual(health.losses.map((loss) => [loss.label, loss.points]),
    [["Alkalinity is enabled but unmapped", 12], ["Alkalinity is not reporting", 8]]);
  assertEqual(health.categories.confidence.lost, 20);
  assert(health.detail.includes("1/2 sensors mapped"),
    `the detail line must count the mapped ones, not the enabled ones: "${health.detail}"`);
});

test("test_faults_that_are_not_sensor_readings_still_reach_the_score", async () => {
  // Reef Health is not a sensor average. Three feeds land in it that no probe
  // reports — the backend's audit of the entity map, the interlock warnings, and
  // maintenance that has gone overdue — and each is a place a penalty can be
  // quietly zeroed without any sensor test noticing.
  await atClock(async () => {
    const { health: unavailable } = await scoreFor(tank(), CALM,
      { _validation: { missing_entities: [], armed_unavailable: ["switch.heater", "switch.pump"] } });
    assertEqual(unavailable.categories.equipment.lost, 36,
      "each armed device OpenReef cannot reach costs 18 equipment points");
    assertEqual(unavailable.losses.map((loss) => [loss.category, loss.status]), [["equipment", "critical"]],
      "an armed control OpenReef cannot see is a critical, not a note");
    assert(unavailable.score < 100, "and it must move the headline number");

    // An armed skimmer with no armed return pump: a relationship OpenReef cannot
    // honour, reported through the interlock feed rather than any sensor.
    const { health: interlock } = await scoreFor(
      tank({ equipment: { sk: { label: "Skimmer", type: "skimmer", armed: true, switch_entity_id: "switch.sk" } } }),
      { ...CALM, "switch.sk": { state: "on" } });
    assertEqual(interlock.categories.maintenance.lost, 8, "an unsatisfied interlock costs maintenance points");
    assertEqual(interlock.topReason, "Skimmer has no armed return pump relationship");
    assert(interlock.detail.includes("1/1 armed"),
      `armed equipment is counted in the detail line: "${interlock.detail}"`);

    const { health: overdue } = await scoreFor(tank({
      maintenance: {
        enabled: true,
        tasks: { water_change: { label: "Water change", enabled: true, cadenceDays: 7, criticalAfterDays: 14, scheduleMode: "interval" } },
        completions: { water_change: [{ id: "old", timestamp: "2026-04-01T09:00:00Z" }] },
      },
    }), CALM);
    assertEqual(overdue.losses.map((loss) => [loss.category, loss.points, loss.status]),
      [["maintenance", 6, "critical"]], "an overdue task costs the score, it is not just a badge");
    assertEqual(overdue.categories.maintenance.lost, 6);
  });
});

test("test_backend_trend_findings_are_scored_and_stay_inside_categories_that_exist", async () => {
  // Trends are computed backend-side and handed over as free-form items, so this
  // is the one input to Reef Health the panel does not author. A scoring trend
  // has to actually cost points; a still-learning one must not; and a category or
  // group the backend invents must land somewhere the breakdown renders rather
  // than disappearing into a key nothing reads.
  await atClock(async () => {
    const { health } = await scoreFor(tank(), CALM, {
      _healthTrends: {
        checkedAt: CLOCK,
        items: {
          temp: { affectsScore: true, penalty: 12, category: "stability", label: "Temperature swinging", detail: "2.9 C in 24h", status: "critical" },
          alkalinity: { affectsScore: false, penalty: 0, group: "learning", label: "Alkalinity trend learning", detail: "Needs more history.", status: "context" },
          // Not in this tank's config at all — a stale trend for a sensor the
          // user removed must not invent a 30-point hole.
          nitrate: { affectsScore: true, penalty: 30, label: "Nitrate trend", detail: "", status: "critical" },
        },
      },
    });
    assertEqual(health.categories.stability.lost, 12, "a scoring trend must actually cost the tank points");
    assertEqual(health.losses.map((loss) => [loss.category, loss.points, loss.status]), [["stability", 12, "critical"]],
      "only the scoring trend is a loss, and only for a sensor this tank still has");
    assert(health.score < 100, "a trend the backend scored has to move the headline number");
    assertEqual(health.learningCount, 1, "a still-learning trend is reported as learning, not as damage");
    assertEqual(health.groups.learning.map((item) => item.label), ["Alkalinity trend learning"]);
    assert(health.groups.learning.every((item) => item.affectsScore === false),
      "nothing in the learning bucket may claim to affect the score");

    const { health: odd } = await scoreFor(tank(), CALM, {
      _healthTrends: {
        checkedAt: CLOCK,
        items: {
          temp: { affectsScore: true, penalty: 10, category: "not_a_category", label: "Temperature drift", detail: "Drifting.", status: "warning" },
          alkalinity: { affectsScore: false, penalty: 0, group: "nonsense", label: "Alkalinity note", detail: "FYI.", status: "context" },
        },
      },
    });
    assertEqual(odd.categories.confidence.lost, 10,
      "a category the panel does not know falls back to confidence rather than being dropped");
    assert(odd.losses.every((loss) => odd.categories[loss.category]),
      `every loss must name a category the breakdown renders: ${JSON.stringify(odd.losses.map((loss) => loss.category))}`);
    assertEqual(odd.groups.nonsense, undefined, "an unrecognised group must not invent a bucket");
    assertEqual(odd.groups.context.map((item) => item.label), ["Alkalinity note"], "it falls back to context");
    assertEqual(odd.contextCount, 1);
  });
});

// --- honesty when there is nothing to go on ---------------------------------

test("test_the_score_admits_what_it_has_not_measured", async () => {
  // Nothing configured at all. OpenReef has measured precisely nothing, so it
  // must at least say so rather than presenting a clean sheet.
  const { health } = await atClock(() => scoreFor({}, {}));
  assert(health.score < 100, `a tank with no sensors must not read a perfect 100: got ${health.score}`);
  assertEqual(health.losses.map((loss) => [loss.category, loss.label]), [["confidence", "No enabled sensors"]],
    "the one thing wrong is that OpenReef cannot see anything");
  assertEqual(health.categories.confidence.score, 70, "the confidence category carries the whole doubt");
  assertEqual(health.topReason, "No enabled sensors", "the headline reason must name the gap");
  assert(health.detail.includes("0/0 sensors mapped"), `the detail line must be honest: "${health.detail}"`);

  // Reef Health also leans on trends it only has after a check runs. Whether
  // that has happened is part of the answer, so an absent or unparseable
  // timestamp must read as "not checked" rather than as a date.
  await atClock(async () => {
    for (const trends of [{}, { checkedAt: "" }, { checkedAt: "not a date" }]) {
      const { health } = await scoreFor(tank(), CALM, { _healthTrends: { ...trends, items: {} } });
      assertEqual(health.trendFreshness, "Not checked this session",
        `missing/unparseable checkedAt (${JSON.stringify(trends)}) must not render as a timestamp`);
    }
    const { health } = await scoreFor(tank(), CALM, {
      _healthTrends: { checkedAt: "2026-06-04T08:00:00Z", items: {} },
    });
    assert(health.trendFreshness !== "Not checked this session", "a real check must be reported as one");
    assert(!/undefined|NaN|Invalid/.test(health.trendFreshness),
      `freshness leaked a placeholder: "${health.trendFreshness}"`);
  });
});

test("test_the_score_never_leaks_nan_or_undefined_however_broken_the_config_is", async () => {
  // The score is rendered straight into the dashboard, so a NaN here is a NaN in
  // front of the user. These are the configs that half-exist: mid-setup, stale
  // mappings, sensors with no thresholds, equipment pointing at nothing.
  const messy = [
    ["empty config", {}, {}],
    ["sensors with no thresholds", tank({ sensors: { alkalinity: { label: "Alkalinity", enabled: true, alertsEnabled: true, entity_id: "sensor.alk", group: "chemistry" } } }), CALM],
    ["mapped entity is unavailable", tank(), { ...CALM, "sensor.temp": { state: "unavailable" } }],
    ["armed equipment with no switch", tank({ equipment: { pump: { label: "Return pump", type: "return_pump", armed: true } } }), CALM],
    ["everything at once", tank({
      tank: { profile: "sps" },
      sensors: { leak: { label: "Leak", enabled: true, alertsEnabled: true, entity_id: "binary_sensor.leak", kind: "binary", group: "safety" } },
      equipment: { heater: { label: "Heater", type: "heater", armed: true, switch_entity_id: "switch.heater" } },
      maintenance: { enabled: true, tasks: { water_change: { label: "Water change", enabled: true, cadenceDays: 7, criticalAfterDays: 14, scheduleMode: "interval" } }, completions: {} },
    }), { "sensor.temp": { state: "40" }, "binary_sensor.leak": { state: "on" }, "switch.heater": { state: "unavailable" } }],
  ];
  await atClock(async () => {
    for (const [name, config, states] of messy) {
      const { health } = await scoreFor(config, states, {
        _validation: { missing_entities: ["sensor.gone"], armed_unavailable: ["switch.heater"] },
      });
      assert(Number.isInteger(health.score) && health.score >= 0 && health.score <= 100,
        `${name}: score must be a whole number in 0-100, got ${health.score}`);
      assert(["A", "B", "C", "D", "E"].includes(health.grade), `${name}: bad grade ${health.grade}`);
      assert(["ok", "warning", "critical"].includes(health.status), `${name}: bad status ${health.status}`);
      for (const [id, item] of Object.entries(health.categories)) {
        assert(Number.isInteger(item.score) && item.score >= 0 && item.score <= 100,
          `${name}: category ${id} scored ${item.score}`);
        assert(Number.isFinite(item.weight) && Number.isFinite(item.lost),
          `${name}: category ${id} has a non-finite weight/lost`);
      }
      for (const field of ["topReason", "nextAction", "detail", "gradeDetail", "profileLabel"]) {
        const text = health[field];
        assert(typeof text === "string" && text.length > 0, `${name}: ${field} is empty`);
        assert(!/undefined|NaN|\[object/.test(text), `${name}: ${field} leaked a placeholder: "${text}"`);
      }
      for (const loss of health.losses) {
        assert(Number.isFinite(loss.points) && loss.points > 0, `${name}: a loss with no points reached the list`);
        assert(health.categories[loss.category], `${name}: loss booked to unknown category ${loss.category}`);
      }
    }
  });
});

test("test_the_grade_and_status_bands_agree_with_the_number", async () => {
  // Grade and status are the same judgement in words. A red "critical" beside a
  // grade A, or an "ok" beside a live cap, is how users stop trusting the card.
  const panel = await makePanel({});
  const bands = [[100, "A"], [90, "A"], [89, "B"], [80, "B"], [79, "C"], [70, "C"], [69, "D"], [60, "D"], [59, "E"], [0, "E"]];
  for (const [score, grade] of bands) {
    assertEqual(panel._healthGrade(score), grade, `${score} should grade ${grade}`);
  }
  assertEqual(panel._healthStatus(95, []), "ok");
  assertEqual(panel._healthStatus(89, []), "warning", "below 90 is no longer a clean bill of health");
  assertEqual(panel._healthStatus(69, []), "critical", "below 70 is critical on the number alone");
  assertEqual(panel._healthStatus(100, [{ status: "warning" }]), "warning",
    "any live cap means something is being held back, however good the average");
  assertEqual(panel._healthStatus(100, [{ status: "critical" }]), "critical",
    "a critical cap is critical regardless of the average");
});

await runTests();
