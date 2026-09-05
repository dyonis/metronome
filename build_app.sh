#!/usr/bin/env bash
# Сборка standalone-приложения "Metronome.app" для macOS.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Нет .venv — создаю и ставлю зависимости…"
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
echo "Готово: dist/Metronome.app"
echo "Запуск: open 'dist/Metronome.app'  (или перетащи в /Applications)"
