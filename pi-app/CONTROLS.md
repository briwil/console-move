# Controls

Everything works from the control board, and nearly everything from a
keyboard too: a keyboard plugged into the Pi, or keys typed into the SSH
window that's running the app.

## Keys on the board

| Key | Press | With SHIFT held |
|---|---|---|
| AUDIO | Input: all inputs to tracks 1–8, or inputs mixed onto the armed track | |
| MIDI, FX, FILE, IMPORT | Not yet (coming in a later version) | |
| SPLICE | Remove the region and close the gap (the rest moves earlier) | Same, on all tracks |
| CUT | Erase the region | Undo |
| LIFT | Take the region off the track into the clipboard, leaving silence | Same, on all tracks |
| DROP | Put the clipboard down at the playhead, replacing what's there | Insert it, pushing the rest later |
| LOOP | Loop on / off (the first time, loops 4 bars from the current bar) | |
| EXPORT | Export stems and a stereo mix to Exports | |
| RECORD | Record on / off. When the OP-XY's clock is coming in and the tape is stopped: get ready, and recording starts when you press play on the OP-XY | |
| SHIFT | Hold for the second column | |
| PLAY | Play / stop | Back to the start (or the loop start) |
| ← / → | Move one grid step | Set the loop start / end at the playhead |
| 1–8 | Arm that track | Mute / unmute that track |

**The region** that SPLICE, CUT and LIFT work on is the loop, if one is set,
or else the bar under the playhead.

## Knobs

| Knob | Turn | Push |
|---|---|---|
| 1–8 (above the tracks) | Track volume (with SHIFT: fine steps) | Mute / unmute |
| Left of the right-hand three | Zoom | Zoom back to 4 bars |
| Right of the right-hand three | Grid: 1/4, 1/8, 1/16, 1/32 | Loop on / off |
| Big knob | Move the playhead by grid steps (with SHIFT: by bars) | Back to the start (or the loop start) |

## Keyboard

| Key | Does |
|---|---|
| Space | Play / stop |
| R | Record |
| 1–8 | Arm a track |
| ← / → | One grid step (Shift: one bar), also `[` / `]` for a bar |
| H | Back to the start |
| G | Change the grid |
| + / − | Zoom in / out |
| I | Input mode |
| E | Export |
| L | Loop on / off |
| { / } | Loop start / end at the playhead |
| C / Shift+C | Lift (this track / all tracks) |
| V / Shift+V | Drop (replace / insert) |
| X / Shift+X | Cut (this track / all tracks) |
| S / Shift+S | Splice (this track / all tracks) |
| U | Undo |
| M | Mute the armed track |
| 9 / 0 | Armed track volume down / up |
| Q | Quit (ignored when the app starts at boot) |

## Syncing with the OP-XY

Console follows the MIDI clock from the first other MIDI device it finds (the
OP-XY), so turn on the OP-XY's USB MIDI clock output. Then:

- When the OP-XY is stopped, Console takes its tempo (the top right shows
  "SYNC").
- Pressing play on the OP-XY starts Console from the start; stop stops it.
- Press RECORD on Console first, and the recording starts exactly when you
  press play on the OP-XY.

To follow a different device, put its name in `~/console-data/settings.json`,
for example `{"clock_device": "OP-XY"}`.
