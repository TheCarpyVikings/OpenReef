import {
  EVAL_DAYS,
  FIXED_NOW,
  compactText,
  expectation,
  makeLiveSeries,
  makeManualSeries,
  stateFromSeries,
  textIncludes,
  withFixedNow,
} from "../sim-utils.mjs";

const TARGETS = {
  alkalinity: 8.3,
  calcium: 430,
  magnesium: 1350,
};

const SENSOR_META = {
  temp: ["Display Tank Temperature", "°C", 24.5, 27.5, "sensor.sim_display_temp", "tank"],
  ph: ["pH Level", "", 7.9, 8.35, "sensor.sim_ph", "chemistry"],
  salinity: ["Salinity", "ppt", 32, 36, "sensor.sim_salinity", "chemistry"],
  alkalinity: ["Alkalinity", "dKH", 7, 11, "", "chemistry"],
  calcium: ["Calcium", "ppm", 380, 460, "", "chemistry"],
  magnesium: ["Magnesium", "ppm", 1250, 1450, "", "chemistry"],
};

function sensorConfig() {
  return Object.fromEntries(Object.entries(SENSOR_META).map(([id, [label, unit, min, max, entityId, group]]) => {
    return [id, {
      label,
      unit,
      min,
      max,
      group,
      enabled: true,
      entity_id: entityId,
      alertsEnabled: true,
      warningBuffer: 10,
    }];
  }));
}

function schedules({ stale = false } = {}) {
  const ageMultiplier = stale ? 1 : 2;
  return {
    alkalinity: { enabled: true, cadenceDays: 4, criticalAfterDays: 8 * ageMultiplier, preferredSource: "Hanna" },
    calcium: { enabled: true, cadenceDays: 7, criticalAfterDays: 14 * ageMultiplier, preferredSource: "Salifert" },
    magnesium: { enabled: true, cadenceDays: 21, criticalAfterDays: 42 * ageMultiplier, preferredSource: "Salifert" },
  };
}

export function buildAllForReefManualReadings(scenario) {
  return {
    alkalinity: makeManualSeries({
      parameter: "alkalinity",
      unit: "dKH",
      startValue: scenario.alkStart,
      dailyDrift: scenario.alkDrift,
      noise: scenario.alkNoise ?? 0.05,
      intervalDays: scenario.manualIntervalDays ?? 4,
      latestAgeDays: scenario.latestAgeDays ?? 1,
      source: "Hanna",
      seed: scenario.id,
    }),
    calcium: makeManualSeries({
      parameter: "calcium",
      unit: "ppm",
      startValue: scenario.caStart,
      dailyDrift: scenario.caDrift,
      noise: scenario.caNoise ?? 5,
      intervalDays: scenario.calciumIntervalDays ?? 7,
      latestAgeDays: scenario.latestAgeDays ?? 1,
      source: "Salifert",
      seed: scenario.id,
    }),
    magnesium: makeManualSeries({
      parameter: "magnesium",
      unit: "ppm",
      startValue: scenario.mgStart,
      dailyDrift: scenario.mgDrift,
      noise: scenario.mgNoise ?? 15,
      intervalDays: scenario.magnesiumIntervalDays ?? 10,
      latestAgeDays: scenario.latestAgeDays ?? 1,
      source: "Salifert",
      seed: scenario.id,
    }),
  };
}

function buildLiveContext(scenario) {
  const ph = makeLiveSeries({
    entityId: "sensor.sim_ph",
    unit: "",
    startValue: scenario.phStart ?? 8.12,
    dailyDrift: scenario.phDrift ?? 0,
    noise: scenario.phNoise ?? 0.07,
    intervalHours: 6,
    seed: `${scenario.id}:ph`,
  });
  const temp = makeLiveSeries({
    entityId: "sensor.sim_display_temp",
    unit: "°C",
    startValue: scenario.tempStart ?? 25.2,
    dailyDrift: 0,
    noise: 0.25,
    intervalHours: 6,
    seed: `${scenario.id}:temp`,
  });
  const salinity = makeLiveSeries({
    entityId: "sensor.sim_salinity",
    unit: "ppt",
    startValue: scenario.salinityStart ?? 35,
    dailyDrift: 0,
    noise: 0.12,
    intervalHours: 12,
    seed: `${scenario.id}:salinity`,
  });
  return { ph, temp, salinity };
}

function buildPanelState(panel, scenario) {
  const manualReadings = buildAllForReefManualReadings(scenario);
  const liveContext = buildLiveContext(scenario);
  const currentDose = scenario.currentDoseMlPerDay ?? 20;
  panel._integrationVersion = "eval";
  panel._config = {
    schemaVersion: 31,
    tank: { name: "All-For-Reef Eval Reef", owner: "OpenReef Eval", profile: "mixed_reef" },
    display: { themeColor: "#22c55e", setupComplete: true, missionCards: { dosing: true } },
    alerts: { hysteresisPercent: 2, muteUntil: {}, lastStates: {} },
    sensors: sensorConfig(),
    equipment: {},
    energy: {},
    manualReadings,
    manualTests: {
      enabled: true,
      schedules: schedules({ stale: scenario.stale }),
    },
    dosing: {
      enabled: true,
      system: {
        primaryProduct: "tropic_marin_all_for_reef",
        secondaryProduct: "",
        tankVolumeLitres: 200,
        sharedDailyDoseMl: currentDose,
        freshTestRequired: true,
        safetyAcknowledged: true,
      },
      parameters: {
        alkalinity: { doserMlPerDay: currentDose, target: TARGETS.alkalinity },
        calcium: { doserMlPerDay: currentDose, target: TARGETS.calcium },
        magnesium: { doserMlPerDay: currentDose, target: TARGETS.magnesium },
      },
    },
  };
  panel._hass = {
    states: {
      "sensor.sim_ph": stateFromSeries(liveContext.ph, "Simulated pH"),
      "sensor.sim_display_temp": stateFromSeries(liveContext.temp, "Simulated Display Temperature"),
      "sensor.sim_salinity": stateFromSeries(liveContext.salinity, "Simulated Salinity"),
    },
  };
  return { manualReadings, liveContext };
}

function analysePanel(panel) {
  return withFixedNow(() => {
    const items = {};
    panel._dosingActiveParameters().forEach(([id, sensor]) => {
      const trendData = panel._manualTrendData(id);
      const healthItem = panel._analyseHealthTrend(id, sensor, trendData);
      items[id] = panel._analyseConsumption(id, sensor, trendData, healthItem);
    });
    panel._consumption = {
      checkedAt: new Date(FIXED_NOW).toISOString(),
      items,
      error: "",
    };
    return {
      mission: panel._dosingMissionState(),
      items,
      summary: panel._dosingSummaryText(),
    };
  });
}

function allAdvice(result) {
  return Object.values(result.items)
    .map((item) => [
      item.maintenanceText,
      item.correctionText,
      item.doNotDoseText,
      item.safetyText,
      item.productAssumption,
    ].filter(Boolean).join(" "))
    .join("\n");
}

function countReadings(readings) {
  return Object.values(readings).reduce((total, rows) => total + rows.length, 0);
}

function livePointCount(liveContext) {
  return Object.values(liveContext).reduce((total, rows) => total + rows.length, 0);
}

function baseExpectations(scenario, result) {
  const text = allAdvice(result);
  const expectations = [
    expectation(
      "No All-For-Reef correction bolus",
      !textIncludes(text, "Advisory correction total") && !textIncludes(text, "split it across about"),
      "All-For-Reef must stay maintenance guidance in this beta pass.",
      "If this fails, correction logic is treating AFR like an exact-strength two-part.",
    ),
    expectation(
      "No automated dosing control language",
      !textIncludes(text, "OpenReef will control") && !textIncludes(text, "automated dosing"),
      "Eval advice must remain advisory-only.",
      "If this fails, wording could imply OpenReef controls dosing pumps.",
    ),
  ];
  if (!scenario.stale) {
    expectations.push(expectation(
      "One-off correction warning is visible",
      textIncludes(text, "Do not use Tropic Marin All-For-Reef as a one-off") || textIncludes(text, "Do not use All-For-Reef for one-off"),
      "AFR setup should always explain that corrections are separate from maintenance dosing.",
    ));
  }
  return expectations;
}

function scenarioExpectations(scenario, result) {
  const text = allAdvice(result);
  const expectations = [...baseExpectations(scenario, result)];
  if (scenario.id === "stable-maintenance") {
    expectations.push(expectation(
      "Stable AFR advice stays calm",
      result.mission.status === "ok" || result.mission.status === "unknown",
      `Mission state: ${result.mission.value} / ${result.mission.status}.`,
    ));
  }
  if (scenario.id === "demand-increasing") {
    expectations.push(expectation(
      "Advisor suggests weekly maintenance review",
      textIncludes(text, "increasing the total daily dose by no more than 5.0 mL/day") && textIncludes(text, "retest calcium and alkalinity"),
      "For 200 L, the official weekly review step is 5 mL/day.",
      "Tune AFR text so falling demand produces a slow weekly review, not a correction.",
    ));
  }
  if (scenario.id === "near-max-dose") {
    expectations.push(expectation(
      "Near max dose warning appears",
      textIncludes(text, "close to the 50.0 mL/day max") || textIncludes(text, "at or above the 50.0 mL/day max"),
      "For 200 L, the official maximum is 50 mL/day.",
      "Tune AFR max-dose guidance before beta users trust the advice.",
    ));
  }
  if (scenario.id === "calcium-led-adjustment") {
    expectations.push(expectation(
      "Calcium-led regulator wording appears",
      textIncludes(text, "calcium as the regular dose regulator"),
      "Tropic Marin guidance says calcium is the preferred regular regulator once AFR is established.",
    ));
  }
  if (scenario.id === "imbalanced-parameters") {
    expectations.push(expectation(
      "Parameter imbalance is not solved with AFR alone",
      textIncludes(text, "correct the imbalance separately") || textIncludes(text, "into balance with separate correction"),
      "AFR should not pretend one shared dose can fix Alk/Ca/Mg imbalance.",
    ));
  }
  if (scenario.id === "stale-manual-tests") {
    expectations.push(expectation(
      "Stale manual tests lock action",
      textIncludes(text, "Retest") || textIncludes(text, "last logged"),
      "Old manual results should not produce actionable AFR changes.",
    ));
  }
  if (scenario.id === "above-target") {
    expectations.push(expectation(
      "Above-target chemistry avoids downward correction",
      textIncludes(text, "Do not add a chemical correction downward") || textIncludes(text, "Do not add a chemical correction while"),
      "OpenReef should not recommend chemical correction downward.",
    ));
  }
  return expectations;
}

export const ALL_FOR_REEF_SCENARIOS = [
  {
    id: "stable-maintenance",
    title: "Stable maintenance",
    expected: "Keep daily dose consistent; no correction bolus.",
    currentDoseMlPerDay: 20,
    alkStart: 8.32,
    alkDrift: -0.001,
    caStart: 431,
    caDrift: -0.03,
    mgStart: 1352,
    mgDrift: 0,
  },
  {
    id: "demand-increasing",
    title: "Demand increasing within headroom",
    expected: "Suggest a slow weekly All-For-Reef maintenance increase, then retest.",
    currentDoseMlPerDay: 20,
    alkStart: 8.55,
    alkDrift: -0.012,
    caStart: 442,
    caDrift: -0.35,
    mgStart: 1360,
    mgDrift: -0.05,
  },
  {
    id: "near-max-dose",
    title: "Near max dose / demand outgrowing AFR",
    expected: "Warn the current AFR dose is near max; do not push beyond 25 mL/100 L/day.",
    currentDoseMlPerDay: 48,
    alkStart: 8.45,
    alkDrift: -0.014,
    caStart: 438,
    caDrift: -0.35,
    mgStart: 1355,
    mgDrift: -0.03,
  },
  {
    id: "calcium-led-adjustment",
    title: "Calcium-led adjustment",
    expected: "Mention calcium as the regular dose regulator while still checking Alk/Mg.",
    currentDoseMlPerDay: 18,
    alkStart: 8.32,
    alkDrift: -0.001,
    caStart: 440,
    caDrift: -0.32,
    mgStart: 1350,
    mgDrift: 0,
  },
  {
    id: "imbalanced-parameters",
    title: "Imbalanced parameters",
    expected: "Warn that AFR alone should not be used to solve Alk/Ca/Mg imbalance.",
    currentDoseMlPerDay: 22,
    alkStart: 8.05,
    alkDrift: 0.008,
    caStart: 450,
    caDrift: -0.28,
    mgStart: 1325,
    mgDrift: 0.18,
  },
  {
    id: "stale-manual-tests",
    title: "Stale manual tests",
    expected: "Lock action until fresh tests are logged.",
    currentDoseMlPerDay: 20,
    alkStart: 8.45,
    alkDrift: -0.01,
    caStart: 438,
    caDrift: -0.2,
    mgStart: 1360,
    mgDrift: -0.1,
    latestAgeDays: 30,
    stale: true,
  },
  {
    id: "above-target",
    title: "Above-target chemistry",
    expected: "Suggest hold/reduce review only; no chemical downward correction.",
    currentDoseMlPerDay: 24,
    alkStart: 8.7,
    alkDrift: 0.006,
    caStart: 445,
    caDrift: 0.15,
    mgStart: 1365,
    mgDrift: 0.1,
  },
];

function scenarioReport(scenario, result, manualReadings, liveContext) {
  const expectations = scenarioExpectations(scenario, result);
  const failures = expectations.filter((item) => !item.passed);
  const rows = Object.entries(result.items).map(([id, item]) => [
    id,
    item.recommendationState,
    item.status,
    compactText(item.maintenanceText),
    compactText(item.correctionText),
    compactText(item.safetyText),
  ]);
  return [
    `## ${scenario.title}`,
    "",
    `Expected: ${scenario.expected}`,
    `Manual data: ${countReadings(manualReadings)} readings across ${EVAL_DAYS} days.`,
    `Live context: ${livePointCount(liveContext)} pH/temp/salinity points across ${EVAL_DAYS} days.`,
    `Advisor mission state: **${result.mission.value}** (${result.mission.status}) - ${result.mission.detail}`,
    "",
    "| Parameter | State | Status | Maintenance | Correction | Safety |",
    "|---|---|---|---|---|---|",
    ...rows.map((row) => `| ${row.map((cell) => String(cell).replaceAll("|", "/")).join(" | ")} |`),
    "",
    "### Expectations",
    "",
    ...expectations.map((item) => {
      const line = `- ${item.passed ? "PASS" : "TWEAK"}: ${item.label}${item.detail ? ` - ${item.detail}` : ""}`;
      return item.passed || !item.tweak ? line : `${line} Tweak needed: ${item.tweak}`;
    }),
    "",
    failures.length ? "### Tweaks Needed\n" : "",
    ...failures.map((item) => `- ${item.tweak || item.label}`),
    "",
  ].filter((line) => line !== "").join("\n");
}

export function runAllForReefMaintenanceEval({ createPanel }) {
  const scenarioReports = ALL_FOR_REEF_SCENARIOS.map((scenario) => {
    const panel = createPanel();
    const { manualReadings, liveContext } = buildPanelState(panel, scenario);
    const result = analysePanel(panel);
    return scenarioReport(scenario, result, manualReadings, liveContext);
  });
  return [
    "# Tropic Marin All-For-Reef Maintenance Eval",
    "",
    `Fixed eval clock: ${new Date(FIXED_NOW).toISOString()}`,
    "Tank: 200 L mixed reef.",
    "Targets: alkalinity 8.3 dKH, calcium 430 ppm, magnesium 1350 ppm.",
    "Primary source for dosing advice: simulated manual alkalinity/calcium/magnesium history.",
    "Live context: simulated pH, display temperature, and salinity history.",
    "",
    "Source anchors checked:",
    "- Tropic Marin All-For-Reef: start at 5 mL/100 L/day, review upward by 2.5 mL/100 L weekly, do not exceed 25 mL/100 L/day, and correct initial imbalances separately.",
    "- Local dosing research doc on balanced all-in-one maintenance systems.",
    "",
    "All-For-Reef model inputs tested: tank volume, current daily dose, weekly review step, maximum daily dose, and manual-test freshness.",
    "",
    ...scenarioReports,
  ].join("\n");
}
