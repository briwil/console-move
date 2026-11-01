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


TWO-PIECE KEYCAPS WITH LATO NUMBERS (snap-fit)  -  split/
=========================================================
Made from your basickeycap.stl (the 18 x 18 mm cap, saved in source/basic-keycap-1u.stl). The stem, skirt and
ribs are your STL exactly. Only the round top changed: it is now its own piece.

  keycap body   the cap without its round top: a round pocket with a floor and six small grooves in the wall
  insert        the round top, with its number let in 0.4 mm. Six small bumps on its edge click into the grooves
  number        the digit alone, for a second colour (it fills the recess exactly)

Numbers 1-8 are Lato ExtraBold, 2.6 mm tall, centred. (Change DIGIT_H or FONT at the top of
make_split_keycaps.py and run it again.)

1. PRINT THE FIT TEST FIRST   split/fit-test.3mf
   One body with a blank insert of each kind: "standard" (bumps 0.22 mm) and "loose" (0.15 mm). Press the insert
   in with your thumb; it should click in and stay put, and come out again with a fingernail or a hobby knife
   in the 0.1 mm gap round it. Use whichever you like:
     standard holds well          -> console-keycaps-snap-standard.3mf
     too tight / insert won't go  -> console-keycaps-snap-loose.3mf
   The bodies are the same in both; only the inserts differ.

2. PRINT THE SET   (8 bodies + 8 inserts on one plate, 256 x 256 bed)
   Open the .3mf in Bambu Studio. Filament 1 = the keycap (body and insert), filament 2 = the number.
   - Bodies print the way up they are (open end down), like your original cap.
   - Inserts are already turned face down: the number is the first layers, so it is flat and sharp.
   - PLA is fine; PETG gives the snap a little more give. 0.12-0.16 mm layers; keep elephant-foot
     compensation on (it keeps the insert from growing at its face).
   If the .3mf won't open the way you expect, the same parts are in split/console-keycaps-split-stl.zip
   (keycap-body.stl x 8, insert-N-standard.stl / insert-N-loose.stl, number-N.stl - the inserts and numbers
   are already face down; put each number on top of its insert).

Rebuild:  python3 make_split_keycaps.py   (writes ./out-split/)
