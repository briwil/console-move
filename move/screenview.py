"""A big screen for Console: a web page on the Move that shows the tape properly (8 tracks with real waveforms,
the playhead, bar grid, loop points, track states), for a phone or tablet on the same network (the phone's
hotspot works anywhere):

    http://move.local:8080

It only shows: nothing on it changes Console. The page asks for the state about 15 times a second (a small
piece of JSON) and for a track's waveform only when it has changed; with no page open it costs nothing.
Made for a Galaxy Z Fold's open screen (2448 x 1848, landscape), and fits any other.
"""
import base64
import json
import os
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

PORT = int(os.environ.get("CONSOLE_SCREEN_PORT", "8080"))
HERE = os.path.dirname(os.path.abspath(__file__))

_T = None                 # console.Transport
_M = None                 # the project menu (a menu open: the tape view)
_frame = None             # the Move's own screen, the latest one drawn (screen.Frame)
_server = None


def start(T, menu=None):
    """Called by app.py once Console is running."""
    global _T, _M, _server
    _T, _M = T, menu
    try:
        _server = ThreadingHTTPServer(("", PORT), _Handler)
    except OSError as e:
        print("Big screen: couldn't open port %d (%s)" % (PORT, e))
        return
    _server.daemon_threads = True
    th = threading.Thread(target=_serve, daemon=True, name="big screen")
    th.start()
    print("Big screen: http://move.local:%d" % PORT)


def _serve():
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)     # below the sound and the controls
    except (AttributeError, OSError):
        pass
    _server.serve_forever(poll_interval=0.5)


_asked = 0.0              # when a page last asked (no page open: nothing is copied)


def frame(f):
    """app.py: the Move's screen as just drawn (for the small copy of it on the page)."""
    global _frame
    if time.monotonic() - _asked < 3:
        _frame = f.px.copy()


# ------------------------------------------------------------------ what the page gets

def _input_text(e, t):
    import pages
    src = e.inputs[t] if t < len(e.inputs) else None
    try:
        if isinstance(src, (list, tuple)):
            a, b = pages.input_parts(e, src[0]), pages.input_parts(e, src[1])
            return "%s  %s / %s" % (a[0], a[1], b[1]) if a[0] == b[0] else "%s %s / %s %s" % (a + b)
        if src == "mix":
            src = None
        a = pages.input_parts(e, src)
        return "%s  %s" % a
    except Exception:                                    # noqa: BLE001
        return ""


def _peak(e, t):
    src = e.inputs[t] if t < len(e.inputs) else None
    chans = list(src) if isinstance(src, (list, tuple)) else [src] if isinstance(src, int) else []
    try:
        return round(float(max([e.in_peaks[c] for c in chans if 0 <= c < len(e.in_peaks)] or [0.0])), 3)
    except Exception:                                    # noqa: BLE001
        return 0.0


def state():
    T = _T
    e = T.engine
    import tape
    fpb = e.frames_per_beat()
    region = e.loop_region()
    armed = set(e.arm_extra) | {T.armed - 1}
    tracks = []
    for t in range(8):
        chans = e.chans(t)
        boxes = [[round(r[0] / fpb, 4), round(r[1] / fpb, 4), int(r[2]) if len(r) > 2 and isinstance(r[2], (int, float))
                  else 0] for r in (e.regions[chans[0]] if chans else [])]
        tracks.append({
            "n": t + 1, "selected": t == T.armed - 1, "armed": t in armed, "audible": bool(e.audible(t)),
            "muted": t in e.mutes, "solo": t in e.solos, "stereo": t in e.stereo,
            "vol": round(e.volumes[t], 3), "pan": round(e.pans[t], 3), "input": _input_text(e, t),
            "peak": _peak(e, t) if (t in armed) else 0.0, "boxes": boxes,
            "waves": [_wave_id(c) for c in chans],
        })
    song = getattr(T, "song", None)
    page = _page(T)
    seq_id, seq_live = "", None
    if page == "seq":
        try:
            static, seq_live = seq_data(T)
            body = json.dumps(static, separators=(",", ":")).encode()
            seq_id = "%08x" % zlib.crc32(body)
            _seq_cache[seq_id] = body
            while len(_seq_cache) > 4:
                _seq_cache.pop(next(iter(_seq_cache)))
        except Exception as ex:                          # noqa: BLE001
            page, seq_live = "tape", {"error": str(ex)[:80]}
    out = {
        "page": page, "seq_id": seq_id, "seq": seq_live,
        "t": time.time(),
        "pos": round(T.tape.pos, 5), "playing": bool(T.playing), "recording": bool(T.recording),
        "overdub": e.rec_mode == "overdub", "bpm": round(e.bpm, 2),
        "sig": list(getattr(e, "time_sig", (4, 4))), "bar": tape.BEATS_PER_BAR, "unit": tape.BEAT_UNIT,
        "position": T.position_text(T.tape.pos), "length": round(e.frames / fpb, 3),
        "zoom": tape.ZOOMS[T.tape.zoom], "res": tape.RES,
        "loop": [round(region[0] / fpb, 4), round(region[1] / fpb, 4)] if region else None,
        "loop_on": bool(e.loop_on),
        "song": e.song or "", "song_mode": bool(song is not None and song.on and song.rows),
        "message": T.message if T.message and time.monotonic() < T.message_until else "",
        "tracks": tracks,
        "screen": _screen_b64(),
    }
    return out


_wave_cache = {}          # channel -> (crc, bytes)
_seq_cache = {}           # tag -> the sequencer's pattern as JSON (the page asks for it when the tag changes)


def _page(T):
    """Which view the big screen shows: the sequencer when the Move is on it, else the tape."""
    m = _M
    if m is not None and (m.open or getattr(getattr(m, "kits", None), "open", False)):
        return "tape"
    if getattr(T, "fx_page", None):
        return "tape"
    if getattr(T, "seq_page", False) and T.engine and T.engine.drums and T.engine.slot is not None:
        return "seq"
    return "tape"


def seq_data(T):
    """The shown instrument's pattern (what doesn't change while it plays), and what does (positions, the
    lane / steps picked)."""
    import sequencer
    e = T.engine
    seq = e.seq
    mid = e.slots[e.slot]
    try:
        import instpage
        title = dict(instpage.machines()).get(mid) or mid
    except Exception:                                    # noqa: BLE001
        title = mid
    playing = bool(e.playing)
    fpb = e.frames_per_beat()
    live = {"pattern": seq.current + 1, "queued": (seq.queued + 1) if seq.queued is not None else None,
            "rec": bool(getattr(T, "live_rec", False))}
    if T.synth_shown():
        import notes
        ms = T.msyn
        pat = seq.pattern
        nl = []
        for step, d in sorted(pat.notes.items()):
            for note, n in sorted(d.items()):
                nl.append([step, note, n.length, n.vel, n.chance, n.ratchet, len(n.locks), len(n.comp)])
        shown = seq.shown_notes()
        static = {"kind": "notes", "title": title, "length": pat.length,
                  "rate": sequencer.RATES[pat.rate][0], "notes": nl,
                  "lane_len": {str(k): v for k, v in pat.lane_len.items()},
                  "root": notes.NAMES[seq.root], "scale": notes.SCALES[seq.scale][0],
                  "degrees": [(seq.root + d) % 12 for d in seq.degrees()],
                  "per_note": bool(getattr(seq, "move_type", 0)), "bar_beats": seq.bar_beats,
                  "spb": pat.steps_per_beat()}
        live.update({"shown": shown, "lane": ms.lane, "first": ms.first(), "page_len": ms.length(),
                     "down": sorted(ms.down), "selected": sorted(ms.selected),
                     "at": ms.playing_step() if playing else None})
        return static, live
    ms = T.mseq
    d = e.drums
    n = max(1, min(sequencer.MAX_LANES, getattr(d, "lanes", 8)))
    names = list(getattr(d, "lane_names", None) or [])
    lanes = []
    for li in range(n):
        ln = seq.pattern.lanes[li]
        steps = [[1 if st.on else 0, st.vel, st.chance, st.ratchet, len(st.locks), len(st.comp)]
                 for st in ln.steps[:ln.length]]
        lanes.append({"name": names[li] if li < len(names) else "LANE %d" % (li + 1), "length": ln.length,
                      "rate": sequencer.RATES[ln.rate][0], "spb": ln.steps_per_beat(), "hits": ln.hits,
                      "group": sequencer.group_steps(ln.steps_per_beat(), tuple(getattr(e, "time_sig", (4, 4)))),
                      "steps": steps})
    static = {"kind": "drums", "title": title, "lanes": lanes, "chances": sequencer.CHANCES}
    try:
        at = seq.position(e._heard_frame(), fpb) if playing else None
    except Exception:                                    # noqa: BLE001
        at = None
    live.update({"lane": T.seqp.lane, "first": ms.first(), "held": ms.held, "selected": list(ms.selected),
                 "at": at})
    return static, live


def _wave_id(c):
    """A short tag that changes when channel c's waveform does (the page then asks for it)."""
    lv = _T.engine.levels[c] if c < len(_T.engine.levels) else None
    if lv is None:
        return "%d:0" % c
    crc = zlib.crc32(lv.tobytes())
    if _wave_cache.get(c, (None,))[0] != crc:
        v = np.clip(np.asarray(lv, np.float32), 0.0, 1.0)
        _wave_cache[c] = (crc, (v * 255).astype(np.uint8).tobytes())
    return "%d:%08x" % (c, crc)


def wave(c):
    _wave_id(c)
    return _wave_cache.get(c, (0, b""))[1]


def _screen_b64():
    f = _frame
    if f is None:
        return ""
    try:
        return base64.b64encode(np.packbits(f.astype(bool), axis=1).tobytes()).decode()
    except Exception:                                    # noqa: BLE001
        return ""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype, cache=False):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=31536000" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path in ("/", "/index.html"):
                self._send(open(os.path.join(HERE, "screenview.html"), "rb").read(), "text/html; charset=utf-8")
            elif path == "/manifest.json":
                self._send(json.dumps({"name": "Console", "short_name": "Console", "display": "fullscreen",
                                       "orientation": "landscape", "start_url": "/", "background_color": "#0b0c0e",
                                       "theme_color": "#0b0c0e",
                                       "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}]}
                                      ).encode(), "application/manifest+json")
            elif path == "/icon.svg":
                self._send(ICON.encode(), "image/svg+xml", cache=True)
            elif path == "/state":
                global _asked
                _asked = time.monotonic()
                self._send(json.dumps(state(), separators=(",", ":")).encode(), "application/json")
            elif path.startswith("/seq/"):
                body = _seq_cache.get(path.split("/")[2])
                if body is None:
                    self.send_error(404)
                else:
                    self._send(body, "application/json", cache=True)
            elif path.startswith("/wave/"):
                c = int(path.split("/")[2].split(":")[0])
                self._send(wave(c), "application/octet-stream", cache=True)    # (its URL has the tag in it)
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as ex:                          # noqa: BLE001
            try:
                self.send_error(500, str(ex)[:100])
            except Exception:                            # noqa: BLE001
                pass


ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" '
        'fill="#0b0c0e"/><g fill="#f2b33d"><rect x="10" y="18" width="44" height="5" rx="2"/><rect x="10" y="29" '
        'width="30" height="5" rx="2"/><rect x="10" y="40" width="38" height="5" rx="2"/></g><rect x="31" y="12" '
        'width="2" height="40" fill="#ff5a4e"/></svg>')
