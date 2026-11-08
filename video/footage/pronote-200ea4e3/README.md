# PRONOTE footage, H session 200ea4e3

The 20 s clip `video/out/footage-pronote-20s.mp4` between part A and part B of `video/out/calligraphe-demo-v3.mp4`.

- Source: the observation screenshots of H session `200ea4e3-78b5-438c-9cf5-431211c253e4`, run `runs/20261107-152520` (real PRONOTE desktop client, Windows trial, 10 of 10 comments verified, fictitious students). It is the approved-CSV writer run: it records no live dictation and no live approval.
- `manifest.json`: every shot of the clip, with its source frame number, SHA-256 of the source file, view (full screen or grid zoom) and output time range, plus the narration offset and the subtitle times. Built by `scripts/pronote_footage.py` (Pillow + ffmpeg) from the 62 original screenshots, which are kept outside the repository; frames 1-6 and 11-25 are used, in order, unretouched.
- `evidence/`: four of the original screenshots, byte-identical (they are JPEG data; the session export named them `.png`): frame 1 (the Saisie des appréciations grid before the first write), 4 (BERNARD Lucas, 119/255 characters typed), 6 (saved, title bar no longer "en modification"), 18 (LAMBERT Gaël, item p03, the injection sentence written as plain text).
- `source.json`: the session and run ids of the export.
- `narration.json`, `pronote-narration.mp3`: the voice-over of the clip (ElevenLabs Alice, `eleven_multilingual_v2`), placed at 0.5 s at its natural tempo; the subtitles are its transcript.

Rebuild: `python scripts/pronote_footage.py <asset_dir> --out video/out/footage-pronote-20s.mp4 --manifest video/footage/pronote-200ea4e3/manifest.json`, where `<asset_dir>` holds `frames/`, `captions.json`, `narration.json` and `pronote-narration.mp3`.
