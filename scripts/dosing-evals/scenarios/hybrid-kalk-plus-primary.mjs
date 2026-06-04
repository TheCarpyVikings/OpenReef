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

function reefFusionParameterConfig(parameter, scenario) {
  const doseKey = {
    alkalinity: "alkDoseMlPerDay",
    calcium: "caDoseMlPerDay",
    magnesium: "mgDoseMlPerDay",
  }[parameter];
  return {
    doserMlPerDay: scenario[doseKey] ?? 16,
    target: CHEMISTRY_TARGETS[parameter],
  };
}

export function buildHybridKalkManualReadings(scenario) {
  return buildChemistryManualReadings(scenario);
}

function buildPanelState(panel, scenario) {
  const manualReadings = buildHybridKalkManualReadings(scenario);
  const liveContext = buildLiveContext(scenario);
  const primaryProduct = scenario.primaryProduct || "seachem_reef_fusion";
  const sensors = reefSensorConfig();
  if (scenario.noPhGuard) {
    sensors.ph.entity_id = "";
    sensors.ph.enabled = false;
  }
  panel._integrationVersion = "eval";
  panel._config = {
    schemaVersion: 31,
    tank: { name: "Hybrid Kalk Eval Reef", owner: "OpenReef Eval", profile: "mixed_reef" },
    display: { themeColor: "#22c55e", setupComplete: true, missionCards: { dosing: true } },
    alerts: { hysteresisPercent: 2, muteUntil: {}, lastStates: {} },
    sensors,
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
        primaryProduct,
        secondaryProduct: "kalkwasser_calcium_hydroxide",
        secondaryDelivery: "dosing_pump",
        tankVolumeLitres: scenario.tankVolumeLitres ?? 200,
        sharedDailyDoseMl: scenario.sharedDoseMlPerDay ?? 24,
        kalkDailyDoseMl: scenario.kalkDailyDoseMl ?? 850,
        kalkConcentrationTspPerGallon: scenario.kalkConcentrationTspPerGallon ?? 1.5,
        kalkEvaporationLimitMlPerDay: scenario.kalkEvaporationLimitMlPerDay ?? 1600,
        kalkMaxPh: scenario.kalkMaxPh ?? 8.45,
        kalkMaxPhRise: scenario.kalkMaxPhRise ?? 0.2,
        freshTestRequired: true,
        safetyAcknowledged: scenario.safetyAcknowledged !== false,
      },
      parameters: {
        alkalinity: reefFusionParameterConfig("alkalinity", scenario),
        calcium: reefFusionParameterConfig("calcium", scenario),
        magnesium: reefFusionParameterConfig("magnesium", scenario),
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
  const expectations = [
    expectation(
      "Advisory-only language remains",
      !textIncludes(text, "automated dosing") && !textIncludes(text, "OpenReef will control"),
      "Hybrid eval advice must remain advisory-only.",
    ),
    expectation(
      "Secondary kalk context is visible",
      textIncludes(text, "Secondary kalkwasser support is configured"),
      "Kalk support should stay visible even when the primary product owns exact Alk/Ca advice.",
      "Add hybrid kalk context if secondary kalk disappears from the advisor.",
    ),
    expectation(
      "Kalk is not used as a correction bolus",
      textIncludes(text, "do not use kalkwasser as a one-off correction") || textIncludes(text, "do not use kalkwasser for one-off correction"),
      "Hybrid advice must explicitly block kalk correction boluses.",
    ),
  ];
  if (scenario.primaryProduct === "tropic_marin_all_for_reef") {
    expectations.push(expectation(
      "All-For-Reef remains maintenance-only",
      textIncludes(text, "Do not use Tropic Marin All-For-Reef as a one-off") || textIncludes(text, "All-For-Reef is a maintenance system"),
      "AFR plus kalk should remain guided maintenance, not a correction calculator.",
    ));
  } else if (!scenario.stale) {
    expectations.push(expectation(
      "Primary two-part exact advice still works",
      (alk?.extraMlPerDay > 0 || calcium?.extraMlPerDay > 0) && textIncludes(text, "Suggested next dose"),
      "Secondary kalk should not block exact primary two-part maintenance advice.",
    ));
  }
  if (scenario.id === "high-ph-risk") {
    expectations.push(expectation(
      "High pH blocks kalk increases",
      textIncludes(text, "Do not increase kalkwasser") && (result.mission.status === "warning" || result.mission.status === "critical"),
      "High pH should warn users not to push kalk harder.",
    ));
  }
  if (scenario.id === "no-ph-guard") {
    expectations.push(expectation(
      "No pH guard warning appears without blocking primary advice",
      textIncludes(text, "No mapped pH guard") && (alk?.extraMlPerDay > 0 || calcium?.extraMlPerDay > 0),
      "Missing pH guard should make kalk context unsafe, but primary two-part advice can remain available.",
    ));
  }
  return expectations;
}

export const HYBRID_KALK_PLUS_PRIMARY_SCENARIOS = [
  {
    id: "reef-fusion-plus-kalk",
    title: "Reef Fusion plus secondary kalk support",
    expected: "Use Reef Fusion exact advice while showing normal secondary kalk safety context.",
    alkDoseMlPerDay: 16,
    caDoseMlPerDay: 16,
    alkStart: 8.52,
    alkDrift: -0.012,
    caStart: 444,
    caDrift: -0.34,
    mgStart: 1350,
    mgDrift: 0,
    phStart: 8.16,
  },
  {
    id: "high-ph-risk",
    title: "Hybrid dosing with high pH risk",
    expected: "Do not increase kalk while still allowing primary system review.",
    alkDoseMlPerDay: 16,
    caDoseMlPerDay: 16,
    alkStart: 8.5,
    alkDrift: -0.01,
    caStart: 442,
    caDrift: -0.28,
    mgStart: 1350,
    mgDrift: 0,
    phStart: 8.48,
    phNoise: 0.02,
    kalkMaxPh: 8.45,
  },
  {
    id: "no-ph-guard",
    title: "Hybrid dosing without pH guard",
    expected: "Warn that kalk context is unsafe while primary two-part advice remains available.",
    alkDoseMlPerDay: 16,
    caDoseMlPerDay: 16,
    alkStart: 8.5,
    alkDrift: -0.012,
    caStart: 442,
    caDrift: -0.34,
    mgStart: 1350,
    mgDrift: 0,
    noPhGuard: true,
  },
  {
    id: "all-for-reef-plus-kalk",
    title: "All-For-Reef plus secondary kalk support",
    expected: "Show AFR maintenance guidance plus secondary kalk context; no correction bolus.",
    primaryProduct: "tropic_marin_all_for_reef",
    sharedDoseMlPerDay: 28,
    alkStart: 8.5,
    alkDrift: -0.01,
    caStart: 442,
    caDrift: -0.26,
    mgStart: 1360,
    mgDrift: -0.18,
    phStart: 8.16,
  },
];

export function runHybridKalkPlusPrimaryEval({ createPanel }) {
  const scenarioReports = HYBRID_KALK_PLUS_PRIMARY_SCENARIOS.map((scenario) => {
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
    "# Hybrid Kalkwasser Plus Primary Dosing Eval",
    "",
    `Fixed eval clock: ${new Date(FIXED_NOW).toISOString()}`,
    "Tank: 200 L mixed reef.",
    "Targets: alkalinity 8.3 dKH, calcium 430 ppm, magnesium 1350 ppm.",
    "Primary source for dosing advice: simulated manual alkalinity/calcium/magnesium history.",
    "",
    "Source anchors checked:",
    "- Kalkwasser is high-pH and evaporation-limited, so OpenReef treats it as support rather than a correction product.",
    "- Reef Fusion exact advice remains on the primary two-part system; All-For-Reef remains maintenance-only.",
    "",
    "Hybrid model inputs tested: primary product advice, secondary kalk pH guard, evaporation capacity, no-pH-guard warnings, and no kalk correction bolus.",
    "",
    ...scenarioReports,
  ].join("\n");
}
