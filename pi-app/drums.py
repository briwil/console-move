"""The drum synth, one of the console's inputs. Three drum machines, picked per song in SETTINGS:

- LXR-02: the six drum voices of the Erica Synths LXR-02 (its open-source firmware, GPL-3.0). Class LXR.
- TR-606 and TR-808: 6W6 and 8W8 from Schwung (Ableton Move), GPL-3.0, in drums/schwung/. Class Schwung.

Drums (at the bottom) holds the one in use and passes everything to it, so the rest of the app talks to
whichever machine the song has. Each machine has lanes (what the drum keys play: keys 1-8, and with SHIFT
9-16 when a machine has more than 8) and voices (its sounds, each with its settings pages).

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
    files = [f for f in glob.glob(os.path.join(DIR, "**", "*.[ch]"), recursive=True)
             if os.sep + "schwung" + os.sep not in f] + [os.path.join(DIR, "build.sh")]
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
            PROBLEM = "DRUM SYNTH NEEDS BUILDING: RUN ~/console/pi-app/setup.sh"
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
        PROBLEM = "DRUM SYNTH NEEDS BUILDING: RUN ~/console/pi-app/setup.sh"
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


class LXR:
    """The LXR-02's drum synth (the library holds a single engine, so make one of these)."""

    id, title = "lxr", "LXR-02"
    voices, channels, lanes = VOICES, VOICES, 7
    names, short = NAMES, SHORT
    lane_voice = [0, 1, 2, 3, 4, 5, 5]          # lane 6 plays the hi-hat open
    lane_short = ["D1", "D2", "D3", "SN", "CY", "HHc", "HHo"]
    lane_names = ["DRUM 1", "DRUM 2", "DRUM 3", "SNARE", "CYMBAL", "CLOSED HAT", "OPEN HAT"]

    def pages(self, voice):
        return dp.PAGES[voice]

    @staticmethod
    def label(param):
        return dp.LABELS.get(param, "?")

    @staticmethod
    def kind(param):
        return dp.KINDS.get(param, ("num",))[0]

    def multi(self, voices):
        """Voices -> the input channels MULTI records (one per track): the voices as they are."""
        return voices

    def channel_sends(self):
        return self.sends()

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
            if lane >= self.lanes:
                continue                     # a lane another machine used (patterns keep all 16)
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


# ---------------------------------------------------------------- the TR-606 and TR-808 (Schwung)

SW_DIR = os.path.join(DIR, "schwung")
# lane order: what keys 1-8 play, then with SHIFT 9-16. The common drums are on the first eight.
SPECS = {
    "606": {"title": "TR-606", "header": "606/sd606_params.h", "prefix": "sd606",
            "voices": ["bd", "sd", "lt", "ht", "ch", "oh", "cy", "cp"],
            "lanes": ["bd", "sd", "lt", "ht", "ch", "oh", "cy", "cp"]},
    "808": {"title": "TR-808", "header": "808/w8_params.h", "prefix": "w8",
            "voices": ["bd", "sd", "lt", "mt", "ht", "lc", "mc", "hc", "rs", "cl", "ma", "cp", "cb", "ch", "oh", "cy"],
            "lanes": ["bd", "sd", "lt", "mt", "ht", "cp", "ch", "oh", "lc", "mc", "hc", "rs", "cl", "ma", "cb", "cy"]},
}
# the machines' own effects and master stage aren't used (Console has its own effects and mixes the voices)
SKIP_KEYS = {"master_dist", "master_drive", "comp", "note_map", "ui_focus", "mutes", "rev_decay", "rev_tone",
             "rev_hpf", "rev_level", "dly_time", "dly_fdbk", "dly_tone", "dly_hpf", "dly_level", "dly_bpm"}
LABEL_WORDS = {"Rev": "REVERB", "Dly": "DELAY", "Distortion": "DIST", "Velocity": "VELOCITY"}


def _c_json(path, name):
    """A JSON text the machine's header keeps as a C string (split over many lines)."""
    import json
    import re
    s = open(path).read()
    body = s[s.index(name + "[] ="):]
    pos, parts = body.index("=") + 1, []
    lit = re.compile(r'\s*"((?:[^"\\]|\\.)*)"')
    while True:
        m = lit.match(body, pos)
        if not m:
            break
        parts.append(m.group(1))
        pos = m.end()
    return json.loads("".join(parts).encode().decode("unicode_escape"))


_sw_building = threading.Lock()


def _sw_build(mid):
    """drums/schwung/lib<mid>.so, built with g++ if it's missing or older than its code."""
    with _sw_building:
        return _sw_build_now(mid)


def _sw_build_now(mid):
    lib = os.path.join(SW_DIR, "lib%s.so" % mid)
    srcs = glob.glob(os.path.join(SW_DIR, mid, "*")) + glob.glob(os.path.join(SW_DIR, "glue*"))
    newest = max((os.path.getmtime(f) for f in srcs), default=0)
    if os.path.exists(lib) and os.path.getmtime(lib) >= newest:
        return lib
    try:
        r = subprocess.run(["g++", "-O2", "-shared", "-fPIC", "-w", "-o", lib + ".tmp",
                            os.path.join(SW_DIR, "glue%s.cpp" % mid)], capture_output=True, text=True, timeout=600)
        if r.returncode == 0:
            os.replace(lib + ".tmp", lib)
        else:
            print("Drums: couldn't build the %s (%s)" % (mid, r.stderr.strip()[-400:]))
    except (OSError, subprocess.SubprocessError) as e:
        print("Drums: couldn't build the %s (%s)" % (mid, e))
    return lib if os.path.exists(lib) else None


def _sw_load(path):
    try:
        lib = ctypes.CDLL(path)
    except OSError as e:
        print("Drums: couldn't load %s: %s" % (path, e))
        return None
    i, v, s = ctypes.c_int, None, ctypes.c_char_p
    for name, args, res in [("sw_init", [ctypes.c_float], i), ("sw_voices", [], i), ("sw_set", [s, i], v),
                            ("sw_get", [s], i), ("sw_trigger", [i, i], v),
                            ("sw_render", [ctypes.POINTER(ctypes.c_float), i], v)]:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, res
    return lib


class Schwung:
    """The TR-606 (6W6) or TR-808 (8W8), each voice coming out on its own (see drums/schwung/glue*.cpp)."""

    channels = 8                     # MULTI: lanes 1-8 onto tracks 1-8; with 16, lanes 9-16 share them

    def __init__(self, mid):
        spec = SPECS[mid]
        self.id, self.title = mid, spec["title"]
        lib = _sw_build(mid)
        self.available = False
        self._lib = _sw_load(lib) if lib else None
        live_path = lib[:-3] + "_live.so" if lib else None
        if self._lib and live_path:
            try:
                if not os.path.exists(live_path) or os.path.getmtime(live_path) < os.path.getmtime(lib):
                    shutil.copyfile(lib, live_path + ".tmp")
                    os.replace(live_path + ".tmp", live_path)
            except OSError:
                live_path = None
        self._live = (_sw_load(live_path) if live_path else None) or self._lib
        if not self._lib:
            return
        self.voices = self._lib.sw_init(44100.0)
        if self._live is not self._lib:
            self._live.sw_init(44100.0)
        self.available = self.voices == len(spec["voices"])
        # the settings, from the machine's own tables
        header = os.path.join(SW_DIR, spec["header"])
        chain = _c_json(header, spec["prefix"] + "_chain_params_json")
        levels = _c_json(header, spec["prefix"] + "_ui_pages_json")["levels"]
        info = {p["key"]: p for p in chain}
        self.params = []             # [{key, label, kind, count/options, default, voice}]
        self.index = {}
        def add(key, label, voice):
            p = info[key]
            entry = {"key": key, "label": LABEL_WORDS.get(label, label).upper(), "voice": voice,
                     "kind": "menu" if p["type"] == "enum" else "num",
                     "options": [o.upper() for o in p.get("options", [])], "default": int(p.get("default", 0))}
            self.index[key] = len(self.params)
            self.params.append(entry)
        self._pages = []
        self.names = []
        for v, vk in enumerate(spec["voices"]):
            lvl = levels[vk]
            self.names.append(lvl["name"].upper())
            labels = {q["key"]: q["label"] for q in lvl["params"] if "key" in q}
            for key in lvl["knobs"]:
                if key not in self.index and key not in SKIP_KEYS:
                    add(key, labels.get(key, key), v)
        root_labels = {q["key"]: q["label"] for q in levels["root"]["params"] if "key" in q}
        kit_keys = [k for k in ("volume", "vel_depth", "hh_choke") if k in info]
        for key in kit_keys:
            if key not in self.index:
                add(key, root_labels.get(key, key), None)
        kit_page = ("KIT", [self.index[k] for k in kit_keys])
        for v, vk in enumerate(spec["voices"]):
            knobs = [self.index[k] for k in levels[vk]["knobs"] if k in self.index]
            self._pages.append([("SOUND", knobs), kit_page])
        self.short = [vk.upper() for vk in spec["voices"]]
        self.lane_voice = [spec["voices"].index(k) for k in spec["lanes"]]
        self.lanes = len(self.lane_voice)
        self.lane_short = [self.short[v] for v in self.lane_voice]
        self.lane_names = [self.names[v] for v in self.lane_voice]
        self.param_count = self.engine_params = len(self.params)
        self.init_values = [p["default"] for p in self.params]
        self.values = list(self.init_values)
        self._send_keys = [(self.index.get(vk + "_rev"), self.index.get(vk + "_dly")) for vk in spec["voices"]]
        self._lock = threading.Lock()
        self._pending = []
        self._locked = [set() for _ in range(self.voices)]
        self.load_kit(self.init_values)

    # ------------------------------------------------------------ what the screens ask
    def pages(self, voice):
        return self._pages[voice]

    def label(self, param):
        return self.params[param]["label"] if 0 <= param < len(self.params) else "?"

    def kind(self, param):
        return self.params[param]["kind"] if 0 <= param < len(self.params) else "num"

    def value_text(self, param, v=None):
        v = self.get_param(param) if v is None else v
        p = self.params[param]
        if p["kind"] == "menu":
            return p["options"][v] if 0 <= v < len(p["options"]) else str(v)
        return str(v)

    def fraction(self, param, v=None):
        v = self.get_param(param) if v is None else v
        p = self.params[param]
        if p["kind"] == "menu":
            return v / max(1, len(p["options"]) - 1)
        return v / 127

    @staticmethod
    def lockable(param):
        return True

    def stepped(self, param, v, clicks):
        p = self.params[param]
        if p["kind"] == "menu":
            return max(0, min(len(p["options"]) - 1, v + (1 if clicks > 0 else -1)))
        return max(0, min(127, v + clicks))

    def step(self, param, clicks):
        v = self.stepped(param, self.get_param(param), clicks)
        self.set_param(param, v)
        return v

    # ------------------------------------------------------------ settings
    def set_param(self, index, value):
        if not 0 <= index < self.param_count:
            return
        value = self.stepped(index, int(value), 0) if self.params[index]["kind"] == "menu" else max(0, min(127, int(value)))
        with self._lock:
            self.values[index] = value
            self._pending.append(("param", index, value))

    def get_param(self, index):
        return self.values[index] if 0 <= index < self.param_count else 0

    def kit(self):
        return list(self.values)

    def load_kit(self, values):
        values = [int(v) for v in list(values)[:self.param_count]]
        values += self.init_values[len(values):]
        with self._lock:
            self.values = values
            self._pending.extend(("param", i, v) for i, v in enumerate(values))

    def init_kit(self):
        self.load_kit(self.init_values)

    def sends(self):
        """Each voice's reverb and delay sends (its REVERB and DELAY knobs), 0..1."""
        rev = np.array([self.values[r] if r is not None else 0 for r, _ in self._send_keys], np.float32) / 127
        dly = np.array([self.values[d] if d is not None else 0 for _, d in self._send_keys], np.float32) / 127
        return rev, dly

    def channel_sends(self):
        rev, dly = self.sends()
        first = [self.lane_voice[c] for c in range(min(self.channels, self.lanes))]
        return rev[first], dly[first]

    def set_bpm(self, bpm):
        pass                         # nothing here follows the tempo (their delays aren't used)

    # ------------------------------------------------------------ sound
    def hit(self, lane, velocity=100):
        with self._lock:
            self._pending.append(("hit", lane, velocity))

    @property
    def two_engines(self):
        return self._live is not self._lib

    def _set(self, lib, index, value):
        lib.sw_set(self.params[index]["key"].encode(), int(value))

    def render(self, frames, events=(), with_live=True):
        """As LXR.render: (sequencer, by hand), each (frames, voices)."""
        todo = []
        if with_live:
            with self._lock:
                todo, self._pending = self._pending, []
        seq = np.zeros((frames, self.voices), np.float32)
        live = np.zeros((frames, self.voices), np.float32)
        engines = (self._lib, self._live) if self.two_engines else (self._lib,)
        for t in todo:
            if t[0] == "hit":
                if 0 <= t[1] < self.lanes:
                    self._live.sw_trigger(self.lane_voice[t[1]], t[2])
            elif t[0] == "param":
                for lib in engines:
                    self._set(lib, t[1], t[2])
        pos = 0
        ptr = lambda a: a.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        for offset, lane, vel, locks in events:
            if not 0 <= lane < self.lanes:
                continue
            offset = max(pos, min(frames, offset))
            if offset > pos:
                self._lib.sw_render(ptr(seq[pos:offset]), offset - pos)
                pos = offset
            voice = self.lane_voice[lane]
            for p in self._locked[voice] - set(locks):
                self._set(self._lib, p, self.values[p])
            for p, v in locks.items():
                if 0 <= p < self.param_count:
                    self._set(self._lib, p, v)
            self._locked[voice] = set(p for p in locks if 0 <= p < self.param_count)
            self._lib.sw_trigger(voice, vel)
        if pos < frames:
            self._lib.sw_render(ptr(seq[pos:]), frames - pos)
        if self.two_engines and with_live:
            self._live.sw_render(ptr(live), frames)
        return seq, live

    def pans(self):
        return np.ones((self.voices, 2), np.float32)          # these machines are mono: every voice centred

    def stereo(self, voices):
        return voices @ self.pans()

    def multi(self, voices):
        """Voices -> 8 channels for MULTI: lane n (and with SHIFT, lane n + 8) onto track n."""
        out = np.zeros((len(voices), self.channels), np.float32)
        for lane, v in enumerate(self.lane_voice):
            out[:, lane % self.channels] += voices[:, v]
        return out


MACHINES = [("lxr", "LXR-02"), ("606", "TR-606"), ("808", "TR-808")]


def _prebuild():
    """At start-up, build the 606 and 808 in the background if they need it (setup.sh normally has), so
    picking one in SETTINGS doesn't wait for the compiler."""
    for mid in SPECS:
        _sw_build(mid)


threading.Thread(target=_prebuild, daemon=True, name="drum builds").start()


class Drums:
    """The song's drum machine. Everything is passed on to it (Drums().use() picks another)."""

    def __init__(self, machine="lxr"):
        self.__dict__["_machines"] = {}
        self.__dict__["m"] = None
        self.__dict__["saved_kits"] = {}       # {machine: kit} from the song, for machines not started yet
        if not self.use(machine):
            self.use("lxr")

    def use(self, machine):
        """Switch to a machine ("lxr", "606", "808"). Returns True if it's there (built and working)."""
        ms = self._machines
        if machine not in ms:
            try:
                ms[machine] = LXR() if machine == "lxr" else Schwung(machine)
            except Exception as e:
                print("Drums: the %s isn't available: %s" % (machine, e))
                return False
            if machine != "lxr" and not ms[machine].available:
                del ms[machine]
                return False
            if machine in self.saved_kits:
                ms[machine].load_kit(self.saved_kits[machine])
        self.__dict__["m"] = ms[machine]
        return True

    def restore(self, machine, kits, kit=None):
        """Opening a song: its machine, every machine's kit as the song left it (the Init Kit if it has none)
        and kit for the song's own machine (older songs only have that one)."""
        kits = dict(kits or {})
        if kit is not None:
            kits[machine] = kit
        self.__dict__["saved_kits"] = kits
        for mid, m in self._machines.items():
            if mid in kits:
                m.load_kit(kits[mid])
            else:
                m.init_kit()
        return self.use(machine) or self.use("lxr")

    def is_init_kit(self, machine, kit):
        """Whether kit (saved for machine) is that machine's Init Kit (False if it can't tell)."""
        m = self._machines.get(machine)
        if m is None:
            return not kit
        if not kit:
            return True
        values = [int(v) for v in list(kit)[:m.param_count]]
        if machine == "lxr" and len(values) == dp.NOISE_DECAY and len(values) > 56:
            values.append(values[56])
        values += m.init_values[len(values):]
        return values == m.init_values

    @property
    def machine(self):
        return self.m.id

    def machine_kits(self):
        """{machine: kit} for every machine used so far (saved with the song)."""
        return {k: m.kit() for k, m in self._machines.items()}

    def __getattr__(self, name):
        return getattr(self.__dict__["m"], name)

    def __setattr__(self, name, value):
        setattr(self.m, name, value)


def available_machines():
    """[(id, title)] of the machines that can run here."""
    out = [("lxr", "LXR-02")] if AVAILABLE else []
    for mid, spec in SPECS.items():
        lib = os.path.join(SW_DIR, "lib%s.so" % mid)
        if os.path.exists(lib) or os.path.exists(os.path.join(SW_DIR, "glue%s.cpp" % mid)):
            out.append((mid, spec["title"]))
    return out
