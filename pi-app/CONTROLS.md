# Controls

Everything works from the control board, and nearly everything from a
keyboard too: a keyboard plugged into the Pi, or keys typed into the SSH
window that's running the app.

## Project menu

The app starts on the project menu. Turn the big knob (or use the arrow
keys) to move, and press PLAY, push the big knob, or press Enter to choose.
FILE (Tab or Esc on a keyboard) goes back to the song.

- **NEW Project** saves the song you're on, then asks for the new project's
  name: it suggests the next free "Song N", so you can just press PLAY. To
  change it: the big knob picks the letter under the green mark, ← / → move
  along, CUT deletes a letter. On a keyboard just type, with Backspace and
  Enter. The project's folder is made straight away (it's on console.local
  under Projects), and the new song starts empty at the same tempo. The
  clipboard carries over, so you can lift a piece in one song and drop it in
  another.
- **SAVE Project** saves the song now. (It also saves by itself whenever you
  stop, and a moment after every edit.) A song from an older version that
  was never named asks for a name here, and then shows up in Projects.
- **SETTINGS:** the big knob (or ↑ ↓) picks a row, ← / → (or the right-hand
  small knob) change it.
  - **MIDI SYNC — EXTERNAL:** Console follows the OP-XY's clock, start and
    stop (see "Syncing with the OP-XY" below).
  - **MIDI SYNC — INTERNAL:** Console leads. It sends MIDI clock to the OP-XY
    all the time (so it takes Console's tempo), and start / stop when you
    play and stop Console. The top right shows LEAD.
  - **TEMPO:** the song's tempo (SHIFT+← / → for 0.1 steps). In external
    sync it comes from the OP-XY.
  - **EXPORT FORMAT:** what EXPORT writes: WAV, AIFF or FLAC (all 24-bit,
    FLAC about half the size) or M4A (AAC 256 kbps, smallest, for sharing).
    The song's own track files are always WAV.
- **LOAD:** coming next.

Console opens whichever project you used last. Every change is written to
the song's files (`projects/<song>/track1.wav`…) a moment after you make it,
so they're always up to date. EXPORT is for a separate copy (stems + a
stereo mix) in the Exports folder.

## Keys on the board

| Key | Press | With SHIFT held |
|---|---|---|
| AUDIO | Input: MULTI / STEREO / MONO (see Input modes below) | Arm all 8 tracks / back to just the selected one |
| FILE | Open / close the project menu | |
| MIDI, FX, IMPORT | Not yet (coming in a later version) | |
| SPLICE | Split the box under the playhead on the armed track(s). On a join between two boxes: join them | Same, on all tracks |
| CUT | Take the box under the playhead off the tape onto the clipboard, leaving an empty space. Hold to take several boxes (see below) | Undo |
| LIFT | Copy the box under the playhead onto the clipboard. Hold to copy several boxes | Start / stop selecting several boxes (no holding needed) |
| DROP | Drop the clipboard onto the armed track at the playhead, replacing what's there | Insert it, pushing the rest of the track later |
| LOOP | Loop on / off (the first time, loops 4 bars from the current bar) | Clear the in/out points |
| EXPORT | Export stems and a stereo mix to Exports | Bounce: the armed tracks onto the selected track (press twice) |
| RECORD | Record on / off. When the OP-XY's clock is coming in and the tape is stopped: get ready, and recording starts when you press play on the OP-XY | Switch between REPLACE and OVERDUB |
| SHIFT | Hold for the second column | |
| PLAY | Play / stop | Back to the start (or the IN point) |
| ← / → | Move one grid step | Set the IN / OUT point at the playhead |
| 1–8 | Select and arm that track (just that one). Press the selected track again to zoom it big (see below) | Arm / disarm that track as well, to record several at once |

## Recording several tracks at once

The selected track (thick outline) always records. Hold SHIFT and press
other track keys to arm them too (thin outline); SHIFT+AUDIO arms all 8.
Pressing a track key without SHIFT goes back to just that track.

In MULTI mode (the OP-XY in 8-channel mode), each armed track records its own input:
input 1 to track 1, input 2 to track 2, and so on. In MONO mode (AUDIO
switches), every armed track records all the inputs mixed together.

Editing (splice, lift, cut, drop) always works on the selected track.

## Boxes: splitting, lifting, cutting and dropping

Every recording shows up on its track as a rounded box in its own colour,
like a region in a DAW. Empty tape has no boxes.

- **SPLICE** splits the box under the playhead in two; the right half gets a
  new colour. It splits every armed track. SPLICE exactly on the join
  between two boxes joins them back into one. SHIFT+SPLICE: all tracks.
- The box under the playhead on the selected track has a white outline:
  that's what LIFT and CUT take.
- **One box:** tap LIFT (copy) or CUT.
- **Several boxes:** hold LIFT or CUT, move with ← / → or the big knob until
  they're all inside the outline, then let go. On a keyboard (or SHIFT+LIFT
  on the board), press `A`, move, then `C` or `X`. They're lifted as one
  piece, including any empty space between them.
- **CUT** leaves an empty space. The boxes either side stay as they are.
- After LIFT or CUT the playhead glides to where the box started; after DROP,
  to where the new box ends (ready to drop the next one after it).
- **DROP** puts the clipboard on the selected track at the playhead as a
  new box, covering what's there. SHIFT+DROP inserts it instead, pushing the
  rest of the track later (splitting a box it lands in the middle of).
- **Recording** makes a new box. In REPLACE mode it covers what was there;
  in OVERDUB mode it joins the box(es) it records over.
- SHIFT+CUT undoes, including splits and joins.

The boxes are only how the tape is divided up; what you hear is the audio on
the track. EXPORT writes each track as a plain WAV.

## Input modes

AUDIO (I on a keyboard) switches between them; the bottom right shows which.

| Mode | What the armed tracks record |
|---|---|
| MULTI | Each its own input: input 1 onto track 1, input 2 onto track 2… (the OP-XY's 8-channel USB mode) |
| STEREO | Left and right onto two tracks side by side, as a stereo pair |
| MONO | All the inputs mixed together, in mono |

## Stereo

Tracks are mono, and any two neighbouring tracks (1+2, 4+5, 7+8…) can be a
stereo pair.

1. Press AUDIO until the bottom right says STEREO (it starts in STEREO when
   the OP-XY is in its 2-channel USB mode).
2. Select a track and SHIFT+arm the one below it, e.g. 7 and SHIFT+8. The
   bottom right shows "STEREO > 7+8".
3. Record. Left goes onto 7, right onto 8. They become a pair: a bracket
   joins their numbers, they're panned left and right, and EXPORT writes them
   as one stereo file ("track7-8 stereo.wav").

A pair edits together: SPLICE splits both, and LIFT / CUT take both sides
(with either track of the pair selected). A stereo piece drops onto the
selected track and the one below it, which become a pair. An armed track
without a neighbour records left and right mixed, in mono.

Recording onto either track of a pair on its own (in MONO or MULTI mode,
or in STEREO with only that one armed) splits the pair back into two normal
mono tracks, panned to the centre. SHIFT+CUT undoes that along with the
recording.

**Pan:** SHIFT + turn a track's knob, or `,` / `.` on a keyboard for the
selected track. Any track can be panned; the stereo mix and what you hear
follow it. A bounce is mono, in the centre.

## Mute and solo

Push a track's knob to mute it; SHIFT+push to solo it. While any track is
soloed, only soloed tracks play (the others' tabs go grey). Solo more than
one to hear a few together. EXPORT ignores solo and uses the mutes.

## Bouncing tracks together

Like on the OP-1: mix tracks down onto one track to free the others.

1. Select the track to bounce onto (e.g. press 2).
2. Arm the tracks to bounce into it with SHIFT+track (e.g. SHIFT+1).
3. Press SHIFT+EXPORT (B on a keyboard). It asks first; press it again.

The tracks are mixed as you hear them (at their volumes) onto the selected
track, whose volume goes to 100% so it sounds the same, and the other tracks
are emptied. SHIFT+CUT undoes it. Stop first; it doesn't work while playing.

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
- In/out points are only for recording and playback; editing uses boxes.
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
| 1–8 (above the tracks) | Track volume (with SHIFT: pan) | Mute / unmute (with SHIFT: solo / unsolo) |
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
| S / Shift+S | Split / join boxes (armed tracks / all tracks) |
| C | Lift (copy) the box |
| X | Cut the box |
| A | Start / stop selecting several boxes |
| V / Shift+V | Drop (replace / insert) |
| U | Undo |
| B | Bounce the armed tracks onto the selected track (press twice) |
| M | Mute the selected track (Shift+M: solo it) |
| 9 / 0 | Armed track volume down / up |
| , / . | Pan the selected track left / right |
| Tab or Esc | Project menu |
| Q | Quit (ignored when the app starts at boot) |

## Syncing with the OP-XY

This is EXTERNAL sync (the default; change it in SETTINGS). Console follows the MIDI clock from the first other MIDI device it finds (the
OP-XY), so turn on the OP-XY's USB MIDI clock output. Then:

- When the OP-XY is stopped, Console takes its tempo (the top right shows
  "SYNC").
- Pressing play on the OP-XY starts Console from the start; stop stops it.
- Press RECORD on Console first, and the recording starts exactly when you
  press play on the OP-XY.

To follow a different device, put its name in `~/console-data/settings.json`,
for example `{"clock_device": "OP-XY"}`.
