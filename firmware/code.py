# Console control board firmware (CircuitPython 10 on the Pimoroni PGA2350).
#
# Reads the keys, the 11 knobs and the 11 knob pushes, and sends them to the
# Pi as USB MIDI on channel 16:
#   keys SW1-SW24        note 0-23     (note on when pressed, note off when let go)
#   new keys 1-6         note 24-29    (v0.2 boards only: the top row of the long board)
#   knob pushes 1-11     note 32-42    (by position, left to right)
#   step buttons 1-16    note 48-63    (v0.2 boards only)
#   knob turns 1-11      CC 1-11, relative: 64 + clicks (65 = one click right, 63 = one left)
#
# BOARD below says which control board this runs on: 1 = the one-piece v0.1 board,
# 2 = the three v0.2 boards (hardware/v2). The pin maps are in hardware/README.md and hardware/v2/README.md.
import time

import keypad
import microcontroller
import usb_midi

CHANNEL = 15                      # MIDI channel 16 (counted from 0)
DIVISOR = 4                       # encoder steps per click; change to 2 if one click moves two steps
BOARD = 1                         # 1 = v0.1 board, 2 = the v0.2 boards


def pin(n):
    return getattr(microcontroller.pin, "GPIO%d" % n)


# ---------------------------------------------------------------- keys (6x6 matrix, diodes column to row)

ROW_PINS = [pin(n) for n in range(2, 8)]      # ROW0-ROW5 = GP2-GP7
if BOARD == 1:
    COL_PINS = [pin(n) for n in range(8, 14)]                               # COL0-COL5 = GP8-GP13
else:
    COL_PINS = [pin(n) for n in range(8, 14)] + [pin(n) for n in range(36, 41)]   # + COL6-COL10 = GP36-GP40
matrix = keypad.KeyMatrix(row_pins=ROW_PINS, column_pins=COL_PINS, columns_to_anodes=True, interval=0.005)

# matrix position (row, column) -> MIDI note
NOTE = {}
for n in range(1, 17):                         # SW1-SW16: the 4x4 grid, rows 0-3, columns 0-3
    NOTE[((n - 1) // 4, (n - 1) % 4)] = n - 1
if BOARD == 1:
    for i in range(6):                         # SW17-SW22: track keys 1-6, row 4
        NOTE[(4, i)] = 16 + i
    NOTE[(5, 0)] = 22                          # SW23: track key 7
    NOTE[(5, 1)] = 23                          # SW24: track key 8
    for r in range(4):                         # ENC1-ENC8 pushes: rows 0-3, columns 4-5
        NOTE[(r, 4)] = 32 + 2 * r
        NOTE[(r, 5)] = 33 + 2 * r
    NOTE[(5, 2)] = 40                          # ENC9 push
    # On the board, the knob labelled ENC11 sits between ENC9 and ENC10, so these two are
    # numbered by position instead: the 10th knob from the left sends 10, the last one 11.
    NOTE[(5, 3)] = 42                          # ENC10 on the board (last knob) push
    NOTE[(5, 4)] = 41                          # ENC11 on the board (10th knob) push
else:
    for r in range(6):
        NOTE[(r, 4)] = 32 + r                  # knob pushes 1-6: column 4
        NOTE[(r, 6)] = 48 + r                  # steps 1-6: column 6
        NOTE[(r, 7)] = 54 + r                  # steps 7-12: column 7
        NOTE[(r, 9)] = 16 + r                  # track keys 1-6: column 9
        NOTE[(r, 10)] = 24 + r                 # new keys 1-6: column 10
    for r in range(5):
        NOTE[(r, 5)] = 38 + r                  # knob pushes 7-11: column 5
    for r in range(4):
        NOTE[(r, 8)] = 60 + r                  # steps 13-16: column 8
    NOTE[(4, 8)] = 22                          # track key 7
    NOTE[(5, 8)] = 23                          # track key 8

# ---------------------------------------------------------------- pin check
# Instead of acting as a controller, report every knob wire (GP14-GP35) as it changes, as MIDI CC on
# channel 14: CC number = wire (0 = GP14 ... 21 = GP35), value 127 = high, 0 = low; plus all of them
# every half second. The Pi's test screen (test-controls.sh) shows them.
# Start it from the test screen (P sends CC 127 = 127 on channel 14), or hold SW1 while plugging in.
# P again (CC 127 = 0) restarts the board as a normal controller.
PIN_CHECK_ON = bytes((0xB0 | 13, 127, 127))
PIN_CHECK_OFF = bytes((0xB0 | 13, 127, 0))


def heard(message):
    """True if the Pi just sent this MIDI message."""
    try:
        data = usb_midi.ports[0].read(64)
    except Exception:
        return False
    return bool(data) and message in data


def pin_check():
    import digitalio
    out = usb_midi.ports[1]
    wires = []
    for n in range(14, 36):
        w = digitalio.DigitalInOut(pin(n))
        w.switch_to_input(pull=digitalio.Pull.UP)
        wires.append(w)
    last = [None] * len(wires)
    every = 0.0
    print("Pin check: turn each knob slowly; unplug to stop")
    while True:
        now = time.monotonic()
        full = now - every > 0.5
        for i, w in enumerate(wires):
            v = w.value
            if v != last[i] or full:
                last[i] = v
                try:
                    out.write(bytes((0xB0 | 13, i, 127 if v else 0)))
                except Exception:
                    pass
        if full:
            every = now
            if heard(PIN_CHECK_OFF):
                microcontroller.reset()        # start again as a normal controller
        time.sleep(0.0005)


time.sleep(2.0)                                # let the matrix scan; time to hold SW1 after plugging in
_event = keypad.Event()
_held = False
while matrix.events.get_into(_event):
    if _event.pressed and _event.key_number == 0:
        _held = True
if _held:
    pin_check()                                # never returns

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
# by position; on the v0.1 board, ENC10 is the last knob and ENC11 the 10th. The v0.2 knob board is wired in order.
KNOB_CC = [1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 10] if BOARD == 1 else list(range(1, 12))
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
check_at = 0.0
while True:
    now = time.monotonic()
    if now >= check_at:                        # the test screen asking for the pin check
        check_at = now + 0.2
        if heard(PIN_CHECK_ON):
            for enc in encoders:
                enc.deinit() if hasattr(enc, "deinit") else (enc.a.deinit(), enc.b.deinit())
            pin_check()
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
            send(0xB0 | CHANNEL, KNOB_CC[i], max(1, min(127, 64 + delta)))
    if not polled:
        time.sleep(0.001)
