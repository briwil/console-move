"""A small KiCad board writer for the v0.2 control boards (make_boards.py uses it).

It places parts, writes the .kicad_pcb, writes a Specctra .dsn for Freerouting, reads
Freerouting's .ses back in as tracks and vias, checks every net is joined, and draws a picture.
The Choc, encoder, PGA2350, USB-C, SOD-123, 0603, TL3342 and M3 footprints are copied from the
v0.1 board (../console-controls.kicad_pcb); the 6 mm button, DO-35 diode and IDC box header are
written here (the same as KiCad's own library ones).
"""
import copy
import math
import os
import re
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
OLD_BOARD = os.path.join(HERE, "..", "console-controls.kicad_pcb")

TRACK = 0.25          # mm
POWER_TRACK = 0.4
CLEARANCE = 0.2
VIA, VIA_DRILL = 0.6, 0.3
POWER_NETS = ("GND", "VBUS")


# ------------------------------------------------------------------ s-expressions

def parse(s):
    toks = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+', s)
    st = [[]]
    for t in toks:
        if t == "(":
            st.append([])
        elif t == ")":
            x = st.pop()
            st[-1].append(x)
        else:
            st[-1].append(t)
    return st[0]


def q(s):
    return '"%s"' % str(s).replace('"', '\\"')


def unq(t):
    return t[1:-1].replace('\\"', '"') if isinstance(t, str) and t.startswith('"') else t


def find(n, key):
    return [c for c in n if isinstance(c, list) and c and c[0] == key]


def get(n, key):
    r = find(n, key)
    return r[0] if r else None


def dump(n, ind=0):
    if not isinstance(n, list):
        return n
    head = []
    i = 0
    while i < len(n) and not isinstance(n[i], list):
        head.append(n[i])
        i += 1
    rest = n[i:]
    if not rest:
        return "(" + " ".join(head) + ")"
    pre = "\t" * (ind + 1)
    s = "(" + " ".join(head)
    for c in rest:
        s += "\n" + pre + (dump(c, ind + 1) if isinstance(c, list) else c)
    return s + "\n" + "\t" * ind + ")"


def f(x):
    s = ("%.4f" % x).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def new_uuid():
    return q(uuid.uuid4())


# ------------------------------------------------------------------ geometry

def rot(x, y, a):
    """KiCad's rotation (y down, angle counter-clockwise on screen)."""
    r = math.radians(a)
    return x * math.cos(r) + y * math.sin(r), -x * math.sin(r) + y * math.cos(r)


class Pad:
    def __init__(self, num, kind, shape, x, y, angle, w, h, layers, drill=None, net=None):
        self.num, self.kind, self.shape = num, kind, shape
        self.x, self.y, self.angle, self.w, self.h = x, y, angle, w, h
        self.layers, self.drill, self.net = layers, drill, net      # layers: "F", "B" or "FB"

    def corners(self, grow=0.0):
        w, h = self.w / 2 + grow, self.h / 2 + grow
        return [(self.x + a, self.y + b) for a, b in (rot(-w, -h, self.angle), rot(w, -h, self.angle),
                                                       rot(w, h, self.angle), rot(-w, h, self.angle))]

    def axis(self):
        """An oval as a line with a width: (x1, y1, x2, y2, width)."""
        if self.w >= self.h:
            d, width = (self.w - self.h) / 2, self.h
            a = rot(d, 0, self.angle)
        else:
            d, width = (self.h - self.w) / 2, self.w
            a = rot(0, d, self.angle)
        return self.x - a[0], self.y - a[1], self.x + a[0], self.y + a[1], width


# ------------------------------------------------------------------ footprints

def _templates():
    b = parse(open(OLD_BOARD).read())[0]
    out = {}
    for fp in find(b, "footprint"):
        name = unq(fp[1])
        if name not in out:
            out[name] = fp
    return out


TEMPLATES = None


def template(name):
    global TEMPLATES
    if TEMPLATES is None:
        TEMPLATES = _templates()
    return copy.deepcopy(TEMPLATES[name])


def text_prop(name, value, x, y, layer, hide=False, size=1.0, mirror=False):
    p = ["property", q(name), q(value), ["at", f(x), f(y), "0"], ["layer", q(layer)]]
    if hide:
        p.append(["hide", "yes"])
    p.append(["uuid", new_uuid()])
    eff = ["effects", ["font", ["size", f(size), f(size)], ["thickness", f(size * 0.15)]]]
    if mirror:
        eff.append(["justify", "mirror"])
    p.append(eff)
    return p


def g_line(x1, y1, x2, y2, layer, w):
    return ["fp_line", ["start", f(x1), f(y1)], ["end", f(x2), f(y2)],
            ["stroke", ["width", f(w)], ["type", "solid"]], ["layer", q(layer)], ["uuid", new_uuid()]]


def g_rect(x1, y1, x2, y2, layer, w):
    return ["fp_rect", ["start", f(x1), f(y1)], ["end", f(x2), f(y2)],
            ["stroke", ["width", f(w)], ["type", "solid"]], ["fill", "no"], ["layer", q(layer)], ["uuid", new_uuid()]]


def g_circle(cx, cy, r, layer, w):
    return ["fp_circle", ["center", f(cx), f(cy)], ["end", f(cx + r), f(cy)],
            ["stroke", ["width", f(w)], ["type", "solid"]], ["fill", "no"], ["layer", q(layer)], ["uuid", new_uuid()]]


def tht_pad(num, shape, x, y, size, drill, angle=0, rratio=None):
    p = ["pad", q(num), "thru_hole", shape, ["at", f(x), f(y)] + ([f(angle)] if angle else []),
         ["size", f(size), f(size)], ["drill", f(drill)], ["layers", '"*.Cu"', '"*.Mask"']]
    if rratio:
        p.append(["roundrect_rratio", f(rratio)])
    p.append(["uuid", new_uuid()])
    return p


def own_footprint(name, side, descr, items):
    s = "B" if side == "B" else "F"
    fp = ["footprint", q(name), ["layer", q(s + ".Cu")], ["uuid", new_uuid()], ["at", "0", "0"],
          ["descr", q(descr)]]
    return fp + items + [["attr", "through_hole"], ["embedded_fonts", "no"]]


def fp_push_6mm(side="F"):
    s = side
    items = [text_prop("Reference", "REF", 3.25, -2, s + ".SilkS", mirror=s == "B"),
             text_prop("Value", "SW_PUSH_6mm", 3.25, 6.7, s + ".Fab", mirror=s == "B"),
             g_rect(0.25, -0.75, 6.25, 5.25, s + ".Fab", 0.1),
             g_line(1, -1, 5.5, -1, s + ".SilkS", 0.12), g_line(1, 5.5, 5.5, 5.5, s + ".SilkS", 0.12),
             g_line(-0.25, 1.5, -0.25, 3, s + ".SilkS", 0.12), g_line(6.75, 1.5, 6.75, 3, s + ".SilkS", 0.12),
             g_circle(3.25, 2.25, 2, s + ".SilkS", 0.12),
             g_rect(-1.5, -1.5, 8, 6, s + ".CrtYd", 0.05)]
    items += [tht_pad("1", "circle", 0, 0, 2, 1.1), tht_pad("1", "circle", 6.5, 0, 2, 1.1),
              tht_pad("2", "circle", 0, 4.5, 2, 1.1), tht_pad("2", "circle", 6.5, 4.5, 2, 1.1)]
    return own_footprint("Button_Switch_THT:SW_PUSH_6mm", side, "6x6 mm tactile switch (Omron B3F style)", items)


def fp_do35(side="B"):
    s = side
    items = [text_prop("Reference", "REF", 3.81, -2.2, s + ".SilkS", size=0.8, mirror=s == "B"),
             text_prop("Value", "1N4148", 3.81, 2.2, s + ".Fab", size=0.8, mirror=s == "B"),
             g_rect(1.81, -1, 5.81, 1, s + ".Fab", 0.1),
             g_rect(1.69, -1.12, 5.93, 1.12, s + ".SilkS", 0.12),
             g_line(2.41, -1.12, 2.41, 1.12, s + ".SilkS", 0.3),       # the band: cathode (pad 1) side
             g_rect(-1.05, -1.25, 8.67, 1.25, s + ".CrtYd", 0.05)]
    items += [tht_pad("1", "rect", 0, 0, 1.6, 0.8), tht_pad("2", "oval", 7.62, 0, 1.6, 0.8)]
    return own_footprint("Diode_THT:D_DO-35_SOD27_P7.62mm_Horizontal", side,
                         "1N4148, DO-35, 7.62 mm lead spacing. Pad 1 / band = cathode", items)


def fp_idc(n, side="B"):
    """2 x n IDC box header, 2.54 mm. Pin 1 at the origin, odd pins down x = 0, even pins down x = 2.54."""
    s = side
    L = 2.54 * (n - 1)
    items = [text_prop("Reference", "REF", 1.27, -6.1, s + ".SilkS", mirror=s == "B"),
             text_prop("Value", "IDC 2x%d" % n, 1.27, L + 6.1, s + ".Fab", mirror=s == "B"),
             g_rect(-3.18, -5.1, 5.72, L + 5.1, s + ".Fab", 0.1),
             g_rect(-3.29, -5.21, 5.83, L + 5.21, s + ".SilkS", 0.12),
             # the key notch (on the odd-pin side, in the middle) and a pin 1 arrow
             g_line(-3.29, L / 2 - 2.2, -2.1, L / 2 - 2.2, s + ".SilkS", 0.12),
             g_line(-2.1, L / 2 - 2.2, -2.1, L / 2 + 2.2, s + ".SilkS", 0.12),
             g_line(-2.1, L / 2 + 2.2, -3.29, L / 2 + 2.2, s + ".SilkS", 0.12),
             g_line(-4.2, 0, -3.6, -0.5, s + ".SilkS", 0.12), g_line(-4.2, 0, -3.6, 0.5, s + ".SilkS", 0.12),
             g_line(-3.6, -0.5, -3.6, 0.5, s + ".SilkS", 0.12),
             g_rect(-3.68, -5.6, 6.22, L + 5.6, s + ".CrtYd", 0.05)]
    for i in range(n):
        items.append(tht_pad(str(2 * i + 1), "roundrect" if i == 0 else "circle", 0, 2.54 * i, 1.7, 1,
                             rratio=0.147 if i == 0 else None))
        items.append(tht_pad(str(2 * i + 2), "circle", 2.54, 2.54 * i, 1.7, 1))
    return own_footprint("Connector_IDC:IDC-Header_2x%02d_P2.54mm_Vertical" % n, side,
                         "2x%d box header, 2.54 mm, for a ribbon cable with IDC plugs. Pin 1 = triangle" % n, items)


FOOTPRINTS = {
    "choc": lambda: template("console:SW_Kailh_Choc_V1_Hotswap"),
    "enc": lambda: template("Rotary_Encoder:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm"),
    "sod123": lambda: template("Diode_SMD:D_SOD-123"),
    "r0603": lambda: template("Resistor_SMD:R_0603_1608Metric"),
    "tl3342": lambda: template("Button_Switch_SMD:SW_SPST_TL3342"),
    "usbc": lambda: template("Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12"),
    "pga2350": lambda: template("console:PGA2350"),
    "m3": lambda: template("MountingHole:MountingHole_3.2mm_M3"),
    "push6": fp_push_6mm,
    "do35": fp_do35,
    "idc10": lambda: fp_idc(10),
    "idc8": lambda: fp_idc(8),
}


class Part:
    def __init__(self, ref, kind, x, y, angle=0.0, value="", nets=None, lcsc=None):
        self.ref, self.kind, self.x, self.y, self.angle = ref, kind, x, y, angle
        self.value, self.nets, self.lcsc = value, dict(nets or {}), lcsc
        self.fp = FOOTPRINTS[kind]()
        self.side = "B" if unq(get(self.fp, "layer")[1]) == "B.Cu" else "F"
        a0 = get(self.fp, "at")
        self.a0 = float(a0[3]) if len(a0) > 3 else 0.0      # the template's own rotation

    def pads(self):
        out = []
        seen = {}
        for p in find(self.fp, "pad"):
            num, kind, shape = unq(p[1]), p[2], p[3]
            at = get(p, "at")
            lx, ly = float(at[1]), float(at[2])
            pa = (float(at[3]) if len(at) > 3 else 0.0) - self.a0 + self.angle
            dx, dy = rot(lx, ly, self.angle)
            size = get(p, "size")
            w, h = float(size[1]), float(size[2])
            lay = [unq(x) for x in get(p, "layers")[1:]]
            if any(x.startswith("*") for x in lay):
                layers = "FB"
            else:
                layers = "".join(sorted({x[0] for x in lay if x.endswith(".Cu")}))
            d = get(p, "drill")
            drill = None
            if d:
                vals = [float(v) for v in d[1:] if v != "oval" and not isinstance(v, list)]
                drill = (vals[0], vals[1] if len(vals) > 1 else vals[0])
            pad = Pad(num, kind, shape, self.x + dx, self.y + dy, pa, w, h, layers, drill, self.nets.get(num))
            pid = num or "X"
            if pid in seen:
                seen[pid] += 1
                pid = "%s@%d" % (pid, seen[pid])
            else:
                seen[pid] = 0
            pad.pid = pid
            out.append(pad)
        return out

    def courtyard(self):
        """The outline of the part's courtyard on its own side, as a box in board coordinates."""
        xs, ys = [], []
        for k in ("fp_rect", "fp_line"):
            for g in find(self.fp, k):
                if "CrtYd" not in unq(get(g, "layer")[1]):
                    continue
                for key in ("start", "end"):
                    e = get(g, key)
                    x, y = rot(float(e[1]), float(e[2]), self.angle)
                    xs.append(self.x + x)
                    ys.append(self.y + y)
        return (min(xs), min(ys), max(xs), max(ys)) if xs else None

    def sexpr(self, ox, oy):
        fp = copy.deepcopy(self.fp)
        keep = []
        for c in fp:
            if isinstance(c, list) and c and c[0] in ("path", "sheetname", "sheetfile", "units", "uuid"):
                continue
            keep.append(c)
        fp[:] = keep
        fp.insert(3, ["uuid", new_uuid()])
        at = get(fp, "at")
        at[1:] = [f(self.x + ox), f(self.y + oy)] + ([f(self.angle)] if self.angle else [])
        da = self.angle - self.a0
        for p in find(fp, "property"):
            name = unq(p[1])
            if name == "Reference":
                p[2] = q(self.ref)
            elif name == "Value":
                p[2] = q(self.value or self.kind)
            elif name == "LCSC":
                p[2] = q(self.lcsc or "")
            pat = get(p, "at")
            if pat and da:
                pat[3:] = [f((float(pat[3]) if len(pat) > 3 else 0) + da)]
            u = get(p, "uuid")
            if u:
                u[1] = new_uuid()
        if self.lcsc and not any(unq(p[1]) == "LCSC" for p in find(fp, "property")):
            i = max(i for i, c in enumerate(fp) if isinstance(c, list) and c[0] == "property")
            fp.insert(i + 1, text_prop("LCSC", self.lcsc, 0, 0, self.side + ".Fab", hide=True))
        for g in fp:
            if isinstance(g, list) and g and g[0].startswith("fp_"):
                u = get(g, "uuid")
                if u:
                    u[1] = new_uuid()
        for p in find(fp, "pad"):
            for c in list(p):
                if isinstance(c, list) and c[0] in ("net", "pinfunction", "pintype"):
                    p.remove(c)
            pat = get(p, "at")
            if da:
                a = (float(pat[3]) if len(pat) > 3 else 0) + da
                pat[3:] = [f(a % 360)] if a % 360 else []
            net = self.nets.get(unq(p[1]))
            u = get(p, "uuid")
            i = p.index(u) if u else len(p)
            if net:
                p.insert(i, ["net", q(net)])
            if u:
                u[1] = new_uuid()
            else:
                p.append(["uuid", new_uuid()])
        return dump(fp, 1)


# ------------------------------------------------------------------ the board

class Board:
    def __init__(self, name, title, w, h, origin=(20.0, 20.0)):
        self.name, self.title, self.w, self.h = name, title, w, h
        self.ox, self.oy = origin
        self.parts = []
        self.texts = []          # (text, x, y, layer, size)
        self.segments = []       # (x1, y1, x2, y2, width, layer "F"/"B", net)
        self.vias = []           # (x, y, net)

    def add(self, part):
        self.parts.append(part)
        return part

    def text(self, s, x, y, layer="F.SilkS", size=1.5):
        self.texts.append((s, x, y, layer, size))

    def all_pads(self):
        for p in self.parts:
            for pad in p.pads():
                yield p, pad

    def nets(self):
        out = {}
        for p, pad in self.all_pads():
            if pad.net:
                out.setdefault(pad.net, []).append((p.ref, pad))
        return out

    # -------------------------------------------------------------- KiCad file

    def write_kicad(self, path):
        head = open(OLD_BOARD).read()
        head = head[:head.index("\t(footprint")]
        head = head.replace('(title "Console control board")', "(title %s)" % q(self.title))
        head = head.replace('(rev "0.1")', '(rev "0.2")')
        out = [head.rstrip("\n")]
        for p in self.parts:
            out.append("\t" + p.sexpr(self.ox, self.oy))
        ox, oy = self.ox, self.oy
        out.append("\t" + dump(["gr_rect", ["start", f(ox), f(oy)], ["end", f(ox + self.w), f(oy + self.h)],
                                ["stroke", ["width", "0.1"], ["type", "default"]], ["fill", "no"],
                                ["layer", '"Edge.Cuts"'], ["uuid", new_uuid()]], 1))
        for s, x, y, layer, size in self.texts:
            eff = ["effects", ["font", ["size", f(size), f(size)], ["thickness", f(size * 0.15)]]]
            if layer.startswith("B."):
                eff.append(["justify", "mirror"])
            out.append("\t" + dump(["gr_text", q(s), ["at", f(ox + x), f(oy + y), "0"], ["layer", q(layer)],
                                    ["uuid", new_uuid()], eff], 1))
        for x1, y1, x2, y2, w, layer, net in self.segments:
            out.append("\t" + dump(["segment", ["start", f(ox + x1), f(oy + y1)], ["end", f(ox + x2), f(oy + y2)],
                                    ["width", f(w)], ["layer", q(layer + ".Cu")], ["net", q(net)],
                                    ["uuid", new_uuid()]], 1))
        for x, y, net in self.vias:
            out.append("\t" + dump(["via", ["at", f(ox + x), f(oy + y)], ["size", f(VIA)], ["drill", f(VIA_DRILL)],
                                    ["layers", '"F.Cu"', '"B.Cu"'], ["net", q(net)], ["uuid", new_uuid()]], 1))
        out.append("\t(embedded_fonts no)\n)\n")
        open(path, "w").write("\n".join(out))

    # -------------------------------------------------------------- Freerouting

    def write_dsn(self, path):
        U = 1000.0          # um per mm

        def c(x, y):
            return "%d %d" % (round(x * U), round(-y * U))

        lines = ['(pcb "%s"' % self.name,
                 '  (parser (string_quote ") (space_in_quoted_tokens on) (host_cad "KiCad\'s Pcbnew") (host_version "10"))',
                 "  (resolution um 10)", "  (unit um)", "  (structure",
                 "    (layer F.Cu (type signal) (property (index 0)))",
                 "    (layer B.Cu (type signal) (property (index 1)))",
                 "    (boundary (path pcb 0 %s %s %s %s %s))" % (c(0, 0), c(self.w, 0), c(self.w, self.h), c(0, self.h), c(0, 0))]
        # holes without copper (switch and encoder pegs, mounting holes) are kept clear on both layers
        for p, pad in self.all_pads():
            if pad.kind == "np_thru_hole":
                lines.append("    (keepout \"\" (circle signal %d %s))" % (round((pad.w + 0.2) * U), c(pad.x, pad.y)))
        lines += ['    (via "Via[0-1]_%d:%d_um")' % (VIA * U, VIA_DRILL * U),
                  "    (rule (width %d) (clearance %d))" % (TRACK * U, CLEARANCE * U + 1),
                  "  )", "  (placement"]
        stacks = {}
        images = []
        for p in self.parts:
            pins = []
            for pad in p.pads():
                if pad.kind == "np_thru_hole":
                    continue
                pid = pad.pid
                layers = ["F.Cu"] if pad.layers == "F" else ["B.Cu"] if pad.layers == "B" else ["F.Cu", "B.Cu"]
                if pad.shape == "circle":
                    shp = ["(circle %s %d)" % (L, round(pad.w * U)) for L in layers]
                elif pad.shape == "oval" and abs(pad.w - pad.h) > 1e-6:
                    x1, y1, x2, y2, w = pad.axis()
                    shp = ["(path %s %d %s %s)" % (L, round(w * U), c(x1 - pad.x, y1 - pad.y), c(x2 - pad.x, y2 - pad.y))
                           for L in layers]
                else:
                    pts = " ".join(c(x - pad.x, y - pad.y) for x, y in pad.corners())
                    shp = ["(polygon %s 0 %s)" % (L, pts) for L in layers]
                key = " ".join("(shape %s)" % x for x in shp)
                if key not in stacks:
                    stacks[key] = "Pad_%d" % len(stacks)
                pins.append("      (pin %s \"%s\" %s)" % (stacks[key], pid, c(pad.x - p.x, pad.y - p.y)))
            img = "IMG_%s" % p.ref
            images.append('    (image "%s"\n%s\n    )' % (img, "\n".join(pins)))
            lines.append('    (component "%s" (place "%s" %s front 0))' % (img, p.ref, c(p.x, p.y)))
        lines += ["  )", "  (library"] + images
        for key, name in stacks.items():
            lines.append('    (padstack "%s" %s (attach off))' % (name, key))
        lines.append('    (padstack "Via[0-1]_%d:%d_um" (shape (circle F.Cu %d)) (shape (circle B.Cu %d)) (attach off))'
                     % (VIA * U, VIA_DRILL * U, VIA * U, VIA * U))
        lines += ["  )", "  (network"]
        nets = self.nets()
        for net, pins in sorted(nets.items()):
            lines.append('    (net "%s" (pins %s))' % (net,  " ".join('%s-%s' % (ref, pad.pid) for ref, pad in pins)))
        normal = [n for n in nets if n not in POWER_NETS]
        power = [n for n in nets if n in POWER_NETS]
        lines.append('    (class "kicad_default" %s (circuit (use_via "Via[0-1]_%d:%d_um")) (rule (width %d) (clearance %d)))'
                     % (" ".join('"%s"' % n for n in normal), VIA * U, VIA_DRILL * U, TRACK * U, CLEARANCE * U + 1))
        if power:
            lines.append('    (class "power" %s (circuit (use_via "Via[0-1]_%d:%d_um")) (rule (width %d) (clearance %d)))'
                         % (" ".join('"%s"' % n for n in power), VIA * U, VIA_DRILL * U, POWER_TRACK * U, CLEARANCE * U + 1))
        lines += ["  )", "  (wiring)", ")"]
        open(path, "w").write("\n".join(lines) + "\n")

    def read_ses(self, path):
        s = parse(open(path).read())[0]
        routes = get(s, "routes")
        res = get(routes, "resolution")
        scale = float(res[2]) * 1000.0 if res and res[1] == "um" else 10000.0     # units per mm
        self.segments, self.vias = [], []
        for net in find(get(routes, "network_out"), "net"):
            name = unq(net[1])
            for w in find(net, "wire"):
                pth = get(w, "path")
                layer = "F" if unq(pth[1]).startswith("F") else "B"
                width = float(pth[2]) / scale
                pts = [float(v) / scale for v in pth[3:]]
                xy = [(pts[i], -pts[i + 1]) for i in range(0, len(pts), 2)]
                for (x1, y1), (x2, y2) in zip(xy, xy[1:]):
                    self.segments.append((x1, y1, x2, y2, width, layer, name))
            for v in find(net, "via"):
                self.vias.append((float(v[2]) / scale, -float(v[3]) / scale, name))

    # -------------------------------------------------------------- checks

    def unjoined(self):
        """Nets whose pads aren't all joined by tracks and vias. Returns {net: number of separate pieces}."""
        out = {}
        tol = 0.05
        for net, pins in self.nets().items():
            items = []                                        # (kind, data)
            for ref, pad in pins:
                items.append(("pad", pad))
            segs = [s for s in self.segments if s[6] == net]
            vias = [v for v in self.vias if v[2] == net]
            n = len(items) + len(segs) + len(vias)
            parent = list(range(n))

            def root(i):
                while parent[i] != i:
                    parent[i] = parent[parent[i]]
                    i = parent[i]
                return i

            def join(i, j):
                parent[root(i)] = root(j)

            nodes = []        # (index, x, y, layers, radius)
            for i, (_, pad) in enumerate(items):
                nodes.append((i, pad, None))
            base = len(items)
            ends = []
            for k, s in enumerate(segs):
                ends.append((base + k, s[0], s[1], s[5]))
                ends.append((base + k, s[2], s[3], s[5]))
            vb = base + len(segs)

            def on_pad(pad, x, y, layer):
                if layer not in pad.layers:
                    return False
                lx, ly = rot(x - pad.x, y - pad.y, -pad.angle)
                return abs(lx) <= pad.w / 2 + tol and abs(ly) <= pad.h / 2 + tol

            for i, (_, pad) in enumerate(items):
                for k, x, y, layer in ends:
                    if on_pad(pad, x, y, layer):
                        join(i, k)
                for j, v in enumerate(vias):
                    if on_pad(pad, v[0], v[1], "F") or on_pad(pad, v[0], v[1], "B"):
                        join(i, vb + j)
            for a in range(len(ends)):
                for b in range(a + 1, len(ends)):
                    if ends[a][3] == ends[b][3] and abs(ends[a][1] - ends[b][1]) < tol and abs(ends[a][2] - ends[b][2]) < tol:
                        join(ends[a][0], ends[b][0])
                for j, v in enumerate(vias):
                    if abs(ends[a][1] - v[0]) < tol and abs(ends[a][2] - v[1]) < tol:
                        join(ends[a][0], vb + j)
            # a track end landing part-way along another track of the same net and layer
            for a in range(len(ends)):
                for k, s in enumerate(segs):
                    if s[5] != ends[a][3]:
                        continue
                    if _dist_seg(ends[a][1], ends[a][2], s) < 0.01:
                        join(ends[a][0], base + k)
            pieces = {root(i) for i in range(len(items))}
            if len(pieces) > 1:
                out[net] = len(pieces)
        return out

    def overlaps(self, gap=0.0):
        """Pairs of parts whose courtyards overlap on the same side."""
        out = []
        boxes = [(p, p.courtyard()) for p in self.parts if p.kind != "m3"]
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                (a, ba), (b, bb) = boxes[i], boxes[j]
                if not ba or not bb:
                    continue
                same = a.side == b.side or a.kind in THROUGH or b.kind in THROUGH
                if not same:
                    continue
                if ba[0] < bb[2] - gap and bb[0] < ba[2] - gap and ba[1] < bb[3] - gap and bb[1] < ba[3] - gap:
                    out.append((a.ref, b.ref))
        return out


THROUGH = ("enc", "push6", "do35", "idc10", "idc8", "pga2350")


def _dist_seg(px, py, s):
    x1, y1, x2, y2 = s[:4]
    dx, dy = x2 - x1, y2 - y1
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / L))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


# ------------------------------------------------------------------ pictures

def render(board, path, scale=8, side="both"):
    """A picture of the board from the front: back tracks blue, front tracks red, pads gold,
    part outlines (courtyards) white for the front and cyan for the back, holes dark."""
    from PIL import Image, ImageDraw, ImageFont
    m = 6
    W, H = int((board.w + 2 * m) * scale), int((board.h + 2 * m) * scale)
    im = Image.new("RGB", (W, H), (18, 20, 24))
    d = ImageDraw.Draw(im, "RGBA")

    def P(x, y):
        return ((x + m) * scale, (y + m) * scale)

    d.rectangle([P(0, 0), P(board.w, board.h)], fill=(32, 78, 44), outline=(220, 220, 200))
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", max(9, int(scale * 1.3)))
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", max(8, int(scale * 0.9)))
    except Exception:
        font = small = ImageFont.load_default()
    for p in board.parts:
        cy = p.courtyard()
        if cy and p.kind != "m3":
            col = (230, 230, 230, 120) if p.side == "F" else (90, 220, 255, 110)
            d.rectangle([P(cy[0], cy[1]), P(cy[2], cy[3])], outline=col)
    layers = [("B", (70, 120, 255, 230)), ("F", (240, 70, 60, 230))]
    for L, col in layers:
        if side not in ("both", L):
            continue
        for x1, y1, x2, y2, w, layer, net in board.segments:
            if layer == L:
                d.line([P(x1, y1), P(x2, y2)], fill=col, width=max(1, int(w * scale)))
    for p, pad in board.all_pads():
        if pad.kind == "np_thru_hole":
            r = pad.w / 2
            d.ellipse([P(pad.x - r, pad.y - r), P(pad.x + r, pad.y + r)], fill=(10, 10, 12))
            continue
        col = (220, 180, 60, 255) if "F" in pad.layers else (200, 150, 40, 200)
        if pad.shape == "circle":
            r = pad.w / 2
            d.ellipse([P(pad.x - r, pad.y - r), P(pad.x + r, pad.y + r)], fill=col)
        elif pad.shape == "oval" and abs(pad.w - pad.h) > 1e-6:
            x1, y1, x2, y2, w = pad.axis()
            d.line([P(x1, y1), P(x2, y2)], fill=col, width=int(w * scale))
            for x, y in ((x1, y1), (x2, y2)):
                d.ellipse([P(x - w / 2, y - w / 2), P(x + w / 2, y + w / 2)], fill=col)
        else:
            d.polygon([P(x, y) for x, y in pad.corners()], fill=col)
        if pad.drill:
            r = min(pad.drill) / 2
            d.ellipse([P(pad.x - r, pad.y - r), P(pad.x + r, pad.y + r)], fill=(10, 10, 12))
    for x, y, net in board.vias:
        r = VIA / 2
        d.ellipse([P(x - r, y - r), P(x + r, y + r)], fill=(200, 200, 200))
        r = VIA_DRILL / 2
        d.ellipse([P(x - r, y - r), P(x + r, y + r)], fill=(10, 10, 12))
    for p in board.parts:
        if p.kind in ("m3",):
            continue
        cy = p.courtyard()
        x = (cy[0] + cy[2]) / 2 if cy else p.x
        y = cy[1] if cy else p.y
        d.text(P(x, y - 1.4), p.ref, fill=(255, 255, 255, 220) if p.side == "F" else (140, 230, 255, 220),
               font=small, anchor="mm")
    for s, x, y, layer, size in board.texts:
        d.text(P(x, y), s, fill=(255, 255, 255, 200) if layer.startswith("F") else (140, 230, 255, 200),
               font=font, anchor="mm")
    im.save(path)


# ------------------------------------------------------------------ a clearance check (KiCad's DRC is the real one)

def _seg_seg(a, b):
    (x1, y1, x2, y2), (x3, y3, x4, y4) = a, b

    def cross(ox, oy, ax, ay, bx, by):
        return (ax - ox) * (by - oy) - (ay - oy) * (bx - ox)
    d1, d2 = cross(x3, y3, x4, y4, x1, y1), cross(x3, y3, x4, y4, x2, y2)
    d3, d4 = cross(x1, y1, x2, y2, x3, y3), cross(x1, y1, x2, y2, x4, y4)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 and d2 and d3 and d4:
        return 0.0
    return min(_dist_seg(x1, y1, (x3, y3, x4, y4)), _dist_seg(x2, y2, (x3, y3, x4, y4)),
               _dist_seg(x3, y3, (x1, y1, x2, y2)), _dist_seg(x4, y4, (x1, y1, x2, y2)))


def _pad_dist(pad, seg):
    """Distance from a line (x1, y1, x2, y2) to the edge of a pad (0 if they touch)."""
    if pad.shape == "circle":
        return max(0.0, _dist_seg(pad.x, pad.y, seg) - pad.w / 2)
    if pad.shape == "oval" and abs(pad.w - pad.h) > 1e-6:
        x1, y1, x2, y2, w = pad.axis()
        return max(0.0, _seg_seg(seg, (x1, y1, x2, y2)) - w / 2)
    pts = pad.corners()
    # inside?
    lx, ly = rot(seg[0] - pad.x, seg[1] - pad.y, -pad.angle)
    if abs(lx) <= pad.w / 2 and abs(ly) <= pad.h / 2:
        return 0.0
    return min(_seg_seg(seg, (pts[i][0], pts[i][1], pts[(i + 1) % 4][0], pts[(i + 1) % 4][1])) for i in range(4))


def clearance_problems(board, clearance=CLEARANCE, edge=0.3, hole=0.25):
    out = []
    pads = list(board.all_pads())
    items = [((s[0], s[1], s[2], s[3]), s[4] / 2, s[5], s[6], "track") for s in board.segments]
    for x, y, net in board.vias:
        items.append(((x, y, x, y), VIA / 2, "FB", net, "via"))
    eps = 0.005
    for i, (g, hw, layers, net, kind) in enumerate(items):
        for x1, y1, x2, y2 in [g]:
            for x, y in ((x1, y1), (x2, y2)):
                if min(x, y, board.w - x, board.h - y) - hw < edge - eps:
                    out.append("%s %s near the board edge at (%.2f, %.2f)" % (kind, net, x, y))
        for p, pad in pads:
            if pad.kind == "np_thru_hole":
                d = _dist_seg(pad.x, pad.y, g) - hw - pad.w / 2
                if d < hole - eps:
                    out.append("%s %s %.3f mm from a hole in %s" % (kind, net, d, p.ref))
                continue
            if pad.net == net or not any(L in pad.layers for L in layers):
                continue
            d = _pad_dist(pad, g) - hw
            if d < clearance - eps:
                out.append("%s %s %.3f mm from %s pad %s (%s)" % (kind, net, d, p.ref, pad.num, pad.net))
        for g2, hw2, layers2, net2, kind2 in items[i + 1:]:
            if net2 == net or not any(L in layers2 for L in layers):
                continue
            d = _seg_seg(g, g2) - hw - hw2
            if d < clearance - eps:
                out.append("%s %s %.3f mm from %s %s at (%.1f, %.1f)" % (kind, net, d, kind2, net2, g[0], g[1]))
    return out
