#!/usr/bin/env python3
"""Console: the Pi app (version 0.3).

Shows the screen layout from layouts/main.ui full screen, with an OP-1 style
tape: the playhead stays in the middle and the tape moves past it, with bar,
beat and grid lines. Records from a USB audio device (an OP-XY in 8-channel
mode records all 8 tracks at once), plays back through it, saves the song and
exports stems. Without an audio device it still runs, showing "NO AUDIO DEVICE".

Keys (a keyboard plugged into the Pi, or typed into an SSH terminal running the app):
    1-8          arm a track for recording
    Space        play / stop
    R            record on / off (also starts playing)
    Left/Right   move back / forward one grid step
    [ / ]        move back / forward one bar (also Shift+Left/Right)
    G            change the grid: 1/4, 1/8, 1/16, 1/32
    + / -        zoom in / out (16, 8, 4, 2 or 1 bars across the screen)
    I            input: all inputs to tracks 1-8 (OP-XY 8-channel), or the inputs mixed to the armed track
    E            export stems and a stereo mix to the Exports folder
    Q            quit (ignored when Console runs as the boot app)

Options:
    --window     open a 1280x400 window instead of full screen (for testing on a laptop)
    --rotate N   turn the picture by N degrees (90 or 270) when the screen is upright
                 and the system isn't rotating it; the default is 270
"""
import argparse
import os
import queue
import sys
import threading
import time

import pygame

import tape
import ui

HERE = os.path.dirname(os.path.abspath(__file__))
FPS = 30
BPM = 120.0


# ---------------------------------------------------------------- keys from an SSH terminal

def start_terminal_keys(q):
    """Read single key presses from the terminal (when run over SSH) and put names on the queue."""
    if not sys.stdin.isatty() or os.environ.get("CONSOLE_NO_TERMINAL_KEYS"):
        return None
    import termios
    import tty
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    def reader():
        names = {" ": "PLAY", "r": "RECORD", "R": "RECORD", "q": "QUIT", "Q": "QUIT",
                 "g": "GRID", "G": "GRID", "+": "ZOOM_IN", "=": "ZOOM_IN", "-": "ZOOM_OUT", "_": "ZOOM_OUT",
                 "[": "BAR_LEFT", "]": "BAR_RIGHT", "i": "INPUT", "I": "INPUT", "e": "EXPORT", "E": "EXPORT",
                 "\x1b[C": "RIGHT", "\x1b[D": "LEFT", "\x1b[1;2C": "BAR_RIGHT", "\x1b[1;2D": "BAR_LEFT"}
        while True:
            try:
                data = os.read(fd, 16).decode(errors="ignore")
            except OSError:
                return
            if not data:
                return
            if data in names:
                q.put(names[data])
                continue
            for ch in data:
                if ch in "12345678":
                    q.put("TRACK" + ch)
                elif ch in names:
                    q.put(names[ch])

    threading.Thread(target=reader, daemon=True).start()
    return lambda: termios.tcsetattr(fd, termios.TCSADRAIN, saved)


PYGAME_KEYS = {
    pygame.K_SPACE: "PLAY", pygame.K_r: "RECORD", pygame.K_LEFT: "LEFT", pygame.K_RIGHT: "RIGHT",
    pygame.K_q: "QUIT", pygame.K_ESCAPE: "QUIT", pygame.K_g: "GRID",
    pygame.K_EQUALS: "ZOOM_IN", pygame.K_PLUS: "ZOOM_IN", pygame.K_KP_PLUS: "ZOOM_IN",
    pygame.K_MINUS: "ZOOM_OUT", pygame.K_KP_MINUS: "ZOOM_OUT",
    pygame.K_LEFTBRACKET: "BAR_LEFT", pygame.K_RIGHTBRACKET: "BAR_RIGHT",
    pygame.K_i: "INPUT", pygame.K_e: "EXPORT",
}
for _n in range(1, 9):
    PYGAME_KEYS[getattr(pygame, "K_%d" % _n)] = "TRACK%d" % _n


# ---------------------------------------------------------------- the recorder's state (no audio yet)

class Transport:
    """Play, record, position and the screen readouts. Uses the audio engine when there is one."""

    def __init__(self, screen, engine=None):
        self.s = screen
        self.engine = engine
        self.tape = tape.Tape(screen, engine)
        self._playing = False
        self._recording = False
        self._armed = 4
        self.message = ""
        self.message_until = 0.0
        if engine:
            screen.set("song", t=engine.song)
        self.update_screen()

    # the engine owns these when it exists, so the audio thread and the screen agree
    @property
    def playing(self):
        return self.engine.playing if self.engine else self._playing

    @playing.setter
    def playing(self, v):
        if self.engine:
            with self.engine.lock:
                self.engine.playing = v
        else:
            self._playing = v

    @property
    def recording(self):
        return self.engine.recording if self.engine else self._recording

    @recording.setter
    def recording(self, v):
        if self.engine:
            with self.engine.lock:
                self.engine.recording = v
        else:
            self._recording = v

    @property
    def armed(self):
        return self.engine.armed if self.engine else self._armed

    @armed.setter
    def armed(self, v):
        if self.engine:
            self.engine.armed = v
        else:
            self._armed = v

    def say(self, text, seconds=4):
        self.message, self.message_until = text, time.monotonic() + seconds

    def stop(self):
        self.playing = self.recording = False
        if self.engine and self.engine.save():
            self.say("SAVED")

    def key(self, name):
        t = self.tape
        if name == "PLAY":
            if self.playing:
                self.stop()
            else:
                self.playing = True
        elif name == "RECORD":
            if self.recording:
                self.recording = False
            else:
                if self.engine and not self.engine.device:
                    self.say("NO AUDIO DEVICE TO RECORD FROM")
                else:
                    self.recording = True
                    self.playing = True
        elif name in ("LEFT", "RIGHT", "BAR_LEFT", "BAR_RIGHT"):
            size = tape.BEATS_PER_BAR if name.startswith("BAR") else t.step
            if self.engine:
                t.pos = self.engine.beats()
            t.move(-1 if name.endswith("LEFT") else 1, size)
            if self.engine:
                self.engine.set_beats(t.pos)
        elif name == "GRID":
            t.cycle_grid()
        elif name == "ZOOM_IN":
            t.zoom_in()
        elif name == "ZOOM_OUT":
            t.zoom_out()
        elif name == "INPUT" and self.engine:
            self.engine.cycle_input()
        elif name == "EXPORT":
            self.export()
        elif name.startswith("TRACK"):
            self.armed = int(name[5:])
        self.update_screen()

    def export(self):
        if not self.engine:
            self.say("NOTHING TO EXPORT IN DEMO MODE")
            return
        self.say("EXPORTING...", 60)

        def work():
            name = self.engine.export()
            self.say("EXPORTED TO EXPORTS / %s" % name.upper() if name else "NOTHING RECORDED YET", 6)
        threading.Thread(target=work, daemon=True).start()

    def tick(self, seconds):
        t = self.tape
        if self.engine:
            was = self._playing
            t.pos = self.engine.beats()
            self._playing = self.engine.playing
            if was and not self._playing:           # the tape reached its end
                self.stop()
        elif self.playing:
            start = t.pos
            t.pos += seconds * BPM / 60
            if t.pos >= tape.TAPE_BEATS:
                t.pos = float(tape.TAPE_BEATS)
                self.playing = self.recording = False
            if self.recording:
                t.record(self.armed, start, t.pos)
        self.update_screen()

    def update_screen(self):
        s, t, e = self.s, self.tape, self.engine
        b = int(t.pos)
        s.set("clock", t="%03d.%d.%d" % (b // 4 + 1, b % 4 + 1, int(t.pos * 4) % 4 + 1))
        s.set("grid", t=t.label())
        all_in = bool(e and e.device and e.input_mode == "all")
        first, last, lane = s.get("track1_lane"), s.get("track8_lane"), s.get("track%d_lane" % self.armed)
        if all_in and first and last:
            s.set("rec_outline", y=first["y"] - 2, h=last["y"] + last["h"] - first["y"] + 4)
        elif lane:
            s.set("rec_outline", y=lane["y"] - 2, h=lane["h"] + 4)
        state = "RECORDING" if self.recording else "PLAYING" if self.playing else "STOPPED"
        s.set("status", t="%s  %s" % (state, "ALL TRACKS" if all_in else "TRACK %d" % self.armed))
        red = "#FF5A4E" if self.recording else "#7D838C"
        s.set("rec_dot", c=red)
        s.set("rec_outline", c=red)

        if self.message and time.monotonic() < self.message_until:
            hint = self.message
        elif not e:
            hint = "DEMO: NO AUDIO ENGINE"
        elif not e.device:
            hint = e.status or "NO AUDIO DEVICE"
        elif all_in:
            hint = "%s  IN 1-%d > TRACKS" % (e.device["name"].upper(), min(8, e.device["capture"]["channels"]))
        else:
            hint = "%s  IN MIX > TRACK %d" % (e.device["name"].upper(), self.armed)
        s.set("hint", t=hint)

        targets = e.targets() if (e and e.device) else {}
        for n in range(1, 9):
            if e and (n - 1) in targets and (self.recording or not self.playing):
                ch = targets[n - 1]
                peak = float(e.in_peaks.max() if ch is None else e.in_peaks[ch])
                level = min(1.0, peak ** 0.5)
            elif self.playing:
                level = t.level_at(n, t.pos - 1 / tape.RES)
            else:
                level = 0
            s.set("track%d_meter" % n, v=round(level * 100))


# ---------------------------------------------------------------- main loop

def start_engine(demo):
    """Start the audio engine, or return None (demo mode) if asked to or if it can't load."""
    if demo:
        return None
    try:
        import alsaaudio  # noqa: F401  (checked here so a missing package means demo mode, not a silent failure)
        import audio
    except ImportError as e:
        print("No audio engine (%s). Run pi-app/setup.sh to install what it needs. Running in demo mode." % e)
        return None
    engine = audio.Engine(bpm=BPM, tape_beats=tape.TAPE_BEATS)
    engine.start()
    return engine


def main():
    ap = argparse.ArgumentParser(description="Console recorder")
    ap.add_argument("--window", action="store_true", help="open a window instead of full screen")
    ap.add_argument("--rotate", type=int, default=int(os.environ.get("CONSOLE_ROTATE", "270")))
    ap.add_argument("--layout", default=os.path.join(HERE, "layouts", "main.ui"))
    ap.add_argument("--demo", action="store_true", help="no audio: show made-up waveforms")
    args = ap.parse_args()

    pygame.init()
    if args.window:
        display = pygame.display.set_mode((ui.WIDTH, ui.HEIGHT))
    else:
        display = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
    pygame.display.set_caption("Console")
    dw, dh = display.get_size()
    rotate = args.rotate if dh > dw else 0      # an upright screen means nobody rotated it for us
    print("Console: display %dx%d driver %s%s" % (dw, dh, pygame.display.get_driver(),
                                                 ", turning the picture %d degrees" % rotate if rotate else ""))
    print("Keys: 1-8 arm track, Space play/stop, R record, I input, E export, Left/Right grid step, [ ] bar, G grid, + - zoom, Q quit")

    screen = ui.Screen.load(args.layout)
    frame = pygame.Surface((ui.WIDTH, ui.HEIGHT))
    engine = start_engine(args.demo)
    transport = Transport(screen, engine)
    keys = queue.Queue()
    restore_terminal = start_terminal_keys(keys)
    clock = pygame.time.Clock()

    try:
        running = True
        while running:
            seconds = clock.tick(FPS) / 1000
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN:
                    shift = ev.mod & pygame.KMOD_SHIFT
                    if shift and ev.key == pygame.K_LEFT:
                        keys.put("BAR_LEFT")
                    elif shift and ev.key == pygame.K_RIGHT:
                        keys.put("BAR_RIGHT")
                    elif ev.key in PYGAME_KEYS:
                        keys.put(PYGAME_KEYS[ev.key])
            while not keys.empty():
                name = keys.get()
                if name == "QUIT":
                    if os.environ.get("CONSOLE_SERVICE"):
                        print("Q ignored: Console is running as the boot app. Stop it with: sudo systemctl stop console")
                    else:
                        running = False
                else:
                    transport.key(name)
            transport.tick(seconds)

            screen.draw(frame)
            out = pygame.transform.rotate(frame, rotate) if rotate else frame
            if out.get_size() != (dw, dh):
                scale = min(dw / out.get_width(), dh / out.get_height())
                size = (round(out.get_width() * scale), round(out.get_height() * scale))
                out = pygame.transform.smoothscale(out, size)
                display.fill((0, 0, 0))
            display.blit(out, ((dw - out.get_width()) // 2, (dh - out.get_height()) // 2))
            pygame.display.flip()
    finally:
        if restore_terminal:
            restore_terminal()
        if engine:
            transport.playing = transport.recording = False
            engine.stop()
            engine.save(wait=True)
        pygame.quit()


if __name__ == "__main__":
    main()
