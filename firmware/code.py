# Console control board firmware (CircuitPython 10 on the Pimoroni PGA2350).
#
# Reads the 24 keys, the 11 knobs and the 11 knob pushes, and sends them to the
# Pi as USB MIDI on channel 16:
#   keys SW1-SW24        note 0-23     (note on when pressed, note off when let go)
#   knob pushes ENC1-11  note 32-42
#   knob turns ENC1-11   CC 1-11, relative: 64 + clicks (65 = one click right, 63 = one left)
#
# The pin map and key layout come from hardware/README.md.
import time

import keypad
import microcontroller
import usb_midi

CHANNEL = 15                      # MIDI channel 16 (counted from 0)
DIVISOR = 4                       # encoder steps per click; change to 2 if one click moves two steps


def pin(n):
    return getattr(microcontroller.pin, "GPIO%d" % n)


# ---------------------------------------------------------------- keys (6x6 matrix, diodes column to row)

ROW_PINS = [pin(n) for n in range(2, 8)]      # ROW0-ROW5 = GP2-GP7
COL_PINS = [pin(n) for n in range(8, 14)]     # COL0-COL5 = GP8-GP13
matrix = keypad.KeyMatrix(row_pins=ROW_PINS, column_pins=COL_PINS, columns_to_anodes=True, interval=0.005)

# matrix position (row, column) -> MIDI note
NOTE = {}
for n in range(1, 17):                         # SW1-SW16: the 4x4 grid, rows 0-3, columns 0-3
    NOTE[((n - 1) // 4, (n - 1) % 4)] = n - 1
for i in range(6):                             # SW17-SW22: track keys 1-6, row 4
    NOTE[(4, i)] = 16 + i
NOTE[(5, 0)] = 22                              # SW23: track key 7
NOTE[(5, 1)] = 23                              # SW24: track key 8
for r in range(4):                             # ENC1-ENC8 pushes: rows 0-3, columns 4-5
    NOTE[(r, 4)] = 32 + 2 * r
    NOTE[(r, 5)] = 33 + 2 * r
NOTE[(5, 2)] = 40                              # ENC9 push
NOTE[(5, 3)] = 41                              # ENC10 push
NOTE[(5, 4)] = 42                              # ENC11 push

# ---------------------------------------------------------------- knobs (A/B on GP14/15 ... GP34/35)


class PolledEncoder:
    """Used only if the chip runs out of hardware encoder readers."""
    TABLE = (0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0)

    def __init__(self, a, b):
        import digitalio
        self.a = digitalio.DigitalInOut(a)
        self.b = digitalio.DigitalInOut(b)
        for p in (self.a, self.b):
            p.switch_to_input(pull=digitalio.Pull.UP)
        self.state = (self.a.value << 1) | self.b.value
        self.steps = 0
        self.position = 0

    def poll(self):
        s = (self.a.value << 1) | self.b.value
        self.steps += self.TABLE[(self.state << 2) | s]
        self.state = s
        while self.steps >= DIVISOR:
            self.steps -= DIVISOR
            self.position += 1
        while self.steps <= -DIVISOR:
            self.steps += DIVISOR
            self.position -= 1


encoders = []
polled = []
for e in range(11):
    a, b = pin(14 + 2 * e), pin(15 + 2 * e)
    try:
        import rotaryio
        enc = rotaryio.IncrementalEncoder(a, b, divisor=DIVISOR)
    except Exception:
        enc = PolledEncoder(a, b)
        polled.append(enc)
    encoders.append(enc)
last = [enc.position for enc in encoders]
if polled:
    print("%d knobs read by polling" % len(polled))

# ---------------------------------------------------------------- send

midi = usb_midi.ports[1]


def send(*data):
    try:
        midi.write(bytes(data))
    except Exception:
        pass                                   # not connected to a host yet


print("Console controls ready")
event = keypad.Event()
while True:
    for enc in polled:
        enc.poll()
    while matrix.events.get_into(event):
        row, col = divmod(event.key_number, len(COL_PINS))
        note = NOTE.get((row, col))
        if note is None:
            continue
        if event.pressed:
            send(0x90 | CHANNEL, note, 127)
        else:
            send(0x80 | CHANNEL, note, 0)
    for i, enc in enumerate(encoders):
        pos = enc.position
        delta = pos - last[i]
        if delta:
            last[i] = pos
            send(0xB0 | CHANNEL, i + 1, max(1, min(127, 64 + delta)))
    if not polled:
        time.sleep(0.001)
