"""The SAMPLE BROWSER: choosing a sampler drum's sample by folders instead of one long list.

Push the big wheel on a sampler drum's page to open it. Then: the wheel turns through the list,
push the wheel to open a folder / choose a sample, "< UP" goes up, Back goes up a folder (and leaves from the top).
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
        rel = os.path.relpath(self.folder, self.root) if self.folder != self.root else os.path.basename(self.root)
        return ("SAMPLE %d  %s" % (self.voice + 1, rel.upper()))[:27]

    # ------------------------------------------------------------ opening and leaving
    def open(self, drums, voice):
        files = drums.files
        if not files:
            self.T.say("NO SAMPLES FOUND", 3)
            return
        if self._files is not files or self._tree is None or len(files) != len(self._files or ()):
            self._build(files)
        self.drums, self.voice = drums, voice
        self.orig = drums.get_param(voice * 8)
        cur = files[self.orig - 1] if 0 < self.orig <= len(files) else None
        self.folder = self.root                        # always from the top of the samples
        self._list()
        self.pick = 0
        self.active = True

    def close(self, keep):
        self._cancel()
        if not keep:
            self.drums.set_param(self.voice * 8, self.orig)
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
            self.drums.set_param(self.voice * 8, val)
            self.T.engine.hit(self.voice, 110)
            self.active = False

    def back(self):
        if self.folder != self.root:
            self.folder_up()
        else:
            self.close(False)

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
        if kind != "file":
            return

        def go():
            if self.active:
                self.drums.set_param(self.voice * 8, val)
                self.T.engine.hit(self.voice, 110)
        self._timer = threading.Timer(0.3, go)
        self._timer.daemon = True
        self._timer.start()
