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
CELL = ParagraphStyle("cell", parent=BODY, fontSize=9.5, leading=12.5, spaceAfter=0)
KEY = ParagraphStyle("key", parent=CELL, fontName="Helvetica-Bold")
CODE = ParagraphStyle("code", parent=BODY, fontName="Courier", fontSize=8.5, leading=11, backColor=SHADE,
                      borderPadding=(5, 6, 5, 6), spaceBefore=4, spaceAfter=10)


def p(text, style=BODY):
    return Paragraph(text, style)


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
      "November 2026. Things still to come are listed at the end.", BODY),

    p("Starting and stopping", H2),
    table([
        ("Start Console", "Shift + Step 2 (the Move's settings), then choose <b>RNBO</b> at the bottom of the list. "
         "Console opens by itself after a few seconds. The menu item keeps the name RNBO."),
        ("Quit", "<b>Shift + Back</b>. Saves the song, quits and gives the Move back to its normal software."),
        ("If something goes wrong", "If the app ever crashes, the Move goes back to normal by itself. What it "
         "printed is saved in /data/UserData/console/app.log."),
        ("Update", "On the Move: Menu, SETTINGS, SOFTWARE UPDATE (push to check, push again to install; "
         "Console restarts). Or from the Mac: <font face='Courier'>ssh ableton@move.local \"python3 "
         "/data/UserData/console/move/move-update.py\"</font>."),
    ]),

    p("The Move's controls at a glance", H2),
    p("Most buttons have a second job with <b>Shift</b> held. Each page below says what changes there.", BODY),
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
        ("Menu", "The project menu (songs, tempo, settings). On the drum page: the kit menu.  "
         "<b>Shift + Menu: export.</b>"),
        ("Back", "Back out of a menu or page.  <b>Shift + Back: save and quit.</b>"),
        ("Left buttons (top to bottom)", "1 Instruments (press again: the instrument's sound, again: "
         "its sequencer; Shift: back).  2 Song mode.  3 FX (reverb, then delay, then off).  4 The recorder "
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
        ("Step buttons 1-8", "Select a track. The screen shows tracks 1-4 or 5-8, whichever group it's in."),
        ("Shift + step 1-8", "Arm or disarm a track: armed tracks record too, and Copy / Delete / Sample take "
         "them along. A dot beside the number marks it."),
        ("Knobs 1-8", "Track volumes.  Shift + knob: pan."),
        ("Record", "Start / stop recording on the selected track and any armed tracks."),
        ("Splices", "A splice shows as a thin divider between two boxes (zoomed in: an I-beam through the sound)."),
    ]),
    p("The zoomed track (left button 4, twice)", H2),
    table([
        ("Knob 1", "Mono / stereo."),
        ("Knob 2", "The input: an instrument's drum, its kit, all kits (and on a stereo track, its left side)."),
        ("Knob 3", "A stereo track's right input."),
        ("Knobs 4-6", "The box under the playhead: gain, fade in, fade out.  Shift + touch knob 4: normalize."),
        ("Left button 4 / Back", "Back to the tape."),
    ]),

    p("Instruments", H2),
    p("Left button 1 opens the INSTRUMENTS page: 8 slots, each a drum machine or a synth. Recording an "
      "instrument onto the tape uses the zoomed track's input (knob 2).", BODY),
    table([
        ("Jog wheel", "Pick a slot. Push: open it (an empty slot: choose what goes in it)."),
        ("Shift + push the jog wheel", "On a loaded slot: change it or remove it."),
        ("Step buttons 1-8", "Mute / unmute a slot."),
        ("Left button 1 again", "The picked instrument's sound page; again: its sequencer."),
    ]),
    p("An instrument's sound", H2),
    table([
        ("Knobs 1-8", "The settings on this page. While one turns, it shows big."),
        ("+ / -", "The next / previous page of settings."),
        ("Shift + touch a knob", "That setting back to its starting value."),
        ("Pads", "Play the drums (or the synth)."),
        ("Menu", "The kit menu (load / save kits)."),
    ]),
]

story += [
    p("The drum sequencer", H2),
    p("The steps live on the 16 step buttons, the screen shows what the knobs do. Each drum (lane) has its "
      "own length, up to 64 steps, and its own speed.", BODY),
    screens(("seq-lane", "The drum's 16 steps (small, at the top) and the lane's settings."),
            ("seq-hold", "Shift + steps 1 and 5 tapped: they blink, and the pads are their settings.")),
    Spacer(1, 6),
    table([
        ("Pads", "Left 4 x 4: pick the drum (its pad lights brighter) and hear it.  Shift + pad: the pattern."),
        ("Step buttons", "Tap: the step on / off. While playing, the playhead moves along them."),
        ("Shift + step buttons", "Select steps to set (below)."),
        ("Left / Right arrows", "Steps 17-32, 33-48, 49-64 (for lanes longer than 16)."),
        ("Knob 1", "LENGTH: the lane's number of steps (1-64)."),
        ("Knob 2", "RATE: the lane's speed (1/16, 1/16 triplets, 1/8, 1/8 triplets, 1/32)."),
        ("Knob 3", "EUCLID: spread a number of hits evenly over the lane (OFF to switch it off)."),
        ("Knob 4", "SHIFT: turn the lane's pattern around by steps."),
        ("+ / -", "The pattern (1-16). While playing, the next one waits its turn (shown as PAT 1>2)."),
        ("Undo", "Undo the last pattern edit."),
    ]),
    p("Step settings (OP-XY style)", H2),
    p("Hold Shift and tap one or more steps: they blink. Let go of Shift. Now the pads are the steps' settings, "
      "bottom left first. Tap a pad: that setting is on and <b>knob 1</b> sets it. Tap the same pad again: "
      "it's off (back to normal). Lit pads: settings the step has; the picked one blinks. "
      "<b>Tap any step to finish.</b>", BODY),
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
        ("Knob 8", "How many times the row plays (1-16)."),
        ("+ / -", "+ switches song mode on, - off. <b>Shift + left button 2</b> does the same from any page "
         "(the tape shows SONG in its top line while it's on). Off: the picked pattern plays, as usual."),
    ]),
    p("Synths: the synth sequencer screen isn't done yet on the Move (its pads play the synth).", SMALL),

    p("FX", H2),
    table([
        ("Left button 3", "Reverb page, again: delay page, again: back."),
        ("Knobs 1-8", "How much of each track goes to the effect (its send)."),
        ("+ / -", "Reverb size / delay time."),
        ("Shift + turn the jog wheel", "Reverb tone / delay feedback."),
        ("Jog wheel", "The effect's level."),
    ]),
    p("The screen labels these settings 1, 2, 3; they're on + / -, Shift + wheel and the wheel.", SMALL),

    p("Menus and export", H2),
    table([
        ("Menu", "The project menu: songs (new, open, save as), tempo, time signature, export format, "
         "settings. Jog wheel: pick, push: choose, Back: close."),
        ("Shift + Menu", "Export: a stereo mix and one file per track, in "
         "/data/UserData/console/data/exports/(song name and time)/."),
    ]),
    p("To copy the exports to the Mac's desktop:", BODY),
    p("scp -r \"ableton@move.local:/data/UserData/console/data/exports\" ~/Desktop/move-exports", CODE),

    p("Not on the Move yet", H2),
    p("The synth sequencer screen and its step buttons; bounce (recording several tracks onto one); the tape's "
      "bar/beat grid when zoomed in a long way. Songs are saved in /data/UserData/console/data.", BODY),
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
