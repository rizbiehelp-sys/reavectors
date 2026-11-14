#!/usr/bin/env python3
"""
Run an image->3D model adapter on a GPU (Kaggle) and write a GLB.

This is the SAME adapter code the AWS worker used, so it runs unchanged wherever
torch + a model repo are installed. Intended for the owner's personal Kaggle GPU
(see kaggle/README.md); not for public customer traffic without Kaggle's written
authorisation.

Usage (on Kaggle, after installing a model repo):
    python scripts/ai3d_run.py --image /kaggle/input/prod.png --model triposr --out /kaggle/working/prod.glb
    python scripts/ai3d_run.py --image p.png --model sf3d --params '{"mc_resolution":384}'

Outputs a JSON line with the model, output path, size and seconds.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="image -> 3D (GLB) on a GPU")
    ap.add_argument("--image", required=True)
    ap.add_argument("--model", default="triposr", help="triposr | sf3d | hunyuan3d")
    ap.add_argument("--out", default="", help="output .glb path")
    ap.add_argument("--params", default="{}", help="JSON params for the adapter")
    ap.add_argument("--cache", default=os.environ.get("MODELS_DIR", "./models"))
    args = ap.parse_args(argv)

    if not os.path.isfile(args.image):
        print(f"image not found: {args.image}", file=sys.stderr)
        return 2
    try:
        params = json.loads(args.params or "{}")
    except json.JSONDecodeError as exc:
        print(f"bad --params JSON: {exc}", file=sys.stderr)
        return 2

    from reavectors.ai.worker_models import build_default_manager

    out_dir = os.path.dirname(args.out) or "."
    os.makedirs(out_dir, exist_ok=True)

    mgr = build_default_manager(cache_dir=args.cache)
    t0 = time.perf_counter()
    path = mgr.run(args.model, args.image, params, out_dir)
    dt = time.perf_counter() - t0

    if args.out and os.path.abspath(path) != os.path.abspath(args.out):
        shutil.move(path, args.out)
        path = args.out

    size = os.path.getsize(path) if os.path.exists(path) else 0
    print(json.dumps({"model": args.model, "out": path, "bytes": size,
                      "seconds": round(dt, 2)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())