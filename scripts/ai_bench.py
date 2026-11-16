#!/usr/bin/env python3
"""
Benchmark the live adapters on ONE GPU and write a reproducible report.

Run once per physical GPU (CUDA_VISIBLE_DEVICES is set from --gpu before torch):
    python scripts/ai_bench.py --gpu 0 --models sdxl-base-1.0,z-image-turbo   # planned -> skipped
    python scripts/ai_bench.py --gpu 1 --models triposr,sf3d
    python scripts/ai_bench.py --list          # registry, no GPU needed
    python scripts/ai_bench.py --dry-run       # plan, no GPU needed

Report fields per model: ok, inference seconds, peak VRAM, output bytes, error.
Writes bench/results/bench-<gpu>-<utc>.json + .md.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _write_report(report: dict, out_root: str) -> str:
    os.makedirs(out_root, exist_ok=True)
    stamp = report["run_id"]
    path = os.path.join(out_root, f"bench-gpu{report['gpu']}-{stamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    md = os.path.join(out_root, f"bench-gpu{report['gpu']}-{stamp}.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write(f"# Benchmark GPU {report['gpu']} — {stamp}\n\n")
        f.write(f"torch {report['env'].get('torch')} · CUDA {report['env'].get('cuda')} · "
                f"{report['env'].get('gpu')}\n\n")
        f.write("| model | ok | seconds | peak VRAM (GB) | bytes | error |\n|---|---|---|---|---|---|\n")
        for r in report["results"]:
            f.write(f"| {r['model']} | {r['ok']} | {r.get('seconds','')} | "
                    f"{r.get('peak_vram_gb','')} | {r.get('bytes','')} | {r.get('error') or ''} |\n")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="per-GPU benchmark")
    ap.add_argument("--gpu", default="0")
    ap.add_argument("--models", default="", help="comma list; default = all live adapters")
    ap.add_argument("--image", default="")
    ap.add_argument("--out", default="./bench/results")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    sys.path.insert(0, ROOT)
    from reavectors.ai import registry

    if args.list:
        for m in registry.REGISTRY:
            print(f"{m.id:22s} {m.task:12s} {m.status:12s} VRAM {m.vram_gb:>5}GB  {m.license}")
        return 0

    live = [m for m in registry.adapters()]
    wanted = [x.strip() for x in args.models.split(",") if x.strip()] or [m.id for m in live]

    if args.dry_run:
        print(f"GPU {args.gpu} plan:")
        for mid in wanted:
            m = registry.get(mid)
            usable = 14.56
            fits = "fits" if m.vram_gb <= usable else "EXCEEDS T4"
            print(f"  {m.id:22s} {m.status:12s} {m.vram_gb}GB ({fits})")
        return 0

    # pinned before torch
    os.environ["CUDA_VISIBLE_DEVICES"] = str(args.gpu)
    from reavectors.ai.worker_models import build_default_manager

    env = {"python": sys.version.split()[0]}
    try:
        import torch
        env["torch"] = torch.__version__
        env["cuda"] = torch.version.cuda
        env["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
    except Exception as exc:  # noqa: BLE001
        env["torch_error"] = str(exc)

    results = []
    mgr = build_default_manager()
    for mid in wanted:
        spec = registry.get(mid)
        rec = {"model": mid, "status": spec.status, "ok": False}
        if spec.status != "adapter_live" or not spec.adapter:
            rec["error"] = "planned (no adapter)"
            results.append(rec)
            continue
        if spec.vram_gb > 14.56:
            rec["error"] = f"needs {spec.vram_gb}GB > T4 14.56GB"
            results.append(rec)
            continue
        if not args.image or not os.path.isfile(args.image):
            rec["error"] = "no --image"
            results.append(rec)
            continue
        out_dir = os.path.join(args.out, "out", mid)
        os.makedirs(out_dir, exist_ok=True)
        try:
            if "torch" in env:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.reset_peak_memory_stats()
            t0 = time.perf_counter()
            path = mgr.run(spec.adapter, args.image, {}, out_dir)
            rec["seconds"] = round(time.perf_counter() - t0, 2)
            rec["ok"] = True
            rec["bytes"] = os.path.getsize(path) if os.path.exists(path) else 0
            if "torch" in env:
                import torch
                if torch.cuda.is_available():
                    rec["peak_vram_gb"] = round(torch.cuda.max_memory_allocated() / 1024 ** 3, 2)
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {exc}"
        results.append(rec)

    report = {"run_id": _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
              "gpu": args.gpu, "env": env, "results": results}
    path = _write_report(report, args.out)
    print(json.dumps({"report": path, "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())