"""The PRONOTE footage shot list, subtitles and committed manifest agree (offline, no Pillow needed)."""

import hashlib
import json
from pathlib import Path

from scripts import pronote_footage as pf

FOOTAGE = Path(__file__).resolve().parents[1] / "video" / "footage" / "pronote-200ea4e3"


def test_shots_are_chronological_and_fill_the_clip():
    frames = [n for n, _, _ in pf.SHOTS]
    assert frames == sorted(set(frames))
    assert abs(sum(s for _, s, _ in pf.SHOTS) - pf.DURATION) < 1e-6
    assert {v for _, _, v in pf.SHOTS} == {"full", "grid"}
    assert pf.SHOTS[0][2] == "full"


def test_subtitles_are_the_supplied_transcript_in_order():
    narration = json.loads((FOOTAGE / "narration.json").read_text(encoding="utf-8"))
    assert " ".join(s for _, _, s in pf.SUBTITLES) == narration["text"]
    ends = [0.0] + [b for _, b, _ in pf.SUBTITLES]
    for (a, b, _), prev_end in zip(pf.SUBTITLES, ends):
        assert prev_end <= a < b <= pf.DURATION
    assert pf.SUBTITLES[0][0] == pf.NARRATION_AT
    assert pf.subtitle_at(0.0) == "" and pf.subtitle_at(1.0) == pf.SUBTITLES[0][2]


def test_manifest_matches_shot_list():
    m = json.loads((FOOTAGE / "manifest.json").read_text(encoding="utf-8"))
    assert (m["session_id"], m["run_id"], m["label"]) == (pf.SESSION, pf.RUN, pf.LABEL)
    assert [(s["source_frame"], s["view"]) for s in m["shots"]] == [(n, v) for n, _, v in pf.SHOTS]
    t, f = 0.0, 0
    for shot, (_, secs, _) in zip(m["shots"], pf.SHOTS):
        count = round((t + secs) * pf.FPS) - round(t * pf.FPS)
        assert (shot["start_s"], shot["end_s"]) == (round(t, 3), round(t + secs, 3))
        assert shot["out_frames"] == [f, f + count - 1]
        t, f = t + secs, f + count
    assert f == round(pf.DURATION * pf.FPS)
    assert m["subtitles"] == [{"start_s": a, "end_s": b, "text": s} for a, b, s in pf.SUBTITLES]
    assert m["narration"]["start_s"] == pf.NARRATION_AT


def test_committed_evidence_stills_are_listed_source_frames():
    m = json.loads((FOOTAGE / "manifest.json").read_text(encoding="utf-8"))
    sha = {s["source_frame"]: s["source_sha256"] for s in m["shots"]}
    for jpg in sorted((FOOTAGE / "evidence").glob("frame-*.jpg")):
        n = int(jpg.stem.split("-")[1])
        assert hashlib.sha256(jpg.read_bytes()).hexdigest() == sha[n], jpg.name
