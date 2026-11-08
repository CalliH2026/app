import assert from 'node:assert/strict';
import {readdirSync, readFileSync, statSync} from 'node:fs';
import {join} from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const walk = (dir) => readdirSync(dir).flatMap((name) => statSync(join(dir, name)).isDirectory() ? walk(join(dir, name)) : [join(dir, name)]);
const SECRET = /sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_|xox[abprs]-|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE|Bearer\s+[A-Za-z0-9._-]{16,}|AIza[0-9A-Za-z_-]{30,}/;

test('dist stays within budget and contains no media video', () => {
  const files = walk(join(ROOT, 'dist'));
  const total = files.reduce((sum, file) => sum + statSync(file).size, 0);
  assert.ok(total < 40 * 1024 * 1024, `dist is ${total} bytes`);
  assert.ok(!walk(ROOT).some((file) => /\.(mp4|mov|webm|mkv)$/i.test(file)));
});

test('no secret-like strings or local paths in the shipped files', () => {
  for (const file of walk(join(ROOT, 'dist', 'public'))) {
    const text = readFileSync(file, 'latin1');
    assert.doesNotMatch(text, SECRET, file);
  }
  assert.doesNotMatch(readFileSync(join(ROOT, 'dist/server/index.js'), 'utf8'), SECRET);
  const routes = readFileSync(join(ROOT, 'dist/routes.js'), 'utf8');
  assert.doesNotMatch(routes, /\/home\/|\/Users\//);
});

test('API fixtures have no local paths or server-only hints', () => {
  const inventory = JSON.parse(readFileSync(join(ROOT, 'dist/route-inventory.json'), 'utf8')).routes;
  for (const route of inventory.filter((item) => item.kind === 'api' && item.type.startsWith('application/json'))) {
    const text = readFileSync(join(ROOT, 'dist/public/_p', route.sha256.slice(0, 24)), 'utf8');
    assert.doesNotMatch(text, /\/home\/|\/Users\/|127\.0\.0\.1|relancez/, route.path);
    assert.doesNotMatch(text, /devin\.ai\/sessions|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i, route.path);
  }
});

test('wrangler template points at the self-contained server and has no account binding', () => {
  const config = readFileSync(join(ROOT, 'wrangler.jsonc'), 'utf8');
  assert.match(config, /"main": "dist\/server\/index.js"/);
  assert.doesNotMatch(config, /"assets"/);
  assert.doesNotMatch(config, /account_id|routes|zone/);
});
