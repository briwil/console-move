"""An instrument's INSERT effect: one Schwung audio effect (Tapescam, Ducker...) on that instrument's sound.

Every instrument (slot) has its own. It is picked on the FX key's third page (after REVERB and DELAY) for the
instrument you're on. Knob 1 picks the effect (NONE, Tapescam, Ducker...), knobs 2-4 change its first three settings.
The effect runs in the sound core (core_slot_insert) through libschwunghost's sh_fx_process, on the instrument's
direct sound, before the tape can record it: so what the tape records from that instrument (KIT inputs) has the
effect in it, and nothing is added to the tape afterwards.
"""
import ctypes
import json
import os

import catalog
import modules
import store

CHOICES_NONE = "NONE"


def _params(folder, jsonname):
    """[(key, label, lo, hi, default, step, options)] from the module's module.json (ui_hierarchy and chain_params)."""
    try:
        info = json.load(open(os.path.join(folder, jsonname)))
    except (OSError, ValueError):
        return []
    found, seen = [], set()

    def add(p):
        if not isinstance(p, dict) or "key" not in p or p["key"] in seen:
            return
        t = p.get("type", "float")
        if t not in ("float", "int", "enum", "bool"):
            return
        seen.add(p["key"])
        opts = p.get("options") or ([] if t != "bool" else ["off", "on"])
        lo, hi = float(p.get("min", 0)), float(p.get("max", 1))
        if opts:
            lo, hi = 0.0, float(len(opts) - 1)
        step = float(p.get("step", 1 if t in ("int", "enum", "bool") else 0.05)) or 0.05
        found.append((p["key"], str(p.get("short_name") or p.get("name") or p["key"]).upper()[:12], lo, hi,
                      float(p.get("default", lo)) if not opts or isinstance(p.get("default"), (int, float)) else 0.0,
                      step, opts))

    caps = info.get("capabilities", {})
    for p in caps.get("chain_params", []) or []:
        add(p)
    for lvl in (caps.get("ui_hierarchy", {}).get("levels", {}) or {}).values():
        for p in lvl.get("params", []) or []:
            add(p)
    return found


class Insert:
    def __init__(self, core=None, slot=0, pos=0):
        self.core = core
        self.slot = slot
        self.pos = pos                      # 0: the first insert effect, 1: the second
        self.index = 0                      # 0 = none, else 1 + position in catalog.FX
        self.h = None
        self.params = []
        self.values = {}
        self.error = ""
        self.lib = None

    def choices(self):
        return [CHOICES_NONE] + [f["title"].upper() for f in catalog.FX]

    def name(self):
        return self.choices()[self.index] if self.index < len(self.choices()) else CHOICES_NONE

    def _lib(self):
        if self.lib is None:
            self.lib = modules.host()
        return self.lib

    def choose(self, index):
        index = max(0, min(len(catalog.FX), index))
        if index == self.index and (self.h or index == 0):
            return
        self.unload()
        self.index = index
        if index == 0:
            return
        f = catalog.FX[index - 1]
        folder = os.path.join(store.MODULES_DIR, f["id"])
        lib = self._lib()
        if lib is None:
            self.error = "THE MODULE HOST ISN'T BUILT"
            self.index = 0
            return
        h = lib.sh_fx_open(os.path.join(folder, f["dsp"]).encode(), folder.encode(), b"")
        if not h:
            self.error = lib.sh_error().decode(errors="replace")[:60] or "COULDN'T START"
            self.index = 0
            return
        self.h, self.error = h, ""
        self.params = (_params(folder, f.get("json", "module.json")) or self._runtime_params(h))[:8]
        self.values = {p[0]: p[4] for p in self.params}
        for p in self.params:
            self._send(p[0])
        if self.core is not None:
            self.core.set_slot_insert(self.slot, self.pos, ctypes.cast(lib.sh_fx_process, ctypes.c_void_p).value, h)

    def _runtime_params(self, h):
        """Effects that don't list their settings in module.json: ask the effect itself (chain_params)."""
        try:
            buf = ctypes.create_string_buffer(8192)
            if self._lib().sh_fx_get(h, b"chain_params", buf, 8192) < 0:
                return []
            info = {"capabilities": {"chain_params": json.loads(buf.value.decode(errors="replace") or "[]")}}
        except (ValueError, OSError, AttributeError, ctypes.ArgumentError):
            return []
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            json.dump(info, open(os.path.join(tmp, "m.json"), "w"))
            return _params(tmp, "m.json")

    def unload(self):
        if self.core is not None:
            self.core.set_slot_insert(self.slot, self.pos, 0, 0)
        if self.h and self.lib:
            self.lib.sh_fx_close(self.h)
        self.h, self.params, self.values = None, [], {}

    def _send(self, key):
        p = next((q for q in self.params if q[0] == key), None)
        if p is None or not self.h:
            return
        v = self.values[key]
        text = p[6][int(v)] if p[6] else ("%d" % v if p[5] >= 1 and float(v).is_integer() else "%.3f" % v)
        self._lib().sh_fx_set(self.h, key.encode(), str(text).encode())

    def modulate(self, slot, value):
        """An LFO moves setting `slot` (0-7) to this value, without changing the one kept on the page."""
        if slot >= len(self.params) or not self.h:
            return
        key = self.params[slot][0]
        self._lib().sh_fx_set(self.h, key.encode(), ("%.4f" % value).encode())

    def restore(self, slot):
        """An LFO lets go of setting `slot`: back to the page's value."""
        if slot < len(self.params) and self.h:
            self._send(self.params[slot][0])

    def knob(self, slot, delta):
        """slot 0-7 -> the effect's first eight settings."""
        if slot >= len(self.params) or not self.h:
            return
        key, _, lo, hi, _, step, _o = self.params[slot]
        self.values[key] = max(lo, min(hi, round((self.values[key] + delta * step) / step) * step))
        self._send(key)

    def text(self, slot):
        if slot >= len(self.params):
            return ("", "")
        key, label, lo, hi, _, step, opts = self.params[slot]
        v = self.values.get(key, 0)
        shown = opts[int(v)].upper() if opts else ("%d%%" % round(v * 100) if hi <= 1.0 else "%g" % v)
        return (label, shown)

    def midi(self, b0, b1, b2):
        """For effects that listen to notes (the Ducker's trigger)."""
        if self.h:
            self._lib().sh_fx_midi(self.h, b0, b1, b2)

    # a saved song's choice
    def to_json(self):
        return {"fx": catalog.FX[self.index - 1]["id"] if self.index and self.h else "", "values": self.values}

    def from_json(self, d):
        ids = [f["id"] for f in catalog.FX]
        if d and d.get("fx") in ids:
            self.choose(ids.index(d["fx"]) + 1)
            for k, v in (d.get("values") or {}).items():
                if k in self.values:
                    self.values[k] = v
                    self._send(k)
