# Control board (rev 0.1)

Open `console-controls.kicad_pro` in KiCad 10. The project's footprint library,
`console.pretty`, has the PGA2350 and the Kailh Choc hotswap footprints, and
`fp-lib-table` loads it automatically.

- `console-controls.kicad_pcb` is the final routed board that was ordered from
  JLCPCB (0 DRC errors).
- `console-controls.kicad_sch` is the schematic with LCSC part numbers. If you
  edited the schematic yourself in KiCad, replace this copy with yours.
- `jlcpcb-order/` holds the BOM and CPL used for assembly, which places 40
  parts on the bottom side. The hotswap sockets were out of stock, so they're
  left off and get hand-soldered.

## Pin map (PGA2350)

| Function | Pins |
|---|---|
| Key matrix rows ROW0–ROW5 | GP2–GP7 |
| Key matrix columns COL0–COL5 | GP8–GP13 |
| Encoders ENC1–ENC11, A/B | GP14/15 … GP34/35, in order |
| Spare | GP0, GP1, GP36–GP46 |
| Reserved | GP47 (PSRAM chip select) |

- **Matrix:** 6×6, COL2ROW. Each diode's cathode (the bar) faces the row.
- **Keys:** SW1–SW16 are the 4×4 grid and SW17–SW24 are the track keys.
- **Encoder pushes:** the ENC1–ENC11 push switches are also in the matrix.
- **Buttons:** SW25 is BOOT and SW26 is RESET.

## Hand assembly after the boards arrive

1. Snap off the 5 mm edge rails.
2. Solder the 24 hotswap sockets on the back.
3. Solder the 11 EC11 encoders.
4. Solder the PGA2350, using 2.54 mm headers or soldering it directly.
