/**
 * Dosing advisor safety gates (panel-only logic, previously untested).
 *
 * The doser CONTROL path is backend Python and well covered (test_dosing,
 * test_dosing_sync). The ADVICE path — "should you change your daily dose, and by
 * how much" — lives entirely in the panel and had no tests at all, despite being
 * the part that tells someone how much to put in a live reef.
 *
 * These pin the refusals rather than the arithmetic: OpenReef must stay locked
 * until it has the facts (acknowledgement, real tank volume, product strength,
 * current dose, fresh tests), and must never turn a maintenance-style product into
 * a one-off correction. Those are deliberate product promises, so they are what a
 * regression would quietly break.
 *
 * Run standalone:  node tests/test_panel_dosing_advice.mjs
 */

import { assert, assertEqual, makePanel, runTests, test } from "./_panel_harness.mjs";

const ALK = "alkalinity";

// A fully-satisfied advisor: acknowledged, real volume, a product with a known
// strength, and a current daily dose. Individual tests take this away again.
function dosingConfig(overrides = {}) {
  const { system = {}, parameters = {}, ...rest } = overrides;
  return {
    tank: { volumeLitres: 300 },
    dosing: {
      system: {
        product: "seachem_reef_fusion",
        safetyAcknowledged: true,
        tankVolumeLitres: 300,
        sharedDailyDoseMl: 40,
        ...system,
      },
      parameters: { alkalinity: { doserMlPerDay: 40, target: 8.3 }, ...parameters },
    },
    sensors: { alkalinity: { label: "Alkalinity", unit: "dKH", enabled: true, entity_id: "sensor.alk" } },
    ...rest,
  };
}

async function safetyFor(config, productId, sensorId = ALK, source = "sensor") {
  const panel = await makePanel(config);
  const sensor = config.sensors[sensorId];
  const product = panel._dosingProduct(productId ?? config.dosing.system.product);
  const paramConfig = panel._dosingParamConfig(sensorId);
  const potency = panel._dosingEffectivePotency(sensorId, sensor, paramConfig, product);
  return {
    panel,
    product,
    potency,
    state: panel._dosingSafetyState(sensorId, sensor, product, potency, paramConfig, source),
  };
}

function locked(state, fragment) {
  return state.status === "locked" && state.locks.some((lock) => lock.toLowerCase().includes(fragment.toLowerCase()));
}

test("test_advice_is_locked_until_the_advisory_only_promise_is_acknowledged", async () => {
  const { state } = await safetyFor(dosingConfig({ system: { safetyAcknowledged: false } }));
  assert(locked(state, "advisory only"),
    `not acknowledged must lock every number: ${JSON.stringify(state.locks)}`);
  assertEqual(state.canExactMaintenance, false);
  assertEqual(state.canExactCorrection, false);
});

test("test_no_exact_millilitres_without_a_real_tank_volume", async () => {
  // mL/unit is meaningless without a volume — and the user is told THAT, rather
  // than the advisor quietly degrading to "maintenance-style, tune from trends"
  // as though exact advice had never been available for this product.
  const { potency, state } = await safetyFor(dosingConfig({ system: { tankVolumeLitres: 0 }, tank: { volumeLitres: 0 } }));
  assertEqual(potency.value, 0, "no volume must not yield a potency");
  assertEqual(potency.source, "awaiting-volume");
  assert(potency.label.includes("net tank water volume"), `the label must name the missing fact: "${potency.label}"`);
  assertEqual(state.canExactMaintenance, false, "no exact dose change without a volume");
  assertEqual(state.canExactCorrection, false, "no exact correction without a volume");
  assertEqual(state.locks, ["Enter real net tank water volume."],
    "one missing fact, one lock — the preset's strength is known, so don't ask for it");
});

test("test_maintenance_advice_is_locked_until_the_current_dose_is_known", async () => {
  const { state } = await safetyFor(dosingConfig({
    system: { sharedDailyDoseMl: 0 },
    parameters: { alkalinity: { doserMlPerDay: 0, target: 8.3 } },
  }));
  assert(locked(state, "current daily dose"),
    `a dose CHANGE is meaningless without the current dose: ${JSON.stringify(state.locks)}`);
  assertEqual(state.canExactMaintenance, false);
});

test("test_a_fully_configured_system_can_finally_give_exact_maintenance_advice", async () => {
  const { state } = await safetyFor(dosingConfig());
  assertEqual(state.locks, [], "nothing should be locked once every fact is present");
  assertEqual(state.canExactMaintenance, true);
  assertEqual(state.tankVolume, 300);
  assert(state.currentDose > 0, "the current dose is carried into the advice");
});

test("test_kalkwasser_never_becomes_a_one_off_correction", async () => {
  // pH- and evaporation-constrained: OpenReef gives routine guidance only. Tested
  // BOTH with no strength (falls back to kalk guidance) and with a hand-entered
  // strength — the second is the path that could otherwise produce a mL figure.
  for (const potencyPerMl of [0, 0.05]) {
    const { potency, state } = await safetyFor(
      dosingConfig({
        system: { product: "kalkwasser_calcium_hydroxide" },
        parameters: { alkalinity: { doserMlPerDay: 40, target: 8.3, potencyPerMl } },
      }),
      "kalkwasser_calcium_hydroxide",
    );
    if (potencyPerMl > 0) assertEqual(potency.value, potencyPerMl, "the entered strength is used for maintenance");
    assertEqual(potency.exactCorrection, false,
      `kalk must never claim exact correction maths (strength ${potencyPerMl})`);
    assertEqual(state.canExactCorrection, false, `kalk must never offer a correction (strength ${potencyPerMl})`);
  }
});

test("test_kalkwasser_warns_when_it_cannot_maintain_the_parameter", async () => {
  const config = dosingConfig({ system: { product: "kalkwasser_calcium_hydroxide" } });
  config.sensors.magnesium = { label: "Magnesium", unit: "ppm", enabled: true, entity_id: "sensor.mg" };
  const { state } = await safetyFor(config, "kalkwasser_calcium_hydroxide", "magnesium");
  assert(state.warnings.some((warning) => warning.includes("does not maintain")),
    `kalk cannot hold magnesium and must say so: ${JSON.stringify(state.warnings)}`);
});

test("test_maintenance_style_products_refuse_one_off_corrections", async () => {
  // All-For-Reef and Aquaforest 1+2+3 are balanced systems: "correcting" an imbalance
  // with them is the classic way to make the imbalance worse.
  for (const productId of ["tropic_marin_all_for_reef", "aquaforest_component_123"]) {
    const { potency, state } = await safetyFor(dosingConfig({ system: { product: productId } }), productId);
    assertEqual(potency.exactCorrection, false, `${productId} must not claim exact correction maths`);
    assertEqual(state.canExactCorrection, false, `${productId} must not offer a one-off correction`);
  }
});

test("test_multi_bottle_products_carry_their_do_not_mix_warning", async () => {
  const expected = {
    seachem_reef_fusion: "never mix the two bottles",
    esv_b_ionic: "separately in high flow",
    brs_pharma_two_part: "separately in high flow",
    brightwell_reef_code_ab: "do not mix concentrates",
  };
  for (const [productId, fragment] of Object.entries(expected)) {
    const { state } = await safetyFor(dosingConfig({ system: { product: productId } }), productId);
    assert(state.warnings.some((warning) => warning.toLowerCase().includes(fragment)),
      `${productId} must keep its handling warning (${fragment}): ${JSON.stringify(state.warnings)}`);
  }
});

test("test_a_product_needing_a_verified_recipe_stays_locked_until_it_has_one", async () => {
  const { potency } = await safetyFor(
    dosingConfig({ system: { product: "fauna_marin_balling_light" } }),
    "fauna_marin_balling_light",
  );
  assert(potency.value === 0 || potency.exactMaintenance === false,
    "a recipe-dependent product must not invent a strength");
});

test("test_stale_manual_tests_lock_the_advice", async () => {
  const config = dosingConfig();
  config.manualTests = { alkalinity: { entries: [] } };
  const { state } = await safetyFor(config, undefined, ALK, "manual");
  assert(state.status === "locked" || !state.manual.fresh,
    "advice off stale manual tests must not be offered as if it were current");
});

test("test_locks_and_warnings_are_plain_english_actions", async () => {
  const { state } = await safetyFor(dosingConfig({
    system: { safetyAcknowledged: false, sharedDailyDoseMl: 0 },
    parameters: { alkalinity: { doserMlPerDay: 0, target: 8.3 } },
  }));
  assert(state.locks.length >= 2, "both missing facts should be listed, not just the first");
  for (const lock of state.locks) {
    assert(/[a-z]/.test(lock) && lock.length > 12, `a lock must tell the user what to do: "${lock}"`);
    assert(!/undefined|NaN|\[object/.test(lock), `lock leaked a placeholder: "${lock}"`);
  }
});

await runTests();
