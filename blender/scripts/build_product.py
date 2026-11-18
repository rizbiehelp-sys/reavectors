"""Build a real product mesh (bottle/jar/can/box/tube) and export GLB.

Headless:
  blender --background --python blender/scripts/build_product.py -- \
      --type bottle --out out/bottle.glb --label label.png --color "#B3122E"

Geometry is parametric; the label is the user's real artwork (never AI-generated).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def _hex(color, default=(0.8, 0.8, 0.85, 1.0)):
    if not color:
        return default
    c = color.strip().lstrip("#")
    if len(c) != 6:
        return default
    r, g, b = (int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return (r, g, b, 1.0)


def bottle_profile(body_r=0.045, height=0.22, neck_r=0.016, shoulder=0.25, taper=0.55):
    """(radius, z) points, bottom -> top."""
    z_body = height * (1 - shoulder)
    return [
        (body_r * 0.92, 0.0), (body_r, 0.01), (body_r, z_body * 0.9),
        (body_r, z_body), (body_r * taper, z_body + height * 0.06),
        (neck_r * 1.4, z_body + height * 0.10), (neck_r, z_body + height * 0.13),
        (neck_r, height), (neck_r * 1.15, height),
    ]


def jar_profile(r=0.055, height=0.10):
    return [(r * 0.95, 0.0), (r, 0.01), (r, height - 0.01), (r * 0.98, height)]


def can_profile(r=0.033, height=0.12):
    return [(r * 0.98, 0.0), (r, 0.005), (r, height - 0.005), (r * 0.98, height)]


def tube_profile(r=0.02, height=0.16):
    return [(r, 0.0), (r, height * 0.85), (r * 0.9, height), (r * 0.3, height + 0.005)]


def build(kind, params):
    kind = (kind or "bottle").lower()
    if kind == "bottle":
        prof = bottle_profile(
            body_r=float(params.get("body_radius", 0.045)),
            height=float(params.get("height", 0.22)),
            neck_r=float(params.get("neck_radius", 0.016)),
            shoulder=float(params.get("shoulder", 0.25)))
        obj = common.lathe("Bottle_Body", prof, segments=int(params.get("segments", 96)))
    elif kind == "jar":
        obj = common.lathe("Jar_Body", jar_profile(
            float(params.get("radius", 0.055)), float(params.get("height", 0.10))),
            segments=int(params.get("segments", 96)))
    elif kind == "can":
        obj = common.lathe("Can_Body", can_profile(
            float(params.get("radius", 0.033)), float(params.get("height", 0.12))),
            segments=int(params.get("segments", 96)))
    elif kind == "tube":
        obj = common.lathe("Tube_Body", tube_profile(
            float(params.get("radius", 0.02)), float(params.get("height", 0.16))),
            segments=int(params.get("segments", 96)))
    elif kind == "box":
        obj = common.box("Box_Body",
                         float(params.get("width", 0.1)),
                         float(params.get("depth", 0.05)),
                         float(params.get("height", 0.2)))
    else:
        raise SystemExit(f"unsupported type: {kind}")
    return obj


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", default="bottle")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--color", default="#B3122E")
    ap.add_argument("--material", default="plastic", choices=["plastic", "glass", "metal"])
    ap.add_argument("--params", default="{}")
    args = ap.parse_args(argv)
    params = json.loads(args.params or "{}")

    common.clear_scene()
    obj = build(args.type, params)

    if args.label and os.path.isfile(args.label):
        common.apply_label(obj, args.label)
    else:
        transmission = 0.85 if args.material == "glass" else 0.0
        metallic = 0.9 if args.material == "metal" else 0.0
        obj.data.materials.append(common.make_material(
            "body", color=_hex(args.color), metallic=metallic,
            roughness=0.35 if args.material != "glass" else 0.08,
            transmission=transmission))

    if args.type in ("bottle", "jar", "can", "tube") and not args.label:
        common.uv_cylindrical(obj)
    common.export_glb(args.out, objects=[obj])
    print(json.dumps({"ok": True, "type": args.type, "out": args.out}))


if __name__ == "__main__":
    main()