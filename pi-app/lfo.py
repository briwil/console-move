"""Two LFOs for every instrument, each aimed at one of its settings (modelled on the Syntakt's). They belong to a
pattern: each pattern keeps its own two (the first time you pick a pattern it starts as a copy of the one you
came from, after that they're separate).

  DEST   which setting it moves (a number setting of the instrument; a list or mode isn't moved)
  WAVE   SINE, TRIANGLE, SAW UP, SAW DOWN, SQUARE, RANDOM (a new random value each cycle)
  SPEED  how long one cycle is: 8 bars down to 1/8 of a beat, in time with the tempo
  DEPTH  how far it swings each way, -100..+100 % of the setting's range
  PHASE  where in the cycle it starts
  MODE   FREE (runs on with the song) or TRIG (starts again at the pattern's first step)
The setting goes up and down around the value it has on the instrument's page.
"""
import copy
import math
import random

WAVES = ["SINE", "TRIANGLE", "SAW UP", "SAW DOWN", "SQUARE", "RANDOM"]
SPEEDS = [("8BAR", 32.0), ("4BAR", 16.0), ("2BAR", 8.0), ("1BAR", 4.0), ("1/2", 2.0), ("1/4", 1.0),
          ("1/8", 0.5), ("1/16", 0.25), ("1/32", 0.125)]
MODES = ["FREE", "TRIG"]
COUNT = 2


def default():
    return {"dest": -1, "wave": 0, "speed": 3, "depth": 50, "phase": 0, "mode": 0}


def defaults():
    return [default() for _ in range(COUNT)]


def of(pattern):
    """A pattern's two LFOs (made if it has none)."""
    if not hasattr(pattern, "lfos") or pattern.lfos is None:
        pattern.lfos = defaults()
    return pattern.lfos


def inherit(seq, n):
    """Picking pattern n: a pattern that has never had LFOs starts as a copy of the current one's."""
    p = seq.patterns[n]
    if getattr(p, "lfos", None) is None:
        cur = getattr(seq.pattern, "lfos", None)
        p.lfos = copy.deepcopy(cur) if cur else None


def to_json(pattern):
    l = getattr(pattern, "lfos", None)
    return None if l is None else copy.deepcopy(l)


def from_json(pattern, data):
    try:
        out = defaults()
        for o, d in zip(out, data or []):
            o["dest"] = int(d.get("dest", -1))
            o["wave"] = max(0, min(len(WAVES) - 1, int(d.get("wave", 0))))
            o["speed"] = max(0, min(len(SPEEDS) - 1, int(d.get("speed", 3))))
            o["depth"] = max(-100, min(100, int(d.get("depth", 50))))
            o["phase"] = max(0, min(100, int(d.get("phase", 0))))
            o["mode"] = max(0, min(len(MODES) - 1, int(d.get("mode", 0))))
        pattern.lfos = out if data else None
    except (TypeError, ValueError, AttributeError):
        pattern.lfos = None


def wave(shape, ph, cycle, seed):
    """-1..1 at phase ph (cycles; the whole part counts the cycle for RANDOM)."""
    f = ph - math.floor(ph)
    if shape == 0:
        return math.sin(2 * math.pi * f)
    if shape == 1:
        return 4 * abs(f - 0.5) - 1 if False else 1 - 4 * abs(f - 0.5)
    if shape == 2:
        return 2 * f - 1
    if shape == 3:
        return 1 - 2 * f
    if shape == 4:
        return 1.0 if f < 0.5 else -1.0
    return random.Random(hash((seed, int(math.floor(ph)))) & 0xFFFFFFFF).uniform(-1, 1)


def settings_dest(machine):
    """[param indexes] an LFO can move on this instrument: the number settings, in page order."""
    out = []
    try:
        for voice in range(max(1, getattr(machine, "voices", 1))):
            for _name, params in machine.pages(voice):
                for p in params:
                    if p not in out and machine.kind(p) in ("num", "pm", "send") and p < machine.param_count:
                        out.append(p)
    except Exception:
        pass
    return out


def top(machine, p):
    try:
        return int(machine.params[p].get("steps", 127))
    except Exception:
        return 127


class Runner:
    """Moves the settings the LFOs aim at (called often, from the sound core's bridge). It sends the setting to the
    instrument without changing the value kept on its page, so the LFO swings around that."""

    def __init__(self, engine):
        self.e = engine
        self.last = {}                 # (slot, lfo) -> (dest, last value sent)

    def tick(self):
        e = self.e
        try:
            fpb = e.frames_per_beat()
        except Exception:
            return
        for k, mid in enumerate(e.slots):
            m = e.drums.get(mid) if (mid and e.drums) else None
            seq = e.seqs.get(mid) if mid else None
            if m is None or seq is None:
                self._release(k, None)
                continue
            lfos = getattr(seq.pattern, "lfos", None) or []
            for j in range(COUNT):
                l = lfos[j] if j < len(lfos) else None
                dest = l["dest"] if l else -1
                key = (k, j)
                prev = self.last.get(key)
                if prev and prev[0] != dest:
                    self._restore(m, prev[0])
                    self.last.pop(key, None)
                if not l or dest < 0 or dest >= getattr(m, "param_count", 0) or not e.playing:
                    if prev and prev[0] == dest and not e.playing:
                        self._restore(m, dest)
                        self.last.pop(key, None)
                    continue
                if (not e.playing) or m.kind(dest) not in ("num", "pm", "send"):
                    continue
                frame = e.seq_clock + e.read_ahead
                if l["mode"] == 1:
                    frame -= getattr(seq, "anchor", 0)
                beats = frame / fpb
                ph = beats / SPEEDS[l["speed"]][1] + l["phase"] / 100.0
                v = wave(l["wave"], ph, 0, (k, j))
                base = m.get_param(dest)
                span = top(m, dest)
                val = int(round(max(0, min(span, base + v * l["depth"] / 100.0 * span / 2))))
                if prev is None or prev[1] != val:
                    self.last[key] = (dest, val)
                    self._send(m, dest, val)

    def _release(self, k, _m):
        for key in [x for x in self.last if x[0] == k]:
            self.last.pop(key, None)

    def _restore(self, m, dest):
        try:
            self._send(m, dest, m.get_param(dest))
        except Exception:
            pass

    @staticmethod
    def _send(m, index, value):
        with m._lock:
            m._pending.append(("param", index, int(value)))
