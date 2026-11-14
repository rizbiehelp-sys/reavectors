#!/usr/bin/env python3
"""
Reproducible single-GPU benchmark harness for ReaVector AI models.

Works identically on **Kaggle** (personal dev / benchmarking only) and on the
**AWS g4dn.xlarge worker** because both use the same adapters in
``reavectors.ai.worker_models``.

Kaggle terms: personal, non-commercial use only. Do NOT wire Kaggle notebooks,
tunnels, polling workers or endpoints to public ReaVector customer requests
without written authorisation from Kaggle. AWS is the public production env.

Each run writes a report containing: model name, weights/version, license,
inference time, peak VRAM, output resolution, mesh stats and quality notes.

Usage (on Kaggle or the worker):
    python bench/kaggle_benchmark.py --image examples/chair.png --models triposr,sf3d
    python bench/kaggle_benchmark.py --gpu 1 --models triposr        # second T4
    python bench/kaggle_benchmark.py --list                           # show the plan
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import platform
import sys
import time

# models the roadmap benchmarks on the dual-T4 Kaggle box (3D ones are live;
# the rest are recorded so reports stay comparable as adapters land).
ROADMAP = [
    ("sdxl", "image", "stabilityai/stable-diffusion-xl-base-1.0", "CreativeML Open RAIL++-M"),
    ("z-image", "image", "Tongyi-MAI/Z-Image", "Apache-2.0 (VERIFY)"),
    ("ltx-video", "video", "Lightricks/LTX-Video", "LTX-Video license (VERIFY)"),
    ("wan2.1", "video", "Wan-AI/Wan2.1-T2V-14B", "Apache-2.0"),
    ("triposr", "image->3d", "stabilityai/TripoSR", "MIT"),
    ("sf3d", "image->3d", "stabilityai/stable-fast-3d", "Stability AI Community License"),
]


def _torch():
    import torch  # imported lazily so this module imports without a GPU
    return torch


def _gpu_info():
    try:
        import torch
        if not torch.cuda.is_available():
            return {"gpu": "cpu", "cuda": None, "torch": torch.__version__}
        return {
            "gpu": torch.cuda.get_device_name(0),
            "cuda": torch.version.cuda,
            "torch": torch.__version__,
            "usable_vram_gb": round(torch.cuda.get_device_properties(0).total_memory / 1024 ** 3, 2),
            "compute_capability": ".".join(map(str, torch.cuda.get_device_capability(0))),
        }
    except Exception as exc:  # noqa: BLE001
        return {"gpu": "unavailable", "error": str(exc), "python": platform.python_version()}


def bench_adapter(name: str, image_path: str, params: dict | None = None,
                  cache_dir: str = "./models", out_dir: str = "./bench/out") -> dict:
    """Load one adapter, run it, and measure time + peak VRAM + mesh stats."""
    from reavectors.ai.worker_models import build_default_manager

    torch = _torch()
    mgr = build_default_manager(cache_dir=cache_dir)
    params = params or {}
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    t0 = time.perf_counter()
    out_path = mgr.run(name, image_path, params, out_dir)
    dt = time.perf_counter() - t0

    peak = 0.0
    if torch.cuda.is_available():
        peak = torch.cuda.max_memory_allocated() / 1024 ** 3

    stats = {}
    try:
        import trimesh
        mesh = trimesh.load(out_path)
        stats = {"vertices": int(len(mesh.vertices)), "faces": int(len(mesh.faces)),
                 "has_texture": bool(getattr(mesh.visual, "uv", None) is not None)}
    except Exception as exc:  # noqa: BLE001
        stats = {"mesh_error": str(exc)}

    version, license_ = next(((m, l) for n, kind, m, l in ROADMAP if n == name), ("?", "?"))
    return {
        "model": name,
        "kind": next((k for n, k, _, _ in ROADMAP if n == name), "unknown"),
        "version": version,
        "license": license_,
        "inference_s": round(dt, 3),
        "peak_vram_gb": round(peak, 2),
        "output": out_path,
        "output_resolution": f"{params.get('mc_resolution', 256)}^3",
        "mesh": stats,
        "quality_notes": "",
    }


def run(models: list[str], image: str, out_root: str) -> str:
    _torch()  # fail fast with a clear error if torch is missing
    info = _gpu_info()
    results = []
    for m in models:
        try:
            results.append(bench_adapter(m, image, out_dir=os.path.join(out_root, m)))
        except Exception as exc:  # noqa: BLE001
            results.append({"model": m, "error": f"{type(exc).__name__}: {exc}"})
    report = {
        "run_id": _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "hardware": info,
        "image": os.path.abspath(image),
        "env": {"CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES", "")},
        "results": results,
    }
    os.makedirs(out_root, exist_ok=True)
    path = os.path.join(out_root, f"benchmark-{report['run_id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    with open(os.path.join(out_root, f"benchmark-{report['run_id']}.md"), "w", encoding="utf-8") as f:
        f.write(_to_md(report))
    print(f"\nwrote {path}")
    return path


def _to_md(report: dict) -> str:
    h = report["hardware"]
    lines = [f"# Benchmark {report['run_id']}", "",
             f"- GPU: **{h.get('gpu')}** · torch {h.get('torch')} · CUDA {h.get('cuda')}",
             f"- Usable VRAM: {h.get('usable_vram_gb', '?')} GB · CC {h.get('compute_capability', '?')}",
             f"- Image: `{report['image']}`", "",
             "| model | kind | version | license | infer (s) | peak VRAM (GB) | output | notes |",
             "|---|---|---|---|---|---|---|---|"]
    for r in report["results"]:
        if r.get("error"):
            lines.append(f"| {r['model']} | - | - | - | - | - | FAILED | {r['error']} |")
        else:
            lines.append(f"| {r['model']} | {r['kind']} | {r['version']} | {r['license']} | "
                         f"{r['inference_s']} | {r['peak_vram_gb']} | {r['output_resolution']} | "
                         f"{r['quality_notes'] or ''} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="ReaVector model benchmark (Kaggle/AWS)")
    ap.add_argument("--image", default="examples/chair.png")
    ap.add_argument("--models", default="triposr", help="comma-separated adapter names")
    ap.add_argument("--out", default="./bench/results")
    ap.add_argument("--list", action="store_true", help="show the benchmark roadmap and exit")
    args = ap.parse_args(argv)
    if args.list:
        for name, kind, ver, lic in ROADMAP:
            live = "adapter-live" if name in ("triposr", "sf3d") else "planned"
            print(f"{name:12s} {kind:10s} {ver:42s} {lic:38s} [{live}]")
        return 0
    if not os.path.isfile(args.image):
        print(f"image not found: {args.image}", file=sys.stderr)
        return 2
    run([m.strip() for m in args.models.split(",") if m.strip()], args.image, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
