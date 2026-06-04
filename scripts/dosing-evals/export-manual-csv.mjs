#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  ALL_FOR_REEF_SCENARIOS,
  buildAllForReefManualReadings,
} from "./scenarios/all-for-reef-maintenance.mjs";
import {
  AQUAFOREST_COMPONENT_SCENARIOS,
  buildAquaforestManualReadings,
} from "./scenarios/aquaforest-component-123.mjs";
import {
  ESV_B_IONIC_SCENARIOS,
  buildEsvBionicManualReadings,
} from "./scenarios/esv-b-ionic.mjs";
import {
  HYBRID_KALK_PLUS_PRIMARY_SCENARIOS,
  buildHybridKalkManualReadings,
} from "./scenarios/hybrid-kalk-plus-primary.mjs";
import {
  REEF_FUSION_SCENARIOS,
  buildReefFusionManualReadings,
} from "./scenarios/seachem-reef-fusion.mjs";
import {
  CUSTOM_DIY_SCENARIOS,
  buildCustomDiyManualReadings,
} from "./scenarios/custom-verified-diy-three-part.mjs";
import {
  ATI_ESSENTIALS_SCENARIOS,
  BRIGHTWELL_KALK_PLUS_SCENARIOS,
  BRIGHTWELL_REEF_CODE_SCENARIOS,
  CALCIUM_REACTOR_SCENARIOS,
  FAUNA_MARIN_BALLING_LIGHT_SCENARIOS,
  RED_SEA_COMPLETE_REEF_CARE_SCENARIOS,
  RED_SEA_SEVEN_PART_SCENARIOS,
  TRITON_CORE7_FLEX_SCENARIOS,
  TROPIC_MARIN_BALLING_SCENARIOS,
  buildAtiEssentialsManualReadings,
  buildBrightwellKalkPlusManualReadings,
  buildBrightwellReefCodeManualReadings,
  buildCalciumReactorManualReadings,
  buildFaunaMarinBallingManualReadings,
  buildRedSeaCompleteManualReadings,
  buildRedSeaSevenPartManualReadings,
  buildTritonCore7ManualReadings,
  buildTropicMarinBallingManualReadings,
} from "./scenarios/remaining-product-systems.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");

const EXPORTS = {
  "all-for-reef-maintenance": {
    directory: "all-for-reef",
    scenarios: ALL_FOR_REEF_SCENARIOS,
    buildReadings: buildAllForReefManualReadings,
  },
  "aquaforest-component-123": {
    directory: "aquaforest-component-123",
    scenarios: AQUAFOREST_COMPONENT_SCENARIOS,
    buildReadings: buildAquaforestManualReadings,
  },
  "ati-essentials": {
    directory: "ati-essentials",
    scenarios: ATI_ESSENTIALS_SCENARIOS,
    buildReadings: buildAtiEssentialsManualReadings,
  },
  "brightwell-kalk-plus-2": {
    directory: "brightwell-kalk-plus-2",
    scenarios: BRIGHTWELL_KALK_PLUS_SCENARIOS,
    buildReadings: buildBrightwellKalkPlusManualReadings,
  },
  "brightwell-reef-code": {
    directory: "brightwell-reef-code",
    scenarios: BRIGHTWELL_REEF_CODE_SCENARIOS,
    buildReadings: buildBrightwellReefCodeManualReadings,
  },
  "calcium-reactor-advisor": {
    directory: "calcium-reactor-advisor",
    scenarios: CALCIUM_REACTOR_SCENARIOS,
    buildReadings: buildCalciumReactorManualReadings,
  },
  "custom-verified-diy-three-part": {
    directory: "custom-diy-three-part",
    scenarios: CUSTOM_DIY_SCENARIOS,
    buildReadings: buildCustomDiyManualReadings,
  },
  "esv-b-ionic": {
    directory: "esv-b-ionic",
    scenarios: ESV_B_IONIC_SCENARIOS,
    buildReadings: buildEsvBionicManualReadings,
  },
  "fauna-marin-balling-light": {
    directory: "fauna-marin-balling-light",
    scenarios: FAUNA_MARIN_BALLING_LIGHT_SCENARIOS,
    buildReadings: buildFaunaMarinBallingManualReadings,
  },
  "hybrid-kalk-plus-primary": {
    directory: "hybrid-kalk-plus-primary",
    scenarios: HYBRID_KALK_PLUS_PRIMARY_SCENARIOS,
    buildReadings: buildHybridKalkManualReadings,
  },
  "red-sea-complete-reef-care": {
    directory: "red-sea-complete-reef-care",
    scenarios: RED_SEA_COMPLETE_REEF_CARE_SCENARIOS,
    buildReadings: buildRedSeaCompleteManualReadings,
  },
  "red-sea-seven-part": {
    directory: "red-sea-seven-part",
    scenarios: RED_SEA_SEVEN_PART_SCENARIOS,
    buildReadings: buildRedSeaSevenPartManualReadings,
  },
  "seachem-reef-fusion": {
    directory: "reef-fusion",
    scenarios: REEF_FUSION_SCENARIOS,
    buildReadings: buildReefFusionManualReadings,
  },
  "triton-core7-flex": {
    directory: "triton-core7-flex",
    scenarios: TRITON_CORE7_FLEX_SCENARIOS,
    buildReadings: buildTritonCore7ManualReadings,
  },
  "tropic-marin-original-balling": {
    directory: "tropic-marin-original-balling",
    scenarios: TROPIC_MARIN_BALLING_SCENARIOS,
    buildReadings: buildTropicMarinBallingManualReadings,
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
