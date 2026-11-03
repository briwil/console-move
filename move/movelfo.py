"""The LFO pages on the Move: after the last settings page of an instrument (Right past it), LFO 1 and LFO 2.
Step buttons: tap = that step of the LFO rests, hold + knob 2/4 = its own WAVE/DEPTH. Knobs 1-6: DEST, WAVE, SPEED, DEPTH, PHASE, MODE (see pi-app/lfo.py). Each pattern has its own."""
import knobgate
import lfo

LABELS = ["DEST", "WAVE", "SPEED", "DEPTH", "PHASE", "MODE"]
CHOICE = {0, 1, 2, 5}                         # knobs that pick from a list: several clicks each


class MoveLFO:
    def __init__(self, T):
        self.T = T
        self.tab = None                       # None (the settings pages), 0 (LFO 1) or 1 (LFO 2)
        self.held = {}                        # step buttons held: step -> True once a knob has used it

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

    def step(self, n, down):
        """A step button (1-16): a tap mutes / unmutes that step of the LFO; hold it and turn DEPTH (knob 4) or WAVE
        (knob 2) to give the step its own."""
        i = n - 1
        if down:
            self.held[i] = False
            return
        used = self.held.pop(i, True)
        if not used:
            steps = self.lfos()[self.tab].setdefault("steps", {})
            st = steps.setdefault(i, {})
            if st.get("mute"):
                st.pop("mute")
            else:
                st["mute"] = 1
            if not st:
                steps.pop(i, None)
            self.T.engine.seq_changed()
            self.T.say("LFO %d STEP %d %s" % (self.tab + 1, n, "RESTS" if st.get("mute") else "PLAYS"), 2)

    def step_lights(self):
        steps = self.lfos()[self.tab].get("steps", {})
        out = []
        for i in range(16):
            st = steps.get(i)
            out.append(127 if i in self.held else 0 if st and st.get("mute") else 45 if st else 20)
        return out

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
        if self.held:
            return n == 2
        return (n - 1) in CHOICE

    def knob(self, number, delta, shift):
        if number > len(LABELS):
            return
        e = self.T.engine
        l = self.lfos()[self.tab]
        k = number - 1
        if self.held and k in (1, 3):                 # a held step: its own WAVE / DEPTH
            steps = self.lfos()[self.tab].setdefault("steps", {})
            way = knobgate.gate(("lfostep", k), delta, shift, 3) if k == 1 else delta
            if not way:
                return
            for i in self.held:
                self.held[i] = True
                st = steps.setdefault(i, {})
                if k == 1:
                    st["wave"] = max(0, min(len(lfo.WAVES) - 1, st.get("wave", l["wave"]) + (1 if way > 0 else -1)))
                else:
                    st["depth"] = max(-100, min(100, st.get("depth", l["depth"]) + way))
                shown = lfo.WAVES[st["wave"]] if k == 1 else "%+d%%" % st["depth"]
            e.seq_changed()
            self.T.say("STEP %s  %s  %s" % (",".join(str(i + 1) for i in sorted(self.held)), LABELS[k], shown), 2)
            return
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
