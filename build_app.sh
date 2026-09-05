#!/usr/bin/env bash
# Build the standalone "Metronome.app" for macOS.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "No .venv — creating it and installing dependencies…"
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
fi

./.venv/bin/pip install -q pyinstaller

./.venv/bin/pyinstaller \
  --name "Metronome" \
  --windowed \
  --noconfirm \
  --clean \
  --osx-bundle-identifier com.den.metronome \
  metronome.py

echo
echo "Done: dist/Metronome.app"
echo "Run: open 'dist/Metronome.app'  (or drag it into /Applications)"
