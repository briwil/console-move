#!/usr/bin/env python3
"""Turn an animation made anywhere (a GIF, a folder of PNGs, or a video) into one the Move can play.

    python3 convert.py my.gif   opening            a GIF: each frame's own duration is kept
    python3 convert.py frames/  opening --fps 12   a folder of PNG / JPG (in name order), fixed speed
    python3 convert.py clip.mov opening --fps 10   a video (needs ffmpeg)

The result is the folder the Screen Designer makes, ready for the Move app (it reads hex/ and the holds):

    opening/animation.json   the frames and how long each is held (in ticks of 1 / fps second)
    opening/hex/NNN.txt      each frame as the Move reads it: 64 rows of 32 hex digits, top row first
    opening/frames/NNN.png   each frame as a picture (white = lit)
    opening/sheet.png        every frame on one picture, to look it over

Frames that repeat one after another become one frame held longer. Needs Pillow (pip install pillow).

Options:
    --fps N         ticks a second (default 10; a GIF's durations are rounded to this)
    --threshold N   0-255: lighter than this is lit (default 128)
    --dither        for pictures with greys: a pattern of dots, not a hard cut
    --invert        swap lit and dark
    --fit           keep the picture's shape (black bars) instead of stretching it to 128 x 64
    --name TEXT     the animation's name in animation.json
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageSequence

W, H = 128, 64


def load(path, fps):
    """[(PIL image, ticks)] from a GIF, a folder of pictures or a video."""
    if os.path.isdir(path):
        files = sorted(p for p in glob.glob(os.path.join(path, "*")) if p.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")))
        if not files:
            sys.exit("No pictures in %s" % path)
        return [(Image.open(p).convert("RGBA"), 1) for p in files]
    ext = os.path.splitext(path)[1].lower()
    if ext == ".gif":
        im = Image.open(path)
        out = []
        for fr in ImageSequence.Iterator(im):
            ms = fr.info.get("duration", 1000 // fps) or 1000 // fps
            out.append((fr.convert("RGBA"), max(1, round(ms * fps / 1000.0))))
        return out
    if not shutil.which("ffmpeg"):
        sys.exit("A video needs ffmpeg (brew install ffmpeg). Or export a GIF or PNG frames instead.")
    tmp = tempfile.mkdtemp(prefix="moveanim")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-vf", "fps=%g" % fps, os.path.join(tmp, "%04d.png")], check=True)
    files = sorted(glob.glob(os.path.join(tmp, "*.png")))
    out = [(Image.open(p).convert("RGBA"), 1) for p in files]
    for _im, _t in out:
        _im.load()
    shutil.rmtree(tmp, ignore_errors=True)
    return out


def to_bits(im, threshold, dither, invert, fit):
    """A 64 x 128 list of rows of 0 / 1 (1 = lit)."""
    bg = Image.new("RGBA", im.size, (0, 0, 0, 255))
    bg.alpha_composite(im)                                  # transparent counts as black
    g = bg.convert("L")
    if fit:
        g.thumbnail((W, H), Image.LANCZOS)
        canvas = Image.new("L", (W, H), 0)
        canvas.paste(g, ((W - g.width) // 2, (H - g.height) // 2))
        g = canvas
    elif g.size != (W, H):
        g = g.resize((W, H), Image.LANCZOS)
    if dither:
        b = g.convert("1")                                  # Floyd-Steinberg
        bits = [[1 if b.getpixel((x, y)) else 0 for x in range(W)] for y in range(H)]
    else:
        bits = [[1 if g.getpixel((x, y)) >= threshold else 0 for x in range(W)] for y in range(H)]
    if invert:
        bits = [[1 - v for v in row] for row in bits]
    return bits


def hex_rows(bits):
    return ["%032x" % int("".join(str(v) for v in row), 2) for row in bits]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("out", help="the folder to make (its name is used as the animation's name too)")
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--threshold", type=int, default=128)
    ap.add_argument("--dither", action="store_true")
    ap.add_argument("--invert", action="store_true")
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--name", default=None)
    a = ap.parse_args()

    frames = []                                             # [bits, ticks], repeats merged
    for im, ticks in load(a.source, a.fps):
        bits = to_bits(im, a.threshold, a.dither, a.invert, a.fit)
        if frames and frames[-1][0] == bits:
            frames[-1][1] += ticks
        else:
            frames.append([bits, ticks])

    os.makedirs(os.path.join(a.out, "hex"), exist_ok=True)
    os.makedirs(os.path.join(a.out, "frames"), exist_ok=True)
    name = a.name or os.path.basename(os.path.abspath(a.out)).capitalize()
    doc = {"format": "move-anim", "version": 1, "width": W, "height": H,
           "meta": {"name": name, "param": name, "drive": "time", "ending": "once", "fps": a.fps,
                    "note": "%d frames, converted from %s" % (len(frames), os.path.basename(a.source.rstrip("/")))},
           "frames": []}
    pics = []
    for n, (bits, ticks) in enumerate(frames, 1):
        rows = hex_rows(bits)
        with open(os.path.join(a.out, "hex", "%03d.txt" % n), "w") as f:
            f.write("\n".join(rows) + "\n")
        pic = Image.new("L", (W, H))
        pic.putdata([255 if v else 0 for row in bits for v in row])
        pic.save(os.path.join(a.out, "frames", "%03d.png" % n))
        pics.append(pic)
        doc["frames"].append({"hold": ticks, "objs": [], "bitmap": rows})   # (the designer's shapes: none; the picture is the bitmap)
    with open(os.path.join(a.out, "animation.json"), "w") as f:
        json.dump(doc, f, indent=1)
    cols = 4
    rows_n = (len(pics) + cols - 1) // cols
    sheet = Image.new("L", (cols * (W * 2 + 8) + 8, rows_n * (H * 2 + 8) + 8), 45)
    for i, p in enumerate(pics):
        r, c = divmod(i, cols)
        sheet.paste(p.resize((W * 2, H * 2), Image.NEAREST), (8 + c * (W * 2 + 8), 8 + r * (H * 2 + 8)))
    sheet.save(os.path.join(a.out, "sheet.png"))
    total = sum(t for _b, t in frames)
    print("%d frames (from %s), %.1f seconds at %g ticks a second -> %s/" % (len(frames), a.source, total / a.fps, a.fps, a.out))


if __name__ == "__main__":
    main()
