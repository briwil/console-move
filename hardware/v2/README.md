# Control boards v0.2 (three boards)

The v0.1 one-piece board split into three smaller boards, joined by ribbon cables, plus 16 step
buttons and 6 new keys. The microcontroller (PGA2350) stays on the keypad board; the other two
boards are only switches, diodes and a socket.

| Board | Size | What's on it | Made by |
|---|---|---|---|
| `console-keypad.kicad_pcb` | 87.5 × 111.5 mm | the 4×4 keys, PGA2350, USB-C, BOOT and RESET, 3 cable sockets | JLCPCB fits the diodes, USB-C, resistors and buttons; you solder the rest |
| `console-keys.kicad_pcb` | 241.5 × 72.5 mm | 8 track keys, 6 new keys, 16 step buttons, 30 diodes, 1 cable socket | bare board, you solder everything |
| `console-knobs.kicad_pcb` | 258 × 35 mm | 11 knobs (with pushes), 11 diodes, 2 cable sockets | bare board, you solder everything |

The boards are made by `make_boards.py` (`python3 make_boards.py --route` places the parts, routes
them with Freerouting and writes the three `.kicad_pcb` files). Open any of them in KiCad 10.
There's no schematic for v0.2: the wiring is in `make_boards.py` and below. Routing used
Freerouting 1.6.5 built from source (with its two `== ""` string comparisons fixed so it runs on
Java 21; set `FREEROUTING_CP` to its classes folder). `route/` keeps each board's `.dsn` and the
routed `.ses`.

**Not ordered yet:** the boards still need KiCad's own design rule check and the Gerber files
made in KiCad before ordering.

## Cables

Three ribbon cables with IDC plugs. Each one goes **pin 1 to pin 1** (an ordinary straight ribbon
cable with the plugs crimped the same way round; the red stripe is pin 1). The sockets are
shrouded box headers, so the plugs only go in one way.

| Cable | From (keypad board) | To | Pins |
|---|---|---|---|
| Knobs 1-6 | J2 | knob board J1 | 20 (2×10) |
| Knobs 7-11 | J3 | knob board J2 | 20 (2×10) |
| Keys | J4 | keys board J1 | 16 (2×8) |

All the sockets are on the back of the boards.

## Pin map (PGA2350)

| Function | Pins |
|---|---|
| Key matrix rows ROW0-ROW5 | GP2-GP7 (shared by all three boards) |
| Keypad columns COL0-COL3 | GP8-GP11 |
| Knob pushes COL4 (knobs 1-6), COL5 (knobs 7-11) | GP12, GP13 |
| Knobs 1-11 A/B, left to right | GP14/15 … GP34/35 |
| Keys board columns COL6-COL10 | GP36-GP40 |
| Spare | GP0, GP1, GP41-GP46 |

Matrix: 6 rows × 11 columns, columns to anodes: switch from the column to the diode's anode, the
diode's cathode (the band) to the row.

| Column | Rows 0-5 |
|---|---|
| COL0-COL3 | keys 1-16 (the 4×4 grid, row by row) |
| COL4 | knob pushes 1-6 |
| COL5 | knob pushes 7-11 (rows 0-4) |
| COL6 | steps 1-6 |
| COL7 | steps 7-12 |
| COL8 | steps 13-16 (rows 0-3), track keys 7-8 (rows 4-5) |
| COL9 | track keys 1-6 |
| COL10 | new keys 1-6 (the top row, left to right) |

The firmware (`../../firmware/code.py`) has both boards' maps: set `BOARD = 2` for these.

### Cable pins

Knobs 1-6 (2×10): 1 GND, 2 COL4, 3-8 ROW0-ROW5, 9/10 knob 1 A/B, 11/12 knob 2 A/B … 19/20 knob 6 A/B.

Knobs 7-11 (2×10): 1 GND, 2 COL5, 3-7 ROW0-ROW4, 8 GND, 9/10 knob 7 A/B … 17/18 knob 11 A/B, 19-20 GND.

Keys (2×8): 1-6 ROW0-ROW5, 7-11 COL6-COL10, 12-16 GND (not used on the keys board).

## Parts to buy (besides what JLCPCB fits)

- 1 × PGA2350 (or reuse the v0.1 one)
- 14 × Kailh Choc V1 switches and 14 hotswap sockets (CPG135001S30): 8 track keys + 6 new keys
- 16 × Choc V1 switches and sockets for the keypad (or reuse the v0.1 ones)
- 16 × 6×6 mm through-hole tactile switches, 4 pins (the height to suit the case)
- 41 × 1N4148 diodes, through-hole (DO-35)
- 11 × EC11 encoders with push switch (the ones you have)
- 4 × 2×10 shrouded box headers, 2.54 mm (IDC, vertical)
- 2 × 2×8 shrouded box headers, 2.54 mm
- 2 × 20-pin and 1 × 16-pin IDC ribbon cables, 2.54 mm, plug at each end, the same way round
  (16-pin to 16-pin, not the 10-to-16 Eurorack power kind)
- 16 × M3 screws and standoffs (4 + 6 + 6)

## Hand assembly

Keys board and knob board: diodes first (the band goes on the side marked on the board), then the
hotswap sockets (back), tactile switches and encoders (front), then the box header (back, notch as
drawn). Keypad board: the 16 hotswap sockets, the PGA2350 and the three box headers.
