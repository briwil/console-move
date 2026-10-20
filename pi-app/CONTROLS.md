# Controls

Everything works from the control board, and nearly everything from a
keyboard too: a keyboard plugged into the Pi, or keys typed into the SSH
window that's running the app.

## Project menu

The app starts on the project menu. Turn the big knob (or use the arrow
keys) to move, and press PLAY, push the big knob, or press Enter to choose.
FILE (Tab or Esc on a keyboard) goes back to the song.

- **NEW Project** saves the song you're on and opens a blank, untitled
  song (same tempo). If the song you're on was never saved with a name and
  has audio, it warns you first: press NEW again to throw it away. The
  clipboard carries over, so you can lift a piece in one song and drop it in
  another.
- **SAVE Project** saves the song. The first time, it asks for a name: it
  suggests the next free "Song N", so you can just press PLAY. To change it:
  the big knob picks the letter under the green mark, ← / → move along, CUT
  deletes a letter. On a keyboard just type, with Backspace and Enter.
  (The app also saves by itself whenever you stop; an untitled song is kept
  in `~/console-data/unsaved` until you name it.)
- **LOAD, SETTINGS:** coming next.

Console opens whichever project you used last.

## Keys on the board

| Key | Press | With SHIFT held |
|---|---|---|
| AUDIO | Input: each input to its own track (OP-XY 8-channel), or all inputs mixed together | Arm all 8 tracks / back to just the selected one |
| FILE | Open / close the project menu | |
| MIDI, FX, IMPORT | Not yet (coming in a later version) | |
| SPLICE | Cut the tape at the playhead on the armed track(s). On an existing splice: take it away | Same, on all tracks |
| CUT | Take the piece under the playhead off the tape onto the clipboard, leaving a gap. Hold to take several pieces (see below) | Undo |
| LIFT | Copy the piece under the playhead onto the clipboard. Hold to copy several pieces | Start / stop selecting several pieces (no holding needed) |
| DROP | Drop the clipboard onto the armed track at the playhead, replacing what's there | Insert it, pushing the rest of the track later |
| LOOP | Loop on / off (the first time, loops 4 bars from the current bar) | Clear the in/out points |
| EXPORT | Export stems and a stereo mix to Exports | |
| RECORD | Record on / off. When the OP-XY's clock is coming in and the tape is stopped: get ready, and recording starts when you press play on the OP-XY | Switch between REPLACE and OVERDUB |
| SHIFT | Hold for the second column | |
| PLAY | Play / stop | Back to the start (or the IN point) |
| ← / → | Move one grid step | Set the IN / OUT point at the playhead |
| 1–8 | Select and arm that track (just that one). Press the selected track again to zoom it big (see below) | Arm / disarm that track as well, to record several at once |

## Recording several tracks at once

The selected track (thick outline) always records. Hold SHIFT and press
other track keys to arm them too (thin outline); SHIFT+AUDIO arms all 8.
Pressing a track key without SHIFT goes back to just that track.

With the OP-XY in 8-channel mode, each armed track records its own input:
input 1 to track 1, input 2 to track 2, and so on. In mix mode (AUDIO
switches), every armed track records all the inputs mixed together.

Editing (splice, lift, cut, drop) always works on the selected track.

## Splices and pieces (like the OP-1)

SPLICE cuts a track's tape at the playhead, shown as a white line with
notches. The splices divide the track into pieces; the piece under the
playhead on the armed track is lit up, and that's what LIFT and CUT take.
With no splices, the whole track is one piece.

- **One piece:** tap LIFT (copy) or CUT.
- **Several pieces:** hold LIFT or CUT, move with ← / → or the big knob
  until everything you want is lit up, then let go. On a keyboard (or with
  SHIFT+LIFT on the board), press `A`, move, then `C` or `X`.
- Several pieces are lifted as **one piece**: the splices between them go,
  and it drops back as one piece.
- **DROP** puts the clipboard on the armed track at the playhead, with a
  splice at each end, so it's its own piece. Drop on another track to move
  things between tracks. SHIFT+DROP inserts it instead of replacing.
- CUT leaves a gap where the piece was, and its splice marks go with it.
- SPLICE on a splice takes it away, joining the two pieces.
- SHIFT+CUT undoes, including splices.

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
- In/out points are only for recording and playback; editing uses splices.
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
| 1–8 (above the tracks) | Track volume (with SHIFT: fine steps) | Mute / unmute (the only way to mute on the board) |
| Left of the right-hand three | Zoom | Zoom back to 4 bars |
| Right of the right-hand three | Grid: 1/4, 1/8, 1/16, 1/32 | Loop on / off |
| Big knob | Move the playhead by grid steps (with SHIFT: by bars) | Back to the start (or the loop start) |

## Keyboard

| Key | Does |
|---|---|
| Space | Play / stop |
| R | Record |
| 1–8 | Select and arm a track |
| Shift+1–8 (! @ # …) | Arm / disarm another track as well |
| ` | Arm all tracks / just the selected one |
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
| S / Shift+S | Splice (this track / all tracks) |
| C | Lift (copy) the piece |
| X | Cut the piece |
| A | Start / stop selecting several pieces |
| V / Shift+V | Drop (replace / insert) |
| U | Undo |
| M | Mute the armed track |
| 9 / 0 | Armed track volume down / up |
| Tab or Esc | Project menu |
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
