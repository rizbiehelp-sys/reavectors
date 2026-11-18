"""Animate a product and render PNG frames (for FFmpeg).

  blender --background --python blender/scripts/animate_product.py -- \
      --type bottle --preset turntable --frames-dir out/frames --resolution 720

Uses presets.py. Camera framing is computed from the object bounds.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import presets  # noqa: E402
from build_product import build, _hex  # noqa: E402


def _setup_camera(obj, push):
    import bpy
    from mathutils import Vector

    bpy.context.view_layer.update()
    coords = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    zs = [c.z for c in coords]
    lo, hi = min(zs), max(zs)
    height = max(1e-3, hi - lo)
    center = Vector((0, 0, (lo + hi) / 2))
    dist = height * (2.2 + push)

    cam_data = bpy.data.cameras.new("Camera")
    cam = bpy.data.objects.new("Camera", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = (0, -dist, center.z)
    direction = center - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam

    light_data = bpy.data.lights.new("Key", type="AREA")
    light_data.energy = 220
    light_data.size = 0.8
    light = bpy.data.objects.new("Key", light_data)
    light.location = (0.6, -0.8, center.z + height)
    light.rotation_euler = (math.radians(30), 0, math.radians(20))
    bpy.context.collection.objects.link(light)
    return cam, center


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", default="bottle")
    ap.add_argument("--preset", default="turntable")
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--resolution", type=int, default=720)
    ap.add_argument("--label", default="")
    ap.add_argument("--color", default="#B3122E")
    ap.add_argument("--material", default="plastic", choices=["plastic", "glass", "metal"])
    ap.add_argument("--params", default="{}")
    args = ap.parse_args(argv)
    p = presets.get(args.preset)

    common.clear_scene()
    obj = build(args.type, json.loads(args.params or "{}"))
    if args.label and os.path.isfile(args.label):
        common.apply_label(obj, args.label)
    else:
        obj.data.materials.append(common.make_material(
            "body", color=_hex(args.color),
            metallic=0.9 if args.material == "metal" else 0.0,
            roughness=0.35, transmission=0.85 if args.material == "glass" else 0.0))

    _setup_camera(obj, p["push"])

    import bpy
    scn = bpy.context.scene
    scn.render.resolution_x = args.resolution
    scn.render.resolution_y = args.resolution
    scn.render.image_settings.file_format = "PNG"
    scn.frame_start = 1
    scn.frame_end = p["frames"]
    scn.render.fps = p["fps"]
    os.makedirs(args.frames_dir, exist_ok=True)
    scn.render.filepath = os.path.join(args.frames_dir, "frame_")

    # turntable / reveal: rotate the object over the timeline
    obj.rotation_mode = "XYZ"
    obj.rotation_euler = (0, 0, 0)
    obj.keyframe_insert("rotation_euler", frame=1)
    obj.rotation_euler = (0, 0, math.radians(p["rotate"]))
    obj.keyframe_insert("rotation_euler", frame=p["frames"])
    for fc in obj.animation_data.action.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = "BEZIER"

    try:
        scn.render.engine = "BLENDER_EEVEE_NEXT"
    except Exception:  # noqa: BLE001
        try:
            scn.render.engine = "BLENDER_EEVEE"
        except Exception:  # noqa: BLE001
            pass

    bpy.ops.render.render(animation=True)
    print(json.dumps({"ok": True, "frames": p["frames"], "fps": p["fps"],
                      "dir": args.frames_dir, "preset": args.preset}))


if __name__ == "__main__":
    main()