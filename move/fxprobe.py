"""Tries every insert effect on its own, each in a separate process, so one that crashes can't take the others
(or Console) with it. For each effect: start it, run sound through it while its knobs move, close it; start
and close it a few more times; then two copies at once. Prints which ones crash, and where.

    ssh -i ~/.ssh/move_key ableton@move.local "python3 /data/UserData/console/move/fxprobe.py"

(Console can keep running: this doesn't use the sound.) Takes a few minutes. Just one: add its name, e.g.
fxprobe.py structor. The instruments: fxprobe.py instruments (or fxprobe.py instruments surge).
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
    stage("after closing: the memory checked")
    junk = [bytearray(n) for n in range(1, 40000, 37)]          # lots of allocating and freeing, so a damaged
    del junk                                                     # heap shows itself here
    import gc
    gc.collect()
    stage("done")
    return 0


def one_inst(mid):
    """In the child process: an instrument started, played (notes / drum hits) while its settings move,
    from the same thread and from another one at the same time."""
    import threading
    import drums

    def stage(s):
        print("stage: " + s, flush=True)
    stage("starting")
    d = drums.Drums("lxr")
    m = d.get(mid)
    if m is None:
        print("couldn't start", flush=True)
        return 3
    try:
        params = [p for _n, ps in m.pages(0) for p in ps]
    except Exception:                                    # noqa: BLE001
        params = []
    synth = hasattr(m, "note_on")

    def play(blocks, knobs=True):
        for b in range(blocks):
            if b % 8 == 0:
                if synth:
                    n = random.randrange(36, 84)
                    m.note_on(n, random.randint(30, 127))
                    if b % 16 == 0:
                        m.note_off(n)
                else:
                    m.hit(random.randrange(max(1, getattr(m, "lanes", 8))), random.randint(30, 127))
            m.render(BLOCK)
            if knobs and params and b % 10 == 0:
                twist()

    def twist():
        p = random.choice(params)
        try:
            v = m.stepped(p, m.get_param(p), random.choice((-40, -3, 3, 40)))
            print("set %s = %s" % (m.label(p), m.value_text(p, v) if hasattr(m, "value_text") else v), flush=True)
            m.set_param(p, v)
        except Exception:                                # noqa: BLE001
            pass
    stage("playing, settings moving")
    play(1500)
    stage("playing while settings move from another thread (as in Console)")
    go = [True]

    def sound():
        while go[0]:
            play(1, knobs=False)
    th = threading.Thread(target=sound)
    th.start()
    end = time.time() + 4
    while time.time() < end and params:
        twist()
        time.sleep(0.0005)
    go[0] = False
    th.join()
    if hasattr(m, "all_off"):
        m.all_off()
    play(100, knobs=False)
    stage("after: the memory checked")
    junk = [bytearray(n) for n in range(1, 40000, 37)]
    del junk
    import gc
    gc.collect()
    time.sleep(1)                                        # (its own threads, if it has any, keep going a moment)
    stage("done")
    return 0


def sweep(mid, key):
    """fxprobe.py sweep noisemaker voices: what the module says about one setting, then every value of it in
    turn while notes play (in a child process: a crash shows the value it was on)."""
    if os.environ.get("FXPROBE_CHILD") != "1":
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "sweep", mid, key],
                           env=dict(os.environ, FXPROBE_CHILD="1"), capture_output=True, text=True, timeout=300)
        out = (r.stdout + r.stderr).strip()
        print(out)
        if r.returncode:
            print("\nCRASHED (%s) on the last value above" % (_signame(-r.returncode) if r.returncode < 0 else r.returncode))
        return
    import json
    import numpy as np
    import catalog
    import modules
    folder = os.path.join(modules.MODULES_DIR, mid)
    inst = modules.Instance(os.path.join(folder, "dsp.so"), folder, {})
    chain = json.loads(inst.get("chain_params", big=True) or "[]")
    entry = next((c for c in chain if c.get("key") == key), None)
    print("chain_params entry: %s" % json.dumps(entry))
    print("its value now: %r" % inst.get(key), flush=True)
    if entry and entry.get("options"):
        values = list(entry["options"]) + list(range(len(entry["options"])))
    else:
        lo, hi = (entry or {}).get("min", 0), (entry or {}).get("max", 16)
        step = (entry or {}).get("step") or (1 if entry and entry.get("type") == "int" else (hi - lo) / 16.0)
        values, v = [], lo - step
        while v <= hi + step + 1e-9:
            values.append(round(v, 4))
            v += step
    out = np.zeros((128, 2), np.float32)
    for v in values:
        print("value %s ..." % v, end=" ", flush=True)
        inst.set(key, v)
        for b in range(60):
            if b % 6 == 0:
                inst.midi(0x90, 48 + b % 24, 100)
            if b % 6 == 3:
                inst.midi(0x80, 48 + (b - 3) % 24, 0)
            inst.render(out)
        print("ok (it says %r)" % inst.get(key), flush=True)


def _signame(n):
    try:
        return signal.Signals(n).name
    except ValueError:
        return str(n)


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--one":
        sys.exit(one(sys.argv[2]))
    if len(sys.argv) > 2 and sys.argv[1] == "--inst":
        sys.exit(one_inst(sys.argv[2]))
    if len(sys.argv) > 3 and sys.argv[1] == "sweep":
        return sweep(sys.argv[2], sys.argv[3])
    insts = len(sys.argv) > 1 and sys.argv[1] == "instruments"
    if insts:
        import drums
        ids = [mid for mid, _ in drums.available_machines()]
        wanted = sys.argv[2:]
    else:
        import catalog
        ids = [f["id"] for f in catalog.FX]
        wanted = sys.argv[1:]
    if wanted:
        ids = [i for i in ids if i in wanted]
    bad = []
    # the C library's memory checks on in each test: an effect that writes where it shouldn't is caught (a
    # damaged heap often doesn't crash the effect that did it, only something later, somewhere else)
    env = dict(os.environ, MALLOC_CHECK_="3", MALLOC_PERTURB_="165")
    dbg = next((p for p in ("/lib/libc_malloc_debug.so.0", "/usr/lib/libc_malloc_debug.so.0",
                            "/lib/aarch64-linux-gnu/libc_malloc_debug.so.0",
                 "/usr/lib/aarch64-linux-gnu/libc_malloc_debug.so.0", "/usr/lib/x86_64-linux-gnu/libc_malloc_debug.so.0") if os.path.exists(p)), None)
    if dbg:
        env["LD_PRELOAD"] = dbg
    try:
        old_libc = tuple(int(x) for x in os.confstr("CS_GNU_LIBC_VERSION").split()[1].split(".")[:2]) < (2, 34)
    except (ValueError, OSError, IndexError):
        old_libc = False
    print("Trying %d %s, one at a time (memory checks %s)...\n" %
          (len(ids), "instruments" if insts else "insert effects", "on" if (dbg or old_libc) else "partly on"),
          flush=True)
    for fx in ids:
        t = time.time()
        try:
            r = subprocess.run([sys.executable, os.path.abspath(__file__), "--inst" if insts else "--one", fx],
                               capture_output=True, text=True, timeout=90, env=env)
            out = (r.stdout + r.stderr).strip().splitlines()
            code = r.returncode
        except subprocess.TimeoutExpired as ex:
            out = ((ex.stdout or b"").decode(errors="replace") if isinstance(ex.stdout, bytes)
                   else (ex.stdout or "")).strip().splitlines()
            code = "hung"
        stages = [l[7:] for l in out if l.startswith("stage: ")]
        sets = [l for l in out if l.startswith("set ")]
        notes = [l for l in out if not l.startswith("stage: ") and l.strip() and not l.startswith("set ")
                 and not l.startswith("insert effect: starting") and not l.startswith("instrument: starting")]
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
            if sets:
                print("             the last settings changed: " + "; ".join(l[4:] for l in sets[-4:])[:300])
            bad.append(fx)
    print("\n%s" % ("Every one that starts is fine on its own." if not bad else
                    "Problem effects: " + ", ".join(bad)), flush=True)


if __name__ == "__main__":
    main()
