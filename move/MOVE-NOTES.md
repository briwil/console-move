# Console on the Ableton Move

This repo started as a copy of `briwil/console` (the Pi 5 version). This folder holds everything
specific to running it on an Ableton Move.

## The Move (as found, Nov 2026)
- Move firmware 2.1.1 — do not update.
- 64-bit ARM (aarch64), glibc Linux with BusyBox tools (no `head -5`; use `head -n 5`).
- 1.8 GB RAM. System partition is nearly full: put everything in `/data/UserData`.
- Python 3.10 is installed; no pip, no numpy, no pygame. Has internet over Wi-Fi.
- SSH: `ssh ableton@move.local`. The Mac's `~/.ssh/config` uses `~/.ssh/move_key` for move.local;
  that public key is the one saved at `http://move.local/development/ssh`.
- `ps` only shows your own processes.

## Audio / controls / screen
RNBO Move Takeover (Cycling '74) is installed. It includes a custom JACK (`/data/UserData/rnbo/bin/jackd -d move`,
libs in `/data/UserData/rnbo/lib`) whose Move driver exposes:
- `system:capture_1/2`, `system:playback_1/2` — stereo, 16-bit, 44100 Hz, fixed 128-sample buffer.
- `system:midi_capture` / `system:midi_playback` — the Move's own controls and lights, MIDI channel 16.
- `system:midi_capture_ext` / `system:midi_playback_ext` — USB MIDI gear.
- `system:display` — send one MIDI event of 1032 bytes: `MOVEDISP` + 1024 bytes.
  Screen is 128 x 64, 1 bit: 8 strips of 128 bytes, each byte 8 pixels going down (bit 0 = top).

Control map (all channel 16):
| Control | Message |
|---|---|
| Pads | notes 68-99, velocity = how hard. 68-75 is the bottom row (left to right), 92-99 the top |
| Knobs 1-8 turn | CC 71-78; 1 = one click right, 127 = one click left |
| Knob touch | notes 0-9, 127 touched / 0 released |
| Step buttons | notes 16-31 |
| Left-side buttons | CC 43 (top), 42, 41, 40 (bottom); 127 / 0 |
| Volume knob | CC 79 (touch: note 8) |
| Jog wheel | turn CC 14 (1 = right, 127 = left), press CC 3, touch note 9 |
| Buttons (CC, 127 down / 0 up) | Play 85, Record 86, Sample 118, Loop 58, Shift 49, Menu 50, Back 51, Capture 52, Undo 56, Copy 60, Delete 119, Mute 88, + 55, - 54, left 62, right 63 |
| Jacks (plug detect) | CC 114: mic 0 / line in 127; CC 115: speaker 0 / line out 127 |
Pad lights: note on, channel 16, note = pad, velocity = colour (127 worked); 0 = off.
(Button numbers and names confirmed on the Move with move/buttons_test.py.)

## Console mode (no RNBO)
RNBO's manager (`rnbomovecontrol`) unplugs anyone else from the screen and pads, so we replace it.
`RNBOLauncher` here is a modified copy of `/data/UserData/rnbo/bin/RNBOLauncher` (original kept on the Move as
`RNBOLauncher.orig`). If `/data/UserData/console/ENABLED` exists, choosing RNBO in the Move's settings
(Shift + Step 2, bottom of the list) starts JACK and the Console app (log: console/app.log); when the app ends
(Shift + Back) the launcher stops and the Move goes back to normal. Also `touch /data/UserData/console/STOP` ends it and
the Move goes back to normal (the app's Shift + Back does this too, after saving). `rm /data/UserData/console/ENABLED` brings RNBO back.

Our programs can't get real-time priority or lock memory (warnings at start); so far that has been fine
(345 audio cycles a second, no dropouts heard).

## Files
- `move_test.py` — hardware test: tone per pad, pad lights, screen text, prints every control message.
  `python3 /data/UserData/move_test.py`
- `RNBOLauncher` — the launcher above. `move-update.py` installs changes to it (once the original is saved as .orig).
- `screen_mockups.py` / `screen-mockups.png` — first screen design proposal (recorder, drum list, drum knob turn).

## The C sound core (pi-app/core)
`core.c` is a JACK client whose process callback makes the sound, 128 frames at a time: instruments (as
"sources"), effects, the Move's controls in, lights and screen out. Python (`core.py`, `instruments.py`) sets
it up and sends timed events; it never runs in the audio path. Measured on the Move: LXR + Dexed + Plaits +
Braids jamming = 8-9% JACK load (the Python engine needed ~61% for the same). Pads feel immediate.
Events can arrive in any order (steps sent ~100 ms ahead, pad hits for now): the core sorts them by frame.
Tests: `move/core_test.py` (pads), `move/seq_test.py` (the real sequencer; `quiet` = pads only).

## Updating
- From the Mac, in one go: `bash ~/update-move.sh` (Pi builds, Mac copies, Move unpacks).
- On the Move itself: `python3 /data/UserData/console/move/move-update.py` downloads the latest from GitHub and
  builds the sound core and effects with Zig (installed once with `... move-update.py setup` into
  /data/UserData/zig). Needs a GitHub fine-grained access key, read-only "Contents" on console-move only,
  saved in /data/UserData/console/github-token. It also installs numpy/Pillow (pip --user) if missing and downloads
  the synths, drum machines and other libraries that GitHub builds (`.github/workflows/move-libs.yml`, the
  "libs-latest" release; Actions > Build Move libraries > Run workflow to rebuild by hand, 1-3 hours).
- After a factory restore: install RNBO, `mkdir -p /data/UserData/console`, save the token in
  `console/github-token`, fetch `move/move-update.py` (see below), then run it. No Pi needed.

## The app's controls (move/app.py)
- Left buttons, top to bottom: 1 instruments (again: the drum's sound, again: its sequencer); 2 song mode
  (move/movesong.py); 3 FX; 4 the recorder (the tape; again: the selected track zoomed: knob 1 mono / stereo,
  2 its input, 4-6 the box under the playhead).
- Drum pads: left 4 x 4 the drums (bottom left first), right 4 x 4 the picked drum chromatically (its TUNE /
  PITCH setting locked, SEMI clicks a semitone). Shift + pad 1-16: the instrument's pattern.
- Drum sequencer (move/moveseq.py): step buttons = 16 steps (<- / -> for 17-64), tap on / off; knobs 1 length,
  2 rate, 3 euclid, 4 shift; + / - the pattern. Shift + tap steps: select them; the pads are then their step
  settings (OP-XY style: velocity, chance, multiply, pulse, hold, jump, random, ramp up / down, then the drum's
  sound locks); tap a pad = on (knob 1 sets it), again = off; tap a step = done. Pulse / hold / jump / pitch
  play in pi-app/sequencer.py (Step.comp, _path / _slot).
- Song mode: rows of a pattern per instrument and a repeat count; step buttons = rows, knobs 1-7 patterns,
  8 repeats, + / - on / off. Saved in data/songmode/<song>.json.
- Menu: the project menu (SETTINGS > SOFTWARE UPDATE: move/moveupdater.py runs move-update.py, then the app
  exits with 75 and RNBOLauncher starts it again). Shift + Menu: export.
- Shift + Back: save, quit and hand the Move back.
