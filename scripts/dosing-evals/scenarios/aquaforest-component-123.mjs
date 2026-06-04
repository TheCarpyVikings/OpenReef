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

function parameterConfig(parameter, scenario) {
  const doseKey = {
    alkalinity: "alkDoseMlPerDay",
    calcium: "caDoseMlPerDay",
    magnesium: "mgDoseMlPerDay",
  }[parameter];
  return {
    doserMlPerDay: scenario[doseKey] ?? scenario.sharedDoseMlPerDay ?? 24,
    target: CHEMISTRY_TARGETS[parameter],
  };
}

export function buildAquaforestManualReadings(scenario) {
  return buildChemistryManualReadings(scenario);
}

function buildPanelState(panel, scenario) {
  const manualReadings = buildAquaforestManualReadings(scenario);
  const liveContext = buildLiveContext(scenario);
  panel._integrationVersion = "eval";
  panel._config = {
    schemaVersion: 31,
    tank: { name: "Aquaforest Component Eval Reef", owner: "OpenReef Eval", profile: "mixed_reef" },
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
        primaryProduct: "aquaforest_component_123",
        secondaryProduct: "",
        tankVolumeLitres: scenario.tankVolumeLitres ?? 200,
        freshTestRequired: true,
        safetyAcknowledged: scenario.safetyAcknowledged !== false,
      },
      parameters: {
        alkalinity: parameterConfig("alkalinity", scenario),
        calcium: parameterConfig("calcium", scenario),
        magnesium: parameterConfig("magnesium", scenario),
      },
    },
  };
  panel._hass = { states: buildHassStates(liveContext) };
  return { manualReadings, liveContext };
}

function scenarioExpectations(scenario, result) {
  const text = allAdvice(result);
  const expectations = [
    expectation(
      "Advisory-only language remains",
      !textIncludes(text, "automated dosing") && !textIncludes(text, "OpenReef will control"),
      "Eval advice must remain advisory-only.",
    ),
    expectation(
      "No one-off correction bolus",
      !textIncludes(text, "Advisory correction total") && !textIncludes(text, "split it across about"),
      "Component 1+2+3+ should not be treated as a one-off correction calculator in beta.",
    ),
  ];
  if (!scenario.stale && scenario.id !== "stable-equal-parts") {
    expectations.push(expectation(
      "Equal-part maintenance guidance is visible",
      textIncludes(text, "Components 1, 2, and 3 dosed equally") || textIncludes(text, "equal daily Component 1+2+3+ dose"),
      "Aquaforest advice should guide equal maintenance dosing and separate correction for imbalances.",
      "Add/tune Aquaforest-specific wording if generic supplement text appears.",
    ));
  }
  if (scenario.id === "imbalanced-parameters") {
    expectations.push(expectation(
      "Imbalance guard is explicit",
      textIncludes(text, "correct them separately first") || textIncludes(text, "parameters are unbalanced"),
      "If Alk/Ca/Mg move differently, OpenReef must not pretend equal-part dosing fixes everything.",
    ));
  }
  if (scenario.id === "stale-manual-tests") {
    expectations.push(expectation(
      "Stale manual tests lock action",
      textIncludes(text, "Retest") || textIncludes(text, "last logged"),
      "Old manual results should not produce actionable changes.",
    ));
  }
  if (scenario.id === "above-target") {
    expectations.push(expectation(
      "Above-target chemistry avoids downward correction",
      textIncludes(text, "Do not chemically correct downward") || textIncludes(text, "Do not use chemical correction downward") || textIncludes(text, "do not use a one-off chemical correction downward"),
      "OpenReef should not recommend chemical correction downward.",
    ));
  }
  return expectations;
}

export const AQUAFOREST_COMPONENT_SCENARIOS = [
  {
    id: "stable-equal-parts",
    title: "Stable equal-part Component 1+2+3+",
    expected: "Keep the equal daily dose steady.",
    sharedDoseMlPerDay: 24,
    alkStart: 8.31,
    alkDrift: -0.001,
    caStart: 431,
    caDrift: -0.03,
    mgStart: 1351,
    mgDrift: 0,
  },
  {
    id: "balanced-demand",
    title: "Balanced demand increasing",
    expected: "Suggest reviewing equal maintenance dose only after fresh tests agree.",
    sharedDoseMlPerDay: 24,
    alkStart: 8.52,
    alkDrift: -0.012,
    caStart: 444,
    caDrift: -0.34,
    mgStart: 1378,
    mgDrift: -0.75,
  },
  {
    id: "imbalanced-parameters",
    title: "Imbalanced parameters",
    expected: "Warn that unequal parameter movement needs separate correction before relying on equal maintenance dosing.",
    sharedDoseMlPerDay: 24,
    alkStart: 8.55,
    alkDrift: -0.012,
    caStart: 431,
    caDrift: -0.02,
    mgStart: 1385,
    mgDrift: 0.2,
  },
  {
    id: "stale-manual-tests",
    title: "Stale manual tests",
    expected: "Lock action until fresh tests are logged.",
    sharedDoseMlPerDay: 24,
    alkStart: 8.5,
    alkDrift: -0.012,
    caStart: 440,
    caDrift: -0.25,
    mgStart: 1360,
    mgDrift: -0.1,
    latestAgeDays: 30,
    stale: true,
  },
  {
    id: "above-target",
    title: "Above-target Component 1+2+3+ chemistry",
    expected: "Avoid chemical correction downward; suggest hold/review only.",
    sharedDoseMlPerDay: 26,
    alkStart: 8.85,
    alkDrift: 0.006,
    caStart: 452,
    caDrift: 0.15,
    mgStart: 1360,
    mgDrift: 0.25,
  },
];

export function runAquaforestComponentEval({ createPanel }) {
  const scenarioReports = AQUAFOREST_COMPONENT_SCENARIOS.map((scenario) => {
    const panel = createPanel();
    const { manualReadings, liveContext } = buildPanelState(panel, scenario);
    const result = analyseDosingPanel(panel, { liveContext, source: "manual" });
    return scenarioReport({
      scenario,
      result,
      manualReadings,
      liveContext,
      expectations: scenarioExpectations(scenario, result),
    });
  });
  return [
    "# Aquaforest Component 1+2+3+ Eval",
    "",
    `Fixed eval clock: ${new Date(FIXED_NOW).toISOString()}`,
    "Tank: 200 L mixed reef.",
    "Targets: alkalinity 8.3 dKH, calcium 430 ppm, magnesium 1350 ppm.",
    "Primary source for dosing advice: simulated manual alkalinity/calcium/magnesium history.",
    "",
    "Source anchors checked:",
    "- Aquaforest Component 1+2+3+ is a regular maintenance system where the components are dosed in equal amounts.",
    "- Aquaforest says calcium, magnesium, or KH imbalances should be corrected with separate additives before continuing balanced component dosing.",
    "",
    "Aquaforest model inputs tested: equal daily dose assumption, manual-test freshness, unbalanced parameter movement, and no one-off correction bolus.",
    "",
    ...scenarioReports,
  ].join("\n");
}
