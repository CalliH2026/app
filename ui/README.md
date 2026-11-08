# ui/

The teacher's approval screen: dictated sentence in, proposal (student, text) out; approve, correct, STOP; the live queue and the journal on the right. See [docs/ui.md](../docs/ui.md) for how to run it with the writer loop.

- `app.py`: FastAPI server on http://127.0.0.1:8765 (`pip install -e ".[ui]"`, then `python -m ui.app`).
- `static/`: one HTML page, one script, one CSS file with variables; no build step. Restyle `style.css` freely; keep state as a word and an icon, never color alone.
- `static/avatars/`: one illustrated SVG per fictitious student (`scripts/make_avatars.py`, DiceBear "Adventurer" by Lisa Wischofsky, CC BY 4.0); initials in a coloured circle when a file is missing.
