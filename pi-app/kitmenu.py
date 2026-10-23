"""The drums menu: FILE on the drum and sequencer pages.
- SAVE KIT names the drum synth's settings and keeps them; LOAD KIT puts a saved kit back. Kits live in
  ~/console-data/kits/<name>.json, so every song can use them.
- COPY PATTERN copies the sequencer's current pattern onto another one.
- CLEAR P-LOCKS takes every parameter lock off the current pattern.

It looks and works like the project menu (same layout, same naming: the big knob picks the letter,
← / → move, CUT deletes, PLAY is OK, FILE goes back).
"""
import copy
import json
import os

import audio
import menu

KITS = os.path.join(audio.DATA, "kits")
ITEMS = [("SAVE", "menu_new"), ("LOAD", "menu_save"), ("COPY", "menu_load"), ("CLEAR", "menu_settings")]
TEXTS = {"SAVE": "SAVE Kit", "LOAD": "LOAD Kit", "COPY": "COPY Pattern", "CLEAR": "CLEAR P-locks"}
ROWS = 7                                   # saved kits shown at once (the layout's set_value1-7)


def kit_names():
    try:
        files = [f[:-5] for f in os.listdir(KITS) if f.endswith(".json") and not f.startswith(".")]
    except OSError:
        return []
    return sorted(files, key=str.lower)


def kit_path(name):
    return os.path.join(KITS, name + ".json")


class KitMenu(menu.Menu):
    def __init__(self, path, transport):
        super().__init__(path, transport)
        self.open = False
        self.choice = 0
        self.kits = []
        self.pick = 0                      # the kit chosen in the LOAD list
        self.replace = None                # a name that's already saved: PLAY again replaces it
        self.copy_to = 1                   # COPY PATTERN: where to (0-15)
        self.confirm = None                # a copy waiting for PLAY again (it would replace a pattern)

    @property
    def drums(self):
        e = self.engine
        return e.drums if e else None

    def show(self):
        self.open, self.mode, self.msg, self.replace = True, "list", "", None
        self.choice = min(self.choice, len(ITEMS) - 1)
        self.refresh()

    # ------------------------------------------------------------ keys

    @property
    def seq(self):
        return self.engine.seq

    def key(self, name):
        if self.mode in ("load", "copy", "clear") and not isinstance(name, tuple):
            if name in ("UP", "LEFT", "BAR_LEFT"):
                self.turn(-1)
            elif name in ("DOWN", "RIGHT", "BAR_RIGHT"):
                self.turn(1)
            elif name in menu.CONFIRM:
                {"load": self.load, "copy": self.copy_pattern, "clear": self.clear_locks}[self.mode]()
            elif name == "FILE":
                self.mode, self.msg = "list", ""
            self.refresh()
            return
        super().key(name)

    def turn(self, delta):
        if self.mode == "copy":
            self.copy_to = (self.copy_to + (1 if delta > 0 else -1)) % 16
            self.confirm, self.msg = None, ""
            return
        if self.mode == "clear":
            return
        if self.mode == "load":
            if self.kits:
                self.pick = max(0, min(len(self.kits) - 1, self.pick + delta))
            self.msg = ""
            return
        if self.mode == "list":
            self.choice = max(0, min(len(ITEMS) - 1, self.choice + delta))
            self.msg = ""
            return
        self.replace = None
        super().turn(delta)

    def name_key(self, name):
        if name not in menu.CONFIRM:
            self.replace = None
        super().name_key(name)

    def char(self, ch):
        if ch not in ("\r", "\n"):
            self.replace = None
        super().char(ch)

    # ------------------------------------------------------------ actions

    def choose(self):
        if not self.drums:
            self.say("THE DRUM SYNTH ISN'T RUNNING")
            return
        what = ITEMS[self.choice][0]
        if what == "SAVE":
            self.mode = "name"
            taken = {n.lower() for n in kit_names()}
            n = 1
            while ("kit %d" % n) in taken:
                n += 1
            self.name = list("Kit %d" % n)
            self.cursor = len(self.name)
            self.msg, self.replace = "", None
        elif what == "COPY":
            self.mode, self.msg, self.confirm = "copy", "", None
            if self.copy_to == self.seq.current:
                self.copy_to = (self.seq.current + 1) % 16
        elif what == "CLEAR":
            if not self.lock_count()[0]:
                self.say("THIS PATTERN HAS NO P-LOCKS")
                return
            self.mode, self.msg = "clear", ""
        else:
            self.kits = kit_names()
            if not self.kits:
                self.say("NO SAVED KITS YET: SAVE ONE FIRST")
                return
            self.mode, self.msg = "load", ""
            self.pick = min(self.pick, len(self.kits) - 1)

    def create(self):
        """PLAY while naming: save the kit under that name."""
        name = "".join(self.name).strip()
        if not name:
            self.say("GIVE IT A NAME FIRST")
            return
        if name.startswith("."):
            self.say("A NAME CAN'T START WITH A DOT")
            return
        same = [n for n in kit_names() if n.lower() == name.lower()]
        if same and self.replace != name:
            self.replace = name
            self.say("THERE'S ALREADY A KIT CALLED %s: PLAY AGAIN TO REPLACE IT" % name.upper())
            return
        try:
            os.makedirs(KITS, exist_ok=True)
            for old in same:
                if old != name:
                    os.remove(kit_path(old))        # "kit 1" replacing "Kit 1": one file, the new spelling
            tmp = kit_path(name) + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"name": name, "values": self.drums.kit()}, f)
            os.replace(tmp, kit_path(name))
        except OSError as err:
            self.say("COULDN'T SAVE: %s" % str(err).upper())
            return
        self.replace = None
        self.close()
        self.transport.say("KIT SAVED: %s" % name.upper(), 3)

    def load(self):
        if not self.kits:
            return
        name = self.kits[self.pick]
        try:
            with open(kit_path(name)) as f:
                values = json.load(f)["values"]
        except (OSError, ValueError, KeyError, TypeError) as err:
            self.say("COULDN'T LOAD %s: %s" % (name.upper(), str(err).upper()[:40]))
            return
        e = self.engine
        self.drums.load_kit(values)
        with e.lock:
            e.dirty.add(-1)                         # the song keeps the kit it's using
        self.close()
        self.transport.say("KIT LOADED: %s" % name.upper(), 3)

    def copy_pattern(self):
        src, dst = self.seq.current, self.copy_to
        if dst == src:
            self.say("THAT'S THIS PATTERN: PICK ANOTHER")
            return
        if not self.seq.patterns[dst].empty() and self.confirm != dst:
            self.confirm = dst
            self.say("PATTERN %d ISN'T EMPTY: PLAY AGAIN TO REPLACE IT" % (dst + 1))
            return
        with self.seq.lock:
            self.seq.undo_stack.append((dst, copy.deepcopy(self.seq.patterns[dst])))   # key 8 undoes it
            self.seq.patterns[dst] = copy.deepcopy(self.seq.patterns[src])
        self.engine.seq_changed()
        self.close()
        self.transport.say("PATTERN %d COPIED TO %d  (KNOB 10 TO GO THERE)" % (src + 1, dst + 1), 4)

    def lock_count(self):
        steps = [s for ln in self.seq.pattern.lanes for s in ln.steps if s.locks]
        return sum(len(s.locks) for s in steps), len(steps)

    def clear_locks(self):
        self.seq.snapshot()                           # key 8 on the sequencer undoes it
        with self.seq.lock:
            for ln in self.seq.pattern.lanes:
                for st in ln.steps:
                    st.locks.clear()
        self.engine.seq_changed()
        self.close()
        self.transport.say("P-LOCKS CLEARED FROM PATTERN %d" % (self.seq.current + 1), 3)

    # ------------------------------------------------------------ drawing

    def refresh(self):
        s = self.s
        s.set("song", t="DRUMS")
        self.choice = min(self.choice, len(ITEMS) - 1)
        listing, loading = self.mode == "list", self.mode == "load"
        texts = TEXTS
        for label, item in menu.ITEMS:
            s.set(item, t="")
        for i, (label, item) in enumerate(ITEMS):
            on = i == self.choice
            s.set(item, t=texts[label] if listing else "", c=menu.ON if on else menu.OFF,
                  s=menu.SIZE_ON if on else menu.SIZE_OFF, y=self.ys[item] - (2 if on else 0))
        # the LOAD list, in the settings rows
        top = max(0, min(self.pick - ROWS // 2, len(self.kits) - ROWS)) if loading else 0
        for r in range(ROWS):
            i = top + r
            name = self.kits[i] if loading and i < len(self.kits) else ""
            on = loading and i == self.pick
            s.set("set_label%d" % (r + 1), t="")
            s.set("set_value%d" % (r + 1), t=name, c=menu.ON if on else "#F2F3F5", x=640, a="center")
        bar = s.get("menu_bar")
        if bar:
            if loading:
                row = s.get("set_value%d" % (self.pick - top + 1))
                s.set("menu_bar", y=row["y"] + self.bar_offset + 2, h=bar["h"], w=1280 + 180)
            else:
                item = ITEMS[self.choice][1]
                s.set("menu_bar", y=self.ys[item] + self.bar_offset, h=bar["h"] if listing else 0, w=self.bar_w)
        if listing:
            s.set("prompt", t="")
            s.set("name_text", t="")
            hint = "TURN OR ← → TO MOVE     PLAY TO CHOOSE     FILE: BACK TO THE DRUMS"
        elif loading:
            s.set("prompt", t="")
            s.set("name_text", t="")
            hint = "LOAD A KIT     BIG KNOB: PICK ONE     PLAY: LOAD IT     FILE: BACK"
        elif self.mode == "copy":
            dst = self.seq.patterns[self.copy_to]
            s.set("prompt", t="COPY PATTERN %d TO" % (self.seq.current + 1), y=self.prompt_y)
            s.set("name_text", t="PATTERN %d" % (self.copy_to + 1))
            if not self.msg:
                s.set("menu_msg", t="IT'S EMPTY" if dst.empty() else "IT HAS STEPS: COPYING REPLACES THEM")
            hint = "BIG KNOB: PICK A PATTERN     PLAY: COPY     FILE: BACK"
        elif self.mode == "clear":
            locks, steps = self.lock_count()
            s.set("prompt", t="CLEAR EVERY P-LOCK IN PATTERN %d?" % (self.seq.current + 1), y=self.prompt_y)
            s.set("name_text", t="%d LOCK%s ON %d STEP%s" % (locks, "" if locks == 1 else "S", steps, "" if steps == 1 else "S"))
            hint = "PLAY: CLEAR THEM (THE STEPS STAY ON OR OFF)     FILE: BACK"
        else:
            s.set("prompt", t="NAME THIS KIT", y=self.prompt_y)
            s.set("name_text", t="".join(self.name) or " ")
            hint = "BIG KNOB: LETTER   ← →: MOVE   CUT: DELETE   PLAY: SAVE   FILE: CANCEL"
        s.set("menu_hint", t=hint)
        if self.msg or self.mode != "copy":
            s.set("menu_msg", t=self.msg)

    def draw(self, surf):
        self.s.draw(surf)
