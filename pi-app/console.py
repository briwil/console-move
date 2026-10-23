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
import math
import os
import queue
import sys
import threading
import time

os.environ.setdefault("SDL_AUDIODRIVER", "dummy")   # pygame mustn't open a sound device: the audio engine owns them
import pygame

import drumparams
import effects
import focus
import kitmenu
import menu
import sequencer
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
    "l": "LOOP", "L": "LOOP", "{": "LOOP_IN", "}": "LOOP_OUT", "k": "CLEAR_REGION", "K": "CLEAR_REGION",
    "c": "COPY", "C": "COPY", "v": "DROP", "V": "DROP_INSERT", "x": "CUT", "X": "CUT",
    "s": "SPLICE", "S": "SPLICE_ALL", "a": "SELECT", "A": "SELECT", "u": "UNDO", "U": "UNDO", "m": "MUTE", "M": "SOLO",
    "o": "REC_MODE", "O": "REC_MODE", "f": "FOCUS", "F": "FOCUS",
    "9": "VOL_DOWN", "0": "VOL_UP", "(": "PHONES_DOWN", ")": "PHONES_UP", "h": "HOME", "H": "HOME", "`": "ARM_ALL", "~": "ARM_ALL",
    "b": "BOUNCE", "B": "BOUNCE", "w": "FX", "W": "FX", "d": "DRUMS", "D": "DRUMS", ",": "PAN_LEFT", "<": "PAN_LEFT", ".": "PAN_RIGHT", ">": "PAN_RIGHT",
}
for _n, _ch in enumerate("!@#$%^&*", 1):              # Shift+1..8 on a US keyboard
    CHAR_ACTIONS[_ch] = "ARM%d" % _n
for _n in range(1, 9):
    CHAR_ACTIONS[str(_n)] = "TRACK%d" % _n
CHAR_ACTIONS.update({"\r": "ENTER", "\n": "ENTER", "\t": "FILE"})
ESCAPES = {"\x1b[C": "RIGHT", "\x1b[D": "LEFT", "\x1b[1;2C": "BAR_RIGHT", "\x1b[1;2D": "BAR_LEFT",
           "\x1b[A": "UP", "\x1b[B": "DOWN", "\x1b": "FILE"}
MODE_NAMES = {"all": "MULTI", "stereo": "STEREO", "mix": "MONO"}     # input modes as shown on screen
TEXT_INPUT = {"on": False}      # while typing a name, keys arrive as ("CHAR", letter) instead of commands


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
            if data in ESCAPES and not (TEXT_INPUT["on"] and data == "\x1b"):
                q.put(ESCAPES[data])
                continue
            for ch in data:
                if TEXT_INPUT["on"]:
                    q.put(("CHAR", ch))
                elif ch in CHAR_ACTIONS:
                    q.put(CHAR_ACTIONS[ch])

    threading.Thread(target=reader, daemon=True).start()
    return lambda: termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def pygame_key(ev):
    """A pygame key press -> action name, ("CHAR", letter) while typing, or None."""
    shift = ev.mod & pygame.KMOD_SHIFT
    if ev.key == pygame.K_LEFT:
        return "BAR_LEFT" if shift else "LEFT"
    if ev.key == pygame.K_RIGHT:
        return "BAR_RIGHT" if shift else "RIGHT"
    if ev.key == pygame.K_UP:
        return "UP"
    if ev.key == pygame.K_DOWN:
        return "DOWN"
    if TEXT_INPUT["on"]:
        if ev.key == pygame.K_ESCAPE:
            return ("CHAR", "\x1b")
        return ("CHAR", ev.unicode) if ev.unicode else None
    if ev.key == pygame.K_ESCAPE:
        return "FILE"
    return CHAR_ACTIONS.get(ev.unicode) if ev.unicode else None


# ---------------------------------------------------------------- control board (MIDI from the firmware)

# key notes 0-23 = SW1-SW24, in keycap order
BOARD_KEYS = ["INPUT", "DRUMS", "FX", "FILE", "SPLICE", "CUT", "LIFT", "DROP",
              "LOOP", "IMPORT", "EXPORT", "RECORD", "SHIFT", "PLAY", "LEFT", "RIGHT"] + \
             ["TRACK%d" % n for n in range(1, 9)]
BOARD_KEYS[6] = "COPY"                # the LIFT key copies (lifts a copy off the tape)
WITH_SHIFT = {"LEFT": "LOOP_IN", "RIGHT": "LOOP_OUT", "CUT": "UNDO", "COPY": "SELECT",
              "DROP": "DROP_INSERT", "SPLICE": "SPLICE_ALL", "PLAY": "HOME", "RECORD": "REC_MODE",
              "LOOP": "CLEAR_REGION", "INPUT": "ARM_ALL", "EXPORT": "BOUNCE"}
# knob pushes: notes 32-42 = ENC1-ENC11
HOLD_KEYS = ("COPY", "CUT")            # hold one and move to take several pieces; let go to copy / cut
PUSHES = ["MUTE%d" % n for n in range(1, 9)] + ["ZOOM_RESET", "LOOP", "HOME"]


class Board:
    """Turns control board MIDI into actions, keeping track of SHIFT."""

    def __init__(self, q):
        self.q = q
        self.shift = False
        self.held = set()                  # hold keys pressed without SHIFT, waiting for their release
        self.pads = None                   # Transport.pad: plays the drum synth straight from this thread
        self.seq_page = lambda: False      # True while the sequencer page turns the 4x4 keys into steps
        self.shift_used = False            # SHIFT did something while held (so letting go isn't step 13)

    def __call__(self, kind, number, value):       # runs in the MIDI thread
        if kind == "note":
            if 0 <= number < len(BOARD_KEYS):
                name = BOARD_KEYS[number]
                steps = self.seq_page()
                if name == "SHIFT":
                    # on the sequencer page SHIFT is also step 13: held, it holds the step (turn knobs to
                    # lock settings to it); press another key with it and it's SHIFT instead
                    self.shift = bool(value)
                    if value:
                        self.shift_used = False
                        if steps:
                            self.q.put(("STEP", number, True))
                    elif steps and not self.shift_used:
                        self.q.put(("STEP", number, False))
                    return
                if steps and self.shift and not self.shift_used:
                    self.shift_used = True
                    self.q.put(("STEP_CANCEL", 12))     # it was SHIFT after all: let go of step 13
                if steps and number < 16:
                    if self.shift:              # SHIFT + one of the 4x4 keys: that key's own job
                        if value:
                            self.q.put(name)
                    else:
                        self.q.put(("STEP", number, bool(value)))
                    return
                if self.shift:
                    self.shift_used = True
                if name in HOLD_KEYS and (not value or not self.shift):
                    if value:
                        self.held.add(name)
                        self.q.put(("HOLD", name))
                    elif name in self.held:
                        self.held.discard(name)
                        self.q.put(("RELEASE", name))
                    return
                if not value:
                    return
                if name.startswith("TRACK") and not self.shift and self.pads and self.pads(int(name[5:])):
                    return                                # a drum pad: played already, nothing else to do
                if self.shift:
                    if name.startswith("TRACK"):
                        name = "ARM" + name[5:]           # SHIFT+track: arm / disarm it as well
                    else:
                        name = WITH_SHIFT.get(name, name)
                self.q.put(name)
            elif 32 <= number < 32 + len(PUSHES) and value:
                name = PUSHES[number - 32]
                if self.shift and self.seq_page() and not self.shift_used:
                    self.q.put(name)                    # step 13 held: a push takes a lock off
                    return
                if self.shift and name.startswith("MUTE"):
                    name = "SOLO" + name[4:]          # SHIFT + push a track knob: solo
                self.q.put(name)
        elif kind == "cc" and 1 <= number <= 11:
            delta = value - 64
            if delta and self.shift and self.seq_page() and not self.shift_used:
                self.q.put(("KNOB", number, delta, False))  # SHIFT held as step 13: the knob locks it
            elif delta:
                self.q.put(("KNOB", number, delta, self.shift))


def drums_mod():
    import drums
    return drums


# ---------------------------------------------------------------- the recorder's state

class Transport:
    """Play, record, position, editing and the screen readouts. Uses the audio engine when there is one."""

    def __init__(self, screen, engine=None, clock=None):
        self.s = screen
        self.engine = engine
        self.clock = clock
        self.link = None                          # linksync.LinkSync, set by main()
        self.tape = tape.Tape(screen, engine)
        for n in range(1, 8):
            screen.custom["track%d_num" % n] = self.draw_num
        self.focus = focus.Focus(screen, self.tape)
        self.fx_page = None                       # None, "reverb" or "delay": what the FX key shows
        self.drum_page = False                    # the DRUMS key: track keys 1-7 play the drum synth
        self.drum_voice = 0                       # the voice the knobs edit (the last one played), 0-5
        self.drum_tab = 0                         # which page of its settings (knob 9 turns them)
        self._drum_hits = [0.0] * 6               # when each voice was last played, to light it up
        self._knob_times = {}                     # knob -> when it last clicked, to speed up fast turns
        self.seq_page = False                     # the MIDI key's second press: the sequencer
        self.seq_lane = 0                         # the sequencer lane being edited, 0-6
        self.seq_bank = 0                         # which 16 steps the 4x4 keys are (the big knob)
        self.held_steps = []                      # steps held down (lane step numbers), in the order pressed
        self._turned = set()                      # held steps that had a knob turned (so letting go doesn't toggle)
        screen.after["playhead"] = self.draw_page
        self._playing = False
        self._recording = False
        self._armed = 4
        self.message = ""
        self.message_until = 0.0
        self.holding = None                # the hold key (LIFT or CUT) being held, if any
        self.bounce_pending = None         # (sources, dest) after the first BOUNCE press
        self._dirty_since = None
        self.glide = None                  # (from beat, to beat, seconds so far): the playhead easing somewhere
        self._bpm_seen = None
        self._bpm_since = 0.0
        self.tab_colours = {n: (screen.get("track%d_tab" % n) or {}).get("c") for n in range(1, 9)}
        if engine:
            screen.set("song", t=engine.song_label)
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
        return bool(self.clock and self.clock.active and self.engine and self.engine.sync_mode == "external")

    def say(self, text, seconds=4):
        self.message, self.message_until = text, time.monotonic() + seconds

    @property
    def linked(self):
        """Ableton Link is on: PLAY and stop go to everyone on the network."""
        return bool(self.link and self.link.on)

    def stop(self):
        self.playing = False
        if self.linked:
            self.link.request_play(False)
        if self.engine:
            self.engine.rec_ready = False
            if self.engine.save():
                self.say("SAVED")

    # ------------------------------------------------------------ actions

    def key(self, name):
        if isinstance(name, tuple):
            if name[0] == "KNOB":
                self.knob(*name[1:])
            elif name[0] == "STEP":
                self.step_key(name[1], name[2])
            elif name[0] == "STEP_CANCEL":
                i = self.seq_bank * 16 + name[1]
                if i in self.held_steps:
                    self.held_steps.remove(i)
                    self._turned.discard(i)
            elif name[0] == "HOLD":
                self.hold(name[1])
            elif name[0] == "RELEASE":
                self.release(name[1])
            self.update_screen()
            return
        t, e = self.tape, self.engine
        if name != "BOUNCE":
            self.bounce_pending = None
        if not isinstance(name, tuple) or name[0] == "KNOB":
            self.glide = None                     # any other control stops the playhead gliding
        if name == "PLAY":
            if self.playing or (self.linked and self.link._waiting):
                self.stop()
            elif self.linked:
                self.link.request_play(True)     # everyone starts, on the next bar
                self.say("STARTING ON THE NEXT BAR (LINK)", 2)
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
                self.say("INPUT: %s" % MODE_NAMES.get(e.input_mode, "NO AUDIO DEVICE"), 2)
        elif name in ("PAN_LEFT", "PAN_RIGHT"):
            self.pan(self.armed, -0.1 if name == "PAN_LEFT" else 0.1)
        elif name == "EXPORT":
            self.export()
        elif name == "BOUNCE":
            self.bounce()
        elif name == "DRUMS":
            self.drums_key()
        elif name.startswith("TRACK") and self.pad(int(name[5:])):
            pass                                  # a keyboard number key on the drum page: played
        elif name.startswith("TRACK"):
            n = int(name[5:])
            if n == self.armed or self.focus.track:
                self.focus.toggle(n)              # the selected track's key again: zoom in / out
            self.armed = n
            if e and not self.recording:
                e.arm_extra = set()               # a plain press arms just this track
        elif name == "ARM_ALL" and e:
            every = set(range(8)) - {self.armed - 1}
            e.arm_extra = set() if e.arm_extra == every else every
            self.say("ALL TRACKS ARMED" if e.arm_extra else "ONLY TRACK %d ARMED" % self.armed, 2)
        elif name.startswith("ARM") and name[3:].isdigit() and e:
            n = int(name[3:])
            if n == self.armed:
                self.say("TRACK %d IS THE SELECTED TRACK, SO IT'S ALWAYS ARMED" % n, 3)
            else:
                e.arm_extra ^= {n - 1}
                self.say("TRACK %d %s" % (n, "ARMED" if (n - 1) in e.arm_extra else "DISARMED"), 2)
        elif name == "FOCUS":
            self.focus.toggle(self.armed)
        elif name.startswith("MUTE") and name[4:] and self.seq_page and self.held_steps:
            self.unlock(int(name[4:]))            # push a knob while holding a step: take its lock off
        elif name.startswith("MUTE"):
            self.mute(int(name[4:]) if name[4:] else self.armed)
        elif name.startswith("SOLO"):
            self.solo(int(name[4:]) if name[4:] else self.armed)
        elif name in ("PHONES_UP", "PHONES_DOWN"):
            self.phones_volume(0.05 if name == "PHONES_UP" else -0.05)
        elif name in ("VOL_UP", "VOL_DOWN"):
            self.volume(self.armed, 0.05 if name == "VOL_UP" else -0.05)
        elif name == "FX":
            self.fx_page = {None: "reverb", "reverb": "delay", "delay": None}[self.fx_page]
            if self.fx_page and not effects.AVAILABLE:
                self.say(effects.PROBLEM or "EFFECTS AREN'T AVAILABLE", 4)
        elif name == "IMPORT":
            self.say("%s COMES IN A LATER VERSION" % name)
        else:
            self.edit(name)
        self.update_screen()

    # ------------------------------------------------------------ the drum synth (the DRUMS key)

    PAD_NAMES = ["DRUM 1", "DRUM 2", "DRUM 3", "SNARE", "CYMBAL", "CLOSED HAT", "OPEN HAT"]

    def drums_key(self):
        """The MIDI key: the drum page, then the sequencer, then back to the tape."""
        e = self.engine
        if self.drum_page and not self.seq_page:
            self.seq_page = True
            self.seq_lane = min(self.seq_lane, sequencer.LANES - 1)
            return
        if self.drum_page:
            self.drum_page = self.seq_page = False
            self.held_steps, self._turned = [], set()
            return
        if not e or not e.drums:
            import drums
            self.say(getattr(drums, "PROBLEM", "") or "THE DRUM SYNTH ISN'T AVAILABLE", 4)
            return
        self.drum_page = True
        if e.input_choice != "DRUMS":
            e.set_input("DRUMS", "DRUM SYNTH")
            self.say("INPUT: DRUM SYNTH  (SETTINGS > INPUT TO CHANGE BACK)", 4)

    def pad(self, n):
        """Track key n on the drum page: play voice n (7 is the hi-hat open). True if it played.
        Called from the MIDI thread, so it only reads a few flags and queues the hit."""
        e = self.engine
        if not (self.drum_page and e and e.drums_input and 1 <= n <= 7):
            return False
        e.hit(n - 1, 100)
        voice = min(n, 6) - 1                     # 7 (open hi-hat) is the hi-hat voice too
        if self.seq_page and not self.held_steps:
            self.seq_lane = n - 1                 # on the sequencer: that lane, too
        self.drum_voice = voice
        self._drum_hits[voice] = time.monotonic()
        return True

    SEQ_PAGES = [("STEP", ["vel", "chance", "ratchet"]), ("LANE", ["length", "hits", "rotate", "rate"])]
    SEQ_LABELS = {"vel": "VELOCITY", "chance": "CHANCE", "ratchet": "RATCHETS", "length": "LENGTH",
                  "hits": "EUCLID", "rotate": "SHIFT", "rate": "RATE"}

    def drum_pages(self):
        """The knob pages: the voice's sound pages, and on the sequencer STEP and LANE as well."""
        pages = list(drumparams.PAGES[self.drum_voice])
        return pages + self.SEQ_PAGES if self.seq_page else pages

    def seq_value(self, what, step=None):
        """A STEP or LANE setting as text (STEP ones for a step)."""
        e, lane = self.engine, self.seq_lane
        if what in ("vel", "chance", "ratchet"):
            if step is None:
                return "-"
            st = e.seq.step(lane, step)
            return str(st.vel) if what == "vel" else sequencer.CHANCES[st.chance] if what == "chance" else "x%d" % st.ratchet
        ln = e.seq.lane(lane)
        if what == "hits":
            return "OFF" if not ln.hits else "%d OF %d" % (ln.hits, ln.length)
        if what == "rate":
            return sequencer.RATES[ln.rate][0]
        return str(getattr(ln, what))

    def seq_fraction(self, what, step=None):
        e, lane = self.engine, self.seq_lane
        ln = e.seq.lane(lane)
        if what in ("vel", "chance", "ratchet"):
            if step is None:
                return 0.0
            st = e.seq.step(lane, step)
            return st.vel / 127 if what == "vel" else (1 - st.chance / (len(sequencer.CHANCES) - 1)) \
                if what == "chance" else st.ratchet / sequencer.MAX_RATCHET
        if what == "length":
            return ln.length / sequencer.MAX_STEPS
        if what == "hits":
            return ln.hits / ln.length
        if what == "rotate":
            return ln.rotate / max(1, ln.length - 1)
        return ln.rate / (len(sequencer.RATES) - 1)

    def step_key(self, key, down):
        """One of the 4x4 keys on the sequencer page: hold to lock settings, press and let go to toggle."""
        e = self.engine
        if not (self.seq_page and e):
            return
        i = self.seq_bank * 16 + key
        if i >= e.seq.lane(self.seq_lane).length:
            return                                # past the end of the lane: nothing there
        if down:
            if i not in self.held_steps:
                self.held_steps.append(i)
            return
        if i in self.held_steps:
            self.held_steps.remove(i)
            if i in self._turned:
                self._turned.discard(i)
            else:
                e.seq.toggle(self.seq_lane, i)
                e.seq_changed()

    def unlock(self, knob):
        e = self.engine
        page = self.drum_pages()[self.drum_tab][1] if self.drum_tab < len(self.drum_pages()) else []
        if knob > len(page) or isinstance(page[knob - 1], str):
            return
        param = page[knob - 1]
        for i in self.held_steps:
            e.seq.step(self.seq_lane, i).locks.pop(param, None)
            self._turned.add(i)
        e.seq_changed()
        self.say("%s UNLOCKED" % drumparams.LABELS[param], 2)

    def drum_knob(self, number, delta, shift):
        """On the drum pages: knobs 1-8 are the settings on the page, knob 9 turns the page. On the
        sequencer, also knob 10 the pattern and the big knob the bank of 16 steps."""
        e = self.engine
        pages = self.drum_pages()
        if number == 9:
            self.drum_tab = max(0, min(len(pages) - 1, self.drum_tab + (1 if delta > 0 else -1)))
            return
        if number == 10:
            target = e.seq.queued if e.seq.queued is not None else e.seq.current
            e.seq.choose_pattern(target + (1 if delta > 0 else -1), e.playing)
            e.seq_changed()
            return
        if number == 11:
            banks = (e.seq.lane(self.seq_lane).length - 1) // 16 + 1
            self.seq_bank = max(0, min(banks - 1, self.seq_bank + (1 if delta > 0 else -1)))
            return
        self.drum_tab = min(self.drum_tab, len(pages) - 1)
        page_name, params = pages[self.drum_tab]
        if number > len(params):
            return
        param = params[number - 1]
        now = time.monotonic()
        fast = now - self._knob_times.get(number, 0) < 0.05
        self._knob_times[number] = now
        clicks = delta if shift else delta * (4 if fast else 1)    # turning quickly goes further; SHIFT: fine
        lane_name = sequencer.LANE_NAMES[self.seq_lane]
        if page_name == "STEP":
            if not self.held_steps:
                self.say("HOLD A STEP AND TURN TO SET ITS %s" % self.SEQ_LABELS[param], 3)
                return
            for i in self.held_steps:
                e.seq.change_step(self.seq_lane, i, param, clicks)
                self._turned.add(i)
            e.seq_changed()
            self.say("STEP %d  %s  %s" % (self.held_steps[0] + 1, self.SEQ_LABELS[param],
                                          self.seq_value(param, self.held_steps[0])), 2)
            return
        if page_name == "LANE":
            e.seq.change_lane(self.seq_lane, param, clicks if param == "length" else delta)
            e.seq_changed()
            banks = (e.seq.lane(self.seq_lane).length - 1) // 16 + 1
            self.seq_bank = min(self.seq_bank, banks - 1)
            self.say("%s  %s  %s" % (lane_name, self.SEQ_LABELS[param], self.seq_value(param)), 2)
            return
        if self.seq_page and self.held_steps:
            if not e.drums.lockable(param):
                self.say("%s CAN'T BE LOCKED TO A STEP" % drumparams.LABELS[param], 3)
                return
            for i in self.held_steps:
                st = e.seq.step(self.seq_lane, i)
                base = st.locks.get(param, e.drums.get_param(param))
                e.seq.set_lock(self.seq_lane, i, param, e.drums.stepped(param, base, clicks))
                self._turned.add(i)
            e.seq_changed()
            v = e.seq.step(self.seq_lane, self.held_steps[0]).locks[param]
            self.say("STEP %d  %s  %s  (LOCKED)" % (self.held_steps[0] + 1, drumparams.LABELS[param],
                                                     e.drums.value_text(param, v)), 2)
            return
        e.change_drum(param, clicks)
        self.say("%s  %s  %s" % (drums_mod().NAMES[self.drum_voice], drumparams.LABELS[param],
                                 e.drums.value_text(param)), 2)

    def knob(self, number, delta, shift):
        t = self.tape
        if self.drum_page and self.engine and self.engine.drums and (number <= 9 or
                                                                     (self.seq_page and not (number == 10 and shift))):
            self.drum_knob(number, delta, shift)
        elif self.fx_page and self.engine and not (number == 10 and shift):
            self.fx_knob(number, delta)
        elif number <= 8:
            if shift:
                self.pan(number, delta * 0.05)          # SHIFT + a track knob: pan
            else:
                self.volume(number, delta * 0.02)
        elif number == 9:
            for _ in range(abs(delta)):
                t.zoom_in() if delta > 0 else t.zoom_out()
        elif number == 10 and shift:
            self.phones_volume(delta * 0.02)       # SHIFT + knob 10: headphone volume
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
        if e and self.linked and not self.playing:
            e.rec_ready = True                    # recording starts with the tape, on Link's next bar
            self.link.request_play(True)
            self.say("RECORDING FROM THE NEXT BAR (LINK)", 3)
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

    # ------------------------------------------------------------ send effects (the FX key)

    FX_KNOBS = {"reverb": (("rev_size", "SIZE"), ("rev_tone", "TONE"), ("rev_level", "LEVEL")),
                "delay": (("dly_time", "TIME"), ("dly_feedback", "FEEDBACK"), ("dly_level", "LEVEL"))}

    def fx_knob(self, number, delta):
        """On an FX page: knobs 1-8 are the tracks' sends, 9 and 10 the effect's settings, the big knob its level."""
        e = self.engine
        if number <= 8:
            e.change_send(self.fx_page, number, delta * 0.02)
        else:
            key = self.FX_KNOBS[self.fx_page][number - 9][0]
            e.change_fx(key, delta if key == "dly_time" else delta * 0.02)

    def fx_value_text(self, key):
        v = self.engine.fx[key]
        if key == "dly_time":
            return v
        return "%d%%" % round(v * 100)

    def draw_page(self, surf, it=None):
        if self.seq_page and self.engine and self.engine.drums:
            self.draw_seq(surf)
        elif self.drum_page and self.engine and self.engine.drums:
            self.draw_drums(surf)
        else:
            self.draw_fx(surf, it)

    def draw_drums(self, surf):
        """The drum page: knob n's setting across track n's lane, and the voices and pages on the right."""
        s, e = self.s, self.engine
        d = e.drums
        small, mid, big = s.font("mono", 600, 14), s.font("mono", 600, 18), s.font("mono", 700, 26)
        accent, grey, white = (255, 181, 71), (125, 131, 140), (242, 243, 245)
        home = lambda n, part: self.focus.home.get((n, part)) or s.get("track%d_%s" % (n, part))
        first, last = home(1, "lane"), home(8, "lane")
        surf.set_clip(None)
        pygame.draw.rect(surf, (12, 13, 16), (0, first["y"] - 4, 1280, last["y"] + last["h"] - first["y"] + 8))
        pages = self.drum_pages()
        self.drum_tab = min(self.drum_tab, len(pages) - 1)
        page_name, params = pages[self.drum_tab]
        label_x, bar_x, bar_w = 72, 230, 470
        for n in range(1, 9):
            lane, tab = home(n, "lane"), home(n, "tab")
            if not lane:
                continue
            on = n <= len(params)
            if tab:
                pygame.draw.rect(surf, accent if on else (40, 43, 50), (tab["x"], tab["y"], tab["w"], tab["h"]), border_radius=6)
                num = s.font("mono", 600, 16).render(str(n), True, (12, 13, 16))
                surf.blit(num, (tab["x"] + (tab["w"] - num.get_width()) // 2, tab["y"] + (tab["h"] - num.get_height()) // 2))
            if not on:
                continue
            param = params[n - 1]
            mid_y = lane["y"] + lane["h"] // 2
            name = mid.render(drumparams.LABELS[param], True, white)
            surf.blit(name, (label_x, mid_y - name.get_height() // 2))
            y, h = lane["y"] + 8, lane["h"] - 16
            pygame.draw.rect(surf, (40, 43, 50), (bar_x, y, bar_w, h), border_radius=3)
            w = round(bar_w * max(0.0, min(1.0, d.fraction(param))))
            if w:
                pygame.draw.rect(surf, accent, (bar_x, y, w, h), border_radius=3)
            value = small.render(d.value_text(param), True, white)
            surf.blit(value, (bar_x + bar_w + 12, mid_y - value.get_height() // 2))
        # the box on the right: the voices (light up when played) and this voice's pages
        bx, by = 880, first["y"]
        bw, bh = first["x"] + first["w"] - bx, last["y"] + last["h"] - by
        pygame.draw.rect(surf, (20, 22, 26), (bx, by, bw, bh), border_radius=6)
        pygame.draw.rect(surf, accent, (bx, by, bw, bh), 2, border_radius=6)
        names = drums_mod().NAMES
        surf.blit(big.render(names[self.drum_voice], True, accent), (bx + 18, by + 14))
        hint = small.render("KEYS 1-7 PLAY", True, grey)
        surf.blit(hint, (bx + bw - 18 - hint.get_width(), by + 22))
        now = time.monotonic()
        cell = (bw - 36) // 6
        for v in range(6):
            x0, y0 = bx + 18 + v * cell, by + 56
            glow = max(0.0, 1.0 - (now - self._drum_hits[v]) / 0.25)
            base = (60, 64, 72) if v != self.drum_voice else (120, 92, 40)
            colour = tuple(round(c + (255 - c) * glow) for c in base)
            pygame.draw.rect(surf, colour, (x0, y0, cell - 6, 26), border_radius=4)
            t = small.render(str(v + 1), True, (12, 13, 16) if (glow > 0.3 or v == self.drum_voice) else white)
            surf.blit(t, (x0 + (cell - 6 - t.get_width()) // 2, y0 + 4))
        py = by + 100
        surf.blit(small.render("KNOB 9: PAGE", True, grey), (bx + 18, py))
        for i, (pname, _) in enumerate(pages):
            colour = accent if i == self.drum_tab else grey
            surf.blit(mid.render(("> " if i == self.drum_tab else "  ") + pname, True, colour), (bx + 18, py + 24 + i * 26))

    def draw_seq(self, surf):
        """The sequencer page: what each knob does along the top, the settings (locked ones green while a
        step is held), the lane and pattern on the right, and the lane's steps along the bottom."""
        s, e = self.s, self.engine
        d, seq = e.drums, e.seq
        tiny, small, mid, big = (s.font("mono", 600, 12), s.font("mono", 600, 14), s.font("mono", 600, 17),
                                 s.font("mono", 700, 24))
        yellow, green, grey, white, dark = (255, 181, 71), (60, 203, 127), (125, 131, 140), (242, 243, 245), (40, 43, 50)
        purple = (178, 120, 255)
        surf.set_clip(None)
        pygame.draw.rect(surf, (12, 13, 16), (0, 36, 1280, 330))
        pages = self.drum_pages()
        self.drum_tab = min(self.drum_tab, len(pages) - 1)
        page_name, params = pages[self.drum_tab]
        held = self.held_steps[0] if self.held_steps else None
        lane = seq.lane(self.seq_lane)
        if held is not None and held >= lane.length:
            held = None
        step = seq.step(self.seq_lane, held) if held is not None else None

        def label(p):
            return self.SEQ_LABELS[p] if isinstance(p, str) else drumparams.LABELS[p]

        # what each knob does, in order: 1-8, then 9, 10 and the big knob
        names = [label(params[i]) if i < len(params) else "" for i in range(8)] + ["PAGE", "PATTERN", "BANK"]
        x, w, gap = 20, 106, 6
        for n, text in enumerate(names):
            pygame.draw.rect(surf, (60, 64, 72) if text else (26, 28, 33), (x, 42, w, 22), 1, border_radius=4)
            if text:
                t = tiny.render(text, True, white if n < 8 else grey)
                surf.blit(t, (x + (w - t.get_width()) // 2, 46))
            x += w + gap
        # the settings, one row per knob
        top, row_h, bar_x, bar_w = 74, 26, 160, 420
        for n in range(8):
            y = top + n * row_h
            num = tiny.render(str(n + 1), True, grey)
            surf.blit(num, (24, y + 6))
            if n >= len(params):
                continue
            p = params[n]
            surf.blit(small.render(label(p), True, white), (44, y + 4))
            if isinstance(p, str):
                frac = self.seq_fraction(p, held)
                text, colour = self.seq_value(p, held), yellow
                if p in ("vel", "chance", "ratchet") and held is not None:
                    colour = green
            elif step is not None and p in step.locks:
                frac, text, colour = d.fraction(p, step.locks[p]), d.value_text(p, step.locks[p]) + "  LOCK", green
            else:
                frac, text, colour = d.fraction(p), d.value_text(p), yellow
            pygame.draw.rect(surf, dark, (bar_x, y + 5, bar_w, row_h - 10), border_radius=3)
            if frac > 0:
                pygame.draw.rect(surf, colour, (bar_x, y + 5, round(bar_w * min(1.0, frac)), row_h - 10), border_radius=3)
            surf.blit(small.render(text, True, white), (bar_x + bar_w + 12, y + 4))
        # the box on the right: lane, pattern, page
        bx, by, bw, bh = 760, 74, 500, 8 * row_h - 4
        pygame.draw.rect(surf, (20, 22, 26), (bx, by, bw, bh), border_radius=6)
        pygame.draw.rect(surf, yellow, (bx, by, bw, bh), 2, border_radius=6)
        surf.blit(big.render(sequencer.LANE_NAMES[self.seq_lane], True, yellow), (bx + 16, by + 10))
        pat = "PATTERN %d" % (seq.current + 1)
        if seq.queued is not None:
            pat += "  > %d NEXT" % (seq.queued + 1)
        t = mid.render(pat, True, white)
        surf.blit(t, (bx + bw - 16 - t.get_width(), by + 14))
        info = "%d STEPS  \u00b7  %s  \u00b7  PAGE: %s" % (lane.length, sequencer.RATES[lane.rate][0], page_name)
        surf.blit(small.render(info, True, grey), (bx + 16, by + 48))
        if held is not None:
            locks = len(step.locks)
            text = "STEP %d HELD%s" % (held + 1, "  \u00b7  %d LOCK%s" % (locks, "" if locks == 1 else "S") if locks else "")
            surf.blit(mid.render(text, True, green), (bx + 16, by + 74))
            hint = "TURN A KNOB TO LOCK IT  \u00b7  PUSH IT TO UNLOCK"
        else:
            hint = "HOLD A STEP AND TURN A KNOB TO LOCK A SETTING"
        surf.blit(tiny.render(hint, True, grey), (bx + 16, by + 104))
        # the 7 lanes: lit when they play, the one being edited outlined
        now = time.monotonic()
        cell = (bw - 32) // 7
        for li in range(sequencer.LANES):
            x0, y0 = bx + 16 + li * cell, by + 128
            v = sequencer.LANE_VOICE[li]
            t_seq = e.seq_hits[li] if e.seq_hits[li] <= now else 0.0
            t_hit = max(self._drum_hits[v] if li < 6 else 0.0, t_seq)
            glow = max(0.0, 1.0 - (now - t_hit) / 0.25)
            base = (60, 64, 72)
            colour = tuple(round(c + (255 - c) * glow) for c in base)
            pygame.draw.rect(surf, colour, (x0, y0, cell - 6, 24), border_radius=4)
            if li == self.seq_lane:
                pygame.draw.rect(surf, yellow, (x0, y0, cell - 6, 24), 2, border_radius=4)
            t = tiny.render(str(li + 1), True, (12, 13, 16) if glow > 0.3 else white)
            surf.blit(t, (x0 + (cell - 6 - t.get_width()) // 2, y0 + 5))
        filled = sum(1 for i in range(lane.length) if lane.steps[i].on)
        surf.blit(tiny.render("%d OF %d STEPS ON" % (filled, lane.length), True, grey), (bx + 16, by + 162))
        # the lane's steps: hollow = off, yellow = on, green = held; the bank the 4x4 keys reach is brighter
        playing_at = None
        if e.playing:
            playing_at = seq.position(e._heard_frame(), e.frames_per_beat())[self.seq_lane]
        bw16, sw, sh, y0 = 16 * 17 + 12, 15, 22, 300
        for i in range(lane.length):
            bank, k = divmod(i, 16)
            x0 = 20 + bank * (bw16 + 24) + k * 17 + (k // 4) * 4
            st = lane.steps[i]
            in_bank = bank == self.seq_bank
            outline = white if in_bank else (90, 95, 104)
            # filled yellow = plays, purple outline = has locks (both: yellow with a purple outline)
            if i in self.held_steps:
                pygame.draw.rect(surf, green, (x0, y0, sw, sh), border_radius=3)
            elif st.on:
                pygame.draw.rect(surf, yellow if in_bank else (150, 110, 50), (x0, y0, sw, sh), border_radius=3)
            if st.locks:
                pygame.draw.rect(surf, purple if in_bank else (110, 80, 160), (x0, y0, sw, sh), 2, border_radius=3)
            elif not st.on and i not in self.held_steps:
                pygame.draw.rect(surf, outline, (x0, y0, sw, sh), 1, border_radius=3)
            if i == playing_at:
                pygame.draw.rect(surf, white, (x0, y0 + sh + 4, sw, 3))
        for bank in range((lane.length - 1) // 16 + 1):
            x0 = 20 + bank * (bw16 + 24)
            t = tiny.render("%d-%d" % (bank * 16 + 1, min(lane.length, bank * 16 + 16)), True,
                            white if bank == self.seq_bank else grey)
            surf.blit(t, (x0, y0 + sh + 10))

    def draw_fx(self, surf, it=None):
        """The FX page: each track's send as a bar across its lane, and the effect's settings on the right."""
        page, e = self.fx_page, self.engine
        if not page or not e:
            return
        s = self.s
        sends = e.rev_sends if page == "reverb" else e.dly_sends
        small, mid, big = s.font("mono", 600, 14), s.font("mono", 600, 18), s.font("mono", 700, 26)
        bar_x, bar_w = 72, 720
        # the layout's own positions: the zoomed track view moves the real items around
        home = lambda n, part: self.focus.home.get((n, part)) or s.get("track%d_%s" % (n, part))
        first, last = home(1, "lane"), home(8, "lane")
        surf.set_clip(None)
        pygame.draw.rect(surf, (12, 13, 16), (0, first["y"] - 4, 1280, last["y"] + last["h"] - first["y"] + 8))
        for n in range(1, 9):
            lane, tab = home(n, "lane"), home(n, "tab")
            if not lane:
                continue
            colour = ui.rgb(tab["c"]) if tab else (200, 200, 200)
            if tab:
                pygame.draw.rect(surf, colour, (tab["x"], tab["y"], tab["w"], tab["h"]), border_radius=6)
                num = s.font("mono", 600, 16).render(str(n), True, (12, 13, 16))
                surf.blit(num, (tab["x"] + (tab["w"] - num.get_width()) // 2, tab["y"] + (tab["h"] - num.get_height()) // 2))
            y, h = lane["y"] + 8, lane["h"] - 16
            pygame.draw.rect(surf, (40, 43, 50), (bar_x, y, bar_w, h), border_radius=3)
            w = round(bar_w * sends[n - 1])
            if w:
                pygame.draw.rect(surf, colour, (bar_x, y, w, h), border_radius=3)
            label = small.render("%d%%" % round(sends[n - 1] * 100), True, (242, 243, 245))
            surf.blit(label, (bar_x + bar_w + 12, lane["y"] + (lane["h"] - label.get_height()) // 2))
        # the settings box on the right
        bx, by = 880, first["y"]
        bw, bh = first["x"] + first["w"] - bx, last["y"] + last["h"] - by
        pygame.draw.rect(surf, (20, 22, 26), (bx, by, bw, bh), border_radius=6)
        pygame.draw.rect(surf, (60, 203, 127), (bx, by, bw, bh), 2, border_radius=6)
        title = big.render(page.upper(), True, (60, 203, 127))
        surf.blit(title, (bx + 18, by + 14))
        hint = small.render("KNOBS 1-8: SENDS", True, (125, 131, 140))
        surf.blit(hint, (bx + bw - 18 - hint.get_width(), by + 22))
        if not effects.AVAILABLE:
            msg = small.render(effects.PROBLEM or "EFFECTS AREN'T AVAILABLE", True, (255, 181, 71))
            surf.blit(msg, (bx + 18, by + 60))
            return
        for i, (key, name) in enumerate(self.FX_KNOBS[page]):
            ry = by + 66 + i * 76
            knob = ("KNOB 9", "KNOB 10", "BIG KNOB")[i]
            surf.blit(mid.render(name, True, (242, 243, 245)), (bx + 18, ry))
            surf.blit(small.render(knob, True, (125, 131, 140)), (bx + 18, ry + 26))
            value = mid.render(self.fx_value_text(key), True, (242, 243, 245))
            surf.blit(value, (bx + bw - 18 - value.get_width(), ry))
            if key == "dly_time":
                names = [n for n, _ in effects.DELAY_TIMES]
                frac = (names.index(e.fx[key]) + 1) / len(names) if e.fx[key] in names else 0
            else:
                frac = e.fx[key] / (0.95 if key == "dly_feedback" else 1.0)
            pygame.draw.rect(surf, (40, 43, 50), (bx + 130, ry + 30, bw - 148, 8), border_radius=4)
            if frac > 0:
                pygame.draw.rect(surf, (60, 203, 127), (bx + 130, ry + 30, round((bw - 148) * frac), 8), border_radius=4)

    def phones_volume(self, delta):
        e = self.engine
        if not e:
            return
        v = e.change_phones_volume(delta)
        if e.port:
            note = "" if e.route == "phones" else "  (%s)" % e.output_label
        else:
            note = "  (OUTPUT IS %s: USE ITS OWN VOLUME)" % (e.output_label or "NOT SET")
        self.say("VOLUME %d%%%s" % (round(v * 100), note), 2)

    def edit_text(self):
        ts = self.engine.edit_tracks()
        return "TRACKS %d+%d (STEREO)" % (ts[0] + 1, ts[1] + 1) if len(ts) == 2 else "TRACK %d" % (ts[0] + 1)

    def draw_num(self, surf, it):
        """The track number, plus a bracket joining a stereo pair's two tabs."""
        self.s.draw_default(surf, it)
        e = self.engine
        n = int(it["name"][5:it["name"].index("_")])
        if not e or (n - 1) not in e.pairs or self.focus.active:
            return
        a, b = self.s.get("track%d_tab" % n), self.s.get("track%d_tab" % (n + 1))
        if not a or not b:
            return
        x = a["x"] - 6
        y0, y1 = a["y"] + 4, b["y"] + b["h"] - 4
        col = (205, 210, 218)
        pygame.draw.line(surf, col, (x, y0), (x, y1), 2)
        pygame.draw.line(surf, col, (x, y0), (x + 3, y0), 2)
        pygame.draw.line(surf, col, (x, y1), (x + 3, y1), 2)

    def pan(self, track, delta):
        if not self.engine:
            return
        self.say("TRACK %d  PAN %s" % (track, self.pan_text(self.engine.change_pan(track, delta))), 2)

    @staticmethod
    def pan_text(p):
        if abs(p) < 0.01:
            return "CENTRE"
        return "%s %d" % ("L" if p < 0 else "R", round(abs(p) * 100))

    def solo(self, track):
        if not self.engine:
            return
        on = self.engine.toggle_solo(track)
        others = sorted(t + 1 for t in self.engine.solos)
        self.say("TRACK %d SOLO %s%s" % (track, "ON" if on else "OFF",
                                          "  (SOLOED: %s)" % ",".join(map(str, others)) if others else ""), 2)

    def mute(self, track):
        if not self.engine:
            return
        muted = self.engine.toggle_mute(track)
        self.say("TRACK %d %s" % (track, "MUTED" if muted else "ON"), 2)

    def hold(self, name):
        """LIFT or CUT pressed on the board: start selecting from the piece under the playhead."""
        if self.engine and not self.recording:
            self.engine.begin_selection()
            self.holding = name
            self.say("MOVE TO TAKE MORE PIECES, LET GO TO %s" % ("COPY" if name == "COPY" else "CUT"), 30)

    def release(self, name):
        if self.holding == name:
            self.holding = None
            self.message_until = 0
            self.edit(name)

    def edit(self, name):
        e = self.engine
        if not e:
            self.say("EDITING NEEDS THE AUDIO ENGINE")
            return
        pos = self.position_text(self.tape.pos)
        if name == "LOOP":
            e.toggle_loop()
            self.say("LOOP ON" if e.loop_on else "LOOP OFF", 2)
            return
        if name in ("LOOP_IN", "LOOP_OUT"):
            e.set_loop_point("in" if name == "LOOP_IN" else "out", self.tape.pos)
            self.say("%s POINT AT %s" % ("IN" if name == "LOOP_IN" else "OUT", pos), 2)
            return
        if name == "CLEAR_REGION":
            e.clear_region()
            self.say("IN/OUT POINTS CLEARED", 2)
            return
        if name == "REC_MODE":
            self.say("RECORDING %s" % ("ADDS TO THE TAPE (OVERDUB)" if e.toggle_rec_mode() == "overdub"
                                       else "REPLACES THE TAPE"), 3)
            return
        if self.recording:
            self.say("STOP RECORDING FIRST")
            return
        if name == "SELECT":
            if e.sel_anchor is None:
                e.begin_selection()
                self.say("SELECTING: MOVE TO TAKE MORE PIECES, THEN COPY OR CUT", 30)
            else:
                e.end_selection()
                self.say("SELECTION CANCELLED", 2)
        elif name == "COPY":
            beats = e.copy()
            if beats:
                self.glide_to_edit(0)
            self.say("COPIED %s FROM %s" % (self.beats_text(beats), self.edit_text()) if beats
                     else "NOTHING HERE TO COPY")
        elif name == "CUT":
            beats = e.cut()
            if beats:
                self.glide_to_edit(0)
            self.say("CUT %s FROM %s" % (self.beats_text(beats), self.edit_text()) if beats
                     else "NOTHING HERE TO CUT")
        elif name in ("DROP", "DROP_INSERT"):
            done = e.drop(insert=name == "DROP_INSERT")
            if done is True:
                self.glide_to_edit(1)
                ts = e.edit_tracks() if len(e.clip) == 2 else [self.armed - 1]
                where = "TRACKS %d+%d" % (ts[0] + 1, ts[0] + 2) if len(e.clip) == 2 else "TRACK %d" % self.armed
                self.say("DROPPED ON %s AT %s%s" % (where, pos, ", PUSHING THE REST LATER" if name == "DROP_INSERT" else ""))
            else:
                self.say(done)
        elif name in ("SPLICE", "SPLICE_ALL"):
            done = e.splice(name == "SPLICE_ALL")
            ts = set(e.armed_tracks())
            ts |= {p for t in ts for p in (t - 1, t + 1) if 0 <= p < 8 and min(t, p) in e.pairs}
            where = "ALL TRACKS" if name == "SPLICE_ALL" else self.armed_text(sorted(t + 1 for t in ts))
            self.say("SPLIT %s AT %s" % (where, pos) if done == "added"
                     else "JOINED BACK TOGETHER ON %s" % where if done == "removed"
                     else "NO BOX HERE TO SPLIT", 2)
        elif name == "UNDO":
            self.say("UNDONE" if e.undo() else "NOTHING TO UNDO", 2)

    def new_song(self, name):
        self.focus.track = None
        self.engine.new_song(name)
        self.tape.pos = 0.0
        self.s.set("song", t=name)
        self.say("NEW PROJECT: %s" % name.upper(), 5)

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
            self.update_glide(seconds)
            was = self._playing
            t.pos = e.beats()
            self._playing = e.playing
            if was and not self._playing:           # stopped by the tape end, or by MIDI stop
                self.stop()
            self.follow_tempo()
            if self.link and self.link.message:
                self.say(self.link.message, 3)
                self.link.message = ""
            self.autosave()
            dirty = getattr(e, "_phones_dirty", None)
            if dirty and time.monotonic() - dirty > 1.0:
                e.save_phones_volume()              # once the knob has stopped turning
        elif self.playing:
            start = t.pos
            t.pos += seconds * BPM / 60
            if t.pos >= tape.TAPE_BEATS:
                t.pos = float(tape.TAPE_BEATS)
                self.playing = self.recording = False
            if self.recording:
                t.record(self.armed, start, t.pos)
        self.focus.update(seconds, self.playing)
        self.update_screen()

    def glide_to_edit(self, which):
        """Ease the playhead to the start (0) or end (1) of the box just lifted, cut or dropped."""
        e = self.engine
        if not e.last_edit or self.playing:
            return
        to = e.last_edit[which] / e.frames_per_beat()
        here = e.beats()
        if abs(to - here) > 1e-6:
            self.glide = (here, to, 0.0)

    def update_glide(self, seconds):
        if not self.glide:
            return
        if self.playing:
            self.glide = None
            return
        a, b, done = self.glide
        length = min(0.9, 0.3 + 0.04 * abs(b - a) ** 0.5)          # longer moves take a little longer
        done += seconds
        f = min(1.0, done / length)
        f = f * f * (3 - 2 * f)                                       # ease in and out
        self.engine.set_beats(a + (b - a) * f)
        self.glide = None if done >= length else (a, b, done)

    def autosave(self):
        """While stopped, write changes to the song's files a moment after the last edit."""
        e = self.engine
        if self.playing or not e.dirty:
            self._dirty_since = None
            return
        now = time.monotonic()
        if self._dirty_since is None:
            self._dirty_since = now
        elif now - self._dirty_since > 1.0:
            self._dirty_since = None
            e.save()

    def bounce(self):
        e = self.engine
        if not e:
            self.say("BOUNCING NEEDS THE AUDIO ENGINE")
            return
        if self.playing:
            self.say("STOP FIRST, THEN BOUNCE")
            return
        sources = sorted(e.arm_extra)
        dest = self.armed - 1
        if not sources:
            self.say("ARM THE TRACKS TO BOUNCE WITH SHIFT+TRACK; THEY GO ONTO THE SELECTED TRACK", 6)
            return
        names = ",".join(str(t + 1) for t in sources)
        if self.bounce_pending != (tuple(sources), dest):
            self.bounce_pending = (tuple(sources), dest)
            self.say("BOUNCE TRACK%s %s INTO TRACK %d? PRESS AGAIN TO DO IT" % ("S" if len(sources) > 1 else "", names, dest + 1), 8)
            return
        self.bounce_pending = None
        beats = e.bounce(sources, dest)
        if beats is None:
            self.say("NOTHING TO BOUNCE")
            return
        e.arm_extra = set()
        self.say("BOUNCED %s INTO TRACK %d (SHIFT+CUT UNDOES)" % (names, dest + 1), 5)

    def follow_tempo(self):
        """Take the OP-XY's tempo while stopped, once it has held steady for a moment."""
        bpm = self.clock.bpm if (self.clock and self.synced) else None
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

    def panel_lines(self):
        e, n = self.engine, self.focus.shown
        if not e:
            return ["DEMO MODE", "NO AUDIO ENGINE"]
        vol = "VOLUME %d%%  PAN %s%s" % (round(e.volumes[n - 1] * 100), self.pan_text(e.pans[n - 1]),
                                         "  MUTED" if (n - 1) in e.mutes else "  SOLO" if (n - 1) in e.solos else "")
        mode = "REC: OVERDUB" if e.rec_mode == "overdub" else "REC: REPLACE"
        r = e.loop_region()
        fpb = e.frames_per_beat()
        inout = ("IN %s  OUT %s" % (self.position_text(r[0] / fpb), self.position_text(r[1] / fpb))) if r else "NO IN/OUT POINTS"
        if e.clip is not None:
            clip = "CLIPBOARD %s%s" % (self.beats_text(len(e.clip[0]) / fpb), "  STEREO" if len(e.clip) == 2 else "")
        else:
            clip = "CLIPBOARD EMPTY"
        return [vol, mode, inout, clip]

    def armed_text(self, armed):
        if len(armed) == 8:
            return "ALL TRACKS"
        if len(armed) == 1:
            return "TRACK %d" % armed[0]
        return "TRACKS " + ",".join(str(n) for n in armed)

    def beats_text(self, beats):
        if beats >= 4 and abs(beats / 4 - round(beats / 4)) < 0.01:
            bars = round(beats / 4)
            return "%d BAR%s" % (bars, "" if bars == 1 else "S")
        return "%g BEAT%s" % (round(beats, 2), "" if abs(beats - 1) < 0.01 else "S")

    def position_text(self, beats):
        bar = math.floor(beats / tape.BEATS_PER_BAR + 1e-9)
        within = max(0.0, beats - bar * tape.BEATS_PER_BAR)
        beat = math.floor(within / tape.BEAT_UNIT + 1e-9)
        sixteenth = math.floor((within - beat * tape.BEAT_UNIT) * 4 + 1e-9)
        return "%03d.%d.%d" % (bar + 1, beat + 1, sixteenth + 1)

    def update_screen(self):
        s, t, e = self.s, self.tape, self.engine
        s.set("clock", t=self.position_text(t.pos))
        region = e.loop_region() if e else None
        s.set("grid", t=t.label() + ("   LOOP" if (region and e.loop_on) else "   IN/OUT" if region else ""))
        bpm = e.bpm if e else BPM
        internal = bool(e and e.sync_mode == "internal")
        if e and tuple(e.time_sig) != tape.SIG:
            tape.set_signature(*e.time_sig)
        sync = "  SYNC" if self.synced else "  LEAD" if internal else ""
        if self.linked:
            sync = "  LINK %d" % self.link.peers
        s.set("bpm", t="%.1f BPM  %s%s" % (bpm, tape.signature_text(), sync))
        all_in = bool(e and e.device and e.input_mode == "all")
        armed = [t + 1 for t in e.armed_tracks()] if e else [self.armed]
        first, last, lane = s.get("track1_lane"), s.get("track8_lane"), s.get("track%d_lane" % self.armed)
        if self.focus.active:
            lane = s.get("track%d_lane" % self.focus.shown)
            if lane:
                s.set("rec_outline", y=lane["y"] - 2, h=lane["h"] + 4)
        elif lane:
            s.set("rec_outline", y=lane["y"] - 2, h=lane["h"] + 4)
        ready = bool(e and e.rec_ready)
        state = "RECORDING" if self.recording else "REC READY" if ready else "PLAYING" if self.playing else "STOPPED"
        overdub = bool(e and e.rec_mode == "overdub")
        selecting = bool(e and e.sel_anchor is not None)
        s.set("status", t="%s  %s%s%s" % (state, self.armed_text(armed),
                                          "  OVERDUB" if overdub else "", "  SELECTING" if selecting else ""))
        if self.focus.active:
            self.focus.info["lines"] = self.panel_lines()
        red = "#FF5A4E" if (self.recording or ready) else "#7D838C"
        t.extra_armed = {n for n in armed if n != self.armed}
        t.arm_colour = ui.rgb(red)
        s.set("rec_dot", c=red)
        s.set("rec_outline", c=red)

        if self.message and time.monotonic() < self.message_until:
            hint = self.message
        elif not e:
            hint = "DEMO: NO AUDIO ENGINE"
        elif self.drum_page and not (e.device and e.drums_input):
            hint = "DRUM SYNTH STARTING..."
        elif self.seq_page:
            mode = MODE_NAMES.get(e.input_mode, "")
            where = (", ".join("%d+%d" % (t + 1, t + 2) for t in e.stereo_pairs_armed()) or "ARM 2 TRACKS SIDE BY SIDE"
                     if e.input_mode == "stereo" else self.armed_text(armed))
            hint = "SEQUENCER  \u00b7  %s > %s  \u00b7  MIDI KEY: BACK TO THE TAPE" % (mode, where)
        elif self.drum_page:
            mode = MODE_NAMES.get(e.input_mode, "")
            where = (", ".join("%d+%d" % (t + 1, t + 2) for t in e.stereo_pairs_armed()) or "ARM 2 TRACKS SIDE BY SIDE"
                     if e.input_mode == "stereo" else self.armed_text(armed))
            hint = "DRUMS  ·  %s > %s  ·  MIDI KEY TO LEAVE" % (mode, where)
        elif self.fx_page:
            hint = "FX: %s  \u00b7  PRESS FX FOR %s" % (self.fx_page.upper(), "DELAY" if self.fx_page == "reverb" else "THE TRACKS")
        elif not e.device:
            hint = e.status or "NO AUDIO DEVICE"
        elif all_in:
            hint = "%s  MULTI > %s" % (e.device["name"].upper(), self.armed_text(armed))
        elif e.input_mode == "stereo":
            pairs = e.stereo_pairs_armed()
            hint = "%s  STEREO > %s" % (e.device["name"].upper(),
                                        ", ".join("%d+%d" % (t + 1, t + 2) for t in pairs) if pairs
                                        else "ARM 2 TRACKS SIDE BY SIDE")
        else:
            hint = "%s  MONO > %s" % (e.device["name"].upper(), self.armed_text(armed))
        s.set("hint", t=hint)

        targets = e.targets() if (e and e.device) else {}
        for n in range(1, 9):
            muted = bool(e and not e.audible(n - 1))      # muted, or another track is soloed
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

    pygame.display.init()                   # not pygame.init(): that would grab the Pi's default sound device
    pygame.font.init()
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
        board = Board(keys)
        _ctl, _clk, clock = midi.start(board, engine, settings.get("clock_device"))
    except Exception as e:
        board = None
        print("No MIDI input:", e)
    transport = Transport(screen, engine, clock)
    if engine:
        import linksync
        transport.link = linksync.LinkSync(engine)
    if board:
        board.pads = transport.pad
        board.seq_page = lambda: transport.seq_page
    project_menu = menu.Menu(os.path.join(HERE, "layouts", "menu.ui"), transport)
    project_menu.kits = kitmenu.KitMenu(os.path.join(HERE, "layouts", "menu.ui"), transport)
    restore_terminal = start_terminal_keys(keys)
    fps = pygame.time.Clock()

    try:
        run_loop(keys, screen, frame, display, transport, project_menu, fps, rotate, dw, dh)
    except Exception:
        import traceback
        details = traceback.format_exc()
        try:
            import audio
            audio.log("Console crashed", details)
        except Exception:
            print(details)
        raise
    finally:
        if restore_terminal:
            restore_terminal()
        if engine:
            transport.playing = False
            engine.stop()
            engine.save(wait=True)
        pygame.quit()
    if project_menu.restart:
        import updater
        print("Restarting with the new version...")
        sys.exit(updater.RESTART_CODE)          # run.sh (or the boot service) starts the app again


def run_loop(keys, screen, frame, display, transport, project_menu, fps, rotate, dw, dh):
    """The main loop: keys in, screen out, until Q."""
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
            elif project_menu.open:
                project_menu.key(name)
            elif project_menu.kits.open:
                project_menu.kits.key(name)
            elif name == "FILE" and transport.drum_page:
                project_menu.kits.show()            # on the drum page, FILE is the drum kit menu
            elif name == "FILE":
                project_menu.show()
            elif not (isinstance(name, tuple) and name[0] == "CHAR"):
                transport.key(name)
            TEXT_INPUT["on"] = project_menu.text_input or project_menu.kits.text_input
        transport.tick(seconds)
        if project_menu.restart:
            running = False                         # a software update was installed: start again

        if project_menu.open:
            project_menu.draw(frame)
        elif project_menu.kits.open:
            project_menu.kits.draw(frame)
        else:
            screen.draw(frame)
        out = pygame.transform.rotate(frame, rotate) if rotate else frame
        if out.get_size() != (dw, dh):
            scale = min(dw / out.get_width(), dh / out.get_height())
            size = (round(out.get_width() * scale), round(out.get_height() * scale))
            out = pygame.transform.smoothscale(out, size)
            display.fill((0, 0, 0))
        display.blit(out, ((dw - out.get_width()) // 2, (dh - out.get_height()) // 2))
        pygame.display.flip()


if __name__ == "__main__":
    main()
