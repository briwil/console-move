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
import subprocess
import threading

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "drums")
LIB = os.path.join(DIR, "libdrums.so")
VOICES = 6
NAMES = ["DRUM 1", "DRUM 2", "DRUM 3", "SNARE", "CYMBAL", "HI-HAT"]
OPEN_HAT = 6
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


def _load():
    global PROBLEM
    if not os.path.exists(LIB) or _newest_source() > os.path.getmtime(LIB):
        ok, err = _build()
        if not ok and not os.path.exists(LIB):
            PROBLEM = "DRUM SYNTH NEEDS BUILDING: RUN pi-app/setup.sh"
            print("Drums: couldn't build drums/libdrums.so (%s). Run pi-app/setup.sh." % err[-500:])
            return None
    try:
        lib = ctypes.CDLL(LIB)
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


class Drums:
    """One drum synth (the library holds a single engine, so make one of these)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending = []         # things to do at the start of the next render, in order
        if AVAILABLE:
            _lib.drums_init()
            self.param_count = _lib.drums_param_count()
        else:
            self.param_count = 0

    # These can be called from any thread: they take effect at the start of the next block of sound.
    def hit(self, lane, velocity=100):
        with self._lock:
            self._pending.append(("hit", lane, velocity))

    def set_param(self, index, value):
        with self._lock:
            self._pending.append(("param", index, value))

    def get_param(self, index):
        return _lib.drums_get_param(index) if AVAILABLE else 0

    def kit(self):
        """The current sound settings, to save in the project."""
        return [self.get_param(i) for i in range(self.param_count)]

    def load_kit(self, values):
        with self._lock:
            self._pending.extend(("param", i, int(v)) for i, v in enumerate(values[:self.param_count]))

    def init_kit(self):
        with self._lock:
            self._pending.append(("init",))

    def set_bpm(self, bpm):
        with self._lock:
            self._pending.append(("bpm", int(round(bpm))))

    def render(self, frames):
        """The next frames of sound: (frames, 6) float32, one mono channel per voice (audio thread)."""
        with self._lock:
            todo, self._pending = self._pending, []
        out = np.zeros((frames, VOICES), np.float32)
        if not AVAILABLE:
            return out
        for t in todo:
            if t[0] == "hit":
                _lib.drums_trigger(t[1], t[2])
            elif t[0] == "param":
                _lib.drums_set_param(t[1], t[2])
            elif t[0] == "init":
                _lib.drums_load_init_kit()
            elif t[0] == "bpm":
                _lib.drums_set_bpm(t[1])
        _lib.drums_render(out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), frames)
        return out

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
