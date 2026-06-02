#!/usr/bin/env node

import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadOpenReefPanel } from "./panel-loader.mjs";
import { runKalkwasserDosingPumpEval } from "./scenarios/kalkwasser-dosing-pump.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");

const scenarios = {
  "kalkwasser-dosing-pump": runKalkwasserDosingPumpEval,
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
