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
| Left-side buttons | CC 40-43, 127 / 0 |
| Volume knob | CC 79 (touch: note 8) |
| Jog wheel | turn CC 14 (1 = right, 127 = left), press CC 3, touch note 9 |
| Buttons (CC, 127 down / 0 up) | Play 85, Record 86, Sample 118, Loop 58, Shift 49, Menu 50, Back 51, Capture 52, Undo 56, Copy 60, Delete 119, Mute 88, + 55, - 54, left 62, right 63 |
| Jacks (plug detect) | CC 114: mic 0 / line in 127; CC 115: speaker 0 / line out 127 |
Pad lights: note on, channel 16, note = pad, velocity = colour (127 worked); 0 = off.
(Button numbers confirmed by pressing each; names from the move-anything project's control list.)

## Console mode (no RNBO)
RNBO's manager (`rnbomovecontrol`) unplugs anyone else from the screen and pads, so we replace it.
`RNBOLauncher` here is a modified copy of `/data/UserData/rnbo/bin/RNBOLauncher` (original kept on the Move as
`RNBOLauncher.orig`). If `/data/UserData/console/ENABLED` exists, choosing RNBO in the Move's settings
(Shift + Step 2, bottom of the list) starts only JACK and waits; `touch /data/UserData/console/STOP` ends it and
the Move goes back to normal. `rm /data/UserData/console/ENABLED` brings RNBO back.

Our programs can't get real-time priority or lock memory (warnings at start); so far that has been fine
(345 audio cycles a second, no dropouts heard).

## Files
- `move_test.py` — hardware test: tone per pad, pad lights, screen text, prints every control message.
  `python3 /data/UserData/move_test.py`
- `RNBOLauncher` — the launcher above.
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
  saved in /data/UserData/console/github-token. The drum machines and synths stay as built on the Pi
  (`build-for-move.sh`, full) until they need rebuilding.
