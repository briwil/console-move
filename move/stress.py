"""The stress test: Console runs by itself on the Move for a while, the way a very busy (and slightly mad)
person would use it, to find crashes, freezes and memory leaks.

Start it (Console running or not):

    ssh -i ~/.ssh/move_key ableton@move.local "echo 60 > /data/UserData/console/stress"

(60 = minutes; "60 random" skips the first two parts.) If Console is running it restarts into the test; otherwise start Console as usual. It uses
its own projects (console/stress-data), so your songs and settings aren't touched. It:

  1. loads every instrument in turn and plays it (with the memory it took),
  2. loads every insert effect in turn (with a second one beside it) while a synth plays,
  3. then until the time's up: random buttons, pads, knobs and the wheel, plus every 20 seconds or so
     a random instrument into a random slot or a random insert effect, and now and then a new,
     saved or opened project.

Every 30 seconds it notes the app's memory. The report is console/stress-report.txt, written as it goes
(so a crash leaves it up to that point, and the crash itself is in console/crashes/):

    ssh -i ~/.ssh/move_key ableton@move.local "cat /data/UserData/console/stress-report.txt"

When it's finished Console restarts as normal with your own songs. Shift + Back stops it early.
"""
import os
import random
import shutil
import time
import traceback

HOME = os.environ.get("CONSOLE_HOME", "/data/UserData/console")
FLAG = os.path.join(HOME, "stress")
RUNNING = os.path.join(HOME, "stress.running")
REPORT = os.path.join(HOME, "stress-report.txt")
DATA = os.path.join(HOME, "stress-data")
INSERTS_FILE = os.path.join(HOME, "insert-fx.json")      # (shared with your own data: put back at the end)
BACKUP = os.path.join(HOME, "insert-fx.json.stress-backup")
RANDOM_ONLY = False             # "60 random" in the file: straight to part 3

# the Move's controls the test presses (see app.py). Not the volume knob, and never Shift + Back (that quits).
PADS = range(68, 100)
STEPS = range(16, 32)
KNOBS = range(71, 79)
WHEEL, PUSH, PLUS, MINUS, SHIFT, BACK = 14, 3, 55, 54, 49, 51
LEFT_BUTTONS = (43, 42, 41, 40)
BUTTONS = {85: 3, 86: 1, 58: 2, 62: 3, 63: 3, 56: 2, 52: 1, 118: 1, 88: 2, 50: 1}   # cc: how often
HOLDS = (60, 119)                                                                # Copy, Delete


def prepare():
    """At the very start (before anything reads CONSOLE_DATA). Returns the test's minutes, or None for
    a normal start."""
    if os.path.exists(FLAG):
        global RANDOM_ONLY
        try:
            words = open(FLAG).read().split()
            RANDOM_ONLY = "random" in [w.lower() for w in words[1:]]
            minutes = float(words[0]) if words else 60
        except (OSError, ValueError):
            minutes = 60
        minutes = max(1.0, min(24 * 60.0, minutes))
        try:
            os.replace(FLAG, RUNNING)
            shutil.rmtree(DATA, ignore_errors=True)
            os.makedirs(DATA, exist_ok=True)
            if os.path.exists(INSERTS_FILE) and not os.path.exists(BACKUP):
                shutil.copy2(INSERTS_FILE, BACKUP)
        except OSError:
            return None
        os.environ["CONSOLE_DATA"] = DATA
        return minutes
    if os.path.exists(RUNNING):                       # the last test never finished: it crashed or froze
        _note("\nSTOPPED %s: Console crashed or froze during the test (it never finished). "
              "The crash is in console/crashes/ (the newest crash-*.log).\n" % time.strftime("%H:%M:%S"))
        _cleanup()
    return None


def _note(text):
    try:
        with open(REPORT, "a") as fh:
            fh.write(text)
    except OSError:
        pass


def _cleanup():
    try:
        os.remove(RUNNING)
    except OSError:
        pass
    try:
        if os.path.exists(BACKUP):
            os.replace(BACKUP, INSERTS_FILE)
    except OSError:
        pass


def _status():
    out = {}
    try:
        for line in open("/proc/self/status"):
            k, _, v = line.partition(":")
            if k in ("VmRSS", "VmHWM", "Threads"):
                out[k] = int(v.split()[0])
    except OSError:
        pass
    try:
        out["fds"] = len(os.listdir("/proc/self/fd"))
    except OSError:
        out["fds"] = 0
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                out["avail"] = int(line.split()[1])
    except OSError:
        pass
    t = os.times()
    out["cpu"] = t.user + t.system
    return out


def _mb(kb):
    return kb / 1024.0


class Stress:
    def __init__(self, minutes, T, m, e, board):
        self.T, self.m, self.e, self.board = T, m, e, board
        self.start = time.monotonic()
        self.end = self.start + minutes * 60
        self.minutes = minutes
        seed = int(time.time())
        self.rng = random.Random(seed)
        self.pending = []                     # [(when, midi bytes)]: releases still to come
        self.shift = False
        self.events = 0
        self.actions = 0
        self.problems = []
        self.mem = []                         # [(seconds, rss kb)]
        self.loads = []                       # [(what, rss before, rss after)]
        self.finished = False
        self.phase = "random" if RANDOM_ONLY else "instruments"
        if RANDOM_ONLY:
            self.random_from = self.start
        self.next_event = self.start + 2
        self.next_mem = self.start
        self.next_peak = self.start
        self.next_cp = 0.0
        self.cp_at = None
        self.baselines = []                   # [(seconds, rss kb)]: an empty project's memory, now and then
        self.peak = 0
        self.next_action = 0.0
        self.next_home = 0.0
        self.next_project = 0.0
        self.saves = 0
        self.last_cpu = (self.start, _status().get("cpu", 0))
        self.inst_list = self._machines()
        self.fx_count = self._fx_count()
        self.inst_i = 0
        self.fx_i = 1
        self.step_at = 0.0
        self.sub = 0
        self.before = 0
        self.random_from = getattr(self, "random_from", None)
        try:
            import crashlog
            self.crashlog = crashlog
        except ImportError:
            self.crashlog = None
        try:
            self.rep = open(REPORT, "w", buffering=1)
        except OSError:
            self.rep = None
        self.say("CONSOLE STRESS TEST  started %s, %d minutes (seed %d)" %
                 (time.strftime("%Y-%m-%d %H:%M:%S"), minutes, seed))
        self.say("%d instruments, %d insert effects to try" % (len(self.inst_list), self.fx_count - 1))
        self.say("")
        m.update_action = lambda: None         # (no software updates in the middle of the test)

    # ------------------------------------------------------------ helpers

    def say(self, text):
        line = "%s  %s" % (self.clock(), text) if text else ""
        if self.rep:
            try:
                self.rep.write(line + "\n")
            except OSError:
                pass
        if self.crashlog:
            self.crashlog.action("[stress] " + text)

    def clock(self):
        s = int(time.monotonic() - self.start)
        return "%3d:%02d" % (s // 60, s % 60)

    def left(self):
        return max(0, int(self.end - time.monotonic()))

    def _machines(self):
        try:
            import drums
            return [mid for mid, _ in drums.available_machines()]
        except Exception:                                    # noqa: BLE001
            return []

    def _fx_count(self):
        try:
            import catalog
            return 1 + len(catalog.FX)
        except Exception:                                    # noqa: BLE001
            return 1

    def problem(self, what):
        self.problems.append("%s  %s" % (self.clock(), what))
        self.say("PROBLEM: " + what)

    def guarded(self, label, fn):
        """A direct action (load an instrument...): a Python error is noted, and the test goes on."""
        self.actions += 1
        try:
            fn()
        except Exception:                                    # noqa: BLE001
            self.problem("%s failed:\n%s" % (label, traceback.format_exc().rstrip()))

    def send(self, *msg):
        b = bytes(msg)
        if b[0] & 0xF0 == 0xB0 and b[1] == SHIFT:
            self.shift = b[2] > 0
        if b[0] & 0xF0 == 0xB0 and b[1] == BACK and b[2] and self.shift:
            return                                           # Shift + Back would quit: never
        self.events += 1
        self.board(b)

    def later(self, delay, *msg):
        self.pending.append((time.monotonic() + delay, bytes(msg)))

    def press(self, cc, hold=0.08):
        self.send(0xB0, cc, 127)
        self.later(hold, 0xB0, cc, 0)

    def pad(self, n, vel=100, hold=0.15):
        self.send(0x90, n, vel)
        self.later(hold, 0x90, n, 0)

    def release_all(self):
        for _, b in self.pending:
            self.board(b)
        self.pending = []
        if self.shift:
            self.send(0xB0, SHIFT, 0)

    def beat(self, now):
        """About 8 times a second (a pad while an instrument or effect is tried)."""
        if now < self.next_event:
            return False
        self.next_event = now + 0.12
        return True

    def rss(self):
        return _status().get("VmRSS", 0)

    def slots_text(self):
        e = self.e
        try:
            ins = getattr(self.T, "_insfx", None) or {}
            fx = ["%d.%d:%s" % (k + 1, p + 1, v.name()) for (k, p), v in sorted(ins.items()) if v.index]
            return "slots %s  inserts %s" % ([s or "-" for s in e.slots], fx or "none")
        except Exception:                                    # noqa: BLE001
            return ""

    def memory(self, now):
        s = _status()
        cpu_t, cpu = self.last_cpu
        pct = 100.0 * (s.get("cpu", 0) - cpu) / max(0.001, now - cpu_t)
        self.last_cpu = (now, s.get("cpu", 0))
        self.mem.append((now - self.start, s.get("VmRSS", 0), self.phase))
        self.say("MEMORY %.1f MB (peak %.1f)  threads %d  files %d  Move free %.0f MB  cpu %.0f%%  %s" %
                 (_mb(s.get("VmRSS", 0)), _mb(s.get("VmHWM", 0)), s.get("Threads", 0), s.get("fds", 0),
                  _mb(s.get("avail", 0)), pct, self.slots_text()))
        if os.environ.get("CONSOLE_TRACEMALLOC"):          # (for finding where Python's memory went)
            import tracemalloc
            if not tracemalloc.is_tracing():
                tracemalloc.start(8)
            else:
                for st in tracemalloc.take_snapshot().statistics("traceback")[:4]:
                    self.say("   %.1f MB  %s" % (st.size / 1048576.0, " <- ".join(
                        "%s:%d" % (os.path.basename(f.filename), f.lineno) for f in list(st.traceback)[::-1][:6])))
        if s.get("avail", 10 ** 9) < 60 * 1024:
            self.problem("the Move is almost out of memory (%.0f MB free)" % _mb(s["avail"]))

    def disk_low(self):
        try:
            st = os.statvfs(HOME)
            return st.f_bavail * st.f_frsize < 400 * 1024 * 1024
        except OSError:
            return False

    # ------------------------------------------------------------ the main loop calls this

    def tick(self, now):
        """Returns False once the test is over (the app then restarts as normal)."""
        if self.finished:
            return False
        due = [p for p in self.pending if p[0] <= now]
        if due:
            self.pending = [p for p in self.pending if p[0] > now]
            for _, b in due:
                self.send(*b)
        if now >= self.next_mem:
            self.next_mem = now + 30
            self.memory(now)
        if now >= self.next_peak:                            # a sudden jump in memory: what was just done
            self.next_peak = now + 0.5
            st = _status()
            hwm = st.get("VmHWM", 0)
            if self.peak and hwm - self.peak > 40 * 1024:
                recent = [r for r in (self.crashlog.recent if self.crashlog else []) if not r.startswith("[stress] MEMORY")]
                self.say("MEMORY JUMP +%.0f MB (peak %.0f MB, now %.0f MB) just after: %s" % (
                    _mb(hwm - self.peak), _mb(hwm), _mb(st.get("VmRSS", 0)), " | ".join(recent[-6:])))
            self.peak = hwm
        if now >= self.end:
            self.finish("finished")
            return False
        try:
            if self.phase == "instruments":
                self.sweep_instruments(now)
            elif self.phase == "inserts":
                self.sweep_inserts(now)
            else:
                self.monkey(now)
        except Exception:                                    # noqa: BLE001
            self.problem("the test itself (%s):\n%s" % (self.phase, traceback.format_exc().rstrip()))
            self.phase = "random"
        return True

    # ------------------------------------------------------------ 1: every instrument

    def playing(self, on):
        if bool(self.e.playing) != on:
            self.press(85)

    def sweep_instruments(self, now):
        e = self.e
        if now < self.step_at:
            if self.sub == 1 and self.beat(now):             # playing it: a few pads
                self.pad(self.rng.choice(PADS), self.rng.randint(30, 127), self.rng.uniform(0.05, 0.4))
            return
        if self.sub == 1:                                     # done playing the last one
            self.playing(False)
            after = self.rss()
            what = self.inst_list[self.inst_i]
            problem = ""
            try:
                problem = e.drums.m.problem() if hasattr(e.drums.m, "problem") else ""
            except Exception:                                # noqa: BLE001
                pass
            self.loads.append((what, self.before, after))
            self.say("  %-16s +%.1f MB%s" % (what, _mb(after - self.before),
                                            ("   (it says: %s)" % problem) if problem else ""))
            self.inst_i += 1
            self.sub = 0
        if self.inst_i >= len(self.inst_list):
            self.guarded("empty slot 1", lambda: e.set_slot(0, None))
            self.say("")
            self.say("2. EVERY INSERT EFFECT (slot 1, with a synth playing)")
            self.phase, self.sub, self.step_at = "inserts", 0, now + 1
            return
        if self.inst_i == 0 and self.sub == 0 and not getattr(self, "_titled", False):
            self._titled = True
            self.say("1. EVERY INSTRUMENT (memory it added)")
        what = self.inst_list[self.inst_i]
        self.before = self.rss()
        other = e.slot_of(what)

        def load():
            if other not in (None, 0):
                e.set_slot(other, None)                      # (it can only be in one slot)
            if not e.set_slot(0, what):
                self.problem("%s wouldn't load" % what)
            e.open_slot(0)
        self.guarded("load " + what, load)
        self.playing(True)
        self.sub, self.step_at = 1, now + 4

    # ------------------------------------------------------------ 2: every insert effect

    def sweep_inserts(self, now):
        e, T = self.e, self.T
        if self.sub == 0:                                    # a synth to play through them
            synth = next((m for m in ("braids", "plaits", "obxd", "sampler") if m in self.inst_list), None)
            synth = synth or (self.inst_list[0] if self.inst_list else None)
            if synth:
                self.guarded("load " + synth, lambda: (e.set_slot(0, synth), e.open_slot(0)))
            self.playing(True)
            self.sub, self.step_at = 2, now + 1
            return
        if now < self.step_at:
            if self.beat(now):
                self.pad(self.rng.choice(PADS), self.rng.randint(40, 127), self.rng.uniform(0.05, 0.5))
            if self.rng.random() < 0.02:                    # and its knobs
                ins = T.insfx(0, 0)
                ins.knob(self.rng.randrange(8), self.rng.choice((-3, -1, 1, 3)))
            return
        if self.sub == 3:
            after = self.rss()
            ins = T.insfx(0, 0)
            title = ins.choices()[self.fx_i] if self.fx_i < len(ins.choices()) else str(self.fx_i)
            self.loads.append(("fx " + title, self.before, after))
            self.say("  %-16s +%.1f MB%s" % (title, _mb(after - self.before),
                                            ("   (%s)" % ins.error) if ins.error else ""))
            self.fx_i += 1
        if self.fx_i >= self.fx_count:
            self.guarded("inserts off", lambda: (T.insfx(0, 0).choose(0), T.insfx(0, 1).choose(0), T._insfx_save()))
            self.playing(False)
            self.say("")
            self.say("3. RANDOM USE until the time's up")
            self.phase = "random"
            self.random_from = now
            self.next_action = now + 2
            return
        self.before = self.rss()
        i = self.fx_i
        j = self.rng.randrange(self.fx_count)

        def load():
            T.insfx(0, 0).choose(i)
            T.insfx(0, 1).choose(j)                          # a second one beside it (sometimes none)
            T._insfx_save()
        self.guarded("insert %d" % i, load)
        self.sub, self.step_at = 3, now + 3

    # ------------------------------------------------------------ 3: random use

    def checkpoint(self, now):
        """Every 8 minutes: an empty project (no instruments, no effects), memory measured after a few seconds.
        Those should stay about the same; if they keep climbing, something isn't giving memory back."""
        e, T = self.e, self.T
        if self.cp_at is None:
            self.release_all()
            self.playing(False)

            def empty():
                for k in range(8):
                    for pos in (0, 1):
                        ins = (getattr(T, "_insfx", None) or {}).get((k, pos))
                        if ins is not None and ins.index:
                            ins.choose(0)
                    e.set_slot(k, None)
                T._insfx_save()
            self.guarded("empty project", empty)
            self.cp_at = now + 6
            return
        if now < self.cp_at:
            return
        kb = self.rss()
        self.baselines.append((now - self.start, kb))
        self.say("CHECK: empty project uses %.1f MB" % _mb(kb))
        self.cp_at = None
        self.next_cp = now + 8 * 60
        for _ in range(3):                                   # and some instruments again
            if self.inst_list:
                k, what = self.rng.randrange(8), self.rng.choice(self.inst_list)
                self.guarded("slot %d %s" % (k + 1, what),
                             lambda k=k, what=what: e.slot_of(what) is None and e.set_slot(k, what))

    def monkey(self, now):
        r = self.rng
        if self.cp_at is not None or now >= self.next_cp:
            self.checkpoint(now)
            return
        if now >= self.next_home:                            # now and then: back out of wherever it got to
            self.next_home = now + r.uniform(40, 90)
            self.release_all()
            for k in range(3):
                self.later(0.05 + k * 0.1, 0xB0, BACK, 127)
                self.later(0.08 + k * 0.1, 0xB0, BACK, 0)
            if self.disk_low():
                self.playing(False)
                self.say("disk nearly full: stopped")
            return
        if now >= self.next_action:
            self.next_action = now + r.uniform(12, 30)
            self.direct(now)
            return
        if now < self.next_event:
            return
        self.next_event = now + r.expovariate(10)            # about 10 a second
        x = r.random()
        if x < 0.30:
            self.pad(r.choice(PADS), r.randint(1, 127), r.uniform(0.03, 1.5))
        elif x < 0.45:
            n = r.choice(STEPS)
            self.send(0x90, n, 127)
            self.later(r.choice((0.05, 0.1, 0.6, 1.5)), 0x90, n, 0)
        elif x < 0.65:
            k = r.choice(KNOBS)
            d = r.choice((1, 1, 1, 2, 5, -1, -1, -1, -2, -5))
            for t in range(r.randint(1, 6)):
                self.later(t * 0.03, 0xB0, k, d if d > 0 else 128 + d)
        elif x < 0.73:
            d = r.choice((1, -1))
            self.send(0xB0, WHEEL, d if d > 0 else 127)
        elif x < 0.77:
            self.press(PUSH)
        elif x < 0.80:
            self.press(r.choice((PLUS, MINUS)))
        elif x < 0.85:
            self.press(r.choice(LEFT_BUTTONS))
        elif x < 0.92:
            names = list(BUTTONS)
            cc = r.choices(names, [BUTTONS[c] for c in names])[0]
            if cc == 86 and self.disk_low():
                return
            self.press(cc)
        elif x < 0.95:
            cc = r.choice(HOLDS)
            self.send(0xB0, cc, 127)
            self.later(r.uniform(0.1, 2.0), 0xB0, cc, 0)
        elif x < 0.98:
            if not self.shift:
                self.send(0xB0, SHIFT, 127)
                self.later(r.uniform(0.2, 2.5), 0xB0, SHIFT, 0)
        else:
            self.press(BACK)

    def direct(self, now):
        """What random presses rarely get to: instruments, insert effects, projects."""
        e, T, r = self.e, self.T, self.rng
        x = r.random()
        if now >= self.next_project and x < 0.25:
            self.next_project = now + r.uniform(180, 420)
            y = r.random()
            if y < 0.4:
                self.saves += 1
                name = "STRESS %d" % self.saves
                self.say("save project as %s" % name)
                self.guarded("save", lambda: e.save_as(name) if e.song is None else e.save(wait=True))
            elif y < 0.7:
                songs = e.song_names()
                if songs:
                    name = r.choice(songs)
                    self.say("open project %s" % name)
                    self.guarded("open " + name, lambda: T.open_song(name))
            else:
                self.say("new project")
                self.guarded("new", lambda: T.new_song(None))
            return
        if x < 0.6 and self.inst_list:
            k = r.randrange(8)
            what = None if r.random() < 0.15 else r.choice(self.inst_list)
            other = e.slot_of(what) if what else None
            self.say("slot %d: %s" % (k + 1, what or "empty"))

            def load():
                if other not in (None, k):
                    e.set_slot(other, None)
                e.set_slot(k, what)
                if what and r.random() < 0.5:
                    e.open_slot(k)
            self.guarded("slot %d %s" % (k + 1, what), load)
        else:
            k, pos = r.randrange(8), r.randrange(2)
            i = 0 if r.random() < 0.2 else r.randrange(1, max(2, self.fx_count))
            self.say("insert %d of slot %d: %d" % (pos + 1, k + 1, i))

            def load():
                ins = T.insfx(k, pos)
                ins.choose(i)
                T._insfx_save()
                if ins.error:
                    self.say("  (%s: %s)" % (ins.name(), ins.error))
            self.guarded("insert", load)

    # ------------------------------------------------------------ the end

    def finish(self, why):
        if self.finished:
            return
        self.finished = True
        try:
            self.release_all()
        except Exception:                                    # noqa: BLE001
            pass
        self.memory(time.monotonic())
        self.say("")
        self.say("RESULT (%s)" % why)
        self.say("  %d presses and turns, %d instrument / effect / project changes" % (self.events, self.actions))
        if len(self.baselines) >= 2:
            first, last = self.baselines[0][1], self.baselines[-1][1]
            self.say("  empty project's memory, every 8 minutes: " +
                     ", ".join("%.0f" % _mb(kb) for _, kb in self.baselines) + " MB")
            if _mb(last - first) > 30 and _mb(self.baselines[-2][1] - first) > 15:
                self.say("  MEMORY KEEPS GROWING: a likely leak (send this report)")
                if RANDOM_ONLY:
                    self.say("  (an instrument stays in memory once it's been used, so some growth is expected "
                             "here: a full test, without \"random\", tries them all first)")
            else:
                self.say("  memory: no sign of a leak")
        else:
            self.say("  memory: too short a test to tell about leaks (run it for 30 minutes or more)")
        big = sorted(self.loads, key=lambda x: x[1] - x[2])[:5]
        if big:
            self.say("  most memory: " + ", ".join("%s +%.0f MB" % (w, _mb(b - a)) for w, a, b in big))
        if self.problems:
            self.say("  %d PROBLEMS (above, marked PROBLEM)" % len(self.problems))
        else:
            self.say("  no problems")
        if why == "finished":
            self.say("Console restarts as normal now (your own songs).")
        if self.rep:
            try:
                self.rep.close()
            except OSError:
                pass
            self.rep = None
        _cleanup()
