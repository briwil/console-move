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
  - **SYNC — EXTERNAL:** Console follows the OP-XY's clock, start and
    stop (see "Syncing with the OP-XY" below).
  - **SYNC — INTERNAL:** Console leads. It sends MIDI clock to the OP-XY
    all the time (so it takes Console's tempo), and start / stop when you
    play and stop Console. The top right shows LEAD.
  - **SYNC — LINK:** Ableton Link, over the Pi's network (Wi-Fi or
    cable), with Ableton Live, phone apps and anything else with Link.
    Tempo: when Console joins, it takes the others' tempo (on its own, its
    tempo leads); a tempo you set while stopped goes to everyone. While the
    tape plays it keeps its tempo (its audio can't stretch), so a tempo
    change from someone else is taken when you stop. PLAY starts everyone,
    on the next bar, and Console starts from the start of the playhead's bar
    so the bars line up; anyone else starting or stopping starts or stops
    Console. RECORD while stopped starts recording on that next bar. The top
    right shows LINK and how many others are connected. Needs
    `~/console/pi-app/setup.sh` run once (it installs Link).
  - **TEMPO:** the song's tempo (SHIFT+← / → for 0.1 steps). In external
    sync it comes from the OP-XY.
  - **EXPORT FORMAT:** what EXPORT writes: WAV, AIFF or FLAC (all 24-bit,
    FLAC about half the size) or M4A (AAC 256 kbps, smallest, for sharing).
    The song's own track files are always WAV.
  - **TIME SIGNATURE:** 2/4 to 7/4, and 5/8, 6/8, 7/8, 9/8, 12/8. It moves
    the bar lines, the clock (bar.beat.16th), SHIFT+arrow bar moves and the
    first loop. The tempo is always in quarter notes. Saved with the song.
  - **INPUT:** which USB audio device Console records from (the OP-XY, a
    RØDE, an audio interface…), or DRUM SYNTH, the built-in drums (see Drum
    synth below). Until you pick one, it uses the first one it
    finds. If the one you picked is unplugged, it records from another one
    and says so here, and switches back by itself when it's plugged in again.
    The tape runs at 44.1 kHz, so record from devices that can do 44.1 kHz
    (the OP-XY does); as an OUTPUT, any rate works.
  - **OUTPUT:** where you hear the tape: **HEADPHONES** (the jack on the
    screen; its sound comes from the Pi over HDMI), or any USB audio device
    with an output that's plugged in (the OP-XY, an audio interface…).
    Until you pick one, it plays on the input device if it has an output,
    otherwise on the headphones. If the one you picked isn't plugged in, it
    plays on the other and says so here. SHIFT + knob 10 sets the headphone (or USB headphone adapter)
    volume (it shows the level while you turn it). With nothing plugged in
    at all, the tape still plays on the headphones; it just can't record.
  - **WI-FI:** shows the network the Pi is on. Press PLAY to see the networks
    nearby (strongest first, with signal strength; CONNECTED, SAVED or OPEN
    beside the name). Big knob or arrow keys pick one; PLAY connects. A saved or
    open network connects straight away; a new one asks for its password: type
    it with the big knob (letters, numbers and symbols) or a USB keyboard, then
    PLAY. LIFT looks again, CUT twice forgets a saved network, FILE goes back.
  - **SOFTWARE UPDATE:** press PLAY to check GitHub for a new version. If
    there is one, it shows what's new; press PLAY again to install it. The
    app then restarts by itself (your song is saved first). It needs the
    internet and the GitHub login the Pi already uses for `git pull`:
    - "GITHUB LOGIN NEEDED": the Pi has to remember the login. Over SSH, run
      `git config --global credential.helper store`, then
      `cd ~/console && git pull` once and type your GitHub name and token.
      After that the update button works on its own.
    - "FILES ON THE PI WERE CHANGED BY HAND": a file in `~/console` was
      edited on the Pi. `cd ~/console && git status` shows which;
      `git checkout -- <file>` puts it back.
    - If an update says it needs `setup.sh`, run `~/console/pi-app/setup.sh`
      once over SSH, then press PLAY to restart.
    - A new start-up animation needs `~/console/pi-app/splash-setup.sh` run
      once, then a reboot.
- **LOAD:** your songs, newest first, with when each was last changed. The
  big knob picks one, PLAY opens it (the song you're leaving is saved
  first). LIFT renames the picked song (naming works as for NEW; the open
  song can be renamed too). CUT deletes the picked song (press it twice; the
  open song can't be deleted). FILE goes back.

A song with nothing in it (no audio, no sequencer steps, the drum kit as a
new song has it) is removed when you leave it, so empty songs from NEW
don't pile up, and NEW's next "Song N" name is the lowest free one.

Console opens whichever project you used last. Every change is written to
the song's files (`projects/<song>/track1.wav`…) a moment after you make it,
so they're always up to date. EXPORT is for a separate copy (stems + a
stereo mix) in the Exports folder.

## Keys on the board

| Key | Press | With SHIFT held |
|---|---|---|
| AUDIO | Input: MULTI / STEREO / MONO (see Input modes below) | Arm all 8 tracks / back to just the selected one |
| FILE | Open / close the project menu | |
| FX | Effects pages: REVERB, then DELAY, then back to the tape (see Effects below) | |
| MIDI | The drum synth: opens the drum page (track keys 1–7 play the drums) and makes it the input. Again: the sequencer. Again: back to the tape (see Drum synth and Drum sequencer below) | |
| IMPORT | Not yet (coming in a later version) | |
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

**Quick in/out sweep: SHIFT + knob 9.** Turn it and the playhead jumps a bar per click
from where it was (snapped to the nearest bar line). The in and out points stretch from
that starting bar to where the playhead is now:
- turning right, the start is the IN point and you set the OUT;
- turning left, the start is the OUT point and you set the IN.

Pause for 2 seconds and the next turn starts a new sweep from the playhead.
**SHIFT + push knob 9** undoes the last sweep: the in/out points go back to how they
were, and the playhead goes back to where it started. A sweep turns LOOP on.

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

### Gain, normalize and fades (in the zoomed view)

Here knobs 1–3 work on the box under the playhead (both sides of a stereo
pair). What they're set to shows next to the track name, and the waveform
shows it too.

| Knob | Turn | Push |
|---|---|---|
| 1 | Gain, ½ dB a click (−40 to +24 dB) | Normalize: the box's loudest peak to −1 dB (SHIFT+push: gain back to 0 dB) |
| 2 | Fade in (5 ms up to 30 s) | Fade in off |
| 3 | Fade out | Fade out off |

- Nothing is written into the recording: the gain and fades stay with the
  box, so you can always change them back. UNDO (SHIFT+CUT) takes back a
  normalize, or a run of knob turns on one box.
- You hear them when it plays, and EXPORT, BOUNCE and COPY/CUT (the
  clipboard) include them.
- SPLICE splits a box's gain onto both halves (the fade in stays on the left,
  the fade out on the right). Joining two boxes with different gains keeps
  how they sound.
- Overdubbing onto a box with gain or fades puts them into its audio first,
  so the new part isn't turned up or faded too.
- Every box edge with nothing right next to it gets a tiny 1 ms fade, and so
  do the joins where DROP puts something down, so edits don't click.

## Drum synth (the MIDI key)

**Three drum machines.** On the drum page or the sequencer, press **FILE → DRUM
MACHINE** and pick one. The song remembers it, and new songs start with the one you
used last.
- **LXR-02** is the one described below.
- **TR-606** (6W6) and **TR-808** (8W8) are from Schwung on the Ableton Move.

How they differ:

| | LXR-02 | TR-606 | TR-808 |
|---|---|---|---|
| Keys 1–8 | 7 drums (key 7: open hat) | BD SD LT HT CH OH CY CP | BD SD LT MT HT CP CH OH |
| SHIFT + keys 1–8 | arm tracks | arm tracks | LC MC HC RS CL MA CB CY |
| Pages per drum | 6 (knob 9) | SOUND | SOUND |

- **SOUND page:** each drum's own settings (TUNE, DECAY, DRIVE, DIST, LEVEL…), plus
  REVERB and DELAY, which send it to Console's effects.
- **What's left out of the 606 and 808:** their own effects and master distortion
  aren't used. Console's reverb and delay do that job, as for the LXR.
- **Kits:** each machine keeps its own kits (FILE → SAVE / LOAD Kit). A song keeps
  each machine's kit, so switching back finds it as you left it.
- **Each machine has its own sequencer.** Switching to another machine gives you its
  own patterns, empty the first time. Switching back finds the previous machine's
  patterns, kit and locks just as you left them, and the song saves them all.
- **MULTI with the 808:** key n records onto track n, and SHIFT + key n records
  onto the same track.

Console has a drum machine built in: the six drum voices of the Erica Synths
LXR-02, running on the Pi from its open-source firmware. It's an input, like
the OP-XY: you hear it along with the tape, and RECORD puts it on tape.

1. Select the track to record onto first (for MULTI, that's any track; see
   below), then press the **MIDI** key (`D` on a keyboard). The bottom right
   shows the drum page. The first time, this also sets SETTINGS > INPUT to
   DRUM SYNTH; set it back there to record from the OP-XY again.
2. Track keys **1–7** play the drums (no velocity yet, every hit is the same):

   | Key | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
   |---|---|---|---|---|---|---|---|
   | Voice | Drum 1 (kick) | Drum 2 | Drum 3 | Snare | Cymbal | Hi-hat closed | Hi-hat open |

3. AUDIO picks how it records, as with any input:
   - **MULTI**: each voice onto its own track, drum 1 onto track 1 … hi-hat
     onto track 6. SHIFT+AUDIO arms them all.
   - **STEREO**: the whole kit, panned, onto a pair (select 7, SHIFT+8).
   - **MONO**: the whole kit onto the selected track.
4. RECORD, play, RECORD again to stop, as usual. Hits land on the tape where
   you pressed the key.

On the drum page the track keys are drum pads, so they don't select tracks;
SHIFT+track still arms one. Press MIDI (twice: it goes through the
sequencer) to get the track keys back.

**Push a knob** on the drum page to put its setting back to where the Init Kit has it.

**Shaping the sounds.** The drum page shows the settings of the voice you
played last (its name is top right; key 7, the open hi-hat, picks the
hi-hat). Knobs 1–8 turn the setting shown on their row; knob 9 steps
through the voice's pages:

| Voices | Pages |
|---|---|
| Drum 1–3 | OSC + AMP, PITCH + VELOCITY, FM + CLICK, FILTER + MIX, LFO |
| Snare | OSC + NOISE, AMP + CLICK, PITCH + VELOCITY, FILTER + MIX, LFO |
| Cymbal, hi-hat | OSC + AMP, VELOCITY + CLICK, OSC 2 + 3, FILTER + MIX, LFO |

Two changes from the LXR-02: the snare's noise has its own decay (NOISE DCY,
next to TONE DECAY on its AMP + CLICK page; the click follows the tone), and
FINE tunes up to a whole semitone up or down (the LXR's goes half).

**The FX key works on every page**, the drum pages too: it shows the tape
tracks' sends and the reverb and delay settings, then press FX until it's
off to get back. **FX SENDS** (each drum's last page): REVERB and DELAY, how much of that
drum goes to Console's reverb and delay (set their sound on the FX key's
pages). They work on the drums as you hear them live; the tape tracks have
their own sends (the FX key). Recording in MULTI copies each drum's sends
onto its track, so it plays back with the same reverb and delay. In STEREO
and MONO the kit is one recording: set that track's sends with the FX key.

Turn a knob quickly to move further; hold SHIFT for one step at a time.
The kit is saved with the song, and a new song starts from the LXR's Init
Kit. VEL TO and LFO TO pick what velocity or the LFO moves (LFO VOICE picks
which voice's settings it can reach). Knob 10 and the big knob work as
usual.

**Saving and loading kits.** On the drum page, FILE opens the DRUMS menu
instead of the project menu:
- **SAVE Kit**: name it (like naming a song: big knob for the letter, ← / →
  to move, CUT deletes, PLAY saves). It keeps every drum setting. Saving
  under a name that's taken asks first; PLAY again replaces it.
- **LOAD Kit**: the big knob picks a saved kit, PLAY loads it.
- FILE goes back without changing anything.

Kits are kept in `~/console-data/kits/`, so any song can load them.

## Drum sequencer (MIDI key, second press)

The MIDI key cycles: drum page → sequencer → back to the tape. The sequencer
plays whenever the tape plays, locked to it (it starts with the tape's
first bar), and records like playing the keys does: MULTI, STEREO or MONO
onto the armed tracks, exactly on the beat. The 4×4 keys keep their normal
jobs here.

**The grid.** The 7 drums are rows (D1, D2, D3, SN, CY, HHc closed hat, HHo
open hat), 32 steps on screen at a time; lanes go up to 64 steps. Steps past
a lane's end are dark.

- **Knob 1** moves the cursor (the highlighted column), step 1 to 64. It
  moves to the 16th column, then the steps scroll under it; near step 64 it
  moves on to the end (and the same going back). Turn quickly to go faster.
- **Track keys 1–7** are the drums: press and let go to put a step at the
  cursor, or take it off. Each plays its sound as you press it. While
  stopped, pressing a different drum's key first just picks its lane;
  press it again to add a step.
- **While playing** (recording or not), the blue cursor hides and the grid
  follows the picked lane's playhead (the white outline). A drum key puts
  the step where it's playing, on the nearest step; the knobs then work on
  that step. Turning knob 1 shows the cursor again for a moment.
- **SHIFT+CUT** undoes the last change (10 steps back), including COPY
  Pattern and CLEAR P-locks. (Track key 8 is a drum now: the 606's clap,
  the 808's open hat.)
- **The TR-808's 16 drums:** the grid shows 8 lanes at a time. SHIFT + a drum
  key picks and plays lanes 9–16 (LC to CY), and the grid switches to them.
- **Knob 10** picks the pattern (16 per song; while playing, the next one
  takes over when the current one ends). The big knob moves the tape as usual.

**Knob modes.** The row of boxes along the top shows what knobs 1–9, 10 and
the big knob do, with their values. **Push knob 1** for the next mode:

- **STEP**: turn for the drum picked last, or hold drum keys to pick
  which: knob 2 LENGTH (1–64, each lane loops
  on its own), 3 VELOCITY, 4 CHANCE (100% down to 0% in tens, or 1:2, 2:2, 1:3… =
  plays on that pass round the lane out of every 2, 3 or 4) and 5 RATCHETS
  (up to 4 quick hits) for the step under the cursor (holding its key turns
  an empty step on; with no key held they only change a step that's on),
  6 EUCLID (spreads that many hits over the lane, rewriting its on/off
  steps), 7 SHIFT (rotates them), 8 RATE (1/16, 1/16T, 1/8, 1/8T, 1/32).
  Changing the rate keeps a lane that's a whole number of bars the same
  number of bars: one bar is 16 steps at 1/16, 24 at 1/16T, 12 at 1/8T.
  Letting go of a key after turning a knob doesn't toggle its step.
- **The drum's sound pages** (OSC + AMP, FILTER + MIX, LFO…, for the drum
  picked last): with no key held, knobs 2–9 change that drum's sound. Hold
  its drum key and turn: the setting is **locked** to the step under the
  cursor (a p-lock; the box shows it in green). The velocity and LFO
  destinations can't be locked.

**Beats and bars.** Each lane has a grey line between its beats: every 4
steps at 1/16, 3 at 1/8T, 6 at 1/16T, 2 at 1/8, 8 at 1/32 (in 4/4). They
follow the time signature: in 6/8, 9/8 and 12/8 a beat is a dotted quarter
(6 steps at 1/16), in 5/8 and 7/8 an eighth. A new pattern's lanes are one
bar long (12 steps at 1/16 in 3/4); changing the time signature does that
again for empty patterns. The step numbers along the bottom follow the
picked lane's beats.

**The steps:** outlined = off, filled = on, purple outline = has p-locks, a
white outline = where each lane is playing (lanes of different lengths are
at different places).

**FILE on the drum or sequencer page** opens the DRUMS menu: SAVE Kit, LOAD
Kit, **COPY Pattern** (the big knob picks where to; copying onto a pattern
with steps asks first) and **CLEAR Locks + Steps** (every lock in the
current pattern, and every step's velocity, chance and ratchets back to
100, 100% and none; the steps stay on or off).

**Velocity** changes a drum's loudness only while its VEL>VOL setting is ON
(PITCH + VELOCITY or VELOCITY + CLICK page). Console's starting kit has it
on for every drum; kits and songs saved before have it off.

## Effects: reverb and delay (the FX key)

Each track can send some of its sound to a **reverb** (ported from the one
in Mutable Instruments Elements and Rings; SIZE now shrinks the room too, from a
small room at 0% to the big hall at 100%) and a **delay** (a tape-style
echo that follows the tempo). Press **FX** to step through the pages:

| Page | Knobs 1–8 | Knob 9 | Knob 10 | Big knob |
|---|---|---|---|---|
| **REVERB** | Each track's reverb amount | Size (how long it rings) | Tone (dark to bright) | Reverb level |
| **DELAY** | Each track's delay amount | Time: 1/16 to 1/2, with dotted (.) and triplet (T) | Feedback (how many repeats) | Delay level |

Press FX a third time to go back to the tape, with the knobs as normal.
On a keyboard, **W** does the same as FX.

- The amounts come after the track's volume and pan, so a muted track
  sends nothing, and a track panned left echoes on the left.
- The effects are never recorded onto the tracks, so you can change them
  any time. They keep ringing after you stop.
- Everything is saved with the song.
- **EXPORT** puts the effects in the mix (with their tails) and also writes
  `reverb return` and `delay return` as stereo files. The dry stems plus
  the two returns rebuild the mix. BOUNCE stays dry.
- The effects are built when you run `setup.sh`. If they haven't been, the
  FX page says so.

## Knobs

| Knob | Turn | Push |
|---|---|---|
| 1–8 (above the tracks) | Track volume (with SHIFT: pan) | Mute / unmute (with SHIFT: solo / unsolo) |
| 9 (left of the right-hand three) | Zoom (with SHIFT: sweep in/out points, below) | Zoom back to 4 bars (with SHIFT: undo the sweep) |
| 10 (the middle one) | Grid: 1/4, 1/8, 1/16, 1/32 (with SHIFT: headphone volume) | Loop on / off |
| 11, the big knob | Move the playhead by grid steps (with SHIFT: by bars) | Back to the start (or the loop start) |

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
| ( / ) | Headphone volume down / up |
| W | FX: reverb page, delay page, back |
| D | Drum synth page on / off (then 1–7 play the drums) |
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

## If recordings crackle

The OP-XY sometimes garbles what it sends over USB (it repeats tiny 1 ms
pieces of audio, which sounds like crackly distortion) while it's also being
sent audio. It doesn't happen every time: about one start in four. So:

- **For clean recordings, set Settings → OUTPUT to HEADPHONES** and listen
  on the screen's jack. Then Console sends nothing to the OP-XY.
- With OUTPUT on the OP-XY, check a recording before relying on it. If it
  crackles, unplugging and replugging the OP-XY starts things afresh.

`~/console/pi-app/usb-buffer-test.py --compare` checks a device for this:
it records several times with and without sending audio to it, and counts
the glitches. (Without `--compare` it tries different buffer sizes.)
