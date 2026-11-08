# Benchmark protocol: measured agent time vs estimated or measured human time

This extends the Calli/PRONOTE section of [human-arm.md](human-arm.md) to any scenario, including the school
outing once its code exists. The tool is `scripts/bench.py`. It writes JSON lines, outside `runs/` and the
README scoreboard, and never computes a saving percentage.

## Rules

1. **Agent times are measured, never estimated.** A record has `basis: measured` and points to its evidence:
   a job file, a run directory or a command, plus an H session ID when there is one.
2. **Human times are either measured (stopwatch, n people) or `basis: estimate`** with a written `assumption`,
   for example "typing 40 wpm, 3 tabs, read-back included". Estimates form their own group. Any comparison
   that uses one reads "estimated human".
3. **Active vs elapsed.** `active_s` is the human's hands-on time. `elapsed_s` is the wall-clock latency of the
   task. For the agent arm, the teacher's active time is the dictation itself. The agent's latency runs in
   parallel and is not teacher time.
4. **Cold vs warm.** `cold` is the first run after a fresh start of the local runtime or app (it includes the
   runtime download/start). `warm` is a repeat with the runtime already up. Use `unknown` when it was not
   controlled. Never relabel afterwards.
5. **Repeats.** At least 3 runs per (scenario, arm, condition) before a median is quoted. Report n, median,
   min–max, failures and retries. The median and range use successful runs only; failures are counted and listed.
6. **No retry inside a measurement.** `bench.py record` runs the command once. A rerun is a new record. A
   writer item that needed a corrective attempt counts in `retries`.
7. **Success artifacts.** A run is `ok` only if the command or provider succeeded and every expected artifact
   exists (`--artifact`). For a writer, every handed-out item must also be read back as `verified`.
8. **Cost** only when it comes from the provider or from token usage at list price, with `cost_note` saying
   which. Otherwise it is left empty.
9. **Same task for both arms:** the same initial state, inputs and final-state check, as in human-arm.md.

## Record fields

`scenario`, `arm` (`agent`|`human`), `basis` (`measured`|`estimate`), `condition`
(`cold`|`warm`|`unknown`|`n/a`), `started_at`, `ended_at`, `elapsed_s`, `active_s`, `ok`, `failure`, `retries`,
`tools` (per-tool or per-item timings: `elapsed_s`, or `offset_s` from the start), `artifacts`, `source`,
`assumption` (estimates), `cost_usd` + `cost_note`, `labels` (runtime, model, answer contract, trigger).
`bench.py` rejects any record that breaks rules 1, 2 or 8.

## Commands

```bash
# Calli preparation jobs (per-tool offsets come from the job's model_tool/app_api events)
python scripts/bench.py from-preparation <workspace-dir>/preparations/prep-*.json --condition warm --out bench/calli.jsonl
# Writer runs (per-item seconds from journal.jsonl; the historical 10/10 run is approved-text writer only)
python scripts/bench.py from-run runs/20261107-152520 --scenario pronote-writer-approved-text --out bench/calli.jsonl
# Any command, e.g. the school-outing entry point once located (run once, no retry)
python scripts/bench.py record --scenario school-outing --condition cold --artifact <expected-result.json> \
    --out bench/outing.jsonl -- <command>
# Summary table (n, OK, failed, retries, median, range, human active, cost)
python scripts/bench.py summarize bench/*.jsonl --markdown
```

## School outing: what to measure once the code is located

- Agent arm: n ≥ 3 cold and n ≥ 3 warm runs of Francois's unmodified entry point. Record the per-tool timings
  from the H session events (H model steps, OSRM route, Linkup if used), the H session IDs and the result
  artifact. A run without its artifact is a failure.
- Human arm: either a stopwatch with the same fictitious inputs and the same expected output (`basis:
  measured`), or a written estimate (`basis: estimate`), shown only as "estimated human".
- Not claimed: a percentage of time saved from agent timings alone, or any number not produced by
  `bench.py summarize` from these files.
