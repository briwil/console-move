"""Punch-in effects (OP-XY style): one effect at a time on an instrument, held on a pad or put on steps.

Each pattern keeps its own: pattern.punch = {step: [effect, chance]} (effect 1-16 as NAMES, chance a place in
sequencer.CHANCES). The steps are sixteenths from the pattern's start, as many as the pattern is long. The sound
work is in fx/fx.c (punch_process); PAN SWING and ECHO THROW are done in audio.py with the pans and sends.
"""
import math
import random

import sequencer

NAMES = ["REPEAT 1/4", "REPEAT 1/8", "REPEAT 1/16", "REPEAT 1/32", "REPEAT 1/8T", "REVERSE", "TAPE STOP",
         "HALF SPEED", "LOW PASS", "HIGH PASS", "RESO PEAK", "BITCRUSH", "GATE 1/16", "PAN SWING", "ECHO THROW",
         "KILL"]
SHORT = ["RP1/4", "RP1/8", "RP16", "RP32", "RP8T", "REV", "STOP", "HALF", "LP", "HP", "RESO", "CRUSH", "GATE",
         "PAN", "ECHO", "KILL"]
PAN_SWING, ECHO_THROW = 14, 15
STEPS_PER_BEAT = 4


def of(pattern):
    """The pattern's punch steps (made if it has none)."""
    if getattr(pattern, "punch", None) is None:
        pattern.punch = {}
    return pattern.punch


def length(pattern):
    """How many punch steps a pattern has: as long as its longest lane (a synth: its length)."""
    if hasattr(pattern, "lanes"):
        return max(1, max(ln.length for ln in pattern.lanes))
    return max(1, pattern.length)


def name(fx):
    return NAMES[fx - 1] if 1 <= fx <= len(NAMES) else ""


def at(seq, frame, fpb, decided=None):
    """(effect, step, beats from the pattern's start) for sequencer time `frame`. effect 0: none there (or its
    chance said no this time round)."""
    p = seq.pattern
    sf = fpb / STEPS_PER_BEAT
    k = math.floor((frame - seq.anchor) / sf)
    beat = (frame - seq.anchor) / fpb
    if k < 0:
        return 0, None, beat
    n = length(p)
    i = k % n
    v = (getattr(p, "punch", None) or {}).get(i)
    if not v:
        return 0, i, beat
    fx, ch = v
    if ch:
        if decided is not None and k in decided:
            ok = decided[k]
        else:
            c = sequencer.CHANCES[ch]
            if c.endswith("%"):
                ok = random.Random(hash((getattr(seq, "seed", 0), "punch", k))).random() * 100 < int(c[:-1])
            else:
                a, b = (int(x) for x in c.split(":"))
                ok = (k // n) % b == a - 1
            if decided is not None:
                if len(decided) > 256:
                    decided.clear()
                decided[k] = ok
        if not ok:
            return 0, i, beat
    return fx, i, beat


def to_json(pattern):
    pu = getattr(pattern, "punch", None)
    return {str(k): [v[0], sequencer.CHANCES[v[1]]] for k, v in pu.items()} if pu else None


def from_json(pattern, data):
    out = {}
    if isinstance(data, dict):
        for k, v in data.items():
            try:
                fx = int(v[0])
                if 1 <= fx <= len(NAMES) and 0 <= int(k) < sequencer.MAX_STEPS:
                    out[int(k)] = [fx, sequencer.chance_index(v[1])]
            except (TypeError, ValueError, IndexError):
                pass
    pattern.punch = out or None
