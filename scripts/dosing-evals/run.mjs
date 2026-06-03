#!/usr/bin/env node

import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadOpenReefPanel } from "./panel-loader.mjs";
import { runAllForReefMaintenanceEval } from "./scenarios/all-for-reef-maintenance.mjs";
import { runKalkwasserDosingPumpEval } from "./scenarios/kalkwasser-dosing-pump.mjs";
import { runSeachemReefFusionEval } from "./scenarios/seachem-reef-fusion.mjs";
import { runCustomVerifiedDiyThreePartEval } from "./scenarios/custom-verified-diy-three-part.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");

const scenarios = {
  "all-for-reef-maintenance": runAllForReefMaintenanceEval,
  "custom-verified-diy-three-part": runCustomVerifiedDiyThreePartEval,
  "kalkwasser-dosing-pump": runKalkwasserDosingPumpEval,
  "seachem-reef-fusion": runSeachemReefFusionEval,
};

const scenarioId = process.argv[2] || "kalkwasser-dosing-pump";
const runner = scenarios[scenarioId];

if (!runner) {
  console.error(`Unknown dosing eval: ${scenarioId}`);
  console.error(`Available evals: ${Object.keys(scenarios).join(", ")}`);
  process.exit(1);
}

const report = runner({
  createPanel: () => loadOpenReefPanel(repoRoot),
});

console.log(report);
