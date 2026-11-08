"""Punch-in effects (OP-XY style), held on pads or put on steps, and stacked: one from each group at once.

Groups (one effect from each can play together; another from the same group replaces it):
    TIME    1-8   REPEAT 1/4, 1/8, 1/16, 1/32, 1/8T, REVERSE, TAPE STOP, HALF SPEED
    FILTER  9-11  LOW PASS, HIGH PASS, RESO PEAK
    CRUSH   12    BITCRUSH          GATE  13  GATE 1/16          PAN   14  PAN SWING
    ECHO    15    ECHO THROW        KILL  16  KILL

A set of effects is a mask: bit (fx - 1) for each. Each pattern keeps its own steps:
pattern.punch = {step: [mask, chance]} (chance a place in sequencer.CHANCES, for all of that step's effects).
The steps are sixteenths from the pattern's start, as many as the pattern is long. The sound work is in
fx/fx.c (punch_process), one stage for each of TIME, FILTER, CRUSH, GATE and KILL, in that order; PAN SWING
and ECHO THROW are done with the pans and sends (core.c, audio.py).
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
GROUPS = [range(1, 9), range(9, 12), (12,), (13,), (14,), (15,), (16,)]
STAGES = [0, 1, 2, 3, 6]                        # the groups punch_process does, in order


def bit(fx):
    return 1 << (fx - 1)


def group(fx):
    return next(g for g, fxs in enumerate(GROUPS) if fx in fxs)


def effects(mask):
    """The effects (1-16) in a mask, lowest first."""
    return [fx for fx in range(1, 17) if mask & bit(fx)]


def in_group(mask, g):
    """The effect of group g in the mask (0: none)."""
    for fx in GROUPS[g]:
        if mask & bit(fx):
            return fx
    return 0


def with_fx(mask, fx):
    """The mask with fx in it, taking out any other of its group."""
    for other in GROUPS[group(fx)]:
        mask &= ~bit(other)
    return mask | bit(fx)


def over(base, top):
    """top's effects win their groups; base's others stay."""
    for fx in effects(top):
        base = with_fx(base, fx)
    return base


def label(mask, short=False):
    names = SHORT if short or len(effects(mask)) > 1 else NAMES
    return "+".join(names[fx - 1] for fx in effects(mask))


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
    """(mask, step, beats from the pattern's start) for sequencer time `frame`. mask 0: none there (or its
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
    mask, ch = v
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
    return mask, i, beat


def to_json(pattern):
    pu = getattr(pattern, "punch", None)
    return {str(k): [effects(v[0]), sequencer.CHANCES[v[1]]] for k, v in pu.items() if v[0]} if pu else None


def from_json(pattern, data):
    out = {}
    if isinstance(data, dict):
        for k, v in data.items():
            try:
                fxs = v[0] if isinstance(v[0], list) else [v[0]]     # (the first version kept one effect)
                mask = 0
                for fx in fxs:
                    if 1 <= int(fx) <= len(NAMES):
                        mask = with_fx(mask, int(fx))
                if mask and 0 <= int(k) < sequencer.MAX_STEPS:
                    out[int(k)] = [mask, sequencer.chance_index(v[1])]
            except (TypeError, ValueError, IndexError):
                pass
    pattern.punch = out or None
