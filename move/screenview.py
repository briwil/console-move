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
_frame = None             # the Move's own screen, the latest one drawn (screen.Frame)
_server = None


def start(T):
    """Called by app.py once Console is running."""
    global _T, _server
    _T = T
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
    out = {
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
