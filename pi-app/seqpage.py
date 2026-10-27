"""The sequencer page (the MIDI key's second press): the lanes as rows of steps, 32 at a time.

Step mode (the usual):
- Knob 1 picks the lane (up and down the rows).
- Track keys 1-8 are 8 steps of the picked lane: the ones in its box (each lane has its own box,
  steps 1-8 to start with). Pressing a key plays the lane's drum; letting go puts that step on, or
  takes it off.
- Hold a key and turn knob 1: the box moves 8 steps along the lane (letting go then doesn't
  change the step). Hold a key and turn knobs 2-9: that step's velocity, chance and ratchets, or on
  a sound page, a setting locked to it (a p-lock).
- With no key held, knobs 2-9 change the lane (length, Euclid, shift, rate) or the drum's sound.
- Push knob 1 for the next knob mode: the drum's sound pages. Knob 10 picks the pattern.

RECORD on this page is pattern recording (the tape never records here): track keys 1-8 play the
drums (SHIFT: lanes 9-16 on the 808), and while playing each press goes into the pattern on the
nearest step. RECORD again: back to step mode.
"""
import time

import pygame

import drumparams
import sequencer
import ui

VISIBLE = 32                     # steps on screen at once
BOX = 8                          # steps the track keys work on
STEP_PARAMS = ["length", "vel", "chance", "ratchet", "hits", "rotate", "rate"]       # knobs 2-8 in STEP mode
STEP_LABELS = {"length": "LENGTH", "vel": "VELOCITY", "chance": "CHANCE", "ratchet": "RATCHETS",
               "hits": "EUCLID", "rotate": "SHIFT", "rate": "RATE"}
LANE_PARAMS = ("length", "hits", "rotate", "rate")
CHANCE_SHOW = 1.0                # seconds the steps show chance after the chance knob stops turning
CHANCE_COLOUR = (242, 243, 245)
GESTURE_GAP = 1.5                # seconds: knob turns closer together than this are one undo step


class SeqPage:
    def __init__(self, transport):
        self.t = transport
        self.lane = 0                # the picked lane (knob 1)
        self.mode = 0                # 0: STEP; 1-5: the drum's sound pages
        self.box = {}                # lane -> the first step of its box (0, 8, 16...)
        self.keys = {}               # step mode: key 1-8 held -> True once a knob turned while it was held
        self.rec = False             # pattern recording: the keys play the drums
        self.held = {}               # recording: lane -> its key is held
        self._gesture = None         # (what, when): the edit being made, so one turn is one undo step
        self.placed = {}             # recording: lane -> the step a key put down while playing

    @property
    def e(self):
        return self.t.engine

    @property
    def seq(self):
        return self.t.engine.seq

    @property
    def d(self):
        return self.t.engine.drums

    def voice(self, lane=None):
        """The drum machine's voice a lane plays (its settings pages)."""
        lv = self.d.lane_voice
        return lv[min(len(lv) - 1, self.lane if lane is None else lane)]

    def short(self, lane):
        names = self.d.lane_short
        return names[lane] if lane < len(names) else "L%d" % (lane + 1)

    def shown_lanes(self):
        """The lanes on screen: up to 8, the bank of the picked lane."""
        n = self.d.lanes
        self.lane = min(self.lane, n - 1)
        first = (self.lane // 8) * 8
        return list(range(first, min(n, first + 8)))

    def pages(self):
        return self.d.pages(self.voice())

    def mode_name(self):
        return "STEP" if self.mode == 0 else self.pages()[self.mode - 1][0]

    def params(self):
        """What knobs 2-9 change in this mode."""
        if self.mode == 0:
            return STEP_PARAMS
        return self.pages()[self.mode - 1][1]

    def box_start(self, lane=None):
        """The first step of a lane's box, kept inside the lane if it got shorter."""
        lane = self.lane if lane is None else lane
        last = (max(1, self.seq.lane(lane).length) - 1) // BOX * BOX
        return min(self.box.get(lane, 0), last)

    def takes_key(self, shift):
        """True if a track key belongs to this page (called from the MIDI thread)."""
        return not shift or (self.rec and self.d.lanes > 8)

    def targets(self):
        """The steps knobs 2-9 work on: the held keys' steps, or while recording the steps just played in."""
        if self.rec:
            return [(lane, self.placed[lane]) for lane in sorted(self.held) if self.placed.get(lane) is not None]
        b = self.box_start()
        return [(self.lane, b + n - 1) for n in sorted(self.keys)]

    def first_column(self):
        """The first step on screen: the page of 32 with the picked lane's box (while recording and
        playing, the one where the picked lane is playing)."""
        at = self.box_start()
        if self.rec and self.e.playing:
            at = max(0, self.seq.position(self.e._heard_frame(), self.e.frames_per_beat())[self.lane] - 15)
            return min(sequencer.MAX_STEPS - VISIBLE, at)
        return min(sequencer.MAX_STEPS - VISIBLE, at // VISIBLE * VISIBLE)

    def _edit(self, what):
        """Before changing the pattern: one undo step per key press, or per run of turns of one knob."""
        now = time.monotonic()
        if not self._gesture or self._gesture[0] != what or now - self._gesture[1] > GESTURE_GAP:
            self.seq.snapshot()
        self._gesture = (what, now)

    def pick(self, lane):
        self.lane = lane
        self.t.drum_voice = self.voice()
        self.mode = min(self.mode, len(self.pages()))

    def leave(self):
        """Off the page: nothing held, step mode."""
        self.keys, self.held, self.placed = {}, {}, {}
        self.rec = False

    # ------------------------------------------------------------ keys and knobs

    def record_key(self):
        self.rec = not self.rec
        self.keys, self.held, self.placed = {}, {}, {}
        if self.rec:
            self.t.say("PATTERN RECORDING: THE KEYS PLAY THE DRUMS; PLAY TO RECORD THEM IN", 4)
        else:
            self.t.say("STEP MODE: THE KEYS ARE STEPS %s" % self.box_text(), 3)

    def box_text(self, lane=None):
        b = self.box_start(lane)
        return "%d-%d" % (b + 1, b + BOX)

    def lane_key(self, n, down, heard_frame=0, shift=False):
        """Track key n pressed or let go."""
        e = self.e
        if not e or not e.drums:
            return
        if self.rec:
            self._rec_key(n, down, heard_frame, shift)
            return
        if down:
            self.keys[n] = False
            return
        turned = self.keys.pop(n, None)
        if turned is None or turned:
            return
        lane = self.lane
        i = self.box_start() + n - 1
        length = self.seq.lane(lane).length
        if i >= length:
            self.t.say("STEP %d IS PAST THE END OF %s (%d STEPS)" % (i + 1, self.short(lane), length), 3)
            return
        self._edit(("toggle", time.monotonic()))
        on = self.seq.toggle(lane, i)
        e.seq_changed()
        self.t.say("%s  STEP %d %s" % (self.short(lane), i + 1, "ON" if on else "OFF"), 1)

    def _rec_key(self, n, down, heard_frame, shift):
        e = self.e
        lane = n - 1 + (8 if shift and self.d.lanes > 8 else 0)
        if lane >= self.d.lanes:
            return
        if not down:
            self.held.pop(lane, None)
            return
        self.pick(lane)
        self.held[lane] = True
        if e.playing:
            # the step goes where it's playing (the nearest step)
            self._edit(("live", time.monotonic()))
            i = self.seq.live_place(lane, heard_frame, e.frames_per_beat())
            self.placed[lane] = i
            e.seq_changed()
            self.t.say("%s  STEP %d" % (self.short(lane), i + 1), 1)

    def cycle_mode(self):
        self.mode = (self.mode + 1) % (len(self.pages()) + 1)
        self.t.say("KNOBS: %s%s" % (self.mode_name(), "" if self.mode == 0 else
                                    "  (HOLD A STEP KEY TO LOCK TO THAT STEP)"), 3)

    def undo(self):
        n = self.seq.undo()
        if n is None:
            self.t.say("NOTHING TO UNDO", 2)
            return
        self._gesture = None
        self.e.seq_changed()
        left = len(self.seq.undo_stack)
        self.t.say("UNDONE%s  (%d MORE)" % ("" if n == self.seq.current else " IN PATTERN %d" % (n + 1), left), 2)

    def _turned(self):
        """A knob turned while keys were held: letting go of them doesn't change their steps."""
        for n in self.keys:
            self.keys[n] = True

    def knob(self, number, delta, shift):
        e, seq = self.e, self.seq
        clicks = self.t.knob_clicks(number, delta, shift)
        if number == 1:
            way = 1 if delta > 0 else -1
            if self.keys and not self.rec:
                # a key held: the box moves 8 steps along the lane
                self._turned()
                last = (max(1, seq.lane(self.lane).length) - 1) // BOX * BOX
                start = max(0, min(last, self.box_start() + way * BOX))
                self.box[self.lane] = start
                self.t.say("%s  KEYS ARE STEPS %s" % (self.short(self.lane), self.box_text()), 2)
                return
            lane = max(0, min(self.d.lanes - 1, self.lane + way))
            if lane != self.lane:
                self.pick(lane)
                self.held, self.placed = {}, {}
            self.t.say("%s  ·  KEYS ARE STEPS %s" % (self.d.lane_names[self.lane], self.box_text()), 2)
            return
        if number == 10:
            target = seq.queued if seq.queued is not None else seq.current
            seq.choose_pattern(target + (1 if delta > 0 else -1), e.playing)
            e.seq_changed()
            return
        params = self.params()
        if number - 2 >= len(params):
            return
        param = params[number - 2]
        steps = self.targets()
        self._turned()
        if self.mode == 0:
            if param in LANE_PARAMS:
                lanes = sorted({l for l, _ in steps}) or [self.lane]
                self._edit((number, tuple(lanes)))
                for lane in lanes:
                    seq.change_lane(lane, param, clicks if param == "length" else delta)
                e.seq_changed()
                self.t.say("%s  %s  %s" % (self.short(lanes[-1]), STEP_LABELS[param],
                                           self.step_value(param, lanes[-1])), 2)
                return
            if not steps:
                self.t.say("HOLD A STEP KEY TO CHANGE ITS %s" % STEP_LABELS[param], 2)
                return
            self._edit((number, tuple(steps)))
            for lane, i in steps:
                if i >= seq.lane(lane).length:
                    self.t.say("STEP %d IS PAST THE END OF %s" % (i + 1, self.short(lane)), 2)
                    return
                seq.change_step(lane, i, param, clicks if param == "vel" else delta)
            e.seq_changed()
            if param == "chance":
                self._chance_until = time.monotonic() + CHANCE_SHOW   # the steps show chance for a moment
            lane, i = steps[-1]
            self.t.say("%s STEP %d  %s  %s" % (self.short(lane), i + 1, STEP_LABELS[param],
                                               self.step_value(param, lane, i)), 2)
            return
        # a sound page: locked to the held steps, or with none held the drum's own sound
        if steps:
            if not e.drums.lockable(param):
                self.t.say("%s CAN'T BE LOCKED TO A STEP" % e.drums.label(param), 3)
                return
            self._edit((number, tuple(steps), "lock"))
            for lane, i in steps:
                if i >= seq.lane(lane).length:
                    self.t.say("STEP %d IS PAST THE END OF %s" % (i + 1, self.short(lane)), 3)
                    return
                st = seq.step(lane, i)
                base = st.locks.get(param, e.drums.get_param(param))
                seq.set_lock(lane, i, param, e.drums.stepped(param, base, clicks))
            e.seq_changed()
            lane, i = steps[-1]
            v = seq.step(lane, i).locks[param]
            self.t.say("%s STEP %d  %s  %s  (LOCKED)" % (self.short(lane), i + 1, e.drums.label(param),
                                                         e.drums.value_text(param, v)), 2)
            return
        e.change_drum(param, clicks)
        self.t.say("%s  %s  %s" % (self.short(self.lane), e.drums.label(param), e.drums.value_text(param)), 2)

    # ------------------------------------------------------------ values for the screen

    def step_value(self, param, lane=None, i=None):
        lane = self.lane if lane is None else lane
        ln = self.seq.lane(lane)
        if param == "length":
            return str(ln.length)
        if param == "hits":
            return "OFF" if not ln.hits else "%d/%d" % (ln.hits, ln.length)
        if param == "rotate":
            return str(ln.rotate)
        if param == "rate":
            return sequencer.RATES[ln.rate][0]
        if i is None:
            steps = [st for l, st in self.targets() if l == lane]
            if not steps:
                return "-"
            i = steps[-1]
        if i >= ln.length:
            return "-"
        st = ln.steps[i]
        if param == "vel":
            return str(st.vel)
        if param == "chance":
            return sequencer.CHANCES[st.chance]
        return "x%d" % st.ratchet

    def knob_boxes(self):
        """[(label, value, locked)] for knobs 1-9, then 10 and the big knob."""
        e = self.e
        steps = self.targets()
        if self.keys and not self.rec:
            boxes = [("BOX (TURN)", "STEPS " + self.box_text(), False)]
        else:
            boxes = [("LANE", self.short(self.lane), False)]
        params = self.params()
        st = None
        if steps:
            lane, i = steps[-1]
            ln = self.seq.lane(lane)
            if i < ln.length:
                st = ln.steps[i]
        for i in range(8):
            if i >= len(params):
                boxes.append(("", "", False))
                continue
            p = params[i]
            if self.mode == 0:
                boxes.append((STEP_LABELS[p], self.step_value(p), False))
            elif st is not None and p in st.locks:
                boxes.append((e.drums.label(p), e.drums.value_text(p, st.locks[p]), True))
            else:
                boxes.append((e.drums.label(p), e.drums.value_text(p), False))
        pat = "%d" % (self.seq.current + 1) + (" > %d" % (self.seq.queued + 1) if self.seq.queued is not None else "")
        boxes.append(("PATTERN", pat, False))
        boxes.append(("BIG KNOB", "TAPE", False))
        return boxes

    # ------------------------------------------------------------ drawing

    def draw(self, surf):
        s, e, seq = self.t.s, self.e, self.seq
        tiny, small, mid = s.font("mono", 600, 11), s.font("mono", 600, 14), s.font("mono", 700, 15)
        grey, white, dark, purple = (125, 131, 140), (242, 243, 245), (12, 13, 16), (178, 120, 255)
        green, cursor_col = (60, 203, 127), (28, 78, 86)
        surf.set_clip(None)
        pygame.draw.rect(surf, (12, 13, 16), (0, 36, 1280, 330))
        # what each knob does, with its value (green: locked to the held step)
        x, w, gap = 20, 108, 4
        for n, (label, value, locked) in enumerate(self.knob_boxes()):
            pygame.draw.rect(surf, (60, 64, 72) if label else (26, 28, 33), (x, 40, w, 38), 1, border_radius=4)
            if label:
                t = tiny.render(label, True, grey)
                surf.blit(t, (x + (w - t.get_width()) // 2, 44))
                v = small.render(value, True, green if locked else white)
                surf.blit(v, (x + (w - v.get_width()) // 2, 58))
            x += w + gap
        ln = seq.lane(self.lane)
        if self.rec:
            info = "KEYS PLAY THE DRUMS%s   ·   PLAY TO RECORD THEM IN   ·   RECORD: BACK TO STEPS" % (
                "  (SHIFT: 9-16)" if self.d.lanes > 8 else "")
        else:
            info = "KEYS: %s STEPS %s  (HOLD A KEY + KNOB 1 TO MOVE)" % (self.short(self.lane), self.box_text())
        info += "   ·   KNOBS: %s (PUSH KNOB 1)   ·   %d STEPS  %s   ·   %s   ·   SHIFT+CUT: UNDO" % (
            self.mode_name(), ln.length, sequencer.RATES[ln.rate][0], self.d.title)
        x = 20
        if self.rec:
            pygame.draw.circle(surf, (230, 60, 60), (x + 6, 90), 6)
            t = tiny.render("PATTERN REC", True, (230, 60, 60))
            surf.blit(t, (x + 16, 84))
            x += 16 + t.get_width() + 14
        surf.blit(tiny.render(info, True, grey), (x, 84))
        # the grid
        first = self.first_column()
        x0, pitch, cw = 72, 35, 28
        shown = self.shown_lanes()
        top, row_h = 102, (35 if len(shown) <= 7 else 31)
        ch = row_h - 6
        col_x = lambda c: x0 + c * pitch
        grid_bottom = top + len(shown) * row_h
        sig = tuple(e.time_sig)
        groups = {l: sequencer.group_steps(seq.lane(l).steps_per_beat(), sig) for l in shown}
        playing = None
        if e.playing:
            playing = seq.position(e._heard_frame(), e.frames_per_beat())
        now = time.monotonic()
        show_chance = now < getattr(self, "_chance_until", 0.0)
        for row, lane in enumerate(shown):
            y = top + row * row_h
            colour = ui.rgb(self.t.tab_colours.get(lane % 8 + 1) or "#7D838C")
            dim = tuple(round(c * 0.75) for c in colour)
            # the drum's tag, lit for a moment when it plays
            hit = max(self.t._drum_hits[self.voice(lane)],
                      e.seq_hits[lane] if e.seq_hits[lane] <= now else 0.0)
            glow = max(0.0, 1.0 - (now - hit) / 0.2)
            tag = tuple(round(c + (255 - c) * glow * 0.6) for c in colour)
            pygame.draw.rect(surf, tag, (20, y, 42, ch), border_radius=5)
            t = small.render(self.short(lane), True, dark)
            surf.blit(t, (20 + (42 - t.get_width()) // 2, y + (ch - t.get_height()) // 2))
            if lane == self.lane:
                pygame.draw.rect(surf, (70, 75, 84), (14, y - 4, col_x(VISIBLE - 1) + cw + 6 - 14, ch + 8), 1,
                                 border_radius=7)
            # the lane's box: the 8 steps the keys work on (bright on the picked lane)
            b = self.box_start(lane)
            c0, c1 = max(b, first), min(b + BOX, first + VISIBLE, seq.lane(lane).length)
            if c0 < c1 and not self.rec:
                bx = col_x(c0 - first)
                rect = (bx - 3, y - 3, col_x(c1 - first) - bx + 6 - (pitch - cw), ch + 6)
                pygame.draw.rect(surf, cursor_col if lane == self.lane else (30, 44, 48), rect, border_radius=6)
                if lane == self.lane:
                    pygame.draw.rect(surf, (96, 196, 210), rect, 2, border_radius=6)
            lane_steps = seq.lane(lane)
            # a grey line between the lane's beats: every 4 steps at 1/16, 3 at 1/8T, by its time signature
            for c in range(1, VISIBLE):
                if (first + c) % groups[lane] == 0 and first + c < lane_steps.length:
                    gx = col_x(c) - (pitch - cw + 1) // 2 - 1
                    pygame.draw.line(surf, (88, 94, 104), (gx, y - 2), (gx, y + ch + 1), 2)
            for c in range(VISIBLE):
                i = first + c
                x = col_x(c)
                st = lane_steps.steps[i]
                if i >= lane_steps.length:
                    pygame.draw.rect(surf, (32, 34, 40), (x, y, cw, ch), 1, border_radius=5)
                    continue
                if st.on:
                    # filled from the bottom by its velocity (or, just after turning the chance knob, its chance)
                    c = sequencer.CHANCES[st.chance]
                    if show_chance and ":" in c:
                        t = tiny.render(c, True, CHANCE_COLOUR)
                        surf.blit(t, (x + (cw - t.get_width()) // 2, y + (ch - t.get_height()) // 2))
                    else:
                        frac = int(c[:-1]) / 100 if show_chance else st.vel / 127
                        h = max(2, round(ch * frac))
                        pygame.draw.rect(surf, CHANCE_COLOUR if show_chance else colour, (x, y + ch - h, cw, h),
                                         border_bottom_left_radius=5, border_bottom_right_radius=5,
                                         border_top_left_radius=5 if h >= ch - 1 else 0,
                                         border_top_right_radius=5 if h >= ch - 1 else 0)
                    if not st.locks:
                        pygame.draw.rect(surf, colour, (x, y, cw, ch), 2, border_radius=5)
                if st.locks:
                    pygame.draw.rect(surf, purple, (x, y, cw, ch), 3, border_radius=5)
                elif not st.on:
                    pygame.draw.rect(surf, dim, (x, y, cw, ch), 1, border_radius=5)
                if playing is not None and playing[lane] == i:
                    pygame.draw.rect(surf, white, (x - 2, y - 2, cw + 4, ch + 4), 2, border_radius=6)
        # step numbers along the bottom, every 4
        g = groups[self.lane]                                   # numbered by the picked lane's beats
        for c in range(VISIBLE):
            if (first + c) % g == 0:
                t = tiny.render(str(first + c + 1), True, grey)
                surf.blit(t, (col_x(c), grid_bottom - 3))
