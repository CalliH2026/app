// Builds dist/: allowlisted static files + saved API responses + read-only Worker route table.
import {createHash} from 'node:crypto';
import {gzipSync} from 'node:zlib';
import {cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync} from 'node:fs';
import {extname, join, relative} from 'node:path';
import {fileURLToPath} from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const DIST = join(ROOT, 'dist');
const PUBLIC = join(DIST, 'public');
const VIDEO = 'https://www.youtube.com/watch?v=mILSh_vLQck';
const MAX_BYTES = 40 * 1024 * 1024;
const TYPES = {'.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf', '.otf': 'font/otf', '.gif': 'image/gif', '.ico': 'image/x-icon',
  '.md': 'text/plain; charset=utf-8', '.txt': 'text/plain; charset=utf-8', '.wav': 'audio/wav'};
const SECRET = /sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_|xox[abprs]-|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE|Bearer\s+[A-Za-z0-9._-]{16,}|AIza[0-9A-Za-z_-]{30,}/;
const LOCAL = /\/home\/ubuntu|\/Users\/[a-z]|127\.0\.0\.1|localhost:\d/;

const MEDIA = JSON.parse(readFileSync(join(ROOT, 'src/media/manifest.json'), 'utf8'));
const OVERRIDES = Object.fromEntries(MEDIA.overrides.flatMap((item) => item.routes.map((route) => [route, item])));
const blobs = {};
const routes = {};
const inventory = [];
const sanitized = [];

function put(path, body, {kind, type, headers = {}, cache}) {
  if (routes[path]) throw new Error('duplicate route ' + path);
  let buffer = Buffer.isBuffer(body) ? body : Buffer.from(body);
  if (kind === 'page' && type.startsWith('text/html') && path !== '/calli/workspace') {
    buffer = Buffer.from(buffer.toString('utf8').replace('</head>', '<script defer src="/preview/metrics.js"></script></head>'));
  }
  const override = OVERRIDES[path];
  if (override) {
    if (createHash('sha256').update(buffer).digest('hex') !== override.original_sha256) throw new Error('media override source changed for ' + path);
    buffer = readFileSync(join(ROOT, 'src/media', override.file));
    type = override.type;
  }
  const sha256 = createHash('sha256').update(buffer).digest('hex');
  const file = '/_p/' + sha256.slice(0, 24);
  writeFileSync(join(PUBLIC, file), buffer);
  const text = /^(text|application\/json|image\/svg)/.test(type) ? buffer.toString('utf8') : '';
  blobs[file.slice(4)] = text && Buffer.from(text, 'utf8').equals(buffer) ? ['t', text] : ['b', buffer.toString('base64')];
  if (SECRET.test(text)) throw new Error('secret-like string in ' + path);
  if ((kind === 'api' || kind === 'page') && LOCAL.test(text)) throw new Error('local path or host in ' + path);
  routes[path] = {file, kind, type, cache: cache || (kind === 'static' ? 'public, max-age=3600' : 'no-cache'), headers};
  inventory.push({method: 'GET, HEAD', path, kind, type, bytes: buffer.length, sha256, ...(override ? {optimized_from_sha256: override.original_sha256} : {})});
}

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}

function replaceOnce(text, from, to, label) {
  if (!text.includes(from)) throw new Error(`landing patch "${label}" did not match`);
  return text.split(from).join(to);
}

const SESSION_IDS = new Map();
const SESSION_RE = /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\b[0-9a-f]{32}\b/gi;
function pseudonym(id) {
  if (!SESSION_IDS.has(id.toLowerCase())) SESSION_IDS.set(id.toLowerCase(), `saved-session-${SESSION_IDS.size + 1}`);
  return SESSION_IDS.get(id.toLowerCase());
}

function sanitizeJson(path, value, pointer = '') {
  if (typeof value === 'string') {
    if (/devin\.ai\/sessions\//.test(value)) { sanitized.push({path, pointer, rule: 'private_session_link'}); return null; }
    if (SESSION_RE.test(value)) {
      SESSION_RE.lastIndex = 0;
      sanitized.push({path, pointer, rule: 'provider_session_id'});
      value = value.replace(SESSION_RE, pseudonym);
    }
    SESSION_RE.lastIndex = 0;
    if (/^\/(home|Users|tmp|private|var)\//.test(value)) { sanitized.push({path, pointer, rule: 'local_path'}); return '[local path omitted]'; }
    if (/relancez (le serveur|avec)/.test(value)) { sanitized.push({path, pointer, rule: 'server_hint'}); return 'Désactivé dans l’aperçu public en lecture seule.'; }
    return value;
  }
  if (Array.isArray(value)) return value.map((item, i) => sanitizeJson(path, item, `${pointer}/${i}`));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, sanitizeJson(path, item, `${pointer}/${key}`)]));
  }
  return value;
}

function injectAdapter(html, path) {
  html = html.replace(/src="\/static\/workspace\.js[^"]*"/, 'src="/static/workspace.js?v=public-11"').replaceAll('Espace de démonstration', 'Espace de travail').replace('Ma famille (vue parent, démonstration)', 'Ma famille (vue parent)');
  const tag = '<link rel="stylesheet" href="/preview/adapter.css"><script src="/preview/adapter.js"></script>';
  const at = html.search(/<head[^>]*>/i);
  if (at < 0) throw new Error('no <head> in ' + path);
  const end = html.indexOf('>', at) + 1;
  return html.slice(0, end) + tag + html.slice(end);
}

rmSync(DIST, {recursive: true, force: true});
mkdirSync(join(PUBLIC, '_p'), {recursive: true});

// 1. Product static files from the a0d922e tree (vendor/ holds a git archive of it).
for (const [dir, prefix] of [['vendor/mvp/static', '/static/'], ['vendor/ui/static', '/calli/static/']]) {
  for (const file of walk(join(ROOT, dir)).sort()) {
    const rel = relative(join(ROOT, dir), file).split('\\').join('/');
    if (rel === 'workspace.html') continue;
    const type = TYPES[extname(file).toLowerCase()];
    if (!type) throw new Error('unexpected static file type ' + rel);
    const source = readFileSync(file);
    // Copy-only polish for the public workspace; execution boundaries are unchanged.
    const body = prefix === '/static/' && rel === 'workspace.js'
      ? Buffer.from(source.toString('utf8').replaceAll('Espace de démonstration', 'Espace de travail'))
      : source;
    put(prefix + rel, body, {kind: 'static', type});
  }
}

// 2. Landing (Root's archive, minimally patched) and guide.
const LANDING_STYLE_REV = createHash('sha256').update(readFileSync(join(ROOT, 'src/landing/styles.css'))).digest('hex').slice(0, 12);
const VIDEO_BLOCK = /<video[\s\S]*?<\/video>/;
let en = readFileSync(join(ROOT, 'src/landing/index.html'), 'utf8');
en = replaceOnce(en, 'href="http://127.0.0.1:18775/">Open the local demo <span aria-hidden="true">↗</span>', 'href="/app">Try the workspace <span aria-hidden="true">→</span>', 'en cta');
en = replaceOnce(en, 'Hackathon prototype · fictional students · local preview', 'Explore New Pronote · <a href="/guide">Testing guide</a>', 'en note');
en = replaceOnce(en, 'width="1440" height="900"', 'width="1920" height="1080"', 'en hero size');
en = replaceOnce(en, '<a href="#questions">Questions</a>', '<a href="#questions">Questions</a><a href="/guide">Guide</a>', 'en nav');
en = replaceOnce(en, 'href="index.fr.html"', 'href="/fr"', 'en lang');
en = replaceOnce(en, 'href="assets/calli-demo.mp4"', `href="${VIDEO}" target="_blank" rel="noopener"`, 'en video link');
let fr = readFileSync(join(ROOT, 'src/landing/index.fr.html'), 'utf8');
fr = replaceOnce(fr, 'href="http://127.0.0.1:18775/">Ouvrir la démo locale', 'href="/app">Essayer l’espace de travail', 'fr cta');
fr = replaceOnce(fr, 'Prototype de hackathon · élèves fictifs · aperçu local', 'Explorez New Pronote · <a href="/guide">Guide de prise en main</a>', 'fr note');
fr = replaceOnce(fr, 'href="index.html"', 'href="/"', 'fr lang');
fr = replaceOnce(fr, 'href="assets/calli-demo.mp4"', `href="${VIDEO}" target="_blank" rel="noopener"`, 'fr video link');
if (fr.includes('width="1440" height="900"')) fr = fr.split('width="1440" height="900"').join('width="1920" height="1080"');
for (const [lang, label] of [['en', 'Watch on YouTube'], ['fr', 'Voir sur YouTube']]) {
  const page = lang === 'en' ? en : fr;
  if (!VIDEO_BLOCK.test(page)) throw new Error('no video block in ' + lang);
  const link = `<a class="video-link" href="${VIDEO}" target="_blank" rel="noopener"><img src="/assets/workspace.png" alt="Calli in action" width="1920" height="1080" loading="lazy"><span class="play">▶ ${label}</span></a>`;
  const patched = replaceOnce(page.replace(VIDEO_BLOCK, link), 'href="styles.css">', `href="/styles.css?v=${LANDING_STYLE_REV}"><link rel="stylesheet" href="/preview.css">`, lang + ' css')
    .split('src="assets/').join('src="/assets/');
  put(lang === 'en' ? '/' : '/fr', patched, {kind: 'page', type: TYPES['.html']});
}
put('/guide', readFileSync(join(ROOT, 'src/guide.html')), {kind: 'page', type: TYPES['.html']});
put('/favicon.ico', readFileSync(join(ROOT, 'src/landing/assets/calli-logo-transparent.svg')), {kind: 'static', type: 'image/svg+xml'});
put('/styles.css', readFileSync(join(ROOT, 'src/landing/styles.css')), {kind: 'static', type: TYPES['.css']});
put('/preview.css', readFileSync(join(ROOT, 'src/landing/preview.css')), {kind: 'static', type: TYPES['.css']});
for (const name of readdirSync(join(ROOT, 'src/landing/assets')).sort()) {
  put('/assets/' + name, readFileSync(join(ROOT, 'src/landing/assets', name)), {kind: 'static', type: TYPES[extname(name)]});
}
put('/preview/adapter.js', readFileSync(join(ROOT, 'src/preview/adapter.js')), {kind: 'static', type: TYPES['.js'], cache: 'no-cache'});
put('/preview/metrics.js', readFileSync(join(ROOT, 'src/preview/metrics.js')), {kind: 'static', type: TYPES['.js'], cache: 'no-cache'});
put('/preview/adapter.css', readFileSync(join(ROOT, 'src/preview/adapter.css')), {kind: 'static', type: TYPES['.css'], cache: 'no-cache'});

// 3. Product pages and saved API responses exported from the offline server.
// capture/raw (unsanitized export, never shipped) -> capture/saved (sanitized, shipped) -> dist.
const RAW = join(ROOT, 'capture/raw');
const SAVED = join(ROOT, 'capture/saved');
if (existsSync(join(RAW, 'manifest.json'))) {
  rmSync(SAVED, {recursive: true, force: true});
  mkdirSync(SAVED, {recursive: true});
  const raw = JSON.parse(readFileSync(join(RAW, 'manifest.json'), 'utf8')).routes;
  const saved = {};
  for (const [path, entry] of Object.entries(raw)) {
    let body = readFileSync(join(RAW, entry.file));
    if (createHash('sha256').update(body).digest('hex') !== entry.sha256) throw new Error('capture hash mismatch ' + path);
    if (entry.headers['content-type'].startsWith('application/json')) {
      body = Buffer.from(JSON.stringify(sanitizeJson(path, JSON.parse(body.toString('utf8')))));
    }
    writeFileSync(join(SAVED, entry.file), body);
    saved[path] = {...entry, sha256: createHash('sha256').update(body).digest('hex'), bytes: body.length, raw_sha256: entry.sha256};
  }
  writeFileSync(join(SAVED, 'manifest.json'), JSON.stringify({base: 'local offline server, sanitized by build/build.mjs', routes: saved}, null, 1) + '\n');
  writeFileSync(join(SAVED, 'sanitization-report.json'), JSON.stringify(sanitized, null, 1) + '\n');
}
const capture = JSON.parse(readFileSync(join(SAVED, 'manifest.json'), 'utf8')).routes;
for (const [path, entry] of Object.entries(capture)) {
  const body = readFileSync(join(SAVED, entry.file));
  if (createHash('sha256').update(body).digest('hex') !== entry.sha256) throw new Error('saved fixture hash mismatch ' + path);
  const type = entry.headers['content-type'];
  const headers = Object.fromEntries(Object.entries(entry.headers).filter(([key]) => key !== 'content-type'));
  if (path === '/' || path === '/calli/workspace') {
    const html = injectAdapter(body.toString('utf8'), path);
    if (path === '/') { put('/app', html, {kind: 'page', type}); put('/workspace', html, {kind: 'page', type}); }
    else put(path, html, {kind: 'page', type});
    continue;
  }
  put(path, body, {kind: 'api', type, headers});
}

const total = walk(PUBLIC).reduce((sum, file) => sum + statSync(file).size, 0);
if (total > MAX_BYTES) throw new Error(`dist/public is ${total} bytes, above the 40 MB budget`);
writeFileSync(join(DIST, 'routes.js'), '// Generated by build/build.mjs. Allowlisted GET/HEAD routes only.\nexport default ' + JSON.stringify(routes, null, 1) + ';\n');
cpSync(join(ROOT, 'src/worker.js'), join(DIST, 'worker.js'));

// Main hosting format: one self-contained module, `export default {fetch}`, assets embedded (no ASSETS binding).
const core = readFileSync(join(ROOT, 'src/worker.js'), 'utf8');
const IMPORT = "import ROUTES from './routes.js';";
const DEFAULT = 'export default {fetch: (request, env) => handle(request, env)};';
if (!core.includes(IMPORT) || !core.includes(DEFAULT)) throw new Error('src/worker.js layout changed');
const server = [
  '// Generated by build/build.mjs from src/worker.js. Read-only Calli public preview.',
  '// Entry: export default {fetch}. Every allowlisted asset is embedded; nothing else is served.',
  'const ROUTES = ' + JSON.stringify(routes) + ';',
  'const BLOBS = ' + JSON.stringify(blobs) + ';',
  core.replace(IMPORT, '').replace(DEFAULT, ''),
  'const decoded = new Map();',
  'function blobBody(id) {',
  "  const [kind, data] = BLOBS[id];",
  "  if (kind === 't') return data;",
  '  if (!decoded.has(id)) decoded.set(id, Uint8Array.from(atob(data), (c) => c.charCodeAt(0)));',
  '  return decoded.get(id);',
  '}',
  'const EMBEDDED_ASSETS = {',
  '  async fetch(request) {',
  '    const id = new URL(request.url).pathname.slice(4);',
  "    if (!Object.prototype.hasOwnProperty.call(BLOBS, id)) return new Response('not found', {status: 404});",
  '    return new Response(blobBody(id));',
  '  },',
  '};',
  'export default {fetch: (request, env) => handle(request, {...(env || {}), ASSETS: EMBEDDED_ASSETS})};',
  '',
].join('\n');
mkdirSync(join(DIST, 'server'), {recursive: true});
writeFileSync(join(DIST, 'server', 'index.js'), server);
const serverGzip = gzipSync(server, {level: 9}).length;
writeFileSync(join(DIST, 'server', 'size.json'), JSON.stringify({bytes: Buffer.byteLength(server), gzip_bytes: serverGzip}, null, 1) + '\n');
if (serverGzip > 3 * 1024 * 1024) throw new Error(`server bundle is ${serverGzip} bytes gzipped, above 3 MiB`);
inventory.sort((a, b) => a.path.localeCompare(b.path));
writeFileSync(join(DIST, 'route-inventory.json'), JSON.stringify({generated_by: 'build/build.mjs', methods: ['GET', 'HEAD'], routes: inventory}, null, 1) + '\n');
cpSync(join(SAVED, 'sanitization-report.json'), join(DIST, 'sanitization-report.json'));
console.log(`server bundle ${(Buffer.byteLength(server) / 1048576).toFixed(2)} MB (${(serverGzip / 1048576).toFixed(2)} MB gzip); ${inventory.length} routes (${inventory.filter((r) => r.kind === 'api').length} api, ${inventory.filter((r) => r.kind === 'page').length} pages), ${(total / 1048576).toFixed(2)} MB, ${JSON.parse(readFileSync(join(SAVED, 'sanitization-report.json'), 'utf8')).length} sanitized values`);
