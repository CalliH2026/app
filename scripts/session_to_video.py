"""Turn an H session into a time-lapse video: the screenshots the agent saw, in order, with a caption per step.

This is the "real footage" of the demo video: no staging, no re-enactment. Every frame is a
platform-served screenshot of the session, fetched with the API key, and the caption is the
agent's action or event type at that step.

Usage:
    python scripts/session_to_video.py SESSION_ID --out video/footage/SESSION_ID --fps 1.25
Requires HAI_API_KEY in the environment and ffmpeg on the PATH.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def to_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    for attr in ("model_dump", "dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            with contextlib.suppress(Exception):
                return fn()
    try:
        return dict(vars(obj))
    except TypeError:
        return {"repr": repr(obj)}


def iter_events(client: Any, session_id: str):
    """All events in timestamp order. The API pages; `total` tells when we have everything."""
    page, got, size = 1, 0, 200  # the API caps page size at 200
    while True:
        res = client.sessions.list_session_events(session_id, page=page, size=size, sort="timestamp")
        d = to_dict(res)
        items = d.get("items") or d.get("events") or d.get("data") or []
        if not items:
            break
        for ev in items:
            got += 1
            yield to_dict(ev)
        total = d.get("total")
        if (total is not None and got >= int(total)) or len(items) < size:
            break
        page += 1


def find_image(ev: dict[str, Any]) -> dict[str, Any] | None:
    data = ev.get("data") if isinstance(ev.get("data"), dict) else ev
    img = data.get("image") if isinstance(data, dict) else None
    if isinstance(img, dict) and img.get("source"):
        return img
    return None


def caption_for(ev: dict[str, Any]) -> str | None:
    """A one-line caption from a policy event: what the agent said it was doing, and the tool it called."""
    data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
    if data.get("kind") != "policy_event":
        return None
    content = str(data.get("content") or "").strip().replace("\n", " ")
    tools = data.get("tool_reqs") or []
    if isinstance(tools, str):
        tools_s = tools
    else:
        tools_s = ", ".join(str(t.get("tool_name", "")) for t in tools if isinstance(t, dict))
    names = re.findall(r"'tool_name': '([a-z_]+)'", tools_s) if isinstance(tools_s, str) else []
    tool = ", ".join(names) if names else (tools_s if isinstance(tools_s, str) and len(tools_s) < 40 else "")
    cap = content[:110]
    return f"{cap}  [{tool}]" if tool else cap


def fetch_image(client: Any, session_id: str, img: dict[str, Any], api_key: str) -> bytes | None:
    src = str(img.get("source", ""))
    if img.get("type") == "base64":
        import base64
        return base64.b64decode(src.split(",", 1)[-1])
    # platform-served screenshots: the API URL needs the bearer, then redirects to a presigned object URL
    # that must be fetched WITHOUT the bearer (the object store rejects two auth mechanisms)
    with contextlib.suppress(Exception):
        import httpx

        with httpx.Client(timeout=60, follow_redirects=False) as hc:
            r = hc.get(src, headers={"Authorization": f"Bearer {api_key}", "User-Agent": "calligraphe/0.1"})
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                r = hc.get(r.headers["location"], headers={"User-Agent": "calligraphe/0.1"}, follow_redirects=True)
            if r.status_code == 200 and (r.headers.get("content-type", "").startswith("image/")
                                         or r.content[:4] == b"\x89PNG" or r.content[:3] == b"\xff\xd8\xff"):
                return r.content
    m = re.search(r"/resources/([^/]+)/([^/?]+)", src)
    if m:
        try:
            return b"".join(client.sessions.get_session_resource(session_id, m.group(1), m.group(2)))
        except Exception:
            return None
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("session_id")
    p.add_argument("--out", default=None, help="output folder (default video/footage/<session_id>)")
    p.add_argument("--fps", type=float, default=1.25, help="frames per second of the time-lapse")
    p.add_argument("--max-frames", type=int, default=400)
    p.add_argument("--no-captions", action="store_true")
    args = p.parse_args(argv)

    api_key = os.environ.get("HAI_API_KEY", "")
    if not api_key:
        print("HAI_API_KEY is not set", file=sys.stderr)
        return 2
    from hai_agents import Client

    client = Client()
    out = Path(args.out or f"video/footage/{args.session_id}")
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    captions: list[dict[str, Any]] = []
    pending_caption = ""
    n = 0
    for ev in iter_events(client, args.session_id):
        img = find_image(ev)
        if img is None:
            cap = caption_for(ev)
            if cap:
                pending_caption = cap
            continue
        data = fetch_image(client, args.session_id, img, api_key)
        if not data:
            continue
        n += 1
        path = frames_dir / f"frame-{n:04d}.png"
        path.write_bytes(data)
        captions.append({"frame": n, "caption": pending_caption, "ts": ev.get("timestamp")})
        pending_caption = ""
        if n >= args.max_frames:
            break
    (out / "captions.json").write_text(json.dumps(captions, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"{n} frames saved under {frames_dir}")
    if n == 0:
        return 1

    if shutil.which("ffmpeg") is None:
        print("ffmpeg not found; frames and captions are saved, assemble elsewhere")
        return 0
    mp4 = out / "timelapse.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(args.fps), "-i", str(frames_dir / "frame-%04d.png"),
           "-vf", "scale=1920:-2:flags=lanczos,format=yuv420p", "-c:v", "libx264", "-crf", "20", "-r", "30", str(mp4)]
    subprocess.run(cmd, check=True)
    print(f"wrote {mp4} ({mp4.stat().st_size // 1024} KB, {n / args.fps:.0f} s)")
    if not args.no_captions:
        srt = out / "captions.srt"
        lines = []
        for c in captions:
            start = (c["frame"] - 1) / args.fps
            end = c["frame"] / args.fps
            def ts(x: float) -> str:
                h = int(x // 3600); m = int(x % 3600 // 60); s = x % 60
                return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")
            text = c["caption"] or ""
            lines.append(f"{c['frame']}\n{ts(start)} --> {ts(end)}\n{text}\n")
        srt.write_text("\n".join(lines), encoding="utf-8")
        print(f"wrote {srt} (burn in with: ffmpeg -i timelapse.mp4 -vf subtitles=captions.srt out.mp4)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
