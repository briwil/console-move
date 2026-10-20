"""The audio engine: records from a USB audio device onto 8 tape tracks and plays them back.

- Finds the first USB audio device (an OP-XY, a UCA202, ...) and keeps retrying
  if none is plugged in, so you can plug one in while the app runs.
- Input modes:
    "all"  input channel N goes to track N, on every armed track (an OP-XY in
           8-channel mode can record all 8 tracks at once)
    "mix"  every input channel mixed together goes to the armed track(s) (for a
           stereo source like a synth into a UCA202)
- One track is selected (self.armed: editing works on it, and it always
  records); more can be armed with it (self.arm_extra).
- Plays the tape out of the same device, if it has an output (the OP-XY does,
  so you hear the tape on its headphone jack).
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
import threading
import time
import wave

import numpy as np

from palette import REGION_COLOURS

TRACKS = 8
RES = 16                 # waveform level values per beat, same as tape.RES
PERIOD = 512             # frames per audio block
PERIODS = 8              # blocks queued in the output buffer (about 90 ms: room for the screen drawing)
MIX_GAIN = 0.6
UNDO_STEPS = 8


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


def saturate(x):
    """Gentle tape-style limit above 0.8, so overdubs that pile up never pass 1.0."""
    y = np.abs(x)
    over = y > 0.8
    if over.any():
        x = x.copy()
        x[over] = np.sign(x[over]) * (0.8 + 0.2 * np.tanh((y[over] - 0.8) / 0.2))
    return x


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
        self.tape_beats = 0.0
        self.volumes = [0.8] * TRACKS
        self.mutes = set()
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
        self.latency = int(self.settings.get("latency_frames", PERIOD * (PERIODS + 1)))
        self.clip = None                        # audio on the clipboard (one piece), for DROP
        # the boxes on each track: [start, end, colour] in frames, sorted, never overlapping.
        # Recording makes a box; SPLICE splits one; CUT takes boxes away and leaves an empty space.
        self.regions = [[] for _ in range(TRACKS)]
        self.sel_anchor = None                  # while selecting several pieces: where the selection started
        self.undo_stack = []                    # each entry: list of (track, start, old samples)
        self._rec_undo = None                   # the undo entry the current recording pass adds to
        self._rec_saved = {}                    # track -> [start, end) already saved for undo this pass
        self._rec_boxes = {}                    # track -> the box this recording pass is making
        self._stop = False
        self._set_beats_len()
        self.load()

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
    def sync_mode(self):
        """"external": follow the OP-XY's MIDI clock. "internal": Console leads and sends clock to it."""
        return "internal" if self.settings.get("sync") == "internal" else "external"

    def set_sync_mode(self, mode):
        self.remember("sync", mode)

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

    def new_song(self):
        """Save the current project, then start an empty, unnamed one (same tempo). It's kept in
        ~/console-data/unsaved until it's saved with a name. The clipboard stays, so a piece can be
        carried over to the new song."""
        self.save(wait=True)
        with self.lock:
            self.playing = self.recording = self.rec_ready = False
            for x in self.tracks:
                x[:] = 0
            self._set_beats_len()                       # fresh, empty waveforms
            self.regions = [[] for _ in range(TRACKS)]
            self.undo_stack = []
            self.volumes = [0.8] * TRACKS
            self.mutes = set()
            self.loop_on, self.loop_a, self.loop_b = False, 0, 0
            self.arm_extra = set()
            self.sel_anchor = None
            self.pos = 0
            self.song = None
            self.dirty = {-1}
        shutil.rmtree(os.path.join(DATA, "unsaved"), ignore_errors=True)
        self.save(wait=True)
        self.remember("last_song", None)

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
        self.volumes = [float(v) for v in meta.get("volumes", self.volumes)][:TRACKS]
        self.mutes = set(meta.get("mutes", []))
        if meta.get("rec_mode") in ("replace", "overdub"):
            self.rec_mode = meta["rec_mode"]
        self._meta_regions = meta.get("regions")
        self._meta_splices = meta.get("splices")       # from version 0.6-0.7, turned into boxes below
        if meta.get("loop"):
            self.loop_on, self.loop_a, self.loop_b = bool(meta["loop"][0]), int(meta["loop"][1]), int(meta["loop"][2])
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

    def save(self, wait=False):
        """Save changed tracks in the background. Returns False if there was nothing to save."""
        with self.lock:
            todo = {t: self.tracks[t].copy() for t in self.dirty if t >= 0}
            changed = bool(self.dirty)
            self.dirty.clear()
            meta = {"bpm": self.bpm, "rate": self.rate, "volumes": self.volumes,
                    "mutes": sorted(self.mutes), "loop": [self.loop_on, self.loop_a, self.loop_b],
                    "rec_mode": self.rec_mode, "regions": [[list(r) for r in rs] for rs in self.regions]}
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

        Stems are the tracks as recorded. The mix uses the track volumes and mutes."""
        with self.lock:
            tracks = [x.copy() for x in self.tracks]
            vols, mutes = list(self.volumes), set(self.mutes)
        ends = [self._extent(x) for x in tracks]
        end = max(ends)
        if end == 0:
            return None
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H%M")
        name = "%s %s" % (self.song_label, stamp)
        folder = os.path.join(DATA, "exports", name)
        os.makedirs(folder, exist_ok=True)
        mix = np.zeros(end, np.float32)
        for t, x in enumerate(tracks):
            if ends[t]:
                write_wav(os.path.join(folder, "%s track%d.wav" % (self.song_label, t + 1)), x[:end], self.rate)
                if t not in mutes:
                    mix += x[:end] * vols[t]
        mix *= MIX_GAIN
        peak = float(np.abs(mix).max())
        if peak > 0.98:
            mix *= 0.98 / peak                   # turn the whole mix down rather than clip it
        write_wav(os.path.join(folder, "%s mix.wav" % self.song_label), np.stack([mix, mix], axis=1), self.rate)
        return name

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
        return {t: None for t in tracks}

    def armed_tracks(self):
        """The armed tracks, 0-7: the selected one plus any others."""
        return sorted({self.armed - 1} | self.arm_extra)

    def cycle_input(self):
        if not self.device:
            return
        modes = ["all", "mix"] if self.device["capture"]["channels"] >= 3 else ["mix"]
        self.input_mode = modes[(modes.index(self.input_mode) + 1) % len(modes)] if self.input_mode in modes else modes[0]

    def start_recording(self):
        """Start a recording pass (call with the lock held or from set_recording)."""
        self.recording = True
        self.playing = True
        self._rec_undo = []
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
                bar = 4 * self.frames_per_beat()
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
                    self.loop_b = int(min(self.frames, f + 4 * 4 * self.frames_per_beat()))
            else:
                self.loop_b = f
                if self.loop_a >= f:
                    self.loop_a = int(max(0, f - 4 * 4 * self.frames_per_beat()))
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

    # ---- the boxes (regions) on each track

    def _regions_from_meta(self):
        """Boxes from project.json; older projects (splice points, or nothing) get boxes made from their audio."""
        self.regions = [[] for _ in range(TRACKS)]
        saved = self._meta_regions
        for t in range(TRACKS):
            if saved and t < len(saved):
                self.regions[t] = sorted([int(r[0]), int(r[1]), int(r[2]) % len(REGION_COLOURS)] for r in saved[t]
                                         if int(r[1]) > int(r[0]))
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
                    self.regions[t].append([x0, x1, self._new_colour(t, x0)])

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
            if r[0] < a:
                out.append([r[0], a, r[2]])
            if r[1] > b:
                out.append([b, r[1], r[2]])
        self.regions[t] = sorted(out)

    def _add_region(self, t, a, b, colour=None):
        a, b = max(0, a), min(self.frames, b)
        if b <= a:
            return None
        self._carve(t, a, b)
        r = [a, b, self._new_colour(t, a) if colour is None else colour]
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
        self._rec_boxes[t] = self._add_region(t, a, b)

    # ---- editing: SPLICE splits a box; LIFT, CUT and DROP work on whole boxes

    def track_end(self, t):
        """Where the audio on track t ends, in frames (from the drawn levels, so it's quick)."""
        lv = self.levels[t]
        nz = np.flatnonzero(lv > 1e-6)
        if not len(nz):
            return 0
        return int(min(self.frames, np.ceil((nz[-1] + 1) / RES * self.frames_per_beat())))

    def selection(self):
        """(track index, start, end) of what LIFT and CUT would take: the box under the playhead,
        or, while selecting, every box from where the selection started to the playhead."""
        t = self.armed - 1
        if self.sel_anchor is None:
            r = self.region_at(t, self.pos)
            return (t, r[0], r[1]) if r else None
        lo, hi = sorted((self.sel_anchor, self.pos))
        rs = [r for r in self.regions[t] if r[0] <= hi and r[1] > lo]
        if not rs:
            return None
        return t, min(r[0] for r in rs), max(r[1] for r in rs)

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
                        pair[0][1] = pair[1][1]
                        self.regions[t].remove(pair[1])
                        done = True
                else:
                    r = self.region_at(t, f)
                    if r and r[0] + tol < f < r[1] - tol:
                        self._regions_changed(t, entries)
                        right = [f, r[1], self._new_colour(t, f, avoid=(r[2],))]
                        r[1] = f
                        self.regions[t] = sorted(self.regions[t] + [right])
                        done = True
            self._push_undo(entries)
            if not done:
                return None
            return "removed" if joining else "added"

    def copy(self):
        """Copy the selected box(es) to the clipboard as one piece. Returns its length in beats, or None."""
        with self.lock:
            sel = self.selection()
            self.sel_anchor = None
            if not sel:
                return None
            t, a, b = sel
            self.clip = self.tracks[t][a:b].copy()
            return (b - a) / self.frames_per_beat()

    def cut(self):
        """Take the selected box(es) off the tape onto the clipboard, leaving an empty space.
        Returns the length in beats, or None."""
        with self.lock:
            sel = self.selection()
            self.sel_anchor = None
            if not sel:
                return None
            t, a, b = sel
            self.clip = self.tracks[t][a:b].copy()
            entries = [(t, a, self.tracks[t][a:b].copy())]
            self._regions_changed(t, entries)
            self._carve(t, a, b)
            self.tracks[t][a:b] = 0
            self._changed(t, a, b)
            self._push_undo(entries)
            return (b - a) / self.frames_per_beat()

    def drop(self, insert=False):
        """Put the clipboard down on the armed track at the playhead as a new box.
        insert=False covers what's there; insert=True pushes the rest of the track later."""
        with self.lock:
            if self.clip is None:
                return False
            t, a = self.armed - 1, int(self.pos)
            x = self.clip
            n = min(len(x), self.frames - a)
            if n <= 0:
                return False
            entries = []
            self._regions_changed(t, entries)
            if insert:
                entries.append((t, a, self.tracks[t][a:].copy()))
                tail = self.tracks[t][a:self.frames - n].copy()
                self.tracks[t][a + n:] = tail
                self.tracks[t][a:a + n] = x[:n]
                moved = []
                for r in self.regions[t]:
                    if r[1] <= a:
                        moved.append(r)
                    elif r[0] >= a:
                        moved.append([r[0] + n, r[1] + n, r[2]])
                    else:                                   # a box across the playhead splits around the new one
                        moved.append([r[0], a, r[2]])
                        moved.append([a + n, r[1] + n, r[2]])
                self.regions[t] = sorted([r[0], min(r[1], self.frames), r[2]] for r in moved if r[0] < self.frames)
                self._changed(t, a, self.frames)
            else:
                entries.append((t, a, self.tracks[t][a:a + n].copy()))
                self.tracks[t][a:a + n] = x[:n]
                self._changed(t, a, a + n)
            self._add_region(t, a, a + n)
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
            entries = []
            for t in ts:
                entries.append(("volume", t, self.volumes[t]))
                self._regions_changed(t, entries)
                entries.append((t, 0, self.tracks[t][:end].copy()))
            mix = np.zeros(end, np.float32)
            spans = []
            for t in ts:
                mix += self.tracks[t][:end] * self.volumes[t]
                spans += [(r[0], r[1]) for r in self.regions[t]]
            for t in ts:
                self.tracks[t][:end] = 0
                self.regions[t] = []
            self.tracks[dest][:end] = saturate(mix)
            self.volumes[dest] = 1.0
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
                    self.regions[item[1]] = item[2]
                    self.dirty.add(-1)
                    continue
                if item[0] == "volume":
                    self.volumes[item[1]] = item[2]
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
            play = dev.get("playback")
            try:
                name = "hw:CARD=%s,DEV=0" % dev["id"]
                cap = alsaaudio.PCM(type=alsaaudio.PCM_CAPTURE, mode=alsaaudio.PCM_NORMAL, device=name,
                                    rate=rate, channels=dev["capture"]["channels"],
                                    format=getattr(alsaaudio, "PCM_FORMAT_" + cap_fmt),
                                    periodsize=PERIOD, periods=PERIODS)
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
                out[done:done + m] = self._block(x[done:done + m], self.pos, loop)
                self.pos += m
                done += m
                if loop and self.pos >= loop[1] and limit == loop[1]:
                    self.pos = loop[0]
        return out

    def _block(self, x, pos, loop):
        """Play and record one stretch of the tape that doesn't cross the loop end."""
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
        mix = np.zeros(m, np.float32)
        for t in range(TRACKS):
            if (overdub or t not in targets) and t not in self.mutes:
                mix += self.tracks[t][idx] * self.volumes[t]
        out = np.empty((m, 2), np.float32)
        out[:, 0] = out[:, 1] = np.tanh(mix * MIX_GAIN)      # tanh: gentle limiting instead of harsh clipping
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
                    self._save_for_undo(t, a, b)
                    self._rec_region(t, a, b)
                    if overdub:
                        self.tracks[t][a:b] = saturate(self.tracks[t][a:b] + src)
                    else:
                        self.tracks[t][a:b] = src
                    self._update_levels(t, a, b, reset=True)
                    self.dirty.add(t)
        return out

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
        seg = np.abs(self.tracks[t][a:b])
        bins = np.minimum((np.arange(a, b) // fpb).astype(np.int64), len(lv) - 1)
        starts = np.concatenate(([0], np.flatnonzero(np.diff(bins)) + 1))
        idx = bins[starts]
        lv[idx] = np.maximum(lv[idx], np.maximum.reduceat(seg, starts))
