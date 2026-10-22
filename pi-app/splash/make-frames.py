#!/usr/bin/env python3
"""Turn the loader renders (splash/loader-source/load_*.png, 1280 x 400) into the start-up frames.

Each frame is put on black, cropped to where anything ever moves, turned to the screen's native
portrait way, and reduced to 256 colours (looks the same on black, and keeps the start-up files small,
since they're loaded before anything else). The last render matches the first, so it's left out to
loop smoothly. If you change the crop box, change the 32 in console.script to match.
Needs python3-pil. Run from anywhere: python3 make-frames.py, then ../splash-setup.sh again.
"""
import glob
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
BOX = (0, 32, 1190, 368)              # left, top, right, bottom in the 1280 x 400 picture

renders = sorted(glob.glob(os.path.join(HERE, "loader-source", "load_*.png")))[:-1]
os.makedirs(os.path.join(HERE, "frames"), exist_ok=True)
for old in glob.glob(os.path.join(HERE, "frames", "loader-*.png")):
    os.remove(old)
for i, path in enumerate(renders):
    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", im.size, (0, 0, 0, 255))
    bg.alpha_composite(im)
    part = bg.crop(BOX).convert("RGB").rotate(270, expand=True)
    part.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(
        os.path.join(HERE, "frames", "loader-%d.png" % i), optimize=True)
print("%d frames written. Set FRAMES = %d in console.script if that changed." % (len(renders), len(renders)))
