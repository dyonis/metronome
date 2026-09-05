#!/usr/bin/env python3
"""
Minimalist metronome for macOS.

A small floating window that stays on top of all windows, built with native
AppKit (PyObjC):
  - tempo (BPM) with - / + buttons;
  - play / pause;
  - beats per measure with an accent on the first beat;
  - visual beat dots;
  - audio click (WAV synthesized on the fly, no external files needed).

Run:
    python metronome.py            # 120 BPM, 4 beats
    python metronome.py --bpm 96 --beats 3
"""

import argparse
import math
import os
import queue
import signal
import struct
import sys
import tempfile
import threading
import time
import wave

MIN_BPM, MAX_BPM = 20, 300
MIN_BEATS, MAX_BEATS = 1, 12


def _write_click(path, freq=1000.0, ms=55, sr=44100, volume=0.6):
    """Synthesize a short click (decaying sine) into a WAV file."""
    n = int(sr * ms / 1000)
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            t = i / sr
            env = math.exp(-t * 70.0)          # fast decay -> no lingering tail
            s = math.sin(2 * math.pi * freq * t) * env * volume
            s = max(-1.0, min(1.0, s))
            frames += struct.pack("<h", int(s * 32767))
        w.writeframes(bytes(frames))


class Metronome(threading.Thread):
    """Precise tick scheduler running on its own thread.

    Sound is produced via the given play(accent: bool) callback.
    On each beat it puts ("beat", index) on the queue for UI highlighting.
    """

    def __init__(self, out_queue, play, bpm=120, beats=4):
        super().__init__(daemon=True)
        self.out_queue = out_queue
        self.play = play
        self.bpm = bpm
        self.beats = beats
        self._running = threading.Event()   # whether ticking is active
        self._wake = threading.Event()      # wake the thread on start
        self._stop = threading.Event()

    # --- control from the UI ---
    def set_bpm(self, bpm):
        self.bpm = max(MIN_BPM, min(MAX_BPM, int(bpm)))

    def set_beats(self, beats):
        self.beats = max(MIN_BEATS, min(MAX_BEATS, int(beats)))

    def start_ticking(self):
        self._running.set()
        self._wake.set()

    def stop_ticking(self):
        self._running.clear()
        self.out_queue.put(("beat", -1))

    def is_running(self):
        return self._running.is_set()

    def shutdown(self):
        self._stop.set()
        self._running.clear()
        self._wake.set()

    # --- the loop itself ---
    def run(self):
        while not self._stop.is_set():
            # Wait for a start command.
            if not self._running.is_set():
                self._wake.wait()
                self._wake.clear()
                if self._stop.is_set():
                    break
                if not self._running.is_set():
                    continue

            beat = 0
            next_time = time.perf_counter()
            while self._running.is_set() and not self._stop.is_set():
                accent = (beat % self.beats == 0)
                try:
                    self.play(accent)
                except Exception:
                    pass
                self.out_queue.put(("beat", beat % self.beats))

                beat = (beat + 1) % max(1, self.beats)
                next_time += 60.0 / self.bpm
                self._sleep_until(next_time)

    def _sleep_until(self, target):
        # Coarse sleep + short spin for accuracy, checking for stop.
        while not self._stop.is_set() and self._running.is_set():
            dt = target - time.perf_counter()
            if dt <= 0:
                return
            time.sleep(min(dt, 0.004))


def run_overlay(engine: Metronome, q: queue.Queue, snd_paths, volume=0.8):
    """Floating window on native AppKit (PyObjC)."""
    import warnings
    import objc
    warnings.filterwarnings("ignore", category=objc.ObjCPointerWarning)
    from AppKit import (
        NSApplication, NSApp, NSWindow, NSView, NSButton, NSSlider, NSTextField,
        NSColor, NSFont, NSSound, NSScreen, NSTimer, NSObject,
        NSBackingStoreBuffered,
        NSWindowStyleMaskBorderless, NSStatusWindowLevel, NSTextAlignmentCenter,
        NSApplicationActivationPolicyAccessory, NSRunLoop, NSRunLoopCommonModes,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary,
        NSWindowCollectionBehaviorFullScreenAuxiliary,
        NSForegroundColorAttributeName, NSFontAttributeName,
    )
    from Foundation import NSMakeRect, NSAttributedString, NSMutableAttributedString
    from PyObjCTools import AppHelper

    W, H = 280.0, 252.0
    volume = max(0.0, min(1.0, float(volume)))

    # Beat-dot colors.
    C_DIM = NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.22)
    C_ON = NSColor.whiteColor()
    C_ACCENT = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.62, 0.16, 1.0)

    # --- sound: two NSSound objects, played from the engine thread ---
    snd_hi = NSSound.alloc().initWithContentsOfFile_byReference_(snd_paths[0], True)
    snd_lo = NSSound.alloc().initWithContentsOfFile_byReference_(snd_paths[1], True)
    snd_hi.setVolume_(volume)
    snd_lo.setVolume_(volume)

    def play(accent):
        s = snd_hi if accent else snd_lo
        s.stop()
        s.play()

    engine.play = play

    class DraggableView(NSView):
        def rightMouseDown_(self, event):
            NSApp().terminate_(None)

        def acceptsFirstMouse_(self, event):
            return True

        def acceptsFirstResponder(self):
            return True

        def keyDown_(self, event):
            code = event.keyCode()
            c = self.controller
            if code == 49:        # space
                c.toggle_(None)
            elif code in (126, 124):   # up / right
                c.bump_(1)
            elif code in (125, 123):   # down / left
                c.bump_(-1)
            elif code == 53:      # esc
                NSApp().terminate_(None)

    def make_label(frame, size, color, bold=False, align=NSTextAlignmentCenter):
        tf = NSTextField.alloc().initWithFrame_(frame)
        tf.setBezeled_(False)
        tf.setDrawsBackground_(False)
        tf.setEditable_(False)
        tf.setSelectable_(False)
        tf.setAlignment_(align)
        tf.setTextColor_(color)
        tf.setFont_(NSFont.boldSystemFontOfSize_(size) if bold
                    else NSFont.systemFontOfSize_(size))
        return tf

    def make_button(frame, title, size, action, color=None):
        b = NSButton.alloc().initWithFrame_(frame)
        b.setBordered_(False)
        b.setTitle_("")
        attrs = {
            NSForegroundColorAttributeName: color or NSColor.colorWithCalibratedWhite_alpha_(0.9, 1.0),
            NSFontAttributeName: NSFont.systemFontOfSize_(size),
        }
        b.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(title, attrs))
        b.setAction_(action)
        return b

    class Controller(NSObject):
        # --- update beat dots ---
        def refresh_dots(self, current):
            s = NSMutableAttributedString.alloc().init()
            font = NSFont.systemFontOfSize_(18)
            for i in range(self.engine.beats):
                if i == current:
                    color = C_ACCENT if i == 0 else C_ON
                else:
                    color = C_DIM
                piece = NSAttributedString.alloc().initWithString_attributes_(
                    "\u25CF  ", {NSForegroundColorAttributeName: color, NSFontAttributeName: font}
                )
                s.appendAttributedString_(piece)
            self.dots.setAttributedStringValue_(s)

        def refresh_bpm(self):
            self.bpm_label.setStringValue_(str(self.engine.bpm))

        def refresh_beats(self):
            n = self.engine.beats
            self.beats_label.setStringValue_(f"{n} beat" + ("" if n == 1 else "s"))
            self.refresh_dots(-1)

        # --- actions ---
        def bump_(self, delta):
            self.engine.set_bpm(self.engine.bpm + delta)
            self.refresh_bpm()

        def inc_(self, sender):
            self.bump_(1)

        def dec_(self, sender):
            self.bump_(-1)

        def incBeats_(self, sender):
            self.engine.set_beats(self.engine.beats + 1)
            self.refresh_beats()

        def decBeats_(self, sender):
            self.engine.set_beats(self.engine.beats - 1)
            self.refresh_beats()

        def toggle_(self, sender):
            if self.engine.is_running():
                self.engine.stop_ticking()
                self.play_btn.setAttributedTitle_(self._play_title("\u25B6"))
            else:
                self.engine.start_ticking()
                self.play_btn.setAttributedTitle_(self._play_title("\u275A\u275A"))

        def _play_title(self, glyph):
            attrs = {
                NSForegroundColorAttributeName: NSColor.whiteColor(),
                NSFontAttributeName: NSFont.systemFontOfSize_(22),
            }
            return NSAttributedString.alloc().initWithString_attributes_(glyph, attrs)

        def volume_(self, sender):
            v = float(sender.doubleValue())
            self.snd_hi.setVolume_(v)
            self.snd_lo.setVolume_(v)

        def close_(self, sender):
            NSApp().terminate_(None)

        # --- timer: beat highlighting ---
        def tick_(self, timer):
            try:
                while True:
                    kind, payload = self.q.get_nowait()
                    if kind == "beat":
                        self.refresh_dots(payload)
            except queue.Empty:
                pass

    # --- window ---
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    rect = NSMakeRect(0, 0, W, H)

    class KeyWindow(NSWindow):
        def canBecomeKeyWindow(self):
            return True

    window = KeyWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        rect, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
    )
    window.setLevel_(NSStatusWindowLevel)
    window.setOpaque_(False)
    window.setBackgroundColor_(NSColor.clearColor())
    window.setHasShadow_(True)
    window.setMovableByWindowBackground_(True)
    window.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorStationary
        | NSWindowCollectionBehaviorFullScreenAuxiliary
    )

    content = DraggableView.alloc().initWithFrame_(rect)
    content.setWantsLayer_(True)
    layer = content.layer()
    layer.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.07, 0.92).CGColor())
    layer.setCornerRadius_(16.0)
    window.setContentView_(content)

    # Beat dots (top).
    dots = make_label(NSMakeRect(10, H - 54, W - 20, 28), 18, C_DIM)
    content.addSubview_(dots)

    # Large BPM + - / +.
    bpm_label = make_label(NSMakeRect(40, 132, W - 80, 58), 46, NSColor.whiteColor(), bold=True)
    content.addSubview_(bpm_label)
    caption = make_label(NSMakeRect(40, 116, W - 80, 16), 11,
                         NSColor.colorWithCalibratedWhite_alpha_(0.5, 1.0))
    caption.setStringValue_("BPM")
    content.addSubview_(caption)

    minus = make_button(NSMakeRect(14, 140, 42, 46), "\u2212", 34, b"dec:")
    plus = make_button(NSMakeRect(W - 56, 140, 42, 46), "+", 34, b"inc:")
    content.addSubview_(minus)
    content.addSubview_(plus)

    # Beats: - N beats +.
    beats_minus = make_button(NSMakeRect(58, 84, 26, 26), "\u2212", 18, b"decBeats:")
    beats_label = make_label(NSMakeRect(90, 83, W - 180, 26), 13,
                             NSColor.colorWithCalibratedWhite_alpha_(0.7, 1.0))
    beats_plus = make_button(NSMakeRect(W - 84, 84, 26, 26), "+", 18, b"incBeats:")
    content.addSubview_(beats_minus)
    content.addSubview_(beats_label)
    content.addSubview_(beats_plus)

    # Play / Pause.
    play_btn = make_button(NSMakeRect(W / 2 - 34, 46, 68, 30), "\u25B6", 22, b"toggle:",
                           color=NSColor.whiteColor())
    content.addSubview_(play_btn)

    # Volume: icon + slider (bottom).
    vol_icon = make_label(NSMakeRect(12, 11, 26, 22), 14,
                          NSColor.colorWithCalibratedWhite_alpha_(0.7, 1.0))
    vol_icon.setStringValue_("\U0001F509")
    content.addSubview_(vol_icon)
    vol_slider = NSSlider.alloc().initWithFrame_(NSMakeRect(42, 13, W - 56, 18))
    vol_slider.setMinValue_(0.0)
    vol_slider.setMaxValue_(1.0)
    vol_slider.setDoubleValue_(volume)
    vol_slider.setContinuous_(True)
    vol_slider.setAction_(b"volume:")
    content.addSubview_(vol_slider)

    # Close button.
    close_btn = make_button(NSMakeRect(W - 30, H - 30, 22, 22), "\u2715", 16, b"close:",
                            color=NSColor.colorWithCalibratedWhite_alpha_(0.75, 1.0))
    content.addSubview_(close_btn)

    # Position: top-right corner.
    screen = NSScreen.mainScreen().frame()
    window.setFrameOrigin_((screen.size.width - W - 20, screen.size.height - H - 60))
    window.orderFrontRegardless()

    controller = Controller.alloc().init()
    controller.q = q
    controller.engine = engine
    controller.dots = dots
    controller.bpm_label = bpm_label
    controller.beats_label = beats_label
    controller.play_btn = play_btn
    controller.snd_hi = snd_hi
    controller.snd_lo = snd_lo
    controller.refresh_bpm()
    controller.refresh_beats()

    for b in (minus, plus, beats_minus, beats_plus, play_btn, close_btn, vol_slider):
        b.setTarget_(controller)

    content.controller = controller
    window.makeFirstResponder_(content)

    timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
        0.02, controller, b"tick:", None, True
    )
    NSRunLoop.currentRunLoop().addTimer_forMode_(timer, NSRunLoopCommonModes)

    signal.signal(signal.SIGINT, lambda *a: NSApp().terminate_(None))

    engine.start()
    app.activateIgnoringOtherApps_(True)
    try:
        AppHelper.runEventLoop()
    finally:
        engine.shutdown()


def main():
    parser = argparse.ArgumentParser(description="Minimalist metronome for macOS")
    parser.add_argument("--bpm", type=int, default=120, help="Tempo, BPM (default 120)")
    parser.add_argument("--beats", type=int, default=4, help="Beats per measure (default 4)")
    parser.add_argument("--volume", type=float, default=0.8,
                        help="Click volume 0.0-1.0 (default 0.8)")
    args = parser.parse_args()

    try:
        import AppKit  # noqa: F401
    except ImportError:
        sys.stderr.write(
            "PyObjC (AppKit) not found. Install dependencies:\n"
            "    pip install -r requirements.txt\n"
        )
        sys.exit(1)

    # Synthesize two clicks into a temp folder (accent has a higher pitch).
    tmp = tempfile.mkdtemp(prefix="metronome_")
    hi = os.path.join(tmp, "click_hi.wav")
    lo = os.path.join(tmp, "click_lo.wav")
    _write_click(hi, freq=1500.0, volume=0.7)
    _write_click(lo, freq=900.0, volume=0.5)

    q = queue.Queue()
    bpm = max(MIN_BPM, min(MAX_BPM, args.bpm))
    beats = max(MIN_BEATS, min(MAX_BEATS, args.beats))
    engine = Metronome(q, play=lambda accent: None, bpm=bpm, beats=beats)
    run_overlay(engine, q, (hi, lo), volume=args.volume)


if __name__ == "__main__":
    main()
