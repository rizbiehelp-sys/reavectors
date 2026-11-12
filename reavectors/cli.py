"""
reavectors CLI
==============

    python -m reavectors INPUT.png -o OUTPUT.svg
    python -m reavectors INPUT.png --format ai,pdf,eps,svg --outdir out
    python -m reavectors INPUT.png --format svg --colors 6 --turdsize 4
"""

from __future__ import annotations

import argparse
import os
import sys

from .vectorize import vectorize
from .export import render_pdf, render_eps

FORMATS = ("svg", "ai", "pdf", "eps")


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="reavectors",
        description="Convert a transparent PNG into clean vector geometry.",
    )
    p.add_argument("input", help="input image (PNG with alpha recommended)")
    p.add_argument("-o", "--output", help="output file (single format)")
    p.add_argument("--outdir", help="output directory when using --format with several types")
    p.add_argument("--format", default="svg",
                   help="comma list of: svg,ai,pdf,eps (default: svg)")
    p.add_argument("--engine", default="auto", choices=("auto", "vtracer", "potrace"),
                   help="tracing engine (default: auto = vtracer, else potrace)")
    p.add_argument("--style", default="logo", choices=("logo", "photo", "line"),
                   help="vtracer preset: logo (flat), photo (gradients), line (two-tone)")
    p.add_argument("--detail", type=int, default=None,
                   help="vtracer layer_difference override (smaller = more detail)")
    p.add_argument("--colors", type=int, default=8,
                   help="potrace palette size 1..256 (default: 8)")
    p.add_argument("--alpha-threshold", type=int, default=128,
                   help="alpha cutoff 0..255 (default: 128)")
    p.add_argument("--turdsize", type=int, default=2,
                   help="drop specks smaller than N pixels (default: 2)")
    p.add_argument("--alphamax", type=float, default=1.0,
                   help="corner threshold 0..1.334 (default: 1.0)")
    p.add_argument("--opttolerance", type=float, default=0.2,
                   help="curve-optimisation tolerance (default: 0.2)")
    p.add_argument("--max-size", type=int, default=1600,
                   help="downscale longest edge to this before tracing (0=off)")
    p.add_argument("--refine", type=float, default=0.0,
                   help="spend up to N seconds refining for higher detail (0=off, e.g. 10)")
    p.add_argument("-q", "--quiet", action="store_true", help="suppress the summary")
    return p


def _stem(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def main(argv=None) -> int:
    args = build_argparser().parse_args(argv)
    if not os.path.exists(args.input):
        print(f"error: input not found: {args.input}", file=sys.stderr)
        return 2

    stats = None
    if args.refine and args.refine > 0:
        from .refine import auto_refine
        progress = None
        if not args.quiet:
            def progress(i, m, engine):
                print(f"  refine pass {i}: match {m}% ({engine})")
        result, stats = auto_refine(
            args.input, budget=args.refine, style=args.style,
            max_size=args.max_size, on_progress=progress,
        )
    else:
        result = vectorize(
            args.input,
            engine=args.engine,
            style=args.style,
            detail=args.detail,
            colors=args.colors,
            alpha_threshold=args.alpha_threshold,
            turdsize=args.turdsize,
            alphamax=args.alphamax,
            opttolerance=args.opttolerance,
            max_size=args.max_size,
        )
    result.source = os.path.basename(args.input)

    formats = [f.strip().lower() for f in args.format.split(",") if f.strip()]
    bad = [f for f in formats if f not in FORMATS]
    if bad:
        print(f"error: unknown format(s): {', '.join(bad)}", file=sys.stderr)
        return 2

    if args.output and len(formats) == 1:
        targets = {formats[0]: args.output}
    else:
        outdir = args.outdir or os.path.dirname(os.path.abspath(args.input)) or "."
        os.makedirs(outdir, exist_ok=True)
        stem = _stem(args.input)
        targets = {f: os.path.join(outdir, f"{stem}.{f}") for f in formats}

    written = []
    for fmt, path in targets.items():
        if fmt == "svg":
            with open(path, "w", encoding="utf-8") as f:
                f.write(result.to_svg())
        elif fmt in ("ai", "pdf"):
            with open(path, "wb") as f:
                f.write(render_pdf(result))
        elif fmt == "eps":
            with open(path, "wb") as f:
                f.write(render_eps(result))
        written.append(path)

    if not args.quiet:
        print(f"vectorised {args.input}")
        print(f"  engine   : {result.engine or args.engine}")
        print(f"  canvas   : {result.width} x {result.height}")
        print(f"  colours  : {result.color_count}")
        if stats is not None:
            print(f"  refine   : {stats.iterations} passes, match {stats.best_match}%, "
                  f"{stats.seconds:.1f}s")
        print(f"  figures  : {result.figure_count}   subpaths: {result.path_count}")
        for path in written:
            print(f"  wrote    : {path}  ({os.path.getsize(path)} bytes)")

    return 0 if result.layers else 1


if __name__ == "__main__":
    raise SystemExit(main())
