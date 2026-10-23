"""Ableton Link: tempo, bar position and start/stop shared over the network with Ableton Live, phone apps
and anything else that has Link. SETTINGS > MIDI SYNC > LINK turns it on.

- Tempo: while the tape is stopped, Console takes Link's tempo, and a tempo you set goes out to everyone.
  While it plays the tape keeps its tempo (its audio can't stretch); stop to take a new one.
- Start and stop: PLAY starts everyone, on the next bar; someone else starting or stopping starts or
  stops Console. Recording armed with RECORD while stopped starts on that bar too.
- Bars line up: the tape starts on a Link bar line (Link's "quantum" is Console's bar length), and the
  audio thread nudges the tape by a frame now and then to stay locked to Link's clock.

Needs the aalink package (setup.sh installs it); without it, LINK just says so.
"""
import asyncio
import math
import threading
import time

try:
    import aalink
    AVAILABLE = True
except Exception:
    aalink = None
    AVAILABLE = False

POLL = 0.004                  # seconds between looks at Link
NUDGE_AT = 64                 # frames of drift before the tape is nudged back (about 1.5 ms)
JUMP_AT = 0.25                # beats: more than this off and it's a jump (a loop, a move), not drift


class LinkSync:
    def __init__(self, engine):
        self.engine = engine
        self.link = None
        self.peers = 0
        self.message = ""                  # something for the screen, once
        self._want_play = None             # True / False: PLAY or stop pressed here, to tell everyone
        self._waiting = False              # Link is playing; the tape starts on the next bar
        self._map = None                   # (tape beat, link beat) at the same moment, while playing
        self._drift = 0.0
        self._last = None                  # (tape beat, link beat) at the last look
        self._sent_bpm = None
        self._seen_tempo = None
        self._tempo_warned = False
        self._joined = 0.0
        if AVAILABLE:
            threading.Thread(target=self._thread, daemon=True, name="link").start()

    @property
    def on(self):
        return AVAILABLE and self.engine.sync_mode == "link"

    def request_play(self, playing):
        """PLAY / stop pressed on Console while Link is on."""
        self._want_play = bool(playing)

    # ------------------------------------------------------------ the Link thread

    def _thread(self):
        try:
            asyncio.run(self._main())
        except Exception as e:
            print("Link stopped:", e)

    async def _main(self):
        e = self.engine
        self.link = link = aalink.Link(e.bpm)
        link.start_stop_sync_enabled = True
        while True:
            await asyncio.sleep(POLL)
            if not self.on:
                if link.enabled:
                    link.enabled = False
                    self._map, self._waiting, self.peers = None, False, 0
                    e.link_nudge = 0
                continue
            if not link.enabled:
                link.enabled = True
                self._joined = time.monotonic()      # see who's there before deciding whose tempo wins
                self._sent_bpm = self._seen_tempo = None
            link.quantum = e.bar_beats()
            self.peers = link.num_peers
            self._tempo(link)
            self._start_stop(link)
            self._follow(link)

    def _tempo(self, link):
        e = self.engine
        tempo = link.tempo
        if self._sent_bpm is None:
            if time.monotonic() - self._joined < 1.5:
                return
            if link.num_peers == 0:
                link.tempo = e.bpm                 # on our own: our tempo is the session's
                self._sent_bpm = self._seen_tempo = e.bpm
                return
            self._sent_bpm = e.bpm                 # joining others: take theirs (below)
        if e.bpm != self._sent_bpm and not e.playing:
            link.tempo = e.bpm                     # changed here: tell everyone
            self._sent_bpm = self._seen_tempo = e.bpm
            return
        if abs(tempo - (self._seen_tempo or tempo)) > 0.005 or abs(tempo - e.bpm) > 0.005:
            self._seen_tempo = tempo
            if not e.playing:
                if e.set_bpm(round(tempo, 2)):
                    self._sent_bpm = e.bpm
                    self.message = "TEMPO %.1f BPM FROM LINK" % tempo
                self._tempo_warned = False
            elif not self._tempo_warned and abs(tempo - e.bpm) > 0.05:
                self._tempo_warned = True
                self.message = "LINK TEMPO IS NOW %.1f: STOP TO TAKE IT" % tempo

    def _start_stop(self, link):
        e = self.engine
        if self._want_play is not None:
            want, self._want_play = self._want_play, None
            if link.playing != want:
                link.playing = want
            if not want:
                self._waiting = False
        playing = link.playing
        if playing and not e.playing and not self._waiting and self._map is None:
            self._waiting = True                   # start the tape on the next bar line
            q = link.quantum
            self._start_at = math.ceil(link.beat / q - 1e-6) * q
            if link.beat - (self._start_at - q) < 0.05:
                self._start_at -= q                # right on a bar line already: go now
        if self._waiting:
            if not playing:
                self._waiting = False
            elif link.beat >= self._start_at:
                self._waiting = False
                late = link.beat - self._start_at   # we looked a moment after the bar line
                bar = e.bar_beats()                 # from the start of the playhead's bar, so the bars line up
                start = math.floor(e.beats() / bar + 1e-6) * bar + late
                e.sync_start(start)
                self._map = (start - late, self._start_at)
                self._drift, self._last = 0.0, None
        if not playing and e.playing and self._map is not None:
            e.sync_stop()
        if not e.playing:
            self._map = None
            e.link_nudge = 0

    def _follow(self, link):
        """Keep the playing tape on Link's beat: nudge it a frame per block while it's off."""
        e = self.engine
        if self._map is None or not e.playing:
            return
        if abs(link.tempo - e.bpm) > 0.005:
            e.link_nudge = 0                       # different tempos: can't lock (see _tempo)
            return
        tape0, link0 = self._map
        lb, tb = link.beat, e.beats()
        expected = tape0 + (lb - link0)
        if self._last is not None:
            # the tape jumped (round the loop, or moved): keep the phase, take the new place
            moved = (tb - self._last[0]) - (lb - self._last[1])
            if abs(moved) > JUMP_AT:
                self._map = (tb - (lb - link0), link0)
                self._last, self._drift = (tb, lb), 0.0
                return
        self._last = (tb, lb)
        off = (tb - expected) * e.frames_per_beat()          # frames: + the tape is ahead
        self._drift = 0.95 * self._drift + 0.05 * off         # the tape moves in blocks: smooth it
        if self._drift > NUDGE_AT:
            e.link_nudge = -1
        elif self._drift < -NUDGE_AT:
            e.link_nudge = 1
        elif abs(self._drift) < NUDGE_AT / 4:
            e.link_nudge = 0
