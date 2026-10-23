# Controller firmware

The code for the PGA2350 on the control board. It runs on **CircuitPython**,
so the code is plain text files you can open and edit.

It reads the 24 keys, the 11 knobs and the 11 knob pushes, and sends them to
the Pi as **USB MIDI** on channel 16. The board shows up as
"Console Controls".

| Control | MIDI message |
|---|---|
| Keys SW1–SW24 | Note 0–23 (on when pressed, off when let go) |
| Knob pushes ENC1–ENC11 | Note 32–42 |
| Knob turns ENC1–ENC11 | CC 1–11, relative: 65 = one click right, 63 = one click left |

## Putting it on the PGA2350 (once)

1. **Install CircuitPython.** Download the PGA2350 file from
   [circuitpython.org/board/pimoroni_pga2350](https://circuitpython.org/board/pimoroni_pga2350/)
   (a `.uf2` file).
2. **Hold the BOOT button** on the control board (SW25), plug the board into
   your computer with USB-C, then let go. A drive called **RP2350** appears.
3. **Drag the `.uf2` file onto that drive.** It restarts, and a drive called
   **CIRCUITPY** appears instead.
4. **Copy `boot.py` and `code.py`** from this folder onto CIRCUITPY,
   replacing the `code.py` that's there.
5. **Unplug it and plug it back in** (so `boot.py` can set the name).

To change the code later, plug the board into your computer, edit `code.py`
on the CIRCUITPY drive, and save. It restarts by itself.

## Testing it

**Easiest:** on the Pi, with the board plugged in, run

```
~/console/pi-app/test-controls.sh
```

It shows every key and knob on the Pi's screen. Each one lights up as you use
it and stays green once it has worked (knobs need a turn left, a turn right
and a push). R clears the marks, Q quits, and Console starts again afterwards.

On your computer, any MIDI monitor shows the messages. On the Pi, with the
board plugged in:

```
amidi -l
```

That lists it with a port name like `hw:3,0,0`. Then, using that name:

```
amidi -p hw:3,0,0 -d
```

prints the messages as you press keys and turn knobs (Ctrl+C to stop). Stop
the Console app first (`sudo systemctl stop console`), because only one
program can read the controller at a time.

## Pin check (finding a bad solder joint on a knob)

Run `~/console/pi-app/test-controls.sh` and press **P** (in the SSH window or on
a keyboard on the Pi). The board stops acting as a controller and reports both
turning wires of every knob, and the screen shows them live with a verdict per
knob: OK, A or B DEAD (that wire's joint is broken), A+B JOINED (a solder
bridge between the two), or STUCK LOW (shorted to ground). Each wire shows its
pin (GP20 = pad 20 on the PGA2350). Press **P** again and the board restarts as
a normal controller. (Holding SW1 for 5 seconds while plugging the board in
also starts it.)

## If something's off

- **A knob moves two steps per click:** set `DIVISOR = 2` in `code.py`
  (or `1`), save, and try again.
- **A knob turns the wrong way:** tell Claude which one; it's a one-line swap.
- **A key does nothing:** check its hotswap socket is soldered, then test it
  with `amidi` to see if a note arrives.
