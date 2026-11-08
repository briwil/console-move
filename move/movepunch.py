"""The PUNCH FX page (left button 1 after AUTOMATION): OP-XY style punch-in effects on the instrument you're on.

Pads 1-16 (the bottom two rows) are the effects (punch.NAMES). They stack: one from each group plays at once
(TIME: pads 1-8, FILTER: 9-11, then BITCRUSH, GATE, PAN SWING, ECHO THROW, KILL each on their own); another
from the same group replaces it.

Hold pads: they play on the instrument while held (several at once: stacked); recording into the pattern
(Record, playing), they also go on the steps they were held over.

On the steps (sixteenths, as long as the pattern): hold a pad and tap steps: it goes on them (tap again: off).
Or hold a step and tap pads: each goes on it (the same pad again: off). Shift + steps: select several (they
blink), then pads put effects on all of them; tap a step without Shift to finish. Hold a step with effects:
knob 1 is its chance (for all of them). Delete + step: its effects go. Shift + Delete, twice: every punch step
in the pattern goes. < > (or the wheel): steps 17-32...
"""
import time

import knobgate
import popup
import punch
import sequencer

PADS = len(punch.NAMES)                 # pads 0-15: the effects
# each effect's pad colour, by group: time (repeats orange, the others yellow), filters, crush / gate, pan / echo, kill
COLOUR = [3, 3, 3, 3, 3, 8, 8, 8, 11, 11, 11, 15, 15, 22, 22, 127]
CONFIRM_SECONDS = 4.0


class Punch:
    def __init__(self, T):
        self.T = T
        self.held = None              # the step held down
        self.selected = []            # steps picked with Shift (they blink)
        self.page = 0
        self.pads_down = []           # the effect pads held (0-15), in the order pressed
        self.confirm_until = 0.0
        self._snapped = None

    @property
    def pad_down(self):
        """The pad pressed last of those held, or None."""
        return self.pads_down[-1] if self.pads_down else None

    # ------------------------------------------------------------ what's shown
    def active(self):
        T = self.T
        return bool(T.seq_page and not T.fx_page and getattr(T, "auto_page", False) == "punch"
                    and T.engine and T.engine.drums)

    @property
    def seq(self):
        return self.T.engine.seq

    def mid(self):
        e = self.T.engine
        return e.slots[e.slot] if e.slot is not None else None

    def steps(self):
        return punch.of(self.seq.pattern)

    def length(self):
        return punch.length(self.seq.pattern)

    def playing_step(self):
        e = self.T.engine
        if not e.playing:
            return None
        try:
            return punch.at(self.seq, e._heard_frame(), e.frames_per_beat())[1]
        except Exception:                                # noqa: BLE001
            return None

    def now(self):
        """The effects playing on this instrument now (a mask), or 0."""
        return self.T.engine.punch_now.get(self.mid(), 0)

    def held_mask(self):
        """The pads held, as a mask (one from each group: the last pressed wins it)."""
        m = 0
        for p in self.pads_down:
            m = punch.with_fx(m, p + 1)
        return m

    def targets(self):
        """The steps a pad puts its effect on: the selected ones, or the one held."""
        if self.selected:
            return list(self.selected)
        return [self.held] if self.held is not None else []

    # ------------------------------------------------------------ controls
    def _snapshot(self, why):
        if self._snapped != why:
            self.seq.snapshot()
            self._snapped = why

    def _toggle(self, steps, fx):
        """fx on these steps (taking out another of its group), or off them if they all have it. Returns
        True if it went on."""
        b = punch.bit(fx)
        with self.seq.lock:
            st = self.steps()
            off = all(st.get(i, [0])[0] & b for i in steps)
            for i in steps:
                old = st.get(i, [0, 0])
                mask = old[0] & ~b if off else punch.with_fx(old[0], fx)
                if mask:
                    st[i] = [mask, old[1]]
                else:
                    st.pop(i, None)
        self.T.engine.seq_changed()
        return not off

    def _live(self):
        """Tell the engine which pads are held now."""
        e = self.T.engine
        m = self.held_mask()
        e.punch_live = (self.mid(), m) if m else None
        if not m:
            e.punch_rec = False

    def pad(self, p, vel):
        """A pad on this page. Returns True (it's used here, never a note)."""
        e = self.T.engine
        if p >= PADS:
            return True
        fx = p + 1
        if not vel:
            if p in self.pads_down:
                self.pads_down.remove(p)
                self._live()
                self._snapped = None
            return True
        tg = [i for i in self.targets() if i < self.length()]
        if tg:                                            # steps picked: the pad puts its effect on them
            self._snapshot(("pad", tuple(tg), time.monotonic()))
            on = self._toggle(tg, fx)
            where = "STEP %d" % (tg[0] + 1) if len(tg) == 1 else "%d STEPS" % len(tg)
            popup.show(self.T, where, punch.name(fx), "ON" if on else "OFF")
            return True
        if p not in self.pads_down:                       # nothing picked: it plays while held (stacked with others)
            self.pads_down.append(p)
        self._snapped = None
        rec = bool(getattr(self.T, "live_rec", False) and e.playing)
        if rec and not e.punch_rec:
            self.seq.snapshot()
        self._live()
        e.punch_rec = rec
        return True

    def step(self, n, down, shift, deleting):
        i = self.page * 16 + n - 1
        if not down:
            if self.held == i:
                self.held = None
                self._snapped = None
            return
        if i >= self.length():
            return
        st = self.steps()
        if self.pads_down and not deleting and not shift:    # pads held: tap steps to put the last one on / off
            fx = self.pad_down + 1
            self._snapshot(("padsteps", self.pad_down))
            on = self._toggle([i], fx)
            popup.show(self.T, "STEP %d" % (i + 1), punch.name(fx), "ON" if on else "OFF")
            return
        if deleting:
            if i in st:
                self.seq.snapshot()
                with self.seq.lock:
                    st.pop(i, None)
                self.T.engine.seq_changed()
                self.T.say("STEP %d: PUNCH FX TAKEN OFF" % (i + 1), 2)
            return
        if shift:                                         # Shift + steps: pick several
            if i in self.selected:
                self.selected.remove(i)
            else:
                self.selected.append(i)
            return
        if self.selected:                                 # a step without Shift: finished picking
            self.selected = []
            return
        self.held = i
        if i in st:
            mask, ch = st[i]
            popup.show(self.T, "STEP %d" % (i + 1), punch.label(mask, short=True), "CHANCE " + sequencer.CHANCES[ch],
                       "KNOB 1")

    def knob(self, number, delta, shift):
        if number != 1 or self.held is None:
            return
        st = self.steps()
        i = self.held
        if i not in st:
            popup.show(self.T, "STEP %d" % (i + 1), "NO PUNCH FX", "TAP A PAD TO ADD ONE")
            return
        one = knobgate.gate(("punch-chance",), delta, shift)
        if not one:
            return
        self._snapshot(("chance", i))
        with self.seq.lock:
            st[i][1] = max(0, min(len(sequencer.CHANCES) - 1, st[i][1] + one))
        self.T.engine.seq_changed()
        popup.show(self.T, "STEP %d" % (i + 1), punch.label(st[i][0], short=True), "CHANCE " + sequencer.CHANCES[st[i][1]])

    def clear(self):
        """Shift + Delete: asks first; again (within a few seconds): every punch step in the pattern goes."""
        if time.monotonic() < self.confirm_until:
            n = len(self.steps())
            self.seq.snapshot()
            with self.seq.lock:
                self.steps().clear()
            self.confirm_until = 0.0
            self.T.engine.seq_changed()
            self.T.say("PUNCH FX TAKEN OFF %d STEP%s" % (n, "" if n == 1 else "S"), 2)
        else:
            self.confirm_until = time.monotonic() + CONFIRM_SECONDS

    def confirming(self):
        return time.monotonic() < self.confirm_until

    def arrows(self, way):
        pages = max(1, (self.length() + 15) // 16)
        self.page = max(0, min(pages - 1, self.page + way))

    def leave(self):
        """Off the page: nothing left held."""
        e = self.T.engine
        if e is not None and self.pads_down:
            e.punch_live, e.punch_rec = None, False
        self.pads_down, self.held, self.selected = [], None, []

    # ------------------------------------------------------------ lights
    def step_lights(self):
        st = self.steps()
        length, now = self.length(), self.playing_step()
        blink = int(time.monotonic() * 4) % 2
        out = []
        for k in range(16):
            i = self.page * 16 + k
            colour = COLOUR[punch.effects(st[i][0])[0] - 1] if i in st else 0
            if i >= length:
                out.append(0)
            elif i in self.selected:
                out.append(120 if blink else colour)
            elif i == self.held or i == now:
                out.append(120 if i in st or i == self.held else 118)
            else:
                out.append(colour)
        return out

    def pad_lights(self):
        out = [0] * 32
        lit = self.now() | self.held_mask()
        if self.held is not None:
            lit |= self.steps().get(self.held, [0])[0]
        for p in range(PADS):
            out[p] = 120 if lit & punch.bit(p + 1) else COLOUR[p]
        return out
