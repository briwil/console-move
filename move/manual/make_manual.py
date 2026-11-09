"""Makes Console-on-Move-Manual.pdf (next to this file): every control of the Move app as it is now.
Run:  python3 move/manual/make_manual.py   (needs reportlab: pip install reportlab)
When a control changes in app.py / moveseq.py, change it here too and run this again."""
import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "Console-on-Move-Manual.pdf")

INK = colors.HexColor("#f2f4f2")
MUTED = colors.HexColor("#9aa39e")
ACCENT = colors.HexColor("#7fd1b4")
LINE = colors.HexColor("#3a403d")
SHADE = colors.HexColor("#1c201e")
PAGE = colors.black

H1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=INK, spaceAfter=6)
H2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=ACCENT, spaceBefore=14,
                    spaceAfter=6)
BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=14, textColor=INK, alignment=TA_LEFT,
                      spaceAfter=6)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=9, leading=12, textColor=MUTED)
H3 = ParagraphStyle("h3", parent=BODY, fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=ACCENT, spaceBefore=8)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=9.5, leading=12.5, spaceAfter=0)
KEY = ParagraphStyle("key", parent=CELL, fontName="Helvetica-Bold")
CODE = ParagraphStyle("code", parent=BODY, fontName="Courier", fontSize=8.5, leading=11, backColor=SHADE,
                      borderPadding=(5, 6, 5, 6), spaceBefore=4, spaceAfter=10)


def p(text, style=BODY):
    return Paragraph(text, style)


def phones(*pairs, width=3.15 * inch):
    """Pictures of the external screen (4:3) side by side, with captions."""
    cells = []
    for name, cap in pairs:
        img = Image(os.path.join(HERE, name + ".png"), width=width, height=width * 0.755)
        cells.append([img, p(cap, SMALL)])
    t = Table([[c[0] for c in cells], [c[1] for c in cells]], colWidths=[width + 8] * len(cells), hAlign="LEFT")
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return t


def table(rows, widths=(1.9 * inch, 4.6 * inch)):
    """Two columns: the control (bold), what it does."""
    data = [[p(a, KEY), p(b, CELL)] for a, b in rows]
    t = Table(data, colWidths=widths, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def screen(name, caption, width=3.0 * inch):
    img = Image(os.path.join(HERE, "screen-%s.png" % name), width=width, height=width / 2)
    framed = Table([[img]], colWidths=[width + 6])          # a thin frame, so the screen stands off the page
    framed.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.75, MUTED), ("LEFTPADDING", (0, 0), (-1, -1), 3),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 3),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return [framed, Spacer(1, 3), p(caption, SMALL)]


def screens(*pairs):
    """Screen pictures side by side, with captions."""
    cells = [screen(n, c) for n, c in pairs]
    t = Table([cells], colWidths=[3.25 * inch] * len(cells), hAlign="LEFT")
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return t


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(PAGE)                        # black pages (drawn first, under everything)
    canvas.rect(0, 0, letter[0], letter[1], stroke=0, fill=1)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.75 * inch, 0.5 * inch, "Console on the Ableton Move - controls")
    canvas.drawRightString(letter[0] - 0.75 * inch, 0.5 * inch, "page %d" % doc.page)
    canvas.restoreState()


story = []
story += [
    p("Console on the Move", H1),
    p("How to drive the Console app on an Ableton Move: an 8-track tape with OP-1-style editing, up to 8 "
      "instruments (drum machines and synths) and a step sequencer. This covers the controls as they are in "
      "November 2026 (updated 4 November). Things still to come are listed at the end.", BODY),

    p("Starting and stopping", H2),
    table([
        ("Start Console", "Shift + Step 2 (the Move's settings), then choose <b>RNBO</b> at the bottom of the list. "
         "Console opens by itself after a few seconds. The menu item keeps the name RNBO."),
        ("Quit", "<b>Shift + Back</b>. Saves the song, quits and gives the Move back to its normal software."),
        ("If something goes wrong", "If the app ever crashes, the Move goes back to normal by itself. What it "
         "printed is saved in /data/UserData/console/app.log, and every run keeps a log in "
         "/data/UserData/console/crashes (running.log is the current run; a crash adds a crash-<date>.log with "
         "the last buttons pressed and where it stopped). Send those when reporting a problem."),
        ("Stress test", "To hunt for crashes and memory leaks, the app can run by itself for a while: "
         "<font face='Courier'>ssh ableton@move.local \"echo 60 &gt; /data/UserData/console/stress\"</font> "
         "(60 = minutes). It uses its own projects, so your songs aren't touched. The report is "
         "/data/UserData/console/stress-report.txt. Shift + Back stops it early."),
        ("Update", "On the Move: Menu, SETTINGS, SOFTWARE UPDATE (push to check, push again to install; "
         "Console restarts). Or from the Mac: <font face='Courier'>ssh ableton@move.local \"python3 "
         "/data/UserData/console/move/move-update.py\"</font>."),
    ]),

    p("The Move's controls at a glance", H2),
    p("Most buttons have a second job with <b>Shift</b> held. Each page below says what changes there. "
      "The tape's own controls (selecting, arming and muting tracks, track volumes, Copy / Delete / Capture / "
      "Sample, moving the playhead) only work on the tape. On the instrument pages, song mode and FX they do "
      "nothing, unless that page uses the control for its own job. Play, Record, Loop and Shift + Play (back to "
      "the start) work everywhere.", BODY),
    table([
        ("Play", "Play / stop.  Shift: back to the start (or the loop's start)."),
        ("Record", "Record on the selected track (and any armed tracks).  Shift: switch between replacing the "
         "tape and adding to it (overdub)."),
        ("Loop", "Loop between the in and out points on / off.  Shift: clear the in and out points."),
        ("Left / Right arrows", "Move the playhead one grid step.  Shift: set the loop's in / out point at the "
         "playhead."),
        ("Undo", "Undo the last tape edit (on the drum sequencer: the last pattern edit)."),
        ("Sample", "Splice: split the box under the playhead (at a splice: join it back).  Shift: on every track."),
        ("Copy (hold)", "Copy the box under the playhead. Hold and turn the jog wheel to take more pieces, let "
         "go to copy.  Shift + Copy: start a selection."),
        ("Delete (hold)", "Cut, the same way as Copy (it leaves an empty space)."),
        ("Capture", "Drop (paste) what was copied or cut at the playhead.  Shift: insert it, pushing the rest "
         "of the track later."),
        ("Mute", "Mute the selected track.  Shift: solo it."),
        ("Menu", "The project menu (songs, tempo, settings). On a sound page: the instrument menu.  "
         "<b>Shift + Menu: export.</b>"),
        ("Back", "Back out of a menu or page.  <b>Shift + Back: save and quit.</b>"),
        ("Left buttons (top to bottom)", "1 Instruments (press again: the instrument's sound, again: "
         "its sequencer, again: back to the instruments; Shift: back one step).  2 Song mode.  3 FX (reverb, delay, "
         "song insert 1, song insert 2, then off).  4 The recorder "
         "(the tape; press again: the selected track zoomed. Shift: arm all tracks)."),
        ("Knobs 1-8", "Depend on the page (below). On the tape: the 8 tracks' volumes; Shift: pan."),
        ("Shift + touch a knob", "Pushes that knob (the Pi's knob push): on the tape it mutes that track."),
        ("+ / -", "The Pi's knob 9: on the tape, zoom in / out. Shift: sweep the in / out points a bar at a time."),
        ("Jog wheel", "Turn: move the playhead a grid step.  Shift + turn: the grid size.  Push: back to "
         "the start. In lists and menus: turn to pick, push to choose."),
        ("Volume knob", "Headphone / speaker volume."),
        ("Step buttons", "On the tape: 1-8 select a track (press the selected one again to zoom in); Shift + "
         "step: arm a track. On the drum sequencer: the 16 steps."),
        ("Pads", "Drums: the left 4 x 4 are the drums (bottom left first; tapping one picks it), the right "
         "4 x 4 play the picked drum chromatically, a semitone a pad (bright pads: the root). A synth plays a "
         "scale.  <b>Shift + pad 1-16: the instrument's pattern.</b>"),
    ]),

    p("The tape", H2),
    screens(("tape", "The tape page: four tracks at a time (the selected track's group) as solid boxes; a "
             "splice is a thin divider. The dotted line is the playhead. Bottom: volume and pan."),
            ("zoom", "Left button 4 again: the selected track zoomed, its sound as a waveform; a splice is an "
             "I-beam. The notch in the ruler is the playhead.")),
    table([
        ("Step buttons 1-8", "Select a track (its light is white). Selecting doesn't arm it."),
        ("Shift + step 1-8", "Arm or disarm a track: <b>armed tracks are red</b> (selected and armed: red and "
         "white blinking) and have a bar beside the number on the screen. <b>Record only records armed tracks</b> "
         "(arm every track you want: say a drum and a synth together). Armed tracks' instruments sound on the tape "
         "page, and Copy / Delete / Sample take them along."),
        ("Knobs 1-8", "Track volumes.  Shift + knob: pan."),
        ("Record", "Start / stop recording on the selected track and any armed tracks."),
        ("Splices", "A splice shows as a thin divider between two boxes (zoomed in: an I-beam through the sound)."),
    ]),
    p("The zoomed track (left button 4, twice)", H2),
    table([
        ("Knob 1", "Mono / stereo (about 5 clicks to switch)."),
        ("Knob 2", "The input: an instrument's drum, its kit, all kits (and on a stereo track, its left side). "
         "About 5 clicks per choice."),
        ("Knob 3", "A stereo track's right input."),
        ("Knobs 4-6", "The box under the playhead: gain, fade in, fade out.  Shift + touch knob 4: normalize."),
        ("Left button 4 / Back", "Back to the tape."),
    ]),

    p("Page names", H2),
    p("Going to another page (left button 1's INSTRUMENT, SEQUENCER, AUTOMATION, PUNCH FX; left button 3's MIXER, REVERB, "
      "DELAY, SONG INSERT 1 and 2; the instruments list, song mode, the tape), its name slides in on a black screen "
      "for about 0.6 of a second, on the Move and the phone. Moving between an instrument's own pages (its sound pages, "
      "LFOs, inserts, SENDS, ARP, PADS) shows no card. Any button, knob or pad cuts it short.", BODY),

    p("Instruments", H2),
    p("Left button 1 opens the INSTRUMENTS page: 8 slots, each a drum machine or a synth. Recording an "
      "instrument onto the tape uses the zoomed track's input (knob 2).", BODY),
    table([
        ("Jog wheel", "Pick a slot. Push: open it (an empty slot: choose what goes in it). Left button 1 does "
         "nothing here."),
        ("Choosing an instrument", "A picture of each instrument scrolls left and right as you turn the wheel "
         "(the ones without a picture yet show their name). Push to choose: it goes straight to its page."),
        ("SAMPLER", "A drum machine of 16 drums, each with two .wav or .aif samples from the Move's sample folders. "
         "Push the wheel on a drum (on its sound page, not LFO, INSERT, SENDS or PADS): SAMPLE 1, SAMPLE 2 and RANDOM; push a sample for the folders, or <b>Delete + "
         "push</b> to take it out. Knobs: LEVEL, PITCH, START, DECAY, PAN, REVERB, DELAY (shared by all its samples) "
         "and BLEND: all the way left only sample 1, the middle both at full volume, all the way right only sample "
         "2. BLEND can be an LFO's target or a step lock, so it can morph between the two, even while a sample "
         "rings. Older songs and presets: sample 2 empty, BLEND left."),
        ("RANDOM", "Push it to turn it on: SAMPLES 3, 4 and 5 appear under it, and each hit plays one of the drum's "
         "samples (1-5) at random. BLEND is off while it's on (and back as it was when you turn it off)."),
        ("MRSAMPLE", "One sample played chromatically on the pads (like the OP-1 or the Move's own Sampler), with an amp "
         "envelope, filter and LFO. Push the wheel on its sound page (not LFO, INSERT, SENDS, ARP or PADS): the sample browser (the Move's sample folders, "
         "each sample plays as you land on it); push a sample to choose it, Back to leave. It is saved with the song "
         "(as a place in the sample list, like the drum sampler's)."),
        ("Shift + push the jog wheel", "On a loaded slot: change it or remove it."),
        ("EDIT (last in the instrument list)", "Every drum machine, then every synth, each with a tick box. Push the "
         "wheel to untick one and it no longer appears in the list when you choose an instrument; tick it to bring it "
         "back. A song that already uses an unticked instrument keeps it. Back returns to the list."),
        ("Step buttons 1-8", "Mute / unmute a slot."),
        ("Left button 1 (in an instrument)", "Round its own pages: sound, sequencer, AUTOMATION, PUNCH FX, then the sound "
         "again (ARP: Shift + step button 3). Back (or Shift + left button 1), from any of them: this page."),
    ]),
    p("A synth's settings that are a switch (an oscillator's SAW or PULSE, HOLD...) show <b>OFF</b> / <b>ON</b> "
      "and flip a click at a time. A preset or kit setting turns one preset a click and stops at the last one.",
      BODY),
    p("Recording the Move's input jack", H2),
    p("The zoomed track's input (knob 2) also offers <b>INPUT L</b> and <b>INPUT R</b>: whatever is plugged "
      "into the Move's audio input (a guitar, a mic). Pick one for a mono track, both for stereo. You hear it "
      "while you arm the track.", BODY),
    p("An instrument's sound", H2),
    table([
        ("Knobs 1-8", "The settings on this page. While one turns, it shows big."),
        ("Up / Down (+ / -)", "The pads' octave (a synth's pads, and the chromatic drum pads on the right). The "
         "screen shows OCT +1 etc."),
        ("Left / Right", "The previous / next page of settings. On a synth's sound pages the big wheel also turns the pages, one page a click."),
        ("Shift + touch a knob", "That setting back to its starting value."),
        ("Settings that pick a mode", "DIST, CHOKE, a wave, on / off: it takes 5 clicks the same way to move to "
         "the next choice, so you don't skip past. Shift + turn: one choice a click. Lists get 3 clicks a choice: "
         "the lane's RATE, MULTIPLY / PULSE / HOLD / JUMP and the pitch ones, song-mode patterns, the grid "
         "and the pattern (Shift + wheel). Numbers (volume, velocity, tune...) take 3 clicks a step."),
        ("Knob speed", "Shift + turn the volume knob: how many clicks of a knob make one step of a number "
         "(1-12, starts at 4). More clicks = easier to be precise. Lists use the speed plus one. It is kept when you switch off."),
        ("Reverb and delay", "Each drum's REVERB and DELAY knobs on its sound page set how much of that drum goes "
         "to the effect. The effects' own settings (size, time, tone, feedback, level) are on left button 3."),
        ("Pads", "Play the drums (or the synth)."),
        ("File / Menu", "The INSTRUMENT MENU: SAVE PRESET, LOAD PRESET, COPY / PASTE PATTERN, CLEAR PATTERN, CLEAR LOCKS "
         "(see Presets below)."),
    ]),
    p("Presets (instrument menu)", H2),
    p("Press File (or Menu) on an instrument's sound page. Presets are the old \"kits\": a sound saved for that one "
      "instrument (a Dexed patch, a drum kit, a Braids sound) and kept with it.", BODY),
    table([
        ("SAVE PRESET", "Name it on the naming screen (below). It is saved for this instrument only, with its INSERT 1 and 2 effects and their settings. A SAMPLER preset remembers each drum's sample by its file, so adding samples later doesn't change it."),
        ("LOAD PRESET", "A list of that instrument's presets: turn the wheel to pick, push to load. Its inserts come back too (presets saved before November 2026 leave the inserts as they are). A SAMPLER sample that has gone from the Move's folders is left empty, and the screen says how many."),
        ("COPY / PASTE PATTERN", "Copy the pattern and paste it onto another pattern or another instrument of the same kind."),
        ("CLEAR PATTERN / CLEAR LOCKS", "Empty the pattern, or only the step settings. Both ask ARE YOU SURE? first."),
    ]),
    p("Presets page (synths)", H2),
    p("A synth's first sound page. It lists your presets (*, saved with SAVE PRESET), then the synth's own, then "
      "Console's (+, for synths that come with none: Plaits and Maze Voice). OB-Xd has 128 factory presets plus "
      "six banks converted from OB-Xf's free patches (Xf Bass, Xf Leads, Xf Pads, Xf Keys, Xf Brass FX, Xf Atmos); "
      "Dexed has 38 banks of 32, among them Yamaha's ROM1A and four Sega Genesis style banks.", BODY),
    table([
        ("The wheel", "The next / previous preset: you hear it as you land on it."),
        ("Push the wheel", "Keep it (one of yours comes back with its inserts too)."),
        ("Back", "The sound you had before you started turning."),
        ("Knob 1", "The bank (OB-Xd, Dexed and other synths with more than one)."),
        ("Left / Right", "The other sound pages; the preset you landed on stays."),
    ]),
    p("Naming screen", H2),
    p("Used for songs, presets and renaming. The letter you are on is shown inverted, in a white box.", BODY),
    table([
        ("Turn the wheel", "Change the letter."),
        ("Push the wheel / Shift + push", "Move to the next / previous letter."),
        ("Delete", "Erase the letter."),
        ("Play", "Save the name.   Back: cancel."),
    ]),
    p("LFOs", H2),
    p("Every instrument has two LFOs per pattern (a new pattern starts as a copy of the one you came from, then "
      "they are separate). On a sound page press <b>Right</b> past the last page: LFO 1, again: LFO 2, then INSERT 1 and 2 (see FX). "
      "On the sampler every drum has its own two LFOs: the LFO pages show the ones of the drum you last played, and "
      "DEST lists that drum's settings (shown as D3 LEVEL, D3 BLEND...).", BODY),
    table([
        ("Knob 1  DEST", "Which setting it moves (numbers only): the instrument's settings, then the number settings of "
         "its two insert effects (shown I1 / I2 and the setting's name, e.g. I1 CUTOFF). Choose the effect first."),
        ("Knob 2  WAVE", "Sine, triangle, saw up / down, square, random."),
        ("Knob 3  SPEED", "8 bars down to 1/32 of a beat, in time with the tempo, with triplet speeds (1/2T, "
         "1/4T, 1/8T, 1/16T) after their straight ones. Last: <b>RND</b>, a new speed every cycle (1 bar down "
         "to 1/16), still in time."),
        ("Knob 4  DEPTH", "How far it swings, -100 to +100 %."),
        ("Knob 5  PHASE", "Where in the cycle it starts."),
        ("Knob 6  MODE", "FREE (runs with the song) or TRIG (restarts at the pattern's first step)."),
        ("Step buttons", "The LFO's 16 steps (1/16 notes, one bar). Tap: that step rests. Hold a step and turn "
         "knob 2 (its own WAVE) or knob 4 (its own DEPTH)."),
    ]),
]

story += [
    p("The drum sequencer", H2),
    p("The steps live on the 16 step buttons, the screen shows what the knobs do. Each drum (lane) has its "
      "own length, up to 64 steps, and its own speed.", BODY),
    p("On every sequencer the step buttons inside the pattern light dim white, the steps with something on them "
      "red, and steps past the pattern's end are off.", BODY),
    p("<b>Triplets:</b> Menu, SETTINGS, <b>TRIPLETS</b> (below TIME SIG, saved with the project) turns every 4th "
      "step off: steps 4, 8, 12 and 16 go dark, do nothing when pressed and show as a dash, and the other steps "
      "play 3 in the time of 4. So a 1/16 lane plays 1/8 triplets, 1/8 plays 1/4 triplets and 1/32 plays 1/16 "
      "triplets. It works on every instrument's sequencer (drums and synths) at once; a pattern keeps its length "
      "in bars, so everything stays lined up. Steps already on the dark buttons are kept, silent, and come back "
      "when it's off. Turned on or off while playing, each pattern changes when it next comes round. The lane's "
      "RATE choices are straight ones (1/1 to 1/32); a lane from an older song on 1/8T or 1/16T keeps it until "
      "you turn its RATE. The arp keeps its own triplet rates.", BODY),
    screens(("seq-lane", "The drum's 16 steps (small, at the top) and the lane's settings."),
            ("seq-hold", "Shift + steps 1 and 5 tapped: they blink, and the pads are their settings.")),
    Spacer(1, 6),
    table([
        ("Pads", "Left 4 x 4: pick the drum (its pad lights brighter) and hear it.  Shift + pad: the pattern."),
        ("Step buttons", "Tap: the step on / off. While playing, the playhead moves along them."),
        ("Shift + step buttons", "Select steps to set (below)."),
        ("Left / Right arrows", "Steps 17-32, 33-48, 49-64 (for lanes longer than 16)."),
        ("Knob 1", "LENGTH: the lane's number of steps (1-64)."),
        ("Knob 2", "RATE: the lane's speed. Ten rates, slowest to fastest, so turning right always speeds up. "
         "It only changes the speed: the lane keeps its steps (double time = a faster rate, same length)."),
        ("Knob 3", "EUCLID: spread a number of hits evenly over the lane (OFF to switch it off)."),
        ("Knob 4", "SHIFT: turn the lane's pattern around by steps."),
        ("+ / -", "The pads' octave (the chromatic drum pads, a synth's notes). Patterns: Shift + a pad; while playing, the next one waits its turn (shown as PAT 1>2)."),
        ("Undo", "Undo the last pattern edit."),
    ]),
    p("Step settings (OP-XY style)", H2),
    p("Hold Shift and tap one or more steps: they blink. Let go of Shift. <b>Knobs 1-8 are now the instrument's "
      "sound page</b> (as on the old Console): turn one and that setting is locked on the selected steps. "
      "It starts on the sound page you last had open. Left / Right or the wheel: its other sound pages. Shift + touch a knob: its lock off. A * on the screen: "
      "locked; a -: a setting that can't be locked.", BODY),
    p("The pads are the steps' settings too, "
      "bottom left first. Tap a pad: that setting is on and <b>knob 1</b> sets it. Tap the same pad again: "
      "it's off (back to normal). Lit pads: settings the step has; the picked one blinks. "
      "The big wheel sets it too, like knob 1. <b>Tap any step, or push the big wheel, to finish.</b>", BODY),
    screens(("seq-lock", "PULSE picked on two steps: knob 1 sets how many times they repeat.")),
    table([
        ("Pad 1  VELOCITY", "How hard (1-127, turned all the way down: RND, random)."),
        ("Pad 2  CHANCE", "How often it plays: 100% down to 0%, or 1:2, 2:3... (the 1st of every 2 times "
         "round, and so on)."),
        ("Pad 3  MULTIPLY", "Hits inside the step: x1 to x8, or RND."),
        ("Pad 4  PULSE", "Play the step again 1-9 times (or RND) before moving on."),
        ("Pad 5  HOLD", "Wait 1-9 steps (or RND) after it, silent."),
        ("Pad 6  JUMP", "Then go to step 1, 5, 9 or 13, skip one (+1), back one (-1), either (+/-), or RND. "
         "Once each time round the lane."),
        ("Pad 7  RANDOM", "A random pitch each time: 2-6 notes over 1 or 3 octaves."),
        ("Pad 8  RAMP UP", "The pitch goes up each time round: 2-6 notes over 1 or 3 octaves."),
        ("Pad 9  RAMP DOWN", "The same, going down. (One of RANDOM / RAMP UP / RAMP DOWN at a time.)"),
        ("Pads 10-32", "The drum's own sound settings (TUNE, DECAY...): a parameter lock for these steps."),
    ]),
    p("<b>Chance for a component.</b> With MULTIPLY, PULSE, HOLD, JUMP, RANDOM, RAMP UP / DOWN or NUDGE set on a "
      "step, knob 2 sets how likely that component is to happen each time round (100% down to 0%, or 1:2, "
      "2:3...). When it doesn't happen the step just plays plain. The same on the synth sequencer."),
    p("Pitch moves use the drum's TUNE (or PITCH) setting, so how far a semitone goes depends on the drum "
      "machine. BEND, PORTAMENTO and TONALITY are for the synth sequencer, still to come.", SMALL),

    p("Song mode (left button 2)", H2),
    p("A list of rows, OP-XY style: each row picks a pattern for every instrument and says how many times it "
      "plays. With song mode on, Play starts at row 1 and goes through the rows, then round again.", BODY),
    screens(("song", "Row 2: the LXR plays pattern 3, twice.")),
    table([
        ("Step buttons", "The rows. Press one past the end: a new row (a copy of the last). Lit: the rows; "
         "the playing one blinks."),
        ("Delete + step button", "Take that row out."),
        ("Knobs 1-7", "The row's pattern for instruments 1-7 (all the way down: -, leave it as it is)."),
        ("Shift + knobs 1-7", "The row's PUNCH FX pattern for instruments 1-7. While Shift is held the screen shows those (FX1, FX2...) in place of the note patterns."),
        ("Knob 8", "How many times the row plays (1-16)."),
        ("+ / -", "+ switches song mode on, - off. <b>Shift + left button 2</b> does the same from any page "
         "(the tape shows SONG in its top line while it's on). Off: the picked pattern plays, as usual."),
    ]),
    p("The synth sequencer", H2),
    p("A synth's sequencer works on chords. The 16 step buttons are the steps (Left / Right for more).", BODY),
    p("UNIFIED or PER NOTE?", H2),
    p("Knob 3 chooses how the pattern is built.", BODY),
    table([
        ("UNIFIED", "One sequence of chords. Every step holds a chord, and the whole pattern shares one LENGTH and "
         "one RATE. Step settings (pulse, hold, jump...) apply to the step as a whole. Easiest: it works like a "
         "normal step sequencer, and a chord is just several pads on one step."),
        ("PER NOTE", "Every pitch gets its own row. Tap a pad to pick a note (it turns white): the 16 steps now show "
         "only that note. Each note has its <b>own LENGTH (knob 1) and its own RATE (knob 2)</b>, and its own "
         "pulse / hold / jump / chance. Pads of notes that already have steps light <b>orange</b>; a step you are "
         "holding lights red. Every note starts at 16 steps; with no note picked, knob 1 asks you to tap a pad (so "
         "it can't change all the notes at once)."),
    ]),
    p("Why use PER NOTE", H3),
    table([
        ("Polyrhythm", "Give a low C a length of 3 and a high G a length of 4: they drift against each other and only "
         "line up every 12 steps, so a simple two-note pattern keeps changing."),
        ("Drone under a melody", "One note with a long length and a slow rate (a held bass or pedal tone) "
         "while a melody note runs 1/16 on top of it."),
        ("Arpeggio that evolves", "Lay out an arpeggio one note per row, each with a different length (5, 7, 8, 11): "
         "the pattern takes a long time to repeat."),
        ("Different speeds", "Bass at 1/8 while the lead is at 1/16 or in triplets, in one instrument."),
        ("Per-note feel", "Chance 50% on a high note only, a jump or hold on one pitch only, "
         "so a pattern breathes without touching the rest."),
        ("Use UNIFIED when", "you want chords, a hook that is the same length all the way through, or the "
         "quickest way to write a loop."),
    ]),
    table([
        ("Step buttons", "Tap: the notes on / off. Hold a step: the pads light its notes; tap pads to add or "
         "remove notes. Hold a step and tap a later step: that is where the notes end (also across pages)."),
        ("Knobs (no step held)", "1 length, 2 rate, 3 type (UNIFIED: one sequence; PER NOTE: tap a pad to see only "
         "its steps), 4 the lit note's own length, 5 key, 6 scale."),
        ("Shift + steps", "Select steps: the pads are their settings. VELOCITY, CHANCE, MULTIPLY, "
         "<b>NUDGE</b> (a step early or late, -50 to +50 %), PULSE, HOLD, JUMP (PER NOTE type only), RANDOM, "
         "RAMP UP, RAMP DOWN (pitch), then the synth's own settings as parameter locks. "
         "Knob 1 sets the picked one; on a component (MULTIPLY, NUDGE, PULSE...) knob 2 sets its chance. With no pad picked, knobs 1-8 are the synth's sound page: turn one to lock "
         "it (Left / Right: its other pages; Shift + touch a knob: the lock off)."),
        ("Record", "On an instrument's sound, sequencer or automation page: recording into the pattern while it "
         "plays. The pads you play go in (a synth note lasts as long as you hold the pad; chromatic drum pads keep "
         "their pitch), and so do the sound page's knobs: turning one puts its value on every step as it plays, notes or "
         "not, and it plays back as the steps go by (a filter sweep over a held note is heard as a sweep). Turn it "
         "again on a later pass to record over those steps. It shows on the automation page as the setting's name "
         "+ REC. Press again to stop. It doesn't touch the tape. It turns itself off at Stop and when you "
         "leave the instrument's pages."),
        ("Step settings colours", "Pads of tapped steps: yellow for the steps you picked, red for settings you changed, dim for the rest."),
        ("Stop", "Every sounding note is let go at Stop (Dexed and other synths too)."),
        ("Drums, by hand", "Hold a step button and press a right-half pad: the step turns on with that pitch."),
    ]),

    p("Automation page", H2),
    p("Left button 1 after the sequencer: what is locked on this pattern's steps, one setting at a time. Recorded "
      "knob moves show here (their name + REC: any step can have one, notes or not), and so do step locks and "
      "step settings made with Shift + steps. When it stops, the sound goes back to the knobs.", BODY),
    table([
        ("Knob 1", "Go through the settings that are set on some step: the step settings (VELOCITY, CHANCE, "
         "MULTIPLY, PULSE...) first, then the sound's (BLEND, CUTOFF...). Each has its own colour on the step "
         "buttons, so you can see you've switched."),
        ("Step buttons", "Lit: that setting is on the step. Tap a lit step: it comes off that step. Tap an unlit "
         "step that plays a note: it gets the setting, with the value of the lit step before it. Hold a step: its "
         "value shows, and knob 1 changes it while you hold the step."),
        ("Delete + step", "Take that setting off the step."),
        ("Shift + Delete", "Take that setting off every step: it asks first (Shift + Delete again: yes)."),
        ("Undo", "Puts back what you took off or changed."),
        ("Pads (drum machines)", "Tap a drum's pad to see its own automation; lit pads have some."),
        ("Left / Right, the wheel", "Steps 17-32 and on."),
        ("External screen", "Every locked setting as a row, each step's value in it, in the same colours as the "
         "step buttons; the one knob 1 is on outlined, the held step framed white."),
    ]),
    p("Punch FX page", H2),
    p("Left button 1 after AUTOMATION: a sequencer of OP-XY style punch-in effects on the instrument you're on, one "
      "lane per effect, each with its own length and rate (as the drum lanes, TRIPLETS too). Each instrument has 16 "
      "punch patterns of its own, apart from its note patterns, and song mode picks them per row. Pads 1-16 (the "
      "bottom two rows) are the effects:", BODY),
    table([
        ("Pads 1-5", "REPEAT 1/4, 1/8, 1/16, 1/32, 1/8T: the slice from when it starts, round and round."),
        ("Pad 6  REVERSE", "The beat just gone, backwards."),
        ("Pad 7  TAPE STOP", "Slows to a halt over a beat."),
        ("Pad 8  HALF SPEED", "An octave down, slowed."),
        ("Pads 9-11", "LOW PASS (sweeps down), HIGH PASS (sweeps up), RESO PEAK (a ringing wah)."),
        ("Pad 12  BITCRUSH", "Grit and lo-fi."),
        ("Pad 13  GATE 1/16", "Chopped in sixteenths."),
        ("Pad 14  PAN SWING", "The whole instrument sways left and right, once a beat."),
        ("Pad 15  ECHO THROW", "Everything into the delay while it's on; the echoes ring on after."),
        ("Pad 16  KILL", "Silence."),
    ]),
    p("They stack: one from each group plays at once (TIME: pads 1-8; FILTER: pads 9-11; BITCRUSH, GATE, PAN SWING, "
      "ECHO THROW and KILL each on their own). Two lanes of the same group on at once: the one whose step started "
      "last wins (the same moment: the higher pad).", BODY),
    table([
        ("Tap a pad", "Its lane: the step buttons show its steps."),
        ("Hold pads", "They play while held (several: stacked). Recording into the pattern (Record, playing): they "
         "go on their lanes' steps they were held over."),
        ("Step buttons", "The lane's steps: tap on / off. Hold one: knob 1 sets its chance (100% down to 0%, or "
         "1:2, 2:3...)."),
        ("Hold a step + tap a later step", "The effect lasts from the held step until that one, as a note's length "
         "(tap the same end again: back to one step). A later step that's on cuts it short."),
        ("Hold a step + tap pads", "Those effects' steps there on / off (each in its own lane)."),
        ("Knob 1 / knob 2", "The lane's LENGTH (steps) and RATE (1/32 to 1/1; with TRIPLETS on they play as triplets)."),
        ("Knob 8", "TIME SCALE (x1 to x32): every lane of the punch pattern that many times slower, for long "
         "sweeps over many bars."),
        ("Shift + pad 1-16", "Punch pattern 1-16 (lit: the current one bright, ones with steps dim). Playing: it "
         "takes over when the instrument's pattern next comes round, from its step 1."),
        ("Delete + step", "That step off."),
        ("Shift + Delete", "Clear every lane of the punch pattern: it asks first (Shift + Delete again: yes)."),
        ("Undo", "Puts back what you changed."),
        ("Left / Right, the wheel", "Steps 17-32 and on."),
    ]),

    p("Pads: key and scale (synths)", H2),
    p("On a synth's settings pages hold <b>Shift</b>: the icons light under the step buttons. <b>Shift + step button 2</b> (the hexagon) opens the PADS page. Press the icon again to return to the settings pages (<b>Back</b> goes to the instruments list): "
      "the PADS page. Knob 1 KEY, knob 2 SCALE (12 scales, or CHROMATIC), knob 3 OCTAVE. The pads then play only "
      "notes in that key and scale, and the pads on the key's root note light white. It is the same key and scale "
      "as the synth sequencer's knobs 5 and 6. Knob 4 VELOCITY: TOUCH (the pads play and record how hard you hit them) or a fixed velocity (turn up from TOUCH: 100, then in fives). Knob 5 CURVE: SOFT (easier to play loud), NORMAL or HARD (needs a harder hit). Pattern recording now stores the velocity you played.", BODY),
    p("A drum machine has a PADS page too (Shift + step button 2 on its sound pages). "
      "It has no key or scale: knob 1 OCTAVE (the right-hand pads, which play the picked drum a semitone a pad), "
      "knob 2 VELOCITY and knob 3 CURVE, which work as on a synth for the drum pads too.", BODY),
    p("Arpeggiator (synths)", H2),
    p("On a synth's sound pages hold Shift and press step button 3 (the branching-nodes icon, bright when the arp is on): the ARP page "
      "(Right: ARP 2; the icon again: back to the sound page). Knob 1 turns it on and off. The arp turns the notes you hold on the pads, and "
      "the chords in the sequencer, into a run of single notes. What you record from the pads is the notes you played, "
      "not the arp's. A rest in the rhythm does not use up a note: the run carries on at the next one.", BODY),
    table([
        ("Knob 1  ON", "Arp on / off."),
        ("Knob 2  MODE", "UP, DOWN, UP-DOWN, DOWN-UP, RANDOM, AS PLAYED, CHORD (every step plays all the notes)."),
        ("Knob 3  OCT", "1-4 octaves."),
        ("Knob 4  RATE", "The ten rates, slowest to fastest. A sequenced chord arpeggiates for as long as it lasts, "
         "so give it a longer length, or a faster rate, to hear more than one note."),
        ("Knob 5  GATE", "How long each note lasts, 10-200 % of a step (over 100 they overlap)."),
        ("Knob 6  HOLD", "The notes keep going after you let go; new notes replace them."),
        ("Knob 7  STYLE", "Five rhythm patterns laid over your rhythm: GALLOP, OFFBEAT, TRESILLO, SYNCOPATED, STUTTER "
         "(OFF: just your rhythm). A rest in either is a rest; an accent in either is an accent."),
        ("ARP 2 (Right)", "Knob 1 GLIDE: portamento between the notes (the synth has to answer CC 65 / CC 5). "
         "Knob 2 BEND: each note starts bent up (+) or down (-) and slides to its pitch (pitch bend)."),
        ("Step buttons", "The 16-step rhythm: tap a step to go note (white), accent (red, louder), rest (off). "
         "It follows the song's clock while it plays."),
    ]),
    p("FX", H2),
    p("The reverb and delay sends and the insert effects are on each instrument <i>before</i> the tape, so they are recorded with the sound. The tape room has no effects.", BODY),
    table([
        ("Left button 3", "The MIXER, again: reverb, again: delay, again: SONG INSERT 1, again: SONG INSERT 2, again: the MIXER. Or turn the jog wheel: the next / previous page (it stops at the MIXER and "
         "at SONG INSERT 2). Back: off."),
        ("MIXER", "The first left button 3 page: knobs 1-8 are the instruments in slots 1-8. Turn a knob: that "
         "instrument's volume (100% is as it is, the most). Hold Shift and turn: its pan (C, L50, R100...). Step buttons 1-8: mute "
         "that instrument (lit = it plays); Shift + a step button: solo it (again: everyone back). The volume and pan are "
         "saved with the song."),
        ("SENDS page", "On every instrument's sound pages, right after INSERT 2. Knob 1: its REVERB send, knob 2: its "
         "DELAY send (a drum machine: all its drums together; each drum's own knobs stay on its sound page), knob 3 "
         "and 4: how much of SONG INSERT 1 and 2 it hears (100%: all of it, 0%: it skips the effect)."),
        ("Choosing an effect", "On an INSERT or SONG INSERT page, push the wheel to browse the effects. The last "
         "entry, EDIT, lists every effect with a tick box: push the wheel to untick one and it leaves the list (tick "
         "it to bring it back). An effect already in use stays. Back returns to the list."),
        ("SONG INSERT 1 / 2", "One effect for the whole song. The tape records each instrument on its own track, so every "
         "loaded instrument gets its own copy of it (after its own INSERT 1 and 2), all following the settings on "
         "this page, and it is recorded with each instrument, as the reverb and delay are. Push the wheel to choose "
         "the effect (the same picture picker); knobs 1-8 are its settings. A copy each means a compressor or "
         "limiter works on each instrument on its own, not on the mix as a whole; character effects (tape, "
         "saturation, filters, lo-fi) work as you'd expect. Each copy uses the effect's CPU, so heavy effects on "
         "many instruments add up. Tape Echo 2, Dissolver, Dragonfly Hall and Cloudseed aren't offered here (with a copy on "
         "every instrument they were too heavy in the load test); they are still there as an instrument's own inserts. "
         "The Move's input jack doesn't get them. Saved with the project."),
        ("Knobs 1-4", "The effect. Reverb: SIZE, TONE, LEVEL and WIDTH (100%: the reverb's full stereo, as it was; 0%: both "
         "sides the same, mono). Delay: TIME, FEEDBACK, LEVEL."),
        ("INSERT 1 / 2", "The last two sound pages of an instrument (after LFO 2; wheel or arrows). Each instrument has two insert effects in a row, picked from 36 (filter, EQ, tape, reverbs, "
         "granular...). Push the wheel to open the picture picker: turn to browse, push to choose, Back to cancel. "
         "Knobs 1-8 are the effect's first eight settings; every effect has its own picture. They are on the instrument <i>before</i> the tape, "
         "so what you record from that instrument has the effects in it; nothing is added to the tape afterwards. "
         "A Ducker ducks its instrument whenever drum 1 of another instrument is hit."),
    ]),

    p("Ableton Link", H2),
    p("Menu, SETTINGS, MIDI SYNC, LINK. Console then shares its tempo (while stopped; a playing tape keeps its "
      "tempo) and its Play / Stop with Live and phone apps on the same Wi-Fi. Starting waits for the next bar.", BODY),

    p("Menus and export", H2),
    table([
        ("Menu", "The project menu: songs (new, open, save as), tempo, time signature, export format, "
         "settings. Jog wheel: pick, push: choose, Back: close."),
        ("Shift in the project menu", "NEW PROJECT becomes DELETE PROJECT and SAVE PROJECT becomes RENAME PROJECT. "
         "Pick the project, then confirm ARE YOU SURE? to delete (you go back to the main menu). Shift + wheel "
         "still moves up and down."),
        ("Settings", "Push the wheel on a setting to edit it (the value shows in a white box), turn to change, push "
         "again to let go."),
        ("Shift + Menu", "Export: a stereo mix and one file per track, in "
         "/data/UserData/console/data/exports/(song name and time)/."),
    ]),
    p("<b>Downloading exports and backing up projects:</b> on a phone, tablet or computer on the same network open "
      "<font face='Courier'>http://move.local:8080/files</font>. It lists every export (the stereo mix and the "
      "stems) and every project: tap <b>Download ZIP</b> for a whole folder, or open <b>Files</b> to take one file. "
      "Stop recording and playing before you back up the project you are working on.", BODY),
    p("Or to copy the exports to the Mac's desktop:", BODY),
    p("scp -r \"ableton@move.local:/data/UserData/console/data/exports\" ~/Desktop/move-exports", CODE),

    p("External screen (a phone or tablet)", H2),
    p("The Move can show what it is doing on a bigger screen: the tape, the sequencer, the instrument's "
      "sound pages and the arpeggiator, redrawn large and updating live. Nothing to install: it is a web page "
      "the Move serves.", BODY),
    table([
        ("Open it", "Menu, SETTINGS, <b>EXTERNAL SCREEN</b>, push. The Move shows a QR code: scan it with the "
         "phone's camera. Any button closes the code."),
        ("Same network", "The phone and the Move must be on the same Wi-Fi. With the phone's own hotspot, join "
         "the Move to the hotspot and scan the code (its address changes, so the QR code is the way in). "
         "On a normal network the address <font face='Courier'>http://move.local:8080</font> also works."),
        ("Browser", "Samsung Internet works. Chrome may refuse because it insists on https:// for new "
         "addresses; open the page in another browser then."),
        ("Tape", "Eight lanes with their waveforms, a bar and beat grid (sixteenths when zoomed right in) so you "
         "can see where a splice lands, the loop, the playhead and the track's volume. ARM shows only on tracks "
         "that really record (armed with Shift + a step button)."),
        ("Instrument pages", "The sequencer (drum steps or a synth's piano roll) and the sound page with its "
         "8 settings as vertical bars. Its tabs go on past the instrument's own pages as the Move does: LFO 1, "
         "LFO 2, INSERT 1 and INSERT 2 with the same setting cards (an INSERT page also shows the effect's "
         "picture and name), then PADS (and on a synth ARP), each as a panel with all its options. On the "
         "instruments list the title says INST and the slot number instead of a track."),
        ("Arp and pads", "On the ARP or PADS page: a translucent panel over the sound page with every arp setting and all its "
         "options. The picked option is white, the rest dim; GATE, GLIDE, BEND and VELOCITY show their value, "
         "and the arp's 16 rhythm steps are along the bottom."),
        ("Reverb and delay", "Left button 3's REVERB and DELAY pages show as the same kind of panel: SIZE, TONE, "
         "LEVEL and WIDTH (reverb) or TIME, FEEDBACK, LEVEL (delay). Each instrument's own send is on its SENDS page."),
        ("Menus and lists", "Whatever menu or list the Move has open shows as a panel too: the project menu, SETTINGS, "
         "open / delete / rename project, naming, the instrument menu (presets, copy / paste / clear pattern), "
         "the questions it asks, the sample browser, choosing an effect or an instrument (with its picture), "
         "the instruments list and song mode. The picked row is lit; long lists scroll."),
        ("Colours", "Each session picks one colour family at random and uses its shades."),
    ]),
    phones(("phone-tape", "The tape on a tablet, with the bar and beat grid."),
           ("phone-arp", "The arp panel over a sound page.")),
    screens(("qr", "MENU, SETTINGS, EXTERNAL SCREEN: scan the code (the address shown is an example).")),

    p("Not on the Move yet", H2),
    p("The LFOs' parameter locks beyond depth and wave; "
      "pictures for the instruments that still show their name; the tape's bar/beat grid when zoomed in a "
      "long way. Songs are saved in /data/UserData/console/data.", BODY),
]

# keep every heading on the same page as the picture or table after it
grouped, i = [], 0
while i < len(story):
    f = story[i]
    if isinstance(f, Paragraph) and f.style is H2:
        j = i + 1
        while j < len(story) and not (isinstance(story[j], Paragraph) and story[j].style is H2) and j - i < 4:
            j += 1
            if isinstance(story[j - 1], Table) and len(story[j - 1]._cellvalues) > 10:
                j -= 1                      # a long table may run on to the next page
                break
        grouped.append(KeepTogether(story[i:j]))
        i = j
    else:
        grouped.append(f)
        i += 1
story = grouped

doc = SimpleDocTemplate(OUT, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                        topMargin=0.7 * inch, bottomMargin=0.8 * inch, title="Console on the Move",
                        author="briwil")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("wrote", OUT)
