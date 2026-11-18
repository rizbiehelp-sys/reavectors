"""Export selected/all meshes to GLB and validate the file header.

Blender:  blender --background --python export_glb.py -- --out out/model.glb
Or import: from export_glb import export
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def export(path, objects=None):
    common.export_glb(path, objects)
    with open(path, "rb") as f:
        magic = f.read(4)
    return {"out": path, "bytes": os.path.getsize(path),
            "valid_glb": magic == b"glTF"}


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = ""
    for i, a in enumerate(argv):
        if a == "--out" and i + 1 < len(argv):
            out = argv[i + 1]
    if not out:
        raise SystemExit("--out <file.glb> required")
    import bpy
    selected = [o for o in bpy.context.selected_objects if o.type == "MESH"]
    result = export(out, selected or None)
    print(json.dumps(result))