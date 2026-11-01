"""How much of the Move's processor Console needs: the tape (8 tracks playing), the effects, and a drum
machine plus synths all playing busy patterns. No sound, no JACK: it just makes the audio as fast as it
can and times it.

    python3 /data/UserData/console/move/bench.py                       (lxr + obxd dexed plaits braids)
    python3 /data/UserData/console/move/bench.py lxr obxd hera wurl     (your own choice)

"LOAD" is the share of real time the work takes: 50% means a second of sound takes half a second to make.
Comfortable is under about 60%; over 100% can't play live at all.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("CONSOLE_PLATFORM", "move")
os.environ.setdefault("CONSOLE_DATA", "/data/UserData/console/bench-data")
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pi-app"))

import numpy as np   # noqa: E402
import audio         # noqa: E402

SECONDS = 15
machines = sys.argv[1:] or ["lxr", "obxd", "dexed", "plaits", "braids"]

audio.flush_denormals()
e = audio.Engine(song=None, bpm=120.0)
if not e.drums:
    sys.exit("The instruments didn't load (no drum synth libraries found). Copy the .so files over first.")

loaded = []
for m in machines:
    slot = len(loaded)
    if e.set_slot(slot, m):
        loaded.append(m)
    else:
        print("couldn't load", m, "(not built, or unknown)")
if not loaded:
    sys.exit("Nothing loaded.")

# busy patterns: drums on 6 lanes, synths 4-note chords on every beat plus a 16th-note line
for i, m in enumerate(loaded):
    s = e.seqs[m]
    if e.is_synth(m):
        for step in range(0, 16, 4):
            for note in (48, 55, 60, 64):
                s.toggle(step, note, 3)
        for step in range(16):
            s.toggle(step, 72 + (step * 5) % 12, 1)
    else:
        for lane in range(6):
            for step in range(lane % 2, 16, 2 if lane < 3 else 3):
                s.toggle(lane, step)

# the tape: 8 tracks of noise, all playing, with some reverb and delay
rng = np.random.default_rng(0)
for t in range(audio.TRACKS):
    e.tracks[t][:] = (rng.standard_normal(e.frames) * 0.05).astype(np.float32)
    e.rev_sends[t], e.dly_sends[t] = 0.2, 0.1
e.inst_view = True
e.device = audio.drum_device(audio.INST_CHANNELS)


def run(seconds, label):
    blocks = int(seconds * e.rate / audio.PERIOD)
    with e.lock:
        e.playing = False
    e._instruments_block(audio.PERIOD, False)
    with e.lock:
        e.playing = True
    was = False
    t0 = time.perf_counter()
    worst = 0.0
    for _ in range(blocks):
        b0 = time.perf_counter()
        x, mon, mr, md = e._instruments_block(audio.PERIOD, was)
        was = True
        e.process(x, monitor=mon, monitor_rev=mr, monitor_dly=md)
        worst = max(worst, time.perf_counter() - b0)
    took = time.perf_counter() - t0
    audio_s = blocks * audio.PERIOD / e.rate
    block_s = audio.PERIOD / e.rate
    print("%-34s LOAD %5.1f%%   slowest block %5.1f%% of its time" % (label, 100 * took / audio_s,
                                                                   100 * worst / block_s))


print("Loaded:", ", ".join(loaded), "| tape: 8 tracks + reverb + delay\n")
run(SECONDS, "everything together")
for i, m in enumerate(loaded):
    e.slot_mutes = set(range(len(loaded))) - {i}
    run(5, "%s alone (with the tape)" % m)
e.slot_mutes = set(range(len(loaded)))
run(5, "the tape alone")
