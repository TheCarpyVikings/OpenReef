import { FIXED_NOW, expectation, textIncludes } from "../sim-utils.mjs";
import {
  CHEMISTRY_TARGETS,
  allAdvice,
  analyseDosingPanel,
  buildChemistryManualReadings,
  buildHassStates,
  buildLiveContext,
  chemistrySchedules,
  reefSensorConfig,
  scenarioReport,
} from "./shared-chemistry-eval.mjs";

const DEFAULT_STRENGTHS = {
  alkalinity: { productDoseMl: 1, productVolumeLitres: 100, productRaise: 0.05 },
  calcium: { productDoseMl: 1, productVolumeLitres: 100, productRaise: 0.35 },
  magnesium: { productDoseMl: 1, productVolumeLitres: 100, productRaise: 0.45 },
};

const PRODUCT_MODELS = {
  ati: {
    reportTitle: "ATI Essentials / Essentials Pro Eval",
    tankName: "ATI Essentials Eval Reef",
    primaryProduct: "ati_essentials",
    sourceAnchors: [
      "ATI Essentials systems are treated as alkalinity-led maintenance for beta; OpenReef does not assume one universal correction strength.",
      "Exact product/version details must be verified by the user before any real doser change.",
    ],
    requiredText: ["ATI Essentials", "alkalinity-led"],
    noOneOffCorrection: true,
  },
  redSea4: {
    reportTitle: "Red Sea Complete Reef Care 4-Part Eval",
    tankName: "Red Sea Complete Reef Care Eval Reef",
    primaryProduct: "red_sea_complete_reef_care_4",
    sourceAnchors: [
      "Red Sea Complete Reef Care is treated as calcium-led multi-part maintenance.",
      "OpenReef should guide review from trends and avoid collapsing the four bottles into one correction.",
    ],
    requiredText: ["Red Sea", "calcium-led"],
    noOneOffCorrection: true,
  },
  triton: {
    reportTitle: "TRITON Core7 Flex Eval",
    tankName: "TRITON Core7 Flex Eval Reef",
    primaryProduct: "triton_core7_flex",
    sourceAnchors: [
      "TRITON Core7 Flex is treated as ICP-guided maintenance.",
      "OpenReef should prompt trend/ICP review rather than one-off correction maths.",
    ],
    requiredText: ["TRITON", "ICP-guided"],
    noOneOffCorrection: true,
  },
  fauna: {
    reportTitle: "Fauna Marin Balling Light Eval",
    tankName: "Fauna Marin Balling Eval Reef",
    primaryProduct: "fauna_marin_balling_light",
    sourceAnchors: [
      "Fauna Marin Balling Light is recipe-dependent and must be dosed as separate solutions.",
      "Verified recipe strength can unlock maintenance mL advice, but OpenReef beta should not give generic correction boluses.",
    ],
    requiredText: ["Balling Light", "recipe-dependent"],
    noOneOffCorrection: true,
    verifiedStrengths: DEFAULT_STRENGTHS,
  },
  brightwellCode: {
    reportTitle: "Brightwell Reef Code A/B Eval",
    tankName: "Brightwell Reef Code Eval Reef",
    primaryProduct: "brightwell_reef_code_ab",
    sourceAnchors: [
      "Brightwell Reef Code A/B is an exact-strength two-part preset for calcium and alkalinity.",
      "The preset does not cover magnesium and should remind users to dose A/B separately.",
    ],
    requiredText: ["Brightwell Reef Code", "separately"],
    exactAllowed: true,
  },
  brightwellKalk: {
    reportTitle: "Brightwell Kalk+2 Eval",
    tankName: "Brightwell Kalk+2 Eval Reef",
    primaryProduct: "",
    secondaryProduct: "brightwell_kalk_plus_2",
    secondaryDelivery: "dosing_pump",
    sourceAnchors: [
      "Brightwell Kalk+2 is treated as kalkwasser-style support: high-pH and evaporation-limited.",
      "OpenReef must not use it as a magnesium correction product or one-off bolus.",
    ],
    requiredText: ["Kalk", "high-pH"],
    noOneOffCorrection: true,
    kalk: true,
  },
  redSea7: {
    reportTitle: "Red Sea Foundation + Trace Colors 7-Part Eval",
    tankName: "Red Sea 7-Part Eval Reef",
    primaryProduct: "red_sea_complete_reef_care_7",
    sourceAnchors: [
      "Red Sea 7-part style workflows are measured-uptake multi-bottle systems.",
      "OpenReef should keep Foundation and trace-style guidance separate and avoid a collapsed correction.",
    ],
    requiredText: ["Red Sea Foundation", "measured"],
    noOneOffCorrection: true,
  },
  tropicBalling: {
    reportTitle: "Tropic Marin Original Balling Eval",
    tankName: "Tropic Marin Balling Eval Reef",
    primaryProduct: "tropic_marin_original_balling",
    sourceAnchors: [
      "Tropic Marin Original Balling uses separate A/B/C parts.",
      "Part C supports ionic balance and must not be treated as a normal one-off correction bottle.",
    ],
    requiredText: ["Original Balling", "Part C"],
    noOneOffCorrection: true,
    verifiedStrengths: DEFAULT_STRENGTHS,
  },
  calciumReactor: {
    reportTitle: "Calcium Reactor Advisor Eval",
    tankName: "Calcium Reactor Eval Reef",
    primaryProduct: "calcium_reactor",
    sourceAnchors: [
      "Calcium reactor advice is a tuning workflow, not bottle dosing.",
      "OpenReef should mention slow effluent/CO2 review and tank pH context.",
    ],
    requiredText: ["Calcium reactor", "effluent"],
    noOneOffCorrection: true,
    phSensitive: true,
  },
};

function doseFor(parameter, scenario) {
  const key = {
    alkalinity: "alkDoseMlPerDay",
    calcium: "caDoseMlPerDay",
    magnesium: "mgDoseMlPerDay",
  }[parameter];
  return scenario[key] ?? scenario.sharedDoseMlPerDay ?? 24;
}

function parameterConfig(parameter, scenario, model) {
  const cfg = {
    doserMlPerDay: doseFor(parameter, scenario),
    target: CHEMISTRY_TARGETS[parameter],
  };
  const strength = scenario.noStrengthFor === parameter ? null : model.verifiedStrengths?.[parameter];
  if (strength && scenario.noStrength !== true) {
    cfg.productDoseMl = strength.productDoseMl;
    cfg.productVolumeLitres = strength.productVolumeLitres;
    cfg.productRaise = strength.productRaise;
  }
  return cfg;
}

function baseConfig(panel, scenario, model) {
  const manualReadings = buildChemistryManualReadings(scenario);
  const liveContext = buildLiveContext(scenario);
  panel._integrationVersion = "eval";
  panel._config = {
    schemaVersion: 31,
    tank: { name: model.tankName, owner: "OpenReef Eval", profile: "mixed_reef" },
    display: { themeColor: "#22c55e", setupComplete: true, missionCards: { dosing: true } },
    alerts: { hysteresisPercent: 2, muteUntil: {}, lastStates: {} },
    sensors: reefSensorConfig(),
    equipment: {},
    energy: {},
    manualReadings,
    manualTests: {
      enabled: true,
      schedules: chemistrySchedules({ stale: scenario.stale }),
    },
    dosing: {
      enabled: true,
      system: {
        primaryProduct: model.primaryProduct,
        secondaryProduct: model.secondaryProduct || "",
        secondaryDelivery: model.secondaryDelivery || "",
        tankVolumeLitres: scenario.noTankVolume ? 0 : scenario.tankVolumeLitres ?? 200,
        freshTestRequired: true,
        safetyAcknowledged: scenario.safetyAcknowledged !== false,
        kalkDailyDoseMl: scenario.kalkDailyDoseMl ?? 900,
        kalkConcentration: scenario.kalkConcentration ?? 2,
        kalkEvaporationLimitMlPerDay: scenario.kalkEvaporationLimitMlPerDay ?? 1700,
        kalkMaxPh: scenario.kalkMaxPh ?? 8.45,
        kalkMaxPhRise: scenario.kalkMaxPhRise ?? 0.2,
      },
      parameters: {
        alkalinity: parameterConfig("alkalinity", scenario, model),
        calcium: parameterConfig("calcium", scenario, model),
        magnesium: parameterConfig("magnesium", scenario, model),
      },
    },
  };
  if (scenario.noPhGuard) {
    panel._config.sensors.ph.entity_id = "";
    panel._config.sensors.ph.enabled = false;
  }
  panel._hass = { states: buildHassStates(liveContext) };
  return { manualReadings, liveContext };
}

function commonExpectations(scenario, result, model) {
  const text = allAdvice(result);
  const expectations = [
    expectation(
      "Advisory-only language remains",
      !textIncludes(text, "OpenReef will control") && !textIncludes(text, "automatic dosing"),
      "Eval advice must stay advisory-only.",
    ),
  ];
  if (!scenario.id.includes("stale")) {
    expectations.push(expectation(
      "Product safety wording is visible",
      model.requiredText.every((needle) => textIncludes(text, needle)),
      `Expected wording: ${model.requiredText.join(", ")}.`,
      "Add product-specific safety/advisor text if generic wording appears.",
    ));
  }
  if (model.noOneOffCorrection) {
    expectations.push(expectation(
      "No one-off correction calculator",
      !textIncludes(text, "Advisory correction total") && !textIncludes(text, "split it across about"),
      "Guided/maintenance systems must not pretend there is a universal correction formula.",
    ));
  }
  if (model.exactAllowed && scenario.id.includes("demand")) {
    expectations.push(expectation(
      "Exact preset advice can appear for covered parameters",
      textIncludes(text, "estimated holding dose") || textIncludes(text, "Suggested next dose"),
      "Exact-strength two-part presets should produce advisory mL when fresh tests and volume are present.",
    ));
  }
  if (scenario.id.includes("stale")) {
    expectations.push(expectation(
      "Stale manual tests lock action",
      textIncludes(text, "Retest") || textIncludes(text, "last logged"),
      "Old manual tests should not produce actionable dosing changes.",
    ));
  }
  if (scenario.id.includes("above")) {
    expectations.push(expectation(
      "Above-target chemistry avoids downward correction",
      textIncludes(text, "Do not chemically correct downward")
        || textIncludes(text, "do not use a one-off chemical correction downward")
        || textIncludes(text, "Do not increase kalkwasser"),
      "OpenReef should not recommend chemical correction downward.",
    ));
  }
  if (scenario.noStrengthFor || scenario.noStrength) {
    expectations.push(expectation(
      "Missing strength locks exact advice",
      textIncludes(text, "enter verified solution strength") || textIncludes(text, "strength before exact mL advice"),
      "Recipe products need verified strength before exact mL advice appears.",
    ));
  }
  if (scenario.noPhGuard) {
    expectations.push(expectation(
      "Missing pH guard is visible",
      textIncludes(text, "No mapped pH guard"),
      "Kalk/reactor-style products should show pH context when the pH guard is missing.",
    ));
  }
  if (scenario.highPh || scenario.kalkMaxPh) {
    expectations.push(expectation(
      "pH ceiling guidance is visible",
      textIncludes(text, "max pH") || textIncludes(text, "tank pH"),
      "High-pH or pH-sensitive systems should surface pH safety context.",
    ));
  }
  if (!scenario.id.includes("stale") && scenario.mgDrift < -0.15 && ["brightwellCode", "brightwellKalk"].includes(model.key)) {
    expectations.push(expectation(
      "Magnesium coverage gap is explicit",
      textIncludes(text, "does not maintain Magnesium") || textIncludes(text, "not a Magnesium dosing product"),
      "Two-part/kalk presets should not pretend to maintain magnesium.",
    ));
  }
  return expectations;
}

function runProductEval({ createPanel }, model) {
  const scenarioReports = model.scenarios.map((scenario) => {
    const panel = createPanel();
    const { manualReadings, liveContext } = baseConfig(panel, scenario, model);
    const result = analyseDosingPanel(panel, { liveContext, source: "manual" });
    return scenarioReport({
      scenario,
      result,
      manualReadings,
      liveContext,
      expectations: commonExpectations(scenario, result, model),
    });
  });
  return [
    `# ${model.reportTitle}`,
    "",
    `Fixed eval clock: ${new Date(FIXED_NOW).toISOString()}`,
    "Tank: 200 L mixed reef.",
    "Targets: alkalinity 8.3 dKH, calcium 430 ppm, magnesium 1350 ppm.",
    "Primary source for dosing advice: simulated manual alkalinity/calcium/magnesium history.",
    "",
    "Source anchors checked:",
    ...model.sourceAnchors.map((item) => `- ${item}`),
    "",
    ...scenarioReports,
  ].join("\n");
}

const STABLE = {
  id: "stable-maintenance",
  title: "Stable maintenance",
  expected: "Keep the current routine steady and avoid tiny correction nudges.",
  alkStart: 8.32,
  alkDrift: -0.001,
  caStart: 431,
  caDrift: -0.03,
  mgStart: 1352,
  mgDrift: 0.02,
};

const DEMAND = {
  id: "demand-increasing",
  title: "Demand increasing",
  expected: "Show maintenance review guidance without unsafe automation.",
  alkStart: 8.55,
  alkDrift: -0.015,
  caStart: 445,
  caDrift: -0.28,
  mgStart: 1368,
  mgDrift: -0.3,
};

const STALE = {
  id: "stale-manual-tests",
  title: "Stale manual tests",
  expected: "Lock action until fresh manual tests are logged.",
  alkStart: 8.45,
  alkDrift: -0.013,
  caStart: 438,
  caDrift: -0.22,
  mgStart: 1360,
  mgDrift: -0.2,
  latestAgeDays: 30,
  stale: true,
};

const ABOVE = {
  id: "above-target-chemistry",
  title: "Above-target chemistry",
  expected: "Avoid downward chemical correction advice.",
  alkStart: 8.88,
  alkDrift: 0.006,
  caStart: 454,
  caDrift: 0.12,
  mgStart: 1362,
  mgDrift: 0.12,
};

function withKey(key, model, scenarios) {
  return { key, ...model, scenarios };
}

const MODELS = {
  ati: withKey("ati", PRODUCT_MODELS.ati, [STABLE, DEMAND, STALE, ABOVE]),
  redSea4: withKey("redSea4", PRODUCT_MODELS.redSea4, [
    STABLE,
    { ...DEMAND, id: "calcium-led-demand", title: "Calcium-led demand", caDrift: -0.45 },
    STALE,
    ABOVE,
  ]),
  triton: withKey("triton", PRODUCT_MODELS.triton, [STABLE, DEMAND, STALE, ABOVE]),
  fauna: withKey("fauna", PRODUCT_MODELS.fauna, [
    STABLE,
    DEMAND,
    { ...DEMAND, id: "missing-recipe-strength", title: "Missing recipe strength", expected: "Lock exact mL until recipe strength is entered.", noStrengthFor: "alkalinity" },
    STALE,
    ABOVE,
  ]),
  brightwellCode: withKey("brightwellCode", PRODUCT_MODELS.brightwellCode, [
    STABLE,
    { ...DEMAND, id: "alkalinity-demand", title: "Alkalinity demand", caDrift: -0.02, mgDrift: 0 },
    { ...DEMAND, id: "calcium-demand", title: "Calcium demand", alkDrift: -0.001, caDrift: -0.5, mgDrift: 0 },
    { ...DEMAND, id: "magnesium-drift", title: "Magnesium drift", alkDrift: -0.001, caDrift: -0.02, mgDrift: -0.45 },
    STALE,
    ABOVE,
  ]),
  brightwellKalk: withKey("brightwellKalk", PRODUCT_MODELS.brightwellKalk, [
    STABLE,
    DEMAND,
    { ...DEMAND, id: "high-ph-risk", title: "High pH risk", expected: "Warn against increasing Kalk+2 when pH is near/over the ceiling.", phStart: 8.46, phNoise: 0.02, kalkMaxPh: 8.4, highPh: true },
    { ...DEMAND, id: "no-ph-guard", title: "No pH guard", expected: "Show that Kalk+2 advice is missing pH safety context.", noPhGuard: true },
    { ...DEMAND, id: "magnesium-drift", title: "Magnesium drift", alkDrift: -0.001, caDrift: -0.02, mgDrift: -0.45 },
    ABOVE,
  ]),
  redSea7: withKey("redSea7", PRODUCT_MODELS.redSea7, [STABLE, DEMAND, STALE, ABOVE]),
  tropicBalling: withKey("tropicBalling", PRODUCT_MODELS.tropicBalling, [
    STABLE,
    DEMAND,
    { ...DEMAND, id: "missing-balling-strength", title: "Missing Balling strength", expected: "Lock exact mL until recipe strength is entered.", noStrengthFor: "calcium" },
    STALE,
    ABOVE,
  ]),
  calciumReactor: withKey("calciumReactor", PRODUCT_MODELS.calciumReactor, [
    STABLE,
    DEMAND,
    { ...DEMAND, id: "low-ph-context", title: "Low pH context", expected: "Mention pH context while treating reactor changes as slow tuning.", phStart: 7.78, phNoise: 0.03 },
    STALE,
    ABOVE,
  ]),
};

export const ATI_ESSENTIALS_SCENARIOS = MODELS.ati.scenarios;
export const RED_SEA_COMPLETE_REEF_CARE_SCENARIOS = MODELS.redSea4.scenarios;
export const TRITON_CORE7_FLEX_SCENARIOS = MODELS.triton.scenarios;
export const FAUNA_MARIN_BALLING_LIGHT_SCENARIOS = MODELS.fauna.scenarios;
export const BRIGHTWELL_REEF_CODE_SCENARIOS = MODELS.brightwellCode.scenarios;
export const BRIGHTWELL_KALK_PLUS_SCENARIOS = MODELS.brightwellKalk.scenarios;
export const RED_SEA_SEVEN_PART_SCENARIOS = MODELS.redSea7.scenarios;
export const TROPIC_MARIN_BALLING_SCENARIOS = MODELS.tropicBalling.scenarios;
export const CALCIUM_REACTOR_SCENARIOS = MODELS.calciumReactor.scenarios;

export const buildAtiEssentialsManualReadings = buildChemistryManualReadings;
export const buildRedSeaCompleteManualReadings = buildChemistryManualReadings;
export const buildTritonCore7ManualReadings = buildChemistryManualReadings;
export const buildFaunaMarinBallingManualReadings = buildChemistryManualReadings;
export const buildBrightwellReefCodeManualReadings = buildChemistryManualReadings;
export const buildBrightwellKalkPlusManualReadings = buildChemistryManualReadings;
export const buildRedSeaSevenPartManualReadings = buildChemistryManualReadings;
export const buildTropicMarinBallingManualReadings = buildChemistryManualReadings;
export const buildCalciumReactorManualReadings = buildChemistryManualReadings;

export function runAtiEssentialsEval(args) {
  return runProductEval(args, MODELS.ati);
}

export function runRedSeaCompleteReefCareEval(args) {
  return runProductEval(args, MODELS.redSea4);
}

export function runTritonCore7FlexEval(args) {
  return runProductEval(args, MODELS.triton);
}

export function runFaunaMarinBallingLightEval(args) {
  return runProductEval(args, MODELS.fauna);
}

export function runBrightwellReefCodeEval(args) {
  return runProductEval(args, MODELS.brightwellCode);
}

export function runBrightwellKalkPlusEval(args) {
  return runProductEval(args, MODELS.brightwellKalk);
}

export function runRedSeaSevenPartEval(args) {
  return runProductEval(args, MODELS.redSea7);
}

export function runTropicMarinBallingEval(args) {
  return runProductEval(args, MODELS.tropicBalling);
}

export function runCalciumReactorEval(args) {
  return runProductEval(args, MODELS.calciumReactor);
}

export function runDosingUiSmokeEval({ createPanel }) {
  const panel = createPanel();
  baseConfig(panel, { ...DEMAND, id: "ui-smoke", title: "UI smoke", expected: "Dosing cards render without broken placeholders." }, MODELS.brightwellCode);
  const result = analyseDosingPanel(panel, { liveContext: buildLiveContext(DEMAND), source: "manual" });
  const html = panel._dosingAdvisorCard?.() || panel._dosingBreakdown?.() || "";
  const text = [allAdvice(result), String(html)].join("\n");
  const expectations = [
    expectation("Advisor generates advice", Object.keys(result.items).length >= 2, "Expected alkalinity/calcium advice rows."),
    expectation("No undefined/null placeholders", !textIncludes(text, "undefined") && !textIncludes(text, "null"), "UI/advice text should not leak JS placeholders."),
    expectation("Advisory warning remains visible", textIncludes(text, "Advisory only") || textIncludes(text, "OpenReef will not control"), "Users must see this is advisory-only."),
  ];
  return [
    "# Dosing Advisor UI Smoke Eval",
    "",
    `Fixed eval clock: ${new Date(FIXED_NOW).toISOString()}`,
    "",
    scenarioReport({
      scenario: { id: "ui-smoke", title: "Dosing Advisor render smoke", expected: "Render/advice text is complete and advisory-only." },
      result,
      manualReadings: buildChemistryManualReadings(DEMAND),
      liveContext: buildLiveContext(DEMAND),
      expectations,
    }),
  ].join("\n");
}
