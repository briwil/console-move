"""The audio engine: records from a USB audio device onto 8 tape tracks and plays them back.

- Finds the first USB audio device (an OP-XY, a UCA202, ...) and keeps retrying
  if none is plugged in, so you can plug one in while the app runs.
- Input modes:
    "all"  input channel N goes to track N (an OP-XY in 8-channel mode records
           all 8 tracks at once)
    "mix"  every input channel mixed together goes to the armed track (for a
           stereo source like a synth into a UCA202)
- Plays the tape out of the same device, if it has an output (the OP-XY does,
  so you hear the tape on its headphone jack).
- Tracks are mono, 32-bit float in memory. Projects are saved as 24-bit WAVs
  (track1.wav ... track8.wav) in ~/console-data/projects/<song>/; exports
  (stems plus a stereo mix) go to ~/console-data/exports/.

Needs python3-numpy and python3-alsaaudio (installed by setup.sh).
"""
import datetime
import json
import os
import re
import threading
import time
import wave

import numpy as np

TRACKS = 8
RES = 16                 # waveform level values per beat, same as tape.RES
PERIOD = 512             # frames per audio block
PERIODS = 8              # blocks queued in the output buffer (about 90 ms: room for the screen drawing)
MIX_GAIN = 0.6

DATA = os.path.realpath(os.path.expanduser(os.environ.get("CONSOLE_DATA", "~/console-data")))

FORMATS = {              # ALSA name -> (bytes per sample, numpy decode)
    "S16_LE": 2,
    "S24_3LE": 3,
    "S32_LE": 4,
}


# ---------------------------------------------------------------- finding a device

def find_device(prefer=None):
    """The first USB audio device with an input, as a dict, or None."""
    try:
        with open("/proc/asound/cards") as f:
            cards = re.findall(r"^\s*(\d+)\s+\[(\S+)\s*\]:\s*(.*)$", f.read(), re.M)
    except OSError:
        return None
    found = []
    for index, cid, desc in cards:
        info = read_stream_info("/proc/asound/card%s/stream0" % index)
        if not info or not info.get("capture"):
            continue
        info.update(index=int(index), id=cid, name=desc.split(" - ")[-1].strip())
        found.append(info)
    if prefer:
        for d in found:
            if prefer.lower() in (d["id"] + " " + d["name"]).lower():
                return d
    return found[0] if found else None


def read_stream_info(path):
    """Channels, rates and formats for playback and capture, from a USB card's stream0 file."""
    try:
        with open(path) as f:
            text = f.read()
    except OSError:
        return None
    info = {}
    for part, body in re.findall(r"^(Playback|Capture):\n((?:[ \t].*\n?)*)", text, re.M):
        alts = []
        for alt in re.split(r"\n\s*Interface", body):
            ch = re.search(r"Channels:\s*(\d+)", alt)
            fmt = re.search(r"Format:\s*(\S+)", alt)
            rates = re.search(r"Rates:\s*([\d, ]+)", alt)
            if ch and fmt and rates:
                alts.append({"channels": int(ch.group(1)), "format": fmt.group(1),
                             "rates": [int(r) for r in re.findall(r"\d+", rates.group(1))]})
        alts = [a for a in alts if a["format"] in FORMATS]
        if alts:
            info[part.lower()] = max(alts, key=lambda a: a["channels"])
    return info


def pick_rate(rates):
    return 44100 if 44100 in rates else 48000 if 48000 in rates else rates[0]


# ---------------------------------------------------------------- sample formats

def decode(data, fmt, channels):
    """Raw bytes from the device -> float32 array (frames, channels), -1..1."""
    width = FORMATS[fmt]
    if width == 2:
        x = np.frombuffer(data, "<i2").astype(np.float32) / 32768.0
    elif width == 4:
        x = np.frombuffer(data, "<i4").astype(np.float32) / 2147483648.0
    else:
        b = np.frombuffer(data, np.uint8).reshape(-1, 3)
        v = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
        v = np.where(v >= 1 << 23, v - (1 << 24), v)
        x = v.astype(np.float32) / 8388608.0
    return x.reshape(-1, channels)


def encode(x, fmt):
    """float array (frames, channels) -> raw bytes for the device."""
    x = np.clip(x, -1.0, 1.0)
    width = FORMATS[fmt]
    if width == 2:
        return (x * 32767).astype("<i2").tobytes()
    if width == 4:
        return (x * 2147483647).astype("<i4").tobytes()
    v = (x * 8388607).astype("<i4").reshape(-1)
    return v.view(np.uint8).reshape(-1, 4)[:, :3].tobytes()


# ---------------------------------------------------------------- WAV files

def write_wav(path, x, rate):
    """Write a float array (frames,) or (frames, channels) as a 24-bit WAV."""
    x = x.reshape(len(x), -1)
    tmp = path + ".part"
    with wave.open(tmp, "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(3)
        w.setframerate(rate)
        w.writeframes(encode(x, "S24_3LE"))
    os.replace(tmp, path)


def read_wav(path):
    """Read a WAV file -> (float32 mono array, rate). Stereo files are mixed to mono."""
    with wave.open(path, "rb") as w:
        ch, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        data = w.readframes(w.getnframes())
    fmt = {2: "S16_LE", 3: "S24_3LE", 4: "S32_LE"}.get(width)
    if not fmt:
        raise ValueError("unsupported WAV sample size")
    return decode(data, fmt, ch).mean(axis=1), rate


# ---------------------------------------------------------------- the engine

class Engine:
    def __init__(self, song="Song 1", bpm=120.0, tape_beats=256, prefer_device=None):
        self.bpm = bpm
        self.tape_beats = tape_beats
        self.rate = 44100
        self.song = song
        self.prefer = prefer_device
        self.settings = self._load_settings()
        self.lock = threading.Lock()
        self.frames = int(round(tape_beats * 60 / bpm * self.rate))
        self.tracks = [np.zeros(self.frames, np.float32) for _ in range(TRACKS)]
        self.levels = [np.zeros(tape_beats * RES, np.float32) for _ in range(TRACKS)]
        self.dirty = set()
        self.pos = 0                    # playhead, in frames
        self.playing = False
        self.recording = False
        self.armed = 4
        self.input_mode = None          # set when a device is found
        self.in_peaks = np.zeros(TRACKS, np.float32)
        self.device = None              # dict from find_device, while connected
        self.status = "NO AUDIO DEVICE"
        self.latency = int(self.settings.get("latency_frames", PERIOD * (PERIODS + 1)))
        self._stop = False
        self._saving = False
        self.load()

    # ------------------------------------------------------------ settings and project files

    def _load_settings(self):
        try:
            with open(os.path.join(DATA, "settings.json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    @property
    def project_dir(self):
        return os.path.join(DATA, "projects", self.song)

    def load(self):
        """Load the song's tracks from its folder, if it has any."""
        for t in range(TRACKS):
            path = os.path.join(self.project_dir, "track%d.wav" % (t + 1))
            if not os.path.exists(path):
                continue
            try:
                x, rate = read_wav(path)
            except Exception as e:
                print("Couldn't read %s: %s" % (path, e))
                continue
            if rate != self.rate:
                print("%s is %d Hz, the tape runs at %d Hz; it will play at the wrong speed" % (path, rate, self.rate))
            n = min(len(x), self.frames)
            self.tracks[t][:n] = x[:n]
            self._update_levels(t, 0, n, reset=True)

    def save(self, wait=False):
        """Save changed tracks in the background. Returns False if there was nothing to save."""
        with self.lock:
            todo = {t: self.tracks[t].copy() for t in self.dirty}
            self.dirty.clear()
        if not todo:
            return False

        def work():
            self._saving = True
            try:
                os.makedirs(self.project_dir, exist_ok=True)
                for t, x in todo.items():
                    path = os.path.join(self.project_dir, "track%d.wav" % (t + 1))
                    end = self._extent(x)
                    if end == 0:
                        if os.path.exists(path):
                            os.remove(path)
                    else:
                        write_wav(path, x[:end], self.rate)
                with open(os.path.join(self.project_dir, "project.json"), "w") as f:
                    json.dump({"bpm": self.bpm, "rate": self.rate, "beats": self.tape_beats}, f)
            except Exception as e:
                print("Saving failed:", e)
            self._saving = False

        th = threading.Thread(target=work, daemon=True)
        th.start()
        if wait:
            th.join()
        return True

    @staticmethod
    def _extent(x):
        nz = np.flatnonzero(np.abs(x) > 1e-6)
        return int(nz[-1]) + 1 if len(nz) else 0

    def export(self):
        """Write stems (every track with audio, all the same length) and a stereo mix. Returns the folder name."""
        with self.lock:
            tracks = [x.copy() for x in self.tracks]
        ends = [self._extent(x) for x in tracks]
        end = max(ends)
        if end == 0:
            return None
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H%M")
        name = "%s %s" % (self.song, stamp)
        folder = os.path.join(DATA, "exports", name)
        os.makedirs(folder, exist_ok=True)
        mix = np.zeros(end, np.float32)
        for t, x in enumerate(tracks):
            if ends[t]:
                write_wav(os.path.join(folder, "%s track%d.wav" % (self.song, t + 1)), x[:end], self.rate)
                mix += x[:end]
        mix *= MIX_GAIN
        peak = float(np.abs(mix).max())
        if peak > 0.98:
            mix *= 0.98 / peak                   # turn the whole mix down rather than clip it
        write_wav(os.path.join(folder, "%s mix.wav" % self.song), np.stack([mix, mix], axis=1), self.rate)
        return name

    # ------------------------------------------------------------ transport (called from the app)

    def beats(self):
        return self.pos * self.bpm / 60 / self.rate

    def set_beats(self, beats):
        with self.lock:
            self.pos = int(min(max(0, beats), self.tape_beats) * 60 / self.bpm * self.rate)

    def targets(self):
        """Which tracks the input records onto right now, as {track index: input channel or None for mix}."""
        if self.input_mode == "all" and self.device:
            ch = self.device["capture"]["channels"]
            return {t: t for t in range(min(TRACKS, ch))}
        return {self.armed - 1: None}

    def cycle_input(self):
        if not self.device:
            return
        modes = ["all", "mix"] if self.device["capture"]["channels"] >= 3 else ["mix"]
        self.input_mode = modes[(modes.index(self.input_mode) + 1) % len(modes)] if self.input_mode in modes else modes[0]

    # ------------------------------------------------------------ the audio thread

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="audio").start()

    def stop(self):
        self._stop = True

    def _run(self):
        import alsaaudio
        while not self._stop:
            dev = find_device(self.prefer or self.settings.get("device"))
            if not dev:
                self.device, self.status = None, "NO AUDIO DEVICE"
                time.sleep(2)
                continue
            cap_fmt = dev["capture"]["format"]
            rate = pick_rate(dev["capture"]["rates"])
            if rate != self.rate:
                self.status = "%s RUNS AT %d HZ (TAPE IS %d)" % (dev["name"].upper(), rate, self.rate)
            cap = pb = None
            try:
                name = "hw:CARD=%s,DEV=0" % dev["id"]
                cap = alsaaudio.PCM(type=alsaaudio.PCM_CAPTURE, mode=alsaaudio.PCM_NORMAL, device=name,
                                    rate=rate, channels=dev["capture"]["channels"],
                                    format=getattr(alsaaudio, "PCM_FORMAT_" + cap_fmt),
                                    periodsize=PERIOD, periods=PERIODS)
                play = dev.get("playback")
                if play:
                    pb = alsaaudio.PCM(type=alsaaudio.PCM_PLAYBACK, mode=alsaaudio.PCM_NORMAL, device=name,
                                       rate=rate, channels=play["channels"],
                                       format=getattr(alsaaudio, "PCM_FORMAT_" + play["format"]),
                                       periodsize=PERIOD, periods=PERIODS)
                    silence = encode(np.zeros((PERIOD, play["channels"]), np.float32), play["format"])
                    for _ in range(PERIODS):
                        pb.write(silence)
                self.device = dev
                if self.input_mode is None:
                    self.input_mode = "all" if dev["capture"]["channels"] >= 8 else "mix"
                self.status = ""
                print("Audio: %s, %d in / %d out, %d Hz" % (dev["name"], dev["capture"]["channels"],
                                                          play["channels"] if play else 0, rate))
                self._loop(cap, pb, dev)
            except Exception as e:
                print("Audio stopped:", e)
                self.status = "AUDIO DEVICE LOST"
            finally:
                for p in (cap, pb):
                    try:
                        p and p.close()
                    except Exception:
                        pass
                self.device = None
                with self.lock:
                    self.recording = False
            time.sleep(1)

    def _loop(self, cap, pb, dev):
        ch_in = dev["capture"]["channels"]
        play = dev.get("playback")
        while not self._stop:
            n, data = cap.read()
            if n <= 0:
                continue                         # an overrun: skip and carry on
            x = decode(data, dev["capture"]["format"], ch_in)[:n]
            out = self.process(x)
            if pb:
                o = np.zeros((n, play["channels"]), np.float32)
                o[:, :min(2, play["channels"])] = out[:, :min(2, play["channels"])]
                pb.write(encode(o, play["format"]))

    def process(self, x):
        """One block of input (frames, channels) -> one block of stereo output. Also records."""
        n = len(x)
        out = np.zeros((n, 2), np.float32)
        with self.lock:
            self.in_peaks[:] = 0
            peaks = np.abs(x).max(axis=0)
            self.in_peaks[:min(TRACKS, len(peaks))] = peaks[:TRACKS]
            if not self.playing:
                return out
            pos = self.pos
            end = min(pos + n, self.frames)
            m = end - pos
            targets = self.targets() if self.recording else {}
            mix = np.zeros(m, np.float32)
            for t in range(TRACKS):
                if t not in targets:
                    mix += self.tracks[t][pos:end]
            out[:m, 0] = out[:m, 1] = np.tanh(mix * MIX_GAIN)      # tanh: gentle limiting instead of harsh clipping
            if targets:
                w0 = pos - self.latency          # what you heard when you played this is that far back
                for t, ch in targets.items():
                    src = x[:m].mean(axis=1) if ch is None else x[:m, ch]
                    a, b = max(0, w0), w0 + m
                    if b > 0:
                        self.tracks[t][a:b] = src[a - w0:]
                        self._update_levels(t, a, b, reset=True)
                        self.dirty.add(t)
            self.pos = end
            if end >= self.frames:
                self.playing = self.recording = False
        return out

    def _update_levels(self, t, a, b, reset=False):
        fpb = 60 * self.rate / (self.bpm * RES)          # frames per level value
        lv = self.levels[t]
        i0, i1 = int(a // fpb), min(len(lv), int((b - 1) // fpb) + 1)
        if reset:
            lv[i0:i1] = 0
        if b <= a:
            return
        seg = np.abs(self.tracks[t][a:b])
        bins = np.minimum((np.arange(a, b) // fpb).astype(np.int64), len(lv) - 1)
        starts = np.concatenate(([0], np.flatnonzero(np.diff(bins)) + 1))
        idx = bins[starts]
        lv[idx] = np.maximum(lv[idx], np.maximum.reduceat(seg, starts))
