"""The project menu: NEW, SAVE, LOAD and SETTINGS. It's the first screen at start-up.

Moving: the big knob, or the arrow keys. Choosing: PLAY, a push on the big
knob, or Enter. FILE (Tab or Esc on a keyboard) goes back to the song.

Naming a new project works like the OP-1: the big knob picks the letter under
the cursor, ← / → move the cursor, CUT deletes a letter. On a keyboard you can
just type.

The look comes from layouts/menu.ui, made with the Screen Designer.
"""
import os

import pygame

import ui

ITEMS = [("NEW", "menu_new"), ("SAVE", "menu_save"), ("LOAD", "menu_load"), ("SETTINGS", "menu_settings")]
ON, OFF = "#3CCB7F", "#5A606B"
SIZE_ON, SIZE_OFF = 28, 24
LETTERS = " ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
MAX_NAME = 24
CONFIRM = ("PLAY", "ENTER", "HOME")          # HOME is a push on the big knob


class Menu:
    def __init__(self, path, transport):
        self.s = ui.Screen.load(path)
        self.transport = transport
        self.open = True
        self.choice = 2                       # LOAD, as in the design
        self.mode = "list"                    # "list" or "name"
        self.name = []
        self.cursor = 0
        self.ys = {n: (self.s.get(n) or {}).get("y", 0) for _, n in ITEMS}
        bar = self.s.get("menu_bar")
        load = self.s.get("menu_load")
        self.bar_offset = (bar["y"] - load["y"]) if bar and load else -4
        self.s.after["name_text"] = self.draw_cursor
        self.msg = ""
        self.refresh()

    @property
    def engine(self):
        return self.transport.engine

    @property
    def text_input(self):
        """True while typing a name, so the keyboard sends letters instead of commands."""
        return self.open and self.mode == "name"

    def say(self, text):
        self.msg = text

    # ------------------------------------------------------------ keys

    def key(self, name):
        if isinstance(name, tuple):
            if name[0] == "KNOB" and name[1] == 11:
                self.turn(name[2])
            elif name[0] == "CHAR":
                self.char(name[1])
            self.refresh()
            return
        if self.mode == "name":
            self.name_key(name)
        elif name in ("LEFT", "UP", "BAR_LEFT"):
            self.turn(-1)
        elif name in ("RIGHT", "DOWN", "BAR_RIGHT"):
            self.turn(1)
        elif name in CONFIRM:
            self.choose()
        elif name == "FILE":
            self.close()
        self.refresh()

    def turn(self, delta):
        if self.mode == "list":
            self.choice = max(0, min(len(ITEMS) - 1, self.choice + delta))
            self.msg = ""
            return
        # naming: change the letter under the cursor
        if self.cursor >= len(self.name):
            if len(self.name) >= MAX_NAME:
                return
            self.name.append("A")              # a new letter starts at A
            if delta > 0:
                delta -= 1
            else:
                delta += 1
        i = LETTERS.find(self.name[self.cursor])
        self.name[self.cursor] = LETTERS[(max(i, 0) + delta) % len(LETTERS)]

    def name_key(self, name):
        if name in ("LEFT", "BAR_LEFT"):
            self.cursor = max(0, self.cursor - 1)
        elif name in ("RIGHT", "BAR_RIGHT"):
            self.cursor = min(len(self.name), self.cursor + 1)
        elif name == "CUT":
            self.delete(self.cursor if self.cursor < len(self.name) else self.cursor - 1)
        elif name in CONFIRM:
            self.create()
        elif name == "FILE":
            self.mode = "list"
            self.msg = ""

    def char(self, ch):
        if self.mode != "name":
            return
        if ch in ("\r", "\n"):
            self.create()
        elif ch in ("\x1b", "\t"):
            self.mode, self.msg = "list", ""
        elif ch in ("\x7f", "\b"):
            self.delete(self.cursor - 1)
        elif ch.isprintable() and ch not in '/\\:*?"<>|' and len(self.name) < MAX_NAME:
            self.name.insert(self.cursor, ch)
            self.cursor += 1

    def delete(self, i):
        if 0 <= i < len(self.name):
            del self.name[i]
            if i < self.cursor:
                self.cursor -= 1
            self.cursor = min(self.cursor, len(self.name))

    # ------------------------------------------------------------ actions

    def choose(self):
        what = ITEMS[self.choice][0]
        if what == "NEW":
            if not self.engine:
                self.say("NEW PROJECTS NEED THE AUDIO ENGINE")
                return
            self.mode = "name"
            self.name = list(self.engine.next_song_name())
            self.cursor = len(self.name)
            self.msg = ""
        else:
            self.say("%s COMES NEXT" % what)

    def create(self):
        name = "".join(self.name).strip()
        e = self.engine
        if not name:
            self.say("GIVE IT A NAME FIRST")
            return
        if name.startswith("."):
            self.say("A NAME CAN'T START WITH A DOT")
            return
        if e.song_exists(name):
            self.say("THERE'S ALREADY A PROJECT CALLED %s" % name.upper())
            return
        self.transport.new_song(name)
        self.mode = "list"
        self.close()

    def show(self):
        self.open, self.mode, self.msg = True, "list", ""
        self.refresh()

    def close(self):
        self.open = False
        self.mode = "list"
        self.msg = ""

    # ------------------------------------------------------------ drawing

    def refresh(self):
        s, e = self.s, self.engine
        s.set("song", t=e.song if e else "Demo")
        listing = self.mode == "list"
        for i, (label, item) in enumerate(ITEMS):
            on = i == self.choice
            text = {"NEW": "NEW Project", "SAVE": "SAVE Project", "LOAD": "LOAD Project", "SETTINGS": "SETTINGS"}[label]
            s.set(item, t=text if listing else "", c=ON if on else OFF, s=SIZE_ON if on else SIZE_OFF,
                  y=self.ys[item] - (2 if on else 0))
        bar = s.get("menu_bar")
        if bar:
            item = ITEMS[self.choice][1]
            s.set("menu_bar", y=self.ys[item] + self.bar_offset, h=bar["h"] if listing else 0)
        if listing:
            s.set("prompt", t="")
            s.set("name_text", t="")
            hint = "TURN OR ← → TO MOVE     PLAY TO CHOOSE     FILE: BACK TO THE SONG"
        else:
            s.set("prompt", t="NAME THE NEW PROJECT")
            s.set("name_text", t="".join(self.name) or " ")
            hint = "BIG KNOB: LETTER   ← →: MOVE   CUT: DELETE   PLAY: MAKE IT   FILE: CANCEL"
        s.set("menu_hint", t=hint)
        s.set("menu_msg", t=self.msg)

    def draw_cursor(self, surf):
        """A block under the letter being changed, OP-1 style."""
        if self.mode != "name":
            return
        it = self.s.get("name_text")
        font = self.s.font(it["f"], it["wt"], it["s"])
        text = "".join(self.name) or " "
        full = font.size(text)[0]
        x0 = it["x"] - full // 2 if it["a"] == "center" else it["x"] - full if it["a"] == "right" else it["x"]
        before = font.size("".join(self.name[:self.cursor]))[0] if self.cursor else 0
        if self.cursor < len(self.name):
            w = max(6, font.size(self.name[self.cursor])[0])
        else:
            w = font.size("A")[0]
        y = it["y"] + font.get_height() + 4
        pygame.draw.rect(surf, ui.rgb(ON), (x0 + before, y, w, 4))

    def draw(self, surf):
        self.s.draw(surf)
