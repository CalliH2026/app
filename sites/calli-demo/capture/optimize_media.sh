#!/usr/bin/env bash
# Regenerates src/media/ from the exported captures (needs ffmpeg; not run by `npm run build`).
# Portrait sprite: WebP q90 re-encode of the a0d922e PNG (served at the original .png path as image/webp).
# Parent voice notes: 48 kbit/s MP3 of the saved 24 kHz mono WAV responses (served as audio/mpeg).
set -euo pipefail
cd "$(dirname "$0")/.."
ffmpeg -v error -y -i vendor/mvp/static/avatars/calli-portraits-fictifs-ia-s01-s10.png -c:v libwebp -quality 90 src/media/portraits-s01-s10.webp
ffmpeg -v error -y -i capture/raw/018.bin -c:a libmp3lame -b:a 48k -ar 24000 src/media/parent-voice-note-job.mp3
ffmpeg -v error -y -i capture/raw/019.bin -c:a libmp3lame -b:a 48k -ar 24000 src/media/parent-voice-note-points.mp3
