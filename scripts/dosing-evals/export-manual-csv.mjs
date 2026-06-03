#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  ALL_FOR_REEF_SCENARIOS,
  buildAllForReefManualReadings,
} from "./scenarios/all-for-reef-maintenance.mjs";
import {
  REEF_FUSION_SCENARIOS,
  buildReefFusionManualReadings,
} from "./scenarios/seachem-reef-fusion.mjs";
import {
  CUSTOM_DIY_SCENARIOS,
  buildCustomDiyManualReadings,
} from "./scenarios/custom-verified-diy-three-part.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");

const EXPORTS = {
  "all-for-reef-maintenance": {
    directory: "all-for-reef",
    scenarios: ALL_FOR_REEF_SCENARIOS,
    buildReadings: buildAllForReefManualReadings,
  },
  "custom-verified-diy-three-part": {
    directory: "custom-diy-three-part",
    scenarios: CUSTOM_DIY_SCENARIOS,
    buildReadings: buildCustomDiyManualReadings,
  },
  "seachem-reef-fusion": {
    directory: "reef-fusion",
    scenarios: REEF_FUSION_SCENARIOS,
    buildReadings: buildReefFusionManualReadings,
  },
};

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replaceAll("\"", "\"\"")}"` : text;
}

function flattenReadings(scenario, readings) {
  return Object.entries(readings)
    .flatMap(([parameter, rows]) => rows.map((row) => ({
      parameter,
      timestamp: row.timestamp,
      value: row.value,
      unit: row.unit,
      source: row.source,
      notes: `${row.notes || "simulated eval data"}; scenario=${scenario.id}`,
    })))
    .sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp) || a.parameter.localeCompare(b.parameter));
}

function toCsv(rows) {
  const header = ["parameter", "timestamp", "value", "unit", "source", "notes"];
  return [
    header,
    ...rows.map((row) => header.map((field) => row[field])),
  ].map((row) => row.map(csvCell).join(",")).join("\n");
}

function writeScenarioCsv(exportConfig, scenario) {
  const outDir = path.join(repoRoot, "docs/eval-data", exportConfig.directory);
  fs.mkdirSync(outDir, { recursive: true });
  const readings = exportConfig.buildReadings(scenario);
  const rows = flattenReadings(scenario, readings);
  const outPath = path.join(outDir, `${scenario.id}.csv`);
  fs.writeFileSync(outPath, `${toCsv(rows)}\n`, "utf8");
  return { outPath, rows: rows.length };
}

const exportId = process.argv[2] || "seachem-reef-fusion";
const exportConfig = EXPORTS[exportId];

if (!exportConfig) {
  console.error(`Unknown manual CSV export: ${exportId}`);
  console.error(`Available exports: ${Object.keys(EXPORTS).join(", ")}`);
  process.exit(1);
}

const results = exportConfig.scenarios.map((scenario) => writeScenarioCsv(exportConfig, scenario));
results.forEach((result) => {
  console.log(`${path.relative(repoRoot, result.outPath)} (${result.rows} rows)`);
});
