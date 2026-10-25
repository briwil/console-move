"""An example test: records a made-up sound, edits it, and saves screenshots.
Run from anywhere:  python3 tools/sim/example.py   (pictures go to ./sim-shots/)"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim                                         # noqa: E402  (must come before the app's modules)
import numpy as np                                 # noqa: E402

out = os.path.abspath("sim-shots")
os.makedirs(out, exist_ok=True)

e = sim.engine("Example")
T = sim.transport(e)
R = e.rate

# put a 2-second tone on track 1 as one box (like a recording)
n = np.arange(2 * R)
with e.lock:
    e.tracks[0][R:3 * R] = 0.25 * np.sin(2 * np.pi * 220 * n / R)
    e._add_region(0, R, 3 * R)
    e._update_levels(0, R, 3 * R, reset=True)

T.armed = e.armed = 1
T.set_pos(3)                                       # the playhead, in beats
sim.shot(T, os.path.join(out, "1-main.png"))

T.key("TRACK1")                                    # zoom into track 1
for _ in range(60):
    T.focus.update(0.05, False)
T.key("MUTE1")                                     # push knob 1: normalize the box
T.knob(3, 10, True)                                # knob 3: fade out
print(T.message)
sim.shot(T, os.path.join(out, "2-zoomed.png"))

m = sim.menu(T)
m.show()
sim.shot(T, os.path.join(out, "3-menu.png"), m)
print("pictures in", out)
