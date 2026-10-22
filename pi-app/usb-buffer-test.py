#!/usr/bin/env python3
"""Find the smallest audio buffer that records cleanly from your USB audio device (e.g. the OP-XY).

With small buffers the Pi's USB audio driver can garble the incoming audio (repeated 1 ms packets:
crackly, "distorted" recordings). This records a few seconds at several buffer sizes, the way the app
does (sending silence to the device at the same time), counts the glitches, and saves the smallest
clean size in ~/console-data/settings.json for the app to use.

Play something on the device the whole time (a song, a loop: anything loud and busy, about a minute),
then run:   ~/console/pi-app/usb-buffer-test.py
It pauses the Console app while it runs and starts it again at the end.
"""
import json
import os
import subprocess
import sys
import tempfile
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import audio  # noqa: E402

SIZES = [(512, 8), (1024, 4), (1024, 8), (2048, 4), (2048, 8)]     # (frames per block, blocks)
SECONDS = 8


def glitches_per_second(path, channels):
    with wave.open(path) as w:
        n = w.getnframes()
        x = np.frombuffer(w.readframes(n), "<i4").reshape(-1, channels)[:, 0] / 2 ** 31
    x = x[4410:]                                     # skip the first 0.1 s (start-up)
    if len(x) < 44100 or np.sqrt(np.mean(x ** 2)) < 0.01:
        return None, 0.0
    d = np.abs(np.diff(x))
    level = float(np.sqrt(np.mean(x ** 2)))
    # a glitch: a sudden step much bigger than the music's own movement around it
    big = np.flatnonzero(d > 0.15)
    count = 0
    for p in big:
        around = d[max(0, p - 30):p + 30]
        if d[p] > 10 * (np.median(around) + 1e-4):
            count += 1
    return count / (len(x) / 44100), level


def record(dev, period, periods, path):
    fmt, ch, rate = dev["capture"]["format"], dev["capture"]["channels"], audio.pick_rate(dev["capture"]["rates"])
    hw = "hw:CARD=%s,DEV=0" % dev["id"]
    size = [] if period is None else ["--period-size=%d" % period, "--buffer-size=%d" % (period * periods)]
    play = None
    if dev.get("playback"):
        p = dev["playback"]
        play = subprocess.Popen(["aplay", "-q", "-D", hw, "-c", str(p["channels"]), "-f", p["format"],
                                 "-r", str(audio.pick_rate(p["rates"])), "-t", "raw"] + size + ["/dev/zero"],
                                stderr=subprocess.DEVNULL)
    try:
        subprocess.run(["arecord", "-q", "-D", hw, "-c", str(ch), "-f", fmt, "-r", str(rate), "-d", str(SECONDS)]
                       + size + [path], check=True, timeout=SECONDS + 20)
    finally:
        if play:
            play.terminate()
            play.wait()
    return ch


def main():
    dev = audio.find_device()
    if not dev:
        print("No USB audio device with an input is plugged in.")
        return 1
    if dev["capture"]["format"] != "S32_LE":
        print("This test only knows 32-bit devices; %s sends %s." % (dev["name"], dev["capture"]["format"]))
        return 1
    print("Testing %s. Keep it playing something loud and busy until this finishes (about %d s)."
          % (dev["name"], (len(SIZES) + 1) * (SECONDS + 1)))
    restart = subprocess.run(["systemctl", "is-active", "--quiet", "console"]).returncode == 0
    if restart:
        print("Pausing the Console app (it may ask for your password)...")
        subprocess.run(["sudo", "systemctl", "stop", "console"], check=True)
    results = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for period, periods in [(None, None)] + SIZES:
                name = "Pi's default" if period is None else "%d x %d" % (period, periods)
                path = os.path.join(tmp, "t.wav")
                ch = record(dev, period, periods, path)
                rate, level = glitches_per_second(path, ch)
                if rate is None:
                    print("  %-14s  too quiet to judge: is it playing?" % name)
                    continue
                print("  %-14s  %5.1f glitches a second" % (name, rate))
                results.append((period, periods, rate))
    finally:
        if restart:
            print("Starting the Console app again...")
            subprocess.run(["sudo", "systemctl", "start", "console"])
    if not results:
        print("Couldn't judge any of them: play something louder and try again.")
        return 1
    base = results[0][2] if results[0][0] is None else 0.0
    clean = [r for r in results if r[0] is not None and r[2] <= base + 0.3]
    if not clean:
        print("Every size glitched. Tell Claude these numbers.")
        return 1
    period, periods, _ = clean[0]
    path = os.path.join(audio.DATA, "settings.json")
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data["usb_period"], data["usb_periods"] = period, periods
    os.makedirs(audio.DATA, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print("Smallest clean size: %d x %d (about %d ms of delay). Saved; the app uses it from now on."
          % (period, periods, round(period * periods / 44.1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
