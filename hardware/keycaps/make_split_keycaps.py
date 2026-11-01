# NOTE: the cross-stem (Cherry-style) design in this file is NOT used. make_choc_keycaps.py is the real one for the Choc V1 switches and only borrows the helpers here (font, icons, mesher, 3MF writer).
#!/usr/bin/env python3
"""Two-piece keycaps (24 of them): the round top is its own piece, the rest of the cap prints flat on the bed.
Built from basic-keycap-1u.stl (cut from your basickeycap.stl), with Lato numbers.

  body      your keycap with the round top cut off flat (at the cap's own top plane, z = 6). The stem, skirt and
            ribs are your STL exactly. The top is one flat face, so the body prints face down on the bed.
  insert    the round top: your dome, whole, with the number or icon let in 0.4 mm, and a little cross-shaped
            post under it that presses into the top of the stem socket (the socket is open at the top now).
            It sits flat on the body, so it can't tilt or go in too far.
  symbol    the number or icon alone, to print in a second colour (it fills the recess exactly)

Everything is built on a 0.05 mm grid as a 2.5D solid (each grid cell has one or more [bottom, top] intervals)
and meshed into watertight STLs; no CAD library needed. Run:  python3 make_split_keycaps.py
Output goes to ./out-split/  (STL files, plus Bambu Studio .3mf plates).

Printing: both pieces go face down on the bed (already turned in the .3mf files).
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
SPLIT = 6.0                     # where the round part comes off: the cap's own top plane
MIN_BODY = 0.4                  # body roof thinner than this is dropped (it would only print as a thin skin)
MIN_DOME = 0.3                  # same for the little flare at the foot of the dome
DOME_FLAT_R = 6.3               # the flat top of the dome (the number / icon must stay inside it)
SOCKET_ARM_W, SOCKET_ARM_L = 1.3, 4.25         # the cross-shaped stem socket (measured from your STL)
POST_LEN = 1.6                  # the post goes this far into the socket (a switch stem needs 3.6 of the 6.0)
POST_CLEAR = {"tight": 0.05, "standard": 0.10, "loose": 0.15}   # how much smaller than the socket, per side
CHAMFER_CELLS = 2               # the post's tip is eased by this many cells (0.1 mm) for starting it in

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

# the 16 icon keys come from make_keycaps.py (same 0.05 mm grid, just a different size of grid: they are
# placed on this one by their offset)
import make_keycaps as old
ICONS = {name: fn for name, fn, ref in old.KEYS[:16]}
ICON_ORDER = [name for name, fn, ref in old.KEYS[:16]]       # keys 1-16; keys 17-24 are the numbers 1-8
OX, OY = int(round((HALF - old.CAP_W / 2) / RES)), int(round((HALF - old.CAP_H / 2) / RES))

def key_mask(key):
    """A digit (1-8, in Lato) or the name of an icon key, as a mask on this grid."""
    if isinstance(key, int):
        return digit_mask(key)
    m = np.zeros((N, N), bool)
    m[OX:OX + old.NX, OY:OY + old.NY] = old.clean(ICONS[key]())
    return m

# ------------------------------------------------------------------ the pieces
def body_layers(orig_b, orig_t):
    """Your keycap with the round top cut off flat at z = 6."""
    b, t = orig_b.copy(), np.minimum(orig_t, SPLIT)
    gone = np.isnan(b) | (t - b < MIN_BODY - 1e-9)
    b[gone] = np.nan
    t[gone] = np.nan
    from scipy import ndimage
    lab, n = ndimage.label(~np.isnan(b))
    assert n == 1, f"the body came apart into {n} pieces"
    return [(b, t)]

def post_mask(clear):
    hw, hl = SOCKET_ARM_W / 2 - clear, SOCKET_ARM_L / 2 - clear
    return ((np.abs(X) <= hw) & (np.abs(Y) <= hl)) | ((np.abs(Y) <= hw) & (np.abs(X) <= hl))

def insert_layers(key, fit, recess=True):
    """The round top: your dome (from z = 6 up), the number or icon let in, and the cross post underneath."""
    ob, ot = ORIGINAL
    b = np.full((N, N), np.nan)
    t = np.full((N, N), np.nan)
    dome = ~np.isnan(ot) & (ot >= SPLIT + MIN_DOME)
    b[dome], t[dome] = SPLIT, ot[dome]
    from scipy import ndimage
    post = post_mask(POST_CLEAR[fit]) & dome
    b[post] = SPLIT - POST_LEN
    tip = post & ~ndimage.binary_erosion(post, iterations=CHAMFER_CELLS)
    b[tip] = SPLIT - POST_LEN + 0.2
    if recess and key is not None:
        m = key_mask(key) & (R <= DOME_FLAT_R)
        t[m] = q(TOP - INLAY)
    return [(b, t)]

def inlay_layers(key):
    b = np.full((N, N), np.nan)
    t = np.full((N, N), np.nan)
    m = key_mask(key) & (R <= DOME_FLAT_R)
    b[m], t[m] = q(TOP - INLAY), TOP
    return [(b, t)]

ORIGINAL = None          # your keycap on the grid, filled in by build_all()

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

def flipped(v, top=TOP):
    """Turn the part over (top face down) and rest it on z = 0; `top` is the height of its top face."""
    out = v.copy()
    out[:, 1] *= -1
    out[:, 2] = top - out[:, 2]
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

def write_3mf(path, title, body, inserts, bodies, cols=4):
    """body = (verts, tris) printed upright, `bodies` copies of it (instances of one object);
    inserts = [(label, disc (v, f), number (v, f) or None, filament of the disc)], each already face-down.
    Filament slots: 1 = the keycap, 2 = the number, 3 = the red record key."""
    files, rels, resources, items, cfg_objects, cfg_instances = {}, [], [], [], [], []
    next_id = 1
    m16 = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"
    ident = "1 0 0 0 1 0 0 0 1 0 0 0"
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
    if bodies:
        body_id = add_object("keycap body", [("body", body[0], body[1], 1)])
        rows = (bodies + cols - 1) // cols
        for n in range(bodies):
            r, c = divmod(n, cols)
            place(body_id, PLATE_C[0] + (c - (cols - 1) / 2) * pitch_x,
                  PLATE_C[1] + ((rows - 1) / 2 - r) * pitch_y, n)
    # the inserts, in rows
    rows = (len(inserts) + cols - 1) // cols
    for n, (label, disc, number, slot) in enumerate(inserts):
        parts = [("top", disc[0], disc[1], slot)]
        if number is not None:
            parts.append(("number", number[0], number[1], 2))
        oid = add_object(label, parts)
        r, c = divmod(n, cols)
        place(oid, PLATE_C[0] + (c - (cols - 1) / 2) * pitch_x * 0.8,
              PLATE_C[1] + ((rows - 1) / 2 - r) * pitch_y * 0.8, 0)

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
KEYS24 = ICON_ORDER + [1, 2, 3, 4, 5, 6, 7, 8]          # keys 1-16 the icons (SW1-SW16), 17-24 the numbers (SW17-SW24)
FITS = list(POST_CLEAR)

def key_name(idx, key):
    return f"{idx:02d}-{key if isinstance(key, str) else 'track%d' % key}"

def build_all():
    global ORIGINAL
    os.makedirs(OUT, exist_ok=True)
    ORIGINAL = rasterize(load_stl(os.path.join(HERE, "source", "basic-keycap-1u.stl")))
    ob, ot = ORIGINAL
    print("keycap rasterised:", int((~np.isnan(ob)).sum()), "cells")

    body_v, body_f, vol = make(body_layers(ob, ot), "body")
    body_v = flipped(body_v, SPLIT)                              # face down, as it prints
    write_stl(os.path.join(OUT, "keycap-body.stl"), body_v, body_f, "keycap body (face down)")
    print(f"keycap-body.stl          {len(body_f):7d} triangles  {vol:7.1f} mm3")

    for fit in FITS:
        row = []
        for idx, key in enumerate(KEYS24, 1):
            name = key_name(idx, key)
            tv, tf, vol_t = make(insert_layers(key, fit), f"insert {name}")
            nv, nf, vol_n = make(inlay_layers(key), f"symbol {name}")
            tv_f, nv_f = flipped(tv), flipped(nv)             # face down, as they print
            write_stl(os.path.join(OUT, f"insert-{name}-{fit}.stl"), tv_f, tf, f"insert {name} (face down)")
            if fit == "standard":
                write_stl(os.path.join(OUT, f"symbol-{name}.stl"), nv_f, nf, f"symbol {name} (face down, second colour)")
            row.append((name, (tv_f, tf), (nv_f, nf), 3 if key == "record" else 1))
            print(f"{name:16s} {fit:9s}  {len(tf):7d} + {len(nf):5d} triangles  {vol_t:6.1f} + {vol_n:4.2f} mm3")
        write_3mf(os.path.join(OUT, f"console-keycap-tops-{fit}.3mf"),
                  f"Console keycap tops, 24 ({fit} fit)", None, row, 0, cols=6)
    write_3mf(os.path.join(OUT, "console-keycap-bodies.3mf"), "Console keycap bodies, 24",
              (body_v, body_f), [], 24, cols=6)
    # a fit test: one body and a blank top of each fit
    blank = []
    for fit in FITS:
        tv, tf, _ = make(insert_layers(None, fit, recess=False), "blank")
        blank.append((f"blank top {fit}", (flipped(tv), tf), None, 1))
    write_3mf(os.path.join(OUT, "fit-test.3mf"), "Console keycap fit test", (body_v, body_f), blank, 3)

if __name__ == "__main__":
    build_all()
    print("done")
