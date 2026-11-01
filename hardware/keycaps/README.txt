Console keycaps for Kailh Choc V1 switches
================================================

Size: 17.5 x 16.5 mm, 2.4 mm thick, icons engraved 0.6 mm deep.
Stem: two prongs 1.2 x 3.0 mm, 5.7 mm apart, 3 mm long (Kailh Choc V1).

1. PRINT THE FIT TEST FIRST
   fit-test-nominal.stl  - exact Kailh prong size
   fit-test-loose.stl    - 0.1 mm thinner prongs
   Push each onto a switch. Use whichever is snug but not forced:
     snug nominal   -> print console-keycaps-nominal.3mf
     too tight      -> print console-keycaps-loose.3mf
   (Each .3mf holds all 24 keys as separate parts. To get single STL files instead,
   run: python3 make_keycaps.py  - it writes stl-nominal/ and stl-loose/ into ./out.)

2. PRINT THE SET (24 keys)
   01-16 = 4x4 function grid (SW1-SW16), 17-24 = track keys 1-8 (SW17-SW24).
   Print 12-record in red if you can.

   Best: resin (SLA). Ordering online (e.g. JLC3DP), upload the STLs and pick a
   resin like "8001" or "Imagine Black/White".
   FDM works too: print top-face DOWN, 0.4 mm nozzle, 0.12 mm layers. The stem
   prongs are small, so print slowly.

3. MAKE THE ICONS STAND OUT (pick one)
   - Paint fill: rub acrylic paint into the engraving, wipe the surface clean.
   - Two-colour printer: print the matching file from inlays/ in a second colour,
     placed into the engraving (top 0.6 mm), as one multi-material object.


TWO-PIECE CHOC KEYCAPS WITH LATO NUMBERS  -  split/
===================================================
Same Kailh Choc V1 switches and the same prongs as above (1.2 x 3.0 mm, 5.7 mm apart), 17.5 x 16.5 mm, 2.4 mm
tall. Your basickeycap.stl was used for STYLE only (the round dome with a small centred symbol).

  body    flat plate 1.4 mm thick with the two prongs under it and three round holes. Prints FLAT on the bed,
          plate face down, prongs pointing up. Nothing round is left on it.
  top     the whole round dome (14.4 mm wide, 1.0 mm thick) with three small round pegs under it that press
          into the holes. The number/icon is let in 0.4 mm. Prints face down, symbol on the first layers.
  symbol  the number/icon alone, for a second colour (fills the recess exactly).

24 keys: 01-16 = the 4x4 function grid, 17-24 = track keys 1-8. Numbers are Lato ExtraBold, 2.6 mm tall.
HOW IT HOLDS: friction from the pegs (not a click). The cap is thin, so a dot of glue makes it permanent.

1. PRINT split/fit-test.3mf FIRST: one body and three blank tops (tight 0.05, standard 0.10, loose 0.15 mm
   clearance). Pick the one that goes in with firm thumb pressure and stays put.
2. PRINT THE SET: split/console-keycap-bodies.3mf (24 bodies) and split/console-keycap-tops-<fit>.3mf
   (24 tops). Filament 1 = the cap, 2 = the symbol, 3 = the record key (red).
   0.12-0.16 mm layers, elephant-foot compensation on. The .3mf files are untested in Bambu Studio; plain STLs
   are in split/console-keycaps-split-stl.zip (standard fit only).
Rebuild:  python3 make_choc_keycaps.py   (writes ./out-choc/)
