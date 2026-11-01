#!/usr/bin/env python3
"""Two-piece snap-fit keycaps with Lato numbers, built from basic-keycap-1u.stl (cut from your basickeycap.stl).

  body      the keycap without its round top: the stem, skirt and ribs are your STL, untouched. The round top
            is replaced by a round pocket with a floor, and six small grooves in the pocket wall.
  insert    the round top with the number on it (Lato ExtraBold, small and centred). Six little bumps on its
            edge click into the grooves.
  number    the digit alone, to print in a second colour (it fills the recess in the insert exactly).

Everything is built on a 0.05 mm grid as a 2.5D solid (each grid cell has one or more [bottom, top] intervals)
and meshed into watertight STLs; no CAD library needed. Run:  python3 make_split_keycaps.py
Output goes to ./out-split/  (STL files, plus Bambu Studio .3mf plates).

Printing: the body goes up the way it is (open end down). The insert goes face down on the bed, so the number is
the first layers and is perfectly flat. The .3mf files already have the inserts flipped.
"""
import io, os, struct, sys, uuid, zipfile
import numpy as np
from matplotlib.path import Path
from matplotlib.textpath import TextPath
from matplotlib.font_manager import FontProperties

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out-split")

# ------------------------------------------------------------------ the grid
RES = 0.05                      # mm
HALF = 9.0                      # the grid covers -9..9 in x and y (the key is 18 x 18)
N = int(round(2 * HALF / RES))
xs = -HALF + (np.arange(N) + 0.5) * RES
X, Y = np.meshgrid(xs, xs, indexing="ij")
R = np.hypot(X, Y)
TH = np.degrees(np.arctan2(Y, X))
q = lambda v: np.round(np.asarray(v) / RES) * RES       # heights live on the grid too

# ------------------------------------------------------------------ the design (mm)
TOP = 8.0                       # the top of the round part (your STL)
FLOOR = 7.0                     # the pocket floor / the underside of the insert
POCKET_R = 6.25                 # pocket wall radius (the round top in your STL is about 7.1 across the rim)
GAP = 0.10                      # the insert is this much smaller all round
INSERT_R = POCKET_R - GAP
BUMPS = 6                       # bumps / grooves round the edge
BUMP_Z0, BUMP_Z1 = 7.10, 7.60   # a bump's height range at its base (45 degree flanks, so it prints without support)
BUMP_HALF_ANGLE = 10.0          # degrees: where a bump fades out to nothing
GROOVE_EXTRA = 0.08             # the groove is this much bigger than the bump all round
GROOVE_HALF_ANGLE = BUMP_HALF_ANGLE + 3.0
BUMP_H = {"standard": 0.22, "loose": 0.15}     # how far a bump sticks out (about 0.12 / 0.05 mm into the wall)
BUMP_ANGLES = [30.0 + 60.0 * k for k in range(BUMPS)]
GROOVE_BUMP_H = max(BUMP_H.values())

DIGIT_H = 2.6                   # digit height (mm): small and centred
FONT = os.path.join(HERE, "fonts", "Lato-ExtraBold.ttf")
INLAY = 0.4                     # how deep the number is let into the insert

# ------------------------------------------------------------------ your keycap, onto the grid
def load_stl(path):
    d = open(path, "rb").read()
    n = struct.unpack("<I", d[80:84])[0]
    a = np.frombuffer(d[84:84 + 50 * n], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    return a["v"].astype(np.float64)

def rasterize(tris):
    """Per grid cell: the lowest and highest surface of the solid (your keycap has one solid span per column)."""
    lo = np.full((N, N), np.inf)
    hi = np.full((N, N), -np.inf)
    eps = (1e-4, 1.7e-4)                              # keeps cell centres off triangle edges
    for t in tris:
        (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = t
        den = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(den) < 1e-12:
            continue                                  # a vertical wall: no area seen from above
        i0 = max(0, int((min(x0, x1, x2) + HALF) / RES) - 1)
        i1 = min(N, int((max(x0, x1, x2) + HALF) / RES) + 2)
        j0 = max(0, int((min(y0, y1, y2) + HALF) / RES) - 1)
        j1 = min(N, int((max(y0, y1, y2) + HALF) / RES) + 2)
        px = X[i0:i1, j0:j1] + eps[0]
        py = Y[i0:i1, j0:j1] + eps[1]
        u = ((px - x0) * (y2 - y0) - (x2 - x0) * (py - y0)) / den
        v = ((x1 - x0) * (py - y0) - (px - x0) * (y1 - y0)) / den
        m = (u >= 0) & (v >= 0) & (u + v <= 1)
        if not m.any():
            continue
        z = z0 + u * (z1 - z0) + v * (z2 - z0)
        sl = (slice(i0, i1), slice(j0, j1))
        lo[sl] = np.where(m, np.minimum(lo[sl], z), lo[sl])
        hi[sl] = np.where(m, np.maximum(hi[sl], z), hi[sl])
    b = np.where(np.isfinite(lo), q(lo), np.nan)
    t = np.where(np.isfinite(hi), q(hi), np.nan)
    ok = ~np.isnan(b) & (t - b > RES / 2)
    return np.where(ok, b, np.nan), np.where(ok, t, np.nan)

# ------------------------------------------------------------------ the number
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

def digit_mask(digit):
    fp = FontProperties(fname=FONT)
    ref = np.vstack(TextPath((0, 0), "1", size=10, prop=fp).to_polygons())
    k = DIGIT_H / (ref[:, 1].max() - ref[:, 1].min())           # the same scale for every digit
    polys = TextPath((0, 0), str(digit), size=10, prop=fp).to_polygons()
    allv = np.vstack(polys)
    cx, cy = (allv[:, 0].min() + allv[:, 0].max()) / 2, (allv[:, 1].min() + allv[:, 1].max()) / 2
    pts = np.c_[X.ravel(), Y.ravel()]
    m = np.zeros(len(pts), bool)
    for pg in polys:                                            # even-odd: the holes in 0, 4, 6, 8, 9 stay open
        m ^= Path((pg - [cx, cy]) * k).contains_points(pts)
    return clean(m.reshape(X.shape))

# ------------------------------------------------------------------ the pieces
def angdiff(a, b):
    return (a - b + 180.0) % 360.0 - 180.0

def bump_profile(bump_h):
    """(radial height of the bump, where it is) in every cell outside the insert's edge: a pyramid-ish bump,
    fading out sideways."""
    h = np.zeros_like(R)
    for ang in BUMP_ANGLES:
        fade = np.clip(1.0 - np.abs(angdiff(TH, ang)) / BUMP_HALF_ANGLE, 0.0, 1.0)
        h = np.maximum(h, bump_h * fade)
    return h

def body_layers(orig_b, orig_t):
    """Your keycap, with a pocket instead of the round top. Two layers: the second is the ceiling of a groove."""
    b1, t1 = orig_b.copy(), orig_t.copy()
    inside = ~np.isnan(b1)
    pocket = inside & (R < POCKET_R)
    t1[pocket] = FLOOR
    assert (t1[pocket] - b1[pocket]).min() >= 0.45, "the pocket floor would be too thin"
    b2 = np.full_like(b1, np.nan)
    t2 = np.full_like(b1, np.nan)
    # six grooves in the wall, matching the bumps (a little bigger all round)
    r_g = INSERT_R + GROOVE_BUMP_H + GROOVE_EXTRA
    near = np.zeros_like(R, bool)
    for ang in BUMP_ANGLES:
        near |= np.abs(angdiff(TH, ang)) <= GROOVE_HALF_ANGLE
    groove = inside & near & (R >= POCKET_R) & (R <= r_g)
    h = np.minimum(R - INSERT_R, GROOVE_BUMP_H)
    lo = q(BUMP_Z0 + h - GROOVE_EXTRA)
    hi = q(BUMP_Z1 - h + GROOVE_EXTRA)
    wall_top = orig_t.copy()
    assert (wall_top[groove] - hi[groove]).min() >= 0.3, "the lip above a groove would be too thin"
    t1[groove] = lo[groove]
    b2[groove], t2[groove] = hi[groove], wall_top[groove]
    return [(b1, t1), (b2, t2)]

def insert_layers(digit, bump_name, recess=True):
    """The round top: a disc with six bumps, and the number let in 0.4 mm (so the colour part drops in)."""
    b = np.full((N, N), np.nan)
    t = np.full((N, N), np.nan)
    disc = R <= INSERT_R
    b[disc], t[disc] = FLOOR, TOP
    h = bump_profile(BUMP_H[bump_name])
    rr = R - INSERT_R
    bump = (R > INSERT_R) & (rr <= h)
    b[bump] = q(BUMP_Z0 + rr[bump])
    t[bump] = q(BUMP_Z1 - rr[bump])
    if recess and digit is not None:
        m = digit_mask(digit) & disc
        t[m] = q(TOP - INLAY)
    return [(b, t)]

def inlay_layers(digit):
    b = np.full((N, N), np.nan)
    t = np.full((N, N), np.nan)
    m = digit_mask(digit) & (R <= INSERT_R)
    b[m], t[m] = q(TOP - INLAY), TOP
    return [(b, t)]

# ------------------------------------------------------------------ meshing (several [bottom, top] spans per cell)
def mesh_layers(layers):
    """Watertight triangle mesh of the solid: every layer is one span per cell (NaN where it has none)."""
    nx, ny = layers[0][0].shape
    lv = []
    for b, t in layers:
        f = ~np.isnan(b)
        lv.append(b[f]); lv.append(t[f])
    levels = np.unique(np.concatenate(lv))
    zk = lambda z: int(round(z / RES * 4))

    # 1) horizontal rectangles (greedy), per layer and level
    rects = []
    for b, t in layers:
        filled = ~np.isnan(b)
        for arr, up in ((t, True), (b, False)):
            for z in np.unique(arr[filled]):
                region = filled & np.isclose(arr, z)
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

    # 2) vertical walls where neighbouring cells differ, merged along straight runs
    def spans(i, j):
        out = []
        if 0 <= i < nx and 0 <= j < ny:
            for b, t in layers:
                if not np.isnan(b[i, j]):
                    out.append((b[i, j], t[i, j]))
        return out

    def minus(A, B):
        res = []
        for lo, hi in A:
            segs = [(lo, hi)]
            for blo, bhi in B:
                new = []
                for s0, s1 in segs:
                    if bhi <= s0 or blo >= s1:
                        new.append((s0, s1)); continue
                    if blo > s0: new.append((s0, min(s1, blo)))
                    if bhi < s1: new.append((max(s0, bhi), s1))
                segs = new
            res += [s for s in segs if s[1] - s[0] > 1e-9]
        return tuple(res)

    walls = []
    def runs(get_edges, line_len, mk):
        prev, start = None, 0
        for k in range(line_len + 1):
            cur = get_edges(k) if k < line_len else None
            if cur != prev:
                if prev:
                    for sp, sign in ((prev[0], 1), (prev[1], -1)):
                        for lo, hi in sp:
                            walls.append(mk(start, k, lo, hi, sign))
                prev, start = cur, k
    for i in range(nx + 1):
        def ge(j, i=i):
            A, B = spans(i - 1, j), spans(i, j)
            r = (minus(A, B), minus(B, A))
            return r if (r[0] or r[1]) else None
        runs(ge, ny, lambda a, c, lo, hi, s, i=i: ((i, a), (i, c), lo, hi, (s, 0, 0)))
    for j in range(ny + 1):
        def ge(i, j=j):
            A, B = spans(i, j - 1), spans(i, j)
            r = (minus(A, B), minus(B, A))
            return r if (r[0] or r[1]) else None
        runs(ge, nx, lambda a, c, lo, hi, s, j=j: ((a, j), (c, j), lo, hi, (0, s, 0)))

    # 3) every vertex that has to exist (so rectangles and walls meet without T-junctions)
    reg = set()
    for i, j, i1, j1, z, up in rects:
        for p in ((i, j), (i1, j), (i1, j1), (i, j1)):
            reg.add((p[0], p[1], zk(z)))
    wall_levels = []
    for p, q_, lo, hi, n in walls:
        lvl = [z for z in levels if lo - 1e-9 <= z <= hi + 1e-9]
        wall_levels.append(lvl)
        for z in lvl:
            reg.add((p[0], p[1], zk(z))); reg.add((q_[0], q_[1], zk(z)))

    verts, vidx, tris = [], {}, []
    def V(i, j, z):
        key = (i, j, zk(z))
        if key not in vidx:
            vidx[key] = len(verts)
            verts.append((-HALF + i * RES, -HALF + j * RES, z))
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
        verts.append((-HALF + (i + i1) / 2 * RES, -HALF + (j + j1) / 2 * RES, z))
        cen = len(verts) - 1
        for m in range(len(ids)):
            a, c = ids[m], ids[(m + 1) % len(ids)]
            tris.append((cen, a, c) if up else (cen, c, a))

    for (p, q_, lo, hi, n), lvl in zip(walls, wall_levels):
        if p[0] == q_[0]:
            line_pts = [(p[0], jj) for jj in range(p[1], q_[1] + 1)]
        else:
            line_pts = [(ii, p[1]) for ii in range(p[0], q_[0] + 1)]
        d = np.array([q_[0] - p[0], q_[1] - p[1], 0.0])
        if np.dot(np.cross(d, [0, 0, 1]), n) < 0:
            line_pts = line_pts[::-1]
        for z0, z1 in zip(lvl, lvl[1:]):
            k0, k1 = zk(z0), zk(z1)
            bot = [pt for m, pt in enumerate(line_pts) if m in (0, len(line_pts) - 1) or (pt[0], pt[1], k0) in reg]
            top = [pt for m, pt in enumerate(line_pts) if m in (0, len(line_pts) - 1) or (pt[0], pt[1], k1) in reg]
            ring_ = [V(*pt, z0) for pt in bot] + [V(*pt, z1) for pt in top[::-1]]
            if len(ring_) == 4:
                a, c, e, f = ring_
                tris += [(a, c, e), (a, e, f)]
                continue
            mx = (line_pts[0][0] + line_pts[-1][0]) / 2 * RES - HALF
            my = (line_pts[0][1] + line_pts[-1][1]) / 2 * RES - HALF
            verts.append((mx, my, (z0 + z1) / 2)); cen = len(verts) - 1
            for m in range(len(ring_)):
                tris.append((cen, ring_[m], ring_[(m + 1) % len(ring_)]))
    return np.array(verts), np.array(tris)

def check(v, f):
    """(number of edges that aren't shared by exactly two triangles, volume in mm3)."""
    from collections import Counter
    e = Counter()
    for a, b_, c in f:
        for u, w in ((a, b_), (b_, c), (c, a)):
            e[(u, w)] += 1
    bad = sum(1 for (u, w), n in e.items() if n != 1 or e.get((w, u), 0) != 1)
    p0, p1, p2 = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    return bad, np.einsum("ij,ij->i", p0, np.cross(p1, p2)).sum() / 6

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

def make(layers, label):
    v, f = mesh_layers(layers)
    bad, vol = check(v, f)
    assert bad == 0 and vol > 0, (label, bad, vol)
    return v, f, vol

# ------------------------------------------------------------------ Bambu Studio .3mf plates
PLATE_C = (128.0, 128.0)                 # the P1S bed is 256 x 256
NS = ('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
      'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
      'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06"')

def flipped(v):
    """Turn the part over (top face down) and rest it on z = 0."""
    out = v.copy()
    out[:, 1] *= -1
    out[:, 2] = TOP - out[:, 2]
    return out

def rested(v):
    out = v.copy()
    out[:, 2] -= out[:, 2].min()
    return out

def mesh_xml(obj_id, v, f, name):
    buf = io.StringIO()
    buf.write(f' <object id="{obj_id}" p:UUID="{uuid.uuid4()}" type="model" name="{name}">\n  <mesh>\n   <vertices>\n')
    np.savetxt(buf, v, fmt='    <vertex x="%.4f" y="%.4f" z="%.4f"/>')
    buf.write('   </vertices>\n   <triangles>\n')
    np.savetxt(buf, f, fmt='    <triangle v1="%d" v2="%d" v3="%d"/>')
    buf.write('   </triangles>\n  </mesh>\n </object>\n')
    return buf.getvalue()

def write_3mf(path, title, body, inserts, bodies):
    """body = (verts, tris) printed upright, `bodies` copies of it (instances of one object);
    inserts = [(label, disc (v, f), number (v, f) or None)], each already face-down.
    Filament slots: 1 = the keycap, 2 = the number."""
    files, rels, resources, items, cfg_objects, cfg_instances = {}, [], [], [], [], []
    next_id = 1
    m16 = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"
    ident = "1 0 0 0 1 0 0 0 1 0 0 0"
    cols = 4
    pitch_x, pitch_y = 22.0, 22.0

    def add_object(label, parts):
        nonlocal next_id
        ids = list(range(next_id, next_id + len(parts)))
        obj_id = next_id + len(parts)
        next_id += len(parts) + 1
        part_file = f"/3D/Objects/object_{obj_id}.model"
        files[part_file[1:]] = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" {NS} requiredextensions="p">\n'
            f' <metadata name="BambuStudio:3mfVersion">1</metadata>\n <resources>\n'
            + "".join(mesh_xml(i, v, f, f"{label} {pname}") for i, (pname, v, f, slot) in zip(ids, parts))
            + ' </resources>\n <build/>\n</model>\n')
        rels.append(f' <Relationship Target="{part_file}" Id="rel-{obj_id}" '
                    f'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>')
        resources.append(
            f'  <object id="{obj_id}" p:UUID="{uuid.uuid4()}" type="model">\n   <components>\n'
            + "\n".join(f'    <component p:path="{part_file}" objectid="{i}" p:UUID="{uuid.uuid4()}" transform="{ident}"/>'
                        for i in ids) + '\n   </components>\n  </object>')
        cfg_objects.append(
            f'  <object id="{obj_id}">\n    <metadata key="name" value="{label}"/>\n'
            f'    <metadata key="extruder" value="{parts[0][3]}"/>\n'
            + "".join(f'    <part id="{i}" subtype="normal_part">\n      <metadata key="name" value="{label} {pname}"/>\n'
                      f'      <metadata key="matrix" value="{m16}"/>\n      <metadata key="extruder" value="{slot}"/>\n    </part>\n'
                      for i, (pname, v, f, slot) in zip(ids, parts))
            + '  </object>')
        return obj_id

    def place(obj_id, x, y, inst):
        items.append(f'  <item objectid="{obj_id}" p:UUID="{uuid.uuid4()}" '
                     f'transform="1 0 0 0 1 0 0 0 1 {x:.3f} {y:.3f} 0" printable="1"/>')
        cfg_instances.append(
            f'    <model_instance>\n      <metadata key="object_id" value="{obj_id}"/>\n'
            f'      <metadata key="instance_id" value="{inst}"/>\n'
            f'      <metadata key="identify_id" value="{obj_id * 100 + inst}"/>\n    </model_instance>')

    # the bodies: one object, several instances, in rows at the back of the bed
    bv = rested(body[0])
    body_id = add_object("keycap body", [("body", bv, body[1], 1)])
    for n in range(bodies):
        r, c = divmod(n, cols)
        place(body_id, PLATE_C[0] + (c - (cols - 1) / 2) * pitch_x, PLATE_C[1] + 20 + r * pitch_y, n)
    # the inserts: in rows at the front
    for n, (label, disc, number) in enumerate(inserts):
        parts = [("top", disc[0], disc[1], 1)]
        if number is not None:
            parts.append(("number", number[0], number[1], 2))
        oid = add_object(label, parts)
        r, c = divmod(n, cols)
        place(oid, PLATE_C[0] + (c - (cols - 1) / 2) * pitch_x * 0.8, PLATE_C[1] - 15 - r * pitch_y * 0.8, 0)

    files["3D/3dmodel.model"] = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" {NS} requiredextensions="p">\n'
        ' <metadata name="Application">BambuStudio-01.10.02.76</metadata>\n'
        ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
        f' <metadata name="Title">{title}</metadata>\n'
        ' <resources>\n' + "\n".join(resources) + '\n </resources>\n'
        f' <build p:UUID="{uuid.uuid4()}">\n' + "\n".join(items) + '\n </build>\n</model>\n')
    files["3D/_rels/3dmodel.model.rels"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        + "\n".join(rels) + '\n</Relationships>\n')
    files["_rels/.rels"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        ' <Relationship Target="/3D/3dmodel.model" Id="rel-1" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n</Relationships>\n')
    files["[Content_Types].xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
        ' <Default Extension="config" ContentType="text/xml"/>\n</Types>\n')
    files["Metadata/model_settings.config"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + "\n".join(cfg_objects) +
        '\n  <plate>\n    <metadata key="plater_id" value="1"/>\n    <metadata key="plater_name" value="keycaps"/>\n'
        '    <metadata key="locked" value="false"/>\n' + "\n".join(cfg_instances) + '\n  </plate>\n</config>\n')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("[Content_Types].xml", files.pop("[Content_Types].xml"))
        for name, data in files.items():
            z.writestr(name, data)

# ------------------------------------------------------------------ main
def build_all():
    os.makedirs(OUT, exist_ok=True)
    ob, ot = rasterize(load_stl(os.path.join(HERE, "source", "basic-keycap-1u.stl")))
    print("keycap rasterised:", int((~np.isnan(ob)).sum()), "cells")

    body_v, body_f, vol = make(body_layers(ob, ot), "body")
    write_stl(os.path.join(OUT, "keycap-body.stl"), body_v, body_f, "keycap body (print upright)")
    print(f"keycap-body.stl          {len(body_f):7d} triangles  {vol:7.1f} mm3")

    sets = {}
    for variant in BUMP_H:
        row = []
        for d in range(1, 9):
            tv, tf, vol_t = make(insert_layers(d, variant), f"insert {d}")
            nv, nf, vol_n = make(inlay_layers(d), f"number {d}")
            tv_f, nv_f = flipped(tv), flipped(nv)             # face down, as they print
            write_stl(os.path.join(OUT, f"insert-{d}-{variant}.stl"), tv_f, tf, f"insert {d} (face down)")
            if variant == "standard":
                write_stl(os.path.join(OUT, f"number-{d}.stl"), nv_f, nf, f"number {d} (face down, second colour)")
            row.append((f"insert {d}", (tv_f, tf), (nv_f, nf)))
            print(f"insert {d} {variant:9s}  {len(tf):7d} + {len(nf):5d} triangles  {vol_t:6.1f} + {vol_n:4.2f} mm3")
        sets[variant] = row
        write_3mf(os.path.join(OUT, f"console-keycaps-snap-{variant}.3mf"),
                  f"Console keycaps, two-piece ({variant} snap)", (body_v, body_f), row, 8)
    # a fit test: one body and a blank insert of each kind
    blank = []
    for variant in BUMP_H:
        tv, tf, _ = make(insert_layers(None, variant, recess=False), "blank")
        blank.append((f"blank insert {variant}", (flipped(tv), tf), None))
    write_3mf(os.path.join(OUT, "fit-test.3mf"), "Console keycap snap fit test", (body_v, body_f), blank, 2)
    return ob, ot, body_layers(ob, ot)

if __name__ == "__main__":
    build_all()
    print("done")
