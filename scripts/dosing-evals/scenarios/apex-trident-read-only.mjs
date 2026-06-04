import { FIXED_NOW, expectation, textIncludes } from "../sim-utils.mjs";
import {
  CHEMISTRY_TARGETS,
  allAdvice,
  analyseDosingPanel,
  buildHassStates,
  buildLiveContext,
  reefSensorConfig,
  scenarioReport,
} from "./shared-chemistry-eval.mjs";

const VERIFIED_STRENGTHS = {
  alkalinity: { productDoseMl: 1, productVolumeLitres: 100, productRaise: 0.053 },
  calcium: { productDoseMl: 1, productVolumeLitres: 100, productRaise: 0.37 },
  magnesium: { productDoseMl: 1, productVolumeLitres: 100, productRaise: 0.47 },
};

function parameterConfig(parameter, scenario) {
  const doseKey = {
    alkalinity: "alkDoseMlPerDay",
    calcium: "caDoseMlPerDay",
    magnesium: "mgDoseMlPerDay",
  }[parameter];
  return {
    doserMlPerDay: scenario[doseKey] ?? 20,
    target: CHEMISTRY_TARGETS[parameter],
    ...VERIFIED_STRENGTHS[parameter],
  };
}

function buildPanelState(panel, scenario) {
  const liveContext = buildLiveContext(scenario, { mappedChemistry: true });
  panel._integrationVersion = "eval";
  panel._config = {
    schemaVersion: 31,
    tank: { name: "Apex Read-Only Eval Reef", owner: "OpenReef Eval", profile: "mixed_reef" },
    display: { themeColor: "#22c55e", setupComplete: true, missionCards: { dosing: true } },
    alerts: { hysteresisPercent: 2, muteUntil: {}, lastStates: {} },
    sensors: reefSensorConfig({ mappedChemistry: true }),
    equipment: {},
    energy: {},
    manualReadings: {},
    manualTests: { enabled: false, schedules: {} },
    dosing: {
      enabled: true,
      system: {
        primaryProduct: "brs_pharma_two_part",
        secondaryProduct: "",
        tankVolumeLitres: scenario.tankVolumeLitres ?? 200,
        customProductName: "Apex/Trident read-only verified three-part",
        freshTestRequired: true,
        safetyAcknowledged: true,
      },
      parameters: {
        alkalinity: parameterConfig("alkalinity", scenario),
        calcium: parameterConfig("calcium", scenario),
        magnesium: parameterConfig("magnesium", scenario),
      },
    },
  };
  panel._hass = { states: buildHassStates(liveContext) };
  return { liveContext };
}

function analysePanel(panel, liveContext) {
  return analyseDosingPanel(panel, { liveContext, source: "mapped-history" });
}

function scenarioExpectations(scenario, result) {
  const text = allAdvice(result);
  const alk = result.items.alkalinity;
  const expectations = [
    expectation(
      "No OpenReef control requirement",
      !textIncludes(text, "mapped switch") && !textIncludes(text, "armed equipment") && !textIncludes(text, "arm equipment"),
      "Apex/Trident read-only users should not need OpenReef-controlled equipment for chemistry advice.",
    ),
    expectation(
      "Mapped chemistry history avoids manual-stale lock",
      !textIncludes(text, "manual tests are not fresh") && !textIncludes(text, "last logged"),
      "Fresh mapped Apex/Trident-style chemistry history should be valid input for advisory trend checks.",
      "If this fails, mapped chemistry sensors are still being treated as stale manual tests.",
    ),
    expectation(
      "Advisory-only language remains",
      !textIncludes(text, "automated dosing") && !textIncludes(text, "OpenReef will control"),
      "The eval must stay advisory-only.",
    ),
  ];
  if (scenario.id === "trident-alk-demand") {
    expectations.push(expectation(
      "Alkalinity trend produces exact maintenance review",
      alk?.extraMlPerDay > 0 && textIncludes(alk.maintenanceText, "Suggested next dose"),
      "Mapped alkalinity history is falling, so the advisor should be useful without manual CSV data.",
      "Tune mapped-history safety/freshness if Apex users only see learning/locked advice.",
    ));
  }
  if (scenario.id === "trident-steady") {
    expectations.push(expectation(
      "Stable read-only chemistry stays calm",
      result.mission.status === "ok" || result.mission.status === "unknown",
      `Mission state: ${result.mission.value} / ${result.mission.status}.`,
    ));
  }
  return expectations;
}

export const APEX_TRIDENT_READ_ONLY_SCENARIOS = [
  {
    id: "trident-steady",
    title: "Apex/Trident read-only stable chemistry",
    expected: "Use mapped chemistry sensor history without requiring OpenReef control or manual tests.",
    alkDoseMlPerDay: 20,
    caDoseMlPerDay: 20,
    mgDoseMlPerDay: 20,
    alkStart: 8.3,
    alkDrift: -0.001,
    caStart: 431,
    caDrift: -0.02,
    mgStart: 1352,
    mgDrift: 0,
    chemistryIntervalHours: 24,
  },
  {
    id: "trident-alk-demand",
    title: "Apex/Trident read-only alkalinity demand",
    expected: "Suggest an advisory alkalinity maintenance change from mapped Trident-style history.",
    alkDoseMlPerDay: 18,
    caDoseMlPerDay: 20,
    mgDoseMlPerDay: 20,
    alkStart: 8.45,
    alkDrift: -0.012,
    caStart: 431,
    caDrift: -0.02,
    mgStart: 1350,
    mgDrift: 0,
    chemistryIntervalHours: 24,
  },
  {
    id: "trident-balanced-demand",
    title: "Apex/Trident read-only balanced demand",
    expected: "Show independent advisory review for Alk/Ca/Mg from mapped chemistry history.",
    alkDoseMlPerDay: 20,
    caDoseMlPerDay: 20,
    mgDoseMlPerDay: 20,
    alkStart: 8.55,
    alkDrift: -0.012,
    caStart: 444,
    caDrift: -0.35,
    mgStart: 1380,
    mgDrift: -0.8,
    chemistryIntervalHours: 24,
  },
];

export function runApexTridentReadOnlyEval({ createPanel }) {
  const scenarioReports = APEX_TRIDENT_READ_ONLY_SCENARIOS.map((scenario) => {
    const panel = createPanel();
    const { liveContext } = buildPanelState(panel, scenario);
    const result = analysePanel(panel, liveContext);
    return scenarioReport({
      scenario,
      result,
      manualReadings: {},
      liveContext,
      expectations: scenarioExpectations(scenario, result),
    });
  });
  return [
    "# Apex/Trident Read-Only Chemistry Eval",
    "",
    `Fixed eval clock: ${new Date(FIXED_NOW).toISOString()}`,
    "Tank: 200 L mixed reef.",
    "Targets: alkalinity 8.3 dKH, calcium 430 ppm, magnesium 1350 ppm.",
    "Primary source for dosing advice: simulated mapped Apex/Trident-style chemistry sensor history.",
    "Control assumption: monitor-only is valid; no OpenReef-controlled dosing pumps or smart plugs are required.",
    "",
    "Source anchors checked:",
    "- Neptune Trident measures alkalinity, calcium, and magnesium repeatedly through the day; OpenReef treats those HA entities as chemistry history rather than manual-test CSV rows.",
    "- Recipe-dependent two/three-part systems still require user-verified product strength before exact mL advice appears.",
    "",
    ...scenarioReports,
  ].join("\n");
}
