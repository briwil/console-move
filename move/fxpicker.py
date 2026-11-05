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
        import insertfx
        self.ins = ins
        song = getattr(ins, "slot", 0) == -1                 # a song insert: not the effects too heavy for it
        skip = insertfx.SONG_SKIP if song else ()
        # (id, title, its number in the catalog): the list can leave some out, so the number is kept with each
        self.choices = [("none", "NO EFFECT", 0)] + [(f["id"], f["title"].upper(), i)
                                                     for i, f in enumerate(catalog.FX, 1) if f["id"] not in skip]
        self.pick = next((k for k, c in enumerate(self.choices) if c[2] == ins.index), 0)
        self.active = True

    def turn(self, delta):
        if self.choices:
            self.pick = (self.pick + (1 if delta > 0 else -1)) % len(self.choices)

    def push(self):
        ins = self.ins
        ins.choose(self.choices[self.pick][2])
        self.active = False
        song = getattr(ins, "slot", 0) == -1                 # SONG INSERT 1 / 2: its copies start on every instrument
        if song:
            self.T.songfx_sync()
        self.T._insfx_save()
        self.T.say("%sINSERT %d: %s%s" % ("SONG " if song else "", ins.pos + 1, ins.name(),
                                          (" (" + ins.error + ")") if ins.error else ""), 2)

    def back(self):
        self.active = False
