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


TWO-PIECE KEYCAPS WITH LATO NUMBERS  -  split/
=============================================
Made from your basickeycap.stl (18 x 18 mm cap, saved in source/basic-keycap-1u.stl). The stem, skirt and ribs
are your STL exactly. The cap is cut flat at z = 6 mm, where the round dome starts:

  body   everything below the dome: skirt, ribs and stem. Its cut face is one flat plane, so it prints
         flat on the bed, face down, with nothing under it.
  top    the whole round dome (z 6 - 8 mm) with a small cross-shaped post underneath. The post pushes
         into the cross socket of the stem. The number or icon is let into the dome 0.4 mm deep.
  symbol the number/icon alone, for a second colour (it fills the recess exactly).

24 keys: 01-16 = the 4x4 function grid, 17-24 = track keys 1-8. Numbers are Lato ExtraBold, 2.6 mm tall.
(Change DIGIT_H or FONT at the top of make_split_keycaps.py and run it again.)

HOW IT HOLDS: the post is a press fit in the stem socket (friction), not a click. A drop of glue is fine
if you want it permanent.

1. PRINT THE FIT TEST FIRST   split/fit-test.3mf
   One body and three blank tops: tight (0.05 mm clearance), standard (0.10), loose (0.15). Press each on.
   It should go in with firm thumb pressure and stay put. Then print the matching tops file:
     console-keycap-tops-tight.3mf / -standard.3mf / -loose.3mf

2. PRINT THE SET (24 of each, on two plates)
   split/console-keycap-bodies.3mf   - 24 bodies, flat face down.
   split/console-keycap-tops-<fit>.3mf - 24 tops, already turned face down, symbol on the first layers.
   Filament 1 = the cap, filament 2 = the symbol (the record key's symbol is filament 3, for red).
   PLA is fine; 0.12-0.16 mm layers; keep elephant-foot compensation on.
   The .3mf files have not been tested in Bambu Studio itself. If one won't open as expected, the same parts
   are in split/console-keycaps-split-stl.zip (keycap-body.stl, insert-NN-name-standard.stl, symbol-NN-name.stl;
   the tops and symbols are already face down).

Rebuild:  python3 make_split_keycaps.py   (writes ./out-split/)
