"""Two-piece keycaps for Kailh Choc V1 switches, 24 keys, Lato numbers.

  body  rounded plate 17.5 x 16.5 x 1.4 mm with the two Choc prongs underneath (1.2 x 3.0 mm, 5.7 mm apart,
        same as make_keycaps.py) and three round holes. Printed FLAT on the bed (plate face down, prongs up).
  top   the round dome (14.4 mm, 1.0 mm thick) with three round pegs under it that press into the holes.
        The number / icon is let into the dome 0.4 mm. Printed face down, so the symbol is the first layers.
  symbol the number / icon alone, for a second colour.
Total height 2.4 mm, same as the old one-piece caps. Reuses the helpers (font, icons, mesher, 3MF writer) from
make_split_keycaps.py.   Run:  python3 make_choc_keycaps.py   (writes ./out-choc/)"""
import os
import numpy as np
from scipy import ndimage
import make_split_keycaps as s
import make_keycaps as old

OUT = os.path.join(s.HERE, "out-choc")
X, Y, R, N, RES = s.X, s.Y, s.R, s.N, s.RES
q = lambda v: np.round(v / RES) * RES

PLATE_T = 1.4                    # body plate thickness
DOME_T = 1.0                     # dome thickness (sits on the plate)
TOP = PLATE_T + DOME_T           # 2.4 total, like the old caps
DOME_R = 7.2
DOME_CHAMFER = 0.5
FLAT_R = 6.5                     # symbols stay inside this
INLAY = 0.4
PEG_LEN = PLATE_T - 0.2          # pegs stop 0.2 short of the underside
HOLES = [(0.0, 0.0, 1.8), (0.0, 4.5, 1.0), (0.0, -4.5, 1.0)]       # x, y, radius (nominal hole size)
CLEAR = {"tight": 0.05, "standard": 0.10, "loose": 0.15}           # peg is this much smaller per side
PRONG_W, PRONG_L, PRONG_SEP, PRONG_LEN = 1.2, 3.0, 5.7, 3.0

ICON_MAX = 3.6                   # icons are shrunk so their longest side is this (digits are 2.6 mm tall)
ICON_MIN_STROKE = 0.4            # thin lines are thickened back up to about this

_digit_or_icon = s.key_mask
def key_mask(key):
    m = _digit_or_icon(key)
    if isinstance(key, int):
        return m
    ii, jj = np.nonzero(m)
    ci, cj = (ii.min() + ii.max()) / 2, (jj.min() + jj.max()) / 2
    k = min(1.0, ICON_MAX / (max(ii.max() - ii.min(), jj.max() - jj.min() + 1) * RES))
    # sample the big icon at 1/k spacing around the centre (a shrink about the centre of its bounding box)
    c = N / 2 - 0.5
    mat = np.diag([1 / k, 1 / k])
    off = np.array([ci, cj]) - mat @ np.array([c, c])
    small = ndimage.affine_transform(m.astype(float), mat, offset=off, order=1) > 0.5
    r = max(0, int(round((ICON_MIN_STROKE - 0.75 * k) / 2 / RES)))
    if r:
        small = ndimage.binary_dilation(small, structure=ndimage.generate_binary_structure(2, 1), iterations=r)
    return s.clean(small)
s.key_mask = key_mask

def disk(cx, cy, r):
    return np.hypot(X - cx, Y - cy) <= r

def plate_mask():
    hx, hy = old.CAP_W / 2 - old.CORNER_R, old.CAP_H / 2 - old.CORNER_R
    qx, qy = np.abs(X) - hx, np.abs(Y) - hy
    d = old.CORNER_R - (np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0))
    return d > 0

def body_layers():
    b = np.full((N, N), np.nan); t = np.full((N, N), np.nan)
    m = plate_mask()
    for cx, cy, r in HOLES:
        m &= ~disk(cx, cy, r)
    b[m], t[m] = 0.0, PLATE_T
    for sx in (-PRONG_SEP / 2, PRONG_SEP / 2):
        p = (np.abs(X - sx) < PRONG_W / 2) & (np.abs(Y) < PRONG_L / 2) & m
        b[p] = -PRONG_LEN
    assert ndimage.label(~np.isnan(b))[1] == 1
    return [(b, t)]

def top_layers(key, fit, recess=True):
    b = np.full((N, N), np.nan); t = np.full((N, N), np.nan)
    dome = R <= DOME_R
    b[dome] = PLATE_T
    t[dome] = q(TOP - np.maximum(0, DOME_CHAMFER - (DOME_R - R[dome])))
    c = CLEAR[fit]
    for cx, cy, r in HOLES:
        peg = disk(cx, cy, r - c)
        b[peg] = PLATE_T - PEG_LEN
        tip = peg & ~ndimage.binary_erosion(peg, iterations=2)
        b[tip] = PLATE_T - PEG_LEN + 0.2
    if recess and key is not None:
        t[s.key_mask(key) & (R <= FLAT_R)] = q(TOP - INLAY)
    return [(b, t)]

def symbol_layers(key):
    b = np.full((N, N), np.nan); t = np.full((N, N), np.nan)
    m = s.key_mask(key) & (R <= FLAT_R)
    b[m], t[m] = q(TOP - INLAY), TOP
    return [(b, t)]

def main():
    os.makedirs(OUT, exist_ok=True)
    bv, bf, vol = s.make(body_layers(), "body")
    bv = s.flipped(bv, PLATE_T)
    s.write_stl(os.path.join(OUT, "keycap-body.stl"), bv, bf, "choc keycap body (flat face down)")
    print(f"body {len(bf)} tris {vol:.1f} mm3, z {bv[:,2].min():.2f}-{bv[:,2].max():.2f}")
    for fit in CLEAR:
        row = []
        for i, key in enumerate(s.KEYS24, 1):
            name = s.key_name(i, key)
            tv, tf, vt = s.make(top_layers(key, fit), "top " + name)
            nv, nf, vn = s.make(symbol_layers(key), "sym " + name)
            tv, nv = s.flipped(tv, TOP), s.flipped(nv, TOP)
            s.write_stl(os.path.join(OUT, f"top-{name}-{fit}.stl"), tv, tf, f"top {name}")
            if fit == "standard":
                s.write_stl(os.path.join(OUT, f"symbol-{name}.stl"), nv, nf, f"symbol {name}")
            row.append((name, (tv, tf), (nv, nf), 3 if key == "record" else 1))
        print(fit, "ok")
        s.write_3mf(os.path.join(OUT, f"console-keycap-tops-{fit}.3mf"), f"Choc keycap tops ({fit})", None, row, 0, cols=6)
    s.write_3mf(os.path.join(OUT, "console-keycap-bodies.3mf"), "Choc keycap bodies", (bv, bf), [], 24, cols=6)
    blank = []
    for fit in CLEAR:
        tv, tf, _ = s.make(top_layers(None, fit, recess=False), "blank")
        blank.append((f"blank top {fit}", (s.flipped(tv, TOP), tf), None, 1))
    s.write_3mf(os.path.join(OUT, "fit-test.3mf"), "Choc keycap fit test", (bv, bf), blank, 3)

if __name__ == "__main__":
    main()
    print("done")
