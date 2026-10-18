# Controller firmware

This is the code for the PGA2350 (RP2350B) on the control board. It hasn't
been started yet.

Its job: scan the 6×6 key matrix, read the 11 encoders and send key and knob
events to the Pi over USB. The pin map is in `../hardware/README.md`.
