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
