"""Choosing an insert effect: one picture at a time, like choosing an instrument (the wheel turns, push chooses,
Back leaves). The pictures are in move/fximg/<id>.txt."""


class FxPicker:
    img_dir = "fximg"

    def __init__(self, T):
        self.T = T
        self.active = False
        self.choices = []                  # [(id, title)]
        self.pick = 0
        self.ins = None

    def open(self, ins):
        import catalog
        self.ins = ins
        self.choices = [("none", "NO EFFECT")] + [(f["id"], f["title"].upper()) for f in catalog.FX]
        self.pick = ins.index if 0 <= ins.index < len(self.choices) else 0
        self.active = True

    def turn(self, delta):
        if self.choices:
            self.pick = (self.pick + (1 if delta > 0 else -1)) % len(self.choices)

    def push(self):
        ins = self.ins
        ins.choose(self.pick)
        self.active = False
        song = getattr(ins, "slot", 0) == -1                 # SONG INSERT 1 / 2: its copies start on every instrument
        if song:
            self.T.songfx_sync()
        self.T._insfx_save()
        self.T.say("%sINSERT %d: %s%s" % ("SONG " if song else "", ins.pos + 1, ins.name(),
                                          (" (" + ins.error + ")") if ins.error else ""), 2)

    def back(self):
        self.active = False
