// Read-only Cloudflare Worker for the Calli public preview.
// Serves only the allowlisted GET routes in routes.js; everything else is rejected.
import ROUTES from './routes.js';

export const READ_ONLY_DETAIL =
  'Aperçu public en lecture seule : cette action n’est pas exécutée ici. Les vues montrent des exécutions enregistrées.';

const SECURITY_HEADERS = {
  'x-content-type-options': 'nosniff',
  'referrer-policy': 'no-referrer',
  'permissions-policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
  'cross-origin-opener-policy': 'same-origin',
};
const PAGE_CSP = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; " +
  "img-src 'self' data: blob:; media-src 'self'; font-src 'self' data:; connect-src 'self'; frame-src 'self'; " +
  "frame-ancestors 'self'; base-uri 'self'; form-action 'none'; object-src 'none'";
const JSON_PREFIXES = ['/api/', '/calli/api/', '/ws/', '/calli/ws/', '/audio/', '/recordings/', '/outputs/'];

export function isJsonPath(path) {
  return path === '/api' || path === '/calli/api' || JSON_PREFIXES.some((prefix) => path.startsWith(prefix));
}

export function isUnsafePath(path) {
  return path.length > 512 || /\.\.|\\|\/\/|%2e|%2f|%5c|%00/i.test(path) || /[\u0000-\u001f\u007f]/.test(path);
}

function json(status, body, extra = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {...SECURITY_HEADERS, 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', ...extra},
  });
}

function notFoundPage(head) {
  const html = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">' +
    '<title>Not found · Calli preview</title><body style="font:16px system-ui;margin:48px;color:#1d2433">' +
    '<h1>Page not found</h1><p>This address is not part of the read-only Calli preview.</p>' +
    '<p><a href="/">Home</a> · <a href="/app">Try the workspace</a> · <a href="/guide">Guide</a></p></body></html>';
  return new Response(head ? null : html, {
    status: 404,
    headers: {...SECURITY_HEADERS, 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store', 'content-security-policy': PAGE_CSP},
  });
}

const METRIC_EVENTS = new Set(['landing', 'workspace', 'teacher', 'parent', 'practice', 'outing', 'video', 'guide']);

async function recordMetric(request, env) {
  const empty = () => new Response(null, {status: 204, headers: {'cache-control': 'no-store'}});
  if (request.method !== 'POST') return json(405, {error: 'method_not_allowed'}, {allow: 'POST'});
  if (request.headers.get('origin') !== new URL(request.url).origin) return json(403, {error: 'origin_not_allowed'});
  if (request.headers.get('dnt') === '1' || request.headers.get('sec-gpc') === '1') return empty();
  if (!request.headers.get('content-type')?.startsWith('application/json')) return json(415, {error: 'json_required'});
  if (Number(request.headers.get('content-length') || 0) > 256) return json(413, {error: 'too_large'});
  let body;
  try {
    const reader = request.body?.getReader();
    if (!reader) return json(400, {error: 'invalid_event'});
    let text = '', bytes = 0;
    const decoder = new TextDecoder();
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      bytes += value.length;
      if (bytes > 256) { await reader.cancel(); return json(413, {error: 'too_large'}); }
      text += decoder.decode(value, {stream: true});
    }
    body = JSON.parse(text + decoder.decode());
  } catch { return json(400, {error: 'invalid_event'}); }
  if (!body || Object.keys(body).length !== 1 || !METRIC_EVENTS.has(body.event)) return json(400, {error: 'invalid_event'});
  // Persist aggregates only: no IP, user agent, referrer, URL, pupil data or visitor identifier.
  // A metrics failure must never block the public demonstration.
  try {
    if (env?.DB) await env.DB.prepare('INSERT INTO daily_metrics (day, event, count) VALUES (?, ?, 1) ON CONFLICT(day, event) DO UPDATE SET count = count + 1')
      .bind(new Date().toISOString().slice(0, 10), body.event).run();
  } catch { /* Availability of the product takes priority over counting. */ }
  return empty();
}

export async function handle(request, env) {
  const method = request.method.toUpperCase();
  const rawPath = request.url.replace(/^[a-z][a-z0-9+.-]*:\/\/[^/?#]*/i, '').split(/[?#]/)[0] || '/';
  const path = new URL(request.url).pathname;
  const upgrade = (request.headers.get('upgrade') || '').toLowerCase();
  if (path === '/metrics/event' && rawPath === path) return recordMetric(request, env);
  if (upgrade === 'websocket') {
    return json(403, {error: 'websocket_disabled', detail: 'Aperçu public : la dictée en direct et le micro sont désactivés.'});
  }
  if (method !== 'GET' && method !== 'HEAD') {
    return json(405, {error: 'read_only', detail: READ_ONLY_DETAIL}, {allow: 'GET, HEAD'});
  }
  if (isUnsafePath(rawPath) || isUnsafePath(path)) {
    return json(400, {error: 'invalid_path', detail: 'Invalid path.'});
  }
  const route = Object.prototype.hasOwnProperty.call(ROUTES, path) ? ROUTES[path] : null;
  if (!route) {
    if (isJsonPath(path)) {
      return json(404, {error: 'unknown_endpoint', detail: 'This endpoint is not part of the read-only public preview.', path});
    }
    return notFoundPage(method === 'HEAD');
  }
  const asset = await env.ASSETS.fetch(new Request(new URL(route.file, request.url).href, {method: 'GET'}));
  if (!asset.ok) return json(502, {error: 'asset_missing', detail: 'Saved preview asset unavailable.', path});
  const headers = {
    ...SECURITY_HEADERS,
    'content-type': route.type,
    'cache-control': route.cache,
    'x-calli-preview': route.kind === 'api' ? 'saved-response' : route.kind,
    ...(route.kind === 'page' ? {'content-security-policy': PAGE_CSP} : {}),
    ...route.headers,
  };
  return new Response(method === 'HEAD' ? null : asset.body, {status: 200, headers});
}

export default {fetch: (request, env) => handle(request, env)};
