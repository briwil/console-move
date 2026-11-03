"""The LFO pages on the Move: after the last settings page of an instrument (Right past it), LFO 1 and LFO 2.
Knobs 1-6: DEST, WAVE, SPEED, DEPTH, PHASE, MODE (see pi-app/lfo.py). Each pattern has its own."""
import knobgate
import lfo

LABELS = ["DEST", "WAVE", "SPEED", "DEPTH", "PHASE", "MODE"]
CHOICE = {0, 1, 2, 5}                         # knobs that pick from a list: several clicks each


class MoveLFO:
    def __init__(self, T):
        self.T = T
        self.tab = None                       # None (the settings pages), 0 (LFO 1) or 1 (LFO 2)

    def active(self):
        T = self.T
        if not T.drum_page:
            self.tab = None
        return self.tab is not None and bool(T.drum_page and not T.seq_page and T.engine and T.engine.drums)

    def arrows(self, way, last_tab):
        """Left / Right on a sound page. Returns True if it moved between the LFO pages / off the settings."""
        T = self.T
        if self.tab is None:
            if way > 0 and T.drum_tab >= last_tab:
                self.tab = 0
                return True
            return False
        self.tab = self.tab + way
        if self.tab < 0:
            self.tab = None
        self.tab = None if self.tab is None else min(lfo.COUNT - 1, self.tab)
        return True

    def lfos(self):
        e = self.T.engine
        return lfo.of(e.seq.pattern)

    def dests(self):
        return lfo.settings_dest(self.T.engine.drums)

    def values(self):
        """[(label, text)] for knobs 1-6."""
        e = self.T.engine
        l = self.lfos()[self.tab]
        d = e.drums
        dest = "OFF"
        if l["dest"] >= 0 and l["dest"] < getattr(d, "param_count", 0):
            dest = ("%s" % d.label(l["dest"]))[:9]
        return [("DEST", dest), ("WAVE", lfo.WAVES[l["wave"]]), ("SPEED", lfo.SPEEDS[l["speed"]][0]),
                ("DEPTH", "%+d%%" % l["depth"]), ("PHASE", "%d%%" % l["phase"]), ("MODE", lfo.MODES[l["mode"]])]

    def is_choice(self, n):
        return (n - 1) in CHOICE

    def knob(self, number, delta, shift):
        if number > len(LABELS):
            return
        e = self.T.engine
        l = self.lfos()[self.tab]
        k = number - 1
        if k in CHOICE:
            way = knobgate.gate(("lfo", k), delta, shift, 3)
            if not way:
                return
            one = 1 if way > 0 else -1
            if k == 0:
                opts = [-1] + self.dests()
                i = opts.index(l["dest"]) if l["dest"] in opts else 0
                l["dest"] = opts[max(0, min(len(opts) - 1, i + one))]
            elif k == 1:
                l["wave"] = max(0, min(len(lfo.WAVES) - 1, l["wave"] + one))
            elif k == 2:
                l["speed"] = max(0, min(len(lfo.SPEEDS) - 1, l["speed"] + one))
            else:
                l["mode"] = max(0, min(len(lfo.MODES) - 1, l["mode"] + one))
        elif k == 3:
            l["depth"] = max(-100, min(100, l["depth"] + delta))
        elif k == 4:
            l["phase"] = max(0, min(100, l["phase"] + delta))
        e.seq_changed()
        self.T.say("LFO %d  %s  %s" % (self.tab + 1, LABELS[k], self.values()[k][1]), 2)
