#!/usr/bin/env node

import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadOpenReefPanel } from "./panel-loader.mjs";
import { runAllForReefMaintenanceEval } from "./scenarios/all-for-reef-maintenance.mjs";
import { runApexTridentReadOnlyEval } from "./scenarios/apex-trident-read-only.mjs";
import { runAquaforestComponentEval } from "./scenarios/aquaforest-component-123.mjs";
import { runEsvBionicEval } from "./scenarios/esv-b-ionic.mjs";
import { runHybridKalkPlusPrimaryEval } from "./scenarios/hybrid-kalk-plus-primary.mjs";
import { runKalkwasserDosingPumpEval } from "./scenarios/kalkwasser-dosing-pump.mjs";
import { runSeachemReefFusionEval } from "./scenarios/seachem-reef-fusion.mjs";
import { runCustomVerifiedDiyThreePartEval } from "./scenarios/custom-verified-diy-three-part.mjs";
import {
  runAtiEssentialsEval,
  runBrightwellKalkPlusEval,
  runBrightwellReefCodeEval,
  runCalciumReactorEval,
  runDosingUiSmokeEval,
  runFaunaMarinBallingLightEval,
  runRedSeaCompleteReefCareEval,
  runRedSeaSevenPartEval,
  runTritonCore7FlexEval,
  runTropicMarinBallingEval,
} from "./scenarios/remaining-product-systems.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");

const scenarios = {
  "all-for-reef-maintenance": runAllForReefMaintenanceEval,
  "apex-trident-read-only": runApexTridentReadOnlyEval,
  "aquaforest-component-123": runAquaforestComponentEval,
  "ati-essentials": runAtiEssentialsEval,
  "brightwell-kalk-plus-2": runBrightwellKalkPlusEval,
  "brightwell-reef-code": runBrightwellReefCodeEval,
  "calcium-reactor-advisor": runCalciumReactorEval,
  "custom-verified-diy-three-part": runCustomVerifiedDiyThreePartEval,
  "dosing-ui-smoke": runDosingUiSmokeEval,
  "esv-b-ionic": runEsvBionicEval,
  "fauna-marin-balling-light": runFaunaMarinBallingLightEval,
  "hybrid-kalk-plus-primary": runHybridKalkPlusPrimaryEval,
  "kalkwasser-dosing-pump": runKalkwasserDosingPumpEval,
  "red-sea-complete-reef-care": runRedSeaCompleteReefCareEval,
  "red-sea-seven-part": runRedSeaSevenPartEval,
  "seachem-reef-fusion": runSeachemReefFusionEval,
  "triton-core7-flex": runTritonCore7FlexEval,
  "tropic-marin-original-balling": runTropicMarinBallingEval,
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
