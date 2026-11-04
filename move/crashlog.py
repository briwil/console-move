"""The crash log: every run of the app writes to console/crashes/running.log (what it prints, the buttons
pressed, and - if the app crashes inside an effect or synth - the Python line it was on). When the app quits
normally the file is thrown away. If it's still there at the next start, the last run crashed (or froze and
was killed): it's kept as crashes/crash-<date>.log, so it's never overwritten by the next run.

    ls /data/UserData/console/crashes
    cat /data/UserData/console/crashes/crash-*.log | tail -120

If the main loop stops for FREEZE seconds (a hang, not a crash) every thread's Python line is written too.
"""
import collections
import faulthandler
import os
import sys
import time

HOME = os.environ.get("CONSOLE_HOME", "/data/UserData/console")
DIR = os.path.join(HOME, "crashes")
RUNNING = os.path.join(DIR, "running.log")
KEEP = 20                       # crash files kept (the oldest go)
MAX_BYTES = 1500000             # running.log is trimmed to its last part past this
FREEZE = 20                     # seconds the main loop can stop before its threads are written out

_fd = None
_writes = 0
_last_arm = 0.0
_crash = None                   # the crash file saved at start-up (the last run's), or None
recent = collections.deque(maxlen=12)    # the last few actions (the stress test shows them)


def _write(text):
    global _writes
    if _fd is None or not text:
        return
    try:
        os.write(_fd, text.encode("utf-8", "replace"))
    except OSError:
        return
    _writes += 1
    if _writes % 200 == 0:
        _trim()


def _trim():
    """Too big: keep its last third (the part that matters for a crash)."""
    try:
        if os.fstat(_fd).st_size <= MAX_BYTES:
            return
        with open(RUNNING, "rb") as fh:
            fh.seek(-MAX_BYTES // 3, os.SEEK_END)
            tail = fh.read()
        os.ftruncate(_fd, 0)
        os.write(_fd, b"(older lines trimmed)\n" + tail)
    except OSError:
        pass


class _Tee:
    """Prints still go to app.log, and to running.log too."""

    def __init__(self, real):
        self.real = real

    def write(self, s):
        try:
            self.real.write(s)
        except Exception:                                # noqa: BLE001
            pass
        _write(s)
        return len(s)

    def flush(self):
        try:
            self.real.flush()
        except Exception:                                # noqa: BLE001
            pass

    def __getattr__(self, name):
        return getattr(self.real, name)


def _commit():
    try:
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        head = open(os.path.join(repo, ".git", "HEAD")).read().strip()
        if head.startswith("ref: "):
            return open(os.path.join(repo, ".git", head[5:])).read().strip()[:8]
        return head[:8]
    except OSError:
        return "?"


def start(note=""):
    """At start-up: keep the last run's log if it crashed, then start this run's. Returns the kept crash
    file's name, or None."""
    global _fd, _crash
    try:
        os.makedirs(DIR, exist_ok=True)
        if os.path.exists(RUNNING) and os.path.getsize(RUNNING) > 0:
            stamp = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(os.path.getmtime(RUNNING)))
            name = "crash-%s.log" % stamp
            os.replace(RUNNING, os.path.join(DIR, name))
            _crash = name
            old = sorted(f for f in os.listdir(DIR) if f.startswith("crash-"))
            for f in old[:-KEEP]:
                os.remove(os.path.join(DIR, f))
        _fd = os.open(RUNNING, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_APPEND, 0o644)
    except OSError as ex:
        print("crash log: can't write %s (%s)" % (DIR, ex))
        _fd = None
        return None
    _write("Console started %s  (version %s)%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), _commit(),
                                                     ("  " + note) if note else ""))
    faulthandler.enable(file=_fd, all_threads=True)       # a native crash (an effect, a synth): the Python line
    sys.stdout = _Tee(sys.stdout)
    sys.stderr = _Tee(sys.stderr)
    return _crash


def last_crash():
    return _crash


def action(what):
    """A button, knob, pad... (the last ones before a crash say what led to it)."""
    recent.append(str(what))
    if _fd is not None:
        _write("%s %s\n" % (time.strftime("%H:%M:%S"), what))


def alive(now):
    """Called by the main loop: if it stops for FREEZE seconds, every thread's Python line gets written."""
    global _last_arm
    if _fd is None or now - _last_arm < 1.0:
        return
    _last_arm = now
    try:
        faulthandler.dump_traceback_later(FREEZE, repeat=True, file=_fd)
    except (ValueError, RuntimeError):
        pass


def done():
    """The app quit normally: this run's log isn't needed."""
    global _fd
    if _fd is None:
        return
    try:
        faulthandler.cancel_dump_traceback_later()
        faulthandler.enable(all_threads=True)             # back to app.log
    except Exception:                                    # noqa: BLE001
        pass
    for s in ("stdout", "stderr"):
        t = getattr(sys, s)
        if isinstance(t, _Tee):
            setattr(sys, s, t.real)
    try:
        os.close(_fd)
        os.remove(RUNNING)
    except OSError:
        pass
    _fd = None
