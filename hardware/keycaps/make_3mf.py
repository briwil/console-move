#!/usr/bin/env python3
"""Pack the keycaps into Bambu Studio project files (.3mf), one plate of 24 keys.

Each key is one object with two parts: the cap and its icon inlay.
Filament slots: 1 = cap colour (cream), 2 = icon colour (black), 3 = record cap (red).
Keys are flipped top-face-down so the stem prongs point up (no supports needed).
"""
import io, os, sys, uuid, zipfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_keycaps as k

PLATE_C = (128.0, 128.0)
PITCH_X, PITCH_Y = 22.0, 21.0
COLS = 6

def flipped(v):
    """Rotate 180 deg about X (top face down), then rest the part on z = 0."""
    out = v.copy()
    out[:, 1] *= -1
    out[:, 2] *= -1
    out[:, 2] += k.TOP
    return out

def mesh_xml(obj_id, v, f, name):
    buf = io.StringIO()
    buf.write(f' <object id="{obj_id}" p:UUID="{uuid.uuid4()}" type="model" name="{name}">\n  <mesh>\n   <vertices>\n')
    np.savetxt(buf, v, fmt='    <vertex x="%.4f" y="%.4f" z="%.4f"/>')
    buf.write('   </vertices>\n   <triangles>\n')
    np.savetxt(buf, f, fmt='    <triangle v1="%d" v2="%d" v3="%d"/>')
    buf.write('   </triangles>\n  </mesh>\n </object>\n')
    return buf.getvalue()

NS = ('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
      'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
      'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06"')

def build(path, slop):
    files = {}
    rels, resources, build_items, cfg_objects, cfg_instances = [], [], [], [], []
    next_id = 1
    for idx, (name, fn, ref) in enumerate(k.KEYS):
        mask = k.clean(fn())
        cap_v, cap_f = k.mesh(*k.build(mask, slop))
        inl_v, inl_f = k.mesh(*k.build(mask, 0, inlay=True))
        assert k.check(cap_v, cap_f)[0] == 0 and k.check(inl_v, inl_f)[0] == 0
        cap_v, inl_v = flipped(cap_v), flipped(inl_v)
        cap_id, inl_id, obj_id = next_id, next_id + 1, next_id + 2
        next_id += 3
        label = f"{idx + 1:02d}-{name}"
        part_file = f"/3D/Objects/object_{obj_id}.model"
        files[part_file[1:]] = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" {NS} requiredextensions="p">\n'
                                f' <metadata name="BambuStudio:3mfVersion">1</metadata>\n <resources>\n'
                                + mesh_xml(cap_id, cap_v, cap_f, label + " cap")
                                + mesh_xml(inl_id, inl_v, inl_f, label + " icon")
                                + ' </resources>\n <build/>\n</model>\n')
        rels.append(f' <Relationship Target="{part_file}" Id="rel-{obj_id}" '
                    f'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>')
        ident = "1 0 0 0 1 0 0 0 1 0 0 0"
        resources.append(f'  <object id="{obj_id}" p:UUID="{uuid.uuid4()}" type="model">\n   <components>\n'
                         f'    <component p:path="{part_file}" objectid="{cap_id}" p:UUID="{uuid.uuid4()}" transform="{ident}"/>\n'
                         f'    <component p:path="{part_file}" objectid="{inl_id}" p:UUID="{uuid.uuid4()}" transform="{ident}"/>\n'
                         f'   </components>\n  </object>')
        r, c = divmod(idx, COLS)
        x = PLATE_C[0] + (c - (COLS - 1) / 2) * PITCH_X
        y = PLATE_C[1] + ((len(k.KEYS) // COLS - 1) / 2 - r) * PITCH_Y
        build_items.append(f'  <item objectid="{obj_id}" p:UUID="{uuid.uuid4()}" '
                           f'transform="1 0 0 0 1 0 0 0 1 {x:.3f} {y:.3f} 0" printable="1"/>')
        cap_slot = 3 if name == "record" else 1
        m16 = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"
        cfg_objects.append(
            f'  <object id="{obj_id}">\n'
            f'    <metadata key="name" value="{label}"/>\n'
            f'    <metadata key="extruder" value="{cap_slot}"/>\n'
            f'    <part id="{cap_id}" subtype="normal_part">\n'
            f'      <metadata key="name" value="{label} cap"/>\n'
            f'      <metadata key="matrix" value="{m16}"/>\n'
            f'      <metadata key="extruder" value="{cap_slot}"/>\n'
            f'    </part>\n'
            f'    <part id="{inl_id}" subtype="normal_part">\n'
            f'      <metadata key="name" value="{label} icon"/>\n'
            f'      <metadata key="matrix" value="{m16}"/>\n'
            f'      <metadata key="extruder" value="2"/>\n'
            f'    </part>\n'
            f'  </object>')
        cfg_instances.append(
            f'    <model_instance>\n      <metadata key="object_id" value="{obj_id}"/>\n'
            f'      <metadata key="instance_id" value="0"/>\n'
            f'      <metadata key="identify_id" value="{obj_id * 10}"/>\n    </model_instance>')
        print(f"  {label} ok")

    files["3D/3dmodel.model"] = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" {NS} requiredextensions="p">\n'
        ' <metadata name="Application">BambuStudio-01.10.02.76</metadata>\n'
        ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
        ' <metadata name="Title">Console keycaps (Kailh Choc V1)</metadata>\n'
        ' <resources>\n' + "\n".join(resources) + '\n </resources>\n'
        f' <build p:UUID="{uuid.uuid4()}">\n' + "\n".join(build_items) + '\n </build>\n</model>\n')
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

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    for variant, slop in (("nominal", 0.0), ("loose", 0.1)):
        print(variant)
        build(os.path.join(out, f"console-keycaps-{variant}.3mf"), slop)
