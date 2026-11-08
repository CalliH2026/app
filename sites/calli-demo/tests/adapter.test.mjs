import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/preview/adapter.js', import.meta.url), 'utf8');

function sandbox(pathname = '/app', search = '') {
  const calls = [];
  const store = new Map();
  const loaded = [];
  const element = () => ({setAttribute() {}, append() {}, hidden: false, set innerHTML(v) { this.html = v; }});
  const window = {
    fetch: async (input, init) => { calls.push([input, init]); return new Response('{}'); },
    localStorage: {getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v)},
    navigator: {mediaDevices: {getUserMedia: async () => 'stream'}, sendBeacon: () => true},
    WebSocket: function () {},
    loadReport: (id) => loaded.push(id),
  };
  const document = {body: {append() {}}, createElement: element, getElementById: () => null, addEventListener() {}};
  const context = {window, document, location: {pathname, search, href: 'https://p.example' + pathname + search}, URL, URLSearchParams,
    Response, setTimeout: (fn) => fn(), clearTimeout() {}, setInterval: () => 0, clearInterval() {}, String, JSON, Promise, Error};
  vm.runInNewContext(source, context);
  return {window, calls, store, loaded};
}

test('GET passes through, every other method is answered locally with 403 JSON', async () => {
  const {window, calls} = sandbox();
  await window.fetch('/api/workspace');
  assert.equal(calls.length, 1);
  for (const method of ['POST', 'PUT', 'DELETE', 'PATCH']) {
    const response = await window.fetch('/api/outings', {method, body: '{}'});
    assert.equal(response.status, 403);
    assert.equal((await response.json()).error, 'read_only');
  }
  assert.equal(calls.length, 1);
});

test('opening the copy shows the saved H report instead of starting a run', async () => {
  const {window, loaded, calls} = sandbox();
  const response = await window.fetch('/api/workspace/documents/copie/open', {method: 'POST', body: '{}'});
  assert.equal(response.status, 403);
  assert.match((await response.json()).detail, /Rapport enregistré du 7 novembre 2026 chargé/);
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(loaded, ['6b073dfc404f']);
  assert.equal(calls.length, 0);
});

test('microphone, websocket and beacons are disabled; saved outing is preselected', async () => {
  const {window, store} = sandbox('/calli/workspace', '?embed=1');
  await assert.rejects(window.navigator.mediaDevices.getUserMedia({audio: true}));
  assert.throws(() => new window.WebSocket('wss://x/ws'));
  assert.equal(window.navigator.sendBeacon('/x', 'y'), false);
  assert.equal(store.get('new-pronote-outing-job'), '23025b24ce29');
});

test('only same-origin aggregate metrics bypass the read-only browser guard',async()=>{const {window,calls}=sandbox();await window.fetch('/metrics/event',{method:'POST',body:'{"event":"parent"}'});assert.equal(calls.length,1);const res=await window.fetch('https://other.example/metrics/event',{method:'POST',body:'{}'});assert.equal(res.status,403);assert.equal(calls.length,1);});
