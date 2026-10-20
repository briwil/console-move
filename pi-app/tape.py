"""The tape: 8 tracks of audio laid out along a timeline, drawn OP-1 style.

The playhead stays in the middle of the screen and the tape moves past it.
Bar, beat and grid lines are drawn across the lanes, with bar numbers on the
ruler above them.

There's no real audio yet. Each track holds a made-up level for every 1/64
note, and recording writes new made-up levels at the playhead, so the screen
behaves the way it will once the audio engine exists.
"""
import math
import random

import numpy as np
import pygame

import ui

RES = 16                    # level values per beat (one per 1/64 note)
TAPE_BARS = 64
BEATS_PER_BAR = 4
TAPE_BEATS = TAPE_BARS * BEATS_PER_BAR

GRIDS = [("1/4", 1), ("1/8", 2), ("1/16", 4), ("1/32", 8)]     # name, lines per beat
ZOOMS = [16, 8, 4, 2, 1]                                       # bars across the screen

BAR_LINE = (58, 63, 72)
BEAT_LINE = (38, 42, 49)
GRID_LINE = (29, 32, 38)
BEFORE_START = (14, 15, 18)
RULER_TEXT = (125, 131, 140)
RULER_NOW = (242, 243, 245)
LOOP_FILL = (30, 36, 52)
LOOP_FILL_OFF = (24, 26, 31)
LOOP_MARK = (79, 140, 255)
LOOP_MARK_OFF = (70, 76, 88)
PIECE_FILL = (40, 44, 54)          # the piece under the playhead on the armed track: what LIFT / CUT would take
SELECT_FILL = (52, 66, 98)         # while selecting several pieces
SPLICE = (226, 229, 235)

# how much of each sample track has something on it, in bars
SAMPLE_FILL = [64, 48, 40, 64, 12, 56, 32, 0]


def sample_track(name, bars):
    """Made-up levels for a track, using the same kind of random envelope as the designer."""
    r = ui._rng(ui._hash(name))
    out = [0.0] * (TAPE_BEATS * RES)
    env, target, run = 0.0, 0.0, 0
    for i in range(min(len(out), bars * BEATS_PER_BAR * RES)):
        if run <= 0:
            on = r() > .28
            run = 10 + math.floor(r() * 60)
            target = .35 + r() * .65 if on else 0
        run -= 1
        env += (target - env) * .18
        out[i] = max(env * (.45 + r() * .55), .04)
    return out


class Tape:
    def __init__(self, screen, engine=None):
        self.s = screen
        self.engine = engine
        if engine:
            self.levels = engine.levels          # real recordings: peak level per 1/64 note
        else:
            self.levels = [np.array(sample_track("track%d" % (n + 1), SAMPLE_FILL[n]), np.float32) for n in range(8)]
        self.pos = 0.0                  # playhead position in beats from the start of the tape
        self.grid = 2                   # index into GRIDS (1/16)
        self.zoom = 2                   # index into ZOOMS (4 bars)
        self._rec_env = 0.0
        self._rec_target = 0.0
        self._rec_run = 0
        lane = screen.get("track1_wave") or {"x": 66, "w": 1128}
        self.center = lane["x"] + lane["w"] // 2
        screen.set("playhead", x1=self.center, x2=self.center)
        for n in range(1, 9):
            screen.custom["track%d_lane" % n] = self.draw_lane
            screen.custom["track%d_wave" % n] = self.draw_wave
        screen.custom["ruler"] = self.draw_ruler

    # ------------------------------------------------------------ settings

    @property
    def total_beats(self):
        return self.engine.tape_beats if self.engine else TAPE_BEATS

    @property
    def ppb(self):
        """Pixels per beat at the current zoom."""
        lane = self.s.get("track1_wave")
        width = lane["w"] if lane else 1128
        return width / (ZOOMS[self.zoom] * BEATS_PER_BAR)

    @property
    def step(self):
        """One grid step, in beats."""
        return 1 / GRIDS[self.grid][1]

    def label(self):
        bars = ZOOMS[self.zoom]
        return "GRID %s   %d BAR%s" % (GRIDS[self.grid][0], bars, "" if bars == 1 else "S")

    def cycle_grid(self):
        self.grid = (self.grid + 1) % len(GRIDS)

    def zoom_in(self):
        self.zoom = min(len(ZOOMS) - 1, self.zoom + 1)

    def zoom_out(self):
        self.zoom = max(0, self.zoom - 1)

    def move(self, steps, size):
        """Move by whole steps of `size` beats, landing on the nearest line."""
        n = math.floor(self.pos / size + 1e-3) + steps
        if steps < 0 and abs(self.pos / size - round(self.pos / size)) > 1e-3:
            n += 1          # first step back only goes to the line just behind
        self.pos = min(max(0.0, n * size), self.total_beats)

    # ------------------------------------------------------------ recording (made-up input for now)

    def record(self, track, from_beat, to_beat):
        lv = self.levels[track - 1]
        i0 = max(0, int(from_beat * RES))
        i1 = min(len(lv), int(to_beat * RES))
        for i in range(i0, i1):
            if self._rec_run <= 0:
                self._rec_target = .4 + random.random() * .6 if random.random() > .2 else 0
                self._rec_run = 8 + random.randint(0, 40)
            self._rec_run -= 1
            self._rec_env += (self._rec_target - self._rec_env) * .2
            lv[i] = max(self._rec_env * (.5 + random.random() * .5), .04)

    def level_at(self, track, beat):
        if beat < 0 or beat >= self.total_beats:
            return 0.0
        return self.shape(float(self.levels[track - 1][int(beat * RES)]))

    def shape(self, a):
        """Real audio peaks look tiny drawn as-is; a square root makes quiet parts visible."""
        return min(1.0, math.sqrt(a)) if self.engine else a

    # ------------------------------------------------------------ drawing

    def x_of(self, beat):
        return self.center + (beat - self.pos) * self.ppb

    def beat_of(self, x):
        return self.pos + (x - self.center) / self.ppb

    def lines(self, x0, x1):
        """(x, kind) for every line between x0 and x1; kind is 'bar', 'beat' or 'grid'."""
        ppb = self.ppb
        step = self.step if self.step * ppb >= 5 else 1 if ppb >= 5 else BEATS_PER_BAR
        b0 = max(0.0, self.beat_of(x0))
        b1 = min(float(self.total_beats), self.beat_of(x1))
        k = math.ceil(b0 / step - 1e-9)
        while k * step <= b1 + 1e-9:
            beat = k * step
            if abs(beat - round(beat)) < 1e-9:
                kind = "bar" if round(beat) % BEATS_PER_BAR == 0 else "beat"
            else:
                kind = "grid"
            yield round(self.x_of(beat)), kind
            k += 1

    def draw_lane(self, surf, it):
        self.s.draw_default(surf, it)
        x0, y0, w, h = it["x"], it["y"], it["w"], it["h"]
        clip = surf.get_clip()
        surf.set_clip(pygame.Rect(x0, y0, w, h))
        start = round(self.x_of(0))
        if start > x0:
            pygame.draw.rect(surf, BEFORE_START, (x0, y0, start - x0, h), 0, it.get("r", 0))
        loop = self.loop_x()
        if loop:
            lx0, lx1 = max(x0, loop[0]), min(x0 + w, loop[1])
            if lx1 > lx0:
                pygame.draw.rect(surf, LOOP_FILL if loop[2] else LOOP_FILL_OFF, (lx0, y0, lx1 - lx0, h))
        sel = self.selection_x(it)
        if sel:
            sx0, sx1, selecting = sel
            sx0, sx1 = max(x0, sx0), min(x0 + w, sx1)
            if sx1 > sx0:
                pygame.draw.rect(surf, SELECT_FILL if selecting else PIECE_FILL, (sx0, y0, sx1 - sx0, h))
        colours = {"bar": BAR_LINE, "beat": BEAT_LINE, "grid": GRID_LINE}
        for x, kind in self.lines(x0, x0 + w):
            pygame.draw.line(surf, colours[kind], (x, y0 + 2), (x, y0 + h - 3), 1)
        surf.set_clip(clip)

    def draw_wave(self, surf, it):
        track = int(it["name"][5:it["name"].index("_")])
        lv = self.levels[track - 1]
        col = ui.rgb(it["c"])
        cy = it["y"] + it["h"] / 2
        ppb = self.ppb
        span = max(1, int(3 / ppb * RES))          # level values covered by one 3-pixel column
        for px in range(it["x"], it["x"] + it["w"] - 1, 3):
            beat = self.beat_of(px + 1)
            if beat < 0 or beat >= self.total_beats:
                continue
            i = int(beat * RES)
            a = float(lv[i:i + span].max()) if span > 1 else float(lv[i])
            if a <= 0.0003:
                continue
            a = self.shape(a)
            bh = max(1, round(a * (it["h"] - 2)))
            surf.fill(col, (px, round(cy - bh / 2), 2, bh))
        self.draw_splices(surf, it, track)

    def draw_splices(self, surf, it, track):
        """A splice: a white line across the lane with a small notch at the top and bottom, like cut tape."""
        e = self.engine
        if not e:
            return
        fpb = e.frames_per_beat()
        lane = self.s.get("track%d_lane" % track) or it
        y0, y1 = lane["y"], lane["y"] + lane["h"] - 1
        for f in e.splices[track - 1]:
            x = round(self.x_of(f / fpb))
            if it["x"] - 4 <= x <= it["x"] + it["w"] + 4:
                pygame.draw.line(surf, SPLICE, (x, y0 + 1), (x, y1 - 1), 1)
                pygame.draw.polygon(surf, SPLICE, [(x - 3, y0), (x + 3, y0), (x, y0 + 4)])
                pygame.draw.polygon(surf, SPLICE, [(x - 3, y1), (x + 3, y1), (x, y1 - 4)])

    def draw_ruler(self, surf, it):
        self.s.draw_default(surf, it)
        font = self.s.font("mono", 500, 11)
        ppb = self.ppb
        bar_px = ppb * BEATS_PER_BAR
        every = 1 if bar_px >= 36 else 2 if bar_px >= 18 else 4
        now_bar = int(self.pos // BEATS_PER_BAR)
        y_bottom = it["y"] + it["h"]
        for x, kind in self.lines(it["x"], it["x"] + it["w"]):
            if kind == "bar":
                bar = round(self.beat_of(x) / BEATS_PER_BAR)
                pygame.draw.line(surf, BAR_LINE, (x, y_bottom - 5), (x, y_bottom - 1), 1)
                if bar % every == 0 and bar < self.total_beats / BEATS_PER_BAR:
                    col = RULER_NOW if bar == now_bar else RULER_TEXT
                    img = font.render(str(bar + 1), True, col)
                    if x + 3 + img.get_width() <= it["x"] + it["w"]:
                        surf.blit(img, (x + 3, it["y"]))
            elif kind == "beat":
                pygame.draw.line(surf, BEAT_LINE, (x, y_bottom - 3), (x, y_bottom - 1), 1)
        loop = self.loop_x()
        if loop:
            col = LOOP_MARK if loop[2] else LOOP_MARK_OFF
            lx0, lx1 = max(it["x"], loop[0]), min(it["x"] + it["w"], loop[1])
            if lx1 > lx0:
                pygame.draw.rect(surf, col, (lx0, y_bottom - 3, lx1 - lx0, 3))
            for x in (loop[0], loop[1]):
                if it["x"] <= x <= it["x"] + it["w"]:
                    pygame.draw.line(surf, col, (x, it["y"]), (x, y_bottom - 1), 2)

    def selection_x(self, it):
        """(x start, x end, selecting) of the selected piece(s) when `it` is the armed track's lane, or None."""
        e = self.engine
        if not e or it["name"] != "track%d_lane" % e.armed or e.recording:
            return None
        sel = e.selection()
        if not sel:
            return None
        fpb = e.frames_per_beat()
        return round(self.x_of(sel[1] / fpb)), round(self.x_of(sel[2] / fpb)), e.sel_anchor is not None

    def loop_x(self):
        """(x start, x end, on) of the loop on screen, or None."""
        e = self.engine
        if not e or not e.loop_region():
            return None
        fpb = e.frames_per_beat()
        return round(self.x_of(e.loop_a / fpb)), round(self.x_of(e.loop_b / fpb)), e.loop_on
