/* Calli public preview adapter: read-only navigation over saved runs.
   Blocks school mutations, provider calls, WebSocket, microphone and beacons. Only the bounded aggregate metrics endpoint accepts a POST. */
(() => {
  'use strict';
  const JOB = '6b073dfc404f';
  const OUTING = '23025b24ce29';
  const VIDEO = 'https://www.youtube.com/watch?v=mILSh_vLQck';
  const DETAIL = 'Aperçu public en lecture seule : cette action n’est pas exécutée ici. Les vues montrent des exécutions enregistrées.';
  const OPEN_COPY = '/api/workspace/documents/copie/open';
  const w = window;
  const embedded = location.pathname.startsWith('/calli/');

  function toast(text) {
    const show = () => {
      let el = document.getElementById('calli-preview-toast');
      if (!el) {
        el = document.createElement('div');
        el.id = 'calli-preview-toast';
        el.className = 'calli-preview-toast';
        el.setAttribute('role', 'status');
        el.setAttribute('aria-live', 'polite');
        document.body.append(el);
      }
      el.textContent = text;
      el.hidden = false;
      clearTimeout(w.__calliPreviewToast);
      w.__calliPreviewToast = setTimeout(() => { el.hidden = true; }, 4200);
    };
    if (document.body) show(); else document.addEventListener('DOMContentLoaded', show, {once: true});
  }

  function pathOf(input) {
    try { return new URL(typeof input === 'string' ? input : input.url, location.href).pathname; } catch { return ''; }
  }

  function blocked(path) {
    if (path === OPEN_COPY) {
      setTimeout(() => showSavedRun().catch(() => {}), 250);
      const text = 'Aperçu public : aucune nouvelle session H n’est lancée. Le rapport enregistré du 7 novembre 2026 est affiché.';
      toast(text);
      return text;
    }
    toast(DETAIL);
    return DETAIL;
  }

  const nativeFetch = w.fetch.bind(w);

  // Opening the copy is the product's trigger for H. Here it attaches the saved run instead.
  async function showSavedRun() {
    if (typeof renderAgent !== 'function') { if (typeof w.loadReport === 'function') w.loadReport(JOB); return; }
    const job = await (await nativeFetch('/api/jobs/' + JOB)).json();
    try { current = job; } catch {} // eslint-disable-line no-undef
    renderAgent(job); // eslint-disable-line no-undef
    if (typeof setPanel === 'function') setPanel(true); // eslint-disable-line no-undef
  }
  w.fetch = function previewFetch(input, init = {}) {
    const method = String(init.method || (input && typeof input === 'object' && input.method) || 'GET').toUpperCase();
    if (method === 'POST' && pathOf(input) === '/metrics/event' && new URL(typeof input === 'string' ? input : input.url, location.href).origin === new URL(location.href).origin) return nativeFetch(input, init);
    if (method !== 'GET' && method !== 'HEAD') {
      const detail = blocked(pathOf(input));
      return Promise.resolve(new Response(JSON.stringify({error: 'read_only', detail}), {
        status: 403, headers: {'Content-Type': 'application/json; charset=utf-8'},
      }));
    }
    return nativeFetch(input, init);
  };

  if (w.XMLHttpRequest) {
    const open = w.XMLHttpRequest.prototype.open;
    const send = w.XMLHttpRequest.prototype.send;
    w.XMLHttpRequest.prototype.open = function (method, ...rest) { this.__calliMethod = String(method).toUpperCase(); return open.call(this, method, ...rest); };
    w.XMLHttpRequest.prototype.send = function (...args) {
      if (this.__calliMethod && this.__calliMethod !== 'GET' && this.__calliMethod !== 'HEAD') { toast(DETAIL); throw new Error(DETAIL); }
      return send.apply(this, args);
    };
  }
  w.WebSocket = function PreviewWebSocket() { toast('Aperçu public : la dictée en direct est désactivée.'); throw new Error('Aperçu public : la dictée en direct est désactivée.'); };
  if (w.navigator) {
    if (w.navigator.mediaDevices) {
      w.navigator.mediaDevices.getUserMedia = () => { toast('Aperçu public : le micro n’est pas utilisé.'); return Promise.reject(new Error('Aperçu public : le micro n’est pas utilisé.')); };
    }
    if (w.navigator.sendBeacon) w.navigator.sendBeacon = () => false;
  }
  try { if (!w.localStorage.getItem('new-pronote-outing-job')) w.localStorage.setItem('new-pronote-outing-job', OUTING); } catch {}

  if (embedded) return;

  const view = new URLSearchParams(location.search).get('view');
  if (view === 'family' || view === 'appreciations') {
    const started = Date.now();
    const timer = setInterval(() => {
      if (typeof w.showPage === 'function' && document.getElementById('main')?.children.length) { clearInterval(timer); w.showPage(view); }
      else if (Date.now() - started > 8000) clearInterval(timer);
    }, 150);
  }

  function chip() {
    const box = document.createElement('details');
    box.className = 'calli-preview-status';
    box.innerHTML = `<summary>Public preview · saved runs</summary>
      <div class="calli-preview-panel">
        <p>Read-only and fictional. These views replay saved outputs: nothing is generated, sent or written from this page.</p>
        <ul>
          <li><a href="/app?job=${JOB}">H preparation report</a><span>Saved run, 7 Nov 2026</span></li>
          <li><a href="/api/jobs/${JOB}/practice/preview" target="_blank" rel="noopener">Interactive exercise</a><span>Generated through the Devin API, saved output</span></li>
          <li><a href="/app?view=outings&amp;outing_id=${OUTING}">School trip research</a><span>Saved partial draft, no booking or payment</span></li>
          <li><a href="/app?view=family">Family view · Mme Martin</a><span>Read-only summary from fictional sources</span></li>
          <li><a href="${VIDEO}?t=33" target="_blank" rel="noopener">Native PRONOTE write</a><span>Recorded run, shown in the demo video</span></li>
        </ul>
        <p class="calli-preview-muted">Live only in the full product: dictation, new H runs, native PRONOTE writing, exercise generation, calendar and notifications.</p>
        <p><a href="/guide">Guide</a> · <a href="${VIDEO}" target="_blank" rel="noopener">Demo video</a></p>
      </div>`;
    document.body.append(box);
  }
  if (document.body) chip(); else document.addEventListener('DOMContentLoaded', chip, {once: true});
})();
