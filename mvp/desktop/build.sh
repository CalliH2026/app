#!/bin/sh
# Maintainer build only. The teacher opens the resulting .app, never this script.
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$PROJECT_DIR"
uv venv --allow-existing .venv-pilot --python 3.12
uv pip install --python .venv-pilot/bin/python -r mvp/desktop/requirements.txt
PLAYWRIGHT_BROWSERS_PATH=0 .venv-pilot/bin/python -m playwright install chromium --no-shell
PLAYWRIGHT_BROWSERS_PATH=0 .venv-pilot/bin/pyinstaller \
  --noconfirm --windowed --onedir --name 'PRONOTE Pilote' \
  --osx-bundle-identifier fr.parallele.pronote-pilot \
  --distpath dist-pilot --workpath build-pilot/work --specpath build-pilot \
  --additional-hooks-dir "$PROJECT_DIR/mvp/desktop/hooks" \
  --paths . --add-data "$PROJECT_DIR/mvp/desktop/pilot.html:mvp/desktop" \
  --add-data "$PROJECT_DIR/mvp/desktop/pilot.js:mvp/desktop" \
  --collect-all pronotepy --collect-all Crypto \
  --hidden-import uvicorn.logging --hidden-import uvicorn.loops.asyncio \
  --hidden-import uvicorn.protocols.http.h11_impl --hidden-import uvicorn.lifespan.off \
  mvp/desktop/launcher.py
BROWSER_DIR=$(.venv-pilot/bin/python -c 'import pathlib, playwright; print(pathlib.Path(playwright.__file__).parent / "driver/package/.local-browsers")')
ditto "$BROWSER_DIR" 'dist-pilot/PRONOTE Pilote.app/Contents/Resources/browsers'
codesign --force --sign - 'dist-pilot/PRONOTE Pilote.app'
# ZIP preserves the macOS application bundle and its symlinks.
ditto -c -k --sequesterRsrc --keepParent 'dist-pilot/PRONOTE Pilote.app' 'dist-pilot/PRONOTE-Pilote-Mac-Apple-Silicon.zip'
