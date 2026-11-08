import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test, {describe} from 'node:test';
import {fileURLToPath} from 'node:url';
import {fileAssets} from '../build/assets.mjs';
import {handle, isUnsafePath} from '../dist/worker.js';
import server from '../dist/server/index.js';

const root = fileURLToPath(new URL('../dist/public', import.meta.url));
const env = {ASSETS: fileAssets(root)};
const inventory = JSON.parse(readFileSync(new URL('../dist/route-inventory.json', import.meta.url))).routes;
const TARGETS = [
  ['dist/server/index.js (embedded assets, main)', (request) => server.fetch(request)],
  ['dist/worker.js + ASSETS binding', (request) => handle(request, env)],
];

for (const [label, run] of TARGETS) describe(label, () => {
const call = (path, init = {}) => run(new Request('https://calli-demo.example' + path, init));
const body = async (path) => JSON.parse(await (await call(path)).text());

test('every inventoried route answers GET with its type and HEAD with no body', async () => {
  for (const route of inventory) {
    const get = await call(route.path);
    assert.equal(get.status, 200, route.path);
    assert.equal(get.headers.get('content-type'), route.type, route.path);
    assert.equal(get.headers.get('x-content-type-options'), 'nosniff');
    assert.equal((await get.arrayBuffer()).byteLength, route.bytes, route.path);
    const head = await call(route.path, {method: 'HEAD'});
    assert.equal(head.status, 200, route.path);
    assert.equal(head.headers.get('content-type'), route.type);
    assert.equal(head.body, null, route.path);
  }
});

test('inventory has the required entry points and only GET/HEAD', () => {
  const paths = new Set(inventory.map((route) => route.path));
  for (const path of ['/', '/guide', '/app', '/workspace', '/calli/workspace', '/api/workspace', '/api/family',
    '/api/jobs/6b073dfc404f', '/api/jobs/6b073dfc404f/practice', '/api/jobs/6b073dfc404f/practice/preview',
    '/api/outings/23025b24ce29', '/calli/api/workspace/cases']) assert.ok(paths.has(path), path);
  assert.ok(inventory.every((route) => route.method === 'GET, HEAD'));
  assert.ok(!inventory.some((route) => /\/(native|pilot|demo|sortie|entrainement)(\.html)?$/.test(route.path)));
});

test('writes, provider actions and unknown methods are rejected as JSON', async () => {
  const targets = ['/api/workspace/documents/copie/open', '/api/jobs/6b073dfc404f/practice', '/api/jobs/6b073dfc404f/practice/approve',
    '/api/outings', '/api/family/digest', '/api/audio', '/api/native/connect', '/api/pronote/background/start', '/calli/api/stop',
    '/calli/api/workspace/observations', '/api/workspace', '/app', '/', '/does-not-exist'];
  for (const path of targets) {
    for (const method of ['POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']) {
      const response = await call(path, {method, ...(method === 'OPTIONS' ? {} : {body: '{}'})});
      assert.equal(response.status, 405, `${method} ${path}`);
      assert.match(response.headers.get('content-type'), /^application\/json/);
      assert.equal(response.headers.get('allow'), 'GET, HEAD');
      assert.equal((await response.json()).error, 'read_only');
    }
  }
});

test('websocket upgrades are refused', async () => {
  for (const path of ['/calli/ws/dictation', '/ws/dictation', '/app']) {
    const response = await call(path, {headers: {upgrade: 'websocket'}});
    assert.equal(response.status, 403);
    assert.equal((await response.json()).error, 'websocket_disabled');
  }
});

test('unknown JSON endpoints fail as JSON, never as HTML', async () => {
  for (const path of ['/api/nope', '/api/jobs/000000000000', '/api/jobs/6b073dfc404f/practice/download', '/api/workspace/documents/secret',
    '/calli/api/workspace/preparations/x', '/api/outings/23025b24ce29/missing', '/audio/progress', '/recordings/x/y', '/outputs/x/y', '/api']) {
    const response = await call(path);
    assert.equal(response.status, 404, path);
    assert.match(response.headers.get('content-type'), /^application\/json/, path);
    assert.equal((await response.json()).error, 'unknown_endpoint');
    const head = await call(path, {method: 'HEAD'});
    assert.equal(head.status, 404);
  }
});

test('unknown pages get a small HTML 404, HEAD without body', async () => {
  const response = await call('/nothing-here');
  assert.equal(response.status, 404);
  assert.match(response.headers.get('content-type'), /^text\/html/);
  assert.match(await response.text(), /Try the workspace/);
  assert.equal((await call('/nothing-here', {method: 'HEAD'})).body, null);
});

test('no arbitrary file serving or traversal', async () => {
  const bad = ['/static/../worker.js', '/static/%2e%2e/routes.js', '/static/..%2fbuild.mjs', '/static//workspace.js', '/static/%5c..%5cx',
    '/calli/static/%2E%2E/%2E%2E/package.json', '/api/../worker.js', '/%00', '/static/workspace.js%00.png'];
  for (const path of bad) {
    const response = await call(path);
    assert.ok([400, 404].includes(response.status), `${path} -> ${response.status}`);
    assert.notEqual(response.status, 200);
  }
  for (const path of ['/_p/' + inventory[0].sha256.slice(0, 24), '/routes.js', '/worker.js', '/package.json', '/capture/raw/manifest.json',
    '/static/native.html', '/static/pilot.js', '/static/workspace.html', '/calli/static/workspace.html', '/vendor/mvp/static/workspace.js']) {
    assert.equal((await call(path)).status, 404, path);
  }
  assert.ok(isUnsafePath('/a/../b') && isUnsafePath('/a%2F..') && !isUnsafePath('/static/brand/calli-logo.svg'));
});

test('query strings do not change routing', async () => {
  assert.equal((await call('/static/workspace.css?v=grading-voice-final-20261107')).status, 200);
  assert.equal((await call('/calli/workspace?embed=1&student=s01')).status, 200);
  assert.equal((await call('/app?job=6b073dfc404f')).status, 200);
});

test('saved fixtures keep the accepted personas and saved statuses', async () => {
  const workspace = await body('/api/workspace');
  assert.match(JSON.stringify(workspace), /Mme Laurent|Madame Laurent/);
  const family = await body('/api/family');
  assert.equal(family.parent.name, 'Grégory Martin');
  assert.deepEqual(family.children.map((child) => child.name), ['Alex Martin', 'Lucas Martin']);
  const job = await body('/api/jobs/6b073dfc404f');
  assert.equal(job.status, 'ready');
  assert.equal(job.report_only, true);
  const practice = await body('/api/jobs/6b073dfc404f/practice');
  assert.equal(practice.provider, 'Devin');
  assert.equal(practice.approved, false);
  const outing = await body('/api/outings/23025b24ce29');
  assert.equal(outing.status, 'partial');
  const state = await body('/calli/api/state');
  assert.equal(state.stopped, true);
  assert.deepEqual(await body('/api/reports'), []);
});

test('saved Devin exercise keeps its sandbox CSP', async () => {
  const response = await call('/api/jobs/6b073dfc404f/practice/preview');
  assert.match(response.headers.get('content-security-policy'), /sandbox allow-scripts; default-src 'none'.*connect-src 'none'/);
  assert.equal(response.headers.get('x-calli-original-sha256'), '4dc614241a077b73ebd11944b3b96497a265489c96d90fe9129a2df3a4de2a1e');
});

test('pages carry a same-origin CSP and the preview adapter', async () => {
  for (const path of ['/app', '/workspace', '/calli/workspace']) {
    const response = await call(path);
    assert.match(response.headers.get('content-security-policy'), /connect-src 'self'.*form-action 'none'/);
    const html = await response.text();
    assert.ok(html.indexOf('/preview/adapter.js') < html.indexOf('<script src="'.concat(path === '/calli/workspace' ? 'static/workspace.js' : '/static/calli-shell.js')));
  }
  const landing = await (await call('/')).text();
  assert.match(landing, /href="\/app">Try the workspace/);
  assert.match(landing, /https:\/\/www\.youtube\.com\/watch\?v=mILSh_vLQck/);
  assert.doesNotMatch(landing, /127\.0\.0\.1|calli-demo\.mp4|<video/);
  assert.match(await (await call('/guide')).text(), /https:\/\/www\.youtube\.com\/watch\?v=mILSh_vLQck/);
});

test('size-optimized media keep their declared type', async () => {
  for (const [path, type] of [['/static/avatars/calli-portraits-fictifs-ia-s01-s10.png', 'image/webp'], ['/api/jobs/6b073dfc404f/audio', 'audio/mpeg'], ['/audio/points', 'audio/mpeg']]) {
    const response = await call(path);
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('content-type'), type);
    const bytes = new Uint8Array(await response.arrayBuffer());
    assert.ok(bytes.length > 1000);
  }
});
});

test('server bundle is a plain default {fetch} module and works without env', async () => {
  assert.equal(typeof server.fetch, 'function');
  const response = await server.fetch(new Request('https://x.example/guide'));
  assert.equal(response.status, 200);
  const size = JSON.parse(readFileSync(new URL('../dist/server/size.json', import.meta.url)));
  assert.ok(size.gzip_bytes < 3 * 1024 * 1024, JSON.stringify(size));
});
