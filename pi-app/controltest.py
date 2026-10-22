"""Control board test: shows every key, knob turn and knob push from the control board.

Run it on the Pi with ./test-controls.sh. Each control lights up green while you use it and
stays marked once it has worked, so you can go round the board and see what's left.
Keyboard: R clears the marks, Q or Escape quits.
"""
import argparse
import os
import queue
import time

os.environ.setdefault("SDL_AUDIODRIVER", "dummy")   # pygame mustn't open a sound device: the audio engine owns them
import pygame

import midi
import ui
from console import BOARD_KEYS, PUSHES

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = ui.WIDTH, ui.HEIGHT

BG = (12, 13, 16)
PANEL = (23, 25, 30)
EDGE = (45, 48, 56)
DIM = (125, 131, 140)
TEXT = (242, 243, 245)
GREEN = (60, 203, 127)
DONE = (34, 86, 64)
AMBER = (255, 181, 71)
RED = (255, 92, 92)

KNOB_NAMES = ["TRACK %d" % n for n in range(1, 9)] + ["ENC9", "ENC10", "ENC11"]


def font(size, weight=500, face="mono"):
    weights = ui.FONT_FILES[face]
    path = os.path.join(ui.FONT_DIR, weights[min(weights, key=lambda w: abs(w - weight))])
    return pygame.font.Font(path if os.path.isfile(path) else None, size)


class State:
    def __init__(self):
        self.clear()
        self.last = "Nothing received yet"
        self.last_time = 0.0
        self.unknown = 0

    def clear(self):
        self.keys_down = set()          # notes 0-23 held now
        self.keys_ok = set()
        self.push_down = set()          # knob numbers 1-11 held now
        self.push_ok = set()
        self.knob_value = [0] * 12      # running count per knob (index 1-11)
        self.knob_flash = [0.0] * 12    # time of the last turn
        self.knob_dir = [0] * 12
        self.knob_left = set()
        self.knob_right = set()

    def control(self, kind, number, value):
        now = time.monotonic()
        if kind == "note" and 0 <= number < 24:
            name = "SW%d %s" % (number + 1, BOARD_KEYS[number])
            if value:
                self.keys_down.add(number)
                self.keys_ok.add(number)
            else:
                self.keys_down.discard(number)
            self.last = "%s  %s" % (name, "pressed" if value else "let go")
        elif kind == "note" and 32 <= number <= 42:
            k = number - 31
            if value:
                self.push_down.add(k)
                self.push_ok.add(k)
            else:
                self.push_down.discard(k)
            self.last = "ENC%d push (%s)  %s" % (k, PUSHES[k - 1], "pressed" if value else "let go")
        elif kind == "cc" and 1 <= number <= 11:
            d = value - 64
            if not d:
                return
            self.knob_value[number] += d
            self.knob_flash[number] = now
            self.knob_dir[number] = 1 if d > 0 else -1
            (self.knob_right if d > 0 else self.knob_left).add(number)
            self.last = "ENC%d turned %s %d  (total %+d)" % (number, "right" if d > 0 else "left", abs(d),
                                                             self.knob_value[number])
        else:
            self.unknown += 1
            self.last = "Unexpected message: %s %d %d" % (kind, number, value)
        self.last_time = now


def draw_key(surf, f_big, f_small, rect, label, sub, down, ok):
    colour = GREEN if down else (DONE if ok else PANEL)
    pygame.draw.rect(surf, colour, rect, border_radius=8)
    pygame.draw.rect(surf, GREEN if ok else EDGE, rect, 2, border_radius=8)
    t = f_big.render(label, True, BG if down else TEXT)
    surf.blit(t, t.get_rect(center=(rect.centerx, rect.centery - 9)))
    s = f_small.render(sub, True, BG if down else DIM)
    surf.blit(s, s.get_rect(center=(rect.centerx, rect.centery + 13)))


def draw_knob(surf, fonts, cx, cy, k, st, now):
    f_big, f_small, f_tiny = fonts
    r = 30
    pushed = k in st.push_down
    turned = now - st.knob_flash[k] < 0.25
    pygame.draw.circle(surf, GREEN if pushed else PANEL, (cx, cy), r)
    both = k in st.knob_left and k in st.knob_right
    pygame.draw.circle(surf, GREEN if both else (AMBER if (k in st.knob_left or k in st.knob_right) else EDGE),
                       (cx, cy), r, 3)
    if turned:
        pygame.draw.circle(surf, AMBER, (cx, cy), r + 6, 3)
    t = f_big.render("%+d" % st.knob_value[k] if st.knob_value[k] else "0", True, BG if pushed else TEXT)
    surf.blit(t, t.get_rect(center=(cx, cy)))
    surf.blit(*_centred(f_small, "ENC%d" % k, TEXT, cx, cy - r - 14))
    marks = "%s %s %s" % ("L" if k in st.knob_left else "-", "R" if k in st.knob_right else "-",
                          "P" if k in st.push_ok else "-")
    surf.blit(*_centred(f_tiny, marks, GREEN if (both and k in st.push_ok) else DIM, cx, cy + r + 13))
    surf.blit(*_centred(f_tiny, KNOB_NAMES[k - 1], DIM, cx, cy + r + 29))


def _centred(f, text, colour, cx, cy):
    t = f.render(text, True, colour)
    return t, t.get_rect(center=(cx, cy))


def draw(surf, st, ctl, fonts, now):
    f_title, f_key, f_sub, f_knob, f_tiny, f_status = fonts
    surf.fill(BG)

    # header
    surf.blit(f_title.render("CONTROL BOARD TEST", True, TEXT), (24, 14))
    if ctl is not None and ctl.connected:
        status, colour = "Board connected (%s)" % ctl.connected, GREEN
    else:
        status, colour = "Board not found: is it plugged in, with the firmware on it?", RED
    s = f_status.render(status, True, colour)
    surf.blit(s, (W - 24 - s.get_width(), 18))

    # 4x4 key grid, SW1-SW16
    kw, kh, gap = 112, 52, 8
    x0, y0 = 24, 56
    for n in range(16):
        r, c = divmod(n, 4)
        rect = pygame.Rect(x0 + c * (kw + gap), y0 + r * (kh + gap), kw, kh)
        draw_key(surf, f_key, f_sub, rect, "SW%d" % (n + 1), BOARD_KEYS[n], n in st.keys_down, n in st.keys_ok)

    # track keys, SW17-SW24
    tx0 = 520
    tw = (W - tx0 - 24 - 7 * gap) // 8
    for i in range(8):
        n = 16 + i
        rect = pygame.Rect(tx0 + i * (tw + gap), y0 + 3 * (kh + gap), tw, kh)
        draw_key(surf, f_key, f_sub, rect, "SW%d" % (n + 1), "TRACK %d" % (i + 1), n in st.keys_down, n in st.keys_ok)

    # knobs, ENC1-ENC11
    kx0, kx1 = tx0 + 34, W - 24 - 34
    for k in range(1, 12):
        cx = round(kx0 + (kx1 - kx0) * (k - 1) / 10)
        draw_knob(surf, (f_knob, f_sub, f_tiny), cx, 118, k, st, now)

    # progress + last message
    knobs_ok = sum(1 for k in range(1, 12) if k in st.knob_left and k in st.knob_right)
    summary = "Keys %d/24    Knob turns (both ways) %d/11    Knob pushes %d/11" % (
        len(st.keys_ok), knobs_ok, len(st.push_ok))
    all_done = len(st.keys_ok) == 24 and knobs_ok == 11 and len(st.push_ok) == 11
    surf.blit(f_status.render(summary + ("    ALL WORKING" if all_done else ""), True,
                              GREEN if all_done else TEXT), (24, y0 + 4 * (kh + gap) + 18))
    age = now - st.last_time
    surf.blit(f_status.render("Last: " + st.last, True, AMBER if st.last_time and age < 1 else DIM),
              (24, y0 + 4 * (kh + gap) + 46))
    hint = f_sub.render("Green = working.  Knobs: L/R = turned left/right, P = pushed.  R clears, Q quits.", True, DIM)
    surf.blit(hint, (W - 24 - hint.get_width(), H - 26))


def main():
    ap = argparse.ArgumentParser(description="Control board test")
    ap.add_argument("--window", action="store_true", help="open a window instead of full screen")
    ap.add_argument("--rotate", type=int, default=int(os.environ.get("CONSOLE_ROTATE", "270")))
    args = ap.parse_args()

    pygame.display.init()                   # not pygame.init(): that would grab the Pi's default sound device
    pygame.font.init()
    if args.window:
        display = pygame.display.set_mode((W, H))
    else:
        display = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
    pygame.display.set_caption("Control board test")
    dw, dh = display.get_size()
    rotate = args.rotate if dh > dw else 0

    st = State()
    events = queue.Queue()
    ctl = midi.Source(lambda cards: next((i for i, cid, desc in cards if midi.is_controller(cid, desc)), None),
                      lambda status, d1, d2: events.put((status, d1, d2)), label="Controls")
    ctl.start()

    fonts = (font(22, 600), font(17, 600, "sans"), font(12), font(18, 600), font(12), font(16))
    frame = pygame.Surface((W, H))
    clock = pygame.time.Clock()
    print("Control board test: press every key, turn every knob both ways and push it. Q quits.")
    running = True
    while running:
        clock.tick(60)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_q, pygame.K_ESCAPE):
                    running = False
                elif ev.key == pygame.K_r:
                    st.clear()
        while not events.empty():
            status, d1, d2 = events.get()
            kind = status & 0xF0
            if kind == 0x90:
                st.control("note", d1, 1 if d2 else 0)
            elif kind == 0x80:
                st.control("note", d1, 0)
            elif kind == 0xB0:
                st.control("cc", d1, d2)
        draw(frame, st, ctl, fonts, time.monotonic())
        out = pygame.transform.rotate(frame, rotate) if rotate else frame
        if out.get_size() != (dw, dh):
            scale = min(dw / out.get_width(), dh / out.get_height())
            out = pygame.transform.smoothscale(out, (round(out.get_width() * scale), round(out.get_height() * scale)))
            display.fill((0, 0, 0))
        display.blit(out, ((dw - out.get_width()) // 2, (dh - out.get_height()) // 2))
        pygame.display.flip()
    ctl.stopped = True
    pygame.quit()


if __name__ == "__main__":
    main()
