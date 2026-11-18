#!/usr/bin/env node
// Seed the demo HA: onboarding user (first run), OpenReef config entry, entity mapping.
// Idempotent. Only ever talks to 127.0.0.1:$DEMO_PORT (see lib.mjs).
import { api, waitForHA, login, wsCall, demoBase, DEMO_USER, DEMO_PASS } from "./lib.mjs";

const { clientId } = demoBase();
const ob = await waitForHA();
if (ob.status === 200 && Array.isArray(ob.json) && ob.json.some((s) => s.step === "user" && !s.done)) {
  console.log("onboarding: creating demo user");
  const u = await api("/api/onboarding/users", { method: "POST", body: { client_id: clientId, name: "Demo User", username: DEMO_USER, password: DEMO_PASS, language: "en" } });
  if (u.status !== 200) throw new Error(`onboarding user ${u.status}`);
  const t = await api("/auth/token", { method: "POST", form: { grant_type: "authorization_code", code: u.json.auth_code, client_id: clientId } });
  const token = t.json.access_token;
  await api("/api/onboarding/core_config", { method: "POST", token, body: {} });
  await api("/api/onboarding/analytics", { method: "POST", token, body: {} });
  await api("/api/onboarding/integration", { method: "POST", token, body: { client_id: clientId, redirect_uri: clientId } });
}

const tok = (await login()).access_token;

// Onboarding auto-adds cloud-flavoured integrations (weather, radio, translate...). Drop them: the demo
// has no internet, and they only log errors. OpenReef is the only entry we keep.
const entries = await api("/api/config/config_entries/entry", { token: tok });
for (const e of entries.json) {
  if (["met", "radio_browser", "google_translate", "shopping_list", "analytics", "backup"].includes(e.domain)) {
    await api(`/api/config/config_entries/entry/${e.entry_id}`, { method: "DELETE", token: tok });
  }
}

// Config entry through the real config flow (single instance: an abort means it already exists).
const flow = await api("/api/config/config_entries/flow", { method: "POST", token: tok, body: { handler: "openreef", show_advanced_options: false } });
if (flow.json.type === "form") {
  const done = await api(`/api/config/config_entries/flow/${flow.json.flow_id}`, { method: "POST", token: tok, body: { tank_name: "Demo Reef", user_name: "Demo User" } });
  if (done.json.type !== "create_entry") throw new Error("config flow did not create an entry: " + JSON.stringify(done.json).slice(0, 300));
  console.log("config flow: OpenReef entry created");
} else console.log("config flow:", flow.json.reason || flow.json.type, "(already set up)");

// Map the fake entities. save_config is a panel websocket command, not a service call.
const [cur] = await wsCall(tok, [{ type: "openreef/get_config" }]);
if (!cur.success) throw new Error("get_config failed: " + JSON.stringify(cur.error));
const cfg = cur.result.config;
cfg.tank.name = "Demo Reef"; cfg.tank.owner = "Demo User"; cfg.tank.volumeLitres = 300;
cfg.display.setupComplete = true;
const sensors = { temp: "demo_tank_temperature", sump_temp: "demo_sump_temperature", ph: "demo_tank_ph", salinity: "demo_tank_salinity",
  alkalinity: "demo_tank_alkalinity", calcium: "demo_tank_calcium", magnesium: "demo_tank_magnesium", nitrate: "demo_tank_nitrate",
  phosphate: "demo_tank_phosphate", orp: "demo_tank_orp" };
for (const [id, ent] of Object.entries(sensors)) { cfg.sensors[id].entity_id = `sensor.${ent}`; cfg.sensors[id].enabled = true; }
const equip = { return_pump: ["Demo return pump", "return_pump", "demo_return_pump"], heater: ["Demo heater", "heater", "demo_heater"],
  skimmer: ["Demo skimmer", "skimmer", "demo_skimmer"], wavemaker: ["Demo wavemaker", "display_wavemaker", "demo_wavemaker"],
  ato: ["Demo ATO", "ato", "demo_ato"], light: ["Demo light", "lighting", "demo_light"] };
const hasPower = new Set(["demo_return_pump", "demo_heater", "demo_skimmer", "demo_wavemaker"]);
cfg.equipment = {};
for (const [id, [label, type, base]] of Object.entries(equip)) {
  cfg.equipment[id] = { label, type, switch_entity_id: `switch.${base}`, power_entity_id: hasPower.has(base) ? `sensor.${base}_power` : "",
    energy_entity_id: "", cost_entity_id: "", armed: true };
}
const [saved] = await wsCall(tok, [{ type: "openreef/save_config", config: cfg }]);
if (!saved.success) throw new Error("save_config failed: " + JSON.stringify(saved.error));
console.log("seeded: sensors + equipment mapped");
