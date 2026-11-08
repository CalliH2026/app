# Human arm: how long does a person take to type the same comments?

The scoreboard compares the loop with a baseline agent. A third line, the human arm, gives the order of magnitude a teacher would recognise. It takes one team member ten minutes, and it is labelled n = 1 in the table: one person, one sitting, not a study.

## Protocol

1. Open the Moodle demo as the teacher (same account the agent uses), course "Mindful Course Creation", assignment "Timed Task", "View all submissions". Pick five students whose feedback field is empty (after an hourly reset, all of them are).
2. Take the five demo comments of `data/moodle_batch_c.csv` (or any five from `data/truth.csv`), printed or on a second screen, exactly as a teacher would have them in mind.
3. Start a stopwatch. For each student: open the row's grading page, type the comment in "Feedback comments", save, go back to the list. Stop the watch after the fifth save. Do not read back; a teacher usually does not.
4. Write the result as a journal, one line per item, with `arm` = `human`, `status` = `verified` only if you then checked the five fields and they match (otherwise `mismatch`), `seconds` = total time divided by five:

```bash
python - <<'EOF'
import json, time
rows = [("h01","Donald Torres",61.0),("h02","Julie Ellis",58.0),("h03","Peter Kelly",64.0),("h04","Charles Bailey",55.0),("h05","Ann Hansen",60.0)]  # replace with your names and your seconds
import pathlib; d = pathlib.Path("runs/%s-human" % time.strftime("%Y%m%d-%H%M%S")); d.mkdir(parents=True)
with open(d / "journal.jsonl", "w", encoding="utf-8") as f:
    for item_id, student, secs in rows:
        f.write(json.dumps({"ts": time.time(), "arm": "human", "target": "moodle", "run_id": d.name, "item_id": item_id,
                            "student": student, "status": "verified", "seconds": secs, "note": "n = 1, one team member typing"}, ensure_ascii=False) + "\n")
(d / "summary.json").write_text(json.dumps({"arm": "human", "target": "moodle", "note": "typed by hand, stopwatch, n = 1"}), encoding="utf-8")
print(d)
EOF
python scripts/report.py
```

5. Say in the README's "How to read it" list who typed, and that the seconds exclude reading back.

The point is not to win the race (a human types a 60-character sentence in well under a minute); it is to show that the agent's 70 to 80 seconds per comment run in parallel with the teacher's dictation of the next one, and that the agent reads back, which the human arm does not.

## Calli / PRONOTE protocol (automatic dictation to the desktop writer)

The Moodle protocol above is historical. It excludes read-back for the human, so it is not a fair comparison for Calli. No Calli/PRONOTE human baseline exists yet, and any chart that uses estimated human times must label them as estimates, kept outside `runs/` and the scoreboard.

Both arms share:

- **Initial state:** the same PRONOTE class, subject and period (3A, FRANCAIS, Trimestre 1), and the same pupils, with their comment cells empty or holding the same previous values.
- **Texts:** the same exact comment texts, e.g. from `data/truth.csv`, given in the same order.
- **Success check:** the same final-state check for every item. One independent person opens each cell afterwards and compares it with the expected text after `agent.queue` normalisation. A comment counts only if it matches.

**Human arm (optional, manual timings):**

- The person navigates to each pupil, types the text, saves, and then reads the cell back. Reading back is part of the task, as it is for the agent.
- Record two times: *active time*, the time hands and eyes are on the task, and *elapsed time*, from the first keystroke to the last check.

**Calli arm:**

- The teacher dictates in `/workspace` and the writer runs `run_writer --runtime local --queue ...` on the Windows guest.
- Teacher active time is dictation plus any correction. Measure it with a stopwatch, or estimate it and label it as an estimate.
- Agent elapsed time is the `elapsed_s` in `summary.json`, measured per run. Total latency runs from the first dictation to the last verified read-back in `journal.jsonl`.
- Report verified, mismatch, unknown and aborted counts from the journal. Unknown never counts as a success.

**Runtime state:**

- *Cold:* the first local session on a machine downloads the runtime (about 60 MB) and starts it.
- *Warm:* the runtime is already installed.
- Report cold and warm runs separately.

**What to expect, and what is not yet measured:**

- Each agent step takes one model call plus one screenshot. Per comment, that means navigation, typing and read-back steps, plus the `next_item` and `report_result` tool calls.
- The historical 10/10 PRONOTE run took 300.8 s. It used approved texts with the earlier writer, so it is not a measurement of the automatic flow.
- The source preparation (15.7 s) runs in parallel and is not on the writing path.
- The automatic end-to-end write has not been verified yet. Only a real run's `summary.json` and journal can provide its numbers.

**Sample size:** with n = 1 to 3 runs per arm, report every run and no averages or significance claims.
