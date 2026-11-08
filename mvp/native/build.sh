#!/bin/sh
set -eu
MVP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BUNDLE="$MVP_DIR/data/H Parallel.app"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"
if command -v rsvg-convert >/dev/null 2>&1; then
  ICONSET="$MVP_DIR/data/Parallele.iconset"
  mkdir -p "$ICONSET"
  for SIZE in 16 32 128 256 512; do
    rsvg-convert -w "$SIZE" -h "$SIZE" "$MVP_DIR/static/parallel-app-icon.svg" -o "$ICONSET/icon_${SIZE}x${SIZE}.png"
    DOUBLE=$((SIZE * 2))
    rsvg-convert -w "$DOUBLE" -h "$DOUBLE" "$MVP_DIR/static/parallel-app-icon.svg" -o "$ICONSET/icon_${SIZE}x${SIZE}@2x.png"
  done
  iconutil -c icns "$ICONSET" -o "$BUNDLE/Contents/Resources/Parallele.icns"
fi
swiftc -swift-version 5 "$MVP_DIR/native/Notifier.swift" "$MVP_DIR/native/PronoteObserver.swift" -o "$BUNDLE/Contents/MacOS/HParallel" -framework Cocoa -framework UserNotifications -framework WebKit -framework Vision -framework ScreenCaptureKit -framework ApplicationServices
cat > "$BUNDLE/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict><key>CFBundleIdentifier</key><string>local.hcompany.parallel-demo</string><key>CFBundleName</key><string>Parallèle</string><key>CFBundleDisplayName</key><string>Parallèle</string><key>CFBundleIconFile</key><string>Parallele</string><key>CFBundleExecutable</key><string>HParallel</string><key>CFBundlePackageType</key><string>APPL</string><key>CFBundleVersion</key><string>1</string><key>LSUIElement</key><true/><key>NSUserNotificationAlertStyle</key><string>alert</string></dict></plist>
PLIST
codesign --force --sign - "$BUNDLE" >/dev/null 2>&1
printf '%s\n' "$BUNDLE"
