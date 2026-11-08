#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"
if [ ! -x .venv/bin/python ]; then
  uv venv --python 3.12 .venv
fi
command -v ffmpeg >/dev/null || { echo "Installer FFmpeg avant de lancer la démo."; exit 1; }
command -v ffprobe >/dev/null || { echo "ffprobe est requis (fourni avec FFmpeg)."; exit 1; }
uv pip install --quiet --python .venv/bin/python -r mvp/requirements.txt
.venv/bin/python -m mvp.video
exec .venv/bin/uvicorn mvp.app:app --host 127.0.0.1 --port 8000 --no-access-log
