"""Console on the Ableton Move: the Pi app's own logic (console.Transport, the menus, the engine) with the
Move's controls and screen. Run in console mode:

    python3 /data/UserData/console/move/app.py

The engine makes its sound with the C sound core (core/bridge.py). The Pi app's drawing is never used: it runs
with the simulator's stand-in pygame, and pages.py draws the Move's screen from the app's state instead.

Controls (see MOVE-NOTES.md):
  Play / Record / Loop / Undo, Shift for their second jobs; Copy = LIFT, Delete = CUT, Capture = DROP,
  Sample = SPLICE, Mute = mute (Shift: solo); Menu = the project menu, Back = back; + / - = the Pi's knob 9;
  left buttons (top to bottom): tape, instruments, FX, the selected track's page (its input); knobs 1-8; jog wheel = the big knob (push to
  choose; Shift + turn = knob 10); step buttons 1-8 select tracks (Shift: arm), on the sequencer the 16 steps;
  pads play the instrument you're on. Shift + touch a knob = push it. Shift + Back: save and quit.
"""
import os
import queue
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
APP = os.path.join(REPO, "pi-app")
STUBS = os.path.join(REPO, "tools", "sim", "stubs")
sys.path[:0] = [STUBS, APP, HERE]
os.environ.setdefault("CONSOLE_PLATFORM", "move")
os.environ.setdefault("CONSOLE_DATA", "/data/UserData/console/data")

import pygame                     # noqa: E402  (the simulator's stand-in: the app draws nothing real)
pygame.init()
import audio                      # noqa: E402
import ui                         # noqa: E402
import console                    # noqa: E402
import menu as menu_mod           # noqa: E402
import kitmenu                    # noqa: E402
import pages                      # noqa: E402
from screen import Frame          # noqa: E402

FPS_SCREEN = 20

# ---------------------------------------------------------------- the Move's controls -> the app's actions

PRESS = {85: ("PLAY", "HOME"), 86: ("RECORD", "REC_MODE"), 58: ("LOOP", "CLEAR_REGION"),
         62: ("LEFT", "LOOP_IN"), 63: ("RIGHT", "LOOP_OUT"), 56: ("UNDO", "UNDO"),
         52: ("DROP", "DROP_INSERT"), 118: ("SPLICE", "SPLICE_ALL"), 88: ("MUTE", "SOLO"),
         50: ("FILE", "FILE"), 3: ("HOME", "HOME_PUSH_SHIFT"),
         42: ("DRUMS", "DRUMS_BACK"), 41: ("FX", "FX"), 40: ("INPUT", "ARM_ALL")}
HOLD = {60: "COPY", 119: "CUT"}            # hold and move to take several boxes (Shift + Copy: select)
SHIFT, BACK, TAPE, PLUS, MINUS, WHEEL, VOLUME = 49, 51, 43, 55, 54, 14, 79
KNOBS = range(71, 79)                      # knobs 1-8
STEPS = range(16, 32)                      # step buttons 1-16 (notes)
PADS = range(68, 100)                      # pads, bottom row first


class MoveBoard:
    def __init__(self, keys, T):
        self.keys, self.T = keys, T
        self.shift = False
        self.held = set()
        self.notes_down = {}               # pad -> the synth note it's playing

    def __call__(self, msg):
        kind, num, val = msg[0] & 0xF0, msg[1], msg[2]
        if kind == 0x80:
            kind, val = 0x90, 0
        if kind == 0xB0:
            self.cc(num, val)
        elif kind == 0x90:
            self.note(num, val)

    def cc(self, num, val):
        k = self.keys
        if num == SHIFT:
            self.shift = val > 0
            return
        if num in KNOBS or num in (WHEEL, VOLUME):
            step = val - 128 if val > 63 else val
            if not step:
                return
            if num == VOLUME:
                k.put(("VOLUME", step))
            elif num == WHEEL:
                k.put(("KNOB", 10, step, False) if self.shift else ("KNOB", 11, step, False))
            else:
                k.put(("KNOB", num - 70, step, self.shift))
            return
        if num in HOLD:
            name = HOLD[num]
            if val and self.shift and name == "COPY":
                k.put("SELECT")
            elif val and not self.shift:
                self.held.add(name)
                k.put(("HOLD", name))
            elif not val and name in self.held:
                self.held.discard(name)
                k.put(("RELEASE", name))
            return
        if not val:
            return
        if num in (PLUS, MINUS):
            k.put(("KNOB", 9, 1 if num == PLUS else -1, self.shift))
        elif num == BACK:
            k.put("QUIT" if self.shift else "BACK")
        elif num == TAPE:
            k.put("TAPE")
        elif num in PRESS:
            k.put(PRESS[num][1 if self.shift else 0])

    def note(self, num, val):
        T, e, k = self.T, self.T.engine, self.keys
        if num in STEPS:
            n = num - 15                                   # 1-16
            if not val:
                return
            if T.seq_page and not T.synth_shown():
                k.put(("STEP", n))
            elif n <= 8:
                k.put(("ARM%d" if self.shift else "TRACK%d") % n)
            return
        if 0 <= num < 8 and val and self.shift:         # Shift + touch a knob: push it
            k.put("MUTE%d" % (num + 1))
            return
        if num in PADS:
            self.pad(num - PADS[0], val)

    def pad(self, p, vel):
        """The pads play the instrument you're on: a drum machine one drum a pad (bottom row first), a synth
        its scale up the pads."""
        T, e = self.T, self.T.engine
        if e is None or e.slot is None or not e.drums:
            return
        mid = e.slots[e.slot]
        if e.is_synth(mid):
            if vel:
                seq = e.seqs.get(mid)
                try:
                    base = seq.note_row(seq.shown_notes()[0])
                    note = seq.row_note(base + p)
                except Exception:
                    note = 48 + p
                self.notes_down[p] = note
                (T.midi_note if T.drum_page else e.note_on)(note, vel)
            else:
                note = self.notes_down.pop(p, None)
                if note is not None:
                    (T.midi_note if T.drum_page else lambda n, v: e.note_off(n))(note, 0)
            return
        d = e.drums
        if p >= d.lanes:
            return
        if vel:
            e.hit(p, vel)
            voice = d.lane_voice[p] if p < len(d.lane_voice) else 0
            T.drum_voice = voice
            T._drum_hits[voice % len(T._drum_hits)] = time.monotonic()
        if T.seq_page and p < 8:
            self.keys.put(("LANE", p + 1, bool(vel), e.seq_clock, False))


# ---------------------------------------------------------------- lights

class Lights:
    """Sends a light's state only when it changes."""

    def __init__(self, core):
        self.core, self.sent = core, {}

    def cc(self, num, on):
        v = 127 if on else 0
        if self.sent.get(("cc", num)) != v:
            self.sent[("cc", num)] = v
            self.core.send_midi(bytes((0xBF, num, v)))

    def note(self, num, v):
        if self.sent.get(("n", num)) != v:
            self.sent[("n", num)] = v
            self.core.send_midi(bytes((0x9F, num, v)))

    def update(self, T, board):
        e = T.engine
        self.cc(85, T.playing)
        self.cc(86, T.recording)
        self.cc(58, bool(e and e.loop_on))
        self.cc(88, bool(e and not e.audible(T.armed - 1)))
        self.cc(49, board.shift)
        page = 43 if not (T.inst_page or T.drum_page or T.seq_page or T.fx_page) else \
            41 if T.fx_page else 42
        for b in (43, 42, 41, 40):
            self.cc(b, b == page)
        # step buttons: the tracks (the selected one bright), or the sequencer's steps
        for i in range(16):
            v = 0
            if T.seq_page and e and not T.synth_shown():
                lane = getattr(T.sp(), "lane", 0)
                try:
                    v = 127 if e.seq.step(lane, i).on else 0
                except Exception:
                    v = 0
            elif i < 8:
                v = 127 if i == T.armed - 1 else (40 if e and i in e.arm_extra else 0)
            self.note(16 + i, v)
        # pads: the drums the instrument has
        lanes = 0
        if e and e.slot is not None and e.drums:
            lanes = 32 if e.is_synth(e.slots[e.slot]) else e.drums.lanes
        for p in range(32):
            self.note(68 + p, 20 if p < lanes else 0)


# ---------------------------------------------------------------- the app

def main():
    e = audio.Engine()
    e.start()
    deadline = time.time() + 15
    while getattr(e, "core", None) is None and time.time() < deadline:
        time.sleep(0.05)
    if getattr(e, "core", None) is None:
        sys.exit("The sound core didn't start: is console mode running? (%s)" % e.status)
    core = e.core
    screen = ui.Screen.load(os.path.join(APP, "layouts", "main.ui"))
    T = console.Transport(screen, e)
    m = menu_mod.Menu(os.path.join(APP, "layouts", "menu.ui"), T)
    m.kits = kitmenu.KitMenu(os.path.join(APP, "layouts", "menu.ui"), T)
    m.kits.main = m
    m.open = False                                   # start on the tape, not the project menu
    keys = queue.Queue()
    board = MoveBoard(keys, T)
    T.shift_held = lambda: board.shift
    frame = Frame()
    lights = Lights(core)
    print("Console on the Move: running. Ctrl+C quits (the song is saved).")
    last = time.monotonic()
    next_screen = 0.0
    next_lights = 0.0
    try:
        while True:
            while True:
                try:
                    board(e.move_midi.get_nowait())
                except queue.Empty:
                    break
            quit_now = False
            while not keys.empty():
                name = keys.get()
                if name == "QUIT":
                    quit_now = True
                    break
                handle(name, T, m, e)
            if quit_now:
                frame.clear()
                frame.centre(64, 28, "SAVING...")
                core.display(frame.bytes())
                break
            now = time.monotonic()
            T.tick(now - last)
            last = now
            if now >= next_screen:
                next_screen = now + 1 / FPS_SCREEN
                pages.draw(frame, T, m)
                core.display(frame.bytes())
            if now >= next_lights:
                next_lights = now + 0.1
                lights.update(T, board)
            time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        import signal
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        T.playing = False
        e.save(wait=True)
        frame.clear()
        core.display(frame.bytes())
        time.sleep(0.1)
        e.stop()
        time.sleep(0.2)
        print("Saved. Bye.")


def handle(name, T, m, e):
    """One action, the way the Pi app's main loop does it (menus first), plus the Move's own."""
    if isinstance(name, tuple) and name[0] == "VOLUME":
        T.phones_volume(name[1] * 0.02)
        return
    if isinstance(name, tuple) and name[0] == "STEP":
        lane = getattr(T.sp(), "lane", 0)
        e.seq.toggle(lane, name[1] - 1)
        e.seq_changed()
        return
    if name == "INPUT" and not (m.open or m.kits.open):
        # left button 4: the selected track's own page (knob 1 mono / stereo, knob 2 its input); again to leave
        for _ in range(4):
            if T.seq_page or T.drum_page or T.inst_page:
                T.key("DRUMS_BACK")
        T.fx_page = None
        T.key("FOCUS")
        return
    if name == "TAPE":                               # the top left button: straight back to the tape
        m.open = False
        m.kits.open = False
        for _ in range(4):
            if T.seq_page or T.drum_page or T.inst_page:
                T.key("DRUMS_BACK")
        T.fx_page = None
        if T.focus.track is not None:
            T.key("FOCUS")
        return
    if name == "BACK":
        if m.open:
            m.key("FILE")
        elif m.kits.open:
            m.kits.key("FILE")
        elif T.inst_page and T.instp.mode:
            T.instp.cancel()
        elif T.seq_page or T.drum_page or T.inst_page:
            T.key("DRUMS_BACK")
        elif T.fx_page:
            T.fx_page = None
        elif T.focus.track is not None:
            T.key("FOCUS")
        return
    if (m.open or m.kits.open) and isinstance(name, tuple) and name[0] in ("HOLD", "RELEASE"):
        if name[0] == "HOLD":
            (m if m.open else m.kits).key(name[1])
    elif m.open:
        m.key("PLAY" if name == "HOME" else name)    # pushing the wheel chooses, as PLAY does
    elif m.kits.open:
        m.kits.key("PLAY" if name == "HOME" else name)
    elif name == "FILE" and T.inst_page and T.instp.mode:
        T.instp.cancel()
    elif name == "FILE" and T.drum_page:
        m.kits.show()
    elif name == "FILE":
        m.show()
    else:
        T.key(name)


if __name__ == "__main__":
    main()
