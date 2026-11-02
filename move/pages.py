"""The Move's screens: what the Pi app's state looks like on 128 x 64 pixels. Each page reads the app's own
state (console.Transport, the engine, the menus) and draws it; nothing here changes anything.

    draw(frame, T, menu)      picks the page the app is on and draws it
"""
import time

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
            text_page(f, menu.kits.s, getattr(menu.kits, "msg", ""))
        elif T.seq_page:
            seq_page(f, T)
        elif T.drum_page:
            sound_page(f, T)
        elif T.inst_page:
            inst_page(f, T)
        elif T.fx_page:
            fx_page(f, T)
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

def tape_page(f, T):
    e, t = T.engine, T.tape
    state = "REC" if T.recording else "PLAY" if T.playing else "STOP"
    if e and e.rec_mode == "overdub" and T.recording:
        state = "ODUB"
    f.rect(0, 0, W, 9, 1)
    f.text(1, 1, state, 0)
    bpm = "%.0f" % (e.bpm if e else 120)
    f.small(30, 2, bpm + " BPM", 0)
    f.right(W - 2, 2, T.position_text(t.pos)[:12], small=True, c=0)
    if not e:
        return
    fpb = e.frames_per_beat()
    beats_across = tape.ZOOMS[t.zoom] * tape.BEATS_PER_BAR
    x0, x1 = 10, W
    mid = x0 + (x1 - x0) // 2
    ppb = (x1 - x0) / beats_across                  # pixels per beat
    first = ((T.armed - 1) // TRACKS_SHOWN) * TRACKS_SHOWN
    top = 10
    # bars and beats
    bar = tape.BEATS_PER_BAR
    b0 = t.pos - (mid - x0) / ppb
    k = int(b0 // bar)
    while True:
        bx = int(round(mid + (k * bar - t.pos) * ppb))
        if bx > x1:
            break
        if bx >= x0:
            for y in range(top, top + TRACKS_SHOWN * LANE_H, 2):
                f.dot(bx, y)
        k += 1
    if ppb * 1 >= 4:                                 # beats, if there's room
        k = int(b0)
        while True:
            bx = int(round(mid + (k - t.pos) * ppb))
            if bx > x1:
                break
            if bx >= x0:
                f.dot(bx, top)
            k += 1
    region = e.loop_region()
    for i in range(TRACKS_SHOWN):
        n = first + i                                # 0-7
        y = top + i * LANE_H
        selected = n == T.armed - 1
        label = str(n + 1)
        if selected:
            f.rect(0, y, 8, LANE_H - 1, 1)
            f.text(2, y + 2, label, 0)
        else:
            f.text(2, y + 2, label)
        if n in e.arm_extra:
            f.dot(8, y + LANE_H // 2)
        if not e.audible(n):
            f.rect(1, y + LANE_H - 2, 6, 1)           # muted: a line under the number
        chans = e.chans(n)
        for c in chans[:1]:                          # the left side (a stereo track's right is under it)
            lv = e.levels[c] if c < len(e.levels) else None
            for r in e.regions[c]:
                a, b = r[0] / fpb, r[1] / fpb
                ra = int(round(mid + (a - t.pos) * ppb))
                rb = int(round(mid + (b - t.pos) * ppb))
                if rb < x0 or ra > x1:
                    continue
                # each box drawn on its own, with its ends and a pixel's gap where two boxes touch (a splice)
                left_end, right_end = ra >= x0, rb - 1 <= x1 - 1
                ra, rb = max(x0, ra), min(x1 - 1, rb - 1)
                if rb < ra:
                    continue
                f.rect(ra, y, rb - ra + 1, 1)
                f.rect(ra, y + LANE_H - 2, rb - ra + 1, 1)
                if left_end:
                    f.rect(ra, y, 1, LANE_H - 1)
                if right_end:
                    f.rect(rb, y, 1, LANE_H - 1)
                if lv is not None:
                    for x in range(ra, rb + 1):
                        beat = t.pos + (x - mid) / ppb
                        idx = int(beat * tape.RES)
                        if 0 <= idx < len(lv):
                            h = int(min(1.0, float(lv[idx])) * (LANE_H - 4))
                            if h:
                                f.rect(x, y + 1 + (LANE_H - 3 - h) // 2, 1, max(1, h))
    # the loop's in and out points
    if region:
        for edge in region:
            bx = int(round(mid + (edge / fpb - t.pos) * ppb))
            if x0 <= bx < x1:
                f.rect(bx, top, 1, 3)
                f.rect(bx, top + TRACKS_SHOWN * LANE_H - 3, 1, 3)
    # the playhead
    for y in range(top, top + TRACKS_SHOWN * LANE_H):
        if y % 2 == 0:
            f.dot(mid, y, 1)
    # the bottom line: the selected track
    n = T.armed - 1
    pan = e.pans[n]
    pan_t = "C" if abs(pan) < 0.05 else ("L%d" % round(-pan * 100) if pan < 0 else "R%d" % round(pan * 100))
    info = "T%d VOL %d PAN %s %s%s" % (T.armed, round(e.volumes[n] * 100), pan_t,
                                       "LOOP" if (region and e.loop_on) else "",
                                       " ST" if n in e.stereo else "")
    f.small(1, H - 6, info)


def focus_page(f, T):
    """The zoomed track: what each of the eight knobs does and its value, one knob a line (knob 1 MONO /
    STEREO, 2 the input, 3 a stereo track's right input, 4-6 the box under the playhead)."""
    n = T.focus.shown
    header(f, "TRACK %d" % n, "ZOOM")
    knobs = T.knob_labels() or []
    for i, item in enumerate(knobs[:8]):
        name, value = (item[0], item[1]) if isinstance(item, (tuple, list)) else (str(item), "")
        live = item[2] if isinstance(item, (tuple, list)) and len(item) > 2 else True
        y = 11 + i * 6
        name = {"MONO / STEREO": "MONO/ST"}.get(name, name)
        f.small(1, y, "%d %s" % (i + 1, name[:8]))
        if live:
            f.right(W - 1, y, str(value)[:20], small=True)


# ------------------------------------------------------------------ instruments

def inst_page(f, T):
    e, ip = T.engine, T.instp
    header(f, "INSTRUMENTS")
    if ip.mode in ("pick", "menu"):
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


def listing(f, rows, pick, top=11, line=7):
    """A list in small letters, the picked row inverted, scrolled to keep it on screen."""
    fit = (H - top) // line
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

def sound_page(f, T):
    e = T.engine
    d = e.drums
    pages = T.drum_pages()
    T.drum_tab = min(T.drum_tab, len(pages) - 1)
    page_name, params = pages[T.drum_tab]
    voice = T.drum_voice
    names = getattr(d, "names", None) or []
    vname = names[voice] if voice < len(names) else ""
    header(f, ("%s %s" % (vname, page_name)).strip()[:18], "%d/%d" % (T.drum_tab + 1, len(pages)))
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


def seq_page(f, T):
    """The sequencer: the picked lane's steps (a first version)."""
    e = T.engine
    seq = e.seq
    sp = T.sp()
    synth = T.synth_shown()
    header(f, ("SYNTH SEQ" if synth else "SEQUENCER"), "PAT %d" % (getattr(seq, "current", 0) + 1))
    if synth:
        f.small(1, 12, "SYNTH SEQUENCER:")
        f.small(1, 19, "STEP BUTTONS COMING NEXT")
        return
    lane = getattr(sp, "lane", 0)
    d = e.drums
    names = getattr(d, "lane_names", None) or []
    f.text(1, 12, (names[lane] if lane < len(names) else "LANE %d" % (lane + 1))[:20])
    ln = seq.lane(lane)
    length = getattr(ln, "length", 16)
    pos = None
    if e.playing:
        try:
            pos = seq.position(e.seq_clock, e.frames_per_beat())
        except Exception:
            pos = None
    playing_step = None
    if isinstance(pos, (tuple, list)):
        playing_step = pos[1] if len(pos) > 1 else pos[0]
    elif isinstance(pos, (int, float)):
        playing_step = int(pos)
    for i in range(min(16, length)):
        col, row = i % 8, i // 8
        x, y = 4 + col * 15, 24 + row * 15
        on = seq.step(lane, i).on
        if on:
            f.rect(x, y, 12, 12)
        else:
            f.frame(x, y, 12, 12)
        if playing_step is not None and i == int(playing_step) % max(1, length):
            f.rect(x + 4, y + 4, 4, 4, 0 if on else 1)


# ------------------------------------------------------------------ effects

def fx_page(f, T):
    e = T.engine
    which = T.fx_page
    keys = [k for k in (e.fx or {}) if k.startswith("rev" if which == "reverb" else "dly")]
    header(f, which.upper())
    for i, k in enumerate(keys):
        y = 13 + i * 10
        f.small(1, y, "%d %s" % (i + 1, k.split("_", 1)[1].upper()))
        f.right(W - 2, y, T.fx_value_text(k)[:10], small=True)


# ------------------------------------------------------------------ the menus (any of the Pi's menu screens)

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
    listing(f, rest, max(0, pick - 1), top=11, line=7)
