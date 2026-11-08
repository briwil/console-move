"""The PUNCH FX page (left button 1 after AUTOMATION): OP-XY style punch-in effects on the instrument you're on.

Pads 1-16 (the bottom two rows) are the effects (punch.NAMES). Hold one: it plays on the instrument while you
hold it; recording into the pattern (Record, playing), it also goes on the steps it was held over.

On the steps (sixteenths, as long as the pattern): hold a step and tap a pad: that effect goes on it (the same
pad again: off). Shift + steps: select several (they blink), then a pad puts the effect on all of them; tap a
step without Shift to finish. Hold a step with an effect: knob 1 is its chance. Delete + step: its effect goes.
Shift + Delete, twice: every punch step in the pattern goes. < > (or the wheel): steps 17-32...
"""
import time

import knobgate
import popup
import punch
import sequencer

PADS = len(punch.NAMES)                 # pads 0-15: the effects
# each effect's pad colour, by kind: repeats, time, filters, colour, space, kill
GROUP = [3, 3, 3, 3, 3, 8, 8, 8, 11, 11, 11, 15, 15, 22, 22, 127]
CONFIRM_SECONDS = 4.0


class Punch:
    def __init__(self, T):
        self.T = T
        self.held = None              # the step held down
        self.selected = []            # steps picked with Shift (they blink)
        self.page = 0
        self.pad_down = None          # the effect pad held (0-15)
        self.confirm_until = 0.0
        self._snapped = None

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
        """The effect playing on this instrument now (1-16), or 0."""
        return self.T.engine.punch_now.get(self.mid(), 0)

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

    def pad(self, p, vel):
        """A pad on this page. Returns True (it's used here, never a note)."""
        e = self.T.engine
        if p >= PADS:
            return True
        fx = p + 1
        if not vel:
            if self.pad_down == p:
                self.pad_down = None
                e.punch_live, e.punch_rec = None, False
                self._snapped = None
            return True
        tg = [i for i in self.targets() if i < self.length()]
        if tg:                                            # steps picked: the pad puts its effect on them
            seq = self.seq
            self._snapshot(("pad", tuple(tg), time.monotonic()))
            with seq.lock:
                st = self.steps()
                off = all(st.get(i, [0])[0] == fx for i in tg)
                for i in tg:
                    if off:
                        st.pop(i, None)
                    else:
                        st[i] = [fx, st[i][1] if i in st else 0]
            e.seq_changed()
            where = "STEP %d" % (tg[0] + 1) if len(tg) == 1 else "%d STEPS" % len(tg)
            popup.show(self.T, where, punch.name(fx), "OFF" if off else "ON")
            return True
        self.pad_down = p                                 # nothing picked: play it while it's held
        rec = bool(getattr(self.T, "live_rec", False) and e.playing)
        if rec:
            self.seq.snapshot()
        e.punch_live, e.punch_rec = (self.mid(), fx), rec
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
            fx, ch = st[i]
            popup.show(self.T, "STEP %d" % (i + 1), punch.name(fx), "CHANCE " + sequencer.CHANCES[ch], "KNOB 1")

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
        popup.show(self.T, "STEP %d" % (i + 1), punch.name(st[i][0]), "CHANCE " + sequencer.CHANCES[st[i][1]])

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
        if e is not None and self.pad_down is not None:
            e.punch_live, e.punch_rec = None, False
        self.pad_down, self.held, self.selected = None, None, []

    # ------------------------------------------------------------ lights
    def step_lights(self):
        st = self.steps()
        length, now = self.length(), self.playing_step()
        blink = int(time.monotonic() * 4) % 2
        out = []
        for k in range(16):
            i = self.page * 16 + k
            if i >= length:
                out.append(0)
            elif i in self.selected:
                out.append(120 if blink else (GROUP[st[i][0] - 1] if i in st else 0))
            elif i == self.held or i == now:
                out.append(120 if i in st or i == self.held else 118)
            else:
                out.append(GROUP[st[i][0] - 1] if i in st else 0)
        return out

    def pad_lights(self):
        out = [0] * 32
        now = self.now()
        st = self.steps()
        on_step = st.get(self.held, [0])[0] if self.held is not None else 0
        for p in range(PADS):
            fx = p + 1
            out[p] = 120 if (p == self.pad_down or fx == now or fx == on_step) else GROUP[p]
        return out
