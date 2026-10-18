#!/usr/bin/env python3
"""Console: the Pi app (version 0.2).

Shows the screen layout from layouts/main.ui full screen, with an OP-1 style
tape: the playhead stays in the middle and the tape moves past it, with bar,
beat and grid lines. There's no audio yet: play, record and the track keys only
change the screen.

Keys (a keyboard plugged into the Pi, or typed into an SSH terminal running the app):
    1-8          arm a track for recording
    Space        play / stop
    R            record on / off (also starts playing)
    Left/Right   move back / forward one grid step
    [ / ]        move back / forward one bar (also Shift+Left/Right)
    G            change the grid: 1/4, 1/8, 1/16, 1/32
    + / -        zoom in / out (16, 8, 4, 2 or 1 bars across the screen)
    Q            quit (ignored when Console runs as the boot app)

Options:
    --window     open a 1280x400 window instead of full screen (for testing on a laptop)
    --rotate N   turn the picture by N degrees (90 or 270) when the screen is upright
                 and the system isn't rotating it; the default is 270
"""
import argparse
import os
import queue
import sys
import threading

import pygame

import tape
import ui

HERE = os.path.dirname(os.path.abspath(__file__))
FPS = 30
BPM = 120.0


# ---------------------------------------------------------------- keys from an SSH terminal

def start_terminal_keys(q):
    """Read single key presses from the terminal (when run over SSH) and put names on the queue."""
    if not sys.stdin.isatty() or os.environ.get("CONSOLE_NO_TERMINAL_KEYS"):
        return None
    import termios
    import tty
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    def reader():
        names = {" ": "PLAY", "r": "RECORD", "R": "RECORD", "q": "QUIT", "Q": "QUIT",
                 "g": "GRID", "G": "GRID", "+": "ZOOM_IN", "=": "ZOOM_IN", "-": "ZOOM_OUT", "_": "ZOOM_OUT",
                 "[": "BAR_LEFT", "]": "BAR_RIGHT",
                 "\x1b[C": "RIGHT", "\x1b[D": "LEFT", "\x1b[1;2C": "BAR_RIGHT", "\x1b[1;2D": "BAR_LEFT"}
        while True:
            try:
                data = os.read(fd, 16).decode(errors="ignore")
            except OSError:
                return
            if not data:
                return
            if data in names:
                q.put(names[data])
                continue
            for ch in data:
                if ch in "12345678":
                    q.put("TRACK" + ch)
                elif ch in names:
                    q.put(names[ch])

    threading.Thread(target=reader, daemon=True).start()
    return lambda: termios.tcsetattr(fd, termios.TCSADRAIN, saved)


PYGAME_KEYS = {
    pygame.K_SPACE: "PLAY", pygame.K_r: "RECORD", pygame.K_LEFT: "LEFT", pygame.K_RIGHT: "RIGHT",
    pygame.K_q: "QUIT", pygame.K_ESCAPE: "QUIT", pygame.K_g: "GRID",
    pygame.K_EQUALS: "ZOOM_IN", pygame.K_PLUS: "ZOOM_IN", pygame.K_KP_PLUS: "ZOOM_IN",
    pygame.K_MINUS: "ZOOM_OUT", pygame.K_KP_MINUS: "ZOOM_OUT",
    pygame.K_LEFTBRACKET: "BAR_LEFT", pygame.K_RIGHTBRACKET: "BAR_RIGHT",
}
for _n in range(1, 9):
    PYGAME_KEYS[getattr(pygame, "K_%d" % _n)] = "TRACK%d" % _n


# ---------------------------------------------------------------- the recorder's state (no audio yet)

class Transport:
    def __init__(self, screen):
        self.s = screen
        self.tape = tape.Tape(screen)
        self.playing = False
        self.recording = False
        self.armed = 4
        self.update_screen()

    def key(self, name):
        t = self.tape
        if name == "PLAY":
            self.playing = not self.playing
            if not self.playing:
                self.recording = False
        elif name == "RECORD":
            self.recording = not self.recording
            if self.recording:
                self.playing = True
        elif name == "LEFT":
            t.move(-1, t.step)
        elif name == "RIGHT":
            t.move(1, t.step)
        elif name == "BAR_LEFT":
            t.move(-1, tape.BEATS_PER_BAR)
        elif name == "BAR_RIGHT":
            t.move(1, tape.BEATS_PER_BAR)
        elif name == "GRID":
            t.cycle_grid()
        elif name == "ZOOM_IN":
            t.zoom_in()
        elif name == "ZOOM_OUT":
            t.zoom_out()
        elif name.startswith("TRACK"):
            self.armed = int(name[5:])
        self.update_screen()

    def tick(self, seconds):
        if not self.playing:
            return
        t = self.tape
        start = t.pos
        t.pos += seconds * BPM / 60
        if t.pos >= tape.TAPE_BEATS:
            t.pos = float(tape.TAPE_BEATS)
            self.playing = self.recording = False
        if self.recording:
            t.record(self.armed, start, t.pos)
        self.update_screen()

    def update_screen(self):
        s, t = self.s, self.tape
        b = int(t.pos)
        s.set("clock", t="%03d.%d.%d" % (b // 4 + 1, b % 4 + 1, int(t.pos * 4) % 4 + 1))
        s.set("grid", t=t.label())
        lane = s.get("track%d_lane" % self.armed)
        if lane:
            s.set("rec_outline", y=lane["y"] - 2)
        state = "RECORDING" if self.recording else "PLAYING" if self.playing else "STOPPED"
        s.set("status", t="%s  TRACK %d" % (state, self.armed))
        s.set("rec_dot", c="#FF5A4E" if self.recording else "#7D838C")
        s.set("rec_outline", c="#FF5A4E" if self.recording else "#7D838C")
        for n in range(1, 9):
            level = t.level_at(n, t.pos - 1 / tape.RES) if self.playing else 0
            s.set("track%d_meter" % n, v=round(level * 100))


# ---------------------------------------------------------------- main loop

def main():
    ap = argparse.ArgumentParser(description="Console recorder")
    ap.add_argument("--window", action="store_true", help="open a window instead of full screen")
    ap.add_argument("--rotate", type=int, default=int(os.environ.get("CONSOLE_ROTATE", "270")))
    ap.add_argument("--layout", default=os.path.join(HERE, "layouts", "main.ui"))
    args = ap.parse_args()

    pygame.init()
    if args.window:
        display = pygame.display.set_mode((ui.WIDTH, ui.HEIGHT))
    else:
        display = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
    pygame.display.set_caption("Console")
    dw, dh = display.get_size()
    rotate = args.rotate if dh > dw else 0      # an upright screen means nobody rotated it for us
    print("Console: display %dx%d driver %s%s" % (dw, dh, pygame.display.get_driver(),
                                                 ", turning the picture %d degrees" % rotate if rotate else ""))
    print("Keys: 1-8 arm track, Space play/stop, R record, Left/Right grid step, [ ] bar, G grid, + - zoom, Q quit")

    screen = ui.Screen.load(args.layout)
    frame = pygame.Surface((ui.WIDTH, ui.HEIGHT))
    transport = Transport(screen)
    keys = queue.Queue()
    restore_terminal = start_terminal_keys(keys)
    clock = pygame.time.Clock()

    try:
        running = True
        while running:
            seconds = clock.tick(FPS) / 1000
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN:
                    shift = ev.mod & pygame.KMOD_SHIFT
                    if shift and ev.key == pygame.K_LEFT:
                        keys.put("BAR_LEFT")
                    elif shift and ev.key == pygame.K_RIGHT:
                        keys.put("BAR_RIGHT")
                    elif ev.key in PYGAME_KEYS:
                        keys.put(PYGAME_KEYS[ev.key])
            while not keys.empty():
                name = keys.get()
                if name == "QUIT":
                    if os.environ.get("CONSOLE_SERVICE"):
                        print("Q ignored: Console is running as the boot app. Stop it with: sudo systemctl stop console")
                    else:
                        running = False
                else:
                    transport.key(name)
            transport.tick(seconds)

            screen.draw(frame)
            out = pygame.transform.rotate(frame, rotate) if rotate else frame
            if out.get_size() != (dw, dh):
                scale = min(dw / out.get_width(), dh / out.get_height())
                size = (round(out.get_width() * scale), round(out.get_height() * scale))
                out = pygame.transform.smoothscale(out, size)
                display.fill((0, 0, 0))
            display.blit(out, ((dw - out.get_width()) // 2, (dh - out.get_height()) // 2))
            pygame.display.flip()
    finally:
        if restore_terminal:
            restore_terminal()
        pygame.quit()


if __name__ == "__main__":
    main()
