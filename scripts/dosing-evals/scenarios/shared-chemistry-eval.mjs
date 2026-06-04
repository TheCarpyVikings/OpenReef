import {
  EVAL_DAYS,
  FIXED_NOW,
  compactText,
  makeLiveSeries,
  makeManualSeries,
  round,
  stateFromSeries,
  withFixedNow,
} from "../sim-utils.mjs";

export const CHEMISTRY_TARGETS = {
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

export function reefSensorConfig({ mappedChemistry = false } = {}) {
  return Object.fromEntries(Object.entries(SENSOR_META).map(([id, [label, unit, min, max, entityId, group]]) => {
    const mappedEntity = mappedChemistry && ["alkalinity", "calcium", "magnesium"].includes(id)
      ? `sensor.apex_${id}`
      : entityId;
    return [id, {
      label,
      unit,
      min,
      max,
      group,
      enabled: true,
      entity_id: mappedEntity,
      alertsEnabled: true,
      warningBuffer: 10,
    }];
  }));
}

export function chemistrySchedules({ stale = false } = {}) {
  const ageMultiplier = stale ? 1 : 2;
  return {
    alkalinity: { enabled: true, cadenceDays: 4, criticalAfterDays: 8 * ageMultiplier, preferredSource: "Hanna" },
    calcium: { enabled: true, cadenceDays: 7, criticalAfterDays: 14 * ageMultiplier, preferredSource: "Salifert" },
    magnesium: { enabled: true, cadenceDays: 14, criticalAfterDays: 28 * ageMultiplier, preferredSource: "Salifert" },
  };
}

export function buildChemistryManualReadings(scenario) {
  return {
    alkalinity: makeManualSeries({
      parameter: "alkalinity",
      unit: "dKH",
      startValue: scenario.alkStart,
      dailyDrift: scenario.alkDrift,
      noise: scenario.alkNoise ?? 0.04,
      intervalDays: scenario.manualIntervalDays ?? 4,
      latestAgeDays: scenario.latestAgeDays ?? 1,
      source: scenario.alkSource ?? "Hanna",
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
      source: scenario.caSource ?? "Salifert",
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
      source: scenario.mgSource ?? "Salifert",
      seed: scenario.id,
    }),
  };
}

function makeChemistryLiveSeries({
  entityId,
  unit,
  startValue,
  dailyDrift = 0,
  noise = 0,
  intervalHours = 12,
  seed = entityId,
  digits = 1,
}) {
  const points = makeLiveSeries({
    entityId,
    unit,
    startValue,
    dailyDrift,
    noise,
    intervalHours,
    seed,
  });
  return points.map((point) => ({ ...point, value: round(point.value, digits) }));
}

export function buildLiveContext(scenario, { mappedChemistry = false } = {}) {
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
    dailyDrift: scenario.tempDrift ?? 0,
    noise: scenario.tempNoise ?? 0.25,
    intervalHours: 6,
    seed: `${scenario.id}:temp`,
  });
  const salinity = makeLiveSeries({
    entityId: "sensor.sim_salinity",
    unit: "ppt",
    startValue: scenario.salinityStart ?? 35,
    dailyDrift: scenario.salinityDrift ?? 0,
    noise: scenario.salinityNoise ?? 0.12,
    intervalHours: 12,
    seed: `${scenario.id}:salinity`,
  });
  const liveContext = { ph, temp, salinity };
  if (mappedChemistry) {
    liveContext.alkalinity = makeChemistryLiveSeries({
      entityId: "sensor.apex_alkalinity",
      unit: "dKH",
      startValue: scenario.alkStart,
      dailyDrift: scenario.alkDrift,
      noise: scenario.alkNoise ?? 0.03,
      intervalHours: scenario.chemistryIntervalHours ?? 24,
      seed: `${scenario.id}:apex-alk`,
      digits: 2,
    });
    liveContext.calcium = makeChemistryLiveSeries({
      entityId: "sensor.apex_calcium",
      unit: "ppm",
      startValue: scenario.caStart,
      dailyDrift: scenario.caDrift,
      noise: scenario.caNoise ?? 3,
      intervalHours: scenario.chemistryIntervalHours ?? 24,
      seed: `${scenario.id}:apex-ca`,
      digits: 0,
    });
    liveContext.magnesium = makeChemistryLiveSeries({
      entityId: "sensor.apex_magnesium",
      unit: "ppm",
      startValue: scenario.mgStart,
      dailyDrift: scenario.mgDrift,
      noise: scenario.mgNoise ?? 8,
      intervalHours: scenario.chemistryIntervalHours ?? 24,
      seed: `${scenario.id}:apex-mg`,
      digits: 0,
    });
  }
  return liveContext;
}

export function buildHassStates(liveContext) {
  const states = {
    "sensor.sim_ph": stateFromSeries(liveContext.ph, "Simulated pH"),
    "sensor.sim_display_temp": stateFromSeries(liveContext.temp, "Simulated Display Temperature"),
    "sensor.sim_salinity": stateFromSeries(liveContext.salinity, "Simulated Salinity"),
  };
  if (liveContext.alkalinity) states["sensor.apex_alkalinity"] = stateFromSeries(liveContext.alkalinity, "Apex Alkalinity");
  if (liveContext.calcium) states["sensor.apex_calcium"] = stateFromSeries(liveContext.calcium, "Apex Calcium");
  if (liveContext.magnesium) states["sensor.apex_magnesium"] = stateFromSeries(liveContext.magnesium, "Apex Magnesium");
  return states;
}

export function analyseDosingPanel(panel, { liveContext = {}, source = "manual" } = {}) {
  return withFixedNow(() => {
    const items = {};
    panel._dosingActiveParameters().forEach(([id, sensor]) => {
      const trendData = source === "mapped-history" && liveContext[id]
        ? { source: "history", range: "7d", points: liveContext[id] }
        : panel._manualTrendData(id);
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

export function allAdvice(result) {
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

export function countReadings(readings) {
  return Object.values(readings || {}).reduce((total, rows) => total + rows.length, 0);
}

export function livePointCount(liveContext) {
  return Object.values(liveContext || {}).reduce((total, rows) => total + rows.length, 0);
}

export function scenarioReport({ scenario, result, manualReadings, liveContext, expectations }) {
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
    `Live context: ${livePointCount(liveContext)} points across ${EVAL_DAYS} days.`,
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
