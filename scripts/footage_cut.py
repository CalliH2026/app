"""Cut a captioned footage clip from the frames exported by scripts/session_to_video.py.

Why not ffmpeg's subtitles filter: the local ffmpeg build has no libass. Captions are drawn on each
frame with Pillow (a dark bar at the bottom, the agent's own sentence for that step), then ffmpeg
assembles the clip at the requested frame rate with a silent audio track, so it concatenates cleanly
with the Remotion parts.

Usage:
    python scripts/footage_cut.py <frames_dir> <captions.json> --from 30 --to 54 --fps 1.25 \
        --out video/footage/moodle-20s.mp4 [--label "Moodle demo school, H session 405d5130, 7 Nov 2026"]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BLUR_BOXES: list[tuple[int, int, int, int]] = []
FONT_CANDIDATES = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:2]


def annotate(src: Path, dst: Path, caption: str, label: str | None, size=(1920, 1080)) -> None:
    img = Image.open(src).convert("RGB")
    img.thumbnail(size, Image.LANCZOS)
    canvas = Image.new("RGB", size, (20, 33, 61))
    canvas.paste(img, ((size[0] - img.width) // 2, (size[1] - img.height) // 2))
    for box in BLUR_BOXES:  # canvas coordinates; faces and e-mails of the demo accounts stay private
        region = canvas.crop(box)
        canvas.paste(region.resize((max(1, (box[2] - box[0]) // 24), max(1, (box[3] - box[1]) // 24)), Image.BILINEAR)
                     .resize((box[2] - box[0], box[3] - box[1]), Image.BILINEAR), box)
    d = ImageDraw.Draw(canvas, "RGBA")
    font = load_font(34)
    small = load_font(22)
    lines = wrap(d, caption, font, size[0] - 240)
    if lines:
        h = 36 + 44 * len(lines)
        y0 = size[1] - h - 70
        d.rounded_rectangle([100, y0, size[0] - 100, y0 + h], radius=16, fill=(20, 20, 20, 215))
        for i, line in enumerate(lines):
            d.text((130, y0 + 18 + 44 * i), line, font=font, fill=(255, 255, 255, 255))
    if label:
        tw = d.textlength(label, font=small)
        d.rounded_rectangle([size[0] - tw - 60, 24, size[0] - 24, 64], radius=10, fill=(20, 20, 20, 180))
        d.text((size[0] - tw - 42, 31), label, font=small, fill=(255, 255, 255, 255))
    canvas.save(dst, "PNG")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("frames_dir")
    p.add_argument("captions")
    p.add_argument("--from", dest="start", type=int, required=True, help="first frame number (1-based, inclusive)")
    p.add_argument("--to", dest="end", type=int, required=True, help="last frame number (inclusive)")
    p.add_argument("--fps", type=float, default=1.25)
    p.add_argument("--out", required=True)
    p.add_argument("--label", default=None)
    p.add_argument("--keep-tool-tag", action="store_true", help="keep the [tool_name] suffix in captions")
    p.add_argument("--blur", action="append", default=[], metavar="X0,Y0,X1,Y1",
                   help="pixelate this canvas rectangle on every frame (repeatable), e.g. the demo user's photo and e-mail")
    args = p.parse_args()
    global BLUR_BOXES
    BLUR_BOXES = [tuple(int(v) for v in b.split(",")) for b in args.blur]

    import re

    def clean(text: str) -> str:
        # drop the trailing tool tag added by session_to_video ("...  [click_web]") unless asked to keep it
        return text if args.keep_tool_tag else re.sub(r"\s*\[[a-z_, ]+\]\s*$", "", text)

    caps = {c["frame"]: clean(c.get("caption") or "") for c in json.loads(Path(args.captions).read_text(encoding="utf-8"))}
    frames = Path(args.frames_dir)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        n = 0
        last_caption = ""
        for i in range(args.start, args.end + 1):
            src = frames / f"frame-{i:04d}.png"
            if not src.exists():
                continue
            n += 1
            last_caption = caps.get(i) or last_caption
            annotate(src, Path(tmp) / f"f-{n:04d}.png", last_caption, args.label)
        if n == 0:
            raise SystemExit("no frames in range")
        if shutil.which("ffmpeg") is None:
            raise SystemExit("ffmpeg not found")
        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-framerate", str(args.fps), "-i", str(Path(tmp) / "f-%04d.png"),
               "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
               "-shortest", "-r", "30", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "20",
               "-c:a", "aac", "-b:a", "128k", str(out)]
        subprocess.run(cmd, check=True)
    dur = n / args.fps
    print(f"wrote {out} ({n} frames, {dur:.1f} s at {args.fps} fps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
