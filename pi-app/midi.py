"""MIDI in: the control board's keys and knobs, and tempo sync from an OP-XY (or anything sending MIDI clock).

Reads ALSA raw MIDI devices (/dev/snd/midiC<card>D0) directly, so nothing extra
needs installing. Each source runs in its own thread and keeps retrying, so
devices can be plugged in and out while the app runs.
"""
import os
import re
import threading
import time

CONTROLLER_NAMES = ("console controls", "circuitpython")


def midi_cards():
    """[(card index, id, description)] for every card with a raw MIDI port."""
    try:
        with open("/proc/asound/cards") as f:
            cards = re.findall(r"^\s*(\d+)\s+\[(\S+)\s*\]:\s*(.*)$", f.read(), re.M)
    except OSError:
        return []
    return [(int(i), cid, desc) for i, cid, desc in cards if os.path.exists("/dev/snd/midiC%sD0" % i)]


def is_controller(cid, desc):
    text = (cid + " " + desc).lower()
    return any(n in text for n in CONTROLLER_NAMES)


class Parser:
    """Turns a MIDI byte stream into messages: (status, data1, data2) tuples and real-time bytes."""

    LENGTH = {0x80: 2, 0x90: 2, 0xA0: 2, 0xB0: 2, 0xC0: 1, 0xD0: 1, 0xE0: 2}

    def __init__(self, on_message, on_realtime):
        self.on_message, self.on_realtime = on_message, on_realtime
        self.status, self.data, self.sysex = None, [], False

    def feed(self, data):
        for b in data:
            if b >= 0xF8:
                self.on_realtime(b)                  # clock, start, continue, stop: can arrive mid-message
                continue
            if b == 0xF0:
                self.sysex = True
                continue
            if self.sysex:
                if b == 0xF7 or b >= 0x80:
                    self.sysex = False
                if b < 0x80 or b == 0xF7:
                    continue
            if b >= 0x80:
                self.status, self.data = b, []
                continue
            if self.status is None:
                continue
            self.data.append(b)
            need = self.LENGTH.get(self.status & 0xF0, 0) if self.status < 0xF0 else {0xF1: 1, 0xF2: 2, 0xF3: 1}.get(self.status, 0)
            if need and len(self.data) == need:
                self.on_message(self.status, self.data[0], self.data[1] if need > 1 else 0)
                self.data = []
                if self.status >= 0xF0:
                    self.status = None               # system common messages don't use running status


class Source(threading.Thread):
    """Reads one kind of MIDI device in the background, reconnecting as needed."""

    def __init__(self, choose, on_message, on_realtime=None, label="MIDI"):
        super().__init__(daemon=True, name=label)
        self.choose = choose                         # function(cards) -> card index or None
        self.label = label
        self.parser = Parser(on_message, on_realtime or (lambda b: None))
        self.connected = None                        # description of the connected device, or None
        self.stopped = False

    def run(self):
        while not self.stopped:
            idx = self.choose(midi_cards())
            if idx is None:
                self.connected = None
                time.sleep(2)
                continue
            path = "/dev/snd/midiC%dD0" % idx
            try:
                fd = os.open(path, os.O_RDONLY)
            except OSError as e:
                print("%s: can't open %s (%s)" % (self.label, path, e))
                time.sleep(2)
                continue
            self.connected = path
            print("%s: reading %s" % (self.label, path))
            try:
                while not self.stopped:
                    data = os.read(fd, 256)
                    if not data:
                        break
                    self.parser.feed(data)
            except OSError:
                pass
            finally:
                os.close(fd)
                self.connected = None
                print("%s: %s disconnected" % (self.label, path))
            time.sleep(1)


class Clock:
    """Follows MIDI clock, start, stop, continue and song position from one device."""

    def __init__(self, engine):
        self.engine = engine
        self.ticks = []                              # times of the last clock ticks
        self.last_tick = 0.0
        self.song_pos = 0.0                          # beats, from the last song position message

    @property
    def active(self):
        return time.monotonic() - self.last_tick < 0.5

    @property
    def bpm(self):
        if len(self.ticks) < 25 or not self.active:
            return None
        span = self.ticks[-1] - self.ticks[0]
        return 60.0 / (span / (len(self.ticks) - 1) * 24) if span > 0 else None

    def realtime(self, b):
        now = time.monotonic()
        if b == 0xF8:                                # clock: 24 per beat
            if now - self.last_tick > 0.5:
                self.ticks = []
            self.ticks.append(now)
            del self.ticks[:-97]                     # about 4 beats of history
            self.last_tick = now
        elif b == 0xFA and self.engine:              # start
            self.engine.sync_start(0.0)
        elif b == 0xFB and self.engine:              # continue
            self.engine.set_beats(self.song_pos)
            self.engine.sync_continue()
        elif b == 0xFC and self.engine:              # stop
            self.engine.sync_stop()

    def message(self, status, d1, d2):
        if status == 0xF2:                           # song position, in 16th notes
            self.song_pos = ((d2 << 7) | d1) / 4.0
            if self.engine and not self.engine.playing:
                self.engine.set_beats(self.song_pos)


def start(on_control, engine, clock_name=None):
    """Start reading the control board and a clock source.

    on_control(kind, number, value) gets ("note", note, 1 or 0) and ("cc", number, value).
    Returns (controller source, clock source, Clock).
    """
    def control_message(status, d1, d2):
        kind = status & 0xF0
        if kind == 0x90:
            on_control("note", d1, 1 if d2 else 0)
        elif kind == 0x80:
            on_control("note", d1, 0)
        elif kind == 0xB0:
            on_control("cc", d1, d2)

    def pick_controller(cards):
        for i, cid, desc in cards:
            if is_controller(cid, desc):
                return i
        return None

    def pick_clock(cards):
        for i, cid, desc in cards:
            if is_controller(cid, desc):
                continue
            if clock_name:
                if clock_name.lower() in (cid + " " + desc).lower():
                    return i
            else:
                return i                             # the first other MIDI device, e.g. the OP-XY
        return None

    clock = Clock(engine)
    ctl = Source(pick_controller, control_message, label="Controls")
    clk = Source(pick_clock, clock.message, clock.realtime, label="Clock")
    ctl.start()
    clk.start()
    return ctl, clk, clock
