"""Deterministic UI capture of the unified Calli shell for the video, with fictional data only.

Starts `python -m ui.shell --stop` on a fresh temporary queue and state directory (no keys are passed, STOP is
set, no writer runs), then captures each workspace page at desktop and narrow sizes. Nothing is generated or
claimed: saved real results are only shown if you point --data-dir at a copy of them.

    pip install playwright && python -m playwright install chromium     # capture-only dependency
    python scripts/capture_shell.py --out runs/capture [--data-dir <copy of saved results>] [--cdp http://localhost:29229]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

PAGES = ("today", "management", "appreciations", "outings", "reports", "agent")
SIZES = {"desktop": (1440, 950), "narrow": (420, 900)}
KEYS = ("HAI_API_KEY", "H_COMPANY_API_KEY", "GLADIA_API_KEY", "LINKUP_API_KEY", "DEVIN_API", "DEVIN_API_KEY",
        "DEMOBRO_API_KEY", "PUBLIC_URL")


async def capture(url: str, out: Path, cdp: str | None) -> list[str]:
    from playwright.async_api import async_playwright

    lines = []
    async with async_playwright() as p:
        browser = await (p.chromium.connect_over_cdp(cdp) if cdp else p.chromium.launch())
        context = browser.contexts[0] if cdp else await browser.new_context()
        for size, (width, height) in SIZES.items():
            page = await context.new_page()
            await page.set_viewport_size({"width": width, "height": height})
            errors: list[str] = []
            page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
            await page.goto(url)
            await page.wait_for_timeout(2500)
            for name in PAGES:
                await page.evaluate(f"document.querySelector('[data-page=\"{name}\"]')?.click()")
                await page.wait_for_timeout(3000)
                path = out / f"{size}-{name}.png"
                await page.screenshot(path=str(path))
                lines.append(f"{path} errors={errors[-1:] or 'none'}")
            await page.close()
        if not cdp:
            await browser.close()
    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default="runs/capture")
    p.add_argument("--data-dir", default=None, help="workspace state to show (default: a fresh empty one)")
    p.add_argument("--port", type=int, default=8790)
    p.add_argument("--cdp", default=None, help="use an already running Chrome (DevTools URL) instead of launching one")
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="calli-capture-"))
    env = {k: v for k, v in os.environ.items() if k not in KEYS}
    cmd = [sys.executable, "-m", "ui.shell", "--stop", "--port", str(args.port), "--queue", str(tmp / "queue.jsonl"),
           "--data-dir", args.data_dir or str(tmp / "data")]
    server = subprocess.Popen(cmd, env=env, cwd=Path(__file__).resolve().parents[1])
    try:
        url = f"http://127.0.0.1:{args.port}/"
        for _ in range(60):
            try:
                urllib.request.urlopen(url, timeout=1)
                break
            except OSError:
                time.sleep(0.5)
        for line in asyncio.run(capture(url, out, args.cdp)):
            print(line)
    finally:
        server.terminate()
        server.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
