"""Tries every insert effect on its own, each in a separate process, so one that crashes can't take the others
(or Console) with it. For each effect: start it, run sound through it while its knobs move, close it; start
and close it a few more times; then two copies at once. Prints which ones crash, and where.

    ssh -i ~/.ssh/move_key ableton@move.local "python3 /data/UserData/console/move/fxprobe.py"

(Console can keep running: this doesn't use the sound.) Takes a few minutes. Just one: add its name, e.g.
fxprobe.py structor
"""
import os
import random
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(os.path.dirname(HERE), "pi-app")
sys.path[:0] = [os.path.join(APP, "schwung"), APP]
BLOCK = 128


def one(fx_id):
    """In the child process: put one effect through its paces, saying each stage as it starts."""
    import ctypes
    import numpy as np
    import catalog
    import insertfx
    index = 1 + [f["id"] for f in catalog.FX].index(fx_id)
    lib = insertfx.Insert()._lib()
    if lib is None:
        print("NO HOST LIBRARY")
        return 2
    rng = np.random.default_rng(1)
    fp = ctypes.POINTER(ctypes.c_float)

    def stage(s):
        print("stage: " + s, flush=True)

    def run(ins, blocks, knobs=True):
        for b in range(blocks):
            left = (rng.standard_normal(BLOCK) * 0.2).astype(np.float32)
            right = left.copy()
            lib.sh_fx_process(ins.h, left.ctypes.data_as(fp), right.ctypes.data_as(fp), BLOCK)
            if not np.all(np.isfinite(left)):
                print("note: it put out NaN / infinity", flush=True)
            if knobs and b % 20 == 0 and ins.params:
                ins.knob(random.randrange(len(ins.params)), random.choice((-5, -1, 1, 5)))

    stage("starting")
    a = insertfx.Insert(None, 0, 0)
    a.choose(index)
    if not a.h:
        print("couldn't start: %s" % a.error, flush=True)
        return 3
    stage("sound through it, knobs moving")
    run(a, 1500)
    stage("its settings read back")
    for p in a.params:
        a.text(a.params.index(p))
    stage("closing")
    a.choose(0)
    for k in range(3):
        stage("starting again (%d)" % (k + 2))
        a.choose(index)
        run(a, 100)
        stage("closing again (%d)" % (k + 2))
        a.choose(0)
    stage("knobs turned while sound runs at the same time (as in Console)")
    import threading
    a.choose(index)
    go = [True]

    def sound():
        while go[0]:
            run(a, 1, knobs=False)
    th = threading.Thread(target=sound)
    th.start()
    end = time.time() + 5
    while time.time() < end and a.params:
        k = random.randrange(len(a.params))
        a.knob(k, random.choice((-40, -5, -1, 1, 5, 40)))          # (big jumps too: ends of the range)
        time.sleep(0.0005)
    go[0] = False
    th.join()
    a.choose(0)
    stage("two at once")
    a.choose(index)
    b = insertfx.Insert(None, 1, 0)
    b.choose(index)
    run(a, 200)
    run(b, 200)
    stage("closing the first of two")
    a.choose(0)
    run(b, 200)
    stage("closing the second")
    b.choose(0)
    stage("done")
    return 0


def _signame(n):
    try:
        return signal.Signals(n).name
    except ValueError:
        return str(n)


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--one":
        sys.exit(one(sys.argv[2]))
    import catalog
    ids = [f["id"] for f in catalog.FX]
    if len(sys.argv) > 1:
        ids = [i for i in ids if i in sys.argv[1:]]
    bad = []
    print("Trying %d insert effects, one at a time...\n" % len(ids), flush=True)
    for fx in ids:
        t = time.time()
        try:
            r = subprocess.run([sys.executable, os.path.abspath(__file__), "--one", fx],
                               capture_output=True, text=True, timeout=90)
            out = (r.stdout + r.stderr).strip().splitlines()
            code = r.returncode
        except subprocess.TimeoutExpired as ex:
            out = ((ex.stdout or b"").decode(errors="replace") if isinstance(ex.stdout, bytes)
                   else (ex.stdout or "")).strip().splitlines()
            code = "hung"
        stages = [l[7:] for l in out if l.startswith("stage: ")]
        notes = [l for l in out if not l.startswith("stage: ") and l.strip()
                 and not l.startswith("insert effect: starting")]
        where = stages[-1] if stages else "?"
        if code == 0:
            print("  ok       %-18s (%.1f s)%s" % (fx, time.time() - t,
                                                   "   " + notes[-1] if any("NaN" in n for n in notes) else ""))
        elif code == 3:
            print("  -        %-18s %s" % (fx, " ".join(notes)[:80]))
        else:
            why = "FROZE" if code == "hung" else "CRASHED (%s)" % _signame(-code) if isinstance(code, int) and code < 0 \
                else "FAILED (exit %s)" % code
            print("  %s  %s, while: %s" % (why, fx, where), flush=True)
            for n in notes[-6:]:
                print("             " + n[:160])
            bad.append(fx)
    print("\n%s" % ("Every effect that starts is fine on its own." if not bad else
                    "Problem effects: " + ", ".join(bad)), flush=True)


if __name__ == "__main__":
    main()
