"""The drum sequencer: 16 patterns, each with 7 lanes (the drum synth's voices, with the hi-hat's open
and closed sounds as two lanes) of up to 64 steps.

Each step: on/off, velocity, chance, ratchets (quick repeats inside the step) and parameter locks
(drum settings that change for that step only). Each lane: its own length (1-64, looping on its own),
rate (1/16, triplets...) and a Euclidean fill.

Timing runs on the sequencer's own clock, not the tape's: frames since PLAY (engine.seq_clock), so every
PLAY starts the pattern from step 1 and tape loops or moving the playhead don't touch it (Brian: they're
separate things). Step k of a lane starts at anchor + k * (frames per step) on that clock. The audio
thread asks events() for each block it plays. The screen and keys change things through the methods here; one lock keeps the
two threads apart.
"""
import copy
import math
import random
import threading

MAX_LANES = 16          # lanes kept in every pattern: the drum machine uses its own number of them
LANES = MAX_LANES       #   (LXR 7, 606 8, 808 16: drums.Drums().lanes)
MAX_STEPS = 64
PATTERNS = 16
LANE_NAMES = ["DRUM 1", "DRUM 2", "DRUM 3", "SNARE", "CYMBAL", "CLOSED HAT", "OPEN HAT"]
LANE_VOICE = [0, 1, 2, 3, 4, 5, 5]          # the drum synth voice each lane plays (its settings)
RATES = [("1/16", 4), ("1/16T", 6), ("1/8", 2), ("1/8T", 3), ("1/32", 8)]      # (name, steps per beat)
# chance: a percentage, or "A:B": plays on the A-th time round the lane out of every B
CHANCES = ["%d%%" % p for p in range(100, -1, -10)] + ["1:2", "2:2", "1:3", "2:3", "3:3", "1:4", "2:4", "3:4", "4:4"]
# songs saved before October 2026 stored chance as a place in this older list
OLD_CHANCES = ["100%", "90%", "75%", "50%", "25%", "10%", "1:2", "2:2", "1:3", "2:3", "3:3", "1:4", "2:4", "3:4", "4:4"]


def chance_index(saved):
    """A saved chance (its text now; a number in the old list before) -> its place in CHANCES."""
    if isinstance(saved, (int, float)) and not isinstance(saved, bool):
        saved = OLD_CHANCES[max(0, min(len(OLD_CHANCES) - 1, int(saved)))]
    saved = str(saved)
    if saved in CHANCES:
        return CHANCES.index(saved)
    if saved.endswith("%"):                          # 75% and 25% went: the nearest ten, rounding up
        try:
            p = min(100, max(0, int(-(-int(saved[:-1]) // 10) * 10)))
            return CHANCES.index("%d%%" % p)
        except ValueError:
            pass
    return 0
MAX_RATCHET = 4
UNDO_STEPS = 10
DEFAULT_VELOCITY = 100


class Step:
    __slots__ = ("on", "vel", "chance", "ratchet", "locks")

    def __init__(self):
        self.on = False
        self.vel = DEFAULT_VELOCITY
        self.chance = 0
        self.ratchet = 1
        self.locks = {}                      # drum parameter number -> value, for this step only

    def blank(self):
        return not self.on and not self.locks and self.vel == DEFAULT_VELOCITY and not self.chance and self.ratchet == 1


def bar_steps(steps_per_beat, bar_beats):
    """Steps in one bar at this rate (bar_beats: quarter notes in a bar), or None if it isn't whole."""
    n = steps_per_beat * bar_beats
    return int(round(n)) if abs(n - round(n)) < 1e-6 and 1 <= round(n) <= MAX_STEPS else None


def group_steps(steps_per_beat, time_sig):
    """How many steps between the grey lines on the grid: one beat of the time signature at this rate
    (a quarter in x/4, a dotted quarter in 6/8, 9/8, 12/8, an eighth in 5/8, 7/8); a bar, or a quarter
    note, when a beat isn't a whole number of steps or is just one."""
    num, den = time_sig
    beat = 1.5 if (den == 8 and num % 3 == 0) else 4.0 / den
    n = steps_per_beat * beat
    if abs(n - round(n)) < 1e-6 and round(n) >= 2:
        return int(round(n))
    return bar_steps(steps_per_beat, num * 4.0 / den) or steps_per_beat


class Lane:
    def __init__(self, length=16):
        self.length = length
        self.rate = 0                        # index into RATES
        self.hits = 0                        # Euclidean fill: hits spread over the length (0: off)
        self.rotate = 0
        self.steps = [Step() for _ in range(MAX_STEPS)]

    def steps_per_beat(self):
        return RATES[self.rate][1]


class Pattern:
    def __init__(self, length=16):
        self.lanes = [Lane(length) for _ in range(LANES)]

    def empty(self):
        return not any(s.on or s.locks for lane in self.lanes for s in lane.steps)


def euclid(hits, length, rotate=0):
    """hits spread as evenly as possible over length steps, starting on the first step (then rotated)."""
    if length <= 0:
        return []
    hits = max(0, min(length, hits))
    on = [hits and (i * hits) % length < hits for i in range(length)]
    rotate %= length
    return on[-rotate:] + on[:-rotate] if rotate else on


def chance_passes(chance, loop_count):
    c = CHANCES[chance]
    if c.endswith("%"):
        p = int(c[:-1])
        return p >= 100 or random.random() * 100 < p
    a, b = (int(v) for v in c.split(":"))
    return loop_count % b == a - 1


class Sequencer:
    def __init__(self):
        self.lock = threading.RLock()
        self.bar_beats = 4.0                 # quarter notes in a bar (the song's time signature)
        self.patterns = [Pattern(self.new_length()) for _ in range(PATTERNS)]
        self.current = 0
        self.queued = None                   # the pattern to switch to at the end of this one
        self.anchor = 0.0                    # tape frame where the current pattern's step 0 falls
        self._decided = {}                   # (lane, k) -> chance result, so ratchets agree across blocks
        self._skip = set()                   # (lane, k): a step recorded live just before it came round
        self.undo_stack = []                 # (pattern number, copy of it before an edit), newest last

    @property
    def pattern(self):
        return self.patterns[self.current]

    # ------------------------------------------------------------ editing (from the screen's thread)

    def new_length(self):
        """A new lane's length: one bar of the time signature at 1/16."""
        return bar_steps(RATES[0][1], self.bar_beats) or 16

    def set_bar_beats(self, bar_beats):
        """The time signature changed: empty patterns start again at one bar of it."""
        with self.lock:
            old = self.bar_beats
            self.bar_beats = bar_beats
            if abs(old - bar_beats) < 1e-9:
                return
            for p in self.patterns:
                if p.empty():
                    for ln in p.lanes:
                        ln.length = bar_steps(ln.steps_per_beat(), bar_beats) or ln.length
                        ln.hits, ln.rotate = 0, 0

    def snapshot(self):
        """Keep the current pattern as it is, for undo (call before changing it)."""
        with self.lock:
            self.undo_stack.append((self.current, copy.deepcopy(self.pattern)))
            del self.undo_stack[:-UNDO_STEPS]

    def undo(self):
        """Put back the last change. Returns the pattern number it was in, or None if there's nothing."""
        with self.lock:
            if not self.undo_stack:
                return None
            n, pattern = self.undo_stack.pop()
            self.patterns[n] = pattern
            return n

    def live_place(self, lane, tape_frame, frames_per_beat):
        """A drum key pressed while recording: put a step on the lane's nearest step to when you pressed it.
        Returns the step number."""
        with self.lock:
            ln = self.lane(lane)
            step_frames = frames_per_beat / ln.steps_per_beat()
            k = round((tape_frame - self.anchor) / step_frames)
            i = k % ln.length
            ln.steps[i].on = True
            if self.anchor + k * step_frames > tape_frame:
                self._skip.add((lane, k))    # it's just ahead: you've played it already, don't play it twice
            return i

    def clear_all_locks(self):
        """Every step lock in every pattern goes (they belong to one drum machine's settings)."""
        with self.lock:
            for p in self.patterns:
                for ln in p.lanes:
                    for s in ln.steps:
                        s.locks = {}

    def lane(self, i):
        return self.pattern.lanes[i]

    def step(self, lane, i):
        return self.pattern.lanes[lane].steps[i]

    def toggle(self, lane, i):
        with self.lock:
            s = self.step(lane, i)
            s.on = not s.on
            return s.on

    def set_lock(self, lane, i, param, value):
        with self.lock:
            s = self.step(lane, i)
            s.locks[param] = int(value)
            s.on = True                      # locking a step plays it
            return s

    def clear_locks(self, lane, i):
        with self.lock:
            self.step(lane, i).locks.clear()

    def change_step(self, lane, i, what, delta):
        """what: "vel", "chance" or "ratchet". Returns the new value."""
        with self.lock:
            s = self.step(lane, i)
            if what == "vel":
                s.vel = max(1, min(127, s.vel + delta))
            elif what == "chance":
                s.chance = max(0, min(len(CHANCES) - 1, s.chance + (1 if delta > 0 else -1)))
            elif what == "ratchet":
                s.ratchet = max(1, min(MAX_RATCHET, s.ratchet + (1 if delta > 0 else -1)))
            s.on = True
            return getattr(s, what)

    def change_lane(self, lane, what, delta):
        """what: "length", "hits", "rotate" or "rate". Returns the new value."""
        with self.lock:
            ln = self.lane(lane)
            if what == "length":
                ln.length = max(1, min(MAX_STEPS, ln.length + delta))
                ln.hits = min(ln.hits, ln.length)
                ln.rotate %= ln.length
                if ln.hits:
                    self._fill(ln)
            elif what == "rate":
                old = ln.steps_per_beat()
                ln.rate = max(0, min(len(RATES) - 1, ln.rate + (1 if delta > 0 else -1)))
                # a lane that's a whole number of bars stays that many bars long at its new rate
                old_bar, new_bar = bar_steps(old, self.bar_beats), bar_steps(ln.steps_per_beat(), self.bar_beats)
                if old_bar and new_bar and ln.length % old_bar == 0:
                    length = ln.length // old_bar * new_bar
                    if length <= MAX_STEPS:
                        ln.length = length
                        ln.hits = min(ln.hits, ln.length)
                        ln.rotate %= ln.length
                        if ln.hits:
                            self._fill(ln)
            elif what == "hits":
                ln.hits = max(0, min(ln.length, ln.hits + (1 if delta > 0 else -1)))
                self._fill(ln)
            elif what == "rotate":
                ln.rotate = (ln.rotate + (1 if delta > 0 else -1)) % ln.length
                if ln.hits:
                    self._fill(ln)
            return getattr(ln, what)

    @staticmethod
    def _fill(ln):
        """Euclidean fill: turn the lane's steps on and off (velocities and locks stay on their steps)."""
        for i, on in enumerate(euclid(ln.hits, ln.length, ln.rotate)):
            ln.steps[i].on = bool(on)

    def choose_pattern(self, n, playing):
        """Pick pattern n: straight away when stopped, else at the end of the current one."""
        with self.lock:
            n = max(0, min(PATTERNS - 1, n))
            if not playing or n == self.current:
                self.current, self.queued = n, None
            else:
                self.queued = n

    def stop(self):
        """The tape stopped: a queued pattern takes over, and the next play starts from the tape's bars."""
        with self.lock:
            if self.queued is not None:
                self.current, self.queued = self.queued, None
            self.anchor = 0.0
            self._decided.clear()
            self._skip.clear()

    # ------------------------------------------------------------ playing (from the audio thread)

    def pattern_frames(self, frames_per_beat):
        return max(ln.length * frames_per_beat / ln.steps_per_beat() for ln in self.pattern.lanes)

    def events(self, start, frames, frames_per_beat):
        """The hits whose time falls in [start, start + frames) tape frames:
        [(offset in frames, lane, velocity, locks)], in time order."""
        out = []
        with self.lock:
            end = start + frames
            if self.queued is not None:
                length = self.pattern_frames(frames_per_beat)
                boundary = self.anchor + math.ceil((start - self.anchor) / length - 1e-9) * length
                if boundary < end:
                    out += self._events(start, boundary, start, frames_per_beat)
                    self.current, self.queued = self.queued, None
                    self.anchor = boundary
                    self._decided.clear()
                    out += self._events(boundary, end, start, frames_per_beat)
                    return out
            out += self._events(start, end, start, frames_per_beat)
            if len(self._decided) > 512:
                self._decided.clear()
        return out

    def _events(self, a, b, block_start, fpb):
        out = []
        for li, ln in enumerate(self.pattern.lanes):
            step_frames = fpb / ln.steps_per_beat()
            first = math.floor((a - self.anchor) / step_frames)
            last = math.floor((b - self.anchor) / step_frames)
            for k in range(first, last + 1):
                i = k % ln.length
                s = ln.steps[i]
                if not s.on:
                    continue
                if (li, k) in self._skip:
                    if self.anchor + k * step_frames + step_frames <= b:
                        self._skip.discard((li, k))
                    continue
                t0 = self.anchor + k * step_frames
                for r in range(s.ratchet):
                    t = t0 + r * step_frames / s.ratchet
                    if a <= t < b:
                        key = (li, k)
                        if key not in self._decided:
                            self._decided[key] = chance_passes(s.chance, k // ln.length)
                        if self._decided[key]:
                            out.append((int(t - block_start), li, s.vel, dict(s.locks)))
        out.sort(key=lambda e: e[0])
        return out

    def position(self, tape_frame, frames_per_beat):
        """Which step each lane is on at this tape frame: [step index] (for the screen)."""
        with self.lock:
            return [math.floor((tape_frame - self.anchor) / (frames_per_beat / ln.steps_per_beat())) % ln.length
                    for ln in self.pattern.lanes]

    # ------------------------------------------------------------ saving

    def to_json(self):
        with self.lock:
            pats = []
            for p in self.patterns:
                lanes = []
                for ln in p.lanes:
                    steps = {}
                    for i, s in enumerate(ln.steps):
                        if not s.blank():
                            steps[str(i)] = [int(s.on), s.vel, CHANCES[s.chance], s.ratchet, {str(k): v for k, v in s.locks.items()}]
                    lanes.append({"length": ln.length, "rate": ln.rate, "hits": ln.hits, "rotate": ln.rotate, "steps": steps})
                pats.append({"lanes": lanes})
            return {"current": self.current, "patterns": pats}

    def from_json(self, data):
        with self.lock:
            self.patterns = [Pattern(self.new_length()) for _ in range(PATTERNS)]
            self.current, self.queued, self.anchor = 0, None, 0.0
            if not isinstance(data, dict):
                return
            try:
                for p, pd in zip(self.patterns, data.get("patterns", [])):
                    for ln, ld in zip(p.lanes, pd.get("lanes", [])):
                        ln.length = max(1, min(MAX_STEPS, int(ld.get("length", 16))))
                        ln.rate = max(0, min(len(RATES) - 1, int(ld.get("rate", 0))))
                        ln.hits = max(0, min(ln.length, int(ld.get("hits", 0))))
                        ln.rotate = int(ld.get("rotate", 0)) % ln.length
                        for i, v in (ld.get("steps") or {}).items():
                            i = int(i)
                            if 0 <= i < MAX_STEPS:
                                s = ln.steps[i]
                                s.on, s.vel, s.chance, s.ratchet = bool(v[0]), int(v[1]), chance_index(v[2]), int(v[3])
                                s.ratchet = max(1, min(MAX_RATCHET, s.ratchet))
                                s.locks = {int(k): int(x) for k, x in (v[4] if len(v) > 4 else {}).items()}
                self.current = max(0, min(PATTERNS - 1, int(data.get("current", 0))))
            except (TypeError, ValueError, KeyError, IndexError, AttributeError) as e:
                print("Sequencer: couldn't read the saved patterns:", e)
