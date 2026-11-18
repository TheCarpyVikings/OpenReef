/** Security boundaries exercised with actual renderers and synthetic data only. */
import { assert, assertEqual, makePanel, runTests, test } from './_panel_harness.mjs';

test('hatchery reminder names from imported configuration cannot create HTML', async () => {
  const name = '<svg onload=window.auditPass=1>';
  const panel = await makePanel({ maintenance: { tasks: { start_v1: {} } } });
  Object.assign(panel, {
    _nps: { summary: { hatchery: {} } }, _npsLoadSummary() {}, _npsEggTypes: () => [],
    _missionSummaryCard: () => '',
    _npsVesselEntries: () => [['v1', { name }], ['v2', { name: 'Second vessel' }]],
    _npsHatchTaskIds: (id) => [`start_${id}`, `harvest_${id}`],
    _maintenanceDueState: () => ({ status: 'ok', label: 'done' }),
    _hatcheryPanel: () => '', _hatcheryRigPanel: () => '',
    _feedingDetails: (_id, _label, content) => content,
  });
  const html = panel._hatcheryTab();
  assert(name.length <= 40, 'payload fits the server-side name limit');
  assert(!html.includes(name), 'no executable SVG from the vessel name');
  assert(html.includes('&lt;svg onload=window.auditPass=1&gt;'), 'the name is displayed as text');
});

function element(attributes) {
  const attrs = { ...attributes };
  return { getAttribute: (name) => attrs[name] || null, setAttribute: (name, value) => { attrs[name] = value; }, attrs };
}
function signed(path, suffix = 'test') { return `/openreef_captures/${path}?authSig=${suffix}`; }
function reply(paths, suffix = 'test') {
  return { urls: Object.fromEntries(paths.map((path) => [path, signed(path, suffix)])), expiresAt: new Date(Date.now() + 600000).toISOString() };
}

test('private media signs through authenticated WS and patches media without rerendering', async () => {
  const config = { captures: [{ thumbnail: 'camera.jpg' }], livestock: { corals: { a: { photoUrl: '/openreef_captures/corals/a.jpg' } } } };
  const before = JSON.stringify(config);
  const panel = await makePanel(config);
  const calls = [];
  panel._callWS = async (message) => { calls.push(message); return reply(message.paths); };
  panel._render = () => { throw new Error('signing must not replace a playing video or edited form'); };
  const placeholder = panel._captureUrl('camera.jpg');
  assert(placeholder.startsWith('data:image/'), 'no unsigned request while authentication is pending');
  const src = element({ src: placeholder });
  const poster = element({ poster: placeholder });
  const link = element({ href: placeholder });
  panel.shadowRoot = { querySelectorAll: () => [src, poster, link] };
  assert(panel._photoUrl(config.livestock.corals.a.photoUrl).startsWith('data:image/'));
  await panel._captureSigning;
  assertEqual(calls.length, 1, 'one batched signing request');
  assertEqual(calls[0].type, 'openreef/sign_capture_urls');
  assertEqual(calls[0].paths, ['camera.jpg', 'corals/a.jpg']);
  assertEqual(src.attrs.src, signed('camera.jpg'));
  assertEqual(poster.attrs.poster, signed('camera.jpg'));
  assertEqual(link.attrs.href, signed('camera.jpg'));
  assertEqual(panel._captureUrl('camera.jpg'), signed('camera.jpg'));
  assertEqual(JSON.stringify(config), before, 'signed URLs are never persisted into tank configuration');
});

test('capture path validation rejects traversal, arbitrary origins and query injection', async () => {
  const panel = await makePanel({});
  panel._callWS = () => { throw new Error('unsafe paths must not be sent for signing'); };
  for (const path of ['../secret', '/etc/passwd', 'feeds/../secret', 'feeds//frame.jpg',
    'https://attacker.invalid/a.jpg', 'a.jpg?x=1', 'a%2f..%2fsecret', 'a\\b.jpg']) {
    assertEqual(panel._captureUrl(path), '', path);
  }
  assertEqual(panel._photoUrl('javascript:alert(1)'), '');
  assertEqual(panel._photoUrl('//attacker.invalid/a.jpg'), '');
  assertEqual(panel._photoUrl('https://photos.example/a.jpg'), 'https://photos.example/a.jpg');
  assertEqual(panel._photoUrl('/local/corals/a.jpg'), '/local/corals/a.jpg');
});

test('expired signatures refresh; a missing or denied signature never exposes a public URL', async () => {
  const panel = await makePanel({});
  panel._callWS = async ({ paths }) => reply(paths, 'first');
  const placeholder = panel._captureUrl('camera.jpg');
  await panel._captureSigning;
  panel._captureUrls.get('camera.jpg').expires = Date.now() + 1000;
  const node = element({ src: signed('camera.jpg', 'first') });
  panel.shadowRoot = { querySelectorAll: () => [node] };
  panel._callWS = async ({ paths }) => reply(paths, 'renewed');
  panel._patchCaptureUrls(true);
  await panel._captureSigning;
  assertEqual(node.attrs.src, signed('camera.jpg', 'renewed'));
  panel._callWS = async () => { throw new Error('unauthorized'); };
  assert(panel._captureUrl('private.jpg').startsWith('data:image/'));
  await panel._captureSigning;
  assert(panel._captureUrl('private.jpg').startsWith('data:image/'));
  assert(!placeholder.startsWith('/openreef_captures/'));
});

test('signing replies cannot replace media with another origin or a different file', async () => {
  const panel = await makePanel({});
  panel._callWS = async () => ({ urls: { 'camera.jpg': 'https://attacker.invalid/a.jpg?authSig=x' }, expiresAt: new Date(Date.now() + 600000).toISOString() });
  const placeholder = panel._captureUrl('camera.jpg');
  const node = element({ src: placeholder });
  panel.shadowRoot = { querySelectorAll: () => [node] };
  await panel._captureSigning;
  assertEqual(node.attrs.src, placeholder);
});

test('media signing batches stay within the backend limit', async () => {
  const panel = await makePanel({});
  const sizes = [];
  panel._callWS = async ({ paths }) => { sizes.push(paths.length); return reply(paths); };
  for (let i = 0; i < 121; i++) panel._captureUrl(`timelapse/display/${i}.jpg`);
  await panel._captureSigning;
  assertEqual(sizes, [100, 21]);
});

test('cached media resumes expiry refresh when the panel reconnects', async () => {
  const panel = await makePanel({});
  panel._callWS = async ({ paths }) => reply(paths);
  panel._captureUrl('camera.jpg');
  await panel._captureSigning;
  panel.isConnected = true;
  assertEqual(panel._captureUrl('camera.jpg'), signed('camera.jpg'));
  assert(panel._captureRefreshTimer, 'a cached URL must still restart renewal');
  clearTimeout(panel._captureRefreshTimer);
  panel._captureRefreshTimer = null;
  panel.isConnected = false;
});

await runTests();
