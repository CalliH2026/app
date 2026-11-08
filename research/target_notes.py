"""Draft target notes for a new school application from its official documentation (Linkup).

When Calligraphe is pointed at a new application, the agent needs notes like
agent/targets/moodle.md or agent/targets/pronote.md: the click path to the per-student
comment, the field names as displayed, and what the application does on save. Those notes
are verified by hand on the real software. This drafts a starting point from the
application's documentation, with its sources, so a human reviews and trims it instead of
starting from a blank page. The draft is never loaded by the writer loop.

    python -m research.target_notes --app "PRONOTE" --task "saisie des appréciations par matière" \
        --out agent/targets/pronote.draft.md

Environment: LINKUP_API_KEY (never printed). Without it, nothing is sent and the command exits 2.
Needs the optional extra: pip install -e ".[research]".
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path
from typing import Any

BANNER = "Draft from official documentation, not yet verified against the application"
_LIST_MARK = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý«\"'])")


def build_query(app: str, task: str) -> str:
    return (
        f"{app}, {task}: according to the official documentation of {app}, what is the exact click path "
        f"(menus, tabs, buttons, in order) a teacher follows to enter and save the comment of one student, "
        f"what are the names of the fields, columns and buttons exactly as displayed in {app}, "
        f"and what does {app} do on save (confirmation message, autosave, validation step)? "
        f"Answer as numbered steps and keep the displayed names in the application's language."
    )


def as_procedure(answer: str) -> list[str]:
    """The answer as a list of steps: its own list items if it has some, else its lines or sentences."""
    lines = [ln.strip() for ln in answer.strip().splitlines() if ln.strip()]
    if any(_LIST_MARK.match(ln) for ln in lines):
        steps: list[str] = []
        for ln in lines:
            if _LIST_MARK.match(ln):
                steps.append(_LIST_MARK.sub("", ln, count=1))
            elif steps:
                steps[-1] += " " + ln
            else:
                steps.append(ln)
        return steps
    if len(lines) > 1:
        return lines
    return [s.strip() for s in _SENTENCE_END.split(lines[0])] if lines else []


def _field(obj: Any, name: str) -> str:
    value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
    return str(value or "").strip()


def render_draft(app: str, task: str, answer: str, sources: list[Any], today: dt.date) -> str:
    out = [f"# {app}: {task}", "", f"> **{BANNER}.**", "", "## Procedure", ""]
    steps = as_procedure(answer)
    out += [f"{i}. {s}" for i, s in enumerate(steps, 1)] or ["(the search returned no answer)"]
    out += ["", "## Sources", ""]
    seen: set[str] = set()
    for src in sources:
        url = _field(src, "url")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(f"- {_field(src, 'name') or url}: <{url}>")
    if not seen:
        out.append("- (no source returned)")
    out += ["", f"Drafted on {today.isoformat()} with Linkup; review every step on the application before use.", ""]
    return "\n".join(out)


def default_client() -> Any:
    from linkup import LinkupClient  # optional extra `research`, imported only when a key is set

    return LinkupClient(api_key=os.environ["LINKUP_API_KEY"])


def draft(app: str, task: str, client: Any, today: dt.date | None = None) -> str:
    response = client.search(query=build_query(app, task), depth="deep", output_type="sourcedAnswer")
    return render_draft(app, task, _field(response, "answer"), list(getattr(response, "sources", None) or []),
                        today or dt.date.today())


def main(argv: list[str] | None = None, client: Any = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--app", required=True, help='application name as its publisher writes it, e.g. "PRONOTE"')
    p.add_argument("--task", required=True, help="the screen or task, in the application's language")
    p.add_argument("--out", required=True, help="draft path, e.g. agent/targets/pronote.draft.md")
    args = p.parse_args(argv)

    if client is None:
        if not os.environ.get("LINKUP_API_KEY"):
            print("LINKUP_API_KEY is not set: nothing drafted", file=sys.stderr)
            return 2
        client = default_client()
    text = draft(args.app, args.task, client)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"[research] draft written to {out}; review it against the application before use")
    return 0


if __name__ == "__main__":
    sys.exit(main())
