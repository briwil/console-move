"""The drum sequencer the Move's way: the 16 step buttons are the steps, the knobs set the lane (or, while a
step button is held, that step), and the screen shows what the knobs do.

  pads (bottom rows)     pick the lane (and play its drum)
  step buttons 1-16      press and let go: the step on / off. Hold one: the knobs set that step
  <- / ->                the lane's steps 1-16, 17-32, 33-48, 49-64
  knobs (no step held)   1 LENGTH, 2 RATE (length scale), 3 EUCLID, 4 SHIFT
  knobs (step held)      page STEP: 1 VELOCITY, 2 CHANCE, 3 RATCHETS; the drum's sound pages: its settings,
                         locked to that step. + / - change the page while the step is held
  + / - (no step held)   the pattern
It works through the Pi app's own SeqPage (T.seqp), so the pattern, undo and saving are the same.
"""
import time

import seqpage

PAGE = 16                                          # step buttons
LANE_KNOBS = ["length", "rate", "hits", "rotate"]  # knobs 1-4, no step held
STEP_KNOBS = ["vel", "chance", "ratchet"]          # knobs 1-3, a step held, page STEP
LABELS = dict(seqpage.STEP_LABELS, rate="RATE", hits="EUCLID", rotate="SHIFT")


class MoveSeq:
    def __init__(self, T):
        self.T = T
        self.page = {}             # lane -> which 16 steps the buttons show (0-3)
        self.held = None           # the step being held (index in the lane), or None
        self.turned = False        # a knob turned while it was held (then letting go doesn't toggle)
        self.knob_page = 0         # while a step is held: 0 STEP, 1.. the drum's sound pages

    # ------------------------------------------------------------ what's shown

    @property
    def sp(self):
        return self.T.seqp

    @property
    def seq(self):
        return self.T.engine.seq

    def active(self):
        T = self.T
        return bool(T.seq_page and not T.synth_shown() and T.engine and T.engine.drums)

    def first(self):
        lane = self.sp.lane
        length = self.seq.lane(lane).length
        last = (max(1, length) - 1) // PAGE
        p = min(self.page.get(lane, 0), last)
        return p * PAGE

    def sound_pages(self):
        return self.sp.pages()

    def page_name(self):
        if self.knob_page == 0:
            return "STEP"
        return self.sound_pages()[self.knob_page - 1][0]

    def knob_list(self):
        """[(label, value, locked)] for knobs 1-8 as they are now."""
        sp, e = self.sp, self.T.engine
        lane = sp.lane
        if self.held is None:
            return [(LABELS[p], sp.step_value(p, lane), False) for p in LANE_KNOBS]
        self._aim()
        if self.knob_page == 0:
            return [(LABELS[p], sp.step_value(p, lane), False) for p in STEP_KNOBS]
        st = self.seq.step(lane, self.held)
        out = []
        for p in self.sound_pages()[self.knob_page - 1][1][:8]:
            if p in st.locks:
                out.append((e.drums.label(p), e.drums.value_text(p, st.locks[p]), True))
            else:
                out.append((e.drums.label(p), e.drums.value_text(p), False))
        return out

    def playing_step(self):
        e = self.T.engine
        if not e.playing:
            return None
        try:
            return self.seq.position(e._heard_frame(), e.frames_per_beat())[self.sp.lane]
        except Exception:
            return None

    # ------------------------------------------------------------ controls

    def _aim(self):
        """Point the Pi's SeqPage at the held step: its cursor there (shown, so it's used while playing)."""
        sp = self.sp
        sp.cursor = self.held
        sp._cursor_until = time.monotonic() + 2.0

    def pick_lane(self, lane):
        sp = self.sp
        if lane >= sp.d.lanes or self.held is not None:
            return
        sp.lane = lane
        self.T.drum_voice = sp.voice()
        self.knob_page = 0

    def step(self, n, down):
        """Step button n (1-16) pressed or let go."""
        i = self.first() + n - 1
        lane = self.sp.lane
        length = self.seq.lane(lane).length
        if down:
            if self.held is None:
                self.held, self.turned, self.knob_page = i, False, 0
            elif i < length:                                  # another step while holding: on / off now
                self._toggle(lane, i)
            return
        if i != self.held:
            return
        if not self.turned:
            if i < length:
                self._toggle(lane, i)
            else:
                self.T.say("STEP %d IS PAST THE END (LENGTH %d: KNOB 1)" % (i + 1, length), 2)
        self.held, self.knob_page = None, 0

    def _toggle(self, lane, i):
        sp = self.sp
        sp._edit(("toggle", time.monotonic()))
        sp.seq.toggle(lane, i)
        self.T.engine.seq_changed()

    def knob(self, number, delta, shift):
        """Knobs 1-8."""
        sp = self.sp
        if self.held is None:
            if number > len(LANE_KNOBS):
                return
            sp.mode, sp.held = 0, {}
            sp.knob(2 + seqpage.STEP_PARAMS.index(LANE_KNOBS[number - 1]), delta, shift)
            return
        self.turned = True
        self._aim()
        if self.knob_page == 0:
            if number > len(STEP_KNOBS):
                return
            sp.mode = 0
            knob = 2 + seqpage.STEP_PARAMS.index(STEP_KNOBS[number - 1])
        else:
            sp.mode = self.knob_page
            knob = number + 1
        sp.held = {sp.lane: True}
        try:
            sp.knob(knob, delta, shift)
        finally:
            sp.held = {}
            sp.mode = 0

    def plus_minus(self, way):
        """+ / -: the knob page while a step is held, else the pattern."""
        if self.held is not None:
            n = len(self.sound_pages()) + 1
            self.knob_page = (self.knob_page + way) % n
            self.turned = True
            self.T.say("KNOBS: %s  (STEP %d)" % (self.page_name(), self.held + 1), 2)
        else:
            self.sp.knob(10, way, False)

    def arrows(self, way):
        """<- / ->: the lane's next or previous 16 steps."""
        lane = self.sp.lane
        length = self.seq.lane(lane).length
        last = (max(1, length) - 1) // PAGE
        p = max(0, min(last, self.first() // PAGE + way))
        self.page[lane] = p
        self.T.say("STEPS %d-%d OF %d" % (p * PAGE + 1, p * PAGE + PAGE, length), 2)

    # ------------------------------------------------------------ lights

    def step_lights(self):
        """16 light values for the step buttons."""
        lane = self.sp.lane
        ln = self.seq.lane(lane)
        first = self.first()
        at = self.playing_step()
        out = []
        for k in range(PAGE):
            i = first + k
            if i >= ln.length:
                v = 0
            elif i == self.held:
                v = 127
            else:
                on = ln.steps[i].on
                v = 127 if on else 0
                if at is not None and i == at:
                    v = 20 if on else 60                  # the playhead: on steps dim, off steps glow
            out.append(v)
        return out
