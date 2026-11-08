# Approval screen and live queue

The teacher's screen (`ui/app.py`) and the writer loop (`agent/run_writer.py --queue`) are two processes joined by one file, `runs/queue.jsonl` (`agent/queue_store.py`). The teacher keeps dictating while the agent writes: an item approved on the screen is picked up at the agent's next `next_item` call.

```
teacher ──> ui/app.py ──append──> runs/queue.jsonl <──next_pending / update── run_writer.py --queue ──> H agent
              │  STOP / Resume ──> runs/STOP                     reads STOP ─┘
              └── polls /api/state every 2 s: queue items + last journal lines (runs/<latest>/journal.jsonl)
```

## Run the screen

```
pip install -e ".[ui]"                      # fastapi + uvicorn
python -m ui.app                            # http://127.0.0.1:8765, data/roster.csv, runs/queue.jsonl
python -m ui.app --roster data/roster_moodle.csv --course "Mindful Course Creation"   # Moodle demo
```

Options: `--queue PATH` (default `runs/queue.jsonl`), `--roster PATH` (`student_id, display_name, aliases`), `--journal PATH` (default: the most recently modified `runs/*/journal.jsonl`), `--course` (stored with each approved item, editable on the page), `--host` (loopback only: 127.0.0.1, localhost or ::1; the screen has no authentication, and it refuses requests whose Host or Origin is another site, and POSTs that are not JSON), `--port`.

On the page:

- **Dictation**: type or paste a sentence; Enter (or Propose) sends it to `voice.structurer.RuleBasedStructurer`. Voice will feed the same box later.
- **Proposal**: the student candidates and the text. One candidate is preselected; two or more (a tie, such as two Lucas) are shown with none selected, and Approve stays disabled until the teacher picks one. No recognized name: the whole-class list opens.
- **Approve** (or Enter when one student is selected) appends a `pending` item. Approving the same text for the same student twice while it is still open does not create a second write. A student who is not on the roster is refused.
- **Correct** makes the text editable and opens the whole-class list, before approving. "Non, plutôt ..." and "non, c'était pour Léa" dictated next apply to the current proposal.
- **STOP** (or Escape, then confirm on the page) creates `runs/STOP`, turns every `pending` item into `aborted`, and shows the red banner "stopped: no new write will start". The item being written finishes its read-back; nothing is reverted. **Resume** removes the STOP file; aborted items stay aborted, approve them again if needed.
- **Queue**: every item with the student's avatar, its state word and icon (○ pending, ◐ writing, ✔ verified, ✖ mismatch, ? not found, ■ aborted), the read-back text, similarity and seconds. A corrective write is shown under the mismatched item it corrects.
- **Journal**: the last 30 lines of the latest run's journal.
- **Class**: every student of the roster with their avatar. The same round 40 px avatar sits left of the name in the proposal and on each queue item.

## Run the loop in live mode

```
export HAI_API_KEY=...                      # never printed, never committed
python -m agent.run_writer --queue runs/queue.jsonl --target moodle --max-time 1800
```

`next_item` hands out the first pending item (it becomes `in_progress`); `report_result` decides the status by read-back comparison, exactly as in CSV mode, and writes it back to the queue file (`verified`, `mismatch` plus one corrective item `<id>-r1` right after it, `not_found`, `aborted`) along with the read-back, similarity and seconds. Every event also goes to `runs/<timestamp>/journal.jsonl`, which the screen shows.

When the queue is momentarily empty, `next_item` returns `{"wait": true, "seconds": 8, "message": "no approved item yet, call wait_web for 8 seconds then next_item again"}` instead of null, for at most `--idle-timeout` seconds (default 300) without an item; then it returns null and the session ends. A STOP file next to the queue file makes `next_item` return null at once. `--max-time` still caps the whole session; raise it for a long dictation.

`--dry-run` lists the queue without creating a session. CSV mode (`--items data/demo_items.csv`) is unchanged.

## Demo sequence

1. `python -m ui.app --roster data/roster_moodle.csv --course "Mindful Course Creation"` and open http://127.0.0.1:8765.
2. In a second terminal: `python -m agent.run_writer --queue runs/queue.jsonl --target moodle`.
3. Type (or dictate) "Barbara, participe bien, doit soigner la rédaction." and press Enter: the proposal shows Barbara Gardner and the text.
4. Press Enter (or Approve): the item appears on the right as ○ pending, then ◐ writing when the agent takes it.
5. Keep dictating the next comments while the agent writes.
6. Watch the item turn ✔ verified, with the read-back text and the similarity; a misread turns ✖ mismatch with its corrective write under it.
7. Press Escape and confirm: the red banner appears, pending items turn ■ aborted, and the agent's next `next_item` returns null.

`data/roster_moodle.csv` (the Mount Orange students of the demo course, same columns as `data/roster.csv`) is not generated by this module; without it, use `--roster data/roster.csv` and the fictitious class.

## Brand

The Calli logo is the final design by Liqin Wang for team Calli: `ui/static/brand/calli-logo.svg`, committed byte for byte
(SHA256 `264bca7de716858d01132c0c59d9253bc982b89db3caafe7268311cf9c362cd0`, viewBox 2048x682, white background).
It is shown as an `<img>` at a fixed height with automatic width (aspect ratio kept) in `/`, `/workspace`, `/sortie`,
`/entrainement` and the README. The small two-stroke `ui/static/calli-logo.svg` stays only as the browser tab icon,
where the wide logo would be unreadable.

## Avatars

The students are fictitious, so their faces are illustrations, never photos of real people. `ui/static/avatars/<student_id>.svg` (one per entry of `data/roster.csv` and `data/roster_moodle.csv`, 6 to 14 KB each) were fetched once from the DiceBear HTTP API by `python scripts/make_avatars.py` and are committed: the screen makes no network call. The seed is the student_id; long hair for girls and short hair for boys, natural hair colours, the four skin tones of the style, friendly expressions only, no facial hair. A new student needs a new file: add the first name to `GIRLS` or `BOYS` in the script and run it again (existing files are kept; `--force` fetches them all again). `tests/test_ui_avatars.py` fails when a roster entry has no file.

In the Calli workspace (`/workspace`), pupils s01 to s10 of `data/roster.csv` use `ui/static/avatars/calli-portraits-fictifs-ia-s01-s10.png` instead: entirely AI-generated portraits of fictional pupils (no real child, no stock photo), one 5x2 atlas (1983x793 PNG, SHA256 `da4b1a4b8fe2ed3675aaaa5ae72517fe3508442de7251228a68530dc49fd8a2d`) committed unchanged and shown as a CSS sprite (`background-size: 500% 200%`, columns 0/25/50/75/100 %, rows 0/100 %) in reading order s01..s10. The page says "Portraits fictifs générés par IA." under the class list. Other IDs and the `/` screen keep the SVG avatars or initials.

When a file is missing (or fails to load), the screen draws the student's initials in a coloured circle instead (`ui/app.py` returns `avatar: null`, `initials`, `color` for each student in `/api/config`).

Attribution: the avatars use the DiceBear style "Adventurer", a remix of ["Adventurer"](https://www.figma.com/community/file/1184595184137881796) by Lisa Wischofsky, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (commercial use and modification allowed with attribution; see https://www.dicebear.com/licenses/). Each SVG keeps this notice in its `<metadata>`.
