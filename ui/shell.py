"""Calli, one command: Francois Amat's teacher workspace (mvp/) with Calli's appreciations module mounted at /calli.

    python -m ui.shell [--queue runs/queue.jsonl] [--roster data/roster.csv] [--course "3A, FRANCAIS, Trimestre 1"]
                       [--data-dir runs/shell] [--port 8000] [--stop]

Loopback only. Never starts Calli's writer (run it separately on the PRONOTE machine) and makes no provider call by
itself; providers are used by authorised flows when the server has the keys. The family view may start a
background preparation on opening when FAMILY_H_LIVE=1. --stop sets Calli's
STOP before serving (review mode: nothing can be queued). With PUBLIC_URL set the Calli module is not mounted.
Needs: pip install -e '.[shell]' (and '.[voice]' for live dictation with GLADIA_API_KEY).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from agent.queue_store import DEFAULT_PATH, QueueStore
from voice.roster import DEFAULT_ROSTER

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COURSE = "3A, FRANCAIS, Trimestre 1"
HOST = "127.0.0.1"


def shell_env(queue: Path, roster: Path, course: str, data_dir: Path, port: int) -> dict[str, str]:
    """Server configuration for mvp.app and its optional Calli module (see mvp/calli_module.py)."""
    return {"CALLI_SOURCE": str(ROOT), "CALLI_QUEUE": str(queue.resolve()), "CALLI_ROSTER": str(roster.resolve()),
            "CALLI_COURSE": course, "PRONOTE_DATA_DIR": str(data_dir.resolve()), "H_LOCAL_PREVIEW_PORT": str(port)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--queue", default=str(DEFAULT_PATH), help="Calli live queue, shared with the writer")
    p.add_argument("--roster", default=str(DEFAULT_ROSTER), help="native roster CSV")
    p.add_argument("--course", default=DEFAULT_COURSE, help="exact class, subject and period of that roster")
    p.add_argument("--data-dir", default="runs/shell", help="state directory of the workspace (reports, outings)")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--stop", action="store_true", help="set Calli's STOP before serving (review mode)")
    p.add_argument("--native-companion", action="store_true",
                   help="also start the workspace's native PRONOTE companion services (off by default)")
    args = p.parse_args(argv)
    queue, data_dir = Path(args.queue), Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    queue.parent.mkdir(parents=True, exist_ok=True)
    if args.stop:
        QueueStore(queue).stop(reason="preview")
    os.environ.update(shell_env(queue, Path(args.roster), args.course, data_dir, args.port))
    if os.environ.get("PUBLIC_URL"):
        print("[calli] PUBLIC_URL is set: the appreciations module stays unmounted (no remote authentication).")

    import uvicorn

    print(f"[calli] http://{HOST}:{args.port}  queue={queue} course={args.course!r} stop={QueueStore(queue).stop_requested()}")
    uvicorn.run("mvp.app:app", host=HOST, port=args.port, lifespan="on" if args.native_companion else "off",
                log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
