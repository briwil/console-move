# Project notes (start here)

This file is for picking the project up again, whether that's me (Brian) later, or a new
helper (person or AI) who hasn't seen any of the earlier conversations. It covers what
the project is, how the code fits together, what's been decided and why, how the Pi
is set up, and what's still open. What each control does is in
[pi-app/CONTROLS.md](pi-app/CONTROLS.md), and installing and running is in
[pi-app/README.md](pi-app/README.md).

## Working with Brian

- Brian is a beginner at coding. Explain things plainly, give terminal commands **one at
  a time**, and don't assume he owns a tool (soldering gear, meters and so on). Ask him.
- Check with him before building things he didn't ask for.
- The project is just for him, so licences don't matter. Still keep the name "Console":
  no mention of the Thingstone Track8, which it's modelled on.
- Changes are pushed straight to `main` on `briwil/console` (a private repo). The Pi
  updates itself from GitHub: **SETTINGS → SOFTWARE UPDATE**, PLAY to check, PLAY again
  to install.

## What it is

A DIY 8-track tape-style recorder and arranger, like an OP-1's tape crossed with a
Track8:

- **Computer:** Raspberry Pi 5 (8 GB), hostname `console` (`console.local`). It boots
  straight into the app.
- **Screen:** Waveshare 7.9" HDMI (400×1280 panel, used as 1280×400 landscape).
- **Control board:** custom KiCad board (rev 0.1, made by JLCPCB) with a Pimoroni PGA2350
  running CircuitPython. It has 24 Kailh Choc keys and 11 EC11 knobs with pushes, and
  talks to the Pi as USB MIDI ("Console Controls", channel 16). See `firmware/` and `hardware/`.
  Rev 0.2 (`hardware/v2/`, not built yet) splits it into keypad, keys and knob boards joined by
  ribbon cables, adding 6 keys (notes 24-29) and 16 step buttons (notes 48-63); the firmware's
  `BOARD = 2` reads it. The Pi app doesn't use the new notes yet.
- **Audio:** any USB audio device. Mostly that's an OP-XY in 8-channel mode (records all 8
  tracks at once). Headphones are on the screen's jack (HDMI audio).

## Code map (`pi-app/`)

| File | What it does |
|---|---|
| `console.py` | The app: main loop, key and knob routing (`Transport.key`, `Transport.knob`), status line, the drum page and the zoomed view's panel text. `Board` turns MIDI from the control board into key names. |
| `audio.py` | The engine (`Engine`): ALSA in and out (pyalsaaudio), the 8 tracks, recording, playback, loop, boxes and editing, undo, save and load, export, bounce, and the output resampler (`OutPort`). |
| `tape.py` | Draws the tape: lanes, waveforms (from `engine.levels`), boxes, ruler, grid and zoom. |
| `focus.py` | The one-track zoomed view (press the selected track's key again), with the tape reels panel. |
| `menu.py` + `layouts/menu.ui` | Project menu: NEW, LOAD (open, rename, delete), SAVE, SETTINGS (Link/sync, tempo, time signature, export format, input, output, Wi-Fi, software update). |
| `wifi.py` | Wi-Fi scan, connect and forget, through NetworkManager's `nmcli` (run with `sudo -n`). |
| `drums.py`, `drumparams.py`, `drums/` | The drum synth: Erica Synths LXR-02 firmware compiled for the Pi (`drums/build.sh` makes `libdrums.so` and `libdrums_live.so`). `drumparams.py` lists every page, knob, label and range. |
| `kitmenu.py` | Drum kits: SAVE and LOAD (the FILE key on the drum page). |
| `sequencer.py`, `seqpage.py` | The grid step sequencer (data and timing; and its screen page). |
| `linksync.py` | Ableton Link (the `aalink` package). |
| `midi.py` | MIDI in and out: the control board, and clock sync with the OP-XY. |
| `effects.py`, `fx/fx.c` | Send reverb and delay (from Mutable Instruments code, compiled by `setup.sh`). |
| `updater.py` | SOFTWARE UPDATE: `git pull` from GitHub. |
| `ui.py`, `layouts/main.ui` | Draws screens made with `tools/screen-designer.html`. |
| `web/` | The file page at http://console.local (download and upload songs, samples, exports). |
| `setup.sh` | One-time install on the Pi: packages, aalink, builds the drums and effects. |
| `splash/`, `*-boot.sh`, `console.service` | Boot logo, boot-to-app service, quiet boot. |

Data lives in `~/console-data/` on the Pi: `projects/<song>/` (`track1.wav`…`track8.wav`,
24-bit, plus `project.json`), `exports/`, `kits/`, `settings.json` and `console.log`.

## How the main parts work

### Tape and boxes

- Each track is **one long mono WAV**, as long as the tape (5 minutes by default).
- Recordings show as **boxes** on top of the audio. A box is
  `[start, end, colour, gain dB, fade in, fade out]` (frames), in `engine.regions[track]`,
  saved in `project.json`. Older 3-number boxes still load.
- SPLICE splits or joins boxes. LIFT copies, CUT cuts, DROP pastes, DROP_INSERT pushes
  later audio along. Edits work on whole boxes. Undo keeps 8 steps of saved samples plus box lists.
- **Box gain and fades are never written into the WAV.** Playback (`envelope()`), the
  waveform (`_update_levels`), export, bounce and the clipboard (`shape_range()`) apply
  them. They're only "baked" into the audio in two cases: when you overdub onto such a
  box, and when you join two boxes with different gains.
- Every box edge with nothing next to it gets a 1 ms fade (`GUARD`), and DROP fades its
  seams (`_seam`), so edits don't click.
- **Recording timing:** the engine plays `read_ahead` frames ahead and writes recordings at
  `pos − (latency − read_ahead)`, so overdubs line up with what you heard.
  `latency_frames` in `settings.json` adjusts it.
- Stereo pairs: two neighbouring tracks, in `engine.pairs`, that edit and export together.

### Drum synth

- The LXR's six voices: DRUM 1–3, SNARE, CYMBAL, HI-HAT (closed and open), played by
  track keys 1–7 on the drum page (the MIDI key).
- **Two copies of the engine** run: one for the sequencer and one for playing by hand.
  The sequencer's sound is delayed by `read_ahead` through a FIFO, so it records in time.
- Parameters 248–259 are Console's own (the per-voice reverb and delay sends), on top of
  the LXR's.
- The snare has a separate noise decay (param 247). VEL>VOL is on in the Init kit.
- Input modes: MULTI (each voice to its own track), STEREO (kit to a pair), MONO.

### Drum machines (LXR-02, TR-606, TR-808)

- `drums.Drums` holds the song's machine and passes everything on to it:
  - `LXR` is the LXR-02;
  - `Schwung("606")` and `Schwung("808")` are 6W6 (charlesvestal/schwung-6W6) and 8W8
    (athousanddetails/schwung-8W8), vendored in `drums/schwung/606` and `808`.
- `drums/schwung/glue606.cpp` and `glue808.cpp` compile each whole engine with a per-voice render
  (`render_voices`). That way Console gets one channel per voice for MULTI, and does the panning and
  effects itself; the engines' own FX and master stage are skipped.
- Their settings and pages are read at run time from the machines' own headers
  (`*_chain_params_json`, `*_ui_pages_json`), so updating the vendored code keeps them in step.
- **Lanes vs voices:**
  - Lanes are what keys play: LXR 7, 606 8, 808 16 (SHIFT + keys = lanes 9–16).
  - `lane_voice` maps each lane to a voice; the 808's lane order puts the common drums on keys 1–8.
  - MULTI: lane n records onto track n % 8.
- **Saved with the song:** the machine is per song (`drum_machine`, plus `drum_kits` for every machine
  used). Kits live in `kits/`, `kits/606/` and `kits/808/`.
- **Patterns:** each machine has its own `Sequencer` in the song (`engine.seqs`, saved as `drum_seqs`
  plus `drum_seq` for the current one), and every pattern keeps 16 lanes.
- The machine is picked from the drums menu (FILE on the drum page, `kitmenu.py`: DRUM MACHINE).
- Built by `setup.sh` (needs g++), or by `drums.py` in the background at start.

### Stereo tracks and per-track inputs (Oct 2026)

- Each track is mono or stereo (`Engine.stereo`) with its own input (`Engine.inputs`: a channel,
  "mix", or [left, right]); the AUDIO key's MULTI/STEREO/MONO modes and the two-track stereo pairs
  are gone (Brian's choice). Set in the zoomed view, knobs 1-3 (box gain / fades on 4-6).
- A stereo track's right channel is `tracks[t + RIGHT]` (RIGHT = 8) with its own boxes
  `regions[t + RIGHT]`, kept in step: `chans(t)` is [t] or [t, t + 8], and edits, recording,
  undo and levels work on channels. Saved as a 2-channel track N.wav; old songs' pairs convert to one
  stereo track. DROP folds stereo to mono / doubles mono; bounce onto a stereo track is stereo.
- The instruments as an input: SLOT_CH = 11 channels per slot (88 in all): 0-7 its lanes (DRUM n, dry
  with sends copied), 8-9 the kit in stereo with its reverb and delay printed (KIT L/R), 10 the kit mono
  (KIT). Slot 1's are 0-10, so older songs' drum inputs still point at the same things. A mono track's
  MIX is ALL KITS. Names say the machine: 606 DRUM 3, MD KIT L+R.

### INSTRUMENTS page (Oct 2026)

- Brian's design: the MIDI key from the tape opens `instpage.py`, 8 slots (`Engine.slots`, machine ids
  or None; `slot` = the one the drum and sequencer pages show; `slot_mutes`). Push knob 1 opens or
  picks, SHIFT+push changes / removes, track keys mute, SHIFT+MIDI (`DRUMS_BACK`) goes back a page.
  MIDI on the drum page toggles drum page / sequencer. Each machine in one slot only (each library is
  one engine). Arranging is done on the tape (record each pattern, then edit), not on this page.
- `Drums.get(machine)` starts a machine without switching to it; `use()` is the shown one. A machine's
  `render(with_live=False)` still applies settings changes (only hits by hand wait).
- `Engine._instruments_block`: each sounding slot renders its own sequencer (shared `seq_clock`) into
  its 11 channels, with its own printed FX (`_slot_fx`) and read-ahead FIFO (`_seq_fifos`).
  `sounding_slots()`: on the instrument pages (`inst_view`, set each tick) every unmuted slot, and the
  tape isn't mixed; on the tape page only the slots armed tracks record from. The shown slot also
  renders its live engine (hits by hand) on the instrument pages.
- Saved as "slots", "slot", "slot_mutes"; songs without them get their drum_machine in slot 1. Kits
  and patterns stay per machine (drum_kits / drum_seqs), so a removed machine comes back as it was.

### Schwung modules (Oct 2026)

- `schwung/`: a generic host for Schwung's plugin API v2 (`host.c` -> `libschwunghost.so`, ctypes in
  `modules.py`). `catalog.py` pins each module to a commit with a native gcc/g++ recipe from its own
  build script; `build.py` fetches (git fetch by SHA) and builds into `schwung/modules/<id>/` (gitignored).
  The app runs it niced in the background at start (`drums._prebuild` -> `modules.build_missing`), so
  setup.sh doesn't change (changing setup.sh makes the updater ask for SSH).
- `modules.Module` has drums.py's machine methods. Settings come from the module's runtime
  `chain_params` (else module.json); per-pad keys are `pad3_`, `v3_`, `pv3_` or a catalog prefix
  (CW-78's bd_, sd_...). `cv_*` (focused-voice copies), write-only actions, `ui_*`, note_map/midi are left
  out. Values are knob positions, sent as text. Pages: the pad's own (SOUND, 8 each), then the kit's in
  the module's ui_hierarchy order, the rest as MORE. A global int/enum change re-reads every value
  (a kit choice changes the rest).
- Pads are MIDI notes 36-51 (a Move drum rack). Two instances (dsp.so and a copy dsp_live.so), as the
  other machines. render_block is always 128 frames (sh_render keeps the remainder), so hits land on
  the next 128-frame block (<= 2.9 ms). Output is stereo only: voices columns 0/1 are L/R, pans()
  routes them, multi() is empty, sends are 0 (they have their own FX). Libpo32 renders hits on a
  worker thread, so it needs real time (silent if rendered faster than real time).
- Forge, Weird Dreams, CW-78, Simian and Libpo32 are in.

### Synths and the synth sequencer (Oct 2026)

- 19 synth modules (catalog kind "synth"); `modules.SynthModule`: pages are the module's own (no per-pad
  split), note_on / note_off / all_off; the sequencer's events carry each note's length as locks["gate"]
  (frames) and render() keeps notes held across blocks (`_held`), lets go before playing at the same
  frame. Live notes go to the second copy and are let go by key release (Board -> Transport.pad_release)
  or the OP-XY's note-offs (midi.start(on_note=Transport.midi_note)).
- `notes.py` `NoteSequencer` (Brian: Deluge-style, each row a note of the scale, chords): patterns of
  {step: {MIDI note: Note(length, vel, chance, ratchet, locks)}}, one length / rate per pattern; root,
  scale (13) and `low` (lowest row on screen, in scale rows) per synth. Same methods the engine and
  pages use as the drum Sequencer. `Engine._seq_for` makes the right kind by `Engine.is_synth`.
- `synthpage.py`: the page (console.py's `sp()` picks it or seqpage for the shown slot). Keys: press puts
  the note on (and plays it), press on an existing note takes it off on release unless a knob turned;
  while playing, live_place + length from how long it was held. ← / → octave, SHIFT ← / → a row.
- The engine lets synths go (all_off) when playback stops or a slot stops sounding.
- JE-8086: CMake build (cmake from pip --user if missing), helper `jp8000-dsp` copied beside dsp.so, one
  copy only (catalog "one_copy"), `roms/` is a symlink to ~/console-data/roms/je8086 (the file page's
  ROMs tab). Its own error ("No JP-8000 ROM...") shows when its slot opens (`sh_module_error`).
- Model-72 is left out: its engine is Rust (no cargo on the Pi).

### MACHINEDRUM (Oct 2026)

- `drums/md/`: mmockett/OP-XY-MNMD's Machinedrum voices (TRX, EFM, P-I, GND; 33 machines; MIT), vendored
  by `drums/md/vendor.py` with three Open-XY SDK headers (MIT). `md_catalog.h` and `md_dispatch.h` are
  generated from its catalog. `glue_md.cpp` makes 16 lanes, each one voice of any machine, 64-sample
  blocks (hits land on the next block, <=1.5 ms), Q31 half scale = 1.0 at LEVEL 127.
- `drums.Machinedrum` (id `md`) subclasses `Schwung`: 12 settings per lane (MACHINE, 8 controls,
  LEVEL, REVERB, DELAY); labels and pages follow the lane's machine; changing MACHINE loads its
  defaults. All 16 lanes cost about 1.5% of a core here.
- Not done: E12 (needs ROM captures via OP-XY-MNMD's tools/capture_e12.py) and the Monomachine synths
  (need synth tracks).

### Lifting several tracks (Oct 2026)

- LIFT / CUT take the selected track's outline span from every audible track with a box there
  (`Engine.lift_tracks`; Brian chose "non-muted", OP-1 style). The clipboard keeps
  `clip_tracks`, `clip_pairs` and `clip_vols`.
- DROP of a multi-track clipboard asks SEPARATE / MERGED on screen (knob 1, DROP again;
  `Transport.drop_ask`). Separate: from the selected track down, packed together. Merged: a mono
  mix at the volumes heard, divided by the landing track's volume so it sounds the same.

### Drum effects printed (Oct 2026)

- Recording the drum synth in STEREO or MONO prints its reverb and delay sends into the take
  (`Engine._drum_input`, each instrument with its own reverb and delay at the FX page's settings). MULTI
  stays dry and copies each drum's sends onto its track (as before). Brian asked for printed.

### Sequencer (grid)

- Seven lanes (one per drum key) and 32 steps visible. Knob 1 moves the cursor, which
  scrolls at the 16th column. Hold a drum key to place steps and change them with the knobs.
- Pushing knob 1 cycles the knob modes: STEP, then the sound pages. In a sound mode,
  holding a step's key p-locks it (parameter locks, Elektron style).
- Each lane has an 8-step box (`SeqPage.box`): ← / → move the picked lane's box, SHIFT + track
  key 1-8 toggles that step of it on the picked lane. The 808's drums 9-16 are SHIFT + knob 1
  (the keys' bank). Brian's design, Oct 2026 (after trying and dropping a keys-are-steps version).
- Key 8 is undo (10 levels).
- 16 patterns. DRUMS menu (FILE): COPY / PASTE Pattern (the copy lives in `KitMenu.pattern_clip`,
  same machine only), CLEAR Pattern (a new empty one) and "clear locks + step settings". Each lane has its own
  rate (triplets too). Length follows bars and the time signature.
- While playing, the cursor is hidden and drum keys place steps live at the playhead.
- It runs on its own clock (`engine.seq_clock`, frames since PLAY), not the tape position: every PLAY
  starts at step 1 and tape loops don't reset it (Oct 2026, Brian). Its sound still records onto the
  tape exactly where it's heard.

### Drum page and the theme

- `drumpage.py` draws the drum page full screen, to Brian's Illustrator design (Oct 2026).
  - Settings run left to right like the knobs.
  - Numbers are line bars that peak at the value; choices are boxes with text.
  - The setting being turned is lime, with its value in place of its name.
  - The pages run along the bottom, and three red dots show while recording.
- Its colours, fonts and sizes come from `theme.py`. The defaults are in `pi-app/theme.json`,
  and Brian's edits in `~/console-data/theme.json`.
- The theme editor is `web/theme.html`, served by `web/server.py` at `/theme`:
  - edits save through `/api/theme`;
  - the app checks the theme files twice a second;
  - for the live picture, the page asks with `~/console-data/.screen-request`, and the app answers
    by saving `.screen.png` (`screen_picture` in console.py).
- To make Brian's downloaded theme the default, copy its values into `pi-app/theme.json`.

### Sync

- **MIDI:** follow the OP-XY's clock (recording waits for its play) or lead it.
- **Ableton Link** (SETTINGS → SYNC → LINK): follows tempo, starts on the next bar, and
  nudges the tape ±1 frame to stay in phase. A nudge during recording is filled in, so the
  recording stays one box.

### Menus and settings

- Hold-keys (CUT, LIFT) reach the menus as plain keys.
- Empty songs are removed automatically.
- Songs can be renamed with LIFT on the LOAD list.
- Text uses Roboto Condensed. `fonts/fonts.json` maps "sans" and "mono" to it; Inter and
  Plex Mono are still there.

## Pi setup (what's been done to Brian's Pi)

- `setup.sh`, `boot-to-app.sh`, `splash-setup.sh` and `web-setup.sh` have been run, and
  the hostname is `console`.
- **Power button:** EEPROM settings `WAIT_FOR_POWER_BUTTON=1` and `POWER_OFF_ON_HALT=1`,
  so the Pi stays off when power is plugged in and starts with the power button. The
  button is wired to the J2 pads next to the J5 battery connector.
- **Boot speed:**
  - `NetworkManager-wait-online` is disabled.
  - `vc4` is in the initramfs (`FRAMEBUFFER=y`, `auto_initramfs=1`) so the logo shows sooner.
  - On 25 Oct 2026, after those changes, boot took 1.7 s kernel + 4.9 s userspace, about
    8 s from the logo to the app.
  - Done on 25 Oct 2026:
    - The app service doesn't wait for the network.
    - cloud-init is disabled (`/etc/cloud/cloud-init.disabled`).
    - The app now starts 3.1 s after the kernel and its first picture is up at 7.1 s. The app
      logs `startup:` lines with the times: `journalctl -b -u console | grep startup`.
  - Tried and undone: having the app stop the animation later (just before it opens the
    screen, with `Type=notify`). Brian found the gap before the app longer, and the
    animation then also showed at shutdown.
- The GPIO header pins were **clipped** (not removed), to make room in the case.
- The screen's ribbon is an FPV-style 20-pin, 0.5 mm pitch cable, folded at 45°.

## Open items

- **Battery:** choosing a UPS/battery board that fits where the Pi sits in the case
  (Geekworm X1201 was the front-runner). Showing battery level in the app comes after.
- **Control board:** problems were reported with knob 9's push and key SW16. They
  haven't been diagnosed yet.
- Drum hits have no velocity from the keys yet (the board's keys aren't
  velocity-sensitive; the sequencer has velocity per step).
- IMPORT (samples) isn't built yet.

## Testing without the Pi

`tools/sim/` runs the app's real code on any computer, with stand-ins for pygame (it
draws to PNG with Pillow), the audio device and `nmcli`. Every change so far was tested
this way before going to the Pi:
- drive it with keys and knobs from a script;
- check the engine (audio, boxes, saved files);
- look at screenshots.

Start with `python3 tools/sim/example.py`, and see [tools/sim/README.md](tools/sim/README.md).
On the Pi itself: `sudo systemctl stop console`, then `pi-app/run.sh` over SSH. Messages
go to `~/console-data/console.log`.

## History

`git log` has every change with a description (the commit messages are written to be read).
