"""Python's side of the sound core (core.c): set it up, hand it the instruments, send it events, read the
Move's controls. The core runs in JACK's audio thread; nothing here does.

    c = Core()                                   # starts the JACK client (console mode must be running)
    s = c.add_engine(lib, voices=6)              # an engine library: lib.<prefix>_render / _trigger
    c.trigger(s, voice, velocity)                # as soon as possible (or at=frame)
    for frame, msg in c.read_midi(): ...         # pads, knobs, buttons
"""
import ctypes as C
import os
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "libconsolecore.so")
LIBJACK = os.environ.get("CONSOLE_LIBJACK", "/data/UserData/rnbo/lib/libjack.so.0")

EV_TRIGGER, EV_MIDI, EV_CALL = 1, 2, 3
u64, vp, i32, f32, ip = C.c_uint64, C.c_void_p, C.c_int, C.c_float, C.c_ssize_t


def addr(fn):
    """The address of a ctypes function (to hand to the core)."""
    return C.cast(fn, vp).value


class Core:
    def __init__(self, name=b"console"):
        lib = self.lib = C.CDLL(LIB)
        for fname, args, res in [
                ("core_open", [C.c_char_p, C.c_char_p], i32), ("core_close", [], None),
                ("core_rate", [], i32), ("core_block", [], i32), ("core_now", [], u64), ("core_cycles", [], C.c_uint), ("core_load", [], f32),
                ("core_add_engine", [vp, vp, i32], i32), ("core_add_module", [vp, vp, vp], i32),
                ("core_source_on", [i32, i32], None), ("core_remove", [i32], None),
                ("core_set_pan", [i32, i32, f32, f32], None), ("core_set_sends", [i32, i32, f32, f32], None),
                ("core_set_gain", [i32, f32], None), ("core_set_master", [f32], None),
                ("core_set_effects", [vp, vp, vp, vp], None), ("core_set_effect_levels", [f32, f32], None),
                ("core_push", [u64, i32, i32, ip, ip, ip, vp], i32), ("core_events_done", [], u64),
                ("core_read_midi", [C.c_char_p, i32], i32), ("core_send_midi", [C.c_char_p, i32], i32),
                ("core_set_display", [C.c_char_p], None)]:
            f = getattr(lib, fname)
            f.argtypes, f.restype = args, res
        r = lib.core_open(LIBJACK.encode(), name)
        if r != 0:
            raise RuntimeError({-1: "couldn't load libjack (%s)" % LIBJACK, -2: "libjack is missing functions",
                                -3: "JACK isn't running (is console mode on?)", -4: "couldn't make JACK ports",
                                -5: "couldn't start the JACK client"}.get(r, "error %d" % r))
        self.rate, self.block = lib.core_rate(), lib.core_block()
        self._keep = []                     # (frame, object): kept alive until the core is past that frame
        self._pushed = 0
        self._lock = threading.Lock()       # pushes come from more than one Python thread
        self._midibuf = C.create_string_buffer(12 * 256)

    def close(self):
        self.lib.core_close()

    # ---- time
    def now(self):
        return self.lib.core_now()

    def cycles(self):
        return self.lib.core_cycles()

    def load(self):
        """JACK's measure of how busy the audio cycle is, in percent."""
        return self.lib.core_load()

    # ---- sources
    def add_engine(self, render, trigger, voices):
        """render(float *out, int n) writing n frames of `voices` interleaved; trigger(voice, velocity)."""
        s = self.lib.core_add_engine(addr(render), addr(trigger), voices)
        if s < 0:
            raise RuntimeError("no room for another source")
        return s

    def add_module(self, sh_render, sh_midi, inst_ptr):
        s = self.lib.core_add_module(addr(sh_render), addr(sh_midi), inst_ptr)
        if s < 0:
            raise RuntimeError("no room for another source")
        return s

    def on(self, s, on=True):
        self.lib.core_source_on(s, 1 if on else 0)

    def remove(self, s):
        """Stops it. Wait for the next cycle (cycles() goes up) before freeing anything it uses."""
        self.lib.core_remove(s)

    def pan(self, s, voice, left, right):
        self.lib.core_set_pan(s, voice, left, right)

    def sends(self, s, voice, rev, dly):
        self.lib.core_set_sends(s, voice, rev, dly)

    def gain(self, s, g):
        self.lib.core_set_gain(s, g)

    def master(self, g):
        self.lib.core_set_master(g)

    def effects(self, rev_process, reverb, dly_process, delay):
        self.lib.core_set_effects(addr(rev_process), reverb, addr(dly_process), delay)

    def effect_levels(self, rev, dly):
        self.lib.core_set_effect_levels(rev, dly)

    # ---- events
    def _push(self, at, kind, src, a=0, b=0, c=0, fn=None, keep=None):
        with self._lock:
            if self.lib.core_push(at or 0, kind, src, a, b, c, fn) != 0:
                return False
            self._pushed += 1
            now = self.lib.core_now()
            if keep is not None:
                # strings an event points at: kept until a while after its frame has gone by
                self._keep.append((max(at or 0, now) + self.rate // 5, keep))
            if self._keep and self._pushed % 64 == 0:
                self._keep = [k for k in self._keep if k[0] >= now]
            return True

    def trigger(self, s, voice, velocity, at=0):
        return self._push(at, EV_TRIGGER, s, voice, velocity)

    def midi(self, s, b0, b1, b2, at=0):
        return self._push(at, EV_MIDI, s, b0, b1, b2)

    def call(self, fn, *args, at=0):
        """fn(*args) in the audio thread, in order with the other events: for changing an instrument's
        settings while it plays. Up to 3 arguments, each an int or bytes (kept alive until used)."""
        vals, keep = [], []
        for a in args:
            if isinstance(a, (bytes, bytearray)):
                buf = C.create_string_buffer(bytes(a))
                keep.append(buf)
                vals.append(C.cast(buf, vp).value)
            else:
                vals.append(int(a))
        vals += [0] * (3 - len(vals))
        return self._push(at, EV_CALL, -1, vals[0], vals[1], vals[2], addr(fn), keep or None)

    # ---- the Move's controls, lights and screen
    def read_midi(self):
        """[(frame, bytes)] for every control message since the last call."""
        out = []
        while True:
            k = self.lib.core_read_midi(self._midibuf, 256)
            raw = self._midibuf.raw
            for i in range(k):
                rec = raw[12 * i:12 * i + 12]
                out.append((int.from_bytes(rec[:8], "little"), rec[8:11]))
            if k < 256:
                return out

    def send_midi(self, msg):
        return self.lib.core_send_midi(bytes(msg), len(msg)) == 0

    def display(self, frame):
        """frame: b"MOVEDISP" + 1024 bytes."""
        self.lib.core_set_display(bytes(frame))
