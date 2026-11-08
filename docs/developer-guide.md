# Calli: developer guide

Start with the [README](../README.md), [use cases](calli-use-cases.md), [integrated architecture](calli-system.md) and [API inventory](calli-api-and-architecture.md). This guide maps behaviour to code, explains important contracts and identifies the tests to run when changing a flow.

## Entry points and ownership

| Area | Start reading here | Responsibility |
|---|---|---|
| Unified launcher | [`ui/shell.py`](../ui/shell.py), [`mvp/app.py`](../mvp/app.py) | Start New Pronote on loopback; configure the optional native module. `--stop` starts a review session; the writer is separate. |
| Native mount | [`mvp/calli_module.py`](../mvp/calli_module.py), [`ui/app.py`](../ui/app.py) | Mount the native ASGI app at `/calli`, preserving its request checks. Disable it when `PUBLIC_URL` is set. The standalone approval page remains a fallback. |
| Dictation | [`ui/dictation.py`](../ui/dictation.py), [`voice/gladia_live.py`](../voice/gladia_live.py), [`voice/structurer.py`](../voice/structurer.py) | Stream audio, aggregate final fragments, match roster names locally and decide one outcome per completed turn. |
| Native persistence | [`agent/queue_store.py`](../agent/queue_store.py), [`agent/run_writer.py`](../agent/run_writer.py), [`agent/identity.py`](../agent/identity.py), [`agent/journal.py`](../agent/journal.py) | Coordinate one writer with the UI; expose bounded H tools; compare reported pupil/text; record results. |
| Native workspace preparation | [`ui/workspace.py`](../ui/workspace.py), [`research/dossier.py`](../research/dossier.py), [`research/preparation.py`](../research/preparation.py), [`research/resources.py`](../research/resources.py) | Observe registered Calli document-open events; freeze a case; select and validate evidence; optionally search generic educational topics. |
| Imported workspace preparation | [`mvp/engine.py`](../mvp/engine.py), [`mvp/native_pipeline.py`](../mvp/native_pipeline.py), [`mvp/preparation_tools.py`](../mvp/preparation_tools.py) | François's workspace/report pipeline, snapshots and H tool calls. This coexists with the native workspace preparer. |
| Teacher assessment | [`mvp/teacher_assessment.py`](../mvp/teacher_assessment.py), [`mvp/grading_voice.py`](../mvp/grading_voice.py) | Validate a teacher-assigned assessment and parse dictation/imports. It is distinct from native PRONOTE grade writing. |
| Exercise | [`mvp/practice.py`](../mvp/practice.py), [`mvp/practice_theme.py`](../mvp/practice_theme.py) | Keep simulation and live Devin generation distinct; persist the artifact; apply presentation styling only to the sandboxed preview. |
| School trip | [`mvp/outings_holo.py`](../mvp/outings_holo.py), [`mvp/outings_orchestration.py`](../mvp/outings_orchestration.py), [`mvp/outings.py`](../mvp/outings.py) | Expose H tools, dispatch requested collectors concurrently, aggregate a sourced or partial dossier. |
| Family | [`mvp/family.py`](../mvp/family.py), [`mvp/static/family.js`](../mvp/static/family.js) | Validate child/source/deadline/action IDs and render a read-only summary from trusted records. |
| Public exploration | [`sites/calli-demo/README.md`](../sites/calli-demo/README.md) | Reproduce the published, allowlisted read-only export with saved outputs. |

`vendor/h_parallel/` is an earlier preserved upstream snapshot used by the standalone adapter. `mvp/` is the current New Pronote shell. Do not assume editing the vendored copy changes the unified UI. Import provenance is in [francois-mvp-import.md](francois-mvp-import.md).

## Contracts worth preserving

| Contract | Input → outcome | Failure / concurrency behaviour |
|---|---|---|
| `DictationPolicy.commit(turn)` | Completed transcript and frozen context → persisted decision; a passing turn queues `d-{turn_id}`. | Repeated turns reuse the decision. Unknown/ambiguous names do not fall back to the selected pupil. STOP is checked again during queue append. |
| `QueueStore` | Item with pupil, course, text and source → pending / claimed / final result. | JSONL rewrites use a lock and atomic replacement. This supports the local UI and one writer, not a distributed fleet. STOP drains pending work, without rollback. |
| `next_item` / `report_result` | One bounded write → reported full name and text → Python comparison and journal. | Missing read-back or an interrupted active write becomes `unknown`; no blind retry. The presentation disables corrective retries. Agent-reported read-back is not independent screen verification. |
| Preparation snapshot | Case identity, course, documents and version → fingerprint-bound report. | Foreign or stale events and invalid evidence references are rejected. Read-only preparation never queues native writes. |
| `practice.start(job_id, mode)` | Frozen report and skill brief → asynchronous activity job. | Live requires a real H report and credentials. Matching jobs are reused; uncertain session creation blocks blind retry. A failed live run does not silently become a simulation. |
| `OutingExecutionPool.request(tool)` | One requested allowlisted tool → execution ticket. | Three collectors can overlap. Repeated tools reuse the execution. `ready()` means all requested collectors settled, including failures; it does not mean a complete dossier. Closing suppresses late publication. |
| Family digest | Child/source/deadline/action identifiers → trusted text and links. | Membership and source checks prevent cross-child selection. Family IDs are separate from the native pupil roster. |
| Practice preview | Stored HTML → isolated, styled preview. | Preview changes preserve the original artifact and download. Network connections are blocked by the preview policy. |

## Routes and boundaries

The unified server exposes workspace routes in `mvp/app.py`; the native sub-app is prefixed `/calli`. Examples:

- `/api/workspace`: workspace state; `/api/jobs/{job_id}`: preparation result and trace.
- `/api/jobs/{job_id}/practice`: exercise status/start; `/preview` and `/download`: separate presentation and artifact paths.
- `/api/outings`: start a trip draft; `/api/outings/{outing_id}`: state and tool execution trace.
- `/api/family`: family view; `/api/family/sources/{source_id}`: source detail.
- `/calli/ws/dictation`: native dictation stream; `/calli/api/workspace/observations`: registered document-open event.

These are code-navigation examples, not a substitute for request models. The mounted application and the public preview expose different surfaces; consult their route definitions before adding a client. Provider keys stay in server environment configuration, never a browser bundle.

## Quality checks

Use a configured development environment with the relevant extras. Tests below use mocks or fixtures; do not inject live provider credentials to make tests pass.

```sh
python -m pip install -e '.[shell,dev]'
ruff check .
python scripts/report.py --check
python -m pytest -q tests/test_dictation.py tests/test_queue_store.py tests/test_writer_identity.py tests/test_writer_unknown.py
python -m pytest -q tests/test_dossier.py tests/test_observation.py tests/test_shell_launcher.py
python -m pytest -q mvp/test_family.py mvp/test_practice.py mvp/test_practice_theme.py mvp/test_calli_module.py mvp/test_outings_orchestration.py
```

The [CI workflow](../.github/workflows/ci.yml) runs root tests on Python 3.10/3.12, preserved H Parallel tests, the unified MVP suite and the public export's build/tests. The full MVP suite also needs its documented system tools, including FFmpeg, Poppler and speech-fixture tooling. The public export runs `npm run build` and `npm test` from `sites/calli-demo/`.

For a new integration, verify idempotency, timeout/failure behaviour and state persistence in tests before using paid APIs. For UI-only changes, inspect the affected teacher/parent flow and source links. Keep recorded-run measurements separate from scenario estimates; regenerate the README scoreboard with `scripts/report.py`.

## Documentation coverage and remaining work

The central modules already contain module docstrings and comments about identity, STOP, snapshots, provider failures and preview isolation. This revision adds contract docstrings for the dictation policy, persistent queue, preparation store, native mount, exercise startup and outing execution pool. It also corrects the architecture boundary: **the structurer is local Python, not part of Gladia**.

This is not exhaustive API documentation for every function. Some imported route handlers remain concise and lightly documented; the source/test map above is the navigation layer. Future consolidation should reduce duplicate preparation paths, document a stable external API, define production role authorisation, and add an operational guide for a multi-user deployment. Attendance and absence workflows remain product-design work.

Comment the reason for an invariant or trade-off; use docstrings for inputs, outcomes, side effects and failure behaviour. Avoid narrating obvious statements. When changing runtime logic, update the relevant contract, diagram and test together. Do not rewrite tool-facing descriptions casually: some docstrings are part of the H tool interface.

## Optional outing Checkout

`mvp/outing_checkout.py` owns server-side prices, Stripe SDK calls and the durable SQLite ledger. `mvp/outing_checkout_routes.py` owns the signed webhook and the authenticated/local HTTP boundary. `mvp/static/outing-checkout.js` adds a separate expandable panel to the existing simulated collection. The public Site never exposes this write path. See [configuration, state diagram and offline tests](outing-stripe-checkout.md).

The landing's six role perspectives are isolated in `sites/calli-demo/src/landing/`, with source provenance in `PERSONAS.md`. Three keyboard-accessible role tabs select two cards each; they do not create product identities or change the teacher/parent demonstration family.

## Latest display and public-preview additions

[Report mathematics](report-mathematics.md) documents KaTeX display-only formatting. [Demo counters](../sites/calli-demo/docs-analytics.md) documents private daily aggregates; school routes remain read-only. [National impact](national-impact-scenario.md) distinguishes official headcounts from scenario assumptions.
