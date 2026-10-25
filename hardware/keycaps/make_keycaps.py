#!/usr/bin/env python3
"""Generate Kailh Choc V1 keycaps with engraved icons for the Console control board.

Each keycap is built on a 0.05 mm grid as a 2.5D solid (every grid cell has a bottom
and top height), then meshed into a watertight STL. No CAD library needed.

Outputs (in ./out):
  stl-nominal/NN-name.stl   prongs 1.2 x 3.0 mm (Kailh nominal)
  stl-loose/NN-name.stl     prongs 1.1 x 2.9 mm (if the nominal ones are too tight)
  inlays/NN-name-inlay.stl  icon-only part, for two-colour printers (optional)
  fit-test-nominal.stl / fit-test-loose.stl   blank caps to test stem fit first
  preview.png
"""
import os, struct
import numpy as np
from matplotlib.path import Path
from matplotlib.textpath import TextPath
from matplotlib.font_manager import FontProperties

RES = 0.05                     # grid size, mm
CAP_W, CAP_H = 17.5, 16.5      # fits 18 x 17 mm Choc spacing with 0.5 mm gaps
CORNER_R = 1.2
TOP = 2.4                      # cap plate thickness
CHAMFER = 0.6                  # 45 degree chamfer on the top edge
ENGRAVE = 0.6                  # icon depth
PRONG_SEP, PRONG_LEN = 5.7, 3.0
STROKE = 0.75                  # icon line width

NX, NY = int(round(CAP_W / RES)), int(round(CAP_H / RES))
xs = -CAP_W / 2 + (np.arange(NX) + 0.5) * RES
ys = -CAP_H / 2 + (np.arange(NY) + 0.5) * RES
X, Y = np.meshgrid(xs, ys, indexing="ij")

# ------------------------------------------------------------------ 2D shape helpers (return bool masks)
def seg_dist(ax, ay, bx, by):
    px, py = X - ax, Y - ay
    dx, dy = bx - ax, by - ay
    t = np.clip((px * dx + py * dy) / (dx * dx + dy * dy + 1e-12), 0, 1)
    return np.hypot(px - t * dx, py - t * dy)

def line(a, b, w=STROKE):
    return seg_dist(a[0], a[1], b[0], b[1]) <= w / 2

def polyline(pts, w=STROKE, closed=False):
    m = np.zeros_like(X, bool)
    seq = list(pts) + ([pts[0]] if closed else [])
    for a, b in zip(seq, seq[1:]):
        m |= line(a, b, w)
    return m

def disk(c, r):
    return np.hypot(X - c[0], Y - c[1]) <= r

def ring(c, r, w=STROKE):
    return np.abs(np.hypot(X - c[0], Y - c[1]) - r) <= w / 2

def rect(x0, y0, x1, y1):
    return (X >= x0) & (X <= x1) & (Y >= y0) & (Y <= y1)

def poly(pts):
    p = Path(pts + [pts[0]])
    return p.contains_points(np.c_[X.ravel(), Y.ravel()]).reshape(X.shape)

def text(s, height=8.0):
    fp = FontProperties(family="DejaVu Sans", weight="bold")
    tp = TextPath((0, 0), s, size=10, prop=fp)
    polys = tp.to_polygons()
    allv = np.vstack(polys)
    x0, x1 = allv[:, 0].min(), allv[:, 0].max()
    y0, y1 = allv[:, 1].min(), allv[:, 1].max()
    k = height / (y1 - y0)
    pts = np.c_[X.ravel(), Y.ravel()]
    m = np.zeros(len(pts), bool)
    for pg in polys:                       # even-odd: holes in 4, 6, 8 stay open
        pg = (pg - [(x0 + x1) / 2, (y0 + y1) / 2]) * k
        m ^= Path(pg).contains_points(pts)
    return m.reshape(X.shape)

# ------------------------------------------------------------------ icons (mm, origin at key centre, y up)
def icon_audio():
    m = np.zeros_like(X, bool)
    for x, h in zip(np.linspace(-3.9, 3.9, 7), [1.0, 2.4, 3.8, 2.0, 4.2, 2.8, 1.4]):
        m |= line((x, -h), (x, h), 0.8)
    return m

def icon_midi():
    m = polyline([(-4.5, -3.2), (4.5, -3.2), (4.5, 3.2), (-4.5, 3.2)], 0.6, closed=True)
    for x in (-2.7, -0.9, 2.7):                       # black keys sit on these divisions
        m |= rect(x - 0.55, -0.2, x + 0.55, 3.2)
        m |= line((x, -3.2), (x, -0.2), 0.5)
    m |= line((0.9, -3.2), (0.9, 3.2), 0.5)
    return m

def icon_fx():
    return poly([(1.4, 4.6), (-2.6, -0.4), (-0.3, -0.4), (-1.5, -4.6), (2.7, 1.0), (0.4, 1.0)])

def icon_file():
    m = polyline([(-3.0, -4.2), (3.0, -4.2), (3.0, 2.4), (1.2, 4.2), (-3.0, 4.2)], closed=True)
    m |= polyline([(1.2, 4.2), (1.2, 2.4), (3.0, 2.4)], 0.6)
    for y in (0.6, -1.2, -3.0 + 0.6):
        m |= line((-1.6, y), (1.6, y), 0.6)
    return m

def icon_splice():
    m = line((-4.6, 0), (4.6, 0)) & ~disk((-1.7, 0), 1.2) & ~disk((1.7, 0), 1.2)
    return m | ring((-1.7, 0), 1.2) | ring((1.7, 0), 1.2)

def icon_cut():
    m = ring((-1.7, -2.9), 1.2) | ring((1.7, -2.9), 1.2)
    m |= line((-0.9, -1.9), (2.3, 4.4), 0.85) | line((0.9, -1.9), (-2.3, 4.4), 0.85)
    return m

def arrow(tip, direction, length, head=2.3, w=0.85):
    d = np.array(direction, float); d /= np.linalg.norm(d)
    n = np.array([-d[1], d[0]])
    tip = np.array(tip, float)
    tail = tip - d * length
    m = line(tail, tip - d * 0.3, w)
    for s in (1, -1):
        m |= line(tip, tip - d * head + s * n * head, w)
    return m

def icon_lift():
    return arrow((0, 4.0), (0, 1), 6.6) | line((-3.6, -3.6), (3.6, -3.6), 0.85)

def icon_drop():
    return arrow((0, -1.8), (0, -1), 5.8) | line((-3.6, -3.8), (3.6, -3.8), 0.85)

def icon_loop():
    d = seg_dist(-2.2, 0.0, 2.2, 0.0)
    m = np.abs(d - 2.4) <= STROKE / 2
    m &= ~((Y > 0) & (X > -0.2) & (X < 1.4))           # gap for the arrowhead
    return m | poly([(-0.2, 3.6), (1.8, 2.4), (-0.2, 1.2)])

def bracket(side):
    s = 1 if side == "right" else -1
    x = 3.6 * s
    return polyline([(x - 2.2 * s, 3.6), (x, 3.6), (x, -3.6), (x - 2.2 * s, -3.6)], 0.8)

def icon_import():
    return bracket("right") | arrow((2.0, 0), (1, 0), 6.4, head=2.0)

def icon_export():
    return bracket("left") | arrow((4.6, 0), (1, 0), 6.0, head=2.0)

def icon_record():
    return disk((0, 0), 3.2)

def icon_shift():
    return polyline([(0, 4.3), (4.1, 0.2), (1.8, 0.2), (1.8, -4.0), (-1.8, -4.0), (-1.8, 0.2), (-4.1, 0.2)],
                    0.75, closed=True)

def icon_play():
    m = line((-3.8, -2.9), (-3.8, 2.9), 0.9) | line((-2.3, -2.9), (-2.3, 2.9), 0.9)
    return m | poly([(-0.6, 3.3), (4.4, 0.0), (-0.6, -3.3)])

def icon_left():
    return arrow((-4.4, 0), (-1, 0), 8.6, head=2.5)

def icon_right():
    return arrow((4.4, 0), (1, 0), 8.6, head=2.5)

KEYS = [  # (file name, icon builder, switch reference)
    ("audio", icon_audio, "SW1"), ("midi", icon_midi, "SW2"), ("fx", icon_fx, "SW3"), ("file", icon_file, "SW4"),
    ("splice", icon_splice, "SW5"), ("cut", icon_cut, "SW6"), ("lift", icon_lift, "SW7"), ("drop", icon_drop, "SW8"),
    ("loop", icon_loop, "SW9"), ("import", icon_import, "SW10"), ("export", icon_export, "SW11"),
    ("record", icon_record, "SW12"), ("shift", icon_shift, "SW13"), ("play", icon_play, "SW14"),
    ("left", icon_left, "SW15"), ("right", icon_right, "SW16"),
] + [(f"track{i}", (lambda i=i: text(str(i))), f"SW{16 + i}") for i in range(1, 9)]

def clean(m):
    """Fill diagonal-only pixel contacts so the mesh stays manifold."""
    m = m.copy()
    while True:
        a, b_, c, d = m[:-1, :-1], m[1:, :-1], m[:-1, 1:], m[1:, 1:]
        x1 = a & d & ~b_ & ~c
        x2 = b_ & c & ~a & ~d
        if not (x1.any() or x2.any()):
            return m
        m[1:, :-1] |= x1; m[:-1, 1:] |= x1
        m[:-1, :-1] |= x2; m[1:, 1:] |= x2

# ------------------------------------------------------------------ cap body
def rounded_rect_inside_dist():
    hx, hy = CAP_W / 2 - CORNER_R, CAP_H / 2 - CORNER_R
    qx, qy = np.abs(X) - hx, np.abs(Y) - hy
    outside = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0)
    return CORNER_R - outside          # >0 inside, distance to the edge

DIST = rounded_rect_inside_dist()
INSIDE = DIST > 0
q = lambda v: np.round(v / RES) * RES   # quantise heights to the grid step

def build(icon_mask, slop, inlay=False):
    b = np.full(X.shape, np.nan)
    t = np.full(X.shape, np.nan)
    if inlay:
        sel = icon_mask & INSIDE
        b[sel], t[sel] = q(TOP - ENGRAVE), q(TOP)
        return b, t
    b[INSIDE] = 0.0
    t[INSIDE] = q(TOP - np.maximum(0, CHAMFER - DIST[INSIDE]))
    if icon_mask is not None:
        sel = icon_mask & INSIDE
        t[sel] = np.minimum(t[sel], q(TOP - ENGRAVE))
    pw, pl = 1.2 - slop, PRONG_LEN - slop
    for cx in (-PRONG_SEP / 2, PRONG_SEP / 2):
        prong = (np.abs(X - cx) < pw / 2) & (np.abs(Y) < pl / 2)
        b[prong] = -3.0
    return b, t

# ------------------------------------------------------------------ meshing
def mesh(b, t):
    """Watertight triangle mesh of the 2.5D solid defined per cell by [b, t]."""
    nx, ny = b.shape
    filled = ~np.isnan(b)
    levels = np.unique(np.concatenate([b[filled], t[filled]]))
    zk = lambda z: int(round(z / RES * 4))      # hashable height key

    # 1) horizontal rectangles (greedy) per level
    rects = []
    for arr, up in ((t, True), (b, False)):
        for z in levels:
            region = filled & np.isclose(arr, z)
            if not region.any():
                continue
            used = np.zeros_like(region)
            for i in range(nx):
                col = region[i] & ~used[i]
                if not col.any():
                    continue
                j = 0
                while j < ny:
                    if not col[j]:
                        j += 1; continue
                    j1 = j
                    while j1 < ny and col[j1]:
                        j1 += 1
                    i1 = i + 1
                    while i1 < nx and region[i1, j:j1].all() and not used[i1, j:j1].any():
                        i1 += 1
                    used[i:i1, j:j1] = True
                    col[j:j1] = False
                    rects.append((i, j, i1, j1, z, up))
                    j = j1

    # 2) vertical walls, merged along straight runs
    def interval(i, j):
        if 0 <= i < nx and 0 <= j < ny and filled[i, j]:
            return (b[i, j], t[i, j])
        return None

    def minus(a, bb):
        lo, hi = a
        if bb is None: return [a]
        out = []
        if bb[0] > lo: out.append((lo, min(hi, bb[0])))
        if bb[1] < hi: out.append((max(lo, bb[1]), hi))
        return tuple(s for s in out if s[1] - s[0] > 1e-9)

    walls = []
    def runs(get_edges, line_len, mk):
        # get_edges(k) -> (spans facing +, spans facing -) for edge k along the line
        prev, start = None, 0
        for k in range(line_len + 1):
            cur = get_edges(k) if k < line_len else None
            if cur != prev:
                if prev:
                    for spans, sign in ((prev[0], 1), (prev[1], -1)):
                        for lo, hi in spans:
                            walls.append(mk(start, k, lo, hi, sign))
                prev, start = cur, k
    for i in range(nx + 1):
        def ge(j, i=i):
            A, B = interval(i - 1, j), interval(i, j)
            r = (minus(A, B) if A else (), minus(B, A) if B else ())
            return r if (r[0] or r[1]) else None
        runs(ge, ny, lambda a, c, lo, hi, s, i=i: ((i, a), (i, c), lo, hi, (s, 0, 0)))
    for j in range(ny + 1):
        def ge(i, j=j):
            A, B = interval(i, j - 1), interval(i, j)
            r = (minus(A, B) if A else (), minus(B, A) if B else ())
            return r if (r[0] or r[1]) else None
        runs(ge, nx, lambda a, c, lo, hi, s, j=j: ((a, j), (c, j), lo, hi, (0, s, 0)))

    # 3) every vertex that must exist
    reg = set()
    for i, j, i1, j1, z, up in rects:
        for p in ((i, j), (i1, j), (i1, j1), (i, j1)):
            reg.add((p[0], p[1], zk(z)))
    wall_levels = []
    for p, q_, lo, hi, n in walls:
        lv = [z for z in levels if lo - 1e-9 <= z <= hi + 1e-9]
        wall_levels.append(lv)
        for z in lv:
            reg.add((p[0], p[1], zk(z))); reg.add((q_[0], q_[1], zk(z)))
    # wall endpoints split rectangle edges and other walls lying on the same line
    # (horizontal neighbours were registered above; vertical collinear walls share endpoints by construction)

    verts, vidx, tris = [], {}, []
    def V(i, j, z):
        key = (i, j, zk(z))
        if key not in vidx:
            vidx[key] = len(verts)
            verts.append((-CAP_W / 2 + i * RES, -CAP_H / 2 + j * RES, z))
        return vidx[key]

    for i, j, i1, j1, z, up in rects:
        k = zk(z)
        per = ([(ii, j) for ii in range(i, i1)] + [(i1, jj) for jj in range(j, j1)] +
               [(ii, j1) for ii in range(i1, i, -1)] + [(i, jj) for jj in range(j1, j, -1)])
        corners = {(i, j), (i1, j), (i1, j1), (i, j1)}
        ids = [V(a, c, z) for a, c in per if (a, c) in corners or (a, c, k) in reg]
        if len(ids) == 4:
            a, c, e, f = ids
            tris += [(a, c, e), (a, e, f)] if up else [(a, e, c), (a, f, e)]
            continue
        verts.append((-CAP_W / 2 + (i + i1) / 2 * RES, -CAP_H / 2 + (j + j1) / 2 * RES, z))
        cen = len(verts) - 1
        for m in range(len(ids)):
            a, c = ids[m], ids[(m + 1) % len(ids)]
            tris.append((cen, a, c) if up else (cen, c, a))

    for (p, q_, lo, hi, n), lv in zip(walls, wall_levels):
        # points along this wall's line where other vertices exist (from rectangles/walls)
        if p[0] == q_[0]:
            line_pts = [(p[0], jj) for jj in range(p[1], q_[1] + 1)]
        else:
            line_pts = [(ii, p[1]) for ii in range(p[0], q_[0] + 1)]
        d = np.array([q_[0] - p[0], q_[1] - p[1], 0.0])
        if np.dot(np.cross(d, [0, 0, 1]), n) < 0:
            line_pts = line_pts[::-1]
        for z0, z1 in zip(lv, lv[1:]):
            k0, k1 = zk(z0), zk(z1)
            bot = [pt for m, pt in enumerate(line_pts) if m in (0, len(line_pts) - 1) or (pt[0], pt[1], k0) in reg]
            top = [pt for m, pt in enumerate(line_pts) if m in (0, len(line_pts) - 1) or (pt[0], pt[1], k1) in reg]
            # polygon: bottom edge forward, top edge backward; fan from its centre
            ring_ = [V(*pt, z0) for pt in bot] + [V(*pt, z1) for pt in top[::-1]]
            if len(ring_) == 4:
                a, c, e, f = ring_
                tris += [(a, c, e), (a, e, f)]
                continue
            mx = (line_pts[0][0] + line_pts[-1][0]) / 2 * RES - CAP_W / 2
            my = (line_pts[0][1] + line_pts[-1][1]) / 2 * RES - CAP_H / 2
            verts.append((mx, my, (z0 + z1) / 2)); cen = len(verts) - 1
            for m in range(len(ring_)):
                tris.append((cen, ring_[m], ring_[(m + 1) % len(ring_)]))
    return np.array(verts), np.array(tris)

def check(v, f):
    from collections import Counter
    e = Counter()
    for a, b_, c in f:
        for u, w in ((a, b_), (b_, c), (c, a)):
            e[(u, w)] += 1
    bad = sum(1 for (u, w), n in e.items() if n != 1 or e.get((w, u), 0) != 1)
    p0, p1, p2 = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    vol = np.einsum("ij,ij->i", p0, np.cross(p1, p2)).sum() / 6
    return bad, vol

def write_stl(path, v, f, name):
    with open(path, "wb") as fh:
        fh.write(name.encode()[:80].ljust(80, b" "))
        fh.write(struct.pack("<I", len(f)))
        p0, p1, p2 = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
        n = np.cross(p1 - p0, p2 - p0)
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        rec = np.zeros(len(f), dtype=[("n", "<f4", 3), ("a", "<f4", 3), ("b", "<f4", 3), ("c", "<f4", 3), ("x", "<u2")])
        rec["n"], rec["a"], rec["b"], rec["c"] = n, p0, p1, p2
        fh.write(rec.tobytes())

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    for d in ("stl-nominal", "stl-loose", "inlays"):
        os.makedirs(os.path.join(out, d), exist_ok=True)
    masks = {}
    for idx, (name, fn, ref) in enumerate(KEYS, 1):
        m = clean(fn())
        masks[name] = m
        fname = f"{idx:02d}-{name}"
        for variant, slop in (("stl-nominal", 0.0), ("stl-loose", 0.1)):
            v, f = mesh(*build(m, slop))
            bad, vol = check(v, f)
            assert bad == 0 and vol > 0, (name, variant, bad, vol)
            write_stl(os.path.join(out, variant, fname + ".stl"), v, f, f"{name} choc v1 keycap")
        v, f = mesh(*build(m, 0, inlay=True))
        bad, vol = check(v, f)
        assert bad == 0 and vol > 0, (name, "inlay", bad, vol)
        write_stl(os.path.join(out, "inlays", fname + "-inlay.stl"), v, f, f"{name} inlay")
        print(f"{fname:14s} {ref:5s} ok  ({len(f)} triangles, {vol:.0f} mm3)")
    for variant, slop in (("nominal", 0.0), ("loose", 0.1)):
        v, f = mesh(*build(None, slop))
        assert check(v, f)[0] == 0
        write_stl(os.path.join(out, f"fit-test-{variant}.stl"), v, f, "choc v1 fit test")
    np.savez_compressed(os.path.join(out, "_masks.npz"), **{"k_" + k: v for k, v in masks.items()})
    print("done")
