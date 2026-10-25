"""The drum synth: the six drum voices of the Erica Synths LXR-02 (its open-source firmware, GPL-3.0),
running on the Pi as one of the console's inputs.

The sound engine is the LXR's own code, in drums/lxr/, compiled with the console's glue
(drums/console_drums.c) into drums/libdrums.so. setup.sh builds it; if it's missing or older than the
code, this builds it with gcc, and if that isn't possible the drum synth is simply off (AVAILABLE False).

Lanes (voices): 0-2 DRUM 1-3, 3 SNARE, 4 CYMBAL, 5 HI-HAT. Hitting lane 6 plays the hi-hat open.
"""
import ctypes
import glob
import math
import os
import shutil
import subprocess
import threading

import numpy as np

import drumparams as dp

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "drums")
LIB = os.path.join(DIR, "libdrums.so")
LIVE_LIB = os.path.join(DIR, "libdrums_live.so")    # a second copy: its own engine, for playing by hand
VOICES = 6
NAMES = ["DRUM 1", "DRUM 2", "DRUM 3", "SNARE", "CYMBAL", "HI-HAT"]
SHORT = ["DR1", "DR2", "DR3", "SN", "CY", "HH"]
OPEN_HAT = 6
VEL_TO_VOLUME = range(137, 143)     # each voice's VEL>VOL setting
PROBLEM = ""              # why the drum synth is off, if it is


def _newest_source():
    files = glob.glob(os.path.join(DIR, "**", "*.[ch]"), recursive=True) + [os.path.join(DIR, "build.sh")]
    return max((os.path.getmtime(f) for f in files), default=0)


def _build():
    try:
        r = subprocess.run(["bash", os.path.join(DIR, "build.sh")], capture_output=True, text=True, timeout=600)
        return r.returncode == 0, r.stderr.strip()
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)


def _load(path=LIB):
    global PROBLEM
    if path == LIB and (not os.path.exists(LIB) or _newest_source() > os.path.getmtime(LIB)):
        ok, err = _build()
        if not ok and not os.path.exists(LIB):
            PROBLEM = "DRUM SYNTH NEEDS BUILDING: RUN pi-app/setup.sh"
            print("Drums: couldn't build drums/libdrums.so (%s). Run pi-app/setup.sh." % err[-500:])
            return None
    if path != LIB:
        # the same library under another name loads as a separate engine with its own settings and voices
        try:
            if not os.path.exists(path) or os.path.getmtime(path) < os.path.getmtime(LIB):
                shutil.copyfile(LIB, path + ".tmp")
                os.replace(path + ".tmp", path)
        except OSError as e:
            print("Drums: couldn't copy the library for a second engine: %s" % e)
            return None
    try:
        lib = ctypes.CDLL(path)
    except OSError as e:
        PROBLEM = "DRUM SYNTH NEEDS BUILDING: RUN pi-app/setup.sh"
        print("Drums: couldn't load %s: %s" % (LIB, e))
        return None
    i, v = ctypes.c_int, None
    for name, args, res in [("drums_init", [], i), ("drums_param_count", [], i),
                            ("drums_set_param", [i, i], v), ("drums_get_param", [i], i),
                            ("drums_load_init_kit", [], v), ("drums_set_bpm", [i], v),
                            ("drums_trigger", [i, i], v), ("drums_pan", [i], i),
                            ("drums_render", [ctypes.POINTER(ctypes.c_float), i], v)]:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, res
    return lib


_lib = _load()
AVAILABLE = _lib is not None
# The sequencer plays _lib; your fingers play _live. Two engines, so the sequencer's hits can be recorded
# exactly on the beat and yours exactly where you pressed (they reach the tape with different delays).
_live = (_load(LIVE_LIB) if AVAILABLE else None) or _lib


class Drums:
    """One drum synth (the library holds a single engine, so make one of these)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending = []         # things to do at the start of the next render, in order
        self._locked = [set() for _ in range(VOICES)]     # parameters the sequencer engine has locked now
        if AVAILABLE:
            _lib.drums_init()
            if _live is not _lib:
                _live.drums_init()
            self.engine_params = _lib.drums_param_count()
        else:
            self.engine_params = 0
        # after the engine's settings come Console's own: each voice's reverb and delay sends
        self.param_count = self.engine_params + (dp.EXTRA_PARAMS if AVAILABLE else 0)
        # what each setting is now, kept here so the screen can read it any time (the engine catches up
        # at the start of its next block); and the LXR's Init Kit, to go back to
        self.values = ([_lib.drums_get_param(i) for i in range(self.engine_params)] + [0] * dp.EXTRA_PARAMS
                       if AVAILABLE else [])
        # Console's starting kit: like the LXR's Init Kit, but with velocity turning the volume up and down
        # on every drum (the LXR's has it off, so velocity would do nothing until you switched it on)
        for p in VEL_TO_VOLUME:
            if p < self.engine_params:
                self.values[p] = 1
        self.init_values = list(self.values)
        with self._lock:
            self._pending.extend(("param", p, 1) for p in VEL_TO_VOLUME if p < self.engine_params)

    # These can be called from any thread: they take effect at the start of the next block of sound.
    def hit(self, lane, velocity=100):
        with self._lock:
            self._pending.append(("hit", lane, velocity))

    def set_param(self, index, value):
        if not 0 <= index < self.param_count:
            return
        value = max(0, min(127, int(value)))
        with self._lock:
            self.values[index] = value
            if index < self.engine_params:
                self._pending.append(("param", index, value))

    def get_param(self, index):
        return self.values[index] if 0 <= index < self.param_count else 0

    def kit(self):
        """The current sound settings, to save in the project."""
        return list(self.values)

    def load_kit(self, values):
        """Settings saved by kit(); missing ones (from an older save) come from the Init Kit."""
        values = [int(v) for v in values[:self.param_count]]
        if len(values) == dp.NOISE_DECAY and len(values) > 56:
            values.append(values[56])                  # saved before the snare noise had its own decay
        values += self.init_values[len(values):]
        with self._lock:
            self.values = values
            self._pending.extend(("param", i, v) for i, v in enumerate(values) if i < self.engine_params)

    def init_kit(self):
        self.load_kit(self.init_values)

    # ------------------------------------------------------------ editing with the knobs

    def target_range(self, param):
        """For a velocity or LFO destination: (first, last) entry of TARGETS it may point at."""
        if dp.KINDS[param] == ("vel_target",):
            voice = param - 149                        # VEL TO params are 149-154, one per voice
        else:
            voice = self.get_param(param - 6) - 1      # the LFO's own voice setting sits 6 below its target
        return dp.VOICE_TARGETS[max(0, min(5, voice))]

    @staticmethod
    def lockable(param):
        """Settings a step can lock: not the velocity and LFO destinations (they pick what's modulated)."""
        return dp.KINDS.get(param, ("num",))[0] in ("num", "pm", "menu", "onoff")

    @staticmethod
    def stepped(param, v, clicks):
        """A lockable setting's value v turned by some clicks."""
        kind = dp.KINDS.get(param, ("num",))
        if kind[0] == "menu":
            return max(0, min(len(dp.MENUS[kind[1]]) - 1, v + (1 if clicks > 0 else -1)))
        if kind[0] == "onoff":
            return 1 if clicks > 0 else 0
        return max(0, min(127, v + clicks))

    def step(self, param, clicks):
        """Turn a setting by some knob clicks. Returns the new value."""
        kind, v = dp.KINDS.get(param, ("num",)), self.get_param(param)
        if kind[0] == "menu":
            v = max(0, min(len(dp.MENUS[kind[1]]) - 1, v + (1 if clicks > 0 else -1)))
        elif kind[0] == "onoff":
            v = 1 if clicks > 0 else 0
        elif kind[0] == "voice":
            old = self.get_param(param + 6)            # keep the LFO's target on the same kind of setting
            first, _ = dp.VOICE_TARGETS[max(0, min(5, v - 1))]
            v = max(1, min(6, v + (1 if clicks > 0 else -1)))
            if old:
                nf, nl = dp.VOICE_TARGETS[v - 1]
                self.set_param(param + 6, min(nl, nf + max(0, old - first)))
        elif kind[0] in ("vel_target", "lfo_target"):
            first, last = self.target_range(param)
            order = [0] + list(range(first, last + 1))     # nothing, then the voice's own settings
            i = order.index(v) if v in order else 0
            v = order[max(0, min(len(order) - 1, i + (1 if clicks > 0 else -1)))]
        else:
            v = max(0, min(127, v + clicks))
        self.set_param(param, v)
        return v

    def value_text(self, param, v=None):
        kind = dp.KINDS.get(param, ("num",))
        v = self.get_param(param) if v is None else v
        if kind[0] == "menu":
            names = dp.MENUS[kind[1]]
            return names[v] if v < len(names) else str(v)
        if kind[0] == "pm":
            return "%+d" % (v - kind[1]) if v != kind[1] else "0"
        if kind[0] == "onoff":
            return "ON" if v else "OFF"
        if kind[0] == "send":
            return "%d%%" % round(v / 127 * 100)
        if kind[0] == "voice":
            return NAMES[max(0, min(5, v - 1))]
        if kind[0] in ("vel_target", "lfo_target"):
            target = dp.TARGETS[v] if v < len(dp.TARGETS) else 0
            if not target:
                return "OFF"
            voice = next((i for i, (a, b) in enumerate(dp.VOICE_TARGETS) if a <= v <= b), None)
            label = dp.LABELS.get(target, "FX %d" % (target - 237))
            return label if voice is None else "%s %s" % (SHORT[voice], label)
        return str(v)

    def fraction(self, param, v=None):
        """How far round the setting is, 0..1, for the screen's bars."""
        kind = dp.KINDS.get(param, ("num",))
        v = self.get_param(param) if v is None else v
        if kind[0] == "menu":
            return v / max(1, len(dp.MENUS[kind[1]]) - 1)
        if kind[0] == "voice":
            return (v - 1) / 5
        if kind[0] in ("vel_target", "lfo_target"):
            return 1.0 if v else 0.0
        return v / 127

    def sends(self):
        """Each voice's reverb and delay sends, 0..1: two arrays of 6."""
        if not AVAILABLE:
            return np.zeros(VOICES, np.float32), np.zeros(VOICES, np.float32)
        rev = np.array([self.values[p] for p in dp.REVERB_SEND], np.float32) / 127
        dly = np.array([self.values[p] for p in dp.DELAY_SEND], np.float32) / 127
        return rev, dly

    def set_bpm(self, bpm):
        with self._lock:
            self._pending.append(("bpm", int(round(bpm))))

    @property
    def two_engines(self):
        return _live is not _lib

    def render(self, frames, events=(), with_live=True):
        """The next frames of sound (audio thread): (sequencer, by hand), each (frames, 6) float32, one mono
        channel per voice. events: the sequencer's hits in this block, [(offset, lane, velocity, locks)].
        With only one engine (the copy failed), everything is in the first and the second is silent."""
        todo = []
        if with_live:                        # False: only the sequencer's engine runs
            with self._lock:
                todo, self._pending = self._pending, []
        seq = np.zeros((frames, VOICES), np.float32)
        live = np.zeros((frames, VOICES), np.float32)
        if not AVAILABLE:
            return seq, live
        engines = (_lib, _live) if self.two_engines else (_lib,)
        for t in todo:
            if t[0] == "hit":
                _live.drums_trigger(t[1], t[2])
            elif t[0] == "param":
                for lib in engines:
                    lib.drums_set_param(t[1], t[2])
            elif t[0] == "bpm":
                for lib in engines:
                    lib.drums_set_bpm(t[1])
        pos = 0
        ptr = lambda a: a.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        for offset, lane, vel, locks in events:
            offset = max(pos, min(frames, offset))
            if offset > pos:
                _lib.drums_render(ptr(seq[pos:offset]), offset - pos)
                pos = offset
            self._apply_locks(min(lane, VOICES - 1), locks)
            _lib.drums_trigger(lane, vel)
        if pos < frames:
            _lib.drums_render(ptr(seq[pos:]), frames - pos)
        if self.two_engines and with_live:
            _live.drums_render(ptr(live), frames)
        return seq, live

    def _apply_locks(self, voice, locks):
        """Before a sequencer hit: put back the voice's settings the last step locked, then lock this step's."""
        for p in self._locked[voice] - set(locks):
            _lib.drums_set_param(p, self.values[p])
        for p, v in locks.items():
            _lib.drums_set_param(p, v)
        self._locked[voice] = set(locks)

    def pans(self):
        """Each voice's left and right gain from the kit's pan settings: (6, 2)."""
        g = np.zeros((VOICES, 2), np.float32)
        for v in range(VOICES):
            p = (_lib.drums_pan(v) if AVAILABLE else 64) / 127.0
            g[v] = math.cos(p * math.pi / 2), math.sin(p * math.pi / 2)
        return g * math.sqrt(2)      # centre = 1.0 in each side

    def stereo(self, voices):
        """(frames, 6) voices -> (frames, 2), panned the way the kit says."""
        return voices @ self.pans()
