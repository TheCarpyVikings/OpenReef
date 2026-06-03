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

export function buildReefFusionManualReadings(scenario) {
  return {
    alkalinity: makeManualSeries({
      parameter: "alkalinity",
      unit: "dKH",
      startValue: scenario.alkStart,
      dailyDrift: scenario.alkDrift,
      noise: scenario.alkNoise ?? 0.04,
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
      noise: scenario.caNoise ?? 4,
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
      noise: scenario.mgNoise ?? 12,
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
    noise: scenario.phNoise ?? 0.06,
    intervalHours: 6,
    seed: `${scenario.id}:ph`,
  });
  const temp = makeLiveSeries({
    entityId: "sensor.sim_display_temp",
    unit: "°C",
    startValue: scenario.tempStart ?? 25.1,
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
  const manualReadings = buildReefFusionManualReadings(scenario);
  const liveContext = buildLiveContext(scenario);
  panel._integrationVersion = "eval";
  panel._config = {
    schemaVersion: 31,
    tank: { name: "Reef Fusion Eval Reef", owner: "OpenReef Eval", profile: "mixed_reef" },
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
        primaryProduct: "seachem_reef_fusion",
        secondaryProduct: "",
        tankVolumeLitres: scenario.tankVolumeLitres ?? 200,
        freshTestRequired: true,
        safetyAcknowledged: scenario.safetyAcknowledged !== false,
      },
      parameters: {
        alkalinity: { doserMlPerDay: scenario.alkDoseMlPerDay ?? 15, target: TARGETS.alkalinity },
        calcium: { doserMlPerDay: scenario.caDoseMlPerDay ?? 15, target: TARGETS.calcium },
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

function baseExpectations(scenario, result) {
  const text = allAdvice(result);
  const alk = result.items.alkalinity;
  const calcium = result.items.calcium;
  const expectations = [
    expectation(
      "No automated dosing control language",
      !textIncludes(text, "OpenReef will control") && !textIncludes(text, "automated dosing"),
      "Eval advice must remain advisory-only.",
      "If this fails, wording could imply OpenReef controls dosing pumps.",
    ),
  ];
  if (!scenario.stale) {
    expectations.push(
      expectation(
        "Seachem preset strengths are active",
        alk?.potencyInfo?.source === "preset" && calcium?.potencyInfo?.source === "preset",
        "Reef Fusion 1 and 2 exact strengths should be taken from the product preset.",
        "If this fails, the advisor is not using the verified Seachem preset.",
      ),
      expectation(
        "Separate-part safety warning is visible",
        textIncludes(text, "never mix the two bottles directly") || textIncludes(text, "Dose Reef Fusion 1 and 2 separately"),
        "Two-part advice must remind users not to mix the parts.",
      ),
    );
  }
  return expectations;
}

function scenarioExpectations(scenario, result) {
  const text = allAdvice(result);
  const alk = result.items.alkalinity;
  const calcium = result.items.calcium;
  const magnesium = result.items.magnesium;
  const expectations = [...baseExpectations(scenario, result)];
  if (scenario.id === "stable-two-part") {
    expectations.push(expectation(
      "Stable two-part advice stays calm",
      result.mission.status === "ok" || result.mission.status === "unknown",
      `Mission state: ${result.mission.value} / ${result.mission.status}.`,
    ));
  }
  if (scenario.id === "alkalinity-demand") {
    expectations.push(expectation(
      "Alkalinity exact maintenance advice appears",
      alk?.extraMlPerDay > 0 && textIncludes(alk.maintenanceText, "Suggested next dose"),
      "Alkalinity is falling while calcium is stable, so only Reef Fusion 2 should need review.",
      "Tune exact two-part maintenance wording before beta users rely on it.",
    ));
    expectations.push(expectation(
      "Calcium is not incorrectly increased",
      !calcium?.extraMlPerDay || Math.abs(calcium.extraMlPerDay) < 0.5,
      "Calcium movement should stay below the useful signal in this scenario.",
    ));
  }
  if (scenario.id === "calcium-demand") {
    expectations.push(expectation(
      "Calcium exact maintenance advice appears",
      calcium?.extraMlPerDay > 0 && textIncludes(calcium.maintenanceText, "Suggested next dose"),
      "Calcium is falling while alkalinity is stable, so only Reef Fusion 1 should need review.",
      "Tune exact two-part maintenance wording before beta users rely on it.",
    ));
    expectations.push(expectation(
      "Alkalinity is not incorrectly increased",
      !alk?.extraMlPerDay || Math.abs(alk.extraMlPerDay) < 0.5,
      "Alkalinity movement should stay below the useful signal in this scenario.",
    ));
  }
  if (scenario.id === "balanced-demand") {
    expectations.push(expectation(
      "Both parts get independent exact maintenance advice",
      alk?.extraMlPerDay > 0 && calcium?.extraMlPerDay > 0,
      "A two-part system should advise each part independently from the matching test trend.",
    ));
  }
  if (scenario.id === "near-max-dose") {
    expectations.push(expectation(
      "Daily product max is respected",
      textIncludes(text, "product maximum") || textIncludes(text, "daily maximum"),
      "Seachem's max of 4 mL per 25 L per product should be visible when the dose is near the limit.",
      "Add/tune Reef Fusion max-dose handling before beta users trust high-demand advice.",
    ));
  }
  if (scenario.id === "stale-manual-tests") {
    expectations.push(expectation(
      "Stale manual tests lock action",
      textIncludes(text, "Retest") || textIncludes(text, "last logged"),
      "Old manual results should not produce actionable Reef Fusion changes.",
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
      "Magnesium is not assigned to Reef Fusion",
      magnesium?.recommendationState === "not-covered" || textIncludes(text, "not a Magnesium dosing product") || textIncludes(text, "does not maintain Magnesium"),
      "Reef Fusion 1/2 is Alk/Ca here; magnesium needs a separate plan.",
      "Improve product coverage rules if Mg advice appears under Reef Fusion.",
    ));
  }
  return expectations;
}

export const REEF_FUSION_SCENARIOS = [
  {
    id: "stable-two-part",
    title: "Stable two-part dosing",
    expected: "Keep both parts steady; no correction or dose-change pressure.",
    alkDoseMlPerDay: 15,
    caDoseMlPerDay: 15,
    alkStart: 8.32,
    alkDrift: -0.001,
    caStart: 431,
    caDrift: -0.03,
    mgStart: 1352,
    mgDrift: 0,
  },
  {
    id: "alkalinity-demand",
    title: "Alkalinity demand rising",
    expected: "Suggest an exact Reef Fusion 2 maintenance review; calcium stays calm.",
    alkDoseMlPerDay: 14,
    caDoseMlPerDay: 15,
    alkStart: 8.48,
    alkDrift: -0.011,
    caStart: 431,
    caDrift: -0.02,
    mgStart: 1350,
    mgDrift: 0,
  },
  {
    id: "calcium-demand",
    title: "Calcium demand rising",
    expected: "Suggest an exact Reef Fusion 1 maintenance review; alkalinity stays calm.",
    alkDoseMlPerDay: 15,
    caDoseMlPerDay: 14,
    alkStart: 8.31,
    alkDrift: -0.001,
    caStart: 444,
    caDrift: -0.34,
    mgStart: 1350,
    mgDrift: 0.02,
  },
  {
    id: "balanced-demand",
    title: "Both parts falling",
    expected: "Give independent exact advice for Reef Fusion 1 and 2, not a shared dose.",
    alkDoseMlPerDay: 16,
    caDoseMlPerDay: 16,
    alkStart: 8.52,
    alkDrift: -0.012,
    caStart: 443,
    caDrift: -0.36,
    mgStart: 1355,
    mgDrift: -0.03,
  },
  {
    id: "near-max-dose",
    title: "Near max dose / demand outgrowing two-part",
    expected: "Warn before pushing beyond Seachem's 4 mL per 25 L daily maximum.",
    alkDoseMlPerDay: 31,
    caDoseMlPerDay: 31,
    alkStart: 8.55,
    alkDrift: -0.07,
    caStart: 445,
    caDrift: -2.4,
    mgStart: 1350,
    mgDrift: 0,
  },
  {
    id: "stale-manual-tests",
    title: "Stale manual tests",
    expected: "Lock exact advice until fresh tests are logged.",
    alkDoseMlPerDay: 15,
    caDoseMlPerDay: 15,
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
    title: "Above-target chemistry",
    expected: "Avoid chemical correction downward; suggest review/hold only.",
    alkDoseMlPerDay: 18,
    caDoseMlPerDay: 18,
    alkStart: 8.8,
    alkDrift: 0.005,
    caStart: 450,
    caDrift: 0.12,
    mgStart: 1355,
    mgDrift: 0,
  },
  {
    id: "magnesium-drift",
    title: "Magnesium drift",
    expected: "State that Reef Fusion 1/2 does not cover magnesium in this preset.",
    alkDoseMlPerDay: 15,
    caDoseMlPerDay: 15,
    alkStart: 8.32,
    alkDrift: -0.001,
    caStart: 431,
    caDrift: -0.03,
    mgStart: 1405,
    mgDrift: -1.1,
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

export function runSeachemReefFusionEval({ createPanel }) {
  const scenarioReports = REEF_FUSION_SCENARIOS.map((scenario) => {
    const panel = createPanel();
    const { manualReadings, liveContext } = buildPanelState(panel, scenario);
    const result = analysePanel(panel);
    return scenarioReport(scenario, result, manualReadings, liveContext);
  });
  return [
    "# Seachem Reef Fusion 1/2 Eval",
    "",
    `Fixed eval clock: ${new Date(FIXED_NOW).toISOString()}`,
    "Tank: 200 L mixed reef.",
    "Targets: alkalinity 8.3 dKH, calcium 430 ppm, magnesium 1350 ppm.",
    "Primary source for dosing advice: simulated manual alkalinity/calcium/magnesium history.",
    "Live context: simulated pH, display temperature, and salinity history.",
    "",
    "Source anchors checked:",
    "- Seachem Reef Fusion: 1 mL / 25 L raises calcium by 4 ppm; 1 mL / 25 L raises alkalinity by 0.176 meq/L (~0.493 dKH); do not exceed 4 mL / 25 L per day; dose parts separately and do not mix directly.",
    "",
    "Reef Fusion model inputs tested: net tank volume, separate current daily doses for parts 1 and 2, preset strengths, product daily maximum, target values, and manual-test freshness.",
    "",
    ...scenarioReports,
  ].join("\n");
}
