"""The project menu: NEW, SAVE, LOAD and SETTINGS. It's the first screen at start-up.

Moving: the big knob, or the arrow keys. Choosing: PLAY, a push on the big
knob, or Enter. FILE (Tab or Esc on a keyboard) goes back to the song.

NEW asks for a name and makes the project's folder straight away. Naming works
like the OP-1: the big knob picks the letter under
the cursor, ← / → move the cursor, CUT deletes a letter. On a keyboard you can
just type.

SETTINGS: the big knob (or ↑ ↓) picks a row, ← / → (or the right-hand
small knob) change it. SHIFT+← / → changes the tempo in small steps.

The look comes from layouts/menu.ui, made with the Screen Designer.
"""
import os
import time

import pygame

import ui
import updater

ITEMS = [("NEW", "menu_new"), ("SAVE", "menu_save"), ("LOAD", "menu_load"), ("SETTINGS", "menu_settings")]
ON, OFF = "#3CCB7F", "#5A606B"
SIZE_ON, SIZE_OFF = 28, 24
LETTERS = " ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
MAX_NAME = 24
CONFIRM = ("PLAY", "ENTER", "HOME")          # HOME is a push on the big knob
SETTINGS = ["SYNC", "TEMPO", "TIMESIG", "FORMAT", "INPUT", "OUTPUT", "UPDATE"]
LABELS = {"SYNC": "SYNC", "TEMPO": "TEMPO", "TIMESIG": "TIME SIGNATURE", "FORMAT": "EXPORT FORMAT", "INPUT": "INPUT", "OUTPUT": "OUTPUT",
          "UPDATE": "SOFTWARE UPDATE"}
FORMAT_NAMES = {"wav": "WAV  (24-bit)", "aiff": "AIFF  (24-bit)", "flac": "FLAC  (24-bit, smaller)",
                "m4a": "M4A  (AAC 256k, smallest)"}


class Menu:
    def __init__(self, path, transport):
        self.s = ui.Screen.load(path)
        self.transport = transport
        self.open = True
        self.choice = 2                       # LOAD, as in the design
        self.mode = "list"                    # "list", "name" or "settings"
        self.row = 0                          # the settings row being changed
        self.name = []
        self.cursor = 0
        self.ys = {n: (self.s.get(n) or {}).get("y", 0) for _, n in ITEMS}
        bar = self.s.get("menu_bar")
        load = self.s.get("menu_load")
        self.bar_offset = (bar["y"] - load["y"]) if bar and load else -4
        self.bar_w = bar["w"] if bar else 920
        self.prompt_y = (self.s.get("prompt") or {}).get("y", 120)
        self.s.after["name_text"] = self.draw_cursor
        self.msg = ""
        self.confirm_new = False              # NEW pressed once on an unsaved song with audio
        self.naming = "new"                   # what the name is for: "new" project or "save" an unnamed one
        self.updater = None                   # made the first time SETTINGS opens
        self.restart = False                  # True once an update is installed: the app restarts
        self.songs = []                       # the LOAD list
        self.pick = 0
        self.confirm = None                   # a delete or open waiting for its second press
        self._done_at = None
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
            elif name[0] == "KNOB" and name[1] == 10 and self.mode == "settings":
                self.change(name[2], fine=name[3])
            elif name[0] == "CHAR":
                self.char(name[1])
            self.refresh()
            return
        if self.mode == "load":
            self.load_key(name)
        elif self.mode == "name":
            self.name_key(name)
        elif self.mode == "settings":
            self.settings_key(name)
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
        if self.mode == "load":
            if self.songs:
                self.pick = max(0, min(len(self.songs) - 1, self.pick + delta))
            self.msg, self.confirm = "", None
            return
        if self.mode == "settings":
            self.row = max(0, min(len(SETTINGS) - 1, self.row + delta))
            self.msg = ""
            return
        if self.mode == "list":
            self.choice = max(0, min(len(ITEMS) - 1, self.choice + delta))
            self.msg = ""
            self.confirm_new = False
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

    def settings_key(self, name):
        if name == "UP":
            self.turn(-1)
        elif name == "DOWN":
            self.turn(1)
        elif name in ("LEFT", "RIGHT"):
            self.change(-1 if name == "LEFT" else 1)
        elif name in ("BAR_LEFT", "BAR_RIGHT", "LOOP_IN", "LOOP_OUT"):     # with shift: small steps
            self.change(-1 if name in ("BAR_LEFT", "LOOP_IN") else 1, fine=True)
        elif name in CONFIRM:
            if SETTINGS[self.row] == "UPDATE":
                self.update_action()
            elif SETTINGS[self.row] in ("SYNC", "TIMESIG", "FORMAT", "INPUT", "OUTPUT"):
                self.change(1)
        elif name == "FILE":
            self.mode, self.msg = "list", ""

    def change(self, delta, fine=False):
        if SETTINGS[self.row] == "UPDATE":
            self.say("PRESS PLAY")
            return
        e = self.engine
        if not e:
            self.say("SETTINGS NEED THE AUDIO ENGINE")
            return
        what = SETTINGS[self.row]
        if what == "SYNC":
            modes = ["external", "internal", "link"]
            e.set_sync_mode(modes[(modes.index(e.sync_mode) + (1 if delta > 0 else -1)) % len(modes)])
            import linksync
            if e.sync_mode == "link" and not linksync.AVAILABLE:
                self.say("LINK NEEDS INSTALLING: RUN pi-app/setup.sh ONCE OVER SSH, THEN RESTART")
            else:
                self.say({"internal": "CONSOLE SENDS MIDI CLOCK, START AND STOP",
                          "external": "CONSOLE FOLLOWS THE OP-XY'S CLOCK, START AND STOP",
                          "link": "TEMPO, BARS AND START / STOP SHARED OVER THE NETWORK"}[e.sync_mode])
        elif what == "FORMAT":
            import audio
            fs = audio.EXPORT_FORMATS
            e.remember("export_format", fs[(fs.index(e.export_format) + (1 if delta > 0 else -1)) % len(fs)])
            self.msg = ""
        elif what == "INPUT":
            choices = e.input_choices()
            if not choices:
                self.say("NO USB AUDIO DEVICE WITH AN INPUT IS PLUGGED IN")
                return
            keys = [k for k, _ in choices]
            now = e.input_choice if e.input_choice in keys else (e.device["id"] if e.device and e.device["id"] in keys else keys[0])
            key, label = choices[(keys.index(now) + (1 if delta > 0 else -1)) % len(choices)] if now in keys else choices[0]
            e.set_input(key, label)
            self.msg = ""
        elif what == "OUTPUT":
            choices = e.output_choices()
            keys = [k for k, _ in choices]
            now = e.output_choice if e.output_choice in keys else ("usb:" + e.device["id"] if e.device and "usb:" + e.device["id"] in keys else "phones")
            key, label = choices[(keys.index(now) + (1 if delta > 0 else -1)) % len(choices)]
            e.set_output(key, label)
            self.say("SHIFT + KNOB 10 CHANGES THE HEADPHONE VOLUME" if key == "phones" else "")
        elif what == "TIMESIG":
            import tape
            sigs = tape.SIGNATURES
            now = tuple(e.time_sig)
            i = sigs.index(now) if now in sigs else sigs.index((4, 4))
            e.set_time_sig(*sigs[(i + (1 if delta > 0 else -1)) % len(sigs)])
            tape.set_signature(*e.time_sig)
            self.msg = ""
        elif what == "TEMPO":
            if self.transport.synced:
                self.say("THE TEMPO COMES FROM THE OP-XY (EXTERNAL SYNC)")
            elif e.playing:
                self.say("STOP FIRST TO CHANGE THE TEMPO")
            else:
                e.set_bpm(round(min(300.0, max(30.0, e.bpm + delta * (0.1 if fine else 1.0))), 1))
                self.msg = ""

    def setting_text(self, what):
        e = self.engine
        if not e:
            return "-"
        if what == "SYNC":
            if e.sync_mode == "link":
                link = self.transport.link
                import linksync
                if not linksync.AVAILABLE:
                    return "LINK  (not installed yet)"
                peers = link.peers if link else 0
                return "LINK  (Ableton Link: %s)" % ("%d other%s" % (peers, "" if peers == 1 else "s") if peers else "nobody else yet")
            return "EXTERNAL  (follow the OP-XY)" if e.sync_mode == "external" else "INTERNAL  (Console leads)"
        if what == "TEMPO":
            return "%.1f BPM%s" % (e.bpm, "  (from the OP-XY)" if self.transport.synced else "")
        if what == "TIMESIG":
            n, d = e.time_sig
            return "%d/%d%s" % (n, d, "  (%s beats of an eighth note)" % n if d == 8 else "")
        if what == "FORMAT":
            return FORMAT_NAMES.get(e.export_format, e.export_format.upper())
        if what == "INPUT":
            return self.input_text()
        if what == "OUTPUT":
            return self.output_text()
        if what == "UPDATE":
            return self.update_text()
        return ""

    def update_action(self):
        u = self.updater
        if u.state in ("idle", "current", "error"):
            u.check()
            self.msg = ""
        elif u.state == "available":
            u.install()
            self.msg = ""
        elif u.state == "done":
            self.restart = True

    def update_text(self):
        u = self.updater
        if u.state == "checking":
            return "CHECKING..."
        if u.state == "current":
            return "UP TO DATE  (%s)" % u.version
        if u.state == "available":
            return "NEW VERSION: PLAY TO INSTALL"
        if u.state == "installing":
            return "INSTALLING..."
        if u.state == "done":
            return "INSTALLED: PLAY TO RESTART" if u.needs_setup else "INSTALLED: RESTARTING..."
        if u.state == "error":
            return "COULDN'T: PLAY TO TRY AGAIN"
        return "%s  \u00b7  PLAY TO CHECK" % u.version

    def update_message(self):
        """The line under the settings, while the update row is chosen."""
        u = self.updater
        if u.state == "available":
            what = u.detail if len(u.detail) <= 60 else u.detail[:57] + "..."
            return "%d CHANGE%s, NEWEST: %s" % (u.count, "" if u.count == 1 else "S", what.upper())
        if u.state == "error":
            return u.detail
        if u.state == "done" and u.needs_setup:
            return "THIS UPDATE NEEDS pi-app/setup.sh RUN ONCE (OVER SSH), THEN PLAY"
        if u.state == "installing":
            return "DON'T TURN OFF THE CONSOLE"
        return ""

    def input_text(self):
        e = self.engine
        key, now = e.input_choice, e.device
        if not key:
            return "%s  (default)" % now["name"].upper() if now else "NOTHING PLUGGED IN"
        chosen = dict(e.input_choices()).get(key, key.upper())
        if now and now["id"] == key:
            return chosen
        if e.input_plugged(key):
            return "%s  (switching...)" % chosen
        if now:
            return "%s  - not found, recording from %s" % (chosen, now["name"].upper())
        return "%s  - not found" % chosen

    def output_text(self):
        e = self.engine
        key = e.output_choice
        names = dict(e.output_choices())
        if key == "phones":
            chosen = "HEADPHONES  (screen jack, %d%%)" % round(e.phones_volume * 100)
        elif key:
            chosen = names.get(key, key[4:].upper())
        else:
            chosen = (e.device["name"].upper() if e.device and e.device.get("playback") else "HEADPHONES") + "  (default)"
        if not e._route_due:
            return chosen                       # the switch hasn't happened yet: give it a moment
        playing = e.output_label
        wanted = "HEADPHONES" if key == "phones" else names.get(key) if key else None
        if wanted and playing and playing != wanted:
            return "%s  - not found, playing on %s" % (chosen.split("  (")[0], playing)
        if wanted and not playing:
            return "%s  - not found" % chosen.split("  (")[0]
        return chosen

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
        e = self.engine
        if what in ("NEW", "SAVE") and not e:
            self.say("PROJECTS NEED THE AUDIO ENGINE")
            return
        if what == "NEW":
            if e.song is None and e.has_audio() and not self.confirm_new:
                self.confirm_new = True
                self.say("THIS SONG ISN'T SAVED. NEW AGAIN THROWS IT AWAY, OR SAVE IT FIRST")
                return
            self.mode = "name"
            self.naming = "new"
            self.name = list(e.next_song_name())
            self.cursor = len(self.name)
            self.msg = ""
        elif what == "SAVE":
            if e.song is None:
                self.mode = "name"
                self.naming = "save"
                self.name = list(e.next_song_name())
                self.cursor = len(self.name)
                self.msg = ""
            else:
                e.save(wait=True)
                self.say("SAVED %s" % e.song.upper())
        elif what == "SETTINGS":
            self.mode, self.row, self.msg = "settings", 0, ""
            if self.updater is None:
                self.updater = updater.Updater()
        elif what == "LOAD":
            if not e:
                self.say("PROJECTS NEED THE AUDIO ENGINE")
                return
            e.save(wait=True)
            self.songs = e.song_names()
            if not self.songs:
                self.say("NO SAVED SONGS YET")
                return
            self.mode, self.msg, self.confirm = "load", "", None
            self.pick = self.songs.index(e.song) if e.song in self.songs else 0

    def load_key(self, name):
        """The LOAD list: big knob or arrows pick, PLAY opens, CUT deletes (press twice), FILE goes back."""
        e = self.engine
        if name in ("LEFT", "UP", "BAR_LEFT"):
            self.turn(-1)
        elif name in ("RIGHT", "DOWN", "BAR_RIGHT"):
            self.turn(1)
        elif name == "FILE":
            self.mode, self.msg = "list", ""
        elif name == "CUT" and self.songs:
            song = self.songs[self.pick]
            if song == e.song:
                self.say("THAT'S THE SONG THAT'S OPEN: OPEN ANOTHER ONE FIRST")
            elif self.confirm != ("delete", song):
                self.confirm = ("delete", song)
                self.say("DELETE %s FOR GOOD? CUT AGAIN TO DELETE IT" % song.upper())
            else:
                e.delete_song(song)
                self.songs = e.song_names()
                self.pick = min(self.pick, max(0, len(self.songs) - 1))
                self.confirm = None
                self.say("DELETED %s" % song.upper())
        elif name in CONFIRM and self.songs:
            song = self.songs[self.pick]
            if song == e.song:
                self.close()
                return
            if e.song is None and e.has_audio() and self.confirm != ("open", song):
                self.confirm = ("open", song)
                self.say("THIS SONG ISN'T SAVED. PLAY AGAIN THROWS IT AWAY, OR SAVE IT FIRST")
                return
            self.transport.open_song(song)
            self.close()

    def create(self):
        """Save the unnamed song with the name typed in."""
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
        if self.naming == "new":
            self.transport.new_song(name)
            self.mode = "list"
            self.close()
            return
        try:
            e.save_as(name)
        except OSError as err:
            self.say("COULDN'T SAVE: %s" % str(err).upper())
            return
        self.transport.s.set("song", t=name)
        self.mode = "list"
        self.say("SAVED AS %s" % name.upper())

    def show(self):
        self.open, self.mode, self.msg, self.confirm_new = True, "list", "", False
        self.refresh()

    def close(self):
        self.open = False
        self.mode = "list"
        self.msg = ""

    # ------------------------------------------------------------ drawing

    def refresh(self):
        s, e = self.s, self.engine
        s.set("song", t=(e.song or "Untitled (not saved yet)") if e else "Demo")
        listing = self.mode == "list"
        for i, (label, item) in enumerate(ITEMS):
            on = i == self.choice
            text = {"NEW": "NEW Project", "SAVE": "SAVE Project", "LOAD": "LOAD Project", "SETTINGS": "SETTINGS"}[label]
            s.set(item, t=text if listing else "", c=ON if on else OFF, s=SIZE_ON if on else SIZE_OFF,
                  y=self.ys[item] - (2 if on else 0))
        settings = self.mode == "settings"
        if self.mode == "load":
            self.refresh_load()
            return
        for i in range(1, len(SETTINGS) + 1):
            s.set("set_value%d" % i, x=660, a="left")
            what = SETTINGS[i - 1] if settings and i <= len(SETTINGS) else None
            on = what is not None and i - 1 == self.row
            s.set("set_label%d" % i, t=LABELS.get(what, ""), c=ON if on else OFF)
            s.set("set_value%d" % i, t=self.setting_text(what) if what else "",
                  c=ON if on else "#F2F3F5")
        bar = s.get("menu_bar")
        if bar:
            if settings:
                row = s.get("set_label%d" % (self.row + 1))
                s.set("menu_bar", y=row["y"] + self.bar_offset + 2, h=bar["h"], w=1280 + 180)
            else:
                item = ITEMS[self.choice][1]
                s.set("menu_bar", y=self.ys[item] + self.bar_offset, h=bar["h"] if listing else 0, w=self.bar_w)
        if listing:
            s.set("prompt", t="")
            s.set("name_text", t="")
            hint = "TURN OR \u2190 \u2192 TO MOVE     PLAY TO CHOOSE     FILE: BACK TO THE SONG"
        elif settings:
            s.set("prompt", t="")                 # 7 rows fill the screen: the hint says where we are
            s.set("name_text", t="")
            hint = "SETTINGS     BIG KNOB: PICK A ROW     \u2190 \u2192: CHANGE IT     FILE: BACK TO THE MENU"
        else:
            s.set("prompt", t="NAME THE NEW PROJECT" if self.naming == "new" else "NAME THIS PROJECT", y=self.prompt_y)
            s.set("name_text", t="".join(self.name) or " ")
            hint = "BIG KNOB: LETTER   \u2190 \u2192: MOVE   CUT: DELETE   PLAY: OK   FILE: CANCEL"
        s.set("menu_hint", t=hint)
        if settings and SETTINGS[self.row] == "UPDATE" and self.updater and not self.msg:
            s.set("menu_msg", t=self.update_message())
        else:
            s.set("menu_msg", t=self.msg)

    def refresh_load(self):
        """The LOAD list: newest first, the open song marked, in the settings rows."""
        s, e = self.s, self.engine
        for label, item in ITEMS:
            s.set(item, t="")
        rows = len(SETTINGS)
        top = max(0, min(self.pick - rows // 2, len(self.songs) - rows))
        for r in range(rows):
            i = top + r
            name = self.songs[i] if i < len(self.songs) else ""
            on = i == self.pick
            when = time.strftime("%b %d  %H:%M", time.localtime(e.song_time(name))).upper() if name else ""
            s.set("set_label%d" % (r + 1), t=when, c=ON if on else OFF)
            s.set("set_value%d" % (r + 1), t=name + ("   (OPEN NOW)" if name and name == e.song else ""),
                  c=ON if on else "#F2F3F5", x=660, a="left")
        bar = s.get("menu_bar")
        if bar and self.songs:
            row = s.get("set_label%d" % (self.pick - top + 1))
            s.set("menu_bar", y=row["y"] + self.bar_offset + 2, h=bar["h"], w=1280 + 180)
        s.set("prompt", t="")
        s.set("name_text", t="")
        s.set("menu_hint", t="LOAD     BIG KNOB: PICK     PLAY: OPEN     CUT: DELETE     FILE: BACK")
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
        if self.mode == "settings":
            self.refresh()                      # the OUTPUT and UPDATE rows change by themselves
            u = self.updater
            if u and u.state == "done" and not u.needs_setup:
                if self._done_at is None:
                    self._done_at = time.monotonic()
                elif time.monotonic() - self._done_at > 2.0:
                    self.restart = True         # give the message a moment, then restart
        self.s.draw(surf)
