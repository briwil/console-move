"""The Move's screens: what the Pi app's state looks like on 128 x 64 pixels. Each page reads the app's own
state (console.Transport, the engine, the menus) and draws it; nothing here changes anything.

    draw(frame, T, menu)      picks the page the app is on and draws it
"""
import time

import numpy as np

import tape
import drumparams    # noqa: F401  (the drum page's names)

from screen import W, H

TRACKS_SHOWN = 4                      # tracks on screen at once (the selected one's group of four)
LANE_H = 11                           # pixels per track


def draw(f, T, menu=None):
    f.clear()
    try:
        if menu is not None and menu.open:
            text_page(f, menu.s, getattr(menu, "msg", ""))
        elif menu is not None and menu.kits.open:
            if menu.kits.mode == "list":
                kit_list(f, menu.kits)
            else:
                text_page(f, menu.kits.s, getattr(menu.kits, "msg", ""))
        elif T.seq_page:
            seq_page(f, T)
        elif T.drum_page:
            sound_page(f, T)
        elif T.inst_page:
            inst_page(f, T)
        elif T.fx_page:
            fx_page(f, T)
        elif getattr(T, "song_page", False):
            song_page(f, T)
        elif T.focus.track is not None:
            focus_page(f, T)
        else:
            tape_page(f, T)
    except Exception as ex:                           # a drawing problem shouldn't stop the app
        f.clear()
        f.text(1, 1, "SCREEN ERROR")
        f.small(1, 12, str(ex)[:31])
    message(f, T)


def message(f, T):
    """The app's short messages (TRACK 3 ARMED...), over the bottom line."""
    if T.message and time.monotonic() < T.message_until:
        f.rect(0, H - 8, W, 8, 1)
        f.small(1, H - 6, T.message[:31], 0)


def header(f, title, right=""):
    f.rect(0, 0, W, 9, 1)
    f.text(1, 1, title, 0, limit=W - 2 - (Frame_width(right) + 4 if right else 0))
    if right:
        f.right(W - 2, 2, right, small=True, c=0)


def Frame_width(s):
    return len(str(s)) * 4 - 1


# ------------------------------------------------------------------ the tape

def tape_header(f, T):
    """The tape's top line: STOP / PLAY / REC / ODUB, the tempo, the position."""
    e, t = T.engine, T.tape
    state = "REC" if T.recording else "PLAY" if T.playing else "STOP"
    if e and e.rec_mode == "overdub" and T.recording:
        state = "ODUB"
    f.rect(0, 0, W, 9, 1)
    f.text(1, 1, state, 0)
    bpm = "%.0f" % (e.bpm if e else 120)
    f.small(30, 2, bpm + " BPM", 0)
    if getattr(T, "song", None) is not None and T.song.on and T.song.rows:
        f.small(61, 2, "SONG", 0)
    f.right(W - 2, 2, T.position_text(t.pos)[:12], small=True, c=0)


LANE_TOPS = (14, 24, 35, 46)            # the four tracks' rows on the tape page (boxes 7 high, a line under)


def ruler_ticks(f, T, y, x0, x1, mid, ppb):
    """Ticks hanging from row y: 3 high on the bar, 2 on the half bar, 1 on the other beats."""
    t = T.tape
    bar = tape.BEATS_PER_BAR
    k = int(t.pos - (mid - x0) / ppb) - 1
    while True:
        x = int(round(mid + (k - t.pos) * ppb))
        if x >= x1:
            break
        if x >= x0:
            in_bar = k % bar
            if abs(in_bar) < 1e-6:
                f.rect(x, y, 1, 3)
            elif ppb >= 3 and abs(in_bar - bar / 2) < 1e-6:
                f.rect(x, y, 1, 2)
            elif ppb >= 3:
                f.dot(x, y)
        k += 1


def tape_page(f, T):
    """The tape, as drawn in the screen designer: the header, a ruler of ticks, four tracks (the selected
    track's group) as solid boxes on a line, splices as a thin divider down to the line, the selected
    track's number inverted. The playhead is a dotted line in the middle (drawn so it shows on boxes too);
    the loop's span is a line under the ruler."""
    e, t = T.engine, T.tape
    tape_header(f, T)
    if not e:
        return
    fpb = e.frames_per_beat()
    beats_across = tape.ZOOMS[t.zoom] * tape.BEATS_PER_BAR
    x0, x1 = 11, 124
    mid = x0 + (x1 - x0) // 2
    ppb = (x1 - x0) / beats_across                  # pixels per beat
    first = ((T.armed - 1) // TRACKS_SHOWN) * TRACKS_SHOWN
    ruler_ticks(f, T, 10, x0, x1, mid, ppb)
    for i in range(TRACKS_SHOWN):
        n = first + i                                # 0-7
        top = LANE_TOPS[i]
        if n == T.armed - 1:
            f.rect(0, top, 9, 7)
            f.text(2, top, str(n + 1), 0)
        else:
            f.text(2, top, str(n + 1))
        if n in e.arm_extra:
            f.rect(9, top + 1, 2, 5)                 # armed (Shift + step button): a bar beside the number
        if not e.audible(n):
            f.rect(1, top + 8, 7, 1)                 # muted: a line under the number
        f.rect(x0, top + 8, x1 - x0, 1)              # the track's line
        c = e.chans(n)[0]
        boxes = e.regions[c]
        for k, r in enumerate(boxes):
            xa = int(round(mid + (r[0] / fpb - t.pos) * ppb))
            xb = int(round(mid + (r[1] / fpb - t.pos) * ppb))
            spliced_before = k > 0 and int(boxes[k - 1][1]) == int(r[0])
            spliced_after = k + 1 < len(boxes) and int(boxes[k + 1][0]) == int(r[1])
            a = xa + (2 if spliced_before else 0)
            b = xb - (1 if spliced_after else 0)     # a splice: a pixel's gap, the divider, a pixel's gap
            a, b = max(x0, a), min(x1, b)
            if b > a:
                f.rect(a, top, b - a, 7)
            if spliced_after and x0 <= xb < x1:
                f.rect(xb, top, 1, 8)
    # the loop's in and out points: a line under the ruler between them
    region = e.loop_region()
    if region:
        a = int(round(mid + (region[0] / fpb - t.pos) * ppb))
        b = int(round(mid + (region[1] / fpb - t.pos) * ppb))
        a, b = max(x0, a), min(x1 - 1, b)
        if b >= a:
            f.rect(a, 13, b - a + 1, 1, 1 if e.loop_on else 1)
            for x in (a, b):
                f.rect(x, 10, 1, 4)
    # the playhead: every other pixel, the opposite of what's under it
    for y in range(10, LANE_TOPS[-1] + 9):
        if y % 2 == 0:
            f.dot(mid, y, 0 if f.px[y, mid] else 1)
    # the bottom line: the selected track
    n = T.armed - 1
    pan = e.pans[n]
    pan_t = "C" if abs(pan) < 0.05 else ("L%d" % round(-pan * 100) if pan < 0 else "R%d" % round(pan * 100))
    info = "T%d VOL %d PAN %s %s%s" % (T.armed, round(e.volumes[n] * 100), pan_t,
                                       "LOOP" if (region and e.loop_on) else "",
                                       " ST" if n in e.stereo else "")
    f.small(1, H - 6, info)


def track_boxes(f, T, n, y, h, x0, x1, mid, ppb):
    """Track n's boxes between y and y + h, each with its ends (a splice shows as a gap), and its sound."""
    e, t = T.engine, T.tape
    fpb = e.frames_per_beat()
    for c in e.chans(n)[:1]:                         # the left side (a stereo track's right is under it)
        lv = e.levels[c] if c < len(e.levels) else None
        for r in e.regions[c]:
            a, b = r[0] / fpb, r[1] / fpb
            ra = int(round(mid + (a - t.pos) * ppb))
            rb = int(round(mid + (b - t.pos) * ppb))
            if rb < x0 or ra > x1:
                continue
            left_end, right_end = ra >= x0, rb - 1 <= x1 - 1
            ra, rb = max(x0, ra), min(x1 - 1, rb - 1)
            if rb < ra:
                continue
            f.rect(ra, y, rb - ra + 1, 1)
            f.rect(ra, y + h - 2, rb - ra + 1, 1)
            if left_end:
                f.rect(ra, y, 1, h - 1)
            if right_end:
                f.rect(rb, y, 1, h - 1)
            if lv is not None:
                for x in range(ra, rb + 1):
                    beat = t.pos + (x - mid) / ppb
                    idx = int(beat * tape.RES)
                    if 0 <= idx < len(lv):
                        v = int(min(1.0, float(lv[idx])) * (h - 4))
                        if v:
                            f.rect(x, y + 1 + (h - 3 - v) // 2, 1, max(1, v))


def bar_dots(f, T, top, bottom, x0, x1, mid, ppb):
    """Bar lines (dotted) and beat ticks along the top."""
    t = T.tape
    bar = tape.BEATS_PER_BAR
    b0 = t.pos - (mid - x0) / ppb
    k = int(b0 // bar)
    while True:
        bx = int(round(mid + (k * bar - t.pos) * ppb))
        if bx > x1:
            break
        if bx >= x0:
            for y in range(top, bottom, 2):
                f.dot(bx, y)
        k += 1
    if ppb >= 4:
        k = int(b0)
        while True:
            bx = int(round(mid + (k - t.pos) * ppb))
            if bx > x1:
                break
            if bx >= x0:
                f.dot(bx, top)
            k += 1


def focus_page(f, T):
    """The zoomed track (left button 4), as drawn in the screen designer: the tape's header, a ruler (long
    tick on the bar, middle one on the half bar, short ones on the beats), the track's sound as one solid
    waveform in 2-pixel columns, splices as an I-beam cutting a gap through it, a line along the bottom.
    The playhead is the notch in the ruler, in the middle. Knobs: 1 mono / stereo, 2 input (3 a stereo
    track's right), 4-6 the box under the playhead (gain, fade in, fade out); values show as they turn."""
    e, t = T.engine, T.tape
    n = T.focus.shown
    tape_header(f, T)
    x0, x1 = 11, 124                                  # the track's area, left of it the number
    mid = x0 + (x1 - x0) // 2
    ruler_y, bottom_y = 11, 58
    centre, half = 35, 16                             # the waveform's middle row and its tallest reach
    beats_across = tape.ZOOMS[t.zoom] * tape.BEATS_PER_BAR
    ppb = (x1 - x0) / beats_across
    f.text(2, 15, str(n))
    if not e.audible(n - 1):
        f.rect(1, 23, 7, 1)                           # muted: a line under the number
    if (n - 1) in e.stereo:
        f.small(1, 26, "ST")
    # the ruler
    f.rect(x0, ruler_y, x1 - x0, 1)
    bar = tape.BEATS_PER_BAR
    first = int((t.pos - (mid - x0) / ppb)) - 1
    k = first
    while True:
        x = int(round(mid + (k - t.pos) * ppb))
        if x >= x1:
            break
        if x >= x0:
            in_bar = k % bar
            if abs(in_bar) < 1e-6:
                f.rect(x, ruler_y + 1, 1, 3)          # the bar
            elif ppb >= 3 and abs(in_bar - bar / 2) < 1e-6:
                f.rect(x, ruler_y + 1, 1, 2)          # the half bar
            elif ppb >= 3:
                f.dot(x, ruler_y + 1)                 # a beat
        k += 1
    # the bottom line
    f.rect(x0, bottom_y, x1 - x0, 1)
    # the sound: each box's levels, solid, in 2-pixel columns
    fpb = e.frames_per_beat()
    c = e.chans(n - 1)[0]
    lv = e.levels[c] if c < len(e.levels) else None
    splices = []
    boxes = e.regions[c]
    for i, r in enumerate(boxes):
        a, b = r[0] / fpb, r[1] / fpb
        xa = int(round(mid + (a - t.pos) * ppb))
        xb = int(round(mid + (b - t.pos) * ppb))
        if i and int(boxes[i - 1][1]) == int(r[0]):
            splices.append(xa)                        # touching the box before: a splice
        if xb < x0 or xa >= x1 or lv is None:
            continue
        for x in range(max(x0, xa), min(x1, xb)):
            col = x0 + (x - x0) // 2 * 2                         # 2-pixel columns: both read the same level
            beat = t.pos + (col + 1 - mid) / ppb
            idx = int(beat * tape.RES)
            if 0 <= idx < len(lv):
                h = max(1, int(round(min(1.0, float(lv[idx])) * half)))
                f.rect(x, centre - h, 1, 2 * h + 1)
    for x in splices:
        if x0 <= x < x1:
            for y in range(ruler_y + 2, bottom_y - 1):          # the I-beam; where it crosses the sound, a gap
                beside = f.px[y, x - 1] if x > 0 else 0
                f.dot(x, y, 0 if beside or (x + 1 < W and f.px[y, x + 1]) else 1)
            f.rect(x - 2, ruler_y + 2, 5, 1)
            f.rect(x - 2, bottom_y - 2, 5, 1)
    # the playhead: a notch in the ruler
    f.rect(mid - 1, ruler_y, 3, 1, 0)
    f.dot(mid, ruler_y + 1)
    f.dot(mid, ruler_y + 2)


# ------------------------------------------------------------------ instruments

def inst_page(f, T):
    e, ip = T.engine, T.instp
    header(f, "INSTRUMENTS")
    if ip.mode == "pick":
        carousel(f, ip)
        return
    if ip.mode == "store":
        st = ip.store
        header(f, "SCHWUNG", "%d" % len(st.items))
        rows = [("FX  " if m["component_type"] == "audio_fx" else "") + m["name"].upper() for m in st.items]
        if rows:
            listing(f, rows, ip.pick, top=11, fit=5)
            f.small(1, 47, (st.items[min(ip.pick, len(st.items) - 1)].get("description", "")).upper()[:31])
            f.small(1, 53, (st.items[min(ip.pick, len(st.items) - 1)].get("description", "")).upper()[31:62])
        f.rect(0, H - 7, W, 7, 1)
        f.small(1, H - 6, (st.msg or "PUSH: INSTALL  BACK: LEAVE")[:31], 0)
        return
    if ip.mode == "menu":
        items = [c[1] if isinstance(c, (tuple, list)) else str(c) for c in ip.choices]
        listing(f, items, ip.pick, top=11)
        return
    names = {}
    try:
        import instpage
        names = {m: title for m, title in instpage.machines()}
    except Exception:
        pass
    rows = []
    for k in range(8):
        mid = e.slots[k] if e else None
        mute = e and k in e.slot_mutes
        rows.append("%d %s%s" % (k + 1, (names.get(mid, mid) or "-").upper(), "  MUTE" if mute else ""))
    listing(f, rows, ip.row, top=11)


_IMG = {}
_CAR = {"pos": None, "t": 0.0}


def instrument_image(mid):
    """The picture for an instrument (move/instimg/<id>.txt: 64 rows of 32 hex digits), or None."""
    if mid not in _IMG:
        arr = None
        try:
            import os
            rows = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "instimg", "%s.txt" % mid)).read().split()
            arr = np.array([[(int(row, 16) >> (127 - x)) & 1 for x in range(128)] for row in rows[:64]], np.uint8)
        except (OSError, ValueError):
            pass
        _IMG[mid] = arr
    return _IMG[mid]


def carousel(f, ip):
    """Choosing an instrument: one picture at a time, sliding left and right as the wheel turns. An
    instrument without a picture yet shows its name."""
    n = len(ip.choices)
    now = time.monotonic()
    pos = _CAR["pos"]
    if pos is None or now - _CAR["t"] > 1.0:
        pos = float(ip.pick)                           # just opened: start on the picked one
    else:
        pos += (ip.pick - pos) * 0.45                  # ease towards it
        if abs(ip.pick - pos) < 0.02:
            pos = float(ip.pick)
    _CAR["pos"], _CAR["t"] = pos, now
    for i in (int(pos // 1), int(pos // 1) + 1):
        if not 0 <= i < n:
            continue
        dx = int(round((i - pos) * W))
        mid, title = ip.choices[i][0], ip.choices[i][1]
        img = instrument_image(mid)
        if img is not None:
            x0, x1 = max(0, dx), min(W, dx + W)
            if x1 > x0:
                f.px[0:64, x0:x1] = img[:, x0 - dx:x1 - dx]
        else:
            f.frame(dx + 4, 4, W - 8, H - 8)
            f.centre(dx + W // 2, 26, str(title)[:19])
    if pos > 0.05:
        f.small(0, 29, "<", 1)
    if pos < n - 1.05:
        f.small(W - 3, 29, ">", 1)


def listing(f, rows, pick, top=11, line=7, fit=None):
    """A list in small letters, the picked row inverted, scrolled to keep it on screen."""
    fit = fit or (H - top) // line
    first = max(0, min(pick - fit // 2, len(rows) - fit))
    for i in range(fit):
        k = first + i
        if k >= len(rows):
            break
        y = top + i * line
        if k == pick:
            f.rect(0, y - 1, W, line, 1)
            f.small(2, y, str(rows[k])[:31], 0)
        else:
            f.small(2, y, str(rows[k])[:31])


# ------------------------------------------------------------------ an instrument's sound

def lfo_page(f, T):
    ml = T.mlfo
    e = T.engine
    header(f, "LFO %d" % (ml.tab + 1), "PAT %d" % (e.seq.current + 1))
    for i, (label, value) in enumerate(ml.values()):
        col, row = divmod(i, 3)
        x, y = col * 65, 13 + row * 11
        f.small(x + 1, y, "%d %s" % (i + 1, label))
        f.right(x + 62, y + 5, str(value)[:9], small=True)
    f.small(1, 50, "STEPS: TAP = REST, HOLD + 2/4")
    f.small(1, 57, "< > : SETTINGS / LFO 1 / LFO 2")


def sound_page(f, T):
    if T.mlfo.active():
        lfo_page(f, T)
        return
    e = T.engine
    d = e.drums
    pages = T.drum_pages()
    T.drum_tab = min(T.drum_tab, len(pages) - 1)
    page_name, params = pages[T.drum_tab]
    voice = T.drum_voice
    names = getattr(d, "names", None) or []
    vname = names[voice] if voice < len(names) else ""
    octave = getattr(T, "octave", 0)
    header(f, ("%s %s" % (vname, page_name)).strip()[:15 if octave else 18],
           ("OCT %+d  " % octave if octave else "") + "%d/%d" % (T.drum_tab + 1, len(pages)))
    now = time.monotonic()
    turning = None
    for i, _p in enumerate(params):
        when = T.drumpage.edited.get(i + 1, 0.0)
        if now - when < 1.0 and (turning is None or when > T.drumpage.edited.get(turning + 1, 0.0)):
            turning = i
    if turning is not None:                           # a knob turning: that one setting, big
        p = params[turning]
        if d.kind(p) in ("menu", "onoff", "voice", "vel_target", "lfo_target"):
            f.centre(W // 2, 26, d.value_text(p)[:20])
        else:
            f.bar_lines(W // 2, 31, d.fraction(p))
        f.text(1, 55, "%d %s" % (turning + 1, d.label(p))[:13])
        f.right(W - 1, 55, d.value_text(p)[:7])
        return
    for i, p in enumerate(params[:8]):              # the page's settings in knob order: 1-4 left, 5-8 right
        col, row = divmod(i, 4)
        x, y = col * 65, 11 + row * 11
        f.small(x + 1, y, ("%d %s" % (i + 1, d.label(p)))[:9])
        if d.kind(p) in ("menu", "onoff", "voice", "vel_target", "lfo_target"):
            f.right(x + 62, y, d.value_text(p)[:6], small=True)
        else:
            frac = max(0.0, min(1.0, d.fraction(p)))
            f.rect(x + 1, y + 7, 60, 1)
            f.rect(x + 1 + int(frac * 59), y + 6, 2, 3)


def synth_seq_page(f, T):
    """The synth sequencer (see movesynth.py): the 16 steps the buttons show, and the knobs or the held step."""
    import notes
    e, ms = T.engine, T.msyn
    seq = e.seq
    first = ms.first()
    pat = "PAT %d" % (seq.current + 1) + (">%d" % (seq.queued + 1) if seq.queued is not None else "")
    rec = "REC " if T.live_rec else ""
    if ms.selected:
        header(f, ms.which(), pat)
    elif ms.lane is not None and ms.kind:
        header(f, rec + "NOTE " + notes.note_name(ms.lane), pat)
    else:
        header(f, rec + ("PER NOTE" if ms.kind else "UNIFIED"), pat)
    at = ms.playing_step()
    length = ms.length()
    for k in range(16):
        i = first + k
        x, y = 1 + k * 8, 11
        if i >= length:
            f.dot(x + 3, y + 3)
            continue
        on = (ms.lane in ms.notes_at(i)) if (ms.lane is not None and ms.kind) else bool(ms.notes_at(i))
        (f.rect if on else f.frame)(x, y, 7, 7)
        if i in ms.down or i in ms.selected:
            f.frame(x - 1, y - 1, 9, 9)
        if at is not None and i == at:
            f.rect(x + 2, y + 2, 3, 3, 0 if on else 1)
    f.small(1, 20, "STEPS %d-%d OF %d" % (first + 1, min(first + 16, length), length))
    if ms.selected:
        f.frame(8, 27, 112, 26)
        f.rect(9, 28, 110, 24, 0)
        if ms.sel is None:
            f.centre(64, 31, "PRESS A PAD")
            f.centre(64, 42, "LIT: THE STEP HAS IT", small=True)
        else:
            key, label = ms.pad_items()[ms.sel]
            f.centre(64, 30, str(label)[:16])
            f.centre(64, 40, ("KNOB 1: %s" % ms.item_value(key))[:22], small=True)
            f.centre(64, 46, "SAME PAD AGAIN: OFF" if ms.engaged(key) else "TURN KNOB 1 TO SET IT", small=True)
        return
    if ms.down:
        f.small(1, 28, "PADS: ADD / TAKE OFF NOTES")
        f.small(1, 35, "TAP A LATER STEP: LENGTH")
        f.small(1, 42, "KNOB 1: LENGTH")
        return
    for i, (label, value, _x) in enumerate(ms.knob_list()):
        col, row = divmod(i, 4)
        x, y = col * 65, 28 + row * 7
        f.small(x + 1, y, ("%d %s" % (i + 1, label))[:10])
        f.right(x + 62, y, str(value)[:5], small=True)
    f.small(66, 49, "SHIFT+STEPS: SETTINGS")


def seq_page(f, T):
    """The drum sequencer: the picked lane's 16 steps on the buttons (drawn small at the top), and what the
    knobs do: the lane's settings, or while a step button is held, that step's (see moveseq.py)."""
    e = T.engine
    synth = T.synth_shown()
    if synth:
        synth_seq_page(f, T)
        return
    ms = T.mseq
    sp, seq = T.seqp, e.seq
    lane = sp.lane
    ln = seq.lane(lane)
    first = ms.first()
    names = getattr(e.drums, "lane_names", None) or []
    name = names[lane] if lane < len(names) else "LANE %d" % (lane + 1)
    pat = "PAT %d" % (seq.current + 1) + (">%d" % (seq.queued + 1) if seq.queued is not None else "")
    if ms.held is None:
        header(f, name[:13], pat)
    else:
        header(f, ms.which(), name[:12])
    # the 16 steps the buttons show
    at = ms.playing_step()
    for k in range(16):
        i = first + k
        x, y = 1 + k * 8, 11
        if i >= ln.length:
            f.dot(x + 3, y + 3)
            continue
        on = ln.steps[i].on
        (f.rect if on else f.frame)(x, y, 7, 7)
        if i == ms.held:
            f.frame(x - 1, y - 1, 9, 9)
        if at is not None and i == at:
            f.rect(x + 2, y + 2, 3, 3, 0 if on else 1)
    f.small(1, 20, "STEPS %d-%d OF %d" % (first + 1, min(first + 16, ln.length), ln.length))
    if ms.held is not None:
        # holding a step: its settings are on the pads; the picked one on knob 1 (OP-XY style)
        knobs = ms.knob_list()
        f.frame(8, 27, 112, 26)
        f.rect(9, 28, 110, 24, 0)
        if not knobs:
            f.centre(64, 31, "PRESS A PAD")
            f.centre(64, 42, "LIT: THE STEP HAS IT", small=True)
        else:
            label, value, on = knobs[0]
            f.centre(64, 30, str(label)[:16])
            f.centre(64, 40, ("KNOB 1: %s" % value)[:22], small=True)
            f.centre(64, 46, "SAME PAD AGAIN: OFF" if on else "TURN KNOB 1 TO SET IT", small=True)
        return
    # the knobs
    knobs = ms.knob_list()
    for i, (label, value, locked) in enumerate(knobs[:8]):
        col, row = divmod(i, 4)
        x, y = col * 65, 28 + row * 7
        f.small(x + 1, y, ("%d %s" % (i + 1, label))[:10])
        if locked:
            f.rect(x + 62 - Frame_width(str(value)[:5]) - 2, y - 1, Frame_width(str(value)[:5]) + 3, 7, 1)
            f.right(x + 62, y, str(value)[:5], small=True, c=0)
        else:
            f.right(x + 62, y, str(value)[:5], small=True)
    if ms.held is None and len(knobs) <= 4:
        f.small(66, 28, "+- PATTERN")
        f.small(66, 35, "<> STEPS")
        f.small(66, 42, "SHIFT+STEPS:")
        f.small(66, 49, " SETTINGS")


# ------------------------------------------------------------------ song mode

def song_page(f, T):
    """Song mode: the picked row's pattern for each instrument (knobs 1-7) and how many times it plays (8)."""
    sg = T.song
    sg.check_song()
    header(f, "SONG " + ("ON" if sg.on else "OFF"),
           "ROW %d/%d" % (sg.pick + 1, len(sg.rows)) if sg.rows else "NO ROWS")
    if not sg.rows:
        f.small(1, 14, "STEP BUTTON 1: ADD A ROW")
        f.small(1, 21, "EACH ROW: A PATTERN FOR")
        f.small(1, 28, "EVERY INSTRUMENT, PLAYED")
        f.small(1, 35, "SO MANY TIMES (KNOB 8)")
        f.small(1, 46, "+ / -: SONG MODE ON / OFF")
        return
    row = sg.rows[sg.pick]
    slots = sg.slots()
    for i, slot in enumerate(slots):
        col, r = divmod(i, 4)
        x, y = col * 65, 13 + r * 8
        v = row["pats"].get(slot)
        f.small(x + 1, y, "%d %s" % (i + 1, sg.short(slot)))
        f.right(x + 62, y, "-" if v is None else "P%d" % (v + 1), small=True)
    col, r = divmod(7, 4)
    f.small(66, 13 + r * 8, "8 PLAYS")
    f.right(W - 2, 13 + r * 8, "x%d" % row["repeat"], small=True)
    if sg.playing_row is not None:
        f.small(1, 48, "PLAYING ROW %d" % (sg.playing_row + 1))
    f.small(1, 56, "STEPS: ROWS  DEL+STEP: OUT")


# ------------------------------------------------------------------ effects

def fx_page(f, T):
    e = T.engine
    which = T.fx_page
    if which == "insert":
        ins = T.insfx()
        header(f, "INSERT: ON THE WHOLE MIX")
        f.small(1, 13, "1 EFFECT")
        f.right(W - 2, 13, ins.name()[:14], small=True)
        for i in range(3):
            label, shown = ins.text(i)
            if label:
                f.small(1, 23 + i * 10, "%d %s" % (i + 2, label))
                f.right(W - 2, 23 + i * 10, shown[:10], small=True)
        f.small(1, 59, (ins.error or "NOT ON THE TAPE").upper()[:31])
        return
    header(f, which.upper())
    for i, (k, name) in enumerate(T.FX_KNOBS[which]):
        y = 13 + i * 10
        f.small(1, y, "%d %s" % (i + 1, name))
        f.right(W - 2, y, T.fx_value_text(k)[:10], small=True)
    s = e.inst_send(which) if e else None
    f.small(1, 43, "4 THIS INSTRUMENT'S SEND")
    f.right(W - 2, 51, ("%d%%" % round(s * 100)) if s is not None else "NONE: OWN FX", small=True)
    f.small(1, 59, "GOES ONTO THE TAPE WITH IT")


# ------------------------------------------------------------------ the menus (any of the Pi's menu screens)

def kit_list(f, k):
    """The drums menu (Menu on a sound page): its choices and the project's, in one list (the wheel stops at the
    ends)."""
    import kitmenu
    rows = [kitmenu.TEXTS[key].upper() for key, _ in kitmenu.ITEMS] + \
           [kitmenu.MAIN_TEXTS[key].upper() for key, _ in kitmenu.MAIN]
    f.rect(0, 0, W, 9, 1)
    f.text(1, 1, "DRUMS MENU", 0)
    f.right(W - 2, 2, "%d/%d" % (k.choice + 1, len(rows)), small=True, c=0)
    listing(f, rows, k.choice, top=11, line=7, fit=6)       # (the bottom line is for messages)
    msg = getattr(k, "msg", "")
    if msg:
        f.rect(0, H - 8, W, 8, 1)
        f.small(1, H - 6, str(msg).upper()[:31], 0)


def text_page(f, s, msg=""):
    """A Pi menu screen: its texts, row by row (from top to bottom), the highlighted row inverted."""
    bar = s.get("menu_bar")
    bar_y = (bar["y"], bar["y"] + bar["h"]) if bar and bar.get("h") else None
    rows = {}
    for it in s.items:
        if it.get("type") != "text" or not it.get("t"):
            continue
        y = int(it["y"]) // 12 * 12
        rows.setdefault(y, []).append(it)
    lines, pick = [], 0
    for y in sorted(rows):
        items = sorted(rows[y], key=lambda it: it["x"])
        text = "  ".join(str(it["t"]) for it in items)
        if bar_y and any(bar_y[0] - 4 <= it["y"] <= bar_y[1] for it in items):
            pick = len(lines)
        lines.append(text.upper())
    if not lines:
        lines = ["MENU"]
    f.rect(0, 0, W, 9, 1)
    f.text(1, 1, lines[0][:21], 0)
    rest = lines[1:]
    listing(f, rest, max(0, pick - 1), top=11, line=10)
