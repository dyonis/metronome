# Metronome (macOS)

A minimalist metronome — a small floating window that stays on top of all windows:

- tempo (BPM) with **-** / **+** buttons;
- **play / pause**;
- beats per measure with an accent on the first beat;
- beat dots that highlight the current beat;
- volume control;
- audio click (WAV synthesized on the fly, no external files needed).

The window is drawn with native macOS AppKit (PyObjC) — no Tk.

## Install

```bash
cd /Users/den/Develop/piano/metronome
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
source .venv/bin/activate
python metronome.py            # 120 BPM, 4 beats
python metronome.py --bpm 96 --beats 3
python metronome.py --volume 0.5
```

## Build an app (.app)

```bash
./build_app.sh
```

The bundle appears in `dist/Metronome.app` — you can drag it into `/Applications`.

## Controls

- **- / +** — tempo by 1 BPM (range 20–300).
- **▶ / ⏸** — start / stop.
- **- N beats +** — beats per measure (accent on the first beat).
- **Bottom slider** — click volume.
- **Space** — play/pause, **arrows** ↑↓←→ — tempo.
- **Drag** — with the mouse anywhere on the window.
- **Close** — the "✕" button, right-click on the window, or `Ctrl+C` in the terminal.

The window always stays above other windows and spaces, with no Dock icon.
