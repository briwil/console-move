"""The SAMPLER: a drum machine of 16 samples, one per drum, each loaded from the Move's sample folders (or any
folder in CONSOLE_SAMPLES, colon separated). Nothing to build: it is plain numpy, so it works anywhere.

Each drum has 8 settings: SAMPLE (the file), LEVEL, PITCH (0.5 semitone a click, 64 = as recorded), START (where in
the sample it begins), DECAY (127: the whole sample; lower: faded out sooner), PAN, REVERB and DELAY.
It looks like the other drum machines to the rest of the app (drums.py's Drums class).

A song keeps a sample as its place in the sorted list of files, so adding or removing samples can change which
one a drum points at (the list is sorted by path: put new samples in a new folder to keep the old order).
"""
import ctypes
import glob
import os
import shutil
import struct
import threading

import numpy as np

RATE = 44100
LANES = 16
PER = 8                                   # settings per drum
KEYS = ["sample", "level", "pitch", "start", "decay", "pan", "reverb", "delay"]
LABELS = ["SAMPLE", "LEVEL", "PITCH", "START", "DECAY", "PAN", "REVERB", "DELAY"]
DEFAULTS = [0, 100, 64, 0, 127, 64, 0, 0]
MAX_SECONDS = 12
MAX_FILES = 4000
LIVE_TAIL = RATE * 4
DEFAULT_DIRS = ["/data/UserData/UserLibrary/Samples", "/data/UserData/console/samples",
                os.path.expanduser("~/console-samples")]


def lib_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "drums", "sampler", "libsampler.so")


def _load(path):
    if not path or not os.path.exists(path):
        return None
    try:
        lib = ctypes.CDLL(path)
    except OSError as e:
        print("Sampler: couldn't load %s: %s" % (path, e))
        return None
    i, v, c = ctypes.c_int, None, ctypes.c_char_p
    for name, args, res in [("sw_init", [ctypes.c_float], i), ("sw_voices", [], i), ("sw_set", [c, i], v),
                            ("sw_get", [c], i), ("sw_trigger", [i, i], v), ("sw_load", [i, ctypes.c_void_p, i], v),
                            ("sw_render", [ctypes.POINTER(ctypes.c_float), i], v)]:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, res
    return lib


def sample_dirs():
    env = os.environ.get("CONSOLE_SAMPLES")
    return [d for d in (env.split(":") if env else DEFAULT_DIRS) if d]


def list_samples():
    """The sorted sample files (paths) in the sample folders."""
    out = []
    for d in sample_dirs():
        for ext in ("wav", "WAV", "Wav"):
            out += glob.glob(os.path.join(d, "**", "*." + ext), recursive=True)
    return sorted(set(out))[:MAX_FILES]


def read_wav(path):
    """(mono float32 samples at RATE) or None. Reads PCM 8/16/24/32 and float32 WAVs, any rate."""
    try:
        data = open(path, "rb").read()
        if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            return None
        pos, fmt, raw = 12, None, None
        while pos + 8 <= len(data):
            tag, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
            body = data[pos + 8:pos + 8 + size]
            if tag == b"fmt ":
                fmt = struct.unpack("<HHIIHH", body[:16])
                if fmt[0] == 0xFFFE and len(body) >= 26:
                    fmt = (struct.unpack("<H", body[24:26])[0],) + fmt[1:]
            elif tag == b"data":
                raw = body
                break
            pos += 8 + size + (size & 1)
        if fmt is None or raw is None:
            return None
        tag, ch, rate, _br, _ba, bits = fmt
        ch = max(1, ch)
        if tag == 3 and bits == 32:
            x = np.frombuffer(raw[:len(raw) // 4 * 4], "<f4").astype(np.float32)
        elif tag == 1 and bits == 16:
            x = np.frombuffer(raw[:len(raw) // 2 * 2], "<i2").astype(np.float32) / 32768
        elif tag == 1 and bits == 8:
            x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
        elif tag == 1 and bits == 24:
            b = np.frombuffer(raw[:len(raw) // 3 * 3], np.uint8).reshape(-1, 3).astype(np.int32)
            v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
            x = (np.where(v >= 1 << 23, v - (1 << 24), v)).astype(np.float32) / (1 << 23)
        elif tag == 1 and bits == 32:
            x = np.frombuffer(raw[:len(raw) // 4 * 4], "<i4").astype(np.float32) / (1 << 31)
        else:
            return None
        x = x[:len(x) // ch * ch].reshape(-1, ch).mean(axis=1)
        if rate != RATE and rate > 0:
            n = int(len(x) * RATE / rate)
            x = np.interp(np.linspace(0, len(x) - 1, max(1, n)), np.arange(len(x)), x).astype(np.float32)
        return np.ascontiguousarray(x[:RATE * MAX_SECONDS], np.float32)
    except (OSError, ValueError, struct.error):
        return None


class Sampler:
    id = "sampler"
    title = "SAMPLER"
    channels = 8
    voices = LANES
    lanes = LANES

    def __init__(self):
        self.files = list_samples()
        self.available = False
        self._lib = _load(lib_path())
        if not self._lib:
            return
        live = lib_path()[:-3] + "_live.so"
        try:
            shutil.copyfile(lib_path(), live + ".tmp")
            os.replace(live + ".tmp", live)
        except OSError:
            live = None
        self._live = (_load(live) if live else None) or self._lib
        self._lib.sw_init(float(RATE))
        if self._live is not self._lib:
            self._live.sw_init(float(RATE))
        self.available = True
        self._cache = {}
        self.params = [{"key": "%s%d" % (KEYS[i % PER], i // PER + 1), "label": LABELS[i % PER],
                        "voice": i // PER, "kind": "menu" if i % PER == 0 else "num"} for i in range(LANES * PER)]
        self.param_count = self.engine_params = len(self.params)
        self.init_values = [DEFAULTS[i % PER] for i in range(self.param_count)]
        self.values = list(self.init_values)
        self.lane_voice = list(range(LANES))
        self.fast_params = {i * PER for i in range(LANES)}      # the SAMPLE settings: scroll a list, not a mode
        self._send_keys = [(v * PER + 6, v * PER + 7) for v in range(LANES)]
        self._lock = threading.Lock()
        self._pending = []
        self._locked = [set() for _ in range(LANES)]
        self.load_kit(self.init_values)

    # ------------------------------------------------------------ names
    def sample_name(self, v):
        i = self.values[v * PER]
        if 0 < i <= len(self.files):
            return os.path.splitext(os.path.basename(self.files[i - 1]))[0].upper()
        return "EMPTY"

    @property
    def names(self):
        return [self.sample_name(v) for v in range(LANES)]

    @property
    def lane_names(self):
        return self.names

    @property
    def short(self):
        return [n[:4] for n in self.names]

    @property
    def lane_short(self):
        return [str(v + 1) for v in range(LANES)]

    def problem(self):
        return "" if self.files else "NO SAMPLES: PUT .WAV FILES IN THE MOVE'S SAMPLES"

    # ------------------------------------------------------------ what the screens ask
    def pages(self, voice):
        v = max(0, min(LANES - 1, voice))
        return [("SOUND", [v * PER + k for k in range(PER)])]

    def label(self, param):
        return self.params[param]["label"] if 0 <= param < len(self.params) else "?"

    def kind(self, param):
        return self.params[param]["kind"] if 0 <= param < len(self.params) else "num"

    def _top(self, param):
        return len(self.files) if param % PER == 0 else 127

    def value_text(self, param, v=None):
        v = self.get_param(param) if v is None else v
        k = param % PER
        if k == 0:
            if 0 < v <= len(self.files):
                return os.path.splitext(os.path.basename(self.files[v - 1]))[0].upper()
            return "EMPTY"
        if k == 2:
            return "%+.1f" % ((v - 64) / 2)
        if k == 5:
            return "C" if v == 64 else ("L%d" % (64 - v) if v < 64 else "R%d" % (v - 64))
        if k in (6, 7):
            return "%d%%" % round(v / 127 * 100)
        return str(v)

    def fraction(self, param, v=None):
        v = self.get_param(param) if v is None else v
        return v / max(1, self._top(param))

    @staticmethod
    def lockable(param):
        return 1 <= param % PER <= 4                  # level, pitch, start, decay (not the sample, pan or sends)

    def stepped(self, param, v, clicks):
        return max(0, min(self._top(param), v + clicks))

    def step(self, param, clicks):
        v = self.stepped(param, self.get_param(param), clicks)
        self.set_param(param, v)
        return v

    def set_param(self, index, value):
        if not 0 <= index < self.param_count:
            return
        value = max(0, min(self._top(index), int(value)))
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
            self.values = [max(0, min(self._top(i), v)) for i, v in enumerate(values)]
            self._pending.extend(("param", i, v) for i, v in enumerate(self.values))

    def init_kit(self):
        self.load_kit(self.init_values)

    def sends(self):
        rev = np.array([self.values[r] for r, _ in self._send_keys], np.float32) / 127
        dly = np.array([self.values[d] for _, d in self._send_keys], np.float32) / 127
        return rev, dly

    def channel_sends(self):
        rev, dly = self.sends()
        return rev[:self.channels], dly[:self.channels]

    def set_bpm(self, bpm):
        pass

    _seq_left = _live_left = 0

    # ------------------------------------------------------------ sound
    def hit(self, lane, velocity=100):
        with self._lock:
            self._pending.append(("hit", lane, velocity))

    def _sample(self, index):
        if not 0 < index <= len(self.files):
            return None
        if index not in self._cache:
            self._cache[index] = read_wav(self.files[index - 1])
        return self._cache[index]

    def _set(self, lib, index, value):
        """One setting into a copy of the engine (lib: the library, or a stand-in that queues the call for the
        sound core)."""
        v, k = divmod(index, PER)
        if k == 0:
            x = self._sample(int(value))
            if x is None or not len(x):
                lib.sw_load(v, 0, 0)
            else:
                lib.sw_load(v, int(x.ctypes.data), len(x))        # (the cache keeps x alive)
        elif k <= 4:
            lib.sw_set(("%s%d" % (KEYS[k], v + 1)).encode(), int(value))

    def render(self, frames, events=(), with_live=True):
        """Not used: the sound core plays this machine through its library (see core/instruments.py)."""
        z = np.zeros((frames, LANES), np.float32)
        return z, z.copy()

    def pans(self):
        p = np.zeros((LANES, 2), np.float32)
        for v in range(LANES):
            a = self.values[v * PER + 5] / 127 * (np.pi / 2)
            p[v] = (np.cos(a) * 1.4142, np.sin(a) * 1.4142)
        return p * 0.7071

    def stereo(self, voices):
        return voices @ self.pans()

    def multi(self, voices):
        out = np.zeros((len(voices), self.channels), np.float32)
        for lane in range(LANES):
            out[:, lane % self.channels] += voices[:, lane]
        return out
