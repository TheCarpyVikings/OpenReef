export const DAY_MS = 86_400_000;
export const FIXED_NOW = Date.parse("2026-06-01T12:00:00Z");
export const EVAL_DAYS = 90;

export function withFixedNow(callback) {
  const originalNow = Date.now;
  Date.now = () => FIXED_NOW;
  try {
    return callback();
  } finally {
    Date.now = originalNow;
  }
}

export function seededRandom(seedText) {
  let seed = 0;
  for (let index = 0; index < seedText.length; index += 1) {
    seed = (seed * 31 + seedText.charCodeAt(index)) >>> 0;
  }
  return function next() {
    seed += 0x6d2b79f5;
    let t = seed;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4_294_967_296;
  };
}

export function round(value, digits = 2) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

export function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

export function isoDaysAgo(ageDays, hour = 19) {
  const date = new Date(FIXED_NOW - ageDays * DAY_MS);
  date.setUTCHours(hour, 30, 0, 0);
  return date.toISOString();
}

export function makeManualSeries({
  parameter,
  unit,
  startValue,
  dailyDrift = 0,
  noise = 0,
  intervalDays = 4,
  latestAgeDays = 1,
  source = "Simulated",
  seed = parameter,
}) {
  const random = seededRandom(`${seed}:${parameter}`);
  const readings = [];
  for (let age = EVAL_DAYS; age >= latestAgeDays; age -= intervalDays) {
    const elapsed = EVAL_DAYS - age;
    const wave = Math.sin(elapsed / 9) * noise * 0.35;
    const jitter = (random() - 0.5) * noise;
    readings.push({
      id: `${parameter}:sim:${age}`,
      timestamp: isoDaysAgo(age),
      value: round(startValue + dailyDrift * elapsed + wave + jitter, parameter === "alkalinity" ? 2 : 0),
      unit,
      source,
      notes: "simulated eval data",
    });
  }
  return readings;
}

export function makeLiveSeries({
  entityId,
  unit,
  startValue,
  dailyDrift = 0,
  noise = 0,
  intervalHours = 6,
  seed = entityId,
}) {
  const random = seededRandom(`${seed}:${entityId}`);
  const points = [];
  const totalHours = EVAL_DAYS * 24;
  for (let hour = totalHours; hour >= 0; hour -= intervalHours) {
    const ageDays = hour / 24;
    const elapsedDays = EVAL_DAYS - ageDays;
    const dayPhase = Math.sin((elapsedDays % 1) * Math.PI * 2);
    const jitter = (random() - 0.5) * noise;
    points.push({
      entity_id: entityId,
      time: FIXED_NOW - hour * 3_600_000,
      value: round(startValue + dailyDrift * elapsedDays + dayPhase * noise * 0.35 + jitter, unit === "pH" ? 2 : 1),
      unit,
    });
  }
  return points;
}

export function stateFromSeries(series, friendlyName) {
  const latest = series[series.length - 1];
  return {
    state: String(latest.value),
    attributes: {
      friendly_name: friendlyName,
      unit_of_measurement: latest.unit,
    },
    last_changed: new Date(latest.time).toISOString(),
    last_updated: new Date(latest.time).toISOString(),
  };
}

export function compactText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

export function expectation(label, passed, detail = "", tweak = "") {
  return { label, passed: Boolean(passed), detail, tweak };
}

export function textIncludes(text, needle) {
  return compactText(text).toLowerCase().includes(String(needle).toLowerCase());
}
