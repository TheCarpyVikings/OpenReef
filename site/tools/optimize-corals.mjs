#!/usr/bin/env node
/**
 * Smithsonian coral pipeline: takes the raw "Low" GLB derivatives downloaded
 * from 3d-api.si.edu and produces web-weight hero models for the dive.
 *
 *   node tools/optimize-corals.mjs <src-dir>
 *
 * Per model: weld → aggressive meshopt simplify → strip normal/occlusion maps
 * (invisible at our viewing distance, half the file size) → resize base colour
 * to 512 webp → meshopt compression. Targets ~150-250 KB per coral.
 */
import { readdirSync } from "node:fs";
import { join } from "node:path";
import { NodeIO } from "@gltf-transform/core";
import {
  EXTMeshoptCompression,
  EXTTextureWebP,
  KHRDracoMeshCompression,
} from "@gltf-transform/extensions";
import { dedup, prune, simplify, textureCompress, weld } from "@gltf-transform/functions";
import { MeshoptDecoder, MeshoptEncoder, MeshoptSimplifier } from "meshoptimizer";
import draco3d from "draco3dgltf";

const srcDir = process.argv[2];
if (!srcDir) {
  console.error("Usage: node tools/optimize-corals.mjs <dir-with-raw-glbs>");
  process.exit(1);
}
const outDir = new URL("../public/corals/", import.meta.url).pathname;

await MeshoptDecoder.ready;
await MeshoptEncoder.ready;
await MeshoptSimplifier.ready;

const io = new NodeIO()
  .registerExtensions([EXTMeshoptCompression, EXTTextureWebP, KHRDracoMeshCompression])
  .registerDependencies({
    "meshopt.decoder": MeshoptDecoder,
    "meshopt.encoder": MeshoptEncoder,
    "draco3d.decoder": await draco3d.createDecoderModule(),
  });

for (const file of readdirSync(srcDir).filter((f) => f.endsWith(".glb") && !f.includes("simp") && f !== "test.glb")) {
  const doc = await io.read(join(srcDir, file));

  // Draco decoded on read; we re-compress with meshopt, so drop the extension.
  for (const ext of doc.getRoot().listExtensionsUsed()) {
    if (ext.extensionName === "KHR_draco_mesh_compression") ext.dispose();
  }

  for (const mat of doc.getRoot().listMaterials()) {
    mat.setNormalTexture(null);
    mat.setOcclusionTexture(null);
    mat.setMetallicRoughnessTexture(null);
  }

  await doc.transform(
    weld(),
    simplify({ simplifier: MeshoptSimplifier, ratio: 0.08, error: 0.03 }),
    prune(),
    dedup(),
    textureCompress({ targetFormat: "webp", resize: [512, 512] })
  );

  doc
    .createExtension(EXTMeshoptCompression)
    .setRequired(true)
    .setEncoderOptions({ method: EXTMeshoptCompression.EncoderMethod.FILTER });

  const out = join(outDir, file);
  await io.write(out, doc);
  const { statSync } = await import("node:fs");
  console.log(`${file}: → ${(statSync(out).size / 1024).toFixed(0)} KB`);
}
