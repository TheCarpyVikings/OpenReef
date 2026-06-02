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

const KALK_SYSTEM = {
  kalkDailyDoseMl: 900,
  kalkConcentrationTspPerGallon: 1,
  kalkEvaporationLimitMlPerDay: 1600,
  kalkMaxPh: 8.45,
  kalkMaxPhRise: 0.2,
};

function sensorConfig({ phMapped = true } = {}) {
  return Object.fromEntries(Object.entries(SENSOR_META).map(([id, [label, unit, min, max, entityId, group]]) => {
    const mappedEntity = id === "ph" && !phMapped ? "" : entityId;
    return [id, {
      label,
      unit,
      min,
      max,
      group,
      enabled: ["temp", "salinity", "alkalinity", "calcium", "magnesium"].includes(id) || (id === "ph" && phMapped),
      entity_id: mappedEntity,
      alertsEnabled: true,
      warningBuffer: 10,
    }];
  }));
}

function schedules({ stale = false } = {}) {
  const ageMultiplier = stale ? 1 : 2;
  return {
    alkalinity: { enabled: true, cadenceDays: 4, criticalAfterDays: 8 * ageMultiplier, preferredSource: "Hanna" },
    calcium: { enabled: true, cadenceDays: 14, criticalAfterDays: 28 * ageMultiplier, preferredSource: "Salifert" },
    magnesium: { enabled: true, cadenceDays: 21, criticalAfterDays: 42 * ageMultiplier, preferredSource: "Salifert" },
  };
}

function buildManualReadings(scenario) {
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
    startValue: scenario.phStart,
    dailyDrift: scenario.phDrift ?? 0,
    noise: scenario.phNoise ?? 0.08,
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
  const manualReadings = buildManualReadings(scenario);
  const liveContext = buildLiveContext(scenario);
  panel._integrationVersion = "eval";
  panel._config = {
    schemaVersion: 31,
    tank: { name: "Kalk Eval Reef", owner: "OpenReef Eval", profile: "mixed_reef" },
    display: { themeColor: "#22c55e", setupComplete: true, missionCards: { dosing: true } },
    alerts: { hysteresisPercent: 2, muteUntil: {}, lastStates: {} },
    sensors: sensorConfig({ phMapped: scenario.phMapped !== false }),
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
        primaryProduct: "",
        secondaryProduct: "kalkwasser_calcium_hydroxide",
        secondaryDelivery: "dosing_pump",
        tankVolumeLitres: 200,
        ...KALK_SYSTEM,
        freshTestRequired: true,
        safetyAcknowledged: true,
      },
      parameters: {
        alkalinity: { doserMlPerDay: 900, target: TARGETS.alkalinity },
        calcium: { doserMlPerDay: 900, target: TARGETS.calcium },
        magnesium: { doserMlPerDay: 0, target: TARGETS.magnesium },
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

function baseExpectations(result) {
  const text = allAdvice(result);
  return [
    expectation(
      "No kalkwasser correction bolus",
      !textIncludes(text, "Advisory correction total") && !textIncludes(text, "split it across about"),
      "Kalkwasser must stay maintenance/support only.",
      "If this fails, correction logic is treating kalk like a normal two-part product.",
    ),
    expectation(
      "No automated dosing control language",
      !textIncludes(text, "OpenReef will control") && !textIncludes(text, "automated dosing"),
      "Eval advice must remain advisory-only.",
      "If this fails, wording could scare beta testers or imply pump control.",
    ),
  ];
}

function scenarioExpectations(scenario, result) {
  const text = allAdvice(result);
  const expectations = [...baseExpectations(result)];
  if (scenario.id === "stable-support") {
    expectations.push(expectation(
      "Stable kalk advice stays calm",
      result.mission.status === "ok" || result.mission.status === "warning",
      `Mission state: ${result.mission.value} / ${result.mission.status}.`,
    ));
  }
  if (scenario.id === "demand-outgrowing-kalk") {
    expectations.push(expectation(
      "Advisor flags kalk capacity gap",
      textIncludes(text, "may not keep up") || textIncludes(text, "add a primary") || textIncludes(text, "evaporation limit"),
      "Kalk should not pretend it can always cover rising demand.",
      "Tune kalk escalation wording so falling Alk/Ca never looks like a precise correction bolus.",
    ));
  }
  if (scenario.id === "high-ph-risk") {
    expectations.push(expectation(
      "High pH risk is explicit",
      textIncludes(text, "high pH") || textIncludes(text, "max pH") || textIncludes(text, "Do not increase kalk"),
      "pH is above the normal mixed-reef ceiling in this scenario.",
      "Read mapped pH state in kalk safety gates and warn before any increase guidance appears.",
    ));
  }
  if (scenario.id === "no-ph-guard") {
    expectations.push(expectation(
      "No pH guard warning appears",
      textIncludes(text, "No mapped pH guard"),
      "Kalk safety should visibly warn when pH is not mapped.",
    ));
  }
  if (scenario.id === "stale-manual-tests") {
    expectations.push(expectation(
      "Stale manual tests lock action",
      textIncludes(text, "Retest") || textIncludes(text, "last logged"),
      "Old manual results should not produce actionable dosing advice.",
    ));
  }
  if (scenario.id === "magnesium-drift") {
    expectations.push(expectation(
      "Magnesium is not assigned to kalkwasser",
      textIncludes(text, "not a Magnesium dosing product") || textIncludes(text, "does not maintain magnesium"),
      "Kalkwasser cannot be allowed to appear as the Mg solution.",
      "Improve wording if the lock is technically correct but not friendly enough.",
    ));
  }
  if (scenario.id === "above-target-chemistry") {
    expectations.push(expectation(
      "Above-target chemistry avoids downward correction",
      textIncludes(text, "Do not") && (textIncludes(text, "downward") || textIncludes(text, "one-off correction")),
      "OpenReef should not recommend chemical correction downward.",
    ));
  }
  return expectations;
}

const SCENARIOS = [
  {
    id: "stable-support",
    title: "Stable support",
    expected: "Maintenance/support guidance only, pH safe, no correction bolus.",
    alkStart: 8.28,
    alkDrift: -0.001,
    caStart: 430,
    caDrift: -0.04,
    mgStart: 1350,
    mgDrift: 0.02,
    phStart: 8.15,
  },
  {
    id: "demand-outgrowing-kalk",
    title: "Demand outgrowing kalk",
    expected: "Warn that kalk may not keep up; suggest review/escalation rather than fake precision.",
    alkStart: 8.65,
    alkDrift: -0.018,
    caStart: 445,
    caDrift: -0.55,
    mgStart: 1360,
    mgDrift: -0.05,
    phStart: 8.17,
  },
  {
    id: "high-ph-risk",
    title: "High pH risk",
    expected: "Do not increase kalk; show high-pH safety warning prominently.",
    alkStart: 8.2,
    alkDrift: -0.007,
    caStart: 427,
    caDrift: -0.2,
    mgStart: 1350,
    mgDrift: 0,
    phStart: 8.48,
    phNoise: 0.03,
  },
  {
    id: "no-ph-guard",
    title: "No pH guard",
    expected: "Warn/lock because kalk context has no mapped pH sensor.",
    alkStart: 8.3,
    alkDrift: -0.006,
    caStart: 430,
    caDrift: -0.15,
    mgStart: 1350,
    mgDrift: 0,
    phStart: 8.15,
    phMapped: false,
  },
  {
    id: "stale-manual-tests",
    title: "Stale manual tests",
    expected: "Exact/actionable advice locked until fresh tests are logged.",
    alkStart: 8.5,
    alkDrift: -0.01,
    caStart: 440,
    caDrift: -0.25,
    mgStart: 1360,
    mgDrift: -0.2,
    phStart: 8.14,
    latestAgeDays: 40,
    stale: true,
  },
  {
    id: "magnesium-drift",
    title: "Magnesium drift",
    expected: "State that kalkwasser does not maintain magnesium.",
    alkStart: 8.32,
    alkDrift: -0.002,
    caStart: 431,
    caDrift: -0.05,
    mgStart: 1400,
    mgDrift: -1.1,
    phStart: 8.16,
  },
  {
    id: "above-target-chemistry",
    title: "Above-target chemistry",
    expected: "Do not chemically correct downward; let consumption/water changes reduce.",
    alkStart: 8.9,
    alkDrift: 0.003,
    caStart: 455,
    caDrift: 0.05,
    mgStart: 1350,
    mgDrift: 0,
    phStart: 8.19,
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

export function runKalkwasserDosingPumpEval({ createPanel }) {
  const scenarioReports = SCENARIOS.map((scenario) => {
    const panel = createPanel();
    const { manualReadings, liveContext } = buildPanelState(panel, scenario);
    const result = analysePanel(panel);
    return scenarioReport(scenario, result, manualReadings, liveContext);
  });
  return [
    "# Kalkwasser / Calcium Hydroxide Dosing-Pump Eval",
    "",
    `Fixed eval clock: ${new Date(FIXED_NOW).toISOString()}`,
    "Tank: 200 L mixed reef.",
    "Targets: alkalinity 8.3 dKH, calcium 430 ppm, magnesium 1350 ppm, pH normal 7.9-8.35.",
    "Primary source for dosing advice: simulated manual alkalinity/calcium/magnesium history.",
    "Live context: simulated pH, display temperature, and salinity history.",
    "",
    "Source anchors checked:",
    "- BRS Pharma Kalkwasser: evaporation-limited, slow dosing, pH constrained.",
    "- Brightwell Kalk+2: slow clear-solution dosing, pH rise guardrails.",
    "- Local dosing research doc on hybrid systems and kalkwasser guardrails.",
    "",
    "Kalk model inputs tested: daily kalk volume, concentration, evaporation ceiling, max pH, and max pH rise.",
    "",
    ...scenarioReports,
  ].join("\n");
}
