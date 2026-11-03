"""The engine (audio.Engine) on the Move's sound core: the app keeps using the engine as it always has, and
this keeps the core in step with it.

On the Pi the engine makes the sound itself (its audio thread runs process()). On the Move, Engine.start()
starts a CoreBridge instead. Every few milliseconds it:
  - sends the core what changed: the tape's memory, each track's volume / pan / sends / mute / stereo, the
    boxes, the loop and punch points, which tracks are armed and what they record, the effects, the volume
  - keeps the instrument slots in the core (instruments.Slot) and passes on their settings and hits
  - starts and stops the tape and the sequencers (instruments.Scheduler) when the engine's playing /
    recording flags change, and moves the tape when the engine's pos is moved
  - takes what the core recorded and does the engine's bookkeeping for it: undo, the boxes, the drawn levels
  - copies back where the tape is, the sequencer's clock, the input meters
The core also reads the Move's pads, knobs and buttons; they're queued in engine.move_midi for the app.
"""
import os
import queue
import sys
import threading
import time
import traceback

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import core as K                              # noqa: E402
from core import Core                         # noqa: E402

TICK = 0.004                                  # seconds between looks at the engine
SLOW_EVERY = 10                               # boxes and track settings: every 10th tick (40 ms)


class CoreBridge:
    def __init__(self, engine):
        self.e = engine
        self.core = None
        self.slots = {}                       # slot number -> (machine id, instruments.Slot)
        self.sched = None
        self._stop = False
        self._was_playing = False
        self._was_recording = False
        self._pos_sent = None                 # the pos we last copied into the engine (to see if the app moved it)
        self._tape_ids = None
        self._boxes = {}                      # channel -> what we last sent
        self._tracks = None
        self._arms = None
        self._fx = None
        self._bpm = None
        self._loop = None
        self._overdub = None
        self._monitor = {}
        self._snap = {}                       # channel -> the tape as it was when recording started (for undo)
        self._tick = 0
        self._play_at = 0
        self.rev = self.dly = None
        engine.move_midi = queue.Queue()      # the Move's controls, for the app

    # ------------------------------------------------------------ starting
    def start(self):
        threading.Thread(target=self._run, daemon=True, name="core bridge").start()

    def stop(self):
        self._stop = True

    def _open(self):
        import effects
        from instruments import Scheduler
        e = self.e
        self.core = c = Core()
        e.core = c
        e.output_label = "MOVE"
        e.status = ""
        e.read_ahead = 2 * c.block
        e.device = self._device()
        if effects and effects.AVAILABLE:
            self.rev, self.dly = effects.Reverb(c.rate), effects.Delay(c.rate)
            c.effects(effects._lib.rev_process, self.rev.h, effects._lib.dly_process, self.dly.h)
        self.sched = Scheduler(c)
        boot = getattr(e, "insert_boot", None)
        if boot:
            try:
                boot()                                # the saved INSERT effect (schwung/insertfx.py)
            except Exception as ex:                   # noqa: BLE001
                print("insert effect: %s" % ex)
        import lfo
        self._lfos = lfo.Runner(self.e)
        print("Sound core running: %d Hz, %d frames a cycle" % (c.rate, c.block))

    def _device(self):
        import audio
        d = audio.drum_device(audio.IN_CHANNELS)
        return d or {"id": "MOVE", "name": "Move", "virtual": True,
                     "capture": {"channels": audio.IN_CHANNELS, "format": "FLOAT", "rates": [44100]}}

    def _run(self):
        while not self._stop:
            try:
                if self.core is None:
                    self._open()
                self._step()
            except Exception as ex:                            # keep going: log it, try again shortly
                print("Core bridge:", ex)
                traceback.print_exc()
                time.sleep(0.5)
                if self.core is None:
                    self.e.status = "SOUND CORE: %s" % str(ex).upper()[:60]
                    time.sleep(2)
            time.sleep(TICK)
        if self.core:
            self.core.close()

    # ------------------------------------------------------------ every tick
    def _step(self):
        e, c = self.e, self.core
        self._tick += 1
        slow = self._tick % SLOW_EVERY == 0
        self._sync_tape_memory()
        self._sync_slots()
        if slow or self._tracks is None:
            self._sync_tracks()
            self._sync_boxes()
            self._sync_fx()
        self._sync_arms()
        c.volume(e.phones_volume)
        self._transport()
        for slot in [s for _mid, s in self.slots.values()]:
            slot.flush()
            slot.tick()
        self._auditions()
        try:
            self._lfos.tick()                              # the LFOs move their settings
        except Exception as ex:                            # noqa: BLE001
            print("LFO:", ex)
        if self.sched.playing:
            self.sched.tick(self._plays(), e.frames_per_beat(), on_events=self._hits)
            e.seq_clock = int(self.sched.seq_frame())
        self._take_recorded()
        self._read_back()
        for _frame, msg in c.read_midi():
            e.move_midi.put(msg)

    # ---- the tape's memory, and each track
    def _sync_tape_memory(self):
        e = self.e
        ids = (e.frames,) + tuple(id(a) if a is not None else None for a in e.tracks)
        if ids != self._tape_ids:
            self._tape_ids = ids
            self.core.tape(list(e.tracks), e.frames)
            self._boxes = {}                           # send them all again
            self._tracks = None

    def _sync_tracks(self):
        e = self.e
        now = tuple((round(e.volumes[t], 4), round(e.pans[t], 4), round(e.rev_sends[t], 4), round(e.dly_sends[t], 4),
                     e.audible(t), t in e.stereo) for t in range(len(e.volumes)))
        now += ((not e.inst_view),)
        if now != self._tracks:
            self._tracks = now
            for t, (v, p, r, d, aud, st) in enumerate(now[:-1]):
                self.core.tape_track(t, v, p, r, d, aud, st)
            self.core.tape_heard(not e.inst_view)
        loop = (e.loop_on, e.loop_a, e.loop_b)
        if loop != self._loop:
            self._loop = loop
            self.core.tape_loop(*loop)
            region = e.loop_region()
            self.core.tape_punch(*(region or (0, 0)))      # in / out points set: recording only between them
        if e.rec_mode != self._overdub:
            self._overdub = e.rec_mode
            self.core.tape_overdub(e.rec_mode == "overdub")

    def _sync_boxes(self):
        import audio
        e = self.e
        for ch, rs in enumerate(e.regions):
            key = tuple(tuple(r) for r in rs)
            if self._boxes.get(ch) == key:
                continue
            self._boxes[ch] = key
            shaped = []
            for i, r in enumerate(rs):
                g, fi, fo = audio.box_shape(rs, i)
                shaped.append((r[0], r[1], g, fi, fo))
            self.core.tape_boxes(ch, shaped)

    def _sync_arms(self):
        import audio
        e = self.e
        armed = set(e.record_tracks())
        now = []
        for t in range(len(e.volumes)):
            src = e.source(t) if t in armed else None
            if isinstance(src, tuple):
                pair = (int(src[0]), int(src[1]))
            elif isinstance(src, int):
                pair = (src, src)
            else:
                pair = (-1, -1)
            now.append((t in armed, pair))
        ext = [pair for on, pair in now if on and max(pair) >= audio.EXT_IN]
        want = (1.0, any(p[0] != p[1] for p in ext)) if ext else (0.0, False)
        if want != getattr(self, "_ext", None):
            self._ext = want                              # hear the Move's input while a track records from it
            self.core.ext_monitor(*want)
        if now != self._arms:
            self._arms = now
            for t, (on, pair) in enumerate(now):
                self.core.tape_arm(t, on, pair)

    def _sync_fx(self):
        import effects
        e = self.e
        fx = dict(e.fx) if e.fx else {}
        key = (tuple(sorted(fx.items())), e.bpm)
        if key == self._fx or not fx or self.rev is None:
            return
        self._fx = key
        dly = effects.delay_beats(fx["dly_time"]) * e.frames_per_beat()
        self.rev.set(fx["rev_size"], fx["rev_tone"])
        self.dly.set(dly, fx["dly_feedback"])
        self.core.effect_levels(fx["rev_level"] * effects.REVERB_MAKEUP, fx["dly_level"])
        for _mid, slot in self.slots.values():
            slot.effect_settings(fx["rev_size"], fx["rev_tone"], dly, fx["dly_feedback"])

    # ---- the instrument slots
    def _sync_slots(self):
        e = self.e
        if not e.drums:
            return
        from instruments import Slot
        import audio
        for k, mid in enumerate(e.slots):
            have = self.slots.get(k)
            if (have[0] if have else None) == mid:
                continue
            if have:
                have[1].remove()
                del self.slots[k]
            self._monitor.pop(k, None)               # the new instrument in this slot isn't heard until it's told so
            if mid:
                m = e.drums.get(mid)
                if m is not None:
                    slot = Slot(self.core, m, k)
                    self.slots[k] = (mid, slot)
                    self._fx = None                     # its effects get the settings on the next look
        if e.bpm != self._bpm:
            self._bpm = e.bpm
            for mid, _slot in self.slots.values():
                m = e.drums.get(mid)
                if m is not None:
                    m.set_bpm(e.bpm)
        # who's heard: the slots that sound now, and on the instrument pages the one you're playing
        sounding = set(e.sounding_slots())
        for k, (mid, slot) in self.slots.items():
            g = audio.DRUMS_MONITOR if (k in sounding or (e.inst_view and k == e.slot)) else 0.0
            if self._monitor.get(k) != g:
                self._monitor[k] = g
                self.core.slot_monitor(k, g)

    def _plays(self):
        e = self.e
        out = []
        for k in e.sounding_slots():
            have = self.slots.get(k)
            seq = e.seqs.get(e.slots[k]) if e.slots[k] else None
            if have and seq is not None:
                out.append((have[1], seq))
        return out

    def _hits(self, slot, events, base):
        """The sequencer's hits: lane 1 (the kick) triggers a Ducker-style insert effect on the OTHER instruments;
        on the slot you're looking at, when you'll hear each hit (the screen flashes it)."""
        e = self.e
        now_c, now_t = self.core.now(), time.monotonic()
        mine = next((k for k, v in self.slots.items() if v[1] is slot), None)
        inserts = getattr(e, "insert_fx", None) or {}
        shown = e.slot is not None and self.slots.get(e.slot, (None, None))[1] is slot
        for offset, lane, _vel, _locks in events:
            if lane == 0 and inserts:
                wait = max(0.0, (base + offset - now_c) / self.core.rate)
                for j, ins in list(inserts.items()):
                    if j[0] != mine and ins.h:
                        threading.Timer(wait, ins.midi, (0x90, 36, max(1, min(127, int(_vel))))).start()
            if shown and lane < len(e.seq_hits):
                e.seq_hits[lane] = now_t + (base + offset - now_c) / self.core.rate

    def _auditions(self):
        e = self.e
        if not e._auditions:
            return
        todo, e._auditions = e._auditions, []
        have = self.slots.get(e.slot) if e.slot is not None else None
        if have:
            have[1].play(todo, self.core.now())

    # ---- transport
    def _transport(self):
        e, c = self.e, self.core
        # the app moved the tape (rewind, jump to a box...)
        if self._pos_sent is not None and abs(e.pos - self._pos_sent) > c.block and not e.recording:
            c.transport(K.T_LOCATE, e.pos)
            self._pos_sent = e.pos
        self._rec_at = 0
        if e.playing and not self._was_playing:
            at = (c.now() // c.block + 2) * c.block      # the start of a cycle, a moment from now
            self._rec_at = at                            # recording too (if it starts now): together
            c.transport(K.T_PLAY, e.pos, at=at)
            self._play_at = at
            self.sched.start_frame, self.sched.sent, self.sched.playing = at, 0, True
            e.seq_clock = 0
        elif not e.playing and self._was_playing:
            c.transport(K.T_STOP)
            self.sched.stop()
            self._stop_instruments()
        if e.recording and not self._was_recording:
            self._start_recording()
        elif not e.recording and self._was_recording:
            c.transport(K.T_RECORD_OFF)
            self._finish_recording()
        self._was_playing, self._was_recording = e.playing, e.recording

    def _stop_instruments(self):
        e = self.e
        for mid, _slot in self.slots.values():
            seq = e.seqs.get(mid)
            if seq is not None:
                seq.stop()
            m = e.drums.get(mid) if e.drums else None
            if hasattr(m, "all_off"):
                m.all_off()

    def _start_recording(self):
        """Before the core starts writing: keep a copy of what's about to be recorded over (undo), and put any
        box gain or fades into the audio first when overdubbing (as the engine does), so they don't apply to
        the new recording."""
        e, c = self.e, self.core
        chans = []
        for t in e.record_tracks():
            chans += e.chans(t)
        with e.lock:
            if e.rec_mode == "overdub" and e._rec_undo is not None:
                for ch in chans:
                    for r in list(e.regions[ch]):
                        e._bake(ch, r, e._rec_undo)
            # the core keeps what it writes over, as it goes, in these (np.empty: no copying up front, so
            # recording starts straight away)
            self._snap = {ch: np.empty(e.frames, np.float32) for ch in chans if e.tracks[ch] is not None}
            e._undo_src = self._snap
        for ch, buf in self._snap.items():
            c.tape_undo(ch, buf)
        self._sync_boxes()
        self._sync_arms()
        c.transport(K.T_RECORD, at=self._rec_at)

    def _finish_recording(self):
        time.sleep(2 * self.core.block / self.core.rate)   # the core's last cycle of recording
        self._take_recorded()
        for ch in self._snap:
            self.core.tape_undo(ch, None)
        time.sleep(2 * self.core.block / self.core.rate)   # it has let go of them
        self.e._undo_src = {}
        self._snap = {}

    def _take_recorded(self):
        import audio
        e, c = self.e, self.core
        got = False
        for ch in range(audio.CHANNELS):
            r = c.recorded(ch)
            if not r:
                continue
            a, b = r
            got = True
            with e.lock:
                e._save_for_undo(ch, a, b)
                e._rec_region(ch, a, b)
                e._update_levels(ch, a, b, reset=True)
                e.dirty.add(ch if ch < audio.TRACKS else ch - audio.RIGHT)
        if got:
            self._sync_boxes()                            # the recording's own box, so it plays back right

    def _read_back(self):
        e, c = self.e, self.core
        playing, _recording = c.tape_state()
        if e.playing and not playing and c.now() > self._play_at + 2 * c.block:
            e.playing = e.recording = False              # the core stopped by itself: the end of the tape
        pos = c.tape_pos()
        e.pos = pos
        self._pos_sent = pos
        if self._tick % 8 == 0:
            peaks = c.input_peaks()
            n = min(len(e.in_peaks), len(peaks))
            e.in_peaks[:n] = peaks[:n]
