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

// Verified-strength example based on a Randy/BRS-style recipe-1 mix.
// The eval intentionally treats these as user-entered instructions rather than
// a universal product preset, because real DIY strength depends on the recipe.
const DIY_STRENGTHS = {
  alkalinity: { productDoseMl: 1, productVolumeLitres: 100, productRaise: 0.053 },
  calcium: { productDoseMl: 1, productVolumeLitres: 100, productRaise: 0.37 },
  magnesium: { productDoseMl: 1, productVolumeLitres: 100, productRaise: 0.47 },
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
    magnesium: { enabled: true, cadenceDays: 14, criticalAfterDays: 28 * ageMultiplier, preferredSource: "Salifert" },
  };
}

export function buildCustomDiyManualReadings(scenario) {
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
      noise: scenario.mgNoise ?? 10,
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
    dailyDrift: scenario.salinityDrift ?? 0,
    noise: 0.12,
    intervalHours: 12,
    seed: `${scenario.id}:salinity`,
  });
  return { ph, temp, salinity };
}

function dosingParameterConfig(parameter, scenario) {
  const doseKey = {
    alkalinity: "alkDoseMlPerDay",
    calcium: "caDoseMlPerDay",
    magnesium: "mgDoseMlPerDay",
  }[parameter];
  const targetKey = {
    alkalinity: "alkTarget",
    calcium: "caTarget",
    magnesium: "mgTarget",
  }[parameter];
  const strength = scenario.missingStrengthFor === parameter
    ? {}
    : scenario.strengthOverrides?.[parameter] || DIY_STRENGTHS[parameter];
  return {
    doserMlPerDay: scenario[doseKey] ?? 20,
    target: scenario[targetKey] ?? TARGETS[parameter],
    ...strength,
  };
}

function buildPanelState(panel, scenario) {
  const manualReadings = buildCustomDiyManualReadings(scenario);
  const liveContext = buildLiveContext(scenario);
  panel._integrationVersion = "eval";
  panel._config = {
    schemaVersion: 31,
    tank: { name: "DIY Three-Part Eval Reef", owner: "OpenReef Eval", profile: "mixed_reef" },
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
        primaryProduct: "brs_pharma_two_part",
        secondaryProduct: "",
        tankVolumeLitres: scenario.tankVolumeLitres ?? 200,
        customProductName: "DIY verified three-part",
        freshTestRequired: true,
        safetyAcknowledged: scenario.safetyAcknowledged !== false,
      },
      parameters: {
        alkalinity: dosingParameterConfig("alkalinity", scenario),
        calcium: dosingParameterConfig("calcium", scenario),
        magnesium: dosingParameterConfig("magnesium", scenario),
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
      item.potencyInfo?.label,
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
      "No automated dosing control language",
      !textIncludes(text, "OpenReef will control") && !textIncludes(text, "automated dosing"),
      "Eval advice must remain advisory-only.",
      "If this fails, wording could imply OpenReef controls dosing pumps.",
    ),
  ];
  if (!scenario.stale) {
    expectations.push(expectation(
      "DIY separate-part safety reminder is visible",
      textIncludes(text, "Dose DIY calcium, alkalinity, and magnesium parts separately"),
      "Concentrated DIY parts should be dosed separately and verified.",
    ));
  }
  return expectations;
}

function scenarioExpectations(scenario, result) {
  const text = allAdvice(result);
  const alk = result.items.alkalinity;
  const calcium = result.items.calcium;
  const magnesium = result.items.magnesium;
  const expectations = [...baseExpectations(scenario, result)];
  if (scenario.id === "stable-verified-three-part") {
    expectations.push(expectation(
      "Stable verified-strength advice stays calm",
      result.mission.status === "ok" || result.mission.status === "unknown",
      `Mission state: ${result.mission.value} / ${result.mission.status}.`,
    ));
  }
  if (scenario.id === "alkalinity-demand") {
    expectations.push(expectation(
      "Alkalinity exact maintenance advice appears",
      alk?.potencyInfo?.source === "calculator" && alk?.extraMlPerDay > 0 && textIncludes(alk.maintenanceText, "Suggested next dose"),
      "Verified DIY alkalinity strength should unlock exact advisory mL changes.",
      "If this fails, the advisor is ignoring user-entered DIY alkalinity strength.",
    ));
  }
  if (scenario.id === "implausibly-weak-alkalinity-strength") {
    expectations.push(expectation(
      "Implausibly weak custom strength locks exact advice",
      alk?.recommendationState === "warning"
        && textIncludes(alk.maintenanceText, "implausibly weak")
        && !textIncludes(alk.maintenanceText, "Suggested next dose")
        && !textIncludes(alk.correctionText, "5300"),
      "OpenReef should catch likely recipe/unit mistakes before showing huge custom-product mL advice.",
      "If this fails, custom verified-strength products can still display unsafe-looking exact dose changes.",
    ));
  }
  if (scenario.id === "calcium-demand") {
    expectations.push(expectation(
      "Calcium exact maintenance advice appears",
      calcium?.potencyInfo?.source === "calculator" && calcium?.extraMlPerDay > 0 && textIncludes(calcium.maintenanceText, "Suggested next dose"),
      "Verified DIY calcium strength should unlock exact advisory mL changes.",
      "If this fails, the advisor is ignoring user-entered DIY calcium strength.",
    ));
  }
  if (scenario.id === "magnesium-demand") {
    expectations.push(expectation(
      "Magnesium exact maintenance advice appears",
      magnesium?.potencyInfo?.source === "calculator" && magnesium?.extraMlPerDay > 0 && textIncludes(magnesium.maintenanceText, "Suggested next dose"),
      "Verified DIY magnesium strength should unlock exact advisory mL changes.",
      "If this fails, the advisor is treating DIY magnesium like an unsupported two-part parameter.",
    ));
  }
  if (scenario.id === "balanced-three-part-demand") {
    expectations.push(expectation(
      "All three parts get independent advice",
      alk?.extraMlPerDay > 0 && calcium?.extraMlPerDay > 0 && magnesium?.extraMlPerDay > 0,
      "A DIY three-part setup should advise each verified part independently.",
    ));
  }
  if (scenario.id === "missing-calcium-strength") {
    expectations.push(expectation(
      "Missing custom strength locks exact calcium advice",
      calcium?.potencyInfo?.source === "custom-required" && !textIncludes(calcium.maintenanceText, "Suggested next dose"),
      "OpenReef should not invent exact calcium mL without verified product strength.",
    ));
  }
  if (scenario.id === "missing-tank-volume") {
    expectations.push(expectation(
      "Missing tank volume locks exact advice",
      textIncludes(text, "Enter real net tank water volume") || textIncludes(text, "Enter net tank volume"),
      "Exact custom-strength calculations need real system volume.",
    ));
  }
  if (scenario.id === "stale-manual-tests") {
    expectations.push(expectation(
      "Stale manual tests lock action",
      textIncludes(text, "Retest") || textIncludes(text, "last logged"),
      "Old manual results should not produce actionable DIY dose changes.",
    ));
  }
  if (scenario.id === "above-target") {
    expectations.push(expectation(
      "Above-target chemistry avoids downward correction",
      textIncludes(text, "Do not chemically correct downward") || textIncludes(text, "chemical correction downward"),
      "OpenReef should not recommend chemical correction downward.",
    ));
  }
  return expectations;
}

export const CUSTOM_DIY_SCENARIOS = [
  {
    id: "stable-verified-three-part",
    title: "Stable verified DIY three-part",
    expected: "Keep all parts steady; no exact correction pressure.",
    alkDoseMlPerDay: 36,
    caDoseMlPerDay: 36,
    mgDoseMlPerDay: 4,
    alkStart: 8.31,
    alkDrift: -0.001,
    caStart: 431,
    caDrift: -0.03,
    mgStart: 1352,
    mgDrift: -0.04,
  },
  {
    id: "alkalinity-demand",
    title: "Alkalinity demand rising",
    expected: "Use the verified alkalinity strength to suggest a small Part 2 review increase.",
    alkDoseMlPerDay: 32,
    caDoseMlPerDay: 36,
    mgDoseMlPerDay: 4,
    alkStart: 8.52,
    alkDrift: -0.012,
    caStart: 431,
    caDrift: -0.02,
    mgStart: 1350,
    mgDrift: -0.03,
  },
  {
    id: "implausibly-weak-alkalinity-strength",
    title: "Implausibly weak alkalinity strength",
    expected: "Lock exact mL advice and ask the user to verify the custom recipe/strength fields.",
    alkDoseMlPerDay: 300,
    caDoseMlPerDay: 36,
    mgDoseMlPerDay: 4,
    alkStart: 8.52,
    alkDrift: -0.012,
    caStart: 431,
    caDrift: -0.02,
    mgStart: 1350,
    mgDrift: -0.03,
    strengthOverrides: {
      alkalinity: { productDoseMl: 1, productVolumeLitres: 1, productRaise: 0.02 },
    },
  },
  {
    id: "calcium-demand",
    title: "Calcium demand rising",
    expected: "Use the verified calcium strength to suggest a Part 1 review increase.",
    alkDoseMlPerDay: 36,
    caDoseMlPerDay: 32,
    mgDoseMlPerDay: 4,
    alkStart: 8.31,
    alkDrift: -0.001,
    caStart: 444,
    caDrift: -0.34,
    mgStart: 1350,
    mgDrift: -0.03,
  },
  {
    id: "magnesium-demand",
    title: "Magnesium demand rising",
    expected: "Use the verified magnesium strength to suggest a separate Part 3 review increase.",
    alkDoseMlPerDay: 36,
    caDoseMlPerDay: 36,
    mgDoseMlPerDay: 3,
    alkStart: 8.32,
    alkDrift: -0.001,
    caStart: 431,
    caDrift: -0.03,
    mgStart: 1395,
    mgDrift: -1.1,
  },
  {
    id: "balanced-three-part-demand",
    title: "All three verified parts falling",
    expected: "Give independent exact advice for alkalinity, calcium, and magnesium.",
    alkDoseMlPerDay: 32,
    caDoseMlPerDay: 32,
    mgDoseMlPerDay: 3,
    alkStart: 8.55,
    alkDrift: -0.012,
    caStart: 444,
    caDrift: -0.34,
    mgStart: 1395,
    mgDrift: -1.1,
  },
  {
    id: "missing-calcium-strength",
    title: "Missing calcium verified strength",
    expected: "Calcium exact advice remains locked while alkalinity/magnesium can still use their verified strengths.",
    alkDoseMlPerDay: 36,
    caDoseMlPerDay: 32,
    mgDoseMlPerDay: 4,
    alkStart: 8.31,
    alkDrift: -0.001,
    caStart: 444,
    caDrift: -0.34,
    mgStart: 1350,
    mgDrift: -0.03,
    missingStrengthFor: "calcium",
  },
  {
    id: "missing-tank-volume",
    title: "Missing net tank volume",
    expected: "Exact calculations are locked because the verified instruction cannot be scaled.",
    tankVolumeLitres: 0,
    alkDoseMlPerDay: 32,
    caDoseMlPerDay: 32,
    mgDoseMlPerDay: 3,
    alkStart: 8.52,
    alkDrift: -0.012,
    caStart: 444,
    caDrift: -0.34,
    mgStart: 1395,
    mgDrift: -1.1,
  },
  {
    id: "stale-manual-tests",
    title: "Stale manual tests",
    expected: "Lock exact advice until fresh tests are logged.",
    alkDoseMlPerDay: 36,
    caDoseMlPerDay: 36,
    mgDoseMlPerDay: 4,
    alkStart: 8.52,
    alkDrift: -0.012,
    caStart: 444,
    caDrift: -0.34,
    mgStart: 1395,
    mgDrift: -1.1,
    latestAgeDays: 30,
    stale: true,
  },
  {
    id: "above-target",
    title: "Above-target chemistry",
    expected: "Do not advise chemical correction downward; review holding/reducing daily doses only.",
    alkDoseMlPerDay: 42,
    caDoseMlPerDay: 42,
    mgDoseMlPerDay: 8,
    alkStart: 8.8,
    alkDrift: 0.005,
    caStart: 450,
    caDrift: 0.12,
    mgStart: 1375,
    mgDrift: 0.25,
  },
];

function scenarioReport(scenario, result, manualReadings, liveContext) {
  const expectations = scenarioExpectations(scenario, result);
  const failures = expectations.filter((item) => !item.passed);
  const rows = Object.entries(result.items).map(([id, item]) => [
    id,
    item.recommendationState,
    item.status,
    item.potencyInfo?.source || "",
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
    "| Parameter | State | Status | Strength | Maintenance | Correction | Safety |",
    "|---|---|---|---|---|---|---|",
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

export function runCustomVerifiedDiyThreePartEval({ createPanel }) {
  const scenarioReports = CUSTOM_DIY_SCENARIOS.map((scenario) => {
    const panel = createPanel();
    const { manualReadings, liveContext } = buildPanelState(panel, scenario);
    const result = analysePanel(panel);
    return scenarioReport(scenario, result, manualReadings, liveContext);
  });
  return [
    "# Custom Verified-Strength / DIY Three-Part Eval",
    "",
    `Fixed eval clock: ${new Date(FIXED_NOW).toISOString()}`,
    "Tank: 200 L mixed reef unless the scenario deliberately omits volume.",
    "Targets: alkalinity 8.3 dKH, calcium 430 ppm, magnesium 1350 ppm.",
    "Primary source for dosing advice: simulated manual alkalinity/calcium/magnesium history.",
    "Live context: simulated pH, display temperature, and salinity history.",
    "",
    "Source anchors checked:",
    "- BRS Pharma 2-Part / DIY recipe guidance: recipe strength depends on the actual mix; verify the instruction strength before exact dosing.",
    "- Randy Holmes-Farley two/three-part recipe context: DIY calcium, alkalinity, and magnesium stock strengths are recipe-specific and should be dosed as separate parts.",
    "",
    "DIY verified-strength model inputs tested: net tank volume, separate current daily doses, user-entered '1 mL raises X in Y litres' instructions, target values, and manual-test freshness.",
    "Example verified strengths used in the eval: alkalinity 1 mL / 100 L raises 0.053 dKH; calcium 1 mL / 100 L raises 0.37 ppm; magnesium 1 mL / 100 L raises 0.47 ppm.",
    "",
    ...scenarioReports,
  ].join("\n");
}
