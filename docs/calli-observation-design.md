# Calli observation design (for review, not implemented)

Calli (Calligraphe + Francois Amat's H Parallel, with Liqing's Scribe UX contract) should notice the work in
progress and prepare complementary work in parallel. Today `/workspace` only "observes" what the teacher selects
or dictates and a frozen authored case (`data/dossiers/s01.json`, `source_kind: authored_demo`). This note compares
Francois's native observer with our `PreparationStore` and proposes the smallest adapter. **Nothing here is wired:
no observer trigger, no background provider call, until the product owner chooses between (A) observing a document
opened inside Calli first and (B) requiring native PRONOTE observation immediately.**

Update: option A was chosen and is implemented (`POST /api/workspace/observations`, see
`docs/parallel-workspace.md`). Option B (native observation) is still design only.

## What the upstream code actually does (`Fran-cois/H-Hack-nov26` @ `160dd5e`, `mvp/`)

| | `native/native_documents.py` `DocumentOpenDetector` | `native_pipeline.py` `NativeCase` / `schedule` | `native_ai.py` `schedule` |
|---|---|---|---|
| Source | registered attachments (`AttachmentRegistry`): each needs `provenance.kind` in `native_document`, `native_export`, `imported_demo_document` (the last requires `import_evidence`); file sha256 checked against the manifest | `NativeSource` (id, role, title, text, sha256, `Provenance{kind, locator, native_context_id, observed_at, imported_into_native}`) | live window text read from the PRONOTE example base (`connection_state == example_open`, `method == win32_controls`) |
| Trigger | a NEW viewer window (pid:hwnd:title) whose title matches a registered `copy`; the first snapshot is only a baseline | `CopyOpened{type: copy_opened, document_id, source_locator, event_id, observed_at}` must match the active copy and context | a new `context_id` (once per context unless forced) |
| Event id / dedupe | sha256 of context id + document id + (source id, sha256) list + audio sha256; persisted `emitted` set | `fingerprint(case, audio)` over origin, copy id, source texts/locators/hashes, audio hash | `context_id` |
| Evidence | method `win32_document_windows`, hwnd, window title, class, process, filename | validators refuse demo/test kinds in a native case | quotes must be substrings of the read window text |
| Effects | none (returns events) | schedules an H job, read-only | H session with `read_pronote_context` and optional `search_resources` (Linkup), writes a report file |

Our `research/preparation.PreparationStore` already has: frozen snapshot + `case_hash` (identity, course, question,
document bytes, version), dedupe by hash, one bounded worker, explicit retry, persisted provider session id and
elapsed time from the SDK, `read_case` required, quote ids resolved to literal text, no queue access. It has **no
trigger**: a job starts only on the teacher's click. Upstream adds what we lack (an observed event with app evidence)
and has what we already have (hash dedupe, read-only H job, literal citations).

## Minimal adapter contract

One JSON object per observation, persisted append-only next to the preparation state:

```json
{
  "event_id": "sha256 of the canonical fields below",
  "event_type": "document_opened | dictation_completed | selection_changed",
  "origin": "app_event | inferred_intent | teacher_dictation",
  "source_kind": "calli_workspace | pronote_native | authored_demo",
  "observed_at": "ISO-8601 with offset, from the observer clock",
  "student_id": "s01", "course_id": "3A, FRANCAIS, Trimestre 1",
  "documents": [{"document_id": "copie", "sha256": "...", "locator": "data/dossiers/s01.json#copie"}],
  "source_hash": "case_hash of the frozen snapshot the event refers to",
  "evidence": {"method": "calli_ui_click | win32_document_windows | ...", "details": {}},
  "provenance": {"observer": "module and version", "native": false}
}
```

Rules: `origin` separates an actual application event (a click in Calli, a native window that appeared) from an
inferred intent (a heuristic guess, never auto-launched) and an explicit teacher dictation (already handled by
`ui/dictation.py`). `provenance.native` is true only with native evidence (method, window handle/title, verified
file hash), never inferred. Ids come from the roster and case files, never from free text. An event may at most
*propose* a preparation (`PreparationStore.prepare(case)` dedupes by `source_hash`); preparation stays read-only and
the writer (`run_writer --queue`) stays the only process that touches PRONOTE.

Option A (inside Calli): emit `document_opened` when the teacher expands a source in `/workspace`
(`origin: app_event`, `source_kind: calli_workspace`). Cheap, honest, testable offline; it observes Calli, not
PRONOTE. Option B (native): port `DocumentOpenDetector` behind the same contract on the Windows VM; needs the
registry of verified native attachments and the window probe, and is untestable on this Linux VM.

## Tool-call visibility (smallest real extension)

Show three kinds separately in the trace panel and journal, only from recorded events (no timers, no invented graph):
- model-invoked tools: `read_case` (preparation), `next_item` and `report_result` (writer), each with call time,
  arguments summary and result status, recorded by our tool wrappers;
- application API calls made by our code: Gladia live session (start/end, final count), H session start/status/
  cancel, with provider ids;
- deterministic checks: citation resolution, identity gate, text comparison, dictation guards, with the rule that
  decided.

Optional later, design only: a Linkup `search_resources(topic)` tool for preparation, enabled per job, with the
frozen case as the only context, a generic query that contains no pupil name or identifier (refused otherwise),
a budget of at most 2 calls per job, results returned with URL and title as provenance, no writing side effects,
and its output kept apart from case citations. Add it only if a task needs external resources.

## Evaluation protocol (to run; no results here)

Arms, same initial data (fictitious roster and case), same task definition and success criterion:
1. manual human baseline in PRONOTE;
2. GUI-only agent (writer without structured tools);
3. hybrid tools + GUI, serial (prepare, then dictate, then write);
4. identical hybrid task with background prefetch (preparation proposed by an observed event).

Success: an independent final-state check of each target cell (exact text, right pupil, right period) after the
run, by a person or a separate read not performed by the writing agent. Measure per task: successful checks, human
active time, elapsed time, interventions, false and missed anticipations (prefetch arm), useful completion before
the teacher needed it, provider and agent cost, redundant or cancelled jobs. Run at least 3 repetitions per arm,
alternate the order, report every run including failures. With n this small, report raw counts and ranges, not
significance. Existing numbers are not measurements of this combined flow: the historical PRONOTE 10/10 run used
the earlier approval flow, the 15.7 s H preparation was one live call, and end-to-end automatic write from dictation
to PRONOTE is still unverified.
