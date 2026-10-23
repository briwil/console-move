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

PIN_CHECK_ON = bytes((0xB0 | 13, 127, 127))      # see firmware/code.py
PIN_CHECK_OFF = bytes((0xB0 | 13, 127, 0))


def terminal_chars(q):
    """Letters typed in the SSH window, onto the queue."""
    import sys
    import threading
    if not sys.stdin.isatty():
        return None
    import termios
    import tty
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    def reader():
        while True:
            try:
                data = os.read(fd, 16).decode(errors="ignore")
            except OSError:
                return
            if not data:
                return
            for ch in data:
                q.put(ch.lower())

    threading.Thread(target=reader, daemon=True).start()
    return lambda: termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def tell_board(ctl, message):
    """Send a MIDI message to the control board. False if it isn't connected."""
    if ctl is None or not ctl.connected:
        return False
    try:
        fd = os.open(ctl.connected, os.O_WRONLY | os.O_NONBLOCK)
        try:
            os.write(fd, message)
        finally:
            os.close(fd)
        return True
    except OSError as e:
        print("Couldn't send to the board:", e)
        return False


def toggle_pin_check(st, ctl):
    if st.pin_mode:
        tell_board(ctl, PIN_CHECK_OFF)                 # the board restarts as a normal controller
        st.clear()
        st.last = "Pin check off: the board is restarting"
    elif tell_board(ctl, PIN_CHECK_ON):
        st.last = "Asked the board for the pin check (needs the new code.py on it)"
    else:
        st.last = "Board not connected"
    st.last_time = time.monotonic()

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
# pin check: knob (by position, 1-11) -> its two wires as numbered by the firmware (0 = GP14 ... 21 = GP35).
# The 10th knob is the one labelled ENC11 on the board (GP34/35), the 11th is ENC10 (GP32/33).
KNOB_WIRES = {k: (2 * (k - 1), 2 * (k - 1) + 1) for k in range(1, 10)}
KNOB_WIRES[10] = (20, 21)
KNOB_WIRES[11] = (18, 19)


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
        self.wire = [None] * 22         # pin check: each wire's level (True = high)
        self.wire_changes = [0] * 22
        self.differ = set()             # knobs whose two wires have stayed at different levels for a moment
        self.differ_since = {}          # knob -> when its wires last became different
        self.pin_mode = False

    def wire_level(self, i, high):
        if self.wire[i] is not None and self.wire[i] != high:
            self.wire_changes[i] += 1
        self.wire[i] = high
        self.pin_mode = True
        for k, (a, b) in KNOB_WIRES.items():
            if i in (a, b):
                apart = self.wire[a] is not None and self.wire[b] is not None and self.wire[a] != self.wire[b]
                if apart:
                    self.differ_since.setdefault(k, time.monotonic())
                else:
                    self.differ_since.pop(k, None)

    def tick(self, now):
        """Wires that are joined together still arrive one message apart; only a difference that lasts counts."""
        for k, since in list(self.differ_since.items()):
            if now - since > 0.012:
                self.differ.add(k)

    def verdict(self, k):
        """(text, colour) for one knob in the pin check."""
        a, b = KNOB_WIRES[k]
        ca, cb = self.wire_changes[a], self.wire_changes[b]
        if self.wire[a] is None or self.wire[b] is None:
            return "NO DATA", DIM
        if ca == 0 and cb == 0:
            low = [n for n, w in (("A", a), ("B", b)) if not self.wire[w]]
            return ("%s STUCK LOW?" % "+".join(low), AMBER) if low else ("TURN IT", DIM)
        if ca and not cb:
            return ("B DEAD" + (" (LOW)" if not self.wire[b] else ""), RED)
        if cb and not ca:
            return ("A DEAD" + (" (LOW)" if not self.wire[a] else ""), RED)
        if k not in self.differ:
            return ("A+B JOINED", RED) if ca + cb > 6 else ("KEEP TURNING", DIM)
        return "OK", GREEN

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


def draw_pins(surf, st, ctl, fonts):
    """The pin check: each knob's two turning wires, live, and what they say about the soldering."""
    f_title, f_key, f_sub, f_knob, f_tiny, f_status = fonts
    surf.fill(BG)
    surf.blit(f_title.render("PIN CHECK: KNOB WIRES", True, TEXT), (24, 14))
    s = f_status.render("Turn each knob slowly, a few clicks each way.  P goes back to the normal test.", True, DIM)
    surf.blit(s, (24, 48))
    w = (W - 48) // 11
    for k in range(1, 12):
        x = 24 + (k - 1) * w
        cx = x + w // 2
        surf.blit(*_centred(f_knob, "KNOB %d" % k, TEXT, cx, 104))
        a, b = KNOB_WIRES[k]
        for row, (name, wi) in enumerate((("A", a), ("B", b))):
            y = 150 + row * 64
            level = st.wire[wi]
            colour = EDGE if level is None else (GREEN if level else AMBER)
            pygame.draw.circle(surf, colour, (cx - 22, y), 14)
            surf.blit(*_centred(f_key, name, BG if level is not None else TEXT, cx - 22, y))
            info = "-" if level is None else ("HIGH" if level else "LOW")
            surf.blit(*_centred(f_tiny, info, DIM, cx + 22, y - 8))
            surf.blit(*_centred(f_tiny, "%d" % st.wire_changes[wi], DIM, cx + 22, y + 8))
            surf.blit(*_centred(f_tiny, "GP%d" % (14 + wi), DIM, cx - 22, y + 26))
        text, colour = st.verdict(k)
        surf.blit(*_centred(f_sub, text, colour, cx, 300))
    hint = f_status.render("A healthy knob: both wires flick between HIGH and LOW as you turn, not always together.", True, DIM)
    surf.blit(hint, (24, H - 36))


def draw(surf, st, ctl, fonts, now):
    f_title, f_key, f_sub, f_knob, f_tiny, f_status = fonts
    if st.pin_mode:
        draw_pins(surf, st, ctl, fonts)
        return
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
    hint = f_sub.render("Green = working.  Knobs: L/R = turned left/right, P = pushed.  R clears, Q quits, P: pin check.", True, DIM)
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
    print("Control board test: press every key, turn every knob both ways and push it.")
    print("Here: Q quits, R clears the marks, P switches the knob pin check on and off.")
    typed = queue.Queue()
    restore = terminal_chars(typed)             # Q, R and P from the SSH window too
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
                elif ev.key == pygame.K_p:
                    toggle_pin_check(st, ctl)
        while not typed.empty():
            ch = typed.get()
            if ch in ("q", "\x1b"):
                running = False
            elif ch == "r":
                st.clear()
            elif ch == "p":
                toggle_pin_check(st, ctl)
        while not events.empty():
            status, d1, d2 = events.get()
            kind = status & 0xF0
            if kind == 0xB0 and (status & 0x0F) == 13 and d1 < 22:
                st.wire_level(d1, d2 >= 64)              # pin check (board plugged in holding SW1)
            elif kind == 0x90:
                st.control("note", d1, 1 if d2 else 0)
            elif kind == 0x80:
                st.control("note", d1, 0)
            elif kind == 0xB0:
                st.control("cc", d1, d2)
        st.tick(time.monotonic())
        draw(frame, st, ctl, fonts, time.monotonic())
        out = pygame.transform.rotate(frame, rotate) if rotate else frame
        if out.get_size() != (dw, dh):
            scale = min(dw / out.get_width(), dh / out.get_height())
            out = pygame.transform.smoothscale(out, (round(out.get_width() * scale), round(out.get_height() * scale)))
            display.fill((0, 0, 0))
        display.blit(out, ((dw - out.get_width()) // 2, (dh - out.get_height()) // 2))
        pygame.display.flip()
    ctl.stopped = True
    if restore:
        restore()
    pygame.quit()


if __name__ == "__main__":
    main()
