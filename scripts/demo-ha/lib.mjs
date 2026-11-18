// Shared helpers for the demo scripts. Every HTTP/WebSocket call goes through demoBase(),
// which REFUSES any target that is not 127.0.0.1:<the demo port> (8300-8399). The only Home
// Assistant these scripts may talk to is the disposable demo one.
export const DEMO_USER = "demo";
export const DEMO_PASS = "demo-reef-only";

export function demoBase() {
  const port = Number(process.env.DEMO_PORT);
  if (!Number.isInteger(port) || port < 8300 || port > 8399) {
    throw new Error(`refusing: DEMO_PORT must be 8300-8399 (got ${process.env.DEMO_PORT})`);
  }
  const base = process.env.DEMO_URL || `http://127.0.0.1:${port}`;
  const u = new URL(base);
  if (u.protocol !== "http:" || u.hostname !== "127.0.0.1" || Number(u.port) !== port) {
    throw new Error(`refusing: target must be http://127.0.0.1:${port}, got ${base}`);
  }
  return { base: `http://127.0.0.1:${port}`, port, clientId: `http://127.0.0.1:${port}/` };
}

export async function api(path, { method = "GET", body, token, form } = {}) {
  const { base } = demoBase();
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload;
  if (form) { headers["Content-Type"] = "application/x-www-form-urlencoded"; payload = new URLSearchParams(form).toString(); }
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  const res = await fetch(base + path, { method, headers, body: payload });
  const text = await res.text();
  let json; try { json = JSON.parse(text); } catch { json = text; }
  return { status: res.status, json };
}

export async function waitForHA(timeoutMs = 240_000) {
  const t0 = Date.now();
  for (;;) {
    try { const r = await api("/api/onboarding"); if (r.status === 200 || r.status === 404) return r; } catch { /* not up yet */ }
    if (Date.now() - t0 > timeoutMs) throw new Error("Home Assistant did not become ready");
    await new Promise((r) => setTimeout(r, 2000));
  }
}

// Log in with the fixed demo user through the real login flow; returns the token response.
export async function login() {
  const { clientId } = demoBase();
  const redirect_uri = clientId;
  const f = await api("/auth/login_flow", { method: "POST", body: { client_id: clientId, handler: ["homeassistant", null], redirect_uri } });
  if (f.status !== 200) throw new Error(`login_flow ${f.status}`);
  const s = await api(`/auth/login_flow/${f.json.flow_id}`, { method: "POST", body: { client_id: clientId, username: DEMO_USER, password: DEMO_PASS } });
  if (s.json.type !== "create_entry") throw new Error("demo login failed");
  const t = await api("/auth/token", { method: "POST", form: { grant_type: "authorization_code", code: s.json.result, client_id: clientId } });
  if (t.status !== 200) throw new Error(`token ${t.status}`);
  return t.json;
}

export function wsCall(accessToken, messages) {
  const { port } = demoBase();
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(`ws://127.0.0.1:${port}/api/websocket`);
    const results = []; let i = 0;
    const timer = setTimeout(() => { ws.close(); reject(new Error("websocket timeout")); }, 60_000);
    const sendNext = () => { if (i < messages.length) ws.send(JSON.stringify({ id: i + 1, ...messages[i] })); else { clearTimeout(timer); ws.close(); resolve(results); } };
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.type === "auth_required") ws.send(JSON.stringify({ type: "auth", access_token: accessToken }));
      else if (m.type === "auth_ok") sendNext();
      else if (m.type === "auth_invalid") { clearTimeout(timer); reject(new Error("ws auth invalid")); }
      else if (m.type === "result") { results.push(m); i++; sendNext(); }
    };
    ws.onerror = (e) => { clearTimeout(timer); reject(new Error("websocket error")); };
  });
}
