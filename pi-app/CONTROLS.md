# Controls

Everything works from the control board, and nearly everything from a
keyboard too: a keyboard plugged into the Pi, or keys typed into the SSH
window that's running the app.

## Keys on the board

| Key | Press | With SHIFT held |
|---|---|---|
| AUDIO | Input: all inputs to tracks 1–8, or inputs mixed onto the armed track | |
| MIDI, FX, FILE, IMPORT | Not yet (coming in a later version) | |
| SPLICE | Remove the region and close the gap (the rest moves earlier). The removed bit goes on the clipboard | Same, on all tracks |
| CUT | Take the region off the track onto the clipboard, leaving silence | Undo |
| LIFT | Copy the region onto the clipboard (the track stays as it is) | Copy it from all tracks |
| DROP | Paste the clipboard onto the armed track at the playhead, replacing what's there | Insert it, pushing the rest later |
| LOOP | Loop on / off (the first time, loops 4 bars from the current bar) | Clear the in/out points |
| EXPORT | Export stems and a stereo mix to Exports | |
| RECORD | Record on / off. When the OP-XY's clock is coming in and the tape is stopped: get ready, and recording starts when you press play on the OP-XY | Switch between REPLACE and OVERDUB |
| SHIFT | Hold for the second column | |
| PLAY | Play / stop | Back to the start (or the IN point) |
| ← / → | Move one grid step | Set the IN / OUT point at the playhead |
| 1–8 | Arm that track. Press the armed track again to zoom it big (see below) | Mute / unmute that track |

**The region** that SPLICE, CUT and LIFT work on is between the IN and OUT
points (the loop), if they're set, or else the bar under the playhead.

**Between tracks:** arm a track, LIFT (or CUT), arm another track, move the
playhead, DROP. Copying from all tracks and dropping puts each track back on
its own track.

## In / out points, replace and overdub

- SHIFT+← sets IN, SHIFT+→ sets OUT. LOOP plays round between them.
- With IN/OUT set, recording only writes between them (punch in / out),
  even if you hold RECORD across the whole thing.
- RECORD with SHIFT switches the record mode (shown at the bottom left):
  - **REPLACE** records over what's there.
  - **OVERDUB** adds to what's there. With the loop on, every time round the
    loop adds another layer, so you can loop a bar, hit record and keep
    playing parts in. It's gently tape-saturated so stacking layers doesn't
    clip harshly.
- SHIFT+CUT (undo) takes back a whole recording pass, or the last edit.
  It remembers 8 steps.

## Zooming into one track

Press the armed track's key again (or `F` on a keyboard) and that track grows
to fill the screen while the others slide away. Underneath it, a pair of
tape reels turn while it plays, with the track's volume, record mode, in/out
points and what's on the clipboard. Everything works the same in this view.
Press the track's key again to go back to all 8; press a different track's
key to zoom to that one instead.

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
| { / } | IN / OUT point at the playhead |
| K | Clear the in/out points |
| O | Replace / overdub |
| F | Zoom the armed track in / out |
| C / Shift+C | Copy (this track / all tracks) |
| V / Shift+V | Paste (replace / insert) |
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
