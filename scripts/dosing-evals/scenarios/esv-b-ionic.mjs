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

// Eval-only verified strengths. OpenReef intentionally asks the user to enter
// these from their actual bottle/recipe because B-Ionic variants/concentrates
// differ and should not be treated as one universal calculator.
const ESV_VERIFIED_STRENGTHS = {
  alkalinity: { productDoseMl: 1, productVolumeLitres: 100, productRaise: 0.055 },
  calcium: { productDoseMl: 1, productVolumeLitres: 100, productRaise: 0.38 },
};

function parameterConfig(parameter, scenario) {
  const doseKey = {
    alkalinity: "alkDoseMlPerDay",
    calcium: "caDoseMlPerDay",
    magnesium: "mgDoseMlPerDay",
  }[parameter];
  const strength = scenario.missingStrengthFor === parameter ? {} : ESV_VERIFIED_STRENGTHS[parameter] || {};
  return {
    doserMlPerDay: scenario[doseKey] ?? 18,
    target: CHEMISTRY_TARGETS[parameter],
    ...strength,
  };
}

export function buildEsvBionicManualReadings(scenario) {
  return buildChemistryManualReadings(scenario);
}

function buildPanelState(panel, scenario) {
  const manualReadings = buildEsvBionicManualReadings(scenario);
  const liveContext = buildLiveContext(scenario);
  panel._integrationVersion = "eval";
  panel._config = {
    schemaVersion: 31,
    tank: { name: "ESV B-Ionic Eval Reef", owner: "OpenReef Eval", profile: "mixed_reef" },
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
        primaryProduct: "esv_b_ionic",
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
  const alk = result.items.alkalinity;
  const calcium = result.items.calcium;
  const magnesium = result.items.magnesium;
  const expectations = [
    expectation(
      "Advisory-only language remains",
      !textIncludes(text, "automated dosing") && !textIncludes(text, "OpenReef will control"),
      "Eval advice must remain advisory-only.",
    ),
  ];
  if (!scenario.stale) {
    expectations.push(expectation(
      "ESV separate-parts safety reminder is visible",
      textIncludes(text, "Dose ESV B-Ionic parts separately") || textIncludes(text, "verify the exact bottle strength"),
      "B-Ionic advice must not hide the variant/strength and separate dosing cautions.",
    ));
  }
  if (!scenario.stale && !scenario.missingStrengthFor) {
    expectations.push(expectation(
      "Verified strength unlocks exact advice",
      alk?.potencyInfo?.source === "calculator" && calcium?.potencyInfo?.source === "calculator",
      "B-Ionic is treated as exact only after strength fields are completed.",
      "If this fails, the verified-strength model is not working for ESV.",
    ));
  }
  if (scenario.id === "alkalinity-demand") {
    expectations.push(expectation(
      "Alkalinity exact maintenance advice appears",
      alk?.extraMlPerDay > 0 && textIncludes(alk.maintenanceText, "Suggested next dose"),
      "Alkalinity is falling while calcium is calm.",
    ));
  }
  if (scenario.id === "calcium-demand") {
    expectations.push(expectation(
      "Calcium exact maintenance advice appears",
      calcium?.extraMlPerDay > 0 && textIncludes(calcium.maintenanceText, "Suggested next dose"),
      "Calcium is falling while alkalinity is calm.",
    ));
  }
  if (scenario.id === "missing-alkalinity-strength") {
    expectations.push(expectation(
      "Missing strength locks only matching part",
      textIncludes(alk?.maintenanceText, "Enter the strength") && calcium?.recommendationState !== "locked",
      "Missing ESV alkalinity strength should remove exact Alk mL advice without blocking calcium guidance.",
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
      textIncludes(text, "Do not chemically correct downward") || textIncludes(text, "do not use a one-off chemical correction downward"),
      "OpenReef should not recommend chemical correction downward.",
    ));
  }
  if (scenario.id === "magnesium-drift") {
    expectations.push(expectation(
      "Magnesium is not assigned to ESV B-Ionic",
      magnesium?.recommendationState === "not-covered" || textIncludes(text, "not a Magnesium dosing product") || textIncludes(text, "does not maintain Magnesium"),
      "B-Ionic two-part does not cover magnesium in this preset.",
    ));
  }
  return expectations;
}

export const ESV_B_IONIC_SCENARIOS = [
  {
    id: "stable-b-ionic",
    title: "Stable verified B-Ionic",
    expected: "Keep both parts steady; no correction pressure.",
    alkDoseMlPerDay: 18,
    caDoseMlPerDay: 18,
    alkStart: 8.34,
    alkDrift: -0.001,
    caStart: 432,
    caDrift: -0.03,
    mgStart: 1350,
    mgDrift: 0,
  },
  {
    id: "alkalinity-demand",
    title: "B-Ionic alkalinity demand",
    expected: "Suggest exact advisory maintenance review for the alkalinity part.",
    alkDoseMlPerDay: 16,
    caDoseMlPerDay: 18,
    alkStart: 8.52,
    alkDrift: -0.012,
    caStart: 431,
    caDrift: -0.02,
    mgStart: 1350,
    mgDrift: 0,
  },
  {
    id: "calcium-demand",
    title: "B-Ionic calcium demand",
    expected: "Suggest exact advisory maintenance review for the calcium part.",
    alkDoseMlPerDay: 18,
    caDoseMlPerDay: 16,
    alkStart: 8.32,
    alkDrift: -0.001,
    caStart: 444,
    caDrift: -0.36,
    mgStart: 1350,
    mgDrift: 0,
  },
  {
    id: "missing-alkalinity-strength",
    title: "Missing alkalinity verified strength",
    expected: "Lock alkalinity exact advice while calcium remains usable.",
    missingStrengthFor: "alkalinity",
    alkDoseMlPerDay: 16,
    caDoseMlPerDay: 16,
    alkStart: 8.48,
    alkDrift: -0.014,
    caStart: 444,
    caDrift: -0.35,
    mgStart: 1350,
    mgDrift: 0,
  },
  {
    id: "stale-manual-tests",
    title: "Stale manual tests",
    expected: "Lock action until fresh tests are logged.",
    alkDoseMlPerDay: 18,
    caDoseMlPerDay: 18,
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
    title: "Above-target B-Ionic chemistry",
    expected: "Avoid chemical correction downward; suggest hold/review only.",
    alkDoseMlPerDay: 20,
    caDoseMlPerDay: 20,
    alkStart: 8.85,
    alkDrift: 0.006,
    caStart: 452,
    caDrift: 0.15,
    mgStart: 1355,
    mgDrift: 0,
  },
  {
    id: "magnesium-drift",
    title: "Magnesium drift",
    expected: "State that B-Ionic two-part is not magnesium coverage in this preset.",
    alkDoseMlPerDay: 18,
    caDoseMlPerDay: 18,
    alkStart: 8.34,
    alkDrift: -0.001,
    caStart: 432,
    caDrift: -0.03,
    mgStart: 1405,
    mgDrift: -1.1,
  },
];

export function runEsvBionicEval({ createPanel }) {
  const scenarioReports = ESV_B_IONIC_SCENARIOS.map((scenario) => {
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
    "# ESV B-Ionic Eval",
    "",
    `Fixed eval clock: ${new Date(FIXED_NOW).toISOString()}`,
    "Tank: 200 L mixed reef.",
    "Targets: alkalinity 8.3 dKH, calcium 430 ppm, magnesium 1350 ppm.",
    "Primary source for dosing advice: simulated manual alkalinity/calcium/magnesium history.",
    "",
    "Source anchors checked:",
    "- ESV/vendor dosing guidance treats B-Ionic as a two-part calcium/alkalinity system and stresses matching bottle/variant instructions.",
    "- OpenReef beta model keeps B-Ionic in verified-strength mode so exact mL advice appears only after the user enters their actual product strength.",
    "",
    "ESV model inputs tested: net tank volume, separate current daily doses, user-verified alkalinity/calcium strengths, target values, and manual-test freshness.",
    "",
    ...scenarioReports,
  ].join("\n");
}
