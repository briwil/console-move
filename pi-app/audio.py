"""The audio engine: records from a USB audio device onto 8 tape tracks and plays them back.

- Finds the first USB audio device (an OP-XY, a UCA202, ...) and keeps retrying
  if none is plugged in, so you can plug one in while the app runs.
- Input modes (shown on screen as MULTI, STEREO and MONO):
    "all"  input channel N goes to track N, on every armed track (an OP-XY in
           8-channel mode can record all 8 tracks at once)
    "stereo" input 1 (left) and 2 (right) go to pairs of neighbouring armed
           tracks (e.g. 7 and 8), which become a stereo pair: panned left
           and right, and exported as one stereo file. An armed track
           without a neighbour gets the mix.
    "mix"  every input channel mixed together goes to the armed track(s)
- One track is selected (self.armed: editing works on it, and it always
  records); more can be armed with it (self.arm_extra).
- Plays the tape out of the same device, if it has an output (the OP-XY does,
  so you hear the tape on its headphone jack), or wherever SETTINGS > OUTPUT
  says: the screen's headphone jack (sound over HDMI) or another USB device.
  Those run on their own clock, so OutPort resamples to keep them in step.
  With no input device plugged in, the tape still plays on the headphones.
- Tracks are mono, 32-bit float in memory. Projects are saved as 24-bit WAVs
  (track1.wav ... track8.wav) in ~/console-data/projects/<song>/; exports
  (stems plus a stereo mix) go to ~/console-data/exports/.

Needs python3-numpy and python3-alsaaudio (installed by setup.sh).
"""
import bisect
import datetime
import json
import os
import random
import re
import shutil
import subprocess
import threading
import time
import traceback
import wave

import numpy as np

from palette import REGION_COLOURS

try:
    import effects
except Exception as _e:                     # numpy or ctypes trouble: carry on without effects
    print("Effects off:", _e)
    effects = None

try:
    import drums
except Exception as _e:                     # carry on without the drum synth
    print("Drum synth off:", _e)
    drums = None

import drumparams
import sequencer

TRACKS = 8
RES = 16                 # waveform level values per beat, same as tape.RES
PERIOD = 512             # frames per audio block (headphones, and playing with no input device)
PERIODS = 8              # blocks queued in the output buffer (about 90 ms: room for the screen drawing)
# The USB input device uses bigger blocks: with 512-frame blocks the Pi's USB audio driver garbles the
# OP-XY's recording stream (repeated 1 ms packets). usb-buffer-test.py finds the smallest clean size and
# saves it as usb_period / usb_periods in settings.json.
USB_PERIOD = 2048
USB_PERIODS = 4
MIX_GAIN = 0.6
UNDO_STEPS = 8
DRUMS_ID = "DRUMS"       # the drum synth's "card id" as an input
DRUMS_MONITOR = 0.8      # how loud you hear the drum synth as you play it (a track's volume at its default)


def drum_device():
    """The drum synth, as an input device (six channels: one per voice), or None if it isn't available."""
    if not (drums and drums.AVAILABLE):
        return None
    return {"id": DRUMS_ID, "name": "Drum Synth", "virtual": True,
            "capture": {"channels": drums.VOICES, "format": "FLOAT", "rates": [44100]}}


DATA = os.path.realpath(os.path.expanduser(os.environ.get("CONSOLE_DATA", "~/console-data")))

FORMATS = {              # ALSA name -> (bytes per sample, numpy decode)
    "S16_LE": 2,
    "S24_3LE": 3,
    "S32_LE": 4,
}


# ---------------------------------------------------------------- finding a device

def usb_inputs():
    """Every USB audio device with an input, as dicts (id, name, capture, playback...)."""
    try:
        with open("/proc/asound/cards") as f:
            cards = re.findall(r"^\s*(\d+)\s+\[(\S+)\s*\]:\s*(.*)$", f.read(), re.M)
    except OSError:
        return []
    found = []
    for index, cid, desc in cards:
        info = read_stream_info("/proc/asound/card%s/stream0" % index)
        if not info or not info.get("capture"):
            continue
        info.update(index=int(index), id=cid, name=desc.split(" - ")[-1].strip())
        found.append(info)
    return found


def find_device(prefer=None):
    """The USB audio device to record from: the one asked for (by card id, or part of its name) if it's
    plugged in, otherwise the first one with an input. None if there's none."""
    found = usb_inputs()
    if prefer:
        for d in found:
            if prefer.lower() == d["id"].lower():
                return d
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


def usb_outputs():
    """Every USB audio device with an output: [{"id", "name", "playback"}]."""
    try:
        with open("/proc/asound/cards") as f:
            cards = re.findall(r"^\s*(\d+)\s+\[(\S+)\s*\]:\s*(.*)$", f.read(), re.M)
    except OSError:
        return []
    found = []
    for index, cid, desc in cards:
        info = read_stream_info("/proc/asound/card%s/stream0" % index)
        if info and info.get("playback"):
            found.append({"id": cid, "name": desc.split(" - ")[-1].strip(), "playback": info["playback"]})
    return found


def hdmi_card():
    """The ALSA card for the HDMI port the screen is on. The screen plays its sound on its headphone jack."""
    try:
        with open("/proc/asound/cards") as f:
            ids = re.findall(r"^\s*\d+\s+\[(vc4hdmi\d)\s*\]", f.read(), re.M)
    except OSError:
        return None
    if not ids:
        return None
    import glob
    for path in sorted(glob.glob("/sys/class/drm/card*-HDMI-A-*/status")):
        try:
            with open(path) as f:
                if f.read().strip() != "connected":
                    continue
            n = int(re.search(r"HDMI-A-(\d+)", path).group(1)) - 1     # HDMI-A-1 is vc4hdmi0
        except (OSError, ValueError, AttributeError):
            continue
        if "vc4hdmi%d" % n in ids:
            return "vc4hdmi%d" % n
    return ids[0]


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


def log(text, details=None):
    """Print a message, and keep it in ~/console-data/console.log so it can be looked at later."""
    print(text)
    if details:
        print(details)
    try:
        os.makedirs(DATA, exist_ok=True)
        path = os.path.join(DATA, "console.log")
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            os.replace(path, path + ".old")
        with open(path, "a") as f:
            f.write("%s  %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text))
            if details:
                f.write(details + "\n")
    except OSError:
        pass


def pan_gains(pan):
    """(left, right) gain for a pan from -1 (left) to 1 (right). Centre is full in both, as before pan existed."""
    return min(1.0, 1.0 - pan), min(1.0, 1.0 + pan)


def saturate(x):
    """Gentle tape-style limit above 0.8, so overdubs that pile up never pass 1.0."""
    y = np.abs(x)
    over = y > 0.8
    if over.any():
        x = x.copy()
        x[over] = np.sign(x[over]) * (0.8 + 0.2 * np.tanh((y[over] - 0.8) / 0.2))
    return x


# ---------------------------------------------------------------- audio files

EXPORT_FORMATS = ["wav", "aiff", "flac", "m4a"]
FFMPEG_CODEC = {
    "aiff": ["-c:a", "pcm_s24be"],
    "flac": ["-c:a", "flac", "-sample_fmt", "s32", "-bits_per_raw_sample", "24"],
    "m4a": ["-c:a", "aac", "-b:a", "256k"],
}


# ---- each box's own gain and fades: kept with the box, never written into the audio, so they can
# always be changed back. A box is [start, end, colour, gain dB, fade in, fade out] (frames).

GUARD = 48              # frames (1 ms): a tiny fade at box edges with nothing next to them, so they never click
FADE_STEPS = [0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.75, 1.0, 1.5, 2.0,
              3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 15.0, 20.0, 30.0]          # seconds, for the fade knobs
GAIN_MIN, GAIN_MAX = -40.0, 24.0
NORMALIZE_DB = -1.0     # NORMALIZE puts a box's loudest peak here


def box(a, b, colour, gain=0.0, fade_in=0, fade_out=0):
    return [int(a), int(b), int(colour), float(gain), int(fade_in), int(fade_out)]


def box_settings(r):
    """(gain dB, fade in, fade out) of a box (older 3-number boxes have none)."""
    return (r[3], r[4], r[5]) if len(r) >= 6 else (0.0, 0, 0)


def box_shape(rs, i, guard=True):
    """(gain, fade in frames, fade out frames) for box i of a track's boxes rs. guard: add the click
    guard at an edge with no box right next to it."""
    r = rs[i]
    db, fi, fo = box_settings(r)
    if guard:
        if not (i > 0 and rs[i - 1][1] >= r[0]):
            fi = max(fi, GUARD)
        if not (i + 1 < len(rs) and rs[i + 1][0] <= r[1]):
            fo = max(fo, GUARD)
    n = r[1] - r[0]
    if fi + fo > n > 0:
        s = n / (fi + fo)
        fi, fo = int(fi * s), int(fo * s)
    return 10 ** (db / 20), fi, fo


def fade_curve(u):
    """0 -> 1, an S-curve (it starts and ends gently)."""
    return (0.5 - 0.5 * np.cos(np.pi * np.clip(u, 0.0, 1.0))).astype(np.float32)


def shape_range(rs, x, a, guard=True, inplace=False):
    """x is the audio of frames a.. on a track whose boxes are rs: returns it with the boxes' gains and
    fades (x itself if nothing changes it)."""
    b = a + len(x)
    y = x if inplace else None
    for i, r in enumerate(rs):
        if r[0] >= b:
            break
        if r[1] <= a:
            continue
        g, fi, fo = box_shape(rs, i, guard)
        if g == 1.0 and not fi and not fo:
            continue
        if y is None:
            y = x.copy()
        lo, hi = max(r[0], a), min(r[1], b)
        if g != 1.0:
            y[lo - a:hi - a] *= g
        if fi:
            z1 = min(hi, r[0] + fi)
            if z1 > lo:
                y[lo - a:z1 - a] *= fade_curve((np.arange(lo, z1) - r[0]) / fi)
        if fo:
            z0 = max(lo, r[1] - fo)
            if hi > z0:
                y[z0 - a:hi - a] *= fade_curve((r[1] - np.arange(z0, hi)) / fo)
    return x if y is None else y


def envelope(rs, idx):
    """The boxes' gains and fades for the frames idx (any order, as the loop wraps), or None for all 1."""
    if not rs or not len(idx):
        return None
    lo, hi = int(idx.min()), int(idx.max()) + 1
    env = None
    for i, r in enumerate(rs):
        if r[0] >= hi:
            break
        if r[1] <= lo:
            continue
        g, fi, fo = box_shape(rs, i)
        if g == 1.0 and (not fi or r[0] + fi <= lo) and (not fo or r[1] - fo >= hi):
            continue
        if env is None:
            env = np.ones(len(idx), np.float32)
        m = (idx >= r[0]) & (idx < r[1])
        f = idx[m]
        e = np.full(len(f), g, np.float32)
        if fi:
            e *= fade_curve((f - r[0]) / fi)
        if fo:
            e *= fade_curve((r[1] - f) / fo)
        env[m] = e
    return env


def write_audio(path, x, rate, fmt="wav"):
    """Write audio (mono, or (frames, 2) stereo) to path + "." + fmt. WAV directly; the others through ffmpeg."""
    wav = path + ".wav"
    write_wav(wav, x, rate)
    if fmt == "wav":
        return wav
    target = path + "." + fmt
    try:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", wav] + FFMPEG_CODEC[fmt] + [target],
                       check=True, capture_output=True, timeout=600)
        os.remove(wav)
        return target
    except Exception as e:
        log("Export: couldn't make %s (%s), kept the WAV" % (os.path.basename(target), e))
        return wav

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


# ---------------------------------------------------------------- a second output

class OutPort(threading.Thread):
    """Plays the tape on a device other than the one recording: the screen's headphone jack, or another
    USB device. That device runs on its own clock, which never quite matches, so the engine pushes blocks
    in at the tape's rate and this resamples them to the device's rate, nudging the speed by up to 0.2%
    (too little to hear) to keep about TARGET frames waiting."""

    TARGET = PERIOD * 3

    def __init__(self, key, device, channels, fmt, rate, in_rate, label):
        super().__init__(daemon=True, name="output")
        import alsaaudio
        self.key, self.label = key, label
        self.channels, self.fmt, self.in_rate = channels, fmt, in_rate
        self.pcm = alsaaudio.PCM(type=alsaaudio.PCM_PLAYBACK, mode=alsaaudio.PCM_NORMAL, device=device,
                                 rate=rate, channels=channels, format=getattr(alsaaudio, "PCM_FORMAT_" + fmt),
                                 periodsize=PERIOD, periods=PERIODS)
        try:
            rate = int(self.pcm.info().get("rate") or rate)     # the rate the device actually took
        except Exception:
            pass
        self.rate = rate
        self.gain = 1.0
        self.lock = threading.Lock()
        self.buf = np.zeros((0, 2), np.float32)
        self.frac = 0.0                           # where the next output frame falls between two input frames
        self.primed = False
        self.dead = None                          # what went wrong, once the device has gone
        self.stopped = False

    def delay(self):
        """About how long, in tape frames, between pushing a block and hearing it."""
        return int(self.TARGET + PERIOD * PERIODS * self.in_rate / self.rate)

    def fill(self):
        return len(self.buf)

    def push(self, block):
        with self.lock:
            self.buf = np.concatenate([self.buf, block[:, :2]])
            if len(self.buf) > self.TARGET * 8:          # the device stalled: drop the backlog
                self.buf = self.buf[-self.TARGET:]

    def _take(self, n):
        with self.lock:
            have = len(self.buf)
            if not self.primed:
                if have < self.TARGET:
                    return None
                self.primed = True
                if have > self.TARGET:                    # start from exactly TARGET, so delay() is right
                    self.buf = self.buf[have - self.TARGET:]
                    have = self.TARGET
            nudge = max(-1.0, min(1.0, (have - self.TARGET) / self.TARGET))
            step = self.in_rate / self.rate * (1.0 + 0.002 * nudge)
            end = self.frac + step * n
            if have < int(end) + 2:
                self.primed = False                       # ran dry: wait until there's enough again
                return None
            pos = self.frac + step * np.arange(n)
            i = pos.astype(np.int64)
            f = (pos - i)[:, None].astype(np.float32)
            out = self.buf[i] * (1.0 - f) + self.buf[i + 1] * f
            used = int(end)
            self.frac = end - used
            self.buf = self.buf[used:]
        return out

    def run(self):
        n = PERIOD
        silence = encode(np.zeros((n, self.channels), np.float32), self.fmt)
        try:
            for _ in range(PERIODS):
                self.pcm.write(silence)
            while not self.stopped:
                block = self._take(n)
                if block is None:
                    self.pcm.write(silence)
                    continue
                o = np.zeros((n, self.channels), np.float32)
                g = self.gain
                sig = block.mean(axis=1, keepdims=True) if self.channels == 1 else block
                sig = sig * g
                if g > 1.0:
                    sig = np.tanh(sig)                    # turned up past the mix level: round off the peaks
                o[:, :sig.shape[1]] = sig
                self.pcm.write(encode(o, self.fmt))
        except Exception as e:
            self.dead = str(e) or e.__class__.__name__
            log("Output %s stopped: %s" % (self.label, self.dead))
        finally:
            try:
                if hasattr(self.pcm, "drop"):
                    self.pcm.drop()                       # stop now, without playing out what's queued
                self.pcm.close()
            except Exception:
                pass

    def close(self):
        self.stopped = True


# ---------------------------------------------------------------- the engine

class Engine:
    """Everything that touches the audio. The app calls its methods; the audio thread runs process()."""

    def __init__(self, song=None, bpm=120.0, prefer_device=None):
        self.settings = self._load_settings()
        self.rate = 44100
        # opens the last project used; None is a new song that hasn't been saved with a name yet
        self.song = song if song is not None else self.settings.get("last_song", "Song 1")
        self.prefer = prefer_device
        self.lock = threading.Lock()
        self.save_lock = threading.Lock()       # one save (or rename) on disk at a time
        self.frames = int(float(self.settings.get("tape_seconds", 300)) * self.rate)
        self.tracks = [np.zeros(self.frames, np.float32) for _ in range(TRACKS)]
        self.levels = [None] * TRACKS
        self.bpm = bpm
        self.time_sig = [4, 4]                  # beats in a bar, and which note is a beat (4/4, 6/8...)
        self.link_nudge = 0                     # Link: frames to move the tape by each block to stay on its beat
        self.tape_beats = 0.0
        self.volumes = [0.8] * TRACKS
        self.pans = [0.0] * TRACKS              # -1 left ... 0 centre ... 1 right
        self.pairs = set()                      # t: tracks t and t+1 are a stereo pair (left, right)
        self.mutes = set()
        self.solos = set()                      # if any track is soloed, only soloed tracks play
        self.rev_sends = [0.0] * TRACKS         # how much of each track goes to the reverb, 0..1
        self.dly_sends = [0.0] * TRACKS         # ... and to the delay
        self.fx = dict(effects.DEFAULTS) if effects else {}
        self._rev = self._dly = None            # the effects, made by the audio thread
        self.drums = drums.Drums() if (drums and drums.AVAILABLE) else None
        self.seq = sequencer.Sequencer()        # the drum sequencer's patterns (saved with the song)
        self.seq_hits = [0.0] * sequencer.LANES  # when each lane's last sequencer hit is heard (for the screen)
        self.loop_on = False
        self.loop_a = self.loop_b = 0           # loop start and end, in frames
        self.dirty = set()
        self.pos = 0                            # playhead, in frames: what you hear right now
        self.playing = False
        self.recording = False
        self.rec_ready = False                  # waiting for a MIDI start to begin recording
        self.rec_mode = "replace"               # "replace" writes over the tape, "overdub" adds to it
        self.armed = 4                          # the selected track, 1-8
        self.arm_extra = set()                  # other armed tracks (0-7), recording along with it
        self.input_mode = None                  # set when a device is found
        self.in_peaks = np.zeros(TRACKS, np.float32)
        self.device = None                      # dict from find_device, while connected
        self.status = "NO AUDIO DEVICE"
        self.read_ahead = PERIOD * PERIODS      # output delay: play the tape this far ahead
        # round trip, out and back in: lines up what you record with what you heard. latency_frames in
        # settings.json is a measured value for the input device's own output; the extra carries over
        self.latency_extra = int(self.settings.get("latency_frames", PERIOD * (PERIODS + 1))) - PERIOD * (PERIODS + 1)
        self.in_period = PERIOD                 # frames per block from the input device
        self.dev_buffer = PERIOD * PERIODS      # the input device's output buffer, in frames
        self.latency = self.read_ahead + self.in_period + self.latency_extra
        self.port = None                        # OutPort while the tape plays somewhere other than the input device
        self.route = None                       # "device" (the input device's own output), "phones", "usb:<id>"
        self.output_label = ""                  # where the tape is playing, for the settings page
        self._route_due = 0.0                   # when to look at the outputs again
        self.clip = None                        # the clipboard, for DROP: [audio] or [left, right] for a stereo pair
        self.last_edit = None                   # (start, end) in frames of the last lift, cut or drop
        # the boxes on each track: [start, end, colour] in frames, sorted, never overlapping.
        # Recording makes a box; SPLICE splits one; CUT takes boxes away and leaves an empty space.
        self.regions = [[] for _ in range(TRACKS)]
        self.sel_anchor = None                  # while selecting several pieces: where the selection started
        self.undo_stack = []                    # each entry: list of (track, start, old samples)
        self._rec_undo = None                   # the undo entry the current recording pass adds to
        self._rec_saved = {}                    # track -> [start, end) already saved for undo this pass
        self._rec_boxes = {}                    # track -> the box this recording pass is making
        self._stop = False
        self._resume_recording = False
        self._set_beats_len()
        self.load()
        try:
            gone = self.clean_empty_songs()          # empty songs left from before (NEW used to keep them)
            if gone:
                print("Removed %d empty song%s" % (gone, "" if gone == 1 else "s"))
        except Exception as e:
            print("Couldn't tidy up empty songs:", e)

    # ------------------------------------------------------------ settings and project files

    def _load_settings(self):
        try:
            with open(os.path.join(DATA, "settings.json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def remember(self, key, value):
        """Store a setting in settings.json, keeping whatever else is in there."""
        path = os.path.join(DATA, "settings.json")
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        data[key] = value
        self.settings[key] = value
        try:
            os.makedirs(DATA, exist_ok=True)
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            print("Couldn't save settings:", e)

    @property
    def export_format(self):
        f = self.settings.get("export_format", "wav")
        return f if f in EXPORT_FORMATS else "wav"

    @property
    def sync_mode(self):
        """"external": follow the OP-XY's MIDI clock. "internal": Console leads and sends clock to it.
        "link": Ableton Link over the network (linksync.py)."""
        mode = self.settings.get("sync")
        return mode if mode in ("internal", "link") else "external"

    def set_sync_mode(self, mode):
        self.remember("sync", mode)

    # ------------------------------------------------------------ where the tape plays

    PHONES_LABEL = "HEADPHONES"
    PHONES_BOOST = 4.0                      # 100% on the headphones is 4x (+12 dB); a soft limiter keeps it clean

    @property
    def output_choice(self):
        """None (the input device, or the headphones if it has no output), "phones" or "usb:<card id>"."""
        return self.settings.get("output")

    @property
    def input_choice(self):
        """The card id of the device to record from, or None for the first one found."""
        return self.prefer or self.settings.get("device")

    def _inputs(self):
        """usb_inputs(), looked at no more than once a second (the settings page asks every frame)."""
        now = time.monotonic()
        cached = getattr(self, "_inputs_cache", None)
        if not cached or now - cached[0] > 1.0:
            cached = self._inputs_cache = (now, usb_inputs())
        return cached[1]

    def input_plugged(self, cid):
        if cid == DRUMS_ID:
            return bool(self.drums)
        return any(d["id"] == cid for d in self._inputs())

    def input_choices(self):
        """[(card id, label)] for the SETTINGS page: every USB device with an input, then the drum synth."""
        choices = [(d["id"], d["name"].upper()) for d in self._inputs()]
        if self.drums:
            choices.append((DRUMS_ID, "DRUM SYNTH"))
        key = self.input_choice
        if key and key not in [k for k, _ in choices]:
            choices.append((key, self.settings.get("device_name", key).upper()))
        return choices

    def find_input(self):
        """The input to use now: the chosen one if it's there, else the first USB device, else None."""
        if self.input_choice == DRUMS_ID and self.drums:
            return drum_device()
        return find_device(None if self.input_choice == DRUMS_ID else self.input_choice)

    @property
    def drums_input(self):
        """True while the drum synth is the input."""
        return bool(self.device and self.device.get("virtual"))

    def hit(self, lane, velocity=100):
        """Play a drum synth voice (lane 0-5; 6 is the hi-hat open). Heard only while it's the input."""
        if self.drums:
            self.drums.hit(lane, velocity)

    def _set_latency(self):
        # an outside device: what you played reached us in_period (plus the measured extra) after you heard
        # the tape. The drum synth plays the moment you press, in step with what you're hearing.
        if self.drums_input:
            self.latency = self.read_ahead
        else:
            self.latency = self.read_ahead + self.in_period + self.latency_extra

    def set_input(self, cid, label=None):
        self.prefer = None
        self.remember("device", cid)
        if label:
            self.remember("device_name", label)
        self._input_due = 0.0                   # the audio thread switches over straight away

    def output_choices(self):
        """[(key, label)] for the SETTINGS page: the headphone jack on the screen, then each USB output."""
        now = time.monotonic()
        cached = getattr(self, "_choices", None)
        if cached and now - cached[0] < 1.0 and cached[1] == self.output_choice:
            return cached[2]
        choices = [("phones", self.PHONES_LABEL)]
        for o in usb_outputs():
            choices.append(("usb:" + o["id"], o["name"].upper()))
        key = self.output_choice
        if key and key not in [k for k, _ in choices]:
            choices.append((key, self.settings.get("output_name", key[4:]).upper()))
        self._choices = (now, key, choices)
        return choices

    def set_output(self, key, label=None):
        self.remember("output", key)
        if label and key.startswith("usb:"):
            self.remember("output_name", label)
        self._route_due = 0.0                   # the audio thread switches over on its next block

    @property
    def phones_volume(self):
        return max(0.0, min(1.0, float(self.settings.get("phones_volume", 0.7))))

    def change_phones_volume(self, delta):
        v = round(max(0.0, min(1.0, self.phones_volume + delta)), 2)
        self.settings["phones_volume"] = v
        self._phones_dirty = time.monotonic()
        port = self.port
        if port:                                # the headphone jack, or a USB output that isn't the input device
            port.gain = v * v * self.PHONES_BOOST   # squared, so the knob feels even from quiet to loud
        return v

    def save_phones_volume(self):
        """Write the headphone level to settings.json (the knob calls this once it stops turning)."""
        if getattr(self, "_phones_dirty", None):
            self._phones_dirty = None
            self.remember("phones_volume", self.phones_volume)

    def _want_route(self, dev):
        """Where the tape should play: (route, details), or (None, None) if there's nowhere."""
        key = self.output_choice
        dev_out = bool(dev and dev.get("playback"))
        if key == "phones":
            card = hdmi_card()
            if card:
                return "phones", card
        elif key and key.startswith("usb:"):
            cid = key[4:]
            if dev and dev["id"] == cid and dev_out:
                return "device", None
            for o in usb_outputs():
                if o["id"] == cid:
                    return key, o
        # the default, or the chosen one isn't there: the input device's output, else the headphones
        if dev_out:
            return "device", None
        card = hdmi_card()
        return ("phones", card) if card else (None, None)

    def _update_route(self, dev):
        """Called by the audio thread: switches outputs when the setting changes or devices come and go."""
        now = time.monotonic()
        port = self.port
        if port and port.dead:
            self._close_port()
            self._route_due = 0.0
        if now < self._route_due:
            return self.route
        self._route_due = now + 2.0
        route, info = self._want_route(dev)
        if route == self.route and (route in ("device", None) or self.port):
            if route == "device":                       # block sizes may have changed with a new device
                self.read_ahead = self.dev_buffer
                self.output_label = dev["name"].upper()
            elif self.port:
                self.port.TARGET = max(PERIOD * 3, 2 * self.in_period)
                self.read_ahead = self.port.delay()
            self._set_latency()
            return route
        self._close_port()
        self.route, self.output_label = None, ""
        try:
            if route == "phones":
                self.port = OutPort("phones", "hdmi:CARD=%s,DEV=0" % info, 2, "S16_LE", self.rate, self.rate,
                                    self.PHONES_LABEL)
                self.port.gain = self.phones_volume ** 2 * self.PHONES_BOOST
            elif route and route.startswith("usb:"):
                pb = info["playback"]
                self.port = OutPort(route, "hw:CARD=%s,DEV=0" % info["id"], pb["channels"], pb["format"],
                                    pick_rate(pb["rates"]), self.rate, info["name"].upper())
                self.port.gain = self.phones_volume ** 2 * self.PHONES_BOOST
        except Exception as e:
            text = "Couldn't open %s: %s" % ("the headphones" if route == "phones" else route, e)
            if text != getattr(self, "_open_error", None):     # say it once, not every 2 seconds
                log(text)
                self._open_error = text
            self.port = None
            if dev and dev.get("playback"):
                route = "device"                # play on the input device instead, and try again later
            else:
                return None
        if self.port:
            self._open_error = None
            self.port.TARGET = max(PERIOD * 3, 2 * self.in_period)    # enough to ride over the input's bigger blocks
            self.port.start()
            self.output_label = self.port.label
            self.read_ahead = self.port.delay()
            log("Output: %s (%d Hz)" % (self.port.label, self.port.rate))
        elif route == "device":
            self.output_label = dev["name"].upper()
            self.read_ahead = self.dev_buffer
        self._set_latency()
        self.route = route
        return route

    def _close_port(self):
        if self.port:
            self.port.close()
            if self.port.is_alive():
                self.port.join(1.0)             # let it actually let go of the device before anything reopens it
            self.port = None

    def song_exists(self, name):
        return os.path.exists(os.path.join(DATA, "projects", name))

    def next_song_name(self):
        n = 1
        while self.song_exists("Song %d" % n):
            n += 1
        return "Song %d" % n

    @property
    def song_label(self):
        return self.song or "Untitled"

    def has_audio(self):
        return any(self.track_end(t) for t in range(TRACKS))

    def new_song(self, name=None):
        """Save the current project, then start an empty one called name (same tempo), with its folder
        in projects/ made straight away. (name=None: an unnamed song kept in ~/console-data/unsaved until
        it's saved with a name.) The clipboard stays, so a piece can be carried over to the new song."""
        was_untitled = self.song is None
        self.save(wait=True)
        self._drop_if_empty()
        self._reset()
        with self.lock:
            self.song = name
            self.dirty = {-1}
        if name is None or was_untitled:              # an unnamed song is thrown away (the menu warned first)
            shutil.rmtree(os.path.join(DATA, "unsaved"), ignore_errors=True)
        self.save(wait=True)
        self.remember("last_song", name)

    def _reset(self):
        """Everything back to an empty song (the tempo and time signature stay)."""
        with self.lock:
            self.playing = self.recording = self.rec_ready = False
            for x in self.tracks:
                x[:] = 0
            self._set_beats_len()                       # fresh, empty waveforms
            self.regions = [[] for _ in range(TRACKS)]
            self.undo_stack = []
            self.volumes = [0.8] * TRACKS
            self.pans = [0.0] * TRACKS
            self.pairs = set()
            self.mutes = set()
            self.solos = set()
            self.rev_sends = [0.0] * TRACKS
            self.dly_sends = [0.0] * TRACKS
            self.fx = dict(effects.DEFAULTS) if effects else {}
            if self.drums:
                self.drums.init_kit()                   # a new song starts with the Init Kit
            self.seq.from_json(None)                    # ... and empty patterns
            self.loop_on, self.loop_a, self.loop_b = False, 0, 0
            self.arm_extra = set()
            self.sel_anchor = None
            self.pos = 0

    # ---- empty songs, and opening and deleting songs (the LOAD menu)

    def is_empty(self):
        """Nothing in this song: no audio, no sequencer steps, and the drum kit as a new song has it."""
        if self.has_audio() or not all(p.empty() for p in self.seq.patterns):
            return False
        return not self.drums or self.drums.kit() == self.drums.init_values

    def _drop_if_empty(self):
        """Leaving a named song with nothing in it: remove its folder, so empty songs don't pile up."""
        if self.song is not None and self.is_empty():
            shutil.rmtree(os.path.join(DATA, "projects", self.song), ignore_errors=True)

    def song_is_empty_on_disk(self, name):
        folder = os.path.join(DATA, "projects", name)
        for t in range(TRACKS):
            path = os.path.join(folder, "track%d.wav" % (t + 1))
            if os.path.exists(path):
                try:
                    x, _ = read_wav(path)
                except Exception:
                    return False                    # can't tell: keep it
                if len(x) and np.abs(x).max() > 1e-6:
                    return False
        try:
            with open(os.path.join(folder, "project.json")) as f:
                meta = json.load(f)
        except OSError:
            meta = {}
        except ValueError:
            return False
        seq = sequencer.Sequencer()
        seq.from_json(meta.get("drum_seq"))
        if not all(p.empty() for p in seq.patterns):
            return False
        kit = meta.get("drum_kit")
        if kit and self.drums:
            probe = drums.Drums.__new__(drums.Drums)       # compare without touching the running engine
            probe.param_count, probe.init_values = self.drums.param_count, self.drums.init_values
            probe.engine_params = self.drums.engine_params
            values = [int(v) for v in kit[:probe.param_count]]
            if len(values) == drumparams.NOISE_DECAY:
                values.append(values[56])
            values += probe.init_values[len(values):]
            if values != probe.init_values:
                return False
        return True

    def clean_empty_songs(self):
        """Remove every song folder with nothing in it (except the one open now). Returns how many."""
        removed = 0
        for name in self.song_names():
            if name != self.song and self.song_is_empty_on_disk(name):
                shutil.rmtree(os.path.join(DATA, "projects", name), ignore_errors=True)
                removed += 1
        return removed

    def song_names(self):
        """The songs in projects/, newest first: [name]."""
        folder = os.path.join(DATA, "projects")
        try:
            names = [n for n in os.listdir(folder) if os.path.isdir(os.path.join(folder, n)) and not n.startswith(".")]
        except OSError:
            return []
        return sorted(names, key=lambda n: os.path.getmtime(os.path.join(folder, n)), reverse=True)

    def song_time(self, name):
        try:
            return os.path.getmtime(os.path.join(DATA, "projects", name))
        except OSError:
            return 0

    def open_song(self, name):
        """Save (or drop, if empty) the current song and open another one from projects/."""
        if self.song is not None:
            self.save(wait=True)
            self._drop_if_empty()
        else:
            shutil.rmtree(os.path.join(DATA, "unsaved"), ignore_errors=True)   # the menu warned first
        self._reset()
        with self.lock:
            self.song = name
            self.undo_stack = []
        self.load()
        with self.lock:
            self.dirty = set()
        self.remember("last_song", name)

    def rename_song(self, old, new):
        """Rename a song's folder (the open one too: it's saved first)."""
        src = os.path.join(DATA, "projects", old)
        dst = os.path.join(DATA, "projects", new)
        if old == self.song:
            self.save(wait=True)
            with self.save_lock, self.lock:
                os.rename(src, dst)
                self.song = new
            self.remember("last_song", new)
        else:
            os.rename(src, dst)

    def delete_song(self, name):
        if name == self.song:
            return False
        shutil.rmtree(os.path.join(DATA, "projects", name), ignore_errors=True)
        return True

    def save_as(self, name):
        """Give the unnamed song a name: it moves from unsaved/ into projects/<name>/."""
        with self.lock:
            self.dirty.add(-1)
        self.save(wait=True)
        src = self.project_dir
        dst = os.path.join(DATA, "projects", name)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with self.save_lock, self.lock:
            shutil.move(src, dst)
            self.song = name
        self.remember("last_song", name)

    @property
    def project_dir(self):
        if self.song is None:
            return os.path.join(DATA, "unsaved")
        return os.path.join(DATA, "projects", self.song)

    def frames_per_beat(self):
        return 60 * self.rate / self.bpm

    def _set_beats_len(self):
        self.tape_beats = self.frames / self.frames_per_beat()
        n = int(np.ceil(self.tape_beats * RES)) + 1
        for t in range(TRACKS):
            self.levels[t] = np.zeros(n, np.float32)

    def bar_beats(self):
        """Quarter-note beats in a bar."""
        return self.time_sig[0] * 4.0 / self.time_sig[1]

    def set_time_sig(self, num, den):
        with self.lock:
            self.time_sig = [int(num), int(den)]
            self.dirty.add(-1)
        self.seq.set_bar_beats(self.bar_beats())

    def set_bpm(self, bpm):
        """Change the tempo (only while stopped). The audio stays put; the bar lines move."""
        with self.lock:
            if self.playing or abs(bpm - self.bpm) < 0.05:
                return False
            self.bpm = float(bpm)
            self._set_beats_len()
            for t in range(TRACKS):
                self._update_levels(t, 0, self._extent(self.tracks[t]))
            self.dirty.add(-1)                  # -1: only project.json changed
        return True

    def load(self):
        """Load the song's tracks and settings from its folder, if it has them."""
        try:
            with open(os.path.join(self.project_dir, "project.json")) as f:
                meta = json.load(f)
        except (OSError, ValueError):
            meta = {}
        if meta.get("bpm"):
            self.bpm = float(meta["bpm"])
            self._set_beats_len()
        sig = meta.get("time_sig")
        self.time_sig = [int(sig[0]), int(sig[1])] if isinstance(sig, list) and len(sig) == 2 else [4, 4]
        self.volumes = [float(v) for v in meta.get("volumes", self.volumes)][:TRACKS]
        self.mutes = set(meta.get("mutes", []))
        self.solos = set(meta.get("solos", []))
        self.pans = ([float(v) for v in meta.get("pans", [])] + [0.0] * TRACKS)[:TRACKS]
        self.pairs = {int(t) for t in meta.get("pairs", []) if 0 <= int(t) < TRACKS - 1}
        self.rev_sends = ([float(v) for v in meta.get("reverb_sends", [])] + [0.0] * TRACKS)[:TRACKS]
        self.dly_sends = ([float(v) for v in meta.get("delay_sends", [])] + [0.0] * TRACKS)[:TRACKS]
        if effects:
            self.fx = dict(effects.DEFAULTS)
            self.fx.update({k: v for k, v in (meta.get("fx") or {}).items() if k in effects.DEFAULTS})
        self.seq.bar_beats = self.bar_beats()          # missing patterns start at a bar of the song's time
        self.seq.from_json(meta.get("drum_seq"))
        if self.drums:
            if meta.get("drum_kit"):
                self.drums.load_kit(meta["drum_kit"])
            else:
                self.drums.init_kit()
        if meta.get("rec_mode") in ("replace", "overdub"):
            self.rec_mode = meta["rec_mode"]
        self._meta_regions = meta.get("regions")
        self._meta_splices = meta.get("splices")       # from version 0.6-0.7, turned into boxes below
        if meta.get("loop"):
            self.loop_on, self.loop_a, self.loop_b = bool(meta["loop"][0]), int(meta["loop"][1]), int(meta["loop"][2])
        self.regions = [[] for _ in range(TRACKS)]       # (the boxes come after the audio, below)
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
        self._regions_from_meta()
        for t in range(TRACKS):
            for r in self.regions[t]:
                if box_settings(r) != (0.0, 0, 0):
                    self._update_levels(t, r[0], r[1], reset=True)     # the waveform shows its gain and fades

    def save(self, wait=False):
        """Save changed tracks in the background. Returns False if there was nothing to save."""
        with self.lock:
            todo = {t: self.tracks[t].copy() for t in self.dirty if t >= 0}
            changed = bool(self.dirty)
            self.dirty.clear()
            meta = {"bpm": self.bpm, "time_sig": self.time_sig, "rate": self.rate, "volumes": self.volumes,
                    "pans": self.pans, "pairs": sorted(self.pairs),
                    "mutes": sorted(self.mutes), "solos": sorted(self.solos), "loop": [self.loop_on, self.loop_a, self.loop_b],
                    "rec_mode": self.rec_mode, "regions": [[list(r) for r in rs] for rs in self.regions],
                    "reverb_sends": self.rev_sends, "delay_sends": self.dly_sends, "fx": dict(self.fx)}
            if self.drums:
                meta["drum_kit"] = self.drums.kit()
            meta["drum_seq"] = self.seq.to_json()
        if not changed:
            return False

        folder = self.project_dir

        def work():
            with self.save_lock:
                try:
                    os.makedirs(folder, exist_ok=True)
                    for t, x in todo.items():
                        path = os.path.join(folder, "track%d.wav" % (t + 1))
                        end = self._extent(x)
                        if end == 0:
                            if os.path.exists(path):
                                os.remove(path)
                        else:
                            write_wav(path, x[:end], self.rate)
                    with open(os.path.join(folder, "project.json"), "w") as f:
                        json.dump(meta, f)
                except Exception as e:
                    print("Saving failed:", e)

        th = threading.Thread(target=work, daemon=True)
        th.start()
        if wait:
            th.join()
        return bool(todo)

    @staticmethod
    def _extent(x):
        nz = np.flatnonzero(np.abs(x) > 1e-6)
        return int(nz[-1]) + 1 if len(nz) else 0

    def export(self):
        """Write stems (every track with audio, all the same length) and a stereo mix. Returns the folder name.

        Stems are the tracks as recorded, with each box's gain and fades. The mix uses the track volumes, pans and mutes, and includes the
        reverb and delay (with their tails); those two are also written as stereo "return" stems, so the
        dry stems plus the returns rebuild the mix."""
        with self.lock:
            tracks = [x.copy() for x in self.tracks]
            boxes = [[list(r) for r in rs] for rs in self.regions]
            vols, mutes, pans, pairs = list(self.volumes), set(self.mutes), list(self.pans), set(self.pairs)
            rev_sends, dly_sends, fx = list(self.rev_sends), list(self.dly_sends), dict(self.fx)
        for t in range(TRACKS):
            shape_range(boxes[t], tracks[t], 0, inplace=True)       # each box's gain and fades
        ends = [self._extent(x) for x in tracks]
        end = max(ends)
        if end == 0:
            return None
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H%M")
        name = "%s %s" % (self.song_label, stamp)
        folder = os.path.join(DATA, "exports", name)
        os.makedirs(folder, exist_ok=True)
        fmt = self.export_format
        if fmt != "wav" and not shutil.which("ffmpeg"):
            log("Export: ffmpeg isn't installed (run pi-app/setup.sh), so writing WAV instead of %s" % fmt.upper())
            fmt = "wav"

        def out(path, x, rate):
            write_audio(path, x, rate, fmt)

        playing = [t for t in range(TRACKS) if ends[t] and t not in mutes]
        use_rev = bool(effects and effects.AVAILABLE and any(rev_sends[t] for t in playing))
        use_dly = bool(effects and effects.AVAILABLE and any(dly_sends[t] for t in playing))
        tail = int(12 * self.rate) if (use_rev or use_dly) else 0
        dry = np.zeros((end + tail, 2), np.float32)
        rev_ret = np.zeros((end + tail, 2), np.float32) if use_rev else None
        dly_ret = np.zeros((end + tail, 2), np.float32) if use_dly else None
        for t in playing:
            gl, gr = pan_gains(pans[t])
            dry[:end, 0] += tracks[t][:end] * vols[t] * gl
            dry[:end, 1] += tracks[t][:end] * vols[t] * gr
        total = end
        if use_rev or use_dly:
            rev, dly = effects.Reverb(self.rate), effects.Delay(self.rate)
            rev.set(fx["rev_size"], fx["rev_tone"])
            dly.set(effects.delay_beats(fx["dly_time"]) * self.frames_per_beat(), fx["dly_feedback"])
            chunk = 65536
            for a in range(0, end + tail, chunk):
                b = min(end + tail, a + chunk)
                rev_in = np.zeros((b - a, 2), np.float32)
                dly_in = np.zeros((b - a, 2), np.float32)
                for t in playing:
                    if a >= end:
                        break
                    gl, gr = pan_gains(pans[t])
                    sig = tracks[t][a:min(b, end)] * vols[t]
                    k = len(sig)
                    if rev_sends[t]:
                        rev_in[:k, 0] += sig * gl * rev_sends[t]
                        rev_in[:k, 1] += sig * gr * rev_sends[t]
                    if dly_sends[t]:
                        dly_in[:k, 0] += sig * gl * dly_sends[t]
                        dly_in[:k, 1] += sig * gr * dly_sends[t]
                level = 0.0
                if use_rev:
                    rev_ret[a:b] = rev.process(rev_in) * (fx["rev_level"] * effects.REVERB_MAKEUP)
                    level = max(level, float(np.abs(rev_ret[a:b]).max()))
                if use_dly:
                    dly_ret[a:b] = dly.process(dly_in) * fx["dly_level"]
                    level = max(level, float(np.abs(dly_ret[a:b]).max()))
                total = b
                if a >= end and level < 1e-4:                   # the tails have died away (-80 dB)
                    break
        done = set()
        pad = lambda x: np.concatenate([x[:end], np.zeros(total - end, np.float32)]) if total > end else x[:end]
        for t in range(TRACKS):
            if t in done:
                continue
            if t in pairs and (ends[t] or ends[t + 1]):           # a stereo pair: one stereo file
                out(os.path.join(folder, "%s track%d-%d stereo" % (self.song_label, t + 1, t + 2)),
                    np.stack([pad(tracks[t]), pad(tracks[t + 1])], axis=1), self.rate)
                done |= {t, t + 1}
            elif ends[t]:
                out(os.path.join(folder, "%s track%d" % (self.song_label, t + 1)), pad(tracks[t]), self.rate)
        mix = dry[:total].copy()
        if use_rev:
            out(os.path.join(folder, "%s reverb return" % self.song_label), rev_ret[:total], self.rate)
            mix += rev_ret[:total]
        if use_dly:
            out(os.path.join(folder, "%s delay return" % self.song_label), dly_ret[:total], self.rate)
            mix += dly_ret[:total]
        mix *= MIX_GAIN
        peak = float(np.abs(mix).max())
        if peak > 0.98:
            mix *= 0.98 / peak                   # turn the whole mix down rather than clip it
        out(os.path.join(folder, "%s mix" % self.song_label), mix, self.rate)
        return name

    # ------------------------------------------------------------ effects (called from the app)

    def change_send(self, kind, track, delta):
        """kind "reverb" or "delay", track 1-8. Returns the new amount, 0..1."""
        sends = self.rev_sends if kind == "reverb" else self.dly_sends
        with self.lock:
            v = round(max(0.0, min(1.0, sends[track - 1] + delta)), 2)
            sends[track - 1] = v
            self.dirty.add(-1)
        return v

    def seq_changed(self):
        """The sequencer's patterns changed: save them with the song."""
        with self.lock:
            self.dirty.add(-1)

    def change_drum(self, param, clicks):
        """Turn a drum synth setting (the LXR's parameter number) by some knob clicks. Returns the new value."""
        v = self.drums.step(param, clicks)
        with self.lock:
            self.dirty.add(-1)                      # the kit is saved with the song
        return v

    def change_fx(self, key, delta):
        """Change one effect setting: rev_size, rev_tone, rev_level, dly_feedback, dly_level (by delta),
        or dly_time (by delta steps through effects.DELAY_TIMES). Returns the new value."""
        with self.lock:
            if key == "dly_time":
                v = effects.step_delay_time(self.fx[key], 1 if delta > 0 else -1)
            else:
                top = 0.95 if key == "dly_feedback" else 1.0
                v = round(max(0.0, min(top, self.fx[key] + delta)), 2)
            self.fx[key] = v
            self.dirty.add(-1)
        return v

    # ------------------------------------------------------------ transport (called from the app)

    def beats(self):
        return self.pos / self.frames_per_beat()

    def set_beats(self, beats):
        with self.lock:
            self.pos = round(min(max(0.0, beats), self.tape_beats) * self.frames_per_beat())

    def targets(self):
        """Which tracks the input records onto, as {track index: input channel, or None for the mix}."""
        tracks = self.armed_tracks()
        if self.input_mode == "all" and self.device:
            ch = self.device["capture"]["channels"]
            return {t: t for t in tracks if t < ch}
        if self.input_mode == "stereo" and self.device and self.device["capture"]["channels"] >= 2:
            out = {}
            for t in tracks:
                if t in out:
                    continue
                if t + 1 in tracks:
                    out[t], out[t + 1] = 0, 1             # left input, right input
                else:
                    out[t] = None
            return out
        return {t: None for t in tracks}

    def stereo_pairs_armed(self):
        """The armed pairs that stereo mode would record onto: [left track index, ...]."""
        tg = self.targets()
        return [t for t, ch in tg.items() if ch == 0 and tg.get(t + 1) == 1]

    def change_pan(self, track, delta):
        with self.lock:
            p = min(1.0, max(-1.0, self.pans[track - 1] + delta))
            self.pans[track - 1] = round(p, 3) if abs(p) > 0.01 else 0.0
            self.dirty.add(-1)
            return self.pans[track - 1]

    def armed_tracks(self):
        """The armed tracks, 0-7: the selected one plus any others."""
        return sorted({self.armed - 1} | self.arm_extra)

    def cycle_input(self):
        if not self.device:
            return
        ch = self.device["capture"]["channels"]
        modes = ["all", "stereo", "mix"] if ch >= 3 else ["stereo", "mix"] if ch == 2 else ["mix"]
        self.input_mode = modes[(modes.index(self.input_mode) + 1) % len(modes)] if self.input_mode in modes else modes[0]

    def start_recording(self):
        """Start a recording pass (call with the lock held or from set_recording)."""
        self._rec_undo = []
        before_pairs, before_pans = set(self.pairs), list(self.pans)
        stereo = self.stereo_pairs_armed() if self.input_mode == "stereo" else []
        in_stereo = set(stereo) | {t + 1 for t in stereo}
        for t in self.targets():
            if t in in_stereo:
                continue
            for p in (t - 1, t):                             # recorded on its own: it's not part of a pair any more
                if p in self.pairs:
                    self.pairs.discard(p)
                    self.pans[p] = self.pans[p + 1] = 0.0
        for t in stereo:                                     # recording in stereo makes the pair
            self.pairs -= {t - 1, t + 1}
            self.pairs.add(t)
            self.pans[t], self.pans[t + 1] = -1.0, 1.0
        if self.pairs != before_pairs:
            self._rec_undo.append(("pairs", None, before_pairs))
            self._rec_undo += [("pan", t, before_pans[t]) for t in range(TRACKS) if self.pans[t] != before_pans[t]]
            self.dirty.add(-1)
        if self.drums_input and self.drums and self.input_mode == "all":
            # each drum recorded onto its own track: give the track that drum's sends, so it plays back
            # with the reverb and delay you heard
            rev_g, dly_g = self.drums.sends()
            for t in self.targets():
                if t < len(rev_g):
                    self.rev_sends[t], self.dly_sends[t] = round(float(rev_g[t]), 2), round(float(dly_g[t]), 2)
            self.dirty.add(-1)
        self.recording = True
        self.playing = True
        self._rec_saved = {}
        self._rec_boxes = {}
        self.undo_stack.append(self._rec_undo)
        del self.undo_stack[:-UNDO_STEPS]

    def set_recording(self, on):
        with self.lock:
            if on and not self.recording:
                self.start_recording()
            elif not on:
                self.recording = False

    # ---- MIDI sync (called from the MIDI thread, so timing is as tight as possible)

    def sync_start(self, beats=0.0):
        with self.lock:
            self.pos = int(beats * self.frames_per_beat())
            if self.rec_ready:
                self.rec_ready = False
                self.start_recording()
            self.playing = True

    def sync_continue(self):
        with self.lock:
            self.playing = True

    def sync_stop(self):
        with self.lock:
            self.playing = self.recording = False

    # ---- loop

    def loop_region(self):
        return (self.loop_a, self.loop_b) if self.loop_b > self.loop_a else None

    def toggle_loop(self):
        with self.lock:
            if not self.loop_region():
                bar = self.bar_beats() * self.frames_per_beat()
                self.loop_a = int((self.pos // bar) * bar)
                self.loop_b = int(min(self.frames, self.loop_a + 4 * bar))
                self.loop_on = True
            else:
                self.loop_on = not self.loop_on
            self.dirty.add(-1)

    def set_loop_point(self, which, beats):
        with self.lock:
            f = round(min(max(0.0, beats), self.tape_beats) * self.frames_per_beat())
            if which == "in":
                self.loop_a = f
                if self.loop_b <= f:
                    self.loop_b = int(min(self.frames, f + 4 * self.bar_beats() * self.frames_per_beat()))
            else:
                self.loop_b = f
                if self.loop_a >= f:
                    self.loop_a = int(max(0, f - 4 * self.bar_beats() * self.frames_per_beat()))
            self.loop_on = self.loop_b > self.loop_a
            self.dirty.add(-1)

    def clear_region(self):
        with self.lock:
            self.loop_on, self.loop_a, self.loop_b = False, 0, 0
            self.dirty.add(-1)

    def toggle_rec_mode(self):
        with self.lock:
            self.rec_mode = "overdub" if self.rec_mode == "replace" else "replace"
            self.dirty.add(-1)
            return self.rec_mode

    # ---- mixing

    def change_volume(self, track, delta):
        with self.lock:
            v = min(1.0, max(0.0, self.volumes[track - 1] + delta))
            self.volumes[track - 1] = round(v, 3)
            self.dirty.add(-1)
            return v

    def toggle_mute(self, track):
        with self.lock:
            self.mutes ^= {track - 1}
            self.dirty.add(-1)
            return (track - 1) in self.mutes

    def toggle_solo(self, track):
        with self.lock:
            self.solos ^= {track - 1}
            self.dirty.add(-1)
            return (track - 1) in self.solos

    def audible(self, t):
        """Whether track t (0-7) is heard: not muted, and soloed if anything is soloed."""
        return t not in self.mutes and (not self.solos or t in self.solos)

    # ---- the boxes (regions) on each track

    def _regions_from_meta(self):
        """Boxes from project.json; older projects (splice points, or nothing) get boxes made from their audio."""
        self.regions = [[] for _ in range(TRACKS)]
        saved = self._meta_regions
        for t in range(TRACKS):
            if saved and t < len(saved):
                self.regions[t] = sorted(box(r[0], r[1], int(r[2]) % len(REGION_COLOURS),
                                             *([float(r[3]), int(r[4]), int(r[5])] if len(r) >= 6 else []))
                                         for r in saved[t] if int(r[1]) > int(r[0]))
                continue
            end = self.track_end(t)
            if not end:
                continue
            first = int(np.flatnonzero(self.levels[t] > 1e-6)[0] / RES * self.frames_per_beat())
            cuts = sorted(int(f) for f in (self._meta_splices[t] if self._meta_splices and t < len(self._meta_splices) else []))
            edges = [0] + [c for c in cuts if 0 < c < end] + [end]
            for x0, x1 in zip(edges, edges[1:]):
                x0, x1 = max(x0, first), x1
                if x1 > x0 and np.any(np.abs(self.tracks[t][x0:x1]) > 1e-6):
                    self.regions[t].append(box(x0, x1, self._new_colour(t, x0)))

    def _new_colour(self, t, f, avoid=()):
        """A random colour for a new box, different from its neighbours."""
        near = set(avoid)
        for r in self.regions[t]:
            if abs(r[1] - f) < 2 or abs(r[0] - f) < 2 or r[0] <= f < r[1]:
                near.add(r[2])
        choices = [i for i in range(len(REGION_COLOURS)) if i not in near] or list(range(len(REGION_COLOURS)))
        return random.choice(choices)

    def region_at(self, t, f):
        for r in self.regions[t]:
            if r[0] <= f < r[1]:
                return r
        return None

    def _carve(self, t, a, b):
        """Clear [a, b) of boxes: boxes inside go, boxes across the edges are trimmed (or split in two)."""
        out = []
        for r in self.regions[t]:
            if r[1] <= a or r[0] >= b:
                out.append(r)
                continue
            both = r[0] < a and r[1] > b                     # split in two: each half keeps its outer fade
            if r[0] < a:
                out.append([r[0], a] + list(r[2:5]) + [0 if both else r[5]])
            if r[1] > b:
                out.append([b, r[1]] + list(r[2:4]) + [0 if both else r[4], r[5]])
        self.regions[t] = sorted(out)

    def _add_region(self, t, a, b, colour=None):
        a, b = max(0, a), min(self.frames, b)
        if b <= a:
            return None
        self._carve(t, a, b)
        r = box(a, b, self._new_colour(t, a) if colour is None else colour)
        self.regions[t] = sorted(self.regions[t] + [r])
        return r

    def _regions_changed(self, t, entries):
        entries.append(("regions", t, [list(r) for r in self.regions[t]]))
        self.dirty.add(-1)

    def _rec_region(self, t, a, b):
        """Recording wrote [a, b) on track t: grow this pass's box, or make one.
        Replace: the new recording is its own box and covers what was there.
        Overdub: it joins the boxes it lands on."""
        own = self._rec_boxes.get(t)
        if own is not None and not any(r is own for r in self.regions[t]):
            own = None
        if self.rec_mode == "overdub":
            touching = [r for r in self.regions[t] if r[0] <= b and r[1] >= a]
            for r in touching:
                # recording onto a box with gain or fades: put them into its audio first, so the new
                # recording isn't changed by them
                self._bake(t, r, self._rec_undo if self._rec_undo is not None else [])
            if touching:
                lo, hi = min([a] + [r[0] for r in touching]), max([b] + [r[1] for r in touching])
                keep = own if any(r is own for r in touching) else touching[0]
                self.regions[t] = [r for r in self.regions[t] if r is keep or not any(r is x for x in touching)]
                keep[0], keep[1] = lo, hi
                self.regions[t].sort()
                self._rec_boxes[t] = keep
                return
        if own is not None and own[0] <= a <= own[1]:
            others = [r for r in self.regions[t] if r is not own]
            self.regions[t] = others
            self._carve(t, a, b)
            own[1] = max(own[1], b)
            self.regions[t] = sorted(self.regions[t] + [own])
            return
        partner = self._rec_boxes.get(t - 1) if (t - 1) in self.pairs else None
        self._rec_boxes[t] = self._add_region(t, a, b, partner[2] if partner else None)

    # ---- editing: SPLICE splits a box; LIFT, CUT and DROP work on whole boxes

    def track_end(self, t):
        """Where the audio on track t ends, in frames (from the drawn levels, so it's quick)."""
        lv = self.levels[t]
        nz = np.flatnonzero(lv > 1e-6)
        if not len(nz):
            return 0
        return int(min(self.frames, np.ceil((nz[-1] + 1) / RES * self.frames_per_beat())))

    def edit_tracks(self):
        """The track(s) LIFT, CUT and DROP work on: the selected track, or both tracks of its stereo pair."""
        t = self.armed - 1
        if t in self.pairs:
            return [t, t + 1]
        if t - 1 in self.pairs:
            return [t - 1, t]
        return [t]

    def selection(self):
        """(track indexes, start, end) of what LIFT and CUT would take: the box under the playhead,
        or, while selecting, every box from where the selection started to the playhead."""
        ts = self.edit_tracks()
        if self.sel_anchor is None:
            lo = hi = self.pos
            rs = [r for t in ts for r in self.regions[t] if r[0] <= lo < r[1]]
        else:
            lo, hi = sorted((self.sel_anchor, self.pos))
            rs = [r for t in ts for r in self.regions[t] if r[0] <= hi and r[1] > lo]
        if not rs:
            return None
        return ts, min(r[0] for r in rs), max(r[1] for r in rs)

    def begin_selection(self):
        with self.lock:
            if self.sel_anchor is None:
                self.sel_anchor = self.pos

    def end_selection(self):
        with self.lock:
            self.sel_anchor = None

    def _changed(self, t, a, b):
        self._update_levels(t, a, b, reset=True)
        self.dirty.add(t)

    def splice(self, all_tracks=False):
        """Split the box under the playhead in two (the right half gets a new colour), on every armed
        track (all_tracks: every track). At a join between two boxes it joins them back into one.
        Returns "added", "removed" or None."""
        with self.lock:
            f = int(self.pos)
            t0 = self.armed - 1
            ts = list(range(TRACKS)) if all_tracks else self.armed_tracks()
            ts = sorted(set(ts) | {p for t in ts for p in (t - 1, t + 1)
                                   if 0 <= p < TRACKS and (min(t, p) in self.pairs)})    # stereo pairs split together
            tol = self.frames_per_beat() / 16

            def join_at(t):
                left = [r for r in self.regions[t] if abs(r[1] - f) <= tol]
                right = [r for r in self.regions[t] if abs(r[0] - f) <= tol]
                return (left[0], right[0]) if left and right and left[0][1] == right[0][0] else None

            joining = join_at(t0) is not None
            entries = []
            done = False
            for t in ts:
                if joining:
                    pair = join_at(t)
                    if pair:
                        self._regions_changed(t, entries)
                        if pair[0][3] != pair[1][3] or pair[0][5] or pair[1][4]:
                            self._bake(t, pair[0], entries)        # different gains, or fades at the join: keep the sound
                            self._bake(t, pair[1], entries)
                        pair[0][1] = pair[1][1]
                        pair[0][5] = pair[1][5]
                        self.regions[t].remove(pair[1])
                        done = True
                else:
                    r = self.region_at(t, f)
                    if r and r[0] + tol < f < r[1] - tol:
                        self._regions_changed(t, entries)
                        right = box(f, r[1], self._new_colour(t, f, avoid=(r[2],)), r[3], 0, r[5])
                        r[1], r[5] = f, 0
                        self.regions[t] = sorted(self.regions[t] + [right])
                        done = True
            self._push_undo(entries)
            if not done:
                return None
            return "removed" if joining else "added"

    def _seam(self, t, f):
        """Where dropped audio meets what was there: a 1 ms fade out and in, so the jump doesn't click."""
        x = self.tracks[t]
        a, b = max(0, f - GUARD), min(self.frames, f + GUARD)
        if f > a:
            x[a:f] *= fade_curve((f - np.arange(a, f)) / GUARD)
        if b > f:
            x[f:b] *= fade_curve((np.arange(f, b) - f + 1) / GUARD)

    def _bake(self, t, r, entries):
        """Put box r's gain and fades into its audio (for undo, in entries) and set them back to none."""
        if len(r) < 6 or box_settings(r) == (0.0, 0, 0):
            return
        a, b = r[0], r[1]
        entries.append((t, a, self.tracks[t][a:b].copy()))
        self.tracks[t][a:b] = np.clip(shape_range([r], self.tracks[t][a:b], a, guard=False), -1.0, 1.0)
        r[3], r[4], r[5] = 0.0, 0, 0
        self._changed(t, a, b)

    # ---- a box's gain, normalize and fades (the knobs in the zoomed track view)

    def boxes_here(self):
        """[(track, box)] under the playhead, on the selected track (both tracks of a stereo pair)."""
        f = int(self.pos)
        return [(t, r) for t in self.edit_tracks() for r in self.regions[t] if r[0] <= f < r[1]]

    def box_info(self):
        """{"gain" dB, "in" s, "out" s, "length" s} of the box under the playhead, or None."""
        with self.lock:
            here = self.boxes_here()
            if not here:
                return None
            r = here[0][1]
            g, fi, fo = box_settings(r)
            return {"gain": g, "in": fi / self.rate, "out": fo / self.rate, "length": (r[1] - r[0]) / self.rate}

    def _box_undo(self, here, kind):
        """Knob turns on the same box, one after another, are one undo step."""
        key = (kind, tuple((t, r[0], r[1]) for t, r in here))
        now = time.monotonic()
        last = getattr(self, "_box_edit", None)
        if not (last and last[0] == key and now - last[1] < 3.0 and self.undo_stack and last[2] is self.undo_stack[-1]):
            entries = []
            for t in sorted({t for t, _ in here}):
                self._regions_changed(t, entries)
            self._push_undo(entries)
            self._box_edit = [key, now, entries]
        else:
            last[1] = now

    def change_box(self, what, delta=0):
        """what: "gain" (delta in dB), "in" / "out" (delta in fade steps), "normalize", or "reset_gain",
        "reset_in", "reset_out". Returns box_info(), "SILENT" (nothing to normalize), or None (no box)."""
        with self.lock:
            here = self.boxes_here()
            if not here:
                return None
            for _, r in here:
                if len(r) < 6:
                    r[3:] = [0.0, 0, 0]
            r0 = here[0][1]
            if what == "normalize":
                peak = max(float(np.abs(self.tracks[t][r[0]:r[1]]).max()) for t, r in here)
                if peak < 1e-5:
                    return "SILENT"
                self._box_undo(here, "normalize-%f" % time.monotonic())
                g = round(float(min(GAIN_MAX, max(GAIN_MIN, NORMALIZE_DB - 20 * np.log10(peak)))), 1)
                for _, r in here:
                    r[3] = g
            elif what in ("gain", "reset_gain"):
                self._box_undo(here, "gain")
                g = 0.0 if what == "reset_gain" else round(float(min(GAIN_MAX, max(GAIN_MIN, r0[3] + delta))), 1)
                for _, r in here:
                    r[3] = g
            else:
                side = 4 if what.endswith("in") else 5
                self._box_undo(here, "fade%d" % side)
                if what.startswith("reset"):
                    v = 0.0
                else:
                    cur = r0[side]
                    steps = [int(round(s * self.rate)) for s in FADE_STEPS]
                    i = max([k for k, s in enumerate(steps) if s <= cur] or [0])
                    if delta < 0 and steps[i] < cur:
                        i += 1                                  # between steps (fitted to a short box)
                    v = FADE_STEPS[max(0, min(len(FADE_STEPS) - 1, i + delta))]
                for _, r in here:
                    other = r[9 - side]
                    r[side] = max(0, min(int(round(v * self.rate)), r[1] - r[0] - other))
            for t, r in here:
                self._update_levels(t, r[0], r[1], reset=True)
            self.dirty.add(-1)
        return self.box_info()

    def copy(self):
        """Copy the selected box(es) to the clipboard as one piece. Returns its length in beats, or None."""
        with self.lock:
            sel = self.selection()
            self.sel_anchor = None
            if not sel:
                return None
            ts, a, b = sel
            self.clip = [shape_range(self.regions[t], self.tracks[t][a:b], a).copy() for t in ts]
            self.last_edit = (a, b)
            return (b - a) / self.frames_per_beat()

    def cut(self):
        """Take the selected box(es) off the tape onto the clipboard, leaving an empty space.
        Returns the length in beats, or None."""
        with self.lock:
            sel = self.selection()
            self.sel_anchor = None
            if not sel:
                return None
            ts, a, b = sel
            self.clip = [shape_range(self.regions[t], self.tracks[t][a:b], a).copy() for t in ts]
            self.last_edit = (a, b)
            entries = []
            for t in ts:
                entries.append((t, a, self.tracks[t][a:b].copy()))
                self._regions_changed(t, entries)
                self._carve(t, a, b)
                self.tracks[t][a:b] = 0
                self._changed(t, a, b)
            self._push_undo(entries)
            return (b - a) / self.frames_per_beat()

    def drop(self, insert=False):
        """Put the clipboard down at the playhead as a new box. A stereo piece goes onto two tracks (the
        selected track's pair, or the selected track and the one below it) and makes them a pair.
        insert=False covers what's there; insert=True pushes the rest of the track(s) later.
        Returns True, or a reason it couldn't."""
        with self.lock:
            if self.clip is None:
                return "NOTHING TO DROP: CUT OR COPY SOMETHING FIRST"
            a = int(self.pos)
            if len(self.clip) == 2:
                base = self.edit_tracks()[0]
                if base + 1 >= TRACKS:
                    return "A STEREO PIECE NEEDS TWO TRACKS: SELECT TRACK 7 OR LOWER"
                ts = [base, base + 1]
            else:
                ts = [self.armed - 1]
            n = min(len(self.clip[0]), self.frames - a)
            if n <= 0:
                return "NO ROOM LEFT ON THE TAPE"
            entries = [("pairs", None, set(self.pairs))]
            colour = None
            for t, x in zip(ts, self.clip):
                self._regions_changed(t, entries)
                a0 = max(0, a - GUARD)
                if insert:
                    entries.append((t, a0, self.tracks[t][a0:a].copy()))
                    entries.append((t, a, self.tracks[t][a:].copy()))
                    tail = self.tracks[t][a:self.frames - n].copy()
                    self.tracks[t][a + n:] = tail
                    self.tracks[t][a:a + n] = x[:n]
                    moved = []
                    for r in self.regions[t]:
                        if r[1] <= a:
                            moved.append(r)
                        elif r[0] >= a:
                            moved.append([r[0] + n, r[1] + n] + list(r[2:]))
                        else:                               # a box across the playhead splits around the new one
                            moved.append([r[0], a] + list(r[2:5]) + [0])
                            moved.append([a + n, r[1] + n] + list(r[2:4]) + [0, r[5]])
                    self.regions[t] = sorted([r[0], min(r[1], self.frames)] + list(r[2:])
                                             for r in moved if r[0] < self.frames)
                    self._seam(t, a)
                    self._seam(t, a + n)
                    self._changed(t, a0, self.frames)
                else:
                    b1 = min(self.frames, a + n + GUARD)
                    entries.append((t, a0, self.tracks[t][a0:b1].copy()))
                    self.tracks[t][a:a + n] = x[:n]
                    self._seam(t, a)
                    self._seam(t, a + n)
                    self._changed(t, a0, b1)
                box = self._add_region(t, a, a + n, colour)
                colour = box[2] if box else colour             # both sides of a stereo piece share a colour
            if len(ts) == 2 and ts[0] not in self.pairs:
                entries += [("pan", ts[0], self.pans[ts[0]]), ("pan", ts[1], self.pans[ts[1]])]
                self.pairs -= {ts[0] - 1, ts[1]}
                self.pairs.add(ts[0])
                self.pans[ts[0]], self.pans[ts[1]] = -1.0, 1.0
                self.dirty.add(-1)
            self.last_edit = (a, a + n)
            self._push_undo(entries)
            return True

    def bounce(self, sources, dest):
        """Mix tracks (0-7) down onto track dest, as you hear them (at their volumes), and empty the
        others. dest's volume goes to 100% so it sounds the same. Returns the length in beats, or None."""
        with self.lock:
            if self.playing or self.recording:
                return None
            ts = sorted(set(sources) | {dest})
            end = max(self.track_end(t) for t in ts)
            if len(ts) < 2 or not end:
                return None
            entries = [("pairs", None, set(self.pairs))]
            for t in ts:
                entries.append(("volume", t, self.volumes[t]))
                entries.append(("pan", t, self.pans[t]))
                self._regions_changed(t, entries)
                entries.append((t, 0, self.tracks[t][:end].copy()))
            mix = np.zeros(end, np.float32)
            spans = []
            for t in ts:
                mix += shape_range(self.regions[t], self.tracks[t][:end], 0) * self.volumes[t]
                spans += [(r[0], r[1]) for r in self.regions[t]]
            for t in ts:
                self.tracks[t][:end] = 0
                self.regions[t] = []
            self.tracks[dest][:end] = saturate(mix)
            self.volumes[dest] = 1.0
            self.pans[dest] = 0.0                        # a bounce is mono, in the centre
            self.pairs -= {p for p in self.pairs if p in ts or p + 1 in ts}
            merged = []                                  # where any of the tracks had a box, the bounce has one
            for a, b in sorted(spans):
                if merged and a <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], b)
                else:
                    merged.append([a, b])
            for a, b in merged:
                self._add_region(dest, a, b)
            for t in ts:
                self._changed(t, 0, end)
            self._push_undo(entries)
            return end / self.frames_per_beat()

    def _push_undo(self, entries):
        if entries:
            self.undo_stack.append(entries)
            del self.undo_stack[:-UNDO_STEPS]

    def undo(self):
        with self.lock:
            while self.undo_stack and not self.undo_stack[-1]:
                self.undo_stack.pop()               # a recording pass that recorded nothing
            if not self.undo_stack or self.recording:
                return False
            for item in reversed(self.undo_stack.pop()):
                if item[0] == "regions":
                    t = item[1]
                    spans = [(r[0], r[1]) for r in self.regions[t]] + [(r[0], r[1]) for r in item[2]]
                    self.regions[t] = item[2]
                    for a, b in spans:                  # gains and fades change how the waveform looks
                        self._update_levels(t, a, b, reset=True)
                    self.dirty.add(-1)
                    continue
                if item[0] in ("volume", "pan", "pairs"):
                    if item[0] == "volume":
                        self.volumes[item[1]] = item[2]
                    elif item[0] == "pan":
                        self.pans[item[1]] = item[2]
                    else:
                        self.pairs = set(item[2])
                    self.dirty.add(-1)
                    continue
                t, a, old = item
                self.tracks[t][a:a + len(old)] = old
                self._changed(t, a, a + len(old))
            return True

    # ------------------------------------------------------------ the audio thread

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="audio").start()

    def stop(self):
        self._stop = True
        self.save_phones_volume()
        self._close_port()

    def _run(self):
        import alsaaudio
        while not self._stop:
            dev = self.find_input()
            if dev and dev.get("virtual"):
                self._drums_loop(dev)
                continue
            if not dev:
                self.device = None
                if not self._play_without_input():
                    self.status = "NO AUDIO DEVICE"
                    time.sleep(2)
                continue
            cap_fmt = dev["capture"]["format"]
            rate = pick_rate(dev["capture"]["rates"])
            if rate != self.rate:
                self.status = "%s RUNS AT %d HZ (TAPE IS %d)" % (dev["name"].upper(), rate, self.rate)
            cap = None
            play = dev.get("playback")
            period = int(self.settings.get("usb_period", USB_PERIOD))
            periods = int(self.settings.get("usb_periods", USB_PERIODS))
            try:
                name = "hw:CARD=%s,DEV=0" % dev["id"]
                cap = alsaaudio.PCM(type=alsaaudio.PCM_CAPTURE, mode=alsaaudio.PCM_NORMAL, device=name,
                                    rate=rate, channels=dev["capture"]["channels"],
                                    format=getattr(alsaaudio, "PCM_FORMAT_" + cap_fmt),
                                    periodsize=period, periods=periods)
                self.in_period, self.dev_buffer = period, period * periods
                self._dev_open = (name, rate, period, periods)
                self._route_due = 0.0                # work out the output again with these sizes
                self.device = dev
                if self.input_mode is None:
                    ch = dev["capture"]["channels"]
                    self.input_mode = "all" if ch >= 8 else "stereo" if ch == 2 else "mix"
                self.status = ""
                print("Audio: %s, %d in / %d out, %d Hz" % (dev["name"], dev["capture"]["channels"],
                                                          play["channels"] if play else 0, rate))
                if self._resume_recording:
                    with self.lock:
                        if self.playing:
                            self.recording = True        # carry on the same recording pass after a hiccup
                            log("Recording resumed")
                self._resume_recording = False
                self._loop(cap, dev)
            except Exception as e:
                self._resume_recording = self.recording
                log("Audio stopped%s: %s" % (" while recording" if self.recording else "", e),
                    traceback.format_exc())
                self.status = "AUDIO DEVICE LOST"
            finally:
                try:
                    cap and cap.close()
                except Exception:
                    pass
                self.device = None
                with self.lock:
                    self.recording = False
            time.sleep(1)

    def _open_device_output(self, play):
        """The input device's own output, primed with silence."""
        import alsaaudio
        name, rate, period, periods = self._dev_open
        pb = alsaaudio.PCM(type=alsaaudio.PCM_PLAYBACK, mode=alsaaudio.PCM_NORMAL, device=name,
                           rate=rate, channels=play["channels"],
                           format=getattr(alsaaudio, "PCM_FORMAT_" + play["format"]),
                           periodsize=period, periods=periods)
        silence = encode(np.zeros((period, play["channels"]), np.float32), play["format"])
        for _ in range(periods):
            pb.write(silence)
        return pb

    def _loop(self, cap, dev):
        """Read the input device, record and play. The device's own output is only opened while the tape
        plays there: the OP-XY sometimes garbles what it sends (repeated 1 ms packets, a crackle in the
        recording) while it's also being sent audio, so with the output elsewhere it's left alone."""
        ch_in = dev["capture"]["channels"]
        play = dev.get("playback")
        pb = None
        self._dev_out_retry = 0.0
        self._input_due = time.monotonic() + 2.0
        try:
            while not self._stop:
                if time.monotonic() >= self._input_due:
                    self._input_due = time.monotonic() + 2.0
                    want = self.find_input()
                    if want and want["id"] != dev["id"]:
                        log("Input: switching to %s" % want["name"])
                        with self.lock:
                            self._resume_recording = self.recording
                        return                       # _run opens the other one
                n, data = cap.read()
                if n <= 0:
                    continue                         # an overrun: skip and carry on
                x = decode(data, dev["capture"]["format"], ch_in)[:n]
                out = self.process(x)
                route = self._update_route(dev)
                if route == "device" and play and pb is None and time.monotonic() >= self._dev_out_retry:
                    try:
                        pb = self._open_device_output(play)
                    except Exception as e:      # keep recording; try the output again in a moment
                        log("Couldn't open %s's output: %s" % (dev["name"], e))
                        self._dev_out_retry = time.monotonic() + 2.0
                elif route != "device" and pb is not None:
                    self._close_pcm(pb)
                    pb = None
                if pb:
                    o = np.zeros((n, play["channels"]), np.float32)
                    o[:, :min(2, play["channels"])] = out[:, :min(2, play["channels"])]
                    pb.write(encode(o, play["format"]))
                port = self.port
                if port:
                    port.push(out)
        finally:
            if pb is not None:
                self._close_pcm(pb)

    @staticmethod
    def _close_pcm(pcm):
        try:
            if hasattr(pcm, "drop"):
                pcm.drop()                           # stop now, without playing out what's queued
            pcm.close()
        except Exception:
            pass

    def _play_without_input(self):
        """With no input device plugged in, play the tape on the headphones (or a USB output) anyway.
        Returns False straight away if there's nowhere to play; otherwise runs until an input device appears."""
        self.in_period = PERIOD
        if self._update_route(None) is None or not self.port:
            return False
        self.status = "NO INPUT DEVICE  ·  PLAYING ON %s" % self.output_label
        silence = np.zeros((PERIOD, 1), np.float32)
        look = time.monotonic() + 2.0
        while not self._stop:
            port = self.port
            if port is None or port.dead:
                self._update_route(None)
                if not self.port:
                    return False
                continue
            if port.fill() > port.TARGET:
                time.sleep(0.003)               # the output sets the pace
                continue
            port.push(self.process(silence))
            self._update_route(None)
            self.status = "NO INPUT DEVICE  ·  PLAYING ON %s" % self.output_label
            if time.monotonic() > look:
                look = time.monotonic() + 2.0
                if self.find_input():
                    return True                 # an input device turned up: go and open it
        return True

    def _drums_loop(self, dev):
        """The drum synth as the input: no device to read, so the output sets the pace (or the clock, if
        there's nowhere to play). Runs until another input is chosen."""
        self.device, self.in_period = dev, PERIOD
        if self.input_mode is None:
            self.input_mode = "all"
        self.status = ""
        self._route_due = 0.0
        log("Input: drum synth")
        if self._resume_recording:
            with self.lock:
                if self.playing:
                    self.recording = True
        self._resume_recording = False
        due = time.monotonic()
        look = time.monotonic() + 2.0
        bpm = None
        was_playing = False
        self._seq_fifo = np.zeros((0, drums.VOICES), np.float32)
        try:
            while not self._stop:
                self._update_route(None)
                port = self.port
                if port and not port.dead:
                    if port.fill() > port.TARGET:
                        time.sleep(0.003)       # the output sets the pace
                        continue
                else:
                    now = time.monotonic()
                    if now < due:
                        time.sleep(min(0.005, due - now))
                        continue
                    due = max(due, now - 0.1) + PERIOD / self.rate
                if self.bpm != bpm:
                    bpm = self.bpm
                    self.drums.set_bpm(bpm)     # the drum synth's tempo-synced LFOs follow the song
                events = []
                if self.playing and not was_playing:
                    # just started: the first read_ahead frames of tape go by before you hear anything, so
                    # make the sequencer's hits for them now, straight into what gets recorded
                    start = self.pos
                    ahead = self.seq.events(start, self.read_ahead, self.frames_per_beat())
                    self._seq_fifo = self.drums.render(self.read_ahead, ahead, with_live=False)[0]
                if self.playing:
                    was_playing = True
                    # the sequencer plays in step with the tape you hear: read_ahead frames on from pos
                    events = self.seq.events(self._heard_frame(), PERIOD, self.frames_per_beat())
                elif was_playing:
                    was_playing = False
                    self.seq.stop()
                if events:
                    soon = time.monotonic() + self.read_ahead / self.rate     # when you'll hear them
                    for offset, lane, _vel, _locks in events:
                        self.seq_hits[lane] = soon + offset / self.rate
                seq_voices, live_voices = self.drums.render(PERIOD, events)
                # what you hear: both, now. What's recorded (at pos, where you pressed): your hits now, and
                # the sequencer's from read_ahead frames ago (they were made that far ahead, to sound on time)
                voices = live_voices + self._delay_sequencer(seq_voices)
                # each voice (MULTI), or the kit panned in stereo (STEREO, and MONO mixes it)
                x = voices if self.input_mode == "all" else self.drums.stereo(voices)
                heard = seq_voices + live_voices
                pans = self.drums.pans() * DRUMS_MONITOR
                rev_g, dly_g = self.drums.sends()            # each drum's sends to the reverb and delay
                out = self.process(x, monitor=heard @ pans,
                                   monitor_rev=(heard * rev_g) @ pans if rev_g.any() else None,
                                   monitor_dly=(heard * dly_g) @ pans if dly_g.any() else None)
                if port and not port.dead:
                    port.push(out)
                if time.monotonic() > look:
                    look = time.monotonic() + 2.0
                    want = self.find_input()
                    if not want or want["id"] != dev["id"]:
                        with self.lock:
                            self._resume_recording = self.recording
                        log("Input: switching from the drum synth")
                        return
        except Exception as e:
            log("Drum synth stopped: %s" % e, traceback.format_exc())
            time.sleep(1)
        finally:
            self.device = None
            with self.lock:
                self.recording = False

    def _heard_frame(self):
        """The tape frame you're hearing as this block goes out (pos + read_ahead, round the loop)."""
        t = self.pos + self.read_ahead
        region = self.loop_region() if self.loop_on else None
        if region and self.pos < region[1] and t >= region[1] and region[1] > region[0]:
            t = region[0] + (t - region[1]) % (region[1] - region[0])
        return t

    def _delay_sequencer(self, block):
        """block, read_ahead frames late: the sequencer's sound lined up with where it belongs on tape."""
        fifo, want = self._seq_fifo, self.read_ahead
        if len(fifo) < want:
            fifo = np.concatenate([np.zeros((want - len(fifo), block.shape[1]), np.float32), fifo])
        elif len(fifo) > want:
            fifo = fifo[len(fifo) - want:]
        fifo = np.concatenate([fifo, block])
        out, self._seq_fifo = fifo[:len(block)], fifo[len(block):]
        return out

    def process(self, x, monitor=None, monitor_rev=None, monitor_dly=None):
        """One block of input (frames, channels) -> one block of stereo output. Also records.
        monitor: (frames, 2) to hear straight away along with the tape (the drum synth as you play it)."""
        n = len(x)
        mix = np.zeros((n, 2), np.float32)              # the tracks, before the limiter
        if monitor is not None:
            mix += monitor
        rev_in = np.zeros((n, 2), np.float32)           # what the tracks send to the reverb
        dly_in = np.zeros((n, 2), np.float32)           # ... and to the delay
        if monitor_rev is not None:
            rev_in += monitor_rev                       # the drum synth's own sends
        if monitor_dly is not None:
            dly_in += monitor_dly
        with self.lock:
            peaks = np.abs(x).max(axis=0) if n else np.zeros(1)
            self.in_peaks[:] = 0
            self.in_peaks[:min(TRACKS, len(peaks))] = peaks[:TRACKS]
            done = 0
            while self.playing and done < n:
                loop = self.loop_region() if self.loop_on else None
                limit = loop[1] if (loop and self.pos < loop[1]) else self.frames
                m = min(n - done, limit - self.pos)
                if m <= 0:
                    if loop and self.pos >= loop[1] and limit == loop[1]:
                        self.pos = loop[0]
                        continue
                    self.playing = self.recording = False
                    break
                self._block(x[done:done + m], self.pos, loop,
                            mix[done:done + m], rev_in[done:done + m], dly_in[done:done + m])
                self.pos += m
                if self.link_nudge and self.pos + self.link_nudge >= 0:
                    self.pos += self.link_nudge         # a frame now and then, to stay on Link's beat
                done += m
                if loop and self.pos >= loop[1] and limit == loop[1]:
                    self.pos = loop[0]
            # the effects run all the time, so their tails ring on after you stop
            mix += self.run_effects(rev_in, dly_in)
        return np.tanh(mix * MIX_GAIN)                  # tanh: gentle limiting instead of harsh clipping

    def run_effects(self, rev_in, dly_in, rev=None, dly=None):
        """The reverb and delay returns, (frames, 2), at their levels. Uses the live effects unless given others."""
        if not effects or not effects.AVAILABLE:
            return 0.0
        if rev is None:
            if self._rev is None:
                self._rev, self._dly = effects.Reverb(self.rate), effects.Delay(self.rate)
            rev, dly = self._rev, self._dly
        fx = self.fx
        rev.set(fx["rev_size"], fx["rev_tone"])
        dly.set(effects.delay_beats(fx["dly_time"]) * self.frames_per_beat(), fx["dly_feedback"])
        return (rev.process(rev_in) * (fx["rev_level"] * effects.REVERB_MAKEUP)
                + dly.process(dly_in) * fx["dly_level"])

    def _block(self, x, pos, loop, mix, rev_in, dly_in):
        """Play and record one stretch of the tape that doesn't cross the loop end.
        Adds the tracks into mix, and what they send to the effects into rev_in and dly_in."""
        m = len(x)
        targets = self.targets() if self.recording else {}
        # what reaches your ears now was sent read_ahead frames ago, so read that far ahead
        idx = np.arange(pos, pos + m) + self.read_ahead
        if loop and pos < loop[1]:
            length = loop[1] - loop[0]
            if length > 0:
                over = idx >= loop[1]
                idx[over] = loop[0] + (idx[over] - loop[1]) % length
        idx = np.minimum(idx, self.frames - 1)
        overdub = self.rec_mode == "overdub"
        for t in range(TRACKS):
            if (overdub or t not in targets) and self.audible(t):
                sig = self.tracks[t][idx] * self.volumes[t]
                env = envelope(self.regions[t], idx)
                if env is not None:
                    sig *= env                               # each box's gain and fades
                gl, gr = pan_gains(self.pans[t])
                stereo = np.stack([sig * gl, sig * gr], axis=1)
                mix += stereo
                if self.rev_sends[t]:
                    rev_in += stereo * self.rev_sends[t]     # sends are after the volume and pan
                if self.dly_sends[t]:
                    dly_in += stereo * self.dly_sends[t]
        if targets:
            # what you played now was in time with what you heard (latency - read_ahead) ago
            w0 = pos - (self.latency - self.read_ahead)
            a, b = max(0, w0), min(self.frames, w0 + m)
            region = self.loop_region()
            if region:                               # in/out points set: only record between them (punch in)
                a, b = max(a, region[0]), min(b, region[1])
            if b > a:
                for t, ch in targets.items():
                    src = (x.mean(axis=1) if ch is None else x[:, ch])[a - w0:b - w0]
                    ta = a
                    own = self._rec_boxes.get(t)
                    if own is not None and 0 < a - own[1] <= 64:
                        # the tape was nudged a frame or two ahead (Link keeping time): fill the gap with
                        # the first new sample, so the recording stays one piece
                        ta = own[1]
                        src = np.concatenate([np.full(a - ta, src[0] if len(src) else 0.0, np.float32), src])
                    self._save_for_undo(t, ta, b)
                    self._rec_region(t, ta, b)
                    a_t = ta
                    if overdub:
                        self.tracks[t][a_t:b] = saturate(self.tracks[t][a_t:b] + src)
                    else:
                        self.tracks[t][a_t:b] = src
                    self._update_levels(t, a_t, b, reset=True)
                    self.dirty.add(t)

    def _save_for_undo(self, t, a, b):
        """Keep what a recording pass overwrites, the first time it overwrites it."""
        if self._rec_undo is None:
            return
        s = self._rec_saved.get(t)
        if s and s[0] <= a and b <= s[1]:
            return                                   # already saved (a loop coming round again)
        if s and a == s[1]:
            self._rec_undo.append((t, a, self.tracks[t][a:b].copy()))
            s[1] = b
        elif not s:
            self._rec_undo.append(("regions", t, [list(r) for r in self.regions[t]]))
            self._rec_undo.append((t, a, self.tracks[t][a:b].copy()))
            self._rec_saved[t] = [a, b]
        else:
            lo, hi = min(a, s[0]), max(b, s[1])
            if a < s[0]:
                self._rec_undo.append((t, a, self.tracks[t][a:s[0]].copy()))
            if b > s[1]:
                self._rec_undo.append((t, s[1], self.tracks[t][s[1]:b].copy()))
            self._rec_saved[t] = [lo, hi]

    def _update_levels(self, t, a, b, reset=False):
        fpb = self.frames_per_beat() / RES          # frames per level value
        lv = self.levels[t]
        if b <= a:
            return
        i0, i1 = int(a // fpb), min(len(lv), int((b - 1) // fpb) + 1)
        if reset:
            lv[i0:i1] = 0
            # widen to whole level values, so the edges keep the audio just outside a-b
            a, b = int(i0 * fpb), min(self.frames, int(np.ceil(i1 * fpb)))
        seg = np.abs(shape_range(self.regions[t], self.tracks[t][a:b], a))
        bins = np.minimum((np.arange(a, b) // fpb).astype(np.int64), len(lv) - 1)
        starts = np.concatenate(([0], np.flatnonzero(np.diff(bins)) + 1))
        idx = bins[starts]
        lv[idx] = np.maximum(lv[idx], np.maximum.reduceat(seg, starts))
