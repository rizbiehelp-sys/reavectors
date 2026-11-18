"""Apply the user's real label artwork to a mesh (cylindrical UVs).

Blender:  blender --background --python apply_label.py -- --label label.png
Or import: from apply_label import apply
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def apply(obj, image_path):
    common.apply_label(obj, image_path)
    return obj


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    label = ""
    for i, a in enumerate(argv):
        if a == "--label" and i + 1 < len(argv):
            label = argv[i + 1]
    import bpy  # noqa: F401
    if not label or not os.path.isfile(label):
        raise SystemExit("--label <image> required")
    obj = bpy.context.active_object
    if obj is None:
        meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
        if not meshes:
            raise SystemExit("no mesh in scene")
        obj = meshes[0]
    apply(obj, label)
    print(json.dumps({"ok": True, "object": obj.name, "label": label}))