#!/usr/bin/env python3
"""Console: the Pi app (version 0.4).

An 8-track tape recorder. The playhead stays in the middle and the tape moves
past it. Records from a USB audio device (an OP-XY in 8-channel mode records
all 8 tracks at once), plays back through it, follows the OP-XY's tempo and
play/stop over MIDI, and edits the tape: loop, lift, drop, cut, splice, undo.

Controls come from the control board (USB MIDI) or a keyboard: a keyboard
plugged into the Pi, or keys typed into the SSH terminal running the app. See
CONTROLS.md for the full list.

Options:
    --window     open a 1280x400 window instead of full screen (for testing on a laptop)
    --rotate N   turn the picture by N degrees (90 or 270) when the screen is upright
                 and the system isn't rotating it; the default is 270
    --demo       no audio engine: made-up waveforms
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

# ---------------------------------------------------------------- keyboard: typed characters -> actions

CHAR_ACTIONS = {
    " ": "PLAY", "r": "RECORD", "R": "RECORD", "q": "QUIT", "Q": "QUIT",
    "g": "GRID", "G": "GRID", "+": "ZOOM_IN", "=": "ZOOM_IN", "-": "ZOOM_OUT", "_": "ZOOM_OUT",
    "[": "BAR_LEFT", "]": "BAR_RIGHT", "i": "INPUT", "I": "INPUT", "e": "EXPORT", "E": "EXPORT",
    "l": "LOOP", "L": "LOOP", "{": "LOOP_IN", "}": "LOOP_OUT",
    "c": "LIFT", "C": "LIFT_ALL", "v": "DROP", "V": "DROP_INSERT", "x": "CUT", "X": "CUT_ALL",
    "s": "SPLICE", "S": "SPLICE_ALL", "u": "UNDO", "U": "UNDO", "m": "MUTE", "M": "MUTE",
    "9": "VOL_DOWN", "0": "VOL_UP", "h": "HOME", "H": "HOME",
}
for _n in range(1, 9):
    CHAR_ACTIONS[str(_n)] = "TRACK%d" % _n
ESCAPES = {"\x1b[C": "RIGHT", "\x1b[D": "LEFT", "\x1b[1;2C": "BAR_RIGHT", "\x1b[1;2D": "BAR_LEFT"}


def start_terminal_keys(q):
    """Read key presses from the terminal (when run over SSH) and put action names on the queue."""
    if not sys.stdin.isatty() or os.environ.get("CONSOLE_NO_TERMINAL_KEYS"):
        return None
    import termios
    import tty
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    def reader():
        while True:
            try:
                data = os.read(fd, 16).decode(errors="ignore")
            except OSError:
                return
            if not data:
                return
            if data in ESCAPES:
                q.put(ESCAPES[data])
                continue
            for ch in data:
                if ch in CHAR_ACTIONS:
                    q.put(CHAR_ACTIONS[ch])

    threading.Thread(target=reader, daemon=True).start()
    return lambda: termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def pygame_key(ev):
    """A pygame key press -> action name, or None."""
    shift = ev.mod & pygame.KMOD_SHIFT
    if ev.key == pygame.K_LEFT:
        return "BAR_LEFT" if shift else "LEFT"
    if ev.key == pygame.K_RIGHT:
        return "BAR_RIGHT" if shift else "RIGHT"
    if ev.key == pygame.K_ESCAPE:
        return "QUIT"
    return CHAR_ACTIONS.get(ev.unicode) if ev.unicode else None


# ---------------------------------------------------------------- control board (MIDI from the firmware)

# key notes 0-23 = SW1-SW24, in keycap order
BOARD_KEYS = ["INPUT", "MIDI", "FX", "FILE", "SPLICE", "CUT", "LIFT", "DROP",
              "LOOP", "IMPORT", "EXPORT", "RECORD", "SHIFT", "PLAY", "LEFT", "RIGHT"] + \
             ["TRACK%d" % n for n in range(1, 9)]
WITH_SHIFT = {"LEFT": "LOOP_IN", "RIGHT": "LOOP_OUT", "CUT": "UNDO", "LIFT": "LIFT_ALL",
              "DROP": "DROP_INSERT", "SPLICE": "SPLICE_ALL", "PLAY": "HOME", "INPUT": "INPUT",
              "EXPORT": "EXPORT"}
# knob pushes: notes 32-42 = ENC1-ENC11
PUSHES = ["MUTE%d" % n for n in range(1, 9)] + ["ZOOM_RESET", "LOOP", "HOME"]


class Board:
    """Turns control board MIDI into actions, keeping track of SHIFT."""

    def __init__(self, q):
        self.q = q
        self.shift = False

    def __call__(self, kind, number, value):       # runs in the MIDI thread
        if kind == "note":
            if 0 <= number < len(BOARD_KEYS):
                name = BOARD_KEYS[number]
                if name == "SHIFT":
                    self.shift = bool(value)
                    return
                if not value:
                    return
                if self.shift:
                    if name.startswith("TRACK"):
                        name = "MUTE" + name[5:]
                    else:
                        name = WITH_SHIFT.get(name, name)
                self.q.put(name)
            elif 32 <= number < 32 + len(PUSHES) and value:
                self.q.put(PUSHES[number - 32])
        elif kind == "cc" and 1 <= number <= 11:
            delta = value - 64
            if delta:
                self.q.put(("KNOB", number, delta, self.shift))


# ---------------------------------------------------------------- the recorder's state

class Transport:
    """Play, record, position, editing and the screen readouts. Uses the audio engine when there is one."""

    def __init__(self, screen, engine=None, clock=None):
        self.s = screen
        self.engine = engine
        self.clock = clock
        self.tape = tape.Tape(screen, engine)
        self._playing = False
        self._recording = False
        self._armed = 4
        self.message = ""
        self.message_until = 0.0
        self._bpm_seen = None
        self._bpm_since = 0.0
        self.tab_colours = {n: (screen.get("track%d_tab" % n) or {}).get("c") for n in range(1, 9)}
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
                if not v:
                    self.engine.recording = False
        else:
            self._playing = v

    @property
    def recording(self):
        return self.engine.recording if self.engine else self._recording

    @recording.setter
    def recording(self, v):
        if self.engine:
            self.engine.set_recording(v)
        else:
            self._recording = v
            if v:
                self._playing = True

    @property
    def armed(self):
        return self.engine.armed if self.engine else self._armed

    @armed.setter
    def armed(self, v):
        if self.engine:
            self.engine.armed = v
        else:
            self._armed = v

    @property
    def synced(self):
        return bool(self.clock and self.clock.active)

    def say(self, text, seconds=4):
        self.message, self.message_until = text, time.monotonic() + seconds

    def stop(self):
        self.playing = False
        if self.engine:
            self.engine.rec_ready = False
            if self.engine.save():
                self.say("SAVED")

    # ------------------------------------------------------------ actions

    def key(self, name):
        if isinstance(name, tuple):
            self.knob(*name[1:])
            self.update_screen()
            return
        t, e = self.tape, self.engine
        if name == "PLAY":
            if self.playing:
                self.stop()
            else:
                self.playing = True
        elif name == "RECORD":
            self.record_key()
        elif name in ("LEFT", "RIGHT", "BAR_LEFT", "BAR_RIGHT"):
            self.move(-1 if name.endswith("LEFT") else 1, tape.BEATS_PER_BAR if name.startswith("BAR") else t.step)
        elif name == "HOME":
            start = e.loop_a / e.frames_per_beat() if (e and e.loop_on and e.loop_region()) else 0.0
            self.set_pos(start if t.pos > start + 1e-6 else 0.0)
        elif name == "GRID":
            t.cycle_grid()
        elif name == "ZOOM_IN":
            t.zoom_in()
        elif name == "ZOOM_OUT":
            t.zoom_out()
        elif name == "ZOOM_RESET":
            t.zoom = tape.ZOOMS.index(4)
        elif name == "INPUT":
            if e:
                e.cycle_input()
        elif name == "EXPORT":
            self.export()
        elif name.startswith("TRACK"):
            self.armed = int(name[5:])
        elif name.startswith("MUTE"):
            self.mute(int(name[4:]) if name[4:] else self.armed)
        elif name in ("VOL_UP", "VOL_DOWN"):
            self.volume(self.armed, 0.05 if name == "VOL_UP" else -0.05)
        elif name in ("MIDI", "FX", "FILE", "IMPORT"):
            self.say("%s COMES IN A LATER VERSION" % name)
        else:
            self.edit(name)
        self.update_screen()

    def knob(self, number, delta, shift):
        t = self.tape
        if number <= 8:
            self.volume(number, delta * (0.005 if shift else 0.02))
        elif number == 9:
            for _ in range(abs(delta)):
                t.zoom_in() if delta > 0 else t.zoom_out()
        elif number == 10:
            for _ in range(abs(delta)):
                t.grid = (t.grid + (1 if delta > 0 else -1)) % len(tape.GRIDS)
        elif number == 11:
            self.move(delta, tape.BEATS_PER_BAR if shift else t.step)

    def record_key(self):
        e = self.engine
        if self.recording:
            self.recording = False
            return
        if e and not e.device:
            self.say("NO AUDIO DEVICE TO RECORD FROM")
            return
        if e and self.synced and not self.playing:
            e.rec_ready = not e.rec_ready
            if e.rec_ready:
                self.say("REC READY: PRESS PLAY ON THE OP-XY", 6)
            return
        self.recording = True

    def set_pos(self, beats):
        self.tape.pos = beats
        if self.engine:
            self.engine.set_beats(beats)

    def move(self, steps, size):
        t = self.tape
        if self.engine:
            t.pos = self.engine.beats()
        t.move(steps, size)
        if self.engine:
            self.engine.set_beats(t.pos)

    def volume(self, track, delta):
        if not self.engine:
            return
        v = self.engine.change_volume(track, delta)
        self.say("TRACK %d  VOLUME %d%%" % (track, round(v * 100)), 2)

    def mute(self, track):
        if not self.engine:
            return
        muted = self.engine.toggle_mute(track)
        self.say("TRACK %d %s" % (track, "MUTED" if muted else "ON"), 2)

    def edit(self, name):
        e = self.engine
        if not e:
            self.say("EDITING NEEDS THE AUDIO ENGINE")
            return
        if name == "LOOP":
            e.toggle_loop()
            self.say("LOOP ON" if e.loop_on else "LOOP OFF", 2)
            return
        if name in ("LOOP_IN", "LOOP_OUT"):
            e.set_loop_point("in" if name == "LOOP_IN" else "out", self.tape.pos)
            self.say("LOOP %s AT %s" % ("START" if name == "LOOP_IN" else "END", self.position_text(self.tape.pos)), 2)
            return
        if self.recording:
            self.say("STOP RECORDING FIRST")
            return
        where = "THE LOOP" if e.loop_region() else "THIS BAR"
        which = lambda all_: "ALL TRACKS" if all_ else "TRACK %d" % self.armed
        if name in ("LIFT", "LIFT_ALL"):
            e.lift(name == "LIFT_ALL")
            self.say("LIFTED %s OF %s" % (where, which(name == "LIFT_ALL")))
        elif name in ("CUT", "CUT_ALL"):
            e.cut(name == "CUT_ALL")
            self.say("ERASED %s OF %s" % (where, which(name == "CUT_ALL")))
        elif name in ("DROP", "DROP_INSERT"):
            if e.drop(insert=name == "DROP_INSERT"):
                self.say("DROPPED AT %s%s" % (self.position_text(self.tape.pos), ", PUSHING THE REST LATER" if name == "DROP_INSERT" else ""))
            else:
                self.say("NOTHING TO DROP: LIFT SOMETHING FIRST")
        elif name in ("SPLICE", "SPLICE_ALL"):
            e.splice(name == "SPLICE_ALL")
            self.say("SPLICED OUT %s OF %s" % (where, which(name == "SPLICE_ALL")))
        elif name == "UNDO":
            self.say("UNDONE" if e.undo() else "NOTHING TO UNDO", 2)

    def export(self):
        if not self.engine:
            self.say("NOTHING TO EXPORT IN DEMO MODE")
            return
        self.say("EXPORTING...", 60)

        def work():
            name = self.engine.export()
            self.say("EXPORTED TO EXPORTS / %s" % name.upper() if name else "NOTHING RECORDED YET", 6)
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ every frame

    def tick(self, seconds):
        t, e = self.tape, self.engine
        if e:
            was = self._playing
            t.pos = e.beats()
            self._playing = e.playing
            if was and not self._playing:           # stopped by the tape end, or by MIDI stop
                self.stop()
            self.follow_tempo()
        elif self.playing:
            start = t.pos
            t.pos += seconds * BPM / 60
            if t.pos >= tape.TAPE_BEATS:
                t.pos = float(tape.TAPE_BEATS)
                self.playing = self.recording = False
            if self.recording:
                t.record(self.armed, start, t.pos)
        self.update_screen()

    def follow_tempo(self):
        """Take the OP-XY's tempo while stopped, once it has held steady for a moment."""
        bpm = self.clock.bpm if self.clock else None
        if not bpm or self.playing:
            self._bpm_seen = None
            return
        bpm = round(bpm, 1)
        now = time.monotonic()
        if self._bpm_seen is None or abs(bpm - self._bpm_seen) > 0.2:
            self._bpm_seen, self._bpm_since = bpm, now
        elif now - self._bpm_since > 0.7 and abs(bpm - self.engine.bpm) > 0.2:
            if self.engine.set_bpm(bpm):
                self.say("TEMPO %.1f BPM FROM MIDI" % bpm, 3)

    def position_text(self, beats):
        b = int(beats)
        return "%03d.%d.%d" % (b // 4 + 1, b % 4 + 1, int(beats * 4) % 4 + 1)

    def update_screen(self):
        s, t, e = self.s, self.tape, self.engine
        s.set("clock", t=self.position_text(t.pos))
        s.set("grid", t=t.label() + ("   LOOP" if e and e.loop_on and e.loop_region() else ""))
        bpm = e.bpm if e else BPM
        s.set("bpm", t="%.1f BPM  4/4%s" % (bpm, "  SYNC" if self.synced else ""))
        all_in = bool(e and e.device and e.input_mode == "all")
        first, last, lane = s.get("track1_lane"), s.get("track8_lane"), s.get("track%d_lane" % self.armed)
        if all_in and first and last:
            s.set("rec_outline", y=first["y"] - 2, h=last["y"] + last["h"] - first["y"] + 4)
        elif lane:
            s.set("rec_outline", y=lane["y"] - 2, h=lane["h"] + 4)
        ready = bool(e and e.rec_ready)
        state = "RECORDING" if self.recording else "REC READY" if ready else "PLAYING" if self.playing else "STOPPED"
        s.set("status", t="%s  %s" % (state, "ALL TRACKS" if all_in else "TRACK %d" % self.armed))
        red = "#FF5A4E" if (self.recording or ready) else "#7D838C"
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
            muted = bool(e and (n - 1) in e.mutes)
            if self.tab_colours.get(n):
                s.set("track%d_tab" % n, c="#2A2D33" if muted else self.tab_colours[n])
            if e and (n - 1) in targets and (self.recording or ready or not self.playing):
                ch = targets[n - 1]
                peak = float(e.in_peaks.max() if ch is None else e.in_peaks[ch])
                level = min(1.0, peak ** 0.5)
            elif self.playing and not muted:
                level = t.level_at(n, t.pos - 1 / tape.RES) * (e.volumes[n - 1] / 0.8 if e else 1)
            else:
                level = 0
            s.set("track%d_meter" % n, v=round(min(1.0, level) * 100))


# ---------------------------------------------------------------- start-up

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
    engine = audio.Engine(bpm=BPM)
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
    print("Keys: see pi-app/CONTROLS.md (Space play, R record, Q quit)")

    screen = ui.Screen.load(args.layout)
    frame = pygame.Surface((ui.WIDTH, ui.HEIGHT))
    engine = start_engine(args.demo)
    keys = queue.Queue()
    clock = None
    try:
        import midi
        settings = engine.settings if engine else {}
        _ctl, _clk, clock = midi.start(Board(keys), engine, settings.get("clock_device"))
    except Exception as e:
        print("No MIDI input:", e)
    transport = Transport(screen, engine, clock)
    restore_terminal = start_terminal_keys(keys)
    fps = pygame.time.Clock()

    try:
        running = True
        while running:
            seconds = fps.tick(FPS) / 1000
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN:
                    name = pygame_key(ev)
                    if name:
                        keys.put(name)
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
            transport.playing = False
            engine.stop()
            engine.save(wait=True)
        pygame.quit()


if __name__ == "__main__":
    main()
