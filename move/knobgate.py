"""Settings that pick a mode (DIST, CHOKE, a wave, on / off...) instead of a number: one click of a knob is
too touchy there, so it takes CLICKS clicks the same way to move to the next choice. Turning the other way,
or pausing, starts the count again. Shift + turn moves one choice a click."""
import time

CLICKS = 5
PAUSE = 0.7                       # seconds without a click: the count starts again

_acc = {}


def gate(key, delta, shift=False):
    """The clicks to apply now: 0 until enough have come, then 1 or -1."""
    if shift:
        return 1 if delta > 0 else -1
    now = time.monotonic()
    total, last = _acc.get(key, (0, 0.0))
    if now - last > PAUSE or (total and (total > 0) != (delta > 0)):
        total = 0
    total += 1 if delta > 0 else -1
    if abs(total) >= CLICKS:
        _acc[key] = (0, now)
        return 1 if total > 0 else -1
    _acc[key] = (total, now)
    return 0


def is_choice(drums, param):
    try:
        return drums.kind(param) in ("menu", "onoff")
    except Exception:
        return False
