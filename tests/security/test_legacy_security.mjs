/** Actual TS handlers with synthetic config and mocked HA/network. No .env or server. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const root = new URL('../../', import.meta.url);
const env = { API_SECRET: 'synthetic-security-test-secret-never-a-real-credential', NODE_ENV: 'production' };
const response = {
    json: (data, options = {}) => {
        const value = { data, status: options.status || 200, headers: new Headers(), cookieValues: {} };
        value.cookies = { set: (key, val, flags) => { value.cookieValues[key] = { value: val, flags }; }, delete: (key) => { value.cookieValues[key] = { deleted: true }; } };
        return value;
    },
    next: () => ({ status: 200, allowed: true }),
    redirect: (url) => ({ status: 307, location: String(url) }),
};
function load(filename, imports = {}, variables = env) {
    const module = { exports: {} };
    const source = ts.transpileModule(fs.readFileSync(new URL(filename, root), 'utf8'), {
        compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText;
    vm.runInNewContext(source, {
        module, exports: module.exports, require: (name) => {
            if (name === 'next/server') return { NextResponse: response };
            if (name === 'zod') return require('zod');
            if (name in imports) return imports[name];
            throw new Error(`Unexpected dependency: ${name}`);
        }, process: { env: variables }, crypto: webcrypto, TextEncoder, TextDecoder, Uint8Array,
        Date, URL, setTimeout, clearTimeout, AbortSignal,
    }, { filename });
    return module.exports;
}
const session = load('src/lib/session.ts');
const validation = load('src/lib/validation.ts');
const middleware = load('src/middleware.ts', { '@/lib/session': session }).middleware;
const req = (path, { method = 'GET', cookie, headers = {}, body } = {}) => {
    const request = new Request(`https://reef.example${path}`, { method, headers, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    request.nextUrl = new URL(request.url);
    request.cookies = { get: (name) => name === 'api_session' && cookie ? { value: cookie } : undefined };
    return request;
};

test('anonymous pages cannot mint credentials, APIs and addon mode stay closed', async () => {
    assert.equal((await middleware(req('/'))).location, 'https://reef.example/login');
    assert.equal((await middleware(req('/api/settings'))).status, 401);
    assert.equal((await middleware(req('/api/auth/google'))).status, 401);
    assert.equal((await middleware(req('/api/auth/callback/google'))).status, 401);
    assert.equal((await middleware(req('/api/spawning'))).status, 401);
    assert.equal((await middleware(req('/api/settings', { cookie: env.API_SECRET }))).status, 401);
    const addon = load('src/middleware.ts', { '@/lib/session': session }, { ...env, HA_ADDON_MODE: 'true' }).middleware;
    assert.equal((await addon(req('/api/settings'))).status, 401);
    const missing = load('src/middleware.ts', { '@/lib/session': session }, {}).middleware;
    assert.equal((await missing(req('/api/settings'))).status, 503);
});

test('sessions are opaque, expiring, tamper resistant, and invalid after secret rotation', async () => {
    const token = await session.createSession(env.API_SECRET);
    assert(!token.includes(env.API_SECRET));
    assert(await session.validSession(token, env.API_SECRET));
    assert.equal(await session.validSession(token.replace(/^\d+/, '1000000000'), env.API_SECRET), false);
    assert.equal(await session.validSession(`${token.slice(0, -1)}${token.endsWith('a') ? 'b' : 'a'}`, env.API_SECRET), false);
    assert.equal(await session.validSession(token, 'rotated-secret'), false);
    assert.equal(session.constantTimeEqual('é', 'e'), false);
    assert.equal((await middleware(req('/api/settings', { cookie: token }))).allowed, true);
});

test('invalid configured secrets fail closed for Bearer, cookies and login', async () => {
    const cookie = await session.createSession(env.API_SECRET);
    for (const secret of [undefined, '', 'short-secret', 'a'.repeat(31), 'a'.repeat(257), ' '.repeat(32), ` ${'a'.repeat(32)}`]) {
        const variables = { ...env, API_SECRET: secret };
        const guarded = load('src/middleware.ts', { '@/lib/session': session }, variables).middleware;
        for (const headers of [{}, { authorization: `Bearer ${secret || ''}` }]) {
            assert.equal((await guarded(req('/api/settings', { cookie, headers }))).status, 503);
        }
        const route = load('src/app/api/auth/session/route.ts', {
            '@/lib/session': session, '@/lib/validation': validation,
            '@/lib/rate-limit': { rateLimit: () => null },
        }, variables);
        assert.equal((await route.POST(req('/api/auth/session', {
            method: 'POST', headers: { origin: 'https://reef.example', 'content-type': 'application/json' },
            body: { secret: secret || '' },
        }))).status, 503);
        await assert.rejects(() => session.createSession(secret), /configuration is invalid/);
    }
    assert.equal(session.validApiSecret('a'.repeat(32)), true);
    assert.equal(session.validApiSecret('a'.repeat(256)), true);
});

test('cookie writes require same-origin; forwarded Origin is not trusted; Bearer still works', async () => {
    const cookie = await session.createSession(env.API_SECRET);
    for (const headers of [{}, { origin: 'https://attacker.example' }, { origin: 'null' },
        { origin: 'https://attacker.example', 'x-forwarded-host': 'attacker.example', 'x-forwarded-proto': 'https' }]) {
        assert.equal((await middleware(req('/api/settings', { cookie, method: 'POST', headers }))).status, 403);
    }
    assert.equal((await middleware(req('/api/settings', { cookie, method: 'POST', headers: { origin: 'https://reef.example' } }))).allowed, true);
    assert.equal((await middleware(req('/api/settings', { method: 'POST', headers: { authorization: `Bearer ${env.API_SECRET}` } }))).allowed, true);
});

test('login checks origin and secret, uses HttpOnly signed cookie, and throttles attempts', async () => {
    const limiter = load('src/lib/rate-limit.ts');
    const route = load('src/app/api/auth/session/route.ts', { '@/lib/session': session, '@/lib/validation': validation, '@/lib/rate-limit': limiter });
    const make = (secret, origin = 'https://reef.example') => req('/api/auth/session', {
        method: 'POST', headers: { origin, 'content-type': 'application/json' }, body: { secret },
    });
    assert.equal((await route.POST(make(env.API_SECRET, 'https://attacker.example'))).status, 403);
    assert.equal((await route.POST(make('incorrect'))).status, 401);
    const login = await route.POST(make(env.API_SECRET));
    assert.equal(login.status, 200);
    assert(await session.validSession(login.cookieValues.api_session.value, env.API_SECRET));
    assert.equal(login.cookieValues.api_session.flags.httpOnly, true);
    assert.equal(login.cookieValues.api_session.flags.secure, true);
    for (let index = 0; index < 8; index++) await route.POST(make('incorrect'));
    assert.equal((await route.POST(make(env.API_SECRET))).status, 429);
});

test('body reader rejects oversized chunked requests and malformed JSON', async () => {
    const chunks = new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array(5)); controller.enqueue(new Uint8Array(5)); controller.close(); } });
    const request = new Request('https://reef.example/api/settings', { method: 'POST', body: chunks, duplex: 'half' });
    assert.equal((await validation.readJsonBody(request, 8)).error.status, 413);
    const bad = new Request('https://reef.example/api/settings', { method: 'POST', body: '{' });
    assert.equal((await validation.readJsonBody(bad)).error.status, 400);
    assert.equal(validation.validateContentType(req('/api/settings', { headers: { 'content-type': 'text/plain; application/json' } })).status, 415);
});

test('service proxy rejects domain aliases, implicit targets, extra targets, and any disarmed target', async () => {
    const calls = [];
    const route = load('src/app/api/ha/service/route.ts', {
        '@/lib/validation': validation,
        '@/lib/server/ha-api': { HAApiError: class extends Error {}, callHAService: async (...args) => { calls.push(args); return []; } },
        '@/lib/server/openreef-config': { isEntityControlArmed: async (id) => id === 'switch.armed' },
    });
    const post = (domain, service, serviceData) => route.POST(req('/api/ha/service', { method: 'POST', headers: { 'content-type': 'application/json' }, body: { domain, service, serviceData } }));
    assert.equal((await post('homeassistant', 'turn_off', { entity_id: 'switch.armed' })).status, 403);
    assert.equal((await post('script', 'turn_on', { entity_id: 'script.example' })).status, 403);
    assert.equal((await post('switch', 'turn_off', { entity_id: 'all' })).status, 400);
    assert.equal((await post('switch', 'turn_off', { entity_id: 'switch.armed', area_id: 'whole_home' })).status, 400);
    assert.equal((await post('switch', 'turn_off', { device_id: 'device' })).status, 400);
    assert.equal((await post('switch', 'turn_off', { entity_id: ['switch.armed', 'switch.locked'] })).status, 403);
    assert.equal(calls.length, 0);
    assert.equal((await post('switch', 'turn_off', { entity_id: 'switch.armed' })).status, 200);
    assert.equal(calls.length, 1);
});

test('HLS proxy rejects decoded traversal and arbitrary resources before reading HA config', async () => {
    const route = load('src/app/api/camera/hls/[...path]/route.ts', {
        '../../ha-config': { getHAConfig: async () => { throw new Error('should never resolve HA config'); } },
    });
    for (const path of [['..', '..', 'config'], ['token', '../config'], ['token', 'file.html'], ['token', 'segment?x=1.ts'], ['token', 'x\\y.ts']]) {
        assert.equal((await route.GET(req('/api/camera/hls/test'), { params: Promise.resolve({ path }) })).status, 400);
    }
});
