"""Build the 20 s PRONOTE footage clip of the explainer from the original H session screenshots.

Source: H session 200ea4e3-78b5-438c-9cf5-431211c253e4, run runs/20261107-152520 (real PRONOTE
desktop client, Windows trial, fictitious students). The screenshots are used unretouched and in
chronological order; each output frame is a scaled view of one screenshot (full screen, or the top
of the screen with the appreciation grid, zoomed), a label bar and the subtitle of the supplied
narration. The narration (ElevenLabs Alice) starts at NARRATION_AT seconds, at its natural tempo.

The screenshots are JPEG data saved with a .png name; they are read as-is and never modified.
Writes the clip and a manifest with the exact source frame and output timing of every shot.

Usage:
    python scripts/pronote_footage.py <asset_dir> --out video/out/footage-pronote-20s.mp4 \
        --manifest video/footage/pronote-200ea4e3/manifest.json
<asset_dir> holds frames/frame-NNNN.png, captions.json, source.json, narration.json and pronote-narration.mp3.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # Pillow is only needed to render, not to import the shot list
    from PIL import Image, ImageDraw, ImageFont

FPS = 30
DURATION = 20.0
SIZE = (1920, 1080)
LABEL = "PRONOTE trial | Recorded H session | Sped up"
SESSION = "200ea4e3-78b5-438c-9cf5-431211c253e4"
RUN = "20261107-152520"
NARRATION_AT = 0.5
BAND_TOP, BAND_BOTTOM = 60, 900  # screenshot area; label above, subtitles below
FULL = (0, 0, 1280, 800)  # whole screen
GRID = (0, 0, 1280, 620)  # title bar, menus and the whole appreciation grid
ZOOM_IN = 0.5  # seconds of the move from FULL to GRID, at the start of the first zoomed shot

# (source frame, seconds on screen, view). Chronological; frames 7-10 (four scroll attempts
# that do not move the list) and everything after frame 25 are left out.
SHOTS: list[tuple[int, float, str]] = [
    (1, 1.5, "full"),   # Saisie des appréciations, 3A FRANCAIS, Trimestre 1
    (2, 1.0, "full"),
    (3, 1.0, "grid"),   # BERNARD Lucas: cell open, 0/255
    (4, 1.5, "grid"),   # text typed, 119/255
    (5, 1.3, "grid"),   # comment shown in the row, title "en modification"
    (6, 1.7, "grid"),   # Ctrl+S done, then read back
    (11, 0.6, "grid"),  # PETIT Lucas
    (12, 0.6, "grid"),
    (13, 0.9, "grid"),
    (14, 0.9, "grid"),
    (15, 1.0, "grid"),
    (16, 0.7, "grid"),  # LAMBERT Gaël (item p03, carries the injection sentence)
    (17, 0.7, "grid"),
    (18, 0.7, "grid"),
    (19, 0.7, "grid"),
    (20, 0.7, "grid"),
    (21, 0.9, "grid"),  # FONTAINE Gaëlle
    (22, 0.9, "grid"),
    (23, 0.9, "grid"),
    (24, 0.9, "grid"),
    (25, 0.9, "grid"),
]

# Subtitles from narration.json, split at the pauses of the recording (silencedetect, -45 dB, 0.15 s),
# times in clip seconds (narration offset included).
SUBTITLES: list[tuple[float, float, str]] = [
    (0.5, 4.5, "Here is the real Pronote desktop, inside a Windows trial."),
    (4.7, 8.6, "The agent writes an approved comment, saves it, and reads it back."),
    (9.0, 12.2, "Ten comments were verified in five minutes."),
    (12.3, 14.3, "These are fictitious students."),
    (14.4, 16.6, "This recording is sped up."),
]

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    from PIL import ImageFont

    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for p in (FONT_DIR / name, Path("/System/Library/Fonts/Supplemental/Arial.ttf")):
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def ease(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def lerp_box(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def wrap(d: ImageDraw.ImageDraw, text: str, f, max_w: int) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=f) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def compose(img: Image.Image, box, subtitle: str, fonts) -> Image.Image:
    from PIL import Image, ImageDraw

    label_f, cite_f, sub_f = fonts
    canvas = Image.new("RGB", SIZE, (20, 20, 20))
    crop = img.crop(tuple(round(v) for v in box))
    h = BAND_BOTTOM - BAND_TOP
    w = round(crop.width * h / crop.height)
    view = crop.resize((w, h), Image.LANCZOS)
    canvas.paste(view, ((SIZE[0] - w) // 2, BAND_TOP))
    d = ImageDraw.Draw(canvas)
    d.text((40, 14), LABEL, font=label_f, fill=(255, 255, 255))
    cite = f"H session {SESSION[:8]} · run {RUN} · fictitious students"
    d.text((SIZE[0] - 40 - d.textlength(cite, font=cite_f), 19), cite, font=cite_f, fill=(190, 190, 190))
    if subtitle:
        lines = wrap(d, subtitle, sub_f, SIZE[0] - 200)
        y = BAND_BOTTOM + (SIZE[1] - BAND_BOTTOM - 56 * len(lines)) // 2
        for line in lines:
            d.text(((SIZE[0] - d.textlength(line, font=sub_f)) / 2, y), line, font=sub_f, fill=(255, 255, 255))
            y += 56
    return canvas


def subtitle_at(t: float) -> str:
    return next((s for a, b, s in SUBTITLES if a <= t < b), "")


def main() -> int:
    from PIL import Image

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("assets")
    p.add_argument("--out", required=True)
    p.add_argument("--manifest", required=True)
    args = p.parse_args()
    assets = Path(args.assets)
    total = sum(s for _, s, _ in SHOTS)
    assert abs(total - DURATION) < 1e-6, total
    captions = {c["frame"]: re.sub(r"\s*\[[a-z_, ]+\]\s*$", "", c.get("caption") or "")
                for c in json.loads((assets / "captions.json").read_text(encoding="utf-8"))}
    narration = json.loads((assets / "narration.json").read_text(encoding="utf-8"))
    assert " ".join(s for _, _, s in SUBTITLES) == narration["text"], "subtitles must be the supplied transcript"
    fonts = (font(26, bold=True), font(22), font(44))

    shots, frame_no, t0 = [], 0, 0.0
    first_zoom = next(i for i, (_, _, v) in enumerate(SHOTS) if v == "grid")
    with tempfile.TemporaryDirectory() as tmp:
        for i, (n, secs, view) in enumerate(SHOTS):
            src = assets / "frames" / f"frame-{n:04d}.png"
            img = Image.open(src).convert("RGB")
            assert img.size == (1280, 800), (src, img.size)
            count = round((t0 + secs) * FPS) - round(t0 * FPS)
            for k in range(count):
                t = (frame_no + k) / FPS
                if view == "full":
                    box = FULL
                elif i == first_zoom:
                    box = lerp_box(FULL, GRID, ease(k / (ZOOM_IN * FPS)))
                else:
                    box = GRID
                compose(img, box, subtitle_at(t), fonts).save(Path(tmp) / f"f-{frame_no + k:04d}.png")
            shots.append({
                "source_frame": n,
                "source_file": f"frames/frame-{n:04d}.png",
                "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                "view": view,
                "start_s": round(t0, 3),
                "end_s": round(t0 + secs, 3),
                "out_frames": [frame_no, frame_no + count - 1],
                "original_caption": captions.get(n, ""),
            })
            frame_no += count
            t0 += secs
        assert frame_no == round(DURATION * FPS), frame_no
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        delay = round(NARRATION_AT * 1000)
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-framerate", str(FPS), "-i", str(Path(tmp) / "f-%04d.png"),
            "-i", str(assets / "pronote-narration.mp3"),
            "-filter_complex",
            (f"[1:a]aresample=48000,aformat=channel_layouts=stereo,adelay={delay}:all=1,"
             f"apad=whole_dur={DURATION},atrim=duration={DURATION}[a]"),
            "-map", "0:v", "-map", "[a]", "-t", str(DURATION),
            "-r", str(FPS), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "18",
            "-c:a", "aac", "-b:a", "160k", str(out),
        ], check=True)

    manifest = {
        "session_id": SESSION,
        "run_id": RUN,
        "source": "H session observation screenshots (JPEG data in files named .png), unretouched, chronological",
        "target": "PRONOTE desktop client, Windows trial; fictitious students",
        "what_it_shows": "the approved-CSV writer run: each cell is written from the approved text, saved (Ctrl+S) "
                         "and read back by the agent (read-backs in runs/20261107-152520/journal.jsonl). "
                         "No live speech and no live approval is recorded here.",
        "output": {"file": str(out), "size": list(SIZE), "fps": FPS, "duration_s": DURATION},
        "views": {"full": list(FULL), "grid": list(GRID), "zoom_in_s": ZOOM_IN,
                  "screen_area_px": [0, BAND_TOP, SIZE[0], BAND_BOTTOM]},
        "label": LABEL,
        "narration": {"file": "pronote-narration.mp3", "start_s": NARRATION_AT, "tempo": 1.0,
                      "voice": narration.get("voice"), "model": narration.get("model"), "text": narration["text"]},
        "subtitles": [{"start_s": a, "end_s": b, "text": s} for a, b, s in SUBTITLES],
        "omitted_frames": "7-10 (scroll attempts with no change on screen) and 26-62 (later items, same pattern)",
        "shots": shots,
    }
    Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(args.manifest).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({frame_no} frames) and {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
