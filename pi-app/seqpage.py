"""The sequencer page (the MIDI key's second press): the 7 lanes as rows of steps, 32 at a time.

- Knob 1 moves the step cursor (the highlighted column), 1 to 64. It moves along to the 16th column,
  then the steps scroll under it, until step 64 comes on screen and it moves on to the end (and the
  same going back).
- Track keys 1-7 are the drums: press and let go to put a step at the cursor, or take it off. Each one
  plays its sound as you press it. While recording, a press puts the step where it's playing instead,
  on the nearest step.
- Hold a track key and turn knobs 2-9 to change that lane: in STEP mode its length, the velocity,
  chance and ratchets of the step under the cursor, its Euclidean fill and shift, and its rate.
- Push knob 1 for the next mode: the drum's sound pages. There, holding a track key locks the
  setting to the step under the cursor (a parameter lock); with no key held, the knobs change the
  drum's own sound.
- Track key 8 undoes (10 steps). Knob 10 picks the pattern.
"""
import time

import pygame

import drumparams
import sequencer
import ui

VISIBLE = 32                     # steps on screen at once
FOLLOW_AT = 15                   # the cursor's column (from 0) while the steps scroll under it
STEP_PARAMS = ["length", "vel", "chance", "ratchet", "hits", "rotate", "rate"]       # knobs 2-8 in STEP mode
STEP_LABELS = {"length": "LENGTH", "vel": "VELOCITY", "chance": "CHANCE", "ratchet": "RATCHETS",
               "hits": "EUCLID", "rotate": "SHIFT", "rate": "RATE"}
LANE_PARAMS = ("length", "hits", "rotate", "rate")
SHORT = ["D1", "D2", "D3", "SN", "CY", "HHc", "HHo"]
GESTURE_GAP = 1.5                # seconds: knob turns closer together than this are one undo step


class SeqPage:
    def __init__(self, transport):
        self.t = transport
        self.cursor = 0
        self.lane = 0                # the lane picked last (its sound pages are the modes)
        self.mode = 0                # 0: STEP; 1-5: the drum's sound pages
        self.held = {}               # lane -> True once a knob turned while it was held (no toggle on release)
        self._gesture = None         # (what, when): the edit being made, so one turn is one undo step

    @property
    def e(self):
        return self.t.engine

    @property
    def seq(self):
        return self.t.engine.seq

    def voice(self, lane=None):
        return sequencer.LANE_VOICE[self.lane if lane is None else lane]

    def pages(self):
        return drumparams.PAGES[self.voice()]

    def mode_name(self):
        return "STEP" if self.mode == 0 else self.pages()[self.mode - 1][0]

    def params(self):
        """What knobs 2-9 change in this mode."""
        if self.mode == 0:
            return STEP_PARAMS
        return self.pages()[self.mode - 1][1]

    def first_column(self):
        return max(0, min(sequencer.MAX_STEPS - VISIBLE, self.cursor - FOLLOW_AT))

    def _edit(self, what):
        """Before changing the pattern: one undo step per key press, or per run of turns of one knob."""
        now = time.monotonic()
        if not self._gesture or self._gesture[0] != what or now - self._gesture[1] > GESTURE_GAP:
            self.seq.snapshot()
        self._gesture = (what, now)

    # ------------------------------------------------------------ keys and knobs

    def lane_key(self, n, down, heard_frame=0):
        lane = n - 1
        e = self.e
        if not e or not e.drums:
            return
        if down:
            self.lane = lane
            self.t.drum_voice = self.voice()
            self.mode = min(self.mode, len(self.pages()))
            self.held[lane] = False
            if e.playing and e.recording:
                self._edit(("live", time.monotonic()))
                i = self.seq.live_place(lane, heard_frame, e.frames_per_beat())
                self.held[lane] = True                     # placed already: letting go doesn't toggle
                e.seq_changed()
                self.t.say("%s  STEP %d" % (SHORT[lane], i + 1), 1)
            return
        turned = self.held.pop(lane, None)
        if turned is None or turned:
            return
        length = self.seq.lane(lane).length
        if self.cursor >= length:
            self.t.say("STEP %d IS PAST THE END OF %s (%d STEPS)" % (self.cursor + 1, SHORT[lane], length), 3)
            return
        self._edit(("toggle", time.monotonic()))
        on = self.seq.toggle(lane, self.cursor)
        e.seq_changed()
        self.t.say("%s  STEP %d %s" % (SHORT[lane], self.cursor + 1, "ON" if on else "OFF"), 1)

    def cycle_mode(self):
        self.mode = (self.mode + 1) % (len(self.pages()) + 1)
        self.t.say("KNOBS: %s%s" % (self.mode_name(), "" if self.mode == 0 else
                                    "  (HOLD A DRUM KEY TO LOCK TO THE STEP)"), 3)

    def undo(self):
        n = self.seq.undo()
        if n is None:
            self.t.say("NOTHING TO UNDO", 2)
            return
        self._gesture = None
        self.e.seq_changed()
        left = len(self.seq.undo_stack)
        self.t.say("UNDONE%s  (%d MORE)" % ("" if n == self.seq.current else " IN PATTERN %d" % (n + 1), left), 2)

    def knob(self, number, delta, shift):
        e, seq = self.e, self.seq
        clicks = self.t.knob_clicks(number, delta, shift)
        if number == 1:
            self.cursor = max(0, min(sequencer.MAX_STEPS - 1, self.cursor + clicks))
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
        lanes = sorted(self.held)
        if self.mode == 0:
            if not lanes:
                self.t.say("HOLD A DRUM KEY (1-7) AND TURN TO SET ITS %s" % STEP_LABELS[param], 3)
                return
            self._edit((number, tuple(lanes)))
            for lane in lanes:
                self.held[lane] = True
                if param in LANE_PARAMS:
                    seq.change_lane(lane, param, clicks if param == "length" else delta)
                elif self.cursor < seq.lane(lane).length:
                    seq.change_step(lane, self.cursor, param, clicks if param == "vel" else delta)
            e.seq_changed()
            lane = lanes[-1]
            self.t.say("%s  %s  %s" % (SHORT[lane], STEP_LABELS[param], self.step_value(param, lane)), 2)
            return
        # a sound page: lock it to the step under the cursor while a drum key is held, else the drum's sound
        if self.lane in self.held:
            lane = self.lane
            if not e.drums.lockable(param):
                self.t.say("%s CAN'T BE LOCKED TO A STEP" % drumparams.LABELS[param], 3)
                return
            if self.cursor >= seq.lane(lane).length:
                self.t.say("STEP %d IS PAST THE END OF %s" % (self.cursor + 1, SHORT[lane]), 3)
                return
            self._edit((number, lane, "lock"))
            self.held[lane] = True
            st = seq.step(lane, self.cursor)
            base = st.locks.get(param, e.drums.get_param(param))
            seq.set_lock(lane, self.cursor, param, e.drums.stepped(param, base, clicks))
            e.seq_changed()
            v = seq.step(lane, self.cursor).locks[param]
            self.t.say("%s STEP %d  %s  %s  (LOCKED)" % (SHORT[lane], self.cursor + 1, drumparams.LABELS[param],
                                                         e.drums.value_text(param, v)), 2)
            return
        e.change_drum(param, clicks)
        self.t.say("%s  %s  %s" % (SHORT[self.lane], drumparams.LABELS[param], e.drums.value_text(param)), 2)

    # ------------------------------------------------------------ values for the screen

    def step_value(self, param, lane=None):
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
        if self.cursor >= ln.length:
            return "-"
        st = ln.steps[self.cursor]
        if param == "vel":
            return str(st.vel)
        if param == "chance":
            return sequencer.CHANCES[st.chance]
        return "x%d" % st.ratchet

    def knob_boxes(self):
        """[(label, value, locked)] for knobs 1-9, then 10 and the big knob."""
        e = self.e
        boxes = [("CURSOR", "STEP %d" % (self.cursor + 1), False)]
        params = self.params()
        st = None
        ln = self.seq.lane(self.lane)
        if self.cursor < ln.length:
            st = ln.steps[self.cursor]
        for i in range(8):
            if i >= len(params):
                boxes.append(("", "", False))
                continue
            p = params[i]
            if self.mode == 0:
                boxes.append((STEP_LABELS[p], self.step_value(p), False))
            elif st is not None and p in st.locks:
                boxes.append((drumparams.LABELS[p], e.drums.value_text(p, st.locks[p]), True))
            else:
                boxes.append((drumparams.LABELS[p], e.drums.value_text(p), False))
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
        # what each knob does, with its value (green: locked to the step under the cursor)
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
        info = "KNOBS: %s  (PUSH KNOB 1)   ·   %s  %d STEPS  %s   ·   KEY 8: UNDO" % (
            self.mode_name(), SHORT[self.lane], ln.length, sequencer.RATES[ln.rate][0])
        surf.blit(tiny.render(info, True, grey), (20, 84))
        # the grid
        first = self.first_column()
        x0, pitch, group, cw = 72, 34, 4, 29
        top, row_h, ch = 102, 35, 29
        # groups of 4 steps (a beat at 1/16) with a gap and a line between them, by step number
        col_x = lambda c: x0 + c * pitch + ((first + c) // 4 - first // 4) * group
        grid_bottom = top + sequencer.LANES * row_h
        for c in range(1, VISIBLE):
            if (first + c) % 4 == 0:
                gx = col_x(c) - 3 - group // 2
                pygame.draw.line(surf, (50, 54, 62), (gx, top - 4), (gx, grid_bottom - 4), 1)
        cx = col_x(self.cursor - first)
        pygame.draw.rect(surf, cursor_col, (cx - 3, top - 6, cw + 6, sequencer.LANES * row_h + 4), border_radius=5)
        playing = None
        if e.playing:
            playing = seq.position(e._heard_frame(), e.frames_per_beat())
        now = time.monotonic()
        for lane in range(sequencer.LANES):
            y = top + lane * row_h
            colour = ui.rgb(self.t.tab_colours.get(lane + 1) or "#7D838C")
            dim = tuple(round(c * 0.75) for c in colour)
            # the drum's tag, lit for a moment when it plays
            hit = max(self.t._drum_hits[self.voice(lane)] if lane < 6 else 0.0,
                      e.seq_hits[lane] if e.seq_hits[lane] <= now else 0.0)
            glow = max(0.0, 1.0 - (now - hit) / 0.2)
            tag = tuple(round(c + (255 - c) * glow * 0.6) for c in colour)
            pygame.draw.rect(surf, tag, (20, y, 42, ch), border_radius=5)
            t = small.render(SHORT[lane], True, dark)
            surf.blit(t, (20 + (42 - t.get_width()) // 2, y + (ch - t.get_height()) // 2))
            if lane == self.lane:
                pygame.draw.rect(surf, white, (14, y - 4, col_x(VISIBLE - 1) + cw + 6 - 14, ch + 8), 2, border_radius=7)
            lane_steps = seq.lane(lane)
            for c in range(VISIBLE):
                i = first + c
                x = col_x(c)
                st = lane_steps.steps[i]
                if i >= lane_steps.length:
                    pygame.draw.rect(surf, (32, 34, 40), (x, y, cw, ch), 1, border_radius=5)
                    continue
                if st.on:
                    pygame.draw.rect(surf, colour, (x, y, cw, ch), border_radius=5)
                if st.locks:
                    pygame.draw.rect(surf, purple, (x, y, cw, ch), 3, border_radius=5)
                elif not st.on:
                    pygame.draw.rect(surf, dim, (x, y, cw, ch), 1, border_radius=5)
                if playing is not None and playing[lane] == i:
                    pygame.draw.rect(surf, white, (x - 2, y - 2, cw + 4, ch + 4), 2, border_radius=6)
        # step numbers along the bottom, every 4
        for c in range(VISIBLE):
            if (first + c) % 4 == 0:
                t = tiny.render(str(first + c + 1), True, grey)
                surf.blit(t, (col_x(c), grid_bottom - 3))
