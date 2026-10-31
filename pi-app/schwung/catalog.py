"""The Schwung sound generators Console can use: where each one's code is, the exact version, and how to
compile it on the Pi (from its own build script, without the Move's cross-compiler or Docker).

kind: "drums" (16 pads on MIDI notes 36-51, like a Move drum rack; the drum sequencer plays them) or
"synth" (played with notes). {out} is where the build writes dsp.so.
"""
import hashlib
import json

FIRST_PAD = 36                       # a Move drum rack: pad 1 is note 36 ... pad 16 note 51

MODULES = [
    # ---------------------------------------------------------------- drum machines
    {"id": "forge", "title": "FORGE", "kind": "drums", "license": "MIT",
     "repo": "filliformes/forge-move", "commit": "fc69e18d24035764bb0cb58b066d50b25baa7d3c",
     "json": "src/module.json",
     "build": [["gcc", "-O2", "-ffast-math", "-shared", "-fPIC", "-w", "-o", "{out}", "src/dsp/forge.c",
                "-lm", "-lpthread"]]},
    {"id": "weirddreams", "title": "WEIRD DREAMS", "kind": "drums", "license": "MIT",
     "repo": "filliformes/weird-dreams-move", "commit": "eabd121d1ffd5d98c077633edeb18df90f85124b",
     "json": "src/module.json",
     "build": [["gcc", "-O2", "-ffast-math", "-shared", "-fPIC", "-w", "-o", "{out}",
                "src/dsp/weird_dreams.c", "-lm", "-lpthread"]]},
    {"id": "libpo32", "title": "LIBPO32", "kind": "drums", "license": "none stated",
     "repo": "mestela/schwung-libpo32", "commit": "4125e2989df1747a66f56388eb0b5bd7e1310079",
     "json": "src/module.json", "files": ["src/kits"],
     "build": [["gcc", "-O3", "-ffast-math", "-shared", "-fPIC", "-w", "-DNDEBUG", "-Isrc/dsp",
                "src/dsp/po32_drum.c", "src/dsp/po32.c", "src/dsp/po32_synth.c",
                "src/dsp/po32_patch_import.c", "-o", "{out}", "-lm", "-lpthread"]]},
    {"id": "cw78", "title": "CW-78", "kind": "drums", "license": "GPL-3.0",
     "repo": "athousanddetails/schwung-cw-78", "commit": "108bae6924f2dc153003b573373bf874faf19953",
     "json": "src/module.json", "lanes": 14,
     "voice_prefixes": ["bd", "sd", "rs", "hh", "cy", "ma", "cl", "hb", "lb", "lc", "cb", "tb", "gu", "mb"],
     "pads": ["Bass Drum", "Snare", "Rimshot", "Hi-Hat", "Cymbal", "Maracas", "Claves", "Hi Bongo",
              "Lo Bongo", "Lo Conga", "Cowbell", "Tambourine", "Guiro", "Metal Beat"],
     "build": [["g++", "-O3", "-std=c++14", "-shared", "-fPIC", "-w", "-Isrc", "-Isrc/dsp", "-Isrc/host",
                "src/dsp/cr78_plugin.cpp", "src/dsp/cr78_engine.cpp", "-o", "{out}", "-lm"]]},
    {"id": "simian", "title": "SIMIAN", "kind": "drums", "license": "GPL-3.0",
     "repo": "legsmechanical/schwung-simian", "commit": "647c2bb8b867e922f5240dec4b40a513cbb61b9e",
     "json": "src/module.json",
     "build": [["g++", "-O3", "-std=c++14", "-shared", "-fPIC", "-w", "-Wno-comment", "-Isrc/dsp",
                "src/dsp/simian_plugin.cpp", "-o", "{out}", "-lm"]]},
]

BY_ID = {m["id"]: m for m in MODULES}


def recipe_version(m):
    """A short tag of how a module is built, so changing its recipe here builds it again."""
    return ":" + hashlib.sha1(json.dumps([m["build"], m["json"], m.get("files", [])]).encode()).hexdigest()[:8]
