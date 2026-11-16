#!/usr/bin/env python3
"""
Run ONE model job pinned to ONE physical GPU (true per-GPU isolation).

CUDA_VISIBLE_DEVICES is set *before* torch is imported, so inside the process the
pinned card is always ``cuda:0`` and the other T4 is untouched. This is how you
use both Kaggle T4s in parallel (two processes, one per GPU).

Usage:
    python scripts/gpu_job.py --gpu 1 --model triposr --image in.png --out job.glb
    python scripts/gpu_job.py --gpu 0 --model sdxl-base-1.0 --image ref.png   # planned -> errors
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="pinned-GPU model job")
    ap.add_argument("--gpu", required=True, help="physical GPU index (0 or 1)")
    ap.add_argument("--model", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", default="", help="output path")
    ap.add_argument("--params", default="{}")
    ap.add_argument("--work", default="./runs", help="workspace root")
    args = ap.parse_args(argv)

    # MUST be set before any torch import happens (manager loads torch lazily).
    os.environ["CUDA_VISIBLE_DEVICES"] = str(args.gpu)
    sys.path.insert(0, ROOT)

    from reavectors.ai import registry
    from reavectors.ai.manifest import JobWorkspace, run_manifest
    from reavectors.ai.worker_models import build_default_manager

    spec = registry.get(args.model)
    if not spec.adapter or spec.status != "adapter_live":
        print(f"{spec.id} has no live adapter (planned)", file=sys.stderr)
        return 3
    if not os.path.isfile(args.image):
        print(f"image not found: {args.image}", file=sys.stderr)
        return 2
    try:
        params = json.loads(args.params or "{}")
    except json.JSONDecodeError as exc:
        print(f"bad --params: {exc}", file=sys.stderr)
        return 2

    ws = JobWorkspace(args.work, spec.id)
    t0 = time.perf_counter()
    try:
        path = build_default_manager().run(spec.adapter, args.image, params, ws.dir)
        ok, err = True, None
    except Exception as exc:  # noqa: BLE001
        path, ok, err = None, False, f"{type(exc).__name__}: {exc}"
    dt = round(time.perf_counter() - t0, 2)

    if args.out and path and os.path.abspath(path) != os.path.abspath(args.out):
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        shutil.move(path, args.out)
        path = args.out

    manifest = run_manifest(spec.id, inputs={"image": os.path.basename(args.image)},
                            params=params, outputs=[path] if path else [],
                            timings={"seconds": dt}, gpu=args.gpu, ok=ok, error=err)
    ws.write_manifest(manifest)
    print(json.dumps({"ok": ok, "model": spec.id, "gpu": args.gpu, "out": path,
                      "seconds": dt, "manifest": ws.path("manifest.json"), "error": err},
                     indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())