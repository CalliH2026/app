# Calli teacher workspace: automatic dictation and preparation

The current unified entrypoint is `python -m ui.shell --stop` (New Pronote). This document describes the underlying native module and its standalone `/workspace` route. The original projects were Calligraphe and H Parallel; the combined product is Calli.

## Calli: two mechanisms, one set of contracts

1. **Observed document opening -> anticipatory preparation.** When the teacher expands a source in the
   `/workspace` dossier, the page posts `document_opened` (`source_kind: calli_workspace`, `origin: app_event`) to
   `POST /api/workspace/observations`. The server resolves pupil, course, case, document and `case_hash` from its
   own files and refuses stale, foreign or unregistered events. A valid event starts at most one H preparation per
   unchanged case (same event replayed, another source of the same case, reopening or refresh reuse the job; a
   failed job is not retried automatically; the manual "Préparer" button is the retry). "Mettre en pause" stops new
   observation-triggered work (`POST /api/workspace/observation`); a running job finishes, bound to its case.
   **Observed surface: only the Calli page.** This is a browser-sent app event, not proof of an OS action; there is
   no screen, window or PRONOTE observation yet (see `docs/calli-observation-design.md`).
2. **Explicit teacher dictation -> automatic verified writer** (SPEC 3.4): completed dictation turn -> guards ->
   queue -> the one native `run_writer --queue` loop.

Preparation is read-only: it never queues, edits or blocks a dictation. Timeline entries come from real callbacks
and stored state only, typed as `observed` (Calli event), `model_tool` (`read_case`, `search_resources` chosen by
H), `app_api` (H session start, Linkup search; Gladia is an app API, not a model tool) and `check` (snapshot,
citation validation). The writer's `next_item`/`report_result` statuses stay in the queue and journal panel.

`search_resources` (optional, `research/resources.py`): after `read_case`, H may pick one topic ID from a fixed
catalog (`paragraph_structure`, `support_idea`, `oral_participation`); the server sends that topic's generic query
to Linkup (no pupil text or names), at most once per preparation, keeps only http(s) sources Linkup returned and
renders those the model referred to by ID. No `LINKUP_API_KEY` -> "indisponible", nothing faked. A link is a
reading suggestion, not evidence of efficacy, and is kept apart from the case quotes.

To trigger the real flow: start the app with `HAI_API_KEY` (and optionally `LINKUP_API_KEY`) and
`--workspace-dir`, open `/workspace`, select Lucas Bernard, expand any source document; the status shows the outcome; the trace is under "Détails techniques (trace)". A failed job keeps a sanitized `diagnostic` (stage client/start/wait/check, error type and chain, HTTP status, the SDK's session status, error_code and error, all redacted and truncated) in its private job file under `--workspace-dir`; it is never in the API response or the page.

`/workspace` is a second screen in the standalone Calli FastAPI app. The original approval page at `/` is unchanged
and stays as the manual fallback. Only the existing writer (`python -m agent.run_writer --queue ...`) touches
the PRONOTE desktop; the workspace adds items to the same `QueueStore` and shows the same journal.

    pip install -e '.[ui,voice]'                       # FastAPI + the official Gladia SDK
    export GLADIA_API_KEY=...  HAI_API_KEY=...         # read by the server only, never sent to the page
    python -m ui.app --roster data/roster.csv --course '3A, FRANCAIS, Trimestre 1' \
        --workspace-dir /path/outside/runs/workspace-state
    # second terminal: the writer loop on the same queue, as before
    python -m agent.run_writer --target pronote --queue runs/queue.jsonl ...

Without `GLADIA_API_KEY` dictation shows "indisponible" and keyboard correction still works; without
`HAI_API_KEY` source preparation shows "indisponible". Nothing is ever fabricated in place of a provider.

## Flow

context (pupil, class, subject, period) -> dictation turn -> server guards -> queue -> writer -> read-back
results. Source preparation is a side panel: it reads a frozen case file and never adds, edits or queues a
comment. Linkup advice (old page only) is not on this path.

1. The microphone opens only when the teacher presses "Commencer la dictée" (no permission prompt on load).
2. The page streams 16 kHz PCM to `ws://127.0.0.1:<port>/ws/dictation` (Host and Origin checked: the HTTP
   middleware does not see WebSockets). The server holds the Gladia key and streams to Gladia live with the
   roster as custom vocabulary (`voice/gladia_live.py`). Only final transcripts are used.
3. "Terminer la dictée" ends the turn. Final fragments are aggregated, so a pause never writes half a sentence.
   A cancel, a pupil change or a lost connection while Gladia drains still cancels the turn.
4. `DictationPolicy` (`ui/dictation.py`) decides once per `turn_id`, persisted in `dictations.json`:
   - `queued`: exactly one comment naming exactly one recognized roster pupil (equal to the selected pupil if
     one is selected), course unchanged, STOP off, 1 to 255 characters, name and speech confidence above
     thresholds. The item is appended with `item_id = "d-" + turn_id` and `source = "automatic_dictation"`.
   - `needs_correction`: no recognized name (an unknown name never falls back to the selected pupil), an
     ambiguous name, a name different from the selected pupil, low confidence, several comments, a spoken
     correction, or more than 255 characters. The transcript is kept for "Corriger ou saisir au clavier".
   - `refused` (empty, STOP, stale context, speech-to-text failure), `cancelled`, `stopped` (spoken "stop").
5. The writer writes and reads back; the journal shows "Texte dicté" (or "Texte approuvé" for a typed
   correction) beside "Texte relu", the exact difference highlighted, and the name the agent reports.

### Thresholds (not calibrated)

`NAME_MIN_CONFIDENCE = 0.8` applies to the roster match from `voice/structurer.py` (0.95 x score for a
clear match, at most 0.6 with a close runner-up, 0.4 when two pupils tie, so ties never pass).
`ASR_MIN_CONFIDENCE = 0.7` applies to the lowest Gladia utterance confidence of the turn. Earlier synthetic
Gladia runs showed correct recognitions near 0.63 and wrong text above it, so neither number is a
correctness guarantee; below either, the turn simply stops for correction. They must be calibrated on real
recordings, not lowered to make a demo pass.

### STOP

The STOP button (top bar, always visible) sets the queue's STOP file at once: no new item is handed out,
pending items are drained to `aborted`, the dictation in progress is cancelled, and the automatic append
checks STOP again under the queue lock. A write already in progress is not interrupted and is not rolled
back. A spoken "stop" is only understood when its dictation turn ends.

### Occupied cells

Automatic items carry no previous value, so the PRONOTE target rules (`agent/targets/pronote.md`, unchanged)
make the writer report `not_found` instead of overwriting a filled cell. Replacing a known previous value is
an exceptional typed path with its own confirmation.

### Unknown writes

`unknown` is a new item and journal status for a write whose persistence is not confirmed: `report_result`
"written" with an empty read-back, an item left `in_progress` by a writer that restarted, or an item handed
out when the session ended. It is never retried automatically (a blind retry could type twice into a row);
the teacher checks the cell. An item that was never started stays `aborted`. Existing runs and evidence are
not rewritten; the README scoreboard columns are unchanged (an `unknown` item counts as attempted, not
verified), adding a column is a follow-up.

### Preparer agent loop: managed or local

`CALLI_PREPARER_RUNTIME` selects where the read-only preparer's agent loop runs:
- **`managed` (default):** H's cloud runs the session.
- **`local`:** the official `hai_agents` `Client.local()` runs the loop on this machine, while model calls still go to H's hosted model. Local runs use inline agents only and have no subagents.

Both modes use the same `read_case` and optional `search_resources` tools, the same `Answer` schema and `environments=[]`. `CALLI_PREPARER_MODEL` optionally sets the agent `model`.

How the local mode behaves:
- **Client lifetime:** each job opens its own client and closes it at the end, whether the job succeeds or fails.
- **Startup:** nothing starts at app start-up or on a GET. The roughly 60 MB runtime is downloaded on the first local job.
- **No fallback:** a local start or session failure fails the job, with no fallback to managed and no automatic retry.
- **Provenance:** the job records `provider_runtime` alongside the session ID and status.

An unknown value makes preparation unavailable instead of picking a default.

## Identity check

A write is verified only if the read-back text is exact and the full student name the agent REPORTS reading
on the row matches the queued pupil (`agent/identity.py`). This checks what the agent reports; it is not an
independent visual audit and does not prove which physical row was typed into.

## The s01 case

`data/dossiers/s01.json` is `source_kind: authored_demo`: a fictitious French writing exercise for the
existing fictitious pupil Lucas Bernard, written for this demo. It is not imported from PRONOTE and carries no
measured grade. It is separate from the measured PRONOTE evidence in `runs/` and `docs/evidence/`. A live H
preparation is shown as returned (summary marked "à relire"); citations are checked mechanically, which does
not make the generated claims pedagogically or linguistically correct.

## What comes from where

### Francois Amat, H Parallel (`Fran-cois/H-Hack-nov26`, commit `160dd5ea32e05f47a1921c15e5a75fedb20b29c1`, `mvp/`)

Shared by a team member for this hackathon; reused with the author's agreement. No license is claimed here
beyond that. Adapted, not vendored:

- `mvp/engine.py` `quote_candidates` / `quote_catalog`: deterministic quote IDs over the documents, the model
  selects IDs and the program substitutes the literal excerpt (`research/dossier.py`).
- `mvp/engine.py` `checked_answer` and the typed answer schema: reject unknown or missing quote IDs and empty
  evidence (`research/dossier.py::check_preparation`).
- `mvp/native_pipeline.py` fingerprinting: canonical snapshot and hash of identity, course, question, document
  bytes and preparation version (`research/dossier.py::snapshot`, `case_hash`).
- `mvp/engine.py` `launch`: `environments=[]` with a single `read_case` custom tool, bounded wait, releasing the
  job's own idle session (`research/preparation.py`).
- `mvp/static/workspace.*` and the h-kit: restrained layout, Plus Jakarta Sans and Fira Code
  (`ui/static/workspace.*`, `ui/static/fonts/` with the OFL license files in `ui/static/fonts/licenses/`).

Not taken: the Mac/Wine observer, Google Calendar, management localStorage, video renderer, fake grades, inbox
and calendar cards, and the `local_demo` dashboard (not a PRONOTE sync).

### Liqin, Scribe des profs UX architecture V3.1

Used as a behavior contract, not as screens: the teacher flow context -> draft -> execution -> results,
explicit pupil/class/subject/period, no draft or identity reuse after a selection change, the 255-character
limit refused on the server with a visible counter, and a separate confirmation for a replacement. Her
BR-001 is adapted as described in SPEC.md 3.4 (automatic dictation under server guards instead of a click
per comment). Her whole contract (30 screens, 12 flows, RBAC matrix, tenant administration, support) is not
implemented.

**Phase 04 V4.2 ("Scribe des profs", Autonome FR, interactive wireframes).** This is a private design file that is not copied into this repo; any screenshot of it must be labelled as a non-connected prototype with no PRONOTE behind it. Calli takes principles from it, not screens:

| Phase 04 screen | Applied in `/workspace` |
|---|---|
| TCH-03 Context | class, subject and period are shown in the header and in the pupil head; the course is fixed on the server |
| TCH-09 Execution | STOP is pinned in the top bar and described as stopping new writes only; a write already under way can finish and nothing is rolled back |
| TCH-10 Results | the per-pupil queue is grouped as Vérifiées / Non confirmées / En cours / Non commencées, and `unknown` reads "Non confirmé : vérification nécessaire", never a confirmed failure |
| TCH-11 Journal | each line shows the dictated text against the read-back text, the name the agent reported, and the time |
| TCH-08 Conflict | the automatic path never overwrites; a replacement needs its own confirmation (BR-004) |
| TCH-13 Accessibility | visible focus, skip link, `aria-live` statuses, a plain-words status legend, keyboard correction field |

Not adopted:
- **TCH-07 batch approval**, because the user explicitly chose automatic dictation without per-comment approval (SPEC 3.4).
- **TCH-12 controlled undo:** the existing journal-based undo tool is unchanged, with no UI for it here.
- **The ADM, SUP and PUB spaces:** design-only, with no role switch or access roles added.

Traceability for this slice (test files under `tests/`):

| ID | Status here | Tests |
|---|---|---|
| BR-001 | adapted: dictation turn is the explicit act, server guards | `test_dictation.py::test_clear_dictation_is_queued_as_automatic_dictation`, `test_unclear_dictation_stops_for_correction` |
| BR-002 | partial: bound to roster ID, course and exact text; no approval versioning per field | `test_workspace_api.py::test_stale_or_unknown_identity_and_empty_text_queue_nothing`, `test_changed_context_is_refused` |
| BR-003 / AT-001 | ambiguous or unknown name abstains | `test_dictation.py::test_unclear_dictation_stops_for_correction[ambiguous]`, `test_unnamed_or_unknown_name_never_falls_back_to_the_selected_pupil` |
| BR-004 / AT-003 | replacement needs its own confirmation; automatic path never overwrites | `test_workspace_api.py::test_replacement_needs_its_own_confirmation` |
| BR-006 / AT-005 / BR-015 / AT-004 | no read-back or lost mid-item is `unknown`, no retry | `test_writer_identity.py::test_written_without_read_back_is_unknown_and_never_retried`, `test_session_end_marks_started_items_unknown_and_unstarted_items_aborted`, `test_queue_store.py::test_recover_marks_items_left_in_progress_unknown` |
| BR-007 / AT-007 | STOP blocks new items, in-flight not interrupted | `test_dictation.py::test_stop_pressed_while_the_turn_is_decided_queues_nothing`, `test_stop_right_after_the_append_leaves_nothing_pending_for_resume`, `test_workspace_api.py::test_stop_blocks_workspace_approval` |
| BR-011 / AT-008 | case documents are data | `test_dossier.py::test_document_instructions_stay_data_and_are_quoted_exactly` |
| BR-016 | preparation never writes or queues | `test_workspace_api.py::test_prepare_is_deduplicated_and_never_touches_the_queue`, `test_dictation.py::test_recent_dictations_listed_and_preparation_never_queues` |
| AT-011 | keyboard correction path when the microphone is unavailable | browser QA only |
| AT-013 | over 255 characters refused, never truncated | `test_workspace_api.py::test_text_over_255_characters_is_refused_not_truncated`, `test_dictation.py::test_unclear_dictation_stops_for_correction[too_long]` |
| AT-015 | lost connection cancels the turn | `test_dictation.py::test_cancel_and_disconnect_queue_nothing` |
| AT-018 | context change between dictation and write | `test_dictation.py::test_start_refuses_stale_course_unknown_pupil_and_stop`, `test_cancel_after_end_while_finals_are_pending_queues_nothing` |

Deferred, not compliant: BR-005 (independent read-back audit after navigation), BR-008 / AT-006 (undo with
concurrent-change check), BR-009 / AT-009 (server-side permissions, tenant authorization; the app is
loopback-only without authentication), BR-010, BR-012 / AT-012 (support access, pseudonymized journals),
BR-013 / AT-010 (instance suspension), BR-014 / AT-014 (qualified target versions), AT-016 (full screen-reader
audit), AT-017 (school exit and purge).

## Local runtime (hai-agents 1.4.3, hai-agent-runtime 0.1.23)

First real run on the fixed code (root, outside this repository): a local preparation with the real H model and Linkup reached `ready` in 16.3 s with `answer_contract=json_text_validated`. H called `read_case`, then `search_resources(oral_participation)`; Linkup returned 3 sources in 1.4 s, H kept 2, and 5 literal citations passed the mechanical check. No queue file was created and nothing was written to PRONOTE. That run was a manual retry of an earlier failure, not a fresh observed trigger. The citation check proves the quotes exist in the frozen case, not that the advice is pedagogically good: the output still contained an awkward English word and an unneeded question, and needs a teacher's review.

Runtime 0.1.23 fails any session that carries an `answer_format` (`answer_schema` in the SDK) with `ModuleNotFoundError: No module named 'datamodel_code_generator'`. It fails before the first model call. This was reproduced offline with the real runtime binary and a stand-in model server.

- Custom tools work without a schema.
- The runtime is a compiled binary. No documented extra or pip package adds the missing module.
- So the local preparer sends no `answer_schema`. It asks for the same `Answer` as JSON text and validates it with the same Pydantic model.
- The `read_case` requirement and citation checks are unchanged. Text that is not the Answer object fails the job at the `check` stage.
- The job records `answer_contract`: `answer_schema` (managed) or `json_text_validated` (local).

Preparer on Mac or Windows (no extra install; the first job downloads the runtime):

    CALLI_PREPARER_RUNTIME=local CALLI_PREPARER_MODEL=holo4-35b-a3b python -m ui.app --workspace-dir <dir>   # macOS shell
    $env:CALLI_PREPARER_RUNTIME="local"; $env:CALLI_PREPARER_MODEL="holo4-35b-a3b"; python -m ui.app --workspace-dir <dir>   # Windows PowerShell

Writer, only inside the interactive Windows guest that shows PRONOTE. It needs the official desktop driver extra, `pip install "hai-agents[desktop]>=1.4.3"`:

    python -m agent.run_writer --target pronote --runtime local --model holo4-35b-a3b --queue runs/queue.jsonl

- `--runtime local` refuses `--desktop-session-id` and any target other than PRONOTE.
- The client is closed only after `summary.json`, `events.jsonl` and `screenshots/` are written.
- The exit code is 0 only when the provider session completed and every handed-out item is verified.
