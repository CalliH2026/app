# Calli in this workspace

**New Pronote** is the interface the teacher sees: Francois Amat's teacher workspace, its report, school outing and
practice flows, with its own n/p wordmark (team Calli, H Company x 42AI hackathon, Paris, November 2026).
**Calli** is the assistant inside it (formerly "Parallèle"): it prepares the work in parallel and, for appreciations,
controls the real legacy PRONOTE client behind New Pronote. This change adds:

- **Naming.** Every agent label (rail, dock, notifications, reports, connections) reads "Calli" / "Assistant Calli",
  with a small line bot icon in the shell's icon style. PRONOTE keeps its name; internal ids and paths are unchanged.
  Liqin Wang's Calli logo (`ui/static/brand/calli-logo.svg`, SHA256
  `264bca7de716858d01132c0c59d9253bc982b89db3caafe7268311cf9c362cd0`) stays in the repository and on Calli's own pages.
- **Pupil photos.** `static/avatars/calli-portraits-fictifs-ia-s01-s10.png` (SHA256
  `da4b1a4b8fe2ed3675aaaa5ae72517fe3508442de7251228a68530dc49fd8a2d`) is Calli's atlas of ten entirely AI-generated
  portraits of fictional pupils, reused unchanged as a CSS sprite. `static/calli-shell.js` maps the fictional Alex Martin
  to one tile explicitly; pupils added by the teacher keep initials. The page says "Photos d'élèves fictives, générées par IA."
- **Appreciations (optional).** A rail entry that shows Calli's dictation-to-PRONOTE module, mounted at `/calli` in this
  same app by `calli_module.py` and shown in an iframe (`/calli/workspace?embed=1`). Calli keeps its own guards (Host and
  Origin checks, JSON-only POSTs, WebSocket origin check), its identity-checked queue, STOP, journal and cell readback.
  There is no extra approve or send step. Without configuration the entry says the module is unavailable and nothing is
  sent or synchronised. "Available" only means the module is mounted; writer state and readback results are shown inside it.
- **Outings.** A finished outing where every collection failed and nothing succeeded reads "rien n'a été préparé" instead
  of "à compléter", without naming a cause the job does not record (also for jobs saved before `h_outcome`).

## Enable the Appreciations module

```
pip install -e /path/to/calligraphe            # its own dependencies; add '.[voice]' for live dictation
export CALLI_SOURCE=/path/to/calligraphe
export CALLI_QUEUE=/path/to/runs/queue.jsonl   # shared with Calli's writer, run separately on the PRONOTE machine
export CALLI_ROSTER=/path/to/calligraphe/data/roster.csv
export CALLI_COURSE="3A, FRANCAIS, Trimestre 1"   # exact course of that roster, as Calli parses it
# optional: CALLI_JOURNAL, CALLI_WORKSPACE_DIR; live dictation only if GLADIA_API_KEY is set
uvicorn mvp.app:app --host 127.0.0.1 --port 8000
```

The module needs Calli's checkout to include page-relative URLs in `ui/static/workspace.*` (Calli patch
"workspace: page-relative URLs and ?embed=1"). This app never starts Calli's writer, and the module is never mounted when `PUBLIC_URL` is set (shared hosting).

## Evidence, as measured (no full-success claim)

- Real H analysis → live Devin practice: H report 97.31 s, Devin session ready 390.83 s, semantic checks passed.
- Real outings with Holo4: one partial in 90.22 s with three facts legitimately unknown; one run timed out at 303.53 s
  with no tool call. No complete budget has been produced.
- Human time saved is not measured; any "about 50 % of active time" figure is a theoretical estimate, not an observation.

## Native pupils in "Mes élèves"
When the module is mounted, the ten fictional pupils of Calli's roster (s01..s10, class from the configured course,
e.g. "3A, FRANCAIS, Trimestre 1") are listed in "Mes élèves" from `/calli/api/config`, with their atlas photos and the
class filter. They are read-only rows, never saved into the browser's local records; Alex (4e B) stays his own case.
"Appréciations" on a row opens the module on that pupil (`?student=sNN`, accepted only if on the roster); the choice
is kept for the browser session. No note or appreciation of Alex is sent to PRONOTE.

## Optional ElevenLabs voice for the synthetic fixtures (mvp/video.py)
Default `TTS_PROVIDER=local` (say / espeak-ng) is unchanged. `TTS_PROVIDER=elevenlabs` uses the documented
`POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128` (`xi-api-key`) with
`ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` (default Alice `Xb7hH8MSUJpSbSDYk0k2`, a stock voice) and
`ELEVENLABS_MODEL_ID` (default `eleven_multilingual_v2`), language `fr`. Any failure is raised; there is no silent
local fallback. Synthetic voices are fixtures, not speech-to-text proof; saved run inputs are never regenerated.

The fixture `mvp/fixtures/alex.json` uses two committed ElevenLabs voices (Alice, `eleven_multilingual_v2`, 24 kHz mono
WAV), `parent-points-elevenlabs.wav` and `parent-progress-elevenlabs.wav`, so a clean checkout serves `/audio/points` and
`/audio/progress` without any provider or local TTS. Texts, durations and hashes: `mvp/fixtures/parent-voices-elevenlabs.json`.
`python -m mvp.video` skips them because they already exist.
