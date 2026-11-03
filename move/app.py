"""Console on the Ableton Move: the Pi app's own logic (console.Transport, the menus, the engine) with the
Move's controls and screen. Run in console mode:

    python3 /data/UserData/console/move/app.py

The engine makes its sound with the C sound core (core/bridge.py). The Pi app's drawing is never used: it runs
with the simulator's stand-in pygame, and pages.py draws the Move's screen from the app's state instead.

Controls (see MOVE-NOTES.md):
  Play / Record / Loop / Undo, Shift for their second jobs; Copy = LIFT, Delete = CUT, Capture = DROP,
  Sample = SPLICE, Mute = mute (Shift: solo); Menu = the project menu (Shift: export), Back = back; + / - = the Pi's knob 9;
  left buttons (top to bottom): instruments, song mode, FX, the recorder (again: the selected track zoomed); knobs 1-8; jog wheel = the
  big knob (push to choose; Shift + turn = knob 10); step buttons 1-8 select tracks (Shift: arm), on the drum sequencer the 16 steps
  (see moveseq.py), on song mode its rows; pads: drums on the left 4 x 4, the picked drum chromatically on the right (Shift + pad: pattern). Shift + touch a knob = push it. Shift + Back: save, quit and go back to the normal Move
  (Ctrl+C over SSH only quits the app).
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
import moveseq                    # noqa: E402
import movesong                   # noqa: E402
import knobgate                   # noqa: E402
import moveupdater                # noqa: E402
import updater                    # noqa: E402
updater.Updater = moveupdater.Updater   # SETTINGS > SOFTWARE UPDATE: from GitHub with move-update.py
from screen import Frame, W       # noqa: E402

FPS_SCREEN = 20

# ---------------------------------------------------------------- the Move's controls -> the app's actions

PRESS = {85: ("PLAY", "HOME"), 86: ("RECORD", "REC_MODE"), 58: ("LOOP", "CLEAR_REGION"),
         62: ("LEFT", "LOOP_IN"), 63: ("RIGHT", "LOOP_OUT"), 56: ("UNDO", "UNDO"),
         52: ("DROP", "DROP_INSERT"), 118: ("SPLICE", "SPLICE_ALL"), 88: ("MUTE", "SOLO"),
         50: ("FILE", "EXPORT"), 3: ("HOME", "HOME_PUSH_SHIFT"),
         43: ("DRUMS", "DRUMS_BACK"), 42: ("SONG", "SONG_TOGGLE"), 41: ("FX", "FX"), 40: ("TAPE", "ARM_ALL")}
HOLD = {60: "COPY", 119: "CUT"}            # hold and move to take several boxes (Shift + Copy: select)
SHIFT, BACK, PLUS, MINUS, WHEEL, VOLUME = 49, 51, 55, 54, 14, 79
# left buttons, top to bottom: 1 instruments (again: the drum's sound, its sequencer), 2 song, 3 FX,
# 4 the recorder (the tape; again: the selected track zoomed)
KNOBS = range(71, 79)                      # knobs 1-8
STEPS = range(16, 32)                      # step buttons 1-16 (notes)
PADS = range(68, 100)                      # pads, bottom row first
WHITE, RED = 120, 127                      # the Move's light colours (velocity of the light message)


def _shuffled(colours, seed):
    import random
    out = list(colours)
    random.Random(seed).shuffle(out)                 # the same "random" order every time, so a pad keeps its colour
    return out


# the drum pads: bright colours, in a random order; the chromatic pads: pastels, in another random order
DRUM_COLOURS = [16] * 16        # the left 4x4: one bright colour
NOTE_COLOURS = [47] * 16        # the right 4x4: one pastel


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
                k.put(("SENS", step) if self.shift else ("VOLUME", step))
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
        elif num in PRESS:
            k.put(PRESS[num][1 if self.shift else 0])

    def note(self, num, val):
        T, e, k = self.T, self.T.engine, self.keys
        if num in STEPS:
            n = num - 15                                   # 1-16
            if getattr(T, "song_page", False) and not T.seq_page:
                if val:
                    k.put(("ROW", n, "CUT" in self.held))  # song mode's rows (Delete + a row: take it out)
                return
            if T.seq_page and not T.synth_shown():
                k.put(("STEP", n, bool(val), self.shift))  # tap: on / off; Shift + taps: select to set
                return
            if not val:
                return
            if n <= 8:
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
        if self.shift and p < 16:                          # Shift + pad: the instrument's pattern 1-16
            if vel:
                self.keys.put(("PATTERN", p))
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
                note = max(0, min(127, note + 12 * getattr(T, "octave", 0)))
                self.notes_down[p] = note
                (T.midi_note if T.drum_page else e.note_on)(note, vel)
            else:
                note = self.notes_down.pop(p, None)
                if note is not None:
                    (T.midi_note if T.drum_page else lambda n, v: e.note_off(n))(note, 0)
            return
        d = e.drums
        ms = T.mseq
        if ms.active() and ms.held is not None:            # steps selected: the pads are their settings
            if vel:
                self.keys.put(("STEP_PAD", p))
            return
        r, c = divmod(p, 8)
        if c < 4:                                          # left 4 x 4: the drums, bottom left first
            lane = r * 4 + c
            if lane >= d.lanes:
                return
            if vel:
                e.hit(lane, vel)
                voice = d.lane_voice[lane] if lane < len(d.lane_voice) else 0
                T.drum_voice = voice
                T._drum_hits[voice % len(T._drum_hits)] = time.monotonic()
                self.keys.put(("PICK_LANE", lane))
            return
        if vel:                                            # right 4 x 4: the picked drum, a semitone a pad
            lane = min(T.seqp.lane, d.lanes - 1)
            semis = r * 4 + (c - 4) + 12 * getattr(T, "octave", 0)
            e._auditions.append((0, lane, vel, ms.pitch_locks(lane, {}, semis)))


def pattern_seq(T):
    """The shown instrument's sequencer (its patterns), or None."""
    e = T.engine
    if not e or e.slot is None or not e.slots[e.slot]:
        return None
    return e.seqs.get(e.slots[e.slot])


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

    def icons(self, which):
        """The icons under the step buttons (controller numbers 16-31): which = a set of 0-15, lit white."""
        for k in range(16):
            v = 120 if k in which else 0
            if self.sent.get(("icon", k)) != v:
                self.sent[("icon", k)] = v
                self.core.send_midi(bytes((0xBF, 16 + k, v)))

    def update(self, T, board):
        e = T.engine
        self.cc(85, T.playing)
        self.cc(86, T.recording)
        self.cc(58, bool(e and e.loop_on))
        self.cc(88, bool(e and not e.audible(T.armed - 1)))
        self.cc(49, board.shift)
        page = 41 if T.fx_page else 43 if (T.inst_page or T.drum_page or T.seq_page) else \
            42 if getattr(T, "song_page", False) else 40
        for b in (43, 42, 41, 40):
            self.cc(b, b == page)
        # step buttons: the tracks (the selected one bright), or the sequencer's steps
        seq_lights = T.mseq.step_lights() if T.mseq.active() else None
        song = getattr(T, "song_page", False) and not T.seq_page and T.song.step_lights()
        for i in range(16):
            v = 0
            if song:
                v = song[i]
            elif T.mseq.active():
                v = seq_lights[i]
            elif i < 8:
                sel, armed = i == T.armed - 1, bool(e and i in e.arm_extra)
                v = (RED if not sel or int(time.monotonic() * 2) % 2 else WHITE) if armed else WHITE if sel else 0
            self.note(16 + i, v)
        # pads
        out = [0] * 32
        q = pattern_seq(T)
        if board.shift and q is not None:                  # Shift: the patterns (the current one bright)
            for p in range(16):
                pat = q.patterns[p]
                out[p] = 127 if p == q.current else 20 if not pat.empty() else 0
        elif T.mseq.active() and T.mseq.held is not None:
            out = T.mseq.pad_lights()
        elif e and e.slot is not None and e.drums:
            if e.is_synth(e.slots[e.slot]):
                out = [20] * 32
            else:
                lanes, picked = e.drums.lanes, T.seqp.lane
                for p in range(32):
                    r, c = divmod(p, 8)
                    if c < 4:                                  # the drums: each its own colour, the picked one white
                        lane = r * 4 + c
                        out[p] = WHITE if lane == picked else DRUM_COLOURS[lane] if lane < lanes else 0
                    else:                                      # the chromatic pads: another set (pastels), roots white
                        k = r * 4 + c - 4
                        out[p] = WHITE if k % 12 == 0 else NOTE_COLOURS[k]
        for p in range(32):
            self.note(68 + p, out[p])


# ---------------------------------------------------------------- the app

PIDFILE = "/data/UserData/console/app.pid"
ICONFILE = os.environ.get("CONSOLE_ICONFILE", "/data/UserData/console/icontest")      # touch it: the step icons light one at a time (see icon_test below)


def already_running():
    """The pid of another copy of the app that's still running (the one the Move started), or None."""
    try:
        pid = int(open(PIDFILE).read().strip())
        if pid != os.getpid() and os.path.exists("/proc/%d" % pid) and \
                "app.py" in open("/proc/%d/cmdline" % pid).read():
            return pid
    except (OSError, ValueError):
        pass
    return None


def main():
    other = already_running()
    if other:
        sys.exit("Console is already running on the Move (it starts by itself in console mode). "
                 "Shift + Back on the Move quits it.")
    try:
        with open(PIDFILE, "w") as fh:
            fh.write(str(os.getpid()))
    except OSError:
        pass
    import signal

    def stop_signal(*_):
        raise KeyboardInterrupt                      # asked to stop (the launcher): save and quit as Ctrl+C does
    signal.signal(signal.SIGTERM, stop_signal)
    e = audio.Engine()
    e.start()
    deadline = time.time() + 15
    while getattr(e, "core", None) is None and time.time() < deadline:
        time.sleep(0.05)
    if getattr(e, "core", None) is None:
        sys.exit("The sound core didn't start: is console mode running? (%s)" % e.status)
    core = e.core
    knobgate.load(os.path.join(os.path.dirname(os.environ["CONSOLE_DATA"]), "knob-sensitivity"))
    e.select_arms = False                            # selecting a track doesn't arm it: Shift + step button does
    screen = ui.Screen.load(os.path.join(APP, "layouts", "main.ui"))
    T = console.Transport(screen, e)
    m = menu_mod.Menu(os.path.join(APP, "layouts", "menu.ui"), T)
    m.kits = kitmenu.KitMenu(os.path.join(APP, "layouts", "menu.ui"), T)
    m.kits.main = m
    kit_turn = m.kits.turn

    def kit_list_turn(delta, k=m.kits):                # the drums menu's list stops at its ends (it wrapped round)
        if k.mode == "list":
            k.choice = max(0, min(kitmenu.ALL - 1, k.choice + delta))
            k.msg = ""
        else:
            kit_turn(delta)
    m.kits.turn = kit_list_turn
    m.open = False                                   # start on the tape, not the project menu
    keys = queue.Queue()
    board = MoveBoard(keys, T)
    T.shift_held = lambda: board.shift
    T.mseq = moveseq.MoveSeq(T)
    T.song_page = False
    T.octave = 0                                     # Up / Down on a sound page: the pads' octave
    T.song = movesong.Song(T)
    T.key("DRUMS")                                   # start on left button 1: the instruments
    frame = Frame()
    lights = Lights(core)
    print("Console on the Move: running. Ctrl+C quits (the song is saved).")
    last = time.monotonic()
    next_screen = 0.0
    next_lights = 0.0
    next_icon_check, icon_test = 0.0, None
    hand_back = False
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
            if m.restart and not quit_now:          # a software update was installed: start the new version
                frame.clear()
                frame.centre(64, 28, "RESTARTING...")
                core.display(frame.bytes())
                break
            if quit_now:
                hand_back = True
                frame.clear()
                frame.centre(64, 28, "SAVING...")
                core.display(frame.bytes())
                break
            now = time.monotonic()
            T.song.tick()
            T.tick(now - last)
            last = now
            e.inst_view = e.inst_view or T.song_page         # the instruments play on the song page too
            if now >= next_icon_check:
                next_icon_check = now + 0.5
                try:
                    mode = open(ICONFILE).read().strip().lower() if os.path.exists(ICONFILE) else None
                except OSError:
                    mode = None
                if mode is None and icon_test is not None:
                    lights.icons(set())                      # finished: the icons go dark
                icon_test = mode
            if icon_test is not None:
                # the icon test: each icon in turn for 2 seconds (or all of them: put "all" in the file)
                k = int(now / 2) % 16
                lit = set(range(16)) if icon_test == "all" else {k}
                lights.icons(lit)
                if now >= next_screen:
                    next_screen = now + 1 / FPS_SCREEN
                    frame.clear()
                    frame.rect(0, 0, W, 9, 1)
                    frame.text(1, 1, "ICON TEST", 0)
                    frame.centre(64, 20, "ALL ON" if icon_test == "all" else "ICON %d OF 16" % (k + 1))
                    frame.small(1, 40, "UNDER STEP BUTTON %s" % ("1-16" if icon_test == "all" else k + 1))
                    frame.small(1, 52, "DELETE THE FILE TO END")
                    core.display(frame.bytes())
                time.sleep(0.005)
                continue
            if now >= next_screen:
                next_screen = now + 1 / FPS_SCREEN
                menu_tick(m)
                pages.draw(frame, T, m)
                core.display(frame.bytes())
            if now >= next_lights:
                next_lights = now + 0.03
                lights.update(T, board)
            time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        T.playing = False
        e.save(wait=True)
        frame.clear()
        core.display(frame.bytes())
        time.sleep(0.1)
        e.stop()
        time.sleep(0.2)
        print("Saved. Bye.")
        if hand_back:                                # Shift + Back: back to the normal Move (see RNBOLauncher)
            try:
                open("/data/UserData/console/STOP", "w").close()
                print("Handing the Move back.")
            except OSError as ex:
                print("Couldn't hand the Move back (%s)" % ex)
        elif m.restart:
            print("Restarting with the new version...")
            sys.exit(moveupdater.RESTART_CODE)


def choice_knob(T, m, e, name):
    """True for a knob that picks from a list or a mode (they count their own clicks, see knobgate), and in the
    menus; the rest are numbers and get the global knob speed."""
    n = name[1]
    if m.open or m.kits.open:
        return True
    if getattr(T, "song_page", False) and not (T.seq_page or T.drum_page or T.inst_page or T.fx_page):
        return True
    if T.focus.track is not None and n <= 3 and not (T.seq_page or T.drum_page or T.inst_page or T.fx_page):
        return True
    if not (e and e.drums):
        return False
    ms = T.mseq
    if T.seq_page and ms.active():
        if ms.selected:
            if n == 1 and ms.sel is not None:
                key = ms.pad_items()[ms.sel][0]
                return (key not in ("vel", "chance")) if isinstance(key, str) else knobgate.is_choice(e.drums, key)
            return False
        return n == 2                                          # the lane's RATE
    if T.drum_page and not (T.fx_page or T.inst_page):
        pages = T.drum_pages()
        params = pages[min(T.drum_tab, len(pages) - 1)][1]
        return n <= len(params) and knobgate.is_choice(e.drums, params[n - 1])
    return False


def menu_tick(m):
    """The Pi redraws the settings each frame (menu.draw), which keeps SOFTWARE UPDATE's row current and
    restarts after an install; the Move never calls draw, so this does that part."""
    if not m.open or getattr(m, "mode", None) not in ("settings", "wifi"):
        return
    m.refresh()
    u = getattr(m, "updater", None)
    if m.mode == "settings" and u and u.state == "done" and not u.needs_setup:
        if getattr(m, "_done_at", None) is None:
            m._done_at = time.monotonic()
        elif time.monotonic() - m._done_at > 2.0:
            m.restart = True


def handle(name, T, m, e):
    """One action, the way the Pi app's main loop does it (menus first), plus the Move's own."""
    if isinstance(name, tuple) and name[0] == "VOLUME":
        T.phones_volume(name[1] * 0.02)
        return
    if isinstance(name, tuple) and name[0] == "SENS":        # Shift + the volume knob: how many clicks a step takes
        v = knobgate.set_speed(knobgate.SPEED + (1 if name[1] > 0 else -1) * (1 if abs(name[1]) < 3 else 2))
        T.say("KNOB SPEED: %d CLICK%s A STEP" % (v, "" if v == 1 else "S"), 3)
        return
    ms = T.mseq
    if isinstance(name, tuple) and name[0] == "KNOB" and 1 <= name[1] <= 8 and not choice_knob(T, m, e, name):
        way = knobgate.numeric(("num", name[1], name[3]), name[2])    # every number knob: SPEED clicks a step
        if not way:
            return
        name = ("KNOB", name[1], way, name[3])
    on_sound = T.drum_page and not (T.seq_page or T.fx_page or T.inst_page or T.song_page or m.open or m.kits.open)
    if on_sound and e and e.drums:
        # a sound page: Up / Down (+ / -) are the pads' octave (as on the Move); Left / Right the settings pages
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] == 9 and not name[3]:
            T.octave = max(-4, min(4, T.octave + (1 if name[2] > 0 else -1)))
            T.say("OCTAVE %s" % ("%+d" % T.octave if T.octave else "0"), 2)
            return
        if name in ("LEFT", "RIGHT"):
            name = ("KNOB", 9, 1 if name == "RIGHT" else -1, False)
    if name == "RECORD" and e and not T.recording and not e.record_tracks():
        T.say("ARM A TRACK FIRST: SHIFT + STEP BUTTON", 3)
        return
    if isinstance(name, tuple) and name[0] == "KNOB" and not (m.open or m.kits.open):
        n = name[1]
        zoomed = T.focus.track is not None and not (T.seq_page or T.drum_page or T.inst_page or T.fx_page
                                                    or T.song_page)
        if (zoomed and n <= 3) or n == 10:
            # a mode or a list (mono / stereo, the input, the grid, the pattern): several clicks per choice
            way = knobgate.gate(("knob", n, zoomed), name[2], False, 5 if zoomed else 3)
            if not way:
                return
            name = ("KNOB", n, way, name[3])
    if (isinstance(name, tuple) and name[0] == "KNOB" and name[1] <= 8 and T.drum_page and not (
            T.seq_page or T.fx_page or T.inst_page or m.open or m.kits.open) and e and e.drums):
        # a setting that picks a mode (DIST, CHOKE...): several clicks per choice
        pages = T.drum_pages()
        params = pages[min(T.drum_tab, len(pages) - 1)][1]
        if name[1] <= len(params) and knobgate.is_choice(e.drums, params[name[1] - 1]):
            way = knobgate.gate(("drum", params[name[1] - 1]), name[2], name[3])
            if not way:
                return
            name = ("KNOB", name[1], way, True)          # one choice (as with Shift: no speeding up)
    if isinstance(name, tuple) and name[0] == "STEP":
        if ms.active():
            ms.step(name[1], name[2], name[3])
        return
    if isinstance(name, tuple) and name[0] == "STEP_PAD":
        if ms.active():
            ms.step_pad(name[1])
        return
    if isinstance(name, tuple) and name[0] == "PICK_LANE":
        if ms.held is None and e and e.drums and name[1] < e.drums.lanes:
            T.seqp.lane = name[1]
            T.drum_voice = T.seqp.voice()
        return
    if isinstance(name, tuple) and name[0] == "PATTERN":
        q = pattern_seq(T)
        if q is not None:
            q.choose_pattern(name[1], e.playing)
            e.seq_changed()
            T.say("PATTERN %d%s" % (name[1] + 1, "  (NEXT)" if e.playing and q.queued is not None else ""), 2)
        return
    if isinstance(name, tuple) and name[0] == "ROW":
        T.song.row_button(name[1], name[2])
        return
    menus = m.open or m.kits.open
    if T.song_page and not menus and not (T.seq_page or T.drum_page or T.inst_page or T.fx_page):
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] <= 8:
            T.song.knob(name[1], name[2])
            return
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] == 9:
            T.song.set_on(name[2] > 0)                     # +: song mode on, -: off
            return
    if name == "SONG_TOGGLE":                          # Shift + left button 2: song mode on / off, from any page
        T.song.toggle()
        return
    if name == "SONG" and not menus:                 # left button 2: song mode
        for _ in range(4):
            if T.seq_page or T.drum_page or T.inst_page:
                T.key("DRUMS_BACK")
        T.fx_page = None
        if T.focus.track is not None:
            T.key("FOCUS")
        T.song_page = True
        return
    if name in ("DRUMS", "FX", "DRUMS_BACK"):
        T.song_page = False
    if ms.active() and not (m.open or m.kits.open) and T.fx_page is None:
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] <= 8:
            ms.knob(name[1], name[2], name[3])
            return
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] == 9:
            ms.plus_minus(1 if name[2] > 0 else -1)
            return
        if name in ("LEFT", "RIGHT"):
            ms.arrows(-1 if name == "LEFT" else 1)
            return
    if name == "TAPE":                               # left button 4: the recorder; again: the track zoomed
        m.open = False
        m.kits.open = False
        on_tape = not (T.song_page or T.seq_page or T.drum_page or T.inst_page or T.fx_page)
        T.song_page = False
        for _ in range(4):
            if T.seq_page or T.drum_page or T.inst_page:
                T.key("DRUMS_BACK")
        T.fx_page = None
        if on_tape:
            T.key("FOCUS")                           # zoom in, or (zoomed) back out
        elif T.focus.track is not None:
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
        elif T.song_page:
            T.song_page = False
        elif T.focus.track is not None:
            T.key("FOCUS")
        return
    if (m.open or m.kits.open) and isinstance(name, tuple) and name[0] in ("HOLD", "RELEASE"):
        if name[0] == "HOLD":
            (m if m.open else m.kits).key(name[1])
    elif m.open:
        m.key("PLAY" if name == "HOME" else name)    # pushing the wheel chooses, as PLAY does
    elif m.kits.open:
        if m.kits.mode == "list" and name in ("LEFT", "RIGHT", "BAR_LEFT", "BAR_RIGHT"):
            return                                   # (the Pi's two columns: here it's one list)
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
