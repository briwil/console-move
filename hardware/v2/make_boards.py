"""Builds the three v0.2 control boards (keypad, keys, knobs) from Brian's layout.

    python3 make_boards.py            places the parts, writes each board's .kicad_pcb and .dsn
    python3 make_boards.py --route    also routes them with Freerouting and reads the tracks back

All positions are in mm from each board's top-left corner. The wiring between boards and the
pin map are in README.md.
"""
import os
import subprocess
import sys

from kicadgen import Board, Part

HERE = os.path.dirname(os.path.abspath(__file__))

# PGA2350 pads -> pin names (from the v0.1 schematic symbol)
PGA = {'A1': 'GND', 'A10': 'GND', 'A2': 'GP1', 'A3': 'VBUS', 'A4': '3V3_EN', 'A5': 'RUN', 'A6': 'USB_DP',
       'A7': 'USB_DM', 'A8': 'BOOTSEL', 'A9': 'GP46', 'B1': 'GP2', 'B10': 'GP45', 'B2': 'GND', 'B3': 'GP0',
       'B4': '3V3', 'B5': 'ADC_VREF', 'B6': 'SWCLK', 'B7': 'SWDIO', 'B8': 'GP47', 'B9': 'GND', 'C1': 'GP4',
       'C10': 'GP44', 'C2': 'GP3', 'C9': 'GP43', 'D1': 'GP6', 'D10': 'GP42', 'D2': 'GP5', 'D9': 'GP41',
       'E1': 'GP8', 'E10': 'GP40', 'E2': 'GP7', 'E9': 'GP39', 'F1': 'GP10', 'F10': 'GP38', 'F2': 'GP9',
       'F9': 'GP37', 'G1': 'GP12', 'G10': 'GP36', 'G2': 'GP11', 'G9': 'GP35', 'H1': 'GP14', 'H10': 'GP34',
       'H2': 'GP13', 'H9': 'GP33', 'I1': 'GP16', 'I10': 'GP32', 'I2': 'GP15', 'I3': 'GP19', 'I4': 'GP21',
       'I5': 'GP23', 'I6': 'GP25', 'I7': 'GP27', 'I8': 'GP29', 'I9': 'GP31', 'J1': 'GND', 'J10': 'GND',
       'J2': 'GP17', 'J3': 'GP18', 'J4': 'GP20', 'J5': 'GP22', 'J6': 'GP24', 'J7': 'GP26', 'J8': 'GP28',
       'J9': 'GP30'}

# What each GP pin does (the firmware uses the same map)
GP_NET = {}
for r in range(6):
    GP_NET[2 + r] = "ROW%d" % r                      # GP2-GP7
for c in range(6):
    GP_NET[8 + c] = "COL%d" % c                      # GP8-GP13: keypad columns 0-3, knob pushes 4-5
for k in range(1, 12):
    GP_NET[12 + 2 * k] = "KNOB%d_A" % k              # GP14/15 ... GP34/35, knobs 1-11 left to right
    GP_NET[13 + 2 * k] = "KNOB%d_B" % k
for c in range(5):
    GP_NET[36 + c] = "COL%d" % (6 + c)               # GP36-GP40: the long board's columns

# The ribbon cables: pin -> net, the same at both ends
CABLE_KNOBS_1_6 = {1: "GND", 2: "COL4", **{3 + r: "ROW%d" % r for r in range(6)},
                   **{9 + 2 * i: "KNOB%d_A" % (i + 1) for i in range(6)},
                   **{10 + 2 * i: "KNOB%d_B" % (i + 1) for i in range(6)}}
CABLE_KNOBS_7_11 = {1: "GND", 2: "COL5", **{3 + r: "ROW%d" % r for r in range(5)}, 8: "GND",
                    **{9 + 2 * i: "KNOB%d_A" % (i + 7) for i in range(5)},
                    **{10 + 2 * i: "KNOB%d_B" % (i + 7) for i in range(5)}, 19: "GND", 20: "GND"}
CABLE_KEYS = {**{1 + r: "ROW%d" % r for r in range(6)}, **{7 + c: "COL%d" % (6 + c) for c in range(5)},
              **{p: "GND" for p in range(12, 17)}}

LCSC_DIODE = "C81598"          # 1N4148W, SOD-123


def header(ref, kind, x, y, cable, rename=None, keep_gnd=True):
    """A box header at (x, y) = pin 1, lying along x (pins 1, 3, 5... in a row, 2, 4, 6... 2.54 mm above)."""
    nets = {}
    for pin, net in cable.items():
        if net == "GND" and not keep_gnd:
            continue
        nets[str(pin)] = (rename or {}).get(net, net)
    return Part(ref, kind, x, y, 90, value="IDC 2x%d" % (len(cable) // 2), nets=nets)


# ------------------------------------------------------------------ keypad board (the microcontroller)

def keypad_board():
    b = Board("keypad", "Console keypad board", 87.5, 111.5)
    for r in range(4):
        for c in range(4):
            n = 4 * r + c + 1
            x, y = 16.5 + 18 * c, 48.5 + 17 * r
            b.add(Part("SW%d" % n, "choc", x, y, value="Key %d" % n,
                       nets={"1": "COL%d" % c, "2": "D%d_A" % n}))
            b.add(Part("D%d" % n, "sod123", x, y + 5, value="1N4148W", lcsc=LCSC_DIODE,
                       nets={"1": "ROW%d" % r, "2": "D%d_A" % n}))
    pga = {}
    for pad, name in PGA.items():
        if name in ("GND", "VBUS", "RUN", "USB_DP", "USB_DM", "BOOTSEL"):
            pga[pad] = name
        elif name.startswith("GP") and int(name[2:]) in GP_NET:
            pga[pad] = GP_NET[int(name[2:])]
    b.add(Part("U1", "pga2350", 17.5, 21, value="PGA2350", nets=pga))
    usb = {"A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND", "SH": "GND", "A4": "VBUS", "A9": "VBUS",
           "B4": "VBUS", "B9": "VBUS", "A5": "CC1", "B5": "CC2", "A6": "USB_DP", "B6": "USB_DP",
           "A7": "USB_DM", "B7": "USB_DM"}
    b.add(Part("J1", "usbc", 84, 19.5, 90, value="USB-C", lcsc="C165948", nets=usb))
    b.add(Part("R1", "r0603", 74, 14, value="5.1k", lcsc="C23186", nets={"1": "CC1", "2": "GND"}))
    b.add(Part("R2", "r0603", 74, 25, value="5.1k", lcsc="C23186", nets={"1": "CC2", "2": "GND"}))
    b.add(Part("SW25", "tl3342", 72, 5.5, value="BOOT", lcsc="C2886898", nets={"1": "BOOTSEL", "2": "GND"}))
    b.add(Part("SW26", "tl3342", 72, 33.5, value="RESET", lcsc="C2886898", nets={"1": "RUN", "2": "GND"}))
    b.add(header("J2", "idc10", 37, 7.5, CABLE_KNOBS_1_6))
    b.add(header("J3", "idc10", 37, 18.5, CABLE_KNOBS_7_11))
    b.add(header("J4", "idc8", 37, 29.5, CABLE_KEYS))
    for i, (x, y) in enumerate([(5, 5), (82.5, 5), (5, 106.5), (82.5, 106.5)]):
        b.add(Part("H%d" % (i + 1), "m3", x, y, value="M3"))
    b.text("KNOBS 1-6", 48.4, 1.6, "B.SilkS", 1.0)
    b.text("KNOBS 7-11", 48.4, 12.6, "B.SilkS", 1.0)
    b.text("KEYS", 45.5, 23.6, "B.SilkS", 1.0)
    b.text("CONSOLE KEYPAD v0.2", 43.75, 37.2, "B.SilkS", 1.2)
    return b


# ------------------------------------------------------------------ knob board

KNOB_X = [20 + 21.255 * i for i in range(10)] + [240.3]
KNOB_Y = 17.0


def knob_board():
    b = Board("knobs", "Console knob board", 258, 35)
    for i, sx in enumerate(KNOB_X):
        k = i + 1
        side_b = k >= 7
        row = (k - 1) if k <= 6 else (k - 7)
        col = "COL4" if k <= 6 else "COL5"
        sfx = "_B" if side_b else ""
        gnd = "GND_B" if side_b else "GND"
        # the footprint's origin is pin A; the shaft is 7.5 right and 2.5 down from it
        b.add(Part("ENC%d" % k, "enc", sx - 7.5, KNOB_Y - 2.5, value="Knob %d" % k,
                   nets={"A": "KNOB%d_A" % k, "B": "KNOB%d_B" % k, "C": gnd, "S1": col + sfx,
                         "S2": "D%d_A" % (24 + k)}))
        # the push's diode stands between this knob and the next: anode (pad 2) up by S2, cathode down
        b.add(Part("D%d" % (24 + k), "do35", sx + 10.5, KNOB_Y + 3.81, 90, value="1N4148",
                   nets={"1": "ROW%d" % row + sfx, "2": "D%d_A" % (24 + k)}))
    rename_b = {"GND": "GND_B", "COL5": "COL5_B", **{"ROW%d" % r: "ROW%d_B" % r for r in range(6)}}
    b.add(header("J1", "idc10", 40, 30.9, CABLE_KNOBS_1_6))
    b.add(header("J2", "idc10", 160, 30.9, CABLE_KNOBS_7_11, rename=rename_b))
    mid = (KNOB_X[4] + KNOB_X[5]) / 2
    for i, (x, y) in enumerate([(5, 5), (mid, 5), (253, 5), (5, 30), (mid, 30), (253, 30)]):
        b.add(Part("H%d" % (i + 1), "m3", x, y, value="M3"))
    b.text("KNOBS 1-6", 51.4, 25.0, "B.SilkS", 1.0)
    b.text("KNOBS 7-11", 171.4, 25.0, "B.SilkS", 1.0)
    b.text("CONSOLE KNOBS v0.2", 120, 2.2, "B.SilkS", 1.2)
    return b


# ------------------------------------------------------------------ the long board (track keys, new keys, steps)

TOP_X = [38.5, 66.2, 120.75, 148.5, 176.2, 217.75]       # the 6 new keys
TOP_Y = 14.9
TRACK_X = [23.75 + 27.714 * i for i in range(8)]          # SW17-SW24
TRACK_Y = 36.9
STEP_X = [15.75 + 14 * i for i in range(16)]              # the 16 step buttons (centres)
STEP_Y = 59.7


def keys_board():
    b = Board("keys", "Console keys board", 241.5, 72.5)
    # matrix: COL6 steps 1-6, COL7 steps 7-12, COL8 steps 13-16 + track keys 7-8, COL9 track keys 1-6,
    # COL10 the new keys 1-6; rows 0-5 down each column
    for i, x in enumerate(TOP_X):
        n, d = 27 + i, 36 + i
        b.add(Part("SW%d" % n, "choc", x, TOP_Y, value="New key %d" % (i + 1),
                   nets={"1": "COL10", "2": "D%d_A" % d}))
        b.add(Part("D%d" % d, "do35", x - 3.81, TOP_Y + 10.7, value="1N4148",
                   nets={"1": "ROW%d" % i, "2": "D%d_A" % d}))
    for i, x in enumerate(TRACK_X):
        n = 17 + i
        col, row = ("COL9", i) if i < 6 else ("COL8", i - 2)
        b.add(Part("SW%d" % n, "choc", x, TRACK_Y, value="Track %d" % (i + 1),
                   nets={"1": col, "2": "D%d_A" % n}))
        b.add(Part("D%d" % n, "do35", x + 13.857, TRACK_Y + 3.81, 90, value="1N4148",
                   nets={"1": "ROW%d" % row, "2": "D%d_A" % n}))
    for i, cx in enumerate(STEP_X):
        n, d = 33 + i, 42 + i
        col, row = ("COL%d" % (6 + i // 6), i % 6) if i < 12 else ("COL8", i - 12)
        b.add(Part("SW%d" % n, "push6", cx - 3.25, STEP_Y - 2.25, value="Step %d" % (i + 1),
                   nets={"1": col, "2": "D%d_A" % d}))
        b.add(Part("D%d" % d, "do35", cx - 3.81, STEP_Y - 8.2, value="1N4148",
                   nets={"1": "ROW%d" % row, "2": "D%d_A" % d}))
    b.add(header("J1", "idc8", 82, 12, CABLE_KEYS, keep_gnd=False))
    for i, (x, y) in enumerate([(5, 4.5), (162.35, 4.5), (236.5, 4.5), (5, 68), (120.75, 68), (236.5, 68)]):
        b.add(Part("H%d" % (i + 1), "m3", x, y, value="M3"))
    b.text("KEYS", 90.9, 17.8, "B.SilkS", 1.0)
    b.text("CONSOLE KEYS v0.2", 93, 25.5, "B.SilkS", 1.2)
    return b


def jlcpcb_files(b, folder):
    """The parts list (BOM) and placement list (CPL) for JLCPCB to fit the parts that have LCSC numbers,
    in the same form as the v0.1 order (positions as KiCad writes them: mm, y upwards)."""
    os.makedirs(folder, exist_ok=True)
    groups = {}
    for p in b.parts:
        if p.lcsc:
            groups.setdefault((p.value, p.fp[1].strip('"'), p.lcsc), []).append(p.ref)
    with open(os.path.join(folder, "console-%s-BOM.csv" % b.name), "w") as fh:
        fh.write("Comment,Designator,Footprint,LCSC Part #\n")
        for (value, fp, lcsc), refs in sorted(groups.items()):
            refs.sort(key=lambda r: (r.rstrip("0123456789"), int(r[len(r.rstrip("0123456789")):] or 0)))
            fh.write('%s,"%s",%s,%s\n' % (value, ",".join(refs), fp.split(":")[-1], lcsc))
    with open(os.path.join(folder, "console-%s-CPL.csv" % b.name), "w") as fh:
        fh.write("Designator,Mid X,Mid Y,Layer,Rotation\n")
        for p in b.parts:
            if p.lcsc:
                fh.write("%s,%.4fmm,%.4fmm,%s,%g\n" % (p.ref, b.ox + p.x, -(b.oy + p.y),
                                                     "Bottom" if p.side == "B" else "Top", p.angle))


BOARDS = {"keypad": keypad_board, "knobs": knob_board, "keys": keys_board}

FREEROUTING = os.environ.get("FREEROUTING_CP", "/tmp/claude-0/fr/out")


def route(b, passes=40):
    dsn = os.path.join(HERE, "route", b.name + ".dsn")
    ses = os.path.join(HERE, "route", b.name + ".ses")
    b.write_dsn(dsn)
    if os.path.exists(ses):
        os.remove(ses)
    subprocess.run(["xvfb-run", "-a", "java", "-cp", FREEROUTING, "app.freerouting.gui.MainApplication",
                    "-de", dsn, "-do", ses, "-mp", str(passes), "-oit", "2"], check=False,
                   stdout=open(dsn[:-4] + ".log", "w"), stderr=subprocess.STDOUT, timeout=3600)
    b.read_ses(ses)


if __name__ == "__main__":
    os.makedirs(os.path.join(HERE, "route"), exist_ok=True)
    names = [a for a in sys.argv[1:] if not a.startswith("-")] or list(BOARDS)
    for name in names:
        b = BOARDS[name]()
        if "--route" in sys.argv:
            route(b)
            bad = b.unjoined()
            print(name, "tracks", len(b.segments), "vias", len(b.vias), "unjoined", bad or "none")
        else:
            b.write_dsn(os.path.join(HERE, "route", name + ".dsn"))
        print(name, "overlaps", b.overlaps() or "none")
        b.write_kicad(os.path.join(HERE, "console-%s.kicad_pcb" % name))
        if name == "keypad":
            jlcpcb_files(b, os.path.join(HERE, "jlcpcb-order"))
