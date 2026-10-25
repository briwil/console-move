"""The drum page (the MIDI key), full screen, to Brian's design (Illustrator, Oct 2026):

- the voice's name at the top left, the BPM and the 7 drum keys (the last one played lit) at the top right;
- the settings on the page left to right, one per knob 1-8, over a purple grid:
  - a number is a row of thin lines that are tallest at the setting's value and shrink away from it;
  - a choice (a wave, a filter type, a target...) is a box with its name in it;
  - the setting being turned is lime, with its value in place of its name, until a second after it stops;
- the voice's pages along the bottom (knob 9 turns them), the one showing in red;
- while recording, three red dots under the pages, one filled, stepping left to right.
"""
import math
import time

import pygame

import drumparams

YELLOW = (241, 193, 47)
PURPLE = (131, 89, 225)
LIME = (205, 224, 90)
GRID = (50, 34, 94)
RULE = (104, 104, 104)
RED = (236, 36, 38)
GREY_TEXT = (89, 90, 90)
KEY_OFF = (53, 53, 53)
CYAN = (0, 174, 239)

LEFT, RIGHT = 26, 1247                 # the edges of the rules, grid and pages
PANEL = (76, 115, 1142, 160)           # the black panel the settings sit on
MID_Y = 170                            # the middle of the bars
LINES, PITCH, TALLEST, SHORTEST = 21, 5, 84, 4      # each bar: 21 lines 5 px apart (100 px wide)
FALLOFF = 4.2                          # lines from the value for the height to drop to about a third
EDIT_SHOW = 1.0                        # seconds a setting stays lime after its knob stops
TEXT_KINDS = ("menu", "onoff", "voice", "vel_target", "lfo_target")


def short_page(name):
    return name.replace("PITCH + VELOCITY", "PITCH+VEL").replace("VELOCITY + CLICK", "VEL+CLICK").replace(" + ", "+")


class DrumPage:
    def __init__(self, transport):
        self.t = transport
        self.edited = {}               # knob number -> when it was last turned
        self._page_size = None

    def font(self, weight, size):
        return self.t.s.font("outfit", weight, size)

    def text(self, surf, s, weight, size, colour, x, baseline, align="left", tracking=0.0, fit=None):
        """Text placed by its baseline. tracking: extra space between letters, in ems (Brian's titles are
        a touch tight). fit: a width it must fit in (it gets smaller until it does)."""
        f = self.font(weight, size)
        while fit and size > 10 and self.width(f, s, size, tracking) > fit:
            size -= 1
            f = self.font(weight, size)
        w = self.width(f, s, size, tracking)
        x = x - w if align == "right" else x - w // 2 if align == "centre" else x
        top = baseline - f.get_ascent()
        if not tracking:
            surf.blit(f.render(s, True, colour), (x, top))
            return w
        for i, ch in enumerate(s):
            cx = x + f.size(s[:i])[0] + round(i * tracking * size)
            surf.blit(f.render(ch, True, colour), (cx, top))
        return w

    @staticmethod
    def width(f, s, size, tracking=0.0):
        return f.size(s)[0] + round((len(s) - 1) * tracking * size) if s else 0

    # ------------------------------------------------------------ drawing

    def draw(self, surf):
        t, e = self.t, self.t.engine
        d = e.drums
        surf.set_clip(None)
        surf.fill((0, 0, 0))
        now = time.monotonic()
        voice = t.drum_voice
        pages = t.drum_pages()
        t.drum_tab = min(t.drum_tab, len(pages) - 1)
        _, params = pages[t.drum_tab]

        # top: the voice, the tempo and the 7 drum keys
        names = __import__("drums").NAMES
        self.text(surf, names[voice], 900, 40, YELLOW, 22, 45, tracking=-0.02)
        sig = "%d/%d" % tuple(e.time_sig) if getattr(e, "time_sig", None) else "4/4"
        self.text(surf, "%.1f BPM %s" % (e.bpm, sig), 300, 14, CYAN, RIGHT, 21, align="right")
        key = getattr(t, "drum_key", voice + 1)
        for k in range(7):
            v = min(k, 5)
            glow = max(0.0, 1.0 - (now - t._drum_hits[v]) / 0.25) if (k < 6 or key == 7) else 0.0
            base = YELLOW if k + 1 == key else KEY_OFF
            colour = tuple(round(c + (255 - c) * glow * 0.7) for c in base)
            pygame.draw.rect(surf, colour, (1077 + k * 25, 30, 20, 20), border_radius=5)

        # the rules and the grid, with the black panel on it
        pygame.draw.rect(surf, RULE, (LEFT, 57, RIGHT - LEFT, 2))
        pygame.draw.rect(surf, RULE, (LEFT, 328, RIGHT - LEFT, 2))
        for k in range(26):
            pygame.draw.rect(surf, GRID, (LEFT - 1, 67 + 10 * k, RIGHT - LEFT + 1, 2))
        for k in range(123):
            pygame.draw.rect(surf, GRID, (LEFT - 1 + 10 * k, 67, 1, 252))
        pygame.draw.rect(surf, (0, 0, 0), PANEL, border_radius=9)

        # the settings, left to right like the knobs
        n = max(1, len(params))
        px, _, pw, _ = PANEL
        for i, param in enumerate(params):
            cx = round(px + (i + 0.5) * pw / n)
            editing = now - self.edited.get(i + 1, 0.0) < EDIT_SHOW
            colour = LIME if editing else PURPLE
            kind = drumparams.KINDS.get(param, ("num",))[0]
            if kind in TEXT_KINDS:
                pygame.draw.rect(surf, colour, (cx - 44, MID_Y - 44, 88, 88), 9, border_radius=12)
                self.text(surf, d.value_text(param), 500, 22, colour, cx, MID_Y + 8, align="centre", fit=66)
            else:
                self.bar(surf, cx, d.fraction(param), colour)
            label = d.value_text(param) if editing else drumparams.LABELS[param]
            self.text(surf, label, 900, 18, colour, cx, 258, align="centre", fit=pw / n - 8)

        # the pages along the bottom, spread edge to edge
        size = self.page_size()
        labels = [short_page(p[0]) for p in pages]
        f = self.font(900, size)
        widths = [self.width(f, s, size, -0.02) for s in labels]
        gap = (RIGHT - LEFT - sum(widths)) / max(1, len(labels) - 1)
        x = LEFT
        for i, s in enumerate(labels):
            self.text(surf, s, 900, size, RED if i == t.drum_tab else GREY_TEXT, round(x), 361, tracking=-0.02)
            x += widths[i] + gap
        self.text(surf, "KNOB 9: PAGE", 600, 14, YELLOW, RIGHT, 386, align="right")

        # recording: three dots stepping left to right
        if t.recording:
            lit = int(now / 0.3) % 3
            for k in range(3):
                c = (624 + k * 16, 381)
                pygame.draw.circle(surf, RED, c, 6, 0 if k == lit else 2)

    def bar(self, surf, cx, frac, colour):
        """Thin lines, tallest at the value, shrinking with distance from it."""
        peak = max(0.0, min(1.0, frac)) * (LINES - 1)
        x0 = cx - (LINES - 1) * PITCH // 2 - 1
        for k in range(LINES):
            h = max(SHORTEST, TALLEST * math.exp(-abs(k - peak) / FALLOFF))
            h = int(round(h / 2)) * 2                     # even, so it sits on whole pixels around the middle
            pygame.draw.rect(surf, colour, (x0 + k * PITCH, MID_Y - h // 2, 2, h))

    def page_size(self):
        """One size for the page names on every voice: the biggest (up to 30) that fits the longest set."""
        if self._page_size is None:
            size = 30
            for pages in drumparams.PAGES:
                labels = [short_page(p[0]) for p in pages]
                while size > 14:
                    f = self.font(900, size)
                    if sum(self.width(f, s, size, -0.02) for s in labels) + 24 * (len(labels) - 1) <= RIGHT - LEFT:
                        break
                    size -= 1
            self._page_size = size
        return self._page_size
