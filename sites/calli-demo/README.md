# Calli public preview (read-only, saved runs)

A read-only, interactive preview of the New Pronote + Calli workspace for the hackathon submission.
Visitors explore saved outputs of real recorded runs with fictional data. Nothing in this package starts an
agent, calls a provider, writes to PRONOTE, records the microphone, uploads a file or charges a payment.

Demo video (final accepted cut, hosted on YouTube; MP4 not stored in Git): https://www.youtube.com/watch?v=mILSh_vLQck

## Hosting format

- **Main: `dist/server/index.js`**, a single ES module with `export default {fetch}`. Every allowlisted
  asset is embedded in it (2.6 MB, 1.4 MB gzipped), so it needs no ASSETS binding, no static directory and no
  environment variables. It can be used as the server entry of a Sites/Workers project as is.
- Alternative: `dist/worker.js` + `dist/routes.js` + `dist/public/` for hosts with a Workers ASSETS binding
  (`assets.directory = dist/public`, `binding = ASSETS`, `run_worker_first = true`). Same route table and checks.
- `wrangler.jsonc` is a template pointing at the main bundle. No account, project ID, route or secret is set.
  `.openai/hosting.json` is not included; the Sites project ID is supplied by the hosting session.
- All product links are same-origin paths (`/app`, `/guide`, `/static/...`); no host name is hard-coded.

## Commands (Node 20+, no dependencies)

    npm run build    # capture/saved + vendor + src -> dist/
    npm test         # 32 offline unit tests (both hosting formats)
    npm run serve    # local check of dist/server/index.js on http://127.0.0.1:8787/

## Routes

- `/` English landing (`/fr` French), with **Try the workspace** -> `/app`.
- `/app` and `/workspace`: the actual New Pronote workspace. Deep links: `/app?job=6b073dfc404f` (saved H
  report), `/app?view=outings&outing_id=23025b24ce29` (saved outing), `/app?view=family`, `/app?doc=copie`.
- `/guide`: how to explore, and what is saved rather than live.
- The full allowlist with type, size and SHA-256 of each response is `dist/route-inventory.json`
  (157 GET/HEAD routes):
- Pages (6): `/`, `/app`, `/calli/workspace`, `/fr`, `/guide`, `/workspace`
- Saved API responses (38): `/api/auth/me`, `/api/calendar/status`, `/api/calli/status`, `/api/family`, `/api/family/sources/A-COPIE`, `/api/family/sources/A-MSG-1`, `/api/family/sources/A-MSG-3`, `/api/family/sources/A-RDV`, `/api/family/sources/L-DEVOIR`, `/api/family/sources/L-REUNION`, `/api/family/sources/L-SORTIE`, `/api/fixture`, `/api/jobs/6b073dfc404f`, `/api/jobs/6b073dfc404f/audio`, `/api/jobs/6b073dfc404f/practice`, `/api/jobs/6b073dfc404f/practice/preview`, `/api/native/context`, `/api/native/documents`, `/api/notifications/status`, `/api/outings/23025b24ce29`, `/api/outings/23025b24ce29/export`, `/api/outings/options`, `/api/pronote/background`, `/api/pronote/connection`, `/api/recordings`, `/api/recordings/native/status`, `/api/reports`, `/api/workspace`, `/api/workspace/documents/bareme`, `/api/workspace/documents/consigne`, `/api/workspace/documents/copie`, `/api/workspace/documents/methode`, `/audio/points`, `/calli/api/config`, `/calli/api/state`, `/calli/api/workspace/cases`, `/calli/api/workspace/cases/s01-francais-t1`, `/calli/api/workspace/dictations`
- Static files (113): product files under `/static/` and `/calli/static/` from `a0d922e`, landing files `/styles.css`, `/preview.css`, `/assets/*`, `/favicon.ico`, and `/preview/adapter.{js,css}`.

Everything else is refused by the Worker:
- any method other than GET/HEAD -> 405 JSON `read_only` (`allow: GET, HEAD`);
- WebSocket upgrades -> 403 JSON;
- traversal, encoded separators, backslashes, control characters, `//` -> 400;
- unknown paths under `/api/`, `/calli/api/`, `/ws/`, `/audio/`, `/recordings/`, `/outputs/` -> 404 JSON
  (never HTML); other unknown paths -> small HTML 404 linking to the workspace;
- internal blob names, source files, the route table and removed product pages are not reachable;
- HEAD returns headers only. Pages carry a same-origin CSP (`connect-src 'self'`, `form-action 'none'`) and
  `permissions-policy: microphone=()`.

## Read-only adapter (`src/preview/adapter.js`)

Injected before the product scripts on `/app`, `/workspace` and `/calli/workspace`. It answers every
non-GET fetch/XHR locally with a 403 and a short French note, disables WebSocket, getUserMedia and sendBeacon,
preselects the saved outing, and, when the teacher opens the copy (the product's H trigger), attaches the saved
H run instead of starting one. A small "À propos de cet espace" chip (bottom left) opens a details panel
with the saved runs and the video. No banner, no mandatory dialog.

## Provenance

- **Product UI**: `vendor/` is `git archive a0d922e30d1201c4ab5d3e2ba97282e6dfc74605 mvp/static ui/static` of
  wilfred-dore/calligraphe (PR22 head "Ma famille: Grégory Martin with Alex and Lucas Martin, compact header,
  caveats in details"), unmodified except that these live/provider entry points were removed: `mvp/static/{native,pilot,index}.html`,
  `{native,pilot,app}.js`, `practice-pythagore-demo.html`, `ui/static/{index.html,app.js,parallel.css,parallel.js,sortie.html,entrainement.html,pcm-worklet.js}`.
- **Saved data**: `capture/saved/` holds 40 GET responses exported by `capture/export_fixtures.py` from the
  `a0d922e` app running offline on saved demo data (STOP on, no provider keys, no writer, GET only). The
  unsanitized export is not shipped; `capture/saved/manifest.json` keeps each raw SHA-256.
  - H preparation report: job `6b073dfc404f`, saved run of 2026-11-07 18:54 CET (Holo, report only, status
    ready). Parent voice note is synthetic.
  - Interactive exercise: saved Devin API output for that job, served byte-identical
    (SHA-256 `4dc614241a077b73ebd11944b3b96497a265489c96d90fe9129a2df3a4de2a1e`) under its original sandbox CSP
    (`sandbox allow-scripts; connect-src 'none'`). Status "to review"; not regenerated.
  - School trip: saved outing `23025b24ce29` (Musée d'Orsay, 4e B), status partial, with sources and tool trace.
    No booking, no payment, no Stripe call.
  - Family: Grégory Martin with Alex Martin and Lucas Martin and their fictional sources.
  - Appreciations: fictional 3A roster and AI-generated fictional portraits. The native PRONOTE write and
    read-back are recorded evidence only: https://www.youtube.com/watch?v=mILSh_vLQck&t=33s
- **Sanitization** (`dist/sanitization-report.json`, 49 values): local paths removed, server-only hints
  replaced, provider session IDs replaced by `saved-session-N` pseudonyms, the private Devin session link removed.
- **Size optimization** (`src/media/manifest.json`, `capture/optimize_media.sh`): the portrait sprite is a WebP
  q90 re-encode of the PNG (served at the original path as image/webp); the two parent voice notes are 48 kbit/s
  MP3 of the saved WAV. Original hashes are recorded.
- **Landing**: Root's archive `calli-landing-video-v4.tar.gz` (SHA-256 `34bc3a9a…ecdc6`). Hero image replaced by
  the accepted PR22 Today capture (SHA-256 `7e49671d…26ca`, 1920x1080). Build patches: CTA -> "Try the workspace"
  `/app`, Guide link, local-preview note -> read-only public preview, video element -> YouTube link. No MP4.

## Not in this preview

Live dictation (Gladia), the native PRONOTE queue, writer and STOP control, new H or Devin runs, exercise
approval/download, new outing research, the family digest generation, calendar and notification connections,
uploads, auth, report export, the pilot and native pages, and the streamed progress audio. These controls are
visible in the product UI but answer with the read-only note.

## QA

`qa/` holds the browser check (`browser-check.js`, 38 checks, Chrome headless against `npm run serve`), its log
and results, and screenshots. Unit test output: `qa/unit-tests.log`.
