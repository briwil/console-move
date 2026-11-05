"""The SAMPLE BROWSER: choosing a sampler drum's sample by folders instead of one long list.

Push the big wheel on a sampler drum's page to open it. It first asks which of the drum's two samples (SAMPLE 1
or SAMPLE 2; BLEND mixes them). Then: the wheel turns through the list, push the wheel to open a folder / choose
a sample, "< UP" goes up, Back goes up a folder (from the top: back to SAMPLE 1 / 2, and Back again leaves).
The highlighted sample is played as you land on it; leaving with Back puts the old sample back."""
import os
import threading


class SampleBrowser:
    def __init__(self, T):
        self.T = T
        self.active = False
        self._tree = None
        self._files = None
        self.root = "/"
        self.folder = "/"
        self.entries = []          # [(label, kind, value)]: kind "up" / "dir" (value: folder path) / "file" (value: index)
        self.pick = 0
        self.voice = 0
        self.which = 0             # the drum's first (0) or second (1) sample
        self.stage = "which"       # "which": SAMPLE 1 / SAMPLE 2; "files": the folders
        self.param = 0
        self.orig = 0
        self._timer = None

    # ------------------------------------------------------------ the folders
    def _build(self, files):
        self._files = files
        tree = {}
        dirs = [os.path.dirname(p) for p in files]
        self.root = os.path.commonpath(dirs) if dirs else "/"
        for i, p in enumerate(files):
            d = os.path.dirname(p)
            tree.setdefault(d, {"dirs": set(), "files": []})["files"].append((os.path.basename(p), i + 1))
            while d != self.root and len(d) > len(self.root):
                parent = os.path.dirname(d)
                tree.setdefault(parent, {"dirs": set(), "files": []})["dirs"].add(d)
                d = parent
        self._tree = tree

    def _list(self):
        node = self._tree.get(self.folder, {"dirs": (), "files": []})
        rows = []
        if self.folder != self.root:
            rows.append(("< UP", "up", os.path.dirname(self.folder)))
        for d in sorted(node["dirs"], key=str.lower):
            rows.append(("> " + os.path.basename(d).upper(), "dir", d))
        for name, idx in sorted(node["files"], key=lambda x: x[0].lower()):
            rows.append((os.path.splitext(name)[0].upper(), "file", idx))
        self.entries = rows

    def title(self):
        if self.stage == "which":
            return "DRUM %d: WHICH SAMPLE?" % (self.voice + 1)
        rel = os.path.relpath(self.folder, self.root) if self.folder != self.root else os.path.basename(self.root)
        return ("D%d S%d  %s" % (self.voice + 1, self.which + 1, rel.upper()))[:27]

    def _which_list(self):
        d = self.drums
        names = [d.sample_name(self.voice, w) if hasattr(d, "sample_name") else "" for w in (0, 1)]
        self.entries = [("SAMPLE %d  %s" % (w + 1, names[w] if names[w] != "EMPTY" else "-"), "which", w)
                        for w in (0, 1)]

    # ------------------------------------------------------------ opening and leaving
    def open(self, drums, voice):
        files = drums.files
        if not files:
            self.T.say("NO SAMPLES FOUND", 3)
            return
        if self._files is not files or self._tree is None or len(files) != len(self._files or ()):
            self._build(files)
        self.drums, self.voice = drums, voice
        self.stage = "which"
        self._which_list()
        self.pick = 0
        self.active = True

    def _choose_which(self, which):
        import sampler
        self.which, self.stage = which, "files"
        self.param = sampler.sample_param(self.voice, which)
        self.orig = self.drums.get_param(self.param)
        self.blend = sampler.BLEND + self.voice          # while browsing, hear only the sample being chosen
        self.blend_orig = self.drums.get_param(self.blend)
        self.drums.set_param(self.blend, 127 if which else 0)
        self.folder = self.root                        # always from the top of the samples
        self._list()
        self.pick = 0

    def _unsolo(self):
        if self.stage == "files" and getattr(self, "blend", None) is not None:
            self.drums.set_param(self.blend, self.blend_orig)

    def close(self, keep):
        self._cancel()
        if not keep and self.stage == "files":
            self.drums.set_param(self.param, self.orig)
        self._unsolo()
        self.active = False

    # ------------------------------------------------------------ controls
    def turn(self, delta):
        if not self.entries:
            return
        self.pick = (self.pick + (1 if delta > 0 else -1)) % len(self.entries)
        self._preview()

    def push(self):
        if not self.entries:
            return
        _l, kind, val = self.entries[self.pick]
        if kind == "which":
            self._choose_which(val)
            return
        if kind in ("up", "dir"):
            came = self.folder
            self.folder = val
            self._list()
            self.pick = 0
            if kind == "up":
                for k, (_l2, k2, v2) in enumerate(self.entries):
                    if v2 == came:
                        self.pick = k
        else:
            self._cancel()
            self.drums.set_param(self.param, val)
            self._unsolo()
            self.T.engine.hit(self.voice, 110)
            self.active = False
            if self.which and self.blend_orig == 0:
                self.T.say("SAMPLE 2 IN. BLEND (KNOB 8) IS ALL ON SAMPLE 1: TURN IT TO HEAR IT", 4)

    def back(self):
        if self.stage == "which":
            self.close(False)
        elif self.folder != self.root:
            self.folder_up()
        else:                                          # the top of the samples: back to SAMPLE 1 / 2
            self._cancel()
            self.drums.set_param(self.param, self.orig)
            self._unsolo()
            self.stage = "which"
            self._which_list()
            self.pick = self.which

    def folder_up(self):
        came = self.folder
        self.folder = os.path.dirname(self.folder)
        self._list()
        self.pick = 0
        for k, (_l, kind, val) in enumerate(self.entries):
            if val == came:
                self.pick = k

    # ------------------------------------------------------------ hearing it
    def _cancel(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _preview(self):
        self._cancel()
        _l, kind, val = self.entries[self.pick]
        if kind != "file" or self.stage != "files":
            return

        def go():
            if self.active and self.stage == "files":
                self.drums.set_param(self.param, val)
                self.T.engine.hit(self.voice, 110)
        self._timer = threading.Timer(0.3, go)
        self._timer.daemon = True
        self._timer.start()
