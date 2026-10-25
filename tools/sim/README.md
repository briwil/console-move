# Simulator

Runs the Pi app's own code on any computer (Linux, Mac or Windows) with no Pi, screen,
control board or audio device. It's how changes get tested before they go on the Pi:
press keys and turn knobs from a script, check what the engine did, and save what the
screen would show as a picture.

## What it needs

Python 3 with `numpy` and `Pillow`:

```
pip install numpy pillow
```

The drum synth also needs `gcc` (it builds `pi-app/drums/libdrums.so` by itself the first
time). Without it, everything except the drums still works.

## Trying it

```
python3 tools/sim/example.py
```

It puts a tone on track 1, normalizes it and fades it out in the zoomed view, and saves
screenshots to `sim-shots/`.

## Writing a test

```python
import sys; sys.path.insert(0, "tools/sim")
import sim                         # always first: it swaps in the stand-ins
e = sim.engine("My test")          # the audio engine; sim.engine(start=True) also runs the audio thread
T = sim.transport(e)               # the main screen: T.key("PLAY"), T.knob(number, clicks, shift)
sim.shot(T, "screen.png")          # the screen as a picture
m = sim.menu(T); m.show(); sim.shot(T, "menu.png", m)
```

- Key names are the ones in `pi-app/console.py` (`PLAY`, `RECORD`, `TRACK1`…`TRACK8`,
  `SPLICE`, `CUT`, `MUTE1` for pushing knob 1, and so on).
- `e.tracks[t]` is track t+1's audio (numpy, −1 to 1), and `e.regions[t]` its boxes.
- To pretend to record, put the engine in recording and feed it audio blocks with
  `e.process(block)`, a float32 array shaped (frames, channels).
- Songs go to `sim-data/` (or wherever `CONSOLE_DATA` points), never to `~/console-data`.

## The stand-ins (`stubs/`)

| File | Stands in for |
|---|---|
| `pygame.py` | pygame. It draws with Pillow, so a surface's picture is `surface.img`. It covers only what Console uses. |
| `alsaaudio.py` | pyalsaaudio. Inputs give silence in real time, and what's played is kept in `PCM.writes`. |
| `nmcli` | NetworkManager, for the Wi-Fi menu. It lists a few made-up networks. Set `NMCLI_LOG` to a file to see the commands it was given. |

If the app starts using a pygame feature the stand-in doesn't have, add it to
`stubs/pygame.py`.
