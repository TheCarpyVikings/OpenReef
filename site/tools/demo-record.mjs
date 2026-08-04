#!/usr/bin/env node
/*
 * Record REAL-tank fixtures for the /demo/ Showroom Reef.
 *
 * Connects to a live Home Assistant over websocket, calls the same read-only
 * openreef/* commands the demo replays, snapshots the states of every entity
 * the config references, and writes site/public/demo/fixtures.json with
 * source:"recorded" — a drop-in replacement for the seeded set that
 * site/tools/demo-fixtures.py generates.
 *
 *   HA_URL=http://homeassistant.local:8123 HA_TOKEN=<long-lived token> \
 *     node site/tools/demo-record.mjs
 *
 * READ-ONLY by construction: the command list below contains no write or
 * actuation commands, and nothing here calls services. Review the output
 * before committing — it becomes public data on openreef.co.uk (tank name,
 * sensor values, maintenance history). Timestamps are rebased in the browser,
 * so a recording stays "fresh" forever.
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HA_URL = process.env.HA_URL?.replace(/\/$/, "");
const HA_TOKEN = process.env.HA_TOKEN;
if (!HA_URL || !HA_TOKEN) {
  console.error("Set HA_URL and HA_TOKEN (profile → security → long-lived access token).");
  process.exit(1);
}

const READ_COMMANDS = [
  "openreef/get_config",
  "openreef/awc_summary",
  "openreef/dosing_summary",
  "openreef/icp_dashboard",
  "openreef/lighting_window",
  "openreef/list_reef_presets",
  "openreef/guardian_status",
];

const wsUrl = `${HA_URL.replace(/^http/, "ws")}/api/websocket`;
const socket = new WebSocket(wsUrl);
let nextId = 1;
const pending = new Map();

const send = (msg) =>
  new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, ...msg }));
  });

socket.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.type === "auth_required") {
    socket.send(JSON.stringify({ type: "auth", access_token: HA_TOKEN }));
  } else if (msg.type === "auth_invalid") {
    console.error("HA rejected the token — generate a fresh long-lived token.");
    process.exit(1);
  } else if (msg.type === "auth_ok") {
    record().catch((err) => {
      console.error(err);
      process.exit(1);
    });
  } else if (msg.type === "result") {
    const p = pending.get(msg.id);
    if (!p) return;
    pending.delete(msg.id);
    if (msg.success) p.resolve(msg.result);
    else p.reject(new Error(`${msg.error?.code}: ${msg.error?.message}`));
  }
};
socket.onerror = () => {
  console.error(`Could not reach ${wsUrl}`);
  process.exit(1);
};

/** Every entity id mentioned anywhere in the config — the demo's state set. */
function referencedEntities(node, found = new Set()) {
  if (Array.isArray(node)) node.forEach((n) => referencedEntities(n, found));
  else if (node && typeof node === "object") {
    for (const [key, value] of Object.entries(node)) {
      if (typeof value === "string" && /^(sensor|binary_sensor|switch|light|camera)\./.test(value)) {
        found.add(value);
      } else if (/entity/i.test(key) || typeof value === "object") {
        referencedEntities(value, found);
      }
    }
  }
  return found;
}

async function record() {
  const ws = {};
  for (const type of READ_COMMANDS) {
    try {
      ws[type] = await send({ type });
      console.log(`recorded ${type}`);
    } catch (err) {
      console.warn(`skipped ${type}: ${err.message}`);
    }
  }
  if (!ws["openreef/get_config"]) throw new Error("get_config failed — nothing to build on.");

  const wanted = referencedEntities(ws["openreef/get_config"].config);
  const all = await send({ type: "get_states" });
  const states = {};
  for (const st of all) {
    if (!wanted.has(st.entity_id)) continue;
    states[st.entity_id] = {
      state: st.state,
      attributes: st.attributes,
      last_changed: st.last_changed,
      last_updated: st.last_updated,
    };
  }
  console.log(`captured ${Object.keys(states).length}/${wanted.size} referenced entity states`);

  const out = {
    generatedAt: new Date().toISOString(),
    source: "recorded",
    ws,
    states,
  };
  const root = dirname(dirname(fileURLToPath(import.meta.url)));
  const dest = join(root, "public", "demo", "fixtures.json");
  mkdirSync(dirname(dest), { recursive: true });
  writeFileSync(dest, JSON.stringify(out, null, 1));
  console.log(`wrote ${dest}`);
  console.log("REVIEW BEFORE COMMITTING — this file becomes public on openreef.co.uk.");
  process.exit(0);
}
